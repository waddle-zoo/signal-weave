from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import Decision, MonitorCard, MonitorPlan, Observation, Outcome


class DecisionJudger(Protocol):
    name: str

    async def compile_plan(self, state: dict[str, Any], card: MonitorCard) -> dict[str, Any]: ...

    async def judge(
        self,
        state: dict[str, Any],
        card: MonitorCard,
        plan: MonitorPlan,
        observations: list[Observation],
    ) -> Decision: ...


@dataclass
class JudgerMetrics:
    """Small, non-sensitive counters used by the local benchmark harness."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def record(self, response: Any) -> None:
        self.requests += 1
        usage = getattr(response, "usage", None)
        self.record_tokens(
            getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)
        )

    def record_tokens(self, input_tokens: Any = None, output_tokens: Any = None) -> None:
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)


class JevJudger:
    name = "jev-latest"

    def __init__(self, api_key: str | None = None) -> None:
        from typesafe_sdk import AsyncTypeSafeClient

        self._client_type = AsyncTypeSafeClient
        self._api_key = api_key
        self.metrics = JudgerMetrics()

    async def compile_plan(self, state: dict[str, Any], card: MonitorCard) -> dict[str, Any]:
        from typesafe_sdk import Choice, Noul

        available_operations = state["available_operations"]
        questions = {
            f"use_{operation['key']}": Noul(
                instructions=(
                    f"Does the owner's monitoring intent require the `{operation['key']}` "
                    "analysis capability for this dashboard?"
                ),
                criteria={
                    "true": operation["description"],
                    "false": "This capability is not needed to answer the owner's monitoring intent.",
                },
            )
            for operation in available_operations
        }
        windows = card.comparison_windows or ["previous_period"]
        questions["baseline"] = Choice(
            instructions="Which comparison window best matches the owner's monitoring intent?",
            criteria={window: None for window in windows},
        )

        async with self._client_type(api_key=self._api_key) as client:
            response = await client.system_one(
                state=state,
                questions=questions,
            )
        self.metrics.record(response)
        operations = [
            operation["key"]
            for operation in available_operations
            if response.nouls[f"use_{operation['key']}"].noul >= 0.6
        ]
        return {"operations": operations, "baseline": response.choices["baseline"].choice}

    async def judge(
        self,
        state: dict[str, Any],
        card: MonitorCard,
        plan: MonitorPlan,
        observations: list[Observation],
    ) -> Decision:
        from typesafe_sdk import Choice, Score

        default_guidance = {
            Outcome.IGNORE.value: "Do not send a notification; the evidence is not actionable.",
            Outcome.INVESTIGATE.value: "Route for human or downstream investigation before action.",
            Outcome.NOTIFY.value: "Send a low-risk notification to one approved recipient group.",
            Outcome.ESCALATE.value: "Send an urgent escalation to one approved recipient group.",
            Outcome.INSUFFICIENT_DATA.value: "Do not interpret the dashboard because required evidence is missing or stale.",
        }
        criteria = {
            outcome.value: card.outcome_guidance.get(outcome.value, default_guidance[outcome.value])
            for outcome in card.allowed_outcomes
        }
        recipient_criteria = {"no_recipient": "No notification should be sent."} | {
            recipient.key: recipient.label for recipient in card.recipients
        }
        async with self._client_type(api_key=self._api_key) as client:
            response = await client.system_one(
                state=state,
                questions={
                    "outcome": Choice(
                        instructions=(
                            "Given the dashboard monitoring intent and computed evidence, "
                            "what should the monitoring workflow do next? Follow any "
                            "owner-provided outcome guidance in `monitor_card.outcome_guidance`."
                        ),
                        criteria=criteria,
                    ),
                    "materiality": Score(
                        instructions=(
                            "How materially does the evidence violate the dashboard owner's "
                            "monitoring intent? Use `monitor_card.materiality_definition` "
                            "when it is provided."
                        ),
                        criteria=["normal", "notable", "material", "critical"],
                    ),
                    "recipient": Choice(
                        instructions="Which approved recipient group should receive this decision, if any? Choose no_recipient when no notification is warranted.",
                        criteria=recipient_criteria,
                    ),
                },
            )
        self.metrics.record(response)
        try:
            outcome = Outcome(response.choices["outcome"].choice)
        except ValueError:
            outcome = Outcome.INVESTIGATE
        if outcome not in card.allowed_outcomes:
            outcome = Outcome.INVESTIGATE
        recipient = response.choices["recipient"].choice
        score = response.scores["materiality"]
        return Decision(
            outcome=outcome,
            recipient_key=None if recipient == "no_recipient" else recipient,
            rationale=f"TypeSafe classified the monitoring state as {outcome.value}; materiality={score.score:.2f}.",
            confidence=response.choices["outcome"].confidence,
            probabilities=response.choices["outcome"].probabilities,
            evidence=state["evidence"],
            observations=observations,
            monitor_id=card.id,
            dashboard_id=card.dashboard_id,
            evaluator=self.name,
        )


def load_api_key(path: str | None = None) -> str | None:
    path = path or os.getenv("TYPESAFE_API_KEY_FILE")
    if not path:
        return os.getenv("TYPESAFE_API_KEY")
    key_path = Path(path)
    if not key_path.exists():
        raise FileNotFoundError(f"TypeSafe API key file does not exist: {key_path}")
    return key_path.read_text().strip()

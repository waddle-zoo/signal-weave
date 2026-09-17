from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import Decision, MonitorPlan, MonitorWorkflow, Observation, Outcome


class DecisionJudger(Protocol):
    name: str

    async def compile_plan(
        self, state: dict[str, Any], workflow: MonitorWorkflow
    ) -> dict[str, Any]: ...

    async def judge(
        self,
        state: dict[str, Any],
        workflow: MonitorWorkflow,
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

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        from typesafe_sdk import AsyncTypeSafeClient

        timeout_seconds = timeout
        if timeout_seconds is None:
            try:
                timeout_seconds = float(os.getenv("TYPESAFE_TIMEOUT_SECONDS", "30"))
            except ValueError as error:
                raise ValueError("TYPESAFE_TIMEOUT_SECONDS must be a positive number") from error
        if timeout_seconds <= 0:
            raise ValueError("TYPESAFE_TIMEOUT_SECONDS must be a positive number")
        self._client_type = AsyncTypeSafeClient
        self._api_key = api_key
        self._timeout = timeout_seconds
        self.metrics = JudgerMetrics()

    async def compile_plan(
        self, state: dict[str, Any], workflow: MonitorWorkflow
    ) -> dict[str, Any]:
        from typesafe_sdk import Choice, Noul

        available_operations = state["available_operations"]
        questions = {
            f"use_{operation['key']}": Noul(
                instructions=(
                    f"Does the owner's workflow intent require the `{operation['key']}` "
                    "analysis capability for the selected sources?"
                ),
                criteria={
                    "true": operation["description"],
                    "false": "This capability is not needed to answer the owner's monitoring intent.",
                },
            )
            for operation in available_operations
        }
        windows = workflow.comparison_windows or ["previous_period"]
        questions["baseline"] = Choice(
            instructions="Which comparison window best matches the owner's monitoring intent?",
            criteria={window: None for window in windows},
        )

        async with self._client_type(api_key=self._api_key, timeout=self._timeout) as client:
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
        workflow: MonitorWorkflow,
        plan: MonitorPlan,
        observations: list[Observation],
    ) -> Decision:
        from typesafe_sdk import Choice, Noul

        default_guidance = {
            Outcome.IGNORE.value: "Do not send a notification; the evidence is not actionable.",
            Outcome.INVESTIGATE.value: "Route for human or downstream investigation before action.",
            Outcome.NOTIFY.value: "Send a low-risk notification to one approved recipient group.",
            Outcome.ESCALATE.value: "Send an urgent escalation to one approved recipient group.",
            Outcome.INSUFFICIENT_DATA.value: "Do not interpret the workflow because required source evidence is missing or stale.",
        }
        action_outcomes = {
            Outcome.IGNORE,
            Outcome.NOTIFY,
            Outcome.ESCALATE,
        }
        action_checks = [
            outcome for outcome in workflow.allowed_outcomes if outcome in action_outcomes
        ]
        questions = {
            f"matches_{outcome.value}": Noul(
                instructions=(
                    f"Does the current workflow evidence satisfy the owner-defined condition "
                    f"for the `{outcome.value}` outcome? Compare `monitor_workflow.intent`, "
                    "`monitor_workflow.materiality_definition`, "
                    "`monitor_workflow.outcome_guidance`, `sources`, and the "
                    "normalized `observations` and `evidence`."
                ),
                criteria={
                    "true": workflow.outcome_guidance.get(
                        outcome.value, default_guidance[outcome.value]
                    ),
                    "false": "The evidence does not satisfy this outcome condition.",
                },
            )
            for outcome in action_checks
        }
        recipient_criteria = {"no_recipient": "No notification should be sent."} | {
            recipient.key: recipient.label for recipient in workflow.recipients
        }
        questions["recipient"] = Choice(
            instructions="Which approved recipient group should receive an automatic action, if one is supported? Choose no_recipient when no automatic action is supported.",
            criteria=recipient_criteria,
        )
        async with self._client_type(api_key=self._api_key, timeout=self._timeout) as client:
            response = await client.system_one(state=state, questions=questions)
        self.metrics.record(response)
        matches = {
            outcome: response.nouls[f"matches_{outcome.value}"].noul for outcome in action_checks
        }
        selected_outcome, selected_probability = (
            max(matches.items(), key=lambda item: item[1])
            if matches
            else (Outcome.INVESTIGATE, 0.0)
        )
        if selected_probability >= workflow.action_confidence_threshold:
            outcome = selected_outcome
            confidence = selected_probability
        else:
            outcome = Outcome.INVESTIGATE
            confidence = max(matches.values(), default=0.0)
        recipient = response.choices["recipient"].choice
        return Decision(
            outcome=outcome,
            recipient_key=None if recipient == "no_recipient" else recipient,
            rationale=(
                f"TypeSafe evaluated owner-defined action conditions; selected={outcome.value}, "
                f"support={confidence:.2f}."
            ),
            confidence=confidence,
            probabilities={outcome.value: probability for outcome, probability in matches.items()},
            evidence=state["evidence"],
            observations=observations,
            workflow_id=workflow.id,
            source_keys=[
                source["source_key"]
                for source in state.get("sources", [])
                if "source_key" in source
            ]
            or [source.key for source in workflow.sources],
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

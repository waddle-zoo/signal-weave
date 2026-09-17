from __future__ import annotations

import os
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


class HeuristicJudger:
    name = "heuristic"

    async def compile_plan(self, state: dict[str, Any], card: MonitorCard) -> dict[str, Any]:
        intent = card.intent.lower()
        operations = ["percent_change", "baseline_comparison", "freshness_check"]
        if "season" in intent:
            operations.append("seasonality_check")
        if any(word in intent for word in ("segment", "mobile", "enterprise", "regional")):
            operations.append("dimension_contribution")
        if any(word in intent for word in ("related", "together", "compare", "inspect")):
            operations.append("cross_chart_comparison")
        return {"operations": list(dict.fromkeys(operations))}

    async def judge(
        self,
        state: dict[str, Any],
        card: MonitorCard,
        plan: MonitorPlan,
        observations: list[Observation],
    ) -> Decision:
        stale = [
            observation
            for observation in observations
            if observation.freshness and "stale" in observation.freshness.lower()
        ]
        candidates = [
            observation
            for observation in observations
            if observation.change_pct is not None
            and abs(observation.change_pct) >= card.materiality_threshold_pct
        ]
        if stale:
            outcome = (
                Outcome.ESCALATE
                if Outcome.ESCALATE in card.allowed_outcomes
                else Outcome.INVESTIGATE
            )
            rationale, confidence = (
                "A monitored input is stale, so the dashboard cannot be interpreted as current.",
                0.99,
            )
        elif not candidates:
            outcome, rationale, confidence = (
                Outcome.IGNORE,
                "No monitored observation crossed the owner-defined materiality threshold.",
                0.98,
            )
        elif any("error" in observation.metric for observation in candidates):
            outcome, rationale, confidence = (
                Outcome.NOTIFY,
                "A material movement is accompanied by a related error signal.",
                0.94,
            )
        elif any("churn" in observation.metric for observation in candidates):
            outcome, rationale, confidence = (
                Outcome.NOTIFY,
                "A material movement is associated with churn, matching the monitoring intent.",
                0.92,
            )
        elif any("season" in observation.metric for observation in observations):
            outcome, rationale, confidence = (
                Outcome.IGNORE,
                "The movement is large, but the dashboard includes an explicit seasonal context signal.",
                0.86,
            )
        else:
            outcome, rationale, confidence = (
                Outcome.INVESTIGATE,
                "A material movement was found, but the evidence does not identify a safe routing decision.",
                0.66,
            )
        if outcome not in card.allowed_outcomes:
            outcome = Outcome.INVESTIGATE
        recipient_key = None
        if outcome in (Outcome.NOTIFY, Outcome.ESCALATE) and card.recipients:
            recipient_key = card.recipients[0].key
        evidence = [
            {
                "chart_id": observation.chart_id,
                "chart_title": observation.chart_title,
                "statement": f"{observation.chart_title} is {observation.freshness}."
                if observation.freshness
                else (
                    f"{observation.chart_title} changed {observation.change_pct:.1f}% versus baseline."
                    if observation.change_pct is not None
                    else f"{observation.chart_title} has no comparable baseline."
                ),
                "values": {
                    "current": observation.current,
                    "baseline": observation.baseline,
                    "change_pct": observation.change_pct,
                    "freshness": observation.freshness,
                },
                "source_url": observation.source_url,
            }
            for observation in (stale or candidates or observations[:1])
        ]
        return Decision(
            outcome=outcome,
            recipient_key=recipient_key,
            rationale=rationale,
            confidence=confidence,
            probabilities={outcome.value: confidence, "other": 1 - confidence},
            evidence=evidence,
            observations=observations,
            monitor_id=card.id,
            dashboard_id=card.dashboard_id,
            evaluator=self.name,
        )


class JevJudger:
    name = "jev-latest"

    def __init__(self, api_key: str | None = None) -> None:
        from typesafe_sdk import AsyncTypeSafeClient

        self._client_type = AsyncTypeSafeClient
        self._api_key = api_key

    async def compile_plan(self, state: dict[str, Any], card: MonitorCard) -> dict[str, Any]:
        from typesafe_sdk import Choice, Noul

        async with self._client_type(api_key=self._api_key) as client:
            response = await client.system_one(
                state=state,
                questions={
                    "need_seasonality": Noul(
                        instructions="Does the monitoring intent require seasonal or same-period comparison?",
                        criteria={
                            "true": "The intent mentions seasonality or periodic variation.",
                            "false": "No seasonal comparison is requested.",
                        },
                    ),
                    "need_dimensions": Noul(
                        instructions="Does the monitoring intent require segment or dimension contribution analysis?",
                        criteria={
                            "true": "The intent asks to inspect a segment, region, device, customer type, or similar dimension.",
                            "false": "No dimension analysis is requested.",
                        },
                    ),
                    "need_cross_chart": Noul(
                        instructions="Does the monitoring intent require comparing related charts together?",
                        criteria={
                            "true": "The intent asks to inspect related charts or multiple signals together.",
                            "false": "One chart or signal is sufficient.",
                        },
                    ),
                    "baseline": Choice(
                        instructions="Which baseline should this monitoring plan use?",
                        criteria={
                            "previous_period": "Immediately preceding equivalent period.",
                            "trailing_4_period_average": "Mean of the last four equivalent periods.",
                            "same_period_last_year": "Equivalent period last year.",
                        },
                    ),
                },
            )
        operations = ["percent_change", "baseline_comparison", "freshness_check"]
        if response.nouls["need_seasonality"].noul >= 0.6:
            operations.append("seasonality_check")
        if response.nouls["need_dimensions"].noul >= 0.6:
            operations.append("dimension_contribution")
        if response.nouls["need_cross_chart"].noul >= 0.6:
            operations.append("cross_chart_comparison")
        return {"operations": operations, "baseline": response.choices["baseline"].choice}

    async def judge(
        self,
        state: dict[str, Any],
        card: MonitorCard,
        plan: MonitorPlan,
        observations: list[Observation],
    ) -> Decision:
        from typesafe_sdk import Choice, Score

        criteria = {outcome.value: None for outcome in card.allowed_outcomes}
        criteria.setdefault(
            "insufficient_data", "Evidence is missing, stale, or not comparable enough to decide."
        )
        recipient_criteria = {"no_recipient": "No notification should be sent."} | {
            recipient.key: recipient.label for recipient in card.recipients
        }
        async with self._client_type(api_key=self._api_key) as client:
            response = await client.system_one(
                state=state,
                questions={
                    "outcome": Choice(
                        instructions="Given the dashboard monitoring intent and computed evidence, what should the monitoring workflow do next?",
                        criteria=criteria,
                    ),
                    "materiality": Score(
                        instructions="How materially does the evidence violate the dashboard owner's monitoring intent?",
                        criteria=["normal", "notable", "material", "critical"],
                    ),
                    "recipient": Choice(
                        instructions="Which approved recipient group should receive this decision, if any? Choose no_recipient when no notification is warranted.",
                        criteria=recipient_criteria,
                    ),
                },
            )
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

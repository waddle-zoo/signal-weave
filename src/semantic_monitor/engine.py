from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analysis import candidate_observations, evidence_statements, observations_for_plan
from .compiler import compile_with_typesafe
from .models import (
    DashboardSnapshot,
    Decision,
    Evidence,
    MonitorCard,
    MonitorPlan,
    Observation,
    Outcome,
)
from .typesafe_adapter import DecisionJudger, JevJudger


@dataclass
class Evaluation:
    card: MonitorCard
    plan: MonitorPlan
    decision: Decision


class MonitorEngine:
    def __init__(self, judger: DecisionJudger | None = None) -> None:
        self.judger = judger or JevJudger()

    async def compile(
        self, card: MonitorCard, dashboard: DashboardSnapshot | None = None
    ) -> MonitorPlan:
        state = {"dashboard": dashboard.model_dump(mode="json")} if dashboard else None
        return await compile_with_typesafe(card, self.judger, state=state)

    async def evaluate(self, dashboard: DashboardSnapshot, card: MonitorCard) -> Evaluation:
        plan = await self.compile(card, dashboard)
        observations = observations_for_plan(dashboard, plan)
        source_errors = self._source_errors(dashboard, plan)
        candidates = candidate_observations(observations, card)
        candidate_keys = {
            (observation.chart_id, observation.metric) for observation in candidates
        }
        evidence_observations = candidates + [
            observation
            for observation in observations
            if (observation.chart_id, observation.metric) not in candidate_keys
        ]
        evidence = [
            {
                "chart_id": observation.chart_id,
                "chart_title": observation.chart_title,
                "statement": statement,
                "values": {
                    "current": observation.current,
                    "baseline": observation.baseline,
                    "change_pct": observation.change_pct,
                    "freshness": observation.freshness,
                    "candidate": (observation.chart_id, observation.metric) in candidate_keys,
                },
                "source_url": observation.source_url,
            }
            for observation, statement in zip(
                evidence_observations, evidence_statements(evidence_observations), strict=False
            )
        ]
        source_error_evidence = [
            Evidence(
                chart_id=error["chart_id"],
                chart_title=error["chart_title"],
                statement=error["message"],
                values={"error": error["message"]},
                source_url=error.get("source_url"),
            )
            for error in source_errors
        ]
        evidence.extend(source_error_evidence)
        evidence_payload = [
            item.model_dump(mode="json") if isinstance(item, Evidence) else item for item in evidence
        ]
        state: dict[str, Any] = {
            "dashboard": {
                "id": dashboard.id,
                "title": dashboard.title,
                "description": dashboard.description,
                "owners": dashboard.owners,
            },
            "monitor_card": card.model_dump(mode="json"),
            "monitor_plan": plan.model_dump(mode="json"),
            "observations": [observation.model_dump(mode="json") for observation in observations],
            "candidate_observations": [
                observation.model_dump(mode="json") for observation in candidates
            ],
            "source_errors": source_errors,
            "evidence": evidence_payload,
        }
        decision = await self.judger.judge(state, card, plan, observations)
        decision = self._apply_safety_gates(
            decision, card, observations, source_errors, source_error_evidence
        )
        return Evaluation(card=card, plan=plan, decision=decision)

    @staticmethod
    def _source_errors(
        dashboard: DashboardSnapshot, plan: MonitorPlan
    ) -> list[dict[str, str | None]]:
        selected = set(plan.selected_chart_ids)
        charts = {chart.id: chart for chart in dashboard.charts}
        errors: list[dict[str, str | None]] = []
        if not selected:
            errors.append(
                {
                    "chart_id": "*",
                    "chart_title": "Selected charts",
                    "message": "The monitoring plan selected no source charts.",
                    "source_url": dashboard.source_url,
                }
            )
        for chart_id in sorted(selected - charts.keys()):
            errors.append(
                {
                    "chart_id": chart_id,
                    "chart_title": chart_id,
                    "message": f"Selected chart {chart_id} was not present in the source dashboard.",
                    "source_url": dashboard.source_url,
                }
            )
        for chart in dashboard.charts:
            if chart.id in selected and chart.error:
                errors.append(
                    {
                        "chart_id": chart.id,
                        "chart_title": chart.title,
                        "message": chart.error,
                        "source_url": dashboard.source_url,
                    }
                )
        return errors

    @staticmethod
    def _apply_safety_gates(
        decision: Decision,
        card: MonitorCard,
        observations: list[Observation],
        source_errors: list[dict[str, str | None]],
        source_error_evidence: list[Evidence],
    ) -> Decision:
        allowed_recipient_keys = {recipient.key for recipient in card.recipients}
        if decision.outcome not in (Outcome.NOTIFY, Outcome.ESCALATE) or (
            decision.recipient_key not in allowed_recipient_keys
        ):
            decision = decision.model_copy(update={"recipient_key": None})
        if source_errors:
            outcome = (
                Outcome.INSUFFICIENT_DATA
                if Outcome.INSUFFICIENT_DATA in card.allowed_outcomes
                else Outcome.INVESTIGATE
            )
            existing_evidence = {
                (item.chart_id, item.statement) for item in decision.evidence
            }
            new_evidence = list(decision.evidence)
            new_evidence.extend(
                item
                for item in source_error_evidence
                if (item.chart_id, item.statement) not in existing_evidence
            )
            return decision.model_copy(
                update={
                    "outcome": outcome,
                    "recipient_key": None,
                    "rationale": "One or more selected source charts were unavailable or ambiguous, so no automatic action is safe.",
                    "confidence": max(decision.confidence or 0.0, 0.95),
                    "evidence": new_evidence,
                }
            )
        stale = [
            observation
            for observation in observations
            if observation.freshness and "stale" in observation.freshness.lower()
        ]
        if stale and Outcome.ESCALATE in card.allowed_outcomes:
            if not card.recipients:
                return decision.model_copy(
                    update={
                        "outcome": Outcome.INVESTIGATE,
                        "recipient_key": None,
                        "rationale": "The dashboard is stale, but no approved recipient is available for escalation.",
                    }
                )
            return decision.model_copy(
                update={
                    "outcome": Outcome.ESCALATE,
                    "recipient_key": card.recipients[0].key if card.recipients else None,
                    "rationale": "A hard freshness gate requires escalation before interpreting this dashboard.",
                    "confidence": max(decision.confidence or 0.0, 0.99),
                }
            )
        if observations and not any(observation.change_pct is not None for observation in observations):
            outcome = (
                Outcome.INSUFFICIENT_DATA
                if Outcome.INSUFFICIENT_DATA in card.allowed_outcomes
                else Outcome.INVESTIGATE
            )
            return decision.model_copy(
                update={
                    "outcome": outcome,
                    "recipient_key": None,
                    "rationale": "The monitored charts returned values but no comparable baseline, so no automatic action is safe.",
                    "confidence": max(decision.confidence or 0.0, 0.95),
                }
            )
        if (
            decision.outcome in (Outcome.IGNORE, Outcome.NOTIFY, Outcome.ESCALATE)
            and (
                decision.confidence is None
                or decision.confidence < card.action_confidence_threshold
            )
        ):
            confidence_text = (
                f"confidence {decision.confidence:.2f}"
                if decision.confidence is not None
                else "no confidence"
            )
            return decision.model_copy(
                update={
                    "outcome": Outcome.INVESTIGATE,
                    "recipient_key": None,
                    "rationale": f"The semantic decision was {decision.outcome.value}, but {confidence_text} is below the automatic-action threshold.",
                }
            )
        if decision.outcome in (Outcome.NOTIFY, Outcome.ESCALATE) and decision.recipient_key is None:
            return decision.model_copy(
                update={
                    "outcome": Outcome.INVESTIGATE,
                    "rationale": "An automatic action was selected without an approved recipient, so it requires investigation.",
                }
            )
        return decision

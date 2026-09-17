from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analysis import candidate_observations, evidence_statements, observations_for_plan
from .compiler import compile_with_typesafe, heuristic_compile
from .models import DashboardSnapshot, Decision, MonitorCard, MonitorPlan, Observation, Outcome
from .typesafe_adapter import DecisionJudger, HeuristicJudger


@dataclass
class Evaluation:
    card: MonitorCard
    plan: MonitorPlan
    decision: Decision


class MonitorEngine:
    def __init__(self, judger: DecisionJudger | None = None) -> None:
        self.judger = judger or HeuristicJudger()

    async def compile(self, card: MonitorCard) -> MonitorPlan:
        if self.judger.name == "heuristic":
            return heuristic_compile(card)
        return await compile_with_typesafe(card, self.judger)

    async def evaluate(self, dashboard: DashboardSnapshot, card: MonitorCard) -> Evaluation:
        plan = await self.compile(card)
        observations = observations_for_plan(dashboard, plan)
        candidates = candidate_observations(observations, card)
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
                },
                "source_url": observation.source_url,
            }
            for observation, statement in zip(
                candidates, evidence_statements(candidates), strict=False
            )
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
            "evidence": evidence,
        }
        decision = await self.judger.judge(state, card, plan, observations)
        decision = self._apply_safety_gates(decision, card, observations)
        return Evaluation(card=card, plan=plan, decision=decision)

    @staticmethod
    def _apply_safety_gates(
        decision: Decision, card: MonitorCard, observations: list[Observation]
    ) -> Decision:
        if decision.outcome not in (Outcome.NOTIFY, Outcome.ESCALATE) and decision.recipient_key is not None:
            decision = decision.model_copy(update={"recipient_key": None})
        stale = [
            observation
            for observation in observations
            if observation.freshness and "stale" in observation.freshness.lower()
        ]
        if stale and Outcome.ESCALATE in card.allowed_outcomes:
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
            decision.confidence is not None
            and decision.confidence < 0.70
            and decision.outcome in (Outcome.IGNORE, Outcome.NOTIFY)
        ):
            return decision.model_copy(
                update={
                    "outcome": Outcome.INVESTIGATE,
                    "recipient_key": None,
                    "rationale": f"The semantic decision was {decision.outcome.value}, but confidence {decision.confidence:.2f} is below the automatic-action threshold.",
                }
            )
        return decision

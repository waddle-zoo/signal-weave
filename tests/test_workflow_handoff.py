from __future__ import annotations

import pytest

from signalweave.engine import InsightEngine
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    Evidence,
    InsightCard,
    InsightResult,
    Observation,
    Outcome,
    ResourceContract,
    ResourceSnapshot,
)


def _card(*, follow_up_guidance: str = "") -> InsightCard:
    return InsightCard(
        id="workflow-card",
        title="Growth pulse",
        what_to_watch="Revenue and the signals that explain material movement.",
        why_watch="Decide whether Growth leadership needs to act.",
        follow_up_guidance=follow_up_guidance,
        sources=[
            {
                "key": "growth-dashboard",
                "adapter": "superset",
                "resource": "dashboard:growth",
                "label": "Growth dashboard",
            }
        ],
        delivery_methods=[
            DeliveryMethod(
                key="growth-analytics",
                outcome=Outcome.INVESTIGATE,
                label="Growth Analytics",
                destination="slack://growth-analytics",
            ),
            DeliveryMethod(
                key="growth-leadership",
                outcome=Outcome.NOTIFY,
                label="Growth Leadership",
                destination="slack://growth-leadership",
            ),
        ],
    )


def _resource() -> ResourceSnapshot:
    return ResourceSnapshot(
        source_key="growth-dashboard",
        adapter="superset",
        resource="dashboard:growth",
        title="Growth dashboard",
        observations=[
            Observation(
                source_key="growth-dashboard",
                subject_id="online-revenue",
                subject_label="Online revenue",
                metric="revenue",
                current=65,
                baseline=100,
                change_pct=-35,
            )
        ],
        evidence=[
            Evidence(
                source_key="growth-dashboard",
                subject_id="online-revenue",
                subject_label="Online revenue",
                statement="Online revenue declined 35%.",
            )
        ],
    )


class TwoStageJudger:
    name = "jev-two-stage-test-double"

    async def compile_plan(self, state, card):
        del state
        return {"capabilities": ["percent_change"], "baseline": card.comparison_windows[0]}

    async def judge(self, state, card, plan, observations):
        del plan
        confirmed = bool(state.get("context", {}).get("facts")) if state.get("context") else False
        outcome = Outcome.NOTIFY if confirmed else Outcome.INVESTIGATE
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            summary="The typed result includes the current evidence.",
            rationale="Diagnostic context is required before leadership delivery." if not confirmed else "Diagnostic context corroborates the cause.",
            confidence=0.9,
            probabilities={outcome.value: 0.9},
            evidence=state["evidence"],
            observations=observations,
            source_keys=[item.source_key for item in observations],
            evaluator=self.name,
        )


@pytest.mark.asyncio
async def test_single_step_cards_keep_outcome_and_get_terminal_handoff():
    run = await InsightEngine(TwoStageJudger()).evaluate(_card(), [_resource()])

    assert run.result.outcome == Outcome.INVESTIGATE
    assert [method.key for method in run.result.delivery_methods] == ["growth-analytics"]
    assert run.result.workflow is not None
    assert run.result.workflow.action == "deliver"
    assert run.result.workflow.status == "ready"
    assert run.result.workflow.delivery_method_keys == ["growth-analytics"]


@pytest.mark.asyncio
async def test_multi_step_card_hands_agent_a_follow_up_then_re_evaluates():
    card = _card(
        follow_up_guidance=(
            "Inspect traffic, campaigns, inventory, checkout failures, payments, and deployments. "
            "Return the diagnostic evidence to this card before notifying leadership."
        )
    )
    engine = InsightEngine(TwoStageJudger())
    first = await engine.evaluate(card, [_resource()])

    assert first.result.outcome == Outcome.INVESTIGATE
    assert first.result.workflow is not None
    assert first.result.workflow.action == "retrieve_evidence"
    assert first.result.workflow.status == "pending"
    assert "checkout failures" in first.result.workflow.instructions
    assert first.result.workflow.completion_criteria.startswith("Submit the follow-up evidence")

    context = ContextSnapshot(
        provider="growth-agent",
        version="diagnostic-1",
        facts=[
            ContextFact(
                fact_id="checkout-regression",
                subject_ref="superset|dashboard:growth",
                relation="diagnosed_by",
                object_ref="ops|checkout-failures",
                statement="Checkout failures increased 42% immediately after a payment deployment.",
            )
        ],
    )
    second = await engine.evaluate(card, [_resource()], context_override=context)

    assert second.result.outcome == Outcome.NOTIFY
    assert second.result.workflow is not None
    assert second.result.workflow.action == "deliver"
    assert second.result.workflow.status == "ready"
    assert second.result.workflow.delivery_method_keys == ["growth-leadership"]


def test_workflow_handoff_is_strictly_typed():
    card = _card(follow_up_guidance="Re-evaluate after diagnostics.")
    assert card.follow_up_guidance == "Re-evaluate after diagnostics."


@pytest.mark.asyncio
async def test_failed_required_source_cannot_become_a_delivery_handoff():
    class UnsafeJudger(TwoStageJudger):
        async def judge(self, state, card, plan, observations):
            del state, plan
            return InsightResult(
                card_id=card.id,
                outcome=Outcome.NOTIFY,
                summary="The judging model attempted to notify despite a failed source.",
                rationale="The safety gate must own the final result.",
                confidence=0.99,
                probabilities={Outcome.NOTIFY.value: 0.99},
                evidence=[],
                observations=observations,
                source_keys=[item.source_key for item in observations],
                evaluator="unsafe-test-double",
            )

    failed = _resource().model_copy(
        update={
            "error": "dashboard unavailable",
            "contract": ResourceContract(source_status="failed"),
        }
    )
    run = await InsightEngine(UnsafeJudger()).evaluate(_card(follow_up_guidance="Repair and re-evaluate."), [failed])

    assert run.result.outcome == Outcome.INSUFFICIENT_DATA
    assert run.result.workflow is not None
    assert run.result.workflow.action == "repair_source"
    assert run.result.workflow.status == "blocked"
    assert run.result.delivery_methods == []

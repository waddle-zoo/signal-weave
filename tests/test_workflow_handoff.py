from __future__ import annotations

import pytest

from signalweave.engine import InsightEngine
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    Evidence,
    EvidencePlan,
    EvidenceSlot,
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
            question_results=[{
                "key": f"question_{i}", "question": question,
                "status": "supported" if confirmed else "unknown",
                "probability": .99 if confirmed else .5,
            } for i, question in enumerate(card.questions)],
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
async def test_workflow_exposes_compiled_evidence_slots_and_completion_state():
    card = _card(follow_up_guidance="Retrieve diagnostic evidence.").model_copy(
        update={
            "questions": ["Did the affected funnel step change?"],
            "watch_for": ["A material online revenue movement."],
        }
    )
    run = await InsightEngine(TwoStageJudger()).evaluate(card, [_resource()])

    assert run.result.evidence_plan is not None
    slots = {slot.key: slot for slot in run.result.evidence_plan.slots}
    assert slots["source:growth-dashboard"].status == "fulfilled"
    assert slots["source:growth-dashboard"].source_refs[0].resource == "dashboard:growth"
    assert slots["question:1"].status == "pending"
    assert slots["watch:1"].status == "pending"
    assert "question:1" in run.result.evidence_plan.missing_slot_keys
    assert "Evidence slots to complete:" in run.result.workflow.instructions
    assert "Did the affected funnel step change?" in run.result.workflow.instructions


@pytest.mark.asyncio
async def test_context_fact_can_fulfill_a_named_evidence_slot_when_semantically_supported():
    card = _card(follow_up_guidance="Re-evaluate after diagnostics.").model_copy(
        update={"questions": ["Did the affected funnel step change?"]}
    )
    context = ContextSnapshot(
        provider="growth-agent",
        version="diagnostic-1",
        facts=[
            ContextFact(
                fact_id="funnel-change",
                slot_key="question:1",
                subject_ref="warehouse|purchase-funnel",
                relation="supports",
                statement="Purchase conversion declined in the affected cohort.",
            )
        ],
    )
    run = await InsightEngine(TwoStageJudger()).evaluate(
        card,
        [_resource()],
        context_override=context,
    )

    assert run.result.evidence_plan is not None
    slot = next(slot for slot in run.result.evidence_plan.slots if slot.key == "question:1")
    assert slot.status == "fulfilled"
    assert slot.evidence_fact_ids == ["funnel-change"]


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
    assert "Evidence slots to complete:" in run.result.workflow.instructions
    assert "growth-dashboard" in run.result.workflow.instructions
    assert "after evidence repair and re-evaluation" in run.result.workflow.instructions
    assert run.result.delivery_methods == []


@pytest.mark.parametrize("guidance", ["", "Report the driver decomposition to leadership."])
def test_data_repair_precedes_analytical_follow_up_even_without_missing_plan_slots(guidance):
    card = _card(follow_up_guidance=guidance)
    result = InsightResult(
        card_id=card.id,
        outcome=Outcome.INSUFFICIENT_DATA,
        summary="The source is reachable but its population coverage is unresolved.",
        rationale="Coverage needs validation.",
        confidence=0.9,
        probabilities={"insufficient_data": 0.9},
        evidence=[], observations=[], source_keys=["growth-dashboard"],
        evaluator="handoff-contract-test",
    )
    handoff = InsightEngine._workflow_handoff(card, result)
    assert handoff.action == "repair_source"
    assert handoff.status == "blocked"
    assert handoff.instructions.startswith("Repair or validate")
    assert "do not reconstruct missing values" in handoff.instructions
    assert "Source health alone is not sufficient" in handoff.completion_criteria
    assert handoff.required_source_keys == ["growth-dashboard"]
    assert handoff.delivery_method_keys == []
    if guidance:
        assert "after evidence repair and re-evaluation" in handoff.instructions
        assert handoff.instructions.endswith(guidance)
    else:
        assert "Card follow-up guidance" not in handoff.instructions


@pytest.mark.parametrize("guidance", ["Inspect the decomposition.", "x" * 8000])
def test_repair_handoff_preserves_large_plan_and_references_untruncated_owner_guidance(guidance):
    card = _card(follow_up_guidance=guidance)
    slots = [EvidenceSlot(key=f"question:{n}", role="question", question="q" * 4000,
                          required=True, source_keys=["growth-dashboard"]) for n in range(3)]
    plan = EvidencePlan(objective="Validate evidence", slots=slots, missing_slot_keys=[s.key for s in slots])
    result = InsightResult(card_id=card.id, outcome=Outcome.INSUFFICIENT_DATA,
                           summary="Required evidence missing", rationale="Repair", evaluator="test",
                           evidence_plan=plan)
    handoff = InsightEngine._workflow_handoff(card, result)
    assert len(handoff.instructions) <= 8000
    assert handoff.instructions.startswith("Repair or validate")
    assert handoff.evidence_plan == plan
    assert "Consult the attached evidence_plan" in handoff.instructions
    assert card.follow_up_guidance == guidance
    if len(guidance) == 8000:
        assert "exceeds this handoff's text limit" in handoff.instructions
        assert f"card {card.id} version {card.version}" in handoff.instructions
    else:
        assert handoff.instructions.endswith(guidance)

import pytest

from signalweave.engine import InsightEngine
from signalweave.evaluation import (
    CardEvaluationCase,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
)
from signalweave.models import (
    DeliveryMethod,
    InsightCard,
    InsightResult,
    Observation,
    Outcome,
    ResourceSnapshot,
    SourceRef,
)

SOURCE = SourceRef(
    key="orders",
    adapter="sql",
    resource="query:orders",
    label="Orders",
)


def card(card_id: str) -> InsightCard:
    return InsightCard(
        id=card_id,
        title="Orders pulse",
        what_to_watch="Orders movement",
        why_watch="Support the operations response",
        decision_guidance="Notify operations for a supported non-expected movement; otherwise ignore.",
        sources=[SOURCE],
        delivery_methods=[
            DeliveryMethod(
                key="operations",
                outcome=Outcome.NOTIFY,
                label="Operations",
                destination="slack://operations",
            )
        ],
    )


def snapshot() -> ResourceSnapshot:
    return ResourceSnapshot(
        source_key="orders",
        adapter="sql",
        resource="query:orders",
        title="Orders",
        observations=[
            Observation(
                source_key="orders",
                subject_id="orders",
                subject_label="Orders",
                metric="orders",
                current=120,
                baseline=100,
                change_pct=20,
            )
        ],
    )


class JevFixture:
    name = "jev-fixture"

    async def compile_plan(self, state, card):
        del state
        return {"capabilities": [], "baseline": card.comparison_windows[0]}

    async def judge(self, state, card, plan, observations):
        del plan
        outcome = Outcome.NOTIFY if card.id.endswith("-good") else Outcome.IGNORE
        methods = [method for method in card.delivery_methods if method.outcome == outcome]
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            delivery_methods=methods,
            summary="fixture",
            rationale="fixture",
            confidence=0.99,
            probabilities={outcome.value: 0.99},
            evidence=state["evidence"],
            observations=observations,
            source_keys=[item.source_key for item in observations],
            evaluator=self.name,
        )


@pytest.mark.asyncio
async def test_card_workflow_evaluator_certifies_a_complete_jev_path():
    case = CardEvaluationCase(
        id="good",
        card=card("orders-good"),
        resources=[snapshot()],
        expected_outcome=Outcome.NOTIFY,
        expected_delivery_method_keys=["operations"],
        required_evidence_source_keys=["orders"],
        expected_retrieval_refs=["sql|query:orders"],
    )

    report = await CardWorkflowEvaluator(InsightEngine(JevFixture())).evaluate(
        [case],
        thresholds=CardEvaluationThresholds(
            min_outcome_accuracy=1,
            min_evidence_recall=1,
            min_retrieval_recall=1,
            min_cases=1,
        ),
    )

    assert report.status == "approved"
    assert report.outcome_accuracy == 1
    assert report.evidence_recall == 1
    assert report.retrieval_recall == 1
    assert report.cases[0].safe_action is True
    assert report.cases[0].delivery_exact is True


@pytest.mark.asyncio
async def test_card_workflow_evaluator_marks_wrong_action_unsafe():
    case = CardEvaluationCase(
        id="wrong",
        card=card("orders-wrong"),
        resources=[snapshot()],
        expected_outcome=Outcome.NOTIFY,
        expected_delivery_method_keys=["operations"],
        required_evidence_source_keys=["orders"],
        expected_retrieval_refs=["sql|query:orders"],
    )

    report = await CardWorkflowEvaluator(InsightEngine(JevFixture())).evaluate([case])

    assert report.status == "shadow"
    assert report.outcome_accuracy == 0
    assert report.unsafe_action_rate == 1
    assert report.cases[0].unsafe_action is True


@pytest.mark.asyncio
async def test_card_workflow_evaluator_blocks_on_runtime_failure():
    class BrokenEngine:
        async def evaluate(self, card, resources, context_override=None):
            del card, resources, context_override
            raise TimeoutError("Jev unavailable")

    case = CardEvaluationCase(
        id="failure",
        card=card("orders-good"),
        expected_outcome=Outcome.NOTIFY,
    )
    report = await CardWorkflowEvaluator(BrokenEngine()).evaluate([case])

    assert report.status == "blocked"
    assert report.error_count == 1
    assert "Jev unavailable" in (report.cases[0].error or "")


@pytest.mark.asyncio
async def test_card_workflow_evaluator_blocks_push_card_without_human_guidance():
    incomplete = card("orders-good").model_copy(update={"decision_guidance": ""})
    case = CardEvaluationCase(
        id="incomplete",
        card=incomplete,
        resources=[snapshot()],
        expected_outcome=Outcome.NOTIFY,
    )

    report = await CardWorkflowEvaluator(InsightEngine(JevFixture())).evaluate([case])

    assert report.status == "blocked"
    assert report.preflight_blockers == [
        "orders-good: push-capable card is missing human decision guidance"
    ]

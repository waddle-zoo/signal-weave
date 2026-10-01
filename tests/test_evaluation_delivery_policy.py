"""Offline owner-labeled delivery checks through the real evaluation engine."""

import pytest
import typesafe_sdk
from test_evaluation import JevFixture, card, snapshot

from signalweave.engine import InsightEngine
from signalweave.evaluation import (
    CardEvaluationCase,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
)
from signalweave.models import DeliveryMethod, Outcome


@pytest.fixture(autouse=True)
def forbid_live_jev(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Delivery policy tests must not instantiate a live Jev client")

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", unexpected_client)


class OutcomeFixture(JevFixture):
    def __init__(self, outcome=Outcome.INVESTIGATE):
        self.outcome = outcome
        self.states = []

    async def judge(self, state, card, plan, observations):
        self.states.append(state)
        result = await super().judge(state, card, plan, observations)
        return result.model_copy(update={
            "outcome": self.outcome,
            "probabilities": {self.outcome.value: 1.0},
            "delivery_methods": [
                method for method in card.delivery_methods if method.outcome == self.outcome
            ],
        })


def delivery_case(actual_keys, expected_keys, *, outcome=Outcome.INVESTIGATE, case_id="delivery"):
    reviewed_card = card("delivery-good").model_copy(update={
        "delivery_methods": [
            DeliveryMethod(
                key=key, outcome=outcome, label=key, destination=f"slack://{key}",
            )
            for key in actual_keys
        ],
    })
    return CardEvaluationCase(
        id=case_id, card=reviewed_card, resources=[snapshot()],
        expected_outcome=outcome, expected_delivery_method_keys=expected_keys,
        required_evidence_source_keys=["orders"],
        expected_retrieval_refs=["sql|query:orders"],
    )


@pytest.mark.parametrize("actual_keys", [
    ["other-owner"], [], ["owner", "other-owner"],
], ids=["wrong-recipient", "missing-recipient", "extra-recipient"])
async def test_correct_outcome_cannot_promote_inexact_owner_labeled_delivery(actual_keys):
    case = delivery_case(actual_keys, ["owner"])
    report = await CardWorkflowEvaluator(InsightEngine(OutcomeFixture())).evaluate([case])

    assert report.error_count == 0
    assert report.outcome_accuracy == report.evidence_recall == report.retrieval_recall == 1
    assert report.unsafe_action_rate == 0  # This existing metric is outcome-only.
    result = report.cases[0]
    assert result.exact_outcome and result.safe_action
    assert result.actual_delivery_method_keys == sorted(actual_keys)
    assert result.delivery_exact is False
    assert report.status == "shadow"


@pytest.mark.parametrize("outcome", [Outcome.IGNORE, Outcome.INVESTIGATE, Outcome.INSUFFICIENT_DATA])
async def test_explicit_owner_labeled_no_route_can_still_certify(outcome):
    report = await CardWorkflowEvaluator(InsightEngine(OutcomeFixture(outcome))).evaluate([
        delivery_case([], [], outcome=outcome),
    ])

    assert report.outcome_accuracy == 1
    assert report.cases[0].actual_delivery_method_keys == []
    assert report.cases[0].delivery_exact is True
    assert report.status == "approved"


@pytest.mark.parametrize("expected_keys,expected_status", [
    (None, "approved"), ([], "shadow"),
], ids=["unlabeled", "explicit-no-route"])
async def test_missing_delivery_label_is_not_an_explicit_empty_label(expected_keys, expected_status):
    report = await CardWorkflowEvaluator(InsightEngine(OutcomeFixture())).evaluate([
        delivery_case(["owner"], expected_keys),
    ])

    assert report.outcome_accuracy == 1
    assert report.cases[0].delivery_exact is (expected_keys is None)
    assert report.status == expected_status


async def test_exact_recipient_set_is_order_independent():
    report = await CardWorkflowEvaluator(InsightEngine(OutcomeFixture())).evaluate([
        delivery_case(["owner", "second-owner"], ["second-owner", "owner"]),
    ])

    assert report.cases[0].delivery_exact is True
    assert report.status == "approved"


async def test_delivery_failure_is_not_averaged_away_by_outcome_accuracy():
    cases = [
        delivery_case(["owner"], ["owner"], case_id=f"exact-{index}")
        for index in range(19)
    ]
    cases.append(delivery_case(["other-owner"], ["owner"], case_id="wrong-recipient"))
    report = await CardWorkflowEvaluator(InsightEngine(OutcomeFixture())).evaluate(cases)

    assert report.successful_case_count == 20
    assert report.outcome_accuracy == 1
    joint_accuracy = sum(case.exact_outcome and case.delivery_exact for case in report.cases) / 20
    assert joint_accuracy == 0.95
    assert report.status == "shadow"  # Delivery is exact, not a new tunable 95% gate.


async def test_allowed_outcome_and_relaxed_thresholds_do_not_waive_delivery_labels():
    case = delivery_case(["other-owner"], ["owner"]).model_copy(update={
        "expected_outcome": Outcome.NOTIFY,
        "allowed_outcomes": [Outcome.NOTIFY, Outcome.INVESTIGATE],
    })
    report = await CardWorkflowEvaluator(InsightEngine(OutcomeFixture())).evaluate(
        [case], thresholds=CardEvaluationThresholds(min_outcome_accuracy=0),
    )

    assert report.outcome_accuracy == 0
    assert report.unsafe_action_rate == 0
    assert report.cases[0].delivery_exact is False
    assert report.status == "shadow"


async def test_delivery_labels_change_only_scoring_not_engine_inputs():
    case = delivery_case(["owner"], ["owner"])
    changed_label = case.model_copy(update={"expected_delivery_method_keys": ["label-only-owner"]})
    original_judger, changed_judger = OutcomeFixture(), OutcomeFixture()
    original = await CardWorkflowEvaluator(InsightEngine(original_judger)).evaluate([case])
    changed = await CardWorkflowEvaluator(InsightEngine(changed_judger)).evaluate([changed_label])

    assert original_judger.states == changed_judger.states
    assert original.input_digest == changed.input_digest
    assert original.label_digest != changed.label_digest
    assert original.outcome_accuracy == changed.outcome_accuracy == 1
    assert original.status == "approved"
    assert changed.status == "shadow"

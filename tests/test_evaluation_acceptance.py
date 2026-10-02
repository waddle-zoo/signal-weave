"""Empirical acceptance contracts through the real engine, without inference calls."""

import copy
import json
from datetime import datetime, timezone

import pytest
import typesafe_sdk

from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.evaluation import (
    CardEvaluationCase,
    CardEvaluationReport,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
    card_acceptance_digest,
)
from signalweave.models import (
    InsightCard,
    InsightCardStatus,
    InsightResult,
    Outcome,
    ResourceSnapshot,
)


@pytest.fixture(autouse=True)
def forbid_live_clients(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Acceptance tests must not instantiate a live inference client")

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", forbidden)
    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", forbidden)


class SemanticDouble:
    name = "offline-acceptance-contract"

    def __init__(self, *, question="supported", watch="present"):
        self.question = question
        self.watch = watch
        self.states = []

    async def compile_plan(self, state, card):
        raise AssertionError("Acceptance must use the stored plan")

    async def judge(self, state, card, plan, observations):
        self.states.append(copy.deepcopy(state))
        value = observations[0].current if observations else None
        outcome = {None: Outcome.INSUFFICIENT_DATA, 100: Outcome.IGNORE, 90: Outcome.INVESTIGATE}.get(value, Outcome.NOTIFY)
        return InsightResult(
            card_id=card.id, outcome=outcome, confidence=0.99,
            probabilities={outcome.value: 0.99}, summary="Offline semantic judgment",
            rationale="Code owns evidence admission and routing.", evaluator=self.name,
            observations=observations, evidence=state["evidence"],
            question_results=[{
                "key": f"question_{i}", "question": question, "status": self.question,
                "probability": 0.5 if self.question == "unknown" else 0.99,
            } for i, question in enumerate(card.questions)],
            watch_results=[{
                "key": f"watch_{i}", "watch_for": watch, "status": self.watch,
                "probability": 0.5 if self.watch == "unknown" else 0.99,
            } for i, watch in enumerate(card.watch_for)],
        )


def card(**updates):
    value = InsightCard.model_validate({
        "id": "acceptance", "title": "Approved metric", "what_to_watch": "Metric movement",
        "why_watch": "Decide whether the owner should respond.",
        "decision_guidance": "Notify on a material decline, ignore stable evidence, and abstain when evidence is missing.",
        "principal_id": "owner", "principal_tenant": "tenant",
        "sources": [{"key": "metric", "adapter": "test", "resource": "query:metric", "label": "Metric"}],
        "delivery_methods": [{"key": "owner", "outcome": "notify", "label": "Owner",
                              "destination": "opaque endpoint / exact ? value"}],
        **updates,
    })
    value.compiled_plan = base_plan(value)
    return value


def snapshot(value=80):
    return ResourceSnapshot.model_validate({
        "source_key": "metric", "adapter": "test", "resource": "query:metric", "title": "Metric",
        "observations": [{"source_key": "metric", "subject_id": "total", "metric": "metric",
                          "current": value, "baseline": 100, "change_pct": value - 100}],
    })


def cases_for(reviewed_card=None):
    reviewed_card = reviewed_card or card()
    cases = []
    for outcome, value in ((Outcome.NOTIFY, 80), (Outcome.IGNORE, 100), (Outcome.INSUFFICIENT_DATA, None)):
        methods = [method for method in reviewed_card.delivery_methods if method.outcome == outcome]
        cases.append(CardEvaluationCase(
            id=f"{reviewed_card.id}-{outcome.value}", card=reviewed_card,
            resources=[snapshot(value)] if value is not None else [],
            expected_outcome=outcome, expected_delivery_method_keys=[method.key for method in methods],
            expected_delivery_destinations={method.key: method.destination for method in methods},
            required_evidence_source_keys=["metric"] if value is not None else [],
            expected_retrieval_refs=["test|query:metric"] if value is not None else [],
        ))
    return cases


async def evaluate(cases, **kwargs):
    return await CardWorkflowEvaluator(InsightEngine(SemanticDouble())).evaluate(
        cases, acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA], **kwargs,
    )


async def test_acceptance_exact_routes_opaque_endpoints_and_missing_evidence():
    cases = cases_for()
    report = await evaluate(cases)
    assert report.status == "approved"
    assert report.acceptance_passed is True
    assert report.acceptance_scope == "supplied_snapshot_replay"
    assert report.acceptance_outcomes == [Outcome.IGNORE, Outcome.INSUFFICIENT_DATA, Outcome.NOTIFY]
    assert report.card_execution_digests == {"acceptance": card_acceptance_digest(cases[0].card)}
    assert report.outcome_accuracy == report.evidence_recall == report.retrieval_recall == 1
    assert report.cases[0].actual_delivery_destinations == cases[0].expected_delivery_destinations
    assert all(row.delivery_exact and row.delivery_destinations_exact for row in report.cases)
    missing = report.cases[-1]
    assert missing.evidence_plan.status == "blocked"
    assert missing.workflow.evidence_plan == missing.evidence_plan
    assert missing.failure_reasons == []
    assert CardEvaluationReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("field", [
    "expected_delivery_method_keys", "expected_delivery_destinations",
    "required_evidence_source_keys", "expected_retrieval_refs",
])
async def test_omitted_labels_block_before_inference(field):
    cases = cases_for()
    payload = cases[0].model_dump()
    del payload[field]
    cases[0] = CardEvaluationCase.model_validate(payload)
    judger = SemanticDouble()
    report = await CardWorkflowEvaluator(InsightEngine(judger)).evaluate(cases, acceptance_outcomes=[Outcome.NOTIFY])
    assert report.status == "blocked" and report.acceptance_passed is False
    assert report.preflight_blockers and judger.states == []


@pytest.mark.parametrize("destinations", [None, {}, {"different-key": "endpoint"}])
async def test_missing_or_inconsistent_destination_labels_block(destinations):
    cases = cases_for()
    cases[0].expected_delivery_destinations = destinations
    report = await evaluate(cases)
    assert report.status == "blocked" and report.acceptance_passed is False


async def test_wrong_exact_endpoint_fails_even_when_all_other_scores_pass():
    cases = cases_for()
    cases[0].expected_delivery_destinations = {"owner": "another opaque endpoint"}
    report = await evaluate(cases)
    assert report.status == "shadow" and report.acceptance_passed is False
    assert report.outcome_accuracy == report.evidence_recall == report.retrieval_recall == 1
    result = report.cases[0]
    assert result.actual_delivery_method_keys == ["owner"]
    assert result.delivery_destinations_exact is False and result.delivery_exact is False
    assert result.failure_reasons == ["delivery_destinations_mismatch"]


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong"])
async def test_delivery_keys_must_match_exactly(mutation):
    cases = cases_for()
    expected = {"missing": [], "extra": ["owner", "extra"], "wrong": ["wrong"]}[mutation]
    cases[0].expected_delivery_method_keys = expected
    cases[0].expected_delivery_destinations = {key: "endpoint" for key in expected}
    report = await evaluate(cases)
    assert report.acceptance_passed is False
    assert "delivery_keys_mismatch" in report.cases[0].failure_reasons


async def test_acceptance_tightens_thresholds_without_mutating_caller_or_relaxing_other_gates():
    relaxed = CardEvaluationThresholds(min_outcome_accuracy=0, min_evidence_recall=0,
                                      min_retrieval_recall=0, max_unsafe_action_rate=1, max_error_rate=1)
    cases = cases_for()
    cases[0].resources[0].observations[0].current = 100
    cases[0].allowed_outcomes = [Outcome.NOTIFY, Outcome.IGNORE]
    report = await evaluate(cases, thresholds=relaxed)
    assert report.acceptance_passed is False and report.status == "shadow"
    assert report.cases[0].safe_action  # Allowed conservatism cannot waive exact acceptance.
    assert report.cases[0].failure_reasons[0] == "outcome_mismatch"
    assert report.thresholds.min_outcome_accuracy == report.thresholds.min_evidence_recall == report.thresholds.min_retrieval_recall == 1
    assert report.thresholds.max_error_rate == report.thresholds.max_unsafe_action_rate == 0
    assert relaxed.min_outcome_accuracy == 0 and relaxed.max_error_rate == 1
    report = await evaluate(cases_for(), thresholds=CardEvaluationThresholds(min_cases=4))
    assert report.acceptance_passed is False
    report = await evaluate(cases_for(), thresholds=CardEvaluationThresholds(require_dataset_provenance=True))
    assert report.status == "blocked" and report.acceptance_passed is False


@pytest.mark.parametrize("field,value,reason", [
    ("required_evidence_source_keys", ["unknown"], "missing_required_evidence"),
    ("expected_retrieval_refs", ["test|unknown"], "missing_expected_retrieval"),
    ("expected_retrieval_refs", [], "unexpected_retrieval"),
])
async def test_missing_or_unexpected_evidence_cannot_pass(field, value, reason):
    cases = cases_for()
    setattr(cases[0], field, value)
    report = await evaluate(cases)
    assert report.acceptance_passed is False
    assert reason in report.cases[0].failure_reasons


@pytest.mark.parametrize("index", [0, 1, 2])
async def test_each_required_outcome_must_have_a_labeled_case(index):
    cases = cases_for()
    removed = cases.pop(index)
    report = await evaluate(cases)
    assert report.status == "blocked" and report.acceptance_passed is False
    assert any(removed.expected_outcome.value in text for text in report.preflight_blockers)


async def test_caller_outcome_coverage_is_required_per_card():
    cases = cases_for()
    report = await CardWorkflowEvaluator(InsightEngine(SemanticDouble())).evaluate(
        cases, acceptance_outcomes=[Outcome.INVESTIGATE],
    )
    assert report.acceptance_passed is False
    assert any("investigate" in text for text in report.preflight_blockers)
    second = card(id="second", delivery_methods=[{
        "key": "ops", "outcome": "investigate", "label": "Ops", "destination": "ops endpoint",
    }])
    second_cases = cases_for(second)[1:]
    report = await evaluate([*cases, *second_cases])
    assert report.acceptance_passed is False
    assert any(text.startswith("second:") and "notify" in text
               for text in report.preflight_blockers)


async def test_readonly_card_with_explicit_quiet_and_missing_cases_needs_no_alert_route():
    cases = cases_for(card(delivery_methods=[]))[1:]
    report = await CardWorkflowEvaluator(InsightEngine(SemanticDouble())).evaluate(
        cases, acceptance_outcomes=[Outcome.IGNORE],
    )
    assert report.acceptance_passed is True
    assert all(row.actual_delivery_destinations == {} for row in report.cases)


async def test_only_policy_applicable_outcomes_are_required():
    reviewed = card(delivery_methods=[
        {"key": "ops", "outcome": "investigate", "label": "Ops", "destination": "opaque ops"},
        {"key": "optional-alert", "outcome": "notify", "label": "Alert", "destination": "opaque alert"},
    ])
    case = CardEvaluationCase(
        id="investigate-only", card=reviewed, resources=[snapshot(90)],
        expected_outcome=Outcome.INVESTIGATE,
        expected_delivery_method_keys=["ops"], expected_delivery_destinations={"ops": "opaque ops"},
        required_evidence_source_keys=["metric"], expected_retrieval_refs=["test|query:metric"],
    )
    report = await CardWorkflowEvaluator(InsightEngine(SemanticDouble())).evaluate(
        [case], acceptance_outcomes=[Outcome.INVESTIGATE],
    )
    assert report.acceptance_passed is True
    assert report.acceptance_outcomes == [Outcome.INVESTIGATE]
    readonly = case.model_copy(update={
        "card": card(delivery_methods=[]), "expected_delivery_method_keys": [],
        "expected_delivery_destinations": {},
    })
    report = await CardWorkflowEvaluator(InsightEngine(SemanticDouble())).evaluate(
        [readonly], acceptance_outcomes=[Outcome.INVESTIGATE],
    )
    assert report.acceptance_passed is True
    assert report.cases[0].actual_delivery_destinations == {}
    quiet = cases_for(card(delivery_methods=[]))[1]
    report = await CardWorkflowEvaluator(InsightEngine(SemanticDouble())).evaluate(
        [quiet], acceptance_outcomes=[Outcome.IGNORE],
    )
    assert report.acceptance_passed is True


async def test_empty_acceptance_request_is_not_ordinary_certification():
    report = await CardWorkflowEvaluator(InsightEngine(SemanticDouble())).evaluate(cases_for(), acceptance_outcomes=[])
    assert report.status == "blocked" and report.acceptance_passed is False
    assert report.acceptance_outcomes == []
    report = await evaluate([])
    assert report.status == "blocked" and report.acceptance_passed is False


async def test_unknown_outcome_rejected_before_inference():
    judger = SemanticDouble()
    with pytest.raises(ValueError):
        await CardWorkflowEvaluator(InsightEngine(judger)).evaluate(cases_for(), acceptance_outcomes=["unknown"])
    assert judger.states == []


async def test_duplicate_case_ids_and_differing_same_version_contracts_block():
    cases = cases_for()
    cases[1].id = cases[0].id
    report = await evaluate(cases)
    assert any("duplicate acceptance case id" in text for text in report.preflight_blockers)
    cases = cases_for()
    cases[1].card = cases[1].card.model_copy(deep=True)
    cases[1].card.delivery_methods[0].destination = "different endpoint"
    report = await evaluate(cases)
    assert report.acceptance_passed is False
    assert any("differing execution contracts" in text for text in report.preflight_blockers)
    assert report.card_execution_digests == {}


async def test_stored_compiled_plan_is_required_before_acceptance():
    cases = cases_for()
    for case in cases:
        case.card.compiled_plan = None
    report = await evaluate(cases)
    assert report.status == "blocked" and report.acceptance_passed is False
    assert any("stored compiled_plan" in text for text in report.preflight_blockers)


@pytest.mark.parametrize("field,value", [
    ("resource", "query:other"), ("adapter", "other"),
])
async def test_snapshot_identity_cannot_be_substituted(field, value):
    cases = cases_for()
    setattr(cases[0].resources[0], field, value)
    report = await evaluate(cases)
    assert report.status == "blocked" and report.acceptance_passed is False
    assert any("snapshot identity" in text for text in report.preflight_blockers)


async def test_extra_snapshots_are_replay_inputs_not_dynamic_retrieval_certification():
    cases = cases_for()
    extra = snapshot()
    extra.source_key = "context"
    extra.resource = "query:context"
    extra.observations = []
    cases[0].resources.append(extra)
    cases[0].expected_retrieval_refs.append("test|query:context")
    report = await evaluate(cases)
    assert report.acceptance_passed is True
    assert report.acceptance_scope == "supplied_snapshot_replay"


async def test_unknown_source_key_does_not_fill_a_missing_declared_source():
    cases = cases_for()
    cases[0].resources[0].source_key = "unknown"
    report = await evaluate(cases)
    assert report.acceptance_passed is False
    assert report.cases[0].outcome == Outcome.INSUFFICIENT_DATA
    assert "outcome_mismatch" in report.cases[0].failure_reasons


@pytest.mark.parametrize("slot", ["question:1", "watch:1"])
@pytest.mark.parametrize("advisory", [False, True])
async def test_required_vs_advisory_unknown_retains_real_engine_diagnostics(slot, advisory):
    reviewed = card(questions=["Can the dimensional contribution be explained?"],
                    watch_for=["An explanatory change is present."],
                    evidence_requirements={slot: not advisory})
    judger = SemanticDouble(**{"question" if slot.startswith("question") else "watch": "unknown"})
    report = await CardWorkflowEvaluator(InsightEngine(judger)).evaluate(cases_for(reviewed), acceptance_outcomes=[Outcome.NOTIFY])
    assert report.acceptance_passed is advisory
    result = report.cases[0]
    evidence_slot = next(item for item in result.evidence_plan.slots if item.key == slot)
    assert evidence_slot.required is not advisory and evidence_slot.status == "pending"
    assert result.workflow.evidence_plan == result.evidence_plan
    assert result.question_results and result.watch_results
    assert result.outcome == (Outcome.NOTIFY if advisory else Outcome.INVESTIGATE)
    assert ("outcome_mismatch" in result.failure_reasons) is not advisory


async def test_endpoint_labels_change_scoring_and_label_digest_only():
    cases = cases_for()
    first_judger = SemanticDouble()
    first = await CardWorkflowEvaluator(InsightEngine(first_judger)).evaluate(cases, acceptance_outcomes=[Outcome.NOTIFY])
    cases[0].expected_delivery_destinations = {"owner": "LABEL_ONLY_SENTINEL"}
    second_judger = SemanticDouble()
    second = await CardWorkflowEvaluator(InsightEngine(second_judger)).evaluate(cases, acceptance_outcomes=[Outcome.NOTIFY])
    assert first.acceptance_passed is True and second.acceptance_passed is False
    assert first.input_digest == second.input_digest
    assert first.card_execution_digests == second.card_execution_digests
    assert first.label_digest != second.label_digest
    assert first_judger.states == second_judger.states
    assert "LABEL_ONLY_SENTINEL" not in json.dumps(second_judger.states)


async def test_ordinary_certification_remains_unassessed_and_legacy_reports_load():
    case = cases_for()[0]
    case.expected_delivery_method_keys = None
    case.expected_delivery_destinations = None
    report = await CardWorkflowEvaluator(InsightEngine(SemanticDouble())).evaluate([case])
    assert report.status == "approved"
    assert report.acceptance_outcomes is report.acceptance_passed is None
    assert report.card_execution_digests == {}
    payload = report.model_dump()
    for field in ("acceptance_outcomes", "acceptance_passed", "card_execution_digests"):
        del payload[field]
    assert CardEvaluationReport.model_validate(payload).acceptance_passed is None


async def test_runtime_failure_cannot_be_relaxed_and_is_diagnostic():
    class BrokenEngine:
        async def evaluate(self, *args, **kwargs):
            raise TimeoutError("offline simulated failure")

    report = await CardWorkflowEvaluator(BrokenEngine()).evaluate(
        cases_for(), acceptance_outcomes=[Outcome.NOTIFY],
        thresholds=CardEvaluationThresholds(max_error_rate=1),
    )
    assert report.status == "blocked" and report.acceptance_passed is False
    assert report.error_count == 3
    assert all(row.failure_reasons == ["runtime_error"] for row in report.cases)


@pytest.mark.parametrize("change", ["destination", "principal_id", "principal_tenant", "plan", "source", "policy", "requirement"])
def test_acceptance_digest_binds_all_executable_inputs(change):
    reviewed = card(questions=["What changed?"])
    original = card_acceptance_digest(reviewed)
    if change == "destination":
        reviewed.delivery_methods[0].destination += "changed"
    elif change in {"principal_id", "principal_tenant"}:
        setattr(reviewed, change, "another")
    elif change == "plan":
        reviewed.compiled_plan.selected_source_keys = []
    elif change == "source":
        reviewed.sources[0].parameters["scope"] = "other"
    elif change == "requirement":
        reviewed.evidence_requirements["question:1"] = False
    else:
        reviewed.decision_guidance += " Another rule."
    assert card_acceptance_digest(reviewed) != original


def test_acceptance_digest_excludes_only_approval_and_review_audit():
    reviewed = card()
    original = card_acceptance_digest(reviewed)
    reviewed = reviewed.model_copy(update={
        "status": InsightCardStatus.APPROVED, "approved_by": "reviewer",
        "approved_at": datetime.now(timezone.utc),
        "onboarding_review_history": [], "onboarding_corrections": [],
    })
    assert card_acceptance_digest(reviewed) == original

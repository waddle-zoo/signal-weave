"""Owner-required evidence is distinct from permitted corroborating context."""

import json

import pytest
from pydantic import ValidationError
from test_evaluation_acceptance import SemanticDouble, cases_for, snapshot

from signalweave.engine import InsightEngine
from signalweave.evaluation import CardEvaluationCase, CardWorkflowEvaluator
from signalweave.models import Outcome


def case_with_context(*, present=True, allowed=True):
    case = cases_for()[0]
    if present:
        extra = snapshot()
        extra.source_key = "context"
        extra.resource = "query:context"
        extra.observations = []
        case.resources.append(extra)
    if allowed:
        case.allowed_retrieval_refs = ["test|query:metric", "test|query:context"]
    return case


async def run(case, judger=None):
    return await CardWorkflowEvaluator(InsightEngine(judger or SemanticDouble())).evaluate(
        [case], acceptance_outcomes=[Outcome.NOTIFY],
    )


@pytest.mark.parametrize("present", [True, False])
async def test_explicit_optional_context_may_be_present_or_absent(present):
    result = await run(case_with_context(present=present))
    assert result.acceptance_passed is True
    assert result.retrieval_precision == result.retrieval_recall == 1
    assert result.cases[0].failure_reasons == []
    assert result.cases[0].expected_retrieval_refs == ["test|query:metric"]
    assert result.cases[0].allowed_retrieval_refs == ["test|query:metric", "test|query:context"]


@pytest.mark.parametrize("allowed", [None, ["test|query:metric"]])
async def test_unlisted_context_still_fails_including_legacy_default(allowed):
    case = case_with_context()
    case.allowed_retrieval_refs = allowed
    result = await run(case)
    assert result.acceptance_passed is False
    assert result.cases[0].unexpected_retrieval_refs == ["test|query:context"]


async def test_permissible_context_cannot_replace_missing_required_retrieval():
    case = case_with_context()
    case.expected_retrieval_refs.append("test|query:required-but-absent")
    case.allowed_retrieval_refs.append("test|query:required-but-absent")
    result = await run(case)
    assert result.acceptance_passed is False
    assert result.cases[0].missing_retrieval_refs == ["test|query:required-but-absent"]
    assert result.retrieval_precision == 1


async def test_optional_only_retrieval_has_no_missing_required_refs():
    case = case_with_context()
    case.expected_retrieval_refs = []
    result = await run(case)
    assert result.acceptance_passed is True
    assert result.retrieval_recall == 1


@pytest.mark.parametrize("allowed", [[], ["test|query:context"], ["test|query:metric"] * 2])
def test_allowlist_must_be_unique_and_include_all_required_refs(allowed):
    payload = case_with_context().model_dump()
    payload["allowed_retrieval_refs"] = allowed
    with pytest.raises(ValidationError):
        CardEvaluationCase.model_validate(payload)


async def test_labels_change_label_digest_not_jev_state_or_execution_digest():
    first, second = SemanticDouble(), SemanticDouble()
    original = case_with_context(present=False, allowed=False)
    permitted = original.model_copy(deep=True)
    permitted.allowed_retrieval_refs = ["test|query:metric", "test|query:context"]
    exact = await run(original, first)
    optional = await run(permitted, second)
    assert exact.input_digest == optional.input_digest
    assert exact.label_digest != optional.label_digest
    assert exact.card_execution_digests == optional.card_execution_digests
    assert first.states == second.states
    assert "allowed_retrieval_refs" not in json.dumps(second.states)


async def test_mcp_exposes_labels_and_rejects_bad_allowlist_before_inference(tmp_path):
    from test_workflow_label_presence import CountingJevDouble, setup, tool

    server, card_id, cases = await setup(tmp_path)
    judger = CountingJevDouble()
    server._test_runtime.engine.judger = judger
    spec = next(x for x in await server.list_tools() if x.name == "evaluate_card_workflow")
    assert "allowed_retrieval_refs" in spec.inputSchema["$defs"]["WorkflowCaseInput"]["properties"]
    cases[0]["allowed_retrieval_refs"] = []
    with pytest.raises(ValidationError, match="must include"):
        await tool(server, "evaluate_card_workflow")(card_id, cases)
    assert judger.judgments == 0
    cases[0]["allowed_retrieval_refs"] = cases[0]["expected_retrieval_refs"] + ["test|optional"]
    result = await tool(server, "evaluate_card_workflow")(
        card_id, cases, acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
    )
    assert result["acceptance_passed"] is True
    assert tool(server, "get_insight_card")(card_id)["status"] == "draft"


async def test_caller_authored_labels_are_not_independent_truth_or_card_approval(tmp_path):
    from test_mcp_acceptance import setup, tool

    server, card_id, cases = await setup(tmp_path)
    for case in cases:
        case["allowed_retrieval_refs"] = case["expected_retrieval_refs"]
        case["expected_retrieval_refs"] = []
    report = await tool(server, "evaluate_card_workflow")(
        card_id, cases, acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
    )
    # A caller can provide weak labels, just as it can provide incorrect expected
    # outcomes. A passing replay neither verifies those labels nor approves use.
    assert report["acceptance_passed"] is True
    assert all(row["expected_retrieval_refs"] == [] for row in report["cases"])
    assert tool(server, "get_insight_card")(card_id)["status"] == "draft"
    with pytest.raises(ValueError, match="approve it before evaluation"):
        await tool(server, "evaluate_insight_card")(card_id)

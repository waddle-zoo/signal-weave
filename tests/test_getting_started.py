"""Orientation is offline guidance, not a simulated Jev decision or user study."""

import json

import pytest

from signalweave.engine import InsightEngine
from signalweave.getting_started import agent_getting_started, getting_started
from signalweave.mcp_server import create_mcp
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteInsightCardStore, SQLiteMetricQueryCardStore


@pytest.mark.parametrize("task", ["start", "monitor"])
def test_agent_guide_distinguishes_bucket_arithmetic_from_comparable_changes(task):
    guide = agent_getting_started(task)
    assert any("Verify period coverage" in text and "beside the headline" in text
               and "currency" in text for text in guide["limits"])
    assert guide["inference_performed"] is False


@pytest.mark.parametrize("provider", ["jev-latest", "openai-decisions", "chatgpt-plan-responses"])
def test_recurring_agent_guide_uses_existing_card_bundle_without_repeating_onboarding(provider):
    guide = agent_getting_started("monitor", decision_provider=provider)
    assert [step["tool"] for step in guide["steps"]] == [
        "evaluate_insight_card", "get_insight_card", "get_decision_receipt",
    ]
    assert "Start here" in guide["steps"][0]["purpose"]
    assert "when needed" in guide["repeat"]
    assert "onboarding examples are not permanent date restrictions" in guide["repeat"]
    assert "explicit owner-requested fixed window" in guide["repeat"]
    assert "already in the packet" in guide["repeat"]
    assert "observation_facts" in guide["repeat"]
    assert "contradicts it" in guide["repeat"]
    assert "Omit context" in guide["optional_context"]
    assert "inside the context object" in guide["optional_context"]
    assert "unverified" in guide["optional_context"]
    assert guide["evaluation_example"] == {
        "card_id": "<approved-card-id>",
        "idempotency_key": "<card-id>:<run-id>",
        "response_mode": "compact",
    }
    assert guide["inference_performed"] is False
    assert "delivery" in guide["agent_owns"]


def test_first_use_guide_still_exposes_discovery_and_owner_approval():
    steps = {step["tool"] for step in agent_getting_started("start")["steps"]}
    assert {"search_catalog", "inspect_resource", "onboard_insight_card",
            "review_insight_card", "approve_insight_card"} <= steps


@pytest.mark.parametrize("task", ["start", "monitor"])
@pytest.mark.parametrize("provider", ["jev-latest", "openai-decisions", "chatgpt-plan-responses"])
def test_agent_guidance_distinguishes_replay_routes_and_bounded_delegation(task, provider):
    guide = agent_getting_started(task, decision_provider=provider)
    limits = " ".join(guide["limits"])
    assert "Without a notify route" in limits
    assert "does not authorize or send" in limits
    assert "historical measurement cutoff" in limits
    assert "separately reviewed archival card" in limits
    assert "preserving the current recurring card's freshness limit" in limits
    assert "does not make evidence current" in limits
    assert "explicitly delegate" in limits and "clarify conflicting approval language" in limits
    assert "does not grant new source access" in limits
    assert "conversation or caller-owned audit" in limits
    assert guide["inference_performed"] is False


def test_onboarding_verifies_the_actual_repeating_source_without_a_new_tool_or_gate():
    guide = agent_getting_started("start")
    limits = " ".join(guide["limits"])
    assert "exact proposed source parameters with inspect_resource" in limits
    assert "unfiltered inspection does not verify a filtered recurring source" in limits
    assert "actual analytical SQL and procedure in caller notes" in limits
    assert "Structural review alone does not demonstrate" in limits


@pytest.mark.parametrize("provider", ["jev-latest", "openai-decisions", "chatgpt-plan-responses"])
def test_first_readout_distinguishes_initial_answer_from_approved_recurring_demonstration(provider):
    guide = agent_getting_started("start", decision_provider=provider)
    readout = guide["first_readout"]
    assert "initial source-backed answer before recurring card setup or approval" in readout
    assert "When the owner requests recurrence and explicitly approves the reviewed card" in readout
    assert "first delivery-disabled evaluation as the recurring demonstration" in readout
    assert "If the person wants recurrence" in guide["next"]
    assert "Feedback is not new approval, scheduling or delivery permission" in readout
    assert "useful example is not proof of unattended reliability" in readout
    assert guide["inference_performed"] is False


def test_monitor_guide_explains_existing_publication_source_without_granting_authority():
    text = agent_getting_started("monitor")["analyst_publications"]
    assert "already an owner-approved source" in text
    assert "own authorized tools" in text and "grants no" in text
    assert "does not verify" in text and "label hypotheses" in text
    assert "not a trust relabel" in text


def test_monitor_guide_does_not_evaluate_an_unrefreshed_analyst_publication():
    guide = agent_getting_started("monitor")
    assert "saved BI or configured query sources" in guide["steps"][0]["purpose"]
    assert "refresh it through the authorized caller workflow first" in guide["steps"][0]["purpose"]
    assert "first rerun the retained queries/calculations" in guide["repeat"]
    assert "does not refresh its underlying analysis" in guide["repeat"]
    assert "old measurements is not a new business observation" in guide["repeat"]


@pytest.fixture
def server(tmp_path):
    class NoInference:
        name = "jev-forbidden-in-orientation"

        def __getattr__(self, name):
            raise AssertionError("Orientation must not request inference")

    class NoSourceAccess:
        name = "private-adapter-name-must-not-leak"

        async def list_resources(self):
            raise AssertionError("Orientation must not enumerate sources")

        async def inspect(self, source):
            raise AssertionError("Orientation must not inspect sources")

    sources = SourceRegistry([NoSourceAccess()])
    return create_mcp(Runtime(
        card_store=SQLiteInsightCardStore(tmp_path / "cards.db"),
        metric_query_store=SQLiteMetricQueryCardStore(tmp_path / "cards.db"),
        sources=sources, engine=InsightEngine(NoInference(), sources),
    ), profile="full")


@pytest.mark.parametrize("task", ["start", "query", "report", "monitor"])
async def test_guide_exposes_only_real_tools_without_source_or_model_calls(server, task):
    tools = {tool.name: tool for tool in await server.list_tools()}
    guide = tools["get_signalweave_guide"]
    assert guide.annotations.readOnlyHint
    assert guide.annotations.destructiveHint is False
    response = await server.call_tool("get_signalweave_guide", {"task": task})
    text = json.dumps(response, default=str)
    assert "private-adapter-name-must-not-leak" not in text
    result = getting_started(task)
    for step in result.get("steps", []):
        assert step["tool"] in tools
    assert "get_signalweave_guide" in server.instructions
    assert "Jev" in text and "TypeSafe" in text


def test_paths_keep_execution_and_approval_honest():
    query = getting_started("query")
    report = getting_started("report")
    monitor = getting_started("monitor")
    assert "Compilation is not execution" in query["human_handoff"]
    assert "typed metric_definitions" in query["needs"]
    assert "inspect_resource" not in [step["tool"] for step in query["steps"]]
    assert any("query-cost limits" in boundary for boundary in query["boundaries"])
    assert "reconciled comparison tables" in report["needs"]
    assert report["steps"][-1]["tool"] == "preview_investigation_report"
    assert not any(step["tool"].startswith("approve") for step in report["steps"])
    assert "does neither by itself" in monitor["human_handoff"]
    assert "missing-evidence" in monitor["needs"]
    assert [step["tool"] for step in monitor["steps"]].index("evaluate_card_workflow") < [
        step["tool"] for step in monitor["steps"]
    ].index("approve_insight_card")


async def test_unknown_path_is_rejected_by_mcp_schema(server):
    with pytest.raises(Exception, match="Input should be"):
        await server.call_tool("get_signalweave_guide", {"task": "run-all-company-tools"})


@pytest.mark.parametrize("task", ["report", "monitor"])
def test_preview_review_distinguishes_execution_from_behavioral_acceptance(task):
    review = getting_started(task)["preview_review"]
    assert "independently propose" in review["before_preview"]
    assert "Do not copy Jev's answer" in review["before_preview"]
    assert "execution, not correctness" in review["compare"]
    assert "Unknown required checks" in review["compare"]
    assert "not automatically fetched" in review["source_coverage"]
    assert "unless the owner requires" in review["source_coverage"]
    assert "including optional sources" in review["source_coverage"]
    assert "delivery-disabled current preview" in review["source_coverage"]
    assert "never lower confidence" in review["repair"]
    assert "comparison window is not a typed analytical comparison" in review["repair"]
    assert "inspected analytical_comparisons keys" in review["repair"]
    assert "capture_current_sources" in review["retest"]
    assert "newly returned card ID" in review["retest"]
    assert "does not replace the current preview or owner approval" in review["retest"]
    assert "do not stop at a passing evaluation" in review["retest"]
    assert "not independent historical acceptance" in review["retest"]


def test_behavioral_review_does_not_expand_query_or_start_paths():
    assert "preview_review" not in getting_started("query")
    assert "preview_review" not in getting_started("start")


@pytest.mark.parametrize("task", ["report", "monitor"])
def test_onboarding_preserves_policy_precedence_and_explicit_labels(task):
    guide = getting_started(task)
    assert any("preserve its wording" in text and "rule order" in text
               for text in guide["boundaries"])
    review = guide["preview_review"]
    assert "owner's original rules" in review["policy_fidelity"]
    assert "quiet branch" in review["policy_fidelity"]
    assert "data-repair instructions" in review["policy_fidelity"]
    assert "authorized directory" in review["policy_fidelity"]
    for field in ("expected_delivery_method_keys", "expected_delivery_destinations",
                  "required_evidence_source_keys", "expected_retrieval_refs"):
        assert field in review["historical_labels"]
    assert "omission means unassessed" in review["historical_labels"]
    assert "near-boundary and exception cases" in review["historical_labels"]
    assert "retain original capture timestamps" in review["historical_labels"]
    assert "does not test fetching" in review["historical_labels"]

import copy
import json

import pytest

from signalweave.mcp_server import create_mcp
from signalweave.models import DeliveryMethod
from signalweave.numeric_conditions import NumericCondition
from tests.test_onboarding import make_server, tool


async def _draft(server, *, source_parameters=None):
    source = {
        "key": "growth",
        "adapter": "superset",
        "resource": "dashboard:7",
        "label": "Growth overview",
    }
    if source_parameters is not None:
        source["parameters"] = source_parameters
    response = await tool(server, "draft_insight_card")(
        title="Compact response contract",
        what_to_watch="Checkout conversion and the evidence that explains a material movement.",
        why_watch="Help Growth decide whether to investigate a customer-impacting regression.",
        watch_for=["Conversion falls materially"],
        questions=["What changed and what evidence explains it?"],
        decision_guidance="Investigate when the evidence is incomplete; notify Growth Ops when corroborated.",
        sources=[source],
    )
    return response["card"]["id"]


async def test_compact_onboarding_retains_typed_review_facts_and_reduces_duplicate_payload(tmp_path):
    full_server = make_server(tmp_path / "full")
    compact_server = make_server(tmp_path / "compact")
    kwargs = {
        "goal": "Monitor checkout conversion and explain material movement.",
        "purpose": "Help Growth decide whether to investigate a customer-impacting regression.",
        "policy": "Investigate when evidence is incomplete; notify Growth Ops when corroborated.",
    }
    full = await tool(full_server, "bootstrap_insight_card")(**kwargs, response_mode="full")
    compact = await tool(compact_server, "bootstrap_insight_card")(**kwargs, response_mode="compact")

    assert len(json.dumps(compact)) < len(json.dumps(full)) * 0.75
    assert compact["response_mode"] == "compact"
    assert compact["details_available"] is True
    assert compact["review"]["selected_source_refs"] == full["review"]["selected_source_refs"]
    assert compact["review"]["discovery_receipt"] == full["review"]["discovery_receipt"]
    assert [item["ref"] for item in compact["review"]["source_candidates"]] == [
        item["ref"] for item in full["review"]["source_candidates"]
    ]
    assert compact["discovery"]["candidate_refs"] == full["discovery"]["candidate_refs"]
    assert compact["card"]["what_to_watch"] == full["card"]["what_to_watch"]
    assert compact["summary"]["what_to_watch"] == full["summary"]["what_to_watch"]
    assert "discovery" not in compact["summary"]
    assert "onboarding_review" not in compact["summary"]


async def test_bootstrap_defaults_to_compact_response_mode(tmp_path):
    server = make_server(tmp_path)
    response = await tool(server, "bootstrap_insight_card")(
        goal="Monitor checkout conversion and explain material movement.",
        purpose="Help Growth decide whether to investigate a customer-impacting regression.",
        policy="Investigate when evidence is incomplete; notify Growth Ops when corroborated.",
    )

    assert response["response_mode"] == "compact"


async def test_compact_review_and_simulation_keep_decision_boundary_and_structured_evidence(tmp_path):
    server = make_server(tmp_path)
    card_id = await _draft(server)

    full_review = await tool(server, "review_insight_card")(card_id, response_mode="full")
    compact_review = await tool(server, "review_insight_card")(card_id, response_mode="compact")
    assert compact_review["response_mode"] == "compact"
    assert compact_review["review"]["source_selection_fingerprint"] == full_review["review"]["source_selection_fingerprint"]
    assert compact_review["review"]["blockers"] == full_review["review"]["blockers"]
    assert [item["ref"] for item in compact_review["review"]["source_candidates"]] == [
        item["ref"] for item in full_review["review"]["source_candidates"]
    ]
    assert len(json.dumps(compact_review)) < len(json.dumps(full_review))

    full_preview = await tool(server, "simulate_insight_card")(
        card_id, response_mode="full"
    )
    compact_preview = await tool(server, "simulate_insight_card")(
        card_id, response_mode="compact"
    )
    assert compact_preview["response_mode"] == "compact"
    assert "report_markdown" not in compact_preview
    assert compact_preview["report_markdown_available"] is True
    full_result = dict(full_preview["result"])
    compact_result = dict(compact_preview["result"])
    for payload in (full_result, compact_result):
        payload.pop("evaluated_at", None)
        payload.pop("telemetry", None)
    assert compact_result == full_result
    full_report = dict(full_preview["report"])
    compact_report = dict(compact_preview["report"])
    full_report.pop("evaluated_at", None)
    compact_report.pop("evaluated_at", None)
    assert compact_report == full_report
    assert compact_preview["resources"][0]["source_key"] == full_preview["resources"][0]["source_key"]
    assert len(json.dumps(compact_preview)) < len(json.dumps(full_preview))


async def test_compact_evaluation_preserves_evidence_but_avoids_duplicate_handoff_payload(tmp_path):
    server = make_server(tmp_path)
    card_id = await _draft(server)
    for _ in range(3):
        await tool(server, "review_insight_card")(card_id)
    await tool(server, "simulate_insight_card")(card_id)
    await tool(server, "approve_insight_card")(card_id)

    full = await tool(server, "evaluate_insight_card")(
        card_id, idempotency_key="full-handoff", response_mode="full"
    )
    agent_server = create_mcp(server._test_runtime, profile="agent")
    compact = await tool(agent_server, "evaluate_insight_card")(
        card_id, idempotency_key="compact-handoff"
    )
    durable = await tool(agent_server, "get_decision_receipt")(
        idempotency_key="compact-handoff"
    )

    expected = dict(durable["result"])
    expected.pop("report_markdown", None)
    assert compact["response_mode"] == "compact"
    assert compact["optional_policy_diagnostics"]["values"] == {
        field: expected[field] for field in ("watch_results", "question_results")
    }
    reconstructed = copy.deepcopy(compact["result"])
    report = reconstructed["report"]
    assert report["full_report_ref"] == {"result_path": ["report"]}
    assert report["evidence_ref"] == {"result_path": ["evidence"]}
    for field in ("numeric_claims", "blockers", "warnings", "coverage", "source_boundaries",
                  "provenance", "unresolved_questions", "numeric_conditions", "status"):
        assert report[field] == expected["report"][field]
    recovered = await tool(agent_server, "get_decision_receipt")(
        idempotency_key="compact-handoff", result_path=report["full_report_ref"]["result_path"],
        limit=100,
    )
    assert {entry["key"]: entry["value"] for entry in recovered["result_page"]["items"]} == expected["report"]
    reconstructed["report"] = expected["report"]
    parent = reconstructed["workflow"]
    assert parent.pop("evidence_plan_ref") == {"result_path": ["evidence_plan"]}
    parent["evidence_plan"] = reconstructed["evidence_plan"]
    assert {**reconstructed, **compact["optional_policy_diagnostics"]["values"]} == expected
    assert compact["result"]["evidence"]
    assert compact["result"]["report"]
    assert "report_markdown" not in compact["result"]
    assert "resources" not in compact
    assert "plan" not in compact
    assert len(json.dumps(compact)) < len(json.dumps(full)) * 0.75


@pytest.mark.parametrize("parent,field", [("report", "evidence"), ("workflow", "evidence_plan")])
@pytest.mark.parametrize("nested", [[], [{"id": "different"}], None, "not-a-section"])
def test_compact_does_not_coalesce_distinct_or_invalid_sections(parent, field, nested):
    from signalweave.mcp_server import _compact_evaluation_response

    response = {"result": {field: [{"id": "canonical"}], parent: {field: nested}}}
    original = copy.deepcopy(response)
    compact = _compact_evaluation_response(response)
    assert compact["result"][parent][field] == nested
    assert f"{field}_ref" not in compact["result"][parent]
    assert response == original


def test_compact_duplicate_references_preserve_facts_source_and_nonduplicates():
    from signalweave.mcp_server import _compact_evaluation_response

    evidence = [{"id": "e-1", "value": 12, "source_key": "source-a", "note": "x" * 4096}]
    plan = {"slots": [{"key": "q-1", "source_keys": ["source-a"]}], "version": 1}
    response = {"result": {"evidence": evidence, "evidence_plan": plan,
                           "report": {"evidence": copy.deepcopy(evidence), "warnings": ["coverage unknown"]},
                           "workflow": {"evidence_plan": copy.deepcopy(plan), "instructions": "Follow up"}}}
    original = copy.deepcopy(response)
    compact = _compact_evaluation_response(response)
    result = compact["result"]
    assert result["evidence"] == evidence
    assert result["evidence_plan"] == plan
    assert result["report"] == {"evidence_ref": {"result_path": ["evidence"]}, "warnings": ["coverage unknown"]}
    assert result["workflow"] == {"evidence_plan_ref": {"result_path": ["evidence_plan"]}, "instructions": "Follow up"}
    assert response == original
    assert len(json.dumps(compact)) < len(json.dumps(response))


def test_compact_preserves_existing_nested_reference_without_overwriting():
    from signalweave.mcp_server import _compact_evaluation_response

    response = {"result": {"evidence": [], "report": {"evidence": [], "evidence_ref": {"result_path": ["other"]}}}}
    assert _compact_evaluation_response(response)["result"]["report"] == response["result"]["report"]


@pytest.mark.parametrize("nested,canonical", [([True], [1]), ([1.0], [1]), ([{"a": False}], [{"a": 0}])])
def test_compact_requires_json_typed_equality_not_python_numeric_equality(nested, canonical):
    from signalweave.mcp_server import _compact_evaluation_response

    response = {"result": {"evidence": canonical, "report": {"evidence": nested}}}
    result = _compact_evaluation_response(response)["result"]
    assert "evidence_ref" not in result["report"]
    assert json.dumps(result["report"]["evidence"]) == json.dumps(nested)


def _publication_report_packet():
    from signalweave.models import Evidence, InsightCard, InsightResult, ResourceSnapshot
    from signalweave.reporting import build_investigation_report

    policy = InsightCard(id="activity", title="Activity check", what_to_watch="Completed activity",
                         why_watch="Apply the owner's rule", comparison_windows=[],
                         sources=[{"key": "activity", "adapter": "mcp", "resource": "query:activity", "label": "Activity"}])
    evidence = Evidence(source_key="activity", statement="Caller-calculated activity from the source query.",
                        values={"current": 12, "prior": 10, "unit": "count"}, provenance=["query:activity"])
    source = ResourceSnapshot(source_key="activity", adapter="mcp", resource="query:activity",
                              title="Activity", evidence=[evidence])
    result = InsightResult(card_id=policy.id, outcome="ignore", summary="Quiet", rationale="Owner policy", evaluator="fixture",
                           evidence=[evidence], source_keys=["activity"],
                           evidence_plan={"objective": "Activity", "slots": [], "status": "complete"})
    report = build_investigation_report(policy, result, [source])
    return {"receipt": {"receipt_id": "receipt-activity"}, "card": policy.model_dump(mode="json"),
            "result": {**result.model_dump(mode="json"), "report": report.model_dump(mode="json")}}


def test_compact_report_does_not_confuse_no_engine_comparisons_with_no_source_measurements():
    from signalweave.mcp_server import _compact_evaluation_response

    packet = _publication_report_packet()
    original = copy.deepcopy(packet)
    report = packet["result"]["report"]
    assert report["numeric_claims"] == []
    assert "No engine-computed comparison claims were produced; inspect source evidence for any source-provided measurements." in report["limitations"]
    compact = _compact_evaluation_response(packet)["result"]
    assert compact["evidence"] == original["result"]["evidence"]
    assert compact["report"]["limitations"] == []
    assert compact["report"]["numeric_claims"] == []
    assert compact["report"]["status"] == report["status"]
    assert "separate analysis" in compact["report"]["checks_scope"]
    assert compact["report"]["full_report_ref"] == {"result_path": ["report"]}
    assert "title" not in compact["report"] and "purpose" not in compact["report"]
    assert packet == original


def test_compact_report_preserves_failed_comparisons_unique_evidence_and_unfamiliar_checks():
    from signalweave.mcp_server import _compact_evaluation_response

    packet = _publication_report_packet()
    report = packet["result"]["report"]
    packet["result"]["analyses"] = [{"status": "failed", "issues": ["Missing denominator"]}]
    report.update(status="blocked", blockers=[{"code": "required_analysis_failed", "message": "Missing denominator"}],
                  warnings=["Required window is incomplete"], unresolved_questions=["Reconcile the denominator"],
                  numeric_conditions=[{"key": "bound-check", "status": "unknown"}],
                  numeric_claims=[{"value": 12, "provisional": True}],
                  future_check={"status": "unresolved"}, title="Unique report title",
                  evidence=[{"source_key": "activity", "statement": "Report-specific evidence"}])
    dynamic = "No validated quantitative analysis was available for this report. Required input is missing."
    report["limitations"].append(dynamic)
    original = copy.deepcopy(packet)
    actual = _compact_evaluation_response(packet)["result"]
    for field in ("status", "blockers", "warnings", "unresolved_questions", "numeric_conditions",
                  "numeric_claims", "future_check", "title", "evidence"):
        assert actual["report"][field] == original["result"]["report"][field]
    assert actual["report"]["limitations"] == [dynamic]
    assert actual["analyses"] == packet["result"]["analyses"]
    assert "evidence_ref" not in actual["report"]
    assert packet == original


def test_large_generated_checks_are_explicitly_paged_to_the_untouched_report():
    from signalweave.mcp_server import _compact_evaluation_response, _receipt_result_page

    packet = _publication_report_packet()
    packet["result"]["report"]["warnings"] = [f"Material source warning {i}: " + "x" * 500 for i in range(200)]
    original = copy.deepcopy(packet)
    compact = _compact_evaluation_response(packet)
    assert "report" not in compact["result"]
    assert compact["evidence_access"]["complete"] is False
    assert any(section["path"] == ["report"] for section in compact["evidence_access"]["available_sections"])
    page = _receipt_result_page(packet["result"], ["report", "warnings"], 0, 25)
    assert page["items"] == original["result"]["report"]["warnings"][:25]
    assert page["has_more"]
    assert packet == original


def test_unknown_or_already_scoped_report_metadata_is_not_replaced():
    from signalweave.mcp_server import _compact_evaluation_response

    for extra in ({"status": {"legacy": True}}, {"checks_scope": "Legacy unique scope"},
                  {"full_report_ref": {"result_path": ["other"]}}):
        packet = _publication_report_packet()
        packet["result"]["report"].update(extra)
        result = _compact_evaluation_response(packet)["result"]["report"]
        for field, value in extra.items():
            assert result[field] == value


async def test_compact_card_read_keeps_latest_review_and_full_read_keeps_legacy_shape(tmp_path):
    server = make_server(tmp_path)
    card_id = await _draft(server)
    await tool(server, "review_insight_card")(card_id)

    full = tool(server, "get_insight_card")(card_id)
    compact = tool(server, "get_insight_card")(card_id, response_mode="compact")
    assert "onboarding_review" in compact
    assert compact["onboarding_review"]["source_selection_fingerprint"] == full["onboarding_review"]["source_selection_fingerprint"]
    assert compact["response_mode"] == "compact"
    assert "response_mode" not in full
    assert "details_available" not in full


async def test_agent_default_compact_approved_card_preserves_policy_and_full_audit(tmp_path):
    server = make_server(tmp_path)
    card_id = await _draft(
        server,
        source_parameters={"dashboard_filters": {"region": "west"}, "saved_query": "sales-v3"},
    )
    for _ in range(3):
        await tool(server, "review_insight_card")(card_id)
    await tool(server, "simulate_insight_card")(card_id)
    approved = await tool(server, "approve_insight_card")(card_id)
    assert approved["status"] == "approved"
    stored_card = server._test_runtime.card_store.get_card(card_id)
    source = stored_card.sources[0].model_copy(
        update={"required_comparison_keys": ["growth-total"]}
    )
    server._test_runtime.card_store.save_card(stored_card.model_copy(update={
        "sources": [source],
        "numeric_conditions": [NumericCondition(
            text="Growth total increased.",
            source_key="growth",
            comparison_key="growth-total",
            measurement="delta",
            unit="USD",
            threshold=0,
            comparator=">",
        )],
        "delivery_methods": [DeliveryMethod(
            key="growth-ops",
            outcome="notify",
            label="Growth Ops",
            destination="slack://growth-ops",
        )],
    }))

    agent_server = create_mcp(server._test_runtime, profile="agent")
    full_schema = next(spec for spec in await server.list_tools() if spec.name == "get_insight_card")
    agent_schema = next(spec for spec in await agent_server.list_tools() if spec.name == "get_insight_card")
    assert full_schema.inputSchema["properties"]["response_mode"]["default"] == "full"
    assert agent_schema.inputSchema["properties"]["response_mode"]["default"] == "compact"

    full = tool(server, "get_insight_card")(card_id)
    compact = tool(agent_server, "get_insight_card")(card_id)
    explicit_full = tool(agent_server, "get_insight_card")(card_id, response_mode="full")

    assert full["onboarding_review"]["source_candidates"]
    assert "onboarding_review" not in compact
    assert explicit_full == full
    assert compact["response_mode"] == "compact"
    assert compact["details_available"] is True
    preserved_fields = (
        "id",
        "title",
        "what_to_watch",
        "why_watch",
        "watch_for",
        "questions",
        "numeric_conditions",
        "evidence_requirements",
        "decision_guidance",
        "follow_up_guidance",
        "sources",
        "comparison_windows",
        "action_confidence_threshold",
        "owner",
        "version",
        "max_source_age_hours",
        "delivery_methods",
        "retrieval_mode",
        "investigation_mode",
        "max_investigation_sources",
        "investigation_threshold",
        "principal_id",
        "principal_tenant",
        "status",
        "approved_by",
        "approved_at",
    )
    assert all(compact[field] == full[field] for field in preserved_fields)
    assert compact["sources"][0]["parameters"] == {
        "dashboard_filters": {"region": "west"},
        "saved_query": "sales-v3",
    }
    assert compact["numeric_conditions"]
    assert compact["delivery_methods"]
    assert len(json.dumps(compact)) < len(json.dumps(full))

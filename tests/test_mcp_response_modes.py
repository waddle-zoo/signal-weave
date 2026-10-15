import json

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
    compact = await tool(server, "evaluate_insight_card")(
        card_id, idempotency_key="compact-handoff", response_mode="compact"
    )
    durable = await tool(server, "get_decision_receipt")(
        idempotency_key="compact-handoff"
    )

    expected = dict(durable["result"])
    expected.pop("report_markdown", None)
    assert compact["response_mode"] == "compact"
    assert compact["optional_policy_diagnostics"]["values"] == {
        field: expected[field] for field in ("watch_results", "question_results")
    }
    assert {**compact["result"], **compact["optional_policy_diagnostics"]["values"]} == expected
    assert compact["result"]["evidence"]
    assert compact["result"]["report"]
    assert "report_markdown" not in compact["result"]
    assert "resources" not in compact
    assert "plan" not in compact
    assert len(json.dumps(compact)) < len(json.dumps(full)) * 0.75


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

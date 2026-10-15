"""Current-source acceptance input is a bounded convenience, not certification."""
import pytest
from test_mcp_acceptance import setup
from test_onboarding import tool


async def test_current_capture_uses_stored_source_identity_and_still_requires_labels(tmp_path):
    server, card_id, _ = await setup(tmp_path)
    result = await tool(server, "evaluate_card_workflow")(card_id, [{
        "id": "owner-current-example", "capture_current_sources": True,
        "expected_outcome": "notify", "expected_delivery_method_keys": ["owner"],
        "expected_delivery_destinations": {"owner": "sink:opaque"},
        "required_evidence_source_keys": ["growth"],
        "expected_retrieval_refs": ["superset|dashboard:7"],
    }])
    assert result["outcome_accuracy"] == 1
    assert result["acceptance_passed"] is None
    assert result["status"] == "shadow"
    assert result["current_source_case_ids"] == ["owner-current-example"]
    assert tool(server, "get_insight_card")(card_id)["status"] == "draft"
    assert result["cases"][0]["actual_evidence_source_keys"] == ["growth"]


@pytest.mark.parametrize("case", [
    {"id": "no-evidence-choice", "expected_outcome": "ignore"},
    {"id": "both", "expected_outcome": "ignore", "capture_current_sources": True, "resources": []},
    {"id": "refs-not-snapshots", "expected_outcome": "ignore", "resources": ["superset|dashboard:7"]},
    {"id": "invented-card", "expected_outcome": "ignore", "resources": [], "card": {}},
    {"id": "coercion", "expected_outcome": "ignore", "capture_current_sources": "true"},
])
async def test_malformed_cases_fail_before_source_fetch_or_judgment(tmp_path, case):
    server, card_id, _ = await setup(tmp_path)
    async def forbidden(*args, **kwargs):
        raise AssertionError("must validate before querying or inference")
    server._test_runtime.sources.resolve = forbidden
    server._test_runtime.engine.evaluate = forbidden
    with pytest.raises(ValueError):
        await tool(server, "evaluate_card_workflow")(card_id, [case])


async def test_current_capture_cannot_fabricate_multiple_historical_periods(tmp_path):
    server, card_id, _ = await setup(tmp_path)
    cases = [{"id": name, "expected_outcome": outcome, "capture_current_sources": True}
             for name, outcome in [("quiet", "ignore"), ("event", "notify")]]
    with pytest.raises(ValueError, match="At most one"):
        await tool(server, "evaluate_card_workflow")(card_id, cases)


@pytest.mark.parametrize("outcomes", [["notify"], ["ignore", "notify", "insufficient_data"], []])
async def test_current_capture_cannot_certify_before_any_source_query(tmp_path, outcomes):
    server, card_id, _ = await setup(tmp_path)
    async def forbidden(*args, **kwargs):
        raise AssertionError("current capture cannot be acceptance")
    server._test_runtime.sources.resolve = forbidden
    with pytest.raises(ValueError, match="shadow check, not acceptance"):
        await tool(server, "evaluate_card_workflow")(card_id, [{
            "id": "current", "capture_current_sources": True, "expected_outcome": "notify",
        }], acceptance_outcomes=outcomes)


async def test_foreign_historical_case_prevents_any_current_capture(tmp_path):
    server, card_id, cases = await setup(tmp_path)
    cases[0]["resources"][0]["contract"]["tenant_id"] = "other-tenant"
    async def forbidden(*args, **kwargs):
        raise AssertionError("authorization must precede current capture")
    server._test_runtime.sources.resolve = forbidden
    with pytest.raises(ValueError, match="outside the authenticated principal"):
        await tool(server, "evaluate_card_workflow")(card_id, [
            {"id": "current", "expected_outcome": "notify", "capture_current_sources": True}, cases[0],
        ])


async def test_current_capture_rechecks_returned_snapshot_tenant(tmp_path):
    server, card_id, cases = await setup(tmp_path)
    from signalweave.models import ResourceSnapshot
    foreign = ResourceSnapshot.model_validate(cases[0]["resources"][0])
    foreign.contract.tenant_id = "other-tenant"
    async def wrong_tenant(*args, **kwargs):
        return [foreign]
    server._test_runtime.sources.resolve = wrong_tenant
    with pytest.raises(ValueError, match="outside the authenticated principal"):
        await tool(server, "evaluate_card_workflow")(card_id, [{
            "id": "current", "expected_outcome": "notify", "capture_current_sources": True,
        }])


async def test_mcp_schema_exposes_snapshot_and_label_shape(tmp_path):
    server, _, _ = await setup(tmp_path)
    schema = next(t.inputSchema for t in await server.list_tools() if t.name == "evaluate_card_workflow")
    definition = schema["$defs"]["WorkflowCaseInput"]
    assert "expected_outcome" in definition["required"]
    assert "capture_current_sources" in definition["properties"]
    assert "ResourceSnapshot" in schema["$defs"]
    assert definition["additionalProperties"] is False

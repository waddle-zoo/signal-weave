"""Keep a reviewed calculation on its card without hidden source activation."""
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from signalweave.mcp_server import create_mcp
from signalweave.models import InsightCard, InsightCardStatus
from tests.test_card_revision_mcp import (
    CARD_ID,
    assert_no_source_or_model_calls,
    revise,
    setup_server,
)
from tests.test_source_selection_approval import (
    REASON,
    ScopedSupersetCatalogDouble,
    reviewed_case,
    stored,
    tool,
)


@pytest.mark.parametrize("sqlite", [False, True], ids=["json", "sqlite"])
async def test_normal_profile_can_replace_sources_and_clear_age_on_the_same_card(tmp_path, sqlite):
    _, runtime, before, catalog, judger = setup_server(tmp_path, sqlite=sqlite)
    server = create_mcp(runtime, profile="agent")
    source = {"key": "sales", "adapter": "superset", "resource": "dashboard:9",
              "label": "Replacement reviewed measure", "parameters": {"region": "west"}}
    result = await revise(server, changes={"sources": [source], "max_source_age_hours": None})
    after = runtime.card_store.get_card(CARD_ID)
    assert after.id == before.id and after.version == before.version+1
    assert after.status is InsightCardStatus.DRAFT
    assert after.max_source_age_hours is None
    assert len(after.sources) == 1 and after.sources[0].resource == "dashboard:9"
    assert after.sources[0].parameters == {"region": "west"}
    assert after.context_bindings == before.context_bindings
    assert after.onboarding_review_history == before.onboarding_review_history
    assert after.approved_by is after.approved_at is after.compiled_plan is after.onboarding_review is None
    assert result["approval_required"] and not result["delivery_enabled"]
    assert_no_source_or_model_calls(catalog, judger)
    with pytest.raises(ToolError, match="draft"):
        await server.call_tool("evaluate_insight_card", {"card_id": CARD_ID, "idempotency_key": "unapproved-new-source"})
    with pytest.raises(ToolError, match="version"):
        await revise(server, changes={"max_source_age_hours": 12})
    assert runtime.card_store.get_card(CARD_ID) == after


@pytest.mark.parametrize("age", [None, 0, 6, 168])
async def test_freshness_revision_preserves_sources_and_omission_preserves_age(tmp_path, age):
    server, runtime, before, catalog, judger = setup_server(tmp_path)
    await revise(server, changes={"max_source_age_hours": age})
    updated = runtime.card_store.get_card(CARD_ID)
    assert updated.max_source_age_hours == age and updated.sources == before.sources
    await revise(server, version=updated.version, changes={"title": "New owner-facing title"})
    assert runtime.card_store.get_card(CARD_ID).max_source_age_hours == age
    assert_no_source_or_model_calls(catalog, judger)


@pytest.mark.parametrize("changes", [
    {"sources": []}, {"sources": None}, {"sources": {}},
    {"sources": [{"key": "measure", "adapter": "superset"}]},
    {"max_source_age_hours": -1}, {"max_source_age_hours": 876001},
    {"max_source_age_hours": "not-an-age"},
])
async def test_invalid_replacement_is_atomic(tmp_path, changes):
    server, runtime, before, catalog, judger = setup_server(tmp_path)
    with pytest.raises(ToolError):
        await revise(server, changes=changes)
    assert runtime.card_store.get_card(CARD_ID) == before
    assert_no_source_or_model_calls(catalog, judger)


async def test_replacement_rebinds_existing_numeric_requirements(tmp_path):
    server, runtime, before, catalog, judger = setup_server(tmp_path)
    condition = {"text": "A supported decline", "source_key": "sales",
                 "comparison_key": "net_sales_previous_week", "measurement": "change_pct",
                 "unit": "percent", "threshold": -5, "comparator": "<="}
    before = InsightCard.model_validate({**before.model_dump(mode="json"), "numeric_conditions": [condition]})
    runtime.card_store.save_card(before)
    replacement = {"key": "sales", "adapter": "superset", "resource": "dashboard:9", "label": "Replacement"}
    await revise(server, changes={"sources": [replacement]})
    after = runtime.card_store.get_card(CARD_ID)
    assert after.numeric_conditions == before.numeric_conditions
    assert after.sources[0].required_comparison_keys == ["net_sales_previous_week"]
    assert_no_source_or_model_calls(catalog, judger)
    with pytest.raises(ToolError, match="source_key"):
        await revise(server, version=after.version, changes={"sources": [
            {"key": "different-local-key", "adapter": "superset", "resource": "dashboard:9", "label": "Other"}]})
    assert runtime.card_store.get_card(CARD_ID) == after
    assert_no_source_or_model_calls(catalog, judger)


@pytest.mark.parametrize("change", ["sources", "max_source_age_hours"])
async def test_old_confirmation_cannot_approve_revised_source_or_freshness(tmp_path, change):
    server, card_id, _, _, _ = await reviewed_case(
        tmp_path, catalog=ScopedSupersetCatalogDouble(), retrieval_mode="fixed")
    shown = await tool(server, "review_insight_card")(card_id)
    old_args = shown["approval_handoff"]["arguments_after_owner_confirmation"]
    card = stored(server, card_id)
    changes = ({"sources": [{"key": "checkout", "adapter": "superset", "resource": "dashboard:8", "label": "Replacement"}]}
               if change == "sources" else {"max_source_age_hours": None})
    await revise(server, card_id=card_id, version=card["version"], changes=changes)
    await tool(server, "review_insight_card")(card_id)
    with pytest.raises(ValueError, match="stale|fingerprint|changed"):
        await tool(server, "approve_insight_card")(**old_args, source_selection_reason=REASON)
    assert stored(server, card_id)["status"] == "draft"

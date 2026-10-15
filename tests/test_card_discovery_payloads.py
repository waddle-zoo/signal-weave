from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from signalweave.mcp_server import create_mcp
from signalweave.models import InsightCardStatus
from tests.test_card_revision_mcp import (
    CARD_ID,
    CARD_VERSION,
    assert_no_source_or_model_calls,
    reviewed_card,
    setup_server,
)
from tests.test_local_investigation import make_runtime

SUMMARY_KEYS = {
    "id",
    "title",
    "owner",
    "status",
    "version",
    "source_count",
    "context_binding_count",
}


def _card_for_listing(card_id, *, status=InsightCardStatus.APPROVED, tenant="default"):
    card = reviewed_card(status=status)
    review = card.onboarding_review
    receipt = review.discovery_receipt.model_copy(
        update={"principal_tenant": tenant}
    )
    review = review.model_copy(
        update={"card_id": card_id, "principal_tenant": tenant, "discovery_receipt": receipt}
    )
    history = [entry.model_copy(update={"card_id": card_id}) for entry in card.onboarding_review_history]
    corrections = [entry.model_copy(update={"card_id": card_id}) for entry in card.onboarding_corrections]
    plan = card.compiled_plan.model_copy(update={"card_id": card_id})
    return card.model_copy(
        update={
            "id": card_id,
            "title": f"Title for {card_id}",
            "status": status,
            "principal_tenant": tenant,
            "approved_by": "growth-owner" if status is InsightCardStatus.APPROVED else None,
            "approved_at": card.approved_at if status is InsightCardStatus.APPROVED else None,
            "compiled_plan": plan,
            "onboarding_review": review,
            "onboarding_review_history": history,
            "onboarding_corrections": corrections,
        }
    )


async def _list(server, **arguments):
    _, result = await server.call_tool("list_insight_cards", arguments)
    return result


async def test_listing_pages_more_than_default_limit_in_stable_id_order(tmp_path):
    server, runtime, _, catalog, judger = setup_server(tmp_path)
    ids = [f"card-{index:02d}" for index in range(33)]
    for card_id in reversed(ids):
        runtime.card_store.save_card(_card_for_listing(card_id))
    expected_ids = sorted([*ids, CARD_ID])

    traversed_ids = []
    offset = 0
    while True:
        page = await _list(server, offset=offset, limit=8)
        page_ids = [card["id"] for card in page["cards"]]
        traversed_ids.extend(page_ids)

        assert page["count"] == len(expected_ids)
        assert page["returned_count"] == len(page_ids)
        assert page["offset"] == offset
        assert page["limit"] == 8
        assert page["response_mode"] == "full"  # setup_server uses the full profile
        assert page["details_available"] is True
        assert page["has_more"] is (offset + len(page_ids) < len(expected_ids))
        assert page["next_offset"] == (
            offset + len(page_ids) if page["has_more"] else None
        )
        if not page["has_more"]:
            break
        offset = page["next_offset"]

    assert traversed_ids == expected_ids
    assert len(traversed_ids) == len(set(traversed_ids))
    assert_no_source_or_model_calls(catalog, judger)


async def test_authorization_and_status_filters_precede_count_and_offset(tmp_path):
    server, runtime, _, catalog, judger = setup_server(tmp_path)
    for card_id, status, tenant in [
        ("a-approved", InsightCardStatus.APPROVED, "default"),
        ("b-approved", InsightCardStatus.APPROVED, "default"),
        ("a-draft", InsightCardStatus.DRAFT, "default"),
        ("0-other-tenant", InsightCardStatus.APPROVED, "tenant-b"),
    ]:
        runtime.card_store.save_card(_card_for_listing(card_id, status=status, tenant=tenant))

    page = await _list(server, status="approved", offset=1, limit=1)

    assert page["count"] == 3
    assert page["returned_count"] == 1
    assert page["offset"] == 1
    assert page["cards"][0]["id"] == "b-approved"
    assert page["has_more"] is True
    assert page["next_offset"] == 2
    assert "0-other-tenant" not in [card["id"] for card in page["cards"]]
    assert_no_source_or_model_calls(catalog, judger)


@pytest.mark.parametrize(
    "arguments",
    [
        {"offset": -1},
        {"offset": True},
        {"offset": False},
        {"offset": 1.5},
        {"offset": "1"},
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"limit": False},
        {"limit": 2.5},
        {"limit": "2"},
        {"response_mode": "summary"},
        {"status": "archived"},
    ],
    ids=[
        "negative-offset",
        "true-offset-is-not-int",
        "false-offset-is-not-int",
        "fractional-offset",
        "string-offset",
        "zero-limit",
        "limit-over-maximum",
        "true-limit-is-not-int",
        "false-limit-is-not-int",
        "fractional-limit",
        "string-limit",
        "invalid-response-mode",
        "invalid-status",
    ],
)
async def test_listing_rejects_invalid_pagination_and_filter_arguments(tmp_path, arguments):
    server, _, _, _, _ = setup_server(tmp_path)
    with pytest.raises(ToolError):
        await _list(server, **arguments)


async def test_profile_defaults_and_explicit_full_mode_preserve_exact_card_json(tmp_path):
    full_server, runtime, card, catalog, judger = setup_server(tmp_path)
    agent_server = create_mcp(runtime, profile="agent")
    stored_json = card.model_dump(mode="json")

    agent_default = await _list(agent_server)
    full_default = await _list(full_server)
    agent_full = await _list(agent_server, response_mode="full")
    full_compact = await _list(full_server, response_mode="compact")

    assert agent_default["response_mode"] == "compact"
    assert set(agent_default["cards"][0]) == SUMMARY_KEYS
    assert agent_default["cards"][0] == {
        "id": CARD_ID,
        "title": card.title,
        "owner": card.owner,
        "status": card.status.value,
        "version": card.version,
        "source_count": len(card.sources),
        "context_binding_count": len(card.context_bindings),
    }
    assert full_default["response_mode"] == "full"
    assert full_default["cards"] == [stored_json]
    assert agent_full["response_mode"] == "full"
    assert agent_full["cards"] == [stored_json]
    assert full_compact["response_mode"] == "compact"
    assert set(full_compact["cards"][0]) == SUMMARY_KEYS
    for result in (agent_default, full_default, agent_full, full_compact):
        assert result["count"] == result["returned_count"] == 1
        assert result["offset"] == 0
        assert result["limit"] == 25
        assert result["has_more"] is False
        assert result["next_offset"] is None
        assert result["details_available"] is True
    assert_no_source_or_model_calls(catalog, judger)


async def test_revision_compact_receipt_keeps_active_fields_and_full_keeps_history(tmp_path):
    full_server, runtime, before, catalog, judger = setup_server(tmp_path)
    agent_server = create_mcp(runtime, profile="agent")

    _, compact_result = await agent_server.call_tool(
        "revise_insight_card",
        {
            "card_id": CARD_ID,
            "expected_card_version": CARD_VERSION,
            "changes": {"title": "Weekly sales change"},
            "reason": "Owner clarified the title.",
        },
    )
    first_revision = runtime.card_store.get_card(CARD_ID)
    expected_compact = first_revision.model_dump(mode="json")
    expected_compact.pop("onboarding_review_history")
    expected_compact.pop("onboarding_corrections")

    assert compact_result["response_mode"] == "compact"
    assert compact_result["card"] == expected_compact
    assert compact_result["card"]["version"] == before.version + 1
    assert compact_result["card"]["status"] == "draft"
    assert compact_result["card"]["title"] == "Weekly sales change"
    assert compact_result["card"]["decision_guidance"] == before.decision_guidance
    assert compact_result["card"]["watch_for"] == before.watch_for
    assert compact_result["card"]["questions"] == before.questions
    assert compact_result["card"]["sources"] == [
        source.model_dump(mode="json") for source in before.sources
    ]
    assert compact_result["card"]["context_bindings"] == [
        binding.model_dump(mode="json") for binding in before.context_bindings
    ]
    assert "onboarding_review_history" not in compact_result["card"]
    assert "onboarding_corrections" not in compact_result["card"]
    assert compact_result["details_available"] is True

    _, full_result = await agent_server.call_tool(
        "revise_insight_card",
        {
            "card_id": CARD_ID,
            "expected_card_version": first_revision.version,
            "changes": {"why_watch": "Support the weekly growth review."},
            "reason": "Owner clarified the purpose.",
            "response_mode": "full",
        },
    )
    second_revision = runtime.card_store.get_card(CARD_ID)

    assert full_result["response_mode"] == "full"
    assert full_result["card"] == second_revision.model_dump(mode="json")
    assert len(full_result["card"]["onboarding_review_history"]) == len(
        before.onboarding_review_history
    )
    assert len(full_result["card"]["onboarding_corrections"]) == len(
        before.onboarding_corrections
    ) + 2
    assert full_result["details_available"] is True
    assert_no_source_or_model_calls(catalog, judger)


async def test_large_stored_history_is_omitted_from_compact_listing_with_byte_reduction(tmp_path):
    server, runtime, card, catalog, judger = setup_server(tmp_path)
    large_history = [
        card.onboarding_corrections[0].model_copy(
            update={
                "correction_id": f"stored-history-{index}",
                "card_version": index + 1,
                "note": f"Historical owner clarification {index}: " + ("x" * 1200),
            }
        )
        for index in range(100)
    ]
    card_with_history = card.model_copy(update={"onboarding_corrections": large_history})
    runtime.card_store.save_card(card_with_history)
    agent_server = create_mcp(runtime, profile="agent")

    compact = await _list(agent_server)
    full = await _list(agent_server, response_mode="full")
    compact_bytes = len(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    full_bytes = len(
        json.dumps(full, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )

    assert set(compact["cards"][0]) == SUMMARY_KEYS
    assert "onboarding_corrections" not in compact["cards"][0]
    assert len(full["cards"][0]["onboarding_corrections"]) == 100
    assert full["cards"][0] == card_with_history.model_dump(mode="json")
    assert compact_bytes * 10 < full_bytes
    assert_no_source_or_model_calls(catalog, judger)


async def test_local_runtime_listing_does_not_read_sources_or_call_judger(tmp_path):
    runtime, source, judger = make_runtime(tmp_path)
    server = create_mcp(runtime, profile="agent")

    result = await _list(server)

    assert result["count"] == 1
    assert result["cards"][0]["id"] == "repeat"
    assert source.calls == 0
    assert judger.states == []

"""Repeat-run MCP responses keep evidence, not duplicated authoring audit trails."""

import json

import pytest
from test_onboarding import make_server, tool


@pytest.mark.parametrize("sqlite", [False, True])
async def test_compact_evaluation_preserves_evidence_and_durable_audit(tmp_path, sqlite):
    server = make_server(tmp_path, sqlite=sqlite)
    drafted = await tool(server, "draft_insight_card")(
        title="Repeatable analysis", what_to_watch="Checkout conversion",
        why_watch="Decide whether Growth needs to act",
        questions=["What changed?"],
        sources=[{"key": "growth", "adapter": "superset", "resource": "dashboard:7",
                  "label": "Growth overview"}],
    )
    card_id = drafted["card"]["id"]
    for _ in range(3):
        await tool(server, "review_insight_card")(card_id)
    tool(server, "record_insight_card_correction")(
        card_id, kind="intent-clarified", note="Owner reviewed the population. " * 60,
    )
    stored = tool(server, "get_insight_card")(card_id)
    preview = await tool(server, "simulate_insight_card")(card_id)
    omitted = {"onboarding_review", "onboarding_review_history", "onboarding_corrections", "compiled_plan"}
    assert preview["card"] == {k: v for k, v in stored.items() if k not in omitted}
    assert preview["delivery_enabled"] is False
    assert preview["resources"] and preview["result"]["evidence"]
    assert tool(server, "get_insight_card")(card_id) == stored

    await tool(server, "approve_insight_card")(card_id)
    stored = tool(server, "get_insight_card")(card_id)
    result = await tool(server, "evaluate_insight_card")(card_id, idempotency_key="repeatable")
    assert result["card"] == {k: v for k, v in stored.items() if k not in omitted}
    assert result["resources"] and result["result"]["evidence"]
    assert "result" not in result["receipt"]
    assert result["plan"] and result["retrieval"]
    full = tool(server, "get_decision_receipt")(idempotency_key="repeatable")
    assert full["receipt"]["result"] == result["result"] == full["result"]
    assert result["receipt"] == {k: v for k, v in full["receipt"].items() if k != "result"}
    assert tool(server, "get_insight_card")(card_id) == stored
    assert stored["onboarding_review_history"] and stored["onboarding_corrections"]

    replay = await tool(server, "evaluate_insight_card")(card_id, idempotency_key="repeatable")
    assert replay["replayed"] and replay["result"] == result["result"]
    assert "result" not in replay["receipt"]
    # Pure serialization saving, not a claim about model tokens or business speed.
    expanded = {**result, "card": stored, "receipt": full["receipt"]}
    assert len(json.dumps(result)) < len(json.dumps(expanded))


async def test_authoring_responses_preserve_current_review_without_repeated_history(tmp_path):
    server = make_server(tmp_path)
    omitted = {"onboarding_review", "onboarding_review_history", "onboarding_corrections", "compiled_plan"}
    for name in ("propose_insight_card", "onboard_insight_card"):
        response = await tool(server, name)(
            what_to_watch="Checkout conversion", why_watch="Decide whether Growth needs to act",
            questions=["What changed?"],
        )
        response = response.get("proposal", response)
        card_id = response["card"]["id"]
        stored = tool(server, "get_insight_card")(card_id)
        assert response["card"] == {k: v for k, v in stored.items() if k not in omitted}
        review = response.get("onboarding_review", response.get("review"))
        assert review == stored["onboarding_review"]
        assert response["plan"] == stored["compiled_plan"]
        for _ in range(2):
            reviewed = await tool(server, "review_insight_card")(card_id)
            stored = tool(server, "get_insight_card")(card_id)
            assert reviewed["card"] == {k: v for k, v in stored.items() if k not in omitted}
            assert reviewed["review"] == stored["onboarding_review"]
        assert len(stored["onboarding_review_history"]) == 3


async def test_context_shape_is_discoverable_and_cannot_claim_trusted_provenance(tmp_path):
    server = make_server(tmp_path)
    for spec in await server.list_tools():
        if spec.name in {"simulate_insight_card", "evaluate_insight_card", "resolve_insight_sources"}:
            shape = spec.inputSchema["$defs"]["ContextSnapshot"]
            assert {"provider", "version"} <= set(shape["required"])
            assert "facts" in shape["properties"]
    drafted = await tool(server, "draft_insight_card")(
        title="Context boundary", what_to_watch="Checkout conversion", why_watch="Growth health",
        sources=[{"key": "growth", "adapter": "superset", "resource": "dashboard:7", "label": "Growth"}],
    )
    from signalweave.models import ContextSnapshot
    preview = await tool(server, "simulate_insight_card")(
        drafted["card"]["id"],
        context=ContextSnapshot(provider="caller", version="v1", trust="trusted"),
    )
    assert preview["result"]["context"]["trust"] == "unverified"

"""Actionable review arguments retain the existing owner and source checks."""

import json

import pytest

from signalweave.mcp_server import _approval_handoff
from signalweave.models import InsightCard, InsightCardOnboardingReview
from tests.test_source_selection_approval import (
    REASON,
    ScopedSupersetCatalogDouble,
    reviewed_case,
    stored,
    tool,
)


async def test_normal_onboard_response_includes_actionable_unapproved_handoff(tmp_path):
    from tests.test_onboarding import make_server

    server = make_server(tmp_path, catalog=ScopedSupersetCatalogDouble())
    result = await tool(server, "onboard_insight_card")(
        what_to_watch="Checkout conversion for completed customer sessions",
        why_watch="Watch customer checkout health",
        selected_sources=[{"ref": "superset|dashboard:7", "key": "checkout", "label": "Checkout"}],
        decision_guidance="Investigate unexpected changes; missing source evidence is insufficient_data.",
        comparison_windows=["previous_period"],
    )
    assert result["card"]["status"] == "draft"
    assert result["approval_handoff"]["arguments_after_owner_confirmation"]["card_id"] == result["card"]["id"]
    assert result["approval_handoff"]["arguments_after_owner_confirmation"]["source_scope_confirmations"] == {
        "superset|dashboard:7": "completed customer sessions",
    }


async def test_review_handoff_preserves_adapter_and_exact_scopes_without_approving(tmp_path):
    server, card_id, _, _, _ = await reviewed_case(
        tmp_path, catalog=ScopedSupersetCatalogDouble(), retrieval_mode="fixed",
    )
    result = await tool(server, "review_insight_card")(card_id, adapter="superset", response_mode="compact")
    handoff = result["approval_handoff"]
    args = handoff["arguments_after_owner_confirmation"]
    assert args == {"card_id": card_id, "adapter": "superset",
                    "source_selection_fingerprint": result["review"]["source_selection_fingerprint"],
                    "source_scope_confirmations": {"superset|dashboard:7": "completed customer sessions"}}
    assert stored(server, card_id)["status"] == "draft"
    assert "source_selection_reason" not in args
    assert handoff["owner_confirmation"]["card_id"] == card_id
    assert handoff["owner_confirmation"]["card_version"] == stored(server, card_id)["version"]
    assert handoff["owner_input_required"] == ["confirm_saved_policy_and_source_scopes"]
    assert handoff["agent_input_after_confirmation"] == ["source_selection_reason"]
    # The handoff supplies no consent or reason on behalf of a human.
    with pytest.raises(ValueError, match="source_selection_reason"):
        await tool(server, "approve_insight_card")(**args)
    approved = await tool(server, "approve_insight_card")(**args, source_selection_reason=REASON)
    assert approved["status"] == "approved"


async def test_handoff_does_not_override_a_source_health_change(tmp_path):
    catalog = ScopedSupersetCatalogDouble()
    server, card_id, _, _, _ = await reviewed_case(tmp_path, catalog=catalog, retrieval_mode="fixed")
    handoff = (await tool(server, "review_insight_card")(card_id))["approval_handoff"]
    catalog.resources[0].contract.source_status = "failed"
    with pytest.raises(ValueError):
        await tool(server, "approve_insight_card")(**handoff["arguments_after_owner_confirmation"], source_selection_reason=REASON)
    assert stored(server, card_id)["status"] == "draft"


async def test_old_owner_handoff_cannot_approve_a_later_reviewed_policy(tmp_path):
    server, card_id, _, _, _ = await reviewed_case(
        tmp_path, catalog=ScopedSupersetCatalogDouble(), retrieval_mode="fixed",
    )
    shown = await tool(server, "review_insight_card")(card_id)
    old_arguments = shown["approval_handoff"]["arguments_after_owner_confirmation"]
    version = shown["card"]["version"]
    tool(server, "revise_insight_card")(
        card_id=card_id, expected_card_version=version,
        changes={"decision_guidance": "Notify Growth only for a decline of at least 15%."},
        reason="Another authorized session revised the policy while the owner was reviewing it.",
    )
    new_review = await tool(server, "review_insight_card")(card_id)
    newer = stored(server, card_id)
    with pytest.raises(ValueError, match="stale|fingerprint|changed"):
        await tool(server, "approve_insight_card")(**old_arguments, source_selection_reason=REASON)
    assert stored(server, card_id) == newer
    approved = await tool(server, "approve_insight_card")(
        **new_review["approval_handoff"]["arguments_after_owner_confirmation"],
        source_selection_reason=REASON,
    )
    assert approved["status"] == "approved"


async def test_dynamic_handoff_never_asserts_owner_acknowledgment(tmp_path):
    server, card_id, _, _, _ = await reviewed_case(tmp_path, catalog=ScopedSupersetCatalogDouble())
    handoff = (await tool(server, "review_insight_card")(card_id))["approval_handoff"]
    assert handoff["dynamic_scope_requires_separate_acknowledgment"] is True
    assert "dynamic_scope_acknowledged" in handoff["owner_input_required"]
    assert "dynamic_scope_acknowledged" not in handoff["arguments_after_owner_confirmation"]
    with pytest.raises(ValueError, match="dynamic_scope_acknowledged"):
        await tool(server, "approve_insight_card")(**handoff["arguments_after_owner_confirmation"], source_selection_reason=REASON)


def test_large_scope_map_is_explicitly_omitted_not_silently_truncated():
    card = InsightCard(id="many", title="Many sources", what_to_watch="Shared meaning", why_watch="Review")
    review = InsightCardOnboardingReview.model_construct(readiness_status="needs_human_review", source_candidates=[
        type("Candidate", (), {"selected": True, "ref": f"company|asset-{i}",
                              "metadata": {"scope": "x" * 3000}})()
        for i in range(10)
    ])
    handoff = _approval_handoff(card, review, None)
    assert handoff["tool"] == "get_insight_card"
    assert handoff["approval_arguments_included"] is False
    assert "arguments_after_owner_confirmation" not in handoff
    assert "owner_confirmation" not in handoff
    assert len(json.dumps(handoff).encode()) < 8192


async def test_owner_question_preserves_population_separately_from_metric_scope(tmp_path):
    catalog = ScopedSupersetCatalogDouble()
    catalog.resources[0].contract.population = "Eligible entities in the source glossary"
    server, card_id, _, _, _ = await reviewed_case(tmp_path, catalog=catalog, retrieval_mode="fixed")
    result = await tool(server, "review_insight_card")(card_id)
    question = next(blocker["question"] for blocker in result["review"]["blockers"] if blocker["code"] == "source-scope-review")
    assert "scope=completed customer sessions" in question
    assert "declared population=Eligible entities in the source glossary" in question
    assert result["approval_handoff"]["declared_populations"] == {
        "superset|dashboard:7": "Eligible entities in the source glossary",
    }


async def test_already_approved_card_is_not_presented_as_needing_approval_again(tmp_path):
    server, card_id, _, _, _ = await reviewed_case(tmp_path, catalog=ScopedSupersetCatalogDouble(), retrieval_mode="fixed")
    result = await tool(server, "review_insight_card")(card_id)
    await tool(server, "approve_insight_card")(**result["approval_handoff"]["arguments_after_owner_confirmation"], source_selection_reason=REASON)
    card = server._test_runtime.card_store.get_card(card_id)
    before = card.model_dump(mode="json")
    handoff = _approval_handoff(card, card.onboarding_review, None)
    assert handoff["approval_arguments_included"] is False
    assert "arguments_after_owner_confirmation" not in handoff
    assert "owner_confirmation" not in handoff
    assert card.model_dump(mode="json") == before

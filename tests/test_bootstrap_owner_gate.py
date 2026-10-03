"""Research-only owner review: both-arm parity, binding and bounded retries."""

import asyncio
import copy
from unittest.mock import AsyncMock

import pytest
from test_bootstrap_agent_trial import make_session

from evaluations.bootstrap_agent_trial import card_fingerprint
from evaluations.bootstrap_scenarios import build_scenarios, public_scenario


@pytest.fixture
def public():
    return public_scenario(build_scenarios(split="dev")[0])


def setup_session(tmp_path, public, treatment):
    session = make_session(tmp_path, public, treatment)
    session.notes = "Use the owner's original investigation policy."
    session.owner_topics.add("materiality")
    session.adapter.inspected.add("company_mcp|inspected")
    session.owner_reviewer = AsyncMock(return_value={"approved": True, "reasons": ["Faithful supplied intent."]})
    return session


@pytest.mark.parametrize("mutation", ["bare_key", "different_endpoint", "unknown_key", "empty_endpoint"])
async def test_owner_review_cannot_approve_route_outside_original_directory(tmp_path, public, mutation):
    session = setup_session(tmp_path, public, True)
    route = copy.deepcopy(public["destinations"][0])
    route["outcome"] = "investigate"
    if mutation == "unknown_key":
        route["key"] = "unlisted-team"
    else:
        route["destination"] = {"bare_key": route["key"], "different_endpoint": "slack://other",
                                "empty_endpoint": ""}[mutation]
    card = {"id": "draft", "delivery_methods": [route]}
    session.product = AsyncMock(return_value=copy.deepcopy(card))
    decision = await session.semantic_owner_review(card)
    assert decision["approved"] is False
    assert decision["directory_validation"] == "rejected"
    assert session.owner_reviewer.await_count == session.owner_review_attempts == 0
    assert session.semantic_approval is None


async def test_exact_endpoint_lookup_accepts_opaque_destinations_and_multiple_outcomes(tmp_path, public):
    public["destinations"][0]["destination"] = "custom-sink:opaque-accepted-value"
    session = setup_session(tmp_path, public, True)
    routes = [{**public["destinations"][0], "outcome": outcome} for outcome in ("notify", "investigate")]
    card = {"id": "draft", "delivery_methods": routes}
    session.product = AsyncMock(return_value=copy.deepcopy(card))
    result = await session.semantic_owner_review(card)
    assert result["approved"] is True
    assert session.owner_reviewer.await_count == 1


async def test_conflicting_directory_keys_fail_closed_before_model_review(tmp_path, public):
    public["destinations"].append({**public["destinations"][0], "destination": "other-endpoint"})
    session = setup_session(tmp_path, public, True)
    card = {"id": "draft", "delivery_methods": [{**public["destinations"][0], "outcome": "notify"}]}
    session.product = AsyncMock(return_value=copy.deepcopy(card))
    result = await session.semantic_owner_review(card)
    assert result["approved"] is False
    assert result["directory_validation"] == "rejected"
    assert session.owner_reviewer.await_count == 0


@pytest.mark.parametrize("treatment", [False, True])
async def test_independent_owner_tool_is_available_to_both_arms_only_during_setup(tmp_path, public, treatment):
    session = setup_session(tmp_path, public, treatment)
    names = [tool["name"] for tool in await session.specs()]
    assert names.count("request_synthetic_owner_approval") == 1
    session.phase = "monitoring"
    assert "request_synthetic_owner_approval" not in [t["name"] for t in await session.specs()]


async def test_baseline_cannot_finish_without_current_review_and_notes_edits_revoke_it(tmp_path, public):
    session = setup_session(tmp_path, public, False)
    assert not (await session.call("finish_setup", {}))["setup_complete"]
    assert not session.setup_complete
    assert (await session.call("request_synthetic_owner_approval", {}))["approved"]
    await session.call("save_notes", {"notes": "Changed policy"})
    assert not (await session.call("finish_setup", {}))["setup_complete"]
    assert (await session.call("request_synthetic_owner_approval", {}))["approved"]
    assert (await session.call("finish_setup", {}))["setup_complete"]
    assert session.owner_reviewer.await_count == 2


async def test_reject_is_not_approval_and_unchanged_retries_do_not_spend_again(tmp_path, public):
    session = setup_session(tmp_path, public, False)
    session.owner_reviewer.return_value = {"approved": False, "reasons": ["Policy changed."]}
    for _ in range(4):
        assert not (await session.call("request_synthetic_owner_approval", {}))["approved"]
    assert session.owner_reviewer.await_count == session.owner_review_attempts == 1
    assert not (await session.call("finish_setup", {}))["setup_complete"]
    for index in range(4):
        session.notes = f"Explicit draft revision {index}"
        await session.call("request_synthetic_owner_approval", {})
    assert session.owner_review_attempts == session.owner_reviewer.await_count == 3


@pytest.mark.parametrize("answer", [None, {}, {"approved": 1}, {"approved": "true"}])
async def test_malformed_owner_decisions_cannot_approve(tmp_path, public, answer):
    session = setup_session(tmp_path, public, False)
    session.owner_reviewer.return_value = answer
    assert not (await session.call("request_synthetic_owner_approval", {}))["approved"]
    assert session.semantic_approval is None


async def test_cancelled_inflight_review_remains_reserved_and_unapproved(tmp_path, public):
    session = setup_session(tmp_path, public, False)
    session.owner_reviewer.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await session.semantic_owner_review(None)
    assert session.owner_review_attempts == len(session.owner_review_records) == 1
    record = session.owner_review_records[0]
    assert record["binding_status"] == "review_pending"
    assert not record["approved"]
    assert session.semantic_approval is None


async def test_source_owner_context_cannot_be_replaced_by_agent_notes_or_future_labels(tmp_path, public):
    public["private"] = {"expected": "hidden-answer"}
    public["periods"][0]["secret_future"] = "hidden-future"
    session = setup_session(tmp_path, public, False)
    session.notes = "Invented owner paraphrase"
    await session.call("request_synthetic_owner_approval", {})
    args = session.owner_reviewer.call_args.kwargs
    assert args["owner_answers"] == public["owner_answers"]
    assert args["artifact"] == {"notes": "Invented owner paraphrase"}
    assert "private" not in args["public"] and "periods" not in args["public"]
    assert "hidden-answer" not in repr(args) and "hidden-future" not in repr(args)


async def test_notes_race_invalidates_owner_acceptance(tmp_path, public):
    session = setup_session(tmp_path, public, False)

    async def race(**kwargs):
        session.notes = "New unreviewed policy"
        return {"approved": True, "reasons": []}

    session.owner_reviewer = race
    result = await session.call("request_synthetic_owner_approval", {})
    assert not result["approved"]
    assert session.semantic_approval is None
    assert session.owner_review_records[0]["approved"] is False


async def test_current_contract_context_is_bounded_and_bound_to_approval(tmp_path, public):
    session = setup_session(tmp_path, public, False)
    ref = next(iter(session.adapter.snapshots))
    session.adapter.inspected.add(ref)
    session.adapter.snapshots[ref]["metadata"]["secret_future"] = "HIDDEN_PAYLOAD"
    before = session.approval_fingerprint(None)
    await session.semantic_owner_review(None)
    context = session.owner_reviewer.call_args.kwargs["source_context"]
    assert len(context["inspected_sources"]) == 1
    assert context["inspected_sources"][0]["ref"] == ref
    assert "HIDDEN_PAYLOAD" not in repr(context)
    assert "analytical_comparisons" not in repr(context)
    session.adapter.snapshots[ref]["contract"]["scope"] = "Changed source population"
    assert session.approval_fingerprint(None) != before
    session.setup_source_context = session.owner_source_context()
    session.setup_complete = True
    approved = session.approval_fingerprint(None)
    session.adapter.set_period(public["periods"][0], session.adapter.clock)
    assert session.approval_fingerprint(None) == approved


async def test_treatment_approval_bound_to_current_card_and_notes(tmp_path, public, monkeypatch):
    session = setup_session(tmp_path, public, True)
    await session.specs()
    card = {"id": "draft", "status": "draft", "decision_guidance": "Investigate only"}
    approvals = []

    async def product(name, args):
        if name == "get_insight_card":
            return copy.deepcopy(card)
        if name == "approve_insight_card":
            approvals.append(args)
            card["status"] = "approved"
            return {"status": "approved"}
        raise AssertionError(name)

    monkeypatch.setattr(session, "product", product)
    session.reviewed["draft"] = session.simulated["draft"] = card_fingerprint(card)
    assert (await session.call("request_synthetic_owner_approval", {"card_id": "draft"}))["approved"]
    session.notes = "New notify policy"
    with pytest.raises(ValueError, match="Synthetic owner requires"):
        await session.call("approve_insight_card", {"card_id": "draft"})
    assert not approvals
    assert (await session.call("request_synthetic_owner_approval", {"card_id": "draft"}))["approved"]
    await session.call("approve_insight_card", {"card_id": "draft"})
    assert (await session.call("finish_setup", {"card_id": "draft"}))["setup_complete"]


async def test_treatment_card_race_cannot_accept(tmp_path, public, monkeypatch):
    session = setup_session(tmp_path, public, True)
    card = {"id": "draft", "status": "draft", "decision_guidance": "Investigate only"}
    monkeypatch.setattr(session, "product", AsyncMock(side_effect=lambda *args: copy.deepcopy(card)))

    async def race(**kwargs):
        card["decision_guidance"] = "Notify everyone"
        return {"approved": True, "reasons": []}

    session.owner_reviewer = race
    result = await session.semantic_owner_review(copy.deepcopy(card))
    assert not result["approved"]
    assert session.semantic_approval is None


@pytest.mark.parametrize("treatment", [False, True])
async def test_policy_notes_are_frozen_during_monitoring_for_both_arms(tmp_path, public, treatment):
    session = setup_session(tmp_path, public, treatment)
    session.phase = "monitoring"
    original = session.notes
    assert "save_notes" not in [tool["name"] for tool in await session.specs()]
    with pytest.raises(ValueError, match="frozen"):
        await session.call("save_notes", {"notes": "Notify everyone on any change"})
    assert session.notes == original


async def test_monitoring_boundary_rechecks_review_fingerprint(tmp_path, public):
    session = setup_session(tmp_path, public, False)
    await session.call("request_synthetic_owner_approval", {})
    await session.assert_current_owner_review()
    session.notes = "Out-of-band mutation"
    with pytest.raises(ValueError, match="matching"):
        await session.assert_current_owner_review()


async def test_changed_original_owner_context_invalidates_review(tmp_path, public):
    session = setup_session(tmp_path, public, False)
    await session.call("request_synthetic_owner_approval", {})
    session.public["destinations"][0]["destination"] = "agent://different-owner"
    with pytest.raises(ValueError, match="matching"):
        await session.assert_current_owner_review()


@pytest.mark.parametrize("error", [OSError, asyncio.CancelledError])
async def test_paid_review_survives_binding_fetch_failure_without_approval(tmp_path, public, monkeypatch, error):
    session = setup_session(tmp_path, public, True)
    session.owner_reviewer.return_value = {"approved": True, "reasons": ["Faithful"],
                                            "episode": {"tool_calls": 1}}
    monkeypatch.setattr(session, "product", AsyncMock(side_effect=error()))
    if error is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await session.semantic_owner_review({"id": "draft"})
    else:
        assert not (await session.semantic_owner_review({"id": "draft"}))["approved"]
    assert session.owner_review_attempts == len(session.owner_review_records) == 1
    assert session.owner_review_records[0]["episode"]["tool_calls"] == 1
    assert not session.owner_review_records[0]["approved"]
    assert session.semantic_approval is None

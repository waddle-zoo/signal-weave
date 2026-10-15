"""Offline setup-smoke integrity checks; no provider or native processes."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import build_scenarios, public_episode
from evaluations.domain_context_onboarding_trial import (
    Episode,
    approval_digest,
    budget_stop,
    public_brief,
    usage_totals,
)
from signalweave.models import InsightCard


def episode():
    public = public_episode(build_scenarios()[0])
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    adapter.set_period(public["period"], datetime.now(timezone.utc))
    return Episode(public, adapter)


def usage(inputs=100, cached=30, output=10):
    return {"kind": "api.response", "provider": "openai", "usage": {
        "input_tokens": inputs, "input_tokens_details": {"cached_tokens": cached}, "output_tokens": output,
    }}


def test_opening_has_no_definition_or_future_answers_and_is_a_copy():
    public = public_episode(build_scenarios()[0])
    public["private"] = {"sentinel": "NOT_FOR_AGENT"}
    brief = public_brief(public)
    assert set(brief) == {"scenario_id", "company", "brief", "owner_topics", "destinations"}
    assert not {"glossary", "private", "owner_answers", "period", "catalog", "periods"} & brief.keys()
    brief["destinations"].clear()
    assert public["destinations"]


def test_usage_distinguishes_cache_and_missing_usage_is_not_free():
    assert usage_totals([usage()]) == {
        "input_tokens": 100, "cached_input_tokens": 30, "uncached_input_tokens": 70, "output_tokens": 10, "responses": 1,
    }
    for invalid in (usage(cached=101), usage(inputs=True), usage(output=None)):
        assert budget_stop([invalid]) == "unknown_usage"
    assert budget_stop([{"kind": "api.error", "provider": "openai"}]) == "unknown_usage_or_agent_error"
    assert budget_stop([usage(500_000, 450_000)]) == "between_episode_token_threshold"
    assert budget_stop([usage(100_000, 25_000)]) == "between_episode_token_threshold"


async def test_baseline_can_discover_read_ask_persist_and_review_without_product():
    session = episode()
    specs = await session.specs()
    names = {tool["name"] for tool in specs}
    assert {"list_company_assets", "read_company_asset", "ask_owner", "save_working_notes", "read_working_notes"} <= names
    catalog = await session.call("list_company_assets", {})
    source = catalog["assets"][0]
    snapshot = await session.call("read_company_asset", {"ref": source["adapter"] + "|" + source["resource"]})
    assert snapshot["contract"]["tenant_id"] == session.public["scenario_id"]
    answer = await session.call("ask_owner", {"topic": "materiality"})
    assert answer["answer"] == session.public["owner_answers"]["materiality"]
    await session.call("save_working_notes", {"notes": "Method and policy saved for later."})
    saved = await session.call("read_working_notes", {})
    assert saved["notes"] == session.notes and saved["id"] == "working"
    await session.call("request_owner_approval", {"kind": "notes", "id": "working", "summary": session.notes})
    assert (await session.call("finish_setup", {"card_ids": [], "message": "A current readout for review.", "unresolved": []}))["semantic_review"] == "pending"


async def test_a_later_notes_edit_invalidates_scripted_consent():
    session = episode()
    await session.call("save_working_notes", {"notes": "Original policy."})
    await session.call("request_owner_approval", {"kind": "notes", "id": "working", "summary": session.notes})
    await session.call("save_working_notes", {"notes": "Different policy."})
    with pytest.raises(ValueError, match="consent"):
        await session.call("finish_setup", {"card_ids": [], "message": "Readout.", "unresolved": []})


async def test_withheld_glossary_is_retrievable_not_removed_from_the_company():
    session = episode()
    assert "glossary" not in public_brief(session.public)
    document = await session.call("read_company_glossary", {})
    assert document["definitions"] == session.public["glossary"]
    document["definitions"].clear()
    assert session.public["glossary"]


def test_card_consent_covers_policy_and_routes_not_mutable_review_audit():
    card = InsightCard(id="one", title="Sales", what_to_watch="Net sales", why_watch="Avoid loss")
    original = card.model_dump(mode="json")
    changed = deepcopy(original)
    changed["what_to_watch"] = "Gross orders"
    assert approval_digest("card", changed) != approval_digest("card", original)
    changed = deepcopy(original)
    changed["status"] = "approved"
    changed["approved_by"] = "synthetic-owner"
    changed["approved_at"] = datetime.now(timezone.utc).isoformat()
    assert approval_digest("card", changed) == approval_digest("card", original)

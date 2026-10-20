"""Offline contract tests for fresh public-MCP context setup."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from evaluations.bootstrap_scenarios import build_scenarios, public_episode
from evaluations.public_context_setup import create_public_context_setup, retail_setup_spec

FIXED_CLOCK = datetime(2026, 9, 17, tzinfo=timezone.utc)


def public_retail_fixture():
    scenario = build_scenarios(
        seed=20261001, split="holdout", connector_profile=True,
    )[0]
    return scenario, public_episode(scenario)


def keys_below(value):
    if isinstance(value, dict):
        yield from value
        for item in value.values():
            yield from keys_below(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys_below(item)


class FakeNative:
    """Small stateful fake for the helper's native MCP calls; no provider path."""

    def __init__(self, *, collision=False, dependency_mismatch=None, brief_mismatch=None, fail_at=None, mutate_inputs=False):
        self.collision = collision
        self.dependency_mismatch = dependency_mismatch
        self.brief_mismatch = brief_mismatch
        self.fail_at = fail_at
        self.mutate_inputs = mutate_inputs
        self.calls = []
        self.context = None
        self.cards = {}
        self._card_number = 0
        self._tool_occurrences = {}

    async def call_tool(self, name, arguments):
        captured = deepcopy(arguments)
        self.calls.append((name, captured))
        self._tool_occurrences[name] = self._tool_occurrences.get(name, 0) + 1
        occurrence = self._tool_occurrences[name]
        if self.fail_at == (name, occurrence):
            raise RuntimeError(f"injected fake failure at {name} call {occurrence}")
        if self.mutate_inputs:
            arguments["fake_native_mutation"] = True

        if name == "save_domain_context":
            self.context = {"id": "context-1", "revision": 1, "status": "draft"}
            return None, deepcopy(self.context)
        if name == "review_domain_context":
            self.context = {"id": captured["entry_id"], "revision": 2, "status": "reviewed"}
            return None, deepcopy(self.context)
        if name == "onboard_insight_card":
            self._card_number += 1
            card_id = "shared-card" if self.collision else f"card-{self._card_number}"
            card = {
                "id": card_id,
                "version": 1,
                "status": "draft",
                "title": captured["title"],
                "what_to_watch": captured["what_to_watch"], "why_watch": captured["why_watch"],
                "sources": [{"key": source["key"], "adapter": source["ref"].split("|", 1)[0],
                             "resource": source["ref"].split("|", 1)[1], "required": source["required"],
                             "required_comparison_keys": source.get("required_comparison_keys", [])}
                            for source in captured["selected_sources"]],
                "selected_sources": deepcopy(captured["selected_sources"]),
                "context_bindings": [],
            }
            self.cards[card_id] = card
            return None, {"card": deepcopy(card)}
        if name == "bind_insight_context":
            card = self.cards[captured["card_id"]]
            card["version"] = captured["expected_card_version"] + 1
            card["context_bindings"] = deepcopy(captured["pins"])
            return None, deepcopy(card)
        if name == "review_insight_card":
            return None, {"approval_handoff": {"arguments_after_owner_confirmation": {
                "card_id": captured["card_id"],
            }}}
        if name == "approve_insight_card":
            card = self.cards[captured["card_id"]]
            card["status"] = "approved"
            return None, {"card": deepcopy(card)}
        if name == "get_insight_card":
            card = deepcopy(self.cards[captured["card_id"]])
            if self.brief_mismatch in {"title", "what_to_watch"}:
                card[self.brief_mismatch] = "Altered brief"
            elif self.brief_mismatch == "sources":
                card["sources"][0]["resource"] = "different-source"
            if self.dependency_mismatch == "entry_id":
                card["context_bindings"][0]["entry_id"] = "different-context"
            elif self.dependency_mismatch == "revision":
                card["context_bindings"][0]["revision"] += 1
            elif self.dependency_mismatch == "required":
                card["context_bindings"][0]["required_for_action"] = False
            elif self.dependency_mismatch == "extra_pin":
                card["context_bindings"].append({
                    "entry_id": "unexpected-context", "revision": 1, "required_for_action": False,
                })
            elif self.dependency_mismatch == "absent_pin":
                card["context_bindings"] = []
            return None, card
        raise AssertionError(f"unexpected native tool call: {name}")


def test_retail_spec_uses_public_fixture_only_and_does_not_mutate_inputs():
    scenario, public = public_retail_fixture()
    public_before = deepcopy(public)
    labels_before = deepcopy(scenario["private"])

    spec = retail_setup_spec(public, FIXED_CLOCK)

    assert public == public_before
    assert scenario["private"] == labels_before
    assert not {"private", "expected", "labels"} & set(keys_below(spec))
    assert spec["cards"][0]["title"] != spec["cards"][1]["title"]
    assert spec["cards"][0]["what_to_watch"] != spec["cards"][1]["what_to_watch"]
    assert spec["cards"][0]["selected_sources"] == spec["cards"][1]["selected_sources"]

    scenario["private"] = {"periods": {"poison": {"outcome": "unexpected"}}}
    public_without_original_labels = public_episode(scenario)
    assert public_without_original_labels == public_before
    assert retail_setup_spec(public_without_original_labels, FIXED_CLOCK) == spec


@pytest.mark.asyncio
async def test_setup_orders_native_calls_and_binds_both_cards_to_same_reviewed_context():
    _, public = public_retail_fixture()
    spec = retail_setup_spec(public, FIXED_CLOCK)
    public_before = deepcopy(public)
    spec_before = deepcopy(spec)
    native = FakeNative(mutate_inputs=True)

    result = await create_public_context_setup(native, spec)

    names = [name for name, _ in native.calls]
    assert names == [
        "save_domain_context", "review_domain_context",
        "onboard_insight_card", "bind_insight_context", "review_insight_card",
        "approve_insight_card", "get_insight_card",
        "onboard_insight_card", "bind_insight_context", "review_insight_card",
        "approve_insight_card", "get_insight_card",
    ]
    assert not {"evaluate_insight_card", "jev", "schedule", "send"} & set(names)
    assert public == public_before
    assert spec == spec_before
    assert result["context"]["id"] == "context-1"
    assert result["context"]["revision"] == 2
    assert result["context"]["status"] == "reviewed"
    assert [card["id"] for card in result["cards"]] == ["card-1", "card-2"]
    assert [card["status"] for card in result["cards"]] == ["approved", "approved"]
    assert all(card["context_bindings"] == [{
        "entry_id": "context-1", "revision": 2, "required_for_action": True,
    }] for card in result["cards"])
    assert [args["pins"] for name, args in native.calls if name == "bind_insight_context"] == [[{
        "entry_id": "context-1", "revision": 2, "required_for_action": True,
    }]] * 2


@pytest.mark.asyncio
async def test_missing_selected_scope_is_rejected_before_any_native_mutation():
    _, public = public_retail_fixture()
    spec = retail_setup_spec(public, FIXED_CLOCK)
    spec["cards"][1]["selected_sources"] = []
    native = FakeNative()

    with pytest.raises(ValueError, match="explicit selected source scopes"):
        await create_public_context_setup(native, spec)

    assert native.calls == []
    assert native.context is None
    assert native.cards == {}


@pytest.mark.asyncio
async def test_partial_write_failure_propagates_and_stops_without_retry():
    _, public = public_retail_fixture()
    spec = retail_setup_spec(public, FIXED_CLOCK)
    native = FakeNative(fail_at=("review_insight_card", 2))

    with pytest.raises(RuntimeError, match="injected fake failure"):
        await create_public_context_setup(native, spec)

    names = [name for name, _ in native.calls]
    assert names == [
        "save_domain_context", "review_domain_context",
        "onboard_insight_card", "bind_insight_context", "review_insight_card",
        "approve_insight_card", "get_insight_card",
        "onboard_insight_card", "bind_insight_context", "review_insight_card",
    ]
    assert native._tool_occurrences["review_insight_card"] == 2
    assert native.cards["card-1"]["status"] == "approved"
    assert native.cards["card-2"]["status"] == "draft"
    assert native.context["status"] == "reviewed"


@pytest.mark.parametrize(
    "mismatch", ["entry_id", "revision", "required", "extra_pin", "absent_pin"],
)
@pytest.mark.asyncio
async def test_returned_approval_snapshot_must_match_exact_context_dependency(mismatch):
    _, public = public_retail_fixture()
    spec = retail_setup_spec(public, FIXED_CLOCK)
    native = FakeNative(dependency_mismatch=mismatch)

    with pytest.raises(RuntimeError, match="reviewed dependency"):
        await create_public_context_setup(native, spec)

    assert [name for name, _ in native.calls].count("get_insight_card") == 1
    assert [name for name, _ in native.calls].count("onboard_insight_card") == 1


@pytest.mark.asyncio
async def test_same_card_id_collision_stops_before_binding_second_card():
    _, public = public_retail_fixture()
    spec = retail_setup_spec(public, FIXED_CLOCK)
    native = FakeNative(collision=True)

    with pytest.raises(RuntimeError, match="Distinct business briefs"):
        await create_public_context_setup(native, spec)

    names = [name for name, _ in native.calls]
    assert names == [
        "save_domain_context", "review_domain_context",
        "onboard_insight_card", "bind_insight_context", "review_insight_card",
        "approve_insight_card", "get_insight_card", "onboard_insight_card",
    ]
    assert native.cards["shared-card"]["status"] == "draft"


@pytest.mark.parametrize("fault", ["title", "what_to_watch", "sources"])
async def test_setup_rejects_changed_saved_brief_or_source_scope(fault):
    _, public = public_retail_fixture()
    with pytest.raises(RuntimeError, match="Stored reporting"):
        await create_public_context_setup(FakeNative(brief_mismatch=fault), retail_setup_spec(public, FIXED_CLOCK))

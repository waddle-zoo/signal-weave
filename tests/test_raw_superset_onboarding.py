"""Offline contracts for the new raw-source authors, not business efficacy."""

import copy
import json

import pytest
from jsonschema import validate

from evaluations.raw_superset_onboarding import (
    AUTHOR_TOOLS,
    MANIFEST,
    OnboardingEpisode,
    check_preflight,
    draft_checks,
    usage_snapshot,
)


class Sources:
    async def specs(self):
        return [{"name": "find_dashboards", "description": "Source", "parameters": {
            "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}]

    async def call(self, name, args):
        return {"source_tool": name, "arguments": args}


class Native:
    async def list_tools(self):
        from types import SimpleNamespace
        return [SimpleNamespace(name=name, description=name, inputSchema={"type": "object"})
                for name in (*AUTHOR_TOOLS, "approve_insight_card", "evaluate_insight_card", "send_message")]

    async def call_tool(self, name, args):
        return [], {"name": name, "arguments": args, "status": "draft"}


async def test_common_tools_and_all_declarations_are_equal_without_topic_enums():
    public = json.loads(MANIFEST.read_text())["owner_declarations"]
    baseline = OnboardingEpisode(Sources(), public)
    treatment = OnboardingEpisode(Sources(), public, Native())
    left, right = await baseline.specs(), await treatment.specs()
    assert left == [s for s in right if s["name"] not in AUTHOR_TOOLS]
    assert not ({"approve_insight_card", "evaluate_insight_card", "send_message"} & {s["name"] for s in right})
    question = {"question": "How do we handle the latest partial reporting month and who should hear about it?"}
    schema = next(s["parameters"] for s in left if s["name"] == "ask_owner")
    validate(question, schema)
    assert await baseline.call("ask_owner", question) == await treatment.call("ask_owner", question)
    assert len((await baseline.call("ask_owner", question))["reference"]["declarations"]) == len(public)


async def test_notes_and_actual_message_required_and_baseline_cannot_claim_card():
    baseline = OnboardingEpisode(Sources(), {})
    payload = {"message": "Sales readout", "card_id": None, "unresolved": []}
    with pytest.raises(ValueError):
        await baseline.call("record_setup", payload)
    await baseline.call("save_working_notes", {"notes": "The reusable brief"})
    assert await baseline.call("read_working_notes", {}) == {"notes": "The reusable brief"}
    with pytest.raises(ValueError):
        await baseline.call("record_setup", {**payload, "card_id": "invented"})
    with pytest.raises(ValueError):
        await baseline.call("record_setup", {**payload, "message": " "})
    await baseline.call("record_setup", payload)
    assert baseline.submission == payload
    with pytest.raises(ValueError, match="already recorded"):
        await baseline.call("find_dashboards", {"query": "Executive"})


async def test_actual_author_calls_forwarded_but_approval_not_forwarded():
    episode = OnboardingEpisode(Sources(), {}, Native())
    result = await episode.call("onboard_insight_card", {"goal": "Sales"})
    assert result["name"] == "onboard_insight_card"
    assert episode.native_calls[0]["result"] == result
    with pytest.raises(ValueError, match="not available"):
        await episode.call("approve_insight_card", {})
    assert len(episode.native_calls) == 1


def successful_preflight():
    return {"protocol": "raw-northstar-onboarding-v1", "completed": True, "preflight_only": True,
            "frozen": {"build": "current"}, "agent_invocations_started": 0, "provider_attempts": 0,
            "initial_card_count": 0, "shared_source_schemas_equal": True,
            "binary_unchanged": True, "research_key_replaced": True,
            "source_probe_successful": True, "usage_known": True}


def test_matching_zero_call_preflight_required():
    preflight = successful_preflight()
    assert check_preflight(preflight, preflight["frozen"]) is None
    for key, value in {"completed": False, "preflight_only": False, "agent_invocations_started": 1,
                       "provider_attempts": 1, "initial_card_count": 1, "shared_source_schemas_equal": False,
                       "binary_unchanged": False, "research_key_replaced": False,
                       "source_probe_successful": False, "usage_known": False,
                       "frozen": {"build": "stale"}}.items():
        changed = copy.deepcopy(preflight)
        changed[key] = value
        with pytest.raises(ValueError):
            check_preflight(changed, preflight["frozen"])


def test_protocol_is_only_onboarding_not_jev_or_enterprise_proof():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["limits"]["agent_invocations"] == 2
    assert manifest["limits"]["jev_attempts"] == 0
    assert "recurring evaluation" in manifest["scope"]
    assert "cannot establish Jev effectiveness" in manifest["interpretation"]
    assert "card" not in manifest and "expected_outcome" not in manifest


def test_missing_wrong_id_or_unreviewed_draft_is_not_qualified():
    episode = OnboardingEpisode(Sources(), {}, Native())
    episode.submission = {"card_id": "saved"}
    assert not all(draft_checks(episode, {"cards": []}).values())
    assert not all(draft_checks(episode, {"cards": [{"id": "invented", "status": "draft"}]}).values())
    actual = {"cards": [{"id": "saved", "status": "draft"}]}
    assert not all(draft_checks(episode, actual).values())
    episode.native_calls.append({"name": "review_insight_card", "arguments": {"card_id": "saved"}, "result": {}})
    assert all(draft_checks(episode, actual).values())
    assert not all(draft_checks(episode, {"cards": [{"id": "saved", "status": "approved"}]}).values())


async def test_closed_live_cohort_rejected_before_any_external_or_state_work(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from evaluations import raw_superset_onboarding as trial
    probe = Mock(side_effect=AssertionError("Closed cohort must stop before probing"))
    monkeypatch.setattr(trial, "verify_binary", probe)
    monkeypatch.setattr(trial, "verify_capture_imports", probe)
    with pytest.raises(ValueError, match="cohort is closed"):
        await trial.run(SimpleNamespace(run=True))
    probe.assert_not_called()


async def test_future_author_pattern_uses_accounting_drain_and_explicit_unchanged_limit(monkeypatch):
    from unittest.mock import AsyncMock

    from evaluations import raw_superset_onboarding as trial
    transport = AsyncMock(return_value={"status": "failed", "error": "tool_call_budget_exhausted"})
    monkeypatch.setattr(trial, "codex_episode", transport)
    limits = {"tools_per_episode": 24, "seconds_per_episode": 300}
    result = await trial.author_episode(Sources(), audit=object(), limits=limits,
                                        codex_executable="/codex", instructions="Read sources", request="Sales")
    assert result["status"] == "failed"
    kwargs = transport.await_args.kwargs
    assert kwargs["accounting_drain"] is True
    assert kwargs["max_tool_calls"] == 24
    assert kwargs["timeout_seconds"] == 300
    assert kwargs["prompt_override"]["execution_budget"]["total_tool_calls_including_save_and_record"] == 24
    assert limits == {"tools_per_episode": 24, "seconds_per_episode": 300}


def accounting_pair():
    return [{"kind": "api.request", "provider": "openai", "request_id": -1},
            {"kind": "api.response", "provider": "openai", "request_id": -1,
             "usage": {"input_tokens": 40, "output_tokens": 8, "input_tokens_details": {"cached_tokens": 12}}}]


def test_accounting_requires_complete_unique_matching_invocation_receipts():
    assert usage_snapshot([], 0)["known"]
    assert not usage_snapshot([], 1)["known"]
    result = usage_snapshot(accounting_pair(), 1)
    assert result["known"] and result["usage"]["input_tokens"] == 40
    events = accounting_pair()
    events[1]["request_id"] = -2
    assert not usage_snapshot(events, 1)["known"]
    assert not usage_snapshot(accounting_pair()[:1], 1)["known"]
    assert not usage_snapshot(accounting_pair()[1:], 1)["known"]
    assert not usage_snapshot(accounting_pair() * 2, 2)["known"]
    events = accounting_pair()
    events.append({"kind": "api.error", "provider": "openai"})
    result = usage_snapshot(events, 1)
    assert result["usage"] is None and result["observed"]["input_tokens"] == 40
    events = accounting_pair()
    events[1]["usage"]["input_tokens_details"]["cached_tokens"] = 100
    assert usage_snapshot(events, 1) == {"known": False, "usage": None, "observed": None}

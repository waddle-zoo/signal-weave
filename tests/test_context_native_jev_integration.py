"""Opt-in current-native/live-Jev integration, not autonomous onboarding or lift.

Scripted fixture-owner approval, synthetic normalized company-MCP exports, three
upstream attempts maximum, no frontier-agent invocation or notification. The
old stopped onboarding cohort is neither resumed nor reclassified by this test.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from evaluations.agent_workflow_cohort import _bridge_identity
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter, RequestBudget
from evaluations.bootstrap_scenarios import build_scenarios, public_episode
from evaluations.domain_context_onboarding_trial import native_context
from scripts.binary_provenance import verify_binary


def check_period(packet, label, destinations):
    result = packet["result"]
    assert result["outcome"] == label["outcome"]
    routes = result["delivery_methods"]
    assert [route["key"] for route in routes] == label["recipients"]
    known = {item["key"]: item["destination"] for item in destinations}
    assert all(route["destination"] == known[route["key"]] for route in routes)
    assert packet["receipt"]["delivery_enabled"] is False
    assert packet["current_context_dependencies"]["required_current"] is True
    assert result.get("judgment", {}).get("status") != "deferred"


def check_deferred_evidence(packet, primary):
    result = packet["result"]
    assert result["outcome"] is None
    assert result["judgment"]["reason"] == "context_review_required"
    snapshot = result["source_by_key"]["sales"]
    assert (snapshot["adapter"], snapshot["resource"]) == (primary["adapter"], primary["resource"])
    assert snapshot["evidence"]
    ref = primary["adapter"] + "|" + primary["resource"]
    assert any(ref in evidence["provenance"] and evidence["values"] for evidence in snapshot["evidence"])


@pytest.mark.parametrize("fault", ["none", "wrong-route", "wrong-destination", "delivery-enabled"])
def test_live_proof_checks_routing_not_only_outcome(fault):
    destinations = [{"key": "growth", "destination": "slack://growth"}]
    packet = {"result": {"outcome": "notify", "delivery_methods": [dict(destinations[0])]},
              "receipt": {"delivery_enabled": False}, "current_context_dependencies": {"required_current": True}}
    if fault == "wrong-route":
        packet["result"]["delivery_methods"][0]["key"] = "other"
    elif fault == "wrong-destination":
        packet["result"]["delivery_methods"][0]["destination"] = "slack://other"
    elif fault == "delivery-enabled":
        packet["receipt"]["delivery_enabled"] = True
    if fault == "none":
        check_period(packet, {"outcome": "notify", "recipients": ["growth"]}, destinations)
    else:
        with pytest.raises(AssertionError):
            check_period(packet, {"outcome": "notify", "recipients": ["growth"]}, destinations)


@pytest.mark.parametrize("fault", ["none", "empty-snapshot", "wrong-source", "no-provenance", "no-values"])
def test_live_proof_checks_deferred_content_and_provenance(fault):
    primary = {"adapter": "company_mcp", "resource": "sales-export"}
    snapshot = {**primary, "evidence": [{"values": {"current": 7}, "provenance": ["company_mcp|sales-export"]}]}
    packet = {"result": {"outcome": None, "judgment": {"reason": "context_review_required"}, "source_by_key": {"sales": snapshot}}}
    if fault == "empty-snapshot":
        packet["result"]["source_by_key"]["sales"] = {}
    elif fault == "wrong-source":
        snapshot["resource"] = "another-export"
    elif fault == "no-provenance":
        snapshot["evidence"][0]["provenance"] = []
    elif fault == "no-values":
        snapshot["evidence"][0]["values"] = {}
    if fault == "none":
        check_deferred_evidence(packet, primary)
    else:
        with pytest.raises((AssertionError, KeyError)):
            check_deferred_evidence(packet, primary)


@pytest.mark.skipif(
    os.getenv("RUN_CONTEXT_JEV_INTEGRATION") != "1",
    reason="requires explicit current native binary and live Jev credential; at most three upstream attempts",
)
async def test_native_approved_context_card_recurrence_with_live_jev(tmp_path, record_property):
    import asyncio

    audit = Audit(path=tmp_path / "trace.jsonl")
    audit.path.touch(mode=0o600)
    budget = RequestBudget(limit=3)
    try:
        with tempfile.TemporaryDirectory(prefix="native-state-", dir=tmp_path) as private:
            async with asyncio.timeout(240):
                await exercise_live_native(Path(private), record_property, audit, budget)
    finally:
        record_property("provider_attempts", budget.used)
        usages = [
            event.get("usage") for event in audit.events if event.get("kind") == "api.response"
        ]
        errors = sum(event.get("kind") in {"api.error", "api.rejected"} for event in audit.events)
        record_property("provider_usage", json.dumps(usages))
        record_property("provider_errors", errors)
        record_property("provider_usage_known", errors == 0 and len(usages) == budget.used and all(
            isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0
                                           for key in ("input_tokens", "output_tokens"))
            for usage in usages
        ))


async def exercise_live_native(tmp_path, record_property, audit, budget):
    binary = Path(os.environ["SIGNALWEAVE_BINARY"]).resolve()
    identity = verify_binary(binary)
    scenario = _bridge_identity(build_scenarios(seed=20261001, connector_profile=True)[0])
    public = public_episode(scenario)
    for field in ("git_commit", "source_sha256", "binary_sha256"):
        record_property("native_" + field, identity[field])
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    adapter.set_period(public["period"], datetime.now(timezone.utc))
    primary = next(item for item in public["catalog"] if item["contract"].get("roles") == ["primary"])
    secondary = next(item for item in public["catalog"] if item["contract"].get("roles") == ["corroborates"])
    primary_ref = primary["adapter"] + "|" + primary["resource"]
    metric = primary["contract"]["metric_names"][0]
    async with native_context(
        binary, Path(os.environ["TYPESAFE_API_KEY_FILE"]).resolve(), public, adapter, audit, tmp_path,
        request_budget=budget,
    ) as (native, _skill):
        _, created = await native.call_tool("onboard_insight_card", {
            "title": "Synthetic recurring sales protocol check",
            "what_to_watch": public["glossary"][metric], "why_watch": public["brief"],
            "decision_guidance": public["owner_answers"]["materiality"],
            "follow_up_guidance": "Use the source's current periods; report arithmetic contributions, not causes.",
            "comparison_windows": ["previous_period"],
            "selected_sources": [{"ref": primary_ref, "key": "sales", "required": True,
                                  "required_comparison_keys": [metric]},
                                 {"ref": secondary["adapter"] + "|" + secondary["resource"],
                                  "key": "posting-policy", "required": True}],
            "delivery_methods": [{"key": "business", "outcome": "notify", **public["destinations"][0]},
                                 {"key": "data", "outcome": "insufficient_data", **public["destinations"][1]}],
        })
        card_id = created["card"]["id"]
        note = {
            "domain": "sales", "title": "Reviewed sales meaning",
            "body": public["glossary"][metric], "kind": "definition",
            "sources": [{"key": "sales", "adapter": primary["adapter"],
                         "resource": primary["resource"], "label": primary["title"]}],
            "provenance": ["Scripted synthetic owner, existing fixture metric definition"],
            "review_after": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        }
        _, saved = await native.call_tool("save_domain_context", {"content": note})
        _, reviewed = await native.call_tool("review_domain_context", {
            "entry_id": saved["id"], "expected_revision": 1, "action": "approve",
            "reason": "Synthetic fixture review, not a real company sign-off.",
        })
        await native.call_tool("bind_insight_context", {
            "card_id": card_id, "expected_card_version": created["card"]["version"],
            "pins": [{"entry_id": saved["id"], "revision": reviewed["revision"], "required_for_action": True}],
            "reason": "Use the existing fixture definition as a prerequisite; no new semantics inferred.",
        })
        _, review = await native.call_tool("review_insight_card", {"card_id": card_id})
        approval = review["approval_handoff"]["arguments_after_owner_confirmation"]
        await native.call_tool("approve_insight_card", {
            **approval,
            "source_selection_reason": "Scripted owner accepts the existing synthetic exporter scopes for this protocol check, not company-wide coverage.",
        })
        assert budget.used == 0, "explicit-source authoring must not invoke the provider"
        outcomes = []
        for period in scenario["public"]["periods"]:
            adapter.set_period(period, datetime.now(timezone.utc))
            _, packet = await native.call_tool("evaluate_insight_card", {
                "card_id": card_id, "idempotency_key": period["period_id"], "response_mode": "full",
            })
            label = scenario["private"]["periods"][period["period_id"]]
            expected = label["outcome"]
            result = packet["result"]
            outcomes.append({"period": period["period_id"], "expected": expected, "actual": result["outcome"]})
            record_property("observed_period_" + str(len(outcomes)), json.dumps(outcomes[-1]))
            audit.emit("native.result", tool="evaluate_insight_card", packet=packet)
            check_period(packet, label, public["destinations"])
        assert 0 < budget.used <= 3 and not budget.exhausted
        before_change = budget.used
        await native.call_tool("save_domain_context", {
            "entry_id": saved["id"], "expected_revision": reviewed["revision"],
            "content": {**note, "body": "A changed draft definition awaits owner clarification."},
        })
        _, deferred = await native.call_tool("evaluate_insight_card", {
            "card_id": card_id, "idempotency_key": "changed-meaning", "response_mode": "full",
        })
        audit.emit("native.result", tool="evaluate_insight_card", packet=deferred)
        check_deferred_evidence(deferred, primary)
        assert budget.used == before_change
    attempts = [event for event in audit.events if event.get("kind") == "api.request"]
    responses = [event for event in audit.events if event.get("kind") == "api.response"]
    assert len(attempts) == len(responses) == budget.used
    assert not any(event.get("kind") in {"api.error", "api.rejected"} for event in audit.events)
    record_property("outcomes", json.dumps(outcomes))

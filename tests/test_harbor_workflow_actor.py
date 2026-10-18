"""Offline contracts for the bounded Harbor workflow actor bridge."""

from __future__ import annotations

import asyncio
import json
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluations.harbor_workflow_actor import (
    ONBOARDING_NATIVE_TOOLS,
    RECURRING_NATIVE_TOOLS,
    HarborWorkflowActor,
)


def run_async(test):
    @wraps(test)
    def wrapper(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return wrapper


class FakeAudit:
    def __init__(self):
        self.events = []

    def emit(self, kind, **payload):
        self.events.append({"kind": kind, **payload})


def tool(name):
    return SimpleNamespace(
        name=name,
        description=f"Read-only fake {name}",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    )


class FakeInstalledServer:
    def __init__(self, names, handler=None):
        self.tools = [tool(name) for name in names]
        self.handler = handler
        self.calls = []

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, json.loads(json.dumps(arguments))))
        if self.handler is None:
            result = {"tool": name, "arguments": arguments}
        else:
            result = self.handler(name, arguments)
            if isinstance(result, Exception):
                raise result
        return [], result


OWNER = {
    "opening_business_request": "Prepare a review handoff for open priority work.",
    "known_owner_intent": "Known clock breaches merit manual review, not a harm claim.",
    "source_expert_facts": ["Ticket times are visible only as known by the snapshot cutoff."],
    "recipient_keys": ["queue-lead", "duty-manager"],
    "destinations": {
        "queue-lead": "simulation://queue-route",
        "duty-manager": "simulation://duty-route",
    },
}
SOURCE_TOOLS = ["list_assets", "query_readonly", "export_query", "list_saved_queries"]
NATIVE_TOOLS = sorted(
    ONBOARDING_NATIVE_TOOLS
    | RECURRING_NATIVE_TOOLS
    | {
        "approve_insight_card",
        "evaluate_card_workflow",
        "save_domain_context",
        "retrieve_domain_context",
    }
)


@run_async
async def test_specs_keep_shared_source_tools_and_limit_native_tools_by_phase():
    source = FakeInstalledServer(SOURCE_TOOLS)
    native = FakeInstalledServer(NATIVE_TOOLS)
    onboarding = HarborWorkflowActor(source, FakeAudit(), OWNER, native=native)
    recurring = HarborWorkflowActor(
        source, FakeAudit(), OWNER, native=native, phase="recurring",
        observation_cutoffs=["2026-10-05T00:00:00Z"],
    )

    onboarding_specs = await onboarding.specs()
    onboarding_names = {spec["name"] for spec in onboarding_specs}
    assert set(SOURCE_TOOLS) <= onboarding_names
    assert {"ask_owner", "save_working_notes"} <= onboarding_names
    assert ONBOARDING_NATIVE_TOOLS <= onboarding_names
    assert not {
        "approve_insight_card", "evaluate_insight_card", "evaluate_card_workflow",
        "save_domain_context", "retrieve_domain_context", "save_brief",
    } & onboarding_names

    recurring_specs = await recurring.specs()
    recurring_names = {spec["name"] for spec in recurring_specs}
    assert set(SOURCE_TOOLS) <= recurring_names
    assert {"ask_owner", "save_working_notes", "save_brief"} <= recurring_names
    assert RECURRING_NATIVE_TOOLS <= recurring_names
    brief_spec = next(spec for spec in recurring_specs if spec["name"] == "save_brief")
    assert brief_spec["parameters"]["properties"]["recipients"]["items"]["enum"] == OWNER["recipient_keys"]
    assert "simulation://" not in json.dumps(brief_spec)
    assert not {
        "search_catalog", "inspect_resource", "onboard_insight_card",
        "revise_insight_card", "review_insight_card", "approve_insight_card",
        "save_domain_context", "retrieve_domain_context",
    } & recurring_names


@run_async
async def test_onboarding_owner_reference_and_notes_are_not_approval():
    native = FakeInstalledServer(NATIVE_TOOLS)
    actor = HarborWorkflowActor(FakeInstalledServer(SOURCE_TOOLS), FakeAudit(), OWNER, native=native)

    reference = await actor.call("ask_owner", {"question": "Which audience is intended?"})
    assert reference["known"] is False
    assert reference["answer"] is None
    assert reference["answer_status"] == "declared_reference_only"
    assert [row["citation"] for row in reference["reference"]["declarations"]] == [
        "opening_business_request", "known_owner_intent", "source_expert_facts",
    ]
    assert all(row["citation"] not in {"recipient_keys", "destinations"}
               for row in reference["reference"]["declarations"])
    assert "simulation://" not in json.dumps(reference)

    notes = "  Keep cohorts and unknown coverage distinct.\n"
    assert await actor.call("save_working_notes", {"notes": notes}) == {
        "saved": True, "approved": False,
    }
    assert actor.notes == notes
    assert actor.setup_complete is False and actor.submission is None

    for name in ("onboard_insight_card", "get_insight_card", "revise_insight_card", "review_insight_card"):
        result = await actor.call(name, {"card_id": "card-1"})
        assert result["tool"] == name
    with pytest.raises(ValueError, match="tool not available"):
        await actor.call("approve_insight_card", {"card_id": "card-1"})
    with pytest.raises(ValueError, match="tool not available"):
        await actor.call("evaluate_insight_card", {"card_id": "card-1"})
    assert [row["name"] for row in actor.native_calls] == [
        "onboard_insight_card", "get_insight_card", "revise_insight_card", "review_insight_card",
    ]


@run_async
async def test_fake_onboarding_then_three_checks_preserves_notes_and_local_briefs():
    cutoffs = [
        "2026-10-05T00:00:00Z",
        "2026-10-12T00:00:00Z",
        "2026-10-19T00:00:00Z",
    ]
    active = {"index": 0}

    def source_result(name, arguments):
        if name == "query_readonly":
            return {
                "sql": arguments["sql"],
                "as_of": cutoffs[active["index"]],
                "rows": [[active["index"]]],
            }
        return {"tool": name, "arguments": arguments}

    async def advance(index):
        active["index"] = index

    source = FakeInstalledServer(SOURCE_TOOLS, source_result)
    native = FakeInstalledServer(NATIVE_TOOLS)
    owner = {**OWNER, "recipient_keys": ["queue-lead", "duty-manager"]}
    onboarding = HarborWorkflowActor(source, FakeAudit(), owner, native=native)
    notes = "Persist the UTC cohort rule and distinguish responded open work."
    await onboarding.call("save_working_notes", {"notes": notes})
    await onboarding.call("onboard_insight_card", {"goal": "Review the priority queue"})
    await onboarding.call("review_insight_card", {"card_id": "card-1"})

    audit = FakeAudit()
    recurring = HarborWorkflowActor(
        source, audit, owner, native=native, phase="recurring", notes=onboarding.notes,
        card_id="card-1", observation_cutoffs=cutoffs, advance=advance,
    )
    assert recurring.notes == notes

    for index in range(3):
        query_args = {"sql": f"SELECT count(*) FROM queue WHERE observation={index}"}
        result = await recurring.call("query_readonly", query_args)
        assert result["as_of"] == cutoffs[index]
        if index == 0:
            await recurring.call("get_signalweave_guide", {})
            await recurring.call("evaluate_insight_card", {
                "card_id": "card-1", "idempotency_key": "run-1",
            })
            await recurring.call("get_decision_receipt", {"receipt_id": "receipt-1"})

        body = f"  Check {index + 1}: known queue state at the cutoff.\n"
        recipients = [] if index == 1 else ["queue-lead"]
        saved = await recurring.call("save_brief", {
            "body": body,
            "recipients": recipients,
            "evidence_refs": [f"company_mcp|queue-{index + 1}"],
        })
        assert saved["brief"]["body"] == body
        assert saved["brief"]["recipients"] == recipients
        assert saved["brief"]["observation_cutoff"] == cutoffs[index]
        assert saved["brief"]["card_id"] == "card-1"
        assert saved["delivery"] == "local_shadow_draft" and saved["sent"] is False
        if index < 2:
            assert saved["continue_request"] is True
            assert saved["next_source_cutoff"] == cutoffs[index + 1]
            if index == 0:
                assert cutoffs[2] not in json.dumps(saved)
        else:
            assert saved["request_complete"] is True
            assert "next_source_cutoff" not in saved

    assert [brief["observation_cutoff"] for brief in recurring.briefs] == cutoffs
    assert [query["arguments"] for query in recurring.queries] == [
        {"sql": f"SELECT count(*) FROM queue WHERE observation={index}"}
        for index in range(3)
    ]
    assert [query["result"]["rows"] for query in recurring.queries] == [[[0]], [[1]], [[2]]]
    assert [row["name"] for row in recurring.native_calls] == [
        "get_signalweave_guide", "evaluate_insight_card", "get_decision_receipt",
    ]
    assert recurring.native_calls[1] == {
        "name": "evaluate_insight_card",
        "observation_cutoff": cutoffs[0],
        "arguments": {"card_id": "card-1", "idempotency_key": "run-1"},
        "result": {
            "tool": "evaluate_insight_card",
            "arguments": {"card_id": "card-1", "idempotency_key": "run-1"},
        },
    }
    assert recurring.setup_complete is False and recurring.submission is None
    assert active["index"] == 2
    specs_json = json.dumps(await recurring.specs())
    assert all(cutoff not in specs_json for cutoff in cutoffs)
    assert any(event["kind"] == "actor.snapshot_advanced" for event in audit.events)


@pytest.mark.parametrize("arguments", [
    {"body": "   ", "recipients": [], "evidence_refs": ["source|one"]},
    {"body": "Brief", "recipients": ["unknown"], "evidence_refs": ["source|one"]},
    {"body": "Brief", "recipients": [], "evidence_refs": ["   "]},
    {"body": "Brief", "recipients": [], "evidence_refs": []},
])
@run_async
async def test_invalid_briefs_never_advance_or_mutate(arguments):
    advance = AsyncMock(return_value="2026-10-12T00:00:00Z")
    actor = HarborWorkflowActor(
        FakeInstalledServer(SOURCE_TOOLS), FakeAudit(), OWNER, phase="recurring",
        observation_cutoffs=["2026-10-05T00:00:00Z", "2026-10-12T00:00:00Z"],
        advance=advance,
    )

    with pytest.raises(ValueError):
        await actor.call("save_brief", arguments)
    assert actor.briefs == []
    advance.assert_not_awaited()


@run_async
async def test_partial_snapshot_advance_failure_keeps_brief_and_never_completes():
    cutoffs = [
        "2026-10-05T00:00:00Z",
        "2026-10-12T00:00:00Z",
        "2026-10-19T00:00:00Z",
    ]
    active = {"index": 0}

    async def advance(index):
        active["index"] = index
        if index == 2:
            raise RuntimeError("snapshot copy changed during activation")
        return cutoffs[index]

    audit = FakeAudit()
    actor = HarborWorkflowActor(
        FakeInstalledServer(SOURCE_TOOLS), audit, OWNER, phase="recurring",
        observation_cutoffs=cutoffs, advance=advance,
    )
    brief_args = {
        "body": "Current observed queue state.",
        "recipients": [],
        "evidence_refs": ["company_mcp|queue"],
    }
    first = await actor.call("save_brief", brief_args)
    assert first["next_source_cutoff"] == cutoffs[1]

    with pytest.raises(RuntimeError, match="did not activate successfully"):
        await actor.call("save_brief", brief_args)

    assert len(actor.briefs) == 2
    assert actor.briefs[1]["observation_cutoff"] == cutoffs[1]
    assert actor.submission is None and actor.setup_complete is False
    assert actor.failed is True
    assert active["index"] == 2  # The callback partially changed caller-owned state.
    failure, = [event for event in audit.events if event["kind"] == "actor.advance_failed"]
    assert failure["completed_brief"]["body"] == brief_args["body"]
    assert failure["partial_activation_possible"] is True
    assert failure["error"]["message"] == "snapshot copy changed during activation"
    with pytest.raises(ValueError, match="Actor session failed"):
        await actor.call("save_brief", brief_args)
    assert len(actor.briefs) == 2


@pytest.mark.parametrize("target", ["source", "native"])
@run_async
async def test_failed_read_can_be_corrected_and_briefed_without_hiding_failure(target):
    def handler(name, arguments):
        if target == "source" and arguments.get("sql") == "SELECT FROM queue":
            raise RuntimeError("SQL syntax error")
        if target == "native" and arguments.get("task") == "unsupported":
            raise ValueError("unsupported guide task")
        return {"tool": name, "arguments": arguments, "recovered": True}

    source = FakeInstalledServer(SOURCE_TOOLS)
    native = FakeInstalledServer(NATIVE_TOOLS)
    if target == "source":
        source.handler = handler
        name, bad_arguments = "query_readonly", {"sql": "SELECT FROM queue"}
        good_arguments = {"sql": "SELECT count(*) FROM queue"}
        expected_event = "actor.source_call_failed"
        error_message = "SQL syntax error"
    else:
        native.handler = handler
        name, bad_arguments = "get_signalweave_guide", {"task": "unsupported"}
        good_arguments = {"task": "start"}
        expected_event = "actor.native_call_failed"
        error_message = "unsupported guide task"
    audit = FakeAudit()
    actor = HarborWorkflowActor(
        source, audit, OWNER, native=native, phase="recurring",
        observation_cutoffs=["2026-10-05T00:00:00Z"],
    )

    with pytest.raises((RuntimeError, ValueError), match=error_message):
        await actor.call(name, bad_arguments)
    assert actor.failed is False
    assert actor.submission is None and actor.setup_complete is False
    calls = actor.native_calls if target == "native" else actor.queries
    assert calls[0]["arguments"] == bad_arguments
    assert calls[0]["result"] is None
    assert calls[0]["error"]["message"] == error_message
    event, = [event for event in actor.audit.events if event["kind"] == expected_event]
    assert event["name"] == name and event["arguments"] == bad_arguments
    assert event["error"]["message"] == error_message

    result = await actor.call(name, good_arguments)
    assert result["recovered"] is True
    assert actor.failed is False
    assert actor.submission is None and actor.setup_complete is False
    assert len(calls) == 2
    assert calls[1]["arguments"] == good_arguments and calls[1]["result"] == result

    brief = await actor.call("save_brief", {
        "body": "Observed queue state after correcting the failed read.",
        "recipients": [],
        "evidence_refs": ["company_mcp|queue-count"],
    })
    assert brief["saved"] is True and brief["sent"] is False
    assert len(actor.briefs) == 1
    assert actor.failed is False
    # Recovery demonstrates tool/session continuity, not semantic usefulness.
    assert not any("business_success" in event for event in audit.events)

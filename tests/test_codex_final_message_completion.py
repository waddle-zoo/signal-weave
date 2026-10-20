"""Offline return-path coverage for opt-in Codex final-message completion."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from evaluations import bootstrap_agent_trial as trial
from evaluations import codex_trial_transport as transport

VALID_USAGE = {"input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0}


def event_line(event):
    return json.dumps(event).encode() + b"\n"


def message_event(text):
    return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}


def usage_event(usage=VALID_USAGE):
    return {"type": "turn.completed", "usage": usage}


@pytest.fixture
def fake_codex_process(monkeypatch):
    session = SimpleNamespace(
        phase="monitoring", treatment=False, submission=None, setup_complete=False,
        public={"brief": "Offline test"}, notes="saved policy",
        adapter=SimpleNamespace(period_context={"period_id": "offline"}),
        server=SimpleNamespace(instructions="Offline instructions"),
        specs=AsyncMock(return_value=[{
            "name": "list_catalog", "description": "Offline test tool",
            "parameters": {"type": "object"},
        }]),
        call=AsyncMock(return_value={"ok": True}),
    )
    audit = trial.Audit()
    state = SimpleNamespace(exit_code=0, bridge=None, closed=False)
    process = SimpleNamespace(
        stdin=SimpleNamespace(write=Mock(), drain=AsyncMock(), close=Mock()),
        stdout=SimpleNamespace(readline=AsyncMock()),
        stderr=SimpleNamespace(readline=AsyncMock(return_value=b"")),
        returncode=None, terminate=Mock(), kill=Mock(), wait=AsyncMock(),
    )

    async def wait():
        if process.returncode is None:
            process.returncode = (
                -9 if process.kill.called else
                -15 if process.terminate.called else state.exit_code
            )
        return process.returncode

    process.wait.side_effect = wait

    @asynccontextmanager
    async def serve(bridge):
        state.bridge = bridge
        try:
            yield "http://127.0.0.1:1234/offline"
        finally:
            state.closed = True

    state.spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(transport, "serve_trial", serve)
    monkeypatch.setattr(transport.asyncio, "create_subprocess_exec", state.spawn)
    monkeypatch.setattr(transport, "child_environment", lambda: {"PATH": "/offline"})

    async def run(events=(), **kwargs):
        if callable(events):
            process.stdout.readline.side_effect = events
        else:
            process.stdout.readline.side_effect = [
                event if isinstance(event, bytes) else event_line(event)
                for event in events
            ] + [b""]
        state.exit_code = kwargs.pop("exit_code", 0)
        return await transport.codex_episode(
            session, key="unused", effort="low", budget=None, audit=audit,
            max_turns=2, max_tool_calls=3, max_output_tokens=100,
            **kwargs,
        )

    state.session = session
    state.audit = audit
    state.process = process
    state.run = run
    return state


async def test_opt_in_completes_on_exact_final_message_and_reports_basis(fake_codex_process):
    fake = fake_codex_process
    message = "  Report recorded locally.\n"

    result = await fake.run(
        [message_event(message), usage_event()], finish_on_final_message=True,
    )

    assert result["status"] == "complete" and result["error"] is None
    assert result["completion_basis"] == "final_message"
    assert result["final_message"] == message
    assert fake.session.submission is None and not fake.session.setup_complete
    assert result["exit_code"] == 0


async def test_default_does_not_complete_from_final_message_or_add_new_result_field(fake_codex_process):
    fake = fake_codex_process

    result = await fake.run([message_event("Report recorded."), usage_event()])

    assert result["status"] == "failed"
    assert result["final_message"] == "Report recorded."
    assert "completion_basis" not in result


@pytest.mark.parametrize("text", ["", " \t\n "])
async def test_blank_final_message_cannot_complete(fake_codex_process, text):
    result = await fake_codex_process.run(
        [message_event(text), usage_event()], finish_on_final_message=True,
    )

    assert result["status"] == "failed"
    assert result["completion_basis"] == "none"
    assert result["final_message"] == text


@pytest.mark.parametrize(
    "events",
    [
        [message_event("Finished.")],
        [message_event("Finished."), usage_event({"input_tokens": -1})],
        [message_event("Finished."), usage_event(), usage_event()],
    ],
    ids=["missing-usage", "malformed-usage", "duplicate-usage"],
)
async def test_final_message_requires_exactly_one_valid_usage_report(fake_codex_process, events):
    result = await fake_codex_process.run(events, finish_on_final_message=True)

    assert result["status"] == "failed"
    assert result["completion_basis"] == "none"


@pytest.mark.parametrize("phase", ["monitoring", "onboarding"])
@pytest.mark.parametrize(
    ("events", "expected_error"),
    [
        ([], "missing_completion_usage"),
        ([usage_event({"input_tokens": -1})], "invalid_completion_usage"),
        ([usage_event(), usage_event()], "ambiguous_completion_usage"),
    ],
    ids=["missing", "malformed", "duplicate"],
)
async def test_opt_in_structured_completion_requires_valid_usage(
    fake_codex_process, phase, events, expected_error,
):
    session = fake_codex_process.session
    session.phase = phase
    if phase == "onboarding":
        session.setup_complete = True
    else:
        session.submission = {"recorded": True}

    result = await fake_codex_process.run(events, finish_on_final_message=True)

    assert result["status"] == "failed"
    assert result["error"] == expected_error
    assert result["completion_basis"] == "none"
    accounting_error = next(
        event for event in reversed(fake_codex_process.audit.events)
        if event["kind"] == "api.error"
    )
    assert accounting_error["error_type"] == expected_error
    assert accounting_error["usage_known"] is False


async def test_started_only_agent_message_is_not_a_completed_final_message(fake_codex_process):
    partial = {
        "type": "item.started",
        "item": {"id": "message-1", "type": "agent_message", "text": "Partial reply."},
    }

    result = await fake_codex_process.run(
        [partial, usage_event()], finish_on_final_message=True,
    )

    assert result["status"] == "failed"
    assert result["completion_basis"] == "none"
    assert result["final_message"] == "Partial reply."


@pytest.mark.parametrize("finish_tool_item", [False, True], ids=["started-only", "completed-tool"])
async def test_agent_message_before_toolwork_is_not_the_final_message(
    fake_codex_process, finish_tool_item,
):
    tool_started = {
        "type": "item.started",
        "item": {"id": "tool-1", "type": "mcp_tool_call", "server": "trial"},
    }
    events = [message_event("Earlier commentary."), tool_started]
    if finish_tool_item:
        events.append({
            "type": "item.completed",
            "item": {"id": "tool-1", "type": "mcp_tool_call", "server": "trial"},
        })
    events.append(usage_event())

    result = await fake_codex_process.run(events, finish_on_final_message=True)

    assert result["status"] == "failed"
    assert result["completion_basis"] == "none"
    assert result["final_message"] == "Earlier commentary."


async def test_completed_agent_message_after_toolwork_can_complete(fake_codex_process):
    events = [
        {
            "type": "item.started",
            "item": {"id": "tool-1", "type": "mcp_tool_call", "server": "trial"},
        },
        {
            "type": "item.completed",
            "item": {"id": "tool-1", "type": "mcp_tool_call", "server": "trial"},
        },
        {
            "type": "item.started",
            "item": {"id": "message-2", "type": "agent_message", "text": "Done."},
        },
        {
            "type": "item.completed",
            "item": {"id": "message-2", "type": "agent_message", "text": "Final report."},
        },
        usage_event(),
    ]

    result = await fake_codex_process.run(events, finish_on_final_message=True)

    assert result["status"] == "complete"
    assert result["completion_basis"] == "final_message"
    assert result["final_message"] == "Final report."


async def test_nonzero_exit_cannot_promote_final_message(fake_codex_process):
    result = await fake_codex_process.run(
        [message_event("Finished."), usage_event()],
        finish_on_final_message=True, exit_code=7,
    )

    assert result["status"] == "failed"
    assert result["completion_basis"] == "none"
    assert result["exit_code"] == 7


async def test_timeout_cannot_promote_even_a_message_with_valid_usage(fake_codex_process):
    events = [event_line(message_event("Finished.")), event_line(usage_event())]

    async def read_then_stall():
        if events:
            return events.pop(0)
        await asyncio.Event().wait()

    result = await fake_codex_process.run(
        read_then_stall, finish_on_final_message=True, timeout_seconds=0.01,
    )

    assert result["status"] == "failed"
    assert result["error"] == "episode_timeout"
    assert result["completion_basis"] == "none"
    assert result["final_message"] == "Finished."


async def test_foreign_tool_error_cannot_promote_final_message(fake_codex_process):
    result = await fake_codex_process.run(
        [
            message_event("Finished."),
            {"type": "item.completed", "item": {"type": "command_execution"}},
            usage_event(),
        ],
        finish_on_final_message=True,
    )

    assert result["status"] == "failed"
    assert result["error"] == "foreign_tool_used"
    assert result["completion_basis"] == "none"
    assert result["foreign_tools"] == ["command_execution"]


async def test_tool_cap_error_cannot_promote_final_message(fake_codex_process):
    fake = fake_codex_process
    reads = [event_line(message_event("Finished.")), event_line(usage_event())]

    async def exhaust_before_usage():
        if len(reads) == 1:
            for _ in range(fake.bridge.max_calls):
                await fake.bridge.call("list_catalog", {})
            with pytest.raises(ValueError, match="tool_call_budget_exhausted"):
                await fake.bridge.call("list_catalog", {})
        return reads.pop(0) if reads else b""

    result = await fake.run(exhaust_before_usage, finish_on_final_message=True)

    assert result["status"] == "failed"
    assert result["error"] == "tool_call_budget_exhausted"
    assert result["completion_basis"] == "none"
    assert result["final_message"] == "Finished."


async def test_codex_error_event_cannot_promote_final_message(fake_codex_process):
    result = await fake_codex_process.run(
        [
            message_event("Finished."), usage_event(),
            {"type": "error", "message": "offline failure"},
        ],
        finish_on_final_message=True,
    )

    assert result["status"] == "failed"
    assert result["error"] == "codex_error"
    assert result["completion_basis"] == "none"


async def test_wall_response_guard_cannot_promote_completed_message(fake_codex_process, monkeypatch):
    fake = fake_codex_process
    killed = asyncio.Event()
    fake.process.kill.side_effect = killed.set
    actual_guard = transport._wall_response_guard

    async def jumped_guard(process, seconds, audit, **_kwargs):
        return await actual_guard(
            process, seconds, audit,
            wall_clock=lambda: 1000.0,
            monotonic_clock=lambda: 10.5,
            started_at=(0.0, 10.0),
        )

    monkeypatch.setattr(transport, "_wall_response_guard", jumped_guard)
    events = [event_line(message_event("Finished.")), event_line(usage_event())]

    async def read_until_killed():
        if events:
            return events.pop(0)
        await killed.wait()
        return b""

    result = await fake.run(
        read_until_killed, finish_on_final_message=True,
        enforce_wall_response_timeout=True, timeout_seconds=90,
    )

    assert result["status"] == "failed"
    assert result["error"] == "wall_episode_timeout"
    assert result["completion_basis"] == "none"
    assert result["final_message"] == "Finished."
    assert result["wall_response_censoring"]["reason"] == "wall_episode_timeout"


async def test_legacy_structured_submission_still_completes_without_usage(fake_codex_process):
    fake_codex_process.session.submission = {}

    result = await fake_codex_process.run([])

    assert result["status"] == "complete" and result["error"] is None
    assert "completion_basis" not in result


@pytest.mark.parametrize("phase", ["monitoring", "onboarding"])
async def test_opt_in_classifies_legacy_structured_completion(fake_codex_process, phase):
    fake_codex_process.session.phase = phase
    if phase == "onboarding":
        fake_codex_process.session.setup_complete = True
        expected_basis = "setup_complete"
    else:
        fake_codex_process.session.submission = {"recorded": True}
        expected_basis = "structured_submission"

    result = await fake_codex_process.run(
        [usage_event()], finish_on_final_message=True,
    )

    assert result["status"] == "complete"
    assert result["completion_basis"] == expected_basis


@pytest.mark.parametrize("kind", ["item.started", "item.completed", "item.updated"])
async def test_activity_after_completion_cannot_inherit_earlier_final_reply(fake_codex_process, kind):
    result = await fake_codex_process.run([
        message_event("Completed readout."), usage_event(),
        {"type": kind, "item": {"id": "late-tool", "type": "mcp_tool_call", "server": "trial", "tool": "list_catalog"}},
    ], finish_on_final_message=True)
    assert result["status"] == "failed" and result["completion_basis"] == "none"
    assert result["error"] == "post_completion_item_activity"
    assert result["final_message"] == "Completed readout."


@pytest.mark.parametrize("phase", ["monitoring", "onboarding"])
async def test_structured_state_does_not_bypass_unfinished_work_guard(fake_codex_process, phase):
    fake_codex_process.session.phase = phase
    fake_codex_process.session.submission = {}
    fake_codex_process.session.setup_complete = True
    result = await fake_codex_process.run([
        {"type": "item.started", "item": {"id": "unfinished", "type": "mcp_tool_call", "server": "trial", "tool": "list_catalog"}},
        usage_event(),
    ], finish_on_final_message=True)
    assert result["status"] == "failed" and result["completion_basis"] == "none"
    assert result["error"] == "unfinished_item_activity"

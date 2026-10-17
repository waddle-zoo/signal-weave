"""Offline transport contracts; no Codex process, socket server, or Jev calls."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import tomllib

from evaluations import bootstrap_agent_trial as trial
from evaluations import codex_trial_transport as transport


def tool(name):
    return {"name": name, "description": "Offline test tool", "parameters": {"type": "object"}}


def session_stub(*, treatment=False, phase="monitoring"):
    names = ["list_catalog", "submit_analysis", "finish_setup"]
    if treatment:
        names.append("onboard_insight_card")
    return SimpleNamespace(
        treatment=treatment, phase=phase, submission=None, setup_complete=False,
        public={"brief": "Synthetic test", "numeric_vocabulary": ["delta"]}, notes="saved policy",
        adapter=SimpleNamespace(inspected={"company_mcp|offline"}, period_context={
            "period_id": "offline-period", "as_of": "2026-10-01T00:00:00+00:00",
        }),
        server=SimpleNamespace(instructions="Offline product instructions"),
        specs=AsyncMock(return_value=[tool(name) for name in names]),
        call=AsyncMock(return_value={"ok": True}),
    )


def test_child_environment_is_allowlisted_and_drops_provider_and_source_secrets(monkeypatch):
    allowed = {name: f"test-{name}" for name in (
        "HOME", "PATH", "TMPDIR", "CODEX_HOME", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR",
    )}
    secrets = {name: "fake-secret" for name in (
        "TYPESAFE_API_KEY", "TYPESAFE_API_KEY_FILE", "JEV_API_KEY", "OPENAI_API_KEY",
        "OPENAI_BASE_URL", "OPENAI_ACCESS_TOKEN", "SUPERSET_PASSWORD", "PRESET_API_TOKEN",
        "SIGNALWEAVE_API_TOKEN", "HTTP_PROXY", "UNRECOGNIZED_SECRET",
    )}
    parent = allowed | secrets
    monkeypatch.setattr(transport.os, "environ", parent)
    assert transport.child_environment() == allowed
    assert parent == allowed | secrets


def test_command_uses_isolated_read_only_trial_configuration():
    cwd, url = "/tmp/offline agent", "http://127.0.0.1:1234/opaque"
    command = transport.codex_command(cwd, url, model="offline-model", effort="low")
    assert command[:2] == ["codex", "exec"]
    assert command[-1] == "-"
    for flag in ("--ignore-user-config", "--ephemeral", "--json", "--skip-git-repo-check"):
        assert flag in command
    for flag, value in (("--sandbox", "read-only"), ("--cd", cwd), ("--model", "offline-model")):
        assert command[command.index(flag) + 1] == value
    settings = [command[i + 1] for i, arg in enumerate(command) if arg == "-c"]
    assert {
        'model_reasoning_effort="low"', 'web_search="disabled"', "project_doc_max_bytes=0",
        "features.skip_host_skill_discovery=true", "features.code_mode_host=true",
        "memories.use_memories=false", "memories.generate_memories=false", "mcp_servers={}",
        f"mcp_servers.trial.url={json.dumps(url)}", "mcp_servers.trial.required=true",
        'mcp_servers.trial.default_tools_approval_mode="approve"',
        'approval_policy="never"',
    } <= set(settings)
    assert settings.index("mcp_servers={}") < settings.index(f"mcp_servers.trial.url={json.dumps(url)}")
    disabled = {command[i + 1] for i, arg in enumerate(command) if arg == "--disable"}
    assert {
        "shell_tool", "unified_exec", "apps", "plugins", "hooks", "multi_agent",
        "browser_use", "computer_use", "image_generation", "view_image", "memories",
        "skill_search", "workspace_dependencies", "shell_snapshot", "code_mode",
        "sleep_tool", "goals",
    } <= disabled
    assert "code_mode_host" not in disabled


@pytest.mark.parametrize("treatment", [False, True])
async def test_bridge_dispatches_only_tools_in_arm_specs(treatment):
    session, audit = session_stub(treatment=treatment), trial.Audit()
    bridge = transport.TrialMCP(session, audit, await session.specs(), max_calls=4)
    listing = await bridge.server.request_handlers[transport.types.ListToolsRequest](
        transport.types.ListToolsRequest(method="tools/list"),
    )
    advertised = {item.name for item in listing.root.tools}
    assert advertised == set(bridge.specs)
    assert ("onboard_insight_card" in advertised) is treatment
    result = await bridge.call("list_catalog", {"limit": 1})
    assert not result.isError
    assert json.loads(result.content[0].text) == {"ok": True}
    session.call.assert_awaited_once_with("list_catalog", {"limit": 1})
    result = await bridge.call("onboard_insight_card", {})
    assert result.isError is (not treatment)
    result = await bridge.call("shell", {"command": "never executed"})
    assert result.isError
    assert json.loads(result.content[0].text)["message"] == "tool not available"
    assert session.call.await_count == (2 if treatment else 1)
    assert bridge.calls == len(audit.events) == 3


@pytest.mark.parametrize("phase,finish", [("onboarding", "finish_setup"), ("monitoring", "submit_analysis")])
async def test_submission_guard_serializes_concurrent_calls(phase, finish):
    session, audit = session_stub(phase=phase), trial.Audit()

    async def finish_call(name, arguments):
        await asyncio.sleep(0)  # Let the competing request reach the lock.
        if phase == "onboarding":
            session.setup_complete = True
        else:
            session.submission = {}  # Even an empty recorded submission closes the episode.
        return {"recorded": True}

    session.call.side_effect = finish_call
    bridge = transport.TrialMCP(session, audit, await session.specs(), max_calls=3)
    first, second = await asyncio.gather(bridge.call(finish, {}), bridge.call("list_catalog", {}))
    assert not first.isError
    assert second.isError
    assert "already submitted" in json.loads(second.content[0].text)["message"]
    session.call.assert_awaited_once_with(finish, {})
    assert bridge.calls == len(audit.events) == 2


async def test_completed_onboarding_does_not_block_monitoring():
    session = session_stub()
    session.setup_complete = True
    bridge = transport.TrialMCP(session, trial.Audit(), await session.specs(), max_calls=1)
    assert not (await bridge.call("list_catalog", {})).isError
    session.call.assert_awaited_once()


async def test_budget_visibility_does_not_rewrite_the_company_payload():
    session, audit = session_stub(), trial.Audit()
    bridge = transport.TrialMCP(session, audit, await session.specs(), max_calls=3,
                                report_remaining_budget=True)
    result = await bridge.call("list_catalog", {})
    assert json.loads(result.content[0].text) == {"ok": True}
    assert "2 company-tool calls remain" in result.content[1].text
    assert "reserve one" in result.content[1].text
    assert "not business/source evidence" in result.content[1].text


@pytest.mark.parametrize("max_calls", [0, 2])
async def test_call_budget_counts_rejected_tools_and_never_dispatches_over_cap(max_calls):
    session, audit = session_stub(), trial.Audit()
    bridge = transport.TrialMCP(session, audit, await session.specs(), max_calls=max_calls)
    for _ in range(max_calls):
        assert (await bridge.call("unavailable", {})).isError
    assert not bridge.exhausted  # Spending exactly the cap is permitted.
    with pytest.raises(ValueError, match="tool_call_budget_exhausted"):
        await bridge.call("list_catalog", {})
    assert bridge.exhausted
    assert bridge.calls == max_calls
    session.call.assert_not_awaited()


async def test_sdk_schema_invalid_calls_count_toward_budget_and_audit_rejections():
    session, audit = session_stub(), trial.Audit()
    specs = trial.common_tools({"owner_topics": ["materiality"], "numeric_vocabulary": ["delta"]}, "monitoring")
    bridge = transport.TrialMCP(session, audit, specs, max_calls=1)
    handler = bridge.server.request_handlers[transport.types.CallToolRequest]
    results = []
    for arguments in ({}, {"ref": 7}, {"ref": []}):
        response = await handler(transport.types.CallToolRequest(
            params=transport.types.CallToolRequestParams(name="inspect_source", arguments=arguments),
        ))
        results.append(response.root)
        assert response.root.isError
        assert bridge.calls == 1
    session.call.assert_not_awaited()
    assert bridge.exhausted
    assert json.loads(results[0].content[0].text)["error"] == "ValidationError"
    for result in results[1:]:
        assert "tool_call_budget_exhausted" in result.content[0].text
    assert [event["kind"] for event in audit.events] == ["tool.result", "tool.rejected", "tool.rejected"]
    assert audit.events[0]["arguments"] == {}
    assert audit.events[0]["result"]["error"] == "ValidationError"
    for event in audit.events[1:]:
        assert event["name"] == "inspect_source"
        assert event["reason"] == "tool_call_budget_exhausted"


async def test_sdk_infinite_submission_does_not_latch_and_finite_retry_finishes(tmp_path):
    session = session_stub()

    async def submit(name, arguments):
        # Exercise the actual submission mutation with a minimal offline session.
        return await trial.ToolSession.call(session, name, arguments)

    session.call.side_effect = submit
    audit = trial.Audit(path=tmp_path / "audit.jsonl")
    specs = trial.common_tools({"owner_topics": ["materiality"], "numeric_vocabulary": ["delta"]}, "monitoring")
    bridge = transport.TrialMCP(session, audit, specs, max_calls=2)
    handler = bridge.server.request_handlers[transport.types.CallToolRequest]
    arguments = {
        "outcome": "ignore", "recipients": [], "evidence_refs": ["company_mcp|offline"],
        "numeric_claims": [{"fact": "delta", "value": float("inf"), "unit": "number",
                            "evidence_refs": ["company_mcp|offline"]}],
        "claims": [], "summary": "Offline submission",
    }
    rejected = await handler(transport.types.CallToolRequest(
        params=transport.types.CallToolRequestParams(name="submit_analysis", arguments=arguments),
    ))
    assert rejected.root.isError
    assert "finite JSON values" in rejected.root.content[0].text
    assert session.submission is None
    session.call.assert_not_awaited()
    assert bridge.calls == 1 and not bridge.exhausted
    event, = audit.events
    assert event["kind"] == "tool.result" and event["name"] == "submit_analysis"
    assert event["arguments"] == {"invalid_json_value": True}
    assert event["result"]["error"] == "ValueError"
    assert json.loads(json.dumps(audit.events, allow_nan=False)) == audit.events

    arguments["numeric_claims"][0]["value"] = 1.0
    accepted = await handler(transport.types.CallToolRequest(
        params=transport.types.CallToolRequestParams(name="submit_analysis", arguments=arguments),
    ))
    assert not accepted.root.isError
    assert json.loads(accepted.root.content[0].text) == {"recorded": True, "delivery_enabled": False}
    session.call.assert_awaited_once_with("submit_analysis", arguments)
    assert session.submission == arguments
    assert bridge.calls == 2 and not bridge.exhausted
    assert len(audit.events) == 2
    assert audit.events[1]["arguments"] == arguments
    assert json.loads(json.dumps(audit.events, allow_nan=False)) == audit.events
    assert [json.loads(line) for line in audit.path.read_text().splitlines()] == audit.events


async def test_tool_exception_is_audited_redacted_and_returned_as_mcp_error():
    session = session_stub()
    session.call.side_effect = RuntimeError("fake-secret " + "x" * 3000)
    audit = trial.Audit(secrets=("fake-secret",))
    bridge = transport.TrialMCP(session, audit, await session.specs(), max_calls=1)
    result = await bridge.call("list_catalog", {"token": "fake-secret"})
    payload = json.loads(result.content[0].text)
    assert result.isError and payload["error"] == "RuntimeError"
    assert payload["message"].startswith("[REDACTED]")
    assert len(payload["message"]) <= 2000
    event, = audit.events
    assert event["kind"] == "tool.result" and event["name"] == "list_catalog"
    assert event["arguments"] == {"token": "[REDACTED]"}
    assert event["result"] == payload and event["seconds"] >= 0
    assert "fake-secret" not in trial.canonical(audit.events)


@pytest.fixture
def fake_episode(monkeypatch):
    session, audit = session_stub(), trial.Audit(secrets=("fake-secret",))
    budget = trial.RequestBudget(1)
    process = SimpleNamespace(
        stdin=SimpleNamespace(write=Mock(), drain=AsyncMock(), close=Mock()),
        stdout=SimpleNamespace(readline=AsyncMock()),
        stderr=SimpleNamespace(readline=AsyncMock(side_effect=[b"fake-secret\n", b""])),
        returncode=None, terminate=Mock(), kill=Mock(), wait=AsyncMock(),
    )
    state = SimpleNamespace(process=process, session=session, audit=audit, bridge=None,
                            closed=False, exit_code=0, budget=budget)

    async def wait():
        process.returncode = -9 if process.kill.called else -15 if process.terminate.called else state.exit_code
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
    monkeypatch.setattr(transport, "verify_trial_registry", AsyncMock(return_value={
        "overrides": ["mcp_servers.trial.enabled=true"], "enabled_servers": ["trial"],
        "registry": [{"name": "trial", "enabled": True}], "registry_sha256": "offline",
    }))

    async def run(events=(), **kwargs):
        episode_model = kwargs.pop("model", None)
        episode_effort = kwargs.pop("effort", "low")
        if callable(events):
            process.stdout.readline.side_effect = events
        elif events is None:
            process.stdout.readline.side_effect = asyncio.Event().wait
        else:
            process.stdout.readline.side_effect = [
                event if isinstance(event, bytes) else json.dumps(event).encode() + b"\n"
                for event in events
            ] + [b""]
        return await transport.codex_episode(
            session, key="unused", model=episode_model, effort=episode_effort,
            budget=budget, audit=audit,
            max_turns=2, max_tool_calls=3, max_output_tokens=100, **kwargs,
        )

    state.run = run
    return state


async def test_selected_model_and_effort_reach_codex_process_and_audit(fake_episode):
    result = await fake_episode.run([
        {"type": "turn.completed", "usage": {
            "input_tokens": 5, "output_tokens": 2, "cached_input_tokens": 0,
        }},
    ], model="gpt-6-luna", effort="xhigh")
    command = list(fake_episode.spawn.call_args.args)
    assert command[command.index("--model") + 1] == "gpt-6-luna"
    settings = [command[i + 1] for i, arg in enumerate(command) if arg == "-c"]
    assert 'model_reasoning_effort="xhigh"' in settings
    request = next(event for event in fake_episode.audit.events if event["kind"] == "api.request")
    response = next(event for event in fake_episode.audit.events if event["kind"] == "api.response")
    assert (request["model"], request["effort"]) == ("gpt-6-luna", "xhigh")
    assert (response["model"], response["effort"]) == ("gpt-6-luna", "xhigh")
    assert (result["model"], result["effort"]) == ("gpt-6-luna", "xhigh")


@pytest.mark.parametrize("phase", ["onboarding", "monitoring"])
@pytest.mark.parametrize("treatment", [False, True])
async def test_episode_completion_usage_and_isolated_process_cleanup(fake_episode, phase, treatment):
    fake = fake_episode
    fake.session.treatment = treatment
    fake.session.phase = phase
    fake.session.setup_complete = phase == "onboarding"
    fake.session.submission = {} if phase == "monitoring" else None
    fake.audit.emit("api.request", provider="jev", request_id=1)
    fake.audit.emit("api.request", provider="openai", request_id=-1)
    usage = {"input_tokens": 100, "cached_input_tokens": 30, "output_tokens": 10}
    result = await fake.run([{"type": "turn.completed", "usage": usage}])
    assert result["status"] == "complete" and result["error"] is None
    assert result["exit_code"] == 0 and result["transport"] == "codex_cli"
    request = next(e for e in fake.audit.events if e.get("transport") == "codex_cli")
    response = fake.audit.events[-1]
    assert request["request_id"] == response["request_id"] == -2
    assert request["accounting_unit"] == "agent_invocation"
    assert (fake.session.server.instructions in request["prompt"]) is treatment
    assert "delivery-disabled shadow evaluation" in request["prompt"]
    assert "record acceptance as unassessed" in request["prompt"]
    assert "do not invent examples" in request["prompt"]
    context = json.loads(request["prompt"].rsplit("\n", 1)[1])
    assert context["period"] == fake.session.adapter.period_context
    assert response["kind"] == "api.response"
    assert response["usage"]["input_tokens_details"] == {"cached_tokens": 30}
    assert response["usage"]["output_tokens"] == 10
    command = fake.spawn.call_args.args
    cwd = Path(command[command.index("--cd") + 1])
    assert not cwd.exists() and fake.closed
    assert fake.spawn.call_args.kwargs["env"] == {"PATH": "/offline"}
    fake.process.stdin.write.assert_called_once_with(request["prompt"].encode())
    fake.process.stdin.close.assert_called_once()
    fake.process.wait.assert_awaited_once()
    fake.process.kill.assert_not_called()
    fake.process.terminate.assert_not_called()
    assert fake.budget.used == 0
    assert "fake-secret" not in trial.canonical(fake.audit.events)


async def test_final_agent_handoff_is_preserved_in_episode_result(fake_episode):
    fake = fake_episode
    fake.session.submission = {}
    result = await fake.run([
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Submitted report."}},
        {"type": "turn.completed", "usage": {
            "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0,
        }},
    ])
    assert result["status"] == "complete"
    assert result["final_message"] == "Submitted report."


async def test_accounting_drain_records_usage_but_fails_exhausted_submission(fake_episode):
    fake = fake_episode

    async def record_submission(name, arguments):
        if name == "submit_analysis":
            fake.session.submission = {"recorded": True}
        return {"ok": True}

    fake.session.call.side_effect = record_submission
    output = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Submitted report."}},
        {"type": "turn.completed", "usage": {
            "input_tokens": 40, "output_tokens": 8, "cached_input_tokens": 0,
        }},
    ]
    first_read = True

    async def read_output():
        nonlocal first_read
        if first_read:
            first_read = False
            for name in ("list_catalog", "list_catalog", "submit_analysis"):
                result = await fake.bridge.call(name, {})
                assert not result.isError
            assert fake.session.submission == {"recorded": True}
            rejected = await fake.bridge.call("list_catalog", {})
            assert rejected.isError
            return json.dumps(output.pop(0)).encode() + b"\n"
        if output:
            return json.dumps(output.pop(0)).encode() + b"\n"
        return b""

    result = await fake.run(read_output, accounting_drain=True)

    assert result["status"] == "failed"
    assert result["error"] == "tool_call_budget_exhausted"
    assert result["tool_calls"] == 3
    assert result["final_message"] == "Submitted report."
    assert fake.bridge.exhausted and fake.bridge.rejected_calls == 1
    assert fake.session.call.await_count == 3
    assert fake.session.call.await_args_list[-1].args == ("submit_analysis", {})
    fake.process.terminate.assert_not_called()
    response = next(event for event in fake.audit.events if event["kind"] == "api.response")
    assert response["usage"]["input_tokens"] == 40
    assert response["usage"]["output_tokens"] == 8


async def test_accounting_drain_audits_cancelled_call_queued_before_dispatch():
    session, audit = session_stub(), trial.Audit()
    bridge = transport.TrialMCP(
        session, audit, await session.specs(), max_calls=2, accounting_drain=True,
    )
    ingress_seen = asyncio.Event()
    emit = audit.emit

    def signal_ingress(kind, **fields):
        emit(kind, **fields)
        if kind == "tool.ingress":
            ingress_seen.set()

    audit.emit = signal_ingress
    await bridge.lock.acquire()
    task = asyncio.create_task(bridge.call("list_catalog", {}))
    try:
        await asyncio.wait_for(ingress_seen.wait(), timeout=1)
        assert bridge.ingress_calls == 1
        assert bridge.calls == 0
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        bridge.lock.release()

    ingress, cancelled = audit.events
    assert ingress["kind"] == "tool.ingress"
    assert ingress["stage"] == "bridge_handler_entered"
    assert cancelled["kind"] == "tool.cancelled"
    assert cancelled["stage"] == "waiting_for_bridge_lock"
    assert cancelled["reason"] == "cancelled_before_dispatch"
    assert cancelled["ingress_call"] == ingress["ingress_call"] == 1
    assert bridge.calls == 0
    session.call.assert_not_awaited()


async def test_accounting_drain_aborts_after_third_refusal_without_dispatch(fake_episode):
    fake = fake_episode

    async def exhaust_and_stall():
        for _ in range(fake.bridge.max_calls):
            assert not (await fake.bridge.call("list_catalog", {})).isError
        for _ in range(transport.ACCOUNTING_DRAIN_ABORT_AFTER_REJECTIONS):
            assert (await fake.bridge.call("list_catalog", {})).isError
        assert (await fake.bridge.call("list_catalog", {})).isError
        assert fake.bridge.rejected_calls == transport.ACCOUNTING_DRAIN_ABORT_AFTER_REJECTIONS + 1
        await asyncio.Event().wait()

    result = await fake.run(exhaust_and_stall, accounting_drain=True)

    assert result["status"] == "failed"
    assert result["error"] == "tool_call_budget_exhausted"
    assert fake.bridge.calls == fake.bridge.max_calls == 3
    assert fake.bridge.rejected_calls == transport.ACCOUNTING_DRAIN_ABORT_AFTER_REJECTIONS + 1
    assert fake.bridge.rejection_limit_event.is_set()
    assert fake.session.call.await_count == 3
    assert sum(event["kind"] == "tool.rejected" for event in fake.audit.events) == 4
    fake.process.terminate.assert_called_once()
    assert fake.audit.events[-1]["kind"] == "api.error"
    assert fake.audit.events[-1]["usage_known"] is False


async def test_parallel_overbudget_calls_are_all_counted_and_audited():
    session, audit = session_stub(), trial.Audit()
    bridge = transport.TrialMCP(
        session, audit, await session.specs(), max_calls=1, accounting_drain=True,
    )
    rejection_event_states = []
    emit = audit.emit

    def record_rejection_event_state(kind, **fields):
        emit(kind, **fields)
        if kind == "tool.rejected":
            rejection_event_states.append(bridge.rejection_limit_event.is_set())

    audit.emit = record_rejection_event_state
    assert not (await bridge.call("list_catalog", {})).isError

    results = await asyncio.gather(*(
        bridge.call("list_catalog", {}) for _ in range(4)
    ))

    assert all(result.isError for result in results)
    assert bridge.calls == 1
    assert bridge.ingress_calls == 5
    assert bridge.rejected_calls == 4
    assert bridge.rejection_limit_event.is_set()
    assert rejection_event_states == [False, False, True, True]
    assert sum(event["kind"] == "tool.ingress" for event in audit.events) == 5
    assert sum(event["kind"] == "tool.rejected" for event in audit.events) == 4
    session.call.assert_awaited_once_with("list_catalog", {})


@pytest.mark.parametrize("event,expected_error", [
    ({"type": "turn.completed", "usage": {}}, "invalid_usage"),
    ({"type": "turn.completed"}, "missing_usage"),
    ({"type": "turn.completed", "usage": {
        "input_tokens": 5, "output_tokens": 2,
    }}, "invalid_usage"),
    ({"type": "turn.completed", "usage": {
        "input_tokens": True, "output_tokens": 2, "cached_input_tokens": 0,
    }}, "invalid_usage"),
    ({"type": "turn.completed", "usage": {
        "input_tokens": 5, "output_tokens": False, "cached_input_tokens": 0,
    }}, "invalid_usage"),
    ({"type": "turn.completed", "usage": {
        "input_tokens": 5, "output_tokens": 2, "cached_input_tokens": True,
    }}, "invalid_usage"),
    ({"type": "turn.completed", "usage": {
        "input_tokens": -1, "output_tokens": 2, "cached_input_tokens": 0,
    }}, "invalid_usage"),
    ({"type": "turn.completed", "usage": {
        "input_tokens": 5, "output_tokens": 2, "cached_input_tokens": -1,
    }}, "invalid_usage"),
    ({"type": "turn.completed", "usage": {
        "input_tokens": 5, "output_tokens": 2, "cached_input_tokens": 6,
    }}, "invalid_usage"),
])
@pytest.mark.parametrize("accounting_drain", [False, True])
async def test_malformed_usage_is_unknown_and_raw_event_is_preserved(
        fake_episode, event, expected_error, accounting_drain):
    result = await fake_episode.run([event], accounting_drain=accounting_drain)

    assert result["status"] == "failed"
    assert any(audit_event.get("kind") == "codex.event"
               and audit_event.get("event") == event
               for audit_event in fake_episode.audit.events)
    assert fake_episode.audit.events[-1]["kind"] == "api.error"
    assert fake_episode.audit.events[-1]["error_type"] == expected_error
    assert fake_episode.audit.events[-1]["usage_known"] is False
    assert not any(audit_event.get("kind") == "api.response"
                   for audit_event in fake_episode.audit.events)


async def test_accounting_drain_timeout_retains_unknown_usage(fake_episode, monkeypatch):
    fake = fake_episode
    monkeypatch.setattr(transport, "ACCOUNTING_DRAIN_SECONDS", .01)

    async def exhaust_and_stall():
        for _ in range(fake.bridge.max_calls):
            await fake.bridge.call("list_catalog", {})
        await fake.bridge.call("list_catalog", {})
        await asyncio.Event().wait()

    result = await fake.run(exhaust_and_stall, accounting_drain=True)

    assert result["status"] == "failed"
    assert result["error"] == "tool_call_budget_exhausted"
    assert fake.session.call.await_count == 3
    fake.process.terminate.assert_called_once()
    assert fake.audit.events[-1]["kind"] == "api.error"
    assert fake.audit.events[-1]["usage_known"] is False


async def test_accounting_drain_stays_inside_outer_episode_deadline(fake_episode):
    fake = fake_episode

    async def exhaust_and_stall():
        for _ in range(fake.bridge.max_calls):
            await fake.bridge.call("list_catalog", {})
        await fake.bridge.call("list_catalog", {})
        await asyncio.Event().wait()

    result = await fake.run(exhaust_and_stall, accounting_drain=True, timeout_seconds=.01)

    assert result["status"] == "failed" and result["error"] == "episode_timeout"
    assert fake.bridge.exhausted
    fake.process.kill.assert_called_once()
    assert fake.audit.events[-1]["kind"] == "api.error"
    assert fake.audit.events[-1]["usage_known"] is False


async def test_foreign_tool_still_aborts_immediately_during_accounting_drain(fake_episode):
    fake = fake_episode

    async def exhaust_then_report_foreign_tool():
        for _ in range(fake.bridge.max_calls):
            await fake.bridge.call("list_catalog", {})
        await fake.bridge.call("list_catalog", {})
        return json.dumps({"type": "item.completed", "item": {
            "type": "command_execution",
        }}).encode() + b"\n"

    result = await fake.run(exhaust_then_report_foreign_tool, accounting_drain=True)

    assert result["status"] == "failed" and result["error"] == "foreign_tool_used"
    assert result["foreign_tools"] == ["command_execution"]
    fake.process.terminate.assert_called_once()
    assert fake.audit.events[-1]["kind"] == "api.error"
    assert fake.audit.events[-1]["usage_known"] is False


async def test_default_episode_keeps_immediate_budget_hard_stop(fake_episode):
    fake = fake_episode

    async def exhaust_then_return_message():
        for _ in range(fake.bridge.max_calls):
            await fake.bridge.call("list_catalog", {})
        with pytest.raises(ValueError, match="tool_call_budget_exhausted"):
            await fake.bridge.call("list_catalog", {})
        return json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "This should not be drained.",
        }}).encode() + b"\n"

    result = await fake.run(exhaust_then_return_message)

    assert result["status"] == "failed" and result["error"] == "tool_call_budget_exhausted"
    assert result["final_message"] == "This should not be drained."
    fake.process.terminate.assert_called_once()
    assert fake.audit.events[-1]["kind"] == "api.error"
    assert fake.audit.events[-1]["usage_known"] is False


async def test_custom_episode_preserves_precomputed_signalweave_bundle(fake_episode):
    fake = fake_episode
    fake.session.submission = {}
    bundle = {"status": "complete", "evidence": [{"source_key": "company_mcp|offline"}],
              "outcome": "investigate"}
    result = await fake.run(
        [{"type": "turn.completed", "usage": {
            "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0,
        }}],
        instructions_override="Custom episode instructions",
        prompt_override={"brief": "same brief"},
        bundle=bundle,
    )
    assert result["status"] == "complete"
    request = next(e for e in fake.audit.events if e.get("transport") == "codex_cli")
    context = json.loads(request["prompt"].rsplit("\n", 1)[1])
    assert context == {"brief": "same brief", "signalweave_evaluation": bundle}


async def test_treatment_bundle_prompt_requires_full_numeric_provenance(fake_episode):
    fake = fake_episode
    fake.session.treatment = True
    fake.session.phase = "monitoring"
    fake.session.setup_complete = True
    fake.session.submission = {}
    bundle = {
        "result": {
            "outcome": "notify",
            "report": {
                "provenance": [{
                    "source_key": "primary", "comparison_key": "collections",
                    "query_refs": ["trino|receipts", "airflow|watermark"],
                }],
            },
        },
    }
    await fake.run(
        [{"type": "turn.completed", "usage": {
            "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0,
        }}],
        bundle=bundle,
    )
    request = next(e for e in fake.audit.events if e.get("transport") == "codex_cli")
    assert "copy every adapter|resource ref" in request["prompt"]
    assert "quality or completeness sources" in request["prompt"]


@pytest.mark.parametrize("event,expected", [
    ({"type": "turn.failed"}, "codex_error"),
    ({"type": "error"}, "codex_error"),
    *[({"type": "item.completed", "item": {"type": kind}}, "foreign_tool_used")
      for kind in ("command_execution", "web_search", "file_change")],
    ({"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "other"}}, "foreign_tool_used"),
    ({"type": "item.started", "item": {"type": "mcp_tool_call", "server": "codex",
                                         "tool": "list_mcp_resources", "arguments": {}}}, "foreign_tool_used"),
])
async def test_episode_rejects_failure_and_foreign_tools_even_after_submission(fake_episode, event, expected):
    fake = fake_episode
    fake.session.submission = {}
    result = await fake.run([event])
    assert result["status"] == "failed" and result["error"] == expected
    fake.process.terminate.assert_called_once()
    fake.process.wait.assert_awaited_once()
    assert fake.closed
    assert fake.audit.events[-1]["kind"] == "api.error"
    assert fake.audit.events[-1]["usage_known"] is False


@pytest.mark.parametrize("tool", ["list_mcp_resources", "list_mcp_resource_templates"])
@pytest.mark.parametrize("server", ["codex", "trial"])
async def test_scoped_builtin_resource_discovery_is_explicit_and_counted_once(fake_episode, tool, server):
    fake = fake_episode
    fake.session.submission = {"summary": "Synthetic completed result"}
    item = {"type": "mcp_tool_call", "server": server, "tool": tool, "id": "metadata-1", "arguments": {}}
    result = await fake.run([
        {"type": "item.started", "item": item}, {"type": "item.completed", "item": item},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0}},
    ], allow_trial_resource_discovery=True)
    assert result["status"] == "complete" and not result["foreign_tools"]
    assert result["resource_discovery_calls"] == 1
    assert len([e for e in fake.audit.events if e["kind"] == "codex.resource_discovery"]) == 1
    fake.process.terminate.assert_not_called()


async def test_valid_resource_discovery_still_requires_explicit_protocol_opt_in(fake_episode):
    item = {"type": "mcp_tool_call", "server": "codex", "tool": "list_mcp_resources", "id": "one", "arguments": {}}
    result = await fake_episode.run([{"type": "item.started", "item": item}])
    assert result["status"] == "failed" and result["foreign_tools"] == ["codex"]
    assert result["resource_discovery_calls"] == 0


@pytest.mark.parametrize("change", [
    {"tool": "read_mcp_resource"}, {"tool": "arbitrary_builtin"}, {"server": "other"},
    {"arguments": {"server": "other"}}, {"arguments": {"uri": "private://data"}},
    {"arguments": {"server": {}}}, {"arguments": None}, {"id": None},
])
async def test_discovery_opt_in_does_not_allow_foreign_resources_or_other_builtin_tools(fake_episode, change):
    item = {"type": "mcp_tool_call", "server": "codex", "tool": "list_mcp_resources", "id": "one", "arguments": {}}
    item.update(change)
    result = await fake_episode.run([{"type": "item.started", "item": item}], allow_trial_resource_discovery=True)
    assert result["status"] == "failed" and result["resource_discovery_calls"] == 0
    fake_episode.process.terminate.assert_called_once()


async def test_resource_discovery_has_a_separate_small_audited_budget(fake_episode):
    events = [{"type": "item.started", "item": {"type": "mcp_tool_call", "server": "codex",
              "tool": "list_mcp_resources", "id": f"metadata-{n}", "arguments": {}}}
              for n in range(transport.MAX_RESOURCE_DISCOVERY_CALLS + 1)]
    result = await fake_episode.run(events, allow_trial_resource_discovery=True)
    assert result["status"] == "failed"
    assert result["foreign_tools"] == ["resource_discovery_budget_exhausted"]
    assert result["resource_discovery_calls"] == transport.MAX_RESOURCE_DISCOVERY_CALLS
    assert result["resource_discovery_attempts"] == transport.MAX_RESOURCE_DISCOVERY_CALLS + 1
    assert result["observed_tool_calls_including_discovery"] == transport.MAX_RESOURCE_DISCOVERY_CALLS + 1


async def test_registry_probe_disables_merged_entries_without_leaking_credentials(monkeypatch):
    outputs = [json.dumps([{"name": "company.private", "enabled": True, "secret": "never-log-this", "transport": {"type": "stdio"}}]).encode(),
               json.dumps([{"name": "company.private", "enabled": False, "transport": {"type": "stdio"}}, {"name": "trial", "enabled": True, "transport": {"type": "streamable_http"}}]).encode()]
    calls = []

    async def spawn(*command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(outputs.pop(0), None)))

    monkeypatch.setattr(transport.asyncio, "create_subprocess_exec", spawn)
    proof = await transport.verify_trial_registry("/offline/codex", "/offline", "http://127.0.0.1:1/trial")
    assert '"company.private"={enabled=false,command="signalweave-disabled-no-launch"}' in proof["overrides"][0]
    assert proof["overrides"][0] in calls[1]
    assert proof["enabled_servers"] == ["trial"]
    assert "never-log-this" not in json.dumps(proof)
    configured = tomllib.loads(proof["overrides"][0])["mcp_servers"]
    assert configured["company.private"]["enabled"] is False
    assert configured["trial"]["required"] is True
    assert configured["trial"]["default_tools_approval_mode"] == "approve"


@pytest.mark.parametrize("first,second", [
    ([{"name": "trial", "enabled": True, "transport": {"type": "stdio"}}], []),
    ([{"name": "other", "enabled": True, "transport": {"type": "stdio"}}], [{"name": "other", "enabled": True, "transport": {"type": "stdio"}}, {"name": "trial", "enabled": True, "transport": {"type": "streamable_http"}}]),
    ([{"name": "other", "enabled": "yes"}], []),
])
async def test_registry_probe_rejects_collisions_or_nonisolated_effective_state(monkeypatch, first, second):
    outputs = [json.dumps(first).encode(), json.dumps(second).encode()]

    async def spawn(*command, **kwargs):
        return SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(outputs.pop(0), None)))

    monkeypatch.setattr(transport.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ValueError):
        await transport.verify_trial_registry("/offline/codex", "/offline", "http://127.0.0.1:1/trial")


async def test_changed_registry_fails_before_any_frontier_process_is_spawned(fake_episode):
    with pytest.raises(ValueError, match="changed after preflight"):
        await fake_episode.run([], allow_trial_resource_discovery=True, expected_registry_sha256="different")
    fake_episode.spawn.assert_not_awaited()


async def test_strict_single_completion_usage_does_not_silently_replace_a_second_turn(fake_episode):
    fake_episode.session.submission = {"message": "synthetic report"}
    completion = {"type": "turn.completed", "usage": {"input_tokens": 20, "cached_input_tokens": 5, "output_tokens": 2}}
    result = await fake_episode.run([completion, completion], strict_single_turn_usage=True)
    assert result["status"] == "failed" and result["error"] == "ambiguous_codex_turn_usage"
    assert len(result["completion_usage_reports"]) == 2
    assert fake_episode.audit.events[-1]["kind"] == "api.error"
    assert fake_episode.audit.events[-1]["usage_known"] is False


@pytest.mark.parametrize("exit_code,error", [(0, "no_structured_submission"), (7, "codex_exit")])
async def test_trial_tool_event_alone_is_not_submission(fake_episode, exit_code, error):
    fake_episode.exit_code = exit_code
    result = await fake_episode.run([
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "trial"}},
    ])
    assert result["status"] == "failed" and result["error"] == error
    assert result["foreign_tools"] == []
    assert fake_episode.audit.events[-1]["error_type"] == "missing_usage"


async def test_episode_timeout_kills_process_and_closes_server(fake_episode):
    result = await fake_episode.run(None, timeout_seconds=.01)
    assert result["status"] == "failed" and result["error"] == "episode_timeout"
    fake_episode.process.kill.assert_called_once()
    fake_episode.process.wait.assert_awaited_once()
    assert fake_episode.closed
    assert fake_episode.audit.events[-1]["error_type"] == "episode_timeout"


@pytest.mark.parametrize("accounting_drain", [False, True])
async def test_opt_in_wall_deadline_reaches_episode_result_without_inventing_usage(fake_episode, monkeypatch, accounting_drain):
    killed = asyncio.Event()
    fake_episode.process.kill.side_effect = killed.set
    actual_guard = transport._wall_response_guard

    async def jumped_guard(process, seconds, audit):
        wall, monotonic = iter([0.0, 1000.0]), iter([10.0, 10.5])
        return await actual_guard(process, seconds, audit,
            wall_clock=lambda: next(wall), monotonic_clock=lambda: next(monotonic))

    async def output_after_kill():
        await killed.wait()
        return b""

    monkeypatch.setattr(transport, "_wall_response_guard", jumped_guard)
    result = await fake_episode.run(output_after_kill, timeout_seconds=90,
        accounting_drain=accounting_drain, enforce_wall_response_timeout=True)
    assert result["status"] == "failed" and result["error"] == "wall_episode_timeout"
    assert result["wall_response_censoring"]["wall_elapsed_seconds"] == 1000
    assert result["wall_response_censoring"]["monotonic_elapsed_seconds"] == .5
    assert result["wall_response_timeout_enabled"] is True
    assert result["completion_usage_reports"] == []
    assert fake_episode.audit.events[-1]["usage_known"] is False
    fake_episode.process.kill.assert_called_once()
    assert fake_episode.closed


async def test_exhausted_jev_budget_does_not_abort_codex_agent(fake_episode):
    fake_episode.budget.exhausted = True
    fake_episode.session.phase = "onboarding"
    fake_episode.session.setup_complete = True
    result = await fake_episode.run([{"type": "turn.completed", "usage": {
        "input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 0,
    }}])
    assert result["status"] == "complete" and result["error"] is None
    fake_episode.process.terminate.assert_not_called()
    assert fake_episode.closed


async def test_malformed_json_still_cleans_up_process_and_server(fake_episode):
    result = await fake_episode.run([b"not-json\n"])
    assert result["status"] == "failed" and result["error"] == "JSONDecodeError"
    fake_episode.process.kill.assert_called_once()
    fake_episode.process.wait.assert_awaited_once()
    assert fake_episode.closed


async def test_malformed_stdout_retains_already_spent_tools_and_timeout_scope(fake_episode):
    fake = fake_episode

    async def readline():
        await fake.bridge.call("list_catalog", {})
        return b"invalid-json\n"

    fake.process.stdout.readline.side_effect = readline
    result = await transport.codex_episode(fake.session, key="unused", effort="low",
        budget=fake.budget, audit=fake.audit, max_turns=1, max_tool_calls=3,
        max_output_tokens=100, timeout_seconds=90)
    assert result["status"] == "failed" and result["tool_calls"] == 1
    assert result["error"] == "JSONDecodeError"
    assert result["response_timeout_seconds"] == 90
    assert "excluding_startup_and_cleanup" in result["timeout_scope"]
    assert result["wall_time_overrun_seconds"] == max(0, result["seconds"] - 90)
    assert any(e["kind"] == "tool.result" and e["actor_role"] == "author" for e in fake.audit.events)
    assert fake.audit.events[-1]["kind"] == "api.error"

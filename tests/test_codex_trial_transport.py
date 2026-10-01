"""Offline transport contracts; no Codex process, socket server, or Jev calls."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

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
        adapter=SimpleNamespace(period_context={
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

    async def run(events=(), **kwargs):
        if events is None:
            process.stdout.readline.side_effect = asyncio.Event().wait
        else:
            process.stdout.readline.side_effect = [
                event if isinstance(event, bytes) else json.dumps(event).encode() + b"\n"
                for event in events
            ] + [b""]
        return await transport.codex_episode(
            session, key="unused", effort="low", budget=budget, audit=audit,
            max_turns=2, max_tool_calls=3, max_output_tokens=100, **kwargs,
        )

    state.run = run
    return state


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


@pytest.mark.parametrize("event,expected", [
    ({"type": "turn.failed"}, "codex_error"),
    ({"type": "error"}, "codex_error"),
    *[({"type": "item.completed", "item": {"type": kind}}, "foreign_tool_used")
      for kind in ("command_execution", "web_search", "file_change")],
    ({"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "other"}}, "foreign_tool_used"),
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


async def test_exhausted_shared_budget_stops_process(fake_episode):
    fake_episode.budget.exhausted = True
    result = await fake_episode.run([{"type": "turn.started"}])
    assert result["status"] == "failed" and result["error"] == "budget_exhausted"
    fake_episode.process.terminate.assert_called_once()
    assert fake_episode.closed


async def test_malformed_json_still_cleans_up_process_and_server(fake_episode):
    with pytest.raises(json.JSONDecodeError):
        await fake_episode.run([b"not-json\n"])
    fake_episode.process.kill.assert_called_once()
    fake_episode.process.wait.assert_awaited_once()
    assert fake_episode.closed

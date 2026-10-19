"""Offline boundaries for the installed evaluation transport."""

import asyncio
import json
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from evaluations import bootstrap_agent_trial as trial
from evaluations import installed_trial_transport as transport
from evaluations.bootstrap_scenarios import build_scenarios, public_scenario
from signalweave.mcp_source import MCPConnection


@pytest.mark.asyncio
async def test_facade_reads_only_through_the_initialized_source_session():
    reply = SimpleNamespace(contents=[{"text": "source-owned definition"}])
    session = SimpleNamespace(read_resource=AsyncMock(return_value=reply))
    facade = transport.InstalledServer(session, "", trial.Audit())

    assert await facade.read_resource("company://definitions") is reply
    session.read_resource.assert_awaited_once_with("company://definitions")
    session.read_resource.side_effect = ValueError("source resource is unavailable")
    with pytest.raises(ValueError, match="source resource is unavailable"):
        await facade.read_resource("company://definitions")


@pytest.mark.asyncio
async def test_embedded_source_server_does_not_replace_controller_signals():
    public = public_scenario(build_scenarios()[0])
    audit = trial.Audit()
    adapter = trial.PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    adapter.set_period(public["onboarding"], datetime.now(timezone.utc))
    handlers = {value: signal.getsignal(value) for value in (signal.SIGINT, signal.SIGTERM)}
    source = transport._SourceSession(adapter, audit, public["scenario_id"])
    async with transport._source_server(source):
        assert {value: signal.getsignal(value) for value in handlers} == handlers
    assert {value: signal.getsignal(value) for value in handlers} == handlers


def test_manifest_uses_real_tenant_and_only_catalog_resources():
    public = {
        "scenario_id": "company-real",
        "catalog": [
            {
                "adapter": "company_mcp",
                "resource": "resource-1",
                "kind": "chart",
                "title": "Current source",
                "contract": {"authorized": True},
            }
        ],
    }
    manifest = transport._manifest(public, "http://127.0.0.1:1234/random")
    connection = manifest["connections"][0]
    assert connection["tenant_id"] == "company-real"
    assert connection["transport"]["url"].endswith("random")
    assert connection["resources"][0]["arguments"] == {"ref": "company_mcp|resource-1"}
    assert "periods" not in json.dumps(manifest)


def test_manifest_preserves_and_validates_mixed_native_adapter_identities():
    public = {
        "scenario_id": "company-mixed-sources",
        "catalog": [
            {"adapter": "stripe", "resource": "payments", "kind": "table", "title": "Payments"},
            {"adapter": "superset", "resource": "sales-chart", "kind": "chart", "title": "Sales"},
            {"adapter": "stripe", "resource": "refunds", "kind": "table", "title": "Refunds"},
        ],
    }

    manifest = transport._manifest(public, "http://127.0.0.1:1234/private-route")

    assert [item["name"] for item in manifest["connections"]] == ["stripe", "superset"]
    assert [
        resource["arguments"]["ref"]
        for connection in manifest["connections"]
        for resource in connection["resources"]
    ] == ["stripe|payments", "stripe|refunds", "superset|sales-chart"]
    for connection in manifest["connections"]:
        MCPConnection.model_validate(connection)


def test_minimal_environment_drops_unintended_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "never")
    monkeypatch.setenv("TYPESAFE_API_KEY", "never")
    monkeypatch.setenv("HTTP_PROXY", "never")
    environment = transport._minimal_environment(tmp_path)
    assert "OPENAI_API_KEY" not in environment
    assert "TYPESAFE_API_KEY" not in environment
    assert "HTTP_PROXY" not in environment
    assert environment["TYPESAFE_MAX_RETRIES"] == "0"


@pytest.mark.asyncio
async def test_setup_failure_reports_bounded_redacted_child_diagnostics(monkeypatch, tmp_path):
    binary = tmp_path / "private" / "signalweave"
    root = tmp_path / "private" / "trial"
    home = root / "home"
    key = root / "typesafe.key"
    manifest = root / "company-mcp.json"
    credential = "never-print-this-key"
    captured = {}

    def fail(command, *, cwd, env, **kwargs):
        captured.update(command=command, cwd=cwd, env=env, kwargs=kwargs)
        return subprocess.CompletedProcess(
            command,
            17,
            stdout=f"setup could not read {manifest}; credential={credential}",
            stderr=f"permission denied at {home}; TYPESAFE_API_KEY=echoed-secret",
        )

    monkeypatch.setattr(transport.subprocess, "run", fail)
    audit = trial.Audit(secrets=(credential,))
    with pytest.raises(RuntimeError, match="exit_code=17") as error:
        await transport._run_setup(binary, root, home, key, manifest, "tenant", audit)

    message = str(error.value)
    assert "could not read [PRIVATE_MANIFEST]" in message
    assert "permission denied at [PRIVATE_HOME]" in message
    assert credential not in message
    assert "echoed-secret" not in message
    assert str(root) not in message and str(home) not in message
    assert captured["cwd"] == str(root)
    assert captured["env"]["HOME"] == str(home)
    assert captured["command"][captured["command"].index("--key-file") + 1] == str(key)
    assert "TYPESAFE_API_KEY" not in captured["env"]
    assert captured["kwargs"]["capture_output"] is True


@pytest.mark.asyncio
async def test_setup_timeout_includes_bounded_child_output(monkeypatch, tmp_path):
    paths = [tmp_path / part for part in ("binary", "root", "home", "key", "manifest")]
    binary, root, home, key, manifest = paths
    long_output = "x" * (transport.SETUP_DIAGNOSTIC_CHARS + 500)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 90, output=long_output, stderr="still waiting")

    monkeypatch.setattr(transport.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out after 90 seconds") as error:
        await transport._run_setup(binary, root, home, key, manifest, "tenant", trial.Audit())
    message = str(error.value)
    assert "still waiting" in message
    assert message.count("x") <= transport.SETUP_DIAGNOSTIC_CHARS + 40


def test_source_session_reads_through_adapter_and_audits(tmp_path):
    audit = trial.Audit()
    adapter = Mock(spec=trial.PublicSourceAdapter)
    snapshot = Mock()
    snapshot.model_dump.return_value = {"adapter": "company_mcp", "resource": "r"}
    adapter.inspect = AsyncMock(return_value=snapshot)
    session = transport._SourceSession(adapter, audit, "company")

    import asyncio

    asyncio.run(session.read_snapshot({"ref": "company_mcp|r"}))
    adapter.inspect.assert_awaited_once()


@pytest.mark.asyncio
async def test_facade_raises_on_mcp_error_and_preserves_success():
    session = AsyncMock()
    facade = transport.InstalledServer(
        session, "instructions", trial.Audit(secrets=("do-not-log",))
    )
    session.call_tool.return_value = Mock(
        isError=True,
        structuredContent=None,
        content=[Mock(model_dump=lambda mode: {"type": "text", "text": "do-not-log"})],
    )
    with pytest.raises(RuntimeError, match="returned an error") as error:
        await facade.call_tool("x", {})
    assert "do-not-log" not in str(error.value)
    session.call_tool.return_value = Mock(
        isError=False, content=[Mock(text='{"ok": true}')], structuredContent=None
    )
    assert (await facade.call_tool("x", {}))[1] == {"ok": True}


@pytest.mark.asyncio
async def test_mcp_initialize_has_bounded_handshake_timeout(monkeypatch):
    session = AsyncMock()

    async def hang():
        await asyncio.sleep(10)

    session.initialize.side_effect = hang
    monkeypatch.setattr(transport, "MCP_INITIALIZE_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(RuntimeError, match="initialize timed out"):
        await transport._initialize_mcp_session(session)
    session.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_jev_proxy_rejects_wrong_method_and_budget_before_upstream(monkeypatch):
    audit, budget = trial.Audit(), trial.RequestBudget(0)
    proxy = transport._JevProxy(audit, budget)

    async def invoke(method, body=b"{}"):
        scope = {
            "type": "http",
            "method": method,
            "path": f"/{proxy.route}/v1/systemone",
            "path_params": {"route": proxy.route},
            "headers": [],
            "query_string": b"",
            "app": SimpleNamespace(state=SimpleNamespace(proxy=proxy)),
        }

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        response = await transport._jev_proxy_handler(transport.Request(scope, receive))
        return response

    response = await invoke("GET")
    assert response.status_code == 404
    response = await invoke("POST", b'{"state": {}, "questions": {}}')
    assert response.status_code == 429
    assert budget.used == 0 and budget.exhausted
    assert [event["kind"] for event in audit.events] == ["api.rejected"]


@pytest.mark.asyncio
async def test_jev_proxy_forwards_only_fixed_endpoint_rejects_redirect_and_redacts_audit(
    monkeypatch,
):
    audit, budget = trial.Audit(secrets=("body-secret",)), trial.RequestBudget(1)
    proxy = transport._JevProxy(audit, budget)
    seen = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, path, *, content, headers):
            seen.update(path=path, content=content, headers=headers)
            return httpx.Response(307, headers={"location": "https://not-allowed.example"})

    monkeypatch.setattr(transport.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/{proxy.route}/v1/systemone",
        "path_params": {"route": proxy.route},
        "headers": [(b"authorization", b"Bearer body-secret")],
        "query_string": b"",
        "app": SimpleNamespace(state=SimpleNamespace(proxy=proxy)),
    }

    async def receive():
        return {
            "type": "http.request",
            "body": b'{"model":"jev-x","state":"body-secret","questions":{"q":{}}}',
            "more_body": False,
        }

    response = await transport._jev_proxy_handler(transport.Request(scope, receive))
    assert response.status_code == 502
    assert seen["path"] == "/v1/systemone"
    assert seen["headers"]["authorization"] == "Bearer body-secret"
    assert "body-secret" not in json.dumps(audit.events)
    assert budget.used == 1


@pytest.mark.asyncio
async def test_jev_proxy_audits_full_typed_response_and_uses_global_budget_id(monkeypatch):
    audit, budget = trial.Audit(), trial.RequestBudget(3, used=1)
    proxy = transport._JevProxy(audit, budget)
    response_payload = {
        "model": "jev-resolved",
        "nouls": {"q": {"noul": 0.9, "probability": 0.9}},
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }

    class FakeResponse:
        status_code, content, headers = 200, json.dumps(response_payload).encode(), {}
        is_redirect, is_success = False, True

        def json(self):
            return response_payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, path, *, content, headers):
            return FakeResponse()

    monkeypatch.setattr(transport.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/{proxy.route}/v1/systemone",
        "path_params": {"route": proxy.route},
        "headers": [],
        "query_string": b"",
        "app": SimpleNamespace(state=SimpleNamespace(proxy=proxy)),
    }

    async def receive():
        return {
            "type": "http.request",
            "body": b'{"state":{},"questions":{"q":{}}}',
            "more_body": False,
        }

    await transport._jev_proxy_handler(transport.Request(scope, receive))
    event = next(item for item in audit.events if item["kind"] == "api.response")
    assert event["request_id"] == 2
    assert event["response"] == response_payload
    assert event["usage"] == response_payload["usage"]


@pytest.mark.asyncio
async def test_installed_binary_is_opt_in(tmp_path):
    binary = os.environ.get("SIGNALWEAVE_TEST_BINARY")
    if not binary:
        pytest.skip("set SIGNALWEAVE_TEST_BINARY to run the real executable")
    binary_path = Path(binary).resolve()
    assert binary_path.is_file() and os.access(binary_path, os.X_OK)
    public = public_scenario(build_scenarios(split="dev")[0])
    audit = trial.Audit()
    adapter = trial.PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    adapter.set_period(public["onboarding"], datetime.now(timezone.utc))
    key_file = tmp_path / "input.key"
    key_file.write_text("offline-packaging-check-not-a-real-key\n")
    key_file.chmod(0o600)
    async with transport.installed_server(
        binary=binary_path,
        key_file=key_file,
        public=public,
        adapter=adapter,
        audit=audit,
        budget=trial.RequestBudget(0),
        work=tmp_path / "work",
    ) as server:
        tools = await server.list_tools()
        assert any(tool.name == "get_signalweave_guide" for tool in tools)
    assert not any(
        event.get("provider") == "jev" and event["kind"] == "api.request" for event in audit.events
    )

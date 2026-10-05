import json
import subprocess

import pytest

from signalweave import client_setup


def completed(returncode=0, *, stdout="", stderr=""):
    return subprocess.CompletedProcess(["agent"], returncode, stdout, stderr)


def inventory(home, *, enabled=True, command=None, args=None, env=None, cwd=None,
              enabled_tools=None, disabled_tools=None):
    entry = json.loads(client_setup.agent_config(home, "claude"))["mcpServers"]["signalweave"]
    return json.dumps([{
        "name": "signalweave",
        "enabled": enabled,
        "enabled_tools": enabled_tools,
        "disabled_tools": disabled_tools,
        "transport": {
            "type": "stdio",
            "command": command if command is not None else entry["command"],
            "args": args if args is not None else entry["args"],
            "env": env,
            "env_vars": [],
            "cwd": cwd,
        },
    }])


def test_codex_registers_only_after_missing_inventory_and_verifies_post_add(monkeypatch, tmp_path):
    home = tmp_path / "private home"
    calls = []

    def run(argv):
        calls.append(argv)
        if len(calls) == 1:
            return completed(stdout="[]")
        if len(calls) == 3:
            return completed(stdout=inventory(home))
        return completed()

    monkeypatch.setattr(client_setup, "_run", run)
    result = client_setup.register_agent(home, "codex")

    assert result.outcome == "registered"
    assert calls[0] == ["codex", "mcp", "list", "--json"]
    assert calls[1][:5] == ["codex", "mcp", "add", "signalweave", "--"]
    assert calls[2] == ["codex", "mcp", "list", "--json"]
    assert "--home" in calls[1]


def test_exact_existing_codex_entry_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        client_setup, "_run", lambda argv: completed(stdout=inventory(tmp_path))
    )

    result = client_setup.register_agent(tmp_path, "codex")

    assert result.outcome == "already_configured"


@pytest.mark.parametrize("variant", [
    {"enabled": False},
    {"env": {"SECRET": "nope"}},
    {"args": ["different"]},
    {"cwd": "/tmp/elsewhere"},
    {"enabled_tools": ["safe_tool"]},
    {"disabled_tools": ["dangerous_tool"]},
])
def test_existing_different_disabled_or_credential_bearing_entry_is_conflict(monkeypatch, tmp_path, variant):
    monkeypatch.setattr(
        client_setup,
        "_run",
        lambda argv: completed(stdout=inventory(tmp_path, **variant)),
    )

    result = client_setup.register_agent(tmp_path, "codex")

    assert result.outcome == "conflict"
    assert result.changed is False


@pytest.mark.parametrize("payload", [
    "not json",
    "{}",
    "[{\"name\": \"signalweave\"}, {\"name\": \"signalweave\"}]",
    "[{\"name\": 4}]",
])
def test_malformed_or_ambiguous_inventory_does_not_mutate(monkeypatch, tmp_path, payload):
    calls = []
    monkeypatch.setattr(
        client_setup, "_run", lambda argv: calls.append(argv) or completed(stdout=payload)
    )

    result = client_setup.register_agent(tmp_path, "codex")

    assert result.outcome == "unavailable"
    assert len(calls) == 1
    assert payload not in result.message


def test_inventory_error_does_not_treat_config_error_as_absence(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        client_setup,
        "_run",
        lambda argv: calls.append(argv) or completed(2, stderr="config file missing; token=secret"),
    )

    result = client_setup.register_agent(tmp_path, "codex")

    assert result.outcome == "unavailable"
    assert "secret" not in result.message
    assert len(calls) == 1


@pytest.mark.parametrize("fail_on", [1, 2])
def test_invalid_cli_encoding_returns_safe_failure(monkeypatch, tmp_path, fail_on):
    calls = []

    def run(argv):
        calls.append(argv)
        if len(calls) == fail_on:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid output")
        return completed(stdout="[]")

    monkeypatch.setattr(client_setup, "_run", run)
    result = client_setup.register_agent(tmp_path, "codex")
    assert result.outcome == ("unavailable" if fail_on == 1 else "failed")
    assert len(calls) == fail_on


def test_post_add_verification_failure_is_reported_without_raw_output(monkeypatch, tmp_path):
    calls = []

    def run(argv):
        calls.append(argv)
        if len(calls) == 1:
            return completed(stdout="[]")
        if len(calls) == 2:
            return completed()
        return completed(stdout=json.dumps([{"name": "signalweave", "enabled": False}]), stderr="secret")

    monkeypatch.setattr(client_setup, "_run", run)
    result = client_setup.register_agent(tmp_path, "codex")

    assert result.outcome == "failed"
    assert "secret" not in result.message
    assert len(calls) == 3


def test_cli_run_is_bounded_scrubbed_and_noninteractive(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNALWEAVE_API_TOKEN", "hidden")
    monkeypatch.setenv("TYPESAFE_API_KEY", "hidden")
    monkeypatch.setenv("SIGNALWEAVE_HOME", "preserved-runtime-setting")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "preserved-agent-setting")
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return completed(stdout="[]")

    monkeypatch.setattr(client_setup.subprocess, "run", run)
    client_setup.read_agent_status(tmp_path, "codex")

    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["stdin"] is subprocess.DEVNULL
    assert seen["kwargs"]["timeout"] == 5.0
    assert "SIGNALWEAVE_API_TOKEN" not in seen["kwargs"]["env"]
    assert "TYPESAFE_API_KEY" not in seen["kwargs"]["env"]
    assert seen["kwargs"]["env"]["SIGNALWEAVE_HOME"] == "preserved-runtime-setting"
    assert seen["kwargs"]["env"]["ANTHROPIC_API_KEY"] == "preserved-agent-setting"


def test_claude_registration_uses_official_cli_without_exposing_output(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        client_setup,
        "_run",
        lambda argv: calls.append(argv) or completed(stdout="SignalWeave added"),
    )

    result = client_setup.register_agent(tmp_path / "home", "claude")

    assert result.outcome == "registered"
    entry = json.loads(client_setup.agent_config(tmp_path / "home", "claude"))["mcpServers"]["signalweave"]
    assert calls == [[
        "claude", "mcp", "add", "--transport", "stdio", "--scope", "user",
        "signalweave", "--", entry["command"], *entry["args"],
    ]]


def test_claude_registration_failure_keeps_manual_command(monkeypatch, tmp_path):
    monkeypatch.setattr(client_setup, "_run", lambda argv: completed(1, stderr="existing entry"))

    result = client_setup.register_agent(tmp_path / "home", "claude")

    assert result.outcome == "conflict"
    assert result.command.startswith("claude mcp add")
    assert result.changed is False


def test_timeout_and_missing_cli_are_bounded_and_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(client_setup, "_run", lambda argv: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 5)))
    result = client_setup.read_agent_status(tmp_path, "codex")
    assert result.outcome == "unavailable"
    assert "timed out" in result.message

    monkeypatch.setattr(client_setup, "_run", lambda argv: (_ for _ in ()).throw(FileNotFoundError()))
    result = client_setup.read_agent_status(tmp_path, "codex")
    assert result.outcome == "unavailable"
    assert "not found" in result.message


def test_invalid_agent_is_rejected(tmp_path):
    with pytest.raises(client_setup.SetupError, match="codex or claude"):
        client_setup.register_agent(tmp_path, "other")

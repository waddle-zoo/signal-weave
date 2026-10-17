import json
import sys

import pytest

import signalweave.cli as cli
from signalweave import local_setup as setup


@pytest.fixture
def local_home(monkeypatch, tmp_path):
    for name in setup._ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("SIGNALWEAVE_HOME", raising=False)
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: "test-context-cli-key")
    home = setup.initialize(tmp_path / "context home")
    home, _ = setup.setup_local(
        home=home,
        source="skip",
        tenant="test-tenant",
        principal="test-principal",
        non_interactive=True,
    )
    return home


def _run_cli(monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", ["signalweave", *map(str, arguments)])
    cli.main()


def _files_except_config(home):
    return {
        path.relative_to(home): path.read_bytes()
        for path in home.rglob("*")
        if path.is_file() and path.name != "config.toml"
    }


def test_context_enable_disable_persist_only_the_flag_and_explain_restart(
    local_home, monkeypatch, capsys,
):
    monkeypatch.setattr(cli, "build_runtime", lambda **_kwargs: pytest.fail("must not build a runtime"))
    before_environment = setup.read_config(local_home)[1]
    before_other_files = _files_except_config(local_home)

    _run_cli(monkeypatch, "context", "enable", "--home", local_home)

    enabled_environment = setup.read_config(local_home)[1]
    assert enabled_environment["SIGNALWEAVE_KNOWLEDGE_ENABLED"] == "1"
    assert {key: value for key, value in enabled_environment.items()
            if key != "SIGNALWEAVE_KNOWLEDGE_ENABLED"} == before_environment
    assert _files_except_config(local_home) == before_other_files
    enabled_output = capsys.readouterr().out
    assert "Saved domain-context setting: enabled" in enabled_output
    assert enabled_output.index("Saved domain-context setting") < enabled_output.index("status: enabled")
    assert "Effective domain-context configuration:" in enabled_output
    assert "does not check live health" in enabled_output
    assert "Restart or reconnect" in enabled_output

    _run_cli(monkeypatch, "context", "disable", "--home", local_home)

    disabled_environment = setup.read_config(local_home)[1]
    assert disabled_environment["SIGNALWEAVE_KNOWLEDGE_ENABLED"] == "0"
    assert {key: value for key, value in disabled_environment.items()
            if key != "SIGNALWEAVE_KNOWLEDGE_ENABLED"} == before_environment
    assert _files_except_config(local_home) == before_other_files
    disabled_output = capsys.readouterr().out
    assert "Saved domain-context setting: disabled" in disabled_output
    assert disabled_output.index("Saved domain-context setting") < disabled_output.index("status: disabled")
    assert "Stored domain context, cards, and history are kept." in disabled_output
    assert "Restart or reconnect" in disabled_output


def test_context_status_json_is_configuration_only_and_does_not_start_provider(
    local_home, monkeypatch, capsys,
):
    monkeypatch.setattr(cli, "build_runtime", lambda **_kwargs: pytest.fail("must not build a runtime"))
    _run_cli(monkeypatch, "context", "enable", "--home", local_home)
    capsys.readouterr()

    _run_cli(monkeypatch, "context", "status", "--home", local_home, "--json")

    report = json.loads(capsys.readouterr().out)
    assert set(report) == {
        "configured", "enabled", "status", "environment_override", "reason", "scope",
    }
    assert report["configured"] is True
    assert report["enabled"] is True
    assert report["status"] == "enabled"
    assert report["environment_override"] is False
    assert "configuration" in report["scope"].lower()


def test_context_status_reports_environment_override(local_home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_runtime", lambda **_kwargs: pytest.fail("must not build a runtime"))
    _run_cli(monkeypatch, "context", "enable", "--home", local_home)
    capsys.readouterr()
    monkeypatch.setenv("SIGNALWEAVE_KNOWLEDGE_ENABLED", "0")

    _run_cli(monkeypatch, "context", "status", "--home", local_home, "--json")
    report = json.loads(capsys.readouterr().out)
    assert report["environment_override"] is True
    assert report["enabled"] is False

    _run_cli(monkeypatch, "context", "status", "--home", local_home)
    output = capsys.readouterr().out
    assert "environment override: yes" in output
    assert "does not check live health" in output


def test_context_enable_without_setup_returns_a_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_runtime", lambda **_kwargs: pytest.fail("must not build a runtime"))
    home = tmp_path / "missing home"

    with pytest.raises(SystemExit) as stopped:
        _run_cli(monkeypatch, "context", "enable", "--home", home)

    assert stopped.value.code == 1
    error = capsys.readouterr().err
    assert "SignalWeave setup error:" in error
    assert home.exists() is False


def test_context_commands_are_discoverable_from_help(monkeypatch, capsys):
    with pytest.raises(SystemExit) as root_help:
        _run_cli(monkeypatch, "--help")
    assert root_help.value.code == 0
    assert "context" in capsys.readouterr().out

    with pytest.raises(SystemExit) as context_help:
        _run_cli(monkeypatch, "context", "--help")
    assert context_help.value.code == 0
    output = capsys.readouterr().out
    assert "enable" in output
    assert "disable" in output
    assert "status" in output


def test_general_status_prints_context_fields_only_when_present(capsys):
    cli._print_status({"status": "ready_for_agent"})
    assert "Domain context:" not in capsys.readouterr().out

    cli._print_status({
        "status": "ready_for_agent",
        "domain_context": {
            "configured": True,
            "enabled": False,
            "status": "blocked",
            "environment_override": True,
            "reason": "An environment setting overrides the saved preference.",
            "secret": "test-only-secret-must-not-print",
        },
    })
    output = capsys.readouterr().out
    assert "configured: yes" in output
    assert "enabled: no" in output
    assert "status: blocked" in output
    assert "environment override: yes" in output
    assert "An environment setting overrides the saved preference." in output
    assert "test-only-secret-must-not-print" not in output

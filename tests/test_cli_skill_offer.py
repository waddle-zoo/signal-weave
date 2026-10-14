import io

import pytest

import signalweave.cli as cli
from signalweave import client_setup, skill_install
from signalweave.client_setup import AgentRegistrationStatus
from signalweave.local_setup import initialize


class TerminalInput(io.StringIO):
    def isatty(self):
        return True


class PipedInput(io.StringIO):
    def isatty(self):
        return False


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SIGNALWEAVE_HOME", raising=False)


def _saved_home(tmp_path):
    key_file = tmp_path / "typesafe.key.input"
    key_file.write_text("test-key\n", encoding="utf-8")
    key_file.chmod(0o600)
    return initialize(tmp_path / "private-signalweave", key_file=key_file)


def _registered(monkeypatch):
    calls = []

    def register(home, selected):
        calls.append((home, selected))
        return AgentRegistrationStatus(selected, "registered", f"Registered {selected}")

    monkeypatch.setattr(client_setup, "register_agent", register)
    return calls


@pytest.mark.parametrize(
    ("agent", "agent_directory"),
    [
        ("codex", ".agents"),
        ("claude", ".claude"),
    ],
)
def test_connect_prompts_after_registration_and_installs_exact_user_skill(
    monkeypatch,
    tmp_path,
    capsys,
    agent,
    agent_directory,
):
    home = _saved_home(tmp_path)
    config_before = (home / "config.toml").read_bytes()
    calls = _registered(monkeypatch)
    monkeypatch.setattr(cli.sys, "stdin", TerminalInput("\n"))
    monkeypatch.setattr(cli.sys, "argv", ["signalweave", "connect", agent, "--home", str(home)])

    cli.main()

    target = tmp_path / agent_directory / "skills" / "signalweave"
    assert calls == [(home, agent)]
    assert (target / "SKILL.md").read_bytes() == skill_install.skill_text().encode()
    assert (home / "config.toml").read_bytes() == config_before
    output = capsys.readouterr().out
    assert (
        f"Install the bundled SignalWeave skill for {agent.title()} in your user scope at {target}? [Y/n]: "
        in output
    )
    assert output.index(f"Registered {agent}") < output.index(
        "Install the bundled SignalWeave skill"
    )
    assert "SignalWeave skill installed:" in output
    assert not (tmp_path / ".codex" / "config.toml").exists()
    assert not (tmp_path / ".claude" / "settings.json").exists()


def test_noninteractive_setup_prints_command_without_installing_skill(
    monkeypatch,
    tmp_path,
    capsys,
):
    key_file = tmp_path / "jev-key"
    key_file.write_text("test-key\n", encoding="utf-8")
    key_file.chmod(0o600)
    calls = _registered(monkeypatch)
    monkeypatch.setattr(cli.sys, "stdin", PipedInput(""))
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "signalweave",
            "setup",
            "--home",
            str(tmp_path / "saved-setup"),
            "--non-interactive",
            "--key-file",
            str(key_file),
            "--source",
            "skip",
            "--agent",
            "codex",
            "--register-agent",
        ],
    )

    cli.main()

    target = tmp_path / ".agents" / "skills" / "signalweave"
    assert calls == [(tmp_path / "saved-setup", "codex")]
    assert not target.exists()
    output = capsys.readouterr().out
    assert f"at {target}" in output
    assert "`signalweave skills install --agent codex --scope user`" in output
    assert "Install the bundled SignalWeave skill" not in output


def test_skill_conflict_is_actionable_and_keeps_saved_setup_and_skill_untouched(
    monkeypatch,
    tmp_path,
    capsys,
):
    home = _saved_home(tmp_path)
    config_before = (home / "config.toml").read_bytes()
    calls = _registered(monkeypatch)
    target = tmp_path / ".agents" / "skills" / "signalweave"
    target.mkdir(parents=True)
    existing_skill = target / "SKILL.md"
    existing_skill.write_text("user-owned skill\n", encoding="utf-8")
    monkeypatch.setattr(cli.sys, "stdin", TerminalInput("\n"))
    monkeypatch.setattr(cli.sys, "argv", ["signalweave", "connect", "codex", "--home", str(home)])

    cli.main()

    output = capsys.readouterr().out
    assert calls == [(home, "codex")]
    assert (home / "config.toml").read_bytes() == config_before
    assert existing_skill.read_text(encoding="utf-8") == "user-owned skill\n"
    assert str(target) in output
    assert "Existing skill contents were not overwritten" in output
    assert "resolve any conflict or permission issue" in output
    assert "`signalweave skills install --agent codex --scope user`" in output
    assert "skill was not installed" in output


def test_permission_error_does_not_abort_or_undo_connection(
    monkeypatch,
    tmp_path,
    capsys,
):
    home = _saved_home(tmp_path)
    config_before = (home / "config.toml").read_bytes()
    calls = _registered(monkeypatch)
    monkeypatch.setattr(cli.sys, "stdin", TerminalInput("\n"))
    monkeypatch.setattr(cli.sys, "argv", ["signalweave", "connect", "codex", "--home", str(home)])

    def denied(*_args, **_kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(skill_install, "install_skill", denied)
    cli.main()

    output = capsys.readouterr().out
    assert calls == [(home, "codex")]
    assert (home / "config.toml").read_bytes() == config_before
    assert "permission denied" in output
    assert "Existing skill contents were not overwritten" in output
    assert "`signalweave skills install --agent codex --scope user`" in output

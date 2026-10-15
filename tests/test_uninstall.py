import io
import sys
from pathlib import Path

import pytest

from signalweave import cli, local_setup
from signalweave import uninstall as module


@pytest.fixture
def installation(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.delenv("SIGNALWEAVE_HOME", raising=False)
    binary = user / ".local" / "bin" / "signalweave"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"native fixture")
    binary.chmod(0o755)
    key = tmp_path / "external-key"
    key.write_text("private-test-key")
    key.chmod(0o600)
    home = local_setup.initialize(key_file=key)
    (home / "state" / "cards.json").write_text('{"preserve": true}')
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(binary))
    return binary, home, key


def test_default_removes_only_executable(installation, capsys):
    binary, home, key = installation
    assert module.uninstall(yes=True)
    assert not binary.exists()
    assert (home / "typesafe.key").exists()
    assert (home / "state" / "cards.json").exists()
    assert key.exists()
    output = capsys.readouterr().out
    assert "private-test-key" not in output
    assert "codex mcp remove signalweave" in output


def test_purge_removes_only_owned_home(installation):
    binary, home, key = installation
    neighbor = home.parent / "unrelated"
    neighbor.write_text("keep")
    assert module.uninstall(purge=True, yes=True)
    assert not binary.exists() and not home.exists()
    assert key.exists() and neighbor.read_text() == "keep"


def test_cancel_changes_nothing(installation, monkeypatch):
    binary, home, _ = installation
    monkeypatch.setattr(sys, "stdin", type("Terminal", (), {"isatty": lambda _: True})())
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert not module.uninstall(purge=True)
    assert binary.exists() and home.exists()


def test_noninteractive_requires_yes(installation, monkeypatch):
    binary, home, _ = installation
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    with pytest.raises(local_setup.SetupError, match="confirmation"):
        module.uninstall(purge=True)
    assert binary.exists() and home.exists()


def test_python_install_never_deletes_interpreter(installation, monkeypatch):
    binary, home, _ = installation
    monkeypatch.setattr(sys, "frozen", False)
    with pytest.raises(local_setup.SetupError, match="package manager"):
        module.uninstall(purge=True, yes=True)
    assert binary.exists() and home.exists()


@pytest.mark.parametrize("target", ["user", "cwd", "ancestor"])
def test_broad_purge_is_rejected(installation, monkeypatch, target):
    binary, home, _ = installation
    candidate = {"user": Path.home(), "cwd": Path.cwd(), "ancestor": home.parent.parent}[target]
    with pytest.raises(local_setup.SetupError):
        module.uninstall(candidate, purge=True, yes=True)
    assert binary.exists() and home.exists()


def test_non_signalweave_directory_is_rejected(installation, tmp_path):
    binary, home, _ = installation
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    with pytest.raises(local_setup.SetupError):
        module.uninstall(other, purge=True, yes=True)
    assert binary.exists() and home.exists() and other.exists()


@pytest.mark.parametrize("kind", ["home", "child", "binary", "parent"])
def test_symlinks_are_rejected(installation, tmp_path, monkeypatch, kind):
    binary, home, key = installation
    if kind == "home":
        link = tmp_path / "home-link"
        link.symlink_to(home, target_is_directory=True)
        home_arg = link
    elif kind == "child":
        (home / "external").symlink_to(key)
        home_arg = home
    elif kind == "binary":
        link = tmp_path / "signalweave"
        link.symlink_to(binary)
        monkeypatch.setattr(sys, "executable", str(link))
        home_arg = home
    else:
        link = tmp_path / "bin-link"
        link.symlink_to(binary.parent, target_is_directory=True)
        monkeypatch.setattr(sys, "executable", str(link / "signalweave"))
        home_arg = home
    with pytest.raises(local_setup.SetupError, match="symlink"):
        module.uninstall(home_arg, purge=True, yes=True)
    assert binary.exists() and home.exists() and key.exists()


def test_repository_inside_home_is_rejected(installation):
    binary, home, _ = installation
    (home / "state" / ".git").mkdir()
    with pytest.raises(local_setup.SetupError, match="repository"):
        module.uninstall(purge=True, yes=True)
    assert binary.exists() and home.exists()


def test_valid_home_nested_in_repository_is_rejected(installation):
    binary, home, _ = installation
    (home.parent / ".git").write_text("gitdir: /unrelated/worktree")
    with pytest.raises(local_setup.SetupError, match="repository"):
        module.uninstall(purge=True, yes=True)
    assert binary.exists() and home.exists()


def test_cli_routes_uninstall_without_runtime(installation, monkeypatch):
    binary, home, _ = installation
    monkeypatch.setattr(sys, "argv", ["signalweave", "uninstall", "--yes"])
    monkeypatch.setattr(cli, "build_runtime", lambda **_: pytest.fail("must not initialize runtime"))
    cli.main()
    assert not binary.exists() and home.exists()

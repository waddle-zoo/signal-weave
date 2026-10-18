"""Offline permission-profile and workspace validation contracts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import tomllib

from evaluations.codex_workspace import (
    PROFILE,
    sandbox_command,
    validate_workspace,
    workspace_settings,
)


def private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def test_validate_workspace_returns_canonical_owned_private_directory(tmp_path):
    workspace = private_dir(tmp_path / "workspace")
    assert validate_workspace(workspace / ".." / "workspace") == workspace.resolve()


def test_validate_workspace_rejects_missing_paths_files_symlinks_and_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_workspace(tmp_path / "missing")

    ordinary_file = tmp_path / "file"
    ordinary_file.write_text("fixture")
    ordinary_file.chmod(0o700)
    with pytest.raises(ValueError, match="directory"):
        validate_workspace(ordinary_file)

    target = private_dir(tmp_path / "target")
    link = tmp_path / "workspace-link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        validate_workspace(link)

    with pytest.raises(ValueError, match="root"):
        validate_workspace(Path("/"))


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o500])
def test_validate_workspace_rejects_non_0700_permissions(tmp_path, mode):
    workspace = private_dir(tmp_path / "workspace")
    workspace.chmod(mode)
    with pytest.raises(ValueError, match="0700"):
        validate_workspace(workspace)


def test_validate_workspace_rejects_a_directory_not_owned_by_current_user(tmp_path, monkeypatch):
    workspace = private_dir(tmp_path / "workspace")
    monkeypatch.setattr(os, "getuid", lambda: workspace.stat().st_uid + 1)
    with pytest.raises(ValueError, match="owned"):
        validate_workspace(workspace)


def test_workspace_settings_are_exact_private_and_network_disabled(tmp_path):
    workspace = private_dir(tmp_path / 'study "quoted" \\ path 🧪')
    settings = workspace_settings(workspace)
    config = tomllib.loads("\n".join(settings))

    assert config["default_permissions"] == PROFILE
    profile = config["permissions"][PROFILE]
    assert profile["filesystem"] == {":minimal": "read", str(workspace.resolve()): "write"}
    assert profile["network"] == {"enabled": False}
    assert ":root" not in profile["filesystem"]
    assert len(settings) == 3


def test_sandbox_command_uses_exact_profile_overrides_and_preserves_argv(tmp_path):
    workspace = private_dir(tmp_path / "workspace")
    argv = ["python", "-c", "print('one argument')", "space kept"]
    command = sandbox_command("/opt/codex", workspace, argv)
    separator = command.index("--")
    settings = [command[index + 1] for index, value in enumerate(command[:separator])
                if value == "-c"]

    assert command[:6] == ["/opt/codex", "sandbox", "-P", PROFILE, "-C", str(workspace.resolve())]
    assert command[-len(argv) - 1:] == ["--", *argv]
    assert settings == workspace_settings(workspace)


@pytest.mark.parametrize("argv", [[], "python -V", ["python", 3]])
def test_sandbox_command_requires_an_explicit_string_argv(tmp_path, argv):
    workspace = private_dir(tmp_path / "workspace")
    with pytest.raises(ValueError, match="sequence of strings"):
        sandbox_command("codex", workspace, argv)

"""Evaluation-only helpers for launching Codex in one private workspace."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path

PROFILE = "signalweave-study"


def validate_workspace(path: str | os.PathLike[str]) -> Path:
    """Return a canonical existing directory owned by this user with mode 0700."""
    supplied = Path(path)
    try:
        supplied_info = supplied.lstat()
    except FileNotFoundError:
        raise
    if stat.S_ISLNK(supplied_info.st_mode):
        raise ValueError("workspace root must not be a symlink")

    canonical = supplied.resolve(strict=True)
    info = canonical.stat()
    if canonical == Path(canonical.anchor):
        raise ValueError("filesystem root cannot be a workspace")
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("workspace must be a directory")
    if info.st_uid != os.getuid():
        raise ValueError("workspace must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("workspace permissions must be exactly 0700")
    return canonical


def workspace_settings(
    path: str | os.PathLike[str], *, readonly_paths: Sequence[str | os.PathLike[str]] = (),
) -> list[str]:
    """Build per-command TOML overrides for the named, network-disabled profile."""
    workspace = validate_workspace(path)
    filesystem = {
        json.dumps(":minimal", ensure_ascii=False): json.dumps("read"),
        json.dumps(str(workspace), ensure_ascii=False): json.dumps("write"),
    }
    if not isinstance(readonly_paths, Sequence) or isinstance(readonly_paths, (str, bytes)):
        raise ValueError("readonly_paths must be an explicit sequence of paths")
    for supplied in readonly_paths:
        candidate = Path(supplied)
        if not candidate.is_absolute() or candidate.is_symlink():
            raise ValueError("Read grants require absolute, non-symlink paths")
        canonical = candidate.resolve(strict=True)
        if canonical == workspace or canonical in workspace.parents:
            raise ValueError("Read grants must not expose a workspace ancestor or replace workspace writes")
        filesystem[json.dumps(str(canonical), ensure_ascii=False)] = json.dumps("read")
    filesystem_value = "{" + ", ".join(
        f"{key} = {value}" for key, value in filesystem.items()
    ) + "}"
    return [
        f"default_permissions = {json.dumps(PROFILE, ensure_ascii=False)}",
        f"permissions.{PROFILE}.filesystem = {filesystem_value}",
        f"permissions.{PROFILE}.network.enabled = false",
    ]


def sandbox_command(
    executable: str | os.PathLike[str],
    path: str | os.PathLike[str],
    argv: Sequence[str],
    *, readonly_paths: Sequence[str | os.PathLike[str]] = (),
) -> list[str]:
    """Return an argv vector for the pinned generic Codex sandbox command."""
    if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError("argv must be a nonempty sequence of strings")
    executable_text = os.fspath(executable)
    if not executable_text:
        raise ValueError("executable must not be empty")

    workspace = validate_workspace(path)
    command = [executable_text, "sandbox", "-P", PROFILE, "-C", str(workspace)]
    for setting in workspace_settings(workspace, readonly_paths=readonly_paths):
        command.extend(["-c", setting])
    return [*command, "--", *argv]

"""Validation helpers for the bounded onedir native installation layout."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

MANAGED_RUNTIME_PARENT = ".signalweave-runtime"
MANAGED_MARKER_NAME = "install-marker"
MANAGED_MARKER_CONTENT = b"signalweave-managed-runtime-v1\n"
MAX_MANAGED_RUNTIMES = 128
_RUNTIME_NAME = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:rc[0-9]+)?\.[A-Za-z0-9]{8}\Z")


def _fail(message: str) -> NoReturn:
    # Keep this import lazy so local_setup can safely import command_path.
    from .local_setup import SetupError

    raise SetupError(message)


@dataclass(frozen=True)
class ManagedInstall:
    launcher: Path
    runtime_root: Path
    runtime_dirs: tuple[Path, ...]
    current_runtime: Path


def render_launcher(native_binary: Path) -> str:
    """Render the stable shell launcher for an absolute native executable path."""
    absolute = Path(os.path.abspath(native_binary))
    value = str(absolute)
    if "\x00" in value:
        raise ValueError("native executable path cannot contain a NUL byte")
    escaped = (
        value.replace("\\", "\\\\")
        .replace("$", "\\$")
        .replace('"', '\\"')
        .replace("`", "\\`")
    )
    return f'#!/bin/sh\n# SignalWeave managed runtime v1\nexec "{escaped}" "$@"\n'


def _lstat(path: Path, description: str) -> os.stat_result:
    try:
        return path.lstat()
    except OSError:
        _fail(f"Managed install {description} is missing or unreadable")


def _check_no_symlink_parents(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except OSError:
            _fail("Managed install paths are missing or unreadable")
        if stat.S_ISLNK(info.st_mode):
            _fail("Managed install paths must not contain symlinks")


def _check_owned_directory(path: Path, description: str) -> None:
    info = _lstat(path, description)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        _fail(f"Managed install {description} must be a directory owned by the current user")


def _check_owned_executable(path: Path, description: str) -> os.stat_result:
    info = _lstat(path, description)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or not info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    ):
        _fail(f"Managed install {description} must be an executable owned by the current user")
    return info


def _check_owned_regular(path: Path, description: str) -> os.stat_result:
    info = _lstat(path, description)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        _fail(f"Managed install {description} must be a regular file owned by the current user")
    return info


def _read_limited(path: Path, limit: int, description: str) -> bytes:
    try:
        with path.open("rb") as source:
            contents = source.read(limit + 1)
    except OSError:
        _fail(f"Managed install {description} is unreadable")
    if len(contents) > limit:
        _fail(f"Managed install {description} is too large")
    return contents


def _check_runtime_marker(runtime: Path) -> None:
    _check_owned_directory(runtime, "runtime")
    marker = runtime / MANAGED_MARKER_NAME
    marker_info = _check_owned_regular(marker, "marker")
    if marker_info.st_size != len(MANAGED_MARKER_CONTENT):
        _fail("Managed install marker does not match the expected version")
    marker_contents = _read_limited(marker, len(MANAGED_MARKER_CONTENT), "marker")
    if marker_contents != MANAGED_MARKER_CONTENT:
        _fail("Managed install marker does not match the expected version")


def _check_runtime_contents(runtime: Path) -> None:
    _check_runtime_marker(runtime)

    def unreadable(_error: OSError) -> None:
        _fail("Managed runtime contents are unreadable")

    for directory, folders, files in os.walk(runtime, followlinks=False, onerror=unreadable):
        for name in (*folders, *files):
            path = Path(directory) / name
            info = _lstat(path, "runtime contents")
            if stat.S_ISLNK(info.st_mode):
                _fail("Managed runtime contents must not contain symlinks")
            if info.st_uid != os.getuid() or not (
                stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
            ):
                _fail("Managed runtime contents must be regular files or directories owned by the current user")


def inspect_managed_install(
    binary: Path, *, include_retained: bool = True
) -> ManagedInstall | None:
    """Validate and describe the managed install containing the running binary.

    A ``None`` result means the executable is not in the managed path hierarchy;
    malformed or unsafe managed-looking installations raise ``SetupError``.
    ``include_retained=False`` validates only the current runtime for fast command
    registration; uninstall uses the full bounded tree scan by default.
    """
    binary = Path(os.path.abspath(binary))
    if binary.name != "signalweave" or binary.parent.parent.name != MANAGED_RUNTIME_PARENT:
        return None

    runtime = binary.parent
    runtime_root = runtime.parent
    bin_directory = runtime_root.parent
    launcher = bin_directory / "signalweave"

    if not _RUNTIME_NAME.fullmatch(runtime.name):
        _fail("Managed runtime directory name is invalid")
    _check_no_symlink_parents(binary)
    _check_owned_directory(bin_directory, "bin directory")
    _check_owned_directory(runtime_root, "runtime directory")
    _check_owned_executable(binary, "native executable")
    if include_retained:
        _check_runtime_contents(runtime)
    else:
        _check_runtime_marker(runtime)

    expected_launcher = render_launcher(binary).encode("utf-8")
    launcher_info = _check_owned_executable(launcher, "launcher")
    if launcher_info.st_size != len(expected_launcher):
        _fail("Managed launcher changed; refusing to uninstall")
    launcher_contents = _read_limited(launcher, len(expected_launcher), "launcher")
    if launcher_contents != expected_launcher:
        _fail("Managed launcher changed; refusing to uninstall")

    if include_retained:
        runtime_dirs: list[Path] = []
        try:
            with os.scandir(runtime_root) as entries:
                for entry in entries:
                    if not _RUNTIME_NAME.fullmatch(entry.name):
                        continue
                    candidate = runtime_root / entry.name
                    runtime_dirs.append(candidate)
                    if len(runtime_dirs) > MAX_MANAGED_RUNTIMES:
                        _fail("Managed install has more than 128 version directories; refusing to uninstall")
                    if candidate != runtime:
                        _check_runtime_contents(candidate)
        except OSError:
            _fail("Managed runtime directory is unreadable")

        runtime_dirs.sort()
        if runtime not in runtime_dirs:
            _fail("Current executable is not in a verified managed runtime")
    else:
        runtime_dirs = [runtime]
    return ManagedInstall(launcher, runtime_root, tuple(runtime_dirs), runtime)


def command_path(executable: Path) -> Path:
    """Return the stable registered command for a managed install.

    Unmanaged invocations retain their supplied path exactly, including relative
    paths used by Python virtual environments.
    """
    managed = inspect_managed_install(executable, include_retained=False)
    return managed.launcher if managed is not None else executable

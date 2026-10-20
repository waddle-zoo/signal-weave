"""Explicit native uninstall; preserve local state unless purge is requested."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import sys
from pathlib import Path

from .local_setup import SetupError, read_config, resolve_home
from .managed_install import inspect_managed_install


def _check_binary(binary: Path) -> None:
    if binary.name != "signalweave" or binary.is_symlink():
        raise SetupError("Uninstall requires the regular native signalweave executable, not a symlink")
    info = binary.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise SetupError("Uninstall requires a native executable owned by the current user")
    for parent in binary.parents:
        if parent.is_symlink():
            raise SetupError("Refusing to uninstall through a symlinked directory")


def _check_purge(root: Path, binary: Path) -> None:
    # Never recursively remove a home, checkout, environment, or its ancestors.
    protected = (Path.home().resolve(), Path.cwd().resolve(), binary.resolve(), Path(sys.prefix).resolve())
    if any(root == item or root in item.parents for item in protected):
        raise SetupError("Refusing to purge a home, working directory, executable, or environment")
    if any((parent / ".git").exists() or (parent / ".git").is_symlink() for parent in (root, *root.parents)):
        raise SetupError("Refusing to purge a local home inside a repository")
    read_config(root)  # Requires a private, owned SignalWeave config and state directory.
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in [*folders, *files]:
            path = Path(directory) / name
            info = path.lstat()
            if name == ".git" or stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
            ) or info.st_uid != os.getuid():
                raise SetupError("Purge refused: local home contains a repository, symlink, special file, or foreign-owned file")


def uninstall(home: str | Path | None = None, *, purge: bool = False, yes: bool = False) -> bool:
    """Remove only the running frozen binary; never delete a Python interpreter."""
    if not getattr(sys, "frozen", False):
        raise SetupError(
            "Self-uninstall is for the native executable. For a Python installation, "
            "use the same package manager that installed signal-weave (pip or uv tool)."
        )
    binary = Path(os.path.abspath(sys.executable))
    root = resolve_home(home)
    managed = inspect_managed_install(binary, include_retained=True)
    if managed is None:
        _check_binary(binary)
    if purge and root.exists():
        _check_purge(root, binary)
    elif purge and root.is_symlink():
        raise SetupError("Refusing to purge a symlink")

    print("Stop running SignalWeave servers and restart your agent after uninstalling.")
    print("Remove the MCP connection with your agent's CLI, if registered:")
    print("  codex mcp remove signalweave")
    print("  claude mcp remove --scope user signalweave")
    print("Agent configuration, agent credentials, and installed workflow skills are not edited.")
    if managed is None:
        print(f"Remove executable: {binary}")
    else:
        print(f"Remove command launcher: {managed.launcher}")
        for runtime in managed.runtime_dirs:
            print(f"Remove managed runtime: {runtime}")
    if purge:
        print(f"Permanently remove local configuration, credentials, cards, and receipts: {root}")
        print("External credential files and remote authorizations are not removed or revoked.")
    else:
        print(f"Keep local configuration, credentials, cards, and receipts: {root}")
    if not yes:
        if not sys.stdin.isatty():
            raise SetupError("Uninstall needs confirmation; use --yes only after reviewing the paths")
        try:
            answer = input("Uninstall SignalWeave? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Canceled; nothing was removed.")
            return False

    # Recheck immediately before mutation. Managed deletion stays within verified
    # version directories; the containing runtime root is removed only if empty.
    if managed is None:
        _check_binary(binary)
    else:
        current_plan = inspect_managed_install(binary, include_retained=True)
        if current_plan != managed:
            raise SetupError("Managed install changed after review; refusing to uninstall")
    if purge and root.exists():
        _check_purge(root, binary)
        shutil.rmtree(root)
        print("Local data removed permanently; recovery requires your own backup.")
    if managed is None:
        binary.unlink()
        print("SignalWeave executable removed. Reinstall to restore the command.")
    else:
        for runtime in managed.runtime_dirs:
            shutil.rmtree(runtime)
        managed.launcher.unlink()
        try:
            managed.runtime_root.rmdir()
        except OSError as error:
            if error.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                raise
        print("SignalWeave launcher and managed runtimes removed. Reinstall to restore the command.")
    return True

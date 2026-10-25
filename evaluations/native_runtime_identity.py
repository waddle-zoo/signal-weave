"""Read-only, bounded identity for the runtime beside a verified native binary."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

MAX_RUNTIME_MEMBERS = 20_000
MAX_RUNTIME_BYTES = 512_000_000
_HASH_CHUNK_BYTES = 1024 * 1024


def _fingerprint(layout: str, external_runtime_used: bool,
                 members: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {
            "format": "native-runtime-identity-v1",
            "bundle_layout": layout,
            "external_runtime_used": external_runtime_used,
            "members": members,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _hash_regular_file(path: Path, expected: os.stat_result) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("Runtime file could not be opened safely") from error

    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode)
                or (before.st_dev, before.st_ino) != (expected.st_dev, expected.st_ino)):
            raise ValueError("Runtime member changed or is not a regular file")

        digest = hashlib.sha256()
        byte_count = 0
        while chunk := os.read(descriptor, _HASH_CHUNK_BYTES):
            byte_count += len(chunk)
            if byte_count > MAX_RUNTIME_BYTES:
                raise ValueError("Runtime exceeds its byte limit")
            digest.update(chunk)

        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (byte_count != expected.st_size
                or any(getattr(before, field) != getattr(after, field) for field in stable_fields)
                or after.st_size != expected.st_size):
            raise ValueError("Runtime file changed while its identity was being read")
        return byte_count, digest.hexdigest()
    except OSError as error:
        raise ValueError("Runtime file could not be read safely") from error
    finally:
        os.close(descriptor)


def _directory_runtime_identity(binary_path: Path) -> dict[str, Any]:
    runtime_root = binary_path.parent / "_internal"
    try:
        root_stat = runtime_root.lstat()
    except OSError as error:
        raise ValueError("Directory-v1 native runtime requires an actual _internal directory") from error
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("Directory-v1 native runtime requires an actual nonsymlink _internal directory")

    pending = [runtime_root]
    directories: list[tuple[Path, os.stat_result]] = []
    files: list[tuple[str, Path, os.stat_result]] = []
    entry_count = 0
    expected_bytes = 0

    while pending:
        directory = pending.pop()
        try:
            directory_stat = directory.lstat()
            if not stat.S_ISDIR(directory_stat.st_mode):
                raise ValueError("Runtime contains a symlink or special file")
            directories.append((directory, directory_stat))
            with os.scandir(directory) as entries:
                for entry in entries:
                    entry_count += 1
                    if entry_count > MAX_RUNTIME_MEMBERS:
                        raise ValueError("Runtime exceeds its member limit")
                    member_path = Path(entry.path)
                    member_stat = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(member_stat.st_mode):
                        pending.append(member_path)
                    elif stat.S_ISREG(member_stat.st_mode):
                        expected_bytes += member_stat.st_size
                        if expected_bytes > MAX_RUNTIME_BYTES:
                            raise ValueError("Runtime exceeds its byte limit")
                        relative_path = member_path.relative_to(runtime_root).as_posix()
                        files.append((relative_path, member_path, member_stat))
                    else:
                        raise ValueError("Runtime contains a symlink or special file")
        except OSError as error:
            raise ValueError("Runtime directory could not be read safely") from error

    if not files:
        raise ValueError("Directory-v1 runtime is empty or contains no regular files")

    members: list[dict[str, Any]] = []
    actual_bytes = 0
    for relative_path, path, expected in sorted(files, key=lambda item: item[0]):
        byte_count, digest = _hash_regular_file(path, expected)
        actual_bytes += byte_count
        if actual_bytes > MAX_RUNTIME_BYTES:
            raise ValueError("Runtime exceeds its byte limit")
        members.append({"path": relative_path, "bytes": byte_count, "sha256": digest})
    if actual_bytes != expected_bytes:
        raise ValueError("Runtime changed while its identity was being collected")

    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    for path, expected in directories:
        try:
            current = path.lstat()
        except OSError as error:
            raise ValueError("Runtime changed while its identity was being collected") from error
        if (not stat.S_ISDIR(current.st_mode)
                or any(getattr(current, field) != getattr(expected, field) for field in stable_fields)):
            raise ValueError("Runtime changed while its identity was being collected")
    for _, path, expected in files:
        try:
            current = path.lstat()
        except OSError as error:
            raise ValueError("Runtime changed while its identity was being collected") from error
        if (not stat.S_ISREG(current.st_mode)
                or any(getattr(current, field) != getattr(expected, field) for field in stable_fields)):
            raise ValueError("Runtime changed while its identity was being collected")

    layout = "directory-v1"
    return {
        "bundle_layout": layout,
        "external_runtime_used": True,
        "runtime_path": "_internal",
        "entry_count": entry_count,
        "member_count": len(members),
        "runtime_bytes": actual_bytes,
        "members": members,
        "fingerprint": _fingerprint(layout, True, members),
    }


def inventory_native_runtime(binary_path: Path, binary_identity: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable runtime inventory for a previously verified native binary.

    Legacy one-file binaries have no external runtime directory to inventory.
    For directory-v1 bundles, every descendant must be a bounded regular file or
    directory; symlinks and special files are rejected rather than followed.
    """
    binary_path = Path(binary_path)
    layout = binary_identity.get("bundle_layout")
    if layout == "directory-v1":
        return _directory_runtime_identity(binary_path)
    if layout in (None, "onefile", "onefile-legacy"):
        legacy_layout = "onefile-legacy"
        members: list[dict[str, Any]] = []
        return {
            "bundle_layout": legacy_layout,
            "external_runtime_used": False,
            "runtime_path": None,
            "entry_count": 0,
            "member_count": 0,
            "runtime_bytes": 0,
            "members": members,
            "fingerprint": _fingerprint(legacy_layout, False, members),
        }
    raise ValueError(f"Unsupported native bundle layout: {layout!r}")


def verify_native_runtime(binary_path: Path, binary_identity: Mapping[str, Any],
                          frozen_identity: object) -> dict[str, Any]:
    """Require an exact previously frozen runtime inventory before binary launch."""
    if not isinstance(frozen_identity, Mapping):
        raise ValueError("Frozen native runtime inventory is missing")
    current = inventory_native_runtime(binary_path, binary_identity)
    if dict(frozen_identity) != current:
        raise ValueError("Native runtime inventory changed")
    return current

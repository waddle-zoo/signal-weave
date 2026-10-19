"""Non-authoritative, bounded inventory of caller files after an evaluation.

This observer does not decide whether an analyst completed useful work. Tool
scratch files and symlinks are recorded without following them, rather than
turning a finished business episode into an unrecorded attempt.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from evaluations.codex_workspace import validate_workspace


def _identity(value: os.stat_result) -> tuple:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def record_workspace(path: Path, *, max_entries: int = 10_000,
                     max_file_bytes: int = 2_000_000,
                     max_total_bytes: int = 100_000_000) -> dict:
    root = validate_workspace(path)
    if min(max_entries, max_file_bytes, max_total_bytes) < 1:
        raise ValueError("Inventory bounds must be positive")
    result = {"files": {}, "coverage": "complete", "hashed_bytes": 0,
              "symlinks_followed": False, "business_grade": None}
    pending = [root]
    while pending:
        directory = pending.pop()
        # Never descend through a symlink, including a directory replaced since
        # enumeration. Actors have stopped; this remains only an observation.
        if directory.is_symlink():
            result["coverage"] = "partial"
            continue
        for item in sorted(directory.iterdir()):
            if len(result["files"]) >= max_entries:
                result["coverage"] = "partial"
                return result
            relative = item.relative_to(root).as_posix()
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode):
                result["files"][relative] = {"kind": "symlink", "target": os.readlink(item),
                                             "followed": False}
            elif stat.S_ISDIR(info.st_mode):
                result["files"][relative] = {"kind": "directory"}
                pending.append(item)
            elif stat.S_ISREG(info.st_mode):
                record = {"kind": "file", "bytes": info.st_size, "sha256": None}
                if (info.st_size > max_file_bytes
                        or result["hashed_bytes"] + info.st_size > max_total_bytes):
                    record["not_hashed"] = "declared_byte_bound"
                    result["coverage"] = "partial"
                else:
                    descriptor = os.open(item, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(descriptor, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        body = stream.read(max_file_bytes + 1)
                        after = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(before.st_mode) or _identity(info) != _identity(before)
                            or _identity(before) != _identity(after)
                            or len(body) != info.st_size or len(body) > max_file_bytes):
                        record["not_hashed"] = "changed_during_observation"
                        result["coverage"] = "partial"
                    else:
                        record["sha256"] = hashlib.sha256(body).hexdigest()
                        result["hashed_bytes"] += len(body)
                result["files"][relative] = record
            else:
                result["files"][relative] = {"kind": "special_file", "followed": False}
                result["coverage"] = "partial"
    return result

"""Bind release and trial binaries to the production source they were built from."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
BUILD_INPUTS = (
    "pyproject.toml", "uv.lock", "LICENSE", "MANIFEST.in",
    "scripts/build_binary.py", "scripts/frozen_entrypoint.py",
    "scripts/binary_provenance.py",
)


def source_fingerprint(root: Path = ROOT) -> str:
    paths = [root / name for name in BUILD_INPUTS if (root / name).is_file()]
    paths.extend(path for path in (root / "src" / "signalweave").rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts
                 and path.suffix in {".py", ".html", ".css", ".svg", ".json"})
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def build_metadata(root: Path = ROOT) -> dict:
    import platform

    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True))
    return {"format_version": 1, "version": version, "git_commit": commit,
            "source_sha256": source_fingerprint(root), "dirty": dirty,
            "python": platform.python_version(), "frozen": True}


def verify_binary(binary: Path, root: Path = ROOT, *, timeout: int = 90) -> dict:
    """Reject old/stale binaries before they can produce evidence for current code."""
    if binary.is_symlink() or not binary.is_file() or not binary.stat().st_size:
        raise ValueError("Expected a nonempty regular native binary")
    before = hashlib.sha256(binary.read_bytes()).hexdigest()
    result = subprocess.run([str(binary.resolve()), "--build-info"], capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode:
        raise ValueError("Binary build-info check failed; rebuild the current source")
    try:
        metadata = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError("Binary has no valid embedded build metadata; rebuild it") from None
    if not isinstance(metadata, dict) or metadata.get("format_version") != 1 or metadata.get("frozen") is not True:
        raise ValueError("Expected embedded native-binary build metadata")
    if not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("source_sha256", ""))) or not re.fullmatch(r"[0-9a-f]{40}", str(metadata.get("git_commit", ""))):
        raise ValueError("Binary build fingerprints are incomplete or invalid")
    expected = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    if metadata.get("version") != expected:
        raise ValueError("Binary version differs from the current source")
    if metadata.get("source_sha256") != source_fingerprint(root):
        raise ValueError("Binary is stale: production source or build inputs changed; rebuild it")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != before:
        raise ValueError("Binary changed during verification")
    return {**metadata, "binary_sha256": before}

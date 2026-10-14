from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.binary_provenance import source_fingerprint, verify_binary
from signalweave.build_info import build_info


def source_tree(path: Path) -> Path:
    package = path / "src" / "signalweave"
    package.mkdir(parents=True)
    (package / "core.py").write_text("policy = 'approved'\n")
    (path / "pyproject.toml").write_text('[project]\nversion = "0.2.0rc3"\n')
    return path


def executable(root: Path, metadata: dict) -> Path:
    path = root / "signalweave"
    path.write_text(f"#!{sys.executable}\nimport json\nprint(json.dumps({metadata!r}))\n")
    path.chmod(0o755)
    return path


def identity(root: Path) -> dict:
    return {"format_version": 1, "version": "0.2.0rc3", "frozen": True,
            "source_sha256": source_fingerprint(root), "git_commit": "a" * 40}


def test_same_version_binary_is_rejected_after_source_change(tmp_path):
    root = source_tree(tmp_path)
    binary = executable(root, identity(root))
    assert verify_binary(binary, root)["binary_sha256"]
    (root / "src" / "signalweave" / "core.py").write_text("policy = 'changed'\n")
    with pytest.raises(ValueError, match="stale"):
        verify_binary(binary, root)


def test_trial_changes_do_not_invalidate_an_unchanged_binary(tmp_path):
    root = source_tree(tmp_path)
    binary = executable(root, identity(root))
    (root / "evaluations").mkdir()
    (root / "evaluations" / "trial.py").write_text("holdout = 100\n")
    assert verify_binary(binary, root)["source_sha256"] == source_fingerprint(root)


def test_dependency_change_invalidates_binary(tmp_path):
    root = source_tree(tmp_path)
    (root / "uv.lock").write_text("lock-version = 1\n")
    binary = executable(root, identity(root))
    (root / "uv.lock").write_text("lock-version = 2\n")
    with pytest.raises(ValueError, match="stale"):
        verify_binary(binary, root)


def test_canonical_skill_change_invalidates_binary(tmp_path):
    root = source_tree(tmp_path)
    skill = root / "skills" / "signalweave" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("instructions = 'first'\n")
    binary = executable(root, identity(root))
    skill.write_text("instructions = 'changed'\n")
    with pytest.raises(ValueError, match="stale"):
        verify_binary(binary, root)


@pytest.mark.parametrize("metadata", [{}, {"format_version": 1, "frozen": False},
                                     {"format_version": 1, "frozen": True}])
def test_binary_without_complete_native_metadata_is_rejected(tmp_path, metadata):
    root = source_tree(tmp_path)
    with pytest.raises(ValueError, match="metadata|fingerprints"):
        verify_binary(executable(root, metadata), root)


def test_source_cli_does_not_claim_to_be_a_native_build(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert build_info()["frozen"] is False


def test_frozen_cli_reads_embedded_identity(tmp_path, monkeypatch):
    metadata = {"format_version": 1, "frozen": True, "source_sha256": "f" * 64}
    (tmp_path / "signalweave-build.json").write_text(json.dumps(metadata))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert build_info() == metadata

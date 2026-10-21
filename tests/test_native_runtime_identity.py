from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from evaluations import (
    harbor_enterprise_journey,
    northstar_enterprise_journey,
    northstar_workspace_journey,
)
from evaluations import native_runtime_identity as runtime_identity


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    binary = bundle / "signalweave"
    binary.write_bytes(b"verified binary fixture")
    internal = bundle / "_internal"
    internal.mkdir()
    return binary, internal


def _inventory(binary: Path) -> dict:
    return runtime_identity.inventory_native_runtime(binary, {"bundle_layout": "directory-v1"})


def test_nested_inventory_is_sorted_deterministic_and_hashes_exact_bytes(tmp_path: Path) -> None:
    binary, internal = _bundle(tmp_path)
    (internal / "z-last").write_bytes(b"last")
    (internal / "nested").mkdir()
    (internal / "nested" / "runtime.bin").write_bytes(b"runtime")

    first = _inventory(binary)
    second = _inventory(binary)

    assert first == second
    assert [member["path"] for member in first["members"]] == [
        "nested/runtime.bin", "z-last",
    ]
    assert first["members"] == [
        {"path": "nested/runtime.bin", "bytes": 7,
         "sha256": hashlib.sha256(b"runtime").hexdigest()},
        {"path": "z-last", "bytes": 4,
         "sha256": hashlib.sha256(b"last").hexdigest()},
    ]
    assert first["external_runtime_used"] is True
    assert first["member_count"] == 2
    assert first["entry_count"] == 3
    assert len(first["fingerprint"]) == 64


def test_changed_file_bytes_change_identity(tmp_path: Path) -> None:
    binary, internal = _bundle(tmp_path)
    member = internal / "libpython.so"
    member.write_bytes(b"before")
    first = _inventory(binary)

    member.write_bytes(b"after!")
    second = _inventory(binary)

    assert first != second
    assert first["fingerprint"] != second["fingerprint"]


def test_added_and_deleted_files_change_identity(tmp_path: Path) -> None:
    binary, internal = _bundle(tmp_path)
    original = internal / "base.dat"
    original.write_bytes(b"base")
    before = _inventory(binary)

    added = internal / "nested" / "extra.dat"
    added.parent.mkdir()
    added.write_bytes(b"extra")
    with_added = _inventory(binary)
    added.unlink()
    added.parent.rmdir()
    after_delete = _inventory(binary)

    assert before["fingerprint"] != with_added["fingerprint"]
    assert with_added["fingerprint"] != after_delete["fingerprint"]
    assert before == after_delete


def test_directory_v1_rejects_missing_runtime(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    binary = bundle / "signalweave"
    binary.write_bytes(b"binary")

    with pytest.raises(ValueError, match="_internal"):
        _inventory(binary)


def test_directory_v1_rejects_non_directory_runtime_root(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    binary = bundle / "signalweave"
    binary.write_bytes(b"binary")
    (bundle / "_internal").write_bytes(b"not a directory")

    with pytest.raises(ValueError, match="actual nonsymlink _internal directory"):
        _inventory(binary)


@pytest.mark.parametrize("contents", ["empty", "directories-only"])
def test_directory_v1_rejects_empty_or_fileless_runtime(tmp_path: Path, contents: str) -> None:
    binary, internal = _bundle(tmp_path)
    if contents == "directories-only":
        (internal / "nested").mkdir()

    with pytest.raises(ValueError, match="empty|regular files"):
        _inventory(binary)


@pytest.mark.parametrize("link_kind", ["runtime-root", "member-file", "member-directory"])
def test_directory_v1_rejects_symlinks(tmp_path: Path, link_kind: str) -> None:
    binary, internal = _bundle(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload").write_bytes(b"external")

    if link_kind == "runtime-root":
        internal.rmdir()
        internal.symlink_to(outside, target_is_directory=True)
    elif link_kind == "member-file":
        (internal / "linked-file").symlink_to(outside / "payload")
    else:
        (internal / "linked-directory").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="nonsymlink|symlink"):
        _inventory(binary)


def test_directory_v1_rejects_fifo(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    binary, internal = _bundle(tmp_path)
    os.mkfifo(internal / "pipe")

    with pytest.raises(ValueError, match="special file"):
        _inventory(binary)


def test_directory_v1_rejects_oversized_runtime_without_reading_it(tmp_path: Path) -> None:
    binary, internal = _bundle(tmp_path)
    oversized = internal / "large.bin"
    with oversized.open("wb") as stream:
        stream.truncate(runtime_identity.MAX_RUNTIME_BYTES + 1)

    with pytest.raises(ValueError, match="byte limit"):
        _inventory(binary)


def test_directory_v1_rejects_member_budget_exceeded(tmp_path: Path, monkeypatch) -> None:
    binary, internal = _bundle(tmp_path)
    (internal / "one").write_bytes(b"1")
    (internal / "two").write_bytes(b"2")
    (internal / "three").write_bytes(b"3")
    monkeypatch.setattr(runtime_identity, "MAX_RUNTIME_MEMBERS", 2)

    with pytest.raises(ValueError, match="member limit"):
        _inventory(binary)


def test_legacy_onefile_identity_is_stable_and_uses_no_external_runtime(tmp_path: Path) -> None:
    binary = tmp_path / "legacy" / "signalweave"
    binary.parent.mkdir()
    binary.write_bytes(b"onefile fixture")

    first = runtime_identity.inventory_native_runtime(binary, {})
    second = runtime_identity.inventory_native_runtime(
        binary, {"bundle_layout": "onefile-legacy"},
    )

    assert first == second
    assert first["bundle_layout"] == "onefile-legacy"
    assert first["external_runtime_used"] is False
    assert first["runtime_path"] is None
    assert first["members"] == []
    assert first["runtime_bytes"] == 0
    assert len(first["fingerprint"]) == 64


def test_all_fresh_journeys_pin_the_runtime_inventory_implementation() -> None:
    for journey in (northstar_workspace_journey, northstar_enterprise_journey,
                    harbor_enterprise_journey):
        assert "evaluations/native_runtime_identity.py" in journey.method()


@pytest.mark.parametrize("journey_name", ["workspace", "northstar_enterprise", "harbor"])
@pytest.mark.parametrize("defect", [
    "missing_identity", "missing_directory", "tampered", "added", "deleted",
])
def test_journey_rejects_unfrozen_or_changed_runtime_before_binary_verification(
    tmp_path: Path, monkeypatch, journey_name: str, defect: str,
) -> None:
    binary, internal = _bundle(tmp_path)
    original = internal / "runtime.bin"
    original.write_bytes(b"frozen runtime")
    frozen_runtime = _inventory(binary)
    if defect == "missing_identity":
        frozen_runtime = None
    elif defect == "missing_directory":
        shutil.rmtree(internal)
    elif defect == "tampered":
        original.write_bytes(b"changed runtime")
    elif defect == "added":
        (internal / "new-runtime.bin").write_bytes(b"new")
    elif defect == "deleted":
        original.unlink()

    journeys = {
        "workspace": northstar_workspace_journey,
        "northstar_enterprise": northstar_enterprise_journey,
        "harbor": harbor_enterprise_journey,
    }
    journey = journeys[journey_name]
    binary_launch = Mock(side_effect=AssertionError("verify_binary must not run"))
    monkeypatch.setattr(journey, "verify_binary", binary_launch)
    method = {"frozen-test-method": "a" * 64}
    monkeypatch.setattr(journey, "method", lambda: method)
    if journey_name == "workspace":
        study = {
            "protocol": journey.PROTOCOL, "method": method, "limits": journey.LIMITS,
            "binary": {"bundle_layout": "directory-v1"}, "native_runtime": frozen_runtime,
            "installed_binary": str(binary),
        }
    elif journey_name == "northstar_enterprise":
        monkeypatch.setattr(journey, "_require_source_docker_context", lambda: None)
        study = {
            "protocol": journey.PROTOCOL, "method": method, "limits": journey.LIMITS,
            "order": list(journey.ORDER), "bootstrap": {},
            "binary": {"bundle_layout": "directory-v1"}, "native_runtime": frozen_runtime,
            "installed_binary": str(binary),
        }
    else:
        study = {
            "protocol": journey.PROTOCOL, "method": method,
            "key_file": str(tmp_path / "private.key"),
            "binary": {"bundle_layout": "directory-v1"}, "native_runtime": frozen_runtime,
            "binary_path": str(binary),
        }

    with pytest.raises(ValueError, match="(?i)runtime|_internal"):
        journey.verify(study, tmp_path)
    binary_launch.assert_not_called()

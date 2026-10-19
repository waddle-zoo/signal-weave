"""Recording tool scratch output must not erase a completed analyst attempt."""
import hashlib

import pytest

from evaluations.workspace_recording import record_workspace


def test_records_more_than_one_hundred_files_and_never_follows_links(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    secret = tmp_path / "outside"
    secret.write_text("not readable evidence")
    for number in range(171):
        (workspace / f"file-{number}").write_text("real caller work")
    (workspace / "scratch-link").symlink_to(secret)
    (workspace / "outside-directory").symlink_to(tmp_path, target_is_directory=True)
    record = record_workspace(workspace)
    assert record["coverage"] == "complete"
    assert len(record["files"]) == 173
    assert record["files"]["scratch-link"] == {
        "kind": "symlink", "target": str(secret), "followed": False}
    assert record["files"]["file-0"]["sha256"] == hashlib.sha256(b"real caller work").hexdigest()
    assert record["business_grade"] is None
    assert "not readable evidence" not in str(record)


def test_inventory_bounds_are_explicit_not_a_business_failure(tmp_path):
    tmp_path.chmod(0o700)
    (tmp_path / "large").write_text("12345")
    record = record_workspace(tmp_path, max_file_bytes=4)
    assert record["coverage"] == "partial"
    assert record["files"]["large"]["sha256"] is None
    assert record["hashed_bytes"] == 0
    for number in range(3):
        (tmp_path / str(number)).touch()
    record = record_workspace(tmp_path, max_entries=2)
    assert record["coverage"] == "partial"
    assert len(record["files"]) == 2
    with pytest.raises(ValueError, match="positive"):
        record_workspace(tmp_path, max_entries=0)

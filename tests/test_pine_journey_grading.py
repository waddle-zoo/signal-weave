"""Independent structural/source checks; no actor or metric implementation imports."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from evaluations.pine_courier_history import create_snapshot
from evaluations.pine_journey_grading import CUTOFFS, grade_pine_world


@pytest.fixture(scope="module")
def source_archive(tmp_path_factory):
    archive = tmp_path_factory.mktemp("public-pine-snapshots")
    for i in range(3):
        # Reconstruct the public fixture on a clean checkout. The independent
        # grader still checks archived hashes and recomputes raw/event counts;
        # it never imports this generator or reads its expected decisions.
        create_snapshot(archive / f"snapshot-{i}.sqlite3", i)
    return archive


@pytest.fixture
def world_file(tmp_path, source_archive):
    for i in range(3):
        shutil.copyfile(source_archive / f"snapshot-{i}.sqlite3", tmp_path / f"snapshot-{i}.sqlite3")

    messages, reads = [], []
    for index, cutoff in enumerate(CUTOFFS):
        recipients = ["dispatch", "data-operations"] if index == 1 else ["dispatch"]
        replies = []
        for recipient in recipients:
            message_id = f"msg-{index}-{recipient}"
            ref = "workspace/brief.md"
            attachment_rel = Path("signalweave/inbox") / message_id / "0-brief.md"
            attachment = tmp_path / attachment_rel
            attachment.parent.mkdir(parents=True, exist_ok=True)
            attachment.write_text(f"offline evidence {index} {recipient}", encoding="utf-8")
            messages.append({
                "id": message_id, "to": recipient, "body": "Delivered simulated note.",
                "evidence_refs": [ref], "source_cutoff": cutoff,
                "attachments": [{"original_ref": ref, "path": attachment_rel.as_posix(),
                                 "sha256": hashlib.sha256(attachment.read_bytes()).hexdigest()}],
            })
            replies.append({"reply_to": message_id, "from": recipient, "body": "Ack; follow-up received."})
        reads.append({"source_cutoff": cutoff, "replies": replies})

    artifact = {
        "messages": messages,
        "owner_conversations": [
            {"question": "What should the review cover?", "answer": "Frozen simulated owner notes.", "known": True},
            {"summary": "Displayed workflow", "saved_card": {"card_id": "pine-card"},
             "source_cutoff": CUTOFFS[0], "answer": "Approved for historical shadow runs."},
        ],
        "operator_actions": [{"returncode": 0}],
        "feedback_reads": reads,
        "current_day": 2,
        "complete": True,
    }
    path = tmp_path / "world-signalweave.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def read_world(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_world(path, artifact):
    path.write_text(json.dumps(artifact), encoding="utf-8")


def test_raw_truth_and_structural_journey_cover_all_three_cutoffs(world_file):
    result = grade_pine_world(world_file)
    assert result["structural_status"] == "pass"
    assert [row["delta_pp"] for row in result["source_reference"]] == pytest.approx(
        [0.0, -8.421052631579, 6.315789473684])
    middle = result["source_reference"][1]
    assert middle["raw_comparison_valid"] is True
    assert middle["cache_comparison_valid"] is False
    assert middle["current_cache_all"]["eligible"] is None
    assert "cache_denominator_missing" in middle["quality_flags"]
    assert middle["current_all"]["on_time"] == 2772
    assert middle["current_all"]["eligible"] == 3420
    assert result["coverage"]["attachment_access"]["checked"] == 4
    assert result["coverage"]["feedback_replies_linked"] == 4
    assert result["prose_numeric_accuracy"].startswith("not graded")


def test_data_operations_delivery_is_required_for_known_cache_gap(world_file):
    artifact = read_world(world_file)
    artifact["messages"] = [m for m in artifact["messages"] if m["to"] != "data-operations"]
    write_world(world_file, artifact)
    result = grade_pine_world(world_file)
    assert result["structural_status"] == "fail"
    assert any("Data Operations" in item for item in result["issues"])


def test_attachment_hash_and_access_are_checked(world_file):
    artifact = read_world(world_file)
    attachment = artifact["messages"][0]["attachments"][0]
    (world_file.parent / attachment["path"]).write_text("changed evidence", encoding="utf-8")
    result = grade_pine_world(world_file)
    assert result["structural_status"] == "fail"
    assert any("attachment hash mismatch" in item for item in result["issues"])


def test_confirmation_and_reply_linkage_are_structural_not_prose_scored(world_file):
    artifact = read_world(world_file)
    artifact["owner_conversations"] = artifact["owner_conversations"][:1]
    artifact["feedback_reads"][0]["replies"][0]["reply_to"] = "not-a-message"
    artifact["messages"][0]["body"] = "A deliberately unverified numeric assertion: 100%."
    write_world(world_file, artifact)
    result = grade_pine_world(world_file)
    assert result["structural_status"] == "fail"
    assert any("confirmation" in item for item in result["issues"])
    assert any("feedback reply" in item for item in result["issues"])
    assert result["prose_numeric_accuracy"].startswith("not graded")


def test_raw_scan_handles_full_13200_parcel_snapshot(world_file):
    result = grade_pine_world(world_file)
    last = result["source_reference"][2]
    assert last["event_counts"]["registered"] == 13200
    assert last["manifest_rows_checked"] > 0
    assert last["current_all"]["eligible"] == 3990

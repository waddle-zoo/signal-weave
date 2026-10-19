from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path

import pytest

from evaluations.harbor_enterprise_fixture import (
    build_fixture,
    copy_active_snapshot,
    default_cutoffs,
    parse_cutoffs,
)

UTC = timezone.utc


def _readonly(path: Path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def test_default_candidate_cutoffs_are_fixed_daily_formative_instants():
    cutoffs = default_cutoffs()
    assert len(cutoffs) == 28
    assert cutoffs[0] == datetime(2026, 2, 23, 6, tzinfo=UTC)
    assert cutoffs[-1] == datetime(2026, 3, 22, 6, tzinfo=UTC)
    assert all(right - left == timedelta(days=1) for left, right in pairwise(cutoffs))
    assert parse_cutoffs(["2026-02-23T01:00:00-05:00"]) == [cutoffs[0]]


def test_cutoff_contract_is_bounded_unique_ordered_and_aware():
    base = datetime(2026, 2, 23, 6, tzinfo=UTC)
    with pytest.raises(ValueError, match="1..40"):
        parse_cutoffs([])
    with pytest.raises(ValueError, match="1..40"):
        parse_cutoffs([base + timedelta(days=day) for day in range(41)])
    with pytest.raises(ValueError, match="increasing"):
        parse_cutoffs([base + timedelta(days=1), base])
    with pytest.raises(ValueError, match="increasing"):
        parse_cutoffs([base, base])
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_cutoffs([datetime(2026, 2, 23, 6)])
    with pytest.raises(ValueError, match="whole-second"):
        parse_cutoffs([base.replace(microsecond=1)])
    with pytest.raises(ValueError, match="precede"):
        parse_cutoffs([datetime(2026, 1, 4, 23, tzinfo=UTC)])


def test_private_snapshots_record_schema_counts_coverage_and_hashes(tmp_path):
    cutoffs = default_cutoffs()[:2]
    built = build_fixture(tmp_path / "private", cutoffs)
    root = Path(built["root"])
    manifest_path = Path(built["manifest"])
    manifest = json.loads(manifest_path.read_text())

    assert (root.stat().st_mode & 0o777) == 0o700
    assert ((root / "snapshots").stat().st_mode & 0o777) == 0o500
    assert (manifest_path.stat().st_mode & 0o777) == 0o600
    assert (root / "private" / "full-history.json").stat().st_mode & 0o777 == 0o600
    assert manifest["reviewer_only"] is True
    assert manifest["generator"]["function"] == "evaluations.harbor_history.make_history"
    assert manifest["generator"]["seed"] == 20261018
    assert len(manifest["snapshots"]) == 2
    history = json.loads((root / manifest["history"]["path"]).read_text())
    assert (
        hashlib.sha256((root / manifest["history"]["path"]).read_bytes()).hexdigest()
        == manifest["history"]["sha256"]
    )
    assert any(
        event["available_at"] > manifest["snapshots"][0]["as_of_utc"] for event in history["events"]
    )

    for cutoff, record in zip(cutoffs, manifest["snapshots"], strict=True):
        snapshot = root / record["path"]
        assert (snapshot.stat().st_mode & 0o777) == 0o400
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == record["sha256"]
        assert record["as_of_utc"] == cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert {"support_tier_sla", "tickets", "ticket_events", "weekly_source_coverage"} <= set(
            record["source_fields"]
        )
        assert {"ticket_id", "status"} <= {
            field["name"] for field in record["source_fields"]["tickets"]
        }
        assert record["row_counts"]["tickets"] > 0
        assert record["row_counts"]["weekly_source_coverage"] > 0
        assert isinstance(record["known_coverage_gaps"], list)
        assert all(gap["coverage_status"] != "complete" for gap in record["known_coverage_gaps"])
        with _readonly(snapshot) as connection:
            assert (
                connection.execute("SELECT as_of_utc FROM source_snapshot").fetchone()[0]
                == record["as_of_utc"]
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM ticket_events WHERE available_at_utc>? OR effective_at_utc>?",
                    (record["as_of_utc"], record["as_of_utc"]),
                ).fetchone()[0]
                == 0
            )
            names = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert "private_history" not in names and "expected_outcomes" not in names
    encoded_manifest = json.dumps(manifest).lower()
    assert "expected_outcome" not in encoded_manifest and '"sql"' not in encoded_manifest


def test_only_selected_snapshot_is_copied_for_the_mcp_source_path(tmp_path):
    first, second = default_cutoffs()[:2]
    built = build_fixture(tmp_path / "private", [first, second])
    source_dir = tmp_path / "analyst-source"
    source_dir.mkdir()
    active = source_dir / "active.sqlite3"
    copied = copy_active_snapshot(built["root"], second, active)

    assert copied["as_of_utc"] == second.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert active.read_bytes() == Path(built["snapshot_paths"][1]).read_bytes()
    assert (active.stat().st_mode & 0o777) == 0o400
    assert list(source_dir.iterdir()) == [active]

    from evaluations.harbor_history_mcp import list_assets, query_readonly

    catalog = list_assets(active)
    assert catalog["source"]["as_of_utc"] == copied["as_of_utc"]
    assert not {"private_history", "expected_outcomes"} & {
        asset["name"] for asset in catalog["assets"]
    }
    future_check = query_readonly(
        active,
        "SELECT COUNT(*) FROM ticket_events WHERE available_at_utc>'2026-02-24T06:00:00Z'",
    )
    assert future_check["rows"] == [[0]]
    with pytest.raises(ValueError, match="outside"):
        copy_active_snapshot(built["root"], first, Path(built["root"]) / "analyst.sqlite3")


def test_private_root_snapshot_and_active_copy_are_never_overwritten(tmp_path):
    cutoff = default_cutoffs()[0]
    output = tmp_path / "private"
    built = build_fixture(output, [cutoff])
    snapshot = Path(built["snapshot_paths"][0])
    before = snapshot.read_bytes()
    with pytest.raises(FileExistsError):
        build_fixture(output, [cutoff])
    assert snapshot.read_bytes() == before

    target_dir = tmp_path / "source"
    target_dir.mkdir()
    target = target_dir / "active.sqlite3"
    copy_active_snapshot(output, cutoff, target)
    with pytest.raises(FileExistsError):
        copy_active_snapshot(output, cutoff, target)
    assert target.read_bytes() == before

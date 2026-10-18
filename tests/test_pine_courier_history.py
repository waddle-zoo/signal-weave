"""Offline source fitness and continuity, not business-policy predictions."""

import hashlib
import sqlite3
import stat
from collections import Counter
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from evaluations import pine_courier_history as source
from signalweave.models import ResourceSnapshot


def rows(path, table):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(f'SELECT * FROM "{table}"')]


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def due_groups(parcels, end):
    """Independent Python count from raw records, not the source cache builder."""
    totals = {}
    for p in parcels:
        if p["due_at_utc"] >= end or p["cancelled_at_utc"] is not None:
            continue
        date = instant(p["due_at_utc"])
        monday = (date - timedelta(days=date.weekday())).strftime("%Y-%m-%dT00:00:00Z")
        for tier in ("ALL", p["service_tier"]):
            counts = totals.setdefault((monday, tier), [0, 0])
            counts[1] += 1
            if p["delivered_at_utc"] is not None and instant(p["delivered_at_utc"]) <= date:
                counts[0] += 1
    return totals


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory):
    root = tmp_path_factory.mktemp("pine-history")
    history = source.make_history()
    paths = [source.materialize_snapshot(history, cutoff, root / f"{i}.sqlite3")
             for i, cutoff in enumerate(source.CUTOFFS)]
    return paths


@pytest.mark.parametrize("index", range(3))
def test_complete_raw_cohorts_and_truthful_cached_exports(snapshots, index):
    path = snapshots[index]
    clock = rows(path, "source_snapshot")[0]
    parcels = rows(path, "parcels")
    totals = due_groups(parcels, clock["current_end_utc"])
    assert instant(clock["as_of_utc"]) - instant(clock["current_end_utc"]) == timedelta(hours=6)
    assert instant(clock["current_end_utc"]) - instant(clock["current_start_utc"]) == timedelta(days=7)
    assert instant(clock["current_start_utc"]) - instant(clock["baseline_start_utc"]) == timedelta(days=7)
    for row in rows(path, "cached_sla_exports"):
        numerator, denominator = totals[(row["week_start_utc"], row["service_tier"])]
        assert row["on_time_parcels"] == numerator
        missing = index == 1 and row["week_start_utc"] == clock["current_start_utc"] and row["service_tier"] == "ALL"
        assert row["eligible_parcels"] == (None if missing else denominator)
    for manifest in rows(path, "due_week_manifests"):
        end = instant(manifest["week_start_utc"]) + timedelta(days=7)
        actual = sum(p["service_tier"] == manifest["service_tier"]
                     and instant(manifest["week_start_utc"]) <= instant(p["due_at_utc"]) < end for p in parcels)
        assert manifest["expected_parcel_count"] == manifest["registered_parcel_count"] == actual
    registered = Counter(p["due_at_utc"][:10] for p in parcels)
    assert registered and any(p["cancelled_at_utc"] for p in parcels)
    for start in {m["week_start_utc"] for m in rows(path, "due_week_manifests")}:
        end = instant(start) + timedelta(days=7)
        assert 2000 <= sum(instant(start) <= instant(p["due_at_utc"]) < end for p in parcels) <= 6000
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_missing_denominator_is_export_defect_not_missing_raw_population(snapshots):
    path = snapshots[1]
    result = source.query(path, "SELECT * FROM cached_sla_exports WHERE eligible_parcels IS NULL")
    assert len(result["rows"]) == 1 and not result["truncated"]
    omitted = dict(zip(result["columns"], result["rows"][0], strict=True))
    totals = due_groups(rows(path, "parcels"), rows(path, "source_snapshot")[0]["current_end_utc"])
    numerator, denominator = totals[(omitted["week_start_utc"], "ALL")]
    assert numerator == omitted["on_time_parcels"] and denominator > numerator > 0
    tiers = [r for r in rows(path, "cached_sla_exports")
             if r["week_start_utc"] == omitted["week_start_utc"] and r["service_tier"] != "ALL"]
    assert sum(r["eligible_parcels"] for r in tiers) == denominator
    repaired = [r for r in rows(snapshots[2], "cached_export_revisions")
                if r["week_start_utc"] == omitted["week_start_utc"] and r["service_tier"] == "ALL"]
    assert [r["revision"] for r in repaired] == [1, 2]
    assert repaired[0] == omitted
    assert repaired[1]["eligible_parcels"] == denominator
    assert repaired[1]["on_time_parcels"] == numerator
    assert repaired[1]["input_cutoff_utc"] == omitted["input_cutoff_utc"]
    assert repaired[1]["export_available_at_utc"] == source.CUTOFFS[2]
    assert repaired[1]["source_note"] != omitted["source_note"]


def test_shared_due_weeks_are_continuous_and_changes_have_visible_events(snapshots):
    previous_totals, previous_parcels, previous_exports = {}, {}, {}
    previous_end = None
    for path in snapshots:
        clock = rows(path, "source_snapshot")[0]
        parcels = {p["parcel_id"]: p for p in rows(path, "parcels")}
        totals = due_groups(parcels.values(), clock["current_end_utc"])
        for key in previous_totals.keys() & totals.keys():
            assert totals[key] == previous_totals[key]
        events = rows(path, "parcel_events")
        for event in events:
            assert event["available_at_utc"] <= clock["as_of_utc"]
            assert event["effective_at_utc"] <= clock["as_of_utc"]
        for parcel, old in previous_parcels.items():
            new = parcels[parcel]
            for key in old:
                if old[key] != new[key]:
                    delivery = key in {"delivered_at_utc", "delivery_available_at_utc"}
                    cancellation = key in {"cancelled_at_utc", "cancellation_available_at_utc"}
                    assert delivery or cancellation
                    assert old[key] is None
                    # Registrations may already include a future promise. Its
                    # on-time delivery can legitimately arrive by the next
                    # cutoff. Only a previously closed cohort is constrained
                    # to late deliveries here; its all-due totals stay fixed.
                    if old["due_at_utc"] < previous_end:
                        assert delivery
                        assert new["delivered_at_utc"] > new["due_at_utc"]
                    kind = "delivery" if delivery else "cancellation"
                    assert any(e["parcel_id"] == parcel and e["event_type"] == kind
                               and e["available_at_utc"] == new[kind + "_available_at_utc"]
                               and previous_end <= e["available_at_utc"] <= clock["as_of_utc"]
                               for e in events)
        exports = {(x["week_start_utc"], x["service_tier"], x["revision"]): x
                   for x in rows(path, "cached_export_revisions")}
        assert all(exports[k] == v for k, v in previous_exports.items())
        previous_totals, previous_parcels, previous_exports = totals, parcels, exports
        previous_end = clock["current_end_utc"]


@pytest.mark.parametrize("index", range(3))
def test_completed_alternative_is_a_different_population(snapshots, index):
    path = snapshots[index]
    end = rows(path, "source_snapshot")[0]["current_end_utc"]
    parcels = rows(path, "parcels")
    due = due_groups(parcels, end)
    for r in rows(path, "completed_only_sla"):
        start = instant(r["week_start_utc"])
        scoped = [p for p in parcels if start <= instant(p["due_at_utc"]) < start + timedelta(days=7)
                  and p["cancelled_at_utc"] is None and p["delivered_at_utc"] is not None
                  and (r["service_tier"] == "ALL" or p["service_tier"] == r["service_tier"])]
        assert r["completed_parcels"] == len(scoped)
        assert r["on_time_parcels"] == sum(p["delivered_at_utc"] <= p["due_at_utc"] for p in scoped)
        numerator, denominator = due[(r["week_start_utc"], r["service_tier"])]
        assert r["on_time_parcels"] == numerator
        assert 0 < r["completed_parcels"] < denominator
        assert numerator / r["completed_parcels"] > numerator / denominator


def test_handworked_boundaries_and_late_record_availability(tmp_path):
    history = {"events": [], "manifests": []}

    def event(parcel, kind, effective, available=None, payload=None):
        history["events"].append({"event_id": f"{parcel}:{kind}", "revision": 1,
                                  "effective_at": instant(effective), "available_at": instant(available or effective),
                                  "payload": {"parcel_id": parcel, "event_type": kind, **(payload or {})}, "tombstone": False})

    due = {"equal": "2026-09-14T00:00:00Z", "late": "2026-09-20T23:00:00Z",
           "delayed": "2026-09-20T12:00:00Z", "undelivered": "2026-09-19T12:00:00Z",
           "cancelled": "2026-09-18T12:00:00Z", "next_week": "2026-09-21T00:00:00Z"}
    for p, promise in due.items():
        event(p, "registration", "2026-09-07T00:00:00Z", payload={"service_tier": "priority", "due_at_utc": promise})
    event("equal", "delivery", due["equal"])
    event("late", "delivery", "2026-09-21T05:30:00Z", source.CUTOFFS[0])
    event("delayed", "delivery", "2026-09-20T11:00:00Z", "2026-09-21T06:00:01Z")
    event("cancelled", "cancellation", "2026-09-18T10:00:00Z")
    first = source.materialize_snapshot(history, source.CUTOFFS[0], tmp_path / "first.sqlite3")
    later = source.materialize_snapshot(history, source.CUTOFFS[1], tmp_path / "later.sqlite3")
    before = {p["parcel_id"]: p for p in rows(first, "parcels")}
    after = {p["parcel_id"]: p for p in rows(later, "parcels")}
    assert before["late"]["delivered_at_utc"] == "2026-09-21T05:30:00Z"
    assert before["delayed"]["delivered_at_utc"] is None
    assert before["delayed"]["delivery_available_at_utc"] is None
    assert after["delayed"]["delivered_at_utc"] == "2026-09-20T11:00:00Z"
    first_counts = due_groups(before.values(), "2026-09-21T00:00:00Z")
    later_counts = due_groups(after.values(), "2026-09-21T00:00:00Z")
    assert first_counts[("2026-09-14T00:00:00Z", "ALL")] == [1, 4]
    assert later_counts[("2026-09-14T00:00:00Z", "ALL")] == [2, 4]
    assert ("2026-09-07T00:00:00Z", "ALL") not in first_counts


def test_later_correction_never_leaks_earlier(tmp_path):
    history = source.make_history()
    original = next(e for e in history["events"] if e["payload"]["event_type"] == "delivery")
    corrected = deepcopy(original)
    corrected.update(revision=2, available_at=instant(source.CUTOFFS[1]))
    corrected["effective_at"] += timedelta(days=2)
    history["events"].append(corrected)
    before = source.materialize_snapshot(history, source.CUTOFFS[0], tmp_path / "before.sqlite3")
    after = source.materialize_snapshot(history, source.CUTOFFS[1], tmp_path / "after.sqlite3")
    a = next(e for e in rows(before, "parcel_events") if e["event_id"] == original["event_id"])
    b = next(e for e in rows(after, "parcel_events") if e["event_id"] == original["event_id"])
    assert a["revision"] == 1 and b["revision"] == 2
    assert a["effective_at_utc"] != b["effective_at_utc"]


def test_public_readonly_surface_provenance_and_no_overwrite(snapshots, tmp_path):
    path = snapshots[1]
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = ResourceSnapshot.model_validate(source.export(path, "SELECT * FROM cached_sla_exports", "cached", "sla", "Cached SLA"))
    assert result.adapter == source.ADAPTER
    assert result.source_captured_at == instant(source.CUTOFFS[1])
    assert any(e.values["eligible_parcels"] is None for e in result.evidence)
    assert all(ref.startswith(source.SOURCE_ID + ":") for e in result.evidence for ref in e.provenance)
    assert all("harbor" not in ref for e in result.evidence for ref in e.provenance)
    with pytest.raises(ValueError, match="read-only"):
        source.query(path, "DELETE FROM parcels")
    with pytest.raises(FileExistsError):
        source.create_snapshot(path, 0)
    link = tmp_path / "link.sqlite3"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        source.query(link, "SELECT * FROM parcels")
    with pytest.raises(FileExistsError):
        source.create_snapshot(link, 0)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("bad", [-1, 3, True, "0"])
def test_invalid_snapshot_index_has_no_writes(tmp_path, bad):
    with pytest.raises(ValueError):
        source.create_snapshot(tmp_path / "no.sqlite3", bad)
    assert list(tmp_path.iterdir()) == []

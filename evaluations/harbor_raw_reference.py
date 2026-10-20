#!/usr/bin/env python3
"""Independently recompute raw Harbor facts from an immutable fixture pack.

Uses Python's standard library and direct read-only SQLite queries. It does not
import the Harbor generator/projector, production metrics, or actor outcomes. The
output contains source counts, exact IDs, cohorts, and coverage, not action labels.

Example:
    python evaluations/harbor_raw_reference.py --fixture artifacts/harbor-fixture
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import stat
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

MANIFEST_RELATIVE_PATH = Path("private/reviewer-manifest.json")
PRIORITY_FLAG = 1  # Source-owned work-population flag, not a universal severity.


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def child_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError(f"Manifest path is not a safe relative path: {relative!r}")
    path = root
    for part in candidate.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Snapshot pack contains a symlink: {path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)) or not resolved.is_file():
        raise ValueError(f"Manifest path is not a regular file under fixture root: {relative!r}")
    return resolved


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"Expected a UTC timestamp with an offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def unix_seconds(value: str) -> int:
    # Matches SQLite's source-owned CAST(strftime('%s', ...) AS INTEGER) clock.
    return int(parse_utc(value).timestamp())


def safe_json(value: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def open_snapshot(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError(f"SQLite did not enter query-only mode: {path}")
    return connection


def rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql).fetchall()]


def elapsed_seconds(start: str, end: str) -> int:
    return unix_seconds(end) - unix_seconds(start)


def elapsed_hours(seconds: int) -> float:
    return round(seconds / 3600, 6)


def classify_coverage(expected: int | None, observed: int) -> str:
    if expected is None:
        return "unknown"
    if observed == expected:
        return "complete"
    if observed > expected:
        return "excess"
    if observed == 0:
        return "missing"
    return "partial"


def by_partition(rows_: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows_:
        result[(row["week_start_utc"], row["support_tier"], row["region"])].append(row)
    return result


def _ticket_record(ticket: dict[str, Any], elapsed: int, limit_hours: int,
                   limit_name: str) -> dict[str, Any]:
    return {
        "ticket_id": ticket["ticket_id"],
        "support_tier": ticket["support_tier"],
        "region": ticket["region"],
        "created_at_utc": ticket["created_at_utc"],
        "elapsed_seconds": elapsed,
        "elapsed_hours": elapsed_hours(elapsed),
        limit_name: limit_hours,
        "first_response_at_utc": ticket["first_response_at_utc"],
    }


def inspect_event_integrity(
    tickets: list[dict[str, Any]], events: list[dict[str, Any]], cutoff: str,
) -> dict[str, Any]:
    event_kind_counts = Counter(event["kind"] for event in events)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[(event["ticket_id"], event["kind"])].append(event)

    duplicate_groups = sum(len(group) > 1 for group in grouped.values())
    by_ticket = {ticket["ticket_id"]: ticket for ticket in tickets}
    mismatches: list[dict[str, str]] = []
    ambiguous: list[dict[str, str]] = []
    cutoff_seconds = unix_seconds(cutoff)

    for ticket_id, ticket in by_ticket.items():
        for kind in ("created", "response", "resolution"):
            group = grouped.get((ticket_id, kind), [])
            if len(group) > 1:
                ambiguous.append({"ticket_id": ticket_id, "kind": kind})
                continue
            event = group[0] if group else None
            if kind == "created":
                expected_timestamp = ticket["created_at_utc"]
                should_exist = True
            elif kind == "response":
                expected_timestamp = ticket["first_response_at_utc"]
                should_exist = expected_timestamp is not None
            else:
                expected_timestamp = ticket["resolved_at_utc"]
                should_exist = ticket["status"] == "resolved" and expected_timestamp is not None

            if (event is None) != (not should_exist):
                mismatches.append({
                    "ticket_id": ticket_id,
                    "kind": kind,
                    "issue": "missing_event" if should_exist else "unexpected_event",
                })
                continue
            if event is None:
                continue

            payload = safe_json(event["payload_json"])
            event_matches = (
                event["ticket_id"] == ticket_id
                and event["kind"] == kind
                and event["effective_at_utc"] == expected_timestamp
                and event["available_at_utc"] is not None
                and unix_seconds(event["available_at_utc"]) <= cutoff_seconds
                and unix_seconds(event["effective_at_utc"]) <= cutoff_seconds
                and payload is not None
                and payload.get("ticket_id") == ticket_id
                and payload.get("kind") == kind
            )
            if kind == "created" and payload is not None:
                event_matches = event_matches and all(
                    payload.get(field) == ticket[field]
                    for field in ("priority", "region", "support_tier")
                )
            if not event_matches:
                mismatches.append({
                    "ticket_id": ticket_id,
                    "kind": kind,
                    "issue": "event_ticket_state_disagrees",
                })

    return {
        "event_kind_counts": dict(sorted(event_kind_counts.items())),
        "duplicate_ticket_kind_groups": duplicate_groups,
        "future_event_effective_rows": sum(
            unix_seconds(event["effective_at_utc"]) > cutoff_seconds for event in events
        ),
        "future_event_available_rows": sum(
            unix_seconds(event["available_at_utc"]) > cutoff_seconds for event in events
        ),
        "ticket_event_state_mismatches": mismatches,
        "ambiguous_duplicate_event_groups": ambiguous,
    }


def analyze_snapshot(
    fixture_root: Path,
    item: dict[str, Any],
    previous_sets: dict[str, set[str]] | None,
) -> tuple[dict[str, Any], dict[str, set[str]]]:
    snapshot_path = child_path(fixture_root, item["path"])
    actual_hash = sha256_file(snapshot_path)
    if actual_hash != item["sha256"]:
        raise ValueError(f"Snapshot hash differs from fixture manifest: {item['path']}")

    cutoff_text = item["as_of_utc"]
    cutoff = parse_utc(cutoff_text)
    cutoff_seconds = unix_seconds(cutoff_text)
    connection = open_snapshot(snapshot_path)
    try:
        ticket_rows = rows(connection, """
            SELECT ticket_id, week_start_utc, created_at_utc, support_tier, region,
                   priority, status, first_response_at_utc, resolved_at_utc
            FROM tickets ORDER BY ticket_id
        """)
        event_rows = rows(connection, """
            SELECT event_id, revision, kind, ticket_id, effective_at_utc,
                   available_at_utc, payload_json
            FROM ticket_events ORDER BY ticket_id, kind, event_id, revision
        """)
        tier_rows = rows(connection, """
            SELECT support_tier, resolution_sla_hours, first_response_sla_hours
            FROM support_tier_sla ORDER BY support_tier
        """)
        clock_rows = rows(connection, "SELECT snapshot_id, as_of_utc FROM source_snapshot")
        calendar_rows = rows(connection, """
            SELECT week_start_utc, support_tier, region
            FROM calendar_partitions ORDER BY week_start_utc, support_tier, region
        """)
        manifest_rows = rows(connection, """
            SELECT week_start_utc, support_tier, region, expected_ticket_count, available_at_utc
            FROM expected_partitions ORDER BY week_start_utc, support_tier, region
        """)

        if len(clock_rows) != 1 or clock_rows[0]["snapshot_id"] != 1:
            raise ValueError(f"Expected one source_snapshot row with snapshot_id=1: {item['path']}")
        if clock_rows[0]["as_of_utc"] != cutoff_text:
            raise ValueError(f"Source clock differs from fixture manifest: {item['path']}")

        tier_clocks = {row["support_tier"]: row for row in tier_rows}
        if len(tier_clocks) != len(tier_rows):
            raise ValueError(f"Duplicate support tier definitions: {item['path']}")
        tickets_by_partition = by_partition(ticket_rows)
        calendar_by_week: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for row in calendar_rows:
            calendar_by_week[row["week_start_utc"]].add((row["support_tier"], row["region"]))

        open_unanswered = [
            row for row in ticket_rows
            if row["status"] == "open" and row["first_response_at_utc"] is None
        ]
        unanswered_by_flag = Counter(row["priority"] for row in open_unanswered)
        overdue_unanswered: list[dict[str, Any]] = []
        overdue_responded_open: list[dict[str, Any]] = []
        for ticket in ticket_rows:
            if ticket["priority"] != PRIORITY_FLAG or ticket["status"] != "open":
                continue
            clock = tier_clocks[ticket["support_tier"]]
            since_creation = cutoff_seconds - unix_seconds(ticket["created_at_utc"])
            if ticket["first_response_at_utc"] is None:
                limit = clock["first_response_sla_hours"]
                if since_creation > limit * 3600:
                    overdue_unanswered.append(_ticket_record(
                        ticket, since_creation, limit, "first_response_clock_limit_hours"))
            else:
                limit = clock["resolution_sla_hours"]
                if since_creation > limit * 3600:
                    overdue_responded_open.append(_ticket_record(
                        ticket, since_creation, limit, "resolution_clock_limit_hours"))

        current_sets = {
            "priority_1_open_unanswered_over_first_response_clock": {
                row["ticket_id"] for row in overdue_unanswered
            },
            "priority_1_open_responded_over_resolution_clock": {
                row["ticket_id"] for row in overdue_responded_open
            },
        }
        set_changes = None
        if previous_sets is not None:
            set_changes = {
                name: {
                    "previous_count": len(previous_sets[name]),
                    "current_count": len(current_sets[name]),
                    "continuing_ids": sorted(previous_sets[name] & current_sets[name]),
                    "newly_present_ids": sorted(current_sets[name] - previous_sets[name]),
                    "no_longer_present_ids": sorted(previous_sets[name] - current_sets[name]),
                }
                for name in current_sets
            }

        completed_weeks = [
            week for week in calendar_by_week
            if datetime.combine(
                date.fromisoformat(week) + timedelta(days=7), time.min, tzinfo=timezone.utc
            ) <= cutoff
        ]
        cohort_week = max(completed_weeks) if completed_weeks else None
        cohort_end = (
            (date.fromisoformat(cohort_week) + timedelta(days=7)).isoformat() + "T00:00:00Z"
            if cohort_week else None
        )

        eligible_resolved: list[dict[str, Any]] = []
        resolved_without_visible_timestamp: list[str] = []
        if cohort_week is not None:
            for ticket in ticket_rows:
                if ticket["week_start_utc"] != cohort_week or ticket["priority"] != PRIORITY_FLAG:
                    continue
                if ticket["status"] == "resolved" and ticket["resolved_at_utc"] is None:
                    resolved_without_visible_timestamp.append(ticket["ticket_id"])
                    continue
                if (
                    ticket["status"] != "resolved"
                    or ticket["resolved_at_utc"] is None
                    or unix_seconds(ticket["resolved_at_utc"]) > cutoff_seconds
                ):
                    continue
                clock = tier_clocks[ticket["support_tier"]]
                elapsed = elapsed_seconds(ticket["created_at_utc"], ticket["resolved_at_utc"])
                eligible_resolved.append({
                    "ticket_id": ticket["ticket_id"],
                    "support_tier": ticket["support_tier"],
                    "region": ticket["region"],
                    "created_at_utc": ticket["created_at_utc"],
                    "resolved_at_utc": ticket["resolved_at_utc"],
                    "elapsed_seconds": elapsed,
                    "resolution_clock_limit_hours": clock["resolution_sla_hours"],
                })

        resolved_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in eligible_resolved:
            resolved_groups[(row["support_tier"], row["region"])].append(row)
        cohort_groups = set(calendar_by_week.get(cohort_week, set())) if cohort_week else set()
        cohort_groups.update(resolved_groups)
        weekly_by_group = []
        for tier, region in sorted(cohort_groups):
            group_rows = sorted(
                resolved_groups.get((tier, region), []), key=lambda row: row["ticket_id"]
            )
            limit = tier_clocks[tier]["resolution_sla_hours"]
            misses = [row for row in group_rows if row["elapsed_seconds"] > limit * 3600]
            denominator = len(group_rows)
            weekly_by_group.append({
                "support_tier": tier,
                "region": region,
                "resolution_clock_limit_hours": limit,
                "priority_1_visible_resolved_denominator": denominator,
                "priority_1_resolution_clock_miss_count": len(misses),
                "miss_rate": round(len(misses) / denominator, 12) if denominator else None,
                "priority_1_visible_resolved_ids": [row["ticket_id"] for row in group_rows],
                "miss_ticket_ids": [row["ticket_id"] for row in misses],
            })

        weekly_denominator = len(eligible_resolved)
        weekly_miss_count = sum(len(group["miss_ticket_ids"]) for group in weekly_by_group)
        weekly = {
            "latest_fully_ended_creation_week_start_utc": cohort_week,
            "creation_week_exclusive_end_utc": cohort_end,
            "calendar_period_ended_by_cutoff": cohort_week is not None,
            "priority_1_visible_resolved_denominator": weekly_denominator,
            "priority_1_resolution_clock_miss_count": weekly_miss_count,
            "descriptive_miss_rate": round(weekly_miss_count / weekly_denominator, 12)
                if weekly_denominator else None,
            "resolved_priority_1_without_visible_resolution_timestamp_ids": sorted(
                resolved_without_visible_timestamp),
            "by_support_tier_and_region": weekly_by_group,
        }

        known_manifests = {
            (row["week_start_utc"], row["support_tier"], row["region"]): row
            for row in manifest_rows
            if unix_seconds(row["available_at_utc"]) <= cutoff_seconds
        }
        future_manifest_rows = [
            row for row in manifest_rows
            if unix_seconds(row["available_at_utc"]) > cutoff_seconds
        ]
        observed_counts = {key: len(values) for key, values in tickets_by_partition.items()}

        snapshot_coverage = []
        for part in calendar_rows:
            key = (part["week_start_utc"], part["support_tier"], part["region"])
            expected = known_manifests.get(key)
            observed = observed_counts.get(key, 0)
            expected_count = expected["expected_ticket_count"] if expected else None
            snapshot_coverage.append({
                "week_start_utc": key[0],
                "support_tier": key[1],
                "region": key[2],
                "expected_created_ticket_count": expected_count,
                "observed_created_ticket_count": observed,
                "manifest_available_at_utc": expected["available_at_utc"] if expected else None,
                "coverage_status": classify_coverage(expected_count, observed),
            })
        coverage_status_counts = Counter(row["coverage_status"] for row in snapshot_coverage)
        snapshot_coverage_gaps = [
            row for row in snapshot_coverage if row["coverage_status"] != "complete"
        ]

        cohort_coverage = [
            row for row in snapshot_coverage if row["week_start_utc"] == cohort_week
        ] if cohort_week else []
        known_cohort_keys = {
            (row["week_start_utc"], row["support_tier"], row["region"])
            for row in snapshot_coverage if row["week_start_utc"] == cohort_week
        }
        if cohort_week:
            for key, values in tickets_by_partition.items():
                if key[0] == cohort_week and key not in known_cohort_keys:
                    cohort_coverage.append({
                        "week_start_utc": key[0],
                        "support_tier": key[1],
                        "region": key[2],
                        "expected_created_ticket_count": None,
                        "observed_created_ticket_count": len(values),
                        "manifest_available_at_utc": None,
                        "coverage_status": "unknown_calendar_partition",
                    })
        cohort_coverage.sort(key=lambda row: (row["support_tier"], row["region"]))

        future_ticket_timestamps = {
            field: sum(
                row[field] is not None and unix_seconds(row[field]) > cutoff_seconds
                for row in ticket_rows
            )
            for field in ("created_at_utc", "first_response_at_utc", "resolved_at_utc")
        }
        raw_table_names = (
            "calendar_partitions", "expected_partitions", "regions", "source_snapshot",
            "support_tier_sla", "ticket_events", "tickets",
        )
        raw_row_counts = {
            name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in raw_table_names
        }
        declared_counts = item.get("row_counts", {})
        manifest_table_count_matches = {
            name: declared_counts.get(name) == raw_row_counts[name]
            for name in raw_table_names if name in declared_counts
        }

        integrity = inspect_event_integrity(ticket_rows, event_rows, cutoff_text)
        result = {
            "source_cutoff_utc": cutoff_text,
            "snapshot": {
                "path": item["path"],
                "sha256": actual_hash,
                "mode_octal": format(stat.S_IMODE(snapshot_path.stat().st_mode), "04o"),
                "embedded_as_of_utc": clock_rows[0]["as_of_utc"],
                "raw_table_row_counts": raw_row_counts,
                "manifest_table_count_matches": manifest_table_count_matches,
            },
            "daily_raw_sets": {
                "open_without_visible_response_counts_by_priority": {
                    str(priority): unanswered_by_flag[priority]
                    for priority in sorted(set(unanswered_by_flag) | {0, PRIORITY_FLAG})
                },
                "priority_1_open_unanswered_over_first_response_clock": {
                    "count": len(overdue_unanswered), "records": overdue_unanswered,
                },
                "priority_1_open_responded_over_resolution_clock": {
                    "count": len(overdue_responded_open), "records": overdue_responded_open,
                },
                "consecutive_as_known_set_differences": set_changes,
            },
            "weekly_raw_facts": weekly,
            "coverage": {
                "snapshot_partition_status_counts": dict(sorted(coverage_status_counts.items())),
                "snapshot_non_complete_partitions": snapshot_coverage_gaps,
                "latest_cohort_creation_coverage_by_support_tier_and_region": cohort_coverage,
                "future_manifest_rows_in_snapshot": len(future_manifest_rows),
                "creation_manifest_scope_note": (
                    "These source rows reconcile creation counts only; they do not establish "
                    "first-response or resolution-event completeness."
                ),
            },
            "as_of_integrity": {
                "future_ticket_timestamp_rows": future_ticket_timestamps,
                "future_event_effective_rows": integrity["future_event_effective_rows"],
                "future_event_available_rows": integrity["future_event_available_rows"],
                "future_manifest_available_rows": len(future_manifest_rows),
                "event_kind_counts": integrity["event_kind_counts"],
                "duplicate_ticket_kind_groups": integrity["duplicate_ticket_kind_groups"],
                "ticket_event_state_mismatches": integrity["ticket_event_state_mismatches"],
                "ambiguous_duplicate_event_groups": integrity["ambiguous_duplicate_event_groups"],
            },
        }
    finally:
        connection.close()

    return result, current_sets


def build_reference(fixture_root: Path) -> dict[str, Any]:
    if fixture_root.is_symlink():
        raise ValueError("Fixture root must not be a symlink")
    fixture_root = fixture_root.resolve(strict=True)
    manifest_path = child_path(fixture_root, MANIFEST_RELATIVE_PATH.as_posix())
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("Fixture manifest must contain a nonempty snapshots list")

    previous_sets = None
    cutoff_results = []
    for item in snapshots:
        if not isinstance(item, dict) or not all(
            key in item for key in ("path", "sha256", "as_of_utc")
        ):
            raise ValueError("Each snapshot manifest entry needs path, sha256, and as_of_utc")
        result, previous_sets = analyze_snapshot(fixture_root, item, previous_sets)
        cutoff_results.append(result)
    cutoff_times = [parse_utc(row["source_cutoff_utc"]) for row in cutoff_results]
    if cutoff_times != sorted(set(cutoff_times)):
        raise ValueError("Snapshot cutoffs must be unique and ordered ascending")

    return {
        "artifact_purpose": "Independent raw source reference facts only; no outcome labels or human-message grade.",
        "fixture_name": fixture_root.name,
        "reviewer_manifest": {
            "path": MANIFEST_RELATIVE_PATH.as_posix(),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "manifest_id": manifest.get("manifest_id"),
        },
        "method": {
            "sqlite_access": "mode=ro&immutable=1; PRAGMA query_only=ON; direct base tables only.",
            "imports": "Python standard library only; no generator, projector, production metrics/helper, or actor outputs.",
            "priority_semantics": "priority=1 is the documented company priority-1 work-population flag; 0 is not flagged.",
            "clock_test": "Elapsed whole seconds are compared strictly greater than the source tier clock in hours*3600.",
            "weekly_cohort": "Latest source calendar week whose exclusive 7-day end is no later than the snapshot clock.",
            "weekly_denominator": "Flagged tickets in that creation week, resolved with a visible resolution timestamp no later than the cutoff.",
            "outcome_thresholds_applied": False,
            "source_writes": False,
            "report_output": "JSON is emitted to stdout unless --output is supplied.",
        },
        "cutoff_count": len(cutoff_results),
        "cutoffs": cutoff_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        required=True,
        help="Fixture root containing private/reviewer-manifest.json and snapshots/",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON to a new or existing output path; default is stdout",
    )
    args = parser.parse_args(argv)
    result = build_reference(args.fixture)
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        fixture_root = args.fixture.expanduser().resolve(strict=True)
        output_path = args.output.expanduser()
        if output_path.resolve(strict=False).is_relative_to(fixture_root):
            parser.error("--output must be outside the immutable --fixture root")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

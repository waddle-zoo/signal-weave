"""Independent read-only summaries of Harbor Help's raw SQLite tables."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_REQUIRED_COLUMNS = {
    "tickets": {
        "ticket_id", "week_start_utc", "created_at_utc", "support_tier", "region",
        "priority", "status", "first_response_at_utc", "resolved_at_utc",
    },
    "support_tier_sla": {
        "support_tier", "resolution_sla_hours", "first_response_sla_hours",
    },
    "source_ingestion_ledger": {
        "week_start_utc", "support_tier", "region", "expected_ticket_count",
        "received_ticket_count", "ingestion_status", "ingested_at_utc",
    },
    "source_snapshot": {"as_of_utc"},
}

_COUNT_FIELDS = (
    "observed_ticket_count",
    "eligible_resolved_priority_count",
    "late_resolved_priority_count",
    "responded_first_response_count",
    "late_first_response_count",
    "open_priority_count",
    "overdue_open_priority_count",
    "unanswered_count",
    "overdue_unanswered_count",
)
_RATE_FIELDS = {
    "late_resolution_rate": (
        "late_resolved_priority_count", "eligible_resolved_priority_count",
    ),
    "late_first_response_rate": (
        "late_first_response_count", "responded_first_response_count",
    ),
    "overdue_open_priority_rate": (
        "overdue_open_priority_count", "open_priority_count",
    ),
    "overdue_unanswered_rate": ("overdue_unanswered_count", "unanswered_count"),
}


def _parse_week_start(value: str, *, label: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an ISO date") from error
    if parsed.isoformat() != value or parsed.weekday() != 0:
        raise ValueError(f"{label} must be a Monday in YYYY-MM-DD form")
    return parsed


def _parse_utc(value: str | None, *, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{label} is not a valid UTC timestamp") from error
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be UTC")
    return parsed


def _validate_raw_tables(connection: sqlite3.Connection) -> None:
    for table, required_columns in _REQUIRED_COLUMNS.items():
        row = connection.execute(
            "SELECT type FROM sqlite_master WHERE name = ?", (table,)
        ).fetchone()
        if row is None or row[0] != "table":
            raise ValueError(f"required raw source {table!r} must be a table")
        columns = {
            item[1] for item in connection.execute(f'PRAGMA table_info("{table}")')
        }
        missing = required_columns - columns
        if missing:
            raise ValueError(f"raw source {table!r} is missing columns: {sorted(missing)}")


def _zero_counts() -> dict[str, int]:
    return dict.fromkeys(_COUNT_FIELDS, 0)


def _with_rates(counts: dict[str, int]) -> dict[str, Any]:
    result: dict[str, Any] = dict(counts)
    for name, (numerator, denominator) in _RATE_FIELDS.items():
        base = counts[denominator]
        result[name] = counts[numerator] / base if base else None
    return result


def _aggregate(cohorts: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        field: sum(cohort[field] for cohort in cohorts)
        for field in _COUNT_FIELDS
    }
    available = [cohort["coverage"] for cohort in cohorts if cohort["coverage"]["present"]]
    absent_count = len(cohorts) - len(available)
    coverage = {
        "present_segment_count": len(available),
        "absent_segment_count": absent_count,
        "known_expected_ticket_count_subtotal": (
            sum(item["expected_ticket_count"] for item in available) if available else None
        ),
        "known_received_ticket_count_subtotal": (
            sum(item["received_ticket_count"] for item in available) if available else None
        ),
        "known_missing_ticket_count_subtotal": (
            sum(item["missing_ticket_count"] for item in available) if available else None
        ),
        "expected_ticket_count": (
            sum(item["expected_ticket_count"] for item in available)
            if available and absent_count == 0 else None
        ),
        "received_ticket_count": (
            sum(item["received_ticket_count"] for item in available)
            if available and absent_count == 0 else None
        ),
        "observed_ticket_count": counts["observed_ticket_count"],
        "missing_ticket_count": (
            sum(item["missing_ticket_count"] for item in available)
            if available and absent_count == 0 else None
        ),
    }
    return {**_with_rates(counts), "coverage": coverage}


def _pool_by(
    cohorts: list[dict[str, Any]], field: str
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cohort in cohorts:
        grouped[cohort[field]].append(cohort)
    return [
        {field: value, **_aggregate(rows)}
        for value, rows in sorted(grouped.items())
    ]


def summarize(
    database: str | Path, week_start: str | date | None = None
) -> dict[str, Any]:
    """Recompute ticket clocks and ledger coverage from Harbor raw tables.

    Cohorts use the ticket's creation week. The ``week_start`` filter accepts
    an ISO Monday or ``datetime.date``. All source rows are validated before
    filtering; absent ledger records remain explicit in each cohort's coverage.
    Cohort keys are the union of ledger-declared and ticket-observed keys, so
    this reference cannot infer segments absent from both or prove full-population
    completeness independently.
    """
    if isinstance(week_start, datetime):
        raise ValueError("week_start must be a Monday date, not a datetime")
    if isinstance(week_start, date):
        requested_week = _parse_week_start(week_start.isoformat(), label="week_start")
    elif week_start is None:
        requested_week = None
    else:
        requested_week = _parse_week_start(week_start, label="week_start")

    path = Path(database)
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = path.resolve().as_uri() + "?mode=ro"

    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.execute("PRAGMA query_only = ON")
        _validate_raw_tables(connection)

        sla: dict[str, tuple[int, int]] = {}
        for tier, resolution_hours, response_hours in connection.execute(
            "SELECT support_tier, resolution_sla_hours, first_response_sla_hours "
            "FROM support_tier_sla"
        ):
            if tier in sla:
                raise ValueError(f"duplicate SLA definition for support tier {tier!r}")
            if (
                not isinstance(tier, str)
                or not tier
                or not isinstance(resolution_hours, int)
                or not isinstance(response_hours, int)
                or resolution_hours <= 0
                or response_hours <= 0
            ):
                raise ValueError("SLA hours must be positive integers with a tier name")
            sla[tier] = (resolution_hours, response_hours)
        if not sla:
            raise ValueError("support_tier_sla has no clock definitions")

        snapshot_rows = list(connection.execute("SELECT as_of_utc FROM source_snapshot"))
        if len(snapshot_rows) != 1:
            raise ValueError("source_snapshot must contain exactly one source cutoff")
        cutoff_text = snapshot_rows[0][0]
        if not isinstance(cutoff_text, str):
            raise ValueError("source_snapshot.as_of_utc must contain a source cutoff")
        cutoff = _parse_utc(cutoff_text, label="source_snapshot.as_of_utc")
        if cutoff is None:
            raise ValueError("source_snapshot.as_of_utc must contain a source cutoff")

        ledger: dict[tuple[str, str, str], dict[str, Any]] = {}
        for week_text, tier, region, expected, received, status, ingested_text in connection.execute(
            "SELECT week_start_utc, support_tier, region, expected_ticket_count, "
            "received_ticket_count, ingestion_status, ingested_at_utc "
            "FROM source_ingestion_ledger"
        ):
            week = _parse_week_start(week_text, label="ledger.week_start_utc")
            if tier not in sla:
                raise ValueError(f"ledger segment references undefined support tier {tier!r}")
            key = (week_text, tier, region)
            if key in ledger:
                raise ValueError(f"duplicate source-ingestion ledger segment {key!r}")
            if (
                not isinstance(expected, int)
                or not isinstance(received, int)
                or expected <= 0
                or received < 0
                or received > expected
            ):
                raise ValueError(f"invalid expected/received counts for ledger segment {key!r}")
            if status not in {"complete", "missing", "recovered"}:
                raise ValueError(f"invalid ingestion status for ledger segment {key!r}")
            ingested = _parse_utc(ingested_text, label=f"ledger {key!r} ingested_at_utc")
            if status == "missing":
                if received != 0 or ingested is not None:
                    raise ValueError(f"missing ledger segment {key!r} has received data")
            elif received != expected or ingested is None:
                raise ValueError(f"received ledger segment {key!r} has inconsistent counts/time")
            if ingested is not None and ingested > cutoff:
                raise ValueError(f"ledger ingestion for {key!r} is after the source cutoff")
            ledger[key] = {
                "expected_ticket_count": expected,
                "received_ticket_count": received,
                "missing_ticket_count": expected - received,
                "ingestion_status": status,
                "ingested_at_utc": ingested_text,
                "ingested_at": ingested,
                "week": week,
            }

        observed: Counter[tuple[str, str, str]] = Counter()
        cohort_counts: dict[tuple[str, str, str], dict[str, int]] = {}
        ticket_ids: set[str] = set()
        rows = connection.execute(
            "SELECT ticket_id, week_start_utc, created_at_utc, support_tier, region, "
            "priority, status, first_response_at_utc, resolved_at_utc FROM tickets"
        )
        for (
            ticket_id, week_text, created_text, tier, region, priority, status,
            response_text, resolved_text,
        ) in rows:
            if not isinstance(ticket_id, str) or not ticket_id:
                raise ValueError("tickets contains an empty or invalid ticket_id")
            if ticket_id in ticket_ids:
                raise ValueError(f"duplicate ticket_id {ticket_id!r}")
            ticket_ids.add(ticket_id)

            week = _parse_week_start(week_text, label=f"ticket {ticket_id!r} week_start_utc")
            created = _parse_utc(created_text, label=f"ticket {ticket_id!r} created_at_utc")
            assert created is not None
            if created.date() - timedelta(days=created.weekday()) != week:
                raise ValueError(f"ticket {ticket_id!r} creation date disagrees with its cohort week")
            if tier not in sla:
                raise ValueError(f"ticket {ticket_id!r} references undefined support tier {tier!r}")
            if not isinstance(region, str) or not region:
                raise ValueError(f"ticket {ticket_id!r} has an empty or invalid region")
            if priority not in (0, 1) or status not in {"open", "resolved"}:
                raise ValueError(f"ticket {ticket_id!r} has invalid priority/status")

            response = _parse_utc(response_text, label=f"ticket {ticket_id!r} first_response_at_utc")
            resolved = _parse_utc(resolved_text, label=f"ticket {ticket_id!r} resolved_at_utc")
            if response is not None and response < created:
                raise ValueError(f"ticket {ticket_id!r} first response predates creation")
            if resolved is not None and resolved < created:
                raise ValueError(f"ticket {ticket_id!r} resolution predates creation")
            if response is not None and resolved is not None and response > resolved:
                raise ValueError(f"ticket {ticket_id!r} first response follows resolution")
            if (status == "open") != (resolved is None):
                raise ValueError(f"ticket {ticket_id!r} status disagrees with resolution time")
            if any(event is not None and event > cutoff for event in (created, response, resolved)):
                raise ValueError(f"ticket {ticket_id!r} has an event after the source cutoff")

            key = (week_text, tier, region)
            observed[key] += 1
            ledger_entry = ledger.get(key)
            if ledger_entry is not None:
                ingested = ledger_entry["ingested_at"]
                if ingested is None:
                    raise ValueError(f"ticket {ticket_id!r} belongs to a non-received ledger segment")
                if any(event is not None and event >= ingested for event in (created, response, resolved)):
                    raise ValueError(f"ticket {ticket_id!r} has an event at/after its ingestion time")

            if requested_week is not None and week != requested_week:
                continue
            counts = cohort_counts.setdefault(key, _zero_counts())
            counts["observed_ticket_count"] += 1
            resolution_hours, response_hours = sla[tier]
            if priority == 1 and status == "resolved" and resolved is not None:
                counts["eligible_resolved_priority_count"] += 1
                if resolved - created > timedelta(hours=resolution_hours):
                    counts["late_resolved_priority_count"] += 1
            if response is not None:
                counts["responded_first_response_count"] += 1
                if response - created > timedelta(hours=response_hours):
                    counts["late_first_response_count"] += 1
            if status == "open":
                if priority == 1:
                    counts["open_priority_count"] += 1
                    if cutoff - created > timedelta(hours=resolution_hours):
                        counts["overdue_open_priority_count"] += 1
                if response is None:
                    counts["unanswered_count"] += 1
                    if cutoff - created > timedelta(hours=response_hours):
                        counts["overdue_unanswered_count"] += 1

        for key, entry in ledger.items():
            if observed[key] != entry["received_ticket_count"]:
                raise ValueError(
                    f"ledger received count disagrees with raw tickets for segment {key!r}"
                )

        keys = set(cohort_counts) | {
            key for key in ledger
            if requested_week is None or ledger[key]["week"] == requested_week
        }
        cohorts: list[dict[str, Any]] = []
        for week_text, tier, region in sorted(keys):
            counts = cohort_counts.get((week_text, tier, region), _zero_counts())
            entry = ledger.get((week_text, tier, region))
            coverage = (
                {
                    "present": True,
                    "expected_ticket_count": entry["expected_ticket_count"],
                    "received_ticket_count": entry["received_ticket_count"],
                    "missing_ticket_count": entry["missing_ticket_count"],
                    "ingestion_status": entry["ingestion_status"],
                    "ingested_at_utc": entry["ingested_at_utc"],
                }
                if entry is not None else
                {
                    "present": False,
                    "expected_ticket_count": None,
                    "received_ticket_count": None,
                    "missing_ticket_count": None,
                    "ingestion_status": None,
                    "ingested_at_utc": None,
                }
            )
            cohorts.append({
                "week_start_utc": week_text,
                "support_tier": tier,
                "region": region,
                **_with_rates(counts),
                "coverage": coverage,
            })

        missing_segments = [
            {
                "week_start_utc": cohort["week_start_utc"],
                "support_tier": cohort["support_tier"],
                "region": cohort["region"],
                "expected_ticket_count": cohort["coverage"]["expected_ticket_count"],
                "received_ticket_count": cohort["coverage"]["received_ticket_count"],
                "missing_ticket_count": cohort["coverage"]["missing_ticket_count"],
                "ingestion_status": cohort["coverage"]["ingestion_status"],
            }
            for cohort in cohorts
            if cohort["coverage"]["present"] and cohort["coverage"]["missing_ticket_count"] > 0
        ]
        uncovered_segments = [
            {
                "week_start_utc": cohort["week_start_utc"],
                "support_tier": cohort["support_tier"],
                "region": cohort["region"],
                "observed_ticket_count": cohort["observed_ticket_count"],
            }
            for cohort in cohorts
            if not cohort["coverage"]["present"]
        ]

        return {
            "source_cutoff_utc": cutoff_text,
            "week_start_filter": requested_week.isoformat() if requested_week else None,
            "coverage_scope_note": (
                "Cohort keys are the union of ledger-declared and ticket-observed keys. "
                "Segments absent from both cannot be inferred, so this summary does not "
                "independently prove whole-population completeness."
            ),
            "by_cohort": cohorts,
            "pooled": _aggregate(cohorts),
            "pooled_by_week": _pool_by(cohorts, "week_start_utc"),
            "pooled_by_tier": _pool_by(cohorts, "support_tier"),
            "pooled_by_region": _pool_by(cohorts, "region"),
            "missing_segments": missing_segments,
            "uncovered_segments": uncovered_segments,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Harbor Help SQLite database")
    parser.add_argument("--week-start", help="filter to a creation-week Monday (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    json.dump(summarize(args.database, args.week_start), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generate a bounded, deterministic raw-ticket SQLite fixture.

This module contains source data and source-owned SLA definitions only. It has
no alert policy, expected decision labels, evaluation imports, or source adapter.
"""

from __future__ import annotations

import os
import random
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_SEED = 20261016
WEEK_COUNT = 26
MAX_TICKETS = 10_000
FIRST_WEEK = date(2026, 1, 5)  # Monday; all periods are fixed UTC weeks.

TIERS = (
    ("enterprise", 48, 2),
    ("business", 24, 4),
    ("self_service", 12, 8),
)
REGIONS = ("north", "central", "south")

_TIER_WORKLOAD = {"enterprise": 14, "business": 27, "self_service": 65}
_REGION_WORKLOAD = {"north": 1.0, "central": 0.82, "south": 0.64}
_WEEK_WORKLOAD = (
    0.78, 0.86, 0.96, 1.08, 1.17, 1.26, 1.11, 0.92, 0.83, 0.98, 1.13, 1.21, 1.02,
)
_RESOLUTION_MISS_BASE = {"enterprise": 0.055, "business": 0.12, "self_service": 0.235}
_RESPONSE_MISS_BASE = {"enterprise": 0.055, "business": 0.11, "self_service": 0.205}
_WEEK_RATE_ADJUSTMENT = (
    -0.035, -0.025, -0.01, 0.0, 0.015, 0.035, 0.02, -0.005, -0.02, 0.01, 0.03, -0.015, 0.005,
)
_MISSING_INTERVAL = (15, "business", "central")
_RECOVERED_INTERVAL = (16, "business", "central")

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE support_tier_sla (
    support_tier TEXT PRIMARY KEY,
    resolution_sla_hours INTEGER NOT NULL CHECK (resolution_sla_hours > 0),
    first_response_sla_hours INTEGER NOT NULL CHECK (first_response_sla_hours > 0)
);

CREATE TABLE source_snapshot (
    snapshot_id INTEGER PRIMARY KEY CHECK (snapshot_id = 1),
    as_of_utc TEXT NOT NULL
);

CREATE TABLE tickets (
    ticket_id TEXT PRIMARY KEY,
    week_start_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    support_tier TEXT NOT NULL REFERENCES support_tier_sla(support_tier),
    region TEXT NOT NULL CHECK (region IN ('north', 'central', 'south')),
    priority INTEGER NOT NULL CHECK (priority IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('resolved', 'open')),
    first_response_at_utc TEXT,
    resolved_at_utc TEXT,
    CHECK (first_response_at_utc IS NULL OR first_response_at_utc >= created_at_utc),
    CHECK (resolved_at_utc IS NULL OR resolved_at_utc >= created_at_utc),
    CHECK ((status = 'open' AND resolved_at_utc IS NULL) OR
           (status = 'resolved' AND resolved_at_utc IS NOT NULL))
);

CREATE TABLE source_ingestion_ledger (
    week_start_utc TEXT NOT NULL,
    support_tier TEXT NOT NULL REFERENCES support_tier_sla(support_tier),
    region TEXT NOT NULL CHECK (region IN ('north', 'central', 'south')),
    expected_ticket_count INTEGER NOT NULL CHECK (expected_ticket_count > 0),
    received_ticket_count INTEGER NOT NULL CHECK (received_ticket_count >= 0),
    ingestion_status TEXT NOT NULL CHECK (ingestion_status IN ('complete', 'missing', 'recovered')),
    ingested_at_utc TEXT,
    PRIMARY KEY (week_start_utc, support_tier, region),
    CHECK ((ingestion_status = 'missing' AND received_ticket_count = 0 AND ingested_at_utc IS NULL)
        OR (ingestion_status IN ('complete', 'recovered')
            AND received_ticket_count = expected_ticket_count AND ingested_at_utc IS NOT NULL))
);

CREATE VIEW weekly_resolution_sla AS
SELECT
    t.week_start_utc,
    t.support_tier,
    t.region,
    COUNT(*) AS observed_ticket_count,
    SUM(CASE WHEN t.priority = 1 AND t.status = 'resolved'
              AND t.resolved_at_utc IS NOT NULL THEN 1 ELSE 0 END)
        AS eligible_resolved_tickets,
    SUM(CASE WHEN t.priority = 1 AND t.status = 'resolved'
              AND t.resolved_at_utc IS NOT NULL
              AND CAST(strftime('%s', t.resolved_at_utc) AS INTEGER) - CAST(strftime('%s', t.created_at_utc) AS INTEGER)
                  > s.resolution_sla_hours * 3600 THEN 1 ELSE 0 END)
        AS resolution_sla_misses,
    1.0 * SUM(CASE WHEN t.priority = 1 AND t.status = 'resolved'
                    AND t.resolved_at_utc IS NOT NULL
                    AND CAST(strftime('%s', t.resolved_at_utc) AS INTEGER) - CAST(strftime('%s', t.created_at_utc) AS INTEGER)
                        > s.resolution_sla_hours * 3600 THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN t.priority = 1 AND t.status = 'resolved'
                           AND t.resolved_at_utc IS NOT NULL THEN 1 ELSE 0 END), 0)
        AS resolution_sla_miss_rate
FROM tickets AS t
JOIN support_tier_sla AS s USING (support_tier)
GROUP BY t.week_start_utc, t.support_tier, t.region;

CREATE VIEW weekly_first_response_sla AS
SELECT
    t.week_start_utc,
    t.support_tier,
    t.region,
    COUNT(*) AS observed_ticket_count,
    SUM(CASE WHEN t.first_response_at_utc IS NOT NULL THEN 1 ELSE 0 END)
        AS first_response_clock_tickets,
    SUM(CASE WHEN t.first_response_at_utc IS NOT NULL
              AND CAST(strftime('%s', t.first_response_at_utc) AS INTEGER) - CAST(strftime('%s', t.created_at_utc) AS INTEGER)
                  > s.first_response_sla_hours * 3600 THEN 1 ELSE 0 END)
        AS first_response_sla_misses,
    SUM(CASE WHEN t.status = 'open' AND t.first_response_at_utc IS NOT NULL
             THEN 1 ELSE 0 END) AS open_tickets_with_response_clock,
    1.0 * SUM(CASE WHEN t.first_response_at_utc IS NOT NULL
                    AND CAST(strftime('%s', t.first_response_at_utc) AS INTEGER) - CAST(strftime('%s', t.created_at_utc) AS INTEGER)
                        > s.first_response_sla_hours * 3600 THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN t.first_response_at_utc IS NOT NULL THEN 1 ELSE 0 END), 0)
        AS first_response_sla_miss_rate
FROM tickets AS t
JOIN support_tier_sla AS s USING (support_tier)
GROUP BY t.week_start_utc, t.support_tier, t.region;

CREATE VIEW weekly_source_coverage AS
SELECT
    l.week_start_utc,
    l.support_tier,
    l.region,
    l.expected_ticket_count,
    COUNT(t.ticket_id) AS observed_ticket_count,
    l.expected_ticket_count - COUNT(t.ticket_id) AS missing_ticket_count,
    l.ingestion_status,
    CASE WHEN COUNT(t.ticket_id) = 0 THEN 'missing'
         WHEN COUNT(t.ticket_id) < l.expected_ticket_count THEN 'partial'
         ELSE l.ingestion_status END AS coverage_status,
    l.ingested_at_utc
FROM source_ingestion_ledger AS l
LEFT JOIN tickets AS t
    ON t.week_start_utc = l.week_start_utc
   AND t.support_tier = l.support_tier
   AND t.region = l.region
GROUP BY l.week_start_utc, l.support_tier, l.region,
         l.expected_ticket_count, l.ingestion_status, l.ingested_at_utc;

CREATE VIEW weekly_open_backlog AS
SELECT t.week_start_utc, t.support_tier, t.region, snapshot.as_of_utc,
    SUM(CASE WHEN t.priority = 1 THEN 1 ELSE 0 END) AS open_priority_tickets,
    SUM(CASE WHEN t.priority = 1
              AND CAST(strftime('%s', snapshot.as_of_utc) AS INTEGER) - CAST(strftime('%s', t.created_at_utc) AS INTEGER)
                  > s.resolution_sla_hours * 3600 THEN 1 ELSE 0 END)
        AS overdue_open_priority_tickets,
    SUM(CASE WHEN t.first_response_at_utc IS NULL THEN 1 ELSE 0 END)
        AS unanswered_tickets,
    SUM(CASE WHEN t.first_response_at_utc IS NULL
              AND CAST(strftime('%s', snapshot.as_of_utc) AS INTEGER) - CAST(strftime('%s', t.created_at_utc) AS INTEGER)
                  > s.first_response_sla_hours * 3600 THEN 1 ELSE 0 END)
        AS overdue_unanswered_tickets
FROM tickets AS t
JOIN support_tier_sla AS s USING (support_tier)
CROSS JOIN source_snapshot AS snapshot
WHERE t.status = 'open'
GROUP BY t.week_start_utc, t.support_tier, t.region, snapshot.as_of_utc;
"""


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _interval_workload(rng: random.Random, week_index: int, tier: str, region: str) -> int:
    seasonal = _WEEK_WORKLOAD[week_index % len(_WEEK_WORKLOAD)]
    count = round(_TIER_WORKLOAD[tier] * _REGION_WORKLOAD[region] * seasonal)
    return max(8, count + rng.randint(-2, 2))


def _ticket_rows(
    rng: random.Random,
    week_index: int,
    week_start: date,
    tier: str,
    region: str,
    count: int,
    resolution_sla_hours: int,
    first_response_sla_hours: int,
) -> list[tuple[Any, ...]]:
    rows = []
    start = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    resolution_rate = min(
        0.32,
        max(0.01, _RESOLUTION_MISS_BASE[tier]
            + _WEEK_RATE_ADJUSTMENT[week_index % len(_WEEK_RATE_ADJUSTMENT)]),
    )
    response_rate = min(
        0.30,
        max(0.01, _RESPONSE_MISS_BASE[tier]
            + _WEEK_RATE_ADJUSTMENT[(week_index + 4) % len(_WEEK_RATE_ADJUSTMENT)]),
    )
    tier_code = {"enterprise": "ENT", "business": "BUS", "self_service": "SELF"}[tier]
    region_code = {"north": "N", "central": "C", "south": "S"}[region]

    for ticket_index in range(count):
        created = start + timedelta(
            minutes=rng.randrange(7 * 24 * 60), seconds=rng.randrange(60)
        )
        is_open = rng.random() < 0.13
        priority = int(rng.random() < 0.72)
        # Resolved tickets have a response clock; some open tickets are still
        # waiting for first response, which keeps the two SLA populations distinct.
        has_response = not is_open or rng.random() < 0.58
        response_minutes: int | None = None
        if has_response:
            response_missed = rng.random() < response_rate
            if response_missed:
                response_minutes = first_response_sla_hours * 60 + rng.randint(1, 360)
            else:
                response_minutes = rng.randint(1, first_response_sla_hours * 60)
        first_response = (
            _utc_timestamp(created + timedelta(minutes=response_minutes))
            if response_minutes is not None else None
        )

        resolved_at = None
        status = "open" if is_open else "resolved"
        if not is_open:
            if priority:
                resolution_missed = rng.random() < resolution_rate
            else:
                resolution_missed = rng.random() < 0.16
            floor_minutes = (response_minutes or 0) + 1
            if resolution_missed:
                resolution_minutes = max(
                    floor_minutes, resolution_sla_hours * 60 + rng.randint(1, 720)
                )
            else:
                resolution_minutes = max(
                    floor_minutes, rng.randint(1, resolution_sla_hours * 60)
                )
            resolved_at = _utc_timestamp(created + timedelta(minutes=resolution_minutes))

        ticket_id = (
            f"HH-{week_index + 1:02d}-{tier_code}-{region_code}-{ticket_index + 1:04d}"
        )
        rows.append((
            ticket_id,
            week_start.isoformat(),
            _utc_timestamp(created),
            tier,
            region,
            priority,
            status,
            first_response,
            resolved_at,
        ))
    return rows


def _created_file_identity(descriptor: int) -> tuple[int, int]:
    stat = os.fstat(descriptor)
    return stat.st_dev, stat.st_ino


def _remove_if_still_ours(path: Path, identity: tuple[int, int]) -> None:
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return
    if (stat.st_dev, stat.st_ino) == identity:
        path.unlink()


def generate_database(output_path: str | os.PathLike[str], *, seed: int = DEFAULT_SEED) -> Path:
    """Create a new fixture database at an explicit, unused path.

    Existing files and symlinks are rejected. The output parent directory must
    already exist. The fixed 26-week data set is bounded to at most MAX_TICKETS.
    """
    path = Path(output_path)
    if not path.name or path.name in {".", ".."}:
        raise ValueError("output_path must name a new SQLite database file")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {path.parent}")

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    identity = _created_file_identity(descriptor)
    os.close(descriptor)
    rng = random.Random(seed)
    inserted_ticket_count = 0
    try:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript(_SCHEMA)
            connection.executemany(
                "INSERT INTO support_tier_sla VALUES (?, ?, ?)", TIERS
            )
            ticket_insert = """
                INSERT INTO tickets (
                    ticket_id, week_start_utc, created_at_utc, support_tier, region,
                    priority, status, first_response_at_utc, resolved_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            ledger_insert = """
                INSERT INTO source_ingestion_ledger (
                    week_start_utc, support_tier, region, expected_ticket_count,
                    received_ticket_count, ingestion_status, ingested_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """

            for week_index in range(WEEK_COUNT):
                week_start = FIRST_WEEK + timedelta(weeks=week_index)
                week_start_text = week_start.isoformat()
                for tier, resolution_hours, response_hours in TIERS:
                    for region in REGIONS:
                        expected_count = _interval_workload(rng, week_index, tier, region)
                        interval = (week_index, tier, region)
                        missing = interval == _MISSING_INTERVAL
                        recovered = interval == _RECOVERED_INTERVAL
                        status = "missing" if missing else "recovered" if recovered else "complete"
                        ingested_at = None
                        received_count = 0 if missing else expected_count
                        if not missing:
                            delay_days = 14 if recovered else 7
                            ingested_at = _utc_timestamp(
                                datetime.combine(week_start, time.min, tzinfo=timezone.utc)
                                + timedelta(days=delay_days, hours=3)
                            )
                            rows = _ticket_rows(
                                rng, week_index, week_start, tier, region, expected_count,
                                resolution_hours, response_hours,
                            )
                            # These are final retrospective states, not a
                            # week-end snapshot. Ingestion cannot predate an
                            # event contained in the supplied interval.
                            last_event = max(
                                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                                for row in rows
                                for timestamp in (row[2], row[7], row[8])
                                if timestamp is not None
                            )
                            ingested_at = max(
                                ingested_at, _utc_timestamp(last_event + timedelta(hours=3))
                            )
                            inserted_ticket_count += len(rows)
                            if inserted_ticket_count > MAX_TICKETS:
                                raise RuntimeError(
                                    f"generated fixture exceeds the {MAX_TICKETS}-ticket bound"
                                )
                            connection.executemany(ticket_insert, rows)
                        connection.execute(
                            ledger_insert,
                            (week_start_text, tier, region, expected_count, received_count,
                             status, ingested_at),
                        )
            connection.execute(
                "INSERT INTO source_snapshot SELECT 1, MAX(ingested_at_utc) "
                "FROM source_ingestion_ledger"
            )
            connection.execute("PRAGMA user_version = 1")
    except BaseException:
        _remove_if_still_ours(path, identity)
        raise
    return path

"""Raw operational support history for development trials, never policy labels.

The full history stays with the research caller. A source process receives only
one newly materialized as-of database. This is not an agent, source adapter,
onboarding result, or an upgrade of the closed retrospective Harbor cohort.
"""

from __future__ import annotations

import json
import math
import os
import random
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evaluations.available_history import project_events

_FIELDS = {
    "created": {"kind", "ticket_id", "support_tier", "region", "priority"},
    "response": {"kind", "ticket_id"},
    "resolution": {"kind", "ticket_id"},
    "partition": {"kind", "week_start_utc", "support_tier", "region", "expected_ticket_count"},
}
WARMUP_WEEKS = 6
OBSERVATION_COUNT = 12

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE source_snapshot (snapshot_id INTEGER PRIMARY KEY CHECK(snapshot_id=1), as_of_utc TEXT NOT NULL);
CREATE TABLE support_tier_sla (support_tier TEXT PRIMARY KEY, resolution_sla_hours INTEGER NOT NULL, first_response_sla_hours INTEGER NOT NULL);
CREATE TABLE regions (region TEXT PRIMARY KEY);
CREATE TABLE calendar_partitions (week_start_utc TEXT, support_tier TEXT, region TEXT, PRIMARY KEY(week_start_utc,support_tier,region));
CREATE TABLE expected_partitions (week_start_utc TEXT, support_tier TEXT, region TEXT, expected_ticket_count INTEGER NOT NULL, available_at_utc TEXT NOT NULL, PRIMARY KEY(week_start_utc,support_tier,region));
CREATE TABLE ticket_events (event_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, kind TEXT NOT NULL, ticket_id TEXT NOT NULL, effective_at_utc TEXT NOT NULL, available_at_utc TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE tickets (ticket_id TEXT PRIMARY KEY, week_start_utc TEXT NOT NULL, created_at_utc TEXT NOT NULL, support_tier TEXT NOT NULL REFERENCES support_tier_sla(support_tier), region TEXT NOT NULL REFERENCES regions(region), priority INTEGER NOT NULL CHECK(priority IN(0,1)), status TEXT NOT NULL CHECK(status IN('open','resolved')), first_response_at_utc TEXT, resolved_at_utc TEXT);

CREATE VIEW weekly_ticket_clocks AS
SELECT t.week_start_utc, t.support_tier, t.region, COUNT(*) AS observed_ticket_count,
 SUM(CASE WHEN t.priority=1 AND t.resolved_at_utc IS NOT NULL THEN 1 ELSE 0 END) AS eligible_resolved_tickets,
 SUM(CASE WHEN t.priority=1 AND unixepoch(t.resolved_at_utc)-unixepoch(t.created_at_utc)>s.resolution_sla_hours*3600 THEN 1 ELSE 0 END) AS resolution_sla_misses,
 SUM(CASE WHEN t.first_response_at_utc IS NOT NULL THEN 1 ELSE 0 END) AS first_response_clock_tickets,
 SUM(CASE WHEN unixepoch(t.first_response_at_utc)-unixepoch(t.created_at_utc)>s.first_response_sla_hours*3600 THEN 1 ELSE 0 END) AS first_response_sla_misses,
 SUM(CASE WHEN t.priority=1 AND t.resolved_at_utc IS NULL THEN 1 ELSE 0 END) AS open_priority_tickets,
 SUM(CASE WHEN t.priority=1 AND t.resolved_at_utc IS NULL AND unixepoch(x.as_of_utc)-unixepoch(t.created_at_utc)>s.resolution_sla_hours*3600 THEN 1 ELSE 0 END) AS overdue_open_priority_tickets,
 SUM(CASE WHEN t.resolved_at_utc IS NULL AND t.first_response_at_utc IS NULL THEN 1 ELSE 0 END) AS unanswered_tickets,
 SUM(CASE WHEN t.resolved_at_utc IS NULL AND t.first_response_at_utc IS NULL AND unixepoch(x.as_of_utc)-unixepoch(t.created_at_utc)>s.first_response_sla_hours*3600 THEN 1 ELSE 0 END) AS overdue_unanswered_tickets
FROM tickets t JOIN support_tier_sla s USING(support_tier) CROSS JOIN source_snapshot x
GROUP BY t.week_start_utc,t.support_tier,t.region;

CREATE VIEW weekly_resolution_sla AS
SELECT week_start_utc,support_tier,region,observed_ticket_count,eligible_resolved_tickets,resolution_sla_misses,
 1.0*resolution_sla_misses/NULLIF(eligible_resolved_tickets,0) AS resolution_sla_miss_rate FROM weekly_ticket_clocks;
CREATE VIEW weekly_first_response_sla AS
SELECT week_start_utc,support_tier,region,observed_ticket_count,first_response_clock_tickets,first_response_sla_misses,
 1.0*first_response_sla_misses/NULLIF(first_response_clock_tickets,0) AS first_response_sla_miss_rate FROM weekly_ticket_clocks;
CREATE VIEW weekly_open_backlog AS
SELECT week_start_utc,support_tier,region,as_of_utc,open_priority_tickets,overdue_open_priority_tickets,unanswered_tickets,overdue_unanswered_tickets
FROM weekly_ticket_clocks CROSS JOIN source_snapshot;
CREATE VIEW weekly_source_coverage AS
WITH counts AS (SELECT week_start_utc,support_tier,region,COUNT(*) AS n FROM tickets GROUP BY week_start_utc,support_tier,region)
SELECT c.week_start_utc,c.support_tier,c.region,e.expected_ticket_count,COALESCE(t.n,0) AS observed_ticket_count,
 e.expected_ticket_count-COALESCE(t.n,0) AS missing_ticket_count,
 CASE WHEN e.expected_ticket_count IS NULL THEN 'unknown'
 WHEN COALESCE(t.n,0)=e.expected_ticket_count THEN 'complete'
 WHEN COALESCE(t.n,0)>e.expected_ticket_count THEN 'excess'
 WHEN COALESCE(t.n,0)=0 THEN 'missing' ELSE 'partial' END AS coverage_status,
 e.available_at_utc AS manifest_available_at_utc
FROM calendar_partitions c LEFT JOIN expected_partitions e USING(week_start_utc,support_tier,region)
LEFT JOIN counts t USING(week_start_utc,support_tier,region);
"""


def _instant(value):
    if not isinstance(value, datetime) or value.utcoffset() is None or value.microsecond:
        raise ValueError("History times must be aware datetimes at one-second precision")
    return value.astimezone(timezone.utc)


def _stamp(value):
    return _instant(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _week(value):
    value = _instant(value)
    return (value.date() - timedelta(days=value.weekday())).isoformat()


def _config(history):
    first = _instant(history["first_week"])
    if first.weekday() or first.hour or first.minute or first.second:
        raise ValueError("first_week must be a UTC Monday at midnight")
    clocks = history["clock_definitions"]
    if not clocks or len({row["support_tier"] for row in clocks}) != len(clocks):
        raise ValueError("Clock tiers must be distinct and nonempty")
    for row in clocks:
        if not isinstance(row["support_tier"], str) or not row["support_tier"].strip():
            raise ValueError("Clock tiers need names")
        if any(type(row[key]) is not int or row[key] <= 0 for key in ("resolution_sla_hours", "first_response_sla_hours")):
            raise ValueError("Clock limits must be positive integer hours")
    regions = history["regions"]
    if not regions or len(set(regions)) != len(regions) or any(not isinstance(r, str) or not r.strip() for r in regions):
        raise ValueError("Regions must be distinct nonempty names")
    return first, clocks, regions


def _visible(history, cutoff):
    first, clocks, regions = _config(history)
    tiers = {row["support_tier"] for row in clocks}
    identities = {}
    for record in history["events"]:
        if not isinstance(record, dict) or set(record) != {"event_id", "revision", "effective_at", "available_at", "tombstone", "payload"}:
            raise ValueError("Only the declared event fields are accepted")
        effective, available = _instant(record["effective_at"]), _instant(record["available_at"])
        if available < effective:
            raise ValueError("An event cannot arrive before it happened")
        payload = record["payload"]
        kind = payload.get("kind") if isinstance(payload, dict) else None
        if kind not in _FIELDS or set(payload) != _FIELDS[kind]:
            raise ValueError("Only the declared source payload fields are accepted")
        if kind in {"created", "partition"}:
            if payload["support_tier"] not in tiers or payload["region"] not in regions:
                raise ValueError("Unknown source tier or region")
        if kind == "created" and (type(payload["priority"]) is not int or payload["priority"] not in (0, 1)):
            raise ValueError("Priority must be zero or one")
        if kind == "partition":
            week = datetime.fromisoformat(payload["week_start_utc"]).replace(tzinfo=timezone.utc)
            if (week.strftime("%Y-%m-%d") != payload["week_start_utc"] or week.weekday()
                    or week < first or effective != week + timedelta(weeks=1)):
                raise ValueError("Partition events identify a closed UTC week")
            if type(payload["expected_ticket_count"]) is not int or payload["expected_ticket_count"] < 0:
                raise ValueError("Expected counts must be nonnegative integers")
        elif not isinstance(payload["ticket_id"], str) or not payload["ticket_id"].strip():
            raise ValueError("Ticket IDs must be nonempty")
        identity = ((kind, payload["week_start_utc"], payload["support_tier"], payload["region"])
                    if kind == "partition" else (kind, payload["ticket_id"]))
        prior = identities.setdefault(record["event_id"], identity)
        if prior != identity:
            raise ValueError("Event identity cannot change across revisions")
    return project_events(history["events"], cutoff)


def make_history(*, seed=20261018, weeks=WARMUP_WEEKS + OBSERVATION_COUNT):
    """Generate source records, with delayed batches and corrections but no decisions."""
    if type(seed) is not int or type(weeks) is not int or not 1 <= weeks <= 54:
        raise ValueError("Use an integer seed and 1..54 weeks")
    rng = random.Random(seed)
    first = datetime(2026, 1, 5, tzinfo=timezone.utc)
    clocks = [{"support_tier": tier, "resolution_sla_hours": resolution, "first_response_sla_hours": response}
              for tier, resolution, response in (("enterprise", 48, 2), ("business", 24, 4), ("self_service", 12, 8))]
    regions = ["north", "central", "south"]
    events = []

    def append(event_id, kind, effective, available, payload, revision=1, tombstone=False):
        events.append({"event_id": event_id, "revision": revision, "effective_at": effective,
            "available_at": available, "tombstone": tombstone, "payload": {"kind": kind, **payload}})

    for week_index in range(weeks):
        week = first + timedelta(weeks=week_index)
        for tier_index, clock in enumerate(clocks):
            tier = clock["support_tier"]
            for region_index, region in enumerate(regions):
                count = max(1, int((12, 27, 46)[tier_index] * (1 - region_index * 0.18)
                                  * (1 + 0.18 * math.sin(week_index * 0.9))) + rng.randint(-2, 2))
                if (week_index, tier, region) == (1, "enterprise", "south"):
                    count = 0
                batch_delay = timedelta(days=9) if (week_index, tier, region) == (9, "business", "central") else timedelta(0)
                manifest_delay = timedelta(days=8) if (week_index, tier, region) == (12, "self_service", "central") else timedelta(0)
                append(f"partition:{week_index}:{tier}:{region}", "partition", week + timedelta(weeks=1),
                    week + timedelta(weeks=1, hours=1) + manifest_delay,
                    {"week_start_utc": week.date().isoformat(), "support_tier": tier, "region": region, "expected_ticket_count": count})
                for index in range(count):
                    ticket = f"t-{rng.getrandbits(96):024x}"
                    created = week + timedelta(seconds=rng.randrange(7 * 86400))
                    priority = int(rng.random() < 0.68)
                    payload = {"ticket_id": ticket, "support_tier": tier, "region": region, "priority": priority}
                    append(f"{ticket}:created", "created", created, created + timedelta(hours=2) + batch_delay, payload)
                    response_seconds = None
                    if rng.random() < 0.93:
                        response_seconds = max(60, int(clock["first_response_sla_hours"] * 3600 * rng.uniform(0.1, 1.5)))
                        responded = created + timedelta(seconds=response_seconds)
                        append(f"{ticket}:response", "response", responded, responded + timedelta(hours=1) + batch_delay, {"ticket_id": ticket})
                    retract_example = (week_index, tier, region, index) == (8, "business", "north", 2)
                    if rng.random() < 0.96 or retract_example:
                        factor = rng.uniform(0.1, 1.4 + 0.3 * math.sin(week_index * 0.7))
                        seconds = max((response_seconds or 0) + 60, int(clock["resolution_sla_hours"] * 3600 * factor))
                        # Synthetic profile, not empirical service rates: 15%
                        # of eventual resolutions have a 7..28-day tail.
                        if rng.random() < 0.15 and not retract_example:
                            seconds = rng.randint(7 * 86400, 28 * 86400)
                        resolved = created + timedelta(seconds=seconds)
                        append(f"{ticket}:resolution", "resolution", resolved, resolved + timedelta(hours=2) + batch_delay, {"ticket_id": ticket})
                        if retract_example:
                            retracted = max(resolved + timedelta(hours=3), week + timedelta(weeks=1, hours=10))
                            append(f"{ticket}:resolution", "resolution", resolved, retracted, {"ticket_id": ticket}, 2, True)
                            append(f"{ticket}:resolution", "resolution", resolved, retracted + timedelta(days=10), {"ticket_id": ticket}, 3)
                    if (week_index, tier, region, index) == (7, "enterprise", "north", 0):
                        append(f"{ticket}:created", "created", created, created + timedelta(days=10),
                            {**payload, "priority": 1 - priority}, 2)
    return {"first_week": first, "clock_definitions": clocks, "regions": regions, "events": events}


def weekly_cutoffs(history):
    """Twelve cutoffs after six warmup weeks in the default 18-week fixture."""
    return [history["first_week"] + timedelta(weeks=week, hours=6)
            for week in range(WARMUP_WEEKS + 1, WARMUP_WEEKS + OBSERVATION_COUNT + 1)]


def materialize_snapshot(history, cutoff, output_path):
    """Write only knowable raw events and derived current source state to a new file."""
    cutoff = _instant(cutoff)
    first, clocks, regions = _config(history)
    if cutoff < first:
        raise ValueError("Snapshot cutoff precedes the source calendar")
    records = _visible(history, cutoff)
    created, child_events, partitions, event_rows = {}, defaultdict(dict), [], []
    semantic_ids = set()
    for record in records:
        payload = record["payload"]
        kind = payload["kind"]
        if kind == "partition":
            key = (kind, payload["week_start_utc"], payload["support_tier"], payload["region"])
            partitions.append((*key[1:], payload["expected_ticket_count"], _stamp(record["available_at"])))
        else:
            ticket = payload["ticket_id"]
            key = (kind, ticket)
            event_rows.append((record["event_id"], record["revision"], kind, ticket,
                _stamp(record["effective_at"]), _stamp(record["available_at"]), json.dumps(payload, sort_keys=True)))
            if kind == "created":
                created[ticket] = record
            else:
                child_events[ticket][kind] = record
        if key in semantic_ids:
            raise ValueError("Multiple active events for the same ticket kind or partition")
        semantic_ids.add(key)
    tickets = []
    for ticket, record in sorted(created.items()):
        payload, when = record["payload"], _instant(record["effective_at"])
        if when < first:
            raise ValueError("Ticket creation precedes the source calendar")
        times = {kind: _instant(row["effective_at"]) for kind, row in child_events[ticket].items()}
        if any(value < when for value in times.values()):
            raise ValueError("Response or resolution precedes its known creation")
        tickets.append((ticket, _week(when), _stamp(when), payload["support_tier"], payload["region"], payload["priority"],
            "resolved" if "resolution" in times else "open", _stamp(times["response"]) if "response" in times else None,
            _stamp(times["resolution"]) if "resolution" in times else None))
    calendar, week = [], first
    while week + timedelta(weeks=1) <= cutoff:
        calendar.extend((week.date().isoformat(), row["support_tier"], region) for row in clocks for region in regions)
        week += timedelta(weeks=1)
    path = Path(output_path)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    identity = os.fstat(descriptor)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(_SCHEMA)
            connection.execute("INSERT INTO source_snapshot VALUES(1,?)", (_stamp(cutoff),))
            connection.executemany("INSERT INTO support_tier_sla VALUES(:support_tier,:resolution_sla_hours,:first_response_sla_hours)", clocks)
            connection.executemany("INSERT INTO regions VALUES(?)", [(region,) for region in regions])
            connection.executemany("INSERT INTO calendar_partitions VALUES(?,?,?)", calendar)
            connection.executemany("INSERT INTO expected_partitions VALUES(?,?,?,?,?)", sorted(partitions))
            connection.executemany("INSERT INTO ticket_events VALUES(?,?,?,?,?,?,?)", sorted(event_rows))
            connection.executemany("INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?)", tickets)
            connection.commit()
    except BaseException:
        # Remove only the newly created file if it still has our exact identity.
        try:
            current = path.lstat()
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                path.unlink()
        raise
    return path

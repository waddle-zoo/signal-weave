"""Bounded synthetic parcel history; source facts, not policy or trial labels."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from evaluations.available_history import project_events
from examples.harbor_help import company_mcp as raw

SOURCE_ID = "pine_courier_parcel_history"
ADAPTER = "pine_courier"
CUTOFFS = ("2026-09-21T06:00:00Z", "2026-09-28T06:00:00Z", "2026-10-05T06:00:00Z")
DEFINITION = ("Noncancelled parcels delivered at or before their promised UTC timestamp / "
              "all noncancelled parcels due in the half-open UTC due week, including "
              "overdue undelivered parcels. Cancellation and delivery use visible source events.")


def _time(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an aware source clock is required")
    return value.astimezone(timezone.utc)


def _stamp(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_history():
    """Return controller-only events and source registration manifests, never labels."""
    start = _time("2026-09-07T00:00:00Z")
    events, manifests = [], []

    def event(parcel, kind, effective, delay, payload=None):
        events.append({"event_id": f"{parcel}:{kind}", "revision": 1,
                       "effective_at": effective, "available_at": effective + delay,
                       "payload": {"parcel_id": parcel, "event_type": kind, **(payload or {})},
                       "tombstone": False})

    for week, count in enumerate((2400, 3000, 3600, 4200)):
        monday = start + timedelta(weeks=week)
        tiers = Counter()
        for number in range(count):
            parcel = "p-" + hashlib.sha256(f"pine:{week}:{number}".encode()).hexdigest()[:22]
            tier = "priority" if number % 4 == 0 else "standard"
            tiers[tier] += 1
            due = monday + timedelta(days=number % 7, hours=8 + number % 12, seconds=number % 59)
            event(parcel, "registration", due - timedelta(days=3), timedelta(minutes=5),
                  {"service_tier": tier, "due_at_utc": _stamp(due)})
            if number % 20 == 0:
                event(parcel, "cancellation", due - timedelta(hours=2), timedelta(minutes=10))
            elif number % 100 < (90, 90, 82, 88)[week]:
                event(parcel, "delivery", due - timedelta(hours=number % 2), timedelta(minutes=15))
            elif number % 3:
                event(parcel, "delivery", due + timedelta(hours=48), timedelta(minutes=30))
        for tier, expected in tiers.items():
            manifests.append({"week_start_utc": _stamp(monday), "service_tier": tier,
                              "expected_parcel_count": expected,
                              "available_at": monday + timedelta(days=7, hours=3)})
    return {"events": events, "manifests": manifests}


def _state(history, cutoff):
    visible = project_events(history["events"], cutoff)
    parcels = {}
    for e in visible:
        p = e["payload"]
        if p["event_type"] == "registration":
            parcels[p["parcel_id"]] = {
                "parcel_id": p["parcel_id"], "service_tier": p["service_tier"],
                "due_at_utc": p["due_at_utc"], "registered_at_utc": _stamp(e["effective_at"]),
                "registration_available_at_utc": _stamp(e["available_at"]),
                "cancelled_at_utc": None, "cancellation_available_at_utc": None,
                "delivered_at_utc": None, "delivery_available_at_utc": None,
            }
    for e in visible:
        p = e["payload"]
        if p["event_type"] in {"cancellation", "delivery"}:
            row = parcels[p["parcel_id"]]
            field = "cancelled" if p["event_type"] == "cancellation" else "delivered"
            row[field + "_at_utc"] = _stamp(e["effective_at"])
            row[p["event_type"] + "_available_at_utc"] = _stamp(e["available_at"])
    return parcels, visible


def materialize_snapshot(history, cutoff, output_path):
    """Exclusively create one of three knowable source snapshots; no model calls."""
    cutoff = _time(cutoff)
    if _stamp(cutoff) not in CUTOFFS:
        raise ValueError("select one of the three declared source cutoffs")
    end = cutoff.replace(hour=0)
    parcels, events = _state(history, cutoff)
    manifests = [m for m in history["manifests"] if m["available_at"] <= cutoff]
    exports = []
    for week in sorted({m["week_start_utc"] for m in manifests}):
        start = _time(week)
        published = start + timedelta(days=7, hours=6)
        if published > cutoff:
            continue
        inputs, _ = _state(history, published)
        for tier in ("ALL", "priority", "standard"):
            selected = [p for p in inputs.values() if start <= _time(p["due_at_utc"]) < start + timedelta(days=7)
                        and p["cancelled_at_utc"] is None and (tier == "ALL" or p["service_tier"] == tier)]
            numerator = sum(p["delivered_at_utc"] is not None and p["delivered_at_utc"] <= p["due_at_utc"]
                            for p in selected)
            omitted = week == "2026-09-21T00:00:00Z" and tier == "ALL"
            exports.append((week, tier, 1, numerator, None if omitted else len(selected),
                            _stamp(published), _stamp(published),
                            "Cached total denominator serialization omitted." if omitted else "Initial source export.", "v1"))
            repaired = published + timedelta(days=7)
            if omitted and repaired <= cutoff:
                exports.append((week, tier, 2, numerator, len(selected), _stamp(repaired),
                                _stamp(published), "Denominator republished from unchanged parcel input.", "v1"))
    path = Path(output_path)
    path.touch(mode=0o600, exist_ok=False)
    try:
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE source_snapshot(as_of_utc TEXT,baseline_start_utc TEXT,
                  current_start_utc TEXT,current_end_utc TEXT);
                CREATE TABLE parcels(parcel_id TEXT PRIMARY KEY,service_tier TEXT,due_at_utc TEXT,
                  registered_at_utc TEXT,registration_available_at_utc TEXT,cancelled_at_utc TEXT,
                  cancellation_available_at_utc TEXT,delivered_at_utc TEXT,delivery_available_at_utc TEXT);
                CREATE TABLE parcel_events(event_id TEXT,revision INTEGER,parcel_id TEXT,event_type TEXT,
                  effective_at_utc TEXT,available_at_utc TEXT,PRIMARY KEY(event_id,revision));
                CREATE TABLE due_week_manifests(week_start_utc TEXT,service_tier TEXT,
                  expected_parcel_count INTEGER,registered_parcel_count INTEGER,available_at_utc TEXT);
                CREATE TABLE metric_definitions(metric TEXT,definition_version TEXT,definition TEXT);
                CREATE TABLE cached_export_revisions(week_start_utc TEXT,service_tier TEXT,revision INTEGER,
                  on_time_parcels INTEGER,eligible_parcels INTEGER,export_available_at_utc TEXT,
                  input_cutoff_utc TEXT,source_note TEXT,definition_version TEXT,
                  PRIMARY KEY(week_start_utc,service_tier,revision));
                CREATE VIEW cached_sla_exports AS SELECT e.* FROM cached_export_revisions e
                  WHERE revision=(SELECT max(r.revision) FROM cached_export_revisions r
                    WHERE r.week_start_utc=e.week_start_utc AND r.service_tier=e.service_tier);
                CREATE VIEW completed_only_sla AS
                  WITH scoped AS (SELECT *,strftime('%Y-%m-%dT00:00:00Z',due_at_utc,'-6 days','weekday 1') week_start_utc
                    FROM parcels CROSS JOIN source_snapshot
                    WHERE due_at_utc<current_end_utc AND cancelled_at_utc IS NULL
                      AND delivered_at_utc IS NOT NULL)
                  SELECT week_start_utc,service_tier,count(*) completed_parcels,
                    sum(delivered_at_utc<=due_at_utc) on_time_parcels
                  FROM scoped GROUP BY week_start_utc,service_tier
                  UNION ALL SELECT week_start_utc,'ALL',count(*),sum(delivered_at_utc<=due_at_utc)
                  FROM scoped GROUP BY week_start_utc;
            """)
            db.execute("INSERT INTO source_snapshot VALUES(?,?,?,?)", (
                _stamp(cutoff), _stamp(end - timedelta(days=14)), _stamp(end - timedelta(days=7)), _stamp(end)))
            db.executemany("INSERT INTO parcels VALUES(?,?,?,?,?,?,?,?,?)", [tuple(p.values()) for p in parcels.values()])
            db.executemany("INSERT INTO parcel_events VALUES(?,?,?,?,?,?)", [(
                e["event_id"], e["revision"], e["payload"]["parcel_id"], e["payload"]["event_type"],
                _stamp(e["effective_at"]), _stamp(e["available_at"])) for e in events])
            for m in manifests:
                observed = sum(p["service_tier"] == m["service_tier"]
                               and m["week_start_utc"] <= p["due_at_utc"] < _stamp(_time(m["week_start_utc"]) + timedelta(days=7))
                               for p in parcels.values())
                db.execute("INSERT INTO due_week_manifests VALUES(?,?,?,?,?)", (
                    m["week_start_utc"], m["service_tier"], m["expected_parcel_count"], observed, _stamp(m["available_at"])))
            db.executemany("INSERT INTO metric_definitions VALUES(?,?,?)", [
                ("due_week_delivery_attainment", "v1", DEFINITION),
                ("completed_only_delivery_attainment", "v1",
                 "On-time noncancelled completed parcels / all noncancelled completed parcels by UTC due week; excludes undelivered parcels.")])
            db.executemany("INSERT INTO cached_export_revisions VALUES(?,?,?,?,?,?,?,?,?)", exports)
    except BaseException:
        path.unlink()
        raise
    return path


def create_snapshot(path, index):
    if type(index) is not int or index not in range(3):
        raise ValueError("select a snapshot index from zero through two")
    return materialize_snapshot(make_history(), CUTOFFS[index], path)


def _decorate(database, result):
    clock = raw.query_readonly(database, "SELECT as_of_utc FROM source_snapshot")["rows"][0][0]
    result["source"] = {**result["source"], "identifier": SOURCE_ID, "as_of_utc": clock,
                        "kind": "synthetic_as_of_snapshot", "description": "Synthetic as-known courier parcel source.",
                        "fixture_note": "Visible source history only; retrieval time is not ingestion freshness."}
    for asset in result.get("assets", []) + ([result["asset"]] if "asset" in result else []):
        asset["identifier"] = f"{SOURCE_ID}:{asset['name']}"
        asset["description"] = "Source-owned table or view; inspect its schema and definitions."
    if "assets_read" in result:
        result["assets_read"] = [v.replace(raw.SOURCE_ID + ":", SOURCE_ID + ":", 1) for v in result["assets_read"]]
    return result


def query(database, sql, row_limit=200):
    return _decorate(database, raw.query_readonly(database, sql, row_limit))


def export(database, sql, resource, source_key, title):
    result = raw.export_query(database, sql, resource, source_key, title)
    metadata = _decorate(database, {"source": result["metadata"]["retrieval"],
                                    "assets_read": result["metadata"]["assets_read"]})
    result.update(adapter=ADAPTER, source_captured_at=metadata["source"]["as_of_utc"])
    result["metadata"].update(retrieval=metadata["source"], assets_read=metadata["assets_read"], capture_status="synthetic_as_of")
    for item in result["evidence"]:
        item["provenance"] = metadata["assets_read"]
    return result


def build_server(database):
    database = raw.validate_database_path(database)
    server = FastMCP("Pine Courier parcel history")

    @server.tool()
    def list_assets() -> dict:
        """Discover source-owned tables and views."""
        return _decorate(database, raw.list_assets(database))

    @server.tool()
    def inspect_asset(asset_name: str) -> dict:
        """Inspect actual schema and source view definitions."""
        return _decorate(database, raw.inspect_asset(database, asset_name))

    @server.tool(name="query_readonly")
    def select(sql: str, row_limit: int = 200) -> dict:
        """Read bounded source rows at this fixed historical cutoff."""
        return query(database, sql, row_limit)

    @server.tool(name="export_query")
    def exported(sql: str, resource: str, source_key: str, title: str) -> dict:
        """Export exact SQL rows as source evidence, not a policy judgment."""
        return export(database, sql, resource, source_key, title)

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="Existing fixed snapshot; no source generation on MCP startup")
    build_server(parser.parse_args().database).run(transport="stdio")

"""Read-only MCP over one immutable Harbor as-of snapshot, not private history."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from examples.harbor_help import company_mcp as raw

SOURCE_ID = "harbor_operational_snapshot"
ADAPTER = "harbor_history"
_DESCRIPTIONS = {
    "source_snapshot": "Synthetic business as-of clock; retrieval time is not this historical cutoff.",
    "tickets": "Ticket state reconstructed only from event revisions available at the declared cutoff.",
    "ticket_events": "Latest available event revisions; includes orphan response/resolution facts without hidden creation attributes.",
    "calendar_partitions": "Expected tier/region cohorts for fully ended UTC weeks, even when their source manifest is unavailable.",
    "expected_partitions": "Only the partition manifests already available at this cutoff; absent does not mean zero.",
}
_TICKET_FIELD_DEFINITIONS = {
    "definition_set": "harbor_ticket_fields",
    "version": "1.0",
    "fields": {
        "priority": {
            "meaning": (
                "Company work-population flag used by the source-owned "
                "weekly_ticket_clocks view; it is not a universal severity "
                "or urgency classification."
            ),
            "values": {
                "0": "Not flagged in this company's priority-1 work population.",
                "1": "Flagged in this company's priority-1 work population.",
            },
        },
        "status": {
            "meaning": "Reconstructed ticket resolution state at the source snapshot cutoff.",
            "values": {
                "open": "No resolution is present in the reconstructed state at the cutoff.",
                "resolved": "A resolution is present in the reconstructed state at the cutoff.",
            },
        },
        "first_response_at_utc": {
            "meaning": (
                "Source event timestamp for the first response visible in the "
                "reconstructed ticket state at the source snapshot cutoff."
            ),
            "null_semantics": (
                "No first-response event is visible in this snapshot; this "
                "does not establish that a response never occurred."
            ),
        },
    },
}


def _decorate(database, value):
    clock = raw.query_readonly(database, "SELECT as_of_utc FROM source_snapshot WHERE snapshot_id=1")
    if clock["truncated"] or len(clock["rows"]) != 1:
        raise ValueError("Snapshot must declare exactly one as-of clock")
    as_of = clock["rows"][0][0]
    parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Snapshot clock must be UTC")
    old = value["source"]
    value["source"] = {**old, "identifier": SOURCE_ID, "kind": "synthetic_as_of_snapshot",
        "description": "Synthetic support state reconstructed from revisions knowable at one business cutoff.",
        "as_of_utc": as_of, "fixture_note": "Immutable as-of source projection, not the final warehouse or current real business data. Future revisions are not in this file.",
        "retrieval_timestamp_semantics": "Time the tool read the file, not the synthetic business as-of clock."}
    for asset in value.get("assets", []) + ([value["asset"]] if "asset" in value else []):
        asset["identifier"] = f"{SOURCE_ID}:{asset['name']}"
        if asset["name"] in _DESCRIPTIONS:
            asset["description"] = _DESCRIPTIONS[asset["name"]]
    if "assets_read" in value:
        value["assets_read"] = [item.replace(raw.SOURCE_ID + ":", SOURCE_ID + ":", 1) for item in value["assets_read"]]
    return value


def list_assets(database):
    return _decorate(database, raw.list_assets(database))


def inspect_asset(database, asset_name):
    value = _decorate(database, raw.inspect_asset(database, asset_name))
    if value["asset"]["name"] == "tickets":
        value["asset"]["field_definitions"] = deepcopy(_TICKET_FIELD_DEFINITIONS)
    return value


def query_readonly(database, sql, row_limit=raw.DEFAULT_ROW_LIMIT):
    return _decorate(database, raw.query_readonly(database, sql, row_limit))


def export_query(database, sql, resource, source_key, title):
    value = raw.export_query(database, sql, resource, source_key, title)
    value["adapter"] = ADAPTER
    metadata = _decorate(database, {"source": value["metadata"]["retrieval"], "assets_read": value["metadata"]["assets_read"]})
    value["source_captured_at"] = metadata["source"]["as_of_utc"]
    value["metadata"].update(retrieval=metadata["source"], assets_read=metadata["assets_read"],
        capture_status="synthetic_as_of", capture_reason="Synthetic knowable-state cutoff, not current real-company freshness.")
    for item in value["evidence"]:
        item["provenance"] = metadata["assets_read"]
    return value


def build_server(database):
    database = raw.validate_database_path(database)
    list_assets(database)  # Reject a non-snapshot file before exposing tools.
    server = FastMCP("Harbor operational history snapshot")

    @server.tool(name="list_assets")
    def catalog() -> dict[str, Any]:
        """Discover raw records and source-owned views available at this snapshot's clock."""
        return list_assets(database)

    @server.tool(name="inspect_asset")
    def inspect(asset_name: str) -> dict[str, Any]:
        """Inspect actual schema and source definitions, without future versions."""
        return inspect_asset(database, asset_name)

    @server.tool(name="query_readonly")
    def query(sql: str, row_limit: int = raw.DEFAULT_ROW_LIMIT) -> dict[str, Any]:
        """Run bounded read-only SQL against this one as-of state."""
        return query_readonly(database, sql, row_limit)

    @server.tool(name="export_query")
    def export(sql: str, resource: str, source_key: str, title: str) -> dict[str, Any]:
        """Return bounded source SQL as evidence, with the synthetic as-of capture clock; no policy decision."""
        return export_query(database, sql, resource, source_key, title)

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="One immutable materialized snapshot; never the private history")
    args = parser.parse_args()
    build_server(args.database).run(transport="stdio")


if __name__ == "__main__":
    main()

"""Synthetic company MCP: execute two read-only aggregations, export their meaning.

This is an example source integration, not a component of the SignalWeave binary.
Its SQLite file is prepared by evaluations/local_investigation_trial.py.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

server = FastMCP("Example company analytical exports")
DATABASE = Path(sys.argv[1]).resolve()


@server.tool()
def read_comparison() -> dict[str, Any]:
    """Read the operator-approved activity comparison. No SQL or locator arguments."""
    with sqlite3.connect(DATABASE.as_uri() + "?mode=ro", uri=True) as connection:
        metadata = json.loads(connection.execute("SELECT payload FROM definition").fetchone()[0])
        totals = connection.execute(
            "SELECT period, SUM(value), SUM(numerator), SUM(denominator) "
            "FROM measurements GROUP BY period ORDER BY period"
        ).fetchall()
        segments = connection.execute(
            "SELECT segment, period, SUM(value), SUM(numerator), SUM(denominator) "
            "FROM measurements GROUP BY segment, period ORDER BY segment, period"
        ).fetchall()
    fields = ("value",) if metadata["kind"] == "additive" else ("numerator", "denominator")

    def values(row):
        raw = dict(zip(("value", "numerator", "denominator"), row, strict=True))
        return {key: raw[key] for key in fields}

    for period, *row in totals:
        metadata[period + "_total"] = values(row)
    groups = {}
    for segment, period, *row in segments:
        groups.setdefault(segment, {"segment": segment})[period] = values(row)
    metadata["segments"] = list(groups.values())
    return {"adapter": "company_metrics", "resource": "activity", "source_key": "activity",
            "title": "Approved activity comparison", "contract": {"tenant_id": "local"},
            "metadata": {"telemetry": {"query_calls": 3}},
            "source_captured_at": datetime.now(timezone.utc).isoformat(),
            "analytical_comparisons": [metadata]}


if __name__ == "__main__":
    server.run(transport="stdio")

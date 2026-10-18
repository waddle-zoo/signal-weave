"""Read-only workflow catalog over one immutable Harbor as-of snapshot."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from evaluations import harbor_history_mcp
from evaluations.harbor_workflow_sources import build_workflow_manifest


def list_saved_queries(database: str) -> dict[str, Any]:
    """Return the four fixed workflow queries and this snapshot's identity/clock."""
    source = harbor_history_mcp.list_assets(database)["source"]
    manifest = build_workflow_manifest(database, sys.executable)
    queries = []
    for item in manifest["connections"][0]["resources"]:
        descriptor = item["descriptor"]
        queries.append({
            "resource": descriptor["resource"],
            "title": descriptor["title"],
            "sql": item["arguments"]["sql"],
            "sha256": descriptor["metadata"]["sql_sha256"],
            "scope": descriptor["contract"]["scope"],
        })
    return {
        "source": source,
        "queries": queries,
    }


def build_server(database: str):
    """Keep the raw history tools and add the shared prepared-query catalog."""
    server = harbor_history_mcp.build_server(database)

    @server.tool(name="list_saved_queries")
    def saved_queries() -> dict[str, Any]:
        """List the four fixed saved queries with their source snapshot clock."""
        return list_saved_queries(database)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="One immutable materialized snapshot; never the private history")
    args = parser.parse_args()
    build_server(args.database).run(transport="stdio")


if __name__ == "__main__":
    main()

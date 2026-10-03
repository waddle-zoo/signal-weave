"""Read-only MCP fixture server for the installed first-report trial.

The input is a public, oracle-free snapshot JSON file.  The server exposes one
fixed tool and never reads a database, computes labels, or accepts selectors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

server = FastMCP("SignalWeave reviewed fixture snapshot")
SNAPSHOT: dict[str, Any] = {}


@server.tool()
def read_snapshot(resource: str) -> dict[str, Any]:
    """Return one deployment-allowlisted public snapshot by fixed resource key."""
    if resource not in SNAPSHOT.get("allowlisted_resources", []):
        raise ValueError("resource is not allowlisted")
    return SNAPSHOT["resources"][resource]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: fixture_snapshot_mcp.py SNAPSHOT.json")
    SNAPSHOT = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    server.run(transport="stdio")

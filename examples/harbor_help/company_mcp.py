"""Read-only stdio MCP for the Harbor Help raw SQLite fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import time
from collections.abc import Sequence
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

SOURCE_ID = "harbor_help_raw_sqlite"
DEFAULT_ROW_LIMIT = 200
MAX_ROW_LIMIT = 1_000
MAX_SQL_BYTES = 16 * 1024
MAX_QUERY_STEPS = 1_000_000
MAX_QUERY_SECONDS = 2.0
PROGRESS_INTERVAL = 1_000
MAX_SQLITE_VALUE_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_RESULT_COLUMNS = 128

_SOURCE_DESCRIPTION = "Synthetic Harbor Help support data in a local SQLite fixture."
_FIXTURE_NOTE = (
    "The fixture represents a fixed final retrospective state with source-supplied event and "
    "ingestion timestamps. This tool reports when the local file was queried, not source "
    "freshness; it does not reconstruct earlier database states."
)
_ASSET_DESCRIPTIONS = {
    "tickets": "Raw ticket records, including status, support tier, region, priority, and timestamps.",
    "support_tier_sla": "Source-owned first-response and resolution clock definitions by support tier.",
    "source_snapshot": "The fixture's fixed final retrospective as-of marker; it is not a time-travel interface.",
    "source_ingestion_ledger": "Expected and received interval counts and their recorded ingestion status.",
    "weekly_resolution_sla": (
        "The resolution-SLA denominator and misses use eligible resolved priority tickets, "
        "grouped by ticket creation week, tier, and region; observed_ticket_count includes all "
        "tickets in that cohort. This is not an all-customer or resolve-week view."
    ),
    "weekly_first_response_sla": (
        "First-response clock counts grouped by ticket creation week, tier, and region; the "
        "population includes open tickets with a response timestamp."
    ),
    "weekly_source_coverage": "Expected, observed, and missing ticket counts by week, tier, and region.",
    "weekly_open_backlog": (
        "Open-ticket clock counts at the fixture's fixed as-of marker, grouped by ticket "
        "creation week, tier, and region."
    ),
}


class QueryBudgetExceeded(RuntimeError):
    """Raised when a query exceeds its SQLite instruction or elapsed-time budget."""


def validate_database_path(database_path: str | os.PathLike[str]) -> Path:
    """Require an existing, regular, non-symlink database file."""
    path = Path(database_path).expanduser()
    try:
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"SQLite database does not exist: {path}") from exc
    if stat.S_ISLNK(file_stat.st_mode):
        raise ValueError("SQLite database path must not be a symlink")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("SQLite database path must be an existing regular file")
    return path.resolve(strict=True)


def _retrieval_metadata() -> dict[str, str]:
    return {
        "identifier": SOURCE_ID,
        "kind": "local_sqlite_fixture",
        "description": _SOURCE_DESCRIPTION,
        "fixture_note": _FIXTURE_NOTE,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "retrieval_timestamp_semantics": (
            "Time this tool queried the local file; not source freshness or an ingestion timestamp."
        ),
    }


def _authorize_readonly(
    source_assets: set[str],
    accessed_assets: set[str] | None = None,
):
    allowed_actions = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    recursive_action = getattr(sqlite3, "SQLITE_RECURSIVE", None)
    if recursive_action is not None:
        allowed_actions.add(recursive_action)

    def authorizer(
        action: int,
        arg1: str | None,
        arg2: str | None,
        _database_name: str | None,
        _trigger_name: str | None,
    ) -> int:
        if action not in allowed_actions:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            function_name = (arg2 or arg1 or "").casefold()
            if function_name in {
                "load_extension",
                "readfile",
                "writefile",
            } or function_name.startswith("pragma_"):
                return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and (arg1 or "").casefold().startswith("pragma_"):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and arg1 in source_assets and accessed_assets is not None:
            accessed_assets.add(arg1)
        return sqlite3.SQLITE_OK

    return authorizer


def _open_readonly(database_path: str | os.PathLike[str]) -> sqlite3.Connection:
    path = validate_database_path(database_path)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        # Set these before installing the authorizer, which denies every PRAGMA.
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_SQLITE_VALUE_BYTES)
        connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, MAX_RESULT_COLUMNS)
        connection.set_authorizer(_authorize_readonly(set()))
    except BaseException:
        connection.close()
        raise
    return connection


def _asset_rows(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return connection.execute(
        "SELECT type, name, sql FROM sqlite_schema "
        "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name"
    ).fetchall()


def list_assets(database_path: str | os.PathLike[str]) -> dict[str, Any]:
    """List user tables and views in the raw source database."""
    with closing(_open_readonly(database_path)) as connection:
        assets = [
            {
                "identifier": f"{SOURCE_ID}:{name}",
                "name": name,
                "type": kind,
                "description": _ASSET_DESCRIPTIONS.get(
                    name,
                    f"Source {kind} named {name}; inspect its SQL definition for its contents.",
                ),
            }
            for kind, name, _schema in _asset_rows(connection)
        ]
    return {"source": _retrieval_metadata(), "assets": assets}


def inspect_asset(database_path: str | os.PathLike[str], asset_name: str) -> dict[str, Any]:
    """Return one asset's columns, exact SQLite schema, and source description."""
    if not isinstance(asset_name, str) or not asset_name:
        raise ValueError("asset_name must be a non-empty table or view name")
    with closing(_open_readonly(database_path)) as connection:
        schema_row = connection.execute(
            "SELECT type, name, sql FROM sqlite_schema "
            "WHERE name = ? AND type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'",
            (asset_name,),
        ).fetchone()
        if schema_row is None:
            raise ValueError(f"Unknown source table or view: {asset_name}")
        kind, name, exact_sql = schema_row
        quoted_name = '"' + name.replace('"', '""') + '"'
        columns = [
            item[0]
            for item in connection.execute(f"SELECT * FROM {quoted_name} LIMIT 0").description or []
        ]
    return {
        "source": _retrieval_metadata(),
        "asset": {
            "identifier": f"{SOURCE_ID}:{name}",
            "name": name,
            "type": kind,
            "description": _ASSET_DESCRIPTIONS.get(
                name, f"Source {kind} named {name}; inspect its SQL definition for its contents."
            ),
            "columns": columns,
            "sql_schema": exact_sql,
        },
    }


def _first_sql_keyword(sql: str) -> str:
    index = 0
    length = len(sql)
    while index < length:
        if sql[index].isspace():
            index += 1
        elif sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                raise ValueError("SQL contains an unterminated comment")
            index = end + 2
        else:
            break
    end = index
    while end < length and (sql[end].isalnum() or sql[end] == "_"):
        end += 1
    return sql[index:end].upper()


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"blob_hex": value.hex()}
    return value


def query_readonly(
    database_path: str | os.PathLike[str],
    sql: str,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> dict[str, Any]:
    """Run a bounded raw-source SELECT and report any partial result explicitly."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty SELECT statement")
    if len(sql.encode("utf-8")) > MAX_SQL_BYTES:
        raise ValueError(f"SQL exceeds the {MAX_SQL_BYTES}-byte limit")
    if _first_sql_keyword(sql) not in {"SELECT", "WITH"}:
        raise ValueError("Only a read-only SELECT statement is allowed")
    if isinstance(row_limit, bool) or not isinstance(row_limit, int):
        raise ValueError("row_limit must be an integer")
    if not 1 <= row_limit <= MAX_ROW_LIMIT:
        raise ValueError(f"row_limit must be between 1 and {MAX_ROW_LIMIT}")

    with closing(_open_readonly(database_path)) as connection:
        source_assets = {name for _kind, name, _schema in _asset_rows(connection)}
        accessed_assets: set[str] = set()
        connection.set_authorizer(_authorize_readonly(source_assets, accessed_assets))
        progress = {"steps": 0, "limit": ""}
        started = time.monotonic()

        def check_budget() -> int:
            progress["steps"] += PROGRESS_INTERVAL
            if progress["steps"] > MAX_QUERY_STEPS:
                progress["limit"] = "instruction budget"
                return 1
            if time.monotonic() - started > MAX_QUERY_SECONDS:
                progress["limit"] = "elapsed-time budget"
                return 1
            return 0

        connection.set_progress_handler(check_budget, PROGRESS_INTERVAL)
        try:
            cursor = connection.execute(sql)
            columns = [item[0] for item in cursor.description or []]
            if not columns:
                raise ValueError("The SQL statement did not return columns")
            if not accessed_assets:
                raise ValueError("The SELECT must read at least one table or view in this source")

            rows: list[list[Any]] = []
            result_bytes = 0
            truncated = False
            truncation_reason: str | None = None
            for raw_row in cursor:
                if len(rows) >= row_limit:
                    truncated = True
                    truncation_reason = "row_limit"
                    break
                row = [_json_value(value) for value in raw_row]
                row_bytes = len(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                )
                if result_bytes + row_bytes > MAX_RESPONSE_BYTES:
                    truncated = True
                    truncation_reason = "response_byte_limit"
                    break
                rows.append(row)
                result_bytes += row_bytes
        except sqlite3.OperationalError as exc:
            if progress["limit"]:
                raise QueryBudgetExceeded(
                    f"Query exceeded its {progress['limit']} ({MAX_QUERY_STEPS} SQLite steps, "
                    f"{MAX_QUERY_SECONDS:g} seconds maximum)"
                ) from exc
            raise
        finally:
            connection.set_progress_handler(None, 0)
        elapsed = time.monotonic() - started

    return {
        "source": _retrieval_metadata(),
        "query": sql,
        "columns": columns,
        "rows": rows,
        "returned_row_count": len(rows),
        "truncated": truncated,
        "truncation_reason": truncation_reason,
        "row_limit": row_limit,
        "assets_read": [f"{SOURCE_ID}:{name}" for name in sorted(accessed_assets)],
        "query_elapsed_seconds": elapsed,
    }


def export_query(database_path, sql: str, resource: str, source_key: str, title: str) -> dict[str, Any]:
    """Wrap a bounded SQL result as source evidence, without policy or interpretation.

    A SignalWeave manifest fixes SQL and identity arguments after operator
    review. This company tool itself is not an authorization or truth boundary.
    """
    if any(not isinstance(value, str) or not value.strip() or len(value) > 500
           for value in (resource, source_key, title)):
        raise ValueError("Use nonempty bounded export identifiers and title")
    result = query_readonly(database_path, sql, MAX_ROW_LIMIT)
    if result["truncated"]:
        raise ValueError("SQL export is incomplete; aggregate or narrow the saved query")
    columns = result["columns"]
    if len(set(columns)) != len(columns):
        raise ValueError("Export columns need unique aliases to preserve every value")
    return {"source_key": source_key, "adapter": "company_sql", "resource": resource, "title": title,
            "source_captured_at": None, "contract": {"tenant_id": "local", "authorized": True},
            "metadata": {"saved_query_definition": {"sql": sql, "sha256": hashlib.sha256(sql.encode()).hexdigest()},
                "retrieval": result["source"], "assets_read": result["assets_read"],
                "capture_status": "unknown", "capture_reason": "Retrieval time does not attest to source capture or freshness"},
            "evidence": [{"source_key": source_key, "subject_id": f"row:{index}",
                "statement": "Source SQL result row; not an alert decision or causal explanation.",
                "values": dict(zip(columns, row, strict=True)), "origin": "source",
                "provenance": result["assets_read"]}
                for index, row in enumerate(result["rows"])]}


def build_server(
    database_path: str | os.PathLike[str], *, exports_dir: Path | None = None,
) -> FastMCP:
    """Build the discoverable stdio company-source MCP server."""
    database = validate_database_path(database_path)
    server = FastMCP("Harbor Help raw SQLite company source")

    @server.tool(name="list_assets")
    def list_assets_tool() -> dict[str, Any]:
        """List source tables and views with their names, types, and descriptions."""
        return list_assets(database)

    @server.tool(name="inspect_asset")
    def inspect_asset_tool(asset_name: str) -> dict[str, Any]:
        """Inspect one table or view's columns, exact SQL, and source description."""
        return inspect_asset(database, asset_name)

    @server.tool(name="query_readonly")
    def query_readonly_tool(sql: str, row_limit: int = DEFAULT_ROW_LIMIT) -> dict[str, Any]:
        """Run one bounded read-only SELECT against raw source tables or views."""
        return query_readonly(database, sql, row_limit)

    @server.tool(name="export_query")
    def export_query_tool(sql: str, resource: str, source_key: str, title: str) -> dict[str, Any]:
        """Wrap bounded SQL rows as source evidence, not files or a policy decision. The operator fixes these arguments in a SignalWeave source manifest."""
        return export_query(database, sql, resource, source_key, title)

    if exports_dir is not None:
        from .query_artifacts import write_query_artifacts

        artifact_root = Path(exports_dir).expanduser().absolute()

        @server.tool(name="export_query_files", annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, openWorldHint=False,
        ))
        def export_query_files_tool(sql: str, row_limit: int = MAX_ROW_LIMIT) -> dict[str, Any]:
            """Save original query rows as JSON, CSV and provenance in the configured local folder. Use the returned files for analysis instead of retyping rows. No message is sent; local paths do not establish recipient access."""
            result = query_readonly(database, sql, row_limit)
            return write_query_artifacts(result, artifact_root)

    return server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="existing regular SQLite fixture file")
    parser.add_argument(
        "--exports-dir", type=Path,
        help="Enable local query-file exports in this private directory; absent by default",
    )
    arguments = parser.parse_args(argv)
    try:
        server = build_server(arguments.database, exports_dir=arguments.exports_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

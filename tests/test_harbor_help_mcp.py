from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from examples.harbor_help import company_mcp
from examples.harbor_help.company_mcp import (
    MAX_ROW_LIMIT,
    MAX_SQL_BYTES,
    QueryBudgetExceeded,
    inspect_asset,
    list_assets,
    query_readonly,
)
from examples.harbor_help.seed import generate_database

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return generate_database(tmp_path / "harbor-help.sqlite3", seed=20261016)


def _payload(result):
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def test_discovery_inspection_and_raw_aggregate_are_source_backed(database: Path):
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE VIEW operator_added_asset AS SELECT COUNT(*) AS ticket_count FROM tickets"
        )
        priorities = [row[0] for row in connection.execute("SELECT priority FROM tickets")]

    catalog = list_assets(database)
    by_name = {asset["name"]: asset for asset in catalog["assets"]}
    assert {asset["type"] for asset in catalog["assets"]} == {"table", "view"}
    assert {"source_snapshot", "weekly_open_backlog", "operator_added_asset"} <= by_name.keys()
    assert by_name["operator_added_asset"]["identifier"].endswith(":operator_added_asset")

    dynamic_view = inspect_asset(database, "operator_added_asset")["asset"]
    assert dynamic_view["columns"] == ["ticket_count"]
    assert dynamic_view["sql_schema"] == (
        "CREATE VIEW operator_added_asset AS SELECT COUNT(*) AS ticket_count FROM tickets"
    )

    resolution = inspect_asset(database, "weekly_resolution_sla")["asset"]
    assert "ticket creation week" in resolution["description"]
    assert "resolve-week" in resolution["description"]
    assert "CREATE VIEW weekly_resolution_sla" in resolution["sql_schema"]

    result = query_readonly(
        database,
        "SELECT COUNT(*) AS ticket_count, SUM(priority) AS priority_total FROM tickets",
    )
    assert result["columns"] == ["ticket_count", "priority_total"]
    assert result["rows"] == [[len(priorities), sum(priorities)]]
    assert result["assets_read"] == ["harbor_help_raw_sqlite:tickets"]
    assert result["truncated"] is False
    assert result["truncation_reason"] is None

    retrieved = datetime.fromisoformat(result["source"]["retrieved_at_utc"])
    assert retrieved.tzinfo is not None
    assert "not source freshness" in result["source"]["fixture_note"]
    assert "earlier database states" in result["source"]["fixture_note"]
    assert result["source"]["retrieval_timestamp_semantics"].startswith("Time this tool queried")
    assert "source_captured_at" not in result


def test_only_readonly_source_selects_are_allowed(database: Path):
    for sql in (
        "DELETE FROM tickets",
        "ATTACH DATABASE '/tmp/other.sqlite' AS other",
        "PRAGMA table_info(tickets)",
    ):
        with pytest.raises(ValueError, match="Only a read-only SELECT"):
            query_readonly(database, sql)

    # WITH passes the initial SELECT-shape check; SQLite's authorizer must still
    # reject a data-changing statement hidden after its CTE.
    with pytest.raises(sqlite3.DatabaseError):
        query_readonly(
            database,
            "WITH chosen AS (SELECT ticket_id FROM tickets LIMIT 1) "
            "DELETE FROM tickets WHERE ticket_id IN (SELECT ticket_id FROM chosen)",
        )

    with pytest.raises(sqlite3.DatabaseError):
        query_readonly(database, "SELECT load_extension('not-installed') FROM tickets LIMIT 1")
    with pytest.raises(sqlite3.DatabaseError):
        query_readonly(database, "SELECT name FROM pragma_table_info('tickets')")
    with pytest.raises(ValueError, match="must read at least one table or view"):
        query_readonly(database, "SELECT 1")

    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] > 0


def test_missing_nonregular_and_symlink_paths_do_not_open_or_create_databases(
    tmp_path: Path, database: Path
):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        list_assets(missing)
    assert not missing.exists()

    with pytest.raises(ValueError, match="regular file"):
        list_assets(tmp_path)

    symlink = tmp_path / "linked.sqlite3"
    symlink.symlink_to(database)
    with pytest.raises(ValueError, match="symlink"):
        list_assets(symlink)
    assert symlink.is_symlink()


def test_each_tool_closes_its_sqlite_connection(database: Path, monkeypatch: pytest.MonkeyPatch):
    real_connect = sqlite3.connect
    connections = []

    class TrackingConnection(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.close_called = False

        def close(self):
            self.close_called = True
            return super().close()

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, factory=TrackingConnection, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(company_mcp.sqlite3, "connect", tracking_connect)
    operations = (
        lambda: list_assets(database),
        lambda: inspect_asset(database, "tickets"),
        lambda: query_readonly(database, "SELECT COUNT(*) FROM tickets"),
    )
    for operation in operations:
        operation()
        assert connections[-1].close_called is True


def test_result_limits_are_explicit_and_sql_size_is_bounded(database: Path):
    result = query_readonly(
        database,
        "SELECT ticket_id FROM tickets ORDER BY ticket_id",
        row_limit=3,
    )
    assert result["returned_row_count"] == 3
    assert len(result["rows"]) == 3
    assert result["truncated"] is True
    assert result["truncation_reason"] == "row_limit"

    with pytest.raises(ValueError, match="byte limit"):
        query_readonly(database, "SELECT " + (" " * MAX_SQL_BYTES) + "ticket_id FROM tickets")
    with pytest.raises(ValueError, match=str(MAX_ROW_LIMIT)):
        query_readonly(database, "SELECT ticket_id FROM tickets", row_limit=MAX_ROW_LIMIT + 1)


def test_expensive_recursive_query_stops_at_instruction_budget(
    database: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("examples.harbor_help.company_mcp.MAX_QUERY_STEPS", 4_000)
    sql = (
        "WITH RECURSIVE numbers(value) AS ("
        "SELECT COUNT(*) FROM tickets UNION ALL "
        "SELECT value + 1 FROM numbers WHERE value < 10000000) "
        "SELECT MAX(value) FROM numbers"
    )
    with pytest.raises(QueryBudgetExceeded, match="instruction budget"):
        query_readonly(database, sql)


@pytest.mark.asyncio
async def test_actual_stdio_mcp_discovers_and_runs_the_same_raw_source_tools(database: Path):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "examples.harbor_help.company_mcp", str(database)],
        env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT)},
        cwd=str(REPOSITORY_ROOT),
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_log:
        with anyio.fail_after(30):
            async with stdio_client(parameters, errlog=error_log) as streams:
                async with ClientSession(*streams) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "Harbor Help raw SQLite company source"
                    discovered = await session.list_tools()
                    names = {tool.name for tool in discovered.tools}
                    assert names == {"list_assets", "inspect_asset", "query_readonly", "export_query"}

                    catalog = _payload(await session.call_tool("list_assets", {}))
                    asset_names = {asset["name"] for asset in catalog["assets"]}
                    assert "source_snapshot" in asset_names
                    assert "weekly_open_backlog" in asset_names

                    inspected = _payload(
                        await session.call_tool(
                            "inspect_asset", {"asset_name": "weekly_open_backlog"}
                        )
                    )
                    assert inspected["asset"]["type"] == "view"
                    assert "as_of_utc" in inspected["asset"]["columns"]

                    query = (
                        "SELECT support_tier, COUNT(*) AS ticket_count, "
                        "SUM(priority) AS priority_total FROM tickets "
                        "GROUP BY support_tier ORDER BY support_tier"
                    )
                    result = _payload(await session.call_tool("query_readonly", {"sql": query}))
                    assert result["truncated"] is False
                    assert result["columns"] == ["support_tier", "ticket_count", "priority_total"]

    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        direct = connection.execute(
            "SELECT support_tier, COUNT(*), SUM(priority) FROM tickets "
            "GROUP BY support_tier ORDER BY support_tier"
        ).fetchall()
    assert result["rows"] == [list(row) for row in direct]


def test_export_preserves_arbitrary_source_columns_without_policy_or_freshness(database):
    from examples.harbor_help.company_mcp import export_query
    from signalweave.models import ResourceSnapshot

    sql = "SELECT support_tier AS niche_segment, COUNT(*) AS observed FROM tickets GROUP BY support_tier"
    value = export_query(database, sql, "metric:custom", "custom", "Source counts")
    parsed = ResourceSnapshot.model_validate(value)
    direct = query_readonly(database, sql)
    assert [item.values for item in parsed.evidence] == [dict(zip(direct["columns"], row, strict=True)) for row in direct["rows"]]
    assert value["source_captured_at"] is None and value["metadata"]["capture_status"] == "unknown"
    assert value["metadata"]["saved_query_definition"]["sql"] == sql
    assert not parsed.analytical_comparisons and not parsed.observations
    assert "outcome" not in value
    with pytest.raises(ValueError, match="incomplete"):
        export_query(database, "SELECT ticket_id FROM tickets", "metric:wide", "wide", "Too wide")
    with pytest.raises(ValueError, match="unique aliases"):
        export_query(database, "SELECT priority, priority FROM tickets LIMIT 1", "metric:duplicate", "duplicate", "Ambiguous")

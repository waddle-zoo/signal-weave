"""The shared saved-query catalog is available over the actual stdio MCP."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import timezone
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.harbor_history import make_history, materialize_snapshot, weekly_cutoffs
from evaluations.harbor_history_mcp import SOURCE_ID, inspect_asset, list_assets
from evaluations.harbor_history_preflight import build_manifest
from evaluations.harbor_workflow_sources import build_workflow_manifest


def _assert_ticket_field_definitions(inspection):
    asset = inspection["asset"]
    definitions = asset["field_definitions"]
    assert asset["name"] == "tickets"
    assert definitions["definition_set"] == "harbor_ticket_fields"
    assert definitions["version"] == "1.0"
    fields = definitions["fields"]
    assert set(fields) == {"priority", "status", "first_response_at_utc"}
    assert fields["priority"]["values"] == {
        "0": "Not flagged in this company's priority-1 work population.",
        "1": "Flagged in this company's priority-1 work population.",
    }
    assert "weekly_ticket_clocks" in fields["priority"]["meaning"]
    assert "not a universal severity" in fields["priority"]["meaning"]
    assert fields["status"]["values"] == {
        "open": "No resolution is present in the reconstructed state at the cutoff.",
        "resolved": "A resolution is present in the reconstructed state at the cutoff.",
    }
    assert "source snapshot cutoff" in fields["status"]["meaning"]
    assert "visible" in fields["first_response_at_utc"]["meaning"]
    assert "does not establish that a response never occurred" in fields[
        "first_response_at_utc"
    ]["null_semantics"]

    encoded = json.dumps(definitions).lower()
    assert not any(term in encoded for term in (
        "ticket_id", "expected_outcome", "threshold", "select ", "count(",
    ))


@pytest.mark.asyncio
async def test_workflow_stdio_catalog_and_raw_tools_share_the_snapshot(tmp_path):
    history = make_history()
    cutoff = weekly_cutoffs(history)[1]
    database = materialize_snapshot(history, cutoff, tmp_path / "workflow.sqlite3")
    as_of = cutoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _assert_ticket_field_definitions(inspect_asset(database, "tickets"))
    assert "field_definitions" not in json.dumps(list_assets(database))
    manifest = build_workflow_manifest(database, Path(sys.executable))
    connection, = manifest["connections"]
    baseline = build_manifest(database, Path(sys.executable))
    baseline_resources = baseline["connections"][0]["resources"]

    assert connection["transport"]["command"] == [
        sys.executable, "-m", "evaluations.harbor_workflow_mcp", str(database),
    ]
    assert connection["resources"][:-1] == baseline_resources
    assert len(connection["resources"]) == 4

    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "evaluations.harbor_workflow_mcp", str(database)],
        env=os.environ.copy(),
    )
    async with stdio_client(server_parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert {tool.name for tool in listed.tools} == {
                "list_assets", "inspect_asset", "query_readonly", "export_query", "list_saved_queries",
            }

            catalog_result = await session.call_tool("list_saved_queries", {})
            assert catalog_result.isError is False
            catalog = catalog_result.structuredContent
            assert isinstance(catalog, dict)
            assert set(catalog) == {"source", "queries"}
            expected_source = list_assets(database)["source"]
            assert {
                key: value for key, value in catalog["source"].items() if key != "retrieved_at_utc"
            } == {
                key: value for key, value in expected_source.items() if key != "retrieved_at_utc"
            }
            assert catalog["source"]["retrieved_at_utc"]
            assert catalog["source"]["identifier"] == SOURCE_ID
            assert catalog["source"]["as_of_utc"] == as_of
            expected_queries = [
                {
                    "resource": item["descriptor"]["resource"],
                    "title": item["descriptor"]["title"],
                    "sql": item["arguments"]["sql"],
                    "sha256": item["descriptor"]["metadata"]["sql_sha256"],
                    "scope": item["descriptor"]["contract"]["scope"],
                }
                for item in connection["resources"]
            ]
            assert catalog["queries"] == expected_queries
            assert len(catalog["queries"]) == 4
            for query in catalog["queries"]:
                assert set(query) == {"resource", "title", "sql", "sha256", "scope"}
                assert query["sha256"] == hashlib.sha256(query["sql"].encode()).hexdigest()

            encoded_catalog = json.dumps(catalog).lower()
            assert str(database).lower() not in encoded_catalog
            assert not any(term in encoded_catalog for term in (
                "transport", "environment", "credentials", "owner_brief", "gold_label",
                "decision_guidance", "expected_outcome", "future_data",
            ))

            inspection_result = await session.call_tool("inspect_asset", {
                "asset_name": "tickets",
            })
            assert inspection_result.isError is False
            _assert_ticket_field_definitions(inspection_result.structuredContent)

            raw_result = await session.call_tool("query_readonly", {
                "sql": "SELECT as_of_utc FROM source_snapshot WHERE snapshot_id=1",
                "row_limit": 10,
            })
            assert raw_result.isError is False
            raw = raw_result.structuredContent
            assert isinstance(raw, dict)
            assert raw["source"]["identifier"] == SOURCE_ID
            assert raw["source"]["as_of_utc"] == as_of
            assert raw["columns"] == ["as_of_utc"]
            assert raw["rows"] == [[as_of]]
            assert raw["truncated"] is False


@pytest.mark.asyncio
async def test_source_stdio_inspection_exposes_versioned_ticket_definitions(tmp_path):
    history = make_history()
    cutoff = weekly_cutoffs(history)[1]
    database = materialize_snapshot(history, cutoff, tmp_path / "source.sqlite3")
    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "evaluations.harbor_history_mcp", str(database)],
        env=os.environ.copy(),
    )

    async with stdio_client(server_parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            catalog = await session.call_tool("list_assets", {})
            assert catalog.isError is False
            assert "harbor_ticket_fields" not in json.dumps(catalog.structuredContent)

            inspected = await session.call_tool("inspect_asset", {
                "asset_name": "tickets",
            })
            assert inspected.isError is False
            _assert_ticket_field_definitions(inspected.structuredContent)

"""Source/time validity checks; these are not onboarding or business outcomes."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.harbor_history import make_history, materialize_snapshot, weekly_cutoffs
from evaluations.harbor_history_mcp import ADAPTER, export_query, list_assets, query_readonly


def rows(path, table):
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]


def ordered(values, *keys):
    return sorted(values, key=lambda row: tuple(row[key] for key in keys))


@pytest.mark.parametrize("seed", [17, 42, 20261018])
def test_every_generated_snapshot_matches_independent_raw_history_reference(tmp_path, seed):
    # Imported only by the test caller: neither source generator nor SQL views
    # may call the independent raw-record implementation to manufacture agreement.
    from evaluations.harbor_history_reference import summarize_history

    history = make_history(seed=seed)
    for index, cutoff in enumerate(weekly_cutoffs(history)):
        snapshot = materialize_snapshot(history, cutoff, tmp_path / f"{index}.sqlite3")
        reference = summarize_history(history, cutoff)
        assert rows(snapshot, "source_snapshot") == [{"snapshot_id": 1, "as_of_utc": reference["as_of_utc"]}]
        assert ordered(rows(snapshot, "tickets"), "ticket_id") == ordered(reference["tickets"], "ticket_id")
        for key, view in (("resolution", "weekly_resolution_sla"), ("first_response", "weekly_first_response_sla"),
                          ("backlog", "weekly_open_backlog"), ("coverage", "weekly_source_coverage")):
            actual = ordered(rows(snapshot, view), "week_start_utc", "support_tier", "region")
            expected = ordered(reference[key], "week_start_utc", "support_tier", "region")
            assert len(actual) == len(expected)
            for result, target in zip(actual, expected, strict=True):
                assert result.keys() == target.keys()
                for name, value in target.items():
                    assert result[name] == (pytest.approx(value, abs=1e-12) if isinstance(value, float) else value)
        orphan = query_readonly(snapshot, "SELECT e.event_id FROM ticket_events e LEFT JOIN tickets t USING(ticket_id) "
            "WHERE e.kind<>'created' AND t.ticket_id IS NULL ORDER BY e.event_id")
        assert [row[0] for row in orphan["rows"]] == reference["orphan_event_ids"]


def test_future_history_is_not_in_the_file_or_its_metadata(tmp_path):
    history = make_history()
    cutoff = weekly_cutoffs(history)[0]
    past_only = {**history, "events": [row for row in history["events"] if row["available_at"] <= cutoff]}
    full = materialize_snapshot(history, cutoff, tmp_path / "full.sqlite3")
    earlier = materialize_snapshot(past_only, cutoff, tmp_path / "earlier.sqlite3")
    assert full.read_bytes() == earlier.read_bytes()
    stamp = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert query_readonly(full, f"SELECT COUNT(*) FROM ticket_events WHERE available_at_utc>'{stamp}' OR effective_at_utc>'{stamp}'")["rows"] == [[0]]
    catalog = list_assets(full)
    names = {item["name"] for item in catalog["assets"]}
    assert not names & {"private_history", "events", "expected_outcomes", "owner_policy"}
    with pytest.raises(sqlite3.DatabaseError):
        query_readonly(full, "SELECT * FROM private_history")
    assert catalog["source"]["as_of_utc"] == stamp
    assert "final retrospective" not in json.dumps(catalog)
    assert (full.stat().st_mode & 0o777) == 0o600
    before = full.read_bytes()
    materialize_snapshot(history, weekly_cutoffs(history)[-1], tmp_path / "later.sqlite3")
    assert full.read_bytes() == before


def test_delayed_rows_manifests_and_empty_partitions_are_distinct(tmp_path):
    history = make_history()
    states = []
    for index, cutoff in enumerate(weekly_cutoffs(history)):
        snapshot = materialize_snapshot(history, cutoff, tmp_path / f"state-{index}.sqlite3")
        states.append(rows(snapshot, "weekly_source_coverage"))
    assert any(row["expected_ticket_count"] == row["observed_ticket_count"] == 0 and row["coverage_status"] == "complete" for row in states[0])
    assert any(row["coverage_status"] in {"missing", "partial"} for group in states for row in group)
    unknown = [row for group in states for row in group if row["coverage_status"] == "unknown"]
    assert unknown and all(row["expected_ticket_count"] is row["missing_ticket_count"] is None for row in unknown)
    late_key = (history["first_week"] + timedelta(weeks=9)).date().isoformat(), "business", "central"
    selected = [[row for row in state if (row["week_start_utc"], row["support_tier"], row["region"]) == late_key] for state in states]
    statuses = [group[0]["coverage_status"] for group in selected if group]
    assert statuses[0] in {"missing", "partial"} and statuses[-1] == "complete"


def test_existing_paths_and_symlinks_are_never_replaced(tmp_path):
    history = make_history(weeks=3)
    cutoff = weekly_cutoffs(history)[0]
    original = materialize_snapshot(history, cutoff, tmp_path / "source.sqlite3")
    content = original.read_bytes()
    with pytest.raises(FileExistsError):
        materialize_snapshot(history, cutoff, original)
    link = tmp_path / "link.sqlite3"
    link.symlink_to(original)
    with pytest.raises(FileExistsError):
        materialize_snapshot(history, cutoff, link)
    assert original.read_bytes() == content and link.is_symlink()


@pytest.mark.parametrize("fault", ["answer_label", "naive", "subsecond", "changed_identity"])
def test_invalid_source_records_fail_before_creating_a_file(tmp_path, fault):
    history = make_history(weeks=1)
    record = next(row for row in history["events"] if row["payload"]["kind"] == "created")
    if fault == "answer_label":
        record["payload"]["expected_outcome"] = "not-a-source-field"
    elif fault == "naive":
        record["effective_at"] = record["effective_at"].replace(tzinfo=None)
    elif fault == "subsecond":
        record["effective_at"] = record["effective_at"].replace(microsecond=1)
    else:
        changed = copy.deepcopy(record)
        changed["revision"] = 2
        changed["payload"]["ticket_id"] = "a-different-ticket"
        history["events"].append(changed)
    path = tmp_path / "invalid.sqlite3"
    with pytest.raises(ValueError):
        materialize_snapshot(history, weekly_cutoffs(history)[0], path)
    assert not path.exists()


def test_export_keeps_the_historical_clock_and_query_not_a_fake_current_capture(tmp_path):
    from signalweave.models import ResourceSnapshot

    history = make_history()
    cutoff = weekly_cutoffs(history)[0]
    snapshot = materialize_snapshot(history, cutoff, tmp_path / "source.sqlite3")
    query = "SELECT support_tier,COUNT(*) AS known FROM tickets GROUP BY support_tier"
    result = export_query(snapshot, query, "metric:known", "known", "Known tickets")
    parsed = ResourceSnapshot.model_validate(result)
    assert parsed.adapter == ADAPTER
    assert parsed.source_captured_at == cutoff
    assert result["metadata"]["capture_status"] == "synthetic_as_of"
    assert result["metadata"]["saved_query_definition"]["sql"] == query
    assert result["metadata"]["assets_read"] == ["harbor_operational_snapshot:tickets"]
    assert len(parsed.evidence) == 3 and not parsed.observations and "outcome" not in result


@pytest.mark.asyncio
async def test_actual_stdio_mcp_can_only_query_one_knowable_snapshot(tmp_path):
    history = make_history()
    cutoff = weekly_cutoffs(history)[0]
    database = materialize_snapshot(history, cutoff, tmp_path / "source.sqlite3")
    future = next(row for row in history["events"] if row["payload"]["kind"] == "created"
                  and row["available_at"] > cutoff + timedelta(weeks=1))
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(command=sys.executable,
        args=["-m", "evaluations.harbor_history_mcp", str(database)],
        env={**os.environ, "PYTHONPATH": str(root)}, cwd=str(root))
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_log:
        with anyio.fail_after(30):
            async with stdio_client(parameters, errlog=error_log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    assert names == {"list_assets", "inspect_asset", "query_readonly", "export_query"}
                    result = await session.call_tool("query_readonly", {"sql": "SELECT COUNT(*) AS known FROM tickets"})
                    assert not result.isError, result
                    assert result.structuredContent is not None, result
                    payload = result.structuredContent
                    assert payload["rows"][0][0] > 0 and payload["source"]["as_of_utc"] == cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
                    result = await session.call_tool("query_readonly", {"sql": f"SELECT ticket_id FROM tickets WHERE ticket_id='{future['payload']['ticket_id']}'"})
                    assert result.structuredContent["rows"] == []
                    denied = await session.call_tool("query_readonly", {"sql": "DELETE FROM tickets"})
                    assert denied.isError
                    missing = await session.call_tool("query_readonly", {"sql": "SELECT * FROM private_history"})
                    assert missing.isError

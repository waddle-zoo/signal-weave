"""Harness contract checks, not business or onboarding success evidence."""

import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import Tool

from evaluations import harbor_onboarding as trial


def actor(tmp_path, treatment=False):
    source = SimpleNamespace(list_tools=AsyncMock(return_value=[
        Tool(name=name, inputSchema={"type": "object", "properties": {}})
        for name in ("list_assets", "inspect_asset", "query_readonly")
    ]), call_tool=AsyncMock(return_value=([], {"rows": [[7]], "truncated": False})))
    server = SimpleNamespace(list_tools=AsyncMock(return_value=[
        Tool(name=name, inputSchema={"type": "object", "properties": {}})
        for name in (*trial.NATIVE_TOOLS, "approve_insight_card", "evaluate_insight_card")
    ]), call_tool=AsyncMock(return_value=([], {"id": "draft-only"}))) if treatment else None
    return trial.Author(source, {"owner://policy": "An ordinary declared policy, not approval"},
                        tmp_path / "publication.json", trial.Audit(), server)


def finding(query="q1"):
    return {"title": "Self-authored finding", "findings": [{"statement": "A possible cause remains a hypothesis.",
        "values": {"claim_kind": "hypothesis", "unusual_measure": 0.125}, "query_ids": [query]}]}


async def test_both_arms_keep_identical_company_owner_and_publication_tools(tmp_path):
    baseline, treatment = actor(tmp_path), actor(tmp_path, True)
    shared, extended = await baseline.specs(), await treatment.specs()
    assert [tool for tool in extended if tool["name"] not in trial.NATIVE_TOOLS] == shared
    assert {tool["name"] for tool in extended}.isdisjoint({"approve_insight_card", "evaluate_insight_card", "review_domain_context"})
    assert len({tool["name"] for tool in extended}) == len(extended)
    from jsonschema import Draft202012Validator
    for tool in extended:
        Draft202012Validator.check_schema(tool["parameters"])


async def test_owner_reference_cannot_become_consent_or_prepared_facts(tmp_path):
    instance = actor(tmp_path)
    reply = await instance.call("ask_owner", {"question": "Which population and alert policy?"})
    assert "An ordinary declared policy" in json.dumps(reply)
    assert instance.submission is None and instance.publication is None
    assert instance.source.call_tool.await_count == 0


async def test_actual_query_references_and_agent_claims_survive_publication(tmp_path):
    instance = actor(tmp_path)
    with pytest.raises(ValueError, match="actual source"):
        await instance.call("publish_analysis", finding())
    result = await instance.call("query_readonly", {"sql": "SELECT COUNT(*) FROM tickets"})
    assert result["audit_query_id"] == "q1" and result["rows"] == [[7]]
    with pytest.raises(ValueError, match="actually executed"):
        await instance.call("publish_analysis", finding("q999"))
    payload = finding()
    await instance.call("publish_analysis", payload)
    publication = json.loads(instance.path.read_text())
    assert publication["evidence"][0]["values"] == payload["findings"][0]["values"]
    assert publication["source_captured_at"] is None
    assert publication["metadata"]["capture_status"] == "unknown"
    assert publication["metadata"]["input_results_sha256"] == {"q1": trial.canonical_hash(result)}
    assert instance.submission is None
    before = instance.path.read_bytes()
    with pytest.raises(ValueError, match="Only one"):
        await instance.call("publish_analysis", payload)
    assert instance.path.read_bytes() == before


async def test_recording_requires_actual_notes_and_publication_but_does_not_authorize(tmp_path):
    instance = actor(tmp_path)
    packet = {"message": "First human readout", "card_id": None, "context_id": None, "unresolved": ["Review this proposed workflow"]}
    with pytest.raises(ValueError, match="Save reusable"):
        await instance.call("record_setup", packet)
    await instance.call("query_readonly", {"sql": "SELECT COUNT(*) FROM tickets"})
    await instance.call("publish_analysis", finding())
    await instance.call("save_working_notes", {"notes": "Reusable policy, separate from dated observations"})
    with pytest.raises(ValueError, match="not native draft"):
        await instance.call("record_setup", {**packet, "card_id": "fake"})
    assert await instance.call("record_setup", packet) == {"recorded": True, "approved": False}
    assert instance.submission == packet
    with pytest.raises(ValueError, match="already recorded"):
        await instance.call("list_assets", {})


async def test_publication_is_bounded_without_changing_agent_values(tmp_path):
    instance = actor(tmp_path)
    await instance.call("query_readonly", {"sql": "SELECT COUNT(*) FROM tickets"})
    payload = deepcopy(finding())
    payload["findings"][0]["values"] = {"large": "x" * 41000}
    with pytest.raises(ValueError, match="40k"):
        await instance.call("publish_analysis", payload)
    assert instance.publication is None and not instance.path.exists()


def test_pending_report_never_invents_fresh_capture_or_findings():
    value = trial.pending_publication()
    assert value["evidence"] == [] and value["source_captured_at"] is None
    assert value["metadata"]["capture_status"] == "unknown"


@pytest.mark.parametrize("fault", [None, "guide", "inventory", "source_error", "source_identity", "tenant", "authorization", "findings", "catalog", "query_missing", "query_truncated", "query_empty", "query_bool"])
def test_preflight_requires_actual_tools_exact_source_and_real_complete_query(fault):
    guide, inventory = {"purpose": "Agent guide"}, set(trial.NATIVE_TOOLS)
    catalog, snapshot = {"resources": [dict(trial.SOURCE)]}, trial.pending_publication()
    probe = {"truncated": False, "columns": ["ticket_count"], "rows": [[123]]}
    if fault == "guide":
        guide = {}
    elif fault == "inventory":
        inventory.remove("review_insight_card")
    elif fault == "source_error":
        snapshot["error"] = "Unavailable"
    elif fault == "source_identity":
        snapshot["resource"] = "other"
    elif fault == "tenant":
        snapshot["contract"]["tenant_id"] = "other"
    elif fault == "authorization":
        snapshot["contract"]["authorized"] = False
    elif fault == "findings":
        snapshot["observations"] = [{"metric": "prepared"}]
    elif fault == "catalog":
        catalog = {"resources": []}
    elif fault == "query_missing":
        probe = {}
    elif fault == "query_truncated":
        probe["truncated"] = True
    elif fault == "query_empty":
        probe["rows"] = []
    elif fault == "query_bool":
        probe["rows"] = [[True]]
    if fault is None:
        trial.validate_preflight(guide, inventory, catalog, snapshot, probe)
    else:
        with pytest.raises(ValueError):
            trial.validate_preflight(guide, inventory, catalog, snapshot, probe)


@pytest.mark.parametrize("seed", [20261016, 982])
def test_saved_source_exports_reconcile_to_independent_raw_reference(tmp_path, seed):
    from evaluations.harbor_reference import summarize
    from examples.harbor_help.company_mcp import export_query
    from examples.harbor_help.seed import generate_database

    database = generate_database(tmp_path / "source.sqlite3", seed=seed)
    reference = summarize(database)
    latest = reference["pooled_by_week"][-2:]
    exports = {item["key"]: export_query(database, item["sql"], item["resource"], item["key"], item["title"])
               for item in trial.export_definitions()}
    for key, packet in exports.items():
        assert packet["source_captured_at"] is None
        rows = [item["values"] for item in packet["evidence"]]
        assert [row["week_start_utc"] for row in rows] == [row["week_start_utc"] for row in latest]
        for row, raw in zip(rows, latest, strict=True):
            if key == "resolution":
                assert row["eligible_resolved_tickets"] == raw["eligible_resolved_priority_count"]
                assert row["resolution_sla_misses"] == raw["late_resolved_priority_count"]
                assert row["miss_rate_fraction"] == pytest.approx(raw["late_resolution_rate"])
            elif key == "coverage":
                assert row["expected_ticket_count"] == raw["coverage"]["expected_ticket_count"]
                assert row["observed_ticket_count"] == raw["observed_ticket_count"]
                assert row["missing_ticket_count"] == raw["coverage"]["missing_ticket_count"]
            else:
                assert row["as_of_utc"] == reference["source_cutoff_utc"]
                assert row["overdue_open_priority_tickets"] == raw["overdue_open_priority_count"]
                assert row["unanswered_tickets"] == raw["unanswered_count"]
    current = exports["resolution"]["evidence"][-1]["values"]
    assert current["comparison_available"] == 1
    assert current["comparison_week_start_utc"] == latest[-2]["week_start_utc"]
    assert current["previous_observed_week_start_utc"] == latest[-2]["week_start_utc"]
    assert current["change_percentage_points"] == pytest.approx(
        100 * (latest[-1]["late_resolution_rate"] - latest[-2]["late_resolution_rate"])
    )


@pytest.mark.parametrize("keep_missing_ledger", [False, True])
def test_missing_calendar_week_is_not_replaced_by_an_older_observed_week(tmp_path, keep_missing_ledger):
    from contextlib import closing

    from examples.harbor_help.company_mcp import export_query
    from examples.harbor_help.seed import generate_database

    database = generate_database(tmp_path / "gap.sqlite3")
    with closing(sqlite3.connect(database)) as connection, connection:
        weeks = [row[0] for row in connection.execute(
            "SELECT DISTINCT week_start_utc FROM source_ingestion_ledger ORDER BY week_start_utc DESC LIMIT 3"
        )]
        current, missing, older = weeks
        connection.execute("DELETE FROM tickets WHERE week_start_utc = ?", (missing,))
        if keep_missing_ledger:
            connection.execute("UPDATE source_ingestion_ledger SET received_ticket_count = 0, "
                               "ingestion_status = 'missing', ingested_at_utc = NULL WHERE week_start_utc = ?", (missing,))
        else:
            connection.execute("DELETE FROM source_ingestion_ledger WHERE week_start_utc = ?", (missing,))
    exports = {item["key"]: export_query(database, item["sql"], item["resource"], item["key"], item["title"])
               for item in trial.export_definitions()}
    for packet in exports.values():
        rows = [evidence["values"] for evidence in packet["evidence"]]
        assert any(row["week_start_utc"] == current for row in rows)
        assert all(row["week_start_utc"] != older for row in rows)
    latest = exports["resolution"]["evidence"][-1]["values"]
    assert latest["eligible_resolved_tickets"] > 0
    assert latest["change_percentage_points"] is None
    assert latest["previous_observed_week_start_utc"] == older
    assert latest["comparison_week_start_utc"] == missing
    assert latest["comparison_available"] == 0


def test_zero_previous_denominator_keeps_current_facts_without_a_fake_change(tmp_path):
    from contextlib import closing

    from examples.harbor_help.company_mcp import export_query
    from examples.harbor_help.seed import generate_database

    database = generate_database(tmp_path / "empty-population.sqlite3")
    with closing(sqlite3.connect(database)) as connection, connection:
        previous = connection.execute("SELECT DISTINCT week_start_utc FROM source_ingestion_ledger "
                                      "ORDER BY week_start_utc DESC LIMIT 1 OFFSET 1").fetchone()[0]
        connection.execute("UPDATE tickets SET priority = 0 WHERE week_start_utc = ?", (previous,))
    definition = next(item for item in trial.export_definitions() if item["key"] == "resolution")
    packet = export_query(database, definition["sql"], definition["resource"], definition["key"], definition["title"])
    prior, current = [evidence["values"] for evidence in packet["evidence"]]
    assert prior["eligible_resolved_tickets"] == 0 and prior["miss_rate_fraction"] is None
    assert current["eligible_resolved_tickets"] > 0 and current["miss_rate_fraction"] is not None
    assert current["comparison_week_start_utc"] == previous
    assert current["comparison_available"] == 0 and current["change_percentage_points"] is None

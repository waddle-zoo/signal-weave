"""Focused offline contracts for the Harbor preflight's fixed SQL."""

from __future__ import annotations

import builtins
import hashlib
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations.harbor_history import make_history, materialize_snapshot
from evaluations.harbor_history_mcp import ADAPTER, query_readonly
from evaluations.harbor_history_preflight import (
    DUMMY_KEY,
    QUERY_DEFINITIONS,
    _errors,
    _structured,
    _validate_exports,
    build_manifest,
    plan_cutoffs,
    query_definition_report,
)
from evaluations.harbor_history_reference import summarize_history


def _query(database: Path, key: str, as_of: str) -> list[dict]:
    result = query_readonly(database, QUERY_DEFINITIONS[key]["sql"], row_limit=100)
    assert result["source"]["identifier"] == "harbor_operational_snapshot"
    assert result["source"]["as_of_utc"] == as_of
    assert result["truncated"] is False
    return [dict(zip(result["columns"], row, strict=True)) for row in result["rows"]]


def test_cutoff_plan_brackets_delayed_creation_facts_not_future_resolutions():
    history = make_history()
    plan = plan_cutoffs(history)
    assert [item["key"] for item in plan] == [
        "first_score_cutoff", "delayed_batch_cutoff", "later_backfill_cutoff",
    ]
    ids = {row["payload"]["ticket_id"] for row in history["events"]
           if row["payload"].get("kind") == "created"
           and row["payload"].get("support_tier") == "business"
           and row["payload"].get("region") == "central"
           and row["available_at"] - row["effective_at"] >= timedelta(days=8)}
    batch = [row for row in history["events"] if row["payload"].get("kind") == "created"
             and row["payload"].get("ticket_id") in ids]
    later_facts = [row for row in history["events"] if row["payload"].get("ticket_id") in ids]
    week = plan[0]["delayed_batch_week_start"]
    assert plan[0]["cutoff"] < plan[1]["cutoff"] < plan[2]["cutoff"]
    assert week + timedelta(weeks=1) <= plan[1]["cutoff"] < min(row["available_at"] for row in batch)
    assert plan[2]["cutoff"] >= max(row["available_at"] for row in batch)
    assert plan[2]["cutoff"] < max(row["available_at"] for row in later_facts)


def test_three_fixed_exports_match_independent_raw_reference(tmp_path):
    history = make_history()
    for item in plan_cutoffs(history):
        cutoff = item["cutoff"]
        as_of = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        database = materialize_snapshot(history, cutoff, tmp_path / f"{item['key']}.sqlite3")
        expected = summarize_history(history, cutoff)
        latest = max(row["week_start_utc"] for row in expected["coverage"])
        previous = (cutoff.date() - timedelta(days=14)).isoformat()

        resolution, = _query(database, "resolution", as_of)
        assert resolution["latest_week_start_utc"] == latest
        assert resolution["comparison_week_start_utc"] == previous
        for prefix, week in (("latest", latest), ("comparison", previous)):
            for field in ("observed_ticket_count", "eligible_resolved_tickets", "resolution_sla_misses"):
                values = [r[field] for r in expected["resolution"] if r["week_start_utc"] == week]
                assert resolution[f"{prefix}_{field}"] == (sum(values) if values else None)
            denominator = resolution[f"{prefix}_eligible_resolved_tickets"]
            rate = resolution[f"{prefix}_resolution_sla_misses"] / denominator if denominator else None
            actual = resolution[f"{prefix}_resolution_sla_miss_rate"]
            assert actual == pytest.approx(rate) if rate is not None else actual is None
        available = bool(resolution["comparison_calendar_available"]
                         and resolution["latest_eligible_resolved_tickets"]
                         and resolution["comparison_eligible_resolved_tickets"])
        assert resolution["arithmetic_difference_available"] == int(available)
        assert resolution["age_matched"] == 0
        assert resolution["semantic_basis"] == "unequal_age_cohort_rates_descriptive_only"
        assert resolution["resolution_sla_miss_rate_arithmetic_difference_percentage_points"] == (
            pytest.approx(100 * (resolution["latest_resolution_sla_miss_rate"]
                                - resolution["comparison_resolution_sla_miss_rate"])) if available else None
        )

        coverage = _query(database, "coverage", as_of)
        assert [row["week_start_utc"] for row in coverage] == [latest, previous]
        for row in coverage:
            group = [r for r in expected["coverage"] if r["week_start_utc"] == row["week_start_utc"]]
            known = [r for r in group if r["expected_ticket_count"] is not None]
            unknown = len(group) - len(known)
            assert row["represented_segments"] == len(group)
            assert row["unknown_manifest_segments"] == unknown
            assert row["known_expected_ticket_count"] == sum(r["expected_ticket_count"] for r in known)
            assert row["expected_ticket_count"] == (
                None if unknown else sum(r["expected_ticket_count"] for r in known))
            assert row["observed_ticket_count"] == sum(r["observed_ticket_count"] for r in group)
            missing = [r["missing_ticket_count"] for r in group if r["missing_ticket_count"] is not None]
            assert row["known_missing_ticket_count"] == sum(missing)
            assert row["missing_ticket_count"] == (None if unknown else sum(missing))
        if item["key"] == "later_backfill_cutoff":
            pending = next(row for row in coverage if row["week_start_utc"] == item["pending_manifest_week_start"])
            assert pending["unknown_manifest_segments"] > 0
            assert pending["expected_ticket_count"] is pending["missing_ticket_count"] is None

        backlog, = _query(database, "backlog", as_of)
        source = expected["backlog"]
        assert backlog["as_of_utc"] == as_of
        assert backlog["known_creation_cohort_count"] == len({r["week_start_utc"] for r in source})
        assert backlog["oldest_known_creation_cohort_week_start"] == min(r["week_start_utc"] for r in source)
        assert backlog["latest_known_creation_cohort_week_start"] == max(r["week_start_utc"] for r in source)
        for field in ("open_priority_tickets", "overdue_open_priority_tickets",
                      "unanswered_tickets", "overdue_unanswered_tickets"):
            assert backlog[field] == sum(row[field] for row in source)


def test_manifest_has_only_fixed_queries_and_strict_structured_results(tmp_path):
    python = Path("/repo/.venv/bin/python")
    manifest = build_manifest(tmp_path / "snapshot.sqlite3", python)
    connection, = manifest["connections"]
    assert connection["read_only"] is True
    assert connection["transport"]["command"] == [
        str(python), "-m", "evaluations.harbor_history_mcp", str(tmp_path / "snapshot.sqlite3")]
    assert len(connection["resources"]) == 3
    for key, resource in zip(QUERY_DEFINITIONS, connection["resources"], strict=True):
        assert resource["tool"] == "export_query"
        assert resource["arguments"]["sql"] == QUERY_DEFINITIONS[key]["sql"]
        assert resource["descriptor"]["adapter"] == ADAPTER
    definition = QUERY_DEFINITIONS["resolution"]["sql"].encode()
    assert query_definition_report()["resolution"]["sha256"] == hashlib.sha256(definition).hexdigest()
    assert DUMMY_KEY.startswith("test-")
    assert _structured(SimpleNamespace(isError=False, structuredContent={"ok": True}), "tool") == {"ok": True}
    with pytest.raises(ValueError, match="omitted structuredContent"):
        _structured(SimpleNamespace(isError=False, structuredContent=None), "tool")


def test_inspection_alias_is_preserved_consistently_not_confused_with_source_registration(tmp_path):
    from evaluations.harbor_history_mcp import export_query

    history = make_history()
    cutoff = plan_cutoffs(history)[0]["cutoff"]
    as_of = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    path = materialize_snapshot(history, cutoff, tmp_path / "alias.sqlite3")
    definition = QUERY_DEFINITIONS["resolution"]
    value = export_query(path, definition["sql"], definition["resource"], "resolution", definition["title"])
    direct = [row["values"] for row in value["evidence"]]
    value["source_key"] = "caller-inspection-alias"
    for row in value["evidence"]:
        row["source_key"] = value["source_key"]
    assert _validate_exports(value, "resolution", as_of, direct) == len(direct)
    value["evidence"][0]["source_key"] = "foreign-key"
    with pytest.raises(ValueError, match="rows differ"):
        _validate_exports(value, "resolution", as_of, direct)


def test_sdk_exception_group_does_not_hide_the_meaningful_leaf_failure():
    from evaluations.bootstrap_agent_trial import Audit

    error = builtins.ExceptionGroup("SDK cleanup", [ValueError("source mismatch"), builtins.ExceptionGroup("nested", [RuntimeError("useful detail")])])
    assert _errors(error, Audit()) == [
        {"type": "ValueError", "message": "source mismatch"},
        {"type": "RuntimeError", "message": "useful detail"},
    ]

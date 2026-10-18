"""Exact source-query meaning before any policy/actor experiment is admitted."""

from datetime import datetime
from pathlib import Path

import pytest

from evaluations.harbor_history import materialize_snapshot, weekly_cutoffs
from evaluations.harbor_history_mcp import export_query, query_readonly
from evaluations.harbor_history_reference import summarize_history
from evaluations.harbor_workflow_history import make_queue_history
from evaluations.harbor_workflow_sources import QUEUE_RESOURCE, QUEUE_SQL, build_workflow_manifest
from signalweave.models import ResourceSnapshot


@pytest.mark.parametrize("priority,response", [(1, False), (1, True), (0, False), (0, True)])
def test_priority_clock_export_matches_independent_visible_ticket_populations(tmp_path, priority, response):
    history = make_queue_history(priority=priority, recorded_response=response, complete_background_responses=True)
    clocks = {row["support_tier"]: row for row in history["clock_definitions"]}
    for index, cutoff in enumerate(weekly_cutoffs(history)[:3]):
        reference = summarize_history(history, cutoff)
        tickets = reference["tickets"]
        opened = [row for row in tickets if row["status"] == "open" and row["priority"] == 1]
        unanswered = [row for row in opened if row["first_response_at_utc"] is None]

        def past_clock(row, field, as_of):
            age = as_of - datetime.fromisoformat(row["created_at_utc"].replace("Z", "+00:00"))
            return age.total_seconds() > clocks[row["support_tier"]][field] * 3600

        expected = {
            "as_of_utc": reference["as_of_utc"], "known_ticket_count": len(tickets),
            "known_open_priority_tickets": len(opened), "known_unanswered_open_priority_tickets": len(unanswered),
            "known_unanswered_open_priority_past_response_clock": sum(past_clock(row, "first_response_sla_hours", cutoff) for row in unanswered),
            "known_open_priority_past_resolution_clock": sum(past_clock(row, "resolution_sla_hours", cutoff) for row in opened),
        }
        database = materialize_snapshot(history, cutoff, tmp_path / f"source-{index}.sqlite3")
        result = query_readonly(database, QUEUE_SQL)
        assert result["truncated"] is False and len(result["rows"]) == 1
        assert dict(zip(result["columns"], result["rows"][0], strict=True)) == expected
        exported = export_query(database, QUEUE_SQL, QUEUE_RESOURCE, "priority-queue", "Known priority clocks")
        snapshot = ResourceSnapshot.model_validate(exported)
        assert snapshot.evidence[0].values == expected
        assert snapshot.source_captured_at == cutoff
        assert snapshot.metadata["saved_query_definition"]["sql"] == QUEUE_SQL


def test_workflow_manifest_adds_one_fixed_query_without_dropping_existing_reads(tmp_path):
    from evaluations.harbor_history_preflight import build_manifest

    path, python = tmp_path / "source.sqlite3", Path("/repo/.venv/bin/python")
    baseline = build_manifest(path, python)
    manifest = build_workflow_manifest(path, python)
    connection, = manifest["connections"]
    assert connection["resources"][:-1] == baseline["connections"][0]["resources"]
    extra = connection["resources"][-1]
    assert extra["descriptor"]["resource"] == QUEUE_RESOURCE
    assert extra["arguments"]["sql"] == QUEUE_SQL and extra["tool"] == "export_query"
    assert extra["descriptor"]["metadata"]["sql_sha256"] in extra["descriptor"]["contract"]["lineage"][0]
    assert not {"outcome", "recipient", "decision_guidance", "expected_outcome"} & extra.keys()
    assert connection["read_only"] is True

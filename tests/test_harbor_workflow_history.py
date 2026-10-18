"""Independent factual checks of a controlled journey, not actor outcomes."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from evaluations.harbor_history import make_history, materialize_snapshot, weekly_cutoffs
from evaluations.harbor_history_mcp import query_readonly
from evaluations.harbor_history_reference import summarize_history
from evaluations.harbor_workflow_history import make_queue_history, make_responded_history


def _sum(reference, view, field):
    return sum(row[field] for row in reference[view])


@pytest.mark.parametrize("seed", [17, 42, 20261018])
@pytest.mark.parametrize("priority", [0, 1])
@pytest.mark.parametrize("recorded_response", [False, True])
def test_controlled_history_has_matched_ordinary_open_and_resolved_states(tmp_path, seed, priority, recorded_response):
    base = make_history(seed=seed)
    augmented = make_queue_history(seed=seed, priority=priority, recorded_response=recorded_response)
    original = set(row["payload"]["ticket_id"] for row in base["events"] if row["payload"]["kind"] == "created")
    ids = set(row["payload"]["ticket_id"] for row in augmented["events"] if row["payload"]["kind"] == "created") - original
    assert len(ids) == 80
    target_week = (base["first_week"] + timedelta(weeks=7)).date().isoformat()
    for index, cutoff in enumerate(weekly_cutoffs(base)[:3]):
        before, after = summarize_history(base, cutoff), summarize_history(augmented, cutoff)
        visible = [ticket for ticket in after["tickets"] if ticket["ticket_id"] in ids]
        assert len(visible) == (0 if index == 0 else 80)
        assert _sum(after, "backlog", "open_priority_tickets") - _sum(before, "backlog", "open_priority_tickets") == (80 * priority if index == 1 else 0)
        assert _sum(after, "backlog", "overdue_open_priority_tickets") - _sum(before, "backlog", "overdue_open_priority_tickets") == (80 * priority if index == 1 else 0)
        assert _sum(after, "backlog", "unanswered_tickets") - _sum(before, "backlog", "unanswered_tickets") == (80 if index == 1 and not recorded_response else 0)
        assert _sum(after, "resolution", "resolution_sla_misses") - _sum(before, "resolution", "resolution_sla_misses") == (80 * priority if index == 2 else 0)
        assert _sum(after, "resolution", "eligible_resolved_tickets") - _sum(before, "resolution", "eligible_resolved_tickets") == (80 * priority if index == 2 else 0)
        assert _sum(after, "first_response", "first_response_sla_misses") == _sum(before, "first_response", "first_response_sla_misses")
        assert _sum(after, "first_response", "first_response_clock_tickets") - _sum(before, "first_response", "first_response_clock_tickets") == (80 if index and recorded_response else 0)
        if visible:
            assert {row["status"] for row in visible} == ({"open"} if index == 1 else {"resolved"})
            assert all((row["first_response_at_utc"] is not None) == recorded_response for row in visible)
            group, = [row for row in after["coverage"] if row["week_start_utc"] == target_week
                       and row["support_tier"] == "enterprise" and row["region"] == "north"]
            assert group["coverage_status"] == "complete" and group["missing_ticket_count"] == 0

        database = materialize_snapshot(augmented, cutoff, tmp_path / f"snapshot-{index}.sqlite3")
        for key, table in (("resolution", "weekly_resolution_sla"), ("first_response", "weekly_first_response_sla"),
                           ("backlog", "weekly_open_backlog"), ("coverage", "weekly_source_coverage")):
            result = query_readonly(database, f"SELECT * FROM {table} ORDER BY week_start_utc,support_tier,region", row_limit=500)
            assert result["truncated"] is False
            rows = [dict(zip(result["columns"], row, strict=True)) for row in result["rows"]]
            expected = sorted(after[key], key=lambda row: (row["week_start_utc"], row["support_tier"], row["region"]))
            assert rows == expected
        if index == 0:
            control = materialize_snapshot(base, cutoff, tmp_path / "ordinary-control.sqlite3")
            assert control.read_bytes() == database.read_bytes()


def test_actual_resolution_does_not_become_known_until_event_arrives(tmp_path):
    history = make_queue_history(resolution_delay_hours=24 * 10)
    cutoff = weekly_cutoffs(history)[2]
    original = {row["payload"]["ticket_id"] for row in make_history()["events"] if row["payload"]["kind"] == "created"}
    resolution_ids = {row["payload"]["ticket_id"] for row in history["events"]
                      if row["payload"]["kind"] == "created"} - original
    state = summarize_history(history, cutoff)
    extra = [row for row in state["tickets"] if row["ticket_id"] in resolution_ids]
    assert len(extra) == 80
    assert all(row["status"] == "open" and row["resolved_at_utc"] is None for row in extra)
    source = materialize_snapshot(history, cutoff, tmp_path / "as-known.sqlite3")
    stamp = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert query_readonly(source, f"SELECT COUNT(*) FROM ticket_events WHERE available_at_utc>'{stamp}'")["rows"] == [[0]]
    # Even count-complete creation manifests cannot certify resolution ingestion.
    week = (history["first_week"] + timedelta(weeks=7)).date().isoformat()
    result = query_readonly(source, "SELECT coverage_status FROM weekly_source_coverage "
                            f"WHERE week_start_utc='{week}' AND support_tier='enterprise' AND region='north'")
    assert result["rows"] == [["complete"]]
    later = summarize_history(history, weekly_cutoffs(history)[4])
    assert all(row["status"] == "resolved" for row in later["tickets"] if row["ticket_id"] in resolution_ids)


@pytest.mark.parametrize("arguments", [
    {"added_tickets": 0}, {"added_tickets": True}, {"added_tickets": 5001},
    {"priority": True}, {"priority": 2}, {"resolution_delay_hours": -1},
    {"resolution_delay_hours": 721}, {"resolution_delay_hours": 1.5}, {"recorded_response": 1},
    {"complete_background_responses": "yes"},
])
def test_invalid_raw_workload_options_are_rejected(arguments):
    with pytest.raises(ValueError):
        make_queue_history(**arguments)


def test_reproduction_does_not_mutate_the_ordinary_source_or_add_policy_fields():
    ordinary = make_history()
    fingerprint = repr(ordinary)
    augmented = make_queue_history(added_tickets=13)
    assert repr(ordinary) == fingerprint
    assert augmented == make_queue_history(added_tickets=13)
    assert len(augmented["events"]) == len(ordinary["events"]) + 13 * 3
    assert set(augmented) == set(ordinary)
    assert all(set(row) == {"event_id", "revision", "effective_at", "available_at", "tombstone", "payload"}
               for row in augmented["events"])


@pytest.mark.parametrize("priority,recorded_response", [(1, False), (1, True), (0, False), (0, True)])
def test_quiet_control_discriminates_priority_and_clock_not_just_workload_volume(tmp_path, priority, recorded_response):
    history = make_queue_history(priority=priority, recorded_response=recorded_response,
                                 complete_background_responses=True)
    response_seconds = {row["support_tier"]: row["first_response_sla_hours"] * 3600
                        for row in history["clock_definitions"]}
    sql = """SELECT COUNT(*) AS known_open_priority_past_first_response_clock
             FROM tickets t JOIN support_tier_sla c USING(support_tier) CROSS JOIN source_snapshot s
             WHERE t.priority=1 AND t.status='open' AND t.first_response_at_utc IS NULL
             AND unixepoch(s.as_of_utc)-unixepoch(t.created_at_utc)>c.first_response_sla_hours*3600"""
    for index, cutoff in enumerate(weekly_cutoffs(history)[:3]):
        reference = summarize_history(history, cutoff)
        qualifying = [ticket for ticket in reference["tickets"]
                      if ticket["priority"] == 1 and ticket["status"] == "open"
                      and ticket["first_response_at_utc"] is None
                      and (cutoff - datetime.fromisoformat(ticket["created_at_utc"].replace("Z", "+00:00"))).total_seconds()
                      > response_seconds[ticket["support_tier"]]]
        expected_count = 80 if index == 1 and priority and not recorded_response else 0
        assert len(qualifying) == expected_count
        database = materialize_snapshot(history, cutoff, tmp_path / f"source-{index}.sqlite3")
        result = query_readonly(database, sql)
        assert result["rows"] == [[expected_count]] and not result["truncated"]
        # Zero qualifying unanswered work is not zero resolution/backlog work.
        if index == 1:
            assert _sum(reference, "backlog", "overdue_open_priority_tickets") > 0
        if index == 0:
            control = materialize_snapshot(make_responded_history(), cutoff, tmp_path / "matched-quiet.sqlite3")
            assert database.read_bytes() == control.read_bytes()


def test_completed_resolution_followup_occurs_before_target_creation_week_rolls_over(tmp_path):
    history = make_queue_history()
    base = make_history()
    original = {row["payload"]["ticket_id"] for row in base["events"] if row["payload"]["kind"] == "created"}
    added = [row for row in history["events"] if row["payload"]["kind"] == "resolution"
             and row["payload"]["ticket_id"] not in original]
    # This is a separate event-triggered follow-up, not another weekly sample.
    cutoff = max(row["available_at"] for row in added) + timedelta(hours=1)
    target = history["first_week"] + timedelta(weeks=7)
    assert target + timedelta(weeks=1) < cutoff < target + timedelta(weeks=2)
    before, after = summarize_history(base, cutoff), summarize_history(history, cutoff)
    week = max(row["week_start_utc"] for row in after["coverage"])
    assert week == target.date().isoformat()
    selected_before = [row for row in before["resolution"] if row["week_start_utc"] == week]
    selected_after = [row for row in after["resolution"] if row["week_start_utc"] == week]
    for field in ("eligible_resolved_tickets", "resolution_sla_misses"):
        assert sum(row[field] for row in selected_after) - sum(row[field] for row in selected_before) == 80
    database = materialize_snapshot(history, cutoff, tmp_path / "followup.sqlite3")
    result = query_readonly(database, "SELECT SUM(eligible_resolved_tickets),SUM(resolution_sla_misses) "
                            f"FROM weekly_resolution_sla WHERE week_start_utc='{week}'")
    assert result["rows"] == [[sum(row[field] for row in selected_after)
                               for field in ("eligible_resolved_tickets", "resolution_sla_misses")]]

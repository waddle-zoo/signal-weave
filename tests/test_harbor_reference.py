from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from evaluations import harbor_reference
from examples.harbor_help.seed import generate_database


def _query(database: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(database) as connection:
        return connection.execute(sql).fetchall()


@pytest.mark.parametrize("seed", [20261016, 4815, 913])
def test_raw_reference_matches_view_counts_and_rates_for_multiple_seeds(tmp_path, seed):
    database = generate_database(tmp_path / f"harbor-{seed}.sqlite3", seed=seed)
    result = harbor_reference.summarize(database)
    cohorts = {
        (row["week_start_utc"], row["support_tier"], row["region"]): row
        for row in result["by_cohort"]
    }

    resolution = {
        (week, tier, region): (observed, eligible, late, rate)
        for week, tier, region, observed, eligible, late, rate in _query(
            database,
            "SELECT week_start_utc, support_tier, region, observed_ticket_count, "
            "eligible_resolved_tickets, resolution_sla_misses, "
            "resolution_sla_miss_rate FROM weekly_resolution_sla",
        )
    }
    response = {
        (week, tier, region): (clocks, late, rate)
        for week, tier, region, clocks, late, rate in _query(
            database,
            "SELECT week_start_utc, support_tier, region, first_response_clock_tickets, "
            "first_response_sla_misses, first_response_sla_miss_rate "
            "FROM weekly_first_response_sla",
        )
    }
    backlog = {
        (week, tier, region): (open_priority, overdue_priority, unanswered, overdue_unanswered)
        for week, tier, region, open_priority, overdue_priority, unanswered, overdue_unanswered
        in _query(
            database,
            "SELECT week_start_utc, support_tier, region, open_priority_tickets, "
            "overdue_open_priority_tickets, unanswered_tickets, "
            "overdue_unanswered_tickets FROM weekly_open_backlog",
        )
    }
    coverage = {
        (week, tier, region): (expected, observed, missing, status)
        for week, tier, region, expected, observed, missing, status in _query(
            database,
            "SELECT week_start_utc, support_tier, region, expected_ticket_count, "
            "observed_ticket_count, missing_ticket_count, ingestion_status "
            "FROM weekly_source_coverage",
        )
    }

    assert len(cohorts) == len(coverage)
    for key, cohort in cohorts.items():
        observed, eligible, late, late_rate = resolution.get(key, (0, 0, 0, None))
        assert cohort["observed_ticket_count"] == observed
        assert cohort["eligible_resolved_priority_count"] == eligible
        assert cohort["late_resolved_priority_count"] == late
        assert cohort["late_resolution_rate"] == pytest.approx(late_rate)

        response_count, late_response, response_rate = response.get(key, (0, 0, None))
        assert cohort["responded_first_response_count"] == response_count
        assert cohort["late_first_response_count"] == late_response
        assert cohort["late_first_response_rate"] == pytest.approx(response_rate)

        open_priority, overdue_priority, unanswered, overdue_unanswered = backlog.get(
            key, (0, 0, 0, 0)
        )
        assert cohort["open_priority_count"] == open_priority
        assert cohort["overdue_open_priority_count"] == overdue_priority
        assert cohort["unanswered_count"] == unanswered
        assert cohort["overdue_unanswered_count"] == overdue_unanswered

        expected, received, missing, status = coverage[key]
        assert cohort["coverage"] == {
            "present": True,
            "expected_ticket_count": expected,
            "received_ticket_count": received,
            "missing_ticket_count": missing,
            "ingestion_status": status,
            "ingested_at_utc": cohort["coverage"]["ingested_at_utc"],
        }

    assert result["pooled"]["late_resolution_rate"] == pytest.approx(
        result["pooled"]["late_resolved_priority_count"]
        / result["pooled"]["eligible_resolved_priority_count"]
    )
    assert result["pooled"]["late_first_response_rate"] == pytest.approx(
        result["pooled"]["late_first_response_count"]
        / result["pooled"]["responded_first_response_count"]
    )
    assert len(result["missing_segments"]) == 1
    assert result["missing_segments"][0]["received_ticket_count"] == 0
    assert result["missing_segments"][0]["missing_ticket_count"] > 0


def test_reference_does_not_require_any_views(tmp_path):
    database = generate_database(tmp_path / "harbor.sqlite3", seed=41)
    before = harbor_reference.summarize(database)
    with sqlite3.connect(database) as connection:
        for view in (
            "weekly_resolution_sla", "weekly_first_response_sla",
            "weekly_open_backlog", "weekly_source_coverage",
        ):
            connection.execute(f"DROP VIEW {view}")
    assert harbor_reference.summarize(database) == before


def test_missing_ledger_coverage_is_none_and_reported_as_uncovered(tmp_path):
    database = generate_database(tmp_path / "harbor.sqlite3", seed=42)
    key = _query(
        database,
        "SELECT week_start_utc, support_tier, region FROM tickets LIMIT 1",
    )[0]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM source_ingestion_ledger "
            "WHERE week_start_utc = ? AND support_tier = ? AND region = ?", key
        )

    result = harbor_reference.summarize(database)
    cohort = next(
        row for row in result["by_cohort"]
        if (row["week_start_utc"], row["support_tier"], row["region"]) == key
    )
    assert cohort["coverage"]["present"] is False
    assert cohort["coverage"]["expected_ticket_count"] is None
    assert cohort["coverage"]["received_ticket_count"] is None
    assert cohort["coverage"]["missing_ticket_count"] is None
    assert result["uncovered_segments"] == [{
        "week_start_utc": key[0],
        "support_tier": key[1],
        "region": key[2],
        "observed_ticket_count": cohort["observed_ticket_count"],
    }]
    pooled_coverage = result["pooled"]["coverage"]
    assert pooled_coverage["absent_segment_count"] == 1
    assert pooled_coverage["expected_ticket_count"] is None
    assert pooled_coverage["received_ticket_count"] is None
    assert pooled_coverage["missing_ticket_count"] is None
    known_coverage = [
        row["coverage"] for row in result["by_cohort"] if row["coverage"]["present"]
    ]
    assert pooled_coverage["known_expected_ticket_count_subtotal"] == sum(
        row["expected_ticket_count"] for row in known_coverage
    )
    assert pooled_coverage["known_received_ticket_count_subtotal"] == sum(
        row["received_ticket_count"] for row in known_coverage
    )
    assert pooled_coverage["known_missing_ticket_count_subtotal"] == sum(
        row["missing_ticket_count"] for row in known_coverage
    )
    assert "cannot be inferred" in result["coverage_scope_note"]


def test_week_filter_uses_creation_cohort_and_has_null_rates_for_empty_week(tmp_path):
    database = generate_database(tmp_path / "harbor.sqlite3", seed=43)
    first_week = harbor_reference.summarize(database)["by_cohort"][0]["week_start_utc"]
    filtered = harbor_reference.summarize(database, first_week)
    assert filtered["week_start_filter"] == first_week
    assert {row["week_start_utc"] for row in filtered["by_cohort"]} == {first_week}

    empty = harbor_reference.summarize(database, "2030-01-07")
    assert empty["by_cohort"] == []
    assert empty["pooled"]["late_resolution_rate"] is None
    assert empty["pooled"]["coverage"]["expected_ticket_count"] is None

    with pytest.raises(ValueError, match="Monday"):
        harbor_reference.summarize(database, "2026-01-06")


def test_invalid_creation_week_and_nonpositive_clock_are_rejected(tmp_path):
    database = generate_database(tmp_path / "harbor.sqlite3", seed=44)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE tickets SET week_start_utc = '2026-01-12' WHERE ticket_id = "
            "(SELECT ticket_id FROM tickets LIMIT 1)"
        )
    with pytest.raises(ValueError, match="creation date disagrees"):
        harbor_reference.summarize(database)

    database = generate_database(tmp_path / "bad-clock.sqlite3", seed=45)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "UPDATE support_tier_sla SET resolution_sla_hours = 0 "
            "WHERE support_tier = 'enterprise'"
        )
    with pytest.raises(ValueError, match="positive integers"):
        harbor_reference.summarize(database)


def test_duplicate_sla_definitions_are_rejected_before_joining(tmp_path):
    database = generate_database(tmp_path / "harbor.sqlite3", seed=46)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ALTER TABLE support_tier_sla RENAME TO old_support_tier_sla")
        connection.execute(
            "CREATE TABLE support_tier_sla (support_tier TEXT, "
            "resolution_sla_hours INTEGER, first_response_sla_hours INTEGER)"
        )
        connection.execute(
            "INSERT INTO support_tier_sla SELECT support_tier, resolution_sla_hours, "
            "first_response_sla_hours FROM old_support_tier_sla"
        )
        connection.execute(
            "INSERT INTO support_tier_sla SELECT support_tier, resolution_sla_hours, "
            "first_response_sla_hours FROM support_tier_sla LIMIT 1"
        )
        connection.execute("DROP TABLE old_support_tier_sla")

    with pytest.raises(ValueError, match="duplicate SLA definition"):
        harbor_reference.summarize(database)


def test_cli_emits_json_and_connections_are_closed_read_only(tmp_path, monkeypatch, capsys):
    database = generate_database(tmp_path / "harbor.sqlite3", seed=47)
    original_bytes = database.read_bytes()
    real_connect = sqlite3.connect
    connections = []
    connection_uris = []

    class TrackingConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    def tracking_connect(*args, **kwargs):
        connection_uris.append((args[0], kwargs.get("uri")))
        connection = real_connect(*args, factory=TrackingConnection, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(harbor_reference.sqlite3, "connect", tracking_connect)
    assert harbor_reference.main([str(database), "--week-start", "2026-01-05"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["week_start_filter"] == "2026-01-05"
    assert connections[-1].closed is True
    assert connection_uris == [(f"{database.as_uri()}?mode=ro", True)]
    assert database.read_bytes() == original_bytes

    with real_connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] > 0

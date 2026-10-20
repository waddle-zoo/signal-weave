from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pytest

from examples.harbor_help.seed import (
    FIRST_WEEK,
    MAX_TICKETS,
    REGIONS,
    TIERS,
    WEEK_COUNT,
    generate_database,
)


def _rows(database: Path, query: str) -> list[tuple]:
    with sqlite3.connect(database) as connection:
        return connection.execute(query).fetchall()


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _database_contents(database: Path) -> tuple[list[tuple], list[tuple], list[tuple]]:
    return (
        _rows(database, "SELECT * FROM support_tier_sla ORDER BY support_tier"),
        _rows(database, "SELECT * FROM tickets ORDER BY ticket_id"),
        _rows(database, "SELECT * FROM source_ingestion_ledger ORDER BY week_start_utc, support_tier, region"),
    )


def test_views_match_independent_recomputation_from_raw_tickets(tmp_path):
    database = generate_database(tmp_path / "harbor.sqlite3", seed=4815)
    with sqlite3.connect(database) as connection:
        ticket_rows = connection.execute(
            """SELECT week_start_utc, created_at_utc, support_tier, region,
                      priority, status, first_response_at_utc, resolved_at_utc
               FROM tickets"""
        ).fetchall()
        sla_hours = {
            tier: (resolution_hours, response_hours)
            for tier, resolution_hours, response_hours in connection.execute(
                "SELECT support_tier, resolution_sla_hours, first_response_sla_hours "
                "FROM support_tier_sla"
            )
        }
        ledger_rows = connection.execute(
            """SELECT week_start_utc, support_tier, region, expected_ticket_count,
                      ingestion_status
               FROM source_ingestion_ledger"""
        ).fetchall()
        resolution_view = connection.execute(
            "SELECT week_start_utc, support_tier, region, eligible_resolved_tickets, "
            "resolution_sla_misses, resolution_sla_miss_rate FROM weekly_resolution_sla"
        ).fetchall()
        response_view = connection.execute(
            "SELECT week_start_utc, support_tier, region, first_response_clock_tickets, "
            "first_response_sla_misses, open_tickets_with_response_clock, "
            "first_response_sla_miss_rate FROM weekly_first_response_sla"
        ).fetchall()
        coverage_view = connection.execute(
            "SELECT week_start_utc, support_tier, region, expected_ticket_count, "
            "observed_ticket_count, missing_ticket_count, ingestion_status, coverage_status "
            "FROM weekly_source_coverage"
        ).fetchall()

    # Recompute the numerators and denominators directly from source rows.
    resolution = defaultdict(lambda: [0, 0])
    response = defaultdict(lambda: [0, 0, 0])
    observed = Counter()
    for week, created_at, tier, region, priority, status, first_response, resolved_at in ticket_rows:
        key = (week, tier, region)
        observed[key] += 1
        resolution_hours, response_hours = sla_hours[tier]
        created = _timestamp(created_at)
        if priority == 1 and status == "resolved" and resolved_at is not None:
            resolution[key][1] += 1
            elapsed = (_timestamp(resolved_at) - created).total_seconds()
            if elapsed > resolution_hours * 3600:
                resolution[key][0] += 1
        if first_response is not None:
            response[key][1] += 1
            elapsed = (_timestamp(first_response) - created).total_seconds()
            if elapsed > response_hours * 3600:
                response[key][0] += 1
            if status == "open":
                response[key][2] += 1

    expected_resolution = {
        (week, tier, region): (misses, eligible, misses / eligible if eligible else None)
        for (week, tier, region), (misses, eligible) in resolution.items()
    }
    assert len(resolution_view) == 26 * 3 * 3 - 1
    for week, tier, region, eligible, misses, rate in resolution_view:
        expected_misses, expected_eligible, expected_rate = expected_resolution[(week, tier, region)]
        assert (misses, eligible) == (expected_misses, expected_eligible)
        assert rate == pytest.approx(expected_rate)

    expected_response = {
        key: (misses, clocks, open_clocks, misses / clocks if clocks else None)
        for key, (misses, clocks, open_clocks) in response.items()
    }
    assert len(response_view) == len(resolution_view)
    for week, tier, region, clocks, misses, open_clocks, rate in response_view:
        expected_misses, expected_clocks, expected_open, expected_rate = expected_response[
            (week, tier, region)
        ]
        assert (misses, clocks, open_clocks) == (
            expected_misses, expected_clocks, expected_open
        )
        assert rate == pytest.approx(expected_rate)

    expected_coverage = {
        (week, tier, region): (count, state)
        for week, tier, region, count, state in ledger_rows
    }
    assert len(coverage_view) == WEEK_COUNT * len(TIERS) * len(REGIONS)
    week_starts = sorted({row[0] for row in ledger_rows})
    assert len(week_starts) == WEEK_COUNT
    assert date.fromisoformat(week_starts[0]) == FIRST_WEEK
    assert all(
        (date.fromisoformat(right) - date.fromisoformat(left)).days == 7
        for left, right in zip(week_starts, week_starts[1:], strict=False)
    )
    assert {row[1] for row in ledger_rows} == {tier for tier, _resolution, _response in TIERS}
    assert {row[2] for row in ledger_rows} == set(REGIONS)
    for week, tier, region, expected_count, observed_count, missing_count, ledger_state, state in coverage_view:
        raw_expected, expected_state = expected_coverage[(week, tier, region)]
        raw_observed = observed[(week, tier, region)]
        computed_state = (
            "missing" if raw_observed == 0 else
            "partial" if raw_observed < raw_expected else
            expected_state
        )
        assert expected_count == raw_expected
        assert observed_count == raw_observed
        assert missing_count == raw_expected - raw_observed
        assert state == computed_state == ledger_state

    assert sum(row[4] for row in coverage_view) <= MAX_TICKETS
    missing = [row for row in coverage_view if row[-1] == "missing"]
    recovered = [row for row in coverage_view if row[-2] == "recovered"]
    assert len(missing) == 1
    assert missing[0][1:3] == ("business", "central")
    assert missing[0][4] == 0 and missing[0][5] > 0
    assert len(recovered) == 1
    assert recovered[0][1:3] == ("business", "central")
    assert recovered[0][4] == recovered[0][3] and recovered[0][-1] == "recovered"

    # The unweighted tier mean is intentionally different from the pooled rate.
    first_week = FIRST_WEEK.isoformat()
    tier_totals = defaultdict(lambda: [0, 0])
    for (week, tier, _region), (misses, eligible) in resolution.items():
        if week == first_week:
            tier_totals[tier][0] += misses
            tier_totals[tier][1] += eligible
    tier_rates = [misses / eligible for misses, eligible in tier_totals.values()]
    pooled_rate = (
        sum(misses for misses, _eligible in tier_totals.values())
        / sum(eligible for _misses, eligible in tier_totals.values())
    )
    unweighted_tier_rate = sum(tier_rates) / len(tier_rates)
    assert abs(pooled_rate - unweighted_tier_rate) >= 0.015

    resolution_population = sum(eligible for _misses, eligible in resolution.values())
    response_population = sum(clocks for _misses, clocks, _open in response.values())
    open_response_population = sum(open_clocks for _misses, _clocks, open_clocks in response.values())
    assert response_population > resolution_population
    assert open_response_population > 0


def test_same_seed_reproduces_raw_database_contents_and_other_seed_varies(tmp_path):
    first = generate_database(tmp_path / "first.sqlite3", seed=912)
    repeat = generate_database(tmp_path / "repeat.sqlite3", seed=912)
    other = generate_database(tmp_path / "other.sqlite3", seed=913)
    assert _database_contents(first) == _database_contents(repeat)
    assert _database_contents(first)[1] != _database_contents(other)[1]


def test_generation_refuses_existing_files_and_symlinks(tmp_path):
    existing = tmp_path / "existing.sqlite3"
    existing.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        generate_database(existing)
    assert existing.read_bytes() == b"keep me"

    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"symlink target")
    link = tmp_path / "linked.sqlite3"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        generate_database(link)
    assert link.is_symlink()
    assert target.read_bytes() == b"symlink target"


@pytest.mark.parametrize("seed", [20261016, 4815])
def test_snapshot_times_and_open_backlog_are_independently_recomputable(tmp_path, seed):
    database = generate_database(tmp_path / "snapshot.sqlite3", seed=seed)
    with sqlite3.connect(database) as connection:
        cutoff_text = connection.execute("SELECT as_of_utc FROM source_snapshot").fetchone()[0]
        cutoff = _timestamp(cutoff_text)
        clocks = dict((tier, (resolution, response)) for tier, resolution, response in connection.execute(
            "SELECT * FROM support_tier_sla"
        ))
        ingested = dict(((week, tier, region), _timestamp(at)) for week, tier, region, at in connection.execute(
            "SELECT week_start_utc, support_tier, region, ingested_at_utc "
            "FROM source_ingestion_ledger WHERE ingested_at_utc IS NOT NULL"
        ))
        tickets = connection.execute("SELECT * FROM tickets").fetchall()
        actual = connection.execute("SELECT * FROM weekly_open_backlog").fetchall()
    assert cutoff == max(ingested.values())
    expected = defaultdict(lambda: [0, 0, 0, 0])
    cross_week_resolutions = 0
    for _id, week, created_text, tier, region, priority, status, response, resolution in tickets:
        created = _timestamp(created_text)
        assert 0 <= (created.date() - date.fromisoformat(week)).days < 7
        interval_time = ingested[(week, tier, region)]
        for event in (created_text, response, resolution):
            if event is not None:
                assert _timestamp(event) < interval_time <= cutoff
        if resolution is not None:
            cross_week_resolutions += (_timestamp(resolution).date() - date.fromisoformat(week)).days >= 7
        if status == "open":
            values = expected[(week, tier, region)]
            age_hours = (cutoff - created).total_seconds() / 3600
            values[0] += priority == 1
            values[1] += priority == 1 and age_hours > clocks[tier][0]
            values[2] += response is None
            values[3] += response is None and age_hours > clocks[tier][1]
    assert cross_week_resolutions > 0
    assert len(actual) == len(expected)
    for week, tier, region, as_of, *counts in actual:
        assert as_of == cutoff_text
        assert counts == expected[(week, tier, region)]
        assert counts[0] >= counts[1] and counts[2] >= counts[3]

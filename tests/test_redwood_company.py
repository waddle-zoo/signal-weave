"""Raw source fitness; counts here are not independent enterprise trials."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from evaluations import redwood_company as company
from signalweave.mcp_source import _Manifest
from signalweave.models import ResourceSnapshot


@pytest.mark.parametrize("index", range(3))
def test_rollup_reconciles_raw_scoped_records_and_mature_dates(tmp_path, index):
    path = company.create_snapshot(tmp_path / "snapshot.sqlite3", index)
    result = company.query(path, company.ROLLUP_SQL)
    rows = {row["warehouse"]: row for row in (dict(zip(result["columns"], r, strict=True)) for r in result["rows"])}
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        clock = dict(db.execute("SELECT * FROM source_snapshot").fetchone())
        shipments = list(db.execute("SELECT * FROM shipments"))
        assert db.execute("SELECT count(*) FROM shipments WHERE paid=0 OR cancelled=1 OR delivered_at_utc IS NULL").fetchone()[0] > 0
    assert datetime.fromisoformat(clock["as_of_utc"]) - datetime.fromisoformat(clock["current_end"]) >= timedelta(days=7)
    assert all(s["recorded_at_utc"] <= clock["as_of_utc"] for s in shipments)
    for name, result_row in rows.items():
        for period, start, end in (("current", clock["current_start"], clock["current_end"]),
                                   ("baseline", clock["baseline_start"], clock["current_start"])):
            eligible = [s for s in shipments if s["paid"] and not s["cancelled"] and s["delivered_at_utc"] is not None
                        and start <= s["promised_at_utc"] < end and (name == "ALL" or s["warehouse"] == name)]
            late = sum(s["delivered_at_utc"] > s["promised_at_utc"] for s in eligible)
            assert result_row[period+"_eligible"] == len(eligible)
            assert result_row[period+"_late"] == late
            assert result_row[period+"_late_pct"] == pytest.approx(100 * late / len(eligible))
        assert result_row["delta_pp"] == pytest.approx(result_row["current_late_pct"]-result_row["baseline_late_pct"])
    exported = ResourceSnapshot.model_validate(company.export(path, company.ROLLUP_SQL, "metric:test", "cohorts", "Test"))
    assert exported.adapter == company.ADAPTER
    assert exported.source_captured_at.isoformat().replace("+00:00", "Z") == company.CUTOFFS[index]
    assert exported.metadata["retrieval"]["identifier"] == company.SOURCE_ID
    assert not any("harbor" in ref for row in exported.evidence for ref in row.provenance)


def test_manifest_missingness_and_previous_case_followthrough_are_visible(tmp_path):
    path = company.create_snapshot(tmp_path / "source.sqlite3", 2)
    definition = next(row for row in company.saved_queries() if row["resource"] == "context:cohort-coverage")
    coverage = company.query(path, definition["sql"])
    rows = {row[0]: dict(zip(coverage["columns"], row, strict=True)) for row in coverage["rows"]}
    assert rows["current"]["unknown_manifest_partitions"] == 1
    assert rows["current"]["expected_eligible_shipments"] is None
    assert rows["baseline"]["expected_eligible_shipments"] == 1656
    cases = company.query(path, "SELECT status,count(*) n FROM delivery_cases GROUP BY status")
    assert dict(cases["rows"]) == {"closed": 60, "open": 30}
    assert not cases["truncated"]


def test_native_catalog_is_the_same_fixed_sql_available_to_baseline(tmp_path):
    manifest = company.manifest(tmp_path / "db.sqlite3", Path("/repo/python"), tmp_path)
    _Manifest.model_validate(manifest)
    entries = manifest["connections"][0]["resources"]
    assert {row["arguments"]["sql"] for row in entries} == {row["sql"] for row in company.saved_queries()}
    assert all("outcome" not in row["arguments"] for row in entries)


def test_source_rejects_mutation_and_silent_overwrite(tmp_path):
    path = company.create_snapshot(tmp_path / "db.sqlite3", 0)
    with pytest.raises(ValueError, match="read-only"):
        company.query(path, "DELETE FROM shipments")
    with pytest.raises(FileExistsError):
        company.create_snapshot(path, 0)

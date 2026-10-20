"""Original source rows become files; this is not a new business-agent trial."""

import json
from pathlib import Path

from evaluations import redwood_company
from examples.harbor_help.query_artifacts import write_query_artifacts


def test_fulfillment_exports_keep_unknown_expectations_and_distinct_denominators(tmp_path):
    database = redwood_company.create_snapshot(tmp_path / "source.sqlite3", 2)
    coverage_sql = next(row[2] for row in redwood_company.QUERY_DEFINITIONS if row[0] == "context:cohort-coverage")
    queries = [coverage_sql, "SELECT warehouse,COUNT(*) AS eligible FROM shipments "
               "WHERE paid=1 AND cancelled=0 AND delivered_at_utc IS NOT NULL "
               "AND promised_at_utc>='2026-05-25T00:00:00Z' AND promised_at_utc<'2026-06-01T00:00:00Z' "
               "AND warehouse IN ('WH-05','WH-06') GROUP BY warehouse ORDER BY warehouse",
               "SELECT shipment_id,status,last_updated_at_utc FROM delivery_cases WHERE status='open' ORDER BY shipment_id"]
    originals = []
    for sql in queries:
        original = redwood_company.query(database, sql, 1000)
        exported = write_query_artifacts(original, tmp_path / "exports")
        recovered = json.loads(Path(exported["paths"]["json"]).read_text())
        assert recovered == original
        assert recovered["source"]["identifier"] == redwood_company.SOURCE_ID
        assert recovered["source"]["as_of_utc"] == redwood_company.CUTOFFS[2]
        assert all("redwood_fulfillment_as_known:" in ref for ref in recovered["assets_read"])
        originals.append(recovered)
    coverage = {r[0]: dict(zip(originals[0]["columns"], r, strict=True)) for r in originals[0]["rows"]}
    assert coverage["current"]["expected_eligible_shipments"] is None
    assert coverage["current"]["known_manifest_received_shipments"] == 1452
    assert dict(originals[1]["rows"]) == {"WH-05": 120, "WH-06": 132}
    assert len(originals[2]["rows"]) == 30

"""Consistency of the retained study record, not new business trials."""

import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "evaluations" / "data"


def test_closed_workflow_record_matches_manifest_and_usage_denominators():
    record = json.loads((DATA / "raw-northstar-workflow-v2-summary.json").read_text())
    manifest = json.loads((DATA / "raw-northstar-workflow-v2.json").read_text())
    assert manifest["execution_status"] == "closed"
    assert record["protocol"] == manifest["protocol"]
    for field, recorded in (("method_commit", "method_commit"), ("report_sha256", "raw_report_sha256"),
                            ("trace_sha256", "raw_trace_sha256")):
        assert record[recorded] == manifest["closed_attempt"][field]
    phases = record["phases"]
    assert len(phases) == record["result"]["invocations"] == 6
    assert {(phase["stage"], phase["arm"]) for phase in phases} == {
        (stage, arm) for stage in ("author", "review", "report") for arm in ("baseline", "signalweave")
    }
    for field in ("input_tokens", "cached_input_tokens", "uncached_input_tokens", "output_tokens"):
        assert sum(phase["frontier_usage"][field] for phase in phases) == record["result"]["usage"][field]
    for phase in phases:
        usage = phase["frontier_usage"]
        assert usage["input_tokens"] == usage["cached_input_tokens"] + usage["uncached_input_tokens"]
    assert record["native_decision"]["analyses"] == []
    assert record["workflow_acceptance"]["status"] == "unassessed"
    assert record["native_approval"]["status"] == "approved"
    assert record["native_approval"]["onboarding_warnings"]
    assert record["native_run_receipt"]["delivery_enabled"] is False


def test_public_source_excerpt_independently_reconstructs_reported_contribution():
    record = json.loads((DATA / "raw-northstar-workflow-v2-summary.json").read_text())
    source = record["recorded_source_excerpt"]
    totals = defaultdict(Decimal)
    online = {}
    seen = set()
    for row in source["selected_raw_monthly_rows"]:
        month = datetime.fromtimestamp(row["order_date"] / 1000, UTC).strftime("%Y-%m")
        key = (month, row["channel"])
        assert key not in seen
        seen.add(key)
        amount = Decimal(str(row["SUM(net_sales)"]))
        totals[month] += amount
        if row["channel"] == "Online":
            online[month] = amount
    assert len(seen) == 12
    assert totals["2026-07"] == Decimal("2158994.74")
    assert totals["2026-08"] == Decimal("2292267.50")
    change = totals["2026-08"] - totals["2026-07"]
    online_change = online["2026-08"] - online["2026-07"]
    assert online_change == Decimal("61949.94")
    assert (change / totals["2026-07"] * 100).quantize(Decimal("0.01")) == Decimal("6.17")
    assert (online_change / change * 100).quantize(Decimal("0.01")) == Decimal("46.48")
    cutoff = source["daily_date_ranges"]["order_date"]["raw_max"]
    assert datetime.fromtimestamp(cutoff / 1000, UTC).date().isoformat() == "2026-09-19"
    assert source["query_scope"]["warehouse_completeness"] == "unknown"

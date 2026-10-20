"""Public audit excerpt integrity, not a new agent/company trial."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "evaluations/data/steward-expert-followup-summary.json"


def capsule():
    return json.loads(PATH.read_text())


def test_public_rows_reconcile_to_comparison_and_supported_accounting():
    data = capsule()
    source = next(s for s in data["sources"] if s["analytical_comparisons"])
    values, comparison = source["payload_values"][0], source["analytical_comparisons"][0]
    rows = values["rows"]
    baseline = {r["channel"]: r["baseline_gross"] - r["baseline_refunds"] for r in rows}
    current = {r["channel"]: r["current_gross"] - r["current_refunds"] for r in rows}
    assert baseline == {"web": 7000, "shop": 3000} and current == {"web": 4000, "shop": 3000}
    assert sum(baseline.values()) == comparison["baseline_total"]["value"] == 10000
    assert sum(current.values()) == comparison["current_total"]["value"] == 7000
    assert 100 * (sum(current.values()) - sum(baseline.values())) / sum(baseline.values()) == -30
    assert 100 * (current["web"] - baseline["web"]) / baseline["web"] == pytest.approx(-42.857142857)
    for segment in comparison["segments"]:
        key = segment["segment"]
        assert segment["baseline"]["value"] == baseline[key] and segment["current"]["value"] == current[key]
    start, middle, end = [datetime.fromisoformat(comparison[k].replace("Z", "+00:00"))
                          for k in ("baseline_start", "baseline_end", "current_end")]
    assert comparison["current_start"] == comparison["baseline_end"]
    assert middle - start == end - middle == timedelta(days=7)
    assert comparison["coverage"] == "complete" and comparison["comparable"] is True
    assert values["refund_timing"] == "posting_week"


def test_exact_reports_and_both_negative_findings_remain_visible():
    data = capsule()
    known = {s["ref"] for s in data["sources"]}
    reviews = {r["case_id"]: r for r in data["review"]["cases"]}
    for arm, entry in data["reports"].items():
        report = entry["recorded_report"]
        caseid = "case-" + hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:12]
        assert caseid == entry["case_id"]
        assert report["outcome"] == "notify" and report["recipients"] == [data["owner_context"]["destinations"][0]["key"]]
        citations = set(re.findall(r"company_mcp\|resource-[a-f0-9]+", report["summary"]))
        if arm == "signalweave":
            assert citations - known == {"company_mcp|resource-949a4c0c0c44fb188d1658"}
            assert reviews[caseid]["usable"] and reviews[caseid]["minor_findings"]
            assert data["review"]["preference"]["result"] == caseid
        else:
            assert not citations - known
            assert "routine report audience" in report["summary"]
            assert not reviews[caseid]["usable"] and reviews[caseid]["material_findings"]


def test_observed_accounting_and_limitations_not_turned_into_a_win():
    data = capsule()
    work = data["observed_work"]
    baseline, treatment = work["baseline"], work["signalweave"]
    assert baseline["source_reads"] == treatment["source_reads"] == 2
    assert treatment["agent_seconds"] > baseline["agent_seconds"]
    assert treatment["uncached_input_tokens"] > baseline["uncached_input_tokens"]
    assert sum(x["input_tokens"] for x in (baseline, treatment)) + 545504 == work["cumulative_including_original_v4"]["input_tokens"]
    assert work["agent_calls_total"] == 6 and work["jev_attempts_total"] == 1
    assert treatment["jev_input_tokens"] == 7014 and treatment["jev_output_tokens"] == 109
    native = data["native_policy_result"]
    assert native["evaluator"] == "jev-latest" and native["outcome"] == "notify"
    assert native["receipt"]["card_version"] == 2 and native["receipt"]["delivery_enabled"] is False
    assert "not calibrated" in native["scope"]
    assert "not autonomous onboarding" in data["scope"].lower()
    assert "not individually logged" in data["setup"]["audit_limit"]
    assert "cost/speed win" in data["scope"]
    assert "unknown is not zero" in work["cost_limits"]
    assert "persistence-check/trace.jsonl" in data["local_artifact_sha256"]
    assert all(re.fullmatch("[a-f0-9]{64}", value) for value in data["local_artifact_sha256"].values())

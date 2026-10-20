"""Integrity of a public audit excerpt, not new product accuracy cases."""

import json
import re
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

CAPSULE = Path(__file__).resolve().parents[1] / "evaluations/data/evidence-first-layout-diagnostic.json"


def test_public_capsule_supports_independent_arithmetic_and_historical_windows():
    data = json.loads(CAPSULE.read_text())
    assert data["kind"] == "synthetic_cached_readout_audit"
    comparison = data["source_comparison"]
    baseline, current = comparison["baseline_total"], comparison["current_total"]
    assert Fraction(str(baseline["numerator"])) / Fraction(str(baseline["denominator"])) == Fraction(9, 10)
    assert Fraction(str(current["numerator"])) / Fraction(str(current["denominator"])) == Fraction(9, 10)
    assert Fraction(str(current["denominator"])) / Fraction(str(baseline["denominator"])) == 2
    parse = datetime.fromisoformat
    assert parse(comparison["current_end"]) - parse(comparison["current_start"]) == timedelta(days=7)
    assert comparison["baseline_end"] == comparison["current_start"]
    assert data["period"]["captured_at"] != data["period"]["as_of"]
    assert data["limitations"] and "not raw trace" in data["scope"]


def test_public_capsule_preserves_recording_and_review_disagreement_not_a_consensus_pass():
    data = json.loads(CAPSULE.read_text())
    readouts = {case["case_id"]: case for case in data["readouts"]}
    assert len(readouts) == 2 and {case["layout"] for case in readouts.values()} == {"candidate", "current"}
    for case in readouts.values():
        assert set(case["recorded_report"]) == {"outcome", "recipients", "summary"}
        assert case["recording_result"] == {"recorded": True, "delivery_enabled": False}
    for review in data["reviews"]:
        assert re.fullmatch("[a-f0-9]{64}", review["original_sha256"])
        assert {case["case_id"] for case in review["cases"]} == readouts.keys()
        for case in review["cases"]:
            assert len(case["gates"]) == 7
            assert case["overall_pass"] == all(gate["status"] == "pass" for gate in case["gates"].values())
    # These are the stored historical opinions, not expected model behavior.
    assert all(case["overall_pass"] for case in data["reviews"][0]["cases"])
    assert not any(case["overall_pass"] for case in data["reviews"][1]["cases"])


def test_public_capsule_contains_only_synthetic_review_material_not_private_runtime_state():
    text = CAPSULE.read_text()
    data = json.loads(text)
    assert not re.search(r"/Users/|/private/|Bearer\s|TYPESAFE_API_KEY|OPENAI_API_KEY", text)
    assert len(text.encode()) < 24_000
    assert re.fullmatch("[a-f0-9]{40}", data["provenance"]["source_commit"])
    assert data["observed_audit_counts"] == {"source_reads": 0, "jev_requests": 0, "native_evaluations": 0}
    assert data["reporter_usage"]["responses"] == 2
    assert all(re.fullmatch("[a-f0-9]{64}", value) for key, value in data["provenance"].items() if key.endswith("sha256"))

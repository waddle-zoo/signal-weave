"""Reconcile retained live evidence offline; do not silently rewrite its scores."""

import copy
import gzip
import hashlib
import json
from pathlib import Path

from evaluations.first_report_trial import native_submission, score
from signalweave.models import InsightCard, InsightResult, ResourceSnapshot
from signalweave.reporting import build_investigation_report

ROOT = Path(__file__).resolve().parents[1] / "docs/evidence"


def recorded(name):
    root = ROOT / name
    manifest = json.loads((root / "manifest.json").read_text())
    report = json.loads((root / "report.json").read_text())
    events = [json.loads(line) for line in gzip.decompress(
        (root / "events.jsonl.gz").read_bytes()).decode().splitlines()]
    for filename, entry in json.loads((root / "checksums.json").read_text()).items():
        data = (root / filename).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        raw = gzip.decompress(data) if filename.endswith(".gz") else data
        assert hashlib.sha256(raw).hexdigest() == entry["uncompressed_sha256"]
    return manifest, report, events


def test_first_attempt_retains_auth_failure_and_disputed_first_report():
    _, report, events = recorded("first-report-live-01")
    assert report["summary"]["approved_companies"] == 0
    assert report["jev_attempts"] == 20
    assert sum(e["kind"] == "api.request" and e.get("provider") == "openai" for e in events) == 4
    assert sum("approval_error" in row for row in report["results"]) == 3
    assert sum(row.get("error") == "first_report_incomplete" for row in report["results"]) == 1


def test_frozen_paired_trial_preserves_strict_scores_and_replay():
    manifest, report, events = recorded("first-report-live-02")
    assert manifest["freeze"]["git_revision"].startswith("cee8d0d")
    assert report["summary"]["approved_companies"] == 4
    assert report["summary"]["native_passed"] == 7
    assert report["summary"]["baseline_passed"] == 5
    assert report["cumulative_jev_attempts"] == 46
    assert report["cumulative_luna_episodes"] == 13
    assert sum(e["kind"] == "api.request" and e.get("provider") == "jev" for e in events) == 26
    assert sum(e["kind"] == "api.request" and e.get("provider") == "openai" for e in events) == 9
    runs = [run for company in report["results"] for run in company["runs"]]
    assert len(runs) == 8
    assert all(r["replay_exact"] and r["split"] == "holdout" for r in runs)
    assert not any(e["kind"] == "api.error" for e in events)


def test_known_oracle_error_is_preserved_not_disguised_as_a_model_failure():
    manifest, report, _ = recorded("first-report-live-02")
    company = next(c for c in manifest["companies"] if c["id"] == "harbor-help")
    assert "route to the Data Steward" in company["owner_policy"]
    period = next(p for p in company["periods"] if p["id"] == "p03")
    assert period["oracle"]["recipients"] == []  # original faulty oracle remains visible
    row = next(r for r in report["results"] if r["company"] == "harbor-help")
    run = next(r for r in row["runs"] if r["period"] == "p03")
    assert run["native_score"]["errors"] == ["recipients"]
    assert run["baseline_score"]["errors"] == ["recipients"]
    assert run["baseline"]["recipients"] == ["support-data-steward"]
    routes = run["native"]["report"]["intended_routes_not_delivered"]
    assert [r["destination"] for r in routes] == ["agent://support-data-steward"]


def test_post_hoc_counts_are_reproducible_and_separate_from_primary():
    manifest, report, _ = recorded("first-report-live-02")
    counts = {"native": 0, "baseline": 0, "baseline_alias": 0}
    for row in report["results"]:
        company = next(c for c in manifest["companies"] if c["id"] == row["company"])
        for run in row["runs"]:
            oracle = copy.deepcopy(next(p["oracle"] for p in company["periods"] if p["id"] == run["period"]))
            if row["company"] == "harbor-help" and run["period"] == "p03":
                oracle["recipients"] = ["support-data-steward"]
            counts["native"] += score(native_submission(run["native"], company["destinations"]), oracle)["passed"]
            counts["baseline"] += score(run["baseline"], oracle)["passed"]
            baseline = copy.deepcopy(run["baseline"])
            if baseline["outcome"] == "no_action":
                baseline["outcome"] = "ignore"
            counts["baseline_alias"] += score(baseline, oracle)["passed"]
    assert counts == {"native": 8, "baseline": 6, "baseline_alias": 7}
    adjudication = json.loads((ROOT / "first-report-live-02/adjudication.json").read_text())
    assert adjudication["frozen_primary"] == {"native_passed": 7, "baseline_passed": 5, "paired_periods": 8}
    assert not adjudication["issues"][2]["supports_unqualified_native_accuracy_advantage"]


def test_current_report_checks_preserve_archived_live_measurements():
    _, report, _ = recorded("first-report-live-02")
    checked = 0
    for row in report["results"]:
        for run in row["runs"]:
            native = run["native"]
            rebuilt = build_investigation_report(
                InsightCard.model_validate(native["card"]),
                InsightResult.model_validate(native["result"]),
                [ResourceSnapshot.model_validate(r) for r in native["resources"]],
            )
            assert rebuilt.status == native["report"]["status"]
            assert [c.model_dump(mode="json") for c in rebuilt.numeric_claims] == native["report"]["numeric_claims"]
            assert [r.model_dump(mode="json") for r in rebuilt.intended_routes_not_delivered] == native["report"]["intended_routes_not_delivered"]
            checked += 1
    assert checked == 8  # Offline report validation, not eight additional Jev runs.

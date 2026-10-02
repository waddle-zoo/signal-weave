"""Audit retained live evidence without network calls or silently replacing failures."""

import gzip
import hashlib
import json
from pathlib import Path

from evaluations.policy_composition_trial import Plan, compose, summary

ROOT = Path(__file__).parents[1] / "docs/evidence"


def read(folder, file):
    return json.loads((ROOT / folder / file).read_text())


def events(folder):
    with gzip.open(ROOT / folder / "events.jsonl.gz", "rt") as stream:
        return [json.loads(line) for line in stream]


def test_retained_ablation_never_becomes_a_repaired_benchmark():
    report = read("judgment-input-ablation-live-02", "report.json")
    assert report["attempts"] == len(report["results"]) == 18
    assert report["summary"] == {
        "original": {"passed": 3, "intended": 6},
        "deduplicated": {"passed": 4, "intended": 6},
        "without_plan": {"passed": 3, "intended": 6}}
    failures = {"northstar-cart:p07", "redwood-fulfillment:p08"}
    assert all(not row["passed"] for row in report["results"] if row["id"] in failures)


def test_failed_first_pass_and_transfer_denominators_are_separate():
    checksums = json.loads((ROOT / "policy-composition-checksums.json").read_text())
    for filename, digest in checksums["files"].items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest
    for folder, expected, episodes in (
        ("policy-composition-live-02", {"baseline": 11, "composed": 9, "broad": 11}, 9),
        ("policy-composition-transfer-live-01", {"baseline": 12, "composed": 8, "broad": 12}, 6),
    ):
        report = read(folder, "report.json")
        manifest = read(folder, "manifest.json")
        assert summary(report["results"], manifest["cases"]) == report["summary"]
        assert {arm: values["correct"] for arm, values in report["summary"].items()} == expected
        assert all(value["intended"] == value["submitted"] == 12 for value in report["summary"].values())
        assert report["jev_attempts"] == 12
        assert report["luna_episodes"] == episodes
        assert all(row["status"] == "complete" and not row["foreign_tools"] for row in report["episodes"])


def test_posthoc_ungated_counterfactual_localizes_but_does_not_repair_live_failures():
    folder = "policy-composition-transfer-live-01"
    report = read(folder, "report.json")
    manifest = read(folder, "manifest.json")
    assert manifest["support_floor"] == .70
    truth = {case["id"]: case["expected"]["outcome"] for case in manifest["cases"]}
    mismatches = []
    for company in report["results"]:
        if company["arm"] != "composed":
            continue
        for run in company["runs"]:
            workflow = run["workflow"]
            answers = dict(workflow["numeric_checks"])
            for key, response in workflow["response"]["answers"].items():
                if key != "overall_outcome":
                    answers[key] = response["choice"]
            # Counterfactual, not a safe policy or a new model call.
            ungated = compose(Plan.model_validate(report["plans"][company["company"]]), answers)
            assert ungated == truth[run["id"]]
            assert workflow["broad_outcome"] == truth[run["id"]]
            if run["outcome"] != truth[run["id"]]:
                mismatches.append(run["id"])
                assert any(answers[key] != value for key, value in workflow["answers"].items())
    assert len(mismatches) == 4
    assert report["summary"]["composed"]["correct"] == 8


def test_labels_never_enter_model_inputs_and_calls_match_accounting():
    for folder in ("policy-composition-live-02", "policy-composition-transfer-live-01"):
        journal = events(folder)
        requests = [e for e in journal if e["kind"] == "api.request" and e.get("provider") == "jev"]
        responses = [e for e in journal if e["kind"] == "api.response" and e.get("provider") == "jev"]
        assert len(requests) == len(responses) == 12
        assert not [e for e in journal if e["kind"] == "api.error"]
        for event in requests:
            state = event["state"]
            assert set(state) == {"policy", "evidence", "compiled_plan", "numeric_checks"}
            assert set(state["evidence"]) == {"id", "facts", "measurements"}
            assert state["evidence"]["id"].startswith("period-")
            assert set(state["numeric_checks"]) == {
                c["id"] for c in state["compiled_plan"]["checks"] if c["kind"] == "numeric"}
        manifest = read(folder, "manifest.json")
        private_ids = {case["id"] for case in manifest["cases"]}
        for event in journal:
            if event["kind"] == "api.request" and event.get("provider") == "openai":
                assert not any(case_id in event["prompt"] for case_id in private_ids)


def test_infrastructure_failures_remain_visible_but_are_not_model_scores():
    assert read("judgment-input-ablation-dns-failure", "report.json")["attempts"] == 18
    report = read("policy-composition-startup-failure", "report.json")
    assert report["jev_attempts"] == 0 and report["luna_episodes"] == 3
    assert all(row["status"] == "failed" for row in report["episodes"])

"""Frozen paired evidence remains a failure even after subsequent development."""

import json
from collections import Counter

from evaluations.business_outcome_trial import public_company, review_packet, summarize
from evaluations.first_report_trial import score
from tests.test_recorded_first_report import ROOT, recorded


def test_frozen_business_trial_retains_all_attempts_and_strict_losses():
    manifest, report, events = recorded("business-outcomes-live-01")
    assert manifest["freeze"]["git_revision"].startswith("7030068")
    assert manifest["freeze"]["git_status"] == ""
    counts = Counter(e.get("provider") for e in events if e["kind"] == "api.request")
    assert counts == {"jev": 12, "openai": 6}
    assert report["jev_attempts"] == 12 and report["luna_episodes"] == 6
    assert not report["unknown_usage_events"]
    assert not report["structured_gate_passed"]
    assert report["summary"]["baseline"]["strict_passed"] == 12
    assert report["summary"]["signalweave"]["strict_passed"] == 10
    assert report["summary"]["signalweave"]["missed_notification_periods"] == 2
    assert all(row["episode"]["status"] == "complete" for row in report["results"])
    assert all(run["replay_exact_no_calls"] for row in report["results"]
               if row["arm"] == "signalweave" for run in row["runs"])


def test_frozen_scores_and_review_mask_reconcile_with_independent_expectations():
    manifest, report, _ = recorded("business-outcomes-live-01")
    path = ROOT / "business-outcomes-live-01"
    expected = json.loads((path / "expected.json").read_text())
    companies = manifest["companies"]
    for company in companies:
        assert company == public_company(company)
        for period in company["periods"]:
            period["oracle"] = expected[company["id"]][period["id"]]
    for row in report["results"]:
        for run in row["runs"]:
            assert score(run["submission"], expected[row["company"]][run["period"]]) == run["score"]
    assert summarize(report["results"], companies) == report["summary"]
    packet, key = review_packet(report["results"], companies)
    assert packet == json.loads((path / "review-input.json").read_text())
    assert key == json.loads((path / "review-key.json").read_text())
    review = json.loads((path / "prose-review.json").read_text())
    usable, wins = Counter(), Counter()
    for case in review["case_findings"]:
        for label in ("A", "B"):
            if case["candidate_" + label]["usable"] == "yes":
                usable[key[case["case_id"]][label]] += 1
        choice = case["practical_usefulness"]
        wins["tie" if choice == "tie" else key[case["case_id"]][choice]] += 1
    assert usable == {"baseline": 12, "signalweave": 10}
    assert wins == {"baseline": 3, "signalweave": 1, "tie": 8}


def test_separate_semantic_probe_retains_remaining_failure_and_budget():
    manifest, report, events = recorded("business-outcomes-probe-live-01")
    assert manifest["freeze"]["git_revision"].startswith("dc619d7")
    assert manifest["freeze"]["git_status"] == ""
    assert report["passed"] == 5 and report["intended"] == 6
    assert report["jev_attempts"] == 6 and report["luna_episodes"] == 0
    assert not report["primary_scores_replaced"]
    assert Counter(e.get("provider") for e in events if e["kind"] == "api.request") == {"jev": 6}
    remaining = [r for r in report["results"] if not r["score"]["passed"]]
    assert [(r["company"], r["period"]) for r in remaining] == [("northstar-cart", "p07")]
    result = remaining[0]["native"]["result"]
    assert result["outcome"] == "investigate"
    assert result["probabilities"]["notify"] == .52

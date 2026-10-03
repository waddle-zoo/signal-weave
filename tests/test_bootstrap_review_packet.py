"""Offline review-export contracts using fabricated results, never model calls."""

import copy
import json
from datetime import datetime, timedelta

import pytest

from evaluations import bootstrap_review_packet as review
from evaluations.bootstrap_scenarios import (
    DEFAULT_SEED,
    build_scenarios,
    dataset_digest,
    public_episode,
)


@pytest.fixture
def review_report(monkeypatch):
    scenarios = build_scenarios(seed=DEFAULT_SEED, split="dev")
    scenario = scenarios[0]
    scenario["private"]["canary"] = "PRIVATE_ORACLE_CANARY"
    scenario["unexpected_top_level"] = "PRIVATE_ORACLE_CANARY"

    def fixtures(*, seed, split):
        assert (seed, split) == (DEFAULT_SEED, "dev")
        return scenarios

    monkeypatch.setattr(review, "build_scenarios", fixtures)
    rows = []
    for index, period in enumerate(scenario["public"]["periods"][:2]):
        refs = list(period["snapshots"])[:1]
        for arm in ("luna_bi", "luna_signalweave_jev"):
            submission = {
                "outcome": "investigate", "summary": f"Review current evidence for period {index}.",
                "evidence_refs": refs.copy(), "recipients": [], "numeric_claims": [], "claims": [],
            }
            if index == 1 and arm == "luna_signalweave_jev":
                submission = None
            rows.append({
                "scenario_id": scenario["scenario_id"], "period_id": period["period_id"],
                "arm": arm, "phase": "monitoring", "status": "complete" if index == 0 else "failed",
                "submission": submission, "inspected_refs": refs.copy(),
                "score": {"exact": False, "canary": "SCORER_RESULT_CANARY"},
                "raw_system_decision": {"canary": "TREATMENT_RESULT_CANARY"},
                "error": None if index == 0 else "EPISODE_ERROR_CANARY",
            })
    rows.insert(0, {
        "scenario_id": scenario["scenario_id"],
        "period_id": scenario["public"]["onboarding"]["period_id"],
        "arm": "luna_bi", "phase": "onboarding", "status": "complete",
        "submission": {"summary": "ONBOARDING_CANARY"}, "inspected_refs": [],
    })
    report = {
        "config": {"seed": DEFAULT_SEED, "split": "dev"}, "rows": rows,
        "status": "partial_or_failed", "summary": {"luna_bi": {}, "luna_signalweave_jev": {}},
        "usage": {}, "budget_censored": False, "comparative_eligible": False,
    }
    return report, scenario


def test_blind_packets_exclude_oracles_scores_and_arm_metadata(review_report):
    report, scenario = review_report
    cases, mapping, compact = review.packets(report)
    text = json.dumps(cases, allow_nan=False)
    for forbidden in (
        "PRIVATE_ORACLE_CANARY", "SCORER_RESULT_CANARY", "TREATMENT_RESULT_CANARY",
        "EPISODE_ERROR_CANARY", "ONBOARDING_CANARY", "luna_bi", "luna_signalweave_jev",
        '"private"', '"score"', '"arm"', '"condition"', '"required_evidence_refs"',
        '"required_numeric_facts"', '"numeric_facts"', '"raw_system_decision"',
    ):
        assert forbidden not in text
    for case in cases:
        assert set(case) == {"case_id", "business", "analysis", "inspected_refs", "execution_complete"}
        assert set(case["business"]) == {
            "company", "brief", "glossary", "owner_answers", "destinations", "catalog", "period",
            "numeric_vocabulary", "submission_contract",
        }
    assert {entry["arm"] for entry in mapping.values()} == {"luna_bi", "luna_signalweave_jev"}
    assert "SCORER_RESULT_CANARY" in json.dumps(compact)
    # Changing the oracle must not change any blinded review evidence.
    scenario["private"] = {"replacement": "OTHER_PRIVATE_ORACLE"}
    assert review.packets(report)[0] == cases


def test_explicit_fixtures_are_digest_checked_without_builtin_reconstruction(review_report, monkeypatch):
    report, scenario = review_report
    report["config"]["dataset_digest"] = dataset_digest([scenario])
    monkeypatch.setattr(review, "build_scenarios", lambda **kwargs: pytest.fail("must use supplied fixtures"))
    assert len(review.packets(report, fixtures_override=[scenario])[0]) == 4
    changed = copy.deepcopy(scenario)
    changed["public"]["brief"] += " changed"
    with pytest.raises(ValueError, match="Fixture digest"):
        review.packets(report, fixtures_override=[changed])


def test_completed_failed_and_missing_submissions_are_all_preserved(review_report):
    report, _ = review_report
    cases, mapping, compact = review.packets(report)
    rows = {(r["scenario_id"], r["period_id"], r["arm"]): r
            for r in report["rows"] if r["phase"] == "monitoring"}
    assert len(cases) == len(mapping) == len(rows) == 4
    assert sum(case["execution_complete"] for case in cases) == 2
    assert sum(case["analysis"] is None for case in cases) == 1
    for case in cases:
        identity = mapping[case["case_id"]]
        row = rows[tuple(identity[key] for key in ("scenario_id", "period_id", "arm"))]
        assert case["analysis"] == row["submission"]
        assert case["inspected_refs"] == row["inspected_refs"]
        assert case["execution_complete"] is (row["status"] == "complete")
    assert len(compact["cases"]) == len(report["rows"])
    for original, exported in zip(report["rows"], compact["cases"], strict=True):
        for key in ("phase", "status", "error", "submission", "score"):
            assert exported[key] == original.get(key)


def test_mapping_is_deterministic_and_paired_arms_receive_identical_public_evidence(review_report):
    report, scenario = review_report
    cases, mapping, compact = review.packets(report)
    assert review.packets(copy.deepcopy(report)) == (cases, mapping, compact)
    assert [case["case_id"] for case in cases] == [f"review-{index:03d}" for index in range(1, 5)]
    assert set(mapping) == {case["case_id"] for case in cases}
    by_period = {}
    for case in cases:
        identity = mapping[case["case_id"]]
        assert set(identity) == {"scenario_id", "period_id", "arm"}
        public = public_episode(scenario, identity["period_id"])
        assert case["business"] == {key: public[key] for key in case["business"]}
        by_period.setdefault(identity["period_id"], []).append(case["business"])
    assert len(by_period) == 2
    for pair in by_period.values():
        assert len(pair) == 2 and pair[0] == pair[1]


def test_export_does_not_mutate_report_or_fixture(review_report):
    report, scenario = review_report
    before_report, before_scenario = copy.deepcopy(report), copy.deepcopy(scenario)
    review.packets(report)
    assert report == before_report
    assert scenario == before_scenario


def test_export_rejects_changed_measured_fixtures():
    fixtures = build_scenarios(seed=DEFAULT_SEED, split="dev")[:1]
    report = {"config": {"seed": DEFAULT_SEED, "split": "dev", "selected_companies": 1,
                         "dataset_digest": "not-the-frozen-digest"}}
    with pytest.raises(ValueError, match="Fixture digest differs"):
        review.packets(report)
    report["config"]["dataset_digest"] = dataset_digest(fixtures)
    report.update(rows=[], status="complete", summary={}, usage={},
                  budget_censored=False, comparative_eligible=True)
    assert review.packets(report)[0] == []


def test_export_reconstructs_explicit_nonprefix_regression_subset():
    fixtures = build_scenarios(seed=20261002, split="holdout")[2:4]
    report = {
        "config": {"seed": 20261002, "split": "holdout", "selected_companies": 2,
                   "selected_scenario_ids": [s["scenario_id"] for s in fixtures],
                   "dataset_digest": dataset_digest(fixtures)},
        "rows": [{"scenario_id": s["scenario_id"], "period_id": s["public"]["periods"][0]["period_id"],
                  "phase": "monitoring", "arm": "luna_bi", "submission": None,
                  "inspected_refs": [], "status": "failed"} for s in fixtures],
        "status": "partial_or_failed", "summary": {}, "usage": {},
        "budget_censored": False, "comparative_eligible": False,
    }
    cases, mapping, _ = review.packets(report)
    assert {entry["scenario_id"] for entry in mapping.values()} == set(report["config"]["selected_scenario_ids"])
    assert {c["business"]["company"] for c in cases} == {s["public"]["company"] for s in fixtures}
    assert len(cases) == 2 and all(not c["execution_complete"] for c in cases)


def test_export_rebases_period_clock_without_changing_fixture(review_report):
    report, scenario = review_report
    original = copy.deepcopy(scenario)
    delta = timedelta(days=47, seconds=123)
    anchor = datetime.fromisoformat(scenario["public"]["onboarding"]["as_of"])
    report["config"]["clock_rebased_to"] = (anchor + delta).isoformat()
    cases, mapping, _ = review.packets(report)
    for case in cases:
        period = public_episode(scenario, mapping[case["case_id"]]["period_id"])["period"]
        assert case["business"]["period"] == review.shift_timestamps(period, delta)
    assert scenario == original

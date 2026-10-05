from pathlib import Path

import pytest

from evaluations.northstar_multistep_paired_review import _score as independent_score
from evaluations.northstar_multistep_paired_trial import build_cases, score_run
from evaluations.northstar_multistep_trial import _observation_coverage, load_trial_spec
from evaluations.northstar_growth_history_trial import _build_resources, _load_period_data
from evaluations.northstar_growth_history_trial import load_spec as load_history_spec
from evaluations.northstar_multistep_trial import _case_lookup


ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "evaluations" / "data" / "northstar-multistep-seed"


def test_multistep_fixture_requires_and_receives_channel_shape():
    trial = load_trial_spec(ROOT / "examples" / "northstar-multistep-trial.json")
    scenario = next(item for item in trial["scenarios"] if item["id"] == "corroborated-broad-decline")
    history = load_history_spec(ROOT / "examples" / "northstar-growth-historical-decisions.json")
    period = _load_period_data(SEED)
    case = _case_lookup(history)[(scenario["period_id"], scenario["base_case_id"])]

    coverage = _observation_coverage(scenario, _build_resources(period, case.replay_case))

    assert coverage == [{
        "source_key": "superset|dashboard:1",
        "subject_type": "channel",
        "available_count": 4,
        "minimum_count": 2,
        "passed": True,
    }]


def test_multistep_fixture_rejects_malformed_coverage_requirements(tmp_path):
    path = tmp_path / "trial.json"
    path.write_text(
        '{"schema_version": 1, "card": {"decision_guidance": "x", "follow_up_guidance": "y"}, '
        '"scenarios": [{"id": "s", "base_case_id": "x", "period_id": "p", '
        '"expected_initial": "ignore", "expected_final": "ignore", "diagnostic_facts": [], '
        '"coverage_requirements": [{"source_key": "s", "subject_type": "channel", "minimum_count": 0}]}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="minimum_count"):
        load_trial_spec(path)


def test_paired_harness_withholds_private_labels_and_facts_from_shared_input():
    cases = build_cases(seed_dir=SEED)

    assert cases
    for case in cases:
        serialized = str(case["shared_input"])
        assert "expected_initial" not in serialized
        assert "expected_final" not in serialized
        assert "required_final_evidence" not in serialized
        assert all(fact["fact_id"] not in serialized for fact in case["diagnostic_facts"])


def test_paired_harness_accepts_chart_level_provenance_for_required_sources():
    case = next(case for case in build_cases(seed_dir=SEED) if case["scenario"] == "ordinary-no-change")
    chart_by_source = {}
    for chart in case["shared_input"]["cached_charts"]:
        chart_by_source.setdefault(chart["source_ref"], chart["id"])
    evidence = [chart_by_source[ref] for ref in case["label"]["required_final_evidence"]]
    submission = {
        "stage": "initial",
        "outcome": case["label"]["expected_final"],
        "delivery": case["label"]["final_delivery"],
        "evidence_refs": evidence,
        "query_justified": False,
        "confidence": 0.9,
    }
    scored = score_run(
        case,
        {
            "arm": "baseline",
            "initial_submission": submission,
            "final_submission": submission,
            "events": [],
            "protocol_errors": [],
            "oracle_leaks": 0,
        },
    )

    assert scored["evidence_recall"] == 1.0
    assert scored["provenance_complete"] is True
    assert scored["final_exact"] is True


def test_paired_scorers_agree_on_authorized_source_level_abstention():
    case = next(case for case in build_cases(seed_dir=SEED) if case["scenario"] == "primary-source-unavailable")
    submission = {
        "stage": "initial",
        "outcome": case["label"]["expected_final"],
        "delivery": case["label"]["final_delivery"],
        "evidence_refs": [case["sources"][0]["ref"]],
        "query_justified": False,
        "confidence": 0.9,
    }
    run = {
        "arm": "baseline",
        "initial_submission": submission,
        "final_submission": submission,
        "events": [],
        "protocol_errors": [],
        "oracle_leaks": 0,
    }

    runner = score_run(case, run)
    independent = independent_score(case, run)

    assert runner["provenance_complete"] is True
    assert runner["final_exact"] is True
    assert runner["unsafe_automatic_action"] is False
    assert independent["provenance_complete"] is True
    assert independent["exact"] is True
    assert independent["unsafe_automatic_action"] is False

from __future__ import annotations

import json

from evaluations.everything_tracking_adversarial_review import audit_report
from evaluations.everything_tracking_trial import (
    DEFAULT_CONFIG,
    _arm_result,
    build_cases,
    build_report,
    load_config,
    run_baseline,
)


def test_everything_tracking_fixture_is_messy_and_cross_enterprise():
    cases = build_cases(load_config(DEFAULT_CONFIG))

    assert len(cases) == 60
    assert len({case.company_id for case in cases}) == 6
    assert len({case.workflow_id for case in cases}) == 12
    assert len({case.company_shape for case in cases}) == 6
    assert len({resource.adapter for case in cases for resource in case.resources}) >= 30
    assert {case.variant for case in cases} == {
        "material_action",
        "expected_change",
        "ambiguous_state",
        "trust_failure",
        "urgent_operational_risk",
    }
    assert min(len(case.resources) for case in cases) >= 7
    assert all(
        any(resource.metadata.get("required") is False for resource in case.resources)
        for case in cases
    )


def test_every_trust_failure_has_a_required_failed_trust_source():
    cases = build_cases(load_config(DEFAULT_CONFIG))

    for case in cases:
        if case.variant != "trust_failure":
            continue
        required_keys = {source.key for source in case.card.sources if source.required}
        assert any(
            resource.source_key in required_keys and resource.error
            for resource in case.resources
        )


def test_movement_only_baseline_is_noisy_on_everything_tracking():
    results = run_baseline(build_cases(load_config(DEFAULT_CONFIG)))

    assert sum(item.unsafe_automatic_action for item in results) > 0
    assert sum(item.exact_outcome for item in results) < len(results)


def _safe_report():
    cases = build_cases(load_config(DEFAULT_CONFIG))
    baseline = run_baseline(cases)
    safe_jev = [
        _arm_result(
            case,
            arm="signalweave-jev",
            outcome=case.expected_outcome,
            evidence_source_keys=case.expected_evidence_source_keys,
            elapsed_ms=100.0,
            requests=2,
            confidence=0.9,
        )
        for case in cases
    ]
    return cases, build_report(
        cases,
        baseline,
        safe_jev,
        {"requests": len(cases) * 2, "input_tokens": 0, "output_tokens": 0},
        1,
    )


def test_adversarial_reviewer_accepts_a_consistent_safe_treatment():
    cases, report = _safe_report()

    review = audit_report(report, cases)

    assert review["passed"] is True
    assert not [finding for finding in review["findings"] if finding["severity"] == "error"]


def test_adversarial_reviewer_catches_a_mutated_unsafe_treatment_result():
    cases, report = _safe_report()
    mutated = json.loads(json.dumps(report))
    target = next(
        item for item in mutated["results"]["signalweave_jev"] if item["expected_outcome"] == "ignore"
    )
    target["actual_outcome"] = "notify"
    target["exact_outcome"] = False
    target["unsafe_automatic_action"] = True
    target["safe_automatic_action"] = False

    review = audit_report(mutated, cases)

    assert review["passed"] is False
    assert any(
        finding["severity"] == "error"
        and "automatic action" in finding["message"]
        for finding in review["findings"]
    )

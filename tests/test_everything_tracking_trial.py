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
        any(resource.metadata.get("evidence_role") == "quality" for resource in case.resources)
        for case in cases
    )
    assert all(
        any(resource.metadata.get("evidence_role") == "owner" for resource in case.resources)
        for case in cases
    )
    assert all(
        any(resource.metadata.get("required") is False for resource in case.resources)
        for case in cases
    )
    assert all(case.card.decision_guidance.strip() not in {"", "None"} for case in cases)


def test_workflow_policy_overrides_are_used_when_present():
    cases = build_cases(load_config(DEFAULT_CONFIG))

    growth = next(case for case in cases if case.workflow_id == "growth-health")
    fulfillment = next(
        case for case in cases if case.workflow_id == "fulfillment-reliability"
    )

    assert "Qualified pipeline" in growth.card.decision_guidance
    assert "Carrier service levels" in fulfillment.card.decision_guidance


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


def test_healthy_sources_publish_machine_readable_freshness_and_comparability():
    cases = build_cases(load_config(DEFAULT_CONFIG))

    case = next(case for case in cases if case.variant == "material_action")
    healthy_required = [
        resource
        for resource in case.resources
        if resource.metadata.get("required") is not False and resource.error is None
    ]

    assert healthy_required
    assert all("fresh" in resource.observations[0].freshness for resource in healthy_required)
    assert all(
        "comparable" in resource.observations[0].freshness
        for resource in healthy_required
    )


def test_trial_cards_separate_advisory_detail_from_gating_evidence():
    cases = build_cases(load_config(DEFAULT_CONFIG))

    case = next(case for case in cases if case.variant == "material_action")
    assert case.card.evidence_requirements == {
        "question:1": False,
        "question:2": False,
        "watch:1": False,
        "watch:2": False,
        "watch:3": False,
    }
    assert "risk_change_pct of 20 or more" in case.card.decision_guidance
    assert "35 or more as severe" in case.card.decision_guidance
    assert all(
        resource.observations[0].attributes.get("risk_direction") in {"up", "down"}
        for resource in case.resources
        if resource.metadata.get("evidence_role") in {"primary", "corroborates", "diagnostic"}
    )
    quality = next(
        resource for resource in case.resources
        if resource.metadata.get("evidence_role") == "quality"
    )
    assert quality.observations[0].attributes["quality_status"] == "healthy"
    assert quality.observations[0].attributes["comparability"] == "same reporting period and population"


def test_trial_owner_context_distinguishes_expected_and_unplanned_movement():
    cases = build_cases(load_config(DEFAULT_CONFIG))

    expected = next(case for case in cases if case.variant == "expected_change")
    material = next(case for case in cases if case.variant == "material_action")
    expected_owner = next(
        resource for resource in expected.resources
        if resource.metadata.get("evidence_role") == "owner"
    )
    material_owner = next(
        resource for resource in material.resources
        if resource.metadata.get("evidence_role") == "owner"
    )

    assert "planned or expected" in expected_owner.evidence[0].statement
    assert "no planned change" in material_owner.evidence[0].statement
    assert material_owner.observations[0].attributes["owner_change_status"] == "unplanned"
    assert material_owner.observations[0].attributes["planned_change"] is False
    assert expected_owner.observations[0].attributes["owner_change_status"] == "planned"
    assert expected_owner.observations[0].attributes["planned_change"] is True


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

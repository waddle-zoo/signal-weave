from __future__ import annotations

from copy import deepcopy

from test_preset_live_onboarding_review import _passing_report

from evaluations.preset_live_semantic_review import _digest, review_report


def _report() -> dict:
    report = deepcopy(_passing_report())
    report["evaluation"]["result"]["outcome"] = "notify"
    report["evaluation"]["result"]["delivery_methods"] = [
        {"key": "slack", "destination": "slack://growth"}
    ]
    return report


def _assessment(report: dict) -> dict:
    return {
        "trial": "preset-live-semantic-assessment",
        "reviewer_id": "growth-owner",
        "tenant_id": "northstar",
        "card_id": "card-1",
        "card_version": 3,
        "report_digest": _digest(report),
        "expected_outcome": "notify",
        "required_evidence_subjects": ["dashboard:1"],
        "forbidden_evidence_subjects": ["dashboard:foreign"],
        "expected_delivery_method_keys": ["slack"],
        "useful": True,
        "note": "The result named the dashboard evidence the growth owner expected.",
    }


def test_operator_assessment_accepts_a_bound_useful_shadow_result():
    report = _report()

    review = review_report(report, _assessment(report))

    assert review["passed"] is True
    assert review["findings"] == []
    assert review["actual_outcome"] == "notify"
    assert review["evidence_subjects"] == ["dashboard:1"]


def test_operator_assessment_rejects_wrong_report_and_outcome_binding():
    report = _report()
    assessment = _assessment(report)
    assessment["report_digest"] = "wrong-digest"
    assessment["expected_outcome"] = "investigate"

    review = review_report(report, assessment)

    assert review["passed"] is False
    assert any("exact shadow report digest" in finding for finding in review["findings"])
    assert any("expected outcome" in finding for finding in review["findings"])


def test_operator_assessment_rejects_missing_required_evidence_and_delivery():
    report = _report()
    assessment = _assessment(report)
    assessment["required_evidence_subjects"] = ["dashboard:missing"]
    assessment["expected_delivery_method_keys"] = ["email"]

    review = review_report(report, assessment)

    assert review["passed"] is False
    assert any("required evidence is missing" in finding for finding in review["findings"])
    assert any("expected delivery methods are missing" in finding for finding in review["findings"])


def test_operator_assessment_rejects_non_useful_or_malformed_labels():
    report = _report()
    assessment = _assessment(report)
    assessment["useful"] = False
    assessment["expected_outcome"] = "maybe"
    assessment["required_evidence_subjects"] = "dashboard:1"

    review = review_report(report, assessment)

    assert review["passed"] is False
    assert any("useful" in finding for finding in review["findings"])
    assert any("supported SignalWeave outcome" in finding for finding in review["findings"])
    assert any("required_evidence_subjects" in finding for finding in review["findings"])


def test_operator_assessment_keeps_transport_safety_as_a_prerequisite():
    report = _report()
    report["evaluation"]["receipt"]["delivery_enabled"] = True

    review = review_report(report, _assessment(report))

    assert review["passed"] is False
    assert any("underlying Preset live shadow report failed" in finding for finding in review["findings"])

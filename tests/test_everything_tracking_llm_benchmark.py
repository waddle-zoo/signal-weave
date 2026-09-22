from __future__ import annotations

import json

from evaluations.everything_tracking_llm_adversarial_review import audit_report
from evaluations.everything_tracking_llm_benchmark import _input_digest, _jev_row
from evaluations.everything_tracking_trial import DEFAULT_CONFIG, build_cases, load_config


def _perfect_report():
    cases = build_cases(load_config(DEFAULT_CONFIG))
    rows = []
    for arm in ("llm-raw", "jev", "llm-signalweave"):
        for case in cases:
            expected_delivery = sorted(
                method.key
                for method in case.card.delivery_methods
                if method.outcome.value == case.expected_outcome
            )
            rows.append(
                {
                    "case_id": case.case_id,
                    "arm": arm,
                    "input_digest": _input_digest(case),
                    "variant": case.variant,
                    "expected_outcome": case.expected_outcome,
                    "actual_outcome": case.expected_outcome,
                    "expected_delivery": expected_delivery,
                    "actual_delivery": expected_delivery,
                    "expected_evidence_source_keys": case.expected_evidence_source_keys,
                    "actual_evidence_source_keys": case.expected_evidence_source_keys,
                    "evidence_recall": 1.0,
                    "exact": True,
                    "unsafe_automatic_action": False,
                    "provenance_valid": True,
                    "confidence": 0.9,
                    "elapsed_ms": 100.0,
                    "api_requests": 1,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "oracle_leaks": 0,
                    "error": None,
                }
            )
    summary = {
        "cases": len(cases),
        "exact": len(cases),
        "exact_rate": 1.0,
        "unsafe_automatic_actions": 0,
        "evidence_recall": 1.0,
        "errors": 0,
        "oracle_leaks": 0,
    }
    return cases, {
        "repeats": 1,
        "design": {
            "companies": len({case.company_id for case in cases}),
            "adapters": sorted({resource.adapter for case in cases for resource in case.resources}),
            "same_card_and_sources_all_arms": True,
            "expected_labels_sent_to_providers": False,
            "direct_llm_and_mediated_llm_same_model": True,
        },
        "arms": {arm: summary for arm in ("llm-raw", "jev", "llm-signalweave")},
        "rows": rows,
        "paired_rows": [{"case_id": case.case_id} for case in cases],
    }


def test_adversarial_reviewer_accepts_a_complete_safe_comparison():
    cases, report = _perfect_report()

    review = audit_report(report, cases)

    assert review["protocol_passed"] is True
    assert review["promotion_ready"] is True
    assert review["verdict"] == "PROMOTE"


def test_adversarial_reviewer_rejects_a_treated_unsafe_action():
    cases, report = _perfect_report()
    mutated = json.loads(json.dumps(report))
    target_case = next(case for case in cases if case.expected_outcome == "ignore")
    target = next(
        row
        for row in mutated["rows"]
        if row["arm"] == "llm-signalweave" and row["case_id"] == target_case.case_id
    )
    target["actual_outcome"] = "notify"
    target["actual_delivery"] = [target_case.card.delivery_methods[0].key]
    target["exact"] = False
    target["unsafe_automatic_action"] = True

    review = audit_report(mutated, cases)

    assert review["protocol_passed"] is False
    assert review["promotion_ready"] is False
    assert any(
        finding["reviewer"] == "correctness"
        and "unsafe automatic action" in finding["message"]
        for finding in review["findings"]
    )


def test_adversarial_reviewer_rejects_provider_errors_and_input_mismatch():
    cases, report = _perfect_report()
    mutated = json.loads(json.dumps(report))
    target = next(row for row in mutated["rows"] if row["arm"] == "jev")
    target["input_digest"] = "not-the-case-bundle"
    target["error"] = "provider timeout"
    target["actual_outcome"] = None
    target["exact"] = False

    review = audit_report(mutated, cases)

    assert review["protocol_passed"] is False
    assert any("input digest" in finding["message"] for finding in review["findings"])
    assert any("provider error" in finding["message"] for finding in review["findings"])


def test_jev_scoring_uses_provider_delivery_instead_of_expected_delivery():
    case = next(case for case in build_cases(load_config(DEFAULT_CONFIG)) if case.expected_outcome == "notify")

    row = _jev_row(
        case,
        {
            "outcome": case.expected_outcome,
            "delivery": [],
            "evidence_source_keys": case.expected_evidence_source_keys,
            "confidence": 0.9,
        },
        {"requests": 0, "input_tokens": 0, "output_tokens": 0},
        100.0,
        None,
    )

    assert row.actual_delivery == []
    assert row.exact is False


def test_cost_estimate_uses_provider_token_usage():
    from evaluations.everything_tracking_llm_benchmark import _estimated_cost

    assert _estimated_cost(
        {"input_tokens": 1_000_000, "output_tokens": 500_000},
        input_price_per_mtok=0.20,
        output_price_per_mtok=1.20,
    ) == 0.8

from evaluations.card_guided_retrieval_adversarial_review import audit_report


def _report() -> dict:
    arm = {
        "retrieval_precision": 0.9,
        "retrieval_recall": 0.95,
        "outcome_accuracy": 0.95,
        "decision_role_accuracy": 0.85,
        "driver_recall": 0.9,
    }
    return {
        "benchmark": "card-guided-retrieval",
        "model": "jev-latest",
        "charts_per_case": 1000,
        "cases": 6,
        "arms": {
            "jev-card-guided": arm,
            "gold-selection-jev": {"outcome_accuracy": 0.95},
            "lexical-selection": {"outcome_accuracy": 0.5},
        },
        "rows": [
            {
                "arm": "gold-selection-jev",
                "expected_outcome": "ignore",
                "selected_count": 1,
            },
            {"arm": "jev-card-guided", "findings": {}},
        ],
    }


def test_adversarial_review_passes_only_a_complete_strong_report():
    review = audit_report(_report())

    assert review["status"] == "pass"
    assert all(review["checks"].values())


def test_adversarial_review_catches_high_retrieval_but_weak_decision_quality():
    report = _report()
    report["arms"]["jev-card-guided"]["outcome_accuracy"] = 0.5
    report["arms"]["gold-selection-jev"]["outcome_accuracy"] = 0.5

    review = audit_report(report)

    assert review["status"] == "fail"
    assert "guided_outcome_accuracy" in {
        item["check"] for item in review["findings"]
    }
    assert "gold_decision_accuracy" in {item["check"] for item in review["findings"]}


def test_catalog_backed_review_rejects_report_label_tampering():
    from evaluations.card_guided_retrieval_benchmark import build_cases
    from tests.test_card_guided_retrieval_benchmark import _config

    report = _report()
    expected_cases = build_cases(_config(), repeats=1)
    report["rows"] = [
        {
            "case_id": case.case_id,
            "arm": "jev-card-guided",
            "expected_outcome": case.expected_outcome,
            "gold_ids": sorted(case.gold_roles),
            "gold_evidence_roles": case.gold_evidence_roles,
            "retrieval_precision": 0.9,
            "retrieval_recall": 0.95,
            "decision_f1": 0.9,
            "decision_role_accuracy": 0.85,
            "suggested_role_accuracy": 0.85,
            "promoted_role_coverage": 0.9,
            "driver_recall": 0.9,
            "suggested_driver_recall": 0.9,
            "outcome_accuracy": 1.0,
            "findings": {},
        }
        for case in expected_cases
    ]
    report["cases"] = len(expected_cases)
    report["arms"]["jev-card-guided"].update(
        {
            "outcome_accuracy": 1.0,
            "retrieval_precision": 0.9,
            "retrieval_recall": 0.95,
            "decision_role_accuracy": 0.85,
            "driver_recall": 0.9,
        }
    )
    report["rows"][0]["expected_outcome"] = "ignore"

    review = audit_report(report, expected_cases=expected_cases)

    assert review["status"] == "fail"
    assert "scenario_labels_verified" in {item["check"] for item in review["findings"]}

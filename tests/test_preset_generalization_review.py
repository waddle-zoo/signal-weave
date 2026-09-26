from copy import deepcopy

from evaluations.preset_generalization_review import review_report


def _passing_report() -> dict:
    return {
        "workspace_count": 1,
        "charts_per_workspace": 8,
        "chart_count": 8,
        "case_coverage": [
            "ambiguous_numeric",
            "dict_metric",
            "empty",
            "explicit",
            "implicit_count",
            "missing_metric",
            "non_numeric_metric",
            "provider_error",
        ],
        "envelope_coverage": ["columnar", "data", "records", "rows", "values"],
        "results": [{"charts": 8, "failures": [], "passed": True, "quality": "partial"}],
        "not_proven": [
            "a real Preset tenant's permissions, plans, rate limits, or network path",
            "live Jev semantic accuracy or business usefulness",
            "managed SignalWeave hosting",
        ],
        "passed": True,
    }


def test_independent_preset_review_accepts_complete_report():
    assert review_report(_passing_report())["passed"] is True


def test_independent_preset_review_rejects_pass_flag_with_hidden_failure():
    report = _passing_report()
    report["results"][0]["failures"] = ["chart was dropped"]

    review = review_report(report)

    assert review["passed"] is False
    assert any("contains trial failures" in finding for finding in review["findings"])


def test_independent_preset_review_rejects_incomplete_coverage():
    report = deepcopy(_passing_report())
    report["envelope_coverage"] = ["data"]
    report["chart_count"] = 7

    review = review_report(report)

    assert review["passed"] is False
    assert any("coverage is incomplete" in finding for finding in review["findings"])
    assert any("chart_count" in finding for finding in review["findings"])

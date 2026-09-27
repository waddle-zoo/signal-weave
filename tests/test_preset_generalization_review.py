from __future__ import annotations

from copy import deepcopy

from evaluations.preset_generalization_review import review_report
from evaluations.preset_generalization_trial import run_trial


def test_generalization_reviewer_accepts_varied_chart_shapes():
    report = run_trial(seed=17, workspace_count=4, charts_per_workspace=8)

    review = review_report(report)

    assert review["passed"] is True
    assert review["findings"] == []


def test_generalization_reviewer_rejects_forged_visualization_coverage():
    report = run_trial(seed=17, workspace_count=4, charts_per_workspace=8)
    mutated = deepcopy(report)
    mutated["viz_type_coverage"] = ["line", "bar"]

    review = review_report(mutated)

    assert review["passed"] is False
    assert any("viz_type_coverage" in finding for finding in review["findings"])


def test_generalization_reviewer_rejects_missing_unknown_chart_shape():
    report = run_trial(seed=17, workspace_count=4, charts_per_workspace=8)
    mutated = deepcopy(report)
    for result in mutated["results"]:
        result["viz_types"] = [
            viz_type for viz_type in result["viz_types"] if viz_type != "vendor_extension"
        ]
    mutated["viz_type_coverage"] = sorted(
        {viz_type for result in mutated["results"] for viz_type in result["viz_types"]}
    )

    review = review_report(mutated)

    assert review["passed"] is False
    assert any("unknown/vendor extension" in finding for finding in review["findings"])

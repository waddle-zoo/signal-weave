import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from signalweave.diagnostics import (
    AnalyticalComparison,
    PeriodValue,
    SegmentPair,
    analyze_comparison,
)
from signalweave.models import InsightCard, ResourceDiscovery, SourceRef
from signalweave.numeric_conditions import NumericCondition, evaluate_numeric_conditions
from signalweave.onboarding import InsightAuthoringService


def comparison(*, kind="additive", unit="number"):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    if kind == "rate":
        baseline = PeriodValue(numerator=80, denominator=100)
        current = PeriodValue(numerator=90, denominator=100)
        segments = [
            SegmentPair(
                segment="a",
                baseline=PeriodValue(numerator=40, denominator=50),
                current=PeriodValue(numerator=45, denominator=50),
            ),
            SegmentPair(
                segment="any",
                baseline=PeriodValue(numerator=40, denominator=50),
                current=PeriodValue(numerator=45, denominator=50),
            ),
        ]
    else:
        baseline = PeriodValue(value=100)
        current = PeriodValue(value=90)
        segments = [
            SegmentPair(segment="a", baseline=PeriodValue(value=60), current=PeriodValue(value=50)),
            SegmentPair(segment="any", baseline=PeriodValue(value=40), current=PeriodValue(value=40)),
        ]
    return AnalyticalComparison(
        key="comparison-a",
        metric="metric-a",
        definition="approved definition",
        population="approved population",
        unit=unit,
        dimension="channel",
        kind=kind,
        baseline_start=start,
        baseline_end=start + timedelta(days=1),
        current_start=start + timedelta(days=1),
        current_end=start + timedelta(days=2),
        coverage="complete",
        disjoint_segments=True,
        comparable=True,
        query_refs=["query-a"],
        baseline_total=baseline,
        current_total=current,
        segments=segments,
    )


def card(*conditions: NumericCondition) -> InsightCard:
    return InsightCard(
        id="card-a",
        title="Card",
        what_to_watch="The approved metric",
        why_watch="Check its bounded movement",
        sources=[SourceRef(
            key="source-a",
            adapter="superset",
            resource="dashboard:a",
            label="Approved source",
            required_comparison_keys=["comparison-a"],
        )],
        numeric_conditions=list(conditions),
    )


def condition(**overrides) -> NumericCondition:
    values = {
        "text": "The metric fell by at least ten units",
        "source_key": "source-a",
        "comparison_key": "comparison-a",
        "measurement": "delta",
        "unit": "number",
        "threshold": 10,
        "comparator": "<=",
    }
    values.update(overrides)
    return NumericCondition(**values)


def evaluate(*conditions, report=None):
    report = report or analyze_comparison("source-a", comparison())
    return evaluate_numeric_conditions(card(*conditions), [report])


@pytest.mark.parametrize("comparator,expected", [("<", "false"), ("<=", "true")])
def test_absolute_strict_and_inclusive_boundaries(comparator, expected):
    result = evaluate(condition(comparator=comparator, threshold=10, absolute=True))[0]
    assert result.status == expected
    assert result.value == 10
    assert result.unit == result.expected_unit == "number"
    assert result.condition_text.startswith("The metric")
    assert result.query_refs == result.provenance == ["query-a"]


def test_numeric_condition_schema_separates_unit_from_absolute_magnitude():
    properties = NumericCondition.model_json_schema()["properties"]
    assert properties["unit"]["type"] == "string"
    assert "magnitude" not in json.dumps(properties["unit"]).lower()
    assert "magnitude" in properties["absolute"]["description"].lower()


def test_contribution_checks_support_any_and_exact_segment_without_reserved_label():
    report = analyze_comparison("source-a", comparison())
    any_result = evaluate(
        condition(measurement="contribution", threshold=-10, comparator="<="), report=report
    )[0]
    exact_result = evaluate(
        condition(measurement="contribution", segment="any", threshold=0, comparator="=="),
        report=report,
    )[0]
    assert any_result.status == "true"
    assert any_result.segment is None
    assert any_result.matched_segment == "a"
    assert exact_result.status == "true"
    assert exact_result.segment == exact_result.matched_segment == "any"


def test_rate_conditions_compare_fraction_in_the_report_unit():
    report = analyze_comparison("source-a", comparison(kind="rate", unit="fraction"))
    result = evaluate(
        condition(measurement="delta", unit="fraction", threshold=0.1, comparator=">="),
        report=report,
    )[0]
    mismatched = evaluate(
        condition(measurement="delta", unit="percent", threshold=10, comparator=">="),
        report=report,
    )[0]
    assert result.status == "true"
    assert result.value == pytest.approx(0.1)
    assert mismatched.status == "unknown"


def rate_effect_comparison(*, baseline_total, current_total, segments):
    return comparison(kind="rate").model_copy(update={
        "baseline_total": PeriodValue(**baseline_total),
        "current_total": PeriodValue(**current_total),
        "segments": [
            SegmentPair(
                segment=segment,
                baseline=PeriodValue(**baseline),
                current=PeriodValue(**current),
            )
            for segment, baseline, current in segments
        ],
    })


def test_pure_mix_can_trigger_segment_contribution_without_within_effect():
    report = analyze_comparison(
        "source-a",
        rate_effect_comparison(
            baseline_total={"numerator": 100, "denominator": 200},
            current_total={"numerator": 180, "denominator": 300},
            segments=[
                ("a", {"numerator": 80, "denominator": 100}, {"numerator": 160, "denominator": 200}),
                ("b", {"numerator": 20, "denominator": 100}, {"numerator": 20, "denominator": 100}),
            ],
        ),
    )
    contribution = evaluate(
        condition(measurement="contribution", threshold=0.05, comparator=">"), report=report
    )[0]
    within = evaluate(
        condition(measurement="within_effect", threshold=0.05, comparator=">"), report=report
    )[0]

    assert report.status == "complete"
    assert report.within_effect == pytest.approx(0)
    assert report.mix_effect == pytest.approx(0.1)
    assert contribution.status == "true"
    assert within.status == "false"


def test_within_effect_can_be_true_while_no_segment_contribution_reaches_threshold():
    report = analyze_comparison(
        "source-a",
        rate_effect_comparison(
            baseline_total={"numerator": 150, "denominator": 300},
            current_total={"numerator": 168, "denominator": 300},
            segments=[
                ("a", {"numerator": 50, "denominator": 100}, {"numerator": 65, "denominator": 100}),
                ("b", {"numerator": 50, "denominator": 100}, {"numerator": 65, "denominator": 100}),
                ("offset", {"numerator": 50, "denominator": 100}, {"numerator": 38, "denominator": 100}),
            ],
        ),
    )
    within = evaluate(
        condition(measurement="within_effect", threshold=0.05, comparator=">"), report=report
    )[0]
    contribution = evaluate(
        condition(measurement="contribution", threshold=0.06, comparator=">="), report=report
    )[0]

    assert report.within_effect == pytest.approx(0.06)
    assert report.mix_effect == pytest.approx(0)
    assert within.status == "true"
    assert contribution.status == "false"


@pytest.mark.parametrize("measurement", ["within_effect", "mix_effect"])
def test_aggregate_rate_effects_are_unknown_for_additive_reports(measurement):
    result = evaluate(condition(measurement=measurement), report=analyze_comparison("source-a", comparison()))[0]
    assert result.status == "unknown"
    assert "symmetric rate decomposition" in result.reason


def test_effects_require_finite_recomputed_report_values():
    rate_report = analyze_comparison("source-a", comparison(kind="rate", unit="fraction"))
    tampered = rate_report.model_copy(update={"within_effect": 999.0})
    assert evaluate(
        condition(measurement="within_effect", unit="fraction"), report=tampered
    )[0].status == "unknown"


def test_numeric_schema_describes_exact_source_and_comparison_bindings():
    properties = NumericCondition.model_json_schema()["properties"]
    assert "selected_sources.key" in properties["source_key"]["description"]
    assert "AnalyticalComparison.key" in properties["comparison_key"]["description"]
    assert "window" in properties["comparison_key"]["description"]
    assert "relative_delta" not in json.dumps(properties)


def test_aggregate_effects_reject_segment_selectors():
    with pytest.raises(ValidationError, match="segment selector"):
        condition(measurement="within_effect", segment="a")


@pytest.mark.parametrize(
    "reports",
    [
        [],
        [analyze_comparison("source-a", comparison(kind="additive", unit="number"))],
        [analyze_comparison("source-a", comparison())] * 2,
    ],
)
def test_missing_incomplete_and_ambiguous_evidence_are_unknown(reports):
    if reports and reports[0].status == "complete":
        reports[0] = reports[0].model_copy(update={"status": "insufficient_data"})
    result = evaluate_numeric_conditions(card(condition()), reports)[0]
    assert result.status == "unknown"


def test_nonfinite_mutated_report_is_unknown():
    report = analyze_comparison("source-a", comparison()).model_copy(update={"delta": float("nan")})
    assert evaluate_numeric_conditions(card(condition()), [report])[0].status == "unknown"


def test_optional_complete_report_can_be_used_but_optional_incomplete_stays_unknown():
    complete = analyze_comparison("source-a", comparison()).model_copy(update={"required": False})
    incomplete = complete.model_copy(update={"status": "insufficient_data"})
    assert evaluate_numeric_conditions(card(condition()), [complete])[0].status == "true"
    assert evaluate_numeric_conditions(card(condition()), [incomplete])[0].status == "unknown"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_key": "other-source"},
        {"comparison_key": "other-comparison"},
        {"measurement": "baseline", "segment": "a"},
        {"threshold": float("inf")},
        {"absolute": 1},
        {"absolute": True, "threshold": -10},
    ],
)
def test_invalid_bindings_and_numeric_inputs_are_rejected(changes):
    with pytest.raises((ValidationError, ValueError)):
        bad = condition(**changes)
        card(bad)


def test_numeric_condition_changes_review_fingerprint():
    discovery = ResourceDiscovery(
        goal="metric",
        matches=[],
        candidate_count=0,
        candidate_limit=1,
        evaluator="test",
    )
    first = InsightAuthoringService.source_selection_fingerprint(
        card(condition(threshold=10)), discovery, None
    )
    second = InsightAuthoringService.source_selection_fingerprint(
        card(condition(threshold=11)), discovery, None
    )
    assert first != second

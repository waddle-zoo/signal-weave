import math
import random
from datetime import datetime
from fractions import Fraction
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from signalweave.diagnostics import (
    AnalysisReport,
    AnalyticalComparison,
    PeriodValue,
    SegmentContribution,
    analyze_comparison,
)


def comparison(kind="additive", **overrides):
    payload = {
        "key": "volume-by-channel", "metric": "volume", "definition": "Completed activity",
        "population": "Eligible population", "unit": "count", "dimension": "channel",
        "kind": kind, "baseline_start": "2026-08-01T00:00:00Z",
        "baseline_end": "2026-08-08T00:00:00Z", "current_start": "2026-08-08T00:00:00Z",
        "current_end": "2026-08-15T00:00:00Z", "coverage": "complete",
        "disjoint_segments": True, "comparable": True, "query_refs": ["query:total", "query:segments"],
        "baseline_total": {"value": 100}, "current_total": {"value": 80},
        "segments": [
            {"segment": "online", "baseline": {"value": 60}, "current": {"value": 30}},
            {"segment": "store", "baseline": {"value": 40}, "current": {"value": 50}},
        ],
    }
    payload.update(overrides)
    return AnalyticalComparison.model_validate(payload)


def rate_comparison():
    # Every stratum improves by 10pp while mix moves toward the lower-rate stratum.
    return comparison("rate", baseline_total={"numerator": 82, "denominator": 100},
                      current_total={"numerator": 28, "denominator": 100}, segments=[
                          {"segment": "high", "baseline": {"numerator": 81, "denominator": 90},
                           "current": {"numerator": 10, "denominator": 10}},
                          {"segment": "low", "baseline": {"numerator": 1, "denominator": 10},
                           "current": {"numerator": 18, "denominator": 90}},
                      ])


def test_additive_offsets_reconcile_without_clamping_contributions():
    report = analyze_comparison("source", comparison())
    assert report.status == "complete"
    assert report.delta == -20
    assert [(row.segment, row.contribution) for row in report.contributions] == [("online", -30), ("store", 10)]
    assert report.residual == 0
    assert report.claim_type == "accounting_decomposition"


def test_simpson_reversal_separates_mix_from_within_improvement():
    report = analyze_comparison("source", rate_comparison())
    assert report.status == "complete"
    assert report.baseline == pytest.approx(.82)
    assert report.current == pytest.approx(.28)
    assert report.delta == pytest.approx(-.54)
    assert report.within_effect == pytest.approx(.10)
    assert report.mix_effect == pytest.approx(-.64)
    assert report.residual == pytest.approx(0)


@pytest.mark.parametrize("changes", [
    {"coverage": "partial"}, {"comparable": False}, {"disjoint_segments": False},
    {"current_total": {"value": 85}}, {"baseline_start": "2026-08-01T00:00:00"},
    {"current_end": "2026-08-14T00:00:00Z", "require_equal_duration": True},
    {"current_start": "2026-08-07T00:00:00Z"},
])
def test_incomplete_or_noncomparable_inputs_have_no_findings(changes):
    report = analyze_comparison("source", comparison(**changes))
    assert report.status == "insufficient_data"
    assert report.issues
    assert report.contributions == []
    assert report.delta is None


def test_missing_value_is_not_zero_and_duplicate_categories_rejected():
    data = comparison().model_dump(mode="json")
    data["segments"][0]["baseline"]["value"] = None
    assert analyze_comparison("source", AnalyticalComparison.model_validate(data)).status == "insufficient_data"
    data = comparison().model_dump(mode="json")
    data["segments"][1]["segment"] = data["segments"][0]["segment"]
    assert analyze_comparison("source", AnalyticalComparison.model_validate(data)).status == "insufficient_data"


def test_zero_rate_denominators_cannot_be_imputed():
    data = rate_comparison().model_dump(mode="json")
    data["segments"][0]["current"]["denominator"] = 0
    data["current_total"]["denominator"] = 90
    report = analyze_comparison("source", AnalyticalComparison.model_validate(data))
    assert report.status == "insufficient_data"
    assert any("positive" in issue for issue in report.issues)


def test_wrong_baseline_fails_and_nonfinite_values_are_rejected():
    assert analyze_comparison("source", comparison(), comparison_window="year_over_year").status == "insufficient_data"
    with pytest.raises(ValidationError):
        comparison(current_total={"value": float("nan")})


def test_null_change_preserves_opposing_movements():
    data = comparison().model_dump(mode="json")
    data["current_total"]["value"] = 100
    data["segments"][1]["current"]["value"] = 70
    report = analyze_comparison("source", AnalyticalComparison.model_validate(data))
    assert report.delta == 0
    assert [row.contribution for row in report.contributions] == [-30, 30]


def test_rate_decomposition_reconciles_generated_partitions_and_is_order_invariant():
    rng = random.Random(6129)
    for _ in range(100):
        rows = []
        for index in range(rng.randint(2, 40)):
            d0, d1 = rng.randint(5, 1000), rng.randint(5, 1000)
            rows.append({"segment": str(index),
                         "baseline": {"numerator": rng.randint(0, d0), "denominator": d0},
                         "current": {"numerator": rng.randint(0, d1), "denominator": d1}})
        totals = {period + "_total": {field: sum(row[period][field] for row in rows)
                                      for field in ("numerator", "denominator")}
                  for period in ("baseline", "current")}
        report = analyze_comparison("source", comparison("rate", segments=rows, **totals))
        # Independent oracle: average both orders of updating four standardized
        # totals. Checking only W + M would admit arbitrary allocations.
        periods = ("baseline", "current")
        standardized = {
            (i, j): sum(
                (Fraction(row[i]["denominator"], totals[i + "_total"]["denominator"])
                 * Fraction(row[j]["numerator"], row[j]["denominator"]) for row in rows),
                Fraction(),
            )
            for i in periods for j in periods
        }
        t00, t01 = standardized["baseline", "baseline"], standardized["baseline", "current"]
        t10, t11 = standardized["current", "baseline"], standardized["current", "current"]
        expected_within = ((t01 - t00) + (t11 - t10)) / 2
        expected_mix = ((t10 - t00) + (t11 - t01)) / 2
        assert report.status == "complete"
        assert report.within_effect == pytest.approx(float(expected_within), rel=1e-13, abs=0)
        assert report.mix_effect == pytest.approx(float(expected_mix), rel=1e-13, abs=0)
        for contribution in report.contributions:
            row = rows[int(contribution.segment)]
            expected = (Fraction(row["current"]["numerator"], totals["current_total"]["denominator"])
                        - Fraction(row["baseline"]["numerator"], totals["baseline_total"]["denominator"]))
            assert contribution.contribution == pytest.approx(float(expected), rel=1e-13, abs=0)
        reversed_report = analyze_comparison("source", comparison("rate", segments=list(reversed(rows)), **totals))
        assert report.contributions == reversed_report.contributions


def additive_rows(baseline, current, **overrides):
    return comparison(
        baseline_total={"value": math.fsum(baseline)},
        current_total={"value": math.fsum(current)},
        segments=[{"segment": str(i), "baseline": {"value": a}, "current": {"value": b}}
                  for i, (a, b) in enumerate(zip(baseline, current, strict=True))],
        **overrides,
    )


def rate_rows(baseline, current, **overrides):
    return comparison(
        "rate",
        baseline_total={"numerator": math.fsum(a for a, _ in baseline),
                        "denominator": math.fsum(b for _, b in baseline)},
        current_total={"numerator": math.fsum(a for a, _ in current),
                       "denominator": math.fsum(b for _, b in current)},
        segments=[{"segment": str(i), "baseline": {"numerator": a, "denominator": b},
                   "current": {"numerator": c, "denominator": d}}
                  for i, ((a, b), (c, d)) in enumerate(zip(baseline, current, strict=True))],
        **overrides,
    )


def assert_unavailable(report):
    assert report.status == "insufficient_data"
    assert report.issues
    assert report.contributions == []
    for name in ("baseline", "current", "delta", "residual", "within_effect", "mix_effect"):
        assert getattr(report, name) is None


@pytest.mark.parametrize("field", ["value", "numerator", "denominator"])
@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf")])
def test_measurements_reject_booleans_and_nonfinite_numbers(field, value):
    with pytest.raises(ValidationError):
        PeriodValue(**{field: value})


@pytest.mark.parametrize("value", [
    True, float("nan"), float("inf"), -float("inf"),
    pytest.param(10**400, id="integer-outside-float-range"),
])
def test_bypassed_input_validation_returns_unavailable(value):
    data = comparison()
    data.segments[0].baseline.value = value
    if isinstance(value, int) and not isinstance(value, bool):
        with pytest.warns(UserWarning, match="serializer warnings"):
            report = analyze_comparison("source", data)
    else:
        report = analyze_comparison("source", data)
    assert_unavailable(report)


def test_finite_output_schema():
    with pytest.raises(ValidationError):
        SegmentContribution(segment="a", baseline=0, current=1, contribution=float("inf"))
    payload = analyze_comparison("source", comparison()).model_dump()
    for field in ("baseline", "current", "delta", "residual", "within_effect", "mix_effect"):
        with pytest.raises(ValidationError):
            AnalysisReport.model_validate({**payload, field: float("nan")})


@pytest.mark.parametrize("scale", [1e-300, 1e-12, 1, 1e12, 1e300])
@pytest.mark.parametrize("field", ["numerator", "denominator"])
def test_inconsistent_rate_totals_fail_at_any_scale(scale, field):
    data = rate_rows([(scale, scale)], [(scale, scale)])
    setattr(data.baseline_total, field, scale * 100)
    setattr(data.current_total, field, scale * 100)
    assert_unavailable(analyze_comparison("source", data))


def test_large_totals_do_not_allow_old_relative_tolerance_slack():
    data = additive_rows([1e12], [1e12 + 100])
    data.baseline_total.value += 500
    data.current_total.value += 500
    assert_unavailable(analyze_comparison("source", data))


def test_subnormal_values_have_no_absolute_tolerance_floor():
    smallest = math.ulp(0.0)
    data = additive_rows([smallest], [2 * smallest])
    report = analyze_comparison("source", data)
    assert report.status == "complete"
    assert report.delta == smallest
    data.baseline_total.value = 0
    assert_unavailable(analyze_comparison("source", data))


def test_representation_rounding_is_allowed_without_erasing_residual():
    report = analyze_comparison("source", additive_rows([.1, 1e9], [.2, 1e9]))
    assert report.status == "complete"
    assert report.contributions[0].contribution == .1
    assert report.residual == report.delta - .1
    assert report.residual != 0
    data = additive_rows([.1, .2], [.2, .4])
    data.baseline_total.value, data.current_total.value = .3, .6
    assert analyze_comparison("source", data).status == "complete"


@pytest.mark.parametrize("baseline,current", [
    ([1e308, -1e308], [-1e308, 1e308]),  # Per-segment difference overflows.
    ([-1e308], [1e308]),  # Total difference overflows.
])
def test_unrepresentable_additive_outputs_fail_without_raising(baseline, current):
    assert_unavailable(analyze_comparison("source", additive_rows(baseline, current)))


def test_overflowing_input_sum_fails_without_raising():
    data = additive_rows([1e308], [1e308])
    data.segments.append(data.segments[0].model_copy(update={"segment": "extra"}))
    assert_unavailable(analyze_comparison("source", data))


def test_exact_summation_handles_cancelling_large_inputs():
    data = additive_rows([1e308, -1e308], [1e308, -1e308])
    data.segments = [data.segments[0], data.segments[0].model_copy(update={"segment": "extra"}),
                     data.segments[1], data.segments[1].model_copy(update={"segment": "last"})]
    report = analyze_comparison("source", data)
    assert report.status == "complete"
    assert report.delta == 0


@pytest.mark.parametrize("rows", [[(1e308, 1e-308)], [(1e-308, 1e308)]])
def test_rate_overflow_and_underflow_fail_without_raising(rows):
    assert_unavailable(analyze_comparison("source", rate_rows(rows, rows)))


def test_large_finite_rates_do_not_overflow_intermediate_mean():
    report = analyze_comparison("source", rate_rows([(1e308, 1)], [(1e308, 1)]))
    assert report.status == "complete"
    assert report.baseline == 1e308
    assert report.within_effect == report.mix_effect == 0


@pytest.mark.parametrize("baseline,current,within,mix", [
    ([(80, 100), (20, 100)], [(90, 100), (30, 100)], Fraction(1, 10), Fraction()),
    ([(80, 100), (20, 100)], [(40, 50), (30, 150)], Fraction(), Fraction(-3, 20)),
    ([(10, 100), (90, 100)], [(80, 200), (80, 100)], Fraction(2, 15), Fraction(-1, 10)),
    ([(0, 100), (0, 100)], [(0, 100), (0, 100)], Fraction(), Fraction()),
])
def test_fixed_independent_split_oracles(baseline, current, within, mix):
    report = analyze_comparison("source", rate_rows(baseline, current))
    assert report.status == "complete"
    assert report.within_effect == float(within)
    assert report.mix_effect == float(mix)
    assert report.delta == float(within + mix)


@pytest.mark.parametrize("numerator,denominator", [(1, 0), (0, 0), (1, -1), (-1, 1)])
def test_invalid_rate_domains_return_unavailable(numerator, denominator):
    data = rate_rows([(numerator, denominator)], [(1, 1)])
    assert_unavailable(analyze_comparison("source", data))


def test_precomputed_rate_is_not_silently_accepted_with_sufficient_statistics():
    data = rate_comparison()
    data.current_total.value = .28
    assert_unavailable(analyze_comparison("source", data))


@pytest.mark.parametrize("scale", [1e-300, 1e-12, 1, 1e12, 1e300])
def test_rate_split_is_invariant_to_common_input_scale(scale):
    data = rate_rows([(10 * scale, 100 * scale), (90 * scale, 100 * scale)],
                     [(80 * scale, 200 * scale), (80 * scale, 100 * scale)])
    report = analyze_comparison("source", data)
    assert report.status == "complete"
    assert report.within_effect == pytest.approx(2 / 15, rel=1e-13, abs=0)
    assert report.mix_effect == pytest.approx(-1 / 10, rel=1e-13, abs=0)
    assert report.delta == pytest.approx(1 / 30, rel=1e-13, abs=0)


@pytest.mark.parametrize("kind", ["additive", "rate"])
def test_unequal_calendar_periods_use_explicit_duration_policy(kind):
    data = comparison() if kind == "additive" else rate_comparison()
    data = AnalyticalComparison.model_validate({**data.model_dump(),
        "baseline_start": "2026-01-01T00:00:00Z", "baseline_end": "2026-02-01T00:00:00Z",
        "current_start": "2026-02-01T00:00:00Z", "current_end": "2026-03-01T00:00:00Z"})
    assert data.require_equal_duration is False
    report = analyze_comparison("source", data)
    assert report.status == "complete"
    assert any("not time-normalized" in note for note in report.limitations)
    data.require_equal_duration = True
    assert_unavailable(analyze_comparison("source", data))


def test_duration_policy_uses_elapsed_utc_time_across_dst():
    tz = ZoneInfo("America/Toronto")
    data = comparison(
        baseline_start=datetime(2026, 3, 7, tzinfo=tz), baseline_end=datetime(2026, 3, 8, tzinfo=tz),
        current_start=datetime(2026, 3, 8, tzinfo=tz), current_end=datetime(2026, 3, 9, tzinfo=tz),
        require_equal_duration=True,
    )
    assert_unavailable(analyze_comparison("source", data))


@pytest.mark.parametrize("kind,unit", [("additive", "USD"), ("rate", "USD/order")])
def test_declared_unit_survives_analysis_and_json_roundtrip(kind, unit):
    data = comparison() if kind == "additive" else rate_comparison()
    data.unit = unit
    report = analyze_comparison("source", data)
    restored = AnalysisReport.model_validate_json(report.model_dump_json())
    assert restored.unit == unit
    assert restored.comparison == data

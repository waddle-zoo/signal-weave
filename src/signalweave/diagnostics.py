"""Reproducible accounting decompositions over adapter-declared measurements.

No model supplies arithmetic, p-values, or causal conclusions. Jev interprets
these reports alongside the business card and the remaining source evidence.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator


class PeriodValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: FiniteFloat | None = None
    numerator: FiniteFloat | None = None
    denominator: FiniteFloat | None = None

    @field_validator("value", "numerator", "denominator", mode="before")
    @classmethod
    def reject_boolean_measurements(cls, value):
        if isinstance(value, bool):
            raise ValueError("Boolean values are not numeric measurements")
        return value


class SegmentPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment: str = Field(min_length=1, max_length=500)
    baseline: PeriodValue
    current: PeriodValue


class AnalyticalComparison(BaseModel):
    """One complete partition, one metric definition, two comparable periods.

    Totals must come from a controlling source query, not be filled in from the
    segment sum merely to make the check pass. Coverage and comparability are
    assertions from the adapter's reviewed measurement contract.

    Inputs are finite measurements, not booleans. Reconciliation allows one
    nearest-binary-float rounding per supplied aggregate, with no fixed absolute
    tolerance; source-level rounding requires a separate measurement contract.
    Equal elapsed duration is opt-in and never implies time normalization.
    """

    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=160)
    metric: str = Field(min_length=1, max_length=240)
    definition: str = Field(min_length=1, max_length=4000)
    population: str = Field(min_length=1, max_length=1000)
    unit: str = Field(min_length=1, max_length=80)
    dimension: str = Field(min_length=1, max_length=160)
    kind: Literal["additive", "rate"]
    baseline_start: datetime
    baseline_end: datetime
    current_start: datetime
    current_end: datetime
    comparison_window: str = "previous_period"
    coverage: Literal["complete", "partial", "unknown"] = "unknown"
    disjoint_segments: bool = False
    comparable: bool = False
    require_equal_duration: bool = Field(
        default=False,
        description=(
            "Require equal elapsed UTC durations in addition to declared comparability. "
            "By default, comparable calendar-period totals may span unequal durations; "
            "the decomposition does not normalize them by elapsed time."
        ),
    )
    required: bool = True
    query_refs: list[str] = Field(min_length=1, max_length=20)
    baseline_total: PeriodValue
    current_total: PeriodValue
    segments: list[SegmentPair] = Field(min_length=1, max_length=1000)


class SegmentContribution(BaseModel):
    segment: str
    baseline: FiniteFloat
    current: FiniteFloat
    contribution: FiniteFloat
    within_effect: FiniteFloat | None = None
    mix_effect: FiniteFloat | None = None


class AnalysisReport(BaseModel):
    source_key: str
    comparison_key: str
    metric: str
    dimension: str
    unit: str
    method: Literal["additive_contribution_v1", "symmetric_rate_decomposition_v1"]
    status: Literal["complete", "insufficient_data"]
    required: bool
    input_digest: str
    query_refs: list[str]
    comparison: AnalyticalComparison
    baseline: FiniteFloat | None = None
    current: FiniteFloat | None = None
    delta: FiniteFloat | None = None
    residual: FiniteFloat | None = None
    within_effect: FiniteFloat | None = None
    mix_effect: FiniteFloat | None = None
    contributions: list[SegmentContribution] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    claim_type: Literal["accounting_decomposition"] = "accounting_decomposition"
    limitations: list[str] = Field(default_factory=lambda: [
        "Contributions explain the measured difference, not its causal mechanism.",
        "No sampling uncertainty or statistical significance is estimated from these aggregates.",
        "Coverage, population and comparability depend on the source measurement contract.",
    ])


def _rounding_bound(values: list[float]) -> Fraction:
    """One nearest-float rounding per supplied aggregate, with no absolute floor.

    Zero is exact. Fractions retain half-ULP bounds even for subnormals and
    prevent the error budget itself from underflowing or overflowing. This
    admits representation error only, not source rounding to cents or percentages.
    """
    return sum((Fraction(math.ulp(value)) / 2 for value in values if value), Fraction())


def _finite_result(value: Fraction) -> float:
    result = float(value)  # OverflowError is converted to an unavailable report.
    if not math.isfinite(result) or (value and result == 0):
        raise ArithmeticError("Computed value cannot be represented as a finite nonzero float")
    return result


def analyze_comparison(
    source_key: str, comparison: AnalyticalComparison, *, comparison_window: str | None = None
) -> AnalysisReport:
    """Validate first, then decompose; missing values never become zero."""
    report = AnalysisReport(
        source_key=source_key,
        comparison_key=comparison.key,
        metric=comparison.metric,
        dimension=comparison.dimension,
        unit=comparison.unit,
        method=("additive_contribution_v1" if comparison.kind == "additive"
                else "symmetric_rate_decomposition_v1"),
        status="insufficient_data",
        required=comparison.required,
        input_digest=hashlib.sha256(comparison.model_dump_json().encode()).hexdigest(),
        query_refs=comparison.query_refs,
        comparison=comparison,
    )
    issues = report.issues
    if comparison.coverage != "complete":
        issues.append("Segment coverage is not declared complete.")
    if not comparison.disjoint_segments:
        issues.append("Segments are not declared mutually exclusive.")
    if not comparison.comparable:
        issues.append("Metric definitions, population and periods are not declared comparable.")
    if comparison_window and comparison.comparison_window != comparison_window:
        issues.append("Source comparison does not match the card's selected baseline window.")
    dates = [comparison.baseline_start, comparison.baseline_end,
             comparison.current_start, comparison.current_end]
    if any(value.utcoffset() is None for value in dates):
        issues.append("Comparison timestamps must include timezones.")
    else:
        dates = [value.astimezone(timezone.utc) for value in dates]
        if not (dates[0] < dates[1] <= dates[2] < dates[3]):
            issues.append("Periods must be ordered, nonempty and nonoverlapping.")
        elif dates[1] - dates[0] != dates[3] - dates[2]:
            if comparison.require_equal_duration:
                issues.append("Comparison policy requires equal elapsed durations.")
            else:
                report.limitations.append(
                    "Periods have unequal elapsed durations; values are not time-normalized."
                )
    if len({row.segment for row in comparison.segments}) != len(comparison.segments):
        issues.append("Duplicate segment labels make the partition ambiguous.")
    if issues:
        return report

    # model_copy/update and mutable nested models can bypass Pydantic validation.
    for value in [comparison.baseline_total, comparison.current_total,
                  *[value for row in comparison.segments for value in (row.baseline, row.current)]]:
        for field in ("value", "numerator", "denominator"):
            number = getattr(value, field)
            if number is None:
                continue
            try:
                valid = (not isinstance(number, bool) and isinstance(number, (int, float))
                         and math.isfinite(number))
            except OverflowError:
                valid = False
            if not valid:
                issues.append("Measurements must be finite numbers, not booleans.")
                return report

    fields = ["value"] if comparison.kind == "additive" else ["numerator", "denominator"]
    bounds: dict[tuple[str, str], Fraction] = {}
    for period in ("baseline", "current"):
        total = getattr(comparison, period + "_total")
        values = [getattr(row, period) for row in comparison.segments]
        for field in fields:
            expected = getattr(total, field)
            parts = [getattr(value, field) for value in values]
            if expected is None or any(value is None for value in parts):
                issues.append(f"Missing {period} {field}; absent segments are not measured zeros.")
                continue
            reconciled = sum(map(Fraction, parts), Fraction())
            bound = _rounding_bound([expected, *parts])
            bounds[period, field] = bound
            if abs(Fraction(expected) - reconciled) > bound:
                issues.append(f"Segment {period} {field} does not reconcile to the controlling total.")
        if comparison.kind == "rate":
            if any(value.denominator is not None and value.denominator <= 0
                   for value in [total, *values]):
                issues.append(f"{period} rate denominators must be positive; missing strata cannot be imputed.")
            if any(value.numerator is not None and value.numerator < 0 for value in [total, *values]):
                issues.append(f"{period} rate numerators must be nonnegative.")
            if any(value.value is not None for value in [total, *values]):
                issues.append("Rate comparisons use numerators and denominators, not precomputed rates.")
    if issues:
        return report

    try:
        # Exact arithmetic over the supplied binary floats prevents intermediate
        # overflow and cancellation; round only at the public float boundary.
        within_total = mix_total = contribution_total = Fraction()
        if comparison.kind == "additive":
            baseline = Fraction(comparison.baseline_total.value)
            current = Fraction(comparison.current_total.value)
            residual_bound = bounds["baseline", "value"] + bounds["current", "value"]
            for row in comparison.segments:
                contribution = Fraction(row.current.value) - Fraction(row.baseline.value)
                contribution_total += contribution
                report.contributions.append(SegmentContribution(
                    segment=row.segment, baseline=row.baseline.value, current=row.current.value,
                    contribution=_finite_result(contribution),
                ))
        else:
            n0 = Fraction(comparison.baseline_total.denominator)
            n1 = Fraction(comparison.current_total.denominator)
            baseline = Fraction(comparison.baseline_total.numerator) / n0
            current = Fraction(comparison.current_total.numerator) / n1
            residual_bound = bounds["baseline", "numerator"] / n0 + bounds["current", "numerator"] / n1
            for row in comparison.segments:
                r0 = Fraction(row.baseline.numerator) / Fraction(row.baseline.denominator)
                r1 = Fraction(row.current.numerator) / Fraction(row.current.denominator)
                w0 = Fraction(row.baseline.denominator) / n0
                w1 = Fraction(row.current.denominator) / n1
                within = (r1 - r0) * (w0 + w1) / 2
                mix = (w1 - w0) * (r0 + r1) / 2
                within_total += within
                mix_total += mix
                contribution_total += within + mix
                report.contributions.append(SegmentContribution(
                    segment=row.segment, baseline=_finite_result(r0), current=_finite_result(r1),
                    contribution=_finite_result(within + mix),
                    within_effect=_finite_result(within), mix_effect=_finite_result(mix),
                ))
            report.within_effect = _finite_result(within_total)
            report.mix_effect = _finite_result(mix_total)
        delta = current - baseline
        if abs(delta - contribution_total) > residual_bound:
            raise ArithmeticError("Computed decomposition does not reconcile")
        report.baseline = _finite_result(baseline)
        report.current = _finite_result(current)
        report.delta = _finite_result(delta)
        # Expose the residual of the returned, rounded contributions as well.
        residual = Fraction(report.delta) - sum(
            (Fraction(row.contribution) for row in report.contributions), Fraction()
        )
        output_bound = _rounding_bound([report.delta, *[row.contribution for row in report.contributions]])
        if abs(residual) > residual_bound + output_bound:
            raise ArithmeticError("Rounded decomposition does not reconcile")
        report.residual = _finite_result(residual)
    except (ArithmeticError, ValueError):
        report.issues.append("Computed decomposition is unrepresentable or does not reconcile.")
        report.contributions = []
        report.baseline = report.current = report.delta = report.residual = None
        report.within_effect = report.mix_effect = None
        return report
    report.contributions.sort(key=lambda row: (-abs(row.contribution), row.segment))
    report.status = "complete"
    return report

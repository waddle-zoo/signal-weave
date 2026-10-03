"""Small, deterministic numeric projections for approved insight cards.

Numeric conditions are deliberately not a policy language.  They bind one
approved source and one analytical comparison to a single measurement and
return a typed result for the parent engine to interpret alongside Jev.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    field_validator,
    model_validator,
)

from .diagnostics import AnalysisReport, analyze_comparison

NumericMeasurement = Literal[
    "baseline", "current", "delta", "contribution", "within_effect", "mix_effect"
]
NumericComparator = Literal["<", "<=", "==", ">=", ">", "!="]
NumericConditionStatus = Literal["true", "false", "unknown"]


class NumericCondition(BaseModel):
    """One owner-authored numeric check over one approved analytical binding."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    source_key: str = Field(
        min_length=1,
        max_length=120,
        description="Exact selected_sources.key for the source supplying this comparison.",
    )
    comparison_key: str = Field(
        min_length=1,
        max_length=160,
        description="Exact AnalyticalComparison.key, not a comparison-window name.",
    )
    measurement: NumericMeasurement = Field(
        description=(
            "Select total baseline, current, delta, a symmetric rate within_effect or "
            "mix_effect, or a segment contribution. Within/mix effects require the "
            "symmetric_rate_decomposition_v1 report method and never accept a segment. "
            "Segment contribution may use segment=null for any segment or an exact "
            "segment label."
        )
    )
    segment: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Only for contribution checks: null checks any segment; a string matches "
            "that exact label. Aggregate effects never accept a segment."
        ),
    )
    unit: str = Field(min_length=1, max_length=80)
    threshold: FiniteFloat
    comparator: NumericComparator
    absolute: StrictBool = Field(default=False, description=(
        "False preserves the signed value (including current-minus-baseline changes). "
        "True takes abs(value) and can match BOTH increases and decreases. Use true only "
        "when the owner explicitly asks for magnitude regardless of direction, never "
        "merely because a threshold is expressed in units rather than percent."
    ))

    @field_validator("threshold", mode="before")
    @classmethod
    def reject_boolean_or_nonfinite_threshold(cls, value):
        if isinstance(value, bool):
            raise ValueError("numeric condition thresholds must be finite numbers, not booleans")
        try:
            if not math.isfinite(float(value)):
                raise ValueError("numeric condition thresholds must be finite")
        except (TypeError, ValueError, OverflowError) as error:
            if isinstance(error, ValueError) and str(error) == "numeric condition thresholds must be finite":
                raise
            raise ValueError("numeric condition thresholds must be finite numbers") from error
        return value

    @field_validator("text", "source_key", "comparison_key", "unit")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("numeric condition fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_selector(self) -> NumericCondition:
        if self.measurement != "contribution" and self.segment is not None:
            raise ValueError("segment selector is only valid for contribution conditions")
        if self.segment is not None and not self.segment.strip():
            raise ValueError("segment selector must not be blank")
        if self.absolute and self.threshold < 0:
            raise ValueError("absolute numeric conditions require a non-negative threshold")
        return self


class NumericConditionResult(BaseModel):
    """A numeric condition outcome with enough evidence to audit its meaning."""

    model_config = ConfigDict(extra="forbid")

    condition_text: str
    source_key: str = Field(description="Selected SourceRef.key bound to this condition.")
    comparison_key: str = Field(description="Exact AnalyticalComparison.key, not a comparison-window name.")
    measurement: NumericMeasurement
    segment: str | None = None
    matched_segment: str | None = None
    comparator: NumericComparator
    threshold: FiniteFloat
    absolute: bool = False
    status: NumericConditionStatus
    value: FiniteFloat | None = None
    unit: str | None = None
    expected_unit: str
    query_refs: list[str] = Field(default_factory=list, max_length=20)
    provenance: list[str] = Field(default_factory=list, max_length=50)
    analysis_input_digest: str | None = None
    reason: str = ""


def _compare(value: float, comparator: NumericComparator, threshold: float) -> bool:
    return {
        "<": value < threshold,
        "<=": value <= threshold,
        "==": value == threshold,
        ">=": value >= threshold,
        ">": value > threshold,
        "!=": value != threshold,
    }[comparator]


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _matching_reports(condition: NumericCondition, analyses: Iterable[AnalysisReport]) -> list[AnalysisReport]:
    return [
        report
        for report in analyses
        if report.source_key == condition.source_key
        and report.comparison_key == condition.comparison_key
    ]


def _trusted_report(report: AnalysisReport) -> AnalysisReport | None:
    """Accept only the derived fields reproducible from its embedded comparison."""
    try:
        validated = AnalysisReport.model_validate(report.model_dump(mode="python"))
        recomputed = analyze_comparison(
            validated.source_key,
            validated.comparison,
            comparison_window=validated.comparison.comparison_window,
        )
    except (TypeError, ValueError, OverflowError, ArithmeticError):
        return None
    derived_fields = (
        "source_key",
        "comparison_key",
        "metric",
        "dimension",
        "unit",
        "method",
        "status",
        "input_digest",
        "query_refs",
        "baseline",
        "current",
        "delta",
        "residual",
        "within_effect",
        "mix_effect",
        "contributions",
    )
    if any(getattr(validated, field) != getattr(recomputed, field) for field in derived_fields):
        return None
    return validated


def _result(
    condition: NumericCondition,
    *,
    status: NumericConditionStatus,
    report: AnalysisReport | None = None,
    value: float | None = None,
    reason: str = "",
    matched_segment: str | None = None,
) -> NumericConditionResult:
    return NumericConditionResult(
        condition_text=condition.text,
        source_key=condition.source_key,
        comparison_key=condition.comparison_key,
        measurement=condition.measurement,
        segment=condition.segment,
        matched_segment=matched_segment,
        comparator=condition.comparator,
        threshold=condition.threshold,
        absolute=condition.absolute,
        status=status,
        value=value,
        unit=report.unit if report else None,
        expected_unit=condition.unit,
        query_refs=list(report.query_refs) if report else [],
        provenance=list(report.query_refs) if report else [],
        analysis_input_digest=report.input_digest if report else None,
        reason=reason,
    )


def _evaluate_one(condition: NumericCondition, analyses: Iterable[AnalysisReport]) -> NumericConditionResult:
    matches = _matching_reports(condition, analyses)
    if len(matches) != 1:
        return _result(
            condition,
            status="unknown",
            reason=(
                "No unique matching analysis report was available."
                if not matches
                else "Multiple matching analysis reports make the binding ambiguous."
            ),
        )
    report = _trusted_report(matches[0])
    if report is None:
        return _result(condition, status="unknown", reason="Matching analysis failed reproducibility checks.")
    if report.status != "complete":
        return _result(condition, status="unknown", report=report, reason="Matching analysis is incomplete.")
    if report.unit != condition.unit:
        return _result(condition, status="unknown", report=report, reason="Condition unit does not match analysis unit.")
    if not _finite(report.baseline) or not _finite(report.current) or not _finite(report.delta):
        return _result(condition, status="unknown", report=report, reason="Matching analysis has no finite total value.")

    if condition.measurement in {"within_effect", "mix_effect"}:
        if report.method != "symmetric_rate_decomposition_v1":
            return _result(
                condition,
                status="unknown",
                report=report,
                reason="Within/mix effects require a symmetric rate decomposition report.",
            )
        effect = getattr(report, condition.measurement)
        if not _finite(effect):
            return _result(
                condition,
                status="unknown",
                report=report,
                reason=f"Matching analysis has no finite {condition.measurement}.",
            )
        value = abs(effect) if condition.absolute else effect
        return _result(
            condition,
            status="true" if _compare(value, condition.comparator, condition.threshold) else "false",
            report=report,
            value=value,
        )
    if condition.measurement == "contribution":
        contributions = [
            row for row in report.contributions if _finite(row.contribution)
        ]
        if not contributions:
            return _result(condition, status="unknown", report=report, reason="Matching analysis has no finite contributions.")
        if condition.segment is None:
            checks = [
                (_finite(abs(row.contribution) if condition.absolute else row.contribution), row.segment,
                 abs(row.contribution) if condition.absolute else row.contribution)
                for row in contributions
            ]
            checks = [item for item in checks if item[0]]
            if len(checks) != len(contributions):
                return _result(condition, status="unknown", report=report, reason="A contribution is nonfinite.")
            matched = [item for item in checks if _compare(item[2], condition.comparator, condition.threshold)]
            status: NumericConditionStatus = "true" if matched else "false"
            chosen = matched[0] if matched else None
            return _result(
                condition,
                status=status,
                report=report,
                value=chosen[2] if chosen else None,
                matched_segment=chosen[1] if chosen else None,
            )
        selected = [row for row in contributions if row.segment == condition.segment]
        if len(selected) != 1:
            return _result(condition, status="unknown", report=report, reason="The exact segment selector was missing or ambiguous.")
        value = selected[0].contribution
    else:
        value = getattr(report, condition.measurement)
    value = abs(value) if condition.absolute else value
    return _result(
        condition,
        status="true" if _compare(value, condition.comparator, condition.threshold) else "false",
        report=report,
        value=value,
        matched_segment=(selected[0].segment if condition.measurement == "contribution" else None),
    )


def evaluate_numeric_conditions(card, analyses: Iterable[AnalysisReport]) -> list[NumericConditionResult]:
    """Evaluate a card's numeric conditions without selecting an action.

    Every condition requires exactly one complete matching report. Missing,
    incomplete, nonfinite, or ambiguous evidence is ``unknown`` and never
    coerced to ``false``.
    """

    reports = tuple(analyses)
    return [_evaluate_one(condition, reports) for condition in card.numeric_conditions]


__all__ = [
    "NumericComparator",
    "NumericCondition",
    "NumericConditionResult",
    "NumericConditionStatus",
    "NumericMeasurement",
    "evaluate_numeric_conditions",
]

"""Bounded, deterministic investigation report artifacts.

This module deliberately sits after evaluation.  It does not interpret Jev
text, call a model, or turn observations into new analytical facts.  Numeric
claims are copied only from an :class:`AnalysisReport` that can be validated
and reproduced by :func:`signalweave.diagnostics.analyze_comparison`.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from html import escape
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from .diagnostics import AnalysisReport, SegmentContribution, analyze_comparison
from .models import EvidencePlan, InsightCard, InsightResult, ResourceSnapshot

ReportStatus = Literal["complete", "partial", "blocked"]
CoverageStatus = Literal[
    "satisfied", "missing", "insufficient_data", "failed", "not_requested"
]


class PeriodProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime


class AnalysisProvenance(BaseModel):
    """The source contract that gives a numeric claim its meaning."""

    model_config = ConfigDict(extra="forbid")

    source_key: str
    comparison_key: str
    query_refs: list[str] = Field(min_length=1)
    definition: str = Field(min_length=1)
    population: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    baseline_period: PeriodProvenance
    current_period: PeriodProvenance
    coverage: Literal["complete", "partial", "unknown"]
    comparable: bool
    input_digest: str = Field(min_length=1)


class NumericClaim(BaseModel):
    """A lossless whitelist of values produced by a validated analysis."""

    model_config = ConfigDict(extra="forbid")

    source_key: str
    comparison_key: str
    metric: str
    dimension: str
    unit: str
    method: Literal["additive_contribution_v1", "symmetric_rate_decomposition_v1"]
    claim_type: Literal["accounting_decomposition"]
    baseline: FiniteFloat
    current: FiniteFloat
    delta: FiniteFloat
    residual: FiniteFloat
    within_effect: FiniteFloat | None = None
    mix_effect: FiniteFloat | None = None
    contributions: list[SegmentContribution] = Field(default_factory=list)
    provenance_key: str


class CoverageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    kind: Literal["source", "analysis", "evidence_slot", "question", "watch"]
    required: bool
    status: CoverageStatus
    source_keys: list[str] = Field(default_factory=list)
    detail: str = ""


class ReportIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    reference: str | None = None
    source_keys: list[str] = Field(default_factory=list)


class IntendedRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    outcome: str
    label: str
    destination: str
    reason: str


class InvestigationReport(BaseModel):
    """A bounded report artifact, not a certification of source truth."""

    model_config = ConfigDict(extra="forbid")

    card_id: str
    title: str
    outcome: str
    purpose: str
    next_step: str | None = None
    status: ReportStatus
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    provenance: list[AnalysisProvenance] = Field(default_factory=list)
    coverage: list[CoverageRecord] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    intended_routes_not_delivered: list[IntendedRoute] = Field(default_factory=list)
    blockers: list[ReportIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evaluated_at: datetime
    evaluator: str


def _analysis_key(report: AnalysisReport) -> tuple[str, str]:
    """Keep opaque source/comparison identities separate; either may contain ``:``."""

    return report.source_key, report.comparison_key


def _analysis_label(key: tuple[str, str]) -> str:
    return json.dumps(list(key), ensure_ascii=False, separators=(",", ":"))


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _issue(
    code: str,
    message: str,
    *,
    reference: str | None = None,
    source_keys: list[str] | None = None,
) -> ReportIssue:
    return ReportIssue(
        code=code,
        message=message,
        reference=reference,
        source_keys=source_keys or [],
    )


def _validated_recomputed_analysis(
    report: AnalysisReport,
) -> tuple[AnalysisReport | None, str | None]:
    """Revalidate a possibly replayed/mutated report and recompute its numbers."""

    try:
        validated = AnalysisReport.model_validate(report.model_dump(mode="python"))
    except (ValidationError, TypeError, ValueError) as error:
        return None, f"Analysis report failed validation: {error}"

    recomputed = analyze_comparison(
        validated.source_key,
        validated.comparison,
        comparison_window=validated.comparison.comparison_window,
    )
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
        return None, "Analysis report does not match a fresh deterministic recomputation."
    return recomputed, None


def _source_requirements(
    card: InsightCard, resources: list[ResourceSnapshot] | None
) -> set[tuple[str, str]]:
    requirements = _required_analysis_keys(card)
    if resources is not None:
        for resource in resources:
            source = next((item for item in card.sources if item.key == resource.source_key), None)
            if source is not None and source.required:
                requirements.update(
                    (resource.source_key, key)
                    for key in resource.contract.required_comparison_keys
                )
    return requirements


def _required_analysis_keys(card: InsightCard) -> set[tuple[str, str]]:
    return {
        (source.key, comparison_key)
        for source in card.sources
        if source.required
        for comparison_key in source.required_comparison_keys
    }


def _append_plan_coverage(
    coverage: list[CoverageRecord],
    blockers: list[ReportIssue],
    warnings: list[str],
    plan: EvidencePlan | None,
) -> None:
    if plan is None:
        return
    if plan.status == "blocked":
        blockers.append(_issue(
            "evidence_plan_blocked",
            "The typed evidence plan is blocked.",
        ))
    for slot in plan.slots:
        if slot.status == "fulfilled":
            status: CoverageStatus = "satisfied"
        elif slot.status == "unavailable":
            status = "failed"
        elif slot.status == "conflicting":
            status = "insufficient_data"
        else:
            status = "missing"
        coverage.append(CoverageRecord(
            key=slot.key,
            kind="evidence_slot",
            required=slot.required,
            status=status,
            source_keys=list(slot.source_keys),
            detail=slot.completion_criteria or slot.question,
        ))
        if status != "satisfied":
            message = f"Evidence slot {slot.key} is {slot.status}."
            if slot.required:
                blockers.append(_issue(
                    "required_evidence_missing" if status == "missing" else "required_evidence_failed",
                    message,
                    reference=slot.key,
                    source_keys=list(slot.source_keys),
                ))
            else:
                warnings.append(message)


def _append_semantic_coverage(
    card: InsightCard,
    result: InsightResult,
    coverage: list[CoverageRecord],
    unresolved: list[str],
    warnings: list[str],
) -> None:
    question_results = list(result.question_results)
    for index, question in enumerate(card.questions, start=1):
        candidate_keys = {f"question:{index}", f"question_{index - 1}", str(index - 1)}
        matched = next((item for item in question_results if item.key in candidate_keys), None)
        matched_status = (
            getattr(matched.status, "value", matched.status) if matched is not None else None
        )
        supported = matched_status in {"supported", "not_supported", "contradicted"}
        coverage.append(CoverageRecord(
            key=f"question:{index}",
            kind="question",
            required=card.evidence_requirements.get(f"question:{index}", True),
            status="satisfied" if supported else "missing",
            detail=question,
        ))
        if not supported:
            unresolved.append(question)
            if not card.evidence_requirements.get(f"question:{index}", True):
                warnings.append(f"Optional question {index} remains unresolved.")

    for index, watch in enumerate(card.watch_for, start=1):
        candidate_keys = {f"watch:{index}", f"watch_{index - 1}", str(index - 1)}
        matched = next((item for item in result.watch_results if item.key in candidate_keys), None)
        fulfilled = matched is not None and matched.status.value in {"present", "absent"}
        coverage.append(CoverageRecord(
            key=f"watch:{index}",
            kind="watch",
            required=card.evidence_requirements.get(f"watch:{index}", True),
            status="satisfied" if fulfilled else "missing",
            detail=watch,
        ))
        if not fulfilled:
            unresolved.append(watch)
            if not card.evidence_requirements.get(f"watch:{index}", True):
                warnings.append(f"Optional watch item {index} remains unresolved.")


def _route_records(
    card: InsightCard, result: InsightResult
) -> tuple[list[IntendedRoute], list[str], list[ReportIssue]]:
    configured = {method.key: method for method in card.delivery_methods}
    selected: list[IntendedRoute] = []
    blockers: list[ReportIssue] = []
    for method in result.delivery_methods:
        approved = configured.get(method.key)
        if approved is None:
            blockers.append(_issue(
                "unauthorized_route",
                f"Result selected unconfigured route {method.key}; no new destination is accepted.",
                reference=method.key,
            ))
            continue
        if approved.outcome != method.outcome:
            blockers.append(_issue(
                "route_outcome_mismatch",
                f"Result route {method.key} does not match its configured outcome.",
                reference=method.key,
            ))
            continue
        if method.destination != approved.destination:
            blockers.append(_issue(
                "route_endpoint_mismatch",
                f"Result route {method.key} changed the configured destination.",
                reference=method.key,
            ))
            continue
        selected.append(IntendedRoute(
            key=method.key,
            outcome=approved.outcome.value,
            label=approved.label,
            destination=approved.destination,
            reason="Caller owns delivery; not sent.",
        ))
    outcome = result.outcome.value
    selected_keys = {item.key for item in selected}
    gaps = [
        f"Configured route {method.key} was not selected for outcome {outcome}."
        for method in card.delivery_methods
        if method.outcome.value == outcome and method.key not in selected_keys
    ]
    return selected, gaps, blockers


def build_investigation_report(
    card: InsightCard,
    result: InsightResult,
    resources: list[ResourceSnapshot] | None = None,
) -> InvestigationReport:
    """Build a bounded report from an already evaluated card/result pair."""

    analyses = list(result.analyses)
    blockers: list[ReportIssue] = []
    warnings: list[str] = []
    limitations: list[str] = [
        "This artifact reports bounded analytical coverage; it is not independently certified truth.",
        "Accounting contributions explain measured differences and do not establish causality or mechanism.",
    ]
    coverage: list[CoverageRecord] = []
    provenance: list[AnalysisProvenance] = []
    numeric_claims: list[NumericClaim] = []

    if result.card_id != card.id:
        blockers.append(_issue(
            "result_card_mismatch",
            "Insight result card_id does not match the requested card.",
            reference=result.card_id,
        ))

    identities = [(_analysis_key(item), item) for item in analyses]
    duplicate_keys = {
        key for key in {item_key for item_key, _ in identities}
        if sum(item_key == key for item_key, _ in identities) > 1
    }
    for key in sorted(duplicate_keys):
        source_key = next(item.source_key for item_key, item in identities if item_key == key)
        blockers.append(_issue(
            "duplicate_analysis",
            f"Analysis identity {_analysis_label(key)} was returned more than once.",
            reference=_analysis_label(key),
            source_keys=[source_key],
        ))

    recomputed_by_key: dict[tuple[str, str], AnalysisReport] = {}
    for analysis in analyses:
        key = _analysis_key(analysis)
        recomputed, error = _validated_recomputed_analysis(analysis)
        if error:
            blockers.append(_issue(
                "invalid_analysis",
                error,
                reference=_analysis_label(key),
                source_keys=[analysis.source_key],
            ))
            coverage.append(CoverageRecord(
                key=_analysis_label(key),
                kind="analysis",
                required=analysis.required,
                status="failed" if analysis.status == "complete" else "insufficient_data",
                source_keys=[analysis.source_key],
                detail=error,
            ))
            continue
        assert recomputed is not None
        recomputed_by_key[key] = recomputed
        coverage.append(CoverageRecord(
            key=_analysis_label(key),
            kind="analysis",
            required=analysis.required,
            status="satisfied" if recomputed.status == "complete" else "insufficient_data",
            source_keys=[analysis.source_key],
            detail="Validated and recomputed from the source comparison contract.",
        ))
        if recomputed.status != "complete":
            message = "Analysis is insufficient_data and supplies no numeric claim."
            if analysis.required:
                blockers.append(_issue(
                    "required_analysis_insufficient_data",
                    message,
                    reference=_analysis_label(key),
                    source_keys=[analysis.source_key],
                ))
            else:
                warnings.append(
                    f"Optional analysis {_analysis_label(key)} is insufficient_data."
                )
            limitations.extend(recomputed.issues)
            continue

        if key in duplicate_keys:
            # The recomputation is useful for the audit trail, but duplicate
            # identities are never allowed to contribute a numeric claim.
            continue

        comparison = recomputed.comparison
        try:
            provenance_item = AnalysisProvenance(
                source_key=recomputed.source_key,
                comparison_key=recomputed.comparison_key,
                query_refs=list(comparison.query_refs),
                definition=comparison.definition,
                population=comparison.population,
                metric=recomputed.metric,
                dimension=recomputed.dimension,
                unit=recomputed.unit,
                baseline_period=PeriodProvenance(
                    start=comparison.baseline_start, end=comparison.baseline_end
                ),
                current_period=PeriodProvenance(
                    start=comparison.current_start, end=comparison.current_end
                ),
                coverage=comparison.coverage,
                comparable=comparison.comparable,
                input_digest=recomputed.input_digest,
            )
        except ValidationError as error:
            blockers.append(_issue(
                "missing_analysis_provenance",
                f"Complete analysis {_analysis_label(key)} lacks required source/query/period/definition provenance: {error}",
                reference=_analysis_label(key),
                source_keys=[recomputed.source_key],
            ))
            continue
        provenance.append(provenance_item)
        try:
            claim = NumericClaim(
                source_key=recomputed.source_key,
                comparison_key=recomputed.comparison_key,
                metric=recomputed.metric,
                dimension=recomputed.dimension,
                unit=recomputed.unit,
                method=recomputed.method,
                claim_type=recomputed.claim_type,
                baseline=recomputed.baseline,
                current=recomputed.current,
                delta=recomputed.delta,
                residual=recomputed.residual,
                within_effect=recomputed.within_effect,
                mix_effect=recomputed.mix_effect,
                contributions=list(recomputed.contributions),
                provenance_key=_analysis_label(key),
            )
        except (ValidationError, TypeError, ValueError) as error:
            blockers.append(_issue(
                "invalid_numeric_claim",
                f"Complete analysis {_analysis_label(key)} produced invalid numeric values: {error}",
                reference=_analysis_label(key),
                source_keys=[recomputed.source_key],
            ))
            continue
        if not all(
            _finite(getattr(claim, field))
            for field in ("baseline", "current", "delta", "residual")
        ):
            blockers.append(_issue(
                "non_finite_numeric_claim",
                f"Complete analysis {_analysis_label(key)} contains a non-finite numeric value.",
                reference=_analysis_label(key),
                source_keys=[recomputed.source_key],
            ))
            continue
        numeric_claims.append(claim)

    required_keys = _source_requirements(card, resources)
    present_pairs = {
        (item.source_key, item.comparison_key) for item in recomputed_by_key.values()
    }
    for source_key, comparison_key in sorted(required_keys - present_pairs):
        blockers.append(_issue(
            "required_analysis_missing",
            f"Required analytical comparison {comparison_key} was not returned for source {source_key}.",
            reference=_analysis_label((source_key, comparison_key)),
            source_keys=[source_key],
        ))
        coverage.append(CoverageRecord(
            key=_analysis_label((source_key, comparison_key)),
            kind="analysis",
            required=True,
            status="missing",
            source_keys=[source_key],
            detail="Required comparison was not returned.",
        ))

    delivered_sources = set(result.source_keys)
    structured_failed_sources: set[str] = set()
    if result.evidence_plan is not None:
        for slot in result.evidence_plan.slots:
            if slot.required and slot.status in {"unavailable", "conflicting"}:
                structured_failed_sources.update(slot.source_keys)
    resources_by_key: dict[str, ResourceSnapshot] = {}
    duplicate_resource_keys: set[str] = set()
    if resources is not None:
        for resource in resources:
            if resource.source_key in resources_by_key:
                duplicate_resource_keys.add(resource.source_key)
            resources_by_key[resource.source_key] = resource
    else:
        warnings.append("Source health was not supplied; source contract coverage is unassessed.")
    for source in card.sources:
        resource = resources_by_key.get(source.key)
        if source.key in structured_failed_sources:
            status = "failed"
            detail = "A required typed evidence slot reports this source as unavailable."
        elif source.key in duplicate_resource_keys:
            status = "failed"
            detail = "More than one source snapshot was supplied for this source key."
        elif resources is not None and resource is None:
            status = "missing"
            detail = "No source snapshot was supplied for this card source."
        elif resource is not None and (resource.error or resource.contract.source_status == "failed"):
            status = "failed"
            detail = resource.error or "Source contract status is failed."
        elif resource is not None and resource.contract.source_status != "healthy":
            status = "failed"
            detail = f"Source contract status is {resource.contract.source_status}."
        elif source.key not in delivered_sources:
            status = "missing"
            detail = "No source evidence was returned for this card source."
        else:
            status = "satisfied"
            detail = "Source evidence was returned; analytical completeness is assessed separately."
        coverage.append(CoverageRecord(
            key=source.key,
            kind="source",
            required=source.required,
            status=status,
            source_keys=[source.key],
            detail=detail,
        ))
        if status != "satisfied":
            message = f"Source {source.key} is {status}."
            if source.required:
                blockers.append(_issue(
                    "required_source_failed" if status == "failed" else "required_source_missing",
                    message,
                    reference=source.key,
                    source_keys=[source.key],
                ))
            else:
                warnings.append(f"Optional source {source.key} is {status}.")

    if result.outcome.value == "insufficient_data":
        blockers.append(_issue(
            "result_insufficient_data",
            "The evaluated result is insufficient_data; this report cannot claim complete coverage.",
        ))
    _append_plan_coverage(coverage, blockers, warnings, result.evidence_plan)
    if result.evidence_plan is None:
        warnings.append("Evidence plan was not supplied; coverage is unassessed.")
    elif result.evidence_plan.status != "complete":
        warnings.append(
            f"Evidence plan is {result.evidence_plan.status}; complete coverage is not established."
        )
    unresolved: list[str] = []
    _append_semantic_coverage(card, result, coverage, unresolved, warnings)
    for item in coverage:
        if item.status == "missing" and item.required and item.kind in {"question", "watch"}:
            blockers.append(_issue(
                "required_semantic_evidence_missing",
                f"Required {item.kind} evidence {item.key} is unresolved.",
                reference=item.key,
                source_keys=item.source_keys,
            ))

    route_records, route_gaps, route_blockers = _route_records(card, result)
    warnings.extend(route_gaps)
    blockers.extend(route_blockers)

    if result.investigation is not None:
        limitations.extend(result.investigation.warnings)
    if result.evidence_plan is not None:
        limitations.extend(result.evidence_plan.warnings)

    if blockers:
        status: ReportStatus = "blocked"
    elif warnings or unresolved or not numeric_claims:
        status = "partial"
        if not numeric_claims:
            limitations.append("No validated quantitative analysis was available for this report.")
    else:
        status = "complete"

    return InvestigationReport(
        card_id=card.id,
        title=card.title,
        outcome=result.outcome.value,
        purpose=card.why_watch,
        next_step=(result.workflow.instructions if result.workflow is not None else None),
        status=status,
        numeric_claims=numeric_claims,
        provenance=provenance,
        coverage=coverage,
        limitations=list(dict.fromkeys(limitations)),
        unresolved_questions=list(dict.fromkeys(unresolved)),
        intended_routes_not_delivered=route_records,
        blockers=blockers,
        warnings=list(dict.fromkeys(warnings)),
        evaluated_at=result.evaluated_at,
        evaluator=result.evaluator,
    )


def _md(value: Any) -> str:
    """Escape untrusted card/source text for compact Markdown."""

    text = str(value).replace("\r", " ").replace("\n", " ")
    text = escape(text, quote=False).replace("\\", "\\\\")
    return "".join(f"\\{char}" if char in "[]()*_!|#`" else char for char in text)


def _number(value: float | None) -> str:
    return "—" if value is None else format(value, ".12g")


def render_investigation_report(report: InvestigationReport) -> str:
    """Render a concise Markdown artifact without adding interpretation."""

    lines = [
        f"# Investigation report: {_md(report.title)}",
        "",
        f"- Status: **{_md(report.status)}**",
        f"- Decision: **{_md(report.outcome)}**",
        f"- Purpose: {_md(report.purpose)}",
        f"- Card: `{_md(report.card_id)}`",
        f"- Evaluator: {_md(report.evaluator)}",
    ]
    if report.next_step:
        lines.extend([
            "",
            "## Suggested next step",
            f"- {_md(report.next_step)} (caller-owned handoff; not a verified fact.)",
        ])
    if report.intended_routes_not_delivered:
        lines.extend([
            "",
            "## Intended destinations not sent",
            *(
                f"- `{_md(route.key)}` → {_md(route.destination)}: {_md(route.reason)}"
                for route in report.intended_routes_not_delivered
            ),
        ])
    lines.extend(["", "## Validated measurements"])
    if report.numeric_claims:
        for claim in report.numeric_claims:
            lines.append(
                f"- **{_md(claim.metric)}** ({_md(claim.unit)}): "
                f"{_number(claim.baseline)} → {_number(claim.current)} "
                f"(measured difference {_number(claim.delta)}; method `{_md(claim.method)}`)."
            )
            if claim.within_effect is not None or claim.mix_effect is not None:
                lines.append(
                    f"  - Accounting effects: within {_number(claim.within_effect)}, "
                    f"mix {_number(claim.mix_effect)}. These do not establish causality."
                )
            if claim.contributions:
                contributions = ", ".join(
                    f"{_md(item.segment)}: {_number(item.contribution)}"
                    for item in claim.contributions
                )
                lines.append(f"  - Accounting contributions: {contributions}.")
    else:
        lines.append("- No validated quantitative claims.")

    lines.extend(["", "## Coverage"])
    for item in report.coverage:
        requirement = "required" if item.required else "optional"
        lines.append(f"- `{_md(item.key)}` — {_md(item.status)} ({requirement}).")
    if not report.coverage:
        lines.append("- No evidence coverage was supplied.")

    if report.provenance:
        lines.extend(["", "## Provenance"])
        for item in report.provenance:
            lines.append(
                f"- `{_md(item.source_key)}:{_md(item.comparison_key)}` — "
                f"definition: {_md(item.definition)}; population: {_md(item.population)}; "
                f"queries: {_md(', '.join(item.query_refs))}; "
                f"periods: {_md(item.baseline_period.start.isoformat())} to "
                f"{_md(item.baseline_period.end.isoformat())}, then "
                f"{_md(item.current_period.start.isoformat())} to "
                f"{_md(item.current_period.end.isoformat())}."
            )

    if report.limitations:
        lines.extend(["", "## Limitations"])
        lines.extend(f"- {_md(item)}" for item in report.limitations)
    if report.unresolved_questions:
        lines.extend(["", "## Unresolved questions"])
        lines.extend(f"- {_md(item)}" for item in report.unresolved_questions)
    if report.blockers:
        lines.extend(["", "## Blockers"])
        lines.extend(f"- `{_md(item.code)}`: {_md(item.message)}" for item in report.blockers)
    if report.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {_md(item)}" for item in report.warnings)
    return "\n".join(lines).strip() + "\n"

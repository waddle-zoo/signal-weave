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
from .models import EvidencePlan, InsightCard, InsightResult, ResourceSnapshot, SourceRef

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
    judgment: str | None = None
    probability: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)


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
    intended_audience: str
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
    sources: dict[str, SourceRef],
    resources_by_key: dict[str, ResourceSnapshot],
) -> set[tuple[str, str]]:
    requirements = {
        (source.key, comparison_key)
        for source in sources.values()
        if source.required
        for comparison_key in source.required_comparison_keys
    }
    for source in sources.values():
        resource = resources_by_key.get(source.key)
        if source.required and resource is not None:
            requirements.update(
                (source.key, comparison.key)
                for comparison in resource.analytical_comparisons
                if comparison.required
            )
    return requirements


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
                warnings.append(f"Optional evidence slot {slot.key} is {slot.status}: {slot.question}")


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
        supported = matched_status == "supported"
        coverage.append(CoverageRecord(
            key=f"question:{index}",
            kind="question",
            required=card.evidence_requirements.get(f"question:{index}", True),
            status="satisfied" if supported else "missing",
            detail=question,
            judgment=matched_status,
            probability=matched.probability if matched is not None else None,
        ))
        if not supported:
            unresolved.append(question)
            if not card.evidence_requirements.get(f"question:{index}", True):
                warnings.append(f"Optional question {index} remains unresolved.")

    for index, watch in enumerate(card.watch_for, start=1):
        candidate_keys = {f"watch:{index}", f"watch_{index - 1}", str(index - 1)}
        matched = next((item for item in result.watch_results if item.key in candidate_keys), None)
        matched_status = (
            getattr(matched.status, "value", matched.status) if matched is not None else None
        )
        fulfilled = matched_status in {"present", "absent"}
        coverage.append(CoverageRecord(
            key=f"watch:{index}",
            kind="watch",
            required=card.evidence_requirements.get(f"watch:{index}", True),
            status="satisfied" if fulfilled else "missing",
            detail=watch,
            judgment=(
                matched_status
                if matched is not None else None
            ),
            probability=matched.probability if matched is not None else None,
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
    seen_keys: set[str] = set()
    outcome = result.outcome.value
    for method in result.delivery_methods:
        if method.key in seen_keys:
            blockers.append(_issue(
                "duplicate_route_selection",
                f"Result selected route {method.key} more than once.",
                reference=method.key,
            ))
            continue
        seen_keys.add(method.key)
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
        if method.outcome.value != outcome:
            blockers.append(_issue(
                "route_result_outcome_mismatch",
                f"Result route {method.key} does not match result outcome {outcome}.",
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
    configured_for_outcome = [
        method for method in card.delivery_methods if method.outcome.value == outcome
    ]
    if outcome in {"notify", "escalate"} and not configured_for_outcome:
        blockers.append(_issue(
            "route_not_configured",
            f"Outcome {outcome} has no configured delivery route; the report cannot complete.",
            reference=outcome,
        ))
    selected_keys = {item.key for item in selected}
    gaps = [
        f"Configured route {method.key} was not selected for outcome {outcome}."
        for method in card.delivery_methods
        if method.outcome.value == outcome and method.key not in selected_keys
    ]
    return selected, gaps, blockers


def _analysis_required(
    sources: dict[str, SourceRef],
    key: tuple[str, str],
    comparison: Any | None = None,
) -> bool:
    source_key, comparison_key = key
    source = sources.get(source_key)
    return bool(
        source is not None
        and source.required
        and (
            comparison_key in source.required_comparison_keys
            or (comparison is not None and comparison.required)
        )
    )


def _analysis_snapshot_error(
    sources: dict[str, SourceRef],
    analysis: AnalysisReport,
    recomputed: AnalysisReport,
    resources_by_key: dict[str, ResourceSnapshot],
    duplicate_resource_keys: set[str],
) -> tuple[str, str] | None:
    source = sources.get(analysis.source_key)
    if source is None:
        return (
            "analysis_source_not_approved",
            f"Analysis source {analysis.source_key} is not an approved card source.",
        )
    if analysis.source_key in duplicate_resource_keys:
        return (
            "duplicate_source_snapshot",
            f"More than one source snapshot was supplied for source {analysis.source_key}.",
        )
    resource = resources_by_key.get(analysis.source_key)
    if resource is None:
        return (
            "analysis_source_snapshot_missing",
            f"No source snapshot was supplied for analysis source {analysis.source_key}.",
        )
    if (resource.adapter, resource.resource) != (source.adapter, source.resource):
        return (
            "analysis_source_identity_mismatch",
            f"Analysis source {analysis.source_key} does not match the approved adapter/resource.",
        )
    matches = [
        comparison
        for comparison in resource.analytical_comparisons
        if comparison.key == analysis.comparison_key
    ]
    if not matches:
        return (
            "analysis_snapshot_comparison_missing",
            f"Analysis comparison {analysis.comparison_key} was not returned by source {analysis.source_key}.",
        )
    if len(matches) > 1:
        return (
            "analysis_snapshot_comparison_duplicate",
            f"Source {analysis.source_key} returned comparison {analysis.comparison_key} more than once.",
        )
    if matches[0].model_dump(mode="python") != recomputed.comparison.model_dump(mode="python"):
        return (
            "analysis_snapshot_comparison_mismatch",
            f"Analysis comparison {analysis.comparison_key} does not match the returned source snapshot.",
        )
    return None


def _authorized_sources(
    card: InsightCard, result: InsightResult
) -> tuple[dict[str, SourceRef], list[ReportIssue]]:
    sources = {source.key: source for source in card.sources}
    blockers: list[ReportIssue] = []
    investigation = result.investigation
    if card.investigation_mode.value != "bounded" or investigation is None:
        return sources, blockers
    if investigation.mode.value != "bounded":
        return sources, blockers
    for selection in investigation.selected:
        selected = selection.source
        existing = sources.get(selected.key)
        if existing is not None:
            if (existing.adapter, existing.resource) != (selected.adapter, selected.resource):
                blockers.append(_issue(
                    "investigation_source_identity_mismatch",
                    f"Investigation source {selected.key} conflicts with the approved source identity.",
                    reference=selected.key,
                ))
            continue
        sources[selected.key] = selected
    return sources, blockers


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
    authorized_sources, source_authorization_blockers = _authorized_sources(card, result)
    blockers.extend(source_authorization_blockers)
    resources_by_key: dict[str, ResourceSnapshot] = {}
    duplicate_resource_keys: set[str] = set()
    if resources is not None:
        for resource in resources:
            if resource.source_key in resources_by_key:
                duplicate_resource_keys.add(resource.source_key)
            resources_by_key[resource.source_key] = resource
            if resource.source_key not in authorized_sources:
                blockers.append(_issue(
                    "foreign_resource",
                    f"Source snapshot {resource.source_key} is not authorized by the card or bounded investigation selection.",
                    reference=resource.source_key,
                    source_keys=[resource.source_key],
                ))
    else:
        warnings.append("Source health was not supplied; source contract coverage is unassessed.")

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
            required = _analysis_required(authorized_sources, key)
            blockers.append(_issue(
                "invalid_analysis",
                error,
                reference=_analysis_label(key),
                source_keys=[analysis.source_key],
            ))
            coverage.append(CoverageRecord(
                key=_analysis_label(key),
                kind="analysis",
                required=required,
                status="failed" if analysis.status == "complete" else "insufficient_data",
                source_keys=[analysis.source_key],
                detail=error,
            ))
            continue
        assert recomputed is not None
        required = _analysis_required(authorized_sources, key, recomputed.comparison)
        if analysis.source_key not in authorized_sources:
            message = f"Analysis source {analysis.source_key} is not an approved card source."
            blockers.append(_issue(
                "analysis_source_not_approved",
                message,
                reference=_analysis_label(key),
                source_keys=[analysis.source_key],
            ))
            coverage.append(CoverageRecord(
                key=_analysis_label(key),
                kind="analysis",
                required=False,
                status="failed",
                source_keys=[analysis.source_key],
                detail=message,
            ))
            continue
        if resources is not None:
            binding_error = _analysis_snapshot_error(
                authorized_sources,
                analysis,
                recomputed,
                resources_by_key,
                duplicate_resource_keys,
            )
            if binding_error is not None:
                code, message = binding_error
                blockers.append(_issue(
                    code,
                    message,
                    reference=_analysis_label(key),
                    source_keys=[analysis.source_key],
                ))
                coverage.append(CoverageRecord(
                    key=_analysis_label(key),
                    kind="analysis",
                    required=required,
                    status="failed",
                    source_keys=[analysis.source_key],
                    detail=message,
                ))
                continue
        recomputed_by_key[key] = recomputed
        coverage.append(CoverageRecord(
            key=_analysis_label(key),
            kind="analysis",
            required=required,
            status="satisfied" if recomputed.status == "complete" else "insufficient_data",
            source_keys=[analysis.source_key],
            detail="Validated and recomputed from the source comparison contract.",
        ))
        if recomputed.status != "complete":
            message = "Analysis is insufficient_data and supplies no numeric claim."
            if required:
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

    required_keys = _source_requirements(authorized_sources, resources_by_key)
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
    for source in authorized_sources.values():
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
        elif resource is not None and (
            resource.adapter != source.adapter or resource.resource != source.resource
        ):
            status = "failed"
            detail = (
                "Returned source snapshot identity does not match the approved source reference "
                f"(expected {source.adapter}:{source.resource}, "
                f"got {resource.adapter}:{resource.resource})."
            )
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
            message = f"Source {source.key} is {status}: {detail}"
            if source.required:
                blockers.append(_issue(
                    "required_source_failed" if status == "failed" else "required_source_missing",
                    message,
                    reference=source.key,
                    source_keys=[source.key],
                ))
            else:
                warnings.append(f"Optional source {source.key} is {status}: {detail}")

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
        intended_audience=(
            f"Card owner: {card.owner}" if card.owner else "Card owner and caller-owned delivery workflow"
        ),
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


def _claim_is_provisional(report: InvestigationReport, claim: NumericClaim) -> bool:
    return any(
        item.kind == "source"
        and claim.source_key in item.source_keys
        and item.status != "satisfied"
        for item in report.coverage
    )


def _route_audience(report: InvestigationReport) -> str:
    if report.outcome == "ignore":
        return "No notification intended (quiet outcome)."
    if report.intended_routes_not_delivered:
        audiences = []
        for route in report.intended_routes_not_delivered:
            audience = f"{route.label} ({route.destination})"
            if audience not in audiences:
                audiences.append(audience)
        return "; ".join(audiences)
    return "Card owner"


def _unique_text(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _sorted_claims(claims: list[NumericClaim]) -> list[NumericClaim]:
    """Preserve caller/analysis order across unlike metrics and units."""

    return list(claims)


def _claim_markdown(claim: NumericClaim) -> str:
    line = (
        f"- **{_md(claim.metric)}** ({_md(claim.unit)}): "
        f"{_number(claim.baseline)} → {_number(claim.current)} "
        f"(Δ {_number(claim.delta)}; method `{_md(claim.method)}`)"
    )
    if claim.contributions:
        top = sorted(
            claim.contributions,
            key=lambda item: abs(item.contribution),
            reverse=True,
        )[:3]
        contributions = ", ".join(
            f"{_md(item.segment)}: {_number(item.contribution)}" for item in top
        )
        line += f"; top contributors: {contributions}"
        if len(claim.contributions) > len(top):
            line += f"; plus {len(claim.contributions) - len(top)} smaller"
    return line + "."


def _front_gap_messages(report: InvestigationReport) -> list[str]:
    priority = {
        "result_card_mismatch": 0,
        "required_source_failed": 0,
        "required_source_missing": 0,
        "invalid_analysis": 0,
        "invalid_numeric_claim": 0,
        "non_finite_numeric_claim": 0,
        "duplicate_analysis": 0,
        "required_analysis_missing": 0,
        "required_analysis_insufficient_data": 0,
        "required_evidence_failed": 0,
        "evidence_plan_blocked": 0,
        "result_insufficient_data": 0,
        "required_semantic_evidence_missing": 2,
    }
    indexed = [
        (priority.get(item.code, 1), index, item.message)
        for index, item in enumerate(report.blockers)
    ]
    indexed.extend((3, index, message) for index, message in enumerate(report.warnings))
    indexed.sort(key=lambda item: (item[0], item[1]))
    return _unique_text([message for _, _, message in indexed])


def render_investigation_report(report: InvestigationReport) -> str:
    """Render concise decision front matter plus one collapsed audit appendix."""

    claims = _sorted_claims(report.numeric_claims)
    provisional = any(_claim_is_provisional(report, claim) for claim in claims)
    lines = [
        f"# Investigation report: {_md(report.title)}",
        "",
        f"- Decision: **{_md(report.outcome)}** · Status: **{_md(report.status)}**",
        f"- Intended route audience: {_md(_route_audience(report))}",
        f"- Goal: {_md(report.purpose)}",
    ]
    if report.status == "blocked":
        lines.extend([
            "",
            "**No complete business conclusion is available. Resolve the listed gaps before relying on this report.**",
        ])
    if provisional:
        lines.extend([
            "",
            "**Measurements are provisional: source or coverage requirements are not fully satisfied.**",
        ])

    if claims:
        heading = "## Measured changes (first 3)" if len(claims) > 3 else "## Measured changes"
        lines.extend(["", heading])
        lines.extend(_claim_markdown(claim) for claim in claims[:3])
    else:
        lines.extend(["", "## Measured changes", "- No validated quantitative claims are available."])

    gap_text = _front_gap_messages(report)
    if gap_text:
        lines.extend(["", "## Gaps requiring attention"])
        visible_gaps = gap_text[:3]
        lines.extend(f"- {_md(item)}" for item in visible_gaps)
        if len(gap_text) > len(visible_gaps):
            lines.append(f"- {len(gap_text) - len(visible_gaps)} additional gap(s) in the audit appendix.")

    if report.next_step:
        lines.extend([
            "",
            "## Next step",
            f"- {_md(report.next_step)} (caller-owned handoff; not a verified fact.)",
        ])

    lines.extend([
        "",
        "<details>",
        "<summary>Audit appendix: policy checks, coverage, limitations, and provenance</summary>",
        "",
    ])

    policy_checks = [item for item in report.coverage if item.kind in {"question", "watch"}]
    if policy_checks:
        lines.extend([
            "### Policy checks (Jev judgments)",
            "These are routing signals from evaluated evidence, not proof or confidence in truth.",
        ])
        for item in policy_checks:
            probability_label = "P(present)" if item.kind == "watch" else "P(supported)"
            probability = (
                f"; {probability_label} {_number(item.probability)}"
                if item.probability is not None
                else ""
            )
            lines.append(
                f"- {_md(item.detail)} — judgment: **{_md(item.judgment or 'unassessed')}**"
                f"{probability}."
            )

    if report.blockers:
        lines.extend(["", "### Technical blockers"])
        lines.extend(
            f"- `{_md(item.code)}`: {_md(item.message)}" for item in report.blockers
        )

    if report.intended_routes_not_delivered:
        lines.extend(["", "### Intended routes not delivered"])
        lines.extend(
            f"- `{_md(route.key)}` → `{_md(route.destination)}` "
            f"({_md(route.label)}): {_md(route.reason)}"
            for route in report.intended_routes_not_delivered
        )

    lines.extend(["", "### Coverage"])
    audit_coverage = [item for item in report.coverage if item.kind not in {"question", "watch"}]
    if audit_coverage:
        for item in audit_coverage:
            requirement = "required" if item.required else "optional"
            lines.append(f"- `{_md(item.key)}` — {_md(item.status)} ({requirement}): {_md(item.detail)}")
    else:
        lines.append("- No non-semantic coverage records.")

    if len(claims) > 3:
        lines.extend(["", "### Additional measured changes"])
        lines.extend(_claim_markdown(claim) for claim in claims[3:])

    if report.limitations:
        lines.extend(["", "### Limitations"])
        lines.extend(f"- {_md(item)}" for item in report.limitations)
    if report.warnings:
        lines.extend(["", "### Warnings"])
        lines.extend(f"- {_md(item)}" for item in report.warnings)

    if report.provenance:
        lines.extend(["", "### Provenance"])
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
    lines.extend(["", "</details>"])
    return "\n".join(lines).strip() + "\n"

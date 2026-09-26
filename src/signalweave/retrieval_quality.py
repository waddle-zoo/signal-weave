"""Owner-labeled retrieval evaluation for Jev-ranked source discovery."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from .evaluation import EvaluationDataset, PromotionStatus, _stable_digest, _time_split_overlaps
from .models import ContextSnapshot, InsightCard, PrincipalContext
from .onboarding import InsightAuthoringService


class RetrievalQualityCase(BaseModel):
    """One natural-language onboarding goal with owner-labeled relevant assets."""

    id: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=8000)
    expected_resource_refs: list[str] = Field(default_factory=list, max_length=500)
    acceptable_resource_refs: list[str] = Field(
        default_factory=list,
        max_length=500,
        description=(
            "Owner-approved related resources that may be recommended without being "
            "required for coverage. If empty, expected_resource_refs is the allowed set."
        ),
    )
    required_resource_groups: list[list[str]] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Owner-labeled alternative resources for a required concept. At least one "
            "resource in each group must be recommended."
        ),
    )
    adapter: str | None = None
    limit: int = Field(default=10, ge=1, le=25)
    principal: PrincipalContext | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    dataset: EvaluationDataset = Field(
        default_factory=lambda: EvaluationDataset(dataset_id="unspecified")
    )

    @model_validator(mode="after")
    def validate_unique_refs(self) -> RetrievalQualityCase:
        if len(self.expected_resource_refs) != len(set(self.expected_resource_refs)):
            raise ValueError("expected_resource_refs must be unique")
        if len(self.acceptable_resource_refs) != len(set(self.acceptable_resource_refs)):
            raise ValueError("acceptable_resource_refs must be unique")
        if not set(self.expected_resource_refs) <= set(
            self.acceptable_resource_refs or self.expected_resource_refs
        ):
            raise ValueError("acceptable_resource_refs must include every expected resource")
        flattened = [ref for group in self.required_resource_groups for ref in group]
        if any(not group for group in self.required_resource_groups):
            raise ValueError("required_resource_groups must not contain empty groups")
        if len(flattened) != len(set(flattened)):
            raise ValueError("required_resource_groups must not repeat resources")
        return self


def load_retrieval_quality_cases(path: str | Path) -> list[RetrievalQualityCase]:
    """Load portable retrieval labels while keeping them outside Jev state."""

    payload = json.loads(Path(path).read_text())
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("retrieval fixture must be a JSON list or an object with cases")
    return [RetrievalQualityCase.model_validate(case) for case in raw_cases]


class RetrievalQualityThresholds(BaseModel):
    """Promotion gates for source retrieval, separate from outcome correctness."""

    min_candidate_recall: float = Field(default=0.95, ge=0.0, le=1.0)
    min_recommended_precision: float = Field(default=0.90, ge=0.0, le=1.0)
    min_recommended_recall: float = Field(default=0.90, ge=0.0, le=1.0)
    min_required_group_recall: float = Field(default=0.90, ge=0.0, le=1.0)
    max_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    min_cases: int = Field(default=1, ge=1, le=1_000_000)
    require_dataset_provenance: bool = False
    required_splits: list[str] = Field(default_factory=list, max_length=10)
    max_unauthorized_refs: int = Field(default=0, ge=0)
    require_disjoint_time_splits: bool = False


class _DatasetCase(Protocol):
    id: str
    dataset: EvaluationDataset


def _dataset_preflight(
    cases: Sequence[_DatasetCase], thresholds: RetrievalQualityThresholds
) -> list[str]:
    blockers: list[str] = []
    if thresholds.require_dataset_provenance:
        missing = [case.id for case in cases if case.dataset.split == "unspecified"]
        if missing:
            blockers.append("dataset provenance is required; unspecified cases: " + ", ".join(missing))
    if thresholds.required_splits:
        observed = {case.dataset.split for case in cases}
        missing_splits = sorted(set(thresholds.required_splits) - observed)
        if missing_splits:
            blockers.append("required evaluation splits are missing: " + ", ".join(missing_splits))
    if thresholds.require_disjoint_time_splits and _time_split_overlaps(
        [case.dataset for case in cases]
    ):
        blockers.append("evaluation dataset time partitions overlap across splits")
    return blockers


class RetrievalQualityCaseResult(BaseModel):
    """Inspectable retrieval result showing pool coverage and Jev selection."""

    case_id: str
    expected_resource_refs: list[str] = Field(default_factory=list)
    candidate_refs: list[str] = Field(default_factory=list)
    ranked_refs: list[str] = Field(default_factory=list)
    recommended_refs: list[str] = Field(default_factory=list)
    candidate_recall: float = Field(ge=0.0, le=1.0)
    recommended_precision: float = Field(ge=0.0, le=1.0)
    recommended_recall: float = Field(ge=0.0, le=1.0)
    required_group_recall: float = Field(ge=0.0, le=1.0)
    reciprocal_rank: float = Field(ge=0.0, le=1.0)
    no_match_correct: bool = True
    latency_ms: float = Field(ge=0.0)
    evaluator: str = "unknown"
    error: str | None = None
    tags: list[str] = Field(default_factory=list)
    dataset_id: str = ""
    split: str = "unspecified"
    unauthorized_refs: list[str] = Field(default_factory=list, max_length=500)


class RetrievalQualityReport(BaseModel):
    """Aggregate report separating catalog recall from Jev ranking quality."""

    case_count: int = Field(ge=0)
    successful_case_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    candidate_recall: float = Field(ge=0.0, le=1.0)
    recommended_precision: float = Field(ge=0.0, le=1.0)
    recommended_recall: float = Field(ge=0.0, le=1.0)
    required_group_recall: float = Field(ge=0.0, le=1.0)
    mean_reciprocal_rank: float = Field(ge=0.0, le=1.0)
    no_match_accuracy: float = Field(ge=0.0, le=1.0)
    error_rate: float = Field(ge=0.0, le=1.0)
    median_latency_ms: float = Field(ge=0.0)
    status: Literal["blocked", "shadow", "approved"]
    thresholds: RetrievalQualityThresholds
    preflight_blockers: list[str] = Field(default_factory=list, max_length=100)
    cases: list[RetrievalQualityCaseResult] = Field(default_factory=list, max_length=1_000_000)
    evaluation_id: str = ""
    input_digest: str = ""
    label_digest: str = ""
    dataset_ids: list[str] = Field(default_factory=list, max_length=200)
    splits: list[str] = Field(default_factory=list, max_length=10)
    time_split_disjoint: bool = True
    jev_requests: int = Field(default=0, ge=0)
    jev_input_tokens: int = Field(default=0, ge=0)
    jev_output_tokens: int = Field(default=0, ge=0)
    unauthorized_ref_count: int = Field(default=0, ge=0)


class BundleRetrievalCase(BaseModel):
    """One owner-labeled test of related evidence after a human anchor exists."""

    id: str = Field(min_length=1, max_length=200)
    card: InsightCard
    context: ContextSnapshot | None = None
    expected_related_groups: list[list[str]] = Field(default_factory=list, max_length=100)
    acceptable_related_refs: list[str] = Field(default_factory=list, max_length=500)
    principal: PrincipalContext | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    dataset: EvaluationDataset = Field(
        default_factory=lambda: EvaluationDataset(dataset_id="unspecified")
    )

    @model_validator(mode="after")
    def validate_related_refs(self) -> BundleRetrievalCase:
        if any(not group for group in self.expected_related_groups):
            raise ValueError("expected_related_groups must not contain empty groups")
        flattened = [ref for group in self.expected_related_groups for ref in group]
        if len(flattened) != len(set(flattened)):
            raise ValueError("expected_related_groups must not repeat resources")
        acceptable = set(self.acceptable_related_refs)
        if not acceptable:
            acceptable = set(flattened)
        if not set(flattened) <= acceptable:
            raise ValueError(
                "acceptable_related_refs must include every expected related resource"
            )
        return self


class BundleRetrievalCaseResult(BaseModel):
    """Inspectable result for the graph-assisted evidence bundle path."""

    case_id: str
    candidate_related_refs: list[str] = Field(default_factory=list)
    selected_related_refs: list[str] = Field(default_factory=list)
    candidate_group_recall: float = Field(ge=0.0, le=1.0)
    selected_group_recall: float = Field(ge=0.0, le=1.0)
    selected_precision: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    evaluator: str = "unknown"
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=50)
    error: str | None = None
    tags: list[str] = Field(default_factory=list)
    dataset_id: str = ""
    split: str = "unspecified"
    unauthorized_refs: list[str] = Field(default_factory=list, max_length=500)


class BundleRetrievalReport(BaseModel):
    """Aggregate certification evidence for trusted graph-assisted expansion."""

    case_count: int = Field(ge=0)
    successful_case_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    candidate_group_recall: float = Field(ge=0.0, le=1.0)
    selected_group_recall: float = Field(ge=0.0, le=1.0)
    selected_precision: float = Field(ge=0.0, le=1.0)
    error_rate: float = Field(ge=0.0, le=1.0)
    median_latency_ms: float = Field(ge=0.0)
    status: Literal["blocked", "shadow", "approved"]
    thresholds: RetrievalQualityThresholds
    preflight_blockers: list[str] = Field(default_factory=list, max_length=100)
    cases: list[BundleRetrievalCaseResult] = Field(default_factory=list, max_length=1_000_000)
    evaluation_id: str = ""
    input_digest: str = ""
    label_digest: str = ""
    dataset_ids: list[str] = Field(default_factory=list, max_length=200)
    splits: list[str] = Field(default_factory=list, max_length=10)
    time_split_disjoint: bool = True
    jev_requests: int = Field(default=0, ge=0)
    jev_input_tokens: int = Field(default=0, ge=0)
    jev_output_tokens: int = Field(default=0, ge=0)
    unauthorized_ref_count: int = Field(default=0, ge=0)


class BundleRetrievalEvaluator:
    """Certify the production ``resolve_bundle`` path after anchor selection."""

    def __init__(self, authoring: InsightAuthoringService, *, max_concurrency: int = 8) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.authoring = authoring
        self.max_concurrency = max_concurrency

    async def evaluate(
        self,
        cases: list[BundleRetrievalCase],
        *,
        thresholds: RetrievalQualityThresholds | None = None,
    ) -> BundleRetrievalReport:
        thresholds = thresholds or RetrievalQualityThresholds()
        preflight_blockers = _dataset_preflight(cases, thresholds)
        if preflight_blockers:
            self._metrics_delta = {}
            return self._report([], thresholds, cases=cases, preflight_blockers=preflight_blockers)
        metrics_before = self._judger_metrics()
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(case: BundleRetrievalCase) -> BundleRetrievalCaseResult:
            async with semaphore:
                return await self._evaluate_case(case)

        results = list(await asyncio.gather(*(run_one(case) for case in cases)))
        self._metrics_delta = self._metrics_delta_from(metrics_before)
        return self._report(results, thresholds, cases=cases)

    def _judger_metrics(self) -> dict[str, int]:
        judger = getattr(self.authoring.engine, "judger", None)
        metrics = getattr(judger, "metrics", None)
        return {
            "requests": int(getattr(metrics, "requests", 0)),
            "input_tokens": int(getattr(metrics, "input_tokens", 0)),
            "output_tokens": int(getattr(metrics, "output_tokens", 0)),
        }

    def _metrics_delta_from(self, before: dict[str, int]) -> dict[str, int]:
        after = self._judger_metrics()
        return {key: max(0, after[key] - before[key]) for key in before}

    async def _evaluate_case(self, case: BundleRetrievalCase) -> BundleRetrievalCaseResult:
        started = time.perf_counter()
        expected_groups = [set(group) for group in case.expected_related_groups]
        acceptable = set(case.acceptable_related_refs) or {
            ref for group in case.expected_related_groups for ref in group
        }
        try:
            bundle = await self.authoring.resolve_bundle(
                case.card,
                context=case.context,
                principal=case.principal,
            )
        except Exception as error:  # noqa: BLE001 - retain one failed label as evidence
            return BundleRetrievalCaseResult(
                case_id=case.id,
                candidate_group_recall=0.0 if expected_groups else 1.0,
                selected_group_recall=0.0 if expected_groups else 1.0,
                selected_precision=0.0 if expected_groups else 1.0,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(error).__name__}: {error}",
                tags=case.tags,
                dataset_id=case.dataset.dataset_id,
                split=case.dataset.split,
            )

        candidates = [*bundle.related_matches, *bundle.omitted_matches]
        candidate_refs = list(dict.fromkeys(match.ref for match in candidates))
        selected_refs = list(dict.fromkeys(match.ref for match in bundle.related_matches))
        candidate_set = set(candidate_refs)
        selected_set = set(selected_refs)
        candidate_group_recall = (
            sum(bool(group & candidate_set) for group in expected_groups) / len(expected_groups)
            if expected_groups
            else 1.0
        )
        selected_group_recall = (
            sum(bool(group & selected_set) for group in expected_groups) / len(expected_groups)
            if expected_groups
            else 1.0
        )
        selected_precision = (
            len(acceptable & selected_set) / len(selected_set)
            if selected_set
            else 1.0
            if not expected_groups
            else 0.0
        )
        unauthorized_refs = sorted(
            match.ref
            for match in candidates
            if case.principal is not None
            and match.contract.tenant_id != case.principal.tenant_id
        )
        return BundleRetrievalCaseResult(
            case_id=case.id,
            candidate_related_refs=candidate_refs,
            selected_related_refs=selected_refs,
            candidate_group_recall=candidate_group_recall,
            selected_group_recall=selected_group_recall,
            selected_precision=selected_precision,
            latency_ms=(time.perf_counter() - started) * 1000,
            evaluator=bundle.evaluator,
            truncated=bundle.truncated,
            warnings=bundle.warnings,
            tags=case.tags,
            dataset_id=case.dataset.dataset_id,
            split=case.dataset.split,
            unauthorized_refs=unauthorized_refs,
        )

    def _report(
        self,
        results: list[BundleRetrievalCaseResult],
        thresholds: RetrievalQualityThresholds,
        *,
        cases: list[BundleRetrievalCase] | None = None,
        preflight_blockers: list[str] | None = None,
    ) -> BundleRetrievalReport:
        preflight_blockers = preflight_blockers or []
        successful = [case for case in results if case.error is None]
        errors = len(results) - len(successful)
        denominator = len(successful) or 1
        error_rate = errors / len(results) if results else 1.0
        candidate_group_recall = sum(case.candidate_group_recall for case in successful) / denominator
        selected_group_recall = sum(case.selected_group_recall for case in successful) / denominator
        selected_precision = sum(case.selected_precision for case in successful) / denominator
        latencies = sorted(case.latency_ms for case in successful)
        median_latency = (
            latencies[len(latencies) // 2]
            if len(latencies) % 2
            else (latencies[len(latencies) // 2 - 1] + latencies[len(latencies) // 2]) / 2
            if latencies
            else 0.0
        )
        sufficient = len(results) >= thresholds.min_cases
        meets = (
            sufficient
            and candidate_group_recall >= thresholds.min_candidate_recall
            and selected_group_recall >= thresholds.min_required_group_recall
            and selected_precision >= thresholds.min_recommended_precision
            and error_rate <= thresholds.max_error_rate
        )
        status = PromotionStatus.APPROVED if meets else PromotionStatus.SHADOW
        if preflight_blockers or not results or (errors and error_rate > thresholds.max_error_rate):
            status = PromotionStatus.BLOCKED
        unauthorized_ref_count = sum(len(case.unauthorized_refs) for case in results)
        if unauthorized_ref_count > thresholds.max_unauthorized_refs:
            status = PromotionStatus.BLOCKED
        case_inputs = [
            {
                "id": case.id,
                "card": case.card.model_dump(mode="json"),
                "context": case.context.model_dump(mode="json") if case.context else None,
                "principal": case.principal.model_dump(mode="json") if case.principal else None,
                "dataset": case.dataset.model_dump(mode="json"),
            }
            for case in (cases or [])
        ]
        case_labels = [
            {
                "id": case.id,
                "expected_related_groups": case.expected_related_groups,
                "acceptable_related_refs": case.acceptable_related_refs,
            }
            for case in (cases or [])
        ]
        metrics = getattr(self, "_metrics_delta", {})
        return BundleRetrievalReport(
            case_count=len(results),
            successful_case_count=len(successful),
            error_count=errors,
            candidate_group_recall=candidate_group_recall,
            selected_group_recall=selected_group_recall,
            selected_precision=selected_precision,
            error_rate=error_rate,
            median_latency_ms=median_latency,
            status=status,
            thresholds=thresholds,
            preflight_blockers=preflight_blockers,
            cases=results,
            evaluation_id=_stable_digest(case_inputs)[:24] if case_inputs else "",
            input_digest=_stable_digest(case_inputs) if case_inputs else "",
            label_digest=_stable_digest(case_labels) if case_labels else "",
            dataset_ids=sorted({case.dataset.dataset_id for case in (cases or [])}),
            splits=sorted({case.dataset.split for case in (cases or [])}),
            time_split_disjoint=not _time_split_overlaps(
                [case.dataset for case in (cases or [])]
            ),
            jev_requests=int(metrics.get("requests", 0)),
            jev_input_tokens=int(metrics.get("input_tokens", 0)),
            jev_output_tokens=int(metrics.get("output_tokens", 0)),
            unauthorized_ref_count=unauthorized_ref_count,
        )


class RetrievalQualityEvaluator:
    """Run owner-labeled goals through the production Jev retrieval path."""

    def __init__(self, authoring: InsightAuthoringService, *, max_concurrency: int = 8) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.authoring = authoring
        self.max_concurrency = max_concurrency

    async def evaluate(
        self,
        cases: list[RetrievalQualityCase],
        *,
        thresholds: RetrievalQualityThresholds | None = None,
    ) -> RetrievalQualityReport:
        thresholds = thresholds or RetrievalQualityThresholds()
        preflight_blockers = self._preflight(cases, thresholds)
        if preflight_blockers:
            self._metrics_delta = {}
            return self._report(
                [], thresholds, cases=cases, preflight_blockers=preflight_blockers
            )
        metrics_before = self._judger_metrics()
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(case: RetrievalQualityCase) -> RetrievalQualityCaseResult:
            async with semaphore:
                return await self._evaluate_case(case)

        results = list(await asyncio.gather(*(run_one(case) for case in cases)))
        self._metrics_delta = self._metrics_delta_from(metrics_before)
        return self._report(results, thresholds, cases=cases)

    @staticmethod
    def _preflight(
        cases: list[RetrievalQualityCase], thresholds: RetrievalQualityThresholds
    ) -> list[str]:
        return _dataset_preflight(cases, thresholds)

    def _judger_metrics(self) -> dict[str, int]:
        judger = getattr(self.authoring.engine, "judger", None)
        metrics = getattr(judger, "metrics", None)
        return {
            "requests": int(getattr(metrics, "requests", 0)),
            "input_tokens": int(getattr(metrics, "input_tokens", 0)),
            "output_tokens": int(getattr(metrics, "output_tokens", 0)),
        }

    def _metrics_delta_from(self, before: dict[str, int]) -> dict[str, int]:
        after = self._judger_metrics()
        return {key: max(0, after[key] - before[key]) for key in before}

    async def _evaluate_case(self, case: RetrievalQualityCase) -> RetrievalQualityCaseResult:
        started = time.perf_counter()
        expected = set(case.expected_resource_refs)
        acceptable = set(case.acceptable_resource_refs or case.expected_resource_refs)
        try:
            discovery = await self.authoring.discover(
                case.goal,
                adapter=case.adapter,
                limit=case.limit,
                principal=case.principal,
            )
        except Exception as error:  # noqa: BLE001 - retain one failed label as evidence
            return RetrievalQualityCaseResult(
                case_id=case.id,
                expected_resource_refs=sorted(expected),
                candidate_recall=0.0 if expected else 1.0,
                recommended_precision=0.0 if expected else 1.0,
                recommended_recall=0.0 if expected else 1.0,
                required_group_recall=0.0 if case.required_resource_groups else 1.0,
                reciprocal_rank=0.0,
                no_match_correct=True if expected else False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(error).__name__}: {error}",
                tags=case.tags,
                dataset_id=case.dataset.dataset_id,
                split=case.dataset.split,
            )

        candidate_refs = list(discovery.candidate_refs)
        ranked_refs = [match.ref for match in discovery.matches]
        recommended_refs = [match.ref for match in discovery.matches if match.recommended]
        unauthorized_refs = sorted(
            match.ref
            for match in discovery.matches
            if case.principal is not None
            and match.contract.tenant_id != case.principal.tenant_id
        )
        candidate_set = set(candidate_refs)
        recommended_set = set(recommended_refs)
        candidate_recall = (
            len(expected & candidate_set) / len(expected) if expected else 1.0
        )
        recommended_precision = (
            len(acceptable & recommended_set) / len(recommended_set)
            if recommended_set
            else 1.0
            if not expected
            else 0.0
        )
        recommended_recall = (
            len(expected & recommended_set) / len(expected)
            if expected
            else 1.0
            if not recommended_set
            else 0.0
        )
        required_group_recall = (
            sum(
                bool(set(group) & recommended_set)
                for group in case.required_resource_groups
            )
            / len(case.required_resource_groups)
            if case.required_resource_groups
            else 1.0
        )
        reciprocal_rank = 0.0
        for index, ref in enumerate(ranked_refs, start=1):
            if ref in expected:
                reciprocal_rank = 1.0 / index
                break
        no_match_correct = (not expected and discovery.no_match) if not expected else True
        return RetrievalQualityCaseResult(
            case_id=case.id,
            expected_resource_refs=sorted(expected),
            candidate_refs=candidate_refs,
            ranked_refs=ranked_refs,
            recommended_refs=recommended_refs,
            candidate_recall=candidate_recall,
            recommended_precision=recommended_precision,
            recommended_recall=recommended_recall,
            required_group_recall=required_group_recall,
            reciprocal_rank=reciprocal_rank,
            no_match_correct=no_match_correct,
            latency_ms=(time.perf_counter() - started) * 1000,
            evaluator=discovery.evaluator,
            tags=case.tags,
            dataset_id=case.dataset.dataset_id,
            split=case.dataset.split,
            unauthorized_refs=unauthorized_refs,
        )

    def _report(
        self,
        results: list[RetrievalQualityCaseResult],
        thresholds: RetrievalQualityThresholds,
        *,
        cases: list[RetrievalQualityCase] | None = None,
        preflight_blockers: list[str] | None = None,
    ) -> RetrievalQualityReport:
        preflight_blockers = preflight_blockers or []
        successful = [case for case in results if case.error is None]
        errors = len(results) - len(successful)
        denominator = len(successful) or 1
        error_rate = errors / len(results) if results else 1.0
        candidate_recall = sum(case.candidate_recall for case in successful) / denominator
        recommended_precision = (
            sum(case.recommended_precision for case in successful) / denominator
        )
        recommended_recall = sum(case.recommended_recall for case in successful) / denominator
        required_group_recall = (
            sum(case.required_group_recall for case in successful) / denominator
        )
        reciprocal_rank = sum(case.reciprocal_rank for case in successful) / denominator
        no_match_cases = [case for case in successful if not case.expected_resource_refs]
        no_match_accuracy = (
            sum(case.no_match_correct for case in no_match_cases) / len(no_match_cases)
            if no_match_cases
            else 1.0
        )
        latencies = sorted(case.latency_ms for case in successful)
        median_latency = (
            latencies[len(latencies) // 2]
            if len(latencies) % 2
            else (latencies[len(latencies) // 2 - 1] + latencies[len(latencies) // 2]) / 2
            if latencies
            else 0.0
        )
        sufficient = len(results) >= thresholds.min_cases
        meets = (
            sufficient
            and candidate_recall >= thresholds.min_candidate_recall
            and recommended_precision >= thresholds.min_recommended_precision
            and recommended_recall >= thresholds.min_recommended_recall
            and required_group_recall >= thresholds.min_required_group_recall
            and error_rate <= thresholds.max_error_rate
        )
        status = PromotionStatus.APPROVED if meets else PromotionStatus.SHADOW
        if preflight_blockers or not results or errors and error_rate > thresholds.max_error_rate:
            status = PromotionStatus.BLOCKED
        case_inputs = [
            {
                "goal": case.goal,
                "adapter": case.adapter,
                "limit": case.limit,
                "principal": case.principal.model_dump(mode="json") if case.principal else None,
                "dataset": case.dataset.model_dump(mode="json"),
            }
            for case in (cases or [])
        ]
        case_labels = [
            {
                "id": case.id,
                "expected_resource_refs": case.expected_resource_refs,
                "acceptable_resource_refs": case.acceptable_resource_refs,
                "required_resource_groups": case.required_resource_groups,
            }
            for case in (cases or [])
        ]
        metrics = getattr(self, "_metrics_delta", {})
        unauthorized_ref_count = sum(len(case.unauthorized_refs) for case in results)
        if unauthorized_ref_count > thresholds.max_unauthorized_refs:
            status = PromotionStatus.BLOCKED
        return RetrievalQualityReport(
            case_count=len(results),
            successful_case_count=len(successful),
            error_count=errors,
            candidate_recall=candidate_recall,
            recommended_precision=recommended_precision,
            recommended_recall=recommended_recall,
            required_group_recall=required_group_recall,
            mean_reciprocal_rank=reciprocal_rank,
            no_match_accuracy=no_match_accuracy,
            error_rate=error_rate,
            median_latency_ms=median_latency,
            status=status,
            thresholds=thresholds,
            preflight_blockers=preflight_blockers,
            cases=results,
            evaluation_id=_stable_digest(case_inputs)[:24] if case_inputs else "",
            input_digest=_stable_digest(case_inputs) if case_inputs else "",
            label_digest=_stable_digest(case_labels) if case_labels else "",
            dataset_ids=sorted({case.dataset.dataset_id for case in (cases or [])}),
            splits=sorted({case.dataset.split for case in (cases or [])}),
            time_split_disjoint=not _time_split_overlaps(
                [case.dataset for case in (cases or [])]
            ),
            jev_requests=int(metrics.get("requests", 0)),
            jev_input_tokens=int(metrics.get("input_tokens", 0)),
            jev_output_tokens=int(metrics.get("output_tokens", 0)),
            unauthorized_ref_count=unauthorized_ref_count,
        )

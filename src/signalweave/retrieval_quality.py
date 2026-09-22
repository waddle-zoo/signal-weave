"""Owner-labeled retrieval evaluation for Jev-ranked source discovery."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .evaluation import PromotionStatus
from .models import PrincipalContext
from .onboarding import InsightAuthoringService


class RetrievalQualityCase(BaseModel):
    """One natural-language onboarding goal with owner-labeled relevant assets."""

    id: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=8000)
    expected_resource_refs: list[str] = Field(default_factory=list, max_length=500)
    adapter: str | None = None
    limit: int = Field(default=10, ge=1, le=25)
    principal: PrincipalContext | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_unique_refs(self) -> RetrievalQualityCase:
        if len(self.expected_resource_refs) != len(set(self.expected_resource_refs)):
            raise ValueError("expected_resource_refs must be unique")
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
    max_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    min_cases: int = Field(default=1, ge=1, le=1_000_000)


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
    reciprocal_rank: float = Field(ge=0.0, le=1.0)
    no_match_correct: bool = True
    latency_ms: float = Field(ge=0.0)
    evaluator: str = "unknown"
    error: str | None = None
    tags: list[str] = Field(default_factory=list)


class RetrievalQualityReport(BaseModel):
    """Aggregate report separating catalog recall from Jev ranking quality."""

    case_count: int = Field(ge=0)
    successful_case_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    candidate_recall: float = Field(ge=0.0, le=1.0)
    recommended_precision: float = Field(ge=0.0, le=1.0)
    recommended_recall: float = Field(ge=0.0, le=1.0)
    mean_reciprocal_rank: float = Field(ge=0.0, le=1.0)
    no_match_accuracy: float = Field(ge=0.0, le=1.0)
    error_rate: float = Field(ge=0.0, le=1.0)
    median_latency_ms: float = Field(ge=0.0)
    status: Literal["blocked", "shadow", "approved"]
    thresholds: RetrievalQualityThresholds
    cases: list[RetrievalQualityCaseResult] = Field(default_factory=list, max_length=1_000_000)


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
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(case: RetrievalQualityCase) -> RetrievalQualityCaseResult:
            async with semaphore:
                return await self._evaluate_case(case)

        results = list(await asyncio.gather(*(run_one(case) for case in cases)))
        return self._report(results, thresholds)

    async def _evaluate_case(self, case: RetrievalQualityCase) -> RetrievalQualityCaseResult:
        started = time.perf_counter()
        expected = set(case.expected_resource_refs)
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
                reciprocal_rank=0.0,
                no_match_correct=False if expected else False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(error).__name__}: {error}",
                tags=case.tags,
            )

        candidate_refs = list(discovery.candidate_refs)
        ranked_refs = [match.ref for match in discovery.matches]
        recommended_refs = [match.ref for match in discovery.matches if match.recommended]
        candidate_set = set(candidate_refs)
        recommended_set = set(recommended_refs)
        candidate_recall = (
            len(expected & candidate_set) / len(expected) if expected else 1.0
        )
        recommended_precision = (
            len(expected & recommended_set) / len(recommended_set)
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
        reciprocal_rank = 0.0
        for index, ref in enumerate(ranked_refs, start=1):
            if ref in expected:
                reciprocal_rank = 1.0 / index
                break
        no_match_correct = (not expected and discovery.no_match) or bool(
            expected & recommended_set
        )
        return RetrievalQualityCaseResult(
            case_id=case.id,
            expected_resource_refs=sorted(expected),
            candidate_refs=candidate_refs,
            ranked_refs=ranked_refs,
            recommended_refs=recommended_refs,
            candidate_recall=candidate_recall,
            recommended_precision=recommended_precision,
            recommended_recall=recommended_recall,
            reciprocal_rank=reciprocal_rank,
            no_match_correct=no_match_correct,
            latency_ms=(time.perf_counter() - started) * 1000,
            evaluator=discovery.evaluator,
            tags=case.tags,
        )

    @staticmethod
    def _report(
        results: list[RetrievalQualityCaseResult], thresholds: RetrievalQualityThresholds
    ) -> RetrievalQualityReport:
        successful = [case for case in results if case.error is None]
        errors = len(results) - len(successful)
        denominator = len(successful) or 1
        error_rate = errors / len(results) if results else 1.0
        candidate_recall = sum(case.candidate_recall for case in successful) / denominator
        recommended_precision = (
            sum(case.recommended_precision for case in successful) / denominator
        )
        recommended_recall = sum(case.recommended_recall for case in successful) / denominator
        reciprocal_rank = sum(case.reciprocal_rank for case in successful) / denominator
        no_match_accuracy = (
            sum(case.no_match_correct for case in successful) / denominator
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
            and error_rate <= thresholds.max_error_rate
        )
        status = PromotionStatus.APPROVED if meets else PromotionStatus.SHADOW
        if not results or errors and error_rate > thresholds.max_error_rate:
            status = PromotionStatus.BLOCKED
        return RetrievalQualityReport(
            case_count=len(results),
            successful_case_count=len(successful),
            error_count=errors,
            candidate_recall=candidate_recall,
            recommended_precision=recommended_precision,
            recommended_recall=recommended_recall,
            mean_reciprocal_rank=reciprocal_rank,
            no_match_accuracy=no_match_accuracy,
            error_rate=error_rate,
            median_latency_ms=median_latency,
            status=status,
            thresholds=thresholds,
            cases=results,
        )

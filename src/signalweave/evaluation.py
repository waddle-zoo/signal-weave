"""Reusable card/workflow certification over labeled historical snapshots.

The evaluator keeps owner labels outside the Jev payload. It measures the full
SignalWeave contract: typed outcome, configured delivery, evidence coverage, and
the resources actually materialized by the run. A card is not promoted merely
because Jev returned a confident answer.
"""

from __future__ import annotations

import asyncio
import json
import time
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .engine import InsightEngine
from .models import ContextSnapshot, InsightCard, Outcome, ResourceSnapshot


class PromotionStatus(StrEnum):
    """Stable certification states used by cards and deployment tooling."""

    BLOCKED = "blocked"
    SHADOW = "shadow"
    APPROVED = "approved"


class CardEvaluationCase(BaseModel):
    """One owner-labeled replay case for one card version."""

    id: str = Field(min_length=1, max_length=200)
    card: InsightCard
    resources: list[ResourceSnapshot] = Field(default_factory=list, max_length=500)
    context: ContextSnapshot | None = None
    expected_outcome: Outcome
    allowed_outcomes: list[Outcome] | None = None
    expected_delivery_method_keys: list[str] | None = None
    required_evidence_source_keys: list[str] = Field(default_factory=list, max_length=500)
    expected_retrieval_refs: list[str] = Field(default_factory=list, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_labels(self) -> CardEvaluationCase:
        if self.allowed_outcomes is not None and not self.allowed_outcomes:
            raise ValueError("allowed_outcomes must contain at least one outcome when provided")
        for field_name in (
            "required_evidence_source_keys",
            "expected_retrieval_refs",
            "expected_delivery_method_keys",
        ):
            values = getattr(self, field_name)
            if values is not None and len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
        return self


class CardEvaluationThresholds(BaseModel):
    """Promotion gates evaluated on a labeled replay set."""

    min_outcome_accuracy: float = Field(default=0.95, ge=0.0, le=1.0)
    min_evidence_recall: float = Field(default=0.95, ge=0.0, le=1.0)
    min_retrieval_recall: float = Field(default=0.95, ge=0.0, le=1.0)
    max_unsafe_action_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    max_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    min_cases: int = Field(default=1, ge=1, le=1_000_000)


class CardEvaluationCaseResult(BaseModel):
    """Inspectable outcome of one replay case."""

    case_id: str
    card_id: str
    card_version: int
    expected_outcome: Outcome
    outcome: Outcome | None = None
    exact_outcome: bool = False
    safe_action: bool = False
    unsafe_action: bool = False
    delivery_exact: bool = False
    evidence_recall: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_recall: float = Field(default=0.0, ge=0.0, le=1.0)
    actual_delivery_method_keys: list[str] = Field(default_factory=list)
    actual_evidence_source_keys: list[str] = Field(default_factory=list)
    actual_retrieval_refs: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)
    summary: str = ""
    rationale: str = ""
    missing_evidence_source_keys: list[str] = Field(default_factory=list)
    missing_retrieval_refs: list[str] = Field(default_factory=list)
    unexpected_retrieval_refs: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0.0)
    evaluator: str = "unknown"
    error: str | None = None
    tags: list[str] = Field(default_factory=list)


class CardEvaluationReport(BaseModel):
    """Aggregate certification report for a card/workflow replay set."""

    card_ids: list[str] = Field(default_factory=list, max_length=100)
    card_versions: dict[str, int] = Field(default_factory=dict)
    case_count: int = Field(ge=0)
    successful_case_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    outcome_accuracy: float = Field(ge=0.0, le=1.0)
    evidence_recall: float = Field(ge=0.0, le=1.0)
    retrieval_precision: float = Field(ge=0.0, le=1.0)
    retrieval_recall: float = Field(ge=0.0, le=1.0)
    unsafe_action_rate: float = Field(ge=0.0, le=1.0)
    error_rate: float = Field(ge=0.0, le=1.0)
    median_latency_ms: float = Field(ge=0.0)
    status: Literal["blocked", "shadow", "approved"]
    thresholds: CardEvaluationThresholds
    preflight_blockers: list[str] = Field(default_factory=list, max_length=100)
    cases: list[CardEvaluationCaseResult] = Field(default_factory=list, max_length=1_000_000)


def load_card_evaluation_cases(path: str | Path) -> list[CardEvaluationCase]:
    """Load a portable JSON fixture without moving labels into Jev state."""

    payload = json.loads(Path(path).read_text())
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("card evaluation fixture must be a JSON list or an object with cases")
    return [CardEvaluationCase.model_validate(case) for case in raw_cases]


class CardWorkflowEvaluator:
    """Replay labeled cases through the real InsightEngine and certify the result."""

    def __init__(self, engine: InsightEngine, *, max_concurrency: int = 8) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.engine = engine
        self.max_concurrency = max_concurrency

    async def evaluate(
        self,
        cases: list[CardEvaluationCase],
        *,
        thresholds: CardEvaluationThresholds | None = None,
    ) -> CardEvaluationReport:
        thresholds = thresholds or CardEvaluationThresholds()
        preflight_blockers = self._preflight(cases)
        if preflight_blockers:
            return self._report(
                [],
                thresholds,
                preflight_blockers=preflight_blockers,
                card_ids=sorted({case.card.id for case in cases}),
                card_versions={case.card.id: case.card.version for case in cases},
            )
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(case: CardEvaluationCase) -> CardEvaluationCaseResult:
            async with semaphore:
                return await self._evaluate_case(case)

        results = list(await asyncio.gather(*(run_one(case) for case in cases)))
        return self._report(results, thresholds)

    @staticmethod
    def _preflight(cases: list[CardEvaluationCase]) -> list[str]:
        blockers: list[str] = []
        for card in {case.card.id: case.card for case in cases}.values():
            if not card.sources:
                blockers.append(f"{card.id}: card declares no source references")
            if card.delivery_methods and not card.decision_guidance.strip():
                blockers.append(
                    f"{card.id}: push-capable card is missing human decision guidance"
                )
        return blockers

    async def _evaluate_case(self, case: CardEvaluationCase) -> CardEvaluationCaseResult:
        started = time.perf_counter()
        try:
            run = await self.engine.evaluate(
                case.card,
                resources=case.resources,
                context_override=case.context,
            )
        except Exception as error:  # noqa: BLE001 - one bad case must remain visible
            return CardEvaluationCaseResult(
                case_id=case.id,
                card_id=case.card.id,
                card_version=case.card.version,
                expected_outcome=case.expected_outcome,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(error).__name__}: {error}",
                tags=case.tags,
            )

        result = run.result
        actual_delivery = sorted(method.key for method in result.delivery_methods)
        expected_delivery = (
            sorted(case.expected_delivery_method_keys)
            if case.expected_delivery_method_keys is not None
            else None
        )
        actual_evidence = sorted(
            {item.source_key for item in result.evidence}
            | {item.source_key for item in result.observations}
        )
        required_evidence = set(case.required_evidence_source_keys)
        present_evidence = required_evidence & set(actual_evidence)
        evidence_recall = (
            len(present_evidence) / len(required_evidence) if required_evidence else 1.0
        )
        actual_retrieval = sorted(
            {f"{resource.adapter}|{resource.resource}" for resource in run.resources}
        )
        expected_retrieval = set(case.expected_retrieval_refs)
        actual_retrieval_set = set(actual_retrieval)
        retrieval_precision = (
            len(expected_retrieval & actual_retrieval_set) / len(actual_retrieval_set)
            if actual_retrieval_set
            else 1.0
            if not expected_retrieval
            else 0.0
        )
        retrieval_recall = (
            len(expected_retrieval & actual_retrieval_set) / len(expected_retrieval)
            if expected_retrieval
            else 1.0
            if not actual_retrieval_set
            else 0.0
        )
        allowed_outcomes = set(case.allowed_outcomes or [case.expected_outcome])
        safe_action = result.outcome in allowed_outcomes
        return CardEvaluationCaseResult(
            case_id=case.id,
            card_id=case.card.id,
            card_version=case.card.version,
            expected_outcome=case.expected_outcome,
            outcome=result.outcome,
            exact_outcome=result.outcome == case.expected_outcome,
            safe_action=safe_action,
            unsafe_action=not safe_action,
            delivery_exact=expected_delivery is None or actual_delivery == expected_delivery,
            evidence_recall=evidence_recall,
            retrieval_precision=retrieval_precision,
            retrieval_recall=retrieval_recall,
            actual_delivery_method_keys=actual_delivery,
            actual_evidence_source_keys=actual_evidence,
            actual_retrieval_refs=actual_retrieval,
            confidence=result.confidence,
            probabilities=result.probabilities,
            summary=result.summary,
            rationale=result.rationale,
            missing_evidence_source_keys=sorted(required_evidence - set(actual_evidence)),
            missing_retrieval_refs=sorted(expected_retrieval - actual_retrieval_set),
            unexpected_retrieval_refs=sorted(actual_retrieval_set - expected_retrieval),
            latency_ms=(time.perf_counter() - started) * 1000,
            evaluator=result.evaluator,
            tags=case.tags,
        )

    @staticmethod
    def _report(
        results: list[CardEvaluationCaseResult],
        thresholds: CardEvaluationThresholds,
        *,
        preflight_blockers: list[str] | None = None,
        card_ids: list[str] | None = None,
        card_versions: dict[str, int] | None = None,
    ) -> CardEvaluationReport:
        preflight_blockers = preflight_blockers or []
        successful = [case for case in results if case.error is None]
        errors = len(results) - len(successful)
        denominator = len(successful) or 1
        outcome_accuracy = sum(case.exact_outcome for case in successful) / denominator
        evidence_recall = sum(case.evidence_recall for case in successful) / denominator
        retrieval_precision = sum(case.retrieval_precision for case in successful) / denominator
        retrieval_recall = sum(case.retrieval_recall for case in successful) / denominator
        unsafe_action_rate = sum(case.unsafe_action for case in successful) / denominator
        error_rate = errors / len(results) if results else 1.0
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
            and outcome_accuracy >= thresholds.min_outcome_accuracy
            and evidence_recall >= thresholds.min_evidence_recall
            and retrieval_recall >= thresholds.min_retrieval_recall
            and unsafe_action_rate <= thresholds.max_unsafe_action_rate
            and error_rate <= thresholds.max_error_rate
        )
        status = PromotionStatus.APPROVED if meets else PromotionStatus.SHADOW
        if (
            preflight_blockers
            or not results
            or errors and error_rate > thresholds.max_error_rate
        ):
            status = PromotionStatus.BLOCKED
        return CardEvaluationReport(
            card_ids=card_ids or sorted({case.card_id for case in results}),
            card_versions=card_versions
            or {case.card_id: case.card_version for case in results},
            case_count=len(results),
            successful_case_count=len(successful),
            error_count=errors,
            outcome_accuracy=outcome_accuracy,
            evidence_recall=evidence_recall,
            retrieval_precision=retrieval_precision,
            retrieval_recall=retrieval_recall,
            unsafe_action_rate=unsafe_action_rate,
            error_rate=error_rate,
            median_latency_ms=median_latency,
            status=status,
            thresholds=thresholds,
            preflight_blockers=preflight_blockers,
            cases=results,
        )

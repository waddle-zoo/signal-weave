"""Reusable card/workflow certification over labeled historical snapshots.

The evaluator keeps owner labels outside the Jev payload. It measures the full
SignalWeave contract: typed outcome, configured delivery, evidence coverage, and
the resources actually materialized by the run. A card is not promoted merely
because Jev returned a confident answer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator

from .engine import InsightEngine
from .models import (
    ContextSnapshot,
    EvidencePlan,
    InsightCard,
    Outcome,
    PrincipalContext,
    QuestionResult,
    ResourceSnapshot,
    WatchResult,
    WorkflowHandoff,
)
from .sources import SourceRegistry

# Increment when admission or promotion semantics require fresh certification.
# Version 3 also gates promotion on owner-labeled delivery exactness; version 2
# reports recorded delivery failures but could still approve them. Keep the
# existing marker name so readiness invalidates those reports without migration.
# Version 4 corrects question handoffs: low answerability is pending, not proof
# of conflict. Re-evaluate serialized plan wording; do not relabel old reports.
# Version 5 distinguishes required retrieval from explicitly permitted context.
# Old exact-set labels keep their semantics; new reports record both sets.
EVIDENCE_ADMISSION_POLICY_VERSION = 5


def has_current_evidence_admission_policy(report: Mapping[str, object]) -> bool:
    """Check stored report compatibility, not approval or overall readiness."""

    version = report.get("evidence_admission_policy_version")
    # Stored certification bodies are opaque dictionaries. Do not coerce a
    # boolean/string/float into a version, or assume unknown future compatibility.
    return type(version) is int and version == EVIDENCE_ADMISSION_POLICY_VERSION


class EvaluationDataset(BaseModel):
    """Identity of the immutable snapshot used for a labeled replay.

    A dataset identity is deliberately separate from the expected labels. It
    lets a report prove which source/context/time partition was evaluated while
    keeping owner judgments outside the Jev request.
    """

    dataset_id: str = Field(min_length=1, max_length=240)
    split: Literal["train", "validation", "holdout", "adversarial", "live_shadow", "unspecified"] = "unspecified"
    observed_from: str = Field(default="", max_length=80)
    observed_to: str = Field(default="", max_length=80)
    source_catalog_version: str = Field(default="", max_length=240)
    context_version: str = Field(default="", max_length=240)
    digest: str = Field(default="", max_length=128)
    label_source: str = Field(default="owner-reviewed", max_length=240)

    @model_validator(mode="after")
    def validate_identity(self) -> EvaluationDataset:
        if self.split != "unspecified" and not self.digest:
            raise ValueError("non-unspecified evaluation datasets require a snapshot digest")
        if self.observed_from and self.observed_to and self.observed_from > self.observed_to:
            raise ValueError("evaluation dataset observed_from must not be after observed_to")
        return self


def _time_split_overlaps(datasets: list[EvaluationDataset]) -> bool:
    """Return whether differently labeled splits overlap in observed time."""

    for index, left in enumerate(datasets):
        if not left.observed_from or not left.observed_to:
            continue
        for right in datasets[index + 1 :]:
            if left.split == right.split or not right.observed_from or not right.observed_to:
                continue
            if left.observed_from <= right.observed_to and right.observed_from <= left.observed_to:
                return True
    return False


def _stable_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _future_capture(resource: ResourceSnapshot, as_of: datetime) -> str | None:
    for field_name in ("captured_at", "source_captured_at"):
        captured_at = getattr(resource, field_name)
        if captured_at is None:
            continue
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        if captured_at > as_of:
            return field_name
    return None


def _future_context(context: ContextSnapshot | None, as_of: datetime) -> bool:
    if context is None:
        return False
    captured_at = context.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    return captured_at > as_of


def card_acceptance_digest(card: InsightCard) -> str:
    """Bind tested policy, source parameters, routes, principal and stored plan.

    Approval/review audit is deliberately excluded. The semantic execution payload
    alone is insufficient: it omits endpoints, identity and the compiled plan.
    This digest is an integrity check, not human authorization or source freshness.
    """

    return _stable_digest({
        "execution_payload": card.execution_payload(),
        "delivery_methods": [method.model_dump(mode="json") for method in card.delivery_methods],
        "principal_id": card.principal_id,
        "principal_tenant": card.principal_tenant,
        "compiled_plan": card.compiled_plan.model_dump(mode="json") if card.compiled_plan else None,
    })


def _case_input(case: CardEvaluationCase) -> dict[str, object]:
    """Return exactly the material allowed into the production evaluation path."""

    return {
        "card": case.card.model_dump(mode="json"),
        "resources": [resource.model_dump(mode="json") for resource in case.resources],
        "context": case.context.model_dump(mode="json") if case.context else None,
        "dataset": case.dataset.model_dump(mode="json"),
        "as_of": case.as_of.isoformat() if case.as_of else None,
    }


def _case_labels(case: CardEvaluationCase) -> dict[str, object]:
    """Labels are report-only and must never be sent to Jev."""

    return {
        "case_id": case.id,
        "expected_outcome": case.expected_outcome,
        "allowed_outcomes": case.allowed_outcomes,
        "expected_delivery_method_keys": case.expected_delivery_method_keys,
        "expected_delivery_destinations": case.expected_delivery_destinations,
        "required_evidence_source_keys": case.required_evidence_source_keys,
        "expected_retrieval_refs": case.expected_retrieval_refs,
        "allowed_retrieval_refs": case.allowed_retrieval_refs,
    }


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
    expected_delivery_destinations: dict[str, str] | None = None
    required_evidence_source_keys: list[str] = Field(default_factory=list, max_length=500)
    expected_retrieval_refs: list[str] = Field(default_factory=list, max_length=500)
    allowed_retrieval_refs: list[str] | None = Field(
        default=None, max_length=500,
        description="Owner-labeled permissible retrieval, including every expected ref. None requires exactly expected_retrieval_refs. Optional context is permitted, never required. This is a scoring label, not source authorization.",
    )
    tags: list[str] = Field(default_factory=list, max_length=50)
    dataset: EvaluationDataset = Field(default_factory=lambda: EvaluationDataset(dataset_id="unspecified"))
    as_of: AwareDatetime | None = Field(
        default=None,
        description="Historical evaluation clock for supplied snapshots; omitted means the live clock.",
    )

    @model_validator(mode="after")
    def validate_labels(self) -> CardEvaluationCase:
        if self.allowed_outcomes is not None and not self.allowed_outcomes:
            raise ValueError("allowed_outcomes must contain at least one outcome when provided")
        for field_name in (
            "required_evidence_source_keys",
            "expected_retrieval_refs",
            "allowed_retrieval_refs",
            "expected_delivery_method_keys",
        ):
            values = getattr(self, field_name)
            if values is not None and len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be unique")
        if self.allowed_retrieval_refs is not None and not set(self.expected_retrieval_refs) <= set(self.allowed_retrieval_refs):
            raise ValueError("allowed_retrieval_refs must include every expected_retrieval_ref")
        if self.as_of is not None:
            for resource in self.resources:
                field_name = _future_capture(resource, self.as_of)
                if field_name is not None:
                    raise ValueError(
                        f"{self.id}: {field_name} is after historical as_of; "
                        "future snapshots cannot be replayed"
                    )
            if _future_context(self.context, self.as_of):
                raise ValueError(
                    f"{self.id}: context captured_at is after historical as_of; "
                    "future context cannot be replayed"
                )
        return self


class WorkflowCaseInput(BaseModel):
    """Caller labels plus either exact historical snapshots or one live capture.

    The stored card is server-owned. A live capture is a single current example,
    never an invented historical period or evidence of full policy coverage.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    expected_outcome: Outcome
    expected_delivery_method_keys: list[str] | None = None
    expected_delivery_destinations: dict[str, str] | None = None
    capture_current_sources: StrictBool = Field(
        default=False,
        description="Explicit read/query permission to fetch this stored card's selected sources for ONE current example. Do not also supply resources.",
    )
    resources: list[ResourceSnapshot] | None = Field(
        default=None, max_length=500,
        description="Exact normalized snapshots from inspection/preview, including source_key and contract.tenant_id; not ref strings or invented metadata. Use [] only to explicitly test missing resources.",
    )
    context: ContextSnapshot | None = None
    allowed_outcomes: list[Outcome] | None = None
    required_evidence_source_keys: list[str] = Field(default_factory=list, max_length=500)
    expected_retrieval_refs: list[str] = Field(default_factory=list, max_length=500)
    allowed_retrieval_refs: list[str] | None = Field(
        default=None, max_length=500,
        description="Owner-labeled permissible retrieval, including every expected ref. None requires exactly expected_retrieval_refs. Optional context is permitted, never required. This is a scoring label, not source authorization.",
    )
    tags: list[str] = Field(default_factory=list, max_length=50)
    dataset: EvaluationDataset = Field(default_factory=lambda: EvaluationDataset(dataset_id="unspecified"))
    as_of: AwareDatetime | None = Field(
        default=None,
        description="Historical evaluation clock for supplied snapshots; omitted means the live clock.",
    )

    @model_validator(mode="after")
    def require_evidence_input(self):
        if self.as_of is not None and self.capture_current_sources:
            raise ValueError("as_of cannot be combined with capture_current_sources=true")
        if self.capture_current_sources == (self.resources is not None):
            raise ValueError("Choose capture_current_sources=true OR explicit resources snapshots (including [] for a missing-resource test).")
        if self.as_of is not None and _future_context(self.context, self.as_of):
            raise ValueError(
                f"{self.id}: context captured_at is after historical as_of; "
                "future context cannot be replayed"
            )
        return self


class CardEvaluationThresholds(BaseModel):
    """Promotion gates evaluated on a labeled replay set."""

    min_outcome_accuracy: float = Field(default=0.95, ge=0.0, le=1.0)
    min_evidence_recall: float = Field(default=0.95, ge=0.0, le=1.0)
    min_retrieval_recall: float = Field(default=0.95, ge=0.0, le=1.0)
    max_unsafe_action_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    max_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    min_cases: int = Field(default=1, ge=1, le=1_000_000)
    require_dataset_provenance: bool = False
    required_splits: list[str] = Field(default_factory=list, max_length=10)
    require_disjoint_time_splits: bool = False


class CardEvaluationCaseResult(BaseModel):
    """Inspectable outcome of one replay case."""

    case_id: str
    card_id: str
    card_version: int
    expected_outcome: Outcome
    as_of: AwareDatetime | None = None
    outcome: Outcome | None = None
    exact_outcome: bool = False
    safe_action: bool = False
    unsafe_action: bool = False
    delivery_exact: bool = False
    delivery_destinations_exact: bool | None = None
    evidence_recall: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_recall: float = Field(default=0.0, ge=0.0, le=1.0)
    actual_delivery_method_keys: list[str] = Field(default_factory=list)
    actual_delivery_destinations: dict[str, str] = Field(default_factory=dict)
    actual_evidence_source_keys: list[str] = Field(default_factory=list)
    actual_retrieval_refs: list[str] = Field(default_factory=list)
    expected_retrieval_refs: list[str] | None = None
    allowed_retrieval_refs: list[str] | None = None
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
    dataset_id: str = ""
    split: str = "unspecified"
    evidence_plan: EvidencePlan | None = None
    workflow: WorkflowHandoff | None = None
    watch_results: list[WatchResult] = Field(default_factory=list)
    question_results: list[QuestionResult] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)


class CardEvaluationReport(BaseModel):
    """Aggregate certification report for a card/workflow replay set."""

    evidence_admission_policy_version: int = Field(
        default=0, ge=0, strict=True,
        description="Evidence admission policy used by this replay; 0 denotes a legacy report.",
    )
    card_ids: list[str] = Field(default_factory=list, max_length=10_000)
    card_versions: dict[str, int] = Field(default_factory=dict)
    acceptance_outcomes: list[Outcome] | None = Field(
        default=None,
        description="Exactly the owner-declared outcome coverage requested per card; passing is limited to supplied cases, not proof of the entire policy.",
    )
    card_execution_digests: dict[str, str] = Field(default_factory=dict)
    acceptance_passed: bool | None = None
    acceptance_scope: Literal["supplied_snapshot_replay"] | None = Field(
        default=None,
        description="Acceptance tests supplied snapshots; it does not certify live adapter resolution or dynamic catalog retrieval.",
    )
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
    evaluation_id: str = ""
    input_digest: str = ""
    label_digest: str = ""
    dataset_ids: list[str] = Field(default_factory=list, max_length=200)
    splits: list[str] = Field(default_factory=list, max_length=10)
    time_split_disjoint: bool = True
    jev_requests: int = Field(default=0, ge=0)
    jev_input_tokens: int = Field(default=0, ge=0)
    jev_output_tokens: int = Field(default=0, ge=0)


def load_card_evaluation_cases(path: str | Path) -> list[CardEvaluationCase]:
    """Load a portable JSON fixture without moving labels into Jev state."""

    payload = json.loads(Path(path).read_text())
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("card evaluation fixture must be a JSON list or an object with cases")
    return [CardEvaluationCase.model_validate(case) for case in raw_cases]


class CardWorkflowEvaluator:
    """Replay labeled cases through the real InsightEngine and certify the result."""

    def __init__(
        self,
        engine: InsightEngine,
        *,
        max_concurrency: int = 8,
        principal: PrincipalContext | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.engine = engine
        self.max_concurrency = max_concurrency
        self.principal = principal

    async def evaluate(
        self,
        cases: list[CardEvaluationCase],
        *,
        thresholds: CardEvaluationThresholds | None = None,
        acceptance_outcomes: list[Outcome] | None = None,
    ) -> CardEvaluationReport:
        """Optionally require exact onboarding replay acceptance for every card.

        Acceptance requires explicit caller-owned labels, a stored compiled plan,
        and coverage of exactly the owner-declared requested outcomes per card.
        Callers explicitly request policy-applicable quiet and missing-data cases.
        Labels must be supplied independently of
        predictions; none are inferred from results or passed into the engine.
        This certifies supplied snapshots, not live adapter resolution or a human.
        """
        thresholds = thresholds or CardEvaluationThresholds()
        if acceptance_outcomes is not None:
            acceptance_outcomes = sorted({Outcome(value) for value in acceptance_outcomes})
            # Freeze what is tested across awaited execution and retain any stronger
            # caller requirements (case count, provenance and split constraints).
            cases = [case.model_copy(deep=True) for case in cases]
            thresholds = thresholds.model_copy(update={
                "min_outcome_accuracy": 1.0,
                "min_evidence_recall": 1.0,
                "min_retrieval_recall": 1.0,
                "max_unsafe_action_rate": 0.0,
                "max_error_rate": 0.0,
            })
        metrics_before = self._judger_metrics()
        preflight_blockers = self._preflight(cases, thresholds)
        if acceptance_outcomes is not None:
            preflight_blockers.extend(self._acceptance_preflight(cases, acceptance_outcomes))
        if preflight_blockers:
            self._metrics_delta = self._metrics_delta_from(metrics_before)
            return self._report(
                [],
                thresholds,
                preflight_blockers=preflight_blockers,
                card_ids=sorted({case.card.id for case in cases}),
                card_versions={case.card.id: case.card.version for case in cases},
                cases=cases,
                acceptance_outcomes=acceptance_outcomes,
            )
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(case: CardEvaluationCase) -> CardEvaluationCaseResult:
            async with semaphore:
                return await self._evaluate_case(case)

        results = list(await asyncio.gather(*(run_one(case) for case in cases)))
        self._metrics_delta = self._metrics_delta_from(metrics_before)
        return self._report(results, thresholds, cases=cases, acceptance_outcomes=acceptance_outcomes)

    def _judger_metrics(self) -> dict[str, int]:
        metrics = getattr(getattr(self.engine, "judger", None), "metrics", None)
        return {
            "requests": int(getattr(metrics, "requests", 0)),
            "input_tokens": int(getattr(metrics, "input_tokens", 0)),
            "output_tokens": int(getattr(metrics, "output_tokens", 0)),
        }

    def _metrics_delta_from(self, before: dict[str, int]) -> dict[str, int]:
        after = self._judger_metrics()
        return {key: max(0, after[key] - before[key]) for key in before}

    @staticmethod
    def _preflight(
        cases: list[CardEvaluationCase], thresholds: CardEvaluationThresholds
    ) -> list[str]:
        blockers: list[str] = []
        versions: dict[str, set[int]] = {}
        for case in cases:
            versions.setdefault(case.card.id, set()).add(case.card.version)
        for card_id, card_versions in versions.items():
            if len(card_versions) > 1:
                blockers.append(
                    f"{card_id}: evaluation mixes card versions "
                    + ", ".join(str(version) for version in sorted(card_versions))
                )
        for case in cases:
            if case.as_of is None:
                continue
            for resource in case.resources:
                field_name = _future_capture(resource, case.as_of)
                if field_name is not None:
                    blockers.append(f"{case.id}: {field_name} is after historical as_of")
            if _future_context(case.context, case.as_of):
                blockers.append(f"{case.id}: context captured_at is after historical as_of")
        for card in {case.card.id: case.card for case in cases}.values():
            if not card.sources:
                blockers.append(f"{card.id}: card declares no source references")
            if card.delivery_methods and not card.decision_guidance.strip():
                blockers.append(
                    f"{card.id}: push-capable card is missing human decision guidance"
                )
        if thresholds.require_dataset_provenance:
            missing = [case.id for case in cases if case.dataset.split == "unspecified"]
            if missing:
                blockers.append(
                    "dataset provenance is required; unspecified cases: " + ", ".join(missing)
                )
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

    @staticmethod
    def _acceptance_preflight(
        cases: list[CardEvaluationCase], acceptance_outcomes: list[Outcome],
    ) -> list[str]:
        blockers: list[str] = []
        if not acceptance_outcomes:
            blockers.append("acceptance_outcomes must explicitly name at least one outcome")
        seen_ids: set[str] = set()
        by_card: dict[str, list[CardEvaluationCase]] = {}
        for case in cases:
            if case.id in seen_ids:
                blockers.append(f"{case.id}: duplicate acceptance case id")
            seen_ids.add(case.id)
            by_card.setdefault(case.card.id, []).append(case)
            if case.expected_delivery_method_keys is None or case.expected_delivery_destinations is None:
                blockers.append(f"{case.id}: acceptance requires explicit delivery keys and destinations (use [] and {{}} for no route)")
            elif set(case.expected_delivery_method_keys) != set(case.expected_delivery_destinations):
                blockers.append(f"{case.id}: delivery destination label keys must match delivery method labels")
            for name in ("required_evidence_source_keys", "expected_retrieval_refs"):
                if name not in case.model_fields_set:
                    blockers.append(f"{case.id}: acceptance requires explicit {name} labels (use [] when none are expected)")
            sources = {source.key: source for source in case.card.sources}
            seen_sources: set[str] = set()
            for resource in case.resources:
                source = sources.get(resource.source_key)
                if resource.source_key in seen_sources:
                    blockers.append(f"{case.id}: duplicate snapshot source key {resource.source_key}")
                seen_sources.add(resource.source_key)
                if source is not None and (source.adapter, source.resource) != (resource.adapter, resource.resource):
                    blockers.append(f"{case.id}: snapshot identity does not match a selected source: {resource.source_key}")
        for card_id, card_cases in by_card.items():
            if len({card_acceptance_digest(case.card) for case in card_cases}) != 1:
                blockers.append(f"{card_id}: acceptance mixes differing execution contracts")
            if any(case.card.compiled_plan is None for case in card_cases):
                blockers.append(f"{card_id}: acceptance requires a stored compiled_plan")
            required = set(acceptance_outcomes)
            missing = required - {case.expected_outcome for case in card_cases}
            if missing:
                blockers.append(f"{card_id}: acceptance outcome coverage missing: " + ", ".join(sorted(missing)))
        return blockers

    async def _evaluate_case(self, case: CardEvaluationCase) -> CardEvaluationCaseResult:
        started = time.perf_counter()
        try:
            evaluate_kwargs = {
                "resources": case.resources,
                "context_override": case.context,
            }
            # Keep legacy/offline engine doubles compatible while preserving the
            # authenticated principal for dynamic follow-up source resolution.
            if self.principal is not None:
                evaluate_kwargs["principal"] = self.principal
            engine = self.engine
            if case.as_of is not None:
                engine = InsightEngine(
                    judger=self.engine.judger,
                    registry=SourceRegistry([]),
                    context_provider=None,
                    investigation_candidate_limit=self.engine.investigation_candidate_limit,
                    max_jev_payload_bytes=self.engine.max_jev_payload_bytes,
                    clock=lambda: case.as_of,
                )
            run = await engine.evaluate(case.card, **evaluate_kwargs)
        except Exception as error:  # noqa: BLE001 - one bad case must remain visible
            return CardEvaluationCaseResult(
                case_id=case.id,
                card_id=case.card.id,
                card_version=case.card.version,
                expected_outcome=case.expected_outcome,
                expected_retrieval_refs=case.expected_retrieval_refs,
                allowed_retrieval_refs=case.allowed_retrieval_refs,
                as_of=case.as_of,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(error).__name__}: {error}",
                failure_reasons=["runtime_error"],
                tags=case.tags,
                dataset_id=case.dataset.dataset_id,
                split=case.dataset.split,
            )

        result = run.result
        actual_delivery = sorted(method.key for method in result.delivery_methods)
        actual_destinations = {method.key: method.destination for method in result.delivery_methods}
        destinations_exact = (
            actual_destinations == case.expected_delivery_destinations
            and len(actual_destinations) == len(result.delivery_methods)
            if case.expected_delivery_destinations is not None else None
        )
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
        allowed_retrieval = (
            expected_retrieval if case.allowed_retrieval_refs is None
            else set(case.allowed_retrieval_refs)
        )
        actual_retrieval_set = set(actual_retrieval)
        retrieval_precision = (
            len(allowed_retrieval & actual_retrieval_set) / len(actual_retrieval_set)
            if actual_retrieval_set
            else 1.0
            if not expected_retrieval
            else 0.0
        )
        retrieval_recall = (
            len(expected_retrieval & actual_retrieval_set) / len(expected_retrieval)
            if expected_retrieval
            else 1.0
        )
        allowed_outcomes = set(case.allowed_outcomes or [case.expected_outcome])
        safe_action = result.outcome in allowed_outcomes
        delivery_exact = (expected_delivery is None or actual_delivery == expected_delivery) and destinations_exact is not False
        failure_reasons = []
        if result.outcome != case.expected_outcome:
            failure_reasons.append("outcome_mismatch")
        if expected_delivery is not None and actual_delivery != expected_delivery:
            failure_reasons.append("delivery_keys_mismatch")
        if destinations_exact is False:
            failure_reasons.append("delivery_destinations_mismatch")
        if evidence_recall < 1:
            failure_reasons.append("missing_required_evidence")
        if retrieval_recall < 1:
            failure_reasons.append("missing_expected_retrieval")
        if retrieval_precision < 1:
            failure_reasons.append("unexpected_retrieval")
        return CardEvaluationCaseResult(
            case_id=case.id,
            card_id=case.card.id,
            card_version=case.card.version,
            expected_outcome=case.expected_outcome,
            as_of=case.as_of,
            outcome=result.outcome,
            exact_outcome=result.outcome == case.expected_outcome,
            safe_action=safe_action,
            unsafe_action=not safe_action,
            delivery_exact=delivery_exact,
            delivery_destinations_exact=destinations_exact,
            evidence_recall=evidence_recall,
            retrieval_precision=retrieval_precision,
            retrieval_recall=retrieval_recall,
            actual_delivery_method_keys=actual_delivery,
            actual_delivery_destinations=actual_destinations,
            actual_evidence_source_keys=actual_evidence,
            actual_retrieval_refs=actual_retrieval,
            expected_retrieval_refs=case.expected_retrieval_refs,
            allowed_retrieval_refs=case.allowed_retrieval_refs,
            confidence=result.confidence,
            probabilities=result.probabilities,
            summary=result.summary,
            rationale=result.rationale,
            missing_evidence_source_keys=sorted(required_evidence - set(actual_evidence)),
            missing_retrieval_refs=sorted(expected_retrieval - actual_retrieval_set),
            unexpected_retrieval_refs=sorted(actual_retrieval_set - allowed_retrieval),
            latency_ms=(time.perf_counter() - started) * 1000,
            evaluator=result.evaluator,
            tags=case.tags,
            dataset_id=case.dataset.dataset_id,
            split=case.dataset.split,
            evidence_plan=result.evidence_plan,
            workflow=result.workflow,
            watch_results=result.watch_results,
            question_results=result.question_results,
            failure_reasons=failure_reasons,
        )

    def _report(
        self,
        results: list[CardEvaluationCaseResult],
        thresholds: CardEvaluationThresholds,
        *,
        preflight_blockers: list[str] | None = None,
        card_ids: list[str] | None = None,
        card_versions: dict[str, int] | None = None,
        cases: list[CardEvaluationCase] | None = None,
        acceptance_outcomes: list[Outcome] | None = None,
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
            # An allowed outcome does not excuse wrong/missing/extra recipients.
            # Unlabeled delivery is unconstrained; an explicit [] requires none.
            and all(case.delivery_exact for case in successful)
            and evidence_recall >= thresholds.min_evidence_recall
            and retrieval_recall >= thresholds.min_retrieval_recall
            and unsafe_action_rate <= thresholds.max_unsafe_action_rate
            and error_rate <= thresholds.max_error_rate
            and (acceptance_outcomes is None or all(case.retrieval_precision == 1.0 for case in successful))
        )
        status = PromotionStatus.APPROVED if meets else PromotionStatus.SHADOW
        if (
            preflight_blockers
            or not results
            or errors and error_rate > thresholds.max_error_rate
        ):
            status = PromotionStatus.BLOCKED
        case_inputs = [_case_input(case) for case in (cases or [])]
        case_labels = [_case_labels(case) for case in (cases or [])]
        metrics = getattr(self, "_metrics_delta", {})
        execution_digests: dict[str, set[str]] = {}
        if acceptance_outcomes is not None:
            for case in cases or []:
                execution_digests.setdefault(case.card.id, set()).add(card_acceptance_digest(case.card))
        return CardEvaluationReport(
            evidence_admission_policy_version=EVIDENCE_ADMISSION_POLICY_VERSION,
            card_ids=card_ids or sorted({case.card_id for case in results}),
            card_versions=card_versions
            or {case.card_id: case.card_version for case in results},
            acceptance_outcomes=acceptance_outcomes,
            card_execution_digests={key: next(iter(values)) for key, values in execution_digests.items() if len(values) == 1},
            acceptance_passed=(status == PromotionStatus.APPROVED) if acceptance_outcomes is not None else None,
            acceptance_scope="supplied_snapshot_replay" if acceptance_outcomes is not None else None,
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
        )

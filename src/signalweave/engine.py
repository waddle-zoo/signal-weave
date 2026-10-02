from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from .analysis import candidate_observations, evidence_statements, observations_for_plan
from .compiler import base_plan, compile_with_typesafe
from .context import ContextProvider, context_facts_as_evidence
from .diagnostics import AnalysisReport, analyze_comparison
from .models import (
    ContextSnapshot,
    DeliveryMethod,
    Evidence,
    EvidencePlan,
    EvidenceSlot,
    InsightCard,
    InsightPlan,
    InsightResult,
    InvestigationMode,
    InvestigationSelection,
    InvestigationTrace,
    Observation,
    Outcome,
    PrincipalContext,
    QuestionStatus,
    ResourceSnapshot,
    RunTelemetry,
    SourceRef,
    WatchStatus,
    WorkflowHandoff,
)
from .retrieval import build_candidate_pool, resource_ref
from .sources import SourceRegistry
from .typesafe_adapter import (
    DEFAULT_MAX_JEV_PAYLOAD_BYTES,
    InsightJudger,
    JevJudger,
    JevPayloadError,
)


@dataclass
class InsightRun:
    card: InsightCard
    resources: list[ResourceSnapshot]
    plan: InsightPlan
    result: InsightResult


@dataclass
class _EvaluationMaterials:
    observations: list[Observation]
    evidence: list[Evidence]
    state: dict[str, Any]
    blocking_source_errors: list[dict[str, Any]]
    source_error_evidence: list[Evidence]
    source_errors: list[dict[str, Any]]
    analyses: list[AnalysisReport]


class EvaluationPayloadError(ValueError):
    """Raised before Jev when one evaluation would exceed its input budget."""

    def __init__(self, *, stage: str, observed_bytes: int, budget_bytes: int) -> None:
        self.stage = stage
        self.observed_bytes = observed_bytes
        self.budget_bytes = budget_bytes
        super().__init__(
            f"{stage} Jev payload exceeded the configured budget "
            f"({observed_bytes} > {budget_bytes} bytes)"
        )


class InsightEngine:
    """Evaluate a user-authored insight card over adapter-provided snapshots."""

    def __init__(
        self,
        judger: InsightJudger | None = None,
        registry: SourceRegistry | None = None,
        context_provider: ContextProvider | None = None,
        investigation_candidate_limit: int = 40,
        max_jev_payload_bytes: int = DEFAULT_MAX_JEV_PAYLOAD_BYTES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if investigation_candidate_limit < 1:
            raise ValueError("investigation_candidate_limit must be positive")
        if max_jev_payload_bytes < 1_024:
            raise ValueError("max_jev_payload_bytes must be at least 1024")
        self.judger = judger or JevJudger()
        self.registry = registry
        self.context_provider = context_provider
        self.investigation_candidate_limit = investigation_candidate_limit
        self.max_jev_payload_bytes = max_jev_payload_bytes
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _assert_jev_payload_budget(self, state: dict[str, Any], *, stage: str) -> int:
        """Fail closed before any Jev request can receive an oversized state."""

        serialized = json.dumps(
            state,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        observed_bytes = len(serialized.encode("utf-8"))
        if observed_bytes > self.max_jev_payload_bytes:
            raise EvaluationPayloadError(
                stage=stage,
                observed_bytes=observed_bytes,
                budget_bytes=self.max_jev_payload_bytes,
            )
        return observed_bytes

    def _judger_metrics(self) -> dict[str, int]:
        metrics = getattr(self.judger, "metrics", None)
        return {
            "requests": max(0, int(getattr(metrics, "requests", 0) or 0)),
            "input_tokens": max(0, int(getattr(metrics, "input_tokens", 0) or 0)),
            "output_tokens": max(0, int(getattr(metrics, "output_tokens", 0) or 0)),
            "payload_bytes": max(0, int(getattr(metrics, "payload_bytes", 0) or 0)),
        }

    @staticmethod
    def _source_telemetry(resources: list[ResourceSnapshot]) -> dict[str, int | float]:
        """Collect optional adapter measurements without treating them as facts."""
        totals: dict[str, int | float] = {
            "source_fetch_ms": 0.0,
            "query_calls": 0,
            "query_bytes_scanned": 0,
            "query_cache_hits": 0,
            "query_cache_misses": 0,
        }
        for resource in resources:
            telemetry = resource.metadata.get("telemetry")
            if not isinstance(telemetry, dict):
                continue
            try:
                totals["source_fetch_ms"] += max(
                    0.0,
                    float(telemetry.get("fetch_ms", telemetry.get("latency_ms", 0)) or 0),
                )
                totals["query_calls"] += max(0, int(telemetry.get("query_calls", 0) or 0))
                totals["query_bytes_scanned"] += max(
                    0,
                    int(
                        telemetry.get(
                            "query_bytes_scanned", telemetry.get("bytes_scanned", 0)
                        )
                        or 0
                    ),
                )
                totals["query_cache_hits"] += max(
                    0,
                    int(
                        telemetry.get(
                            "query_cache_hits",
                            telemetry.get(
                                "cache_hits", 1 if telemetry.get("cache_hit") is True else 0
                            ),
                        )
                        or 0
                    ),
                )
                totals["query_cache_misses"] += max(
                    0,
                    int(
                        telemetry.get(
                            "query_cache_misses",
                            telemetry.get(
                                "cache_misses", 1 if telemetry.get("cache_hit") is False else 0
                            ),
                        )
                        or 0
                    ),
                )
            except (TypeError, ValueError):
                # A malformed optional measurement must not fail an evaluation.
                continue
        return totals

    def _run_telemetry(
        self,
        *,
        started: float,
        source_fetch_ms: float,
        metrics_before: dict[str, int],
        resources: list[ResourceSnapshot],
        result: InsightResult,
        jev_payload_bytes: int,
    ) -> RunTelemetry:
        metrics_after = self._judger_metrics()
        provider = {
            key: max(0, metrics_after[key] - metrics_before[key])
            for key in metrics_after
        }
        measured_payload_bytes = provider["payload_bytes"] or jev_payload_bytes
        source = self._source_telemetry(resources)
        return RunTelemetry(
            wall_time_ms=max(0.0, (perf_counter() - started) * 1000),
            source_fetch_ms=max(float(source_fetch_ms), float(source["source_fetch_ms"])),
            source_count=len(resources),
            observation_count=len(result.observations),
            evidence_count=len(result.evidence),
            jev_requests=provider["requests"],
            jev_input_tokens=provider["input_tokens"],
            jev_output_tokens=provider["output_tokens"],
            jev_payload_bytes=measured_payload_bytes,
            jev_payload_budget_bytes=self.max_jev_payload_bytes,
            query_calls=int(source["query_calls"]),
            query_bytes_scanned=int(source["query_bytes_scanned"]),
            query_cache_hits=int(source["query_cache_hits"]),
            query_cache_misses=int(source["query_cache_misses"]),
        )

    async def compile(
        self,
        card: InsightCard,
        resources: list[ResourceSnapshot] | None = None,
    ) -> InsightPlan:
        if card.compiled_plan is not None and card.compiled_plan.card_version == card.version:
            if not card.compiled_plan.comparison_windows or not set(
                card.compiled_plan.comparison_windows
            ).issubset(card.comparison_windows):
                raise ValueError("compiled_plan comparison windows must be a nonempty subset of card windows")
            # A cached semantic selection is not authority to waive prerequisites
            # or carry fulfilled evidence into another run.
            current = base_plan(card)
            return card.compiled_plan.model_copy(update={
                "evidence_slots": current.evidence_slots,
                "questions": current.questions,
                "watch_for": current.watch_for,
                "card_scope": current.card_scope,
            })
        state = {
            "sources": (
                [resource.model_dump(mode="json") for resource in resources]
                if resources is not None
                else [source.model_dump(mode="json") for source in card.sources]
            )
        }
        self._assert_jev_payload_budget(state, stage="compile")
        return await compile_with_typesafe(card, self.judger, state=state)

    async def evaluate(
        self,
        card: InsightCard,
        resources: list[ResourceSnapshot] | None = None,
        context_override: ContextSnapshot | None = None,
        principal: PrincipalContext | None = None,
    ) -> InsightRun:
        started = perf_counter()
        metrics_before = self._judger_metrics()
        source_fetch_ms = 0.0
        authorized_tenants = [principal.tenant_id] if principal else None
        if resources is None:
            if self.registry is None:
                raise ValueError("InsightEngine needs resources or a SourceRegistry")
            source_started = perf_counter()
            resources = await self.registry.resolve(
                card.sources, authorized_tenants=authorized_tenants
            )
            source_fetch_ms += (perf_counter() - source_started) * 1000
        else:
            resources = list(resources)

        context = context_override or await self._load_context(card, resources)
        self._assert_jev_payload_budget(
            {
                "card": card.execution_payload(),
                "sources": [resource.model_dump(mode="json") for resource in resources],
                "context": context.model_dump(mode="json") if context else None,
            },
            stage="source",
        )
        plan = await self.compile(card, resources)
        investigation = await self._select_investigation(
            card, plan, resources, context, authorized_tenants=authorized_tenants
        )
        evaluation_card = card
        if investigation is not None and investigation.selected and self.registry is not None:
            selected_sources = [selection.source for selection in investigation.selected]
            source_started = perf_counter()
            selected_resources = await self.registry.resolve(
                selected_sources, authorized_tenants=authorized_tenants
            )
            source_fetch_ms += (perf_counter() - source_started) * 1000
            selected_by_key = {resource.source_key: resource for resource in selected_resources}
            updated_selections: list[InvestigationSelection] = []
            investigation_failed = investigation.failed
            investigation_warnings = list(investigation.warnings)
            for selection in investigation.selected:
                resource = selected_by_key.get(selection.source.key)
                retrieval_error = None
                retrieval_status = "succeeded"
                if resource is None:
                    retrieval_status = "failed"
                    retrieval_error = "selected source was not returned by the registry"
                elif resource.error:
                    retrieval_status = "failed"
                    retrieval_error = resource.error
                elif resource.contract.source_status != "healthy":
                    retrieval_status = "failed"
                    retrieval_error = (
                        "selected source contract status is "
                        f"{resource.contract.source_status}"
                    )
                elif not resource.observations and not resource.evidence and not resource.analytical_comparisons:
                    retrieval_status = "failed"
                    retrieval_error = "selected source returned no observations or evidence"
                if retrieval_status == "failed":
                    investigation_failed = True
                    investigation_warnings.append(
                        f"Selected follow-up source {selection.source.resource} could not be "
                        f"used: {retrieval_error}"
                    )
                updated_selections.append(
                    selection.model_copy(
                        update={
                            "retrieval_status": retrieval_status,
                            "retrieval_error": retrieval_error,
                        }
                    )
                )
            investigation = investigation.model_copy(
                update={
                    "failed": investigation_failed,
                    "selected": updated_selections,
                    "warnings": investigation_warnings,
                }
            )
            resources = [*resources, *selected_resources]
            evaluation_card = card.model_copy(
                update={
                    "sources": [*card.sources, *selected_sources],
                    "compiled_plan": None,
                }
            )
            plan = await self.compile(evaluation_card, resources)

        materials = self._evaluation_materials(
            evaluation_card, plan, resources, context, investigation
        )
        judgment_payload_bytes = self._assert_jev_payload_budget(
            materials.state, stage="judgment"
        )
        result = await self.judger.judge(
            materials.state, evaluation_card, plan, materials.observations
        )
        result = result.model_copy(
            update={"analyses": materials.analyses}
        )
        if materials.blocking_source_errors:
            # There is no reliable item-to-source dependency map here. Missing
            # required evidence cannot establish absence or refute a question.
            result = result.model_copy(update={
                "watch_results": [item.model_copy(update={"status": WatchStatus.UNKNOWN}) for item in result.watch_results],
                "question_results": [item.model_copy(update={"status": QuestionStatus.UNKNOWN}) for item in result.question_results],
            })
        result = result.model_copy(
            update={
                "context": context,
                "investigation": investigation,
                "evidence_plan": self._build_evidence_plan(
                    card=evaluation_card,
                    plan=plan,
                    result=result,
                    resources=resources,
                    context=context,
                    source_errors=materials.source_errors,
                ),
            }
        )
        result = self._apply_safety_gates(
            result,
            evaluation_card,
            plan,
            materials.observations,
            materials.blocking_source_errors,
            materials.source_error_evidence,
            materials.source_errors,
        )
        result = result.model_copy(
            update={"workflow": self._workflow_handoff(evaluation_card, result)}
        )
        result = result.model_copy(
            update={
                "telemetry": self._run_telemetry(
                    started=started,
                    source_fetch_ms=source_fetch_ms,
                    metrics_before=metrics_before,
                    resources=resources,
                    result=result,
                    jev_payload_bytes=judgment_payload_bytes,
                )
            }
        )
        return InsightRun(
            card=card,
            resources=resources,
            plan=plan,
            result=result,
        )

    @staticmethod
    def _build_evidence_plan(
        *,
        card: InsightCard,
        plan: InsightPlan,
        result: InsightResult,
        resources: list[ResourceSnapshot],
        context: ContextSnapshot | None,
        source_errors: list[dict[str, Any]] | None = None,
    ) -> EvidencePlan:
        """Resolve the compiled evidence checklist against this run's facts."""

        resources_by_key = {resource.source_key: resource for resource in resources}
        context_by_slot: dict[str, list[Any]] = {}
        if context is not None:
            for fact in context.facts:
                if fact.slot_key:
                    context_by_slot.setdefault(fact.slot_key, []).append(fact)
        slots: list[EvidenceSlot] = []
        warnings: list[str] = []
        blocking_keys = {
            error["source_key"] for error in (
                source_errors if source_errors is not None else InsightEngine._source_errors(card, resources)
            ) if error["blocking"]
        }
        blocking_keys.update(report.source_key for report in result.analyses if report.required and report.status != "complete")
        for slot in plan.evidence_slots:
            status = slot.status
            fact_ids = list(slot.evidence_fact_ids)
            evidence_source_keys = list(slot.evidence_source_keys)
            slot_facts = context_by_slot.get(slot.key, [])
            if slot_facts:
                fact_ids = [fact.fact_id for fact in slot_facts]
                evidence_source_keys = sorted({fact.subject_ref.split("|", 1)[0] for fact in slot_facts})
            if ((slot.role == "primary" and blocking_keys.intersection(slot.source_keys))
                    or (slot.role in {"watch", "question"} and blocking_keys)):
                status = "unavailable"
                fact_ids = []
                evidence_source_keys = []
            elif slot_facts and slot.role not in {"watch", "question"}:
                status = "fulfilled"
                # Slot tags associate provenance; semantic watch/question slots
                # still require Jev's evidence judgment below. Trusted context
                # may truthfully report that a condition is unknown or disputed.
            elif slot.role == "primary":
                relevant = [
                    resources_by_key[key]
                    for key in slot.source_keys
                    if key in resources_by_key
                ]
                analytical_reports = [
                    report for report in result.analyses if report.source_key in slot.source_keys
                ]
                admitted = {(report.source_key, report.comparison_key) for report in analytical_reports if report.status == "complete"}
                required_analyses = {
                    (source.key, key) for source in card.sources if source.key in slot.source_keys
                    for key in source.required_comparison_keys
                }
                if required_analyses - admitted or any(report.required and report.status != "complete" for report in analytical_reports):
                    status = "unavailable"
                elif any(
                    resource.error or resource.contract.source_status == "failed"
                    for resource in relevant
                ):
                    status = "unavailable"
                elif any(resource.observations or resource.evidence for resource in relevant) or any(
                    report.status == "complete" for report in analytical_reports
                ):
                    status = "fulfilled"
                    evidence_source_keys = sorted(resource.source_key for resource in relevant)
                else:
                    status = "pending"
            elif slot.role == "question":
                index_text = slot.key.removeprefix("question:")
                try:
                    question_result = result.question_results[int(index_text) - 1]
                except (ValueError, IndexError):
                    question_result = None
                if question_result is not None and question_result.status.value == "supported":
                    status = "fulfilled"
                else:
                    # This judgment measures answerability, not contradiction.
                    # Low support cannot identify why an answer is unavailable.
                    status = "pending"
            elif slot.role == "watch":
                index_text = slot.key.removeprefix("watch:")
                try:
                    watch_result = result.watch_results[int(index_text) - 1]
                except (ValueError, IndexError):
                    watch_result = None
                if watch_result is not None and watch_result.status.value == "present":
                    status = "fulfilled"
                elif watch_result is not None and watch_result.status.value == "absent":
                    status = "fulfilled"
            slots.append(
                slot.model_copy(
                    update={
                        "status": status,
                        "evidence_fact_ids": fact_ids,
                        "evidence_source_keys": evidence_source_keys,
                    }
                )
            )

        known_slots = {slot.key for slot in plan.evidence_slots}
        unknown_fact_slots = sorted(
            {fact.slot_key for fact in (context.facts if context else []) if fact.slot_key}
            - known_slots
        )
        if unknown_fact_slots:
            warnings.append(
                "Context supplied facts for unknown evidence slots: "
                + ", ".join(unknown_fact_slots)
            )
        missing = [slot.key for slot in slots if slot.status in {"pending", "unavailable"}]
        conflicting = [slot.key for slot in slots if slot.status == "conflicting"]
        required_missing = [
            slot.key
            for slot in slots
            if slot.required and slot.status != "fulfilled"
        ]
        status = "complete" if not required_missing else "incomplete"
        if any(slot.status == "unavailable" and slot.required for slot in slots):
            status = "blocked"
        if conflicting:
            warnings.append(
                "Some owner-authored evidence questions or watch items remain conflicting."
            )
        return EvidencePlan(
            objective=card.why_watch or card.what_to_watch,
            slots=slots,
            status=status,
            missing_slot_keys=missing,
            conflicting_slot_keys=conflicting,
            warnings=warnings,
            context_version=context.version if context else None,
        )

    @staticmethod
    def _workflow_handoff(card: InsightCard, result: InsightResult) -> WorkflowHandoff:
        """Turn the final outcome into a bounded caller-owned next step."""

        objective = card.why_watch or card.what_to_watch
        delivery_keys = [method.key for method in result.delivery_methods]
        evidence_plan = result.evidence_plan
        pending_sources = (
            sorted(
                {
                    source_key
                    for slot in evidence_plan.slots
                    if slot.status in {"pending", "unavailable"}
                    for source_key in slot.source_keys
                }
            )
            if evidence_plan
            else []
        )
        plan_instructions = ""
        if evidence_plan and evidence_plan.missing_slot_keys:
            plan_slots = {
                slot.key: slot
                for slot in evidence_plan.slots
                if slot.key in evidence_plan.missing_slot_keys
            }
            plan_instructions = "Evidence slots to complete:\n" + "\n".join(
                f"- {slot.key}: {slot.question} "
                f"(sources: {', '.join(slot.source_keys) or 'caller-authorized catalog'})"
                for slot in plan_slots.values()
            )
        if result.outcome == Outcome.IGNORE:
            return WorkflowHandoff(
                status="complete",
                step_key="suppress",
                action="suppress",
                objective=objective,
                instructions="Record the result and suppress delivery for this run.",
                completion_criteria="No further workflow step is required unless new evidence arrives.",
                evidence_plan=evidence_plan,
            )
        if result.outcome in {Outcome.NOTIFY, Outcome.ESCALATE}:
            return WorkflowHandoff(
                status="ready",
                step_key="deliver",
                action="deliver",
                objective=objective,
                instructions=(
                    "Deliver the evidence bundle to the configured destination. "
                    "Do not invent a destination or change the outcome."
                ),
                required_source_keys=sorted(set([*result.source_keys, *pending_sources])),
                completion_criteria="The caller-owned delivery adapter accepted the evidence bundle.",
                delivery_method_keys=delivery_keys,
                evidence_plan=evidence_plan,
            )
        if result.outcome == Outcome.INSUFFICIENT_DATA:
            required_sources = sorted(source.key for source in card.sources if source.required)
            return WorkflowHandoff(
                status="blocked",
                step_key="repair-source",
                action="repair_source",
                objective=objective,
                instructions=(
                    card.follow_up_guidance
                    or "Repair or validate the required source, then re-evaluate the same card."
                ),
                required_source_keys=required_sources,
                completion_criteria="Required sources are healthy and a new evaluation is submitted.",
                delivery_method_keys=delivery_keys,
                evidence_plan=evidence_plan,
            )

        selected_sources = (
            [selection.source.key for selection in result.investigation.selected]
            if result.investigation is not None
            else []
        )
        has_follow_up_guidance = bool(card.follow_up_guidance.strip())
        if not has_follow_up_guidance and delivery_keys:
            return WorkflowHandoff(
                status="ready",
                step_key="deliver",
                action="deliver",
                objective=objective,
                instructions=(
                    "Deliver the configured investigation route. This card does not define "
                    "a follow-up step, so the existing single-step behavior is terminal."
                ),
                required_source_keys=sorted(set([*result.source_keys, *pending_sources])),
                completion_criteria="The caller-owned delivery adapter accepted the evidence bundle.",
                delivery_method_keys=delivery_keys,
                evidence_plan=evidence_plan,
            )
        return WorkflowHandoff(
            status="pending" if has_follow_up_guidance else "blocked",
            step_key="investigate",
            action="retrieve_evidence" if has_follow_up_guidance else "request_review",
            objective=objective,
            instructions=(
                (card.follow_up_guidance or "Review the evidence and gather the missing context before deciding whether to notify.")
                + (f"\n\n{plan_instructions}" if plan_instructions else "")
            ),
            required_source_keys=sorted(set([*selected_sources, *pending_sources])),
            completion_criteria=(
                "Submit the follow-up evidence after completing the required evidence slots "
                "as a versioned context snapshot to the same card for re-evaluation before "
                "leadership delivery."
                if has_follow_up_guidance
                else "A human or caller-owned agent must review the evidence and decide the next retrieval."
            ),
            delivery_method_keys=delivery_keys,
            evidence_plan=evidence_plan,
        )

    async def _load_context(
        self, card: InsightCard, resources: list[ResourceSnapshot]
    ) -> ContextSnapshot | None:
        if self.context_provider is None:
            return None
        try:
            return await self.context_provider.get_context(card, resources)
        except Exception as error:  # noqa: BLE001 - context is visible but optional
            return ContextSnapshot(
                provider=self.context_provider.name,
                version="unavailable",
                trust="unverified",
                warnings=[f"Context provider failed: {type(error).__name__}: {error}"],
            )

    async def _select_investigation(
        self,
        card: InsightCard,
        plan: InsightPlan,
        resources: list[ResourceSnapshot],
        context: ContextSnapshot | None,
        *,
        authorized_tenants: list[str] | None = None,
    ) -> InvestigationTrace | None:
        if card.investigation_mode != InvestigationMode.BOUNDED:
            return None
        selector = getattr(self.judger, "select_investigation_sources", None)
        if self.registry is None or not callable(selector):
            return InvestigationTrace(
                mode=card.investigation_mode,
                candidate_count=0,
                candidate_limit=card.max_investigation_sources,
                failed=True,
                evaluator="not-configured",
                context_version=context.version if context else None,
                warnings=[
                    "Bounded investigation was requested but the registry or Jev selector "
                    "is not configured; the card will be judged over its current evidence."
                ],
            )
        goal = f"{card.what_to_watch}\nPurpose: {card.why_watch}"
        try:
            catalog_page = await self.registry.search_resources(
                goal,
                limit=self.investigation_candidate_limit,
                authorized_tenants=authorized_tenants,
            )
        except Exception as error:  # noqa: BLE001 - optional investigation fails closed
            if isinstance(error, JevPayloadError):
                raise
            return InvestigationTrace(
                mode=card.investigation_mode,
                candidate_count=0,
                candidate_limit=card.max_investigation_sources,
                failed=True,
                evaluator=getattr(selector, "name", "jev-latest"),
                context_version=context.version if context else None,
                warnings=[
                    "The authorized catalog could not be read for bounded investigation: "
                    f"{type(error).__name__}: {error}"
                ],
            )
        catalog = catalog_page.resources
        current_refs = {(resource.adapter, resource.resource) for resource in resources}
        anchors = [
            descriptor
            for descriptor in catalog
            if (descriptor.adapter, descriptor.resource)
            in {(source.adapter, source.resource) for source in card.sources}
        ]
        pool = build_candidate_pool(
            goal,
            catalog,
            anchors=anchors,
            context=context,
            limit=self.investigation_candidate_limit,
        )
        candidates = [
            resource
            for resource in pool.resources
            if (resource.adapter, resource.resource) not in current_refs
        ]
        if not candidates:
            return InvestigationTrace(
                mode=card.investigation_mode,
                attempted=False,
                candidate_count=0,
                candidate_limit=card.max_investigation_sources,
                catalog_count=catalog_page.total_count,
                catalog_has_more=catalog_page.has_more,
                catalog_strategy=catalog_page.strategy,
                evaluator=getattr(selector, "name", "jev-latest"),
                context_version=context.version if context else None,
                warnings=[
                    "No authorized follow-up candidates were available.",
                    *catalog_page.warnings,
                ],
            )
        observations = observations_for_plan(resources, plan.selected_source_keys)
        observations = self._apply_comparison_window(observations, plan)
        initial_materials = self._evaluation_materials(
            card, plan, resources, context, None
        )
        try:
            decision = await selector(
                {
                    "card": card.execution_payload(),
                    "insight_card": card.execution_payload(),
                    "insight_plan": plan.model_dump(mode="json"),
                    "observations": [item.model_dump(mode="json") for item in observations],
                    "evidence": [
                        item.model_dump(mode="json") for item in initial_materials.evidence
                    ],
                    "context": context.model_dump(mode="json") if context else None,
                    "candidate_signals": {
                        resource_ref(resource): pool.signals.get(resource_ref(resource), [])
                        for resource in candidates
                    },
                },
                card,
                plan,
                candidates,
                card.max_investigation_sources,
            )
        except Exception as error:  # noqa: BLE001 - optional investigation fails closed
            return InvestigationTrace(
                mode=card.investigation_mode,
                attempted=True,
                candidate_count=len(candidates),
                candidate_limit=card.max_investigation_sources,
                catalog_count=catalog_page.total_count,
                catalog_has_more=catalog_page.has_more,
                catalog_strategy=catalog_page.strategy,
                failed=True,
                evaluator=getattr(selector, "name", "jev-latest"),
                context_version=context.version if context else None,
                warnings=[
                    "Jev could not select a bounded follow-up source: "
                    f"{type(error).__name__}: {error}",
                    *catalog_page.warnings,
                ],
            )
        proceed_probability = max(
            0.0, min(1.0, float(decision.get("probability", 0.0)))
        )
        candidate_by_ref = {resource_ref(resource): resource for resource in candidates}
        selected: list[InvestigationSelection] = []
        warnings: list[str] = []
        if catalog_page.has_more:
            warnings.append(
                "The adapter returned a bounded catalog page; Jev did not see the full "
                "authorized catalog."
            )
        failed = False
        if proceed_probability < card.investigation_threshold:
            warnings.append(
                f"Jev did not support a bounded follow-up ({proceed_probability:.2f} < "
                f"{card.investigation_threshold:.2f}); the initial evidence was retained."
            )
        else:
            seen_refs: set[str] = set()
            for item in decision.get("selections", []):
                ref = str(item.get("ref") or "")
                candidate = candidate_by_ref.get(ref)
                if candidate is None:
                    warnings.append(f"Jev returned an unauthorized or unknown candidate: {ref}")
                    continue
                if ref in seen_refs:
                    continue
                score = max(0.0, min(1.0, float(item.get("score", 0.0))))
                confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
                if score < 0.50:
                    continue
                seen_refs.add(ref)
                selected.append(
                    InvestigationSelection(
                        source=SourceRef(
                            key=f"investigate-{len(selected) + 1}",
                            adapter=candidate.adapter,
                            resource=candidate.resource,
                            label=candidate.title,
                            required=False,
                        ),
                        score=score,
                        confidence=confidence,
                        selection_reason=(
                            "Jev selected this authorized source as potentially explanatory; "
                            "candidate signals: "
                            + ", ".join(pool.signals.get(ref, []))
                        ),
                    )
                )
                if len(selected) >= card.max_investigation_sources:
                    break
            if not selected:
                warnings.append(
                    "Jev supported a follow-up, but no authorized candidate met the "
                    "minimum explanatory score; the result cannot be treated as complete."
                )
                failed = True
        selected_refs = {selection.source.adapter + "|" + selection.source.resource for selection in selected}
        warnings.extend(catalog_page.warnings)
        return InvestigationTrace(
            mode=card.investigation_mode,
            attempted=True,
            candidate_count=len(candidates),
            candidate_limit=card.max_investigation_sources,
            catalog_count=catalog_page.total_count,
            catalog_has_more=catalog_page.has_more,
            catalog_strategy=catalog_page.strategy,
            failed=failed,
            need_probability=proceed_probability,
            selected=selected,
            omitted_refs=[resource_ref(resource) for resource in candidates if resource_ref(resource) not in selected_refs][:100],
            evaluator=getattr(selector, "name", "jev-latest"),
            context_version=context.version if context else None,
            warnings=warnings,
        )

    def _evaluation_materials(
        self,
        card: InsightCard,
        plan: InsightPlan,
        resources: list[ResourceSnapshot],
        context: ContextSnapshot | None,
        investigation: InvestigationTrace | None,
    ) -> _EvaluationMaterials:
        observations = observations_for_plan(resources, plan.selected_source_keys)
        observations = self._apply_comparison_window(observations, plan)
        source_errors = self._source_errors(card, resources, now=self.clock())
        analyses = []
        analytical_evidence = []
        required_sources = {source.key for source in card.sources if source.required}
        required_comparisons = {
            (source.key, key) for source in card.sources for key in source.required_comparison_keys
        }
        for resource in resources:
            if resource.source_key not in plan.selected_source_keys and resource.source_key not in required_sources:
                continue
            for comparison in resource.analytical_comparisons:
                report = analyze_comparison(
                    resource.source_key, comparison,
                    comparison_window=plan.comparison_windows[0] if plan.comparison_windows else None,
                )
                report = report.model_copy(update={
                    "required": resource.source_key in required_sources and (
                        comparison.required or (resource.source_key, comparison.key) in required_comparisons
                    ),
                })
                analyses.append(report)
                if report.status == "complete":
                    for observation in observations:
                        if (observation.source_key, observation.subject_id, observation.metric) != (
                            report.source_key, report.comparison_key, report.metric,
                        ):
                            continue
                        values = [(observation.current, report.current), (observation.baseline, report.baseline)]
                        conflict = any(
                            value is not None and (
                                not math.isfinite(value) or not math.isclose(
                                    value, expected, rel_tol=0, abs_tol=max(math.ulp(value), math.ulp(expected))
                                )
                            ) for value, expected in values
                        )
                        if conflict or (observation.unit != "number" and observation.unit != report.unit):
                            source_errors.append({
                                "source_key": resource.source_key, "resource": resource.resource,
                                "label": resource.title, "message": "Observation conflicts with its matched analytical comparison.",
                                "blocking": resource.source_key in required_sources,
                                "quality_status": "analysis_conflict", "source_url": resource.source_url,
                            })
                statement = (
                    f"{comparison.metric}: {report.baseline:g} to {report.current:g}; "
                    f"measured difference {report.delta:g}. {report.method} reconciles "
                    f"{len(report.contributions)} segments. This is an accounting decomposition, "
                    "not a causal explanation."
                    if report.status == "complete"
                    else f"Analysis unavailable for {comparison.metric}: " + " ".join(report.issues)
                )
                analytical_evidence.append(Evidence(
                    source_key=resource.source_key, subject_id=comparison.key,
                    subject_label=comparison.metric, statement=statement,
                    values=report.model_dump(mode="json"), origin="derived",
                    provenance=comparison.query_refs, source_url=resource.source_url,
                ))
                if report.status != "complete":
                    source_errors.append({
                        "source_key": resource.source_key, "resource": resource.resource,
                        "label": resource.title, "message": statement,
                        "blocking": report.required and resource.source_key in required_sources,
                        "quality_status": "analysis_incomplete", "source_url": resource.source_url,
                    })
        blocking_source_errors = [error for error in source_errors if error["blocking"]]
        priority_observations = candidate_observations(observations)
        priority_keys = {
            (observation.source_key, observation.subject_id, observation.metric)
            for observation in priority_observations
        }
        evidence_observations = priority_observations + [
            observation
            for observation in observations
            if (observation.source_key, observation.subject_id, observation.metric)
            not in priority_keys
        ]
        evidence = [
            Evidence(
                source_key=observation.source_key,
                subject_id=observation.subject_id,
                subject_label=observation.subject_label,
                statement=statement,
                values={
                    "current": observation.current,
                    "baseline": observation.baseline,
                    "previous": observation.previous,
                    "change_pct": observation.change_pct,
                    "freshness": observation.freshness,
                    "priority": (
                        observation.source_key,
                        observation.subject_id,
                        observation.metric,
                    )
                    in priority_keys,
                    "metric": observation.metric,
                    "unit": observation.unit,
                    "dimensions": observation.dimensions,
                    **observation.attributes,
                },
                source_url=observation.source_url,
            )
            for observation, statement in zip(
                evidence_observations,
                evidence_statements(evidence_observations),
                strict=False,
            )
        ]
        evidence.extend(
            item
            for resource in resources
            if resource.source_key in plan.selected_source_keys
            for item in resource.evidence
        )
        source_error_evidence = [
            Evidence(
                source_key=error["source_key"],
                subject_id=error["resource"],
                subject_label=error["label"],
                statement=error["message"],
                values={
                    "error": error["message"],
                    "blocking": error["blocking"],
                    "quality_status": error.get("quality_status"),
                },
                source_url=error.get("source_url"),
                origin="derived",
            )
            for error in source_errors
        ]
        evidence.extend(source_error_evidence)
        evidence.extend(context_facts_as_evidence(context))
        evidence.extend(analytical_evidence)
        from .numeric_conditions import evaluate_numeric_conditions

        unhealthy_keys = {error["source_key"] for error in source_errors}
        numeric_conditions = evaluate_numeric_conditions(
            card, [report for report in analyses if report.source_key not in unhealthy_keys]
        )
        state: dict[str, Any] = {
            "card": card.execution_payload(),
            "insight_card": card.execution_payload(),
            "insight_plan": plan.model_dump(mode="json"),
            "sources": [resource.model_dump(mode="json") for resource in resources],
            "observations": [observation.model_dump(mode="json") for observation in observations],
            "priority_observations": [
                observation.model_dump(mode="json") for observation in priority_observations
            ],
            "source_errors": source_errors,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "analyses": [item.model_dump(mode="json") for item in analyses],
            "numeric_conditions": [item.model_dump(mode="json") for item in numeric_conditions],
            "context": context.model_dump(mode="json") if context else None,
            "investigation": investigation.model_dump(mode="json") if investigation else None,
        }
        return _EvaluationMaterials(
            observations=observations,
            evidence=evidence,
            state=state,
            blocking_source_errors=blocking_source_errors,
            source_error_evidence=source_error_evidence,
            source_errors=source_errors,
            analyses=analyses,
        )

    @staticmethod
    def _apply_comparison_window(
        observations: list[Observation], plan: InsightPlan
    ) -> list[Observation]:
        """Use the compiled window when the source exposes that baseline."""
        window = plan.comparison_windows[0] if plan.comparison_windows else "previous_period"
        if window == "previous_period":
            return observations
        adjusted: list[Observation] = []
        for observation in observations:
            # A card can request several windows while an adapter only exposes
            # one of them. Preserve the adapter's ordinary baseline when the
            # selected window is unavailable; otherwise a valid comparison is
            # accidentally turned into insufficient data.
            baseline = observation.comparison_baselines.get(window, observation.baseline)
            change_pct = None
            if baseline is not None and observation.current is not None and baseline != 0:
                change_pct = round(
                    (observation.current - baseline) / abs(baseline) * 100, 3
                )
            adjusted.append(
                observation.model_copy(
                    update={"baseline": baseline, "change_pct": change_pct}
                )
            )
        return adjusted

    @staticmethod
    def _source_errors(
        card: InsightCard, resources: list[ResourceSnapshot], *, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        declared = {source.key: source for source in card.sources}
        provided = {resource.source_key: resource for resource in resources}
        errors: list[dict[str, Any]] = []
        if not declared:
            errors.append(
                {
                    "source_key": "*",
                    "resource": "*",
                    "label": "Insight card sources",
                    "message": "The insight card declares no source references.",
                    "source_url": None,
                    "blocking": True,
                }
            )
        for key, source in declared.items():
            resource = provided.get(key)
            if resource is None:
                errors.append(
                    {
                        "source_key": key,
                        "resource": source.resource,
                        "label": source.label,
                        "message": f"Source {key} was not returned by its adapter.",
                        "source_url": None,
                        "blocking": source.required,
                    }
                )
            elif resource.error:
                errors.append(
                    {
                        "source_key": key,
                        "resource": source.resource,
                        "label": resource.title or source.label,
                        "message": resource.error,
                        "source_url": resource.source_url,
                        "blocking": source.required,
                    }
                )
            if resource is not None:
                returned_keys = [comparison.key for comparison in resource.analytical_comparisons]
                missing_keys = set(source.required_comparison_keys) - set(returned_keys)
                if missing_keys or len(returned_keys) != len(set(returned_keys)):
                    errors.append({
                        "source_key": key, "resource": source.resource, "label": source.label,
                        "message": "Required analytical comparisons are missing or comparison keys are duplicated.",
                        "source_url": resource.source_url, "blocking": source.required,
                        "quality_status": "analysis_incomplete",
                    })
            if resource is not None and not resource.error and not resource.observations and not resource.evidence and not resource.analytical_comparisons:
                errors.append(
                    {
                        "source_key": key,
                        "resource": source.resource,
                        "label": resource.title or source.label,
                        "message": "Source returned no observations or evidence.",
                        "source_url": resource.source_url,
                        "blocking": source.required,
                    }
                )
            if resource is not None and resource.contract.source_status != "healthy":
                status = resource.contract.source_status
                errors.append(
                    {
                        "source_key": key,
                        "resource": source.resource,
                        "label": resource.title or source.label,
                        "message": f"Source contract status is {status}.",
                        "source_url": resource.source_url,
                        "blocking": source.required and status in {"failed", "unknown"},
                        "quality_status": status,
                    }
                )
            quality = resource.metadata.get("data_quality") if resource is not None else None
            if isinstance(quality, dict) and quality.get("status") == "partial":
                chart_errors = quality.get("chart_errors", [])
                baseline_gaps = quality.get("missing_baseline_chart_ids", [])
                generic_issues = quality.get("issues", [])
                if not isinstance(chart_errors, list):
                    chart_errors = [str(chart_errors)] if chart_errors else []
                if not isinstance(baseline_gaps, list):
                    baseline_gaps = [str(baseline_gaps)] if baseline_gaps else []
                if not isinstance(generic_issues, list):
                    generic_issues = [str(generic_issues)] if generic_issues else []
                issue_count = len(chart_errors) + len(baseline_gaps) + len(generic_issues)
                blocking = quality.get("blocking")
                if not isinstance(blocking, bool):
                    # Preserve the existing Superset contract while allowing
                    # non-dashboard adapters to declare their own quality
                    # issues without inventing chart-shaped fields.
                    blocking = bool(chart_errors)
                errors.append(
                    {
                        "source_key": key,
                        "resource": source.resource,
                        "label": resource.title or source.label,
                        "message": (
                            "Source returned partial evidence: "
                            f"{issue_count} quality issue(s)."
                        ),
                        "source_url": resource.source_url,
                        "blocking": source.required and blocking,
                        "quality_status": "partial",
                    }
                )
            if resource is not None and card.max_source_age_hours is not None:
                captured_at = resource.source_captured_at or resource.captured_at
                if captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=timezone.utc)
                age_hours = ((now or datetime.now(timezone.utc)) - captured_at).total_seconds() / 3600
                if age_hours > card.max_source_age_hours:
                    errors.append(
                        {
                            "source_key": key,
                            "resource": source.resource,
                            "label": resource.title or source.label,
                            "message": (
                                f"Source snapshot is {age_hours:.1f} hours old; maximum is "
                                f"{card.max_source_age_hours:g} hours."
                            ),
                            "source_url": resource.source_url,
                            "blocking": source.required,
                        }
                    )
        return errors

    @staticmethod
    def _delivery_methods_for(card: InsightCard, outcome: Outcome) -> list[DeliveryMethod]:
        return [method for method in card.delivery_methods if method.outcome == outcome]

    @classmethod
    def _with_outcome(
        cls,
        result: InsightResult,
        card: InsightCard,
        outcome: Outcome,
        **updates: Any,
    ) -> InsightResult:
        updates = {
            **updates,
            "outcome": outcome,
            "delivery_methods": cls._delivery_methods_for(card, outcome),
        }
        return result.model_copy(update=updates)

    @classmethod
    def _apply_safety_gates(
        cls,
        result: InsightResult,
        card: InsightCard,
        plan: InsightPlan,
        observations: list[Observation],
        blocking_source_errors: list[dict[str, Any]],
        source_error_evidence: list[Evidence],
        source_errors: list[dict[str, Any]],
    ) -> InsightResult:
        safe_outcomes = {Outcome.IGNORE, Outcome.INVESTIGATE, Outcome.INSUFFICIENT_DATA}
        configured_outcomes = {method.outcome for method in card.delivery_methods}
        available_outcomes = safe_outcomes | configured_outcomes
        if result.outcome not in available_outcomes:
            return cls._with_outcome(
                result,
                card,
                Outcome.INVESTIGATE,
                rationale=(
                    f"The semantic result returned unavailable outcome "
                    f"{result.outcome.value}; routed to investigate."
                ),
            )

        if blocking_source_errors:
            existing_evidence = {
                (item.source_key, item.subject_id, item.statement) for item in result.evidence
            }
            new_evidence = list(result.evidence)
            new_evidence.extend(
                item
                for item in source_error_evidence
                if (item.source_key, item.subject_id, item.statement) not in existing_evidence
            )
            return cls._with_outcome(
                result,
                card,
                Outcome.INSUFFICIENT_DATA,
                rationale=(
                    "One or more required card sources were unavailable, so no automatic "
                    "interpretation is safe."
                ),
                confidence=max(result.confidence or 0.0, 0.95),
                evidence=new_evidence,
            )

        if result.investigation is not None and result.investigation.failed:
            return cls._with_outcome(
                result,
                card,
                Outcome.INVESTIGATE,
                rationale=(
                    "The bounded investigation stage failed before it could establish the "
                    "requested follow-up evidence, so the result requires review."
                ),
            )

        from .numeric_conditions import evaluate_numeric_conditions

        required_keys = {source.key for source in card.sources if source.required}
        failed_keys = {error["source_key"] for error in source_errors}
        unresolved_numeric = [
            item for item in evaluate_numeric_conditions(
                card, [analysis for analysis in result.analyses if analysis.source_key not in failed_keys]
            ) if item.status == "unknown" and item.source_key in required_keys
        ]
        if unresolved_numeric:
            return cls._with_outcome(
                result, card, Outcome.INSUFFICIENT_DATA,
                rationale=(
                    "A numeric check bound to required evidence could not be computed. "
                    "Repair its measurement binding, unit, or source before automatic interpretation."
                ),
            )

        if (
            result.context is not None
            and result.context.trust == "unverified"
            and result.context.facts
            and result.outcome in {Outcome.NOTIFY, Outcome.ESCALATE}
        ):
            return cls._with_outcome(
                result,
                card,
                Outcome.INVESTIGATE,
                rationale=(
                    "The result used caller-supplied context marked unverified; a trusted "
                    "context provider or human review is required before automatic action."
                ),
            )

        if (
            result.evidence_plan is not None
            and result.outcome in {Outcome.NOTIFY, Outcome.ESCALATE}
            and result.evidence_plan.status != "complete"
        ):
            return cls._with_outcome(
                result,
                card,
                Outcome.INVESTIGATE,
                rationale=(
                    "The card-defined evidence plan is not complete, so the agent must "
                    "retrieve the missing or conflicting evidence before automatic delivery."
                ),
            )

        required_source_keys = {
            source.key for source in card.sources if source.required
        }
        stale = [
            observation
            for observation in observations
            if observation.source_key in required_source_keys
            and observation.freshness
            and "stale" in observation.freshness.lower()
        ]
        stale_keys = {
            error["source_key"]
            for error in source_errors
            if error.get("quality_status") == "stale"
        }
        stale.extend(
            observation
            for observation in observations
            if observation.source_key in required_source_keys
            and observation.source_key in stale_keys
            and observation not in stale
        )
        if stale or stale_keys & required_source_keys:
            stale_outcome = (
                Outcome.ESCALATE
                if cls._delivery_methods_for(card, Outcome.ESCALATE)
                else Outcome.INVESTIGATE
            )
            return cls._with_outcome(
                result,
                card,
                stale_outcome,
                rationale=(
                    "A freshness gate found stale evidence; the result requires attention "
                    "before interpreting the movement."
                ),
                confidence=max(result.confidence or 0.0, 0.99),
            )

        ambiguous = [
            observation
            for observation in observations
            if observation.source_key in required_source_keys
            and str(observation.attributes.get("source_status", "")).lower() == "ambiguous"
        ]
        ambiguous_keys = {
            error["source_key"] for error in source_errors
            if error.get("quality_status") == "ambiguous"
        }
        if (ambiguous or ambiguous_keys & required_source_keys) and result.outcome in {Outcome.NOTIFY, Outcome.ESCALATE}:
            return cls._with_outcome(
                result,
                card,
                Outcome.INVESTIGATE,
                rationale=(
                    "One or more selected sources were marked ambiguous by the adapter, "
                    "so no automatic route is safe until the definitions are reconciled."
                ),
            )

        numeric_observations = [
            observation for observation in observations if observation.current is not None
        ]
        analyzed_observations = {
            (report.source_key, report.comparison_key, report.metric)
            for report in result.analyses if report.status == "complete"
        }
        incomplete_baselines = [
            observation
            for observation in numeric_observations
            if observation.source_key in required_source_keys
            and (observation.source_key, observation.subject_id, observation.metric) not in analyzed_observations
            and (observation.baseline is None or observation.change_pct is None)
        ]
        comparable_baselines = [
            observation
            for observation in numeric_observations
            if observation.source_key in required_source_keys
            and observation.baseline is not None
            and observation.change_pct is not None
        ]
        if incomplete_baselines and not comparable_baselines:
            return cls._with_outcome(
                result,
                card,
                Outcome.INSUFFICIENT_DATA,
                rationale=(
                    f"{len(incomplete_baselines)} numeric observation(s) were returned without "
                    "a comparable baseline and no required observation had one, so no "
                    "automatic interpretation is safe."
                ),
                confidence=max(result.confidence or 0.0, 0.95),
            )

        if (
            result.outcome in (Outcome.IGNORE, Outcome.NOTIFY, Outcome.ESCALATE)
            and (
                result.confidence is None
                or result.confidence < card.action_confidence_threshold
            )
        ):
            confidence_text = (
                f"confidence {result.confidence:.2f}"
                if result.confidence is not None
                else "no confidence"
            )
            return cls._with_outcome(
                result,
                card,
                Outcome.INVESTIGATE,
                rationale=(
                    f"The semantic result was {result.outcome.value}, but {confidence_text} "
                    "is below the automatic-action threshold."
                ),
            )

        if result.outcome in (Outcome.NOTIFY, Outcome.ESCALATE) and not cls._delivery_methods_for(
            card, result.outcome
        ):
            return cls._with_outcome(
                result,
                card,
                Outcome.INVESTIGATE,
                rationale=(
                    "An automatic outcome was selected without a configured delivery method, "
                    "so it requires investigation."
                ),
            )

        # Delivery routes are always selected from the stored card, never from
        # model output. This keeps destinations and side effects code-owned.
        return result.model_copy(
            update={"delivery_methods": cls._delivery_methods_for(card, result.outcome)}
        )

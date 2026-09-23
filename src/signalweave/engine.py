from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from .analysis import candidate_observations, evidence_statements, observations_for_plan
from .compiler import compile_with_typesafe
from .context import ContextProvider, context_facts_as_evidence
from .models import (
    ContextSnapshot,
    DeliveryMethod,
    Evidence,
    InsightCard,
    InsightPlan,
    InsightResult,
    InvestigationMode,
    InvestigationSelection,
    InvestigationTrace,
    Observation,
    Outcome,
    PrincipalContext,
    ResourceSnapshot,
    RunTelemetry,
    SourceRef,
)
from .retrieval import build_candidate_pool, resource_ref
from .sources import SourceRegistry
from .typesafe_adapter import InsightJudger, JevJudger


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
    blocking_partial_source_errors: list[dict[str, Any]]
    source_error_evidence: list[Evidence]
    source_errors: list[dict[str, Any]]


class InsightEngine:
    """Evaluate a user-authored insight card over adapter-provided snapshots."""

    def __init__(
        self,
        judger: InsightJudger | None = None,
        registry: SourceRegistry | None = None,
        context_provider: ContextProvider | None = None,
        investigation_candidate_limit: int = 40,
    ) -> None:
        if investigation_candidate_limit < 1:
            raise ValueError("investigation_candidate_limit must be positive")
        self.judger = judger or JevJudger()
        self.registry = registry
        self.context_provider = context_provider
        self.investigation_candidate_limit = investigation_candidate_limit

    def _judger_metrics(self) -> dict[str, int]:
        metrics = getattr(self.judger, "metrics", None)
        return {
            "requests": max(0, int(getattr(metrics, "requests", 0) or 0)),
            "input_tokens": max(0, int(getattr(metrics, "input_tokens", 0) or 0)),
            "output_tokens": max(0, int(getattr(metrics, "output_tokens", 0) or 0)),
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
    ) -> RunTelemetry:
        metrics_after = self._judger_metrics()
        provider = {
            key: max(0, metrics_after[key] - metrics_before[key])
            for key in metrics_after
        }
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
            return card.compiled_plan
        state = {
            "sources": (
                [resource.model_dump(mode="json") for resource in resources]
                if resources is not None
                else [source.model_dump(mode="json") for source in card.sources]
            )
        }
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
                elif not resource.observations and not resource.evidence:
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
        result = await self.judger.judge(
            materials.state, evaluation_card, plan, materials.observations
        )
        result = result.model_copy(
            update={"context": context, "investigation": investigation}
        )
        result = self._apply_safety_gates(
            result,
            evaluation_card,
            plan,
            materials.observations,
            materials.blocking_source_errors,
            materials.blocking_partial_source_errors,
            materials.source_error_evidence,
            materials.source_errors,
        )
        result = result.model_copy(
            update={
                "telemetry": self._run_telemetry(
                    started=started,
                    source_fetch_ms=source_fetch_ms,
                    metrics_before=metrics_before,
                    resources=resources,
                    result=result,
                )
            }
        )
        return InsightRun(
            card=card,
            resources=resources,
            plan=plan,
            result=result,
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
                    "card": card.model_dump(mode="json"),
                    "insight_card": card.model_dump(mode="json"),
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
        source_errors = self._source_errors(card, resources)
        blocking_source_errors = [error for error in source_errors if error["blocking"]]
        blocking_partial_source_errors = [
            error
            for error in source_errors
            if error.get("quality_status") == "partial" and error["blocking"]
        ]
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
        state: dict[str, Any] = {
            "card": card.model_dump(mode="json"),
            "insight_card": card.model_dump(mode="json"),
            "insight_plan": plan.model_dump(mode="json"),
            "sources": [resource.model_dump(mode="json") for resource in resources],
            "observations": [observation.model_dump(mode="json") for observation in observations],
            "priority_observations": [
                observation.model_dump(mode="json") for observation in priority_observations
            ],
            "source_errors": source_errors,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "context": context.model_dump(mode="json") if context else None,
            "investigation": investigation.model_dump(mode="json") if investigation else None,
        }
        return _EvaluationMaterials(
            observations=observations,
            evidence=evidence,
            state=state,
            blocking_source_errors=blocking_source_errors,
            blocking_partial_source_errors=blocking_partial_source_errors,
            source_error_evidence=source_error_evidence,
            source_errors=source_errors,
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
        card: InsightCard, resources: list[ResourceSnapshot]
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
            elif not resource.observations and not resource.evidence:
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
                errors.append(
                    {
                        "source_key": key,
                        "resource": source.resource,
                        "label": resource.title or source.label,
                        "message": (
                            "Source returned partial evidence: "
                            f"{len(quality.get('chart_errors', []))} chart error(s), "
                            f"{len(quality.get('missing_baseline_chart_ids', []))} chart(s) "
                            "without a comparable baseline."
                        ),
                        "source_url": resource.source_url,
                        "blocking": source.required and bool(quality.get("chart_errors")),
                        "quality_status": "partial",
                    }
                )
            if resource is not None and card.max_source_age_hours is not None:
                captured_at = resource.captured_at
                if captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - captured_at).total_seconds() / 3600
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
        blocking_partial_source_errors: list[dict[str, Any]],
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

        if blocking_partial_source_errors:
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
                    "One or more required sources returned partial evidence, so no automatic "
                    "interpretation is safe until the missing dashboard data is resolved."
                ),
                confidence=max(result.confidence or 0.0, 0.95),
                evidence=new_evidence,
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
        if stale:
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
        if ambiguous and result.outcome in {Outcome.NOTIFY, Outcome.ESCALATE}:
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
        incomplete_baselines = [
            observation
            for observation in numeric_observations
            if observation.source_key in required_source_keys
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

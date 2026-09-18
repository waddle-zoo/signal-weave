from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .analysis import candidate_observations, evidence_statements, observations_for_plan
from .compiler import compile_with_typesafe
from .models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    InsightPlan,
    InsightResult,
    Observation,
    Outcome,
    ResourceSnapshot,
)
from .sources import SourceRegistry
from .typesafe_adapter import InsightJudger, JevJudger


@dataclass
class InsightRun:
    card: InsightCard
    resources: list[ResourceSnapshot]
    plan: InsightPlan
    result: InsightResult


class InsightEngine:
    """Evaluate a user-authored insight card over adapter-provided snapshots."""

    def __init__(
        self,
        judger: InsightJudger | None = None,
        registry: SourceRegistry | None = None,
    ) -> None:
        self.judger = judger or JevJudger()
        self.registry = registry

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
    ) -> InsightRun:
        if resources is None:
            if self.registry is None:
                raise ValueError("InsightEngine needs resources or a SourceRegistry")
            resources = await self.registry.resolve(card.sources)
        else:
            resources = list(resources)

        plan = await self.compile(card, resources)
        observations = observations_for_plan(resources, plan.selected_source_keys)
        observations = self._apply_comparison_window(observations, plan)
        source_errors = self._source_errors(card, resources)
        blocking_source_errors = [error for error in source_errors if error["blocking"]]
        blocking_partial_source_errors = [
            error
            for error in source_errors
            if error.get("quality_status") == "partial" and error["blocking"]
        ]

        # Priority ordering helps a client render the interesting rows first. It
        # is not a retrieval boundary: all observations remain in state/evidence.
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
            )
            for error in source_errors
        ]
        evidence.extend(source_error_evidence)
        evidence_payload = [item.model_dump(mode="json") for item in evidence]
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
            "evidence": evidence_payload,
        }
        result = await self.judger.judge(state, card, plan, observations)
        result = self._apply_safety_gates(
            result,
            card,
            plan,
            observations,
            blocking_source_errors,
            blocking_partial_source_errors,
            source_error_evidence,
        )
        return InsightRun(card=card, resources=resources, plan=plan, result=result)

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
                        "blocking": source.required,
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
        if incomplete_baselines:
            return cls._with_outcome(
                result,
                card,
                Outcome.INSUFFICIENT_DATA,
                rationale=(
                    f"{len(incomplete_baselines)} numeric observation(s) were returned without "
                    "a comparable baseline, so no automatic interpretation is safe."
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

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analysis import candidate_observations, evidence_statements, observations_for_plan
from .compiler import compile_with_typesafe
from .models import (
    Decision,
    Evidence,
    MonitorPlan,
    MonitorWorkflow,
    Observation,
    Outcome,
    ResourceSnapshot,
)
from .sources import SourceRegistry
from .typesafe_adapter import DecisionJudger, JevJudger


@dataclass
class Evaluation:
    workflow: MonitorWorkflow
    resources: list[ResourceSnapshot]
    plan: MonitorPlan
    decision: Decision


class MonitorEngine:
    """Evaluate a user workflow over one or more adapter-provided snapshots."""

    def __init__(
        self,
        judger: DecisionJudger | None = None,
        registry: SourceRegistry | None = None,
    ) -> None:
        self.judger = judger or JevJudger()
        self.registry = registry

    async def compile(
        self,
        workflow: MonitorWorkflow,
        resources: list[ResourceSnapshot] | None = None,
    ) -> MonitorPlan:
        state = {
            "sources": (
                [resource.model_dump(mode="json") for resource in resources]
                if resources is not None
                else [source.model_dump(mode="json") for source in workflow.sources]
            )
        }
        return await compile_with_typesafe(workflow, self.judger, state=state)

    async def evaluate(
        self,
        workflow: MonitorWorkflow,
        resources: list[ResourceSnapshot] | None = None,
    ) -> Evaluation:
        if resources is None:
            if self.registry is None:
                raise ValueError("MonitorEngine needs resources or a SourceRegistry")
            resources = await self.registry.resolve(workflow.sources)
        else:
            resources = list(resources)

        plan = await self.compile(workflow, resources)
        observations = observations_for_plan(resources, plan.selected_source_keys)
        source_errors = self._source_errors(workflow, resources)
        blocking_source_errors = [error for error in source_errors if error["blocking"]]
        candidates = candidate_observations(observations, workflow)
        candidate_keys = {
            (observation.source_key, observation.subject_id, observation.metric)
            for observation in candidates
        }
        evidence_observations = candidates + [
            observation
            for observation in observations
            if (observation.source_key, observation.subject_id, observation.metric)
            not in candidate_keys
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
                    "candidate": (
                        observation.source_key,
                        observation.subject_id,
                        observation.metric,
                    )
                    in candidate_keys,
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
                values={"error": error["message"], "blocking": error["blocking"]},
                source_url=error.get("source_url"),
            )
            for error in source_errors
        ]
        evidence.extend(source_error_evidence)
        evidence_payload = [item.model_dump(mode="json") for item in evidence]
        state: dict[str, Any] = {
            "workflow": workflow.model_dump(mode="json"),
            "monitor_workflow": workflow.model_dump(mode="json"),
            "monitor_plan": plan.model_dump(mode="json"),
            "sources": [resource.model_dump(mode="json") for resource in resources],
            "observations": [observation.model_dump(mode="json") for observation in observations],
            "candidate_observations": [
                observation.model_dump(mode="json") for observation in candidates
            ],
            "source_errors": source_errors,
            "evidence": evidence_payload,
        }
        decision = await self.judger.judge(state, workflow, plan, observations)
        decision = self._apply_safety_gates(
            decision,
            workflow,
            observations,
            blocking_source_errors,
            source_error_evidence,
        )
        return Evaluation(
            workflow=workflow,
            resources=resources,
            plan=plan,
            decision=decision,
        )

    @staticmethod
    def _source_errors(
        workflow: MonitorWorkflow, resources: list[ResourceSnapshot]
    ) -> list[dict[str, Any]]:
        declared = {source.key: source for source in workflow.sources}
        provided = {resource.source_key: resource for resource in resources}
        errors: list[dict[str, Any]] = []
        if not declared:
            errors.append(
                {
                    "source_key": "*",
                    "resource": "*",
                    "label": "Workflow sources",
                    "message": "The workflow declares no source references.",
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
        return errors

    @staticmethod
    def _apply_safety_gates(
        decision: Decision,
        workflow: MonitorWorkflow,
        observations: list[Observation],
        blocking_source_errors: list[dict[str, Any]],
        source_error_evidence: list[Evidence],
    ) -> Decision:
        allowed_recipient_keys = {recipient.key for recipient in workflow.recipients}
        if decision.outcome not in (Outcome.NOTIFY, Outcome.ESCALATE) or (
            decision.recipient_key not in allowed_recipient_keys
        ):
            decision = decision.model_copy(update={"recipient_key": None})
        if blocking_source_errors:
            outcome = (
                Outcome.INSUFFICIENT_DATA
                if Outcome.INSUFFICIENT_DATA in workflow.allowed_outcomes
                else Outcome.INVESTIGATE
            )
            existing_evidence = {
                (item.source_key, item.subject_id, item.statement) for item in decision.evidence
            }
            new_evidence = list(decision.evidence)
            new_evidence.extend(
                item
                for item in source_error_evidence
                if (item.source_key, item.subject_id, item.statement) not in existing_evidence
            )
            return decision.model_copy(
                update={
                    "outcome": outcome,
                    "recipient_key": None,
                    "rationale": "One or more required workflow sources were unavailable, so no automatic action is safe.",
                    "confidence": max(decision.confidence or 0.0, 0.95),
                    "evidence": new_evidence,
                }
            )
        stale = [
            observation
            for observation in observations
            if observation.freshness and "stale" in observation.freshness.lower()
        ]
        if stale and Outcome.ESCALATE in workflow.allowed_outcomes:
            if not workflow.recipients:
                return decision.model_copy(
                    update={
                        "outcome": Outcome.INVESTIGATE,
                        "recipient_key": None,
                        "rationale": "A workflow source is stale, but no approved recipient is available for escalation.",
                    }
                )
            return decision.model_copy(
                update={
                    "outcome": Outcome.ESCALATE,
                    "recipient_key": workflow.recipients[0].key,
                    "rationale": "A hard freshness gate requires escalation before interpreting the workflow sources.",
                    "confidence": max(decision.confidence or 0.0, 0.99),
                }
            )
        if observations and not any(observation.change_pct is not None for observation in observations):
            outcome = (
                Outcome.INSUFFICIENT_DATA
                if Outcome.INSUFFICIENT_DATA in workflow.allowed_outcomes
                else Outcome.INVESTIGATE
            )
            return decision.model_copy(
                update={
                    "outcome": outcome,
                    "recipient_key": None,
                    "rationale": "The workflow returned observations but no comparable baseline, so no automatic action is safe.",
                    "confidence": max(decision.confidence or 0.0, 0.95),
                }
            )
        if (
            decision.outcome in (Outcome.IGNORE, Outcome.NOTIFY, Outcome.ESCALATE)
            and (
                decision.confidence is None
                or decision.confidence < workflow.action_confidence_threshold
            )
        ):
            confidence_text = (
                f"confidence {decision.confidence:.2f}"
                if decision.confidence is not None
                else "no confidence"
            )
            return decision.model_copy(
                update={
                    "outcome": Outcome.INVESTIGATE,
                    "recipient_key": None,
                    "rationale": f"The semantic decision was {decision.outcome.value}, but {confidence_text} is below the automatic-action threshold.",
                }
            )
        if decision.outcome in (Outcome.NOTIFY, Outcome.ESCALATE) and decision.recipient_key is None:
            return decision.model_copy(
                update={
                    "outcome": Outcome.INVESTIGATE,
                    "rationale": "An automatic action was selected without an approved recipient, so it requires investigation.",
                }
            )
        return decision

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from .compiler import SUPPORTED_OPERATIONS
from .models import (
    MonitorCardProposal,
    MonitorWorkflow,
    Recipient,
    ResourceDescriptor,
    ResourceDiscovery,
    ResourceMatch,
    SourceRef,
)
from .sources import SourceRegistry


class ResourceRelevanceJudger(Protocol):
    """The Jev capability required to rank bounded catalog candidates."""

    name: str

    async def rank_resources(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> dict[str, float]: ...


def resource_ref(resource: ResourceDescriptor) -> str:
    """Return the opaque reference an MCP client can pass back after selection."""
    return f"{resource.adapter}|{resource.resource}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "monitor"


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", value.lower()) if len(term) > 2}


def _search_text(resource: ResourceDescriptor) -> str:
    metadata = " ".join(str(value) for value in resource.metadata.values())
    return " ".join(
        [resource.adapter, resource.resource, resource.kind, resource.title, resource.description, metadata]
    )


@dataclass
class MonitorAuthoringService:
    """Conversation-facing monitor-card authoring over installed source adapters.

    Candidate retrieval is deliberately bounded before Jev sees the catalog. The
    lexical prefilter is only a recall guard for very large catalogs; Jev remains
    the required semantic ranker and there is no local relevance fallback.
    """

    registry: SourceRegistry
    engine: Any
    max_candidates: int = 40
    recommendation_threshold: float = 0.60

    async def discover(
        self,
        goal: str,
        *,
        adapter: str | None = None,
        limit: int = 10,
    ) -> ResourceDiscovery:
        if not goal.strip():
            raise ValueError("monitoring goal must not be empty")
        if not 1 <= limit <= 25:
            raise ValueError("limit must be between 1 and 25")
        resources = await self.registry.list_resources(adapter)
        candidates, truncated = self._bounded_candidates(goal, resources)
        judger = self._relevance_judger()
        scores = await judger.rank_resources(goal, candidates)
        matches = [
            ResourceMatch(
                ref=resource_ref(resource),
                adapter=resource.adapter,
                resource=resource.resource,
                kind=resource.kind,
                title=resource.title,
                description=resource.description,
                source_url=resource.source_url,
                relevance=max(0.0, min(1.0, float(scores.get(resource_ref(resource), 0.0)))),
            )
            for resource in candidates
        ]
        matches.sort(key=lambda match: (-match.relevance, match.title.lower(), match.ref))
        visible = matches[:limit]
        if visible and not any(match.relevance >= self.recommendation_threshold for match in visible):
            visible[0] = visible[0].model_copy(update={"recommended": True})
        else:
            visible = [
                match.model_copy(update={"recommended": match.relevance >= self.recommendation_threshold})
                for match in visible
            ]
        return ResourceDiscovery(
            goal=goal,
            matches=visible,
            candidate_count=len(resources),
            candidate_limit=self.max_candidates,
            truncated=truncated,
            evaluator=judger.name,
        )

    async def propose(
        self,
        goal: str,
        *,
        selected_sources: list[dict[str, Any]] | None = None,
        adapter: str | None = None,
        limit: int = 10,
        comparison_windows: list[str] | None = None,
        materiality_threshold_pct: float = 10.0,
        materiality_definition: str | None = None,
        recipients: list[Recipient] | None = None,
        owner: str | None = None,
    ) -> MonitorCardProposal:
        discovery = await self.discover(goal, adapter=adapter, limit=limit)
        matches = {match.ref: match for match in discovery.matches}
        requested = selected_sources
        if requested is None:
            requested = [{"ref": match.ref} for match in discovery.matches if match.recommended]
        unknown = [item.get("ref") for item in requested if item.get("ref") not in matches]
        if unknown:
            raise ValueError(
                "selected source refs must come from discover_monitor_inputs: "
                + ", ".join(str(item) for item in unknown)
            )
        source_refs = [
            SourceRef(
                key=f"source-{_slug(str(item['ref']))}",
                adapter=matches[item["ref"]].adapter,
                resource=matches[item["ref"]].resource,
                label=str(item.get("label") or matches[item["ref"]].title),
                parameters=item.get("parameters") or {},
                required=bool(item.get("required", True)),
            )
            for item in requested
        ]
        title = goal.strip().rstrip(".")[:200] or "Operational monitor"
        workflow = MonitorWorkflow(
            id=f"workflow-{_slug(title)}-{uuid4().hex[:8]}",
            title=title,
            intent=goal,
            sources=source_refs,
            comparison_windows=comparison_windows
            or ["previous_period", "trailing_4_period_average"],
            materiality_threshold_pct=materiality_threshold_pct,
            materiality_definition=materiality_definition,
            recipients=recipients or [],
            owner=owner,
        )
        plan = await self.engine.compile(workflow)
        questions: list[str] = []
        if not source_refs:
            questions.append("Select at least one source candidate before approval.")
        if not workflow.recipients:
            questions.append("Choose the configured recipient groups for notify or escalate outcomes.")
        if not workflow.materiality_definition:
            questions.append(
                f"Define what counts as material, or confirm the starting threshold of "
                f"{workflow.materiality_threshold_pct:g}%.")
        if plan.comparison_windows:
            questions.append(
                f"Confirm the comparison window proposed by Jev: {plan.comparison_windows[0]}."
            )
        if discovery.truncated:
            questions.append(
                "Confirm the selected sources; discovery used a bounded candidate set "
                f"from {discovery.candidate_count} catalog resources."
            )
        return MonitorCardProposal(
            workflow=workflow,
            plan=plan,
            discovery=discovery,
            questions=questions,
        )

    def _relevance_judger(self) -> ResourceRelevanceJudger:
        judger = getattr(self.engine, "judger", None)
        if not hasattr(judger, "rank_resources"):
            raise RuntimeError("the configured Jev judger does not support resource discovery")
        return judger

    def _bounded_candidates(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> tuple[list[ResourceDescriptor], bool]:
        if len(resources) <= self.max_candidates:
            return resources, False
        goal_terms = _terms(goal)
        ranked = sorted(
            enumerate(resources),
            key=lambda item: (
                -len(goal_terms & _terms(_search_text(item[1]))),
                item[1].title.lower(),
                item[0],
            ),
        )
        return [resource for _, resource in ranked[: self.max_candidates]], True


def proposal_summary(proposal: MonitorCardProposal) -> dict[str, Any]:
    """Return a compact MCP-friendly view while retaining the full typed proposal."""
    return {
        "status": proposal.status.value,
        "workflow_id": proposal.workflow.id,
        "title": proposal.workflow.title,
        "selected_sources": [source.model_dump(mode="json") for source in proposal.workflow.sources],
        "recommended_operations": [
            {"key": operation, "description": SUPPORTED_OPERATIONS[operation]}
            for operation in proposal.plan.operations
            if operation in SUPPORTED_OPERATIONS
        ],
        "comparison_windows": proposal.plan.comparison_windows,
        "recipients": [recipient.model_dump(mode="json") for recipient in proposal.workflow.recipients],
        "questions": proposal.questions,
        "discovery": proposal.discovery.model_dump(mode="json"),
    }

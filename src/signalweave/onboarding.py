from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from .compiler import SUPPORTED_CAPABILITIES
from .models import (
    DeliveryMethod,
    InsightCard,
    InsightCardProposal,
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
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "insight"


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", value.lower()) if len(term) > 2}


def _search_text(resource: ResourceDescriptor) -> str:
    metric_text = " ".join(
        " ".join(
            [
                definition.key,
                definition.label,
                definition.description,
                definition.population,
                definition.grain,
                " ".join(definition.aliases),
                " ".join(definition.dimensions),
            ]
        )
        for definition in resource.contract.metric_definitions
    )
    metadata = " ".join(str(value) for value in resource.metadata.values())
    return " ".join(
        [
            resource.adapter,
            resource.resource,
            resource.kind,
            resource.title,
            resource.description,
            resource.contract.tenant_id,
            resource.contract.domain,
            resource.contract.scope,
            resource.contract.population,
            resource.contract.grain,
            " ".join(resource.contract.metric_names),
            metric_text,
            metadata,
        ]
    )


def insight_goal(
    what_to_watch: str,
    why_watch: str,
    watch_for: list[str] | None = None,
    questions: list[str] | None = None,
) -> str:
    """Create the discovery query without adding another card concept."""
    parts = [what_to_watch.strip(), f"Purpose: {why_watch.strip()}"]
    if watch_for:
        parts.append("Look for: " + "; ".join(watch_for))
    if questions:
        parts.append("Questions: " + "; ".join(questions))
    return "\n".join(parts)


@dataclass
class InsightAuthoringService:
    """Conversation-facing card authoring over installed source adapters.

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
            raise ValueError("insight goal must not be empty")
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
                contract=resource.contract,
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
        warnings: list[str] = []
        if truncated:
            warnings.append(
                "The catalog was bounded before Jev ranking; verify that the selected "
                "source is present in the returned candidate set."
            )
        if any(resource.contract.tenant_id == "default" for resource in candidates):
            warnings.append(
                "One or more candidates lack an explicit tenant identity; production "
                "deployments should configure tenant-aware adapter metadata."
            )
        authorized_tenants = self.registry.authorized_tenants
        authorized_tenant = (
            next(iter(authorized_tenants)) if authorized_tenants and len(authorized_tenants) == 1 else None
        )
        return ResourceDiscovery(
            goal=goal,
            matches=visible,
            candidate_count=len(resources),
            candidate_limit=self.max_candidates,
            truncated=truncated,
            evaluator=judger.name,
            authorized_tenant=authorized_tenant,
            warnings=warnings,
        )

    async def propose(
        self,
        what_to_watch: str,
        why_watch: str,
        *,
        watch_for: list[str] | None = None,
        questions: list[str] | None = None,
        selected_sources: list[dict[str, Any]] | None = None,
        adapter: str | None = None,
        limit: int = 10,
        title: str | None = None,
        comparison_windows: list[str] | None = None,
        delivery_methods: list[DeliveryMethod] | None = None,
        action_confidence_threshold: float = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
    ) -> InsightCardProposal:
        if not what_to_watch.strip():
            raise ValueError("what_to_watch must not be empty")
        if not why_watch.strip():
            raise ValueError("why_watch must not be empty")
        watch_for = list(watch_for or [])
        questions = list(questions or [])
        delivery_methods = list(delivery_methods or [])
        goal = insight_goal(what_to_watch, why_watch, watch_for, questions)
        discovery = await self.discover(goal, adapter=adapter, limit=limit)
        matches = {match.ref: match for match in discovery.matches}
        requested = selected_sources
        if requested is None:
            requested = [{"ref": match.ref} for match in discovery.matches if match.recommended]
        unknown = [item.get("ref") for item in requested if item.get("ref") not in matches]
        if unknown:
            raise ValueError(
                "selected source refs must come from discover_insight_sources: "
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
        card_title = (title or what_to_watch.strip().rstrip("."))[:200] or "Untitled insight"
        card = InsightCard(
            id=f"card-{_slug(card_title)}-{uuid4().hex[:8]}",
            title=card_title,
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for,
            questions=questions,
            sources=source_refs,
            comparison_windows=comparison_windows
            or ["previous_period", "trailing_4_period_average"],
            delivery_methods=delivery_methods,
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
        )
        plan = await self.engine.compile(card)
        setup_questions: list[str] = []
        if not source_refs:
            setup_questions.append("Select at least one source candidate before approval.")
        if not watch_for and not questions:
            setup_questions.append(
                "Add at least one thing to look for or one question the evidence should answer."
            )
        if not delivery_methods:
            setup_questions.append(
                "Add delivery methods if this card should push a result beyond the calling client."
            )
        if plan.comparison_windows:
            setup_questions.append(
                f"Confirm the comparison window proposed by Jev: {plan.comparison_windows[0]}."
            )
        if discovery.truncated:
            setup_questions.append(
                "Confirm the selected sources; discovery used a bounded candidate set "
                f"from {discovery.candidate_count} catalog resources."
            )
        return InsightCardProposal(
            card=card,
            plan=plan,
            discovery=discovery,
            setup_questions=setup_questions,
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


def proposal_summary(proposal: InsightCardProposal) -> dict[str, Any]:
    """Return a compact MCP-friendly view while retaining the full typed proposal."""
    return {
        "status": proposal.status.value,
        "card_id": proposal.card.id,
        "title": proposal.card.title,
        "what_to_watch": proposal.card.what_to_watch,
        "why_watch": proposal.card.why_watch,
        "watch_for": proposal.card.watch_for,
        "questions": proposal.card.questions,
        "selected_sources": [source.model_dump(mode="json") for source in proposal.card.sources],
        "recommended_capabilities": [
            {"key": capability, "description": SUPPORTED_CAPABILITIES[capability]}
            for capability in proposal.plan.capabilities
            if capability in SUPPORTED_CAPABILITIES
        ],
        "comparison_windows": proposal.plan.comparison_windows,
        "delivery_methods": [
            method.model_dump(mode="json") for method in proposal.card.delivery_methods
        ],
        "setup_questions": proposal.setup_questions,
        "discovery": proposal.discovery.model_dump(mode="json"),
    }

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ContextSnapshot, ResourceDescriptor


def resource_ref(resource: ResourceDescriptor) -> str:
    return f"{resource.adapter}|{resource.resource}"


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
            resource.contract.domain,
            resource.contract.scope,
            resource.contract.population,
            resource.contract.grain,
            " ".join(resource.contract.metric_names),
            metric_text,
            metadata,
        ]
    )


def _metadata_refs(resource: ResourceDescriptor) -> set[str]:
    """Read only explicit opaque references published by an adapter/catalog."""
    values: list[object] = [
        *resource.contract.lineage,
        resource.metadata.get("related_resources", []),
        resource.metadata.get("related_refs", []),
    ]
    refs: set[str] = set()
    for value in values:
        if isinstance(value, str):
            refs.add(value)
        elif isinstance(value, list):
            refs.update(item for item in value if isinstance(item, str))
    return refs


@dataclass(frozen=True)
class CandidatePool:
    resources: list[ResourceDescriptor]
    signals: dict[str, list[str]]
    total_count: int
    truncated: bool
    strategy: str = "hybrid-metadata"


def build_candidate_pool(
    goal: str,
    resources: list[ResourceDescriptor],
    *,
    anchors: list[ResourceDescriptor] | None = None,
    context: ContextSnapshot | None = None,
    limit: int = 40,
) -> CandidatePool:
    """Build a bounded recall pool before Jev performs semantic ranking.

    This is deliberately not a relevance decision. It unions lexical, catalog,
    relationship, domain, and context signals so a source with weak wording but
    strong lineage or graph linkage is not discarded before Jev sees it.
    """
    if limit < 1:
        raise ValueError("candidate pool limit must be positive")
    if len(resources) <= limit:
        return CandidatePool(
            resources=list(resources),
            signals={resource_ref(resource): ["catalog"] for resource in resources},
            total_count=len(resources),
            truncated=False,
        )

    goal_terms = _terms(goal)
    anchor_refs = {resource_ref(resource) for resource in (anchors or [])}
    anchor_domains = {
        resource.contract.domain for resource in (anchors or []) if resource.contract.domain
    }
    context_refs = set()
    context_target_refs = set()
    if context is not None:
        context_refs = {
            ref
            for fact in context.facts
            for ref in (fact.subject_ref, fact.object_ref)
            if ref
        }
        anchor_ref_set = {resource_ref(anchor) for anchor in (anchors or [])}
        context_target_refs = {
            fact.object_ref
            for fact in context.facts
            if fact.object_ref
            and fact.subject_ref in anchor_ref_set
            and fact.relation.lower().startswith("requires_")
        }

    scored: list[tuple[tuple[int, int, int, int, int, str], ResourceDescriptor, list[str]]] = []
    for resource in resources:
        ref = resource_ref(resource)
        text_terms = _terms(_search_text(resource))
        overlap = len(goal_terms & text_terms)
        signals: list[str] = []
        if overlap:
            signals.append(f"lexical:{overlap}")
        if goal_terms & _terms(resource.title):
            signals.append("title-match")
        if resource.contract.domain in anchor_domains:
            signals.append("anchor-domain")
        related_refs = _metadata_refs(resource)
        anchor_related = bool(related_refs & anchor_refs) or bool(
            any(resource_ref(anchor) in related_refs for anchor in (anchors or []))
        )
        if anchor_related:
            signals.append("anchor-relationship")
        context_related = bool(related_refs & context_refs)
        if context_related:
            signals.append("context-relationship")
        required_context_related = bool(related_refs & context_target_refs) or ref in context_target_refs
        if required_context_related:
            signals.append("required-context-relationship")
        if ref in context_refs:
            signals.append("context-reference")
        if not signals:
            signals.append("catalog-fallback")
        relationship_score = (
            int("anchor-relationship" in signals)
            + int("context-relationship" in signals)
            + (2 * int("required-context-relationship" in signals))
            + int("context-reference" in signals)
        )
        title_score = int("title-match" in signals)
        domain_score = int("anchor-domain" in signals)
        scored.append(
            (
                (
                    relationship_score,
                    title_score,
                    overlap,
                    domain_score,
                    int("catalog-fallback" not in signals),
                    ref,
                ),
                resource,
                signals,
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:limit]
    return CandidatePool(
        resources=[resource for _, resource, _ in selected],
        signals={resource_ref(resource): signals for _, resource, signals in selected},
        total_count=len(resources),
        truncated=True,
    )

from __future__ import annotations

from typing import Protocol

from .models import ContextSnapshot, InsightCard, ResourceSnapshot


class ContextProvider(Protocol):
    """Read-only boundary for a company-owned graph, catalog, or feedback system."""

    name: str

    async def get_context(
        self, card: InsightCard, resources: list[ResourceSnapshot]
    ) -> ContextSnapshot: ...


def context_facts_as_evidence(context: ContextSnapshot | None):
    """Convert external context claims into inspectable evidence without rewriting them."""
    if context is None:
        return []
    from .models import Evidence

    return [
        Evidence(
            source_key="context",
            subject_id=fact.subject_ref,
            subject_label=fact.subject_ref,
            statement=fact.statement,
            values={
                "relation": fact.relation,
                "object_ref": fact.object_ref,
                "context_provider": context.provider,
                "context_version": context.version,
                "context_trust": context.trust,
            },
            source_url=fact.source_url,
            origin="context",
            provenance=[
                f"provider:{context.provider}",
                f"version:{context.version}",
                f"fact:{fact.fact_id}",
                *fact.provenance,
            ],
        )
        for fact in context.facts
    ]

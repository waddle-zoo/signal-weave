from __future__ import annotations

from types import SimpleNamespace

import pytest

from signalweave.models import (
    CatalogSearchPage,
    ContextFact,
    ContextSnapshot,
    InsightCard,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    RetrievalMode,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService
from signalweave.sources import SourceRegistry


class RelationshipCatalog:
    name = "catalog"

    def __init__(self) -> None:
        tenant = "tenant-a"
        self.resources = [
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:anchor",
                kind="dashboard",
                title="Growth overview",
                description="Approved growth dashboard anchor.",
                contract=ResourceContract(tenant_id=tenant, domain="growth", roles=["primary"]),
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="query:fulfillment-latency",
                kind="query",
                title="Fulfillment latency query",
                description="Cross-domain diagnostic query with no shared title vocabulary.",
                contract=ResourceContract(
                    tenant_id=tenant,
                    domain="fulfillment",
                    roles=["diagnostic"],
                ),
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:other-tenant",
                kind="dashboard",
                title="Other tenant growth overview",
                description="Should never cross the authorization boundary.",
                contract=ResourceContract(tenant_id="tenant-b", domain="growth"),
            ),
        ]
        self.search_calls = 0
        self.expand_calls: list[list[str]] = []
        self.list_calls = 0

    async def list_resources(self):
        self.list_calls += 1
        raise AssertionError("relationship expansion must not full-scan the catalog")

    async def search_resources(self, query, *, limit, cursor=None):
        del query, cursor
        self.search_calls += 1
        return CatalogSearchPage(
            resources=[self.resources[0], self.resources[2]][:limit],
            total_count=2,
            has_more=False,
            provider=self.name,
            strategy="native-index",
        )

    async def expand_related_resources(self, related_refs, *, limit, authorized_tenants=None):
        del authorized_tenants
        self.expand_calls.append(list(related_refs))
        if "catalog|dashboard:anchor" not in related_refs:
            return CatalogSearchPage(
                total_count=0,
                provider=self.name,
                strategy="native-related-index",
            )
        return CatalogSearchPage(
            resources=[self.resources[1]][:limit],
            total_count=1,
            has_more=False,
            provider=self.name,
            strategy="native-related-index",
        )

    async def authorize(self, source, *, authorized_tenants=None):
        allowed = set(authorized_tenants or [])
        for resource in self.resources:
            if resource.resource == source.resource and (
                not allowed or resource.contract.tenant_id in allowed
            ):
                return resource
        return None

    async def inspect(self, source):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=source.adapter,
            resource=source.resource,
            title=source.label,
        )


class RelationshipJev:
    name = "jev-related-expansion-test"

    async def rank_resources(self, goal, resources):
        del goal
        return {
            f"{resource.adapter}|{resource.resource}": (
                0.95 if resource.resource == "query:fulfillment-latency" else 0.10
            )
            for resource in resources
        }


@pytest.mark.asyncio
async def test_relationship_expansion_finds_nonlexical_neighbor_without_full_scan():
    adapter = RelationshipCatalog()
    registry = SourceRegistry([adapter], authorized_tenants=["tenant-a"])
    service = InsightAuthoringService(
        registry=registry,
        engine=SimpleNamespace(judger=RelationshipJev()),
        max_candidates=10,
        related_source_limit=3,
        principal=SimpleNamespace(tenant_id="tenant-a"),
    )
    card = InsightCard(
        id="relationship-card",
        title="Growth with fulfillment context",
        what_to_watch="Growth conversion movement",
        why_watch="Decide whether the movement needs action",
        questions=["What related evidence explains the movement?"],
        sources=[
            SourceRef(
                key="anchor",
                adapter="catalog",
                resource="dashboard:anchor",
                label="Growth overview",
            )
        ],
        retrieval_mode=RetrievalMode.EXPAND,
    )

    bundle = await service.resolve_bundle(card)

    assert adapter.search_calls == 1
    assert adapter.list_calls == 0
    assert adapter.expand_calls == [["catalog|dashboard:anchor"]]
    assert [match.resource for match in bundle.related_matches] == [
        "query:fulfillment-latency"
    ]
    assert [source.resource for source in bundle.selected_sources] == [
        "dashboard:anchor",
        "query:fulfillment-latency",
    ]
    assert "multi-adapter-related-expansion" in bundle.candidate_strategy
    # The native search result is not tenant-aware, so the registry redacts
    # its provider-wide count while retaining the related expansion count.
    assert bundle.candidate_count == 2
    assert any("catalog count was redacted" in warning for warning in bundle.warnings)
    assert all("other-tenant" not in source.resource for source in bundle.selected_sources)


@pytest.mark.asyncio
async def test_unverified_context_cannot_widen_relationship_neighborhood():
    adapter = RelationshipCatalog()
    registry = SourceRegistry([adapter], authorized_tenants=["tenant-a"])
    service = InsightAuthoringService(
        registry=registry,
        engine=SimpleNamespace(judger=RelationshipJev()),
        max_candidates=10,
        related_source_limit=3,
        principal=SimpleNamespace(tenant_id="tenant-a"),
    )
    card = InsightCard(
        id="unverified-context-card",
        title="Growth with unverified context",
        what_to_watch="Growth conversion movement",
        why_watch="Decide whether the movement needs action",
        sources=[
            SourceRef(
                key="anchor",
                adapter="catalog",
                resource="dashboard:anchor",
                label="Growth overview",
            )
        ],
        retrieval_mode=RetrievalMode.EXPAND,
    )
    context = ContextSnapshot(
        provider="caller-supplied",
        version="unverified-1",
        trust="unverified",
        facts=[
            ContextFact(
                fact_id="requires-fulfillment",
                subject_ref="catalog|dashboard:anchor",
                relation="requires_diagnostic_context",
                object_ref="catalog|query:fulfillment-latency",
                statement="The anchor requires a fulfillment diagnostic.",
            )
        ],
    )

    bundle = await service.resolve_bundle(card, context=context)

    assert adapter.expand_calls == [["catalog|dashboard:anchor"]]
    assert bundle.context_version == "unverified-1"
    assert any("unverified" in warning for warning in bundle.warnings)


@pytest.mark.asyncio
async def test_trusted_requires_relationship_is_expanded_and_covered():
    adapter = RelationshipCatalog()
    registry = SourceRegistry([adapter], authorized_tenants=["tenant-a"])
    service = InsightAuthoringService(
        registry=registry,
        engine=SimpleNamespace(judger=RelationshipJev()),
        max_candidates=10,
        related_source_limit=3,
        principal=SimpleNamespace(tenant_id="tenant-a"),
    )
    card = InsightCard(
        id="trusted-context-card",
        title="Growth with trusted context",
        what_to_watch="Growth conversion movement",
        why_watch="Decide whether the movement needs action",
        sources=[
            SourceRef(
                key="anchor",
                adapter="catalog",
                resource="dashboard:anchor",
                label="Growth overview",
            )
        ],
        retrieval_mode=RetrievalMode.EXPAND,
    )
    context = ContextSnapshot(
        provider="company-graph",
        version="graph-v1",
        facts=[
            ContextFact(
                fact_id="requires-fulfillment",
                subject_ref="catalog|dashboard:anchor",
                relation="requires_diagnostic_context",
                object_ref="catalog|query:fulfillment-latency",
                statement="The anchor requires a fulfillment diagnostic.",
            )
        ],
    )

    bundle = await service.resolve_bundle(card, context=context)

    assert adapter.expand_calls == [
        ["catalog|dashboard:anchor", "catalog|query:fulfillment-latency"]
    ]
    assert [match.resource for match in bundle.related_matches] == [
        "query:fulfillment-latency"
    ]
    assert not any("missing one or more explicit" in warning for warning in bundle.warnings)

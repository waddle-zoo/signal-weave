from types import SimpleNamespace

import pytest

from signalweave.engine import InsightEngine
from signalweave.models import (
    CatalogSearchPage,
    ContextFact,
    ContextSnapshot,
    InsightCard,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    RetrievalMode,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService
from signalweave.retrieval_quality import (
    BundleRetrievalCase,
    BundleRetrievalEvaluator,
    RetrievalQualityCase,
    RetrievalQualityEvaluator,
    RetrievalQualityThresholds,
)
from signalweave.sources import SourceRegistry


class CatalogAdapter:
    name = "catalog"

    async def list_resources(self):
        return self.resources

    async def search_resources(self, query, *, limit, cursor=None):
        del query, cursor
        return CatalogSearchPage(
            resources=self.resources[:limit],
            total_count=len(self.resources),
            provider="catalog-index",
            strategy="server-search",
        )

    @property
    def resources(self):
        return [
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:revenue",
                kind="dashboard",
                title="Revenue movement",
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="query:quality",
                kind="query",
                title="Revenue data quality",
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:unrelated",
                kind="dashboard",
                title="Warehouse staffing",
            ),
        ]


class Ranker:
    name = "jev-retrieval-fixture"

    async def rank_resources(self, goal, resources):
        if "nothing" in goal:
            return {f"{resource.adapter}|{resource.resource}": 0.1 for resource in resources}
        return {
            f"{resource.adapter}|{resource.resource}": (
                0.95
                if resource.resource in {"dashboard:revenue", "query:quality"}
                else 0.1
            )
            for resource in resources
        }


@pytest.mark.asyncio
async def test_retrieval_quality_separates_candidate_coverage_from_jev_selection():
    adapter = CatalogAdapter()
    service = InsightAuthoringService(
        SourceRegistry([adapter]),
        InsightEngine(judger=Ranker()),
        max_candidates=3,
    )
    cases = [
        RetrievalQualityCase(
            id="revenue",
            goal="revenue movement and quality",
            expected_resource_refs=[
                "catalog|dashboard:revenue",
                "catalog|query:quality",
            ],
        ),
        RetrievalQualityCase(
            id="revenue-related-source-group",
            goal="revenue movement and quality",
            expected_resource_refs=["catalog|dashboard:revenue"],
            acceptable_resource_refs=[
                "catalog|dashboard:revenue",
                "catalog|query:quality",
            ],
            required_resource_groups=[["catalog|query:quality"]],
        ),
        RetrievalQualityCase(id="no-match", goal="nothing relevant"),
    ]

    report = await RetrievalQualityEvaluator(service).evaluate(
        cases,
        thresholds=RetrievalQualityThresholds(
            min_candidate_recall=1,
            min_recommended_precision=1,
            min_recommended_recall=1,
            min_cases=3,
        ),
    )

    assert report.status == "approved"
    assert report.candidate_recall == 1
    assert report.recommended_precision == 1
    assert report.recommended_recall == 1
    assert report.required_group_recall == 1
    assert report.no_match_accuracy == 1
    assert report.cases[0].candidate_refs == [
        "catalog|dashboard:revenue",
        "catalog|query:quality",
        "catalog|dashboard:unrelated",
    ]


@pytest.mark.asyncio
async def test_retrieval_quality_exposes_jev_threshold_miss_as_shadow():
    class ConservativeRanker(Ranker):
        async def rank_resources(self, goal, resources):
            scores = await super().rank_resources(goal, resources)
            scores["catalog|query:quality"] = 0.59
            return scores

    adapter = CatalogAdapter()
    service = InsightAuthoringService(
        SourceRegistry([adapter]),
        SimpleNamespace(judger=ConservativeRanker()),
        max_candidates=3,
    )
    report = await RetrievalQualityEvaluator(service).evaluate(
        [
            RetrievalQualityCase(
                id="revenue",
                goal="revenue movement and quality",
                expected_resource_refs=[
                    "catalog|dashboard:revenue",
                    "catalog|query:quality",
                ],
            )
        ],
        thresholds=RetrievalQualityThresholds(
            min_candidate_recall=1,
            min_recommended_precision=1,
            min_recommended_recall=1,
        ),
    )

    assert report.status == "shadow"
    assert report.candidate_recall == 1
    assert report.recommended_recall == 0.5
    assert report.cases[0].recommended_refs == ["catalog|dashboard:revenue"]


class RelationshipBundleAdapter:
    name = "catalog"

    def __init__(self):
        tenant = "tenant-a"
        self.anchor = ResourceDescriptor(
            adapter=self.name,
            resource="dashboard:anchor",
            kind="dashboard",
            title="Growth overview",
            contract=ResourceContract(tenant_id=tenant, domain="growth", roles=["primary"]),
        )
        self.related = ResourceDescriptor(
            adapter=self.name,
            resource="query:fulfillment",
            kind="query",
            title="Fulfillment context",
            metadata={"related_refs": ["graph|fulfillment"]},
            contract=ResourceContract(tenant_id=tenant, domain="fulfillment", roles=["diagnostic"]),
        )

    async def list_resources(self):
        raise AssertionError("bundle evaluation must not full-scan the catalog")

    async def search_resources(self, query, *, limit, cursor=None, authorized_tenants=None):
        del query, cursor, authorized_tenants
        return CatalogSearchPage(
            resources=[self.anchor][:limit],
            total_count=1,
            provider="catalog-index",
            strategy="native-index",
        )

    async def expand_related_resources(
        self, related_refs, *, limit, authorized_tenants=None
    ):
        del authorized_tenants
        if "graph|fulfillment" not in related_refs:
            return CatalogSearchPage(
                total_count=0,
                provider="catalog-index",
                strategy="native-related-index",
            )
        return CatalogSearchPage(
            resources=[self.related][:limit],
            total_count=1,
            provider="catalog-index",
            strategy="native-related-index",
        )

    async def authorize(self, source, *, authorized_tenants=None):
        del source, authorized_tenants
        return self.anchor

    async def inspect(self, source):
        del source
        raise AssertionError("bundle evaluation should not inspect sources")


class RelationshipBundleRanker:
    name = "jev-bundle-fixture"

    async def rank_resources(self, goal, resources):
        del goal
        return {
            f"{resource.adapter}|{resource.resource}": (
                0.95 if resource.resource == "query:fulfillment" else 0.10
            )
            for resource in resources
        }


@pytest.mark.asyncio
async def test_bundle_quality_evaluator_certifies_graph_assisted_expansion():
    adapter = RelationshipBundleAdapter()
    service = InsightAuthoringService(
        SourceRegistry([adapter], authorized_tenants=["tenant-a"]),
        SimpleNamespace(judger=RelationshipBundleRanker()),
        max_candidates=10,
        related_source_limit=2,
    )
    card = InsightCard(
        id="bundle-card",
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
    context = ContextSnapshot(
        provider="company-graph",
        version="graph-v1",
        facts=[
            ContextFact(
                fact_id="requires-fulfillment",
                subject_ref="catalog|dashboard:anchor",
                relation="requires_related_context",
                object_ref="graph|fulfillment",
                statement="Growth movement requires fulfillment context.",
            )
        ],
    )

    report = await BundleRetrievalEvaluator(service).evaluate(
        [
            BundleRetrievalCase(
                id="growth-bundle",
                card=card,
                context=context,
                expected_related_groups=[["catalog|query:fulfillment"]],
                principal=PrincipalContext(tenant_id="tenant-a", principal_id="owner"),
            )
        ],
        thresholds=RetrievalQualityThresholds(
            min_candidate_recall=1,
            min_recommended_precision=1,
            min_required_group_recall=1,
            min_cases=1,
            max_unauthorized_refs=0,
        ),
    )

    assert report.status == "approved"
    assert report.candidate_group_recall == 1
    assert report.selected_group_recall == 1
    assert report.selected_precision == 1
    assert report.cases[0].selected_related_refs == ["catalog|query:fulfillment"]


@pytest.mark.asyncio
async def test_graph_obligation_retains_top_jev_projection_below_optional_threshold():
    adapter = RelationshipBundleAdapter()

    class LowConfidenceRanker(RelationshipBundleRanker):
        async def rank_resources(self, goal, resources):
            scores = await super().rank_resources(goal, resources)
            scores["catalog|query:fulfillment"] = 0.42
            return scores

    service = InsightAuthoringService(
        SourceRegistry([adapter], authorized_tenants=["tenant-a"]),
        SimpleNamespace(judger=LowConfidenceRanker()),
        max_candidates=10,
        related_source_limit=2,
    )
    card = InsightCard(
        id="low-confidence-bundle-card",
        title="Growth with fulfillment context",
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
                relation="requires_related_context",
                object_ref="graph|fulfillment",
                statement="Growth movement requires fulfillment context.",
            )
        ],
    )

    bundle = await service.resolve_bundle(
        card,
        context,
        principal=PrincipalContext(tenant_id="tenant-a", principal_id="owner"),
    )

    assert [source.resource for source in bundle.related_matches] == ["query:fulfillment"]
    assert any("below the optional relevance threshold" in warning for warning in bundle.warnings)

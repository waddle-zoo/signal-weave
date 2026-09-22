from types import SimpleNamespace

import pytest

from signalweave.engine import InsightEngine
from signalweave.models import CatalogSearchPage, ResourceDescriptor
from signalweave.onboarding import InsightAuthoringService
from signalweave.retrieval_quality import (
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
        RetrievalQualityCase(id="no-match", goal="nothing relevant"),
    ]

    report = await RetrievalQualityEvaluator(service).evaluate(
        cases,
        thresholds=RetrievalQualityThresholds(
            min_candidate_recall=1,
            min_recommended_precision=1,
            min_recommended_recall=1,
            min_cases=2,
        ),
    )

    assert report.status == "approved"
    assert report.candidate_recall == 1
    assert report.recommended_precision == 1
    assert report.recommended_recall == 1
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

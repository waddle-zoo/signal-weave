from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signalweave.engine import InsightEngine
from signalweave.models import (
    CatalogSearchPage,
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    EvidenceFinding,
    InsightCard,
    InsightResult,
    InvestigationMode,
    Observation,
    Outcome,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.retrieval import build_candidate_pool, resource_ref
from signalweave.sources import SourceRegistry


def descriptor(
    resource: str,
    title: str,
    *,
    domain: str = "operations",
    metadata: dict[str, object] | None = None,
    lineage: list[str] | None = None,
) -> ResourceDescriptor:
    return ResourceDescriptor(
        adapter="superset",
        resource=resource,
        kind="dashboard",
        title=title,
        metadata=metadata or {},
        contract=ResourceContract(domain=domain, lineage=lineage or []),
    )


def observation(source_key: str, metric: str, current: float, baseline: float) -> Observation:
    return Observation(
        source_key=source_key,
        subject_id=metric,
        subject_label=metric.replace("_", " ").title(),
        metric=metric,
        current=current,
        baseline=baseline,
        change_pct=(current - baseline) / abs(baseline) * 100,
    )


def snapshot(source: SourceRef, obs: Observation) -> ResourceSnapshot:
    return ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[obs],
        captured_at=datetime.now(timezone.utc),
    )


def test_candidate_pool_preserves_relationship_signal_when_words_do_not_match():
    anchor = descriptor("dashboard:exec", "Executive revenue pulse")
    related = descriptor(
        "dashboard:warehouse",
        "Warehouse operations",
        domain="operations",
        metadata={"related_resources": ["superset|dashboard:exec"]},
    )
    decoys = [
        descriptor(f"dashboard:decoy-{index}", f"Generic dashboard {index}")
        for index in range(100)
    ]

    pool = build_candidate_pool(
        "why did revenue change and what explains it?",
        [anchor, *decoys, related],
        anchors=[anchor],
        limit=5,
    )

    assert resource_ref(related) in {resource_ref(item) for item in pool.resources}
    assert "anchor-relationship" in pool.signals[resource_ref(related)]
    assert pool.truncated is True


def test_candidate_pool_preserves_context_referenced_source():
    anchor = descriptor("dashboard:exec", "Executive pulse")
    referenced = descriptor("dashboard:billing", "Billing operations")
    decoys = [descriptor(f"dashboard:decoy-{index}", f"Generic {index}") for index in range(20)]
    context = ContextSnapshot(
        provider="company-graph",
        version="graph-42",
        facts=[
            ContextFact(
                fact_id="edge-1",
                subject_ref="superset|dashboard:exec",
                relation="diagnosed_by",
                object_ref="superset|dashboard:billing",
                statement="The executive pulse is diagnosed by billing operations.",
            )
        ],
    )

    pool = build_candidate_pool(
        "investigate the executive pulse",
        [anchor, *decoys, referenced],
        anchors=[anchor],
        context=context,
        limit=5,
    )

    assert resource_ref(referenced) in {resource_ref(item) for item in pool.resources}
    assert "context-reference" in pool.signals[resource_ref(referenced)]


class InvestigationAdapter:
    name = "superset"

    def __init__(self, anchor: SourceRef, diagnostic: SourceRef):
        self.anchor = anchor
        self.diagnostic = diagnostic
        self.inspected: list[str] = []

    async def list_resources(self):
        return [
            descriptor(self.anchor.resource, self.anchor.label),
            descriptor(self.diagnostic.resource, self.diagnostic.label),
        ]

    async def inspect(self, source):
        self.inspected.append(source.resource)
        if source.resource == self.anchor.resource:
            return snapshot(source, observation(source.key, "revenue", 80, 100))
        return snapshot(source, observation(source.key, "billing_failures", 20, 5))


class ContextDouble:
    name = "company-graph"

    async def get_context(self, card, resources):
        del card, resources
        return ContextSnapshot(
            provider=self.name,
            version="graph-42",
            facts=[
                ContextFact(
                    fact_id="relationship-1",
                    subject_ref="superset|dashboard:exec",
                    relation="diagnosed_by",
                    object_ref="superset|dashboard:billing",
                    statement="Billing failures are a known diagnostic signal for revenue movement.",
                    provenance=["owner:revenue-ops"],
                )
            ],
        )


class InvestigationJudger:
    name = "jev-test-investigation"

    async def compile_plan(self, state, card):
        del state
        return {"capabilities": ["percent_change"], "baseline": card.comparison_windows[0]}

    async def select_investigation_sources(
        self, state, card, plan, candidates, max_sources
    ):
        del state, card, plan, max_sources
        return {
            "probability": 0.96,
            "selections": [
                # The engine must reject model output outside the authorized candidate set.
                {"ref": "superset|dashboard:not-authorized", "score": 1.0, "confidence": 1.0},
                {
                    "ref": resource_ref(candidates[0]),
                    "score": 0.95,
                    "confidence": 0.92,
                },
            ],
        }

    async def judge(self, state, card, plan, observations):
        del plan
        assert state["context"]["version"] == "graph-42"
        assert any(item["origin"] == "context" for item in state["evidence"])
        assert any(item.source_key.startswith("investigate-") for item in observations)
        return InsightResult(
            card_id=card.id,
            outcome=Outcome.NOTIFY,
            delivery_methods=[method for method in card.delivery_methods if method.outcome == Outcome.NOTIFY],
            summary="The diagnostic source corroborated the movement.",
            rationale="The billing failure observation explains the revenue movement.",
            confidence=0.94,
            probabilities={"notify": 0.94, "investigate": 0.06},
            evidence=state["evidence"],
            observations=observations,
            evidence_findings=[
                EvidenceFinding(
                    key="evidence_0",
                    source_key="anchor",
                    subject_id="revenue",
                    subject_label="Revenue",
                    metric="revenue",
                    role="driver",
                    probability=0.9,
                )
            ],
            source_keys=[item.source_key for item in observations],
            evaluator=self.name,
        )


class BrokenInvestigationJudger(InvestigationJudger):
    async def select_investigation_sources(
        self, state, card, plan, candidates, max_sources
    ):
        del state, card, plan, candidates, max_sources
        raise TimeoutError("synthetic Jev timeout")

    async def judge(self, state, card, plan, observations):
        del plan, observations
        assert state["context"]["version"] == "graph-42"
        return InsightResult(
            card_id=card.id,
            outcome=Outcome.NOTIFY,
            delivery_methods=[
                method for method in card.delivery_methods if method.outcome == Outcome.NOTIFY
            ],
            summary="The initial source moved.",
            rationale="The follow-up stage was unavailable.",
            confidence=0.95,
            probabilities={"notify": 0.95, "investigate": 0.05},
            evidence=state["evidence"],
            observations=[],
            source_keys=[],
            evaluator=self.name,
        )


@pytest.mark.asyncio
async def test_bounded_investigation_fetches_authorized_context_and_preserves_trace():
    anchor = SourceRef(
        key="anchor", adapter="superset", resource="dashboard:exec", label="Executive pulse"
    )
    diagnostic = SourceRef(
        key="diagnostic", adapter="superset", resource="dashboard:billing", label="Billing operations"
    )
    adapter = InvestigationAdapter(anchor, diagnostic)
    registry = SourceRegistry([adapter], enforce_catalog=True)
    card = InsightCard(
        id="card-investigation",
        title="Executive pulse",
        what_to_watch="Revenue movement and the operational signal that explains it.",
        why_watch="Tell Revenue Operations when a material movement deserves attention.",
        sources=[anchor],
        investigation_mode=InvestigationMode.BOUNDED,
        max_investigation_sources=1,
        delivery_methods=[
            DeliveryMethod(
                key="revenue-ops",
                outcome=Outcome.NOTIFY,
                label="Revenue Operations",
                destination="slack://revenue-ops",
            )
        ],
    )

    run = await InsightEngine(
        InvestigationJudger(), registry=registry, context_provider=ContextDouble()
    ).evaluate(card)

    assert run.result.outcome == Outcome.NOTIFY
    assert run.result.context is not None
    assert run.result.context.version == "graph-42"
    assert run.result.investigation is not None
    assert run.result.investigation.attempted is True
    assert len(run.result.investigation.selected) == 1
    assert run.result.investigation.selected[0].source.resource == diagnostic.resource
    assert any("unauthorized" in warning for warning in run.result.investigation.warnings)
    assert adapter.inspected == [anchor.resource, diagnostic.resource]
    assert any(item.origin == "context" for item in run.result.evidence)


@pytest.mark.asyncio
async def test_investigation_provider_failure_cannot_auto_notify():
    anchor = SourceRef(
        key="anchor", adapter="superset", resource="dashboard:exec", label="Executive pulse"
    )
    diagnostic = SourceRef(
        key="diagnostic", adapter="superset", resource="dashboard:billing", label="Billing operations"
    )
    registry = SourceRegistry([InvestigationAdapter(anchor, diagnostic)], enforce_catalog=True)
    card = InsightCard(
        id="card-investigation-timeout",
        title="Executive pulse",
        what_to_watch="Revenue movement",
        why_watch="Support an operating decision.",
        sources=[anchor],
        investigation_mode=InvestigationMode.BOUNDED,
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Operations",
                destination="test://ops",
            )
        ],
    )

    run = await InsightEngine(
        BrokenInvestigationJudger(), registry=registry, context_provider=ContextDouble()
    ).evaluate(card)

    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.investigation is not None
    assert run.result.investigation.failed is True
    assert "timeout" in run.result.investigation.warnings[0]


@pytest.mark.asyncio
async def test_context_provider_failure_is_unverified_and_visible():
    class BrokenContext:
        name = "company-graph"

        async def get_context(self, card, resources):
            del card, resources
            raise TimeoutError("graph unavailable")

    class FailureJudger:
        name = "jev-context-failure"

        async def compile_plan(self, state, card):
            del state
            return {"capabilities": ["percent_change"], "baseline": card.comparison_windows[0]}

        async def judge(self, state, card, plan, observations):
            del plan
            return InsightResult(
                card_id=card.id,
                outcome=Outcome.INVESTIGATE,
                summary="Context was unavailable.",
                rationale="The graph provider failed and the result should be reviewed.",
                confidence=0.5,
                probabilities={"investigate": 0.5},
                evidence=state["evidence"],
                observations=observations,
                source_keys=[source.source_key for source in observations],
                evaluator=self.name,
            )

    source = SourceRef(
        key="anchor", adapter="superset", resource="dashboard:exec", label="Executive pulse"
    )
    card = InsightCard(
        id="card-context-failure",
        title="Executive pulse",
        what_to_watch="Revenue movement",
        why_watch="Support an operating decision.",
        sources=[source],
    )

    run = await InsightEngine(
        FailureJudger(), context_provider=BrokenContext()
    ).evaluate(card, [snapshot(source, observation(source.key, "revenue", 80, 100))])

    assert run.result.context is not None
    assert run.result.context.trust == "unverified"
    assert "graph unavailable" in run.result.context.warnings[0]


@pytest.mark.asyncio
async def test_bounded_investigation_abstains_when_selector_is_not_available():
    class NoInvestigationJudger:
        name = "no-investigation-judger"

        async def compile_plan(self, state, card):
            del state
            return {"capabilities": ["percent_change"], "baseline": card.comparison_windows[0]}

        async def judge(self, state, card, plan, observations):
            del plan
            return InsightResult(
                card_id=card.id,
                outcome=Outcome.NOTIFY,
                summary="test",
                rationale="test",
                confidence=0.9,
                probabilities={"notify": 0.9},
                evidence=state["evidence"],
                observations=observations,
                source_keys=[item.source_key for item in observations],
                evaluator=self.name,
            )

    source = SourceRef(
        key="anchor", adapter="superset", resource="dashboard:exec", label="Executive pulse"
    )
    card = InsightCard(
        id="card-no-investigation-selector",
        title="Executive pulse",
        what_to_watch="Revenue movement",
        why_watch="Support an operating decision.",
        sources=[source],
        investigation_mode=InvestigationMode.BOUNDED,
    )
    resource = snapshot(source, observation(source.key, "revenue", 80, 100))

    run = await InsightEngine(NoInvestigationJudger()).evaluate(card, [resource])

    assert run.result.investigation is not None
    assert run.result.investigation.attempted is False
    assert run.result.investigation.failed is True
    assert run.result.outcome == Outcome.INVESTIGATE
    assert "not configured" in run.result.investigation.warnings[0]


@pytest.mark.asyncio
async def test_investigation_keeps_100k_catalog_bounded_before_jev():
    anchor = SourceRef(
        key="anchor", adapter="superset", resource="dashboard:exec", label="Executive pulse"
    )
    diagnostic = SourceRef(
        key="diagnostic", adapter="superset", resource="dashboard:billing", label="Billing operations"
    )

    class SearchOnlyAdapter:
        name = "superset"

        def __init__(self):
            self.search_calls = 0

        async def list_resources(self):
            return []

        async def search_resources(self, query, *, limit, cursor=None):
            del query, cursor
            self.search_calls += 1
            assert limit == 40
            return CatalogSearchPage(
                resources=[descriptor(diagnostic.resource, diagnostic.label)],
                total_count=100_000,
                has_more=True,
                next_cursor="next-page",
                provider="superset-index",
                strategy="server-search",
            )

        async def inspect(self, source):
            return snapshot(source, observation(source.key, "billing_failures", 20, 5))

    adapter = SearchOnlyAdapter()
    registry = SourceRegistry([adapter], enforce_catalog=False)
    card = InsightCard(
        id="card-100k-catalog",
        title="Executive pulse",
        what_to_watch="Revenue movement",
        why_watch="Support an operating decision.",
        sources=[anchor],
        investigation_mode=InvestigationMode.BOUNDED,
        max_investigation_sources=1,
    )

    run = await InsightEngine(
        InvestigationJudger(), registry=registry, context_provider=ContextDouble()
    ).evaluate(card, resources=[snapshot(anchor, observation(anchor.key, "revenue", 80, 100))])

    assert adapter.search_calls == 1
    assert run.result.investigation is not None
    assert run.result.investigation.catalog_count == 100_000
    assert run.result.investigation.catalog_has_more is True
    assert run.result.investigation.catalog_strategy == "server-search"
    assert run.result.investigation.candidate_count == 1

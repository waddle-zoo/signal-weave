"""Offline checks for evaluator-to-engine principal propagation."""

import pytest
from test_evaluation import card, snapshot

from signalweave.engine import InsightEngine
from signalweave.evaluation import CardEvaluationCase, CardWorkflowEvaluator
from signalweave.models import (
    DeliveryMethod,
    InsightCard,
    InsightResult,
    InvestigationMode,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.sources import SourceRegistry


def evaluation_case() -> CardEvaluationCase:
    return CardEvaluationCase(
        id="principal-propagation",
        card=card("principal-propagation-good"),
        resources=[snapshot()],
        expected_outcome="notify",
    )


@pytest.mark.asyncio
async def test_evaluator_passes_authenticated_principal_to_engine():
    class RecordingEngine:
        def __init__(self):
            self.principal = None

        async def evaluate(self, card, *, resources, context_override, principal):
            del card, resources, context_override
            self.principal = principal
            raise RuntimeError("stop after propagation check")

    principal = PrincipalContext(principal_id="owner", tenant_id="tenant-a")
    engine = RecordingEngine()

    report = await CardWorkflowEvaluator(engine, principal=principal).evaluate(
        [evaluation_case()]
    )

    assert engine.principal == principal
    assert report.status == "blocked"
    assert report.cases[0].error == "RuntimeError: stop after propagation check"


@pytest.mark.asyncio
async def test_evaluator_omits_principal_for_legacy_offline_engine_double():
    class LegacyEngine:
        async def evaluate(self, card, *, resources, context_override):
            del card, resources, context_override
            raise RuntimeError("legacy double reached")

    report = await CardWorkflowEvaluator(LegacyEngine()).evaluate([evaluation_case()])

    assert report.status == "blocked"
    assert report.cases[0].error == "RuntimeError: legacy double reached"


@pytest.mark.asyncio
async def test_real_engine_keeps_bounded_followup_catalog_tenant_scoped():
    anchor = ResourceDescriptor(
        adapter="tenant-mcp", resource="anchor", kind="dashboard", title="Anchor",
        contract=ResourceContract(tenant_id="tenant-a"),
    )
    foreign = anchor.model_copy(update={
        "resource": "foreign", "title": "Foreign",
        "contract": ResourceContract(tenant_id="tenant-b"),
    })
    diagnostic = anchor.model_copy(update={
        "resource": "diagnostic", "title": "Diagnostic",
    })

    class TenantCatalog:
        name = "tenant-mcp"

        def __init__(self):
            self.list_calls = 0
            self.authorize_scopes = []

        async def list_resources(self):
            self.list_calls += 1
            # Deliberately return a foreign descriptor too; SourceRegistry must
            # enforce the tenant boundary before the engine sees candidates.
            return [diagnostic, foreign]

        async def authorize(self, source, *, authorized_tenants=None):
            self.authorize_scopes.append(authorized_tenants)
            descriptor = {
                anchor.resource: anchor,
                diagnostic.resource: diagnostic,
                foreign.resource: foreign,
            }[source.resource]
            if authorized_tenants and descriptor.contract.tenant_id not in authorized_tenants:
                return None
            return descriptor

        async def inspect(self, source):
            return ResourceSnapshot(
                source_key=source.key, adapter=source.adapter, resource=source.resource,
                title=source.label,
            )

    class InvestigationJev:
        name = "offline-investigation"

        def __init__(self):
            self.candidate_refs = []

        async def compile_plan(self, state, card):
            del state
            return {"capabilities": [], "baseline": card.comparison_windows[0]}

        async def select_investigation_sources(self, state, card, plan, candidates, max_sources):
            del state, card, plan, max_sources
            self.candidate_refs = [f"{item.adapter}|{item.resource}" for item in candidates]
            return {
                "probability": 0.99,
                "selections": [{"ref": self.candidate_refs[0], "score": 0.99, "confidence": 0.99}],
            }

        async def judge(self, state, card, plan, observations):
            del plan
            return InsightResult(
                card_id=card.id, outcome="ignore", delivery_methods=[], summary="offline",
                rationale="offline", confidence=1.0, probabilities={"ignore": 1.0},
                evidence=state["evidence"], observations=observations, evaluator=self.name,
            )

    adapter = TenantCatalog()
    judger = InvestigationJev()
    registry = SourceRegistry([adapter])
    card = InsightCard(
        id="tenant-scoped-investigation", title="Tenant scoped", what_to_watch="Anchor",
        why_watch="Check tenant scope", decision_guidance="Ignore if unchanged.",
        sources=[SourceRef(key="anchor", adapter="tenant-mcp", resource="anchor", label="Anchor")],
        investigation_mode=InvestigationMode.BOUNDED,
        delivery_methods=[DeliveryMethod(key="unused", outcome="notify", label="Unused", destination="sink")],
    )
    anchor_snapshot = ResourceSnapshot(
        source_key="anchor", adapter="tenant-mcp", resource="anchor", title="Anchor",
        observations=[],
    )
    principal = PrincipalContext(principal_id="owner", tenant_id="tenant-a")
    engine = InsightEngine(judger, registry=registry)
    report = await CardWorkflowEvaluator(engine, principal=principal).evaluate([
        CardEvaluationCase(
            id="tenant-scope", card=card, resources=[anchor_snapshot], expected_outcome="ignore",
        )
    ])

    assert report.cases[0].error is None
    assert adapter.list_calls == 1
    assert judger.candidate_refs == ["tenant-mcp|diagnostic"]
    assert adapter.authorize_scopes
    assert all(scope == frozenset({"tenant-a"}) for scope in adapter.authorize_scopes)
    assert report.cases[0].actual_retrieval_refs == [
        "tenant-mcp|anchor", "tenant-mcp|diagnostic",
    ]

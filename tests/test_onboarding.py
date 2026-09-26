import asyncio
from types import SimpleNamespace

import httpx
import pytest

from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import (
    CertificationRecord,
    ContextFact,
    ContextSnapshot,
    Evidence,
    InsightCard,
    InsightCardStatus,
    InsightResult,
    Observation,
    Outcome,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
)
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import (
    InMemoryCertificationReportStore,
    JsonInsightCardStore,
    SQLiteDecisionFeedbackStore,
    SQLiteDecisionReceiptStore,
    SQLiteInsightCardStore,
)


class SupersetCatalogDouble:
    name = "superset"

    def __init__(self):
        self.resources = [
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:7",
                kind="dashboard",
                title="Growth overview",
                description="Revenue, conversion, and checkout health.",
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:8",
                kind="dashboard",
                title="Finance close",
                description="Month-end reporting and forecast variance.",
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:9",
                kind="dashboard",
                title="People operations",
                description="Hiring and retention metrics.",
            ),
        ]

    async def list_resources(self):
        return self.resources

    async def inspect(self, source):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=source.adapter,
            resource=source.resource,
            title=source.label,
            observations=[
                Observation(
                    source_key=source.key,
                    subject_id="conversion",
                    subject_label="Checkout conversion",
                    metric="checkout_conversion",
                    current=0.82,
                    baseline=0.95,
                    change_pct=-13.684,
                )
            ],
            )


class AmbiguousSupersetCatalogDouble(SupersetCatalogDouble):
    def __init__(self):
        super().__init__()
        self.resources[1] = self.resources[1].model_copy(update={"title": "Growth overview"})


class BoundedAnchorCatalogDouble(SupersetCatalogDouble):
    def __init__(self):
        super().__init__()
        self.resources.extend(
            ResourceDescriptor(
                adapter=self.name,
                resource=f"dashboard:{index}",
                kind="dashboard",
                title=f"A decoy growth asset {index}",
                description="A distractor that is not the selected operating asset.",
            )
            for index in range(10, 30)
        )
        self.resources.append(
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:42",
                kind="dashboard",
                title="Z canonical growth asset",
                description="The human-selected growth asset.",
            )
        )


class StaleSupersetCatalogDouble(SupersetCatalogDouble):
    def __init__(self):
        super().__init__()
        self.resources[0] = self.resources[0].model_copy(
            update={"contract": ResourceContract(source_status="stale")}
        )


class OnboardingJevDouble:
    name = "jev-onboarding-test-double"

    async def rank_resources(self, goal, resources):
        del goal
        return {
            f"{resource.adapter}|{resource.resource}": {
                "dashboard:7": 0.94,
                "dashboard:8": 0.31,
                "dashboard:9": 0.12,
            }[resource.resource]
            for resource in resources
        }

    async def compile_plan(self, state, card):
        del state
        return {
            "capabilities": ["percent_change", "cross_source_comparison"],
            "baseline": card.comparison_windows[0],
        }

    async def select_investigation_sources(
        self, state, card, plan, candidates, max_sources
    ):
        del state, card, plan, candidates, max_sources
        return {"probability": 0.0, "selections": []}

    async def judge(self, state, card, plan, observations):
        del plan
        return InsightResult(
            card_id=card.id,
            outcome=Outcome.NOTIFY,
            summary="Test-only onboarding result.",
            rationale="Test-only onboarding decision.",
            confidence=0.91,
            probabilities={Outcome.NOTIFY.value: 0.91},
            delivery_methods=[],
            evidence=[Evidence.model_validate(item) for item in state["evidence"]],
            observations=observations,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )


class ExplicitAnchorJevDouble(OnboardingJevDouble):
    async def rank_resources(self, goal, resources):
        del goal
        return {f"{resource.adapter}|{resource.resource}": 0.20 for resource in resources}


class BundleJevDouble(OnboardingJevDouble):
    async def rank_resources(self, goal, resources):
        del goal
        return {
            f"{resource.adapter}|{resource.resource}": {
                "dashboard:7": 0.94,
                "dashboard:8": 0.88,
                "dashboard:9": 0.12,
            }[resource.resource]
            for resource in resources
        }


class CompanyGraphContextDouble:
    name = "company-graph"

    async def get_context(self, card, resources):
        del card, resources
        return ContextSnapshot(
            provider=self.name,
            version="graph-v7",
            facts=[
                ContextFact(
                    fact_id="growth-diagnostic",
                    subject_ref="superset|dashboard:7",
                    relation="requires_diagnostic_context",
                    object_ref="superset|dashboard:8",
                    statement="Finance context is required to interpret growth movement.",
                    provenance=["owner:growth-ops"],
                )
            ],
        )


class NoResourceRankingJudger:
    name = "non-jev-test-judger"


class LowRelevanceJudger(OnboardingJevDouble):
    async def rank_resources(self, goal, resources):
        del goal
        return {f"{resource.adapter}|{resource.resource}": 0.12 for resource in resources}


class AmbiguousCatalogJevDouble(OnboardingJevDouble):
    async def rank_resources(self, goal, resources):
        del goal
        return {
            f"{resource.adapter}|{resource.resource}": 0.91
            if resource.resource in {"dashboard:7", "dashboard:8"}
            else 0.12
            for resource in resources
        }


def make_server(tmp_path, judger=None, *, sqlite=False, catalog=None, context_provider=None):
    registry = SourceRegistry([catalog or SupersetCatalogDouble()], authorized_tenants=["default"])
    engine = InsightEngine(
        judger or OnboardingJevDouble(),
        registry=registry,
        context_provider=context_provider,
    )
    card_store = (
        SQLiteInsightCardStore(tmp_path / "signalweave.db")
        if sqlite
        else JsonInsightCardStore(tmp_path / "cards.json")
    )
    return create_mcp(
        Runtime(
            card_store=card_store,
            sources=registry,
            engine=engine,
            decision_receipts=(
                SQLiteDecisionReceiptStore(tmp_path / "signalweave.db") if sqlite else None
            ),
            decision_feedback=(
                SQLiteDecisionFeedbackStore(tmp_path / "signalweave.db") if sqlite else None
            ),
            context_provider=context_provider,
            principal=PrincipalContext(principal_id="test-principal", tenant_id="default"),
        )
    )


def tool(server, name):
    return server._tool_manager.get_tool(name).fn


@pytest.mark.asyncio
async def test_mcp_can_use_trusted_request_principal_for_shared_catalog(tmp_path):
    catalog = SupersetCatalogDouble()
    tenant_resources = []
    for tenant_id in ("tenant-a", "tenant-b"):
        tenant_resources.extend(
            resource.model_copy(
                update={
                    "contract": resource.contract.model_copy(
                        update={"tenant_id": tenant_id}
                    )
                }
            )
            for resource in catalog.resources
        )
    shared_catalog = SupersetCatalogDouble()
    shared_catalog.resources = tenant_resources
    registry = SourceRegistry([shared_catalog])
    runtime = Runtime(
        card_store=JsonInsightCardStore(tmp_path / "cards.json"),
        sources=registry,
        engine=InsightEngine(OnboardingJevDouble(), registry=registry),
    )
    server = create_mcp(
        runtime,
        principal_resolver=lambda context: PrincipalContext(
            principal_id=context.principal_id,
            tenant_id=context.tenant_id,
            authorization_source="test-gateway",
        ),
    )

    discovery = await tool(server, "discover_insight_sources")(
        goal="Checkout conversion risk.",
        adapter="superset",
        ctx=SimpleNamespace(principal_id="b-user", tenant_id="tenant-b"),
    )

    assert discovery["matches"]
    assert {match["contract"]["tenant_id"] for match in discovery["matches"]} == {
        "tenant-b"
    }
    assert discovery["authorized_tenant"] == "tenant-b"

    runtime.card_store.save_card(
        InsightCard(
            id="tenant-a-card",
            title="Tenant A",
            what_to_watch="Tenant A conversion",
            why_watch="Keep tenant A isolated",
            principal_id="a-user",
            principal_tenant="tenant-a",
        )
    )
    with pytest.raises(ValueError, match="outside the authenticated principal tenant"):
        await tool(server, "get_insight_card")(
            "tenant-a-card",
            ctx=SimpleNamespace(principal_id="b-user", tenant_id="tenant-b"),
        )

    readiness = tool(server, "get_enterprise_readiness")(
        ctx=SimpleNamespace(principal_id="b-user", tenant_id="tenant-b")
    )
    assert readiness["tenant_id"] == "tenant-b"
    assert readiness["cards"] == []


@pytest.mark.asyncio
async def test_generic_card_flow_discovers_proposes_previews_and_requires_approval(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PUSH_WEBHOOK_TOKEN", "test-webhook-token")
    server = make_server(tmp_path)

    discovery = await tool(server, "discover_insight_sources")(
        goal="Checkout conversion and mobile revenue risk.",
        adapter="superset",
        limit=2,
    )
    assert discovery["matches"][0]["resource"] == "dashboard:7"
    assert discovery["matches"][0]["recommended"] is True

    proposal = await tool(server, "propose_insight_card")(
        what_to_watch="Checkout conversion and related mobile signals.",
        why_watch="Help Growth decide whether a conversion movement needs action.",
        watch_for=["Checkout conversion is materially down.", "Mobile errors corroborate the movement."],
        questions=["Is mobile the likely source of the regression?"],
        decision_guidance=(
            "Ignore normal variation; investigate when the primary movement lacks support; "
            "notify Growth Ops when the movement is corroborated by mobile errors."
        ),
        selected_sources=[
            {
                "ref": "superset|dashboard:7",
                "parameters": {"chart_ids": ["62", "64"]},
            }
        ],
        delivery_methods=[
            {
                "key": "growth-ops",
                "outcome": "notify",
                "label": "Growth Ops",
                "destination": "slack://growth-ops",
            }
        ],
    )
    card_id = proposal["proposal"]["card"]["id"]
    assert proposal["proposal"]["status"] == "draft"
    assert proposal["proposal"]["card"]["what_to_watch"].startswith("Checkout")
    assert proposal["proposal"]["card"]["watch_for"] == [
        "Checkout conversion is materially down.",
        "Mobile errors corroborate the movement.",
    ]
    assert proposal["proposal"]["card"]["retrieval_mode"] == "expand"
    assert proposal["proposal"]["card"]["sources"][0]["parameters"] == {
        "chart_ids": ["62", "64"]
    }
    assert proposal["proposal"]["onboarding_review"]["status"] == "ready_for_approval"
    assert proposal["proposal"]["onboarding_review"]["principal_id"] == "test-principal"
    assert proposal["proposal"]["onboarding_review"]["principal_tenant"] == "default"
    assert proposal["proposal"]["onboarding_review"]["discovery_receipt"]["evaluator"] == "jev-onboarding-test-double"
    assert proposal["proposal"]["onboarding_review"]["discovery_receipt"]["candidate_refs"]
    assert proposal["proposal"]["onboarding_review"]["source_candidates"][0]["selected"] is True
    assert proposal["proposal"]["setup_questions"]

    stored = tool(server, "get_insight_card")(card_id)
    assert stored["status"] == "draft"
    assert stored["principal_tenant"] == "default"
    assert stored["onboarding_review"]["discovery_receipt"]["principal_tenant"] == "default"
    assert len(stored["onboarding_review_history"]) == 1
    assert tool(server, "list_insight_cards")(status="draft")["count"] == 1

    correction = tool(server, "record_insight_card_correction")(
        card_id,
        kind="candidate-rejected",
        source_ref="superset|dashboard:8",
        note="Finance close is not part of this growth workflow.",
    )
    assert correction["status"] == "recorded"
    assert correction["correction"]["principal_tenant"] == "default"
    assert tool(server, "get_insight_card")(card_id)["onboarding_corrections"][0]["kind"] == (
        "candidate-rejected"
    )

    with pytest.raises(ValueError, match="draft"):
        await tool(server, "evaluate_insight_card")(card_id)

    app = server.streamable_http_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "draft-evaluation"},
            headers={"Authorization": "Bearer test-webhook-token"},
        )
    assert response.status_code == 409

    preview = await tool(server, "simulate_insight_card")(
        card_id,
        context={"provider": "agent-context", "version": "v1", "facts": []},
    )
    assert preview["status"] == "preview"
    assert preview["delivery_enabled"] is False
    assert preview["result"]["outcome"] == "notify"
    assert preview["result"]["context"]["trust"] == "unverified"
    assert preview["result"]["delivery_methods"][0]["key"] == "growth-ops"

    approved = await tool(server, "approve_insight_card")(card_id, actor="spoofed-label")
    assert approved["status"] == "approved"
    assert approved["card"]["approved_by"] == "test-principal"
    approved_card = tool(server, "get_insight_card")(card_id)
    assert approved_card["status"] == "approved"
    assert len(approved_card["onboarding_review_history"]) == 2
    assert tool(server, "list_insight_cards")(status="approved")["count"] == 1
    evaluated = await tool(server, "evaluate_insight_card")(card_id, actor="spoofed-label")
    assert evaluated["result"]["delivery_methods"][0]["key"] == "growth-ops"
    assert evaluated["receipt"]["actor"] == "test-principal"

    concurrent = await asyncio.gather(
        tool(server, "evaluate_insight_card")(
            card_id, idempotency_key="concurrent-evaluation", actor="scheduler-a"
        ),
        tool(server, "evaluate_insight_card")(
            card_id, idempotency_key="concurrent-evaluation", actor="scheduler-a"
        ),
    )
    assert sorted(result["replayed"] for result in concurrent) == [False, True]

    scoped_replay = await tool(server, "evaluate_insight_card")(
        card_id, idempotency_key="concurrent-evaluation", actor="scheduler-b"
    )
    assert scoped_replay["replayed"] is True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "approved-evaluation"},
            headers={"Authorization": "Bearer test-webhook-token"},
        )
    assert response.status_code == 200

    assert response.json()["result"]["delivery_methods"][0]["key"] == "growth-ops"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        replay = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "approved-evaluation"},
            headers={"Authorization": "Bearer test-webhook-token"},
        )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["receipt"]["status"] == "replayed"


@pytest.mark.asyncio
async def test_one_call_onboarding_returns_usable_human_review_packet_without_approval(tmp_path):
    server = make_server(tmp_path)

    onboarding = await tool(server, "onboard_insight_card")(
        what_to_watch="Checkout conversion and the signals that explain a material movement.",
        why_watch="Help Growth decide whether to investigate a customer-impacting regression.",
        watch_for=["Conversion falls materially", "A related mobile signal corroborates it"],
        questions=["What changed and what evidence explains it?"],
        decision_guidance=(
            "Ignore normal variation; investigate when evidence is incomplete; notify Growth "
            "Ops when the movement is corroborated."
        ),
        delivery_methods=[
            {
                "key": "growth-ops",
                "outcome": "notify",
                "label": "Growth Ops",
                "destination": "slack://growth-ops",
            }
        ],
    )

    assert onboarding["status"] == "ready_for_approval"
    assert onboarding["next_action"] == "simulate_then_approve"
    assert onboarding["approval_required"] is True
    assert onboarding["delivery_enabled"] is False
    assert onboarding["card"]["status"] == "draft"
    assert onboarding["card"]["sources"]
    assert onboarding["review"]["discovery_receipt"]["evaluator"] == (
        "jev-onboarding-test-double"
    )
    assert onboarding["plan"]["compiled_by"] == "jev-onboarding-test-double"

    stored = tool(server, "get_insight_card")(onboarding["card"]["id"])
    assert stored["status"] == "draft"


@pytest.mark.asyncio
async def test_one_call_onboarding_surfaces_missing_human_context_instead_of_guessing(tmp_path):
    server = make_server(tmp_path)

    onboarding = await tool(server, "onboard_insight_card")(
        what_to_watch="Checkout conversion.",
        why_watch="Support a growth decision.",
        delivery_methods=[
            {
                "key": "growth-ops",
                "outcome": "notify",
                "label": "Growth Ops",
                "destination": "slack://growth-ops",
            }
        ],
    )

    assert onboarding["status"] == "blocked"
    assert onboarding["next_action"] == "answer_setup_questions"
    assert onboarding["approval_required"] is True
    assert onboarding["delivery_enabled"] is False
    assert any(
        blocker["code"] == "decision-guidance-required"
        for blocker in onboarding["review"]["blockers"]
    )


@pytest.mark.asyncio
async def test_push_card_onboarding_blocks_without_human_decision_guidance(tmp_path):
    server = make_server(tmp_path)

    proposal = await tool(server, "propose_insight_card")(
        what_to_watch="Checkout conversion.",
        why_watch="Decide whether Growth should respond.",
        selected_sources=[{"ref": "superset|dashboard:7"}],
        delivery_methods=[
            {
                "key": "growth-ops",
                "outcome": "notify",
                "label": "Growth Ops",
                "destination": "slack://growth-ops",
            }
        ],
    )

    review = proposal["proposal"]["onboarding_review"]
    assert review["status"] == "needs_human_input"
    assert any(
        blocker["code"] == "decision-guidance-required"
        for blocker in review["blockers"]
    )


@pytest.mark.asyncio
async def test_discovery_abstains_when_no_candidate_clears_recommendation_threshold(tmp_path):
    server = make_server(tmp_path, judger=LowRelevanceJudger())

    discovery = await tool(server, "discover_insight_sources")(
        goal="A metric that is absent from this catalog.", adapter="superset", limit=3
    )

    assert discovery["no_match"] is True
    assert all(match["recommended"] is False for match in discovery["matches"])
    assert "No catalog candidate" in discovery["warnings"][0]


@pytest.mark.asyncio
async def test_webhook_fails_closed_and_rejects_oversized_or_invalid_payloads(
    tmp_path, monkeypatch
):
    server = make_server(tmp_path)
    app = server.streamable_http_app()
    monkeypatch.delenv("PUSH_WEBHOOK_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing_token = await client.post(
            "/webhooks/evaluate", content=b"{}"
        )
    assert missing_token.status_code == 503

    monkeypatch.setenv("PUSH_WEBHOOK_TOKEN", "test-webhook-token")
    monkeypatch.setenv("SIGNALWEAVE_MAX_HTTP_BODY_BYTES", "8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        oversized = await client.post(
            "/webhooks/evaluate",
            content=b'{"card_id":"x"}',
            headers={"Authorization": "Bearer test-webhook-token"},
        )
        malformed = await client.post(
            "/webhooks/evaluate",
            content=b"not-json",
            headers={"Authorization": "Bearer test-webhook-token"},
        )
    assert oversized.status_code == 413
    assert malformed.status_code == 400


@pytest.mark.asyncio
async def test_oidc_style_webhook_resolver_scopes_card_evaluation_without_shared_secret(tmp_path):
    registry = SourceRegistry([SupersetCatalogDouble()], authorized_tenants=["default"])
    runtime = Runtime(
        card_store=JsonInsightCardStore(tmp_path / "cards.json"),
        sources=registry,
        engine=InsightEngine(OnboardingJevDouble(), registry=registry),
    )
    runtime.card_store.save_card(
        InsightCard(
            id="tenant-a-webhook-card",
            title="Tenant A",
            what_to_watch="Tenant A metric",
            why_watch="Keep tenant A isolated",
            status=InsightCardStatus.APPROVED,
            principal_id="a-user",
            principal_tenant="tenant-a",
        )
    )
    server = create_mcp(
        runtime,
        http_principal_resolver=lambda: PrincipalContext(
            principal_id="b-user", tenant_id="tenant-b", authorization_source="oidc:test"
        ),
    )
    app = server.streamable_http_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/evaluate",
            json={"card_id": "tenant-a-webhook-card", "idempotency_key": "cross-tenant"},
        )
    assert response.status_code == 404
    assert "outside the authenticated principal tenant" in response.json()["error"]


@pytest.mark.asyncio
async def test_scoped_workflow_evaluation_rejects_foreign_snapshot_contract(tmp_path):
    server = make_server(tmp_path)
    card = InsightCard(
        id="scoped-eval-card",
        title="Scoped evaluation",
        what_to_watch="A tenant-owned metric",
        why_watch="Keep the evaluation dataset isolated.",
        sources=[
            {
                "key": "source-1",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
        principal_id="test-principal",
        principal_tenant="default",
    )
    # The MCP factory owns the store closure; create the card through its
    # public draft tool so this test exercises the same production path.
    draft = await tool(server, "draft_insight_card")(
        title=card.title,
        what_to_watch=card.what_to_watch,
        why_watch=card.why_watch,
        sources=[source.model_dump(mode="json") for source in card.sources],
    )
    with pytest.raises(ValueError, match="outside the authenticated principal tenant"):
        await tool(server, "evaluate_card_workflow")(
            draft["card"]["id"],
            cases=[
                {
                    "id": "foreign-snapshot",
                    "resources": [
                        {
                            "source_key": "source-1",
                            "adapter": "superset",
                            "resource": "dashboard:7",
                            "title": "Foreign dashboard",
                            "contract": {"tenant_id": "other-tenant", "authorized": True},
                        }
                    ],
                    "expected_outcome": "investigate",
                }
            ],
        )


@pytest.mark.asyncio
async def test_proposal_rejects_source_not_returned_by_discovery(tmp_path):
    server = make_server(tmp_path)

    with pytest.raises(ValueError, match="discover_insight_sources"):
        await tool(server, "propose_insight_card")(
            what_to_watch="Checkout conversion.",
            why_watch="Decide whether Growth should act.",
            selected_sources=[{"ref": "superset|dashboard:999"}],
        )


@pytest.mark.asyncio
async def test_review_insight_card_explains_omitted_recommended_sources(tmp_path):
    server = make_server(tmp_path, BundleJevDouble())
    drafted = await tool(server, "draft_insight_card")(
        title="Growth context review",
        what_to_watch="Checkout conversion and the context needed to understand a movement.",
        why_watch="Help Growth decide whether a conversion change needs action.",
        questions=["What explains the movement?"],
        sources=[
            {
                "key": "growth-anchor",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
    )

    review = await tool(server, "review_insight_card")(drafted["card"]["id"])

    assert review["review"]["status"] == "needs_human_input"
    assert review["review"]["selected_source_refs"] == ["superset|dashboard:7"]
    assert review["review"]["missing_recommended_refs"] == ["superset|dashboard:8"]
    candidate = next(
        item
        for item in review["review"]["source_candidates"]
        if item["resource"] == "dashboard:8"
    )
    assert candidate["recommended"] is True
    assert "Jev judged it materially relevant" in candidate["reason"]


@pytest.mark.asyncio
async def test_review_insight_card_surfaces_ambiguous_candidates(tmp_path):
    server = make_server(
        tmp_path,
        AmbiguousCatalogJevDouble(),
        catalog=AmbiguousSupersetCatalogDouble(),
    )
    drafted = await tool(server, "draft_insight_card")(
        title="Repeated growth source",
        what_to_watch="Checkout conversion.",
        why_watch="Decide whether Growth should act.",
        watch_for=["Conversion moves materially."],
        sources=[
            {
                "key": "growth",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
    )

    review = await tool(server, "review_insight_card")(drafted["card"]["id"])

    assert review["review"]["status"] == "needs_human_input"
    assert review["review"]["ambiguous_candidate_groups"] == [
        ["superset|dashboard:7", "superset|dashboard:8"]
    ]
    assert review["review"]["readiness_status"] == "needs_human_review"
    assert any(
        blocker["code"] == "definition-conflict"
        for blocker in review["review"]["blockers"]
    )
    assert any("Disambiguate" in question for question in review["review"]["questions"])


@pytest.mark.asyncio
async def test_approval_fails_closed_on_source_health_blocker(tmp_path):
    server = make_server(tmp_path, catalog=StaleSupersetCatalogDouble())
    drafted = await tool(server, "draft_insight_card")(
        title="Stale growth source",
        what_to_watch="Checkout conversion.",
        why_watch="Decide whether Growth should act.",
        sources=[
            {
                "key": "growth",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
    )

    card_id = drafted["card"]["id"]
    review = await tool(server, "review_insight_card")(card_id)
    assert review["review"]["readiness_status"] == "needs_human_review"
    with pytest.raises(ValueError, match="source-health-review"):
        await tool(server, "approve_insight_card")(card_id)


@pytest.mark.asyncio
async def test_direct_draft_accepts_free_form_card_and_outcome_routes(tmp_path):
    server = make_server(tmp_path)
    drafted = await tool(server, "draft_insight_card")(
        title="Cross-system data health",
        what_to_watch="A Superset dashboard and a warehouse quality query.",
        why_watch="Decide whether an analyst can trust the numbers.",
        sources=[
            {
                "key": "dashboard",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            },
            {
                "key": "quality",
                "adapter": "superset",
                "resource": "dashboard:8",
                "label": "Finance close",
            },
        ],
        questions=["Can the current numbers be trusted?"],
        delivery_methods=[
            {
                "key": "analyst-review",
                "outcome": "investigate",
                "label": "Analyst review",
                "destination": "queue://analysts",
            }
        ],
    )
    assert drafted["card"]["what_to_watch"].startswith("A Superset")
    assert drafted["plan"]["capabilities"] == [
        "percent_change",
        "cross_source_comparison",
    ]


@pytest.mark.asyncio
async def test_dynamic_bundle_keeps_anchors_and_adds_jev_related_sources(tmp_path):
    server = make_server(tmp_path, BundleJevDouble())
    drafted = await tool(server, "draft_insight_card")(
        title="Growth with finance context",
        what_to_watch="Checkout conversion and the context needed to understand a movement.",
        why_watch="Help Growth decide whether a conversion change needs action.",
        sources=[
            {
                "key": "growth-anchor",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
        questions=["What context explains a conversion movement?"],
        retrieval_mode="expand",
        card_id="dynamic-bundle",
    )
    assert drafted["card"]["retrieval_mode"] == "expand"

    bundle_preview = await tool(server, "resolve_insight_sources")("dynamic-bundle")
    bundle = bundle_preview["bundle"]
    assert bundle["anchor_source_keys"] == ["growth-anchor"]
    assert [match["resource"] for match in bundle["related_matches"]] == ["dashboard:8"]
    assert [source["resource"] for source in bundle["selected_sources"]] == [
        "dashboard:7",
        "dashboard:8",
    ]
    assert bundle["selected_sources"][1]["required"] is False

    await tool(server, "approve_insight_card")("dynamic-bundle")
    evaluated = await tool(server, "evaluate_insight_card")(
        "dynamic-bundle", idempotency_key="dynamic-bundle:1"
    )
    assert evaluated["retrieval"]["evaluator"] == "jev-onboarding-test-double"
    assert evaluated["result"]["retrieval"]["selected_sources"][1]["resource"] == "dashboard:8"
    assert evaluated["result"]["source_keys"] == ["growth-anchor", "related-superset-dashboard-8"]


@pytest.mark.asyncio
async def test_dynamic_bundle_avoids_colliding_with_human_source_keys(tmp_path):
    server = make_server(tmp_path, BundleJevDouble())
    drafted = await tool(server, "draft_insight_card")(
        title="Collision-safe context",
        what_to_watch="Checkout conversion and related context.",
        why_watch="Decide whether the conversion movement needs action.",
        sources=[
            {
                "key": "related-superset-dashboard-8",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
        retrieval_mode="expand",
        card_id="collision-safe-bundle",
    )

    bundle = (await tool(server, "resolve_insight_sources")("collision-safe-bundle"))["bundle"]
    assert [source["key"] for source in bundle["selected_sources"]] == [
        "related-superset-dashboard-8",
        "related-superset-dashboard-8-2",
    ]
    assert drafted["card"]["retrieval_mode"] == "expand"


@pytest.mark.asyncio
async def test_sqlite_runtime_replays_completed_evaluation_after_restart(tmp_path):
    server = make_server(tmp_path, sqlite=True)
    drafted = await tool(server, "draft_insight_card")(
        title="Restart-safe card",
        what_to_watch="Checkout conversion.",
        why_watch="Decide whether Growth should act.",
        sources=[
            {
                "key": "growth",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
        questions=["Should this run use the latest available snapshot?"],
        card_id="restart-safe",
    )
    await tool(server, "approve_insight_card")("restart-safe")
    first = await tool(server, "evaluate_insight_card")(
        drafted["card"]["id"], idempotency_key="daily:restart-safe"
    )

    restarted = make_server(tmp_path, sqlite=True)
    replay = await tool(restarted, "evaluate_insight_card")(
        "restart-safe", idempotency_key="daily:restart-safe"
    )

    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert replay["receipt"]["status"] == "replayed"
    assert replay["result"] == first["result"]


@pytest.mark.asyncio
async def test_decision_feedback_is_scoped_and_survives_restart(tmp_path):
    server = make_server(tmp_path, sqlite=True)
    drafted = await tool(server, "draft_insight_card")(
        title="Feedback card",
        what_to_watch="Checkout conversion.",
        why_watch="Decide whether Growth should act.",
        decision_guidance="Ignore ordinary movement and investigate a material conversion change.",
        watch_for=["Conversion drops materially."],
        questions=["Is this a meaningful movement?"],
        sources=[
            {
                "key": "growth",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
        delivery_methods=[
            {
                "key": "growth-ops",
                "outcome": "notify",
                "label": "Growth Ops",
                "destination": "slack://growth-ops",
            }
        ],
        card_id="feedback-card",
    )
    await tool(server, "approve_insight_card")("feedback-card")
    evaluated = await tool(server, "evaluate_insight_card")(
        drafted["card"]["id"], idempotency_key="daily:feedback-card"
    )

    recovered = tool(server, "get_decision_receipt")(
        receipt_id=evaluated["receipt"]["receipt_id"]
    )
    assert recovered["receipt"]["delivery_mode"] == "shadow"
    assert recovered["receipt"]["status"] == "delivery_disabled"
    assert recovered["result"] == evaluated["result"]
    assert recovered["feedback"] == []

    recorded = tool(server, "record_decision_feedback")(
        idempotency_key="daily:feedback-card",
        kind="noisy",
        feedback_id="feedback:daily:feedback-card",
        expected_outcome="ignore",
        note="The movement was expected seasonality.",
    )

    assert recorded["status"] == "recorded"
    assert recorded["feedback"]["principal_tenant"] == "default"
    assert recorded["feedback"]["expected_outcome"] == "ignore"
    assert tool(server, "list_decision_feedback")(card_id="feedback-card")["count"] == 1

    replayed = tool(server, "record_decision_feedback")(
        idempotency_key="daily:feedback-card",
        kind="noisy",
        feedback_id="feedback:daily:feedback-card",
        expected_outcome="ignore",
        note="The movement was expected seasonality.",
    )
    assert replayed["status"] == "replayed"
    assert tool(server, "list_decision_feedback")(card_id="feedback-card")["count"] == 1

    restarted = make_server(tmp_path, sqlite=True)
    listed = tool(restarted, "list_decision_feedback")(idempotency_key="daily:feedback-card")
    assert listed["count"] == 1
    assert listed["feedback"][0]["note"] == "The movement was expected seasonality."
    restarted_receipt = tool(restarted, "get_decision_receipt")(
        idempotency_key="daily:feedback-card"
    )
    assert restarted_receipt["receipt"]["delivery_mode"] == "shadow"
    assert len(restarted_receipt["feedback"]) == 1

    with pytest.raises(ValueError, match="unknown decision receipt"):
        tool(restarted, "record_decision_feedback")(
            idempotency_key="daily:missing",
            kind="useful",
        )


@pytest.mark.asyncio
async def test_feedback_keeps_the_receipt_card_version_after_a_card_revision(tmp_path):
    server = make_server(tmp_path, sqlite=True)
    await tool(server, "draft_insight_card")(
        title="Versioned feedback card",
        what_to_watch="Checkout conversion.",
        why_watch="Decide whether Growth should act.",
        decision_guidance="Ignore ordinary movement and notify Growth when conversion drops materially.",
        watch_for=["Conversion drops materially."],
        questions=["Is this a meaningful movement?"],
        sources=[
            {
                "key": "growth",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
        delivery_methods=[
            {
                "key": "growth-ops",
                "outcome": "notify",
                "label": "Growth Ops",
                "destination": "slack://growth-ops",
            }
        ],
        card_id="versioned-feedback",
    )
    await tool(server, "approve_insight_card")("versioned-feedback")
    evaluated = await tool(server, "evaluate_insight_card")(
        "versioned-feedback", idempotency_key="daily:versioned-feedback"
    )

    stored = tool(server, "get_insight_card")("versioned-feedback")
    revised = InsightCard.model_validate(stored).model_copy(
        update={"version": 2, "compiled_plan": None}
    )
    SQLiteInsightCardStore(tmp_path / "signalweave.db").save_card(revised)

    feedback = tool(server, "record_decision_feedback")(
        idempotency_key="daily:versioned-feedback",
        feedback_id="feedback:versioned-feedback",
        kind="useful",
    )
    assert evaluated["receipt"]["card_version"] == 1
    assert feedback["feedback"]["card_version"] == 1


def test_enterprise_readiness_reports_open_gates(tmp_path):
    server = make_server(tmp_path)

    report = tool(server, "get_enterprise_readiness")()

    assert report["status"] == "blocked"
    assert report["tenant_id"] == "default"
    assert report["context_provider"]["configured"] is False
    assert {gate["code"] for gate in report["gates"]} >= {
        "bootstrap-certification-missing",
        "no-cards",
        "retrieval-certification-missing",
    }


def test_enterprise_readiness_blocks_stale_workflow_certification(tmp_path):
    registry = SourceRegistry([SupersetCatalogDouble()], authorized_tenants=["default"])
    reports = InMemoryCertificationReportStore()
    runtime = Runtime(
        card_store=JsonInsightCardStore(tmp_path / "cards.json"),
        sources=registry,
        engine=InsightEngine(OnboardingJevDouble(), registry=registry),
        certification_reports=reports,
        principal=PrincipalContext(principal_id="test-principal", tenant_id="default"),
    )
    server = create_mcp(runtime)
    runtime.card_store.save_card(
        InsightCard(
            id="stale-card",
            title="Stale certification",
            what_to_watch="Growth movement",
            why_watch="Decide whether growth needs action",
            status=InsightCardStatus.APPROVED,
            principal_id="test-principal",
            principal_tenant="default",
            version=2,
        )
    )
    reports.save(
        CertificationRecord(
            report_id="workflow:stale-card:v1",
            kind="card_workflow",
            subject_id="stale-card",
            tenant_id="default",
            subject_version="1",
            status="approved",
        )
    )

    report = tool(server, "get_enterprise_readiness")()

    assert report["status"] == "blocked"
    assert "workflow-certification-stale" in {gate["code"] for gate in report["gates"]}
    summary = report["cards"][0]["workflow_certification"]
    assert summary["stale"] is True


@pytest.mark.asyncio
async def test_approval_retains_authorized_anchor_omitted_from_bounded_review(tmp_path):
    server = make_server(
        tmp_path,
        judger=ExplicitAnchorJevDouble(),
        catalog=BoundedAnchorCatalogDouble(),
    )
    drafted = await tool(server, "draft_insight_card")(
        title="Growth anchor",
        what_to_watch="Monitor growth movement.",
        why_watch="Decide whether the growth team needs to act.",
        watch_for=["Material movement in the selected growth asset."],
        questions=["Does the selected asset support action?"],
        decision_guidance="Ignore normal movement; investigate or notify only when evidence supports action.",
        sources=[
            {
                "key": "growth-anchor",
                "adapter": "superset",
                "resource": "dashboard:42",
                "label": "Z canonical growth asset",
            }
        ],
        delivery_methods=[
            {
                "key": "growth-ops",
                "outcome": "notify",
                "label": "Growth Ops",
                "destination": "slack://growth-ops",
            }
        ],
        card_id="bounded-anchor-card",
    )

    reviewed = await tool(server, "review_insight_card")(drafted["card"]["id"], limit=10)
    review = reviewed["review"]

    assert review["selected_outside_bounded_candidates"] == []
    assert "explicit-card-anchor" in {
        signal
        for candidate in review["source_candidates"]
        for signal in candidate["retrieval_signals"]
        if candidate["resource"] == "dashboard:42"
    }
    approved = await tool(server, "approve_insight_card")(drafted["card"]["id"])
    assert approved["status"] == "approved"


@pytest.mark.asyncio
async def test_runtime_context_provider_expands_bundle_and_is_receipt_visible(tmp_path):
    server = make_server(
        tmp_path,
        judger=BundleJevDouble(),
        sqlite=True,
        context_provider=CompanyGraphContextDouble(),
    )
    drafted = await tool(server, "draft_insight_card")(
        title="Graph-backed growth pulse",
        what_to_watch="Growth movement.",
        why_watch="Decide whether Growth should act.",
        questions=["What related evidence explains the movement?"],
        sources=[
            {
                "key": "growth",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
        retrieval_mode="expand",
        card_id="graph-backed-card",
    )

    preview = await tool(server, "simulate_insight_card")(drafted["card"]["id"])
    assert preview["result"]["context"]["provider"] == "company-graph"
    assert preview["result"]["context"]["version"] == "graph-v7"
    assert "dashboard:8" in {source["resource"] for source in preview["retrieval"]["selected_sources"]}

    await tool(server, "approve_insight_card")("graph-backed-card")
    evaluated = await tool(server, "evaluate_insight_card")(
        "graph-backed-card", idempotency_key="daily:graph-backed"
    )
    assert evaluated["receipt"]["context_provider"] == "company-graph"
    assert evaluated["receipt"]["context_version"] == "graph-v7"

    feedback = tool(server, "record_decision_feedback")(
        idempotency_key="daily:graph-backed",
        kind="useful",
        expected_outcome="notify",
    )
    assert feedback["feedback"]["context_provider"] == "company-graph"
    assert feedback["feedback"]["context_version"] == "graph-v7"


def test_mcp_exposes_generic_authoring_tools(tmp_path):
    server = make_server(tmp_path)
    names = set(server._tool_manager._tools)
    assert {
        "assess_bootstrap",
        "discover_insight_sources",
        "evaluate_card_workflow",
        "evaluate_retrieval_quality",
        "resolve_insight_sources",
        "review_insight_card",
        "record_insight_card_correction",
        "record_decision_feedback",
        "list_decision_feedback",
        "get_enterprise_readiness",
        "propose_insight_card",
        "draft_insight_card",
        "simulate_insight_card",
        "approve_insight_card",
        "evaluate_insight_card",
        "get_decision_receipt",
        "list_insight_cards",
        "get_insight_card",
        "get_certification_report",
        "list_certification_reports",
    } <= names


@pytest.mark.asyncio
async def test_mcp_bootstrap_reports_local_catalog_fallback_honestly(tmp_path):
    server = make_server(tmp_path)

    report = await tool(server, "assess_bootstrap")(
        manifest={
            "tenant_id": "default",
            "adapters": [
                {
                    "adapter": "superset",
                    "probe_goal": "growth dashboard",
                    "required_capabilities": ["catalog", "inspect"],
                }
            ],
        }
    )

    assert report["status"] == "needs_review"
    assert report["adapters"][0]["capabilities"]["catalog"] is True
    assert report["adapters"][0]["capabilities"]["inspect"] is True
    assert any("local-scan-fallback" in warning for warning in report["warnings"])


@pytest.mark.asyncio
async def test_mcp_retrieval_quality_keeps_owner_labels_outside_discovery(tmp_path):
    server = make_server(tmp_path)

    report = await tool(server, "evaluate_retrieval_quality")(
        cases=[
            {
                "id": "growth-dashboard",
                "goal": "Checkout conversion and mobile revenue risk",
                "expected_resource_refs": ["superset|dashboard:7"],
            }
        ],
        thresholds={
            "min_candidate_recall": 1,
            "min_recommended_precision": 1,
            "min_recommended_recall": 1,
        },
    )

    assert report["status"] == "approved"
    assert report["candidate_recall"] == 1
    assert report["recommended_recall"] == 1
    assert report["certification_report_id"]
    stored_report = tool(server, "get_certification_report")(
        report["certification_report_id"]
    )
    assert stored_report["kind"] == "retrieval_quality"
    assert tool(server, "list_certification_reports")()["count"] == 1


@pytest.mark.asyncio
async def test_discovery_requires_jev_resource_ranking(tmp_path):
    registry = SourceRegistry([SupersetCatalogDouble()])
    server = create_mcp(
        Runtime(
            card_store=JsonInsightCardStore(tmp_path / "cards.json"),
            sources=registry,
            engine=InsightEngine(NoResourceRankingJudger(), registry=registry),
        )
    )

    with pytest.raises(RuntimeError, match="does not support resource discovery"):
        await tool(server, "discover_insight_sources")(goal="Checkout growth")

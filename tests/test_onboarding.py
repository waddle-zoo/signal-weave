import asyncio

import httpx
import pytest

from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import (
    Evidence,
    InsightResult,
    Observation,
    Outcome,
    ResourceDescriptor,
    ResourceSnapshot,
)
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import (
    JsonInsightCardStore,
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


class NoResourceRankingJudger:
    name = "non-jev-test-judger"


def make_server(tmp_path, judger=None, *, sqlite=False):
    registry = SourceRegistry([SupersetCatalogDouble()])
    engine = InsightEngine(judger or OnboardingJevDouble(), registry=registry)
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
        )
    )


def tool(server, name):
    return server._tool_manager.get_tool(name).fn


@pytest.mark.asyncio
async def test_generic_card_flow_discovers_proposes_previews_and_requires_approval(tmp_path):
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
    assert proposal["proposal"]["setup_questions"]

    stored = tool(server, "get_insight_card")(card_id)
    assert stored["status"] == "draft"
    assert tool(server, "list_insight_cards")(status="draft")["count"] == 1

    with pytest.raises(ValueError, match="draft"):
        await tool(server, "evaluate_insight_card")(card_id)

    app = server.streamable_http_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "draft-evaluation"},
        )
    assert response.status_code == 409

    preview = await tool(server, "simulate_insight_card")(card_id)
    assert preview["status"] == "preview"
    assert preview["delivery_enabled"] is False
    assert preview["result"]["outcome"] == "notify"
    assert preview["result"]["delivery_methods"][0]["key"] == "growth-ops"

    approved = await tool(server, "approve_insight_card")(card_id)
    assert approved["status"] == "approved"
    assert tool(server, "get_insight_card")(card_id)["status"] == "approved"
    assert tool(server, "list_insight_cards")(status="approved")["count"] == 1
    evaluated = await tool(server, "evaluate_insight_card")(card_id)
    assert evaluated["result"]["delivery_methods"][0]["key"] == "growth-ops"

    concurrent = await asyncio.gather(
        tool(server, "evaluate_insight_card")(
            card_id, idempotency_key="concurrent-evaluation", actor="scheduler-a"
        ),
        tool(server, "evaluate_insight_card")(
            card_id, idempotency_key="concurrent-evaluation", actor="scheduler-b"
        ),
    )
    assert sorted(result["replayed"] for result in concurrent) == [False, True]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "approved-evaluation"},
        )
    assert response.status_code == 200
    assert response.json()["result"]["delivery_methods"][0]["key"] == "growth-ops"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        replay = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "approved-evaluation"},
        )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["receipt"]["status"] == "replayed"


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


def test_mcp_exposes_generic_authoring_tools(tmp_path):
    server = make_server(tmp_path)
    names = set(server._tool_manager._tools)
    assert {
        "discover_insight_sources",
        "resolve_insight_sources",
        "propose_insight_card",
        "draft_insight_card",
        "simulate_insight_card",
        "approve_insight_card",
        "evaluate_insight_card",
        "list_insight_cards",
        "get_insight_card",
    } <= names


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

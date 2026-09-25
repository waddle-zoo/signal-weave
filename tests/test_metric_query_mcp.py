from types import SimpleNamespace

import pytest

from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import (
    MetricDefinition,
    MetricQueryCard,
    MetricQueryPlan,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
)
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import JsonInsightCardStore, JsonMetricQueryCardStore


class CatalogAdapter:
    name = "trino"

    async def list_resources(self):
        return [
            ResourceDescriptor(
                adapter="trino",
                resource="query:orders",
                kind="metric_query",
                title="Orders metric catalog",
                description="Approved revenue definitions.",
                contract=ResourceContract(
                    tenant_id="acme",
                    domain="finance",
                    metric_definitions=[
                        MetricDefinition(
                            key="net_revenue",
                            label="Net revenue",
                            description="Revenue after refunds from completed orders.",
                            relation="lakehouse.finance.orders",
                            aggregation="sum",
                            measure_column="net_revenue",
                            time_column="occurred_at",
                            dimensions={"user_type": "user_type"},
                            partition_column="event_date",
                        )
                    ],
                ),
            )
        ]

    async def inspect(self, source):
        raise AssertionError(f"metric query compilation should not execute {source.resource}")


class QuerySelector:
    name = "jev-test-double"

    async def compile_plan(self, state, card):
        del state, card
        return {"capabilities": [], "baseline": "previous_period"}

    async def judge(self, state, card, plan, observations):
        del state, card, plan, observations
        raise AssertionError("metric query test should not evaluate an insight card")

    async def rank_resources(self, goal, resources):
        del goal, resources
        return {}

    async def select_metric_plan(
        self, goal, candidates, requested_dimensions, requested_time_grain
    ):
        del goal
        return {
            "candidate_id": candidates[0]["candidate_id"],
            "probability": 0.97,
            "dimensions": requested_dimensions or ["user_type"],
            "time_grain": requested_time_grain or "month",
        }


def tool(server, name):
    return server._tool_manager.get_tool(name).fn


@pytest.mark.asyncio
async def test_metric_query_card_is_plain_language_then_deterministic_sql(tmp_path):
    registry = SourceRegistry([CatalogAdapter()], authorized_tenants=["acme"])
    server = create_mcp(
        Runtime(
            card_store=JsonInsightCardStore(tmp_path / "insight-cards.json"),
            metric_query_store=JsonMetricQueryCardStore(tmp_path / "metric-cards.json"),
            sources=registry,
            engine=InsightEngine(QuerySelector(), registry=registry),
        )
    )

    proposed = await tool(server, "propose_metric_query_card")(
        question="What is net revenue per user type by month?",
        why="Give Finance a reproducible monthly breakdown.",
        selected_sources=[{"ref": "trino|query:orders", "label": "Orders catalog"}],
        requested_dimensions=["user_type"],
        requested_time_grain="month",
        title="Monthly net revenue",
    )
    card_id = proposed["card"]["id"]
    assert proposed["status"] == "draft"
    assert proposed["card"]["query_plan"]["metric_key"] == "net_revenue"

    preview = tool(server, "compile_metric_query_card")(
        card_id,
        "2026-01-01T00:00:00+00:00",
        "2026-02-01T00:00:00+00:00",
    )
    assert preview["status"] == "preview"
    assert "SUM(\"net_revenue\")" in preview["compiled_query"]["sql"]
    assert ":window_start" in preview["compiled_query"]["sql"]

    approved = tool(server, "approve_metric_query_card")(card_id)
    assert approved["status"] == "approved"
    compiled = tool(server, "compile_metric_query_card")(
        card_id,
        "2026-01-01T00:00:00+00:00",
        "2026-02-01T00:00:00+00:00",
    )
    assert compiled["status"] == "approved"


def test_metric_query_cards_are_scoped_for_list_lookup_compile_and_approval(tmp_path):
    registry = SourceRegistry([CatalogAdapter()], authorized_tenants=["acme"])
    store = JsonMetricQueryCardStore(tmp_path / "metric-cards.json")
    plan = MetricQueryPlan(
        source_key="source-1-query-orders",
        metric_key="net_revenue",
        relation="lakehouse.finance.orders",
        dialect="trino",
        aggregation="sum",
        measure_column="net_revenue",
        time_column="occurred_at",
        time_grain="month",
        dimensions={"user_type": "user_type"},
        partition_column="event_date",
        selection_probability=0.97,
    )
    for tenant in ("tenant-a", "tenant-b"):
        store.save_card(
            MetricQueryCard(
                id=f"metric-{tenant}",
                title=f"{tenant} revenue",
                question="What is net revenue?",
                why="Operate the business.",
                sources=[
                    {
                        "key": "source-1-query-orders",
                        "adapter": "trino",
                        "resource": "query:orders",
                        "label": "Orders",
                    }
                ],
                query_plan=plan,
                principal_id=f"{tenant}-user",
                principal_tenant=tenant,
            )
        )
    server = create_mcp(
        Runtime(
            card_store=JsonInsightCardStore(tmp_path / "insight-cards.json"),
            metric_query_store=store,
            sources=registry,
            engine=InsightEngine(QuerySelector(), registry=registry),
        ),
        principal_resolver=lambda ctx: PrincipalContext(
            principal_id=ctx.principal_id,
            tenant_id=ctx.tenant_id,
        ),
    )

    tenant_a = SimpleNamespace(principal_id="a-user", tenant_id="tenant-a")
    assert tool(server, "list_metric_query_cards")(ctx=tenant_a)["cards"][0]["id"] == (
        "metric-tenant-a"
    )
    with pytest.raises(ValueError, match="outside the authenticated principal tenant"):
        tool(server, "get_metric_query_card")("metric-tenant-b", ctx=tenant_a)
    with pytest.raises(ValueError, match="outside the authenticated principal tenant"):
        tool(server, "compile_metric_query_card")(
            "metric-tenant-b",
            "2024-01-01T00:00:00Z",
            "2024-02-01T00:00:00Z",
            ctx=tenant_a,
        )
    with pytest.raises(ValueError, match="outside the authenticated principal tenant"):
        tool(server, "approve_metric_query_card")("metric-tenant-b", ctx=tenant_a)

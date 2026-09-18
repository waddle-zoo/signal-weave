import pytest

from signalweave.models import MetricDefinition, ResourceContract, ResourceDescriptor, SourceRef
from signalweave.query_planner import QueryWindow, compile_query, plan_query
from signalweave.sources import SourceRegistry
from signalweave.trino_adapter import TrinoQueryAdapter


def metric_resource(*, tenant_id="acme", resource="query:revenue"):
    return ResourceDescriptor(
        adapter="trino",
        resource=resource,
        kind="metric_query",
        title="Net revenue by user type",
        description="Net revenue for active users by user type and month.",
        contract=ResourceContract(
            tenant_id=tenant_id,
            domain="finance",
            population="completed customer transactions",
            grain="one row per transaction",
            roles=["primary_metric"],
            metric_definitions=[
                MetricDefinition(
                    key="net_revenue",
                    label="Net revenue",
                    description="Net revenue from completed transactions.",
                    relation="lakehouse.analytics.orders",
                    aggregation="sum",
                    measure_column="net_revenue",
                    time_column="occurred_at",
                    dimensions={"user_type": "user_type", "region": "region"},
                    partition_column="event_date",
                    aliases=["revenue after refunds", "NRR"],
                    population="completed customer transactions",
                    grain="one row per transaction",
                )
            ],
        ),
    )


class Selector:
    name = "jev-test-double"

    async def select_metric_plan(
        self, goal, candidates, requested_dimensions, requested_time_grain
    ):
        del goal
        return {
            "candidate_id": candidates[0]["candidate_id"],
            "probability": 0.94,
            "dimensions": requested_dimensions or ["user_type"],
            "time_grain": requested_time_grain or "month",
        }


@pytest.mark.asyncio
async def test_plan_query_selects_typed_metric_and_compiles_bounded_trino_sql():
    descriptor = metric_resource()
    registry = SourceRegistry([CatalogAdapter([descriptor])], authorized_tenants=["acme"])
    source = SourceRef(
        key="revenue",
        adapter="trino",
        resource="query:revenue",
        label="Net revenue",
    )

    plan = await plan_query(
        registry=registry,
        selector=Selector(),
        goal="What is net revenue per user type by month?",
        source_refs=[source],
        requested_dimensions=["user_type"],
        requested_time_grain="month",
    )
    compiled = compile_query(
        plan,
        QueryWindow("2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),
    )

    assert plan.metric_key == "net_revenue"
    assert plan.dimensions == {"user_type": "user_type"}
    assert 'FROM "lakehouse"."analytics"."orders"' in compiled.sql
    assert 'SUM("net_revenue") AS metric_value' in compiled.sql
    assert 'date_trunc(\'month\', "occurred_at") AS "month"' in compiled.sql
    assert '"event_date" >= CAST(:window_start AS TIMESTAMP)' in compiled.sql
    assert compiled.parameters["window_end"].startswith("2026-02")
    assert len(compiled.fingerprint) == 24


@pytest.mark.asyncio
async def test_query_planning_rejects_dimension_not_in_approved_definition():
    descriptor = metric_resource()
    registry = SourceRegistry([CatalogAdapter([descriptor])], authorized_tenants=["acme"])
    source = SourceRef(key="revenue", adapter="trino", resource="query:revenue", label="Revenue")

    with pytest.raises(ValueError, match="not available"):
        await plan_query(
            registry=registry,
            selector=Selector(),
            goal="Net revenue by customer segment",
            source_refs=[source],
            requested_dimensions=["customer_segment"],
        )


@pytest.mark.asyncio
async def test_registry_filters_tenant_and_rejects_unlisted_resource():
    allowed = metric_resource(tenant_id="acme")
    foreign = metric_resource(tenant_id="other", resource="query:foreign")
    registry = SourceRegistry(
        [CatalogAdapter([allowed, foreign])], authorized_tenants=["acme"]
    )

    assert [item.resource for item in await registry.list_resources()] == ["query:revenue"]
    snapshots = await registry.resolve(
        [
            SourceRef(
                key="foreign",
                adapter="trino",
                resource="query:foreign",
                label="Foreign",
            )
        ]
    )
    assert snapshots[0].error
    assert "authorized adapter catalog" in snapshots[0].error


@pytest.mark.asyncio
async def test_trino_adapter_executes_only_compiled_plan_and_normalizes_rows():
    descriptor = metric_resource()
    executor = FakeExecutor(
        [
            {"user_type": "business", "month": "2026-01-01", "metric_value": 120, "baseline_metric_value": 100}
        ]
    )
    adapter = TrinoQueryAdapter([descriptor], executor)
    snapshot = await adapter.inspect(
        SourceRef(
            key="revenue",
            adapter="trino",
            resource="query:revenue",
            label="Revenue",
            parameters={
                "metric_key": "net_revenue",
                "dimensions": ["user_type"],
                "time_grain": "month",
                "window_start": "2026-01-01T00:00:00+00:00",
                "window_end": "2026-02-01T00:00:00+00:00",
            },
        )
    )
    assert executor.sql.startswith("SELECT")
    assert "DROP" not in executor.sql
    assert snapshot.observations[0].change_pct == 20.0
    assert snapshot.metadata["query_fingerprint"]


class FakeExecutor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    async def execute(self, sql, parameters):
        self.sql = sql
        assert parameters["window_start"].startswith("2026-01")
        return self.rows


class CatalogAdapter:
    name = "trino"

    def __init__(self, resources):
        self.resources = resources

    async def list_resources(self):
        return self.resources

    async def inspect(self, source):
        raise AssertionError(f"query tests should not execute source: {source.resource}")

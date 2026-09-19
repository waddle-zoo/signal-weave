import pytest

from signalweave.models import (
    CatalogSearchPage,
    Observation,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.sources import SourceRegistry
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_models import SupersetChartSnapshot, SupersetDashboardSnapshot


class FakeAdapter:
    name = "sql"

    async def list_resources(self):
        return []

    async def inspect(self, source):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=source.label,
        )


class BrokenCatalogAdapter:
    name = "broken"

    async def list_resources(self):
        raise TimeoutError("catalog timeout")

    async def inspect(self, source):
        del source
        raise AssertionError("inspect must not run after catalog failure")


class TenantCatalogAdapter:
    name = "superset"

    async def list_resources(self):
        return [
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:allowed",
                kind="dashboard",
                title="Allowed dashboard",
                contract=ResourceContract(tenant_id="tenant-a"),
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:other-tenant",
                kind="dashboard",
                title="Other tenant dashboard",
                contract=ResourceContract(tenant_id="tenant-b"),
            ),
        ]

    async def inspect(self, source):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=source.label,
        )


class BoundedSearchAdapter:
    name = "catalog"

    async def list_resources(self):
        raise AssertionError("bounded search must not materialize the full catalog")

    async def search_resources(self, query, *, limit, cursor=None):
        assert query == "revenue movement"
        assert limit == 3
        assert cursor is None
        return CatalogSearchPage(
            resources=[
                ResourceDescriptor(
                    adapter=self.name,
                    resource="dashboard:revenue",
                    kind="dashboard",
                    title="Revenue movement",
                )
            ],
            total_count=100_000,
            has_more=True,
            next_cursor="page-2",
            provider="catalog-index",
            strategy="server-search",
        )

    async def inspect(self, source):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=source.label,
        )


@pytest.mark.asyncio
async def test_source_registry_resolves_multiple_adapter_refs():
    registry = SourceRegistry([FakeAdapter()])
    sources = [
        SourceRef(key="orders", adapter="sql", resource="query:orders", label="Orders"),
        SourceRef(key="quality", adapter="sql", resource="query:quality", label="Quality"),
    ]

    snapshots = await registry.resolve(sources)

    assert [snapshot.source_key for snapshot in snapshots] == ["orders", "quality"]
    assert registry.adapter_names() == ["sql"]


@pytest.mark.asyncio
async def test_source_registry_turns_adapter_failures_into_snapshots():
    registry = SourceRegistry([])
    source = SourceRef(
        key="airflow-load",
        adapter="airflow",
        resource="dag:warehouse-load",
        label="Warehouse load",
    )

    snapshots = await registry.resolve([source])

    assert snapshots[0].source_key == "airflow-load"
    assert "not installed" in snapshots[0].error


@pytest.mark.asyncio
async def test_source_registry_isolates_unrelated_catalog_outages():
    registry = SourceRegistry(
        [FakeAdapter(), BrokenCatalogAdapter()], enforce_catalog=False
    )
    sources = [
        SourceRef(key="healthy", adapter="sql", resource="query:orders", label="Orders"),
        SourceRef(key="broken", adapter="broken", resource="query:catalog", label="Broken"),
    ]

    snapshots = await registry.resolve(sources)

    assert snapshots[0].error is None
    assert "catalog unavailable" in snapshots[1].error


@pytest.mark.asyncio
async def test_source_registry_blocks_direct_inspection_outside_authorized_catalog():
    registry = SourceRegistry(
        [TenantCatalogAdapter()],
        authorized_tenants={"tenant-a"},
    )
    source = SourceRef(
        key="other-tenant",
        adapter="superset",
        resource="dashboard:other-tenant",
        label="Other tenant dashboard",
    )

    snapshot = await registry.inspect(source)

    assert snapshot.error == (
        "source is not present in the authorized adapter catalog; rediscover it before inspection"
    )


@pytest.mark.asyncio
async def test_source_registry_preserves_bounded_search_coverage_without_full_scan():
    registry = SourceRegistry([BoundedSearchAdapter()])

    page = await registry.search_resources("revenue movement", limit=3)

    assert [resource.resource for resource in page.resources] == ["dashboard:revenue"]
    assert page.total_count == 100_000
    assert page.has_more is True
    assert page.next_cursor == "page-2"
    assert page.strategy == "server-search"


class FakeSupersetClient:
    async def list_dashboards(self):
        return [{"id": 7, "dashboard_title": "Revenue", "owners": [{"username": "alice"}]}]

    async def dashboard_snapshot(self, dashboard_id, include_data=True, chart_ids=None):
        del include_data, chart_ids
        return SupersetDashboardSnapshot(
            id=str(dashboard_id),
            title="Revenue",
            owners=["alice"],
            source_url="https://superset.example/dashboard/7",
            charts=[
                SupersetChartSnapshot(
                    id="62",
                    title="Revenue by region",
                    metric="SUM(revenue)",
                    related_chart_ids=["64"],
                    observations=[
                        Observation(
                            source_key="old-key",
                            subject_id="62",
                            subject_label="Revenue by region",
                            subject_type="superset_chart",
                            metric="SUM(revenue)",
                            current=120,
                            baseline=100,
                            change_pct=20,
                        )
                    ],
                )
            ],
        )


@pytest.mark.asyncio
async def test_superset_adapter_uses_server_paged_catalog_search():
    class PaginatedClient(FakeSupersetClient):
        async def list_dashboards_page(self, *, page, page_size, query):
            assert page == 0
            assert page_size == 5
            assert query == "revenue movement"
            return ([{"id": 7, "dashboard_title": "Revenue movement"}], 100_000)

    page = await SupersetAdapter(PaginatedClient()).search_resources(
        "revenue movement", limit=5
    )

    assert page.resources[0].resource == "dashboard:7"
    assert page.total_count == 100_000
    assert page.has_more is True
    assert page.next_cursor == "1"
    assert page.strategy == "superset-server-filter"


@pytest.mark.asyncio
async def test_superset_adapter_preserves_dashboard_chart_context():
    adapter = SupersetAdapter(FakeSupersetClient())
    source = SourceRef(
        key="revenue-dashboard",
        adapter="superset",
        resource="dashboard:7",
        label="Revenue dashboard",
        parameters={"chart_ids": ["62"]},
    )

    snapshot = await adapter.inspect(source)

    assert snapshot.source_key == "revenue-dashboard"
    assert snapshot.observations[0].source_key == "revenue-dashboard"
    assert snapshot.metadata["owners"] == ["alice"]
    assert snapshot.metadata["charts"][0]["related_chart_ids"] == ["64"]
    assert snapshot.evidence[0].values["metric"] == "SUM(revenue)"


def test_source_registry_rejects_duplicate_adapter_registration():
    with pytest.raises(ValueError, match="already registered"):
        SourceRegistry([FakeAdapter(), FakeAdapter()])

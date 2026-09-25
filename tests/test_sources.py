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


class NativeAuthorizeAdapter(BoundedSearchAdapter):
    name = "native"

    def __init__(self):
        self.authorize_called = 0
        self.inspect_called = 0

    async def authorize(self, source, *, authorized_tenants=None):
        del authorized_tenants
        self.authorize_called += 1
        if source.resource != "dashboard:revenue":
            return None
        return ResourceDescriptor(
            adapter=self.name,
            resource=source.resource,
            kind="dashboard",
            title="Revenue movement",
            contract=ResourceContract(tenant_id="tenant-a"),
        )

    async def inspect(self, source):
        self.inspect_called += 1
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=source.label,
            observations=[
                Observation(
                    source_key=source.key,
                    subject_id="revenue",
                    subject_label="Revenue",
                    metric="revenue",
                    current=110,
                    baseline=100,
                    change_pct=10,
                )
            ],
        )


class LocalScanAdapter:
    name = "local"

    async def list_resources(self):
        return [
            ResourceDescriptor(
                adapter=self.name,
                resource=f"query:{index}",
                kind="query",
                title=title,
            )
            for index, title in enumerate(
                ["Unrelated one", "Revenue movement", "Unrelated two", "Revenue quality"]
            )
        ]

    async def inspect(self, source):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=source.label,
        )


class LargeLocalScanAdapter(LocalScanAdapter):
    name = "large-local"

    async def list_resources(self):
        resources = [
            ResourceDescriptor(
                adapter=self.name,
                resource="query:revenue-movement",
                kind="query",
                title="Revenue movement",
            )
        ]
        resources.extend(
            ResourceDescriptor(
                adapter=self.name,
                resource=f"query:unrelated-{index}",
                kind="query",
                title=f"Unrelated {index}",
            )
            for index in range(599)
        )
        return resources


class OversizedSnapshotAdapter:
    name = "oversized"

    async def list_resources(self):
        return [
            ResourceDescriptor(
                adapter=self.name,
                resource="payload:large",
                kind="payload",
                title="Large payload",
            )
        ]

    async def inspect(self, source):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=source.label,
            observations=[
                Observation(
                    source_key=source.key,
                    subject_id="metric",
                    subject_label="Metric",
                    metric="metric",
                    current=2,
                    baseline=1,
                    change_pct=100,
                )
            ],
            metadata={"large_field": "x" * 10_000},
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


@pytest.mark.asyncio
async def test_source_registry_redacts_unscoped_native_catalog_counts():
    class UnscopedTenantSearch:
        name = "unscoped"

        async def list_resources(self):
            raise AssertionError("tenant-scoped search must not materialize the catalog")

        async def search_resources(self, query, *, limit, cursor=None):
            del query, limit, cursor
            return CatalogSearchPage(
                resources=[
                    ResourceDescriptor(
                        adapter=self.name,
                        resource="dashboard:visible",
                        kind="dashboard",
                        title="Visible dashboard",
                        contract=ResourceContract(tenant_id="tenant-a"),
                    ),
                    ResourceDescriptor(
                        adapter=self.name,
                        resource="dashboard:foreign",
                        kind="dashboard",
                        title="Foreign dashboard",
                        contract=ResourceContract(tenant_id="tenant-b"),
                    ),
                ],
                total_count=100_000,
                has_more=True,
                provider="unscoped-index",
                strategy="server-search",
            )

    registry = SourceRegistry([UnscopedTenantSearch()], authorized_tenants={"tenant-a"})

    page = await registry.search_resources("dashboard", limit=10)

    assert [resource.resource for resource in page.resources] == ["dashboard:visible"]
    assert page.total_count == 1
    assert page.has_more is True
    assert any("catalog count was redacted" in warning for warning in page.warnings)


@pytest.mark.asyncio
async def test_source_registry_inspects_native_search_result_without_full_catalog_scan():
    adapter = NativeAuthorizeAdapter()
    registry = SourceRegistry([adapter], authorized_tenants={"tenant-a"})
    source = SourceRef(
        key="revenue",
        adapter="native",
        resource="dashboard:revenue",
        label="Revenue movement",
    )

    snapshot = await registry.inspect(source)

    assert snapshot.error is None
    assert adapter.authorize_called == 1
    assert adapter.inspect_called == 1


@pytest.mark.asyncio
async def test_source_registry_bounds_local_scan_and_preserves_multiple_adapters():
    class OtherLocalAdapter(LocalScanAdapter):
        name = "other"

        async def list_resources(self):
            resources = await super().list_resources()
            return [resource.model_copy(update={"adapter": self.name}) for resource in resources]

    registry = SourceRegistry([LocalScanAdapter(), OtherLocalAdapter()])

    page = await registry.search_resources("revenue movement", limit=4)

    assert len(page.resources) == 4
    assert {resource.adapter for resource in page.resources} == {"local", "other"}
    assert all("Revenue" in resource.title for resource in page.resources)
    assert page.total_count == 8
    assert page.has_more is True
    assert any("locally scanned" in warning for warning in page.warnings)


@pytest.mark.asyncio
async def test_source_registry_does_not_overflow_bounded_catalog_page():
    registry = SourceRegistry([LargeLocalScanAdapter()])

    page = await registry.search_resources("revenue movement", limit=5)

    assert len(page.resources) == 5
    assert page.resources[0].resource == "query:revenue-movement"
    assert page.total_count == 600
    assert page.has_more is True


@pytest.mark.asyncio
async def test_source_registry_fails_closed_on_oversized_snapshot_payload():
    registry = SourceRegistry([OversizedSnapshotAdapter()], max_snapshot_bytes=1_024)
    source = SourceRef(
        key="large", adapter="oversized", resource="payload:large", label="Large payload"
    )

    snapshot = await registry.inspect(source)

    assert snapshot.observations == []
    assert snapshot.evidence == []
    assert "payload budget" in snapshot.error
    budget = snapshot.metadata["signalweave_budget"]
    assert budget["status"] == "exceeded"
    assert budget["max_snapshot_bytes"] == 1_024
    assert budget["observed_snapshot_bytes"] > budget["max_snapshot_bytes"]


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
async def test_superset_adapter_recovers_natural_language_title_search():
    class NaturalLanguageClient:
        async def list_dashboards_page(self, *, page, page_size, query):
            del page, page_size
            if query == "executive":
                return ([{"id": 7, "dashboard_title": "Executive Command Center"}], 1)
            return ([], 0)

    page = await SupersetAdapter(NaturalLanguageClient()).search_resources(
        "what changed on the executive command center", limit=5
    )

    assert [resource.resource for resource in page.resources] == ["dashboard:7"]
    assert page.strategy == "superset-server-filter-term-fallback"
    assert "bounded title-term fallback" in page.warnings[0]


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

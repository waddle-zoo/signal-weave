import pytest

from semantic_monitor.models import (
    Observation,
    ResourceSnapshot,
    SourceRef,
)
from semantic_monitor.sources import SourceRegistry
from semantic_monitor.superset_adapter import SupersetAdapter
from semantic_monitor.superset_models import SupersetChartSnapshot, SupersetDashboardSnapshot


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

import os

import pytest

from signalweave.models import SourceRef
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SUPERSET_INTEGRATION") != "1",
    reason="set RUN_SUPERSET_INTEGRATION=1 to exercise a live local Superset",
)


@pytest.mark.asyncio
async def test_local_superset_dashboard_data_round_trip():
    client = SupersetClient(
        base_url=os.getenv("SUPERSET_URL", "http://127.0.0.1:8088"),
        username=os.getenv("SUPERSET_USERNAME", "admin"),
        password=os.getenv("SUPERSET_PASSWORD", "admin"),
    )

    assert await client.health()
    dashboards = await client.list_dashboards()
    assert any(item.get("dashboard_title") == "Sales Dashboard" for item in dashboards)

    snapshot = await client.dashboard_snapshot(7)
    assert snapshot.title == "Sales Dashboard"
    assert len(snapshot.charts) >= 5
    assert any(chart.observations for chart in snapshot.charts)

    timeseries = await client.dashboard_snapshot(7, chart_ids=["64"])
    assert timeseries.charts[0].observations[0].baseline is not None

    card_source = SourceRef(
        key="sales-dashboard",
        adapter="superset",
        resource="dashboard:7",
        label="Sales dashboard",
        parameters={"chart_ids": ["64"]},
    )
    resource = await SupersetAdapter(client).inspect(card_source)
    assert resource.source_key == "sales-dashboard"
    assert resource.metadata["provider"] == "superset"
    assert resource.observations[0].baseline is not None


@pytest.mark.asyncio
async def test_local_superset_chart_matrix_has_no_silent_loss():
    client = SupersetClient(
        base_url=os.getenv("SUPERSET_URL", "http://127.0.0.1:8088"),
        username=os.getenv("SUPERSET_USERNAME", "admin"),
        password=os.getenv("SUPERSET_PASSWORD", "admin"),
    )

    dashboards = await client.list_dashboards()
    snapshots = [
        await client.dashboard_snapshot(dashboard["id"])
        for dashboard in dashboards
        if dashboard.get("id") is not None
    ]
    charts = [chart for snapshot in snapshots for chart in snapshot.charts]

    assert charts
    assert all(
        chart.semantic_status
        in {"extracted", "partial", "unsupported", "metadata_only", "no_data"}
        for chart in charts
    )
    assert all(chart.observations or chart.semantic_notes or chart.error for chart in charts)
    assert all(
        not chart.observations
        or chart.metrics
        and {observation.metric for observation in chart.observations} <= set(chart.metrics)
        for chart in charts
    )

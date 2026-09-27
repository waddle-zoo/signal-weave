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

    # Do not bind the integration proof to the IDs or titles of the bundled
    # Superset examples.  Imports, fixture versions, and real customer
    # workspaces all assign different IDs and names.  Select the first
    # dashboard that actually exposes a populated saved chart instead.
    snapshots = [
        await client.dashboard_snapshot(item["id"])
        for item in dashboards
        if item.get("id") is not None
    ]
    snapshot = next(
        (
            candidate
            for candidate in snapshots
            if len(candidate.charts) >= 1
            and any(chart.observations for chart in candidate.charts)
        ),
        None,
    )
    assert snapshot is not None, "fixture has no dashboard with populated chart data"
    assert snapshot.charts

    chart_with_observations = next(
        (
            chart
            for chart in snapshot.charts
            if chart.observations
        ),
        None,
    )
    assert chart_with_observations is not None, "fixture has no chart with observations"

    timeseries = await client.dashboard_snapshot(
        snapshot.id, chart_ids=[chart_with_observations.id]
    )
    assert timeseries.charts[0].observations
    assert timeseries.charts[0].metrics

    card_source = SourceRef(
        key="integration-dashboard",
        adapter="superset",
        resource=f"dashboard:{snapshot.id}",
        label=snapshot.title,
        parameters={"chart_ids": [chart_with_observations.id]},
    )
    resource = await SupersetAdapter(client).inspect(card_source)
    assert resource.source_key == "integration-dashboard"
    assert resource.metadata["provider"] == "superset"
    assert resource.observations
    assert {observation.metric for observation in resource.observations} <= set(
        timeseries.charts[0].metrics
    )


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

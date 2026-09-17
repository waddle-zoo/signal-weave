import os

import pytest

from semantic_monitor.superset_client import SupersetClient

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

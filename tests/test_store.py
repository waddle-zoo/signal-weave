import json

from semantic_monitor.models import MonitorCard
from semantic_monitor.store import JsonMonitorStore


def test_monitor_store_writes_valid_catalog_atomically(tmp_path):
    path = tmp_path / "monitors.json"
    store = JsonMonitorStore(path)
    card = MonitorCard(
        id="monitor-1",
        dashboard_id="dashboard-1",
        title="Sales pulse",
        intent="Notify when sales move materially.",
    )

    store.save(card)

    assert json.loads(path.read_text())["monitor-1"]["title"] == "Sales pulse"
    assert list(tmp_path.glob("*.tmp")) == []

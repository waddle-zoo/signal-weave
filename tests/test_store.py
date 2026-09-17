import json

from semantic_monitor.models import MonitorWorkflow, SourceRef
from semantic_monitor.store import JsonWorkflowStore


def test_monitor_store_writes_valid_catalog_atomically(tmp_path):
    path = tmp_path / "monitors.json"
    store = JsonWorkflowStore(path)
    workflow = MonitorWorkflow(
        id="monitor-1",
        title="Sales pulse",
        intent="Notify when sales move materially.",
        sources=[
            SourceRef(
                key="sales",
                adapter="superset",
                resource="dashboard:1",
                label="Sales dashboard",
            )
        ],
    )

    store.save_workflow(workflow)

    assert json.loads(path.read_text())["monitor-1"]["title"] == "Sales pulse"
    assert list(tmp_path.glob("*.tmp")) == []

import pytest

from signalweave.models import (
    Evidence,
    Observation,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.sources import SourceRegistry


class ArtifactAdapter:
    """Small connector double: the core only sees the adapter contract."""

    def __init__(self, name, resources, snapshots):
        self.name = name
        self._resources = resources
        self._snapshots = snapshots

    async def list_resources(self):
        return self._resources

    async def inspect(self, source):
        return self._snapshots[source.resource].model_copy(
            update={"source_key": source.key}
        )


@pytest.mark.asyncio
async def test_monitor_can_combine_looker_and_hex_artifacts_without_vendor_logic():
    looker_source = ResourceDescriptor(
        adapter="looker",
        resource="dashboard:executive-growth",
        kind="dashboard",
        title="Executive growth",
        metadata={"artifact_system": "looker", "contains": ["saved_query"]},
    )
    hex_source = ResourceDescriptor(
        adapter="hex",
        resource="project:retention-investigation",
        kind="notebook",
        title="Retention investigation",
        metadata={"artifact_system": "hex", "contains": ["sql_cell", "chart"]},
    )
    looker_snapshot = ResourceSnapshot(
        source_key="unused",
        adapter="looker",
        resource=looker_source.resource,
        title=looker_source.title,
        observations=[
            Observation(
                subject_id="activation-rate",
                subject_label="Activation rate",
                subject_type="chart",
                metric="activation_rate",
                current=0.42,
                baseline=0.51,
                change_pct=-17.65,
            )
        ],
        evidence=[
            Evidence(
                subject_id="owner",
                subject_label="Dashboard owner",
                statement="Growth owns the dashboard.",
                values={"team": "growth"},
            )
        ],
    )
    hex_snapshot = ResourceSnapshot(
        source_key="unused",
        adapter="hex",
        resource=hex_source.resource,
        title=hex_source.title,
        observations=[
            Observation(
                subject_id="activation-driver",
                subject_label="Activation investigation",
                subject_type="notebook_result",
                metric="payment_error_rate",
                current=0.18,
                baseline=0.06,
                change_pct=200.0,
            )
        ],
        evidence=[
            Evidence(
                subject_id="run",
                subject_label="Notebook run",
                statement="The latest published project run completed successfully.",
                values={"run_status": "completed"},
            )
        ],
    )
    registry = SourceRegistry(
        [
            ArtifactAdapter("looker", [looker_source], {looker_source.resource: looker_snapshot}),
            ArtifactAdapter("hex", [hex_source], {hex_source.resource: hex_snapshot}),
        ]
    )

    snapshots = await registry.resolve(
        [
            SourceRef(
                key="growth-dashboard",
                adapter="looker",
                resource=looker_source.resource,
                label=looker_source.title,
            ),
            SourceRef(
                key="retention-notebook",
                adapter="hex",
                resource=hex_source.resource,
                label=hex_source.title,
            ),
        ]
    )

    assert [snapshot.adapter for snapshot in snapshots] == ["looker", "hex"]
    assert {item.metric for snapshot in snapshots for item in snapshot.observations} == {
        "activation_rate",
        "payment_error_rate",
    }
    assert all(snapshot.error is None for snapshot in snapshots)

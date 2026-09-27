import asyncio
import json

import httpx

from evaluations.preset_generalization_trial import (
    GeneratedWorkspaceTransport,
    _workspaces,
    run_trial,
)
from signalweave.hosted import HostedDataPolicy
from signalweave.models import SourceRef
from signalweave.preset_adapter import PresetAdapter, PresetCloudClient


def test_generated_preset_shapes_do_not_depend_on_named_fixture_values():
    report = run_trial(seed=17, workspace_count=4, charts_per_workspace=8)

    assert report["passed"] is True
    assert report["chart_count"] == 32
    assert set(report["case_coverage"]) == {
        "ambiguous_numeric",
        "dict_metric",
        "empty",
        "explicit",
        "implicit_count",
        "missing_metric",
        "non_numeric_metric",
        "provider_error",
    }
    assert set(report["envelope_coverage"]) == {
        "columnar",
        "data",
        "records",
        "rows",
        "values",
    }
    assert len(report["viz_type_coverage"]) >= 10
    assert "vendor_extension" in report["viz_type_coverage"]
    assert {
        "all_columns",
        "dict_metric",
        "dimension_count",
        "metrics",
        "spatial_count",
        "visual_measures",
    }.issubset(set(report["param_variant_coverage"]))


def test_generated_large_dashboard_fails_closed_before_partial_jev_state():
    workspace = _workspaces(seed=91, workspace_count=1, charts_per_workspace=64)[0]
    snapshot_budget = 32_768

    async def inspect():
        client = PresetCloudClient(
            f"https://{workspace['id']}.preset.generated",
            access_token="generated-token",
            transport=httpx.MockTransport(GeneratedWorkspaceTransport(workspace)),
        )
        adapter = PresetAdapter(
            client,
            tenant_id=workspace["tenant_id"],
            policy=HostedDataPolicy(
                max_result_rows=100, max_snapshot_bytes=snapshot_budget
            ),
            adapter_name=f"preset__{workspace['id']}",
        )
        return await adapter.inspect(
            SourceRef(
                key="generated-large-dashboard",
                adapter=adapter.name,
                resource=f"dashboard:{workspace['dashboard_id']}",
                label=workspace["dashboard_title"],
            )
        )

    snapshot = asyncio.run(inspect())
    quality = snapshot.metadata["data_quality"]
    serialized_size = len(
        json.dumps(
            snapshot.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    )

    assert quality["status"] == "failed"
    assert quality["reason"] == "dashboard_snapshot_bytes_exceeded"
    assert quality["chart_count"] == 64
    assert quality["snapshot_bytes"] > quality["max_snapshot_bytes"]
    assert quality["max_snapshot_bytes"] == snapshot_budget
    assert snapshot.observations == []
    assert snapshot.evidence == []
    assert serialized_size <= quality["max_snapshot_bytes"]

"""SourceRef parameters must be executed or rejected, never merely echoed."""

import re
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from signalweave.models import InsightCard, SourceRef
from signalweave.preset_adapter import PresetAdapter
from signalweave.sources import SourceParameterError, SourceRegistry
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient
from tests.test_onboarding import make_server, tool
from tests.test_sources import FakeSupersetClient

UNSUPPORTED_PARAMETER = r"Unsupported.*source parameter"
BACKEND_READS = (
    "list_dashboards",
    "get_dashboard_metadata",
    "get_chart_metadata",
    "dashboard_snapshot",
    "chart_data",
)


@pytest.fixture
def client():
    dashboard_client = FakeSupersetClient()
    return SimpleNamespace(
        list_dashboards=AsyncMock(wraps=dashboard_client.list_dashboards),
        get_dashboard_metadata=AsyncMock(
            return_value={"id": 7, "dashboard_title": "Revenue", "tenant_id": "default"}
        ),
        dashboard_snapshot=AsyncMock(wraps=dashboard_client.dashboard_snapshot),
        get_chart_metadata=AsyncMock(
            return_value={
                "id": 62,
                "slice_name": "Revenue",
                "viz_type": "table",
                "params": {
                    "metrics": [{"label": "Revenue"}],
                    "granularity_sqla": "period",
                    "time_range": "Last month",
                    "adhoc_filters": [{"subject": "region", "comparator": "west"}],
                },
            }
        ),
        chart_data=AsyncMock(
            return_value=[{"data": [{"period": 1, "Revenue": 100}, {"period": 2, "Revenue": 120}]}]
        ),
        extract_chart_data=SupersetClient.extract_chart_data,
        constrain_response_limits=Mock(),
        set_query_mode=Mock(),
    )


@pytest.fixture(params=[SupersetAdapter, PresetAdapter], ids=["superset", "preset"])
def adapter(request, client):
    return request.param(client, tenant_id="default")


def source(adapter, resource, parameters):
    return SourceRef(
        key="revenue",
        adapter=adapter.name,
        resource=resource,
        label="Revenue",
        parameters=deepcopy(parameters),
    )


def assert_no_backend_reads(client):
    for name in BACKEND_READS:
        getattr(client, name).assert_not_awaited()


@pytest.mark.parametrize("entrypoint", ["inspect", "authorize"])
@pytest.mark.parametrize(
    "parameters",
    [
        {"time_range": "Last week"},
        {"filter": {"region": "west"}},
        {"filters": [{"col": "region", "op": "==", "val": "west"}]},
        {"chart_ids": ["62"]},
    ],
)
async def test_chart_rejects_unsupported_parameters_before_backend_reads(
    adapter, client, entrypoint, parameters
):
    ref = source(adapter, "chart:62", parameters)
    with pytest.raises(SourceParameterError, match=UNSUPPORTED_PARAMETER):
        await getattr(adapter, entrypoint)(ref)
    assert ref.parameters == parameters
    assert_no_backend_reads(client)


@pytest.mark.parametrize("entrypoint", ["inspect", "authorize"])
@pytest.mark.parametrize(
    "parameters",
    [
        {"time_range": "Last week"},
        {"filters": [{"col": "region", "op": "==", "val": "west"}]},
        {"chart_ids": ["62"], "time_range": "Last week"},
        {"chart_ids": ["62"], "filter": {"region": "west"}},
    ],
)
async def test_dashboard_rejects_unknown_and_mixed_parameters_entirely(
    adapter, client, entrypoint, parameters
):
    ref = source(adapter, "dashboard:7", parameters)
    with pytest.raises(SourceParameterError, match=UNSUPPORTED_PARAMETER):
        await getattr(adapter, entrypoint)(ref)
    assert ref.parameters == parameters
    assert_no_backend_reads(client)


async def test_empty_chart_parameters_preserve_saved_filters_and_actual_observations(adapter, client):
    ref = source(adapter, "chart:62", {})
    saved_chart = deepcopy(client.get_chart_metadata.return_value)

    descriptor = await adapter.authorize(ref)
    snapshot = await adapter.inspect(ref)

    assert descriptor.resource == ref.resource
    assert snapshot.error is None
    assert snapshot.adapter == adapter.name
    assert snapshot.source_key == ref.key
    assert snapshot.observations[0].current == 120
    assert snapshot.observations[0].baseline == 100
    assert snapshot.observations[0].source_key == ref.key
    assert snapshot.evidence[0].subject_id == "62"
    assert snapshot.metadata["parameters"] == {}
    client.chart_data.assert_awaited_once_with(saved_chart)
    assert client.get_chart_metadata.return_value == saved_chart
    client.dashboard_snapshot.assert_not_awaited()


@pytest.mark.parametrize("parameters", [{}, {"chart_ids": ["62"]}])
async def test_dashboard_documented_parameters_reach_backend_and_preserve_snapshot(
    adapter, client, parameters
):
    ref = source(adapter, "dashboard:7", parameters)

    descriptor = await adapter.authorize(ref)
    snapshot = await adapter.inspect(ref)

    assert descriptor.resource == ref.resource
    assert snapshot.error is None
    assert snapshot.adapter == adapter.name
    assert snapshot.source_key == ref.key
    assert snapshot.observations[0].current == 120
    assert snapshot.observations[0].baseline == 100
    assert snapshot.observations[0].source_key == ref.key
    assert snapshot.evidence[0].subject_id == "62"
    assert snapshot.metadata["parameters"] == parameters
    assert snapshot.metadata["owners"] == ["alice"]
    client.dashboard_snapshot.assert_awaited_once_with(
        "7", include_data=True, chart_ids=parameters.get("chart_ids")
    )
    client.chart_data.assert_not_awaited()


@pytest.mark.parametrize("resource", ["chart:62", "dashboard:7"])
async def test_registry_resolution_retains_parameter_error_without_measurements(
    adapter, client, resource
):
    ref = source(adapter, resource, {"time_range": "Last week"})
    registry = SourceRegistry([adapter], authorized_tenants={"default"})

    snapshots = await registry.resolve([ref])

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.source_key == ref.key
    assert snapshot.adapter == ref.adapter
    assert snapshot.resource == ref.resource
    assert snapshot.error is not None
    assert re.search(UNSUPPORTED_PARAMETER, snapshot.error)
    assert snapshot.observations == []
    assert snapshot.evidence == []
    assert snapshot.analytical_comparisons == []
    assert_no_backend_reads(client)


async def test_onboarding_cannot_accept_unsupported_source_parameters(adapter, client, tmp_path):
    server = make_server(tmp_path, catalog=adapter)
    with pytest.raises(SourceParameterError, match=UNSUPPORTED_PARAMETER) as error:
        await tool(server, "onboard_insight_card")(
            title="Revenue",
            what_to_watch="Revenue in the requested period",
            why_watch="Support the owner's review",
            selected_sources=[
                {"ref": f"{adapter.name}|chart:62", "parameters": {"time_range": "Last week"}}
            ],
        )
    assert "time_range" in str(error.value)
    assert "authorized adapter catalog" not in str(error.value)
    assert not isinstance(error.value, PermissionError)
    assert_no_backend_reads(client)


async def test_existing_card_review_rejects_unsupported_parameters_without_rewriting_them(
    adapter, client, tmp_path
):
    server = make_server(tmp_path, catalog=adapter)
    store = server._test_runtime.card_store
    card = InsightCard(
        id="saved-revenue",
        title="Revenue",
        what_to_watch="Revenue in the requested period",
        why_watch="Support the owner's review",
        sources=[source(adapter, "chart:62", {"time_range": "Last week"})],
        principal_id="test-principal",
        principal_tenant="default",
    )
    store.save_card(card)
    original = store.get_card(card.id).model_dump(mode="json")

    with pytest.raises(SourceParameterError, match=UNSUPPORTED_PARAMETER) as error:
        await tool(server, "review_insight_card")(card.id)

    assert "time_range" in str(error.value)
    assert "authorized adapter catalog" not in str(error.value)
    assert not isinstance(error.value, PermissionError)
    assert store.get_card(card.id).model_dump(mode="json") == original
    assert_no_backend_reads(client)


@pytest.mark.parametrize("operation", ["onboard_insight_card", "review_insight_card"])
async def test_unauthorized_sources_keep_catalog_errors_distinct_from_parameter_errors(
    adapter, client, tmp_path, operation
):
    adapter.tenant_id = "other-tenant"
    server = make_server(tmp_path, catalog=adapter)
    if operation == "review_insight_card":
        card = InsightCard(
            id="unauthorized-revenue",
            title="Revenue",
            what_to_watch="Revenue",
            why_watch="Support the owner's review",
            sources=[source(adapter, "chart:62", {})],
            principal_id="test-principal",
            principal_tenant="default",
        )
        server._test_runtime.card_store.save_card(card)
        arguments = {"card_id": card.id}
    else:
        arguments = {
            "title": "Revenue",
            "what_to_watch": "Revenue",
            "why_watch": "Support the owner's review",
            "selected_sources": [{"ref": f"{adapter.name}|chart:62"}],
        }

    with pytest.raises(ValueError, match="authorized adapter catalog") as error:
        await tool(server, operation)(**arguments)

    assert not isinstance(error.value, SourceParameterError)
    assert re.search(UNSUPPORTED_PARAMETER, str(error.value)) is None
    assert_no_backend_reads(client)

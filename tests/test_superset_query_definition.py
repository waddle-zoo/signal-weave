from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from signalweave.models import Observation, SourceRef
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient
from signalweave.superset_models import SupersetChartSnapshot, SupersetDashboardSnapshot


class DirectChartClient(SupersetClient):
    def __init__(self, chart: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        super().__init__("https://superset.invalid")
        self.chart = chart
        self.rows = rows

    async def get_chart_metadata(self, chart_id: int | str) -> dict[str, Any]:
        assert str(self.chart["id"]) == str(chart_id)
        return self.chart

    async def chart_data(self, chart: dict[str, Any]) -> list[dict[str, Any]]:
        assert chart is self.chart
        return [{"data": self.rows}]


class ChartWithParams(SupersetChartSnapshot):
    params: Any


class DashboardClient(SupersetClient):
    def __init__(self, snapshot: SupersetDashboardSnapshot) -> None:
        super().__init__("https://superset.invalid")
        self.snapshot = snapshot

    async def dashboard_snapshot(
        self,
        dashboard_id: int | str,
        include_data: bool = True,
        chart_ids: list[str] | None = None,
    ) -> SupersetDashboardSnapshot:
        assert str(self.snapshot.id) == str(dashboard_id)
        assert include_data is True
        assert chart_ids is None
        return self.snapshot

    async def get_chart_metadata(self, chart_id: int | str) -> dict[str, Any]:
        raise AssertionError(f"adapter must not fetch chart metadata: {chart_id}")


def _source(resource: str) -> SourceRef:
    return SourceRef(
        key="source",
        adapter="superset",
        resource=resource,
        label="Sales",
    )


@pytest.mark.asyncio
async def test_direct_chart_projects_only_saved_query_fields_and_preserves_source_values():
    params = {
        "metrics": [
            {
                "label": "Average net sales",
                "expression": "AVG(net_sales)",
                "aggregate": "AVG",
            }
        ],
        "groupby": ["region"],
        "granularity_sqla": "order_date",
        "time_grain_sqla": "P1M",
        "time_range": "Last 90 days",
        "adhoc_filters": [],
        "row_limit": 132,
        "all_columns": ["net_sales", "region"],
        "datasource": "17__table",
        "viz_type": "table",
        "password": "must-not-escape",
        "api_token": "also-must-not-escape",
    }
    original_params = copy.deepcopy(params)
    client = DirectChartClient(
        {"id": 10, "slice_name": "Net sales", "params": params},
        [{"Average net sales": 12.5, "region": "west"}],
    )

    snapshot = await SupersetAdapter(client).inspect(_source("chart:10"))

    saved = snapshot.metadata["saved_query_definition"]
    assert saved["status"] == "available"
    assert saved["source_chart_id"] == "10"
    assert saved["source_chart_ref"] == "chart:10"
    assert saved["parameters"] == {
        key: original_params[key]
        for key in (
            "metrics",
            "groupby",
            "granularity_sqla",
            "time_grain_sqla",
            "time_range",
            "adhoc_filters",
            "row_limit",
            "all_columns",
        )
    }
    assert saved["parameters"]["metrics"][0]["expression"] == "AVG(net_sales)"
    assert "datasource" not in saved["parameters"]
    assert "viz_type" not in saved["parameters"]
    assert "password" not in repr(saved)
    assert "api_token" not in repr(saved)
    assert snapshot.observations
    assert all(observation.metric != "SUM(net_sales)" for observation in snapshot.observations)

    saved["parameters"]["metrics"][0]["expression"] = "mutated"
    assert params == original_params


@pytest.mark.asyncio
async def test_direct_chart_parses_json_encoded_saved_params():
    client = DirectChartClient(
        {
            "id": 11,
            "slice_name": "Net sales",
            "params": '{"metrics":["SUM(net_sales)"],"groupby":[],"adhoc_filters":[]}',
        },
        [{"SUM(net_sales)": 25}],
    )

    snapshot = await SupersetAdapter(client).inspect(_source("chart:11"))

    assert snapshot.metadata["saved_query_definition"]["parameters"] == {
        "metrics": ["SUM(net_sales)"],
        "groupby": [],
        "adhoc_filters": [],
    }
    assert snapshot.observations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "reason"),
    [
        ("{not-json", "invalid_params"),
        (["metrics", "not a map"], "invalid_params"),
        ({"metrics": [object()]}, "invalid_definition"),
    ],
)
async def test_invalid_saved_params_are_marked_omitted_without_losing_observations(
    params: Any, reason: str
):
    client = DirectChartClient(
        {"id": 12, "slice_name": "Net sales", "params": params},
        [{"net_sales": 25}],
    )

    snapshot = await SupersetAdapter(client).inspect(_source("chart:12"))

    assert snapshot.metadata["saved_query_definition"] == {
        "source_chart_id": "12",
        "source_chart_ref": "chart:12",
        "audience": "agent",
        "status": "omitted",
        "reason": reason,
    }
    assert snapshot.observations


@pytest.mark.asyncio
async def test_oversized_utf8_definition_is_omitted_without_truncating_observations():
    client = DirectChartClient(
        {
            "id": 13,
            "slice_name": "Net sales",
            "params": {"metrics": ["net_sales"], "all_columns": ["é" * 5000]},
        },
        [{"net_sales": 25}],
    )

    snapshot = await SupersetAdapter(client).inspect(_source("chart:13"))

    assert snapshot.metadata["saved_query_definition"]["status"] == "omitted"
    assert snapshot.metadata["saved_query_definition"]["reason"] == "size_limit_exceeded"
    assert snapshot.metadata["saved_query_definition"]["source_chart_id"] == "13"
    assert snapshot.observations


@pytest.mark.asyncio
async def test_dashboard_projects_params_already_present_on_chart_snapshot():
    chart = ChartWithParams(
        id="14",
        title="Net sales",
        metric="net_sales",
        metrics=["net_sales"],
        params={"metrics": [{"expression": "AVG(net_sales)"}], "all_columns": ["region"]},
        observations=[
            Observation(
                source_key="superset-chart:14",
                subject_id="14:net_sales:0",
                subject_label="Net sales",
                subject_type="superset_chart",
                metric="net_sales",
                current=25,
            )
        ],
    )
    dashboard = SupersetDashboardSnapshot(
        id="7",
        title="Sales",
        charts=[chart],
    )
    snapshot = await SupersetAdapter(DashboardClient(dashboard)).inspect(
        _source("dashboard:7")
    )

    chart_metadata = snapshot.metadata["charts"][0]
    assert chart_metadata["metrics"] == ["net_sales"]
    assert chart_metadata["saved_query_definition"]["parameters"] == {
        "metrics": [{"expression": "AVG(net_sales)"}],
        "all_columns": ["region"],
    }
    assert "params" not in chart_metadata
    assert snapshot.observations


@pytest.mark.asyncio
async def test_dashboard_without_chart_params_does_not_fetch_them_or_mark_them_invented():
    chart = SupersetChartSnapshot(
        id="15",
        title="Net sales",
        metric="net_sales",
        metrics=["net_sales"],
        observations=[
            Observation(
                source_key="superset-chart:15",
                subject_id="15:net_sales:0",
                subject_label="Net sales",
                subject_type="superset_chart",
                metric="net_sales",
                current=25,
            )
        ],
    )
    dashboard = SupersetDashboardSnapshot(id="8", title="Sales", charts=[chart])
    snapshot = await SupersetAdapter(DashboardClient(dashboard)).inspect(
        _source("dashboard:8")
    )

    assert "saved_query_definition" not in snapshot.metadata["charts"][0]
    assert snapshot.metadata["charts"][0]["metrics"] == ["net_sales"]
    assert snapshot.observations


@pytest.mark.asyncio
async def test_real_client_dashboard_path_carries_definition_without_extra_requests():
    class Client(DirectChartClient):
        metadata_reads = 0
        query_calls = 0

        async def get_dashboard_metadata(self, dashboard_id):
            return {"id": 8}

        @staticmethod
        def metadata_to_snapshot(metadata):
            return SupersetDashboardSnapshot(id="8", title="Saved aggregate", charts=[
                SupersetChartSnapshot(id="42", title="Saved average", metric="unknown")])

        async def get_chart_metadata(self, chart_id):
            self.metadata_reads += 1
            return await super().get_chart_metadata(chart_id)

        async def chart_data(self, chart, **kwargs):
            self.query_calls += 1
            return await super().chart_data(chart)

    params = {"metrics": [{"expressionType": "SQL", "sqlExpression": "AVG(score)", "label": "Average score"}],
              "groupby": ["region"], "row_limit": 100}
    client = Client({"id": 42, "slice_name": "Saved average", "params": params},
                    [{"region": "North", "Average score": 8.5}])
    snapshot = await SupersetAdapter(client).inspect(_source("dashboard:8"))
    definition = snapshot.metadata["charts"][0]["saved_query_definition"]
    assert definition["parameters"] == params
    assert "dashboard filters" in definition["scope"]
    assert client.metadata_reads == 1 and client.query_calls == 1
    assert snapshot.observations[0].current == 8.5
    assert snapshot.contract.metric_definitions == []  # No business meaning is fabricated.


@pytest.mark.parametrize("kind", ["large_string", "deep_json", "deep_map", "cycle", "wide"])
def test_query_definition_input_guards_omit_without_escaping(kind):
    from signalweave.superset_client import _saved_query_definition
    if kind == "large_string":
        params = '{"metrics":["' + "x" * 70_000 + '"]}'
    elif kind == "deep_json":
        params = '{"metrics":' + "[" * 2000 + '"value"' + "]" * 2000 + "}"
    elif kind == "wide":
        params = {"metrics": list(range(5000))}
    else:
        values = []
        params = {"metrics": values}
        if kind == "cycle":
            values.append(values)
        else:
            for _ in range(50):
                child = []
                values.append(child)
                values = child
    definition = _saved_query_definition("42", params)
    assert definition["status"] == "omitted"
    assert definition["reason"] in {"input_size_limit_exceeded", "invalid_params", "structure_limit_exceeded"}


def test_recursive_params_failure_is_local_to_metadata_parsing(monkeypatch):
    def recursive_decoder(value):
        raise RecursionError("synthetic decoder recursion limit")
    monkeypatch.setattr("signalweave.superset_client.json.loads", recursive_decoder)
    assert SupersetClient._params({"params": "{}"}) == {}


def test_large_valid_params_keep_query_filters_even_when_agent_projection_is_omitted():
    from signalweave.superset_client import _saved_query_definition
    params = {"metrics": ["score"], "all_columns": ["score"],
              "time_range": "Last week", "adhoc_filters": [{"col": "region", "op": "==", "val": "west"}],
              "visualization_configuration": "x" * 70_000}
    encoded = json.dumps(params)
    assert SupersetClient._params({"params": encoded}) == params
    assert _saved_query_definition("42", encoded)["status"] == "omitted"


@pytest.mark.parametrize("params", [None, [], ["unsupported"], 42])
def test_non_mapping_params_do_not_raise_or_become_query_parameters(params):
    assert SupersetClient._params({"params": params}) == {}


def test_generic_params_depth_scanner_ignores_brackets_inside_strings():
    from signalweave.superset_client import SupersetClient

    params = json.dumps({"metrics": ["score"], "description": "[" * 2000 + "]" * 2000})

    assert SupersetClient._params({"params": params}) == {
        "metrics": ["score"],
        "description": "[" * 2000 + "]" * 2000,
    }


@pytest.mark.parametrize("kind", ["raw", "value", "key", "integer", "cumulative"])
def test_large_scalars_rejected_before_copying_or_full_encoding(kind):
    from signalweave.superset_client import _saved_query_definition

    class NoAllocationString(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("large string must be rejected before encoding")

        def __deepcopy__(self, memo):
            raise AssertionError("oversized declarations must not be copied")

    if kind == "raw":
        params = NoAllocationString("x" * 70_000)
    elif kind == "value":
        params = {"all_columns": [NoAllocationString("x" * 9000)]}
    elif kind == "key":
        params = {"metrics": [{NoAllocationString("x" * 9000): "value"}]}
    elif kind == "integer":
        params = {"row_limit": 1 << 100_000}
    else:
        params = {"all_columns": ["x" * 4000] * 3}
    assert _saved_query_definition("42", params)["status"] == "omitted"


async def test_recursive_params_do_not_fail_dashboard_or_discard_other_chart_facts():
    class Client(SupersetClient):
        async def get_dashboard_metadata(self, dashboard_id):
            return {"id": 8}

        @staticmethod
        def metadata_to_snapshot(metadata):
            return SupersetDashboardSnapshot(id="8", title="Mixed saved parameters", charts=[
                SupersetChartSnapshot(id=str(i), title=f"Chart {i}", metric="unknown") for i in (1, 2)])

        async def get_chart_metadata(self, chart_id):
            params = '{"metrics":' + "[" * 2000 + '"value"' + "]" * 2000 + "}"
            return {"id": chart_id, "params": params if str(chart_id) == "1" else {"metrics": ["score"]}}

        async def chart_data(self, chart, **kwargs):
            return [{"data": [{"score": 8.5}]}]

    snapshot = await SupersetAdapter(Client("https://superset.invalid")).inspect(_source("dashboard:8"))
    assert snapshot.error is None
    assert len(snapshot.observations) == 2
    assert snapshot.metadata["charts"][0]["saved_query_definition"]["status"] == "omitted"
    assert snapshot.metadata["charts"][0]["error"] is None
    assert snapshot.metadata["charts"][1]["saved_query_definition"]["status"] == "available"
    assert [observation.current for observation in snapshot.observations] == [8.5, 8.5]

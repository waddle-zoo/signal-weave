from __future__ import annotations

import copy
import math

import pytest

from evaluations.raw_superset_tools import RawSupersetTools
from signalweave.superset_client import SupersetClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return copy.deepcopy(self.payload)


class FakeSupersetClient:
    def __init__(self, metadata=None, envelopes=None):
        self.metadata = metadata or {}
        self.envelopes = envelopes or []
        self.requests_made = 0
        self.chart_data_calls = 0
        self.chart_data_arguments = []
        self.dashboard_page_arguments = []
        self.request_arguments = []
        self.dashboard_response = {"result": []}
        self.query_error = None

    async def list_dashboards_page(self, *, page, page_size, query):
        self.dashboard_page_arguments.append(
            {"page": page, "page_size": page_size, "query": query}
        )
        return (
            [
                {
                    "id": 7,
                    "dashboard_title": "Sales",
                    "description": "Saved dashboard",
                    "position_json": "private dashboard payload",
                }
            ],
            1,
        )

    async def _request(self, method, path, *, timeout, **kwargs):
        self.request_arguments.append((method, path, timeout, kwargs))
        self.requests_made += 1
        return FakeResponse(self.dashboard_response)

    async def get_chart_metadata(self, chart_id):
        self.requests_made += 1
        return copy.deepcopy(self.metadata)

    async def chart_data(self, chart, **kwargs):
        self.chart_data_calls += 1
        self.requests_made += 1
        self.chart_data_arguments.append((copy.deepcopy(chart), kwargs))
        if self.query_error:
            raise ValueError(self.query_error)
        return copy.deepcopy(self.envelopes)

    @staticmethod
    def _rows_from_result_item(result):
        return SupersetClient._rows_from_result_item(result)


@pytest.fixture
def saved_chart_data():
    metadata = {
        "id": 42,
        "slice_name": "Daily sales",
        "description": "Saved chart description",
        "viz_type": "table",
        "datasource_id": 17,
        "datasource_type": "table",
        "params": {
            "granularity_sqla": "period",
            "all_columns": ["period", "created_date", "revenue"],
            "row_limit": 500,
        },
        "query_context": {
            "queries": [
                {"columns": ["period", "revenue"], "row_limit": 3},
                {"columns": ["created_date", "revenue"], "row_limit": 4},
            ]
        },
    }
    envelopes = [
        {
            "query": "SELECT period, revenue FROM daily_sales ORDER BY period",
            "colnames": ["period", "revenue", "flag", "optional_numeric"],
            "data": [
                {
                    "period": "2026-01-02",
                    "revenue": 10,
                    "flag": True,
                    "optional_numeric": 2,
                },
                {
                    "period": "2026-01-01",
                    "revenue": 20,
                    "flag": False,
                    "optional_numeric": None,
                },
            ],
            "sql_rowcount": 80,
            "rowcount": 2,
        },
        {
            "query": "SELECT created_date, revenue FROM daily_sales_archive",
            "colnames": ["created_date", "revenue", "nullable", "unstable"],
            "data": [
                {"created_date": "2025-12-31", "revenue": 5, "nullable": None, "unstable": math.nan}
            ],
            "sql_rowcount": 100,
            "rowcount": 1,
        },
    ]
    return metadata, envelopes


@pytest.mark.asyncio
async def test_tool_specs_are_shared_bounded_and_do_not_accept_sql():
    tools = RawSupersetTools(FakeSupersetClient())

    specs = await tools.specs()

    assert [spec["name"] for spec in specs] == [
        "find_dashboards",
        "list_dashboard_charts",
        "read_chart_rows",
        "profile_saved_chart",
    ]
    assert all(spec["parameters"]["additionalProperties"] is False for spec in specs)
    assert all("sql" not in spec["parameters"]["properties"] for spec in specs)
    rows = specs[2]["parameters"]["properties"]
    assert rows["limit"]["maximum"] == 250
    assert rows["offset"]["default"] == 0
    assert specs[1]["parameters"]["properties"]["id"]["pattern"] == "^[1-9][0-9]*$"


@pytest.mark.asyncio
async def test_dashboard_search_and_chart_listing_return_only_requested_metadata():
    client = FakeSupersetClient()
    client.dashboard_response = {
        "result": [
            {
                "id": 42,
                "slice_name": "Daily sales",
                "description": "Saved chart",
                "all_chart_data": {"secret": "must not escape"},
            }
        ]
    }
    tools = RawSupersetTools(client)

    dashboards = await tools.call("find_dashboards", {"query": "revenue"})
    charts = await tools.call("list_dashboard_charts", {"id": "7"})

    assert client.dashboard_page_arguments == [
        {"page": 0, "page_size": 10, "query": "revenue"}
    ]
    assert dashboards["dashboards"] == [
        {"id": "7", "title": "Sales", "description": "Saved dashboard"}
    ]
    assert client.request_arguments[0][:3] == (
        "GET",
        "/api/v1/dashboard/7/charts",
        30,
    )
    assert charts == {
        "dashboard_id": "7",
        "charts": [{"id": "42", "title": "Daily sales", "description": "Saved chart"}],
    }
    assert "all_chart_data" not in repr(charts)
    assert tools.telemetry == {
        "logical_tool_calls": 2,
        "chart_query_http_requests": 0,
    }


@pytest.mark.asyncio
async def test_multi_envelope_rows_flatten_with_sql_provenance_and_saved_query_scope(
    saved_chart_data,
):
    metadata, envelopes = saved_chart_data
    client = FakeSupersetClient(metadata, envelopes)
    tools = RawSupersetTools(client)

    result = await tools.call("read_chart_rows", {"id": "42", "offset": 1, "limit": 2})

    assert result["rows"] == [
        {
            "period": "2026-01-01",
            "revenue": 20,
            "flag": False,
            "optional_numeric": None,
        },
        {
            "created_date": "2025-12-31",
            "revenue": 5,
            "nullable": None,
            "unstable": math.nan,
        },
    ]
    assert result["columns"] == [
        "period",
        "revenue",
        "flag",
        "optional_numeric",
        "created_date",
        "nullable",
        "unstable",
    ]
    assert result["total_query_row_count"] == 3
    assert result["offset"] == 1
    assert result["limit"] == 2
    assert result["next_offset"] is None
    assert result["has_more_returned_rows"] is False
    assert result["actual_sql"] == [
        {"query_index": 0, "sql": "SELECT period, revenue FROM daily_sales ORDER BY period"},
        {"query_index": 1, "sql": "SELECT created_date, revenue FROM daily_sales_archive"},
    ]
    assert result["declared_row_limits"] == [
        {"query_index": 0, "declared": True, "row_limit": 3},
        {"query_index": 1, "declared": True, "row_limit": 4},
    ]
    assert result["provider_row_counts"] == [
        {"query_index": 0, "sql_rowcount": 80, "rowcount": 2},
        {"query_index": 1, "sql_rowcount": 100, "rowcount": 1},
    ]
    assert result["query_scope"] == {
        "kind": "saved_chart_query",
        "dashboard_filters_applied": False,
        "warehouse_completeness": "unknown",
    }
    assert client.chart_data_arguments[0][1] == {}
    assert tools.telemetry == {
        "logical_tool_calls": 1,
        "chart_query_http_requests": 1,
    }


@pytest.mark.asyncio
async def test_profile_reports_raw_ranges_and_nulls_without_semantic_inference(
    saved_chart_data,
):
    metadata, envelopes = saved_chart_data
    tools = RawSupersetTools(FakeSupersetClient(metadata, envelopes))

    result = await tools.call("profile_saved_chart", {"id": "42"})

    assert result["returned_rowcount"] == 3
    assert result["numeric_ranges"]["revenue"] == {
        "min": 5,
        "max": 20,
        "null_count": 0,
        "missing_count": 0,
        "finite_numeric_count": 3,
    }
    assert result["numeric_ranges"]["optional_numeric"] == {
        "min": 2,
        "max": 2,
        "null_count": 1,
        "missing_count": 1,
        "finite_numeric_count": 1,
    }
    assert "flag" not in result["numeric_ranges"]
    assert "unstable" not in result["numeric_ranges"]
    assert result["date_ranges"]["period"]["raw_min"] == "2026-01-01"
    assert result["date_ranges"]["period"]["raw_max"] == "2026-01-02"
    assert result["date_ranges"]["created_date"]["raw_min"] == "2025-12-31"
    assert result["date_ranges"]["created_date"]["raw_max"] == "2025-12-31"
    assert "sum" not in repr(result).lower()
    assert "mean" not in repr(result).lower()
    assert "metric_meaning" not in repr(result)
    assert result["query_scope"]["warehouse_completeness"] == "unknown"


@pytest.mark.asyncio
async def test_query_cache_serves_pages_and_profiles_with_deepcopy_delivery(saved_chart_data):
    metadata, envelopes = saved_chart_data
    client = FakeSupersetClient(metadata, envelopes)
    tools = RawSupersetTools(client)

    first = await tools.call("read_chart_rows", {"id": "42", "offset": 0, "limit": 1})
    first["rows"][0]["revenue"] = -999
    first["query_definition"]["params"]["all_columns"].append("mutated")
    second = await tools.call("read_chart_rows", {"id": "42", "offset": 1, "limit": 1})
    profile = await tools.call("profile_saved_chart", {"id": "42"})
    repeat = await tools.call("read_chart_rows", {"id": "42", "offset": 0, "limit": 1})

    assert client.chart_data_calls == 1
    assert client.chart_data_arguments[0][1] == {}
    assert second["rows"][0]["revenue"] == 20
    assert profile["numeric_ranges"]["revenue"]["min"] == 5
    assert repeat["rows"][0]["revenue"] == 10
    assert repeat["query_definition"]["params"]["all_columns"] == [
        "period",
        "created_date",
        "revenue",
    ]
    assert first["telemetry"]["chart_query_cache_hit"] is False
    assert second["telemetry"]["chart_query_cache_hit"] is True
    assert repeat["telemetry"]["logical_tool_calls"] == 4
    assert repeat["telemetry"]["chart_query_http_requests"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("read_chart_rows", {"id": "0"}),
        ("read_chart_rows", {"id": "00042"}),
        ("read_chart_rows", {"id": "-1"}),
        ("read_chart_rows", {"id": "1.5"}),
        ("read_chart_rows", {"id": "9223372036854775808"}),
        ("list_dashboard_charts", {"id": "abc"}),
        ("profile_saved_chart", {"id": 42}),
        ("read_chart_rows", {"id": "42", "offset": -1}),
        ("read_chart_rows", {"id": "42", "offset": True}),
        ("read_chart_rows", {"id": "42", "offset": 20_001}),
        ("read_chart_rows", {"id": "42", "limit": 0}),
        ("read_chart_rows", {"id": "42", "limit": 251}),
        ("read_chart_rows", {"id": "42", "sql": "SELECT 1"}),
    ],
)
async def test_invalid_ids_pages_and_arguments_are_rejected_before_io(name, arguments):
    client = FakeSupersetClient()
    tools = RawSupersetTools(client)

    with pytest.raises(ValueError):
        await tools.call(name, arguments)

    assert client.requests_made == 0
    assert tools.chart_query_http_requests == 0


@pytest.mark.asyncio
async def test_query_results_over_row_bound_raise_instead_of_truncating():
    metadata = {"id": 42, "params": {"all_columns": ["secret_value"]}}
    envelopes = [{"data": [{"secret_value": index} for index in range(20_001)]}]
    client = FakeSupersetClient(metadata, envelopes)
    tools = RawSupersetTools(client)

    with pytest.raises(ValueError, match="20000-row bound") as error:
        await tools.call("read_chart_rows", {"id": "42"})

    assert "secret_value" not in str(error.value)
    assert "19999" not in str(error.value)
    assert client.chart_data_calls == 1
    assert "42" not in tools._chart_cache


@pytest.mark.asyncio
async def test_provider_query_errors_are_redacted_from_tool_errors():
    client = FakeSupersetClient({"id": 42}, [])
    client.query_error = "query failed near customer_email@example.test"
    tools = RawSupersetTools(client)

    with pytest.raises(ValueError, match="saved chart query failed") as error:
        await tools.call("profile_saved_chart", {"id": "42"})

    assert "customer_email" not in str(error.value)
    assert tools.chart_query_http_requests == 1

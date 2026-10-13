import asyncio
import json

import httpx
import pytest

from signalweave.models import SourceRef
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import (
    DEFAULT_MAX_CONCURRENT_CHART_REQUESTS,
    SupersetClient,
)


def test_metadata_mapping_is_read_only_and_safe():
    snapshot = SupersetClient.metadata_to_snapshot(
        {"id": 42, "dashboard_title": "Revenue", "owners": [{"username": "alice"}]}
    )
    assert snapshot.id == "42"
    assert snapshot.title == "Revenue"
    assert snapshot.owners == ["alice"]
    assert snapshot.charts == []


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"available_comparison_windows": ["previous_period"]}, ["previous_period"]),
        (
            {"json_metadata": '{"signalweave_comparison_windows": ["previous_period"]}'},
            ["previous_period"],
        ),
        (
            {"json_metadata": '{"signalweave": {"comparison_windows": ["custom"]}}'},
            ["custom"],
        ),
        ({"json_metadata": "not-json"}, []),
    ],
)
def test_source_owned_comparison_windows_are_explicit_and_never_inferred(metadata, expected):
    assert SupersetClient.comparison_windows_from_metadata(metadata) == expected


def test_dashboard_mapping_preserves_source_owned_comparison_windows():
    snapshot = SupersetClient.metadata_to_snapshot(
        {
            "id": 42,
            "dashboard_title": "Revenue",
            "json_metadata": '{"signalweave_comparison_windows": ["previous_period"]}',
        }
    )
    assert snapshot.available_comparison_windows == ["previous_period"]


@pytest.mark.asyncio
async def test_dashboard_chart_data_uses_superset_canonical_trailing_slash():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/chart/42/data/":
            return httpx.Response(200, json={"result": [{"data": [{"value": 7}]}]})
        raise AssertionError(f"unexpected Superset request: {request.url}")

    client = SupersetClient("http://superset.test", transport=httpx.MockTransport(handler))

    result = await client.chart_data(
        {"id": 42},
        dashboard_id=7,
    )

    assert result == [{"data": [{"value": 7}]}]
    assert requests[0].url.path == "/api/v1/chart/42/data/"
    assert requests[0].url.params["filters_dashboard_id"] == "7"
    assert client.requests_made == 1
    assert client.request_path_counts == {"/api/v1/chart/42/data/": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ([{"data": [], "is_cached": True}], "cached"),
        ([{"data": [], "is_cached": False}], "uncached"),
        ([{"data": [], "is_cached": True}, {"data": [], "is_cached": False}], "mixed"),
        ([{"data": [], "is_cached": None}], "unknown"),
        ([{"data": []}], "unknown"),
    ],
)
async def test_chart_data_surfaces_cache_provenance(result, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": result})

    client = SupersetClient("http://superset.test", transport=httpx.MockTransport(handler))
    telemetry: dict[str, object] = {}

    await client.chart_data(
        {"id": 42, "params": {"datasource": "1__table"}},
        response_telemetry=telemetry,
    )

    assert telemetry["cache_status"] == expected


@pytest.mark.asyncio
async def test_chart_data_rejects_malformed_cache_provenance():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": [{"data": [], "is_cached": "yes"}]})

    client = SupersetClient("http://superset.test", transport=httpx.MockTransport(handler))

    with pytest.raises(ValueError, match="invalid is_cached"):
        await client.chart_data(
            {"id": 42, "params": {"datasource": "1__table"}},
            response_telemetry={},
        )


def test_query_context_preserves_chart_time_grain_and_filters():
    chart = {
        "id": 42,
        "datasource_id": 3,
        "datasource_type": "table",
        "params": {
            "metrics": [{"label": "SUM(revenue)"}],
            "groupby": ["region"],
            "granularity_sqla": "event_date",
            "time_grain_sqla": "P1D",
            "adhoc_filters": [
                {
                    "subject": "region",
                    "operator": "IN",
                    "comparator": ["NA"],
                },
                {
                    "subject": "event_date",
                    "operator": "TEMPORAL_RANGE",
                    "comparator": "No filter",
                },
            ],
        },
    }

    query = SupersetClient._query_context(chart)
    query_object = query["queries"][0]
    assert query_object["columns"] == ["event_date", "region"]
    assert query_object["extras"] == {"time_grain_sqla": "P1D"}
    assert query_object["filters"] == [{"col": "region", "op": "IN", "val": ["NA"]}]


def test_query_context_derives_datasource_from_superset_form_data():
    query = SupersetClient._query_context(
        {
            "id": 42,
            "params": {
                "datasource": "17__table",
                "metrics": [{"label": "SUM(revenue)"}],
            },
        }
    )

    assert query["datasource"] == {"id": 17, "type": "table"}


def test_query_context_uses_all_columns_for_saved_table_charts():
    query = SupersetClient._query_context(
        {
            "datasource_id": 17,
            "params": {
                "viz_type": "table",
                "all_columns": ["order_date", "region", "net_sales"],
            },
        }
    )

    assert query["queries"][0]["columns"] == ["order_date", "region", "net_sales"]


@pytest.mark.parametrize(
    ("params", "expected_metrics", "expected_columns"),
    [
        (
            {
                "viz_type": "bubble_v2",
                "x": {"label": "SUM(quantity_ordered)"},
                "y": {"label": "COUNT_DISTINCT(country)"},
                "size": "count",
                "entity": "deal_size",
                "series": "product_line",
            },
            [
                {"label": "SUM(quantity_ordered)"},
                {"label": "COUNT_DISTINCT(country)"},
                "count",
            ],
            ["deal_size", "product_line"],
        ),
        (
            {
                "viz_type": "histogram_v2",
                "column": "expected_earn",
            },
            ["count"],
            ["expected_earn"],
        ),
        (
            {
                "viz_type": "gantt_chart",
                "series": "priority",
                "start_time": "start_time",
                "end_time": "end_time",
            },
            ["count"],
            ["priority", "start_time", "end_time"],
        ),
        (
            {
                "viz_type": "deck_arc",
                "start_spatial": {"latCol": "LATITUDE", "lonCol": "LONGITUDE"},
                "end_spatial": {"latCol": "LATITUDE_DEST", "lonCol": "LONGITUDE_DEST"},
            },
            ["count"],
            ["LATITUDE", "LONGITUDE", "LATITUDE_DEST", "LONGITUDE_DEST"],
        ),
        (
            {
                "viz_type": "deck_path",
                "line_column": "path_json",
            },
            ["count"],
            ["path_json"],
        ),
    ],
)
def test_query_context_recovers_visualization_specific_fields(
    params, expected_metrics, expected_columns
):
    query = SupersetClient._query_context({"datasource_id": 3, "params": params})
    query_object = query["queries"][0]

    assert query_object["metrics"] == expected_metrics
    assert query_object["columns"] == expected_columns


def test_heatmap_x_axis_is_a_dimension_not_a_duplicate_time_grain():
    query = SupersetClient._query_context(
        {
            "datasource_id": 3,
            "params": {
                "viz_type": "heatmap_v2",
                "metric": "count",
                "groupby": ["genre"],
                "x_axis": "year",
            },
        }
    )

    query_object = query["queries"][0]
    assert query_object["granularity"] is None
    assert query_object["columns"] == ["genre", "year"]


def test_query_context_bounds_saved_chart_limits():
    query = SupersetClient._query_context(
        {
            "datasource_id": 3,
            "params": {"row_limit": 999999, "series_limit": -10},
        }
    )

    query_object = query["queries"][0]
    assert query_object["row_limit"] == 10000
    assert query_object["series_limit"] == 0


def test_saved_query_context_is_preferred_and_forced_to_bounded_json():
    chart = {
        "query_context": {
            "datasource": {"id": 3, "type": "table"},
            "queries": [
                {
                    "columns": ["event_date"],
                    "metrics": ["Revenue"],
                    "row_limit": 999999,
                    "series_limit": -2,
                }
            ],
            "result_format": "csv",
            "result_type": "results",
            "force": True,
        }
    }

    query = SupersetClient._saved_query_context(chart)

    assert query is not None
    assert query["result_format"] == "json"
    assert query["result_type"] == "full"
    assert query["force"] is False
    assert query["queries"][0]["columns"] == ["event_date"]
    assert query["queries"][0]["row_limit"] == 10000
    assert query["queries"][0]["series_limit"] == 0


@pytest.mark.asyncio
async def test_dashboard_paging_arguments_are_bounded():
    client = SupersetClient("http://superset")

    for args in [(-1, 100, 1), (0, 0, 1), (0, 100, 0)]:
        with pytest.raises(ValueError):
            # The method validates before opening a network client.
            await client.list_dashboards(*args)


@pytest.mark.parametrize(
    ("page", "page_size", "query", "expected_query"),
    [
        (0, 5, "", {"page": 0, "page_size": 5}),
        (
            2,
            7,
            " revenue movement ",
            {
                "page": 2,
                "page_size": 7,
                "filters": [
                    {
                        "col": "dashboard_title",
                        "opr": "ct",
                        "value": "revenue movement",
                    }
                ],
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_dashboard_page_pagination_and_search_filter_are_encoded_in_q(
    page, page_size, query, expected_query
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"result": []})

    client = SupersetClient(
        "http://superset.test", transport=httpx.MockTransport(handler)
    )
    await client.list_dashboards_page(page=page, page_size=page_size, query=query)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/api/v1/dashboard/"
    assert set(request.url.params.keys()) == {"q"}
    assert json.loads(request.url.params["q"]) == expected_query


@pytest.mark.asyncio
async def test_dashboard_snapshot_records_source_failures_for_safety_gates():
    class BrokenClient(SupersetClient):
        async def get_dashboard_metadata(self, dashboard_id):
            return {
                "id": dashboard_id,
                "dashboard_title": "Broken dashboard",
                "position_json": '{"chart": {"type": "CHART", "meta": {"chartId": 42}}}',
            }

        async def get_chart_metadata(self, chart_id):
            raise httpx.ReadTimeout("source timeout")

    snapshot = await BrokenClient("http://superset").dashboard_snapshot(7)

    assert snapshot.charts[0].error
    assert "source timeout" in snapshot.charts[0].error
    resource = await SupersetAdapter(BrokenClient("http://superset")).inspect(
        SourceRef(
            key="broken-dashboard",
            adapter="superset",
            resource="dashboard:7",
            label="Broken dashboard",
        )
    )
    assert resource.error
    assert "source timeout" in resource.error


@pytest.mark.asyncio
async def test_dashboard_snapshot_bounds_chart_request_concurrency():
    class CountingClient(SupersetClient):
        def __init__(self):
            super().__init__("https://superset.test")
            self.active_requests = 0
            self.max_active_requests = 0

        async def get_dashboard_metadata(self, dashboard_id):
            position = {
                f"chart-{index}": {
                    "type": "CHART",
                    "meta": {"chartId": index},
                }
                for index in range(1, 25)
            }
            return {
                "id": dashboard_id,
                "dashboard_title": "Large dashboard",
                "position_json": position,
            }

        async def get_chart_metadata(self, chart_id):
            return {
                "id": chart_id,
                "slice_name": f"Chart {chart_id}",
                "params": {"metrics": [{"label": "Revenue"}]},
            }

        async def chart_data(
            self,
            chart,
            *,
            dashboard_id=None,
            allow_unscoped_fallback=False,
            scope_telemetry=None,
        ):
            del chart, dashboard_id, allow_unscoped_fallback, scope_telemetry
            self.active_requests += 1
            self.max_active_requests = max(
                self.max_active_requests, self.active_requests
            )
            try:
                await asyncio.sleep(0.001)
                return [{"data": [{"period": 1, "Revenue": 10}]}]
            finally:
                self.active_requests -= 1

    client = CountingClient()

    snapshot = await client.dashboard_snapshot(7)

    assert len(snapshot.charts) == 24
    assert client.max_active_requests == DEFAULT_MAX_CONCURRENT_CHART_REQUESTS
    assert client.active_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resource_path", "requested_id", "message"),
    [
        (
            "/api/v1/dashboard/7",
            7,
            "Superset dashboard response did not match the requested dashboard ID",
        ),
        (
            "/api/v1/chart/101",
            101,
            "Superset chart response did not match the requested chart ID",
        ),
    ],
)
async def test_metadata_endpoints_reject_substituted_resource_ids(
    resource_path, requested_id, message
):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == resource_path
        return httpx.Response(200, json={"result": {"id": "foreign-resource"}})

    client = SupersetClient(
        "https://superset.test", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ValueError, match=message):
        if resource_path.startswith("/api/v1/dashboard"):
            await client.get_dashboard_metadata(requested_id)
        else:
            await client.get_chart_metadata(requested_id)


@pytest.mark.asyncio
async def test_dashboard_snapshot_rejects_substituted_chart_metadata():
    class SubstitutedChartClient(SupersetClient):
        async def get_dashboard_metadata(self, dashboard_id):
            return {
                "id": dashboard_id,
                "dashboard_title": "Substituted chart",
                "position_json": (
                    '{"chart": {"type": "CHART", "meta": {"chartId": 42}}}'
                ),
            }

        async def get_chart_metadata(self, chart_id):
            del chart_id
            return {"id": 99, "slice_name": "Foreign chart"}

    snapshot = await SubstitutedChartClient("https://superset.test").dashboard_snapshot(7)

    assert snapshot.charts[0].error
    assert "did not match the requested chart ID" in snapshot.charts[0].error


@pytest.mark.asyncio
async def test_partial_dashboard_preserves_good_charts_and_quality_metadata():
    class PartiallyBrokenClient(SupersetClient):
        async def get_dashboard_metadata(self, dashboard_id):
            return {
                "id": dashboard_id,
                "dashboard_title": "Partially available dashboard",
                "position_json": (
                    '{"good": {"type": "CHART", "meta": {"chartId": 42}}, '
                    '"bad": {"type": "CHART", "meta": {"chartId": 43}}}'
                ),
            }

        async def get_chart_metadata(self, chart_id):
            return {
                "id": chart_id,
                "slice_name": f"Chart {chart_id}",
                "params": {"metrics": [{"label": "Revenue"}], "granularity_sqla": "period"},
            }

        async def chart_data(self, chart, *, dashboard_id=None, allow_unscoped_fallback=False):
            del allow_unscoped_fallback
            if str(chart["id"]) == "43":
                raise httpx.ReadTimeout("chart unavailable")
            return [{"data": [{"period": 1, "Revenue": 10}, {"period": 2, "Revenue": 12}]}]

    resource = await SupersetAdapter(PartiallyBrokenClient("http://superset")).inspect(
        SourceRef(
            key="partial-dashboard",
            adapter="superset",
            resource="dashboard:7",
            label="Partially available dashboard",
        )
    )

    assert resource.error is None
    assert len(resource.observations) == 1
    assert resource.metadata["data_quality"] == {
        "status": "partial",
        "chart_count": 2,
        "charts_with_observations": 1,
        "chart_errors": ["43: Data unavailable from Superset: chart unavailable"],
        "semantic_issues": ["43: Chart normalization failed: chart unavailable"],
        "missing_baseline_chart_ids": [],
    }


@pytest.mark.asyncio
async def test_dashboard_snapshot_rejects_unknown_selected_chart_ids():
    class CatalogClient(SupersetClient):
        async def get_dashboard_metadata(self, dashboard_id):
            return {
                "id": dashboard_id,
                "dashboard_title": "Catalog",
                "position_json": '{"chart": {"type": "CHART", "meta": {"chartId": 42}}}',
            }

    with pytest.raises(ValueError, match="selected chart IDs"):
        await CatalogClient("http://superset").dashboard_snapshot(7, chart_ids=["99"])


@pytest.mark.asyncio
@pytest.mark.parametrize("chart_ids", [[], [""], ["  "]])
async def test_dashboard_snapshot_rejects_empty_selected_chart_ids(chart_ids):
    class CatalogClient(SupersetClient):
        async def get_dashboard_metadata(self, dashboard_id):
            return {
                "id": dashboard_id,
                "dashboard_title": "Revenue",
                "position_json": {
                    "chart": {"type": "CHART", "meta": {"chartId": 64}}
                },
            }

    with pytest.raises(
        ValueError,
        match="chart_ids must be a non-empty list of non-empty strings",
    ):
        await CatalogClient("http://superset").dashboard_snapshot(
            7, chart_ids=chart_ids
        )


def test_time_series_rows_include_exact_returned_bucket_provenance():
    chart = {
        "id": 42,
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "aggregate": "SUM",
                    "column": {"column_name": "revenue"},
                    "label": "Revenue",
                }
            ],
            "granularity_sqla": "event_date",
            "groupby": ["region"],
        },
    }
    observations = SupersetClient.observations_from_chart_data(
        chart,
        [
            {
                "data": [
                    {"event_date": "2026-11-30", "region": "NA", "Revenue": 20},
                    {"event_date": "2026-01-02", "region": "NA", "Revenue": 10},
                    {"event_date": "2026-04-03", "region": "EU", "Revenue": 5},
                    {"event_date": "2026-11-30", "region": "EU", "Revenue": 10},
                    {"event_date": "2026-04-03", "region": "NA", "Revenue": 10},
                ]
            }
        ],
    )

    assert observations[0].current == 30
    assert observations[0].baseline == 15
    assert observations[0].change_pct == 100.0
    assert "time_encoding" not in observations[0].attributes
    assert "current_period_iso" not in observations[0].attributes
    assert observations[0].attributes["time_column"] == "event_date"
    assert observations[0].attributes["current_period"] == "2026-11-30"
    assert observations[0].attributes["baseline_period"] == "2026-04-03"
    assert (
        observations[0].attributes["comparison_basis"]
        == "last_two_returned_time_buckets"
    )
    assert observations[0].attributes["time_bucket_count"] == 3
    assert observations[0].attributes["period_coverage"].startswith("unverified;")


def test_additive_grouped_sum_keeps_pooled_series_and_channel_children():
    chart = {
        "id": 42,
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "aggregate": "SUM",
                    "column": {"column_name": "sales"},
                    "label": "SUM(sales)",
                }
            ],
            "granularity_sqla": "period",
            "groupby": ["channel"],
        },
    }
    observations = SupersetClient.observations_from_chart_data(
        chart,
        [
            {
                "data": [
                    {"period": 1, "channel": "Online", "SUM(sales)": 100},
                    {"period": 1, "channel": "Store", "SUM(sales)": 100},
                    {"period": 2, "channel": "Online", "SUM(sales)": 50},
                    {"period": 2, "channel": "Store", "SUM(sales)": 150},
                ]
            }
        ],
    )

    by_channel = {
        item.dimensions["channel"]: (item.current, item.baseline, item.change_pct)
        for item in observations
        if item.dimensions
    }
    pooled = next(item for item in observations if not item.dimensions)
    assert by_channel == {"Online": (50.0, 100.0, -50.0), "Store": (150.0, 100.0, 50.0)}
    assert (pooled.current, pooled.baseline, pooled.change_pct) == (200.0, 200.0, 0.0)


def test_time_series_rows_become_a_comparable_observation():
    chart = {
        "id": 42,
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "aggregate": "SUM",
                    "column": {"column_name": "revenue"},
                    "label": "Revenue",
                }
            ],
            "granularity_sqla": "period",
            "time_grain_sqla": "P1M",
            "groupby": ["region"],
        },
    }
    observations = SupersetClient.observations_from_chart_data(
        chart,
        [
            {
                "data": [
                    {"period": 1, "region": "NA", "Revenue": 10},
                    {"period": 1, "region": "EU", "Revenue": 5},
                    {"period": 2, "region": "NA", "Revenue": 20},
                    {"period": 2, "region": "EU", "Revenue": 10},
                ]
            }
        ],
    )

    assert observations[0].current == 30
    assert observations[0].baseline == 15
    assert observations[0].change_pct == 100.0
    assert observations[0].attributes["current_period"] == 2
    assert observations[0].attributes["baseline_period"] == 1
    assert "time_encoding" not in observations[0].attributes
    assert "current_period_iso" not in observations[0].attributes


def test_nonadditive_grouped_time_series_preserves_each_group_and_iso_provenance():
    chart = {
        "id": 42,
        "slice_name": "Latency",
        "params": {
            "metrics": [
                {
                    "expressionType": "SIMPLE",
                    "aggregate": "AVG",
                    "column": {"column_name": "latency"},
                    "label": "AVG(latency)",
                }
            ],
            "granularity_sqla": "period",
            "groupby": [{"column_name": "cluster_id", "label": "Cluster"}],
        },
    }
    result = [
        {
            "colnames": ["period", "Cluster", "AVG(latency)"],
            "coltypes": [2, 1, 0],
            "data": [
                [1709251200000, "A", 5],
                [1709251200000, "B", 50],
                [1711929600000, "A", 10],
                [1711929600000, "B", 100],
            ],
        }
    ]

    extraction = SupersetClient.extract_chart_data(chart, result)
    observations = extraction.observations
    reversed_result = [{**result[0], "data": list(reversed(result[0]["data"]))}]

    assert {(item.current, item.baseline) for item in observations} == {
        (10.0, 5.0),
        (100.0, 50.0),
    }
    assert 110.0 not in {item.current for item in observations}
    assert {item.dimensions["Cluster"] for item in observations} == {"A", "B"}
    assert all(item.attributes["dimensions"] == item.dimensions for item in observations)
    assert all(
        item.attributes["current_period_iso"] == "2024-04-01T00:00:00+00:00"
        for item in observations
    )
    assert len({item.subject_id for item in observations}) == 2
    assert {item.subject_id for item in observations} == {
        item.subject_id
        for item in SupersetClient.extract_chart_data(chart, reversed_result).observations
    }
    assert extraction.semantic_status == "extracted"


@pytest.mark.parametrize(
    ("spec", "metric_key", "expected"),
    [
        ({"expressionType": "SIMPLE", "aggregate": "SUM", "label": "Revenue"}, "Revenue", True),
        ({"expressionType": "SIMPLE", "aggregate": "COUNT", "label": "Rows"}, "Rows", True),
        ({"expressionType": "SQL", "sqlExpression": "SUM(revenue)", "label": "Revenue"}, "Revenue", True),
        ({"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Rows"}, "Rows", True),
        ({"expressionType": "SIMPLE", "aggregate": "AVG", "label": "Revenue"}, "Revenue", False),
        ({"expressionType": "SIMPLE", "aggregate": "MAX", "label": "Maximum"}, "Maximum", False),
        ({"expressionType": "SIMPLE", "aggregate": "MIN", "label": "Minimum"}, "Minimum", False),
        ({"expressionType": "SIMPLE", "aggregate": "COUNT", "label": "Customers", "distinct": True}, "Customers", False),
        ({"expressionType": "SQL", "sqlExpression": "SUM(success) / SUM(total)", "label": "Rate"}, "Rate", False),
        ({"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT customer_id)", "label": "Customers"}, "Customers", False),
        ({"expressionType": "SQL", "sqlExpression": "PERCENTILE_CONT(0.95)", "label": "p95"}, "p95", False),
        ({"label": "Total Revenue"}, "Total Revenue", False),
    ],
)
def test_only_explicit_additive_metric_definitions_are_poolable(spec, metric_key, expected):
    chart = {"params": {"metrics": [spec]}}
    assert SupersetClient._metric_is_additive(chart, metric_key) is expected


def test_grouped_ratios_percentiles_and_unknown_metrics_remain_per_group():
    extraction = SupersetClient.extract_chart_data(
        {
            "id": 42,
            "params": {
                "metrics": [
                    {
                        "expressionType": "SQL",
                        "sqlExpression": "SUM(signups) / SUM(sessions)",
                        "label": "Signup rate",
                    },
                    {
                        "expressionType": "SQL",
                        "sqlExpression": "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency)",
                        "label": "p95",
                    },
                    {"label": "Revenue"},
                ],
                "granularity_sqla": "period",
                "groupby": ["cluster"],
            },
        },
        [
            {
                "data": [
                    {"period": 1, "cluster": "A", "Signup rate": 0.2, "p95": 10, "Revenue": 5},
                    {"period": 1, "cluster": "B", "Signup rate": 0.6, "p95": 90, "Revenue": 50},
                    {"period": 2, "cluster": "A", "Signup rate": 0.3, "p95": 11, "Revenue": 6},
                    {"period": 2, "cluster": "B", "Signup rate": 0.7, "p95": 100, "Revenue": 60},
                ]
            }
        ],
    )

    actual = {
        metric: {
            item.dimensions["cluster"]: (item.current, item.baseline)
            for item in extraction.observations
            if item.metric == metric
        }
        for metric in ("Signup rate", "p95", "Revenue")
    }
    assert actual == {
        "Signup rate": {"A": (0.3, 0.2), "B": (0.7, 0.6)},
        "p95": {"A": (11.0, 10.0), "B": (100.0, 90.0)},
        "Revenue": {"A": (6.0, 5.0), "B": (60.0, 50.0)},
    }


@pytest.mark.parametrize("axis_source", ["params_columns", "saved_query_context"])
def test_nonadditive_series_uses_declared_columns_as_group_axes(axis_source):
    params = {
        "metrics": [
            {"expressionType": "SIMPLE", "aggregate": "AVG", "label": "AVG(latency)"}
        ],
        "granularity_sqla": "period",
    }
    chart = {"id": 42, "params": params}
    dimension_key = "cluster"
    if axis_source == "params_columns":
        params["columns"] = [{"column_name": "cluster_id", "label": "Cluster"}]
        dimension_key = "Cluster"
    else:
        chart["query_context"] = {"queries": [{"columns": ["cluster"]}]}

    extraction = SupersetClient.extract_chart_data(
        chart,
        [
            {
                "data": [
                    {"period": 2, dimension_key: "A", "AVG(latency)": 10},
                    {"period": 2, dimension_key: "B", "AVG(latency)": 100},
                ]
            }
        ],
    )

    assert {
        item.dimensions[dimension_key]: item.current
        for item in extraction.observations
    } == {"A": 10.0, "B": 100.0}
    assert all(item.baseline is None for item in extraction.observations)
    assert extraction.semantic_status == "partial"


def test_other_resolved_metrics_in_columns_are_not_group_axes():
    extraction = SupersetClient.extract_chart_data(
        {
            "id": 42,
            "params": {
                "metrics": [
                    {
                        "expressionType": "SIMPLE",
                        "aggregate": "AVG",
                        "column": {"column_name": "latency"},
                        "label": "AVG(latency)",
                    },
                    {
                        "expressionType": "SIMPLE",
                        "aggregate": "COUNT",
                        "column": {"column_name": "event_id"},
                        "label": "Sample count",
                    },
                ],
                "granularity_sqla": "period",
                "columns": ["cluster", "Sample count"],
            },
        },
        [
            {
                "data": [
                    {"period": 1, "cluster": "A", "AVG(latency)": 5, "Sample count": 10},
                    {"period": 1, "cluster": "B", "AVG(latency)": 50, "Sample count": 100},
                    {"period": 2, "cluster": "A", "AVG(latency)": 10, "Sample count": 11},
                    {"period": 2, "cluster": "B", "AVG(latency)": 100, "Sample count": 101},
                ]
            }
        ],
    )

    latency = {
        item.dimensions["cluster"]: (item.current, item.baseline)
        for item in extraction.observations
        if item.metric == "AVG(latency)"
    }
    assert latency == {"A": (10.0, 5.0), "B": (100.0, 50.0)}
    assert all(
        "Sample count" not in item.dimensions
        for item in extraction.observations
        if item.metric == "AVG(latency)"
    )


def test_nonadditive_duplicate_bucket_without_group_is_not_summed():
    extraction = SupersetClient.extract_chart_data(
        {
            "id": 42,
            "params": {
                "metrics": [
                    {"expressionType": "SIMPLE", "aggregate": "AVG", "label": "AVG(latency)"}
                ],
                "granularity_sqla": "period",
            },
        },
        [
            {
                "data": [
                    {"period": 1, "AVG(latency)": 10},
                    {"period": 1, "AVG(latency)": 100},
                ]
            }
        ],
    )

    assert len(extraction.observations) == 1
    assert extraction.observations[0].current is None
    assert extraction.observations[0].baseline is None
    assert extraction.semantic_status == "partial"


def test_duplicate_nonadditive_group_bucket_is_not_summed():
    extraction = SupersetClient.extract_chart_data(
        {
            "id": 42,
            "params": {
                "metrics": [
                    {"expressionType": "SIMPLE", "aggregate": "AVG", "label": "AVG(latency)"}
                ],
                "granularity_sqla": "period",
                "groupby": ["cluster"],
            },
        },
        [
            {
                "data": [
                    {"period": 1, "cluster": "A", "AVG(latency)": 8},
                    {"period": 2, "cluster": "A", "AVG(latency)": 10},
                    {"period": 2, "cluster": "A", "AVG(latency)": 20},
                ]
            }
        ],
    )

    assert len(extraction.observations) == 1
    assert extraction.observations[0].current is None
    assert extraction.observations[0].baseline == 8
    assert extraction.observations[0].change_pct is None
    assert extraction.semantic_status == "partial"


def test_missing_group_baseline_is_partial_not_zero():
    extraction = SupersetClient.extract_chart_data(
        {
            "id": 42,
            "params": {
                "metrics": [{"label": "Revenue"}],
                "granularity_sqla": "period",
                "groupby": ["cluster"],
            },
        },
        [
            {
                "data": [
                    {"period": 1, "cluster": "A", "Revenue": 10},
                    {"period": 2, "cluster": "A", "Revenue": 20},
                    {"period": 2, "cluster": "B", "Revenue": 100},
                ]
            }
        ],
    )

    observations = {item.dimensions["cluster"]: item for item in extraction.observations}
    assert observations["A"].current == 20
    assert observations["A"].baseline == 10
    assert observations["B"].current == 100
    assert observations["B"].baseline is None
    assert observations["B"].change_pct is None
    assert extraction.semantic_status == "partial"


def test_single_time_bucket_has_raw_current_period_and_no_baseline_period():
    observations = SupersetClient.observations_from_chart_data(
        {
            "id": 42,
            "params": {
                "metrics": [{"label": "Revenue"}],
                "granularity_sqla": "event_date",
            },
        },
        [{"data": [{"event_date": "2026-08-17", "Revenue": 12}]}],
    )

    observation = observations[0]
    assert observation.current == 12
    assert observation.baseline is None
    assert observation.attributes["time_column"] == "event_date"
    assert observation.attributes["current_period"] == "2026-08-17"
    assert observation.attributes["baseline_period"] is None
    assert (
        observation.attributes["comparison_basis"]
        == "last_two_returned_time_buckets"
    )
    assert observation.attributes["time_bucket_count"] == 1
    assert observation.comparison_baselines == {}


def test_declared_temporal_superset_columns_add_iso_periods_and_keep_raw_values():
    observations = SupersetClient.observations_from_chart_data(
        {
            "id": 42,
            "params": {
                "metrics": [{"label": "SUM(net_sales)"}],
                "granularity_sqla": "order_date",
            },
        },
        [
            {
                "colnames": ["channel", "order_date", "SUM(net_sales)"],
                "coltypes": [1, 2, 0],
                "data": [
                    ["web", 1709251200000, 10],
                    ["web", 1711929600000, 20],
                ],
            }
        ],
    )

    attributes = observations[0].attributes
    assert attributes["current_period"] == 1711929600000
    assert attributes["baseline_period"] == 1709251200000
    assert attributes["time_encoding"] == "superset_epoch_milliseconds"
    assert attributes["current_period_iso"] == "2024-04-01T00:00:00+00:00"
    assert attributes["baseline_period_iso"] == "2024-03-01T00:00:00+00:00"


def test_temporal_period_iso_conversion_respects_finite_datetime_bounds():
    convert = SupersetClient._superset_epoch_milliseconds_iso
    assert convert(-62135596800000) == "0001-01-01T00:00:00+00:00"
    assert convert(253402300799999) == "9999-12-31T23:59:59.999000+00:00"
    for value in (
        -62135596800001,
        253402300800000,
        float("nan"),
        float("inf"),
        float("-inf"),
        10**1000,
        True,
        "1711929600000",
        None,
    ):
        assert convert(value) is None


def test_mixed_period_values_and_type_declarations_are_not_guessed_as_dates():
    chart = {
        "id": 42,
        "params": {"metrics": [{"label": "Revenue"}], "granularity_sqla": "period"},
    }
    mixed_values = SupersetClient.observations_from_chart_data(
        chart,
        [
            {
                "colnames": ["period", "Revenue"],
                "coltypes": [2, 0],
                "data": [[1709251200000, 10], ["2024-04-01", 20]],
            }
        ],
    )[0].attributes
    assert mixed_values["current_period"] == "2024-04-01"
    assert mixed_values["baseline_period_iso"] == "2024-03-01T00:00:00+00:00"
    assert "current_period_iso" not in mixed_values
    assert mixed_values["time_encoding"] == "superset_epoch_milliseconds"

    mixed_declarations = SupersetClient.observations_from_chart_data(
        chart,
        [
            {"colnames": ["period", "Revenue"], "coltypes": [2, 0], "data": [[1709251200000, 10]]},
            {"colnames": ["period", "Revenue"], "coltypes": [0, 0], "data": [[1711929600000, 20]]},
        ],
    )[0].attributes
    assert mixed_declarations["current_period"] == 1711929600000
    assert "time_encoding" not in mixed_declarations
    assert "current_period_iso" not in mixed_declarations

    partly_undeclared = SupersetClient.observations_from_chart_data(
        chart,
        [
            {"colnames": ["period", "Revenue"], "coltypes": [2, 0], "data": [[1709251200000, 10]]},
            {"data": [{"period": 1711929600000, "Revenue": 20}]},
        ],
    )[0].attributes
    assert "time_encoding" not in partly_undeclared
    assert "current_period_iso" not in partly_undeclared


def test_typed_string_periods_do_not_claim_epoch_time_encoding():
    attributes = SupersetClient.observations_from_chart_data(
        {
            "id": 42,
            "params": {"metrics": [{"label": "Revenue"}], "granularity_sqla": "period"},
        },
        [
            {
                "colnames": ["period", "Revenue"],
                "coltypes": [2, 0],
                "data": [["2024-03-01", 10], ["2024-04-01", 20]],
            }
        ],
    )[0].attributes

    assert attributes["current_period"] == "2024-04-01"
    assert attributes["baseline_period"] == "2024-03-01"
    assert "time_encoding" not in attributes
    assert "current_period_iso" not in attributes
    assert "baseline_period_iso" not in attributes


def test_temporal_single_bucket_keeps_raw_period_and_has_no_baseline_iso():
    observation = SupersetClient.observations_from_chart_data(
        {
            "id": 42,
            "params": {"metrics": [{"label": "Revenue"}], "granularity_sqla": "period"},
        },
        [{"colnames": ["period", "Revenue"], "coltypes": [2, 0], "data": [[1711929600000, 12]]}],
    )[0]

    assert observation.attributes["current_period"] == 1711929600000
    assert observation.attributes["current_period_iso"] == "2024-04-01T00:00:00+00:00"
    assert observation.attributes["baseline_period"] is None
    assert "baseline_period_iso" not in observation.attributes
    assert observation.attributes["time_bucket_count"] == 1


def test_time_series_rows_include_supported_comparison_baselines():
    observations = SupersetClient.observations_from_chart_data(
        {
            "id": 42,
            "params": {"metrics": [{"label": "Revenue"}], "granularity_sqla": "period"},
        },
        [
            {
                "data": [
                    {"period": 1, "Revenue": 10},
                    {"period": 2, "Revenue": 20},
                    {"period": 3, "Revenue": 30},
                    {"period": 4, "Revenue": 40},
                    {"period": 5, "Revenue": 50},
                ]
            }
        ],
    )

    assert observations[0].comparison_baselines == {
        "previous_period": 40.0,
        "trailing_4_period_average": 25.0,
    }


def test_ambiguous_numeric_result_retains_all_metrics_and_marks_review_required():
    observations = SupersetClient.observations_from_chart_data(
        {"id": 42, "params": {}},
        [{"data": [{"revenue": 10, "orders": 2}, {"revenue": 12, "orders": 3}]}],
    )

    assert {item.metric for item in observations} == {"revenue", "orders"}
    assert len(observations) == 4


def test_chart_extraction_normalizes_columnar_and_nested_result_shapes():
    extraction = SupersetClient.extract_chart_data(
        {
            "id": 42,
            "viz_type": "custom_viz",
            "params": {"metrics": [{"label": "Revenue"}]},
        },
        [{"data": {"columns": ["region", "Revenue"], "data": [["NA", 10], ["EU", 12]]}}],
    )

    assert [item.current for item in extraction.observations] == [10.0, 12.0]
    assert extraction.metrics == ["Revenue"]
    assert extraction.semantic_status == "extracted"


def test_implicit_count_charts_keep_numeric_dimensions_out_of_metric_set():
    extraction = SupersetClient.extract_chart_data(
        {
            "id": 42,
            "viz_type": "histogram_v2",
            "params": {"column": "quantity_ordered"},
        },
        [{"data": [{"quantity_ordered": 1, "count": 4}, {"quantity_ordered": 2, "count": 7}]}],
    )

    assert extraction.metrics == ["count"]
    assert extraction.semantic_status == "extracted"
    assert extraction.observations[0].dimensions == {"quantity_ordered": 1}


@pytest.mark.asyncio
async def test_dashboard_chart_data_can_fallback_only_for_unfiltered_dashboards():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            return httpx.Response(
                400,
                json={"message": "Chart has no query context saved. Please save the chart again."},
            )
        return httpx.Response(200, json={"result": [{"data": [{"value": 7}]}]})

    client = SupersetClient("http://superset.test", transport=httpx.MockTransport(handler))
    result = await client.chart_data(
        {
            "id": 42,
            "datasource": "1__table",
            "params": {"metrics": ["value"]},
        },
        dashboard_id=7,
        allow_unscoped_fallback=True,
    )

    assert result == [{"data": [{"value": 7}]}]
    assert calls == ["GET /api/v1/chart/42/data/", "POST /api/v1/chart/data"]


@pytest.mark.asyncio
async def test_dashboard_chart_data_does_not_fallback_for_filter_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "invalid filter state"})

    client = SupersetClient("http://superset.test", transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await client.chart_data(
            {"id": 42},
            dashboard_id=7,
            allow_unscoped_fallback=True,
        )


@pytest.mark.asyncio
async def test_dashboard_snapshot_surfaces_unscoped_fallback_telemetry():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Growth",
                        "position_json": {
                            "chart-42": {"type": "CHART", "meta": {"chartId": 42}}
                        },
                        "json_metadata": "{}",
                    }
                },
            )
        if request.url.path == "/api/v1/chart/42":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 42,
                        "slice_name": "Revenue",
                        "params": '{"datasource":"1__table","metrics":["value"]}',
                    }
                },
            )
        if request.url.path == "/api/v1/chart/42/data/":
            return httpx.Response(
                400,
                json={"message": "Chart has no query context saved. Please save the chart again."},
            )
        if request.url.path == "/api/v1/chart/data":
            return httpx.Response(200, json={"result": [{"data": [{"value": 7}]}]})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = SupersetClient("http://superset.test", transport=httpx.MockTransport(handler))
    snapshot = await client.dashboard_snapshot(7)

    assert snapshot.scope_telemetry == {
        "dashboard_scoped_requests": 0,
        "chart_query_fallbacks": 1,
    }
    assert snapshot.charts[0].data_scope == "chart_query_fallback"


@pytest.mark.asyncio
async def test_dashboard_snapshot_never_falls_back_when_native_filters_exist():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Filtered growth",
                        "position_json": {
                            "chart-42": {"type": "CHART", "meta": {"chartId": 42}}
                        },
                        "json_metadata": (
                            '{"native_filter_configuration":[{"id":"region",'
                            '"controlValues":{"defaultToFirstItem":false},'
                            '"defaultDataMask":{"extraFormData":{"filters":['
                            '{"col":"region","op":"IN","val":["ca"]}]},'
                            '"filterState":{"value":["ca"]}}}]}'
                        ),
                    }
                },
            )
        if request.url.path == "/api/v1/chart/42":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 42,
                        "slice_name": "Revenue",
                        "params": '{"datasource":"1__table","metrics":["value"]}',
                    }
                },
            )
        if request.url.path == "/api/v1/chart/42/data/":
            return httpx.Response(
                400,
                json={"message": "Chart has no query context saved. Please save the chart again."},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = SupersetClient("http://superset.test", transport=httpx.MockTransport(handler))
    snapshot = await client.dashboard_snapshot(7)

    assert snapshot.scope_telemetry == {
        "dashboard_scoped_requests": 0,
        "chart_query_fallbacks": 0,
    }
    assert snapshot.charts[0].error is not None
    assert "400 Bad Request" in snapshot.charts[0].error
    assert "POST /api/v1/chart/data" not in calls


@pytest.mark.asyncio
async def test_dashboard_snapshot_falls_back_for_native_filters_without_defaults():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Initial-load growth",
                        "position_json": {
                            "chart-42": {"type": "CHART", "meta": {"chartId": 42}}
                        },
                        "json_metadata": (
                            '{"default_filters":"{}",'
                            '"native_filter_configuration":[{"id":"region",'
                            '"controlValues":{"defaultToFirstItem":false},'
                            '"defaultDataMask":{"extraFormData":{},"filterState":{}}}]}'
                        ),
                    }
                },
            )
        if request.url.path == "/api/v1/chart/42":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 42,
                        "slice_name": "Revenue",
                        "params": '{"datasource":"1__table","metrics":["value"]}',
                    }
                },
            )
        if request.url.path == "/api/v1/chart/42/data/":
            return httpx.Response(
                400,
                json={"message": "Chart has no query context saved. Please save the chart again."},
            )
        if request.url.path == "/api/v1/chart/data":
            return httpx.Response(200, json={"result": [{"data": [{"value": 7}]}]})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = SupersetClient("http://superset.test", transport=httpx.MockTransport(handler))
    snapshot = await client.dashboard_snapshot(7)

    assert snapshot.charts[0].observations
    assert snapshot.charts[0].data_scope == "chart_query_fallback"
    assert snapshot.scope_telemetry == {
        "dashboard_scoped_requests": 0,
        "chart_query_fallbacks": 1,
    }
    assert calls == [
        "GET /api/v1/dashboard/7",
        "GET /api/v1/chart/42",
        "GET /api/v1/chart/42/data/",
        "POST /api/v1/chart/data",
    ]


def test_dashboard_chart_array_metadata_is_discovered_without_position_json():
    snapshot = SupersetClient.metadata_to_snapshot(
        {
            "id": 42,
            "dashboard_title": "Niche charts",
            "charts": [{"id": 7, "title": "Custom visualization", "viz_type": "custom_viz"}],
        }
    )

    assert [chart.id for chart in snapshot.charts] == ["7"]
    assert snapshot.charts[0].viz_type == "custom_viz"


def test_table_chart_uses_date_like_column_as_time_and_numeric_column_as_metric():
    observations = SupersetClient.observations_from_chart_data(
        {
            "id": 42,
            "params": {
                "all_columns": ["order_date", "region", "net_sales"],
            },
        },
        [
            {
                "data": [
                    {"order_date": "2026-02-11", "region": "NA", "net_sales": 10},
                    {"order_date": "2026-05-27", "region": "NA", "net_sales": 12},
                ]
            }
        ],
    )

    assert observations[0].metric == "net_sales"
    assert observations[0].current == 12
    assert observations[0].baseline == 10
    assert observations[0].attributes["time_column"] == "order_date"
    assert observations[0].attributes["current_period"] == "2026-05-27"
    assert observations[0].attributes["baseline_period"] == "2026-02-11"

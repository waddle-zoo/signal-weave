import httpx
import pytest

from signalweave.models import SourceRef
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient


def test_metadata_mapping_is_read_only_and_safe():
    snapshot = SupersetClient.metadata_to_snapshot(
        {"id": 42, "dashboard_title": "Revenue", "owners": [{"username": "alice"}]}
    )
    assert snapshot.id == "42"
    assert snapshot.title == "Revenue"
    assert snapshot.owners == ["alice"]
    assert snapshot.charts == []


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


@pytest.mark.asyncio
async def test_dashboard_search_page_uses_server_side_json_filter():
    class SearchClient(SupersetClient):
        def __init__(self):
            super().__init__("http://superset")
            self.params = None

        async def _request(self, method, path, *, timeout, **kwargs):
            del method, path, timeout
            self.params = kwargs["params"]
            return httpx.Response(
                200,
                json={
                    "result": [{"id": 7, "dashboard_title": "Revenue movement"}],
                    "count": 1,
                },
                request=httpx.Request("GET", "http://superset/api/v1/dashboard/"),
            )

    client = SearchClient()
    dashboards, count = await client.list_dashboards_page(
        page=0, page_size=10, query="revenue movement"
    )

    assert dashboards[0]["id"] == 7
    assert count == 1
    assert '"dashboard_title"' in client.params["q"]
    assert '"revenue movement"' in client.params["q"]


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

        async def chart_data(self, chart, *, dashboard_id=None):
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


def test_time_series_rows_become_a_comparable_observation():
    chart = {
        "id": 42,
        "params": {
            "metrics": [{"label": "Revenue"}],
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
                    {"order_date": 1, "region": "NA", "net_sales": 10},
                    {"order_date": 2, "region": "NA", "net_sales": 12},
                ]
            }
        ],
    )

    assert observations[0].metric == "net_sales"
    assert observations[0].current == 12
    assert observations[0].baseline == 10

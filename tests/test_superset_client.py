import pytest

from semantic_monitor.superset_client import SupersetClient


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


def test_saved_query_context_is_preferred_and_forced_to_bounded_json():
    chart = {
        "query_context": {
            "datasource": {"id": 3, "type": "table"},
            "queries": [{"columns": ["event_date"], "metrics": ["Revenue"]}],
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


@pytest.mark.asyncio
async def test_dashboard_paging_arguments_are_bounded():
    client = SupersetClient("http://superset")

    for args in [(-1, 100, 1), (0, 0, 1), (0, 100, 0)]:
        with pytest.raises(ValueError):
            # The method validates before opening a network client.
            await client.list_dashboards(*args)


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

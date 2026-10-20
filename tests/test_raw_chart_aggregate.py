from __future__ import annotations

import math
from decimal import Decimal

import pytest

from evaluations.raw_chart_aggregate import (
    MAX_INPUT_ROWS,
    aggregate_saved_chart_rows,
    validate_aggregation_request,
)


def _aggregate(
    rows,
    *,
    columns=None,
    filters=None,
    group_by=None,
    aggregations=None,
    **kwargs,
):
    return aggregate_saved_chart_rows(
        rows,
        ["period", "channel", "amount"] if columns is None else columns,
        filters=[] if filters is None else filters,
        group_by=[] if group_by is None else group_by,
        aggregations=[{"op": "count"}] if aggregations is None else aggregations,
        **kwargs,
    )


def test_groups_raw_partial_period_rows_and_preserves_query_provenance():
    rows = [
        {"period": "2026-10-01", "channel": "web", "amount": Decimal("12.40")},
        {"period": "2026-10-01", "channel": "store", "amount": Decimal("3.10")},
        {"period": "2026-10-02", "channel": "web", "amount": Decimal("7.60")},
    ]
    filters = [{"column": "channel", "op": "eq", "value": "web"}]
    provenance = {
        "query_definition": {"params": {"period_window": ["2026-10-01", "2026-10-02"]}},
        "actual_sql": [{"query_index": 0, "sql": "SELECT period, channel, amount ..."}],
        "query_scope": {
            "kind": "saved_chart_query",
            "warehouse_completeness": "unknown",
        },
        "provider_row_counts": [{"query_index": 0, "rowcount": 3}],
    }

    result = _aggregate(
        rows,
        filters=filters,
        group_by=["period", "channel"],
        aggregations=[{"op": "sum", "column": "amount"}, {"op": "count"}],
        query_provenance=provenance,
    )

    assert result["scope"] == {
        "kind": "saved_chart_query_returned_rows",
        "input_row_count": 3,
        "warehouse_completeness": "unknown",
    }
    assert result["request"]["filters"] == filters
    assert result["request"]["group_by"] == ["period", "channel"]
    assert result["source_provenance"] == provenance
    assert result["matched_row_count"] == 2
    assert result["groups"] == [
        {
            "key": {"period": "2026-10-01", "channel": "web"},
            "row_count": 1,
            "aggregations": [
                {
                    "op": "sum",
                    "column": "amount",
                    "sum": "12.40",
                    "value_count": 1,
                    "null_count": 0,
                },
                {"op": "count", "count": 1},
            ],
        },
        {
            "key": {"period": "2026-10-02", "channel": "web"},
            "row_count": 1,
            "aggregations": [
                {"op": "sum", "column": "amount", "sum": "7.60", "value_count": 1, "null_count": 0},
                {"op": "count", "count": 1},
            ],
        },
    ]
    assert all(type(group["key"]["period"]) is str for group in result["groups"])


def test_duplicate_rows_count_separately_and_sum_reports_nulls_and_decimal_exactly():
    rows = [
        {"period": "day", "channel": "web", "amount": Decimal("0.10")},
        {"period": "day", "channel": "web", "amount": Decimal("0.10")},
        {"period": "day", "channel": "web", "amount": None},
        {"period": "day", "channel": None, "amount": Decimal("2.5")},
    ]

    result = _aggregate(
        rows,
        group_by=["channel"],
        aggregations=[{"op": "sum", "column": "amount"}, {"op": "count"}],
    )

    assert result["groups"] == [
        {
            "key": {"channel": "web"},
            "row_count": 3,
            "aggregations": [
                {"op": "sum", "column": "amount", "sum": "0.20", "value_count": 2, "null_count": 1},
                {"op": "count", "count": 3},
            ],
        },
        {
            "key": {"channel": None},
            "row_count": 1,
            "aggregations": [
                {"op": "sum", "column": "amount", "sum": "2.5", "value_count": 1, "null_count": 0},
                {"op": "count", "count": 1},
            ],
        },
    ]


def test_all_null_sum_is_unavailable_not_zero_and_null_equality_is_explicit():
    rows = [{"period": "day", "channel": None, "amount": None}]

    result = _aggregate(
        rows,
        filters=[{"column": "channel", "op": "eq", "value": None}],
        aggregations=[{"op": "sum", "column": "amount"}],
    )

    assert result["matched_row_count"] == 1
    assert result["groups"][0]["aggregations"] == [
        {"op": "sum", "column": "amount", "sum": None, "value_count": 0, "null_count": 1}
    ]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (True, "non-numeric"),
        (math.inf, "non-finite"),
        (Decimal("NaN"), "non-finite"),
        ("not numeric", "non-numeric"),
    ],
)
def test_sum_rejects_boolean_nonfinite_and_unsupported_types(value, message):
    rows = [{"period": "day", "channel": "web", "amount": value}]

    with pytest.raises(ValueError, match=message):
        _aggregate(rows, aggregations=[{"op": "sum", "column": "amount"}])


@pytest.mark.parametrize("value", [None, True, math.inf, "3"])
def test_numeric_comparisons_reject_null_boolean_nonfinite_and_non_numeric_cells(value):
    rows = [{"period": "day", "channel": "web", "amount": value}]

    with pytest.raises(ValueError):
        _aggregate(
            rows,
            filters=[{"column": "amount", "op": "gte", "value": 1}],
            aggregations=[{"op": "count"}],
        )


def test_numeric_comparison_uses_finite_decimal_values():
    rows = [
        {"period": "day", "channel": "web", "amount": Decimal("1.20")},
        {"period": "day", "channel": "web", "amount": Decimal("2.30")},
    ]

    result = _aggregate(
        rows,
        filters=[{"column": "amount", "op": "gt", "value": 2}],
        aggregations=[{"op": "sum", "column": "amount"}],
    )

    assert result["matched_row_count"] == 1
    assert result["groups"][0]["aggregations"][0]["sum"] == "2.30"


def test_missing_columns_and_unsupported_raw_shapes_fail_instead_of_dropping_rows():
    with pytest.raises(ValueError, match="not declared"):
        _aggregate(
            [{"period": "day", "channel": "web", "amount": 1}],
            group_by=["unknown"],
        )

    with pytest.raises(ValueError, match="missing referenced columns"):
        _aggregate(
            [{"period": "day", "amount": 1}],
            group_by=["channel"],
        )

    with pytest.raises(ValueError, match="non-scalar"):
        _aggregate(
            [{"period": "day", "channel": ["web"], "amount": 1}],
            filters=[{"column": "channel", "op": "eq", "value": "web"}],
        )


def test_numeric_equality_does_not_treat_booleans_as_numbers():
    rows = [
        {"period": "day", "channel": "web", "amount": True},
        {"period": "day", "channel": "web", "amount": 1},
    ]

    result = _aggregate(
        rows,
        filters=[{"column": "amount", "op": "eq", "value": 1}],
        aggregations=[{"op": "count"}],
    )

    assert result["matched_row_count"] == 1
    assert result["groups"][0]["row_count"] == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"filters": [{"column": "channel", "op": "eq", "value": "web", "sql": "x"}]},
            "exactly column, op, and value",
        ),
        ({"group_by": ["period", "channel", "amount", "extra"]}, "at most 3"),
        (
            {"aggregations": [{"op": "sum", "column": "amount", "alias": "x"}]},
            "must be count or sum",
        ),
    ],
)
def test_filter_group_and_aggregation_schemas_are_strict(changes, message):
    kwargs = {
        "filters": [],
        "group_by": [],
        "aggregations": [{"op": "count"}],
    }
    kwargs.update(changes)

    with pytest.raises(ValueError, match=message):
        _aggregate(
            [{"period": "day", "channel": "web", "amount": 1}],
            **kwargs,
        )


def test_group_and_output_limits_fail_instead_of_returning_partial_results():
    rows = [
        {"period": "day", "channel": "web", "amount": 1},
        {"period": "day", "channel": "store", "amount": 2},
    ]

    with pytest.raises(ValueError, match="1-group bound"):
        _aggregate(rows, group_by=["channel"], max_groups=1)
    with pytest.raises(ValueError, match="output bound"):
        _aggregate(rows, max_output_bytes=20)
    with pytest.raises(ValueError, match="max_groups"):
        _aggregate(rows, max_groups=True)


def test_input_row_limit_is_checked_without_truncating():
    rows = [{"period": "day", "channel": "web", "amount": 1}] * (MAX_INPUT_ROWS + 1)

    with pytest.raises(ValueError, match="at most 20000 returned rows"):
        _aggregate(rows)


def test_request_and_source_provenance_are_deepcopied_in_result():
    filters = [{"column": "channel", "op": "eq", "value": "web"}]
    provenance = {"actual_sql": [{"query_index": 0, "sql": "select raw rows"}]}
    result = _aggregate(
        [{"period": "day", "channel": "web", "amount": 1}],
        filters=filters,
        query_provenance=provenance,
    )

    filters[0]["value"] = "store"
    provenance["actual_sql"][0]["sql"] = "mutated source"
    assert result["request"]["filters"][0]["value"] == "web"
    assert result["source_provenance"]["actual_sql"][0]["sql"] == "select raw rows"

    result["source_provenance"]["actual_sql"][0]["sql"] = "mutated result"
    assert provenance["actual_sql"][0]["sql"] == "mutated source"


def test_pre_io_validator_returns_normalized_request_and_referenced_columns():
    request = validate_aggregation_request(
        [{"column": "channel", "op": "eq", "value": "web"}],
        ["period"],
        [{"op": "sum", "column": "amount"}, {"op": "count"}],
        max_groups=7,
    )

    assert request == {
        "filters": [{"column": "channel", "op": "eq", "value": "web"}],
        "group_by": ["period"],
        "aggregations": [{"op": "sum", "column": "amount"}, {"op": "count"}],
        "max_groups": 7,
        "referenced_columns": ["period", "channel", "amount"],
    }


@pytest.mark.parametrize(
    ("filters", "group_by", "aggregations", "max_groups"),
    [
        (None, [], [{"op": "count"}], 100),
        ([{"column": "x", "op": "contains", "value": "a"}], [], [{"op": "count"}], 100),
        ([{"column": "x", "op": "eq", "value": {"x": 1}}], [], [{"op": "count"}], 100),
        ([{"column": "x", "op": "gte", "value": True}], [], [{"op": "count"}], 100),
        ([{"column": "x", "op": [], "value": 1}], [], [{"op": "count"}], 100),
        ([], ["x", True], [{"op": "count"}], 100),
        ([], [], [{"op": "sum", "column": 2}], 100),
        ([], [], [{"op": "count"}], True),
    ],
)
def test_pre_io_validator_rejects_invalid_request_without_source_rows(
    filters, group_by, aggregations, max_groups
):
    with pytest.raises(ValueError):
        validate_aggregation_request(
            filters,
            group_by,
            aggregations,
            max_groups=max_groups,
        )


def test_aggregator_uses_pre_io_request_validation_before_row_validation():
    with pytest.raises(ValueError, match="invalid column or operator"):
        aggregate_saved_chart_rows(
            rows=[],
            columns=[],
            filters=[{"column": "x", "op": "contains", "value": "a"}],
            group_by=[],
            aggregations=[{"op": "count"}],
        )

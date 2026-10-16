"""Bounded in-memory aggregation for rows already returned by a saved chart query.

This research-only helper never issues queries. Results describe only the supplied
returned rows; they do not imply full warehouse coverage. Filters compare raw
values (date strings are not parsed), duplicate rows remain separate, SUM skips
and reports nulls, and unsupported/non-finite values fail explicitly.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

MAX_INPUT_ROWS = 20_000
MAX_FILTERS = 12
MAX_AGGREGATIONS = 8
MAX_GROUPS = 1_000
MAX_OUTPUT_BYTES = 256_000
MAX_REQUEST_BYTES = 16_384
MAX_COLUMN_CHARS = 256
MAX_FILTER_STRING_CHARS = 2_048
_MAX_NUMERIC_DIGITS = 100
_MAX_NUMERIC_EXPONENT = 100
_DECIMAL_PRECISION = 512
_FILTER_OPERATORS = {"eq", "gt", "gte", "lt", "lte"}


def validate_aggregation_request(
    filters: list[dict[str, Any]],
    group_by: list[str],
    aggregations: list[dict[str, Any]],
    *,
    max_groups: int = 100,
) -> dict[str, Any]:
    """Validate source-independent arguments before any saved-chart query runs.

    Returns normalized request arguments and stable referenced column names. This
    does not check those names against a chart's source columns.
    """
    if type(filters) is not list or len(filters) > MAX_FILTERS:
        raise ValueError(f"filters must be a list of at most {MAX_FILTERS} definitions")
    if type(group_by) is not list or len(group_by) > 3:
        raise ValueError("group_by must be a list of at most 3 raw column names")
    if any(
        type(column) is not str or not column or len(column) > MAX_COLUMN_CHARS
        for column in group_by
    ) or len(set(group_by)) != len(group_by):
        raise ValueError("group_by must contain unique non-empty raw column names")
    if type(aggregations) is not list or not aggregations or len(aggregations) > MAX_AGGREGATIONS:
        raise ValueError(f"aggregations must contain 1 to {MAX_AGGREGATIONS} definitions")
    if type(max_groups) is not int or not 1 <= max_groups <= MAX_GROUPS:
        raise ValueError(f"max_groups must be an integer from 1 through {MAX_GROUPS}")

    normalized_filters = [_validate_filter(item, index) for index, item in enumerate(filters)]
    _json_bytes(filters, "filters")
    normalized_aggregations = [
        _validate_aggregation(item, index) for index, item in enumerate(aggregations)
    ]
    if (
        len(
            _json_bytes(
                {
                    "filters": filters,
                    "group_by": group_by,
                    "aggregations": aggregations,
                    "max_groups": max_groups,
                },
                "aggregation definitions",
            )
        )
        > MAX_REQUEST_BYTES
    ):
        raise ValueError(
            f"aggregation definitions exceed the {MAX_REQUEST_BYTES}-byte request bound"
        )
    referenced = list(group_by)
    for column in [item["column"] for item in normalized_filters] + [
        item["column"] for item in normalized_aggregations if item["op"] == "sum"
    ]:
        if column not in referenced:
            referenced.append(column)
    return {
        "filters": normalized_filters,
        "group_by": list(group_by),
        "aggregations": normalized_aggregations,
        "max_groups": max_groups,
        "referenced_columns": referenced,
    }


def aggregate_saved_chart_rows(
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    filters: list[dict[str, Any]],
    group_by: list[str],
    aggregations: list[dict[str, Any]],
    query_provenance: dict[str, Any] | None = None,
    max_groups: int = 100,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    """Filter and aggregate cached saved-chart rows without querying or coercion.

    Filters are ANDed. ``eq`` accepts JSON scalar values (including null); numeric
    comparisons require finite numbers. ``count`` counts matching rows, including
    duplicates and nulls. ``sum`` uses finite numeric values, skips nulls, and
    reports both counts. All referenced columns must exist in the declared column
    list and every input row. Results preserve the request definitions and source
    provenance, and fail rather than truncate when a configured bound is exceeded.
    """
    request = validate_aggregation_request(filters, group_by, aggregations, max_groups=max_groups)
    if type(rows) is not list or len(rows) > MAX_INPUT_ROWS:
        raise ValueError(f"rows must be a list of at most {MAX_INPUT_ROWS} returned rows")
    if (
        type(columns) is not list
        or any(type(column) is not str or not column for column in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("columns must be a unique list of non-empty raw column names")
    if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES:
        raise ValueError(f"max_output_bytes must be an integer from 1 through {MAX_OUTPUT_BYTES}")
    if query_provenance is None:
        query_provenance = {}
    if not isinstance(query_provenance, Mapping):
        raise ValueError("query_provenance must be an object")

    normalized_filters = request["filters"]
    normalized_aggregations = request["aggregations"]
    referenced = set(request["referenced_columns"])
    missing_declared = referenced - set(columns)
    if missing_declared:
        raise ValueError(
            f"referenced columns are not declared: {', '.join(sorted(missing_declared))}"
        )
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or any(type(key) is not str for key in row):
            raise ValueError(f"row {index} must be an object with string column names")
        missing = referenced - set(row)
        if missing:
            raise ValueError(
                f"row {index} is missing referenced columns: {', '.join(sorted(missing))}"
            )

    output_provenance = copy.deepcopy(dict(query_provenance))
    # Validate provenance before processing rows so invalid provider values never
    # become a partially computed result.
    _json_bytes(output_provenance, "query_provenance")
    groups: dict[tuple[tuple[type, Any], ...], dict[str, Any]] = {}
    matched_row_count = 0

    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        for row_index, row in enumerate(rows):
            filter_values = []
            for definition in normalized_filters:
                value = row[definition["column"]]
                if definition["op"] == "eq":
                    _validate_raw_scalar(value, definition["column"], row_index)
                elif _number(value, definition["column"], row_index, allow_null=False) is None:
                    raise ValueError("null cannot be used in a numeric comparison")
                filter_values.append(value)
            if not all(
                _matches(value, definition)
                for value, definition in zip(filter_values, normalized_filters, strict=True)
            ):
                continue

            key_values = tuple(row[column] for column in group_by)
            for column, value in zip(group_by, key_values, strict=True):
                _validate_group_value(value, column, row_index)
            identity = tuple((type(value), value) for value in key_values)
            group = groups.get(identity)
            if group is None:
                if len(groups) >= request["max_groups"]:
                    raise ValueError(
                        f"aggregation exceeded the {request['max_groups']}-group bound"
                    )
                group = {
                    "key_values": key_values,
                    "row_count": 0,
                    "sums": [Decimal(0) for _ in normalized_aggregations],
                    "value_counts": [0 for _ in normalized_aggregations],
                    "null_counts": [0 for _ in normalized_aggregations],
                }
                groups[identity] = group
            group["row_count"] += 1
            matched_row_count += 1
            for index, definition in enumerate(normalized_aggregations):
                if definition["op"] != "sum":
                    continue
                value = _number(row[definition["column"]], definition["column"], row_index)
                if value is None:
                    group["null_counts"][index] += 1
                else:
                    group["sums"][index] += value
                    group["value_counts"][index] += 1

    results = []
    for group in groups.values():
        aggregate_results = []
        for index, definition in enumerate(normalized_aggregations):
            if definition["op"] == "count":
                aggregate_results.append({"op": "count", "count": group["row_count"]})
            else:
                count = group["value_counts"][index]
                aggregate_results.append(
                    {
                        "op": "sum",
                        "column": definition["column"],
                        "sum": format(group["sums"][index], "f") if count else None,
                        "value_count": count,
                        "null_count": group["null_counts"][index],
                    }
                )
        results.append(
            {
                "key": dict(zip(group_by, group["key_values"], strict=True)),
                "row_count": group["row_count"],
                "aggregations": aggregate_results,
            }
        )

    result = {
        "scope": {
            "kind": "saved_chart_query_returned_rows",
            "input_row_count": len(rows),
            "warehouse_completeness": "unknown",
        },
        "request": {
            "filters": copy.deepcopy(filters),
            "group_by": copy.deepcopy(group_by),
            "aggregations": copy.deepcopy(aggregations),
        },
        "matched_row_count": matched_row_count,
        "groups": results,
        "source_provenance": output_provenance,
    }
    if len(_json_bytes(result, "aggregation result")) > max_output_bytes:
        raise ValueError(f"aggregation result exceeded the {max_output_bytes}-byte output bound")
    return result


def _validate_filter(item: Any, index: int) -> dict[str, Any]:
    if type(item) is not dict or set(item) != {"column", "op", "value"}:
        raise ValueError(f"filter {index} must contain exactly column, op, and value")
    column, operator, value = item["column"], item["op"], item["value"]
    if (
        type(column) is not str
        or not column
        or len(column) > MAX_COLUMN_CHARS
        or type(operator) is not str
        or operator not in _FILTER_OPERATORS
    ):
        raise ValueError(f"filter {index} has an invalid column or operator")
    if type(value) is str and len(value) > MAX_FILTER_STRING_CHARS:
        raise ValueError(
            f"filter {index} string exceeds the {MAX_FILTER_STRING_CHARS}-character bound"
        )
    if operator == "eq":
        _validate_raw_scalar(value, column, "filter")
    elif _number(value, column, "filter", allow_null=False) is None:
        raise ValueError(f"filter {index} numeric comparison requires a finite number")
    return {"column": column, "op": operator, "value": value}


def _validate_aggregation(item: Any, index: int) -> dict[str, Any]:
    if type(item) is not dict:
        raise ValueError(f"aggregation {index} must be an object")
    if item == {"op": "count"}:
        return {"op": "count"}
    if (
        set(item) != {"op", "column"}
        or item.get("op") != "sum"
        or type(item.get("column")) is not str
        or not item["column"]
        or len(item["column"]) > MAX_COLUMN_CHARS
    ):
        raise ValueError(f"aggregation {index} must be count or sum with one raw column")
    return {"op": "sum", "column": item["column"]}


def _validate_raw_scalar(value: Any, column: str, row_index: Any) -> None:
    if value is None or type(value) in (str, bool):
        return
    if type(value) in (int, float) or isinstance(value, Decimal):
        _number(value, column, row_index)
        return
    raise ValueError(f"column {column!r} has an unsupported non-scalar value at {row_index}")


def _validate_group_value(value: Any, column: str, row_index: int) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        _number(value, column, row_index)
        return
    raise ValueError(f"group column {column!r} has an unsupported value at row {row_index}")


def _number(value: Any, column: str, row_index: Any, *, allow_null: bool = True) -> Decimal | None:
    if value is None and allow_null:
        return None
    if value is None:
        raise ValueError(f"column {column!r} is null at {row_index}")
    if type(value) is bool or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"column {column!r} has a non-numeric value at {row_index}")
    if type(value) is float and not math.isfinite(value):
        raise ValueError(f"column {column!r} has a non-finite number at {row_index}")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"column {column!r} has an invalid number at {row_index}") from None
    if not number.is_finite():
        raise ValueError(f"column {column!r} has a non-finite number at {row_index}")
    parts = number.as_tuple()
    if len(parts.digits) > _MAX_NUMERIC_DIGITS or abs(parts.exponent) > _MAX_NUMERIC_EXPONENT:
        raise ValueError(
            f"column {column!r} exceeds the supported numeric precision at {row_index}"
        )
    return number


def _matches(value: Any, definition: dict[str, Any]) -> bool:
    expected = definition["value"]
    operator = definition["op"]
    if operator == "eq":
        if value is None or expected is None:
            return value is None and expected is None
        if type(value) is bool or type(expected) is bool:
            return type(value) is type(expected) and value == expected
        if isinstance(value, (int, float, Decimal)) and isinstance(expected, (int, float)):
            return _number(value, definition["column"], "filter") == _number(
                expected, definition["column"], "filter"
            )
        return type(value) is type(expected) and value == expected
    actual = _number(value, definition["column"], "filter", allow_null=False)
    target = _number(expected, definition["column"], "filter", allow_null=False)
    if operator == "gt":
        return actual > target
    if operator == "gte":
        return actual >= target
    if operator == "lt":
        return actual < target
    return actual <= target


def _json_bytes(value: Any, label: str) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must contain only finite JSON-compatible values") from None

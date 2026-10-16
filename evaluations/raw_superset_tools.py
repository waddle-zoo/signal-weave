"""Bounded, research-only raw Superset tools shared by evaluation arms.

This module is intentionally outside the SignalWeave service import path. It
executes only saved Superset charts and exposes their returned rows without
assigning business meaning to fields or values.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from signalweave.superset_client import SupersetClient

MAX_CHART_ROWS = 20_000
MAX_PAGE_SIZE = 250
MAX_QUERY_LENGTH = 2_000
MAX_RESOURCE_ID = 2**63 - 1


class RawSupersetTools:
    """Research tools for saved dashboard and chart inspection.

    Query results are fetched once per chart for this helper instance. Cache
    entries retain deep copies of the original provider envelopes, and every
    returned value is copied again so a caller cannot mutate later pages.
    """

    def __init__(self, client: SupersetClient) -> None:
        self.client = client
        self.logical_tool_calls = 0
        self.chart_query_http_requests = 0
        self._chart_cache: dict[str, dict[str, Any]] = {}

    @property
    def telemetry(self) -> dict[str, int]:
        """Return tool-call and provider-query counts as separate measures."""

        return {
            "logical_tool_calls": self.logical_tool_calls,
            "chart_query_http_requests": self.chart_query_http_requests,
        }

    async def specs(self) -> list[dict[str, Any]]:
        """Return the same bounded tool schemas to either evaluation arm."""

        return copy.deepcopy(
            [
                {
                    "name": "find_dashboards",
                    "description": "Search Superset dashboard titles; returns at most 10 matches.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "maxLength": MAX_QUERY_LENGTH,
                            }
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "list_dashboard_charts",
                    "description": (
                        "List chart IDs, titles, and descriptions on a dashboard. "
                        "Does not return chart data."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"id": {"type": "string", "pattern": "^[1-9][0-9]*$"}},
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "read_chart_rows",
                    "description": (
                        "Read one page from the saved chart query result. Pages share a cached "
                        "query result. The row count covers returned query rows; warehouse "
                        "completeness is unknown."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "pattern": "^[1-9][0-9]*$"},
                            "offset": {"type": "integer", "minimum": 0, "default": 0},
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_PAGE_SIZE,
                                "default": 100,
                            },
                        },
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "profile_saved_chart",
                    "description": (
                        "Profile raw values returned by a saved chart query using numeric and "
                        "raw date ranges only; no sums, means, or inferred metric meanings."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"id": {"type": "string", "pattern": "^[1-9][0-9]*$"}},
                        "required": ["id"],
                        "additionalProperties": False,
                    },
                },
            ]
        )

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a research tool call after strict argument validation."""

        self.logical_tool_calls += 1
        if not isinstance(arguments, Mapping):
            raise ValueError("Tool arguments must be an object")

        if name == "find_dashboards":
            self._validate_keys(arguments, {"query"})
            query = arguments.get("query")
            if not isinstance(query, str) or len(query) > MAX_QUERY_LENGTH:
                raise ValueError("query must be a string of at most 2000 characters")
            return await self._find_dashboards(query)

        if name == "list_dashboard_charts":
            self._validate_keys(arguments, {"id"})
            dashboard_id = self._resource_id(arguments.get("id"), "dashboard")
            return await self._list_dashboard_charts(dashboard_id)

        if name == "read_chart_rows":
            self._validate_keys(arguments, {"id"}, {"offset", "limit"})
            chart_id = self._resource_id(arguments.get("id"), "chart")
            offset = self._page_integer(
                arguments.get("offset", 0), "offset", 0, MAX_CHART_ROWS
            )
            limit = self._page_integer(arguments.get("limit", 100), "limit", 1, MAX_PAGE_SIZE)
            return await self._read_chart_rows(chart_id, offset, limit)

        if name == "profile_saved_chart":
            self._validate_keys(arguments, {"id"})
            chart_id = self._resource_id(arguments.get("id"), "chart")
            return await self._profile_saved_chart(chart_id)

        raise ValueError("Unknown raw Superset tool")

    @staticmethod
    def _validate_keys(
        arguments: Mapping[str, Any], required: set[str], optional: set[str] | None = None
    ) -> None:
        allowed = required | (optional or set())
        if required - set(arguments) or set(arguments) - allowed:
            raise ValueError("Tool arguments do not match the declared schema")

    @staticmethod
    def _resource_id(value: Any, kind: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) > 19
            or re.fullmatch(r"[1-9][0-9]*", value) is None
        ):
            raise ValueError(f"{kind} id must be a positive decimal string")
        parsed = int(value)
        if parsed < 1 or parsed > MAX_RESOURCE_ID:
            raise ValueError(f"{kind} id must be a positive decimal string")
        return str(parsed)

    @staticmethod
    def _page_integer(value: Any, name: str, minimum: int, maximum: int | None) -> int:
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            if maximum is None:
                raise ValueError(f"{name} must be an integer of at least {minimum}")
            raise ValueError(f"{name} must be an integer from {minimum} through {maximum}")
        return value

    async def _find_dashboards(self, query: str) -> dict[str, Any]:
        try:
            dashboards, provider_count = await self.client.list_dashboards_page(
                page=0, page_size=10, query=query
            )
        except Exception:
            raise ValueError("Superset dashboard search failed") from None

        results = []
        for item in dashboards:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            try:
                dashboard_id = self._resource_id(str(raw_id), "dashboard")
            except ValueError:
                continue
            results.append(
                {
                    "id": dashboard_id,
                    "title": item.get("dashboard_title", item.get("title")),
                    "description": item.get("description"),
                }
            )
        return {
            "dashboards": copy.deepcopy(results),
            "provider_count": provider_count,
            "returned_count": len(results),
            "limit": 10,
        }

    async def _list_dashboard_charts(self, dashboard_id: str) -> dict[str, Any]:
        try:
            response = await self.client._request(
                "GET", f"/api/v1/dashboard/{dashboard_id}/charts", timeout=30
            )
            payload = response.json()
        except Exception:
            raise ValueError("Superset dashboard chart listing failed") from None

        result = payload.get("result", payload) if isinstance(payload, dict) else payload
        if isinstance(result, dict):
            result = result.get("charts", result.get("result"))
        if not isinstance(result, list):
            raise ValueError("Superset dashboard chart response had an unsupported shape")

        charts = []
        for item in result:
            if not isinstance(item, dict):
                continue
            try:
                chart_id = self._resource_id(str(item.get("id")), "chart")
            except ValueError:
                raise ValueError("Superset dashboard chart response contained an invalid id") from None
            charts.append(
                {
                    "id": chart_id,
                    "title": item.get("slice_name", item.get("title")),
                    "description": item.get("description"),
                }
            )
        return {"dashboard_id": dashboard_id, "charts": copy.deepcopy(charts)}

    async def _load_chart(self, chart_id: str) -> tuple[dict[str, Any], bool]:
        cached = self._chart_cache.get(chart_id)
        if cached is not None:
            return copy.deepcopy(cached), True

        try:
            metadata = await self.client.get_chart_metadata(chart_id)
        except Exception:
            raise ValueError("Superset saved chart metadata could not be read") from None
        if not isinstance(metadata, dict):
            raise ValueError("Superset saved chart metadata had an unsupported shape")
        try:
            returned_id = self._resource_id(str(metadata.get("id")), "chart")
        except ValueError:
            raise ValueError("Superset saved chart metadata contained an invalid id") from None
        if returned_id != chart_id:
            raise ValueError("Superset saved chart metadata did not match the requested id")

        request_count_before = self._client_request_count()
        try:
            envelopes = await self.client.chart_data(copy.deepcopy(metadata))
        except Exception:
            self._count_chart_query_requests(request_count_before)
            raise ValueError("Superset saved chart query failed") from None
        self._count_chart_query_requests(request_count_before)

        if not isinstance(envelopes, list) or any(not isinstance(item, dict) for item in envelopes):
            raise ValueError("Superset saved chart query returned an unsupported envelope")
        original_envelopes = copy.deepcopy(envelopes)
        try:
            rows = [
                row
                for envelope in original_envelopes
                for row in self.client._rows_from_result_item(envelope)
            ]
        except Exception:
            raise ValueError("Superset saved chart rows could not be normalized") from None
        if len(rows) > MAX_CHART_ROWS:
            raise ValueError("Superset saved chart query exceeded the 20000-row bound")

        entry = {
            "metadata": copy.deepcopy(metadata),
            "envelopes": original_envelopes,
            "rows": copy.deepcopy(rows),
            "columns": self._columns(original_envelopes, rows),
        }
        self._chart_cache[chart_id] = copy.deepcopy(entry)
        return copy.deepcopy(entry), False

    def _client_request_count(self) -> int | None:
        try:
            value = self.client.requests_made
        except Exception:
            return None
        return value if type(value) is int and value >= 0 else None

    def _count_chart_query_requests(self, before: int | None) -> None:
        after = self._client_request_count()
        if before is not None and after is not None:
            self.chart_query_http_requests += max(0, after - before)
        else:
            # A small fake client may not expose HTTP request telemetry. In
            # that case, one chart_data invocation represents one query call.
            self.chart_query_http_requests += 1

    @staticmethod
    def _columns(
        envelopes: list[dict[str, Any]], rows: list[dict[str, Any]]
    ) -> list[str]:
        result: list[str] = []
        for envelope in envelopes:
            nested = envelope.get("data")
            candidates = [envelope.get("colnames")]
            if isinstance(nested, dict):
                candidates.extend((nested.get("colnames"), nested.get("columns")))
            for columns in candidates:
                if isinstance(columns, list):
                    for column in columns:
                        if isinstance(column, str) and column not in result:
                            result.append(column)
        for row in rows:
            for column in row:
                name = str(column)
                if name not in result:
                    result.append(name)
        return result

    async def _read_chart_rows(
        self, chart_id: str, offset: int, limit: int
    ) -> dict[str, Any]:
        entry, cache_hit = await self._load_chart(chart_id)
        rows = entry["rows"]
        page = copy.deepcopy(rows[offset : offset + limit])
        page_end = offset + len(page)
        has_more = page_end < len(rows)
        metadata = entry["metadata"]
        return {
            "chart_id": chart_id,
            "query_definition": self._query_definition(metadata),
            "actual_sql": self._actual_sql(entry["envelopes"]),
            "columns": copy.deepcopy(entry["columns"]),
            "rows": page,
            "offset": offset,
            "limit": limit,
            "total_query_row_count": len(rows),
            "next_offset": page_end if has_more else None,
            "has_more_returned_rows": has_more,
            "query_scope": {
                "kind": "saved_chart_query",
                "dashboard_filters_applied": False,
                "warehouse_completeness": "unknown",
            },
            "declared_row_limits": self._declared_row_limits(metadata),
            "provider_row_counts": self._provider_row_counts(entry["envelopes"]),
            "telemetry": self._call_telemetry(cache_hit),
        }

    async def _profile_saved_chart(self, chart_id: str) -> dict[str, Any]:
        entry, cache_hit = await self._load_chart(chart_id)
        metadata = entry["metadata"]
        rows = entry["rows"]
        return {
            "chart_id": chart_id,
            "query_definition": self._query_definition(metadata),
            "actual_sql": self._actual_sql(entry["envelopes"]),
            "columns": copy.deepcopy(entry["columns"]),
            "returned_rowcount": len(rows),
            "provider_row_counts": self._provider_row_counts(entry["envelopes"]),
            "declared_row_limits": self._declared_row_limits(metadata),
            "numeric_ranges": self._numeric_ranges(rows, entry["columns"]),
            "date_ranges": self._date_ranges(metadata, rows, entry["columns"]),
            "query_scope": {
                "kind": "saved_chart_query",
                "dashboard_filters_applied": False,
                "warehouse_completeness": "unknown",
            },
            "telemetry": self._call_telemetry(cache_hit),
        }

    def _call_telemetry(self, cache_hit: bool) -> dict[str, int | bool]:
        return {
            **self.telemetry,
            "chart_query_cache_hit": cache_hit,
        }

    @staticmethod
    def _query_definition(metadata: dict[str, Any]) -> dict[str, Any]:
        definition: dict[str, Any] = {"chart_id": str(metadata["id"])}
        for key in (
            "slice_name",
            "title",
            "description",
            "viz_type",
            "datasource_id",
            "datasource_type",
            "params",
            "query_context",
        ):
            if key in metadata:
                definition[key] = copy.deepcopy(metadata[key])
        return definition

    @staticmethod
    def _actual_sql(envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actual_sql = []
        for index, envelope in enumerate(envelopes):
            sql = envelope.get("query", envelope.get("sql"))
            nested = envelope.get("data")
            if not isinstance(sql, str) and isinstance(nested, dict):
                sql = nested.get("query", nested.get("sql"))
            if isinstance(sql, str):
                actual_sql.append({"query_index": index, "sql": sql})
        return actual_sql

    @staticmethod
    def _provider_row_counts(envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts = []
        for index, envelope in enumerate(envelopes):
            values: dict[str, Any] = {"query_index": index}
            for key in ("sql_rowcount", "rowcount"):
                if key in envelope:
                    values[key] = copy.deepcopy(envelope[key])
            nested = envelope.get("data")
            if isinstance(nested, dict):
                for key in ("sql_rowcount", "rowcount"):
                    if key not in values and key in nested:
                        values[key] = copy.deepcopy(nested[key])
            if len(values) > 1:
                counts.append(values)
        return counts

    @staticmethod
    def _saved_params(metadata: dict[str, Any]) -> dict[str, Any]:
        params = metadata.get("params")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                return {}
        return params if isinstance(params, dict) else {}

    @classmethod
    def _declared_row_limits(cls, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        context = metadata.get("query_context")
        if isinstance(context, str):
            try:
                context = json.loads(context)
            except json.JSONDecodeError:
                context = None
        if isinstance(context, dict) and isinstance(context.get("queries"), list):
            return [
                {
                    "query_index": index,
                    "declared": isinstance(query, dict) and "row_limit" in query,
                    "row_limit": copy.deepcopy(query.get("row_limit"))
                    if isinstance(query, dict) and "row_limit" in query
                    else None,
                }
                for index, query in enumerate(context["queries"])
            ]
        params = cls._saved_params(metadata)
        return (
            [
                {
                    "query_index": 0,
                    "declared": True,
                    "row_limit": copy.deepcopy(params["row_limit"]),
                }
            ]
            if "row_limit" in params
            else []
        )

    @staticmethod
    def _numeric_ranges(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        row_count = len(rows)
        for column in columns:
            values = [row[column] for row in rows if column in row]
            finite = [
                value
                for value in values
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and (not isinstance(value, float) or math.isfinite(value))
            ]
            if not finite:
                continue
            result[column] = {
                "min": min(finite),
                "max": max(finite),
                "null_count": sum(value is None for value in values),
                "missing_count": row_count - len(values),
                "finite_numeric_count": len(finite),
            }
        return result

    @classmethod
    def _date_ranges(
        cls, metadata: dict[str, Any], rows: list[dict[str, Any]], columns: list[str]
    ) -> dict[str, Any]:
        params = cls._saved_params(metadata)
        candidates: set[str] = set()
        granularity = params.get("granularity_sqla")
        if isinstance(granularity, str) and granularity:
            candidates.add(granularity)
        all_columns = params.get("all_columns")
        if isinstance(all_columns, list):
            candidates.update(
                column
                for column in all_columns
                if isinstance(column, str)
                and any(token in column.lower() for token in ("date", "time", "timestamp"))
            )

        ranges: dict[str, Any] = {}
        for column in columns:
            if column not in candidates:
                continue
            present = [row[column] for row in rows if column in row]
            non_null = [value for value in present if value is not None]
            safe_raw_values = [
                value
                for value in non_null
                if isinstance(value, str)
                or (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and (not isinstance(value, float) or math.isfinite(value))
                )
            ]
            raw_min = raw_max = None
            range_status = "no_comparable_values"
            if safe_raw_values:
                try:
                    raw_min = min(safe_raw_values)
                    raw_max = max(safe_raw_values)
                    range_status = "raw_values"
                except TypeError:
                    range_status = "mixed_raw_types"
            ranges[column] = {
                "raw_min": raw_min,
                "raw_max": raw_max,
                "range_status": range_status,
                "null_count": sum(value is None for value in present),
                "missing_count": len(rows) - len(present),
            }
        return ranges

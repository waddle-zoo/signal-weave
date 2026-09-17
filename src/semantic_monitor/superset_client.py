from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

import httpx

from .models import ChartSnapshot, DashboardSnapshot, Observation


class SupersetClient:
    """Small read-only Superset adapter.

    The client only executes the query definition already attached to a saved
    Superset chart. It does not accept or generate arbitrary SQL.
    """

    def __init__(
        self, base_url: str, username: str | None = None, password: str | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()

    async def _auth_headers(self, force_refresh: bool = False) -> dict[str, str]:
        if self._token and not force_refresh:
            return {"Authorization": f"Bearer {self._token}"}
        if not self.username or not self.password:
            return {}
        async with self._auth_lock:
            if self._token and not force_refresh:
                return {"Authorization": f"Bearer {self._token}"}
            async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
                response = await client.post(
                    "/api/v1/security/login",
                    json={
                        "username": self.username,
                        "password": self.password,
                        "provider": "db",
                        "refresh": True,
                    },
                )
                response.raise_for_status()
                self._token = response.json()["access_token"]
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=headers
        ) as client:
            response = await client.request(method, path, **kwargs)
            if response.status_code == 401 and self._token and self.username and self.password:
                self._token = None
                refreshed_headers = await self._auth_headers(force_refresh=True)
                response = await client.request(method, path, headers=refreshed_headers, **kwargs)
            response.raise_for_status()
            return response

    async def health(self) -> bool:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            response = await client.get("/health")
            return response.is_success

    async def get_dashboard_metadata(self, dashboard_id: int | str) -> dict[str, Any]:
        response = await self._request("GET", f"/api/v1/dashboard/{dashboard_id}", timeout=30)
        return response.json().get("result", response.json())

    async def get_chart_metadata(self, chart_id: int | str) -> dict[str, Any]:
        response = await self._request("GET", f"/api/v1/chart/{chart_id}", timeout=30)
        return response.json().get("result", response.json())

    async def list_dashboards(
        self, page: int = 0, page_size: int = 100, max_pages: int = 100
    ) -> list[dict[str, Any]]:
        """List dashboards across Superset pages, bounded to a safe maximum.

        A dashboard catalog is often larger than one API page. The MCP-facing
        default walks up to 10,000 dashboards while callers can still request
        a smaller bounded scan by lowering ``max_pages``.
        """
        if page < 0 or page_size <= 0 or max_pages <= 0:
            raise ValueError("page must be non-negative; page_size and max_pages must be positive")
        dashboards: list[dict[str, Any]] = []
        for current_page in range(page, page + max_pages):
            response = await self._request(
                "GET",
                "/api/v1/dashboard/",
                timeout=30,
                params={"page": current_page, "page_size": page_size},
            )
            result = response.json()
            batch = result.get("result", [])
            if not isinstance(batch, list):
                break
            dashboards.extend(item for item in batch if isinstance(item, dict))
            count = result.get("count")
            if not batch or len(batch) < page_size or (
                isinstance(count, int) and (current_page + 1) * page_size >= count
            ):
                break
        return dashboards

    @staticmethod
    def _params(chart: dict[str, Any]) -> dict[str, Any]:
        params = chart.get("params", {})
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = {}
        return dict(params)

    @staticmethod
    def _chart_filters(params: dict[str, Any]) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        for item in params.get("adhoc_filters", []):
            if not isinstance(item, dict):
                continue
            operator = item.get("operator") or item.get("op")
            subject = item.get("subject") or item.get("col")
            comparator = item.get("comparator", item.get("val"))
            if not operator or not subject or comparator in (None, "No filter"):
                continue
            filters.append({"col": subject, "op": operator, "val": comparator})
        return filters

    @staticmethod
    def _bounded_int(
        params: dict[str, Any], key: str, default: int, minimum: int, maximum: int
    ) -> int:
        try:
            value = int(params.get(key) or default)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    @classmethod
    def _query_context(cls, chart: dict[str, Any]) -> dict[str, Any]:
        """Build a bounded chart-data request from a saved chart definition."""
        params = cls._params(chart)
        metrics = params.get("metrics")
        if not metrics and params.get("metric"):
            metrics = [params["metric"]]
        groupby = params.get("groupby") or params.get("columns") or []
        granularity = (
            params.get("granularity")
            or params.get("granularity_sqla")
            or params.get("x_axis")
        )
        columns = list(params.get("columns") or groupby)
        if params.get("time_grain_sqla") and granularity and granularity not in columns:
            columns.insert(0, granularity)
        extras = {}
        if params.get("time_grain_sqla"):
            extras["time_grain_sqla"] = params["time_grain_sqla"]
        form_data = dict(params)
        form_data["slice_id"] = chart.get("id")
        return {
            "datasource": {
                "id": chart.get("datasource_id"),
                "type": chart.get("datasource_type", "table"),
            },
            "force": False,
            "queries": [
                {
                    "time_range": params.get("time_range") or "No filter",
                    "granularity": granularity,
                    "metrics": metrics or [],
                    "filters": cls._chart_filters(params),
                    "extras": extras,
                    "applied_time_extras": {},
                    "columns": columns,
                    "orderby": [],
                    "annotation_layers": [],
                    "row_limit": cls._bounded_int(params, "row_limit", 10000, 1, 10000),
                    "series_limit": cls._bounded_int(params, "series_limit", 0, 0, 1000),
                    "order_desc": True,
                    "url_params": {},
                    "custom_params": {},
                    "custom_form_data": {},
                    "post_processing": [],
                }
            ],
            "form_data": form_data,
            "result_format": "json",
            "result_type": "full",
        }

    @classmethod
    def _saved_query_context(cls, chart: dict[str, Any]) -> dict[str, Any] | None:
        saved = chart.get("query_context")
        if not saved:
            return None
        if isinstance(saved, str):
            try:
                saved = json.loads(saved)
            except json.JSONDecodeError:
                return None
        if not isinstance(saved, dict):
            return None
        context = dict(saved)
        context["force"] = False
        context["result_format"] = "json"
        context["result_type"] = "full"
        queries = context.get("queries")
        if isinstance(queries, list):
            bounded_queries: list[dict[str, Any]] = []
            for query in queries:
                if not isinstance(query, dict):
                    continue
                bounded_query = dict(query)
                bounded_query["row_limit"] = cls._bounded_int(
                    bounded_query, "row_limit", 10000, 1, 10000
                )
                bounded_query["series_limit"] = cls._bounded_int(
                    bounded_query, "series_limit", 0, 0, 1000
                )
                bounded_queries.append(bounded_query)
            context["queries"] = bounded_queries
        return context

    async def chart_data(self, chart: dict[str, Any]) -> list[dict[str, Any]]:
        payload = self._saved_query_context(chart) or self._query_context(chart)
        response = await self._request("POST", "/api/v1/chart/data", timeout=60, json=payload)
        return response.json().get("result", [])

    @staticmethod
    def _numeric_keys(rows: Iterable[dict[str, Any]]) -> list[str]:
        counts: dict[str, int] = {}
        for row in rows:
            for key, value in row.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    counts[key] = counts.get(key, 0) + 1
        return [key for key, _ in sorted(counts.items(), key=lambda item: -item[1])]

    @classmethod
    def _metric_key(cls, chart: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
        params = cls._params(chart)
        candidates: list[str] = []
        metrics = params.get("metrics") or ([params["metric"]] if params.get("metric") else [])
        for metric in metrics:
            if isinstance(metric, str):
                candidates.append(metric)
            elif isinstance(metric, dict):
                label = metric.get("label")
                column = metric.get("column", {})
                if label:
                    candidates.append(str(label))
                if isinstance(column, dict) and column.get("column_name"):
                    candidates.append(str(column["column_name"]))
        numeric_keys = cls._numeric_keys(rows)
        for candidate in candidates:
            if candidate in numeric_keys:
                return candidate
        granularity = {
            params.get("granularity"),
            params.get("granularity_sqla"),
            params.get("x_axis"),
        }
        fallback = [key for key in numeric_keys if key not in granularity]
        return fallback[0] if len(fallback) == 1 else None

    @classmethod
    def _time_key(cls, chart: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
        params = cls._params(chart)
        for candidate in (
            params.get("granularity"),
            params.get("granularity_sqla"),
            params.get("x_axis"),
        ):
            if candidate and any(candidate in row for row in rows):
                return candidate
        return None

    @staticmethod
    def _sort_value(value: Any) -> tuple[int, Any]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return (0, float(value))
        return (1, str(value))

    @classmethod
    def _observations_from_result(
        cls, chart: dict[str, Any], result: dict[str, Any]
    ) -> list[Observation]:
        rows = [row for row in result.get("data", []) if isinstance(row, dict)]
        if not rows:
            return []
        metric_key = cls._metric_key(chart, rows)
        if metric_key is None:
            return []
        values = [row[metric_key] for row in rows if isinstance(row.get(metric_key), (int, float))]
        time_key = cls._time_key(chart, rows)
        values_by_time: dict[Any, float] = {}
        if time_key:
            for row in rows:
                time_value = row.get(time_key)
                metric_value = row.get(metric_key)
                if time_value is not None and isinstance(metric_value, (int, float)):
                    values_by_time[time_value] = values_by_time.get(time_value, 0.0) + float(metric_value)
        ordered_values = [
            values_by_time[key] for key in sorted(values_by_time, key=cls._sort_value)
        ]
        comparable_values = ordered_values if len(ordered_values) >= 2 else values
        current = float(comparable_values[-1]) if comparable_values else None
        baseline = float(comparable_values[-2]) if len(comparable_values) > 1 else None
        change_pct = None
        if current is not None and baseline not in (None, 0):
            change_pct = round((current - baseline) / abs(baseline) * 100, 3)
        dimensions: dict[str, float] = {}
        if len(rows) > 1 and baseline is None:
            dimension_candidates = [
                key for key in rows[0] if key not in {metric_key, time_key}
            ]
            for row in rows[:25]:
                label = next(
                    (
                        str(value)
                        for key, value in row.items()
                        if key in dimension_candidates
                        and not isinstance(value, (int, float, bool))
                    ),
                    None,
                )
                if label is not None and isinstance(row.get(metric_key), (int, float)):
                    dimensions[label] = float(row[metric_key])
        return [
            Observation(
                chart_id=str(chart.get("id")),
                chart_title=str(chart.get("slice_name") or chart.get("id")),
                metric=metric_key,
                current=current,
                baseline=baseline,
                change_pct=change_pct,
                dimensions=dimensions,
                source_url=chart.get("url"),
            )
        ]

    @classmethod
    def observations_from_chart_data(
        cls, chart: dict[str, Any], result: list[dict[str, Any]]
    ) -> list[Observation]:
        observations: list[Observation] = []
        for item in result:
            observations.extend(cls._observations_from_result(chart, item))
        return observations

    async def dashboard_snapshot(
        self,
        dashboard_id: int | str,
        include_data: bool = True,
        chart_ids: list[str] | None = None,
    ) -> DashboardSnapshot:
        metadata = await self.get_dashboard_metadata(dashboard_id)
        snapshot = self.metadata_to_snapshot(metadata)
        if not include_data:
            return snapshot

        selected = set(chart_ids) if chart_ids else None
        if selected is not None:
            snapshot = snapshot.model_copy(
                update={"charts": [chart for chart in snapshot.charts if chart.id in selected]}
            )

        semaphore = asyncio.Semaphore(8)

        async def load_chart(chart: ChartSnapshot) -> ChartSnapshot:
            async with semaphore:
                try:
                    chart_metadata = await self.get_chart_metadata(chart.id)
                    observations = self.observations_from_chart_data(
                        chart_metadata, await self.chart_data(chart_metadata)
                    )
                    if not observations:
                        raise ValueError("no unambiguous numeric metric observation was returned")
                    return chart.model_copy(update={"observations": observations})
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                    return chart.model_copy(
                        update={
                            "error": f"Data unavailable from Superset: {error}",
                            "description": f"Data unavailable from Superset: {error}",
                        }
                    )

        charts = await asyncio.gather(*(load_chart(chart) for chart in snapshot.charts))
        return snapshot.model_copy(update={"charts": charts})

    @staticmethod
    def metadata_to_snapshot(metadata: dict[str, Any]) -> DashboardSnapshot:
        """Map stable dashboard metadata into a safe inspection snapshot."""
        position = metadata.get("position_json", {})
        if isinstance(position, str):
            try:
                position = json.loads(position)
            except json.JSONDecodeError:
                position = {}
        charts: list[ChartSnapshot] = []
        for item in position.values() if isinstance(position, dict) else []:
            if not isinstance(item, dict) or item.get("type") != "CHART":
                continue
            chart_id = item.get("meta", {}).get("chartId")
            if chart_id is None:
                continue
            charts.append(
                ChartSnapshot(
                    id=str(chart_id),
                    title=str(
                        item.get("meta", {}).get("sliceNameOverride")
                        or item.get("meta", {}).get("sliceName")
                        or chart_id
                    ),
                    metric="unknown",
                )
            )
        return DashboardSnapshot(
            id=str(metadata.get("id")),
            title=metadata.get("dashboard_title")
            or "Untitled dashboard",
            description=metadata.get("description") or "",
            owners=[
                str(owner.get("username", owner)) if isinstance(owner, dict) else str(owner)
                for owner in metadata.get("owners", [])
            ],
            charts=charts,
            source_url=metadata.get("url"),
        )

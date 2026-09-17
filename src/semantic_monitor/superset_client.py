from __future__ import annotations

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

    async def _auth_headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        if not self.username or not self.password:
            return {}
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

    async def health(self) -> bool:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            response = await client.get("/health")
            return response.is_success

    async def get_dashboard_metadata(self, dashboard_id: int | str) -> dict[str, Any]:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30, headers=headers) as client:
            response = await client.get(f"/api/v1/dashboard/{dashboard_id}")
            response.raise_for_status()
            return response.json().get("result", response.json())

    async def get_chart_metadata(self, chart_id: int | str) -> dict[str, Any]:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30, headers=headers) as client:
            response = await client.get(f"/api/v1/chart/{chart_id}")
            response.raise_for_status()
            return response.json().get("result", response.json())

    async def list_dashboards(self, page: int = 0, page_size: int = 100) -> list[dict[str, Any]]:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30, headers=headers) as client:
            response = await client.get(
                "/api/v1/dashboard/", params={"page": page, "page_size": page_size}
            )
            response.raise_for_status()
            result = response.json()
            return result.get("result", [])

    @staticmethod
    def _query_context(chart: dict[str, Any]) -> dict[str, Any]:
        """Build a bounded chart-data request from a saved chart definition."""
        params = chart.get("params", {})
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = {}
        params = dict(params)
        metrics = params.get("metrics")
        if not metrics and params.get("metric"):
            metrics = [params["metric"]]
        groupby = params.get("groupby") or params.get("columns") or []
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
                    "granularity": params.get("granularity_sqla") or params.get("x_axis"),
                    "metrics": metrics or [],
                    "filters": [],
                    "extras": {},
                    "applied_time_extras": {},
                    "columns": groupby,
                    "orderby": [],
                    "annotation_layers": [],
                    "row_limit": int(params.get("row_limit") or 10000),
                    "series_limit": int(params.get("series_limit") or 0),
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

    async def chart_data(self, chart: dict[str, Any]) -> list[dict[str, Any]]:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60, headers=headers) as client:
            response = await client.post("/api/v1/chart/data", json=self._query_context(chart))
            response.raise_for_status()
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
    def _observations_from_result(
        cls, chart: dict[str, Any], result: dict[str, Any]
    ) -> list[Observation]:
        rows = [row for row in result.get("data", []) if isinstance(row, dict)]
        if not rows:
            return []
        numeric_keys = cls._numeric_keys(rows)
        if not numeric_keys:
            return []
        metric_key = numeric_keys[0]
        values = [row[metric_key] for row in rows if isinstance(row.get(metric_key), (int, float))]
        current = float(values[-1]) if values else None
        baseline = float(values[-2]) if len(values) > 1 else None
        change_pct = None
        if current is not None and baseline not in (None, 0):
            change_pct = round((current - baseline) / abs(baseline) * 100, 3)
        dimensions: dict[str, float] = {}
        if len(rows) > 1 and baseline is None:
            for row in rows[:25]:
                label = next(
                    (
                        str(value)
                        for key, value in row.items()
                        if key != metric_key and not isinstance(value, (int, float, bool))
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

        charts: list[ChartSnapshot] = []
        for chart in snapshot.charts:
            try:
                chart_metadata = await self.get_chart_metadata(chart.id)
                observations = self.observations_from_chart_data(
                    chart_metadata, await self.chart_data(chart_metadata)
                )
                charts.append(chart.model_copy(update={"observations": observations}))
            except httpx.HTTPError as error:
                charts.append(
                    chart.model_copy(
                        update={"description": f"Data unavailable from Superset: {error}"}
                    )
                )
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

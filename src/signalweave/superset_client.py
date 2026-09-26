from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from .models import Observation
from .superset_models import SupersetChartSnapshot, SupersetDashboardSnapshot


@dataclass(frozen=True)
class ChartObservationExtraction:
    """Normalized chart evidence plus an explicit semantic quality result.

    The extractor is intentionally chart-type agnostic.  It does not pretend
    that every numeric field has the same meaning: when a chart omits an
    explicit metric definition, all numeric fields are retained and the result
    is marked ``partial`` so callers can require review instead of silently
    losing a signal or inventing a total.
    """

    observations: list[Observation]
    metrics: list[str]
    semantic_status: str
    notes: list[str]
    row_count: int = 0
    columns: list[str] | None = None


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
        self,
        page: int = 0,
        page_size: int = 100,
        max_pages: int = 100,
        query: str | None = None,
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
            batch, count = await self.list_dashboards_page(
                page=current_page, page_size=page_size, query=query
            )
            dashboards.extend(item for item in batch if isinstance(item, dict))
            if not batch or len(batch) < page_size or (
                isinstance(count, int) and (current_page + 1) * page_size >= count
            ):
                break
        return dashboards

    async def list_dashboards_page(
        self,
        *,
        page: int = 0,
        page_size: int = 100,
        query: str | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Return one permission-filtered dashboard page and its server count."""
        if page < 0 or page_size <= 0:
            raise ValueError("page must be non-negative and page_size must be positive")
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if query and query.strip():
            params["q"] = json.dumps(
                {
                    "filters": [
                        {
                            "col": "dashboard_title",
                            "opr": "ct",
                            "value": query.strip(),
                        }
                    ]
                },
                separators=(",", ":"),
            )
        response = await self._request(
            "GET", "/api/v1/dashboard/", timeout=30, params=params
        )
        result = response.json()
        batch = result.get("result", [])
        return (
            [item for item in batch if isinstance(item, dict)] if isinstance(batch, list) else [],
            result.get("count") if isinstance(result.get("count"), int) else None,
        )

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

    @classmethod
    def _datasource(cls, chart: dict[str, Any]) -> dict[str, Any]:
        """Normalize the dataset locator across Superset chart API shapes.

        Superset versions and saved-chart responses do not expose this field
        consistently. Some return `datasource_id`/`datasource_type` while
        others only retain the Explore form-data value, for example
        `params.datasource = "17__table"`. Sending a null datasource makes
        an otherwise valid saved chart fail with a 400 response.
        """
        params = cls._params(chart)
        raw = chart.get("datasource") or params.get("datasource")
        datasource_id = chart.get("datasource_id")
        datasource_type = chart.get("datasource_type")
        if isinstance(raw, dict):
            datasource_id = datasource_id or raw.get("id")
            datasource_type = datasource_type or raw.get("type")
        elif isinstance(raw, str):
            identifier, separator, raw_type = raw.partition("__")
            if datasource_id is None and identifier:
                datasource_id = int(identifier) if identifier.isdigit() else identifier
            if datasource_type is None and separator and raw_type:
                datasource_type = raw_type
        if datasource_id is None:
            raise ValueError("Superset chart metadata did not expose a datasource id")
        return {"id": datasource_id, "type": datasource_type or "table"}

    @staticmethod
    def _bounded_int(
        params: dict[str, Any], key: str, default: int, minimum: int, maximum: int
    ) -> int:
        try:
            value = int(params.get(key) or default)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    @staticmethod
    def _dedupe_values(values: Iterable[Any]) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        for value in values:
            if value is None or not isinstance(value, (str, dict)):
                continue
            key = json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    @classmethod
    def _query_metrics(cls, params: dict[str, Any]) -> list[Any]:
        """Recover metric expressions from Superset visualization-specific fields.

        Superset's Explore form data does not use one universal metric field. For
        example, bubble charts put measures in ``x``/``y``/``size`` while a
        histogram may only specify a ``column`` and implicitly counts rows.
        Keeping this translation here makes the downstream evidence contract
        independent of the visualization plugin.
        """
        metrics = params.get("metrics")
        if not metrics and params.get("metric") is not None:
            metrics = [params["metric"]]
        explicit = cls._as_list(metrics)
        if not explicit:
            explicit = [params[key] for key in ("x", "y", "size") if params.get(key) is not None]
        if explicit:
            return cls._dedupe_values(explicit)
        # Superset accepts count as the implicit measure for dimension-only
        # charts. This is also the useful row-count signal for histograms,
        # geospatial plots, and Gantt charts.
        if any(
            params.get(key) is not None
            for key in (
                "column",
                "groupby",
                "series",
                "entity",
                "spatial",
                "start_spatial",
                "end_spatial",
                "line_column",
                "start_time",
                "end_time",
            )
        ):
            return ["count"]
        return []

    @classmethod
    def _query_columns(cls, params: dict[str, Any], granularity: str | None) -> list[Any]:
        columns: list[Any] = []
        columns.extend(cls._as_list(params.get("columns")))
        columns.extend(cls._as_list(params.get("groupby")))
        for key in (
            "x_axis",
            "entity",
            "series",
            "column",
            "line_column",
            "start_time",
            "end_time",
        ):
            value = params.get(key)
            if isinstance(value, str) and value:
                columns.append(value)
        spatials = [params.get("spatial"), params.get("start_spatial"), params.get("end_spatial")]
        for spatial in spatials:
            if not isinstance(spatial, dict):
                continue
            columns.extend(
                value
                for key in ("latCol", "lonCol")
                if isinstance(value := spatial.get(key), str) and value
            )
        if not columns:
            columns.extend(cls._as_list(params.get("all_columns")))
        columns = cls._dedupe_values(columns)
        if params.get("time_grain_sqla") and granularity and granularity not in columns:
            columns.insert(0, granularity)
        return columns

    @classmethod
    def _query_context(cls, chart: dict[str, Any]) -> dict[str, Any]:
        """Build a bounded chart-data request from a saved chart definition."""
        params = cls._params(chart)
        metrics = cls._query_metrics(params)
        granularity = params.get("granularity") or params.get("granularity_sqla")
        if not isinstance(granularity, str):
            granularity = None
        columns = cls._query_columns(params, granularity)
        extras = {}
        if params.get("time_grain_sqla"):
            extras["time_grain_sqla"] = params["time_grain_sqla"]
        form_data = dict(params)
        form_data["slice_id"] = chart.get("id")
        return {
            "datasource": cls._datasource(chart),
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
        result = response.json().get("result", [])
        if isinstance(result, dict):
            return [result]
        return [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    @staticmethod
    def _numeric_keys(rows: Iterable[dict[str, Any]]) -> list[str]:
        counts: dict[str, int] = {}
        for row in rows:
            for key, value in row.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    counts[key] = counts.get(key, 0) + 1
        return [key for key, _ in sorted(counts.items(), key=lambda item: -item[1])]

    @classmethod
    def _viz_type(cls, chart: dict[str, Any]) -> str:
        params = cls._params(chart)
        return str(chart.get("viz_type") or params.get("viz_type") or "unknown")

    @staticmethod
    def _normalized_key(value: Any) -> str:
        return "".join(character for character in str(value).lower() if character.isalnum())

    @classmethod
    def _metric_specs(cls, chart: dict[str, Any]) -> list[Any]:
        params = cls._params(chart)
        metrics = params.get("metrics") or ([params["metric"]] if params.get("metric") else [])
        if isinstance(metrics, (str, dict)):
            return [metrics]
        if isinstance(metrics, list) and metrics:
            return [metric for metric in metrics if isinstance(metric, (str, dict))]
        visual_measures = [params[key] for key in ("x", "y", "size") if params.get(key) is not None]
        if visual_measures:
            return cls._dedupe_values(visual_measures)
        if any(
            params.get(key) is not None
            for key in (
                "column",
                "spatial",
                "start_spatial",
                "end_spatial",
                "line_column",
                "start_time",
                "end_time",
            )
        ):
            return ["count"]
        return []

    @staticmethod
    def _metric_candidates(spec: Any) -> list[str]:
        if isinstance(spec, str):
            candidates = [spec]
        elif isinstance(spec, dict):
            candidates = [
                str(spec[key])
                for key in ("label", "metric", "expression")
                if spec.get(key) is not None
            ]
            column = spec.get("column")
            if isinstance(column, dict) and column.get("column_name") is not None:
                candidates.append(str(column["column_name"]))
        else:
            candidates = []
        expanded = list(candidates)
        for candidate in candidates:
            if "(" in candidate and candidate.endswith(")"):
                expanded.append(candidate[candidate.find("(") + 1 : -1])
        return list(dict.fromkeys(expanded))

    @classmethod
    def _metric_keys(
        cls, chart: dict[str, Any], rows: list[dict[str, Any]], time_key: str | None
    ) -> tuple[list[str], list[str]]:
        params = cls._params(chart)
        numeric_keys = cls._numeric_keys(rows)
        row_keys = {str(key): key for row in rows for key in row}
        normalized_row_keys = {
            cls._normalized_key(key): key for key in row_keys
        }
        specs = cls._metric_specs(chart)
        if specs:
            selected: list[str] = []
            missing: list[str] = []
            for spec in specs:
                candidates = cls._metric_candidates(spec)
                match = next(
                    (
                        row_keys[candidate]
                        for candidate in candidates
                        if candidate in row_keys and candidate in numeric_keys
                    ),
                    None,
                )
                if match is None:
                    match = next(
                        (
                            normalized_row_keys[cls._normalized_key(candidate)]
                            for candidate in candidates
                            if cls._normalized_key(candidate) in normalized_row_keys
                            and normalized_row_keys[cls._normalized_key(candidate)] in numeric_keys
                        ),
                        None,
                    )
                if match is None:
                    missing.append(str(candidates[0] if candidates else spec))
                elif match not in selected:
                    selected.append(str(match))
            return selected, missing

        granularity = {
            params.get("granularity"),
            params.get("granularity_sqla"),
            params.get("x_axis"),
        }
        granularity.update(
            str(column)
            for column in params.get("all_columns", [])
            if isinstance(column, str)
            and any(token in column.lower() for token in ("date", "time", "timestamp"))
        )
        return [key for key in numeric_keys if key not in granularity and key != time_key], []

    @classmethod
    def _rows_from_result_item(cls, result: Any) -> list[dict[str, Any]]:
        """Normalize common Superset tabular result envelopes.

        Superset chart plugins can wrap the same query rows as ``data``,
        ``records``, ``rows``, or columnar ``columns``/``data`` payloads.  The
        chart adapter keeps this normalization generic and leaves visualization
        semantics to the explicit metric/query definition.
        """
        payload = result.get("data") if isinstance(result, dict) and "data" in result else result
        if isinstance(payload, list):
            if all(isinstance(row, dict) for row in payload):
                return payload
            return []
        if not isinstance(payload, dict):
            return []
        for key in ("records", "rows", "results", "values"):
            rows = payload.get(key)
            if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                return rows
        columns = payload.get("columns")
        values = payload.get("data")
        if isinstance(columns, list) and isinstance(values, list):
            return [
                {str(column): value for column, value in zip(columns, row, strict=False)}
                for row in values
                if isinstance(row, list)
            ]
        return []

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
        for candidate in params.get("all_columns", []):
            if (
                isinstance(candidate, str)
                and any(token in candidate.lower() for token in ("date", "time", "timestamp"))
                and any(candidate in row for row in rows)
            ):
                return candidate
        return None

    @staticmethod
    def _sort_value(value: Any) -> tuple[int, Any]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return (0, float(value))
        return (1, str(value))

    @classmethod
    def extract_chart_data(
        cls, chart: dict[str, Any], result: list[dict[str, Any]]
    ) -> ChartObservationExtraction:
        rows: list[dict[str, Any]] = []
        for item in result:
            rows.extend(cls._rows_from_result_item(item))
        if not rows:
            return ChartObservationExtraction([], [], "no_data", ["The chart query returned no tabular rows."])
        columns = list(dict.fromkeys(str(key) for row in rows for key in row))
        time_key = cls._time_key(chart, rows)
        metric_keys, missing = cls._metric_keys(chart, rows, time_key)
        notes = [f"Metric definition was not present in result rows: {item}." for item in missing]
        explicit_metrics = bool(cls._metric_specs(chart))
        if not metric_keys:
            status = "unsupported" if explicit_metrics or cls._numeric_keys(rows) else "metadata_only"
            message = (
                "Declared metric columns could not be matched to numeric result fields."
                if status == "unsupported"
                else "The chart returned rows but no numeric metric columns."
            )
            return ChartObservationExtraction(
                [],
                [],
                status,
                [*notes, message],
                row_count=len(rows),
                columns=columns,
            )
        if not explicit_metrics and len(metric_keys) > 1:
            notes.append(
                "The chart returned multiple numeric columns without explicit metric semantics; "
                "all were retained as separate observations and require review."
            )

        observations: list[Observation] = []
        chart_id = str(chart.get("id"))
        chart_title = str(chart.get("slice_name") or chart.get("id"))
        for metric_key in metric_keys:
            numeric_rows = [
                row for row in rows if isinstance(row.get(metric_key), (int, float))
            ]
            if not numeric_rows:
                continue
            if time_key:
                values_by_time: dict[Any, float] = {}
                for row in numeric_rows:
                    time_value = row.get(time_key)
                    if time_value is not None:
                        values_by_time[time_value] = values_by_time.get(time_value, 0.0) + float(row[metric_key])
                ordered_values = [
                    values_by_time[key] for key in sorted(values_by_time, key=cls._sort_value)
                ]
                current = float(ordered_values[-1]) if ordered_values else None
                comparison_baselines: dict[str, float] = {}
                if len(ordered_values) >= 2:
                    comparison_baselines["previous_period"] = float(ordered_values[-2])
                if len(ordered_values) >= 5:
                    comparison_baselines["trailing_4_period_average"] = sum(ordered_values[-5:-1]) / 4
                baseline = comparison_baselines.get("previous_period")
                change_pct = (
                    round((current - baseline) / abs(baseline) * 100, 3)
                    if current is not None and baseline not in (None, 0)
                    else None
                )
                observations.append(
                    Observation(
                        source_key=f"superset-chart:{chart_id}",
                        subject_id=f"{chart_id}:{metric_key}",
                        subject_label=chart_title,
                        subject_type="superset_chart",
                        metric=metric_key,
                        current=current,
                        baseline=baseline,
                        change_pct=change_pct,
                        comparison_baselines=comparison_baselines,
                        attributes={"viz_type": cls._viz_type(chart)},
                        source_url=chart.get("url"),
                    )
                )
                continue

            for index, row in enumerate(numeric_rows[:500]):
                dimensions = {
                    str(key): value
                    for key, value in row.items()
                    if key not in metric_keys
                }
                observations.append(
                    Observation(
                        source_key=f"superset-chart:{chart_id}",
                        subject_id=f"{chart_id}:{metric_key}:{index}",
                        subject_label=chart_title,
                        subject_type="superset_chart",
                        metric=metric_key,
                        current=float(row[metric_key]),
                        dimensions=dimensions,
                        attributes={"viz_type": cls._viz_type(chart)},
                        source_url=chart.get("url"),
                    )
                )
        status = "partial" if notes else "extracted"
        if not observations:
            status = "unsupported"
            notes.append("Metric columns were declared but no numeric values were returned.")
        return ChartObservationExtraction(
            observations,
            metric_keys,
            status,
            notes,
            row_count=len(rows),
            columns=columns,
        )

    @classmethod
    def _observations_from_result(
        cls, chart: dict[str, Any], result: dict[str, Any]
    ) -> list[Observation]:
        return cls.extract_chart_data(chart, [result]).observations

    @classmethod
    def observations_from_chart_data(
        cls, chart: dict[str, Any], result: list[dict[str, Any]]
    ) -> list[Observation]:
        return cls.extract_chart_data(chart, result).observations

    async def dashboard_snapshot(
        self,
        dashboard_id: int | str,
        include_data: bool = True,
        chart_ids: list[str] | None = None,
    ) -> SupersetDashboardSnapshot:
        metadata = await self.get_dashboard_metadata(dashboard_id)
        snapshot = self.metadata_to_snapshot(metadata)
        selected = set(chart_ids) if chart_ids else None
        if selected is not None:
            available = {chart.id for chart in snapshot.charts}
            missing = sorted(selected - available)
            if missing:
                raise ValueError(
                    "Superset dashboard does not contain selected chart IDs: "
                    + ", ".join(missing)
                )
            snapshot = snapshot.model_copy(
                update={"charts": [chart for chart in snapshot.charts if chart.id in selected]}
            )
        if not include_data:
            return snapshot

        semaphore = asyncio.Semaphore(8)

        async def load_chart(chart: SupersetChartSnapshot) -> SupersetChartSnapshot:
            async with semaphore:
                try:
                    chart_metadata = await self.get_chart_metadata(chart.id)
                    extraction = self.extract_chart_data(
                        chart_metadata, await self.chart_data(chart_metadata)
                    )
                    updates: dict[str, Any] = {
                        "observations": extraction.observations,
                        "metrics": extraction.metrics,
                        "metric": extraction.metrics[0] if extraction.metrics else "unknown",
                        "viz_type": self._viz_type(chart_metadata),
                        "semantic_status": extraction.semantic_status,
                        "semantic_notes": extraction.notes,
                        "result_row_count": extraction.row_count,
                        "result_columns": extraction.columns or [],
                    }
                    if not extraction.observations:
                        updates["error"] = "; ".join(extraction.notes)
                        updates["description"] = updates["error"]
                    return chart.model_copy(update=updates)
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                    return chart.model_copy(
                        update={
                            "error": f"Data unavailable from Superset: {error}",
                            "description": f"Data unavailable from Superset: {error}",
                            "semantic_status": "unsupported",
                            "semantic_notes": [f"Chart normalization failed: {error}"],
                        }
                    )

        charts = await asyncio.gather(*(load_chart(chart) for chart in snapshot.charts))
        return snapshot.model_copy(update={"charts": charts})

    @staticmethod
    def metadata_to_snapshot(metadata: dict[str, Any]) -> SupersetDashboardSnapshot:
        """Map stable dashboard metadata into a safe inspection snapshot."""
        position = metadata.get("position_json", {})
        if isinstance(position, str):
            try:
                position = json.loads(position)
            except json.JSONDecodeError:
                position = {}
        chart_items: list[dict[str, Any]] = []
        if isinstance(position, dict):
            chart_items.extend(item for item in position.values() if isinstance(item, dict))
        elif isinstance(position, list):
            chart_items.extend(item for item in position if isinstance(item, dict))
        for key in ("charts", "slices"):
            items = metadata.get(key)
            if isinstance(items, list):
                chart_items.extend(item for item in items if isinstance(item, dict))

        charts: list[SupersetChartSnapshot] = []
        seen_chart_ids: set[str] = set()
        for item in chart_items:
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            item_type = str(item.get("type") or "CHART").upper()
            chart_id = meta.get("chartId") or item.get("chartId") or item.get("slice_id")
            chart_id = chart_id or item.get("id")
            if chart_id is None or (item_type not in {"CHART", "SLICE"} and not meta.get("chartId")):
                continue
            chart_id = str(chart_id)
            if chart_id in seen_chart_ids:
                continue
            seen_chart_ids.add(chart_id)
            charts.append(
                SupersetChartSnapshot(
                    id=chart_id,
                    title=str(
                        meta.get("sliceNameOverride")
                        or meta.get("sliceName")
                        or item.get("slice_name")
                        or item.get("title")
                        or chart_id
                    ),
                    metric="unknown",
                    viz_type=str(meta.get("viz_type") or item.get("viz_type") or "unknown"),
                )
            )
        return SupersetDashboardSnapshot(
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

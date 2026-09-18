from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

import httpx

from .models import (
    Evidence,
    MetricQueryPlan,
    Observation,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from .query_planner import QueryWindow, compile_query


class TrinoExecutor(Protocol):
    async def execute(self, sql: str, parameters: dict[str, str]) -> list[dict[str, Any]]: ...


class HttpxTrinoExecutor:
    """Read-only Trino HTTP executor for already-compiled SignalWeave queries."""

    def __init__(
        self,
        base_url: str,
        *,
        user: str,
        catalog: str | None = None,
        schema: str | None = None,
        timeout: float = 30.0,
        max_rows: int = 1000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not user.strip():
            raise ValueError("Trino user is required")
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.catalog = catalog
        self.schema = schema
        self.timeout = timeout
        self.max_rows = max_rows
        self._client = client

    async def execute(self, sql: str, parameters: dict[str, str]) -> list[dict[str, Any]]:
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("SignalWeave Trino execution only permits SELECT queries")
        # The compiler emits named parameters. Trino's HTTP endpoint does not
        # perform binding, so substitute only the two ISO timestamps after
        # validating their shape. No caller-controlled SQL reaches this method.
        rendered = sql
        for name, value in parameters.items():
            if not _safe_timestamp(value):
                raise ValueError(f"invalid Trino query parameter: {name}")
            rendered = rendered.replace(f":{name}", f"TIMESTAMP '{value.replace('T', ' ').replace('+00:00', '')}'")
        headers = {
            "X-Trino-User": self.user,
            "X-Trino-Source": "signal-weave",
        }
        if self.catalog:
            headers["X-Trino-Catalog"] = self.catalog
        if self.schema:
            headers["X-Trino-Schema"] = self.schema
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        try:
            response = await client.post("/v1/statement", content=rendered, headers=headers)
            response.raise_for_status()
            payload = response.json()
            rows = _rows_from_trino(payload)
            next_uri = payload.get("nextUri")
            while next_uri and len(rows) < self.max_rows:
                response = await client.get(next_uri, headers=headers)
                response.raise_for_status()
                payload = response.json()
                rows.extend(_rows_from_trino(payload))
                next_uri = payload.get("nextUri")
            return rows[: self.max_rows]
        finally:
            if owns_client:
                await client.aclose()


class TrinoQueryAdapter:
    """Expose an approved Trino metric catalog and execute only compiled plans."""

    name = "trino"

    def __init__(
        self,
        resources: Iterable[ResourceDescriptor],
        executor: TrinoExecutor,
        *,
        max_rows: int = 1000,
    ) -> None:
        self.resources = list(resources)
        self.executor = executor
        self.max_rows = max_rows
        if any(resource.adapter != self.name for resource in self.resources):
            raise ValueError("TrinoQueryAdapter resources must use adapter='trino'")

    async def list_resources(self) -> list[ResourceDescriptor]:
        return list(self.resources)

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        descriptor = next(
            (
                resource
                for resource in self.resources
                if resource.resource == source.resource
            ),
            None,
        )
        if descriptor is None:
            raise ValueError(f"unknown approved Trino resource: {source.resource}")
        metric_key = str(source.parameters.get("metric_key") or "")
        definition = next(
            (item for item in descriptor.contract.metric_definitions if item.key == metric_key),
            None,
        )
        if definition is None:
            raise ValueError("Trino source parameters.metric_key must name an approved definition")
        dimensions = source.parameters.get("dimensions") or []
        if not isinstance(dimensions, list) or not all(isinstance(item, str) for item in dimensions):
            raise ValueError("Trino source parameters.dimensions must be a list of names")
        unknown = [item for item in dimensions if item not in definition.dimensions]
        if unknown:
            raise ValueError("Trino dimensions are not approved: " + ", ".join(unknown))
        grain = str(source.parameters.get("time_grain") or "month")
        if grain not in definition.supported_grains:
            raise ValueError(f"Trino time grain is not approved: {grain}")
        window = QueryWindow(
            str(source.parameters.get("window_start") or ""),
            str(source.parameters.get("window_end") or ""),
        )
        plan = MetricQueryPlan(
            source_key=source.key,
            metric_key=definition.key,
            relation=definition.relation,
            dialect=definition.dialect,
            aggregation=definition.aggregation,
            measure_column=definition.measure_column,
            time_column=definition.time_column,
            time_grain=grain,
            dimensions={name: definition.dimensions[name] for name in dimensions},
            partition_column=definition.partition_column,
            population=definition.population or descriptor.contract.population,
            grain=definition.grain or descriptor.contract.grain,
            selection_probability=1.0,
            selected_by="approved-source-ref",
        )
        compiled = compile_query(plan, window)
        rows = await self.executor.execute(compiled.sql, compiled.parameters)
        observations = _observations_from_rows(source, rows, grain, self.max_rows)
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=descriptor.title,
            description=descriptor.description,
            observations=observations,
            evidence=[
                Evidence(
                    source_key=source.key,
                    subject_id=compiled.fingerprint,
                    subject_label=definition.label,
                    statement="Approved Trino metric query executed in a bounded time window.",
                    values={
                        "metric_key": definition.key,
                        "query_fingerprint": compiled.fingerprint,
                        "scan_guard": compiled.scan_guard,
                        "row_count": len(rows),
                    },
                )
            ],
            metadata={
                "provider": "trino",
                "metric_key": definition.key,
                "compiled_sql": compiled.sql,
                "query_fingerprint": compiled.fingerprint,
            },
            contract=descriptor.contract,
        )


def _safe_timestamp(value: str) -> bool:
    from datetime import datetime

    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _rows_from_trino(payload: dict[str, Any]) -> list[dict[str, Any]]:
    columns = [str(column.get("name")) for column in payload.get("columns", [])]
    return [dict(zip(columns, row, strict=False)) for row in payload.get("data", [])]


def _observations_from_rows(
    source: SourceRef, rows: list[dict[str, Any]], grain: str, max_rows: int
) -> list[Observation]:
    observations: list[Observation] = []
    for index, row in enumerate(rows[:max_rows]):
        value = row.get("metric_value")
        current = float(value) if isinstance(value, (int, float)) else None
        baseline_value = row.get("baseline_metric_value")
        baseline = float(baseline_value) if isinstance(baseline_value, (int, float)) else None
        change_pct = None
        if current is not None and baseline not in (None, 0):
            change_pct = round((current - baseline) / abs(baseline) * 100, 3)
        dimensions = {
            key: value
            for key, value in row.items()
            if key not in {"metric_value", "baseline_metric_value", grain}
        }
        if grain in row:
            dimensions[grain] = row[grain]
        observations.append(
            Observation(
                source_key=source.key,
                subject_id=f"{source.resource}:{index}",
                subject_label=str(row.get(grain) or f"row {index + 1}"),
                subject_type="trino_metric",
                metric="metric_value",
                current=current,
                baseline=baseline,
                change_pct=change_pct,
                dimensions=dimensions,
            )
        )
    return observations

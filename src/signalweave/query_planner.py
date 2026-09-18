from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .models import (
    CompiledQuery,
    MetricDefinition,
    MetricQueryPlan,
    ResourceDescriptor,
    SourceRef,
)
from .sources import SourceRegistry


class MetricCandidate(dict[str, Any]):
    """JSON-shaped candidate passed to Jev; code remains the source of truth."""


class MetricSelector(Protocol):
    name: str

    async def select_metric_plan(
        self,
        goal: str,
        candidates: list[MetricCandidate],
        requested_dimensions: list[str],
        requested_time_grain: str | None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class QueryWindow:
    start: str
    end: str

    def validate(self) -> None:
        try:
            start = datetime.fromisoformat(self.start.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.end.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("query windows must be ISO-8601 timestamps") from error
        if end <= start:
            raise ValueError("query window end must be after start")


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_RELATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){0,3}$")


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _quote_relation(value: str) -> str:
    if not _RELATION.fullmatch(value):
        raise ValueError(f"unsafe SQL relation: {value!r}")
    return ".".join(_quote_identifier(part) for part in value.split("."))


def _metric_expression(definition: MetricDefinition) -> str:
    if definition.aggregation == "count":
        return "COUNT(*)"
    assert definition.measure_column is not None
    column = _quote_identifier(definition.measure_column)
    if definition.aggregation == "count_distinct":
        return f"COUNT(DISTINCT {column})"
    return f"{definition.aggregation.upper()}({column})"


def _time_expression(column: str, grain: str) -> str:
    return f"date_trunc('{grain}', {_quote_identifier(column)})"


def compile_query(plan: MetricQueryPlan, window: QueryWindow) -> CompiledQuery:
    """Compile an approved plan into bounded deterministic SQL.

    No natural-language input reaches this function.  Every relation, column,
    aggregation, grain, and dimension has already been selected from a typed
    catalog entry and is validated again before SQL is emitted.
    """

    window.validate()
    if plan.time_grain not in {"day", "week", "month", "quarter", "year"}:
        raise ValueError(f"unsupported time grain: {plan.time_grain}")
    if plan.measure_column is None and plan.aggregation != "count":
        raise ValueError("a non-count query plan requires a measure column")

    dimension_selects = [
        f"{_quote_identifier(column)} AS {_quote_identifier(name)}"
        for name, column in plan.dimensions.items()
    ]
    time_select = (
        f"{_time_expression(plan.time_column, plan.time_grain)} AS "
        f"{_quote_identifier(plan.time_grain)}"
    )
    select_items = [*dimension_selects, time_select, f"{_metric_expression_from_plan(plan)} AS metric_value"]
    partition_column = plan.partition_column or plan.time_column
    where = (
        f"{_quote_identifier(partition_column)} >= CAST(:window_start AS TIMESTAMP)"
        f" AND {_quote_identifier(partition_column)} < CAST(:window_end AS TIMESTAMP)"
    )
    sql = (
        "SELECT\n  "
        + ",\n  ".join(select_items)
        + f"\nFROM {_quote_relation(plan.relation)}\nWHERE {where}"
    )
    group_items = [str(index) for index in range(1, len(dimension_selects) + 2)]
    if group_items:
        sql += "\nGROUP BY " + ", ".join(group_items)
    sql += f"\nORDER BY {_quote_identifier(plan.time_grain)}"
    normalized = " ".join(sql.split())
    fingerprint = hashlib.sha256(
        (normalized + "|" + window.start + "|" + window.end).encode("utf-8")
    ).hexdigest()[:24]
    return CompiledQuery(
        plan=plan,
        sql=sql,
        parameters={"window_start": window.start, "window_end": window.end},
        fingerprint=fingerprint,
        scan_guard=(
            f"partition {partition_column} bounded to [{window.start}, {window.end})"
        ),
    )


def _metric_expression_from_plan(plan: MetricQueryPlan) -> str:
    definition = MetricDefinition(
        key=plan.metric_key,
        label=plan.metric_key,
        relation=plan.relation,
        dialect=plan.dialect,
        aggregation=plan.aggregation,
        measure_column=plan.measure_column,
        time_column=plan.time_column,
        supported_grains=[plan.time_grain],
        dimensions=plan.dimensions,
        partition_column=plan.partition_column,
        population=plan.population,
        grain=plan.grain,
    )
    return _metric_expression(definition)


def metric_candidates(
    resources: list[ResourceDescriptor], source_refs: list[SourceRef]
) -> list[MetricCandidate]:
    allowed = {(source.adapter, source.resource): source.key for source in source_refs}
    candidates: list[MetricCandidate] = []
    for resource in resources:
        source_key = allowed.get((resource.adapter, resource.resource))
        if source_key is None:
            continue
        for definition in resource.contract.metric_definitions:
            candidate_id = f"{source_key}:{definition.key}"
            candidates.append(
                MetricCandidate(
                    candidate_id=candidate_id,
                    source_key=source_key,
                    metric_key=definition.key,
                    label=definition.label,
                    description=definition.description,
                    relation=definition.relation,
                    dialect=definition.dialect,
                    aggregation=definition.aggregation,
                    measure_column=definition.measure_column,
                    time_column=definition.time_column,
                    supported_grains=list(definition.supported_grains),
                    dimensions=dict(definition.dimensions),
                    partition_column=definition.partition_column,
                    population=definition.population or resource.contract.population,
                    grain=definition.grain or resource.contract.grain,
                    tenant_id=resource.contract.tenant_id,
                    domain=resource.contract.domain,
                )
            )
    return candidates


async def plan_query(
    *,
    registry: SourceRegistry,
    selector: MetricSelector,
    goal: str,
    source_refs: list[SourceRef],
    requested_dimensions: list[str] | None = None,
    requested_time_grain: str | None = None,
) -> MetricQueryPlan:
    if not goal.strip():
        raise ValueError("metric query goal must not be empty")
    if not source_refs:
        raise ValueError("metric query requires at least one approved source")
    requested_dimensions = list(requested_dimensions or [])
    descriptors = await registry.list_resources()
    candidates = metric_candidates(descriptors, source_refs)
    if not candidates:
        raise ValueError(
            "no approved metric definitions are available for the selected sources; "
            "the adapter must publish typed query contracts"
        )
    selection = await selector.select_metric_plan(
        goal,
        candidates,
        requested_dimensions,
        requested_time_grain,
    )
    candidate_by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    selected_id = str(selection.get("candidate_id", ""))
    if selected_id not in candidate_by_id:
        raise ValueError("semantic selector returned a metric candidate outside the approved catalog")
    candidate = candidate_by_id[selected_id]
    probability = max(0.0, min(1.0, float(selection.get("probability", 0.0))))
    if probability < 0.60:
        raise ValueError("metric definition match is too uncertain for deterministic compilation")

    supported_dimensions = dict(candidate["dimensions"])
    unknown_dimensions = [name for name in requested_dimensions if name not in supported_dimensions]
    if unknown_dimensions:
        raise ValueError(
            "requested dimensions are not available in the selected metric definition: "
            + ", ".join(unknown_dimensions)
        )
    dimensions = {
        name: supported_dimensions[name]
        for name in selection.get("dimensions", requested_dimensions)
        if name in supported_dimensions
    }
    grain = str(selection.get("time_grain") or requested_time_grain or "month")
    if grain not in candidate["supported_grains"]:
        raise ValueError(
            f"time grain {grain!r} is not supported by metric definition {candidate['metric_key']}"
        )
    return MetricQueryPlan(
        source_key=str(candidate["source_key"]),
        metric_key=str(candidate["metric_key"]),
        relation=str(candidate["relation"]),
        dialect=str(candidate["dialect"]),
        aggregation=str(candidate["aggregation"]),
        measure_column=candidate.get("measure_column"),
        time_column=str(candidate["time_column"]),
        time_grain=grain,
        dimensions=dimensions,
        partition_column=candidate.get("partition_column"),
        population=str(candidate.get("population", "")),
        grain=str(candidate.get("grain", "")),
        selection_probability=probability,
        selected_by=selector.name,
    )

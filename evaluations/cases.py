"""Load evaluation cases without making them part of product decision logic."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semantic_monitor.models import MonitorWorkflow, Observation, ResourceSnapshot, SourceRef


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    expected_outcome: str
    expected_recipient: str | None
    resources: list[ResourceSnapshot]
    workflow: MonitorWorkflow


def default_fixture_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "demo-cases.json"


def _normalize_dashboard(raw: dict[str, Any]) -> tuple[ResourceSnapshot, str]:
    dashboard_id = str(raw["id"])
    source_key = f"superset-{dashboard_id}"
    observations: list[Observation] = []
    chart_metadata: list[dict[str, Any]] = []
    for chart in raw.get("charts", []):
        chart_metadata.append(
            {
                "id": str(chart["id"]),
                "title": chart.get("title", chart["id"]),
                "metric": chart.get("metric", "unknown"),
                "description": chart.get("description", ""),
                "related_chart_ids": chart.get("related_chart_ids", []),
                "error": chart.get("error"),
            }
        )
        for raw_observation in chart.get("observations", []):
            observation = dict(raw_observation)
            observation["source_key"] = source_key
            observation["subject_id"] = str(observation.pop("chart_id", chart["id"]))
            observation["subject_label"] = observation.pop(
                "chart_title", chart.get("title", chart["id"])
            )
            observation["subject_type"] = "superset_chart"
            observations.append(Observation.model_validate(observation))
    resource = ResourceSnapshot(
        source_key=source_key,
        adapter="superset",
        resource=f"dashboard:{dashboard_id}",
        title=raw.get("title", "Untitled dashboard"),
        description=raw.get("description", ""),
        observations=observations,
        metadata={
            "provider": "superset",
            "dashboard_id": dashboard_id,
            "owners": raw.get("owners", []),
            "charts": chart_metadata,
        },
        source_url=raw.get("source_url"),
    )
    return resource, source_key


def _workflow_from_card(
    raw: dict[str, Any], dashboard: dict[str, Any], source_key: str
) -> MonitorWorkflow:
    card = dict(raw)
    chart_ids = card.pop("chart_ids", [])
    card.pop("dashboard_id", None)
    card["sources"] = [
        SourceRef(
            key=source_key,
            adapter="superset",
            resource=f"dashboard:{dashboard['id']}",
            label=dashboard.get("title", dashboard["id"]),
            parameters={"chart_ids": chart_ids} if chart_ids else {},
        )
    ]
    return MonitorWorkflow.model_validate(card)


def load_evaluation_cases(path: str | Path | None = None) -> list[EvaluationCase]:
    fixture_path = Path(path) if path else default_fixture_path()
    payload: dict[str, Any] = json.loads(fixture_path.read_text())
    cases: list[EvaluationCase] = []
    for item in payload["cases"]:
        resource, source_key = _normalize_dashboard(item["dashboard"])
        cases.append(
            EvaluationCase(
                id=item["id"],
                expected_outcome=item["expected_outcome"],
                expected_recipient=item.get("expected_recipient"),
                resources=[resource],
                workflow=_workflow_from_card(item["monitor_card"], item["dashboard"], source_key),
            )
        )
    return cases

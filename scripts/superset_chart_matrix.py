"""Exercise the SignalWeave Superset boundary against every local chart.

This is deliberately an integration harness rather than production code. It
does not invent fixtures or expected business outcomes: it asks the running
Superset instance for its saved dashboards, runs the normal client path, and
checks the evidence contract for silent loss.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from typing import Any

from signalweave.superset_client import SupersetClient


def _chart_issue(chart: Any) -> str | None:
    if chart.semantic_status not in {
        "extracted",
        "partial",
        "unsupported",
        "metadata_only",
        "no_data",
    }:
        return f"{chart.id}: invalid semantic status {chart.semantic_status!r}"
    if not chart.observations and not chart.semantic_notes and not chart.error:
        return f"{chart.id}: no observations without an explanation"
    if chart.observations and not chart.metrics:
        return f"{chart.id}: observations exist without metric labels"
    metric_labels = set(chart.metrics)
    missing = sorted({observation.metric for observation in chart.observations} - metric_labels)
    if missing:
        return f"{chart.id}: observations have unregistered metrics {missing}"
    return None


async def run() -> int:
    client = SupersetClient(
        base_url=os.getenv("SUPERSET_URL", "http://127.0.0.1:8088"),
        username=os.getenv("SUPERSET_USERNAME", "admin"),
        password=os.getenv("SUPERSET_PASSWORD", "admin"),
    )
    dashboards = await client.list_dashboards()
    statuses: Counter[str] = Counter()
    viz_types: Counter[str] = Counter()
    charts_seen = 0
    observations_seen = 0
    issues: list[str] = []
    non_extracted: list[dict[str, Any]] = []
    dashboard_summaries: list[dict[str, Any]] = []

    for dashboard in dashboards:
        dashboard_id = dashboard.get("id")
        if dashboard_id is None:
            continue
        snapshot = await client.dashboard_snapshot(dashboard_id)
        dashboard_observations = sum(len(chart.observations) for chart in snapshot.charts)
        charts_seen += len(snapshot.charts)
        observations_seen += dashboard_observations
        for chart in snapshot.charts:
            statuses[chart.semantic_status] += 1
            viz_types[chart.viz_type] += 1
            issue = _chart_issue(chart)
            if issue:
                issues.append(
                    f"dashboard={dashboard_id} title={snapshot.title!r} {issue} "
                    f"status={chart.semantic_status} notes={chart.semantic_notes!r}"
                )
            if chart.semantic_status != "extracted":
                non_extracted.append(
                    {
                        "dashboard_id": str(dashboard_id),
                        "dashboard_title": snapshot.title,
                        "chart_id": chart.id,
                        "title": chart.title,
                        "viz_type": chart.viz_type,
                        "status": chart.semantic_status,
                        "metrics": chart.metrics,
                        "notes": chart.semantic_notes,
                        "error": chart.error,
                    }
                )
        dashboard_summaries.append(
            {
                "id": str(dashboard_id),
                "title": snapshot.title,
                "charts": len(snapshot.charts),
                "observations": dashboard_observations,
            }
        )

    report = {
        "dashboards": len(dashboard_summaries),
        "charts": charts_seen,
        "observations": observations_seen,
        "semantic_status": dict(sorted(statuses.items())),
        "viz_types": dict(sorted(viz_types.items())),
        "non_extracted": non_extracted,
        "silent_loss_issues": issues,
        "dashboard_summaries": dashboard_summaries,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))

from __future__ import annotations

from collections.abc import Iterable

from .models import DashboardSnapshot, MonitorCard, MonitorPlan, Observation


def observations_for_plan(dashboard: DashboardSnapshot, plan: MonitorPlan) -> list[Observation]:
    selected = set(plan.selected_chart_ids)
    observations: list[Observation] = []
    for chart in dashboard.charts:
        if chart.id in selected:
            observations.extend(chart.observations)
    return observations


def candidate_observations(
    observations: Iterable[Observation], card: MonitorCard
) -> list[Observation]:
    result = []
    for observation in observations:
        if observation.freshness and "stale" in observation.freshness.lower():
            result.append(observation)
        elif (
            observation.change_pct is not None
            and abs(observation.change_pct) >= card.materiality_threshold_pct
        ):
            result.append(observation)
    return result


def evidence_statements(observations: Iterable[Observation]) -> list[str]:
    statements: list[str] = []
    for observation in observations:
        if observation.freshness and "stale" in observation.freshness.lower():
            statements.append(f"{observation.chart_title} is {observation.freshness}.")
            continue
        if observation.change_pct is None:
            statements.append(f"{observation.chart_title} has no current value.")
            continue
        direction = "increased" if observation.change_pct > 0 else "declined"
        statement = f"{observation.chart_title} {direction} {abs(observation.change_pct):.1f}% versus baseline."
        if observation.dimensions:
            detail = ", ".join(f"{key}={value:g}" for key, value in observation.dimensions.items())
            statement += f" Dimensions: {detail}."
        statements.append(statement)
    return statements

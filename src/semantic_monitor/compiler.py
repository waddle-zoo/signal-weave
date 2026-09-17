from __future__ import annotations

from typing import Any

from .models import MonitorCard, MonitorPlan

SUPPORTED_OPERATIONS: dict[str, str] = {
    "percent_change": "Compare current and baseline values using the source chart's metric definition.",
    "baseline_comparison": "Compare the selected comparison windows available on the monitor card.",
    "freshness_check": "Check whether the source data is fresh enough to interpret.",
    "seasonality_check": "Compare the movement with an owner-described seasonal or periodic pattern.",
    "dimension_contribution": "Inspect available dimensions to identify where the movement is concentrated.",
    "cross_chart_comparison": "Compare related selected charts for corroborating or contradictory signals.",
}


def base_plan(card: MonitorCard) -> MonitorPlan:
    """Build the minimum safe plan used when a semantic planner returns no operations."""
    operations = ["percent_change", "baseline_comparison", "freshness_check"]
    return MonitorPlan(
        monitor_id=card.id,
        dashboard_id=card.dashboard_id,
        selected_chart_ids=card.chart_ids,
        comparison_windows=card.comparison_windows,
        operations=list(dict.fromkeys(operations)),
        investigation_questions=card.investigation_hints,
        recipient_keys=[recipient.key for recipient in card.recipients],
        compiled_by="jev-latest",
        source_intent=card.intent,
    )


async def compile_with_typesafe(
    card: MonitorCard, typesafe: Any, state: dict[str, Any] | None = None
) -> MonitorPlan:
    """Compile owner intent into the fixed analysis capabilities this service can execute."""
    state = state or {}
    state = {
        "monitor_card": card.model_dump(mode="json"),
        "dashboard": state.get("dashboard", {}),
        "available_operations": [
            {"key": key, "description": description}
            for key, description in SUPPORTED_OPERATIONS.items()
        ],
    }
    answers = await typesafe.compile_plan(state, card)
    base = base_plan(card)
    selected = answers.get("operations", [])
    known = set(SUPPORTED_OPERATIONS)
    operations = [value for value in selected if value in known]
    selected_window = answers.get("baseline")
    comparison_windows = (
        [selected_window]
        if selected_window in card.comparison_windows
        else base.comparison_windows
    )
    return base.model_copy(
        update={
            "operations": operations or base.operations,
            "comparison_windows": comparison_windows,
            "compiled_by": typesafe.name,
        }
    )

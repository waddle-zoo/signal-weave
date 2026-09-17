from __future__ import annotations

from typing import Any

from .models import MonitorPlan, MonitorWorkflow

SUPPORTED_OPERATIONS: dict[str, str] = {
    "percent_change": "Compare current and baseline values for numeric observations.",
    "baseline_comparison": "Compare the workflow's selected comparison windows.",
    "freshness_check": "Check whether source data is fresh enough to interpret.",
    "seasonality_check": "Compare movement with an owner-described seasonal or periodic pattern.",
    "dimension_contribution": "Inspect available dimensions to identify where movement is concentrated.",
    "cross_source_comparison": "Compare observations and evidence across the selected sources.",
    "related_context_check": "Use source-provided relationships and context to interpret a signal.",
}


def base_plan(workflow: MonitorWorkflow) -> MonitorPlan:
    """Build the minimum safe plan; it never invents source-specific execution."""
    return MonitorPlan(
        workflow_id=workflow.id,
        selected_source_keys=[source.key for source in workflow.sources],
        comparison_windows=workflow.comparison_windows,
        operations=["percent_change", "baseline_comparison", "freshness_check"],
        investigation_questions=workflow.investigation_hints,
        recipient_keys=[recipient.key for recipient in workflow.recipients],
        compiled_by="jev-latest",
        source_intent=workflow.intent,
    )


async def compile_with_typesafe(
    workflow: MonitorWorkflow, typesafe: Any, state: dict[str, Any] | None = None
) -> MonitorPlan:
    """Compile owner intent into the fixed capabilities this service can execute."""
    state = state or {}
    state = {
        "workflow": workflow.model_dump(mode="json"),
        "sources": state.get("sources", []),
        "available_operations": [
            {"key": key, "description": description}
            for key, description in SUPPORTED_OPERATIONS.items()
        ],
    }
    answers = await typesafe.compile_plan(state, workflow)
    base = base_plan(workflow)
    selected = answers.get("operations", [])
    known = set(SUPPORTED_OPERATIONS)
    operations = [value for value in selected if value in known]
    selected_window = answers.get("baseline")
    comparison_windows = (
        [selected_window]
        if selected_window in workflow.comparison_windows
        else base.comparison_windows
    )
    selected_sources = [
        key for key in answers.get("source_keys", base.selected_source_keys)
        if key in base.selected_source_keys
    ]
    return base.model_copy(
        update={
            "operations": operations or base.operations,
            "comparison_windows": comparison_windows,
            "selected_source_keys": selected_sources or base.selected_source_keys,
            "compiled_by": typesafe.name,
        }
    )

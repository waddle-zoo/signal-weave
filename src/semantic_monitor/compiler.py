from __future__ import annotations

from typing import Any

from .models import MonitorCard, MonitorPlan


def heuristic_compile(card: MonitorCard) -> MonitorPlan:
    """Compile a card into a bounded plan without asking a generative model."""
    operations = ["percent_change", "baseline_comparison", "freshness_check"]
    intent = card.intent.lower()
    if any(word in intent for word in ("season", "seasonal", "normal variation")):
        operations.append("seasonality_check")
    if any(word in intent for word in ("segment", "regional", "mobile", "enterprise", "smb")):
        operations.append("dimension_contribution")
    if any(word in intent for word in ("related", "together", "compare", "inspect")):
        operations.append("cross_chart_comparison")
    return MonitorPlan(
        monitor_id=card.id,
        dashboard_id=card.dashboard_id,
        selected_chart_ids=card.chart_ids,
        comparison_windows=card.comparison_windows,
        operations=list(dict.fromkeys(operations)),
        investigation_questions=card.investigation_hints,
        recipient_keys=[recipient.key for recipient in card.recipients],
        compiled_by="heuristic",
        source_intent=card.intent,
    )


async def compile_with_typesafe(card: MonitorCard, typesafe: Any) -> MonitorPlan:
    """Compile intent with narrow TypeSafe selections, never arbitrary SQL."""
    state = {
        "monitor_card": card.model_dump(mode="json"),
        "available_operations": [
            "percent_change",
            "baseline_comparison",
            "freshness_check",
            "seasonality_check",
            "dimension_contribution",
            "cross_chart_comparison",
        ],
    }
    answers = await typesafe.compile_plan(state, card)
    base = heuristic_compile(card)
    selected = answers.get("operations", [])
    operations = [value for value in selected if value in state["available_operations"]]
    return base.model_copy(
        update={"operations": operations or base.operations, "compiled_by": "jev"}
    )

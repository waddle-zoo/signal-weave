from __future__ import annotations

from typing import Any

from .models import InsightCard, InsightPlan

# This is deliberately a small capability vocabulary. Jev can select which
# capabilities fit a card, but it cannot invent executable operations.
SUPPORTED_CAPABILITIES: dict[str, str] = {
    "percent_change": "Compare current and baseline values for numeric observations.",
    "baseline_comparison": "Compare the card's selected comparison windows.",
    "freshness_check": "Check whether source data is fresh enough to interpret.",
    "seasonality_check": "Compare movement with an owner-described seasonal or periodic pattern.",
    "dimension_contribution": "Inspect dimensions to identify where movement is concentrated.",
    "cross_source_comparison": "Compare observations and evidence across selected sources.",
    "related_context_check": "Use source-provided relationships and context to interpret a signal.",
    "watch_for_checks": "Evaluate each owner-authored item in the card's things-to-look-for list.",
    "question_checks": "Evaluate whether the available evidence supports each owner-authored question.",
    "rank_relevant_signals": "Rank the observations most relevant to the card's stated purpose.",
}


def _base_capabilities(card: InsightCard) -> list[str]:
    capabilities = ["percent_change", "baseline_comparison", "freshness_check"]
    if len(card.sources) > 1:
        capabilities.append("cross_source_comparison")
    if card.watch_for:
        capabilities.append("watch_for_checks")
    if card.questions:
        capabilities.append("question_checks")
    return capabilities


def base_plan(card: InsightCard) -> InsightPlan:
    """Build the minimum safe plan; it never invents source-specific execution."""
    return InsightPlan(
        card_id=card.id,
        card_version=card.version,
        selected_source_keys=[source.key for source in card.sources],
        comparison_windows=card.comparison_windows,
        capabilities=_base_capabilities(card),
        watch_for=card.watch_for,
        questions=card.questions,
        delivery_method_keys=[method.key for method in card.delivery_methods],
        compiled_by="jev-latest",
        card_scope=f"{card.what_to_watch}\nWhy: {card.why_watch}",
        investigation_mode=card.investigation_mode,
        max_investigation_sources=card.max_investigation_sources,
    )


async def compile_with_typesafe(
    card: InsightCard, typesafe: Any, state: dict[str, Any] | None = None
) -> InsightPlan:
    """Compile owner language into the fixed capabilities this service executes."""
    state = state or {}
    state = {
        "card": card.model_dump(mode="json"),
        "insight_card": card.model_dump(mode="json"),
        "sources": state.get("sources", []),
        "available_capabilities": [
            {"key": key, "description": description}
            for key, description in SUPPORTED_CAPABILITIES.items()
        ],
    }
    answers = await typesafe.compile_plan(state, card)
    base = base_plan(card)
    selected = answers.get("capabilities", [])
    known = set(SUPPORTED_CAPABILITIES)
    capabilities = [value for value in selected if value in known]
    selected_window = answers.get("baseline")
    comparison_windows = (
        [selected_window]
        if selected_window in card.comparison_windows
        else base.comparison_windows
    )
    selected_sources = [
        key for key in answers.get("source_keys", base.selected_source_keys)
        if key in base.selected_source_keys
    ]
    return base.model_copy(
        update={
            "capabilities": capabilities or base.capabilities,
            "comparison_windows": comparison_windows,
            "selected_source_keys": selected_sources or base.selected_source_keys,
            "compiled_by": typesafe.name,
        }
    )

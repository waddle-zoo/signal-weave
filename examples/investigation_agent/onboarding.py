"""Pure caller-owned bridge from business intent to a native draft call.

This module deliberately does not discover, infer, call, or persist anything.
The caller supplies the already-approved source and destination directories.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from signalweave.models import (
    InsightCard,
    InvestigationQuestions,
    Outcome,
    SourceRef,
    WatchConditions,
)


class RouteIntent(BaseModel):
    """One explicit outcome-to-approved-destination selection."""

    model_config = ConfigDict(extra="forbid")

    destination_key: str = Field(min_length=1)
    outcome: Outcome
    method_key: str | None = Field(default=None, min_length=1)


class DraftIntent(BaseModel):
    """Free-form business intent plus exact selectors into approved directories."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    what_to_watch: str = Field(min_length=1)
    why_watch: str = Field(min_length=1)
    decision_guidance: str
    source_keys: list[str]
    routes: list[RouteIntent]
    watch_for: WatchConditions = Field(default_factory=list)
    questions: InvestigationQuestions = Field(default_factory=list)
    evidence_requirements: dict[str, StrictBool] = Field(default_factory=dict)
    follow_up_guidance: str = ""


class _ApprovedDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    destination: str = Field(min_length=1)


def _approved_sources(items: list[SourceRef | dict[str, Any]]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for item in items:
        source = SourceRef.model_validate(deepcopy(item))
        if source.key in sources:
            raise ValueError(f"duplicate approved source key: {source.key}")
        sources[source.key] = source.model_dump(mode="python")
    return sources


def _approved_destinations(items: list[dict[str, Any]]) -> dict[str, _ApprovedDestination]:
    destinations: dict[str, _ApprovedDestination] = {}
    for item in items:
        destination = _ApprovedDestination.model_validate(deepcopy(item))
        if destination.key in destinations:
            raise ValueError(f"duplicate approved destination key: {destination.key}")
        destinations[destination.key] = destination
    return destinations


def draft_arguments(
    intent: DraftIntent | dict[str, Any],
    approved_sources: list[SourceRef | dict[str, Any]],
    approved_destinations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build serializable kwargs for ``draft_insight_card``.

    Selectors are exact directory keys.  All values that can affect source
    access or delivery routing come from those directories, never from prose.
    """

    draft = DraftIntent.model_validate(intent)
    source_directory = _approved_sources(approved_sources)
    destination_directory = _approved_destinations(approved_destinations)

    if len(draft.source_keys) != len(set(draft.source_keys)):
        raise ValueError("duplicate source selector")
    unknown_sources = [key for key in draft.source_keys if key not in source_directory]
    if unknown_sources:
        raise ValueError(f"unknown approved source key: {unknown_sources[0]}")
    selected_keys = set(draft.source_keys)
    missing_required = [
        key for key, source in source_directory.items()
        if source["required"] and key not in selected_keys
    ]
    if missing_required:
        raise ValueError(f"required approved source was not selected: {missing_required[0]}")
    if not draft.source_keys:
        raise ValueError("at least one approved source must be selected")

    routes: list[dict[str, Any]] = []
    endpoint_routes: dict[str, list[RouteIntent]] = {}
    for route in draft.routes:
        destination = destination_directory.get(route.destination_key)
        if destination is None:
            raise ValueError(f"unknown approved destination key: {route.destination_key}")
        method_key = route.method_key or route.destination_key
        method = {
            "key": method_key,
            "outcome": route.outcome.value,
            "label": destination.label,
            "destination": destination.destination,
        }
        if any(existing["key"] == method_key for existing in routes):
            raise ValueError(f"duplicate delivery method key: {method_key}")
        routes.append(method)
        endpoint_routes.setdefault(destination.destination, []).append(route)

    for endpoint, endpoint_intents in endpoint_routes.items():
        if len(endpoint_intents) > 1 and any(route.method_key is None for route in endpoint_intents):
            raise ValueError(
                "routes sharing an endpoint require explicit distinct method_key values: "
                + endpoint
            )

    arguments = {
        "title": draft.title,
        "what_to_watch": draft.what_to_watch,
        "why_watch": draft.why_watch,
        "watch_for": list(draft.watch_for),
        "questions": list(draft.questions),
        "evidence_requirements": deepcopy(draft.evidence_requirements),
        "decision_guidance": draft.decision_guidance,
        "follow_up_guidance": draft.follow_up_guidance,
        "sources": [deepcopy(source_directory[key]) for key in draft.source_keys],
        "delivery_methods": routes,
    }

    # Use the native model as a compatibility check, but never return its
    # generated id, defaults, principal, history, plan, or approval state.
    InsightCard(id="draft-intent-validation", **deepcopy(arguments))
    return arguments

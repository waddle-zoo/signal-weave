from __future__ import annotations

from collections.abc import Iterable

from .models import Observation, ResourceSnapshot


def observations_for_plan(
    resources: Iterable[ResourceSnapshot], plan_source_keys: Iterable[str]
) -> list[Observation]:
    """Flatten the selected adapter snapshots without knowing their provider."""
    selected = set(plan_source_keys)
    return [
        observation
        for resource in resources
        if resource.source_key in selected
        for observation in resource.observations
    ]


def candidate_observations(
    observations: Iterable[Observation],
) -> list[Observation]:
    """Order changed or incomplete observations first without hiding the rest.

    This is only an evidence ordering aid. The engine always sends every
    normalized observation to the configured judger, so a card with a hundred
    metrics does not silently become a top-k alert.
    """
    result: list[Observation] = []
    for observation in observations:
        if observation.freshness and "stale" in observation.freshness.lower():
            result.append(observation)
        elif observation.change_pct is not None and observation.change_pct != 0:
            result.append(observation)
    return result


def evidence_statements(observations: Iterable[Observation]) -> list[str]:
    statements: list[str] = []
    for observation in observations:
        label = observation.subject_label or observation.subject_id
        if observation.freshness and "stale" in observation.freshness.lower():
            statements.append(f"{label} is {observation.freshness}.")
            continue
        if observation.change_pct is None:
            statements.append(f"{label} has no current comparable value.")
            continue
        direction = "increased" if observation.change_pct > 0 else "declined"
        statement = (
            f"{label} {direction} {abs(observation.change_pct):.1f}% versus baseline."
        )
        if observation.dimensions:
            detail = ", ".join(
                f"{key}={value}" for key, value in observation.dimensions.items()
            )
            statement += f" Dimensions: {detail}."
        statements.append(statement)
    return statements

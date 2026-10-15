"""Fresh offline fixtures for policy composition, not a live Jev benchmark.

The cases intentionally contain only a plain-English owner policy, evidence
facts, and an independently frozen expected result.  They do not contain a
hand-authored atomic-check tree or boolean composition plan: the onboarding
workflow under evaluation is expected to compile those from ``policy`` once
per company before it sees measurements.

The expected labels are expert-supplied evaluation truth.  They are not
LLM-onboarded, not copied from a model response, and not used as runtime
company configuration.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

LABEL_SOURCE = "expert-supplied; frozen independently of model outputs; not LLM-onboarded"
_DESTINATIONS = {
    "notify": "primary-owner",
    "investigate": "review-owner",
    "insufficient_data": "data-owner",
}

_FIELD_CATALOGS = {
    "cobalt-market": {
        "total_decline_pct": {
            "type": "number",
            "description": "Percent decline in comparable total settled orders; positive means decline.",
        },
        "max_region_decline_pct": {
            "type": "number",
            "description": "Largest percent decline among comparable regions; null when regional data is absent.",
        },
    },
    "maple-mobility": {
        "on_time_pct": {
            "type": "number",
            "description": "Current weekly on-time delivery percentage for the comparable fleet.",
        },
        "cancellation_delta_pp": {
            "type": "number",
            "description": "Current cancellation rate minus baseline rate, in percentage points; null when absent.",
        },
    },
    "quartz-care": {
        "release_priority": {
            "type": "string",
            "description": "Owner-defined priority class copied from the release record; semantic facts, not a threshold.",
        },
    },
}


def _decline_pct(baseline: float | None, current: float | None) -> float | None:
    if baseline is None or current is None:
        return None
    return round((baseline - current) / baseline * 100, 2)


def _cobalt_measurements(
    total: tuple[float, float], regions: dict[str, tuple[float, float]] | None,
) -> dict[str, float | None]:
    declines = [] if regions is None else [
        _decline_pct(baseline, current) for baseline, current in regions.values()
    ]
    return {
        "total_decline_pct": _decline_pct(*total),
        "max_region_decline_pct": max(declines) if declines else None,
    }


def _maple_measurements(
    *, on_time_pct: float, cancellation_rate: tuple[float, float] | None,
) -> dict[str, float | None]:
    cancellation_delta = None
    if cancellation_rate is not None:
        baseline, current = cancellation_rate
        cancellation_delta = round(current - baseline, 2)
    return {
        "on_time_pct": on_time_pct,
        "cancellation_delta_pp": cancellation_delta,
    }


def _quartz_measurements(priority: str | None) -> dict[str, str | None]:
    return {"release_priority": priority}


def _case(
    case_id: str,
    company: str,
    policy: str,
    facts: list[tuple[str, str]],
    outcome: str,
    reason: str,
    *,
    tags: tuple[str, ...],
    measurements: dict[str, Any],
    recipients: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build one JSON-ready case while keeping the public schema small."""
    return {
        "id": case_id,
        "company": company,
        "policy": {
            "text": policy,
            "destinations": deepcopy(_DESTINATIONS),
        },
        "field_catalog": deepcopy(_FIELD_CATALOGS[company]),
        "measurements": deepcopy(measurements),
        "facts": [{"id": fact_id, "statement": statement} for fact_id, statement in facts],
        "expected": {
            "outcome": outcome,
            "recipients": list(recipients),
            "reason": reason,
        },
        "metadata": {
            "label_source": LABEL_SOURCE,
            "tags": list(tags),
        },
    }


_CASES = [
    _case(
        "cobalt-orders-flat-total",
        "cobalt-market",
        (
            "For comparable weekly orders, notify the primary owner when total orders "
            "decline by 10% or more OR any region declines by 15% or more. Both total "
            "and regional populations must be comparable. An approved migration-freeze "
            "exception overrides those triggers and means ignore. If comparability is "
            "not established, send insufficient_data to the data owner."
        ),
        [
            ("f1", "Total orders were 1,000 last week and 1,000 this week."),
            ("f2", "East-region orders were 500 last week and 400 this week."),
            ("f3", "West-region orders were 500 last week and 600 this week."),
            ("f4", "The total and regional populations use the same settled-order definition."),
            ("f5", "No approved migration-freeze exception covers this week."),
        ],
        "notify",
        "The aggregate is flat, but the east-region decline independently satisfies the OR branch.",
        tags=("or_vs_and", "flat_total", "opposing_movements"),
        measurements=_cobalt_measurements((1000, 1000), {"east": (500, 400), "west": (500, 600)}),
        recipients=("primary-owner",),
    ),
    _case(
        "cobalt-orders-quiet",
        "cobalt-market",
        (
            "For comparable weekly orders, notify the primary owner when total orders "
            "decline by 10% or more OR any region declines by 15% or more. Both total "
            "and regional populations must be comparable. An approved migration-freeze "
            "exception overrides those triggers and means ignore. If comparability is "
            "not established, send insufficient_data to the data owner."
        ),
        [
            ("f1", "Total orders were 1,000 last week and 950 this week."),
            ("f2", "East-region orders were 500 last week and 460 this week."),
            ("f3", "West-region orders were 500 last week and 490 this week."),
            ("f4", "The total and regional populations use the same settled-order definition."),
            ("f5", "No approved migration-freeze exception covers this week."),
        ],
        "ignore",
        "Neither the 10% total decline nor the 15% regional decline threshold is met.",
        tags=("quiet", "or_vs_and", "near_threshold"),
        measurements=_cobalt_measurements((1000, 950), {"east": (500, 460), "west": (500, 490)}),
    ),
    _case(
        "cobalt-orders-exception",
        "cobalt-market",
        (
            "For comparable weekly orders, notify the primary owner when total orders "
            "decline by 10% or more OR any region declines by 15% or more. Both total "
            "and regional populations must be comparable. An approved migration-freeze "
            "exception overrides those triggers and means ignore. If comparability is "
            "not established, send insufficient_data to the data owner."
        ),
        [
            ("f1", "Total orders fell from 1,000 to 800."),
            ("f2", "East-region orders fell from 500 to 390."),
            ("f3", "The total and regional populations remain comparable."),
            ("f4", "A signed owner notice approves a migration freeze for this exact week."),
        ],
        "ignore",
        "Both trigger branches are present, but the explicitly approved exception overrides them.",
        tags=("exception_override", "or_vs_and"),
        measurements=_cobalt_measurements((1000, 800), {"east": (500, 390)}),
    ),
    _case(
        "cobalt-orders-missing-context",
        "cobalt-market",
        (
            "For comparable weekly orders, notify the primary owner when total orders "
            "decline by 10% or more OR any region declines by 15% or more. Both total "
            "and regional populations must be comparable. An approved migration-freeze "
            "exception overrides those triggers and means ignore. If comparability is "
            "not established, send insufficient_data to the data owner."
        ),
        [
            ("f1", "Total orders fell from 1,000 to 840."),
            ("f2", "The regional breakdown is absent for the current week."),
            ("f3", "The source does not establish whether the total and regional populations match."),
            ("f4", "No approved migration-freeze exception is available."),
        ],
        "insufficient_data",
        "A total decline is visible, but the policy requires comparable regional context before routing it.",
        tags=("missing_context", "insufficient_data"),
        measurements=_cobalt_measurements((1000, 840), None),
        recipients=("data-owner",),
    ),
    _case(
        "maple-delivery-both-triggers",
        "maple-mobility",
        (
            "For the same weekly fleet, notify the primary owner only when on-time "
            "delivery falls below 92% AND the cancellation rate rises by at least 2 "
            "percentage points. A signed weather-closure exception covering the week "
            "overrides both triggers and means ignore. If an exception is claimed but "
            "its approval or scope conflicts, investigate. If either required metric is "
            "missing, send insufficient_data to the data owner. If only one trigger holds, ignore."
        ),
        [
            ("f1", "On-time delivery fell from 95% to 90% for the same fleet."),
            ("f2", "The cancellation rate rose from 3% to 6% for that fleet."),
            ("f3", "No weather-closure exception covers the comparison week."),
        ],
        "notify",
        "Both conjunctive trigger conditions are established and no exception applies.",
        tags=("and", "directional_change"),
        measurements=_maple_measurements(on_time_pct=90, cancellation_rate=(3, 6)),
        recipients=("primary-owner",),
    ),
    _case(
        "maple-delivery-one-sided",
        "maple-mobility",
        (
            "For the same weekly fleet, notify the primary owner only when on-time "
            "delivery falls below 92% AND the cancellation rate rises by at least 2 "
            "percentage points. A signed weather-closure exception covering the week "
            "overrides both triggers and means ignore. If an exception is claimed but "
            "its approval or scope conflicts, investigate. If either required metric is "
            "missing, send insufficient_data to the data owner. If only one trigger holds, ignore."
        ),
        [
            ("f1", "On-time delivery rose from 90% to 95% for the same fleet."),
            ("f2", "The cancellation rate rose from 3% to 6% for that fleet."),
            ("f3", "No weather-closure exception covers the comparison week."),
        ],
        "ignore",
        "The cancellation-rate increase alone does not satisfy the required on-time decline condition.",
        tags=("and", "quiet", "directional_increase"),
        measurements=_maple_measurements(on_time_pct=95, cancellation_rate=(3, 6)),
    ),
    _case(
        "maple-delivery-exception-conflict",
        "maple-mobility",
        (
            "For the same weekly fleet, notify the primary owner only when on-time "
            "delivery falls below 92% AND the cancellation rate rises by at least 2 "
            "percentage points. A signed weather-closure exception covering the week "
            "overrides both triggers and means ignore. If an exception is claimed but "
            "its approval or scope conflicts, investigate. If either required metric is "
            "missing, send insufficient_data to the data owner. If only one trigger holds, ignore."
        ),
        [
            ("f1", "On-time delivery fell from 95% to 89% for the same fleet."),
            ("f2", "The cancellation rate rose from 3% to 7% for that fleet."),
            ("f3", "One current schedule says a signed weather closure covers the whole fleet."),
            ("f4", "An equally authoritative current schedule says the closure covers only two depots."),
        ],
        "investigate",
        "Both triggers hold, but the exception scope conflicts, so the owner must resolve it before action.",
        tags=("and", "exception_conflict", "conflicting_evidence"),
        measurements=_maple_measurements(on_time_pct=89, cancellation_rate=(3, 7)),
        recipients=("review-owner",),
    ),
    _case(
        "maple-delivery-missing-rate",
        "maple-mobility",
        (
            "For the same weekly fleet, notify the primary owner only when on-time "
            "delivery falls below 92% AND the cancellation rate rises by at least 2 "
            "percentage points. A signed weather-closure exception covering the week "
            "overrides both triggers and means ignore. If an exception is claimed but "
            "its approval or scope conflicts, investigate. If either required metric is "
            "missing, send insufficient_data to the data owner. If only one trigger holds, ignore."
        ),
        [
            ("f1", "On-time delivery fell from 95% to 89% for the same fleet."),
            ("f2", "The current cancellation-rate value is missing."),
            ("f3", "No weather-closure exception covers the comparison week."),
        ],
        "insufficient_data",
        "The AND policy cannot be applied because the cancellation-rate condition is unknown.",
        tags=("and", "missing_context", "insufficient_data"),
        measurements=_maple_measurements(on_time_pct=89, cancellation_rate=None),
        recipients=("data-owner",),
    ),
    _case(
        "quartz-release-high-priority",
        "quartz-care",
        (
            "Notify the primary owner when a high-priority contract release is missing "
            "signed reconciliation. Routine releases do not trigger. A signed release-manager "
            "reconciliation overrides a stale checklist. If the priority classification or "
            "reconciliation status is missing or conflicting, send "
            "insufficient_data to the data owner."
        ),
        [
            ("f1", "The release record classifies the contract release as high priority."),
            ("f2", "The release checklist says signed reconciliation is missing."),
            ("f3", "No signed release-manager reconciliation is present."),
        ],
        "notify",
        "This qualitative condition is directly established: high priority plus missing signed reconciliation.",
        tags=("qualitative_semantics", "exception_override"),
        measurements=_quartz_measurements("high"),
        recipients=("primary-owner",),
    ),
    _case(
        "quartz-release-routine",
        "quartz-care",
        (
            "Notify the primary owner when a high-priority contract release is missing "
            "signed reconciliation. Routine releases do not trigger. A signed release-manager "
            "reconciliation overrides a stale checklist. If the priority classification or "
            "reconciliation status is missing or conflicting, send "
            "insufficient_data to the data owner."
        ),
        [
            ("f1", "The release record classifies the contract release as routine priority."),
            ("f2", "The release checklist says signed reconciliation is missing."),
            ("f3", "No signed release-manager reconciliation is present."),
        ],
        "ignore",
        "Missing signed reconciliation is not actionable under this policy for a routine release.",
        tags=("qualitative_semantics", "quiet"),
        measurements=_quartz_measurements("routine"),
    ),
    _case(
        "quartz-release-missing-priority",
        "quartz-care",
        (
            "Notify the primary owner when a high-priority contract release is missing "
            "signed reconciliation. Routine releases do not trigger. A signed release-manager "
            "reconciliation overrides a stale checklist. If the priority classification or "
            "reconciliation status is missing or conflicting, send "
            "insufficient_data to the data owner."
        ),
        [
            ("f1", "The release checklist says signed reconciliation is missing."),
            ("f2", "The release evidence does not include a priority classification."),
            ("f3", "No signed release-manager reconciliation is present."),
        ],
        "insufficient_data",
        "The policy cannot distinguish its high-priority trigger from its routine exclusion.",
        tags=("qualitative_semantics", "missing_context", "insufficient_data"),
        measurements=_quartz_measurements(None),
        recipients=("data-owner",),
    ),
    _case(
        "quartz-release-conflicting-priority",
        "quartz-care",
        (
            "Notify the primary owner when a high-priority contract release is missing "
            "signed reconciliation. Routine releases do not trigger. A signed release-manager "
            "reconciliation overrides a stale checklist. If the priority classification or "
            "reconciliation status is missing or conflicting, send "
            "insufficient_data to the data owner."
        ),
        [
            ("f1", "The release record classifies the contract release as high priority."),
            ("f2", "An equally authoritative release record classifies the same release as routine priority."),
            ("f3", "The release checklist says signed reconciliation is missing."),
            ("f4", "No signed release-manager reconciliation is present."),
        ],
        "insufficient_data",
        "Conflicting priority classifications prevent applying either the high-priority trigger or routine exclusion.",
        tags=("qualitative_semantics", "conflicting_evidence", "insufficient_data"),
        measurements=_quartz_measurements(None),
        recipients=("data-owner",),
    ),
]


def cases() -> list[dict[str, Any]]:
    """Return fresh copies so a trial cannot mutate the frozen fixture."""
    return deepcopy(_CASES)


__all__ = ["LABEL_SOURCE", "cases"]

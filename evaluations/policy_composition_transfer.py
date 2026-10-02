"""Fresh transfer fixtures for the policy-composition trial.

These cases reuse the three reviewed policy and catalog contracts from the
development fixture, but contain new wording, values, and case identities.
Expected outcomes are fixed here before any model output exists.  The transfer
set excludes unresolved policy language: every exception, comparison basis,
required field, and conflict is explicit in the facts.

This module is deliberately data-only.  It does not import or execute the
policy compiler, numeric evaluator, or composition implementation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

LABEL_SOURCE = "expert-supplied; frozen before model outputs; transfer fixture only"

# Deliberately excluded from this transfer set because they would test policy
# authoring ambiguity rather than ordered composition: unclear exception scope,
# conflicting comparison windows, unstated population definitions, and causal
# explanations not present in the owner policies.
EXCLUDED_AMBIGUITIES = (
    "unclear exception scope",
    "conflicting comparison windows",
    "unstated population definitions",
    "causal explanations beyond the owner policy",
)

_DESTINATIONS = {
    "notify": "primary-owner",
    "investigate": "review-owner",
    "insufficient_data": "data-owner",
}

_POLICIES = {
    "cobalt-market": (
        "For comparable weekly orders, notify the primary owner when total orders "
        "decline by 10% or more OR any region declines by 15% or more. Both total "
        "and regional populations must be comparable. An approved migration-freeze "
        "exception overrides those triggers and means ignore. If comparability is "
        "not established, send insufficient_data to the data owner."
    ),
    "maple-mobility": (
        "For the same weekly fleet, notify the primary owner only when on-time "
        "delivery falls below 92% AND the cancellation rate rises by at least 2 "
        "percentage points. A signed weather-closure exception covering the week "
        "overrides both triggers and means ignore. If an exception is claimed but "
        "its approval or scope conflicts, investigate. If either required metric is "
        "missing, send insufficient_data to the data owner. If only one trigger holds, ignore."
    ),
    "quartz-care": (
        "Notify the primary owner when a high-priority contract release is missing "
        "signed reconciliation. Routine releases do not trigger. A signed release-manager "
        "reconciliation overrides a stale checklist. If the priority classification or "
        "reconciliation status is missing or conflicting, send insufficient_data to "
        "the data owner."
    ),
}

_CATALOGS = {
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


def _case(
    case_id: str,
    company: str,
    facts: list[tuple[str, str]],
    measurements: dict[str, Any],
    outcome: str,
    reason: str,
    *,
    tags: tuple[str, ...],
    recipients: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": case_id,
        "company": company,
        "policy": {
            "text": _POLICIES[company],
            "destinations": deepcopy(_DESTINATIONS),
        },
        "field_catalog": deepcopy(_CATALOGS[company]),
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
        "cobalt-transfer-opposed-nonzero-total",
        "cobalt-market",
        [
            ("f1", "Settled orders changed from 1,000 to 1,020 for the same weekly population."),
            ("f2", "North-region orders changed from 700 to 550."),
            ("f3", "South-region orders changed from 300 to 470."),
            ("f4", "The total and regional populations use the same settled-order definition."),
            ("f5", "No migration-freeze exception covers this week."),
        ],
        {"total_decline_pct": -2.0, "max_region_decline_pct": 21.43},
        "notify",
        "The north-region decline is at least 15%, so the regional OR branch applies even though the total increased.",
        tags=("opposing_movements", "unequal_nonzero_totals", "or_branch"),
        recipients=("primary-owner",),
    ),
    _case(
        "cobalt-transfer-exact-ten-fifteen",
        "cobalt-market",
        [
            ("f1", "Settled orders changed from 1,000 to 900 for the same weekly population."),
            ("f2", "North-region orders changed from 600 to 510."),
            ("f3", "South-region orders changed from 400 to 390."),
            ("f4", "The total and regional populations are comparable."),
            ("f5", "No migration-freeze exception covers this week."),
        ],
        {"total_decline_pct": 10.0, "max_region_decline_pct": 15.0},
        "notify",
        "Both the total 10% boundary and the regional 15% boundary satisfy their inclusive policy thresholds.",
        tags=("exact_boundary", "inclusive_thresholds"),
        recipients=("primary-owner",),
    ),
    _case(
        "cobalt-transfer-approved-freeze",
        "cobalt-market",
        [
            ("f1", "Settled orders changed from 1,200 to 900 for the same weekly population."),
            ("f2", "West-region orders changed from 800 to 560."),
            ("f3", "The total and regional populations are comparable."),
            ("f4", "A signed owner notice approves a migration freeze for this exact week."),
        ],
        {"total_decline_pct": 25.0, "max_region_decline_pct": 30.0},
        "ignore",
        "The explicitly approved migration-freeze exception overrides both notification triggers.",
        tags=("approved_exception", "exception_override"),
    ),
    _case(
        "cobalt-transfer-missing-regions",
        "cobalt-market",
        [
            ("f1", "Settled orders changed from 1,000 to 880."),
            ("f2", "The current regional export was not produced."),
            ("f3", "The source does not establish comparability for the missing regional population."),
            ("f4", "No migration-freeze exception covers this week."),
        ],
        {"total_decline_pct": 12.0, "max_region_decline_pct": None},
        "insufficient_data",
        "Regional comparability is required by the policy and is not established.",
        tags=("absent_required_metric", "missing_context"),
        recipients=("data-owner",),
    ),
    _case(
        "maple-transfer-both-triggers",
        "maple-mobility",
        [
            ("f1", "On-time delivery fell from 96% to 91% for the same weekly fleet."),
            ("f2", "The cancellation rate rose from 4% to 7% for that fleet."),
            ("f3", "No weather-closure exception covers the comparison week."),
        ],
        {"on_time_pct": 91.0, "cancellation_delta_pp": 3.0},
        "notify",
        "Both conjunctive trigger conditions hold and no approved exception applies.",
        tags=("and_branch", "both_triggers"),
        recipients=("primary-owner",),
    ),
    _case(
        "maple-transfer-one-trigger",
        "maple-mobility",
        [
            ("f1", "On-time delivery fell from 96% to 90% for the same weekly fleet."),
            ("f2", "The cancellation rate rose from 4% to 5%, one percentage point."),
            ("f3", "No weather-closure exception covers the comparison week."),
        ],
        {"on_time_pct": 90.0, "cancellation_delta_pp": 1.0},
        "ignore",
        "Only the on-time condition holds; the policy requires both conditions.",
        tags=("and_branch", "one_false"),
    ),
    _case(
        "maple-transfer-strict-boundary",
        "maple-mobility",
        [
            ("f1", "On-time delivery changed from 94% to exactly 92% for the same weekly fleet."),
            ("f2", "The cancellation rate rose from 4% to exactly 6%."),
            ("f3", "No weather-closure exception covers the comparison week."),
        ],
        {"on_time_pct": 92.0, "cancellation_delta_pp": 2.0},
        "ignore",
        "The cancellation boundary is met, but on-time delivery is not below 92% as required.",
        tags=("strict_boundary", "one_false"),
    ),
    _case(
        "maple-transfer-missing-cancellation",
        "maple-mobility",
        [
            ("f1", "On-time delivery fell from 95% to 90% for the same weekly fleet."),
            ("f2", "The current cancellation-rate value is absent."),
            ("f3", "No weather-closure exception covers the comparison week."),
        ],
        {"on_time_pct": 90.0, "cancellation_delta_pp": None},
        "insufficient_data",
        "The cancellation condition is required by the AND policy but its value is missing.",
        tags=("absent_required_metric", "and_branch"),
        recipients=("data-owner",),
    ),
    _case(
        "quartz-transfer-high-priority",
        "quartz-care",
        [
            ("f1", "The release record classifies this contract release as high priority."),
            ("f2", "The signed-reconciliation field is explicitly missing."),
            ("f3", "No signed release-manager reconciliation is present."),
        ],
        {"release_priority": "high"},
        "notify",
        "A high-priority release is explicitly missing signed reconciliation.",
        tags=("qualitative_trigger",),
        recipients=("primary-owner",),
    ),
    _case(
        "quartz-transfer-routine-release",
        "quartz-care",
        [
            ("f1", "The release record classifies this contract release as routine priority."),
            ("f2", "The signed-reconciliation field is explicitly missing."),
            ("f3", "No signed release-manager reconciliation is present."),
        ],
        {"release_priority": "routine"},
        "ignore",
        "Routine releases do not trigger even when signed reconciliation is missing.",
        tags=("qualitative_exclusion",),
    ),
    _case(
        "quartz-transfer-signed-override",
        "quartz-care",
        [
            ("f1", "The release record classifies this contract release as high priority."),
            ("f2", "A stale checklist says signed reconciliation is missing."),
            ("f3", "A signed release-manager reconciliation explicitly covers this release and confirms completion."),
        ],
        {"release_priority": "high"},
        "ignore",
        "The signed release-manager reconciliation overrides the stale checklist.",
        tags=("signed_reconciliation_override", "approved_exception"),
    ),
    _case(
        "quartz-transfer-priority-conflict",
        "quartz-care",
        [
            ("f1", "The primary release record classifies this contract release as high priority."),
            ("f2", "A second authoritative release record classifies the same release as routine priority."),
            ("f3", "The signed-reconciliation field is explicitly missing."),
            ("f4", "No signed release-manager reconciliation is present."),
        ],
        {"release_priority": None},
        "insufficient_data",
        "Conflicting high and routine classifications prevent applying the policy safely.",
        tags=("priority_conflict", "high_vs_routine"),
        recipients=("data-owner",),
    ),
]


def cases() -> list[dict[str, Any]]:
    """Return independent copies of the frozen transfer cases."""
    return deepcopy(_CASES)


__all__ = ["EXCLUDED_AMBIGUITIES", "LABEL_SOURCE", "cases"]

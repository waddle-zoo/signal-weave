"""Abstract truth-table checks for the reviewed policy plans.

These vectors validate policy composition only. They intentionally do not load
fixture measurements, expected case labels, runtime events, or model outputs.
"""

import json
from pathlib import Path

import pytest

from evaluations.policy_composition_trial import Plan, compose

PLAN_PATH = Path(__file__).parents[1] / "evaluations/data/policy-composition-reviewed-plans.json"


def _plans():
    return json.loads(PLAN_PATH.read_text())["plans"]


def _evaluate(plan, state):
    """Apply the frozen plan schema: AND within a clause, OR across clauses."""
    reference = plan["default"]
    for rule in plan["rules"]:
        if any(
            all(state.get(key) == value for key, value in clause.items())
            for clause in rule["when"]
        ):
            reference = rule["outcome"]
            break
    actual = compose(Plan.model_validate(plan), state)
    assert actual == reference
    return actual


def test_reviewed_plans_keep_schema_compact_and_remove_duplicate_quartz_question():
    plans = _plans()
    assert set(plans) == {"cobalt-market", "maple-mobility", "quartz-care"}
    assert all(len(plan["checks"]) <= 5 for plan in plans.values())
    assert {check["id"] for check in plans["quartz-care"]["checks"]} == {
        "priority_known", "reconciliation_known", "signed_reconciliation_present",
        "high_priority_release",
    }
    assert "routine_release" not in {check["id"] for check in plans["quartz-care"]["checks"]}


@pytest.mark.parametrize("state,expected", [
    ({
        "freeze_approved": "false", "total_comparable": "true", "regional_comparable": "true",
        "total_decline_ge_10": "false", "regional_decline_ge_15": "false",
    }, "ignore"),
    ({
        "freeze_approved": "false", "total_comparable": "true", "regional_comparable": "true",
        "total_decline_ge_10": "false", "regional_decline_ge_15": "true",
    }, "notify"),
    ({
        "freeze_approved": "true", "total_comparable": "true", "regional_comparable": "true",
        "total_decline_ge_10": "true", "regional_decline_ge_15": "true",
    }, "ignore"),
    ({
        "freeze_approved": "unknown", "total_comparable": "unknown", "regional_comparable": "true",
        "total_decline_ge_10": "true", "regional_decline_ge_15": "true",
    }, "insufficient_data"),
    ({
        "freeze_approved": "false", "total_comparable": "true", "regional_comparable": "true",
        "total_decline_ge_10": "unknown", "regional_decline_ge_15": "false",
    }, "investigate"),
])
def test_cobalt_truth_vectors_cover_quiet_or_exception_and_data_gap_order(state, expected):
    assert _evaluate(_plans()["cobalt-market"], state) == expected


@pytest.mark.parametrize("state,expected", [
    ({
        "exception_conflict": "false", "exception_covers_week": "false",
        "required_metrics_available": "true", "on_time_below": "true", "cancellation_rise": "false",
    }, "ignore"),
    ({
        "exception_conflict": "false", "exception_covers_week": "false",
        "required_metrics_available": "true", "on_time_below": "true", "cancellation_rise": "true",
    }, "notify"),
    ({
        "exception_conflict": "false", "exception_covers_week": "true",
        "required_metrics_available": "true", "on_time_below": "true", "cancellation_rise": "true",
    }, "ignore"),
    ({
        "exception_conflict": "true", "exception_covers_week": "true",
        "required_metrics_available": "true", "on_time_below": "true", "cancellation_rise": "true",
    }, "investigate"),
    ({
        "exception_conflict": "unknown", "exception_covers_week": "false",
        "required_metrics_available": "false", "on_time_below": "unknown", "cancellation_rise": "unknown",
    }, "insufficient_data"),
    ({
        "exception_conflict": "false", "exception_covers_week": "false",
        "required_metrics_available": "unknown", "on_time_below": "unknown", "cancellation_rise": "true",
    }, "insufficient_data"),
    ({
        "exception_conflict": "false", "exception_covers_week": "unknown",
        "required_metrics_available": "true", "on_time_below": "true", "cancellation_rise": "true",
    }, "investigate"),
])
def test_maple_truth_vectors_cover_and_quiet_missing_exception_and_conflict(state, expected):
    assert _evaluate(_plans()["maple-mobility"], state) == expected


@pytest.mark.parametrize("state,expected", [
    ({
        "priority_known": "true", "reconciliation_known": "true",
        "signed_reconciliation_present": "false", "high_priority_release": "true",
    }, "notify"),
    ({
        "priority_known": "true", "reconciliation_known": "true",
        "signed_reconciliation_present": "false", "high_priority_release": "false",
    }, "ignore"),
    ({
        "priority_known": "true", "reconciliation_known": "true",
        "signed_reconciliation_present": "true", "high_priority_release": "true",
    }, "ignore"),
    ({
        "priority_known": "false", "reconciliation_known": "true",
        "signed_reconciliation_present": "false", "high_priority_release": "unknown",
    }, "insufficient_data"),
    ({
        "priority_known": "true", "reconciliation_known": "unknown",
        "signed_reconciliation_present": "true", "high_priority_release": "true",
    }, "insufficient_data"),
    ({
        "priority_known": "true", "reconciliation_known": "true",
        "signed_reconciliation_present": "false", "high_priority_release": "unknown",
    }, "investigate"),
])
def test_quartz_truth_vectors_cover_data_gaps_signed_override_and_high_vs_not_high(state, expected):
    assert _evaluate(_plans()["quartz-care"], state) == expected

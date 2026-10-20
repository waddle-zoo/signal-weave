"""Offline timing-contract tests for the opt-in calendar report cohort."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from evaluations import reviewed_setup_report_trial as trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter

UTC = timezone.utc
OFF_BOUNDARY_CLOCK = datetime(2026, 10, 15, 8, 45, 40, 123456, tzinfo=UTC)


def _scenario():
    return trial.clarified_development_scenario()


def _adapter(scenario):
    return PublicSourceAdapter(scenario["public"]["catalog"], scenario["scenario_id"], Audit())


def _as_datetime(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _comparisons(snapshots):
    return [comparison for snapshot in snapshots.values()
            for comparison in snapshot.get("analytical_comparisons", [])]


def test_calendar_paired_is_opt_in_and_keeps_existing_cohort_settings_frozen():
    original_limits = dict(trial.LIMITS)
    old_paired = trial.cohort_settings("paired")
    repair = trial.cohort_settings("interpretation-repair-v1")
    protocol, limits, arms = trial.cohort_settings("calendar-paired-v1")

    assert old_paired == (trial.PROTOCOL, original_limits, (False, True))
    assert repair == ("handoff-interpretation-v1", {
        **original_limits, "agent_invocations": 3,
        "between_invocation_input_stop": 300_000,
        "between_invocation_uncached_stop": 90_000,
    }, (True,))
    assert protocol == "calendar-paired-v1"
    assert limits == original_limits
    assert limits["agent_invocations"] == 6
    assert limits["jev_attempts"] == 3
    assert arms == (False, True)
    assert trial.LIMITS == original_limits


def test_shared_rebase_targets_latest_monday_utc_and_is_a_whole_week():
    scenario = _scenario()
    periods = scenario["public"]["periods"]
    offset, target = trial.calendar_measurement_rebase(periods, OFF_BOUNDARY_CLOCK)
    latest_original = max(_as_datetime(period["as_of"]) for period in periods)

    assert target == datetime(2026, 10, 12, tzinfo=UTC)
    assert latest_original + offset == target
    assert offset == timedelta(days=-7)
    assert offset.total_seconds() % timedelta(days=7).total_seconds() == 0


def test_calendar_mode_preserves_week_bounds_spacing_capture_separation_and_fixture():
    scenario = _scenario()
    periods = scenario["public"]["periods"]
    original_periods = deepcopy(periods)
    offset, target = trial.calendar_measurement_rebase(periods, OFF_BOUNDARY_CLOCK)
    baseline = _adapter(scenario)
    treatment = _adapter(scenario)
    rebased_cutoffs = []

    for period in periods:
        baseline.set_period(period, OFF_BOUNDARY_CLOCK, measurement_offset=offset)
        treatment.set_period(period, OFF_BOUNDARY_CLOCK, measurement_offset=offset)
        context = baseline.period_context
        rebased_as_of = _as_datetime(context["as_of"])
        rebased_cutoffs.append(rebased_as_of)

        assert baseline.snapshots == treatment.snapshots
        assert context == treatment.period_context
        assert rebased_as_of == _as_datetime(period["as_of"]) + offset
        assert context["captured_at"] == OFF_BOUNDARY_CLOCK.isoformat()
        assert context["as_of"] != context["captured_at"]
        assert rebased_as_of.weekday() == 0
        assert rebased_as_of.time() == datetime.min.time()

        comparisons = _comparisons(baseline.snapshots)
        assert comparisons
        for comparison in comparisons:
            bounds = [_as_datetime(comparison[field]) for field in
                      ("baseline_start", "baseline_end", "current_start", "current_end")]
            assert all(bound.weekday() == 0 and bound.time() == datetime.min.time()
                       for bound in bounds)
            assert bounds[1] - bounds[0] == timedelta(days=7)
            assert bounds[2] - bounds[1] == timedelta(0)
            assert bounds[3] - bounds[2] == timedelta(days=7)
            assert bounds[3] == rebased_as_of

    original_cutoffs = [_as_datetime(period["as_of"]) for period in periods]
    assert [right - left for left, right in zip(rebased_cutoffs, rebased_cutoffs[1:], strict=False)] == [
        right - left for left, right in zip(original_cutoffs, original_cutoffs[1:], strict=False)
    ]
    assert rebased_cutoffs[-1] == target
    assert periods == original_periods


def test_calendar_mode_preserves_fresh_and_72_hour_source_ages():
    scenario = _scenario()
    original = scenario["public"]["periods"][0]
    fresh = deepcopy(original)
    fresh_ref, fresh_snapshot = next(iter(fresh["snapshots"].items()))
    stale = deepcopy(original)
    stale_ref, stale_snapshot = next(iter(stale["snapshots"].items()))
    original_as_of = _as_datetime(original["as_of"])
    fresh_snapshot["source_captured_at"] = original_as_of.isoformat()
    stale_snapshot["source_captured_at"] = (original_as_of - timedelta(hours=72)).isoformat()
    offset, _ = trial.calendar_measurement_rebase(scenario["public"]["periods"], OFF_BOUNDARY_CLOCK)

    fresh_adapter = _adapter(scenario)
    stale_adapter = _adapter(scenario)
    fresh_adapter.set_period(fresh, OFF_BOUNDARY_CLOCK, measurement_offset=offset)
    stale_adapter.set_period(stale, OFF_BOUNDARY_CLOCK, measurement_offset=offset)

    fresh_capture = _as_datetime(fresh_adapter.snapshots[fresh_ref]["captured_at"])
    fresh_source_capture = _as_datetime(fresh_adapter.snapshots[fresh_ref]["source_captured_at"])
    stale_capture = _as_datetime(stale_adapter.snapshots[stale_ref]["captured_at"])
    stale_source_capture = _as_datetime(stale_adapter.snapshots[stale_ref]["source_captured_at"])
    assert fresh_capture == OFF_BOUNDARY_CLOCK
    assert fresh_capture - fresh_source_capture == timedelta(0)
    assert stale_capture == OFF_BOUNDARY_CLOCK
    assert stale_capture - stale_source_capture == timedelta(hours=72)


def test_legacy_set_period_default_keeps_its_existing_rebase_behavior():
    scenario = _scenario()
    period = scenario["public"]["periods"][0]
    adapter = _adapter(scenario)
    adapter.set_period(period, OFF_BOUNDARY_CLOCK)

    assert adapter.period_context == {
        "period_id": period["period_id"], "as_of": OFF_BOUNDARY_CLOCK.isoformat(),
    }
    comparisons = _comparisons(adapter.snapshots)
    assert comparisons
    assert all(comparison["current_end"] == OFF_BOUNDARY_CLOCK.isoformat()
               for comparison in comparisons)


def test_calendar_mode_rejects_naive_clock_period_and_snapshot_datetimes():
    scenario = _scenario()
    period = scenario["public"]["periods"][0]
    offset = timedelta(days=-7)
    naive_clock = datetime(2026, 10, 15, 8, 45, 40)
    with pytest.raises(ValueError, match="clock must include a timezone"):
        _adapter(scenario).set_period(period, naive_clock, measurement_offset=offset)

    naive_period = deepcopy(period)
    naive_period["as_of"] = "2026-10-05T00:00:00"
    with pytest.raises(ValueError, match="period.as_of must include a timezone"):
        _adapter(scenario).set_period(naive_period, OFF_BOUNDARY_CLOCK, measurement_offset=offset)

    naive_snapshot = deepcopy(period)
    ref = next(iter(naive_snapshot["snapshots"]))
    naive_snapshot["snapshots"][ref]["source_captured_at"] = "2026-10-05T00:00:00"
    with pytest.raises(ValueError, match="must include a timezone"):
        _adapter(scenario).set_period(naive_snapshot, OFF_BOUNDARY_CLOCK, measurement_offset=offset)

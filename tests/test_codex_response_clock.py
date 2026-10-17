"""Deterministic research deadline checks; no actual sleep or inference."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evaluations.bootstrap_agent_trial import Audit
from evaluations.codex_trial_transport import _wall_response_guard


@pytest.mark.parametrize("now,reason", [(1000.0, "wall_episode_timeout"), (-1.0, "wall_clock_reversed")])
async def test_wall_deadline_censors_suspended_or_reversed_clock(now, reason):
    process = SimpleNamespace(returncode=None, kill=Mock())
    wall, monotonic = iter([0.0, now]), iter([10.0, 10.5])
    audit = Audit()
    result = await _wall_response_guard(process, 480, audit,
        wall_clock=lambda: next(wall), monotonic_clock=lambda: next(monotonic))
    process.kill.assert_called_once_with()
    assert result == {"reason": reason, "wall_elapsed_seconds": now, "monotonic_elapsed_seconds": 0.5}
    assert audit.events == [{"kind": "codex.response_clock_censored", "episode": "preflight", **result}]


async def test_finished_process_is_not_killed_or_censored():
    process = SimpleNamespace(returncode=0, kill=Mock())
    assert await _wall_response_guard(process, 1, Audit()) is None
    process.kill.assert_not_called()


async def test_exit_race_keeps_clock_record_without_changing_usage():
    process = SimpleNamespace(returncode=None, kill=Mock(side_effect=ProcessLookupError))
    wall = iter([0.0, 2.0])
    audit = Audit()
    result = await _wall_response_guard(process, 1, audit, wall_clock=lambda: next(wall))
    assert result["reason"] == "wall_episode_timeout"
    assert not any(event["kind"].startswith("api.") for event in audit.events)


async def test_late_exited_process_is_censored_without_being_killed():
    process = SimpleNamespace(returncode=0, kill=Mock())
    audit = Audit()
    result = await _wall_response_guard(process, 480, audit, started_at=(0.0, 10.0),
        wall_clock=lambda: 1000.0, monotonic_clock=lambda: 10.5)
    assert result["reason"] == "wall_episode_timeout"
    process.kill.assert_not_called()

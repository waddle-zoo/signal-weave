import copy

import pytest

from evaluations.bootstrap_agent_trial import usage_summary
from evaluations.enterprise_journey_review import onboarding_stories, validate_execution


def test_story_keeps_failed_setup_interview_and_review_without_inventing_first_value_time():
    fixtures = [{"scenario_id": "one", "private": {"canary": "not exported"}, "public": {
        "company": "Example", "brief": "Explain a change", "catalog": [
            {"adapter": "bi", "resource": "alternate", "metadata": {"scope_note": "Pilot only"}}]}}]
    report = {"rows": [{"scenario_id": "one", "period_id": "setup", "arm": "test",
                        "phase": "onboarding", "status": "failed", "error": "timeout",
                        "seconds": 10, "notes": "Owner policy retained"}]}
    base = {"episode": "one/test/setup"}
    events = [
        {**base, "kind": "tool.result", "name": "get_signalweave_guide", "result": {}, "arguments": {}},
        {**base, "kind": "tool.result", "name": "ask_owner", "arguments": {"topic": "materiality"},
         "result": {"answer": "Owner's threshold"}},
        {**base, "kind": "tool.result", "name": "simulate_insight_card", "result": {"error": "provider failure"}},
        {**base, "kind": "tool.result", "name": "preview_investigation_report", "result": {"status": "preview"}},
        {**base, "kind": "tool.result", "name": "record_owner_review", "actor_role": "owner_reviewer", "result": {}},
        {**base, "kind": "review.result", "approved": False, "reasons": ["Incorrect routing"]},
        {**base, "kind": "source.read", "ref": "bi|alternate"},
        {"episode": "different", "kind": "source.read", "ref": "bi|alternate"},
    ]
    story, = onboarding_stories(report, events, fixtures)
    assert story["status"] == "failed"
    assert story["guide_calls"] == 1 and story["author_tool_calls"] == 4
    assert story["first_successful_preview_tool_ordinal"] == 4
    assert story["first_preview_wall_time"] is None
    assert story["alternate_scope_read_count"] == 1
    assert len(story["owner_interview"]) == len(story["owner_reviews"]) == len(story["tool_errors"]) == 1
    assert "not exported" not in str(story)


@pytest.fixture
def execution():
    fixtures = [{"scenario_id": "one", "public": {"onboarding": {"period_id": "setup"},
                                                   "periods": [{"period_id": "later"}]}}]
    events = [{"episode": "one/luna_signalweave_jev/setup", "provider": "jev", "request_id": 1,
               "kind": kind} for kind in ("api.request", "api.error")]
    rows = [{"scenario_id": "one", "arm": arm, "period_id": period,
             "usage": usage_summary([e for e in events if e["episode"] == f"one/{arm}/{period}"])}
            for arm in ("luna_bi", "luna_signalweave_jev") for period in ("setup", "later")]
    return {"rows": rows, "usage": usage_summary(events)}, events, fixtures


def test_execution_counts_planned_denominators_and_retains_failed_attempt(execution):
    report, events, fixtures = execution
    before = copy.deepcopy(execution)
    assert validate_execution(report, events, fixtures) == {
        "expected_episodes": 4, "expected_onboardings": 2,
        "expected_monitoring_per_arm": 1, "validated": True}
    assert execution == before


@pytest.mark.parametrize("defect", ["missing_row", "duplicate_row", "foreign_episode",
                                   "missing_terminal", "duplicate_request", "unknown_provider",
                                   "report_usage", "episode_usage"])
def test_execution_rejects_mixed_truncated_and_miscounted_artifacts(execution, defect):
    report, events, fixtures = execution
    if defect == "missing_row":
        report["rows"].pop()
    elif defect == "duplicate_row":
        report["rows"][-1] = report["rows"][0]
    elif defect == "foreign_episode":
        events[0]["episode"] = "wrong"
    elif defect == "missing_terminal":
        events.pop()
    elif defect == "duplicate_request":
        events.append(events[0])
    elif defect == "unknown_provider":
        events[0]["provider"] = "unknown"
    elif defect == "report_usage":
        report["usage"]["jev"]["attempts"] += 1
    else:
        report["rows"][0]["usage"]["jev"]["attempts"] += 1
    with pytest.raises(ValueError):
        validate_execution(report, events, fixtures)

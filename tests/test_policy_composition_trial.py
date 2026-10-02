import copy

import pytest
from pydantic import ValidationError

from evaluations.policy_composition_trial import (
    AuthorSession,
    Plan,
    ReportSession,
    compose,
    numeric_checks,
    public_case,
    review_packet,
    run,
    summary,
)


def plan():
    return Plan.model_validate({
        "checks": [
            {"id": "decline", "kind": "numeric", "condition": "At least ten", "field": "decline", "op": "ge", "threshold": 10},
            {"id": "exception", "kind": "semantic", "condition": "An approved exception applies"}],
        "rules": [{"when": [{"exception": "true"}], "outcome": "ignore"},
                  {"when": [{"decline": "unknown"}], "outcome": "insufficient_data"},
                  {"when": [{"decline": "true", "exception": "false"}], "outcome": "notify"}],
        "default": "ignore"})


@pytest.mark.parametrize("value,expected", [(10, "true"), (9.9, "false"), (None, "unknown"),
                                           (float("nan"), "unknown"), (True, "unknown")])
def test_numeric_boundaries_and_missing(value, expected):
    assert numeric_checks(plan(), {"decline": value}) == {"decline": expected}


@pytest.mark.parametrize("values,expected", [
    ({"decline": "true", "exception": "true"}, "ignore"),
    ({"decline": "true", "exception": "false"}, "notify"),
    ({"decline": "true", "exception": "unknown"}, "investigate"),
    ({"decline": "unknown", "exception": "false"}, "insufficient_data"),
])
def test_precedence_and_unknown_never_silently_notify(values, expected):
    assert compose(plan(), values) == expected


def test_bad_references_and_numeric_shapes_rejected():
    payload = plan().model_dump()
    payload["rules"][0]["when"][0] = {"invented": "true"}
    with pytest.raises(ValidationError):
        Plan.model_validate(payload)
    payload = plan().model_dump()
    payload["checks"][0]["threshold"] = float("inf")
    with pytest.raises(ValidationError):
        Plan.model_validate(payload)


async def test_author_does_not_accept_unknown_fields():
    subject = AuthorSession({"different_field": {}})
    with pytest.raises(ValueError, match="catalog"):
        await subject.call("submit_plan", plan().model_dump())


async def test_dry_run_and_private_label_boundary(tmp_path):
    from evaluations.policy_composition_cases import cases
    case = cases()[0]
    original = copy.deepcopy(case)
    assert set(public_case(case)) == {"id", "facts", "measurements"}
    assert case["id"] not in str(public_case(case))
    assert case == original
    result = await run(tmp_path / "trial")
    assert result["jev_attempts"] == result["luna_episodes"] == 0
    assert all(row["correct"] == 0 and row["intended"] == 12 for row in summary([], cases()).values())
    assert summary([], cases())["composed"]["missed_business_notifications"] == 3
    packet, key = review_packet([], cases())
    assert len(packet["cases"]) == len(key) == 12
    assert all(set(row["candidates"]) == {"A", "B"} for row in packet["cases"])


async def test_source_cache_and_fake_recipient_boundaries():
    from evaluations.bootstrap_agent_trial import Audit
    case = {"id": "period", "facts": [{"id": "f1", "statement": "Observed"}],
            "measurements": {"decline": 0}, "policy": {"destinations": {"notify": "owner"}}}
    subject = ReportSession([case], plan(), treatment=False, judger=None, audit=Audit())
    await subject.call("read_current", {})
    await subject.call("read_current", {})
    assert subject.reads == 1
    with pytest.raises(ValueError, match="Cite"):
        await subject.call("submit_report", {"id": public_case(case)["id"], "citations": ["madeup"], "outcome": "notify"})
    await subject.call("submit_report", {"id": public_case(case)["id"], "citations": ["f1"], "outcome": "notify", "narrative": "Observed"})
    assert subject.runs[0]["recipients"] == ["owner"]

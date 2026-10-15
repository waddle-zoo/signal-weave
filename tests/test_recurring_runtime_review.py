"""Offline contract tests for the isolated recurring-runtime prose reviewer."""

import json

import pytest
from pydantic import ValidationError

from evaluations import recurring_runtime_review as review


def packet(case_count=12):
    return {
        "scope": "masked",
        "rubric": ["numeric fidelity", "causation", "policy significance"],
        "instructions": "Review both quoted candidates.",
        "cases": [
            {
                "id": f"company-{index // 4}:p{index:02d}",
                "brief": "Watch the approved metric.",
                "policy": "Notify the exact owner when the policy is met.",
                "destinations": [{"key": "owner", "label": "Owner"}],
                "sources": [{"key": "metric", "unit": "number"}],
                "candidates": {"A": {"narrative": f"Candidate A {index}"},
                               "B": {"narrative": f"Candidate B {index}"}},
            }
            for index in range(case_count)
        ],
    }


def write_packet(tmp_path, value=None):
    path = tmp_path / "review-input.json"
    path.write_text(json.dumps(packet() if value is None else value), encoding="utf-8")
    return path


async def test_session_exposes_only_submit_and_waits_for_all_six_reviews():
    session = review.ReviewSession(packet()["cases"][:6])
    assert [spec["name"] for spec in await session.specs()] == ["submit_case_review"]
    with pytest.raises(ValueError, match="only submit_case_review"):
        await session.call("read_case", {"case_id": "company-0:p00"})
    for index, case_id in enumerate(list(session.cases)[1:], start=1):
        result = await session.call("submit_case_review", {
            "case_id": case_id, "a_usable": index % 2 == 0, "b_usable": True,
            "winner": "tie", "reasons": ["Both reports expose the relevant caveat."],
        })
        assert result["all_cases_complete"] is False
        assert session.submission is None
    await session.call("submit_case_review", {
        "case_id": "company-0:p00", "a_usable": True, "b_usable": True,
        "winner": "tie", "reasons": ["Both reports are usable for the policy."],
    })
    assert session.submission is not None
    assert session.submission["case_count"] == 6
    assert len(session.submission["reviews"]) == 6
    with pytest.raises(ValueError, match="already recorded"):
        await session.call("submit_case_review", {
            "case_id": "company-0:p00", "a_usable": True, "b_usable": True,
            "winner": "tie", "reasons": ["A second submission is not permitted."],
        })


@pytest.mark.parametrize("bad", [
    {"case_id": "x", "a_usable": 1, "b_usable": False, "winner": "A", "reasons": ["x"]},
    {"case_id": "x", "a_usable": True, "b_usable": False, "winner": "C", "reasons": ["x"]},
    {"case_id": "x", "a_usable": True, "b_usable": False, "winner": "A", "reasons": []},
    {"case_id": "x", "a_usable": True, "b_usable": False, "winner": "A", "reasons": [" "]},
    {"case_id": "x", "a_usable": True, "b_usable": False, "winner": "A", "reasons": ["x"], "extra": 1},
])
async def test_case_review_schema_is_strict(bad):
    session = review.ReviewSession(packet()["cases"][:6])
    with pytest.raises(ValidationError):
        await session.call("submit_case_review", bad)
    assert session.submission is None


def test_input_requires_public_twelve_case_packet_and_never_accepts_oracles(tmp_path):
    path = write_packet(tmp_path)
    loaded = review.load_review_input(path)
    assert len(loaded["cases"]) == 12
    batches = review.split_cases(loaded["cases"])
    assert batches == [loaded["cases"][::2], loaded["cases"][1::2]]
    assert {case["id"].split(":")[0] for case in batches[0]} == {
        "company-0", "company-1", "company-2",
    }
    assert all(sum(case["id"].startswith(company) for case in batch) == 2
               for batch in batches for company in ("company-0", "company-1", "company-2"))
    for forbidden in ("oracle", "expected", "review_key", "scoring_labels"):
        bad = packet()
        bad["cases"][0][forbidden] = "private"
        with pytest.raises(ValueError):
            review.load_review_input(write_packet(tmp_path, bad))


async def test_dry_run_makes_no_codex_calls_and_persists_digest(monkeypatch, tmp_path):
    async def forbidden(*args, **kwargs):
        raise AssertionError("dry run must not invoke Codex")

    monkeypatch.setattr(review, "codex_episode", forbidden)
    output = tmp_path / "dry"
    result = await review.run_review(write_packet(tmp_path), output)
    assert result["status"] == "dry_run"
    assert result["review_status"] == "not_run"
    assert result["correctness_claim"] is False
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["case_count"] == 12
    assert manifest["input_digest"] == result["input_digest"]
    assert manifest["freeze"]["git_revision"]
    assert manifest["reviewer_freeze_clean"] is (not bool(manifest["freeze"]["git_status"].strip()))
    assert not (output / "events.jsonl").exists()


async def test_live_run_is_two_high_effort_six_case_episodes_and_retains_partial_state(monkeypatch, tmp_path):
    calls = []

    async def fake_episode(session, **kwargs):
        calls.append(kwargs)
        assert session.submission is None
        kwargs["audit"].emit("api.request", provider="openai", request_id=-len(calls))
        assert len(kwargs["prompt_override"]["cases"]) == 6
        assert "candidates" in kwargs["prompt_override"]["cases"][0]
        for case_id in session.cases:
            await session.call("submit_case_review", {
                "case_id": case_id, "a_usable": True, "b_usable": False,
                "winner": "A", "reasons": ["A keeps the numeric caveat and route visible."],
            })
        kwargs["audit"].emit("api.response", provider="openai", request_id=-len(calls),
                              usage={"input_tokens": 100, "output_tokens": 20})
        return {"status": "complete", "error": None, "exit_code": 0,
                "foreign_tools": [], "tool_calls": 6, "seconds": 1.0}

    monkeypatch.setattr(review, "codex_episode", fake_episode)
    output = tmp_path / "live"
    result = await review.run_review(write_packet(tmp_path), output, live=True)
    assert len(calls) == 2
    assert all(call["effort"] == "high" and call["timeout_seconds"] == 240 for call in calls)
    assert all(call["max_tool_calls"] == 8 and call["key"] == "" for call in calls)
    assert all(len(record["case_ids"]) == 6 for record in result["episodes"])
    assert result["review_status"] == "complete"
    assert result["correctness_claim"] is False
    assert len(result["reviews"]) == 12
    assert (output / "events.jsonl").exists()
    assert json.loads((output / "progress.json").read_text())["failures"] == []


def test_usage_requires_required_counts_reconciles_and_marks_empty_live_episodes():
    missing = review._usage([
        {"kind": "api.request", "episode": "review:1"},
        {"kind": "api.response", "episode": "review:1", "usage": {"output_tokens": 3}},
    ])
    assert {item["reason"] for item in missing["unknown_usage"]} == {"missing_input_tokens"}
    mismatch = review._usage([
        {"kind": "api.request", "episode": "review:1"},
        {"kind": "api.request", "episode": "review:1"},
        {"kind": "api.response", "episode": "review:1",
         "usage": {"input_tokens": 1, "output_tokens": 1}},
    ])
    assert mismatch["by_episode"]["review:1"]["requests"] == 2
    assert mismatch["by_episode"]["review:1"]["responses"] == 1
    assert {item["reason"] for item in mismatch["unknown_usage"]} == {"request_response_mismatch"}
    empty = review._usage([], expected_episodes=("review:2",))
    assert empty["unknown_usage"] == [{"episode": "review:2", "reason": "missing_usage"}]


async def test_failed_episode_writes_failure_and_does_not_claim_complete(monkeypatch, tmp_path):
    async def failed(session, **kwargs):
        return {"status": "failed", "error": "episode_timeout", "exit_code": None,
                "foreign_tools": [], "tool_calls": 0, "seconds": 240}

    monkeypatch.setattr(review, "codex_episode", failed)
    result = await review.run_review(write_packet(tmp_path), tmp_path / "failed", live=True)
    assert result["status"] == "partial"
    assert result["review_status"] == "incomplete"
    assert len(result["failures"]) == 2
    assert result["completed_case_count"] == 0
    assert result["correctness_claim"] is False


async def test_foreign_tools_fail_the_episode_even_after_all_reviews(monkeypatch, tmp_path):
    async def foreign(session, **kwargs):
        kwargs["audit"].emit("api.request", provider="openai", request_id=-1)
        for case_id in session.cases:
            await session.call("submit_case_review", {
                "case_id": case_id, "a_usable": False, "b_usable": False,
                "winner": "neither", "reasons": ["Both candidates omit the required caveat."],
            })
        kwargs["audit"].emit("api.response", provider="openai", request_id=-1,
                              usage={"input_tokens": 10, "output_tokens": 10})
        return {"status": "complete", "error": None, "exit_code": 0,
                "foreign_tools": ["shell"], "tool_calls": 6, "seconds": 1.0}

    monkeypatch.setattr(review, "codex_episode", foreign)
    result = await review.run_review(write_packet(tmp_path), tmp_path / "foreign", live=True)
    assert result["status"] == "partial"
    assert result["review_status"] == "incomplete"
    assert any(item["error"] == "foreign_tool_used" for item in result["failures"])
    assert result["completed_case_count"] == 12

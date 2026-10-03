"""Offline contract tests for the opt-in owner-review qualification runner."""

from __future__ import annotations

import asyncio
import json

import pytest

from evaluations import bootstrap_owner_review as reviewer
from evaluations import owner_review_qualification as runner
from evaluations.bootstrap_agent_trial import Audit, RequestBudget


def test_cases_are_generic_and_expectations_are_not_reviewer_input():
    cases = runner.qualification_cases()
    assert len(cases) >= 4
    assert {case["expected_approved"] for case in cases} == {True, False}
    for case in cases:
        reviewer_input = {
            "public": case["public"],
            "owner_answers": case["owner_answers"],
            "artifact": case["artifact"],
            "source_context": case["source_context"],
        }
        assert "expected_approved" not in json.dumps(reviewer_input)
        assert "private" not in json.dumps(reviewer_input).lower()

    within = next(case for case in cases if case["case_id"] == "valid_within_effect_binding")
    condition = within["artifact"]["card"]["numeric_conditions"][0]
    comparison = within["source_context"]["inspected_sources"][0]["analytical_comparisons"][0]
    assert condition["measurement"] == "within_effect"
    assert condition["comparison_key"] == comparison["key"]

    plain = next(case for case in cases if case["case_id"] == "plain_numeric_policy_without_bindings")
    plain_source = plain["source_context"]["inspected_sources"][0]
    assert plain["artifact"]["card"]["numeric_conditions"] == []
    assert plain_source["contract"]["required_comparison_keys"] == []
    assert plain_source["analytical_comparisons"] == []

    fabricated = next(case for case in cases if case["case_id"] == "fabricated_comparison_binding")
    assert fabricated["artifact"]["card"]["sources"][0]["required_comparison_keys"] == [
        "future_conversion_comparison"
    ]


@pytest.mark.asyncio
async def test_fabricated_binding_is_rejected_before_model(monkeypatch):
    fabricated = next(case for case in runner.qualification_cases()
                      if case["case_id"] == "fabricated_comparison_binding")
    called = False

    async def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("fabricated binding must fail before transport")

    monkeypatch.setattr(reviewer.codex_trial_transport, "codex_episode", forbidden)
    result = await reviewer.review_owner_artifact(
        public=fabricated["public"], owner_answers=fabricated["owner_answers"],
        artifact=fabricated["artifact"], source_context=fabricated["source_context"],
        audit=Audit(), budget=RequestBudget(1),
    )
    assert result["approved"] is False
    assert result["episode"]["error"] == "invalid_review_input"
    assert called is False


def test_run_retains_per_case_inputs_results_and_trace_without_expectation_in_input(
    monkeypatch, tmp_path
):
    async def fake_review_owner_artifact(*, public, owner_answers, artifact, source_context, audit, budget):
        assert "expected_approved" not in json.dumps({"public": public, "owner_answers": owner_answers, "artifact": artifact, "source_context": source_context})
        budget.claim()
        encoded = json.dumps(artifact)
        approved = (
            "fabricated" not in encoded
            and '"destination": "route://operations"' in encoded
            and "revenue" not in encoded
        )
        if "fabricated" in encoded:
            result = {
                "approved": False, "reasons": ["invalid review input"], "review": None,
                "episode": {"status": "failed", "error": "invalid_review_input", "tool_calls": 0},
            }
        else:
            audit.emit("api.request", provider="openai", request_id=budget.used,
                       model="gpt-5.6-luna")
            result = {
                "approved": approved, "reasons": ["offline transport double"],
                "review": {"approved": approved, "reasons": ["offline transport double"]},
                "episode": {"status": "complete", "exit_code": 0, "foreign_tools": []},
            }
        audit.emit("review.result", approved=approved)
        return result

    monkeypatch.setattr(runner, "review_owner_artifact", fake_review_owner_artifact)
    output = tmp_path / "qualification"
    summary = asyncio.run(runner.run_qualification(output))
    assert output.exists() and summary["attempts_used"] == 4
    assert summary["budget_claims_used"] == 5
    assert summary["all_passed"] is True
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["instructions_digest"]
    assert set(manifest["input_digests"]) == {case["case_id"] for case in runner.qualification_cases()}
    assert set(manifest["source_files"]) == {
        "evaluations/owner_review_qualification.py",
        "evaluations/bootstrap_owner_review.py",
        "evaluations/bootstrap_agent_trial.py",
    }
    for case in runner.qualification_cases():
        case_dir = output / case["case_id"]
        assert (case_dir / "input.json").exists()
        assert (case_dir / "result.json").exists()
        assert (case_dir / "trace.jsonl").exists()
        assert "expected_approved" not in (case_dir / "input.json").read_text()


def test_run_requires_live_and_existing_output_is_refused(monkeypatch, tmp_path):
    with pytest.raises(SystemExit, match="--live"):
        runner.main(["--output", str(tmp_path / "missing")])
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(SystemExit, match="already exists"):
        runner.main(["--live", "--output", str(existing)])


def test_semantic_rejection_requires_clean_completed_valid_review():
    case = next(case for case in runner.qualification_cases()
                if case["expectation"] == "semantic_rejection")
    base = {
        "approved": False,
        "review": {"approved": False, "reasons": ["Correct semantic rejection."]},
        "episode": {
            "status": "complete", "error": None, "exit_code": 0,
            "foreign_tools": [],
        },
    }
    assert runner._passed(case, base) is True
    for field, value in (
        ("exit_code", 1),
        ("foreign_tools", ["shell"]),
    ):
        failed = json.loads(json.dumps(base))
        failed["episode"][field] = value
        assert runner._passed(case, failed) is False

    missing_review = json.loads(json.dumps(base))
    missing_review["review"] = None
    assert runner._passed(case, missing_review) is False

    malformed_review = json.loads(json.dumps(base))
    malformed_review["review"] = {"approved": False, "reasons": []}
    assert runner._passed(case, malformed_review) is False

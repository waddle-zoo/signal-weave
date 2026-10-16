"""Explicit new owner input, independent arm qualification, no inference."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations import public_owner_report_trial as trial
from tests.test_public_owner_report_trial import FakeNative, _patch_offline

NOTE = Path(trial.__file__).with_name("data") / "courier-owner-clarification-v1.md"


def selected(tmp_path, monkeypatch, *, live=False, failure=None):
    args, state, _, _ = _patch_offline(monkeypatch, tmp_path, live=live, failure=failure)
    args.development_owner = args.expert_reference = args.explicit_owner_confirmation = True
    args.expert_notes_file = None
    args.owner_clarifications_file = str(NOTE)
    original = FakeNative.call_tool

    async def shadow(native, name, arguments):
        content, result = await original(native, name, arguments)
        if name == "evaluate_insight_card":
            result["receipt"]["delivery_enabled"] = False
        return content, result

    monkeypatch.setattr(FakeNative, "call_tool", shadow)
    return args, state


def test_new_owner_input_does_not_change_sources_measurements_or_labels():
    original = trial.development_scenario()
    changed, identity = trial.attach_owner_clarification(original, NOTE)
    assert changed["private"] == original["private"]
    for key in ("catalog", "onboarding", "periods", "destinations", "glossary"):
        assert changed["public"][key] == original["public"][key]
    text = NOTE.read_text().strip()
    assert changed["public"]["owner_answers"]["workflow_boundaries"] == text
    assert changed["public"]["brief"].endswith(text)
    assert "workflow_boundaries" not in original["public"]["owner_answers"]
    assert len(identity["sha256"]) == 64


@pytest.mark.parametrize("text", ["", "  \n", "x" * 16001])
def test_invalid_clarifications_fail_before_any_episode(tmp_path, text):
    path = tmp_path / "note"
    path.write_text(text)
    with pytest.raises(ValueError):
        trial.attach_owner_clarification(trial.development_scenario(), path)


def test_clarification_cannot_rewrite_legacy_protocol_selection():
    with pytest.raises(ValueError, match="requires"):
        trial.validate_cohort_options(SimpleNamespace(owner_clarifications_file=str(NOTE)))


async def test_preflight_is_blank_zero_inference_and_exact_shared_owner_input(tmp_path, monkeypatch):
    args, state = selected(tmp_path, monkeypatch)
    result = await trial.run(args)
    assert result["completed"] is True and result["protocol"] == trial.CLARIFIED_OWNER_PROTOCOL
    assert result["initial_native_card_count"] == result["agent_invocations_started"] == result["provider_attempts"] == 0
    assert result["paired_reporting_complete"] is False and result["qualified_arms"] == []
    assert result["owner_clarification"]["sha256"]
    assert state["sequence"] == []


async def test_complete_pair_keeps_six_calls_one_jev_and_explicit_qualification(tmp_path, monkeypatch):
    args, state = selected(tmp_path, monkeypatch, live=True)
    original = trial.codex_episode
    author_context = []

    async def capture(session, **kwargs):
        if isinstance(session, trial.AuthorEpisode):
            prompt = kwargs["prompt_override"]
            author_context.append((prompt["brief"], session.public["owner_answers"]["workflow_boundaries"]))
        return await original(session, **kwargs)

    monkeypatch.setattr(trial, "codex_episode", capture)
    result = await trial.run(args)
    assert result["completed"] is result["paired_reporting_complete"] is True
    assert result["qualified_arms"] == ["baseline", "signalweave"]
    assert result["agent_invocations_started"] == 6 and result["provider_attempts"] == 1
    assert len(state["review_calls"]) == 2
    assert len(author_context) == 2 and author_context[0] == author_context[1]
    assert author_context[0][0].endswith(NOTE.read_text().strip())


async def test_rejected_baseline_does_not_censor_treatment_or_become_a_pair(tmp_path, monkeypatch):
    args, state = selected(tmp_path, monkeypatch, live=True)
    original = trial.review_owner_artifact

    async def reject_only_baseline(**kwargs):
        result = await original(**kwargs)
        if "card" not in kwargs["artifact"]:
            result["approved"] = False
        return result

    monkeypatch.setattr(trial, "review_owner_artifact", reject_only_baseline)
    result = await trial.run(args)
    assert result["completed"] is True and result["paired_reporting_complete"] is False
    assert result["onboarding_status"]["baseline"] == "needs_owner_review"
    assert result["qualified_arms"] == ["signalweave"]
    assert result["agent_invocations_started"] == 5 and result["provider_attempts"] == 1
    assert [e["arm"] for e in result["episodes"] if e["stage"] == "report"] == ["signalweave"]
    assert state["review_calls"] == ["baseline", "signalweave"]


async def test_rejected_arms_do_not_report_or_imply_readiness(tmp_path, monkeypatch):
    args, _ = selected(tmp_path, monkeypatch, live=True, failure="rejected_review")
    result = await trial.run(args)
    assert result["completed"] is True and result["paired_reporting_complete"] is False
    assert result["qualified_arms"] == [] and result["agent_invocations_started"] == 4
    assert result["provider_attempts"] == 0
    assert not any(e["stage"] == "report" for e in result["episodes"])


async def test_known_incomplete_author_does_not_import_or_retry_an_artifact(tmp_path, monkeypatch):
    args, _ = selected(tmp_path, monkeypatch, live=True, failure="incomplete_author")
    result = await trial.run(args)
    assert result["completed"] is True and result["paired_reporting_complete"] is False
    assert result["onboarding_status"]["baseline"] == "author_incomplete"
    assert result["qualified_arms"] == ["signalweave"] and result["agent_invocations_started"] == 4


async def test_unknown_usage_still_stops_globally_without_an_extra_arm(tmp_path, monkeypatch):
    args, state = selected(tmp_path, monkeypatch, live=True, failure="unknown_usage")
    result = await trial.run(args)
    assert not result.get("completed") and result["usage_known"] is False
    assert state["sequence"] == [("author", "baseline")]

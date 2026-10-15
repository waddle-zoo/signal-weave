"""Offline prompt-role safeguards for the owner-handoff author turns."""

import pytest

from evaluations import domain_context_onboarding_trial as trial
from tests.test_owner_handoff_workflow import install_owner_handoff_runner_fakes


@pytest.mark.parametrize("stage", ["first", "second"])
def test_author_instruction_helper_keeps_baseline_and_treatment_roles_distinct(stage):
    baseline = trial.owner_handoff_author_instructions(stage, treatment=False)
    treatment = trial.owner_handoff_author_instructions(stage, treatment=True)

    for instructions in (baseline, treatment):
        lowered = instructions.lower()
        assert "do not invent" in lowered
        assert "schedule" in lowered
        assert "send" in lowered
        assert "evaluat" in lowered

    for forbidden in ("SignalWeave", "revise_insight_card", "approve_insight_card"):
        assert forbidden not in baseline

    if stage == "first":
        assert "save_working_notes" in baseline
        assert "finish_setup.card_ids must be empty" in baseline
        assert "SignalWeave draft card" in treatment
        assert "exact ID in finish_setup.card_ids" in treatment
        assert "request_owner_approval" not in baseline
    else:
        assert "save_working_notes" in baseline
        assert "request_owner_approval with kind=notes and id=working" in baseline
        assert "Keep finish_setup.card_ids empty" in baseline
        assert "revise_insight_card" in treatment
        assert "Never create a replacement" in treatment
        assert "request_owner_approval" in treatment
        assert "approve that card" in treatment
        assert "finish_setup.card_ids" in treatment


async def test_actual_codex_calls_receive_role_specific_author_instructions(monkeypatch, tmp_path):
    args, _ = install_owner_handoff_runner_fakes(monkeypatch, tmp_path)
    captured = []
    fake_codex_episode = trial.codex_episode

    async def capture_kwargs(session, **kwargs):
        captured.append(
            {
                "episode": session.adapter.audit.episode,
                "instructions_override": kwargs["instructions_override"],
            }
        )
        return await fake_codex_episode(session, **kwargs)

    monkeypatch.setattr(trial, "codex_episode", capture_kwargs)

    report = await trial.run_owner_workflow(args)

    assert "failure" not in report
    author_calls = {
        item["episode"]: item["instructions_override"]
        for item in captured
        if "-owner-handoff-first" in item["episode"] or "-owner-handoff-second" in item["episode"]
    }
    assert set(author_calls) == {
        "baseline-owner-handoff-first",
        "signalweave-owner-handoff-first",
        "baseline-owner-handoff-second",
        "signalweave-owner-handoff-second",
    }

    baseline_first = author_calls["baseline-owner-handoff-first"]
    baseline_second = author_calls["baseline-owner-handoff-second"]
    treatment_second = author_calls["signalweave-owner-handoff-second"]

    for instructions in (baseline_first, baseline_second):
        assert "SignalWeave" not in instructions
        assert "revise_insight_card" not in instructions
        assert "approve_insight_card" not in instructions
        assert "Do not invent" in instructions
        assert "schedule" in instructions
        assert "send" in instructions
        assert "evaluat" in instructions

    assert "finish_setup.card_ids must be empty" in baseline_first
    assert "request_owner_approval with kind=notes and id=working" in baseline_second
    assert "Keep finish_setup.card_ids empty" in baseline_second
    assert "revise_insight_card" in treatment_second
    assert "Never create a replacement" in treatment_second
    assert "request_owner_approval" in treatment_second
    assert "approve that card" in treatment_second
    assert "finish_setup.card_ids" in treatment_second

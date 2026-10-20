"""Explicit expert inputs are quoted data, not inferred semantics or approval."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from evaluations import public_owner_report_trial as trial
from evaluations.source_expert_reference import attach_steward_notes
from tests.test_public_owner_report_trial import _patch_offline

NOTES = Path(__file__).resolve().parents[1] / "evaluations/data/juniper-source-steward-v1.md"


def test_notes_copy_only_explicit_input_and_never_rewrite_fixture_or_policy():
    fixture = trial.scenario()
    original = copy.deepcopy(fixture)
    attached, source, digest = attach_steward_notes(fixture, NOTES)
    assert fixture == original
    assert digest == hashlib.sha256(NOTES.read_bytes()).hexdigest()
    assert attached["public"]["glossary"]["source_steward_notes"] == NOTES.read_text()
    attached["public"]["glossary"].pop("source_steward_notes")
    assert attached == original
    primary = next(c for c in fixture["public"]["catalog"] if c["contract"].get("roles") == ["primary"])
    assert source == primary["adapter"] + "|" + primary["resource"]
    assert source in NOTES.read_text()
    assert "no additional" in NOTES.read_text()


@pytest.mark.parametrize("fault", ["empty", "oversize", "no-primary", "multiple-primary", "existing-notes"])
def test_missing_or_ambiguous_inputs_do_not_create_expert_context(tmp_path, fault):
    fixture = trial.scenario()
    path = tmp_path / "expert.md"
    path.write_text("An explicit fictional expert declaration.")
    if fault == "empty":
        path.write_text(" \n")
    elif fault == "oversize":
        path.write_text("x" * 16_001)
    elif fault == "no-primary":
        for c in fixture["public"]["catalog"]:
            c["contract"]["roles"] = []
    elif fault == "multiple-primary":
        for c in fixture["public"]["catalog"]:
            c["contract"]["roles"] = ["primary"]
    else:
        fixture["public"]["glossary"]["source_steward_notes"] = "Earlier conflicting declaration."
    with pytest.raises(ValueError):
        attach_steward_notes(fixture, path)


def test_conflicting_expert_text_is_preserved_not_silently_reconciled(tmp_path):
    path = tmp_path / "conflicting.md"
    path.write_text("This source is monthly, not weekly, and includes tax. Population remains unknown.")
    fixture = trial.scenario()
    attached, _, _ = attach_steward_notes(fixture, path)
    assert attached["public"]["glossary"]["source_steward_notes"] == path.read_text()
    assert attached["public"]["glossary"]["comparison"] == fixture["public"]["glossary"]["comparison"]
    assert attached["public"]["owner_answers"] == fixture["public"]["owner_answers"]


async def test_notes_are_available_equally_and_to_the_independent_reviewer(tmp_path, monkeypatch):
    args, state, _, _ = _patch_offline(monkeypatch, tmp_path, live=True)
    args.expert_reference, args.expert_notes_file = True, NOTES
    original_review = trial.review_owner_artifact
    declarations = []

    async def inspect_review(**kwargs):
        declarations.append(kwargs["public"]["glossary"]["source_steward_notes"])
        return await original_review(**kwargs)

    monkeypatch.setattr(trial, "review_owner_artifact", inspect_review)
    result = await trial.run(args)
    assert result["completed"] and result["protocol"] == trial.STEWARD_PROTOCOL
    assert declarations == [NOTES.read_text(), NOTES.read_text()]
    assert result["expert_notes"]["sha256"] == hashlib.sha256(NOTES.read_bytes()).hexdigest()
    assert state["review_calls"] == ["baseline", "signalweave"]
    exported = json.loads((tmp_path / "trial-output/public-onboarding-input.json").read_text())
    assert exported["glossary"]["source_steward_notes"] == NOTES.read_text()


async def test_declaration_change_stops_before_another_model_call(tmp_path, monkeypatch):
    args, state, _, _ = _patch_offline(monkeypatch, tmp_path, live=True)
    notes = tmp_path / "expert.md"
    notes.write_text(NOTES.read_text())
    args.expert_reference, args.expert_notes_file = True, notes
    original_author = trial.codex_episode

    async def changed_after_author(session, **kwargs):
        result = await original_author(session, **kwargs)
        notes.write_text(notes.read_text() + "\nChanged declaration after the first call.\n")
        return result

    monkeypatch.setattr(trial, "codex_episode", changed_after_author)
    result = await trial.run(args)
    assert not result.get("completed", False)
    assert "declaration changed" in json.dumps(result["failure"])
    assert state["model_calls"] == [("author", "baseline")]
    assert state["review_calls"] == [] and result["provider_attempts"] == 0


async def test_notes_need_reference_mode_before_any_trial_starts(tmp_path, monkeypatch):
    args, state, _, _ = _patch_offline(monkeypatch, tmp_path, live=True)
    args.expert_notes_file = NOTES
    with pytest.raises(ValueError, match="require --expert-reference"):
        await trial.run(args)
    assert state["sequence"] == []

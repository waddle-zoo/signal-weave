"""Offline prompt-role safeguards for the owner-handoff author turns."""

import json

import pytest
from jsonschema import ValidationError, validate

from evaluations import domain_context_onboarding_trial as trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import public_episode
from tests.test_owner_handoff_workflow import install_owner_handoff_runner_fakes


class _NativeCard:
    async def list_tools(self):
        return []

    async def call_tool(self, name, args):
        assert name == "get_insight_card"
        assert args["card_id"] == "card-1"
        return [], {"id": "card-1", "status": "approved"}


def _handoff_episode(*, treatment, stage, native=None):
    public = public_episode(trial.clarified_development_scenario())
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    return trial.HandoffEpisode(
        public,
        adapter,
        native if treatment else None,
        stage=stage,
        owner_answers=public["owner_answers"] if stage == "second" else None,
        first_card={"id": "card-1", "version": 1} if treatment and stage == "second" else None,
    )


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
        assert "only the supplied trial-server tools" in instructions

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


@pytest.mark.parametrize("stage", ["first", "second"])
@pytest.mark.parametrize("treatment", [False, True], ids=["baseline", "treatment"])
async def test_presented_handoff_schemas_match_each_arm_and_stage(stage, treatment):
    session = _handoff_episode(treatment=treatment, stage=stage, native=_NativeCard())
    tools = json.loads(json.dumps(await session.specs()))
    by_name = {tool["name"]: tool for tool in tools}
    schemas = {name: tool["parameters"] for name, tool in by_name.items()}
    setup_schema = schemas["finish_setup"]
    expected_card_ids = ["card-1"] if treatment else []

    assert setup_schema["properties"]["card_ids"]["maxItems"] == (1 if treatment else 0)
    validate({"card_ids": expected_card_ids, "message": "Current readout.", "unresolved": []},
             setup_schema)
    if treatment:
        with pytest.raises(ValidationError):
            validate({"card_ids": ["card-1", "card-2"], "message": "Current readout.", "unresolved": []},
                     setup_schema)
    else:
        with pytest.raises(ValidationError):
            validate({"card_ids": ["card-1"], "message": "Current readout.", "unresolved": []},
                     setup_schema)

    if stage == "first":
        assert "request_owner_approval" not in by_name
    else:
        approval = by_name["request_owner_approval"]
        expected_kinds = ["card", "context", "notes"] if treatment else ["notes"]
        assert approval["parameters"]["properties"]["kind"]["enum"] == expected_kinds
        if treatment:
            assert "saved card/context" in approval["description"]
            for kind in expected_kinds:
                validate({"kind": kind, "id": "saved-artifact", "summary": "Review saved artifact."},
                         approval["parameters"])
        else:
            assert "saved baseline notes" in approval["description"]
            assert "card/context" not in approval["description"]
            validate({"kind": "notes", "id": "working", "summary": "Review saved notes."},
                     approval["parameters"])
            for kind in ("card", "context"):
                with pytest.raises(ValidationError):
                    validate({"kind": kind, "id": "unsupported", "summary": "Unsupported."},
                             approval["parameters"])

    trial.validate_owner_handoff_schemas(tools, session.public["owner_topics"][0], treatment=treatment)


@pytest.mark.parametrize("treatment", [False, True], ids=["baseline", "treatment"])
async def test_finish_setup_dispatch_matches_presented_card_id_capability(monkeypatch, treatment):
    native = _NativeCard() if treatment else None
    session = _handoff_episode(treatment=treatment, stage="second", native=native)
    await session.call("save_working_notes", {"notes": "Saved definitions and the owner's policy."})

    if treatment:
        monkeypatch.setattr(trial, "approval_digest", lambda kind, artifact: "saved-card-digest")
        await session.call("request_owner_approval", {
            "kind": "card", "id": "card-1", "summary": "Review the revised saved card.",
        })
        session.revision_verified = True
        arguments = {"card_ids": ["card-1"], "message": "Policy is recorded.", "unresolved": []}
        result = await session.call("finish_setup", arguments)
        assert result["recorded"] is True
        assert session.setup["card_ids"] == ["card-1"]
    else:
        before_approvals = dict(session.approvals)
        before_requests = list(session.owner_requests)
        with pytest.raises(ValueError, match="saved approval target unavailable"):
            await session.call("request_owner_approval", {
                "kind": "card", "id": "card-1", "summary": "Review an unavailable card.",
            })
        assert session.approvals == before_approvals
        assert session.owner_requests == before_requests

        await session.call("request_owner_approval", {
            "kind": "notes", "id": "working", "summary": "Review the saved baseline notes.",
        })
        before_finish = {
            "approvals": dict(session.approvals),
            "finished_stages": set(session.finished_stages),
            "notes": session.notes,
            "owner_requests": list(session.owner_requests),
            "setup": session.setup,
            "setup_complete": session.setup_complete,
        }
        with pytest.raises(ValueError, match="baseline setup cannot include card IDs"):
            await session.call("finish_setup", {
                "card_ids": ["unsupported-card"], "message": "Policy is recorded.", "unresolved": [],
            })
        assert session.approvals == before_finish["approvals"]
        assert session.finished_stages == before_finish["finished_stages"]
        assert session.notes == before_finish["notes"]
        assert session.owner_requests == before_finish["owner_requests"]
        assert session.setup == before_finish["setup"]
        assert session.setup_complete == before_finish["setup_complete"]

        result = await session.call("finish_setup", {
            "card_ids": [], "message": "Policy is recorded.", "unresolved": [],
        })
        assert result["recorded"] is True
        assert session.setup["card_ids"] == []


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


@pytest.mark.parametrize("cohort", ["owner-handoff-v3", "owner-handoff-v4"])
def test_role_corrected_cohort_is_new_and_cannot_recharge_closed_unknown_usage(cohort):
    from types import SimpleNamespace

    args = SimpleNamespace(cohort_id=cohort, owner_handoff=True, charge_trace=None)
    protocol, limits, charge = trial.owner_workflow_settings(args)
    assert protocol == cohort
    assert limits == trial.OWNER_HANDOFF_LIMITS
    assert charge is None
    args.charge_trace = "closed-v2-trace"
    with pytest.raises(ValueError):
        trial.owner_workflow_settings(args)

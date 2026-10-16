"""Offline contracts for the clarified Pine Courier explicit-owner pair."""

import json
import sys

import pytest

from evaluations import public_owner_report_trial as trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import public_episode
from evaluations.domain_context_onboarding_trial import clarified_development_scenario
from tests.test_public_owner_report_trial import FakeNative, _patch_offline


def _select_development_owner(args):
    args.development_owner = True
    args.expert_reference = True
    args.expert_notes_file = None
    args.explicit_owner_confirmation = True
    args.baseline_handoff_report = None
    args.baseline_handoff_trace = None
    return args


def test_development_flag_requires_reference_and_explicit_confirmation(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "public_owner_report_trial.py", "--binary", "/binary", "--codex-executable", "/codex",
        "--output", "/output", "--development-owner",
    ])

    with pytest.raises(SystemExit) as error:
        trial.main()

    assert error.value.code == 2
    assert "requires --expert-reference and --explicit-owner-confirmation" in capsys.readouterr().err


@pytest.mark.parametrize(("field", "value", "message"), [
    ("expert_notes_file", "/private/steward-notes.txt", "cannot be combined with --expert-notes-file"),
    ("baseline_handoff_report", "/archive/report.json", "cannot resume or import an archived baseline handoff"),
    ("baseline_handoff_trace", "/archive/trace.jsonl", "cannot resume or import an archived baseline handoff"),
])
def test_development_flag_rejects_notes_and_archived_handoffs(field, value, message):
    from types import SimpleNamespace

    args = SimpleNamespace(
        development_owner=True, expert_reference=True, explicit_owner_confirmation=True,
        expert_notes_file=None, baseline_handoff_report=None, baseline_handoff_trace=None,
    )
    setattr(args, field, value)

    with pytest.raises(ValueError, match=message):
        trial.validate_cohort_options(args)


def test_development_fixture_reuses_declared_answers_and_adds_memory_request_once():
    original = clarified_development_scenario()
    fixture = trial.development_scenario()
    request = "Remember the agreed definition for future investigations."

    assert fixture["scenario_id"] == original["scenario_id"]
    assert fixture["public"]["company"] == "Pine Courier"
    assert fixture["public"]["owner_answers"] == original["public"]["owner_answers"]
    assert fixture["public"]["periods"] == original["public"]["periods"]
    assert fixture["public"]["brief"].startswith(original["public"]["brief"])
    assert fixture["public"]["brief"].count(request) == 1
    assert trial.development_scenario()["public"]["brief"].count(request) == 1


@pytest.mark.asyncio
async def test_development_author_uses_plain_owner_answers_and_matching_shared_tools():
    fixture = trial.development_scenario()
    public = public_episode(fixture)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    baseline = trial.DevelopmentConversationAuthorEpisode(public, adapter)
    native = FakeNative(adapter, public["scenario_id"])
    treatment = trial.DevelopmentConversationAuthorEpisode(public, adapter, native)

    baseline_specs, treatment_specs = await baseline.specs(), await treatment.specs()
    baseline_hashes, treatment_hashes = trial.pin_tools(baseline_specs), trial.pin_tools(treatment_specs)
    shared = set(baseline_hashes) & set(treatment_hashes)
    assert {name for name in shared if baseline_hashes[name] != treatment_hashes[name]} == {
        "finish_setup", "request_owner_approval",
    }
    assert issubclass(trial.DevelopmentConversationAuthorEpisode, trial.ConversationAuthorEpisode)

    for topic in trial.DEVELOPMENT_OWNER_TOPICS:
        left = await baseline.call("ask_owner", {"topic": topic})
        right = await treatment.call("ask_owner", {"topic": topic})
        expected = public["owner_answers"][topic]
        assert left["known"] is right["known"] is True
        assert left["answer"] == right["answer"] == expected

    reference = await baseline.call("ask_owner", {
        "topic": "Explain any source detail not declared in the public owner answers.",
    })
    assert reference["known"] is False
    assert reference["answer"] is None
    assert reference["answer_status"] == "reference_only"


@pytest.mark.asyncio
async def test_development_preflight_checks_public_answers_without_inference(tmp_path, monkeypatch):
    args, state, _binary, _codex = _patch_offline(monkeypatch, tmp_path, live=False)
    _select_development_owner(args)

    report = await trial.run(args)

    assert report["completed"] is True
    assert report["protocol"] == trial.DEVELOPMENT_OWNER_PROTOCOL
    assert report["period_index"] == 0
    assert report["agent_invocations_started"] == report["provider_attempts"] == 0
    assert report["provider_usage_known"] is True
    assert report["initial_native_card_count"] == 0
    assert report["development_owner_preflight_verified_arms"] == ["baseline", "signalweave"]
    assert report["reference_preflight_arms"] == ["baseline", "signalweave"]
    assert report["preflight_bridge_fidelity_verified"] is True
    assert report["preflight_primary_comparisons"] == 1
    assert "domain_context_onboarding_trial.py" in report["frozen_helpers"]
    assert state["model_calls"] == state["review_calls"] == state["sequence"] == []
    assert state["budget"].limit == state["budget"].used == 0

    exported = json.loads((tmp_path / "trial-output" / "public-onboarding-input.json").read_text())
    fixture = trial.development_scenario()
    assert exported["scenario_id"] == fixture["scenario_id"]
    assert exported["period"]["period_id"] == fixture["public"]["onboarding"]["period_id"]
    assert exported["brief"].endswith(report["development_memory_request"])
    assert not ({"private", "periods", "labels"} & exported.keys())


@pytest.mark.asyncio
async def test_live_mock_pair_uses_period_index_zero_and_six_bounded_calls(tmp_path, monkeypatch):
    args, state, _binary, _codex = _patch_offline(monkeypatch, tmp_path, live=True)
    _select_development_owner(args)
    report = await trial.run(args)

    assert report["completed"] is True
    assert report["protocol"] == trial.DEVELOPMENT_OWNER_PROTOCOL
    assert report["limits"]["agent_invocations"] == 6
    assert report["limits"]["jev_attempts"] == state["budget"].used == report["provider_attempts"] == 1
    assert report["limits"]["between_invocation_input_stop"] == 1_200_000
    assert report["limits"]["between_invocation_uncached_stop"] == 220_000
    assert report["agent_invocations_started"] == 6
    assert state["sequence"] == [
        ("author", "baseline"), ("review", "baseline"),
        ("author", "signalweave"), ("review", "signalweave"),
        ("report", "baseline"), ("report", "signalweave"),
    ]

    fixture = trial.development_scenario()
    selected = fixture["public"]["periods"][0]
    assert selected["period_id"] != fixture["public"]["periods"][1]["period_id"]
    report_contexts = [context for stage, _arm, context in state["contexts"] if stage == "report"]
    assert len(report_contexts) == 2
    assert all(context["period_id"] == selected["period_id"] for context in report_contexts)
    author_entries = [entry for entry in report["episodes"] if entry["stage"] == "author"]
    assert len(author_entries) == 2
    for entry in author_entries:
        asked_topics = {item.get("topic") for item in entry["owner_requests"]}
        # Reusing an already supplied glossary answer must not become a false
        # onboarding failure for not asking the same question again.
        assert "context_review" in asked_topics
        assert "source_scope" not in asked_topics

    native_calls = state["native"].calls
    assert native_calls[0][0] == "list_insight_cards"
    assert native_calls[0][1] == {}
    assert all(name not in {"restore_reviewed_card", "import_sqlite"} for name, _args in native_calls)


@pytest.mark.asyncio
async def test_default_and_v5_protocols_keep_legacy_fixture_and_period(tmp_path, monkeypatch):
    default_root = tmp_path / "default"
    default_root.mkdir()
    args, _state, _binary, _codex = _patch_offline(monkeypatch, default_root, live=False)
    default_report = await trial.run(args)

    assert default_report["protocol"] == trial.PROTOCOL
    assert default_report["period_index"] == 2
    assert trial.scenario()["public"]["company"] == "Juniper Trail Retail"
    assert trial.scenario()["public"]["brief"].endswith(
        "Remember the agreed definition for future sales investigations."
    )

    v5_root = tmp_path / "v5"
    v5_root.mkdir()
    args, _state, _binary, _codex = _patch_offline(monkeypatch, v5_root, live=False)
    notes = v5_root / "steward-notes.txt"
    notes.write_text("Public fictional steward declaration for the unchanged v5 path.")
    args.expert_reference = True
    args.expert_notes_file = str(notes)
    args.explicit_owner_confirmation = True
    v5_report = await trial.run(args)

    assert v5_report["protocol"] == trial.CONVERSATION_PROTOCOL
    assert v5_report["period_index"] == 2
    assert v5_report["expert_notes"]["sha256"]
    assert trial.scenario()["public"]["company"] == "Juniper Trail Retail"

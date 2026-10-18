"""Journey admission/artifact controls; no model, provider or human outcome claims."""

import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations import harbor_workflow_journey as journey


def author(message, notes, card=None):
    value = {"process_complete": True, "episode": {"final_message": message}, "notes": notes,
             "card": card, "approval_handoff": {"arguments_after_owner_confirmation": {"card_id": "c1"}}}
    value["review_artifact_digest"] = journey.digest({"message": message, "notes": notes, "card": card})
    return value


def test_review_identifies_the_actual_messages_notes_and_saved_card(tmp_path):
    authors = {"signalweave": author("Known records need review", "Use first response, not resolution", {"id": "c1", "status": "draft"}),
               "baseline": author("Known records need review", "Use the saved query and retain prior handoff IDs")}
    for arm, value in authors.items():
        journey.write(tmp_path / f"onboarding-{arm}.json", value)
    review = {"reviewer": "Fictional exercise expert", "reviewer_type": "simulated_expert",
              "approved_for_shadow_recurrence": True, "reason": "Reviewed definitions, actual brief, sources and audience",
              "source_selection_reason": "Confirmed known-record first-response population, not resolution work",
              "assessments": {"signalweave": "Reviewed actual draft and human brief", "baseline": "Reviewed actual portable notes and human brief"},
              "artifacts": {arm: value["review_artifact_digest"] for arm, value in authors.items()}}
    path = tmp_path / "review.json"
    journey.write(path, review)
    actual, saved = journey.reviewed_artifacts(tmp_path, path)
    assert actual == review and saved == authors
    # An explicit reviewer, not a filled-in protocol template, must see an edit.
    altered = copy.deepcopy(authors["signalweave"])
    altered["notes"] = "Changed policy after review"
    (tmp_path / "onboarding-signalweave.json").write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="actual current author artifacts"):
        journey.reviewed_artifacts(tmp_path, path)


@pytest.mark.parametrize("fault", ["no-consent", "no-reviewer", "no-reason", "no-notes", "no-card", "no-handoff"])
def test_artifact_existence_cannot_substitute_for_review(tmp_path, fault):
    authors = {"signalweave": author("Readout", "Agreed brief", {"id": "c1", "status": "draft"}),
               "baseline": author("Readout", "Agreed brief")}
    if fault == "no-notes":
        authors["baseline"]["notes"] = ""
    elif fault == "no-card":
        authors["signalweave"]["card"] = None
    elif fault == "no-handoff":
        authors["signalweave"]["approval_handoff"] = {}
    for arm, value in authors.items():
        journey.write(tmp_path / f"onboarding-{arm}.json", value)
    review = {"reviewer": "Exercise expert", "reviewer_type": "simulated_expert",
              "approved_for_shadow_recurrence": fault != "no-consent", "reason": "Actual artifact review",
              "artifacts": {arm: journey.digest({"message": value["episode"]["final_message"],
                                                "notes": value["notes"], "card": value["card"]})
                            for arm, value in authors.items()}}
    if fault == "no-reviewer":
        review["reviewer"] = ""
    elif fault == "no-reason":
        review["reason"] = ""
    path = tmp_path / "review.json"
    journey.write(path, review)
    with pytest.raises(ValueError):
        journey.reviewed_artifacts(tmp_path, path)


def completed(input_tokens=1000, uncached=100, attempts=0):
    return {"process_complete": True, "usage": {"known": True, "usage": {
        "input_tokens": input_tokens, "uncached_input_tokens": uncached}}, "provider_attempts": attempts,
        "provider_usage": {"known": True}}


def test_between_actor_budget_includes_both_arms_and_onboarding(tmp_path):
    journey.write(tmp_path / "onboarding-signalweave.json", completed(input_tokens=400_000))
    journey.write(tmp_path / "onboarding-baseline.json", completed(input_tokens=300_000))
    with pytest.raises(ValueError, match="stop reached"):
        journey.admission(tmp_path)


@pytest.mark.parametrize("fault", ["failed", "unknown", "uncached", "provider", "unreported-claim"])
def test_no_next_actor_after_censored_or_exhausted_work(tmp_path, fault):
    report = completed()
    if fault == "failed":
        report["process_complete"] = False
    elif fault == "unknown":
        report["usage"]["known"] = False
    elif fault == "uncached":
        report["usage"]["usage"]["uncached_input_tokens"] = 150_000
    elif fault == "provider":
        report["provider_attempts"] = 7
    else:
        journey._private_file(tmp_path / "onboarding-signalweave.claimed", "interrupted")
    if fault != "unreported-claim":
        journey.write(tmp_path / "onboarding-signalweave.json", report)
    with pytest.raises(ValueError):
        journey.admission(tmp_path)


def test_exact_provider_ceiling_does_not_forbid_a_no_provider_baseline(tmp_path):
    journey.write(tmp_path / "recurring-signalweave.json", completed(attempts=6))
    assert journey.admission(tmp_path) == 6


def test_stage_lock_prevents_concurrent_budget_checks(tmp_path):
    with journey.single_actor(tmp_path):
        with pytest.raises(FileExistsError):
            with journey.single_actor(tmp_path):
                pytest.fail("Second coordinator must not enter")
    assert not (tmp_path / "actor-running.lock").exists()
    assert journey.admission(tmp_path) == 0


@pytest.mark.asyncio
async def test_default_actor_command_does_not_start_paid_work(tmp_path):
    with pytest.raises(ValueError, match="explicit --execute"):
        await journey.run_actor(tmp_path, "baseline", "onboarding")
    assert list(tmp_path.iterdir()) == []


def test_shared_prior_context_contains_no_future_source_values_or_approval():
    owner = journey.owner_context()
    assert owner["recipient_keys"] == ["support_queue_lead", "duty_manager"]
    assert owner["resolved_policy_variant"]["variant"] == "unanswered-priority-handoff"
    assert owner["owner_type"].startswith("fictional prior context")
    assert not {"expected_outcome", "gold_answer", "source_cutoffs", "approved"} & owner.keys()


def test_summary_preserves_actual_messages_and_unknown_usage(tmp_path):
    report = {**completed(), "total_stage_seconds": 12.3, "briefs": [{"body": "Inspect these known items"}],
              "episode": {"final_message": "Useful first answer"}, "errors": []}
    report["usage"]["usage"]["output_tokens"] = 500
    journey.write(tmp_path / "onboarding-baseline.json", report)
    result = journey.summarize(tmp_path)
    assert result["recorded_stages"][0]["final_message"] == "Useful first answer"
    assert result["recorded_total_usage"]["input_tokens"] == 1000
    assert len(result["recorded_stages"]) == 1 and result["expected_stages"] == 4
    journey._private_file(tmp_path / "onboarding-signalweave.claimed", "interrupted")
    unknown = journey.summarize(tmp_path)
    assert unknown["recorded_total_usage"] is None
    assert unknown["unreported_claims"] == ["onboarding-signalweave"]


@pytest.mark.asyncio
async def test_complete_staged_caller_with_scripted_analyst_and_source_doubles(tmp_path, monkeypatch):
    """Exercise orchestration only: these doubles are NOT live business results."""
    snapshots = []
    key = tmp_path / "test.key"
    key.write_text("synthetic-never-sent")
    for index in range(3):
        path = tmp_path / f"snapshot-{index}"
        path.write_text(str(index))
        snapshots.append({"path": str(path), "sha256": journey._sha(path), "cutoff": f"2026-03-{index + 1:02d}T06:00:00Z"})
    study = {"protocol": journey.PROTOCOL, "snapshots": snapshots, "key_file": str(key),
             "codex": {"path": "scripted-test-double"}, "registry_sha256": "scripted-not-a-real-registry"}
    journey.write(tmp_path / "study.json", study)
    for arm in journey.ARMS:
        work = tmp_path / arm
        work.mkdir()
        journey._activate(Path(snapshots[0]["path"]), work / "active.sqlite3", None)
        if arm == "signalweave":
            skill = work / ".agents/skills/signalweave/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("Scripted test skill, not a trained analyst")
    card = {"id": "test-card", "status": "draft", "decision_guidance": "Exercise policy"}
    handoff = {"arguments_after_owner_confirmation": {"card_id": "test-card"}}

    class SessionDouble:
        def __init__(self, native, arm, audit, budget):
            self.native, self.arm, self.audit, self.budget = native, arm, audit, budget

        async def list_tools(self):
            names = (["onboard_insight_card", "review_insight_card", "evaluate_insight_card"]
                     if self.native else ["query_readonly"])
            return [SimpleNamespace(name=name, description="Scripted test double", inputSchema={"type": "object"}) for name in names]

        async def call_tool(self, name, arguments):
            if name == "onboard_insight_card":
                value = {"card": copy.deepcopy(card)}
            elif name == "review_insight_card":
                value = {"card": copy.deepcopy(card), "approval_handoff": handoff}
            elif name == "list_insight_cards":
                value = {"cards": [{"id": card["id"]}]}
            elif name == "get_insight_card":
                value = copy.deepcopy(card)
            elif name == "approve_insight_card":
                card["status"] = "approved"
                value = copy.deepcopy(card)
            else:
                index = int((tmp_path / self.arm / "active.sqlite3").read_text())
                value = {"scripted_observation_index": index}
                if name == "evaluate_insight_card":
                    self.budget.claim()
                    self.audit.emit("api.request", provider="jev", request_id=self.budget.used,
                                    transport="scripted_test_double")
                    self.audit.emit("api.response", provider="jev", request_id=self.budget.used,
                                    usage={"input_tokens": 100, "output_tokens": 10}, transport="scripted_test_double")
                    value.update(replayed=False, receipt={"receipt_id": f"test-receipt-{index}", "card_id": card["id"],
                        "status": "delivery_disabled", "idempotency_key": f"test-key-{index}"},
                        result={"outcome": "investigate", "evaluator": "jev-scripted-test-double"})
            return [], value

    @asynccontextmanager
    async def session_doubles(study, root, arm, audit, budget):
        yield (SessionDouble(False, arm, audit, budget),
               SessionDouble(True, arm, audit, budget) if arm == "signalweave" else None)

    async def scripted_actor(actor, **kwargs):
        audit = kwargs["audit"]
        audit.emit("api.request", provider="openai", request_id=1, transport="scripted_test_double")
        if actor.phase == "onboarding":
            await actor.call("query_readonly", {"sql": "scripted source read"})
            await actor.call("save_working_notes", {"notes": "Retained only this arm's source map, SQL and agreed policy"})
            if actor.treatment:
                await actor.call("onboard_insight_card", {})
                await actor.call("review_insight_card", {"card_id": "test-card"})
        else:
            for index in range(3):
                assert "Retained only this arm" in actor.notes
                name = "evaluate_insight_card" if actor.treatment else "query_readonly"
                actual = await actor.call(name, {"card_id": "test-card"} if actor.treatment else {"sql": "reused query"})
                assert actual["scripted_observation_index"] == index
                await actor.call("save_brief", {"body": f"Scripted brief for observation {index}",
                    "recipients": ["support_queue_lead"] if index == 1 else [],
                    "evidence_refs": ["scripted-source-not-real-evidence"]})
        audit.emit("api.response", provider="openai", request_id=1, usage={"input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 100}, "output_tokens": 100})
        return {"status": "complete", "final_message": "Scripted final reply, not live analyst work"}

    monkeypatch.setattr(journey, "verify_study", lambda study: None)
    monkeypatch.setattr(journey, "sessions", session_doubles)
    monkeypatch.setattr(journey, "codex_episode", scripted_actor)
    authors = {}
    for arm in journey.ARMS:
        authors[arm] = await journey.run_actor(tmp_path, arm, "onboarding", execute=True)
        assert authors[arm]["process_complete"] and authors[arm]["provider_attempts"] == 0, (authors[arm]["errors"], authors[arm]["usage"])
    review = {"reviewer": "Scripted unit-test expert", "reviewer_type": "simulated_expert",
              "approved_for_shadow_recurrence": True, "reason": "Tests mechanics only, no business assessment",
              "source_selection_reason": "Scripted source selection, not real expert assessment",
              "assessments": {arm: "Scripted test-double artifacts only" for arm in journey.ARMS},
              "artifacts": {arm: value["review_artifact_digest"] for arm, value in authors.items()}}
    review_path = tmp_path / "review.json"
    journey.write(review_path, review)
    for arm in journey.ARMS:
        result = await journey.run_actor(tmp_path, arm, "recurring", execute=True, review_path=review_path)
        assert result["process_complete"] and len(result["briefs"]) == 3
        assert all(brief["sent"] is False for brief in result["briefs"])
        assert result["provider_attempts"] == (3 if arm == "signalweave" else 0)
        assert result["policy_path_exercised"] is (arm == "signalweave")
    summary = journey.summarize(tmp_path)
    assert len(summary["recorded_stages"]) == 4
    assert summary["recorded_total_usage"]["input_tokens"] == 4000
    with pytest.raises(ValueError, match="stop reached"):
        journey.admission(tmp_path)


@pytest.mark.parametrize("fault", [None, "deferred", "replayed", "duplicate", "no-provider", "wrong-card"])
def test_exposure_requires_distinct_current_policy_receipts_not_just_saved_briefs(fault):
    calls = [{"name": "evaluate_insight_card", "observation_cutoff": str(index), "result": {
        "receipt": {"receipt_id": f"r{index}", "idempotency_key": f"k{index}", "card_id": "c", "status": "delivery_disabled"},
        "result": {"outcome": "investigate", "evaluator": "jev-latest"}, "replayed": False}} for index in range(3)]
    provider = {"known": True, "attempts": 3}
    if fault == "deferred":
        calls[1]["result"]["result"]["judgment"] = {"status": "deferred"}
    elif fault == "replayed":
        calls[1]["result"]["replayed"] = True
    elif fault == "duplicate":
        calls[1]["result"]["receipt"] = calls[0]["result"]["receipt"]
    elif fault == "no-provider":
        provider["attempts"] = 0
    elif fault == "wrong-card":
        calls[1]["result"]["receipt"]["card_id"] = "other"
    assert journey.policy_path_exercised(calls, ["0", "1", "2"], "c", provider) is (fault is None)


def test_provider_usage_keeps_failed_or_missing_accounting_unknown():
    from evaluations.bootstrap_agent_trial import Audit

    audit = Audit()
    assert journey.provider_usage(audit, 0) == {"known": True, "attempts": 0,
                                              "usage": {"input_tokens": 0, "output_tokens": 0}}
    audit.emit("api.request", provider="jev", request_id=1)
    assert journey.provider_usage(audit, 1)["known"] is False
    audit.emit("api.response", provider="jev", request_id=1, usage={"input_tokens": 200, "output_tokens": 20})
    assert journey.provider_usage(audit, 1)["usage"] == {"input_tokens": 200, "output_tokens": 20}
    audit.emit("api.error", provider="jev", request_id=1)
    assert journey.provider_usage(audit, 1)["usage"] is None


def test_installed_skill_and_bridge_are_checked_again_before_continuing(tmp_path, monkeypatch):
    skill, manifest, codex = (tmp_path / name for name in ("SKILL.md", "manifest.json", "codex"))
    skill.write_bytes((journey.ROOT / "skills/signalweave/SKILL.md").read_bytes())
    manifest.write_text("{}")
    codex.write_text("test-double")
    study = {"protocol": journey.PROTOCOL, "method": {"test": "identity"}, "binary_path": "test-binary",
             "binary_identity": {"test": True}, "codex": {"path": str(codex), "sha256": journey._sha(codex)},
             "skill_path": str(skill), "skill_sha256": journey._sha(skill), "manifest_path": str(manifest),
             "manifest_sha256": journey._sha(manifest), "snapshots": []}
    monkeypatch.setattr(journey, "method_identity", lambda: {"test": "identity"})
    monkeypatch.setattr(journey, "verify_binary", lambda *args: {"test": True})
    journey.verify_study(study)
    manifest.write_text('{"changed":true}')
    with pytest.raises(ValueError, match="source bridge changed"):
        journey.verify_study(study)
    manifest.write_text("{}")
    skill.write_text("changed installed treatment")
    with pytest.raises(ValueError, match="skill changed"):
        journey.verify_study(study)

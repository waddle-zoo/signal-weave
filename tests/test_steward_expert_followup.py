"""Follow-up provenance/control checks, not report quality evidence."""

import copy
import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from evaluations import steward_expert_followup as followup
from evaluations.bootstrap_scenarios import public_episode
from signalweave.models import InsightCard
from tests.test_public_owner_report_trial import FakeNative, _response


class RetainedNative(FakeNative):
    def __init__(self, adapter, tenant, card, context):
        super().__init__(adapter, tenant)
        self.card, self.context = copy.deepcopy(card), copy.deepcopy(context)

    async def call_tool(self, name, args):
        if name == "get_context_history":
            return [], {"revisions": [copy.deepcopy(self.context)]}
        if name == "review_domain_context":
            self.calls.append((name, copy.deepcopy(args)))
            self.context.update(status="reviewed", revision=self.context["revision"] + 1)
            return [], copy.deepcopy(self.context)
        if name == "bind_insight_context":
            self.calls.append((name, copy.deepcopy(args)))
            self.card["version"] += 1
            self.card["context_bindings"] = [{**pin, "content_digest": "a" * 64, "source_digest": "b" * 64}
                                              for pin in args["pins"]]
            return [], {"version": self.card["version"]}
        if name == "review_insight_card":
            self.calls.append((name, copy.deepcopy(args)))
            return [], {"approval_handoff": {"arguments_after_owner_confirmation": {"card_id": args["card_id"]}}}
        return await super().call_tool(name, args)


def inputs(tmp_path, monkeypatch):
    binary, codex, key = [tmp_path / n for n in ("binary", "codex", "key")]
    binary.write_bytes(b"offline native")
    codex.write_bytes(b"offline Codex")
    key.write_text("synthetic-not-a-live-key")
    identity, cli = {"binary_sha256": followup.digest(binary)}, {"sha256": followup.digest(codex), "path": str(codex)}
    prior = tmp_path / "prior"
    prior.mkdir()
    owned = prior / "private-native-state/native-home"
    owned.mkdir(parents=True)
    (owned / "config.toml").write_text("# offline retained-state marker")
    fixture, _, note_hash = followup.attach_steward_notes(followup.scenario(), followup.NOTES)
    public = public_episode(fixture)
    source = public["catalog"][0]
    card = InsightCard(id="retained-card", title="Retained policy", what_to_watch="A source-backed business question",
        why_watch="Unit workflow", sources=[{"key": "source", "adapter": source["adapter"], "resource": source["resource"], "label": "Source"}]).model_dump(mode="json")
    context = {"id": "retained-context", "revision": 1, "status": "draft", "content": {"body": "Exact stored definition"}}
    episodes = [{"arm": arm, "stage": "author", "agent": {"status": "complete"}, "notes": "Original saved notes",
                 "independent_review": {"approved": arm == "baseline"}} for arm in ("baseline", "signalweave")]
    episodes[1].update(card=card, owner_requests=[{"kind": "context", "saved_artifact": {"revisions": [context]}}])
    events = []
    for i in range(4):
        events.extend([{"kind": "api.request", "provider": "openai", "episode": f"prior:{i}"},
                       {"kind": "api.response", "provider": "openai", "episode": f"prior:{i}", "usage": _response()}])
    usage = followup.summarize_usage(SimpleNamespace(events=events), followup.zero_usage())["usage"]
    report = {"protocol": "public-steward-reference-v4", "failure": {"message": "Original study remains stopped"},
              "agent_invocations_started": 4, "provider_attempts": 0, "usage": usage, "build": identity, "codex": cli,
              "episodes": episodes, "expert_notes": {"sha256": note_hash},
              "scenario_sha256": hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest(),
              "read_clock": "2026-10-15T23:00:00+00:00", "measurement_offset_seconds": 0}
    (prior / "report.json").write_text(json.dumps(report))
    (prior / "trace.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (prior / "public-onboarding-input.json").write_text(json.dumps(public))
    manifest = {"protocol": "unit-expert-followup", **{k: followup.digest(prior / n) for n, k in (
        ("report.json", "report_sha256"), ("trace.jsonl", "trace_sha256"), ("public-onboarding-input.json", "public_input_sha256"))}}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(followup, "MANIFEST", manifest_path)
    monkeypatch.setattr(followup, "verify_binary", lambda _: identity)

    async def pinned(_):
        return cli

    monkeypatch.setattr(followup, "pinned_codex", pinned)
    state = {"native": None, "model_calls": 0}

    @asynccontextmanager
    async def native_context(_binary, _key, supplied, adapter, audit, root, *, request_budget):
        assert root == prior / "private-native-state"
        assert (root / "native-home/config.toml").is_file()
        state["budget"] = request_budget
        native = RetainedNative(adapter, supplied["scenario_id"], card, context)
        state["native"] = native
        yield native, (followup.Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md").read_text()

    async def reporter(session, **kwargs):
        state["model_calls"] += 1
        audit = kwargs["audit"]
        audit.emit("api.request", provider="openai")
        if session.native:
            state["budget"].claim()
            audit.emit("api.request", provider="jev")
            audit.emit("api.response", provider="jev", usage={"input_tokens": 10, "output_tokens": 1})
            await session.call("evaluate_insight_card", {"card_id": session.approved_card_id, "idempotency_key": session.run_key})
        await session.call("record_report", {"outcome": "ignore", "recipients": [], "summary": "Offline sink check, not a company finding."})
        audit.emit("api.response", provider="openai", usage=_response())
        return {"status": "complete"}

    monkeypatch.setattr(followup, "native_context", native_context)
    monkeypatch.setattr(followup, "codex_episode", reporter)
    args = SimpleNamespace(prior=str(prior), binary=str(binary), codex_executable=str(codex), key_file=str(key),
                           output=str(tmp_path / "output"), run=False)
    return args, state, report, identity, cli


async def test_preflight_retains_real_drafts_without_approval_or_new_calls(tmp_path, monkeypatch):
    args, state, _, _, _ = inputs(tmp_path, monkeypatch)
    result = await followup.run(args)
    assert result["completed"] and result["retained_drafts_verified"]
    assert result["agent_invocations_started"] == 4 and result["new_agent_invocations_started"] == 0
    assert state["model_calls"] == 0 and result["provider_attempts"] == 0
    assert state["native"].card["status"] == "draft" and state["native"].context["status"] == "draft"


async def test_expert_intervention_keeps_policy_and_charges_four_plus_two(tmp_path, monkeypatch):
    args, state, original, _, _ = inputs(tmp_path, monkeypatch)
    args.run = True
    result = await followup.run(args)
    assert result["completed"] and result["provider_usage_known"]
    assert result["agent_invocations_started"] == 6 and result["new_agent_invocations_started"] == 2
    assert result["provider_attempts"] == 1 and state["model_calls"] == 2
    card = result["expert_intervention"]["card"]
    assert followup.policy_signature(card) == followup.policy_signature(original["episodes"][1]["card"])
    assert card["version"] == 2 and card["context_bindings"][0]["required_for_action"]
    assert result["expert_intervention"]["context"]["revision"] == 2
    assert json.loads((tmp_path / "prior/report.json").read_text()) == original


@pytest.mark.parametrize("fault", ["changed-input", "changed-binary", "changed-cli"])
def test_loader_rejects_unpinned_evidence(tmp_path, monkeypatch, fault):
    args, _, _, identity, cli = inputs(tmp_path, monkeypatch)
    if fault == "changed-input":
        (tmp_path / "prior/public-onboarding-input.json").write_text("{}")
    elif fault == "changed-binary":
        identity = {"binary_sha256": "different"}
    else:
        cli = {"sha256": "different"}
    with pytest.raises(ValueError):
        followup.load_prior(followup.Path(args.prior), identity, cli)


async def test_changed_native_draft_cannot_be_replaced_or_approved(tmp_path, monkeypatch):
    args, state, _, _, _ = inputs(tmp_path, monkeypatch)
    original = followup.existing_drafts

    async def changed(native, card, context):
        native.card["decision_guidance"] = "Changed before sign-off"
        return await original(native, card, context)

    monkeypatch.setattr(followup, "existing_drafts", changed)
    args.run = True
    result = await followup.run(args)
    assert not result.get("completed", False)
    assert state["model_calls"] == 0 and result["provider_attempts"] == 0
    assert not any(name.startswith("approve") for name, _ in state["native"].calls)

"""Research conversation fidelity; no model behavior or human-UX claims."""

import copy
from datetime import datetime, timezone

import pytest

from evaluations import public_owner_report_trial as trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_owner_review import review_payload
from evaluations.bootstrap_scenarios import public_episode
from evaluations.explicit_owner_conversation import AuditedNative
from signalweave.models import InsightCard, SourceRef
from tests.test_public_owner_report_trial import FakeNative, _patch_offline


@pytest.mark.parametrize("kind", ["notes", "card"])
async def test_reply_is_bound_to_actual_saved_artifact_and_does_not_approve_it(kind):
    public = public_episode(trial.scenario())
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    native = FakeNative(adapter, public["scenario_id"]) if kind == "card" else None
    episode = trial.ConversationAuthorEpisode(public, adapter, native)
    if native:
        created = await episode.call("onboard_insight_card", {"title": "An agent's actual draft"})
        target = created["card"]["id"]
        before = copy.deepcopy(native.card)
    else:
        await episode.call("save_working_notes", {"notes": "The agent's actual reusable brief"})
        target = "working"
    result = await episode.call("request_owner_approval", {
        "kind": kind, "id": target, "summary": "Actual owner-facing summary",
    })
    request = episode.owner_requests[-1]
    assert request["summary"] == "Actual owner-facing summary"
    assert request["owner_reply"] == result
    assert "consent" not in result and result["owner_type"] == "scripted_fixture"
    assert result["confirmation_target"]["id"] == target
    assert result["confirmation_target"]["artifact_digest"] == episode.approvals[kind, target]
    assert "Do not schedule anything or send a message" in result["answer"]
    if native:
        assert request["saved_artifact"] == before
        assert result["confirmation_target"]["card_version"] == before["version"]
        assert f"{target}, version {before['version']}" in result["answer"]
        assert native.card == before and native.card["status"] == "draft"
        assert not any(name == "approve_insight_card" for name, _ in native.calls)
        assert "source_selection_reason" not in result and "approval_handoff" not in result
    else:
        assert request["saved_artifact"] == {"notes": episode.notes}
        assert result["confirmation_target"]["card_version"] is None


@pytest.mark.parametrize("kind", ["notes", "card"])
async def test_a_reply_to_old_content_cannot_complete_new_content(kind):
    public = public_episode(trial.scenario())
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    native = FakeNative(adapter, public["scenario_id"]) if kind == "card" else None
    episode = trial.ConversationAuthorEpisode(public, adapter, native)
    if native:
        target = (await episode.call("onboard_insight_card", {"title": "Original draft"}))["card"]["id"]
    else:
        await episode.call("save_working_notes", {"notes": "Original brief"})
        target = "working"
    reply = await episode.call("request_owner_approval", {"kind": kind, "id": target, "summary": "Original summary"})
    original_digest = reply["confirmation_target"]["artifact_digest"]
    if native:
        native.card["version"] += 1
        native.card["decision_guidance"] = "A changed policy not shown to the owner"
        with pytest.raises(ValueError, match="consent"):
            await episode.call("approve_insight_card", {"card_id": target})
    else:
        await episode.call("save_working_notes", {"notes": "Changed brief"})
        with pytest.raises(ValueError, match="consent"):
            await episode.call("finish_setup", {"card_ids": [], "message": "Not complete", "unresolved": []})
    assert episode.owner_requests[-1]["owner_reply"]["confirmation_target"]["artifact_digest"] == original_digest
    assert not episode.setup_complete


async def test_missing_artifact_never_receives_a_yes():
    public = public_episode(trial.scenario())
    episode = trial.ConversationAuthorEpisode(
        public, PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit()),
    )
    with pytest.raises(ValueError, match="unavailable"):
        await episode.call("request_owner_approval", {"kind": "notes", "id": "missing", "summary": "Please approve"})
    assert episode.owner_requests == [] and episode.approvals == {}


async def test_native_wrapper_records_helper_calls_and_failures_without_rewriting():
    class Native:
        instructions = "Actual native instructions"

        async def call_tool(self, name, arguments):
            if name == "failure":
                raise ValueError("native rejection")
            return ["raw"], {"actual": arguments}

    audit = Audit()
    native = AuditedNative(Native(), audit)
    assert native.instructions == "Actual native instructions"
    assert await native.call_tool("get_insight_card", {"card_id": "saved"}) == (["raw"], {"actual": {"card_id": "saved"}})
    with pytest.raises(ValueError, match="native rejection"):
        await native.call_tool("failure", {})
    assert [event["kind"] for event in audit.events] == [
        "native.operation.start", "native.operation.result", "native.operation.start", "native.operation.error",
    ]


async def test_new_protocol_preflight_is_separate_zero_inference_and_audited(tmp_path, monkeypatch):
    args, state, _, _ = _patch_offline(monkeypatch, tmp_path, live=False)
    args.explicit_owner_confirmation = args.expert_reference = True
    args.expert_notes_file = str(trial.Path(trial.__file__).with_name("data") / "juniper-source-steward-v1.md")
    result = await trial.run(args)
    assert result["completed"] is True
    assert result["protocol"] == trial.CONVERSATION_PROTOCOL
    assert result["agent_invocations_started"] == result["provider_attempts"] == 0
    assert result["limits"] == trial.LIMITS
    assert len(result["frozen_helpers"]) == 3
    assert state["sequence"] == []
    trace = (tmp_path / "trial-output" / "trace.jsonl").read_text()
    assert '"native.operation.start"' in trace and '"native.operation.result"' in trace


async def test_existing_protocol_retains_opaque_reply_not_retroactively_repaired():
    public = public_episode(trial.scenario())
    episode = trial.ReferenceAuthorEpisode(public, PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit()))
    await episode.call("save_working_notes", {"notes": "Original notes"})
    result = await episode.call("request_owner_approval", {"kind": "notes", "id": "working", "summary": "Original summary"})
    assert "answer" not in result and "owner_reply" not in episode.owner_requests[-1]


async def test_new_protocol_keeps_six_call_order_and_shared_tools(tmp_path, monkeypatch):
    args, state, _, _ = _patch_offline(monkeypatch, tmp_path, live=True)
    args.explicit_owner_confirmation = args.expert_reference = True
    args.expert_notes_file = str(trial.Path(trial.__file__).with_name("data") / "juniper-source-steward-v1.md")
    result = await trial.run(args)
    assert result["completed"] is True and result["agent_invocations_started"] == 6
    assert state["sequence"] == [
        ("author", "baseline"), ("review", "baseline"),
        ("author", "signalweave"), ("review", "signalweave"),
        ("report", "baseline"), ("report", "signalweave"),
    ]
    for entry in result["episodes"][:2]:
        requests = [r for r in entry["owner_requests"] if "saved_artifact" in r]
        assert requests and all(r["owner_reply"]["answer"].startswith("Yes.") for r in requests)
    baseline = result["author_tool_inventories"]["baseline"]
    treatment = result["author_tool_inventories"]["signalweave"]
    assert {name for name in baseline if baseline[name] != treatment[name]} == {
        "finish_setup", "request_owner_approval",
    }


async def test_actual_fixture_reviewer_packet_links_usd_metric_to_relative_percent():
    # A unit-contract probe, not an authored/imported study card or model score.
    fixture = trial.scenario()
    public = public_episode(fixture)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    adapter.set_period(public["period"], datetime.now(timezone.utc))
    asset = next(a for a in public["catalog"] if a["contract"].get("roles") == ["primary"])
    source = SourceRef(key="selected", adapter=asset["adapter"], resource=asset["resource"], label=asset["title"])
    snapshot = await adapter.inspect(source)
    comparison = snapshot.analytical_comparisons[0]
    source = source.model_copy(update={"required_comparison_keys": [comparison.key]})
    card = InsightCard(
        id="unit-contract-probe", title="Unit-contract probe", what_to_watch="Net sales",
        why_watch="Check the serialized review units", sources=[source],
        numeric_conditions=[{"text": "Decline by at least ten percent", "source_key": source.key,
                             "comparison_key": comparison.key, "measurement": "change_pct",
                             "threshold": -10, "unit": "percent", "comparator": "<=", "absolute": False}],
    )
    packet = review_payload(public=fixture["public"], owner_answers=public["owner_answers"],
                            artifact={"card": card.model_dump(mode="json"), "notes": ""},
                            source_context={"catalog": public["catalog"], "inspected_sources": [
                                {**snapshot.model_dump(mode="json"), "ref": f"{source.adapter}|{source.resource}"},
                            ]})
    binding = packet["execution_contract"]["numeric_bindings"][0]
    assert comparison.unit == "USD" and binding["unit"] == "percent"
    assert binding["runtime_projection"]["bound_comparison"] == comparison.key
    assert binding["runtime_projection"]["formula"] == "100 * (current - baseline) / abs(baseline)"
    assert "nonzero baseline" in binding["runtime_projection"]["preconditions"]
    assert binding["absolute"] is False


@pytest.mark.parametrize("reference,notes", [(False, False), (True, False), (False, True)])
async def test_new_protocol_requires_fixed_source_context_before_start(tmp_path, monkeypatch, reference, notes):
    args, state, _, _ = _patch_offline(monkeypatch, tmp_path, live=False)
    args.explicit_owner_confirmation = True
    args.expert_reference = reference
    args.expert_notes_file = "notes" if notes else None
    with pytest.raises(ValueError, match="requires"):
        await trial.run(args)
    assert not (tmp_path / "trial-output").exists()
    assert state["sequence"] == []

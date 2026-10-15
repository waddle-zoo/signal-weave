"""Offline contracts for the two-turn owner-handoff cohort."""

import hashlib
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations import domain_context_onboarding_trial as trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import public_episode


def episode(*, stage="first", owner_answers=None, native=None, first_card=None):
    scenario = trial.clarified_development_scenario()
    public = public_episode(scenario)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    adapter.set_period(public["period"], datetime.now(timezone.utc))
    return trial.HandoffEpisode(public, adapter, native, stage=stage,
                                owner_answers=owner_answers, first_card=first_card)


def first_entry(public, *, card_ids=None, topic="materiality"):
    return {
        "setup": {"card_ids": card_ids or [], "message": "Current readout.",
                  "unresolved": ["Which threshold and destination should govern the recurring action?"]},
        "notes": "Saved source notes and initial policy draft.",
        "owner_requests": [{"topic": topic, "stage": "first", "answer_status": "pending"}],
    }


async def test_first_turn_owner_question_is_pending_and_glossary_stays_available():
    session = episode()
    specs = await session.specs()
    by_name = {tool["name"]: tool for tool in specs}
    assert {"read_company_glossary", "ask_owner", "save_working_notes"} <= by_name.keys()
    assert by_name["ask_owner"]["parameters"]["properties"]["topic"]["enum"] == session.public["owner_topics"]
    assert "request_owner_approval" not in by_name
    assert "approve_insight_card" not in by_name

    answer = await session.call("ask_owner", {"topic": "source_scope"})
    assert answer["answer_status"] == "pending_owner_answer"
    assert answer["answer"] is None
    assert session.public["owner_answers"]["source_scope"] not in json.dumps(answer)

    glossary = await session.call("read_company_glossary", {})
    assert glossary["definitions"]["population"] == session.public["glossary"]["population"]
    await session.call("save_working_notes", {"notes": "Initial definitions and source notes."})
    result = await session.call("finish_setup", {
        "card_ids": [], "message": "Current evidence is available; policy needs the owner's answer.",
        "unresolved": ["Which owner threshold should determine the recurring action?"],
    })
    assert result["handoff_state"] == "awaiting_owner_context"
    assert session.setup["unresolved"]


async def test_missing_declared_answer_stops_without_guessing():
    session = episode(stage="second", owner_answers={"metric_scope": "Declared scope."})
    with pytest.raises(ValueError, match="declared owner answer is missing"):
        await session.call("ask_owner", {"topic": "materiality"})
    assert session.terminal_stop

    public = deepcopy(session.public)
    public["owner_answers"].pop("materiality")
    with pytest.raises(ValueError, match="complete declared public owner-answer packet"):
        trial.owner_handoff_prompt(public, first_entry(public))


def test_second_turn_packet_contains_only_public_answers_and_saved_handoff():
    session = episode()
    public = deepcopy(session.public)
    public["fixture_private"] = {"expected_outcome": "PRIVATE_LABEL_SENTINEL"}
    entry = first_entry(public, card_ids=["saved-card"])
    card = {"id": "saved-card", "version": 7, "private_label": "PRIVATE_CARD_SENTINEL"}

    packet = trial.owner_handoff_prompt(public, entry, card)
    assert packet["owner_answers"] == public["owner_answers"]
    assert packet["owner_questions"] == entry["setup"]["unresolved"]
    assert packet["saved_notes"] == entry["notes"]
    assert packet["saved_setup"] == entry["setup"]
    assert packet["saved_card"] == {"card_id": "saved-card", "version": 7}
    assert "PRIVATE_LABEL_SENTINEL" not in json.dumps(packet)
    assert "PRIVATE_CARD_SENTINEL" not in json.dumps(packet)
    assert "fixture_private" not in packet["business"]
    assert "glossary" not in packet["business"]
    assert "period" not in packet["business"]
    assert "catalog" not in packet["business"]

    second_arm_packet = trial.owner_handoff_prompt(public, first_entry(public), None)
    assert second_arm_packet["owner_answers"] == packet["owner_answers"]


class FakeNative:
    def __init__(self, card):
        self.card = deepcopy(card)
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == "get_insight_card":
            return [], deepcopy(self.card)
        if name == "revise_insight_card":
            if not isinstance(args.get("changes"), dict) or not args.get("reason"):
                raise ValueError("revise_insight_card requires changes and reason")
            if (type(args.get("expected_card_version")) is not int
                    or args["expected_card_version"] != self.card["version"]):
                raise ValueError("card version changed; get and review the current card before revising")
            self.card["version"] += 1
            return [], {"card": deepcopy(self.card), "approval_required": True}
        raise AssertionError(f"unexpected native call: {name}")


async def test_revision_allows_argument_correction_but_requires_same_card_version_plus_one():
    first_card = {"id": "saved-card", "version": 7, "status": "draft"}
    native = FakeNative(first_card)
    session = episode(stage="second", owner_answers={"materiality": "Declared policy."},
                      native=native, first_card=first_card)

    with pytest.raises(ValueError, match="exact saved card ID"):
        await session.call("revise_insight_card", {
            "card_id": "mistyped-card-id", "expected_card_version": 7,
            "changes": {"decision_guidance": "Clarified policy."}, "reason": "Owner answer",
        })
    assert session.terminal_stop is None
    assert not session.revision_attempted

    with pytest.raises(ValueError, match="expected_card_version"):
        await session.call("revise_insight_card", {
            "card_id": "saved-card", "expected_card_version": 6,
            "changes": {"decision_guidance": "Clarified policy."}, "reason": "Owner answer",
        })
    assert session.terminal_stop is None
    assert not session.revision_attempted

    with pytest.raises(ValueError, match="requires changes and reason"):
        await session.call("revise_insight_card", {
            "card_id": "saved-card", "expected_card_version": 7, "reason": "Owner answer",
        })
    assert session.terminal_stop is None
    assert not session.revision_attempted

    result = await session.call("revise_insight_card", {
        "card_id": "saved-card", "expected_card_version": 7,
        "changes": {"decision_guidance": "Clarified policy."}, "reason": "Owner answer",
    })
    assert result["card"]["id"] == "saved-card"
    assert result["card"]["version"] == 8
    assert native.card["version"] == 8
    assert session.revision_verified


async def test_changed_saved_card_and_unresolved_second_turn_are_terminal_stops():
    first_card = {"id": "saved-card", "version": 2, "status": "draft"}
    native = FakeNative(first_card)
    session = episode(stage="second", owner_answers={"materiality": "Declared policy."},
                      native=native, first_card=first_card)
    native.card["version"] = 3
    with pytest.raises(ValueError, match="saved card changed outside"):
        await session.call("revise_insight_card", {
            "card_id": "saved-card", "expected_card_version": 2,
            "changes": {"decision_guidance": "Policy."}, "reason": "Owner answer",
        })
    assert session.terminal_stop is not None
    assert [name for name, _ in native.calls] == ["get_insight_card"]

    unresolved = episode(stage="second", owner_answers={"materiality": "Declared policy."})
    with pytest.raises(ValueError, match="second author turn remains unresolved"):
        await unresolved.call("finish_setup", {
            "card_ids": [], "message": "Still awaiting clarification.",
            "unresolved": ["A material policy question remains."],
        })
    assert unresolved.setup is None
    with pytest.raises(ValueError, match="cohort stopped"):
        await unresolved.call("save_working_notes", {"notes": "No retry."})


def test_owner_handoff_limits_cover_all_charged_invocation_types():
    assert trial.OWNER_HANDOFF_PROTOCOL == "owner-handoff-v1"
    assert trial.OWNER_HANDOFF_LIMITS == {
        "codex_invocations": 8,
        "author_tools_per_turn": 24,
        "author_seconds_per_turn": 240,
        "review_tools": 2,
        "review_seconds": 90,
        "report_tools": 12,
        "report_seconds": 180,
        "jev_attempts": 2,
        "between_invocation_input_stop": 1_200_000,
        "between_invocation_uncached_stop": 180_000,
    }


async def test_missing_owner_handoff_flag_keeps_legacy_protocol_defaults(monkeypatch, tmp_path):
    class PreflightNative:
        async def call_tool(self, name, args):
            raise RuntimeError("offline preflight sentinel")

    @asynccontextmanager
    async def fake_native_context(*args, **kwargs):
        yield PreflightNative(), "installed skill"

    async def fake_pinned_codex(path):
        return {"path": "/offline/codex", "version": "codex-cli 0.162.0-alpha.2",
                "sha256": "c" * 64}

    monkeypatch.setattr(trial, "verify_binary", lambda path: {"binary_sha256": "b" * 64})
    monkeypatch.setattr(trial, "pinned_codex", fake_pinned_codex)
    monkeypatch.setattr(trial, "native_context", fake_native_context)
    args = SimpleNamespace(binary="/offline/signalweave", codex_executable="codex",
                           output=str(tmp_path / "legacy"), key_file="/offline/key",
                           prior_trace=None, run=False)

    report = await trial.run_owner_workflow(args)
    assert report["protocol"] == "owner-workflow-v1"
    assert report["limits"]["codex_invocations"] == 6
    assert report["limits"]["between_invocation_input_stop"] == 600_000
    assert report["limits"]["between_invocation_uncached_stop"] == 100_000
    assert report["agent_invocations_started"] == 0
    assert report["preflight_only"] is True


class FakeRunnerNative:
    def __init__(self):
        self.card = None
        self.revisions = []
        self.evaluations = []
        self.instructions = "Offline fake native instructions."
        self.tools = [
            SimpleNamespace(name=name, description="offline fake", inputSchema={"type": "object"})
            for name in ("get_signalweave_guide", "bootstrap_insight_card", "get_insight_card",
                         "revise_insight_card", "approve_insight_card", "evaluate_insight_card",
                         "get_decision_receipt")
        ]

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, args):
        if name == "get_insight_card":
            assert self.card is not None
            return [], deepcopy(self.card)
        if name == "bootstrap_insight_card":
            self.card = {
                "id": "handoff-card-1", "title": "Dispatch service check",
                "what_to_watch": "Use the declared Delivery service source.",
                "why_watch": "The owner needs a recurring dispatch readout.",
                "decision_guidance": "Draft policy awaiting owner answers.",
                "version": 1, "status": "draft",
            }
            return [], {"card": deepcopy(self.card)}
        if name == "revise_insight_card":
            assert args["card_id"] == self.card["id"]
            assert args["expected_card_version"] == self.card["version"]
            self.revisions.append(deepcopy(args))
            self.card.update(args.get("changes", {}))
            self.card["version"] += 1
            return [], {"card": deepcopy(self.card), "approval_required": True}
        if name == "approve_insight_card":
            self.card["status"] = "approved"
            return [], {"card": deepcopy(self.card)}
        if name == "evaluate_insight_card":
            self.evaluations.append(deepcopy(args))
            receipt = {
                "card_id": self.card["id"],
                "card_version": self.card["version"],
                "idempotency_key": args["idempotency_key"],
                "status": "delivery_disabled",
            }
            return [], {"result": {"card_id": self.card["id"]}, "receipt": receipt}
        raise AssertionError(f"unexpected fake native call: {name}")


def install_owner_handoff_runner_fakes(monkeypatch, tmp_path, *, review_decisions=None,
                                       missing_usage_at=None):
    binary = tmp_path / "signalweave"
    codex = tmp_path / "codex"
    binary.write_text("offline native binary fingerprint")
    codex.write_text("offline pinned Codex fingerprint")
    native = FakeRunnerNative()
    invocation_order = []
    codex_options = []
    handoff_packets = []
    author_source_refs = []
    review_inputs = []
    report_notes = []
    decisions = list(review_decisions or [True, True])

    def emit_invocation(audit, label):
        index = len(invocation_order)
        invocation_order.append(label)
        request_id = -(100 + index)
        audit.emit("api.request", provider="openai", request_id=request_id,
                   transport="offline-test", model="gpt-6-luna", effort="medium")
        if index != missing_usage_at:
            audit.emit("api.response", provider="openai", request_id=request_id,
                       usage={"input_tokens": 100, "input_tokens_details": {"cached_tokens": 0},
                              "output_tokens": 10})

    async def read_same_source(session):
        assets = (await session.call("list_company_assets", {}))["assets"]
        source = assets[0]
        ref = f"{source['adapter']}|{source['resource']}"
        await session.call("read_company_asset", {"ref": ref})
        return ref

    async def fake_codex_episode(session, **kwargs):
        label = session.adapter.audit.episode
        emit_invocation(session.adapter.audit, label)
        codex_options.append({"label": label, "max_tool_calls": kwargs["max_tool_calls"],
                              "timeout_seconds": kwargs["timeout_seconds"]})
        is_treatment = session.native is not None
        if label.endswith("-first"):
            author_source_refs.append((label, await read_same_source(session)))
            glossary = await session.call("read_company_glossary", {})
            assert glossary["definitions"]["population"]
            pending = await session.call("ask_owner", {"topic": "routing"})
            assert pending["answer_status"] == "pending_owner_answer"
            assert pending["answer"] is None
            await session.call("save_working_notes", {
                "notes": "Same source notes in both arms; routing policy answer is pending.",
            })
            card_ids = []
            if is_treatment:
                created = await session.call("bootstrap_insight_card", {
                    "title": "Dispatch service check",
                })
                card_ids = [created["card"]["id"]]
            await session.call("finish_setup", {
                "card_ids": card_ids,
                "message": "The declared source is available; owner policy remains pending.",
                "unresolved": ["Which authorized destination should receive the recurring action?"],
            })
        elif label.endswith("-second"):
            packet = deepcopy(kwargs["prompt_override"])
            handoff_packets.append((label, packet))
            assert packet["owner_answers"]
            assert packet["saved_notes"] == "Same source notes in both arms; routing policy answer is pending."
            author_source_refs.append((label, await read_same_source(session)))
            answer = await session.call("ask_owner", {"topic": "routing"})
            assert answer["answer_status"] == "answered" and answer["answer"]
            await session.call("save_working_notes", {
                "notes": "Same source notes in both arms; apply the declared routing policy.",
            })
            card_ids = []
            if is_treatment:
                first = session.first_card
                revised = await session.call("revise_insight_card", {
                    "card_id": first["id"], "expected_card_version": first["version"],
                    "changes": {"decision_guidance": "Apply the declared routing policy."},
                    "reason": "Apply the supplied owner answer.",
                })
                assert revised["card"]["id"] == first["id"]
                assert revised["card"]["version"] == first["version"] + 1
                card_ids = [first["id"]]
                await session.call("request_owner_approval", {
                    "kind": "card", "id": first["id"],
                    "summary": "Review the same revised draft.",
                })
                await session.call("approve_insight_card", {"card_id": first["id"]})
            else:
                await session.call("request_owner_approval", {
                    "kind": "notes", "id": "working", "summary": "Review the saved policy notes.",
                })
            await session.call("finish_setup", {
                "card_ids": card_ids,
                "message": "The declared policy is recorded for independent review.",
                "unresolved": [],
            })
        elif label.endswith("-report"):
            report_notes.append(session.notes)
            await read_same_source(session)
            if is_treatment:
                evaluation = await session.call("evaluate_insight_card", {
                    "card_id": session.approved_card_id, "idempotency_key": session.run_key,
                })
                assert evaluation["receipt"]["card_version"] == session.approved_card_version
            await session.call("submit_analysis", {
                "outcome": "ignore", "recipients": [], "evidence_refs": [],
                "claims": [], "numeric_claims": [], "summary": "A bounded current-period report.",
            })
        else:
            raise AssertionError(f"unexpected Codex invocation: {label}")
        return {"status": "complete", "exit_code": 0, "foreign_tools": []}

    async def fake_review_owner_artifact(**kwargs):
        label = kwargs["audit"].episode
        emit_invocation(kwargs["audit"], label)
        review_inputs.append({"label": label, "owner_answers": deepcopy(kwargs["owner_answers"]),
                              "source_context": deepcopy(kwargs["source_context"]),
                              "artifact": deepcopy(kwargs["artifact"])})
        decision = decisions[len(review_inputs) - 1]
        return {"approved": decision, "reasons": [] if decision else ["synthetic rejection"],
                "synthetic": True, "human_approval": False}

    @asynccontextmanager
    async def fake_native_context(*args, **kwargs):
        yield native, "installed SignalWeave skill bytes"

    def fake_verify_binary(path):
        return {"binary_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}

    async def fake_pinned_codex(path):
        resolved = Path(path).resolve()
        return {"path": str(resolved), "version": "codex-cli 0.162.0-alpha.2",
                "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()}

    monkeypatch.setattr(trial, "native_context", fake_native_context)
    monkeypatch.setattr(trial, "verify_binary", fake_verify_binary)
    monkeypatch.setattr(trial, "pinned_codex", fake_pinned_codex)
    monkeypatch.setattr(trial, "codex_episode", fake_codex_episode)
    monkeypatch.setattr("evaluations.bootstrap_owner_review.review_owner_artifact", fake_review_owner_artifact)
    args = SimpleNamespace(binary=str(binary), codex_executable=str(codex),
                           output=str(tmp_path / "owner-handoff-output"), key_file=str(tmp_path / "key"),
                           prior_trace=None, run=True, owner_workflow=False, owner_handoff=True)
    state = SimpleNamespace(invocation_order=invocation_order, codex_options=codex_options,
                            handoff_packets=handoff_packets, author_source_refs=author_source_refs,
                            review_inputs=review_inputs, report_notes=report_notes, native=native)
    return args, state


async def test_runner_executes_full_eight_invocation_handoff_and_receipt_gate(monkeypatch, tmp_path):
    args, state = install_owner_handoff_runner_fakes(monkeypatch, tmp_path)
    report = await trial.run_owner_workflow(args)

    assert "failure" not in report
    assert report["protocol"] == "owner-handoff-v1"
    assert report["pair_status"] == "both_reports_complete"
    assert state.invocation_order == [
        "baseline-owner-handoff-first", "signalweave-owner-handoff-first",
        "baseline-owner-handoff-second", "signalweave-owner-handoff-second",
        "baseline-owner-handoff-policy-review", "signalweave-owner-handoff-policy-review",
        "baseline-owner-handoff-report", "signalweave-owner-handoff-report",
    ]
    assert report["agent_invocations_started"] == report["usage"]["responses"] == 8
    assert len(report["episodes"]) == 6
    assert [entry["stage"] for entry in report["episodes"]] == [
        "first_author", "first_author", "second_author", "second_author",
        "fresh_report", "fresh_report",
    ]
    first_entries = report["episodes"][:2]
    assert all(entry["handoff_state"] == "awaiting_owner_answers" for entry in first_entries)
    assert all(entry["setup"]["unresolved"] for entry in first_entries)
    assert all(any(item["answer_status"] == "pending" for item in entry["owner_requests"])
               for entry in first_entries)
    assert all(not any(item.get("topic") == "source_scope" for item in entry["owner_requests"])
               for entry in first_entries)
    assert first_entries[1]["first_card"]["version"] == 1

    second_entries = report["episodes"][2:4]
    assert second_entries[0]["notes"] == second_entries[1]["notes"]
    packets = [packet for _, packet in state.handoff_packets]
    assert len(packets) == 2
    assert packets[0]["owner_answers"] == packets[1]["owner_answers"]
    expected_public = public_episode(trial.clarified_development_scenario())
    assert packets[0]["owner_answers"] == expected_public["owner_answers"]
    assert set(packets[0]["owner_answers"]) == set(expected_public["owner_topics"])
    assert packets[0]["saved_notes"] == packets[1]["saved_notes"]
    assert packets[0]["owner_questions"] == packets[1]["owner_questions"]
    assert packets[0].get("saved_card") is None
    assert packets[1]["saved_card"] == {"card_id": "handoff-card-1", "version": 1}
    assert second_entries[1]["card"]["id"] == first_entries[1]["first_card"]["id"]
    assert second_entries[1]["card"]["version"] == first_entries[1]["first_card"]["version"] + 1
    assert second_entries[1]["card"]["status"] == "approved"
    assert {ref for _, ref in state.author_source_refs} == {state.author_source_refs[0][1]}
    assert len(state.author_source_refs) == 4
    assert len(state.review_inputs) == 2
    assert state.review_inputs[0]["owner_answers"] == state.review_inputs[1]["owner_answers"]
    review_source_refs = [
        {source["ref"] for source in item["source_context"]["inspected_sources"]}
        for item in state.review_inputs
    ]
    assert review_source_refs[0] == review_source_refs[1]
    assert report["common_glossary_context"]["available_to_both_first_turns"] is True
    assert report["common_glossary_context"]["response_channel_unavailable_first"] is True
    assert report["common_glossary_context"]["population_source_scope"] == expected_public["glossary"]["population"]
    assert set(report["common_glossary_context"]["owner_response_topics_supplied_on_second_turn"]) == set(expected_public["owner_topics"])
    assert set(report["owner_answer_topics_delivered"]["baseline"]) == set(expected_public["owner_topics"])
    assert set(report["owner_answer_topics_delivered"]["signalweave"]) == set(expected_public["owner_topics"])
    assert report["common_glossary_context"]["policy_decisions_withheld_until_second_turn"] == [
        "action threshold", "owner-route confirmation",
    ]
    assert "owner_policy_complete" in report["scoring_semantics"]["owner_question_topic_coverage_complete"]
    assert "independent semantic reviews" in report["scoring_semantics"]["semantic_completion_gate"].lower()
    assert state.native.revisions[0]["card_id"] == "handoff-card-1"
    assert state.native.revisions[0]["expected_card_version"] == 1
    assert state.native.card["version"] == 2 and state.native.card["status"] == "approved"
    assert state.native.evaluations == [{
        "card_id": "handoff-card-1", "idempotency_key": "owner-handoff-v1:" +
        trial.clarified_development_scenario()["public"]["periods"][0]["period_id"],
    }]
    assert report["episodes"][-1]["approved_card_execution_verified"] is True
    assert all(option["max_tool_calls"] == 24 and option["timeout_seconds"] == 240
               for option in state.codex_options if "-handoff-first" in option["label"]
               or "-handoff-second" in option["label"])
    assert all(entry["source_reads"] == 1 for entry in report["episodes"][-2:])
    for report_entry in report["episodes"][-2:]:
        assert report_entry["owner_topics_asked"] == ["routing", "routing"]
        assert set(report_entry["owner_answer_topics_delivered"]) == set(expected_public["owner_topics"])
        score = report_entry["structured_score"]
        assert score["owner_question_topic_coverage_complete"] is False
        assert "owner_policy_complete" not in score
        assert type(score["legacy_exact_including_question_coverage"]) is bool
        assert "exact" not in score
        assert "missing_owner_policy_lookup" in score["errors"]


async def test_first_rejected_review_stops_before_second_review_and_reports(monkeypatch, tmp_path):
    args, state = install_owner_handoff_runner_fakes(monkeypatch, tmp_path, review_decisions=[False, True])
    report = await trial.run_owner_workflow(args)

    assert report["pair_status"] == "incomplete"
    assert "baseline independent policy review rejected" in report["failure"]
    assert state.invocation_order == [
        "baseline-owner-handoff-first", "signalweave-owner-handoff-first",
        "baseline-owner-handoff-second", "signalweave-owner-handoff-second",
        "baseline-owner-handoff-policy-review",
    ]
    assert len(state.review_inputs) == 1
    assert len(report["episodes"]) == 4
    assert not any(entry["stage"] == "fresh_report" for entry in report["episodes"])
    assert report["agent_invocations_started"] == report["usage"]["responses"] == 5


async def test_missing_usage_stops_before_any_additional_invocation(monkeypatch, tmp_path):
    args, state = install_owner_handoff_runner_fakes(monkeypatch, tmp_path, missing_usage_at=0)
    report = await trial.run_owner_workflow(args)

    assert report["pair_status"] == "incomplete"
    assert "unknown invocation usage" in report["failure"]
    assert state.invocation_order == ["baseline-owner-handoff-first"]
    assert report["agent_invocations_started"] == 1
    assert report["usage"]["responses"] == 0
    assert len(report["episodes"]) == 1

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations.company_people import CompanyPerson
from evaluations.harbor_enterprise_world import (
    MAX_CARD_SNAPSHOT_BYTES,
    HarborEnterpriseBridge,
    HarborWorld,
)

USAGE = {"input_tokens": 31, "output_tokens": 9, "cached_input_tokens": 4}


class Audit:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append({"kind": kind, **deepcopy(fields)})

    def redact(self, value):
        return deepcopy(value)


class FakeMCP:
    def __init__(self, tools, results=None):
        self.tools = tools
        self.results = results or {}
        self.calls = []

    async def list_tools(self):
        return [SimpleNamespace(name=name, description=description, inputSchema=deepcopy(schema))
                for name, description, schema in self.tools]

    async def call_tool(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        return [], deepcopy(self.results.get(name, {"called": name, "arguments": arguments}))


def tool(name, schema=None):
    return (name, f"Actual tool {name}.", schema or {
        "type": "object", "properties": {"value": {"type": "string"}},
        "required": ["value"], "additionalProperties": False,
    })


def native_card_snapshot(target_bytes):
    card = {
        "id": "card-exact-native-snapshot",
        "version": 7,
        "status": "approved",
        "source_scope": {"adapter": "harbor_history", "resource": "query:open-tickets"},
        "provenance": {"source_ref": "source:queue", "result_ref": "result:2026-10-19"},
        "padding": "",
    }
    encoded = json.dumps(card, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    if target_bytes is not None:
        assert target_bytes >= len(encoded)
        card["padding"] = "x" * (target_bytes - len(encoded))
        assert len(json.dumps(card, ensure_ascii=False, allow_nan=False,
                              sort_keys=True).encode("utf-8")) == target_bytes
    return card


def episode(message="I reviewed the request.", *, tool_calls=0, usage=USAGE):
    return {
        "status": "complete" if usage is not None else "failed",
        "error": None if usage is not None else "unknown_usage",
        "completion_basis": "final_message",
        "final_message": message,
        "completion_usage_reports": [usage] if usage is not None else [{"input_tokens": "unknown"}],
        "tool_calls": tool_calls,
        "observed_tool_calls_including_discovery": tool_calls,
    }


async def default_runner(session, **kwargs):
    return episode()


def test_saved_world_rejects_unannounced_person_model_changes(tmp_path):
    world, _bridge, source, audit, _roles = build_world(tmp_path)
    state = world.snapshot()
    world.people["owner"].model = "gpt-6.1-sol"
    with pytest.raises(ValueError, match="different inbox or person context"):
        HarborWorld(source, world.workspace, world.inbox_root, world.people, "owner", audit, state=state)


def build_world(tmp_path, *, owner_runner=None, recipient_runner=None, state=None,
                native=None, callbacks=None, advance_callback=None, register_query_callback=None,
                confirm_snapshot_callback=None, observation_context_callback=None,
                max_tool_calls=256, max_messages=64, max_attachments=96):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    inbox_root = tmp_path / "inboxes"
    inbox_root.mkdir(mode=0o700)
    role_audits = {"owner": Audit(), "recipient": Audit()}
    people = {}
    for key, runner, brief in (
        ("owner", owner_runner, "Business owner who can explain and consent to displayed policy."),
        ("recipient", recipient_runner, "Operations colleague who reviews only messages and delivered files."),
    ):
        inbox = inbox_root / key
        inbox.mkdir(mode=0o700)
        people[key] = CompanyPerson(
            role_brief=brief,
            business_knowledge="Use only caller-supplied business facts and your own conversation.",
            known_unknowns="The current reporting period may be unspecified.",
            authority="You may clarify or consent to the exact displayed policy; you cannot change native status or perform work.",
            inbox_root=inbox,
            audit=role_audits[key],
            episode_runner=runner or default_runner,
            max_attachments=max_attachments,
        )
    source = FakeMCP([tool("list_assets"), tool("query_readonly")])
    world_audit = Audit()
    world = HarborWorld(
        source, workspace, inbox_root, people, "owner", world_audit, native,
        state=state, callback_tools=callbacks,
        advance_callback=advance_callback,
        register_query_callback=register_query_callback,
        confirm_snapshot_callback=confirm_snapshot_callback,
        observation_context_callback=observation_context_callback,
        max_tool_calls=max_tool_calls, max_messages=max_messages,
    )
    return world, HarborEnterpriseBridge(world), source, world_audit, role_audits


@pytest.mark.asyncio
async def test_actual_source_and_native_tools_keep_their_contracts_and_routes(tmp_path):
    source = FakeMCP([tool("query_readonly", {
        "type": "object", "properties": {"sql": {"type": "string"}},
        "required": ["sql"], "additionalProperties": False,
    })], {"query_readonly": {"rows": [["raw", 17]]}})
    native = FakeMCP([tool("approve_insight_card", {
        "type": "object", "properties": {"card_id": {"type": "string"},
                                             "version": {"type": "integer"}},
        "required": ["card_id", "version"], "additionalProperties": False,
    })], {"approve_insight_card": {"status": "approved", "version": 3}})
    world, bridge, _, _, _ = build_world(tmp_path, native=native)
    world.source = source
    world.native = native
    world.workspace_actor = None
    bridge.base = None

    specs = await bridge.specs()
    by_name = {spec["name"]: spec for spec in specs}
    assert by_name["company_query_readonly"]["parameters"] == source.tools[0][2]
    assert by_name["approve_insight_card"]["parameters"] == native.tools[0][2]
    query_args = {"sql": "SELECT 1 AS current_observation"}
    actual = await bridge.call("company_query_readonly", query_args)
    approved = await bridge.call("approve_insight_card", {"card_id": "native-card", "version": 3})

    assert source.calls == [("query_readonly", query_args)]
    assert native.calls == [("approve_insight_card", {"card_id": "native-card", "version": 3})]
    assert actual["rows"] == [["raw", 17]] and "_caller_artifact" in actual
    assert approved["status"] == "approved"
    saved = list((world.workspace / "tool-responses").glob("response-*.json"))
    assert len(saved) == 2
    assert {json.loads(path.read_text())["name"] for path in saved} == {
        "company_query_readonly", "approve_insight_card"}


@pytest.mark.asyncio
async def test_owner_sees_exact_saved_card_and_natural_reply_never_approves(tmp_path):
    prompts = []
    replies = iter((
        "That proposed threshold conflicts with our stated policy; I don't consent to it.",
        "This displayed policy matches what I meant. I consent to this exact version and source scope.",
    ))

    async def owner_runner(session, **kwargs):
        prompts.append(kwargs["prompt_override"])
        kwargs["audit"].emit("episode.completion", usage=USAGE)
        result = episode(next(replies), tool_calls=0)
        result["private_cli_raw_metadata"] = {"prompt_override": deepcopy(kwargs["prompt_override"])}
        return result

    card = {"id": "card-actual-91", "version": 4, "status": "draft",
            "policy": {"review": "strict and source-specific"},
            "sources": [{"adapter": "harbor_history", "resource": "actual_source"}]}
    native = FakeMCP([tool("get_insight_card"), tool("approve_insight_card")])
    native.results["get_insight_card"] = card

    async def confirm(card_id):
        return (await native.call_tool("get_insight_card", {"card_id": card_id}))[1]

    world, bridge, _, _, role_audits = build_world(
        tmp_path, owner_runner=owner_runner, native=native, confirm_snapshot_callback=confirm)
    first = await bridge.call("ask_owner", {"question": "What policy should this proposal follow?"})
    rejected = await bridge.call("confirm_snapshot", {
        "card_id": card["id"], "question": "Please review this saved card and tell me what you agree with."})
    consented = await bridge.call("confirm_snapshot", {
        "card_id": card["id"], "question": "Please review the revised saved card and tell me your view."})

    assert set(first) == {"status", "person_key", "final_message", "error", "attachment_reads"}
    assert "private_cli_raw_metadata" not in json.dumps(first)
    assert "business_knowledge" not in json.dumps(first)
    assert first["final_message"] == "That proposed threshold conflicts with our stated policy; I don't consent to it."
    assert set(rejected["reply"]) == set(consented["reply"]) == set(first)
    assert rejected["displayed_native_card"] == card and consented["displayed_native_card"] == card
    assert rejected["snapshot_review_mode"] == consented["snapshot_review_mode"] == "inline"
    assert rejected["snapshot_sha256"] == consented["snapshot_sha256"] == hashlib.sha256(
        json.dumps(card, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert not world.people["owner"].session.manifest
    assert "Exact saved native card returned by the caller:" in prompts[1]["incoming"]["message"]
    assert json.dumps(card, ensure_ascii=False, sort_keys=True) in prompts[1]["incoming"]["message"]
    assert prompts[1]["incoming"]["message"].endswith(json.dumps(card, ensure_ascii=False, sort_keys=True))
    assert prompts[2]["prior_conversation"][-1]["text"] == rejected["reply"]["final_message"]
    assert native.calls == [("get_insight_card", {"card_id": card["id"]})] * 2
    assert not any(name == "approve_insight_card" for name, _ in native.calls)
    assert role_audits["owner"].events
    assert len(world.state["person_replies"]) == 3
    assert "episode" in world.state["person_replies"][0]
    assert world.state["person_replies"][0]["final_message"] == first["final_message"]
    assert world.state["person_replies"][0]["episode"]["private_cli_raw_metadata"]
    world_reply_event = next(event for event in world.audit.events if event["kind"] == "company_person.reply")
    assert world_reply_event["person_record"] == world.state["person_replies"][0]
    assert world_reply_event["person_record"]["episode"]["private_cli_raw_metadata"]


@pytest.mark.asyncio
async def test_large_snapshot_is_exactly_delivered_logged_and_restored_without_autoapproval(tmp_path):
    cards = [native_card_snapshot(12_000), native_card_snapshot(12_100)]
    cards[1]["version"] = 8
    expected_bytes = [
        json.dumps(card, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
        for card in cards
    ]
    reviewed = []
    current_card = {"value": cards[0]}

    async def owner_runner(session, **kwargs):
        prompt = kwargs["prompt_override"]
        assert "Please use read_delivered_attachment to inspect this exact JSON file" in prompt["incoming"]["message"]
        attachment_names = (await session.specs())[0]["parameters"]["properties"]["attachment"]["enum"]
        attachment_name = next(name for name in attachment_names if name.endswith(
            hashlib.sha256(expected_bytes[len(reviewed)]).hexdigest() + ".json"))
        read = await session.call("read_delivered_attachment", {"attachment": attachment_name})
        assert read["text"].encode("utf-8") == expected_bytes[len(reviewed)]
        reviewed.append((attachment_name, read))
        return episode("I inspected the exact snapshot and do not consent to this proposal.")

    native = FakeMCP([tool("get_insight_card"), tool("approve_insight_card")])

    async def confirm(card_id):
        native.results["get_insight_card"] = current_card["value"]
        return (await native.call_tool("get_insight_card", {"card_id": card_id}))[1]

    world, bridge, _, audit, _ = build_world(
        tmp_path, owner_runner=owner_runner, native=native, confirm_snapshot_callback=confirm)
    first = await bridge.call("confirm_snapshot", {
        "card_id": "card-exact-native-snapshot", "question": "Please review the exact saved card."})

    assert first["snapshot_review_mode"] == "attachment"
    assert first["snapshot_bytes"] == len(expected_bytes[0])
    first_hash = hashlib.sha256(expected_bytes[0]).hexdigest()
    first_name = f"native-card-snapshot-{first_hash}.json"
    first_path = world.people["owner"].session.inbox / first_name
    assert first["snapshot_sha256"] == first_hash
    assert first["snapshot_attachment"] == {
        "attachment": first_name, "bytes": len(expected_bytes[0]), "sha256": first_hash}
    assert first_path.read_bytes() == expected_bytes[0]
    assert first_path.stat().st_mode & 0o222 == 0
    assert first["reply"]["final_message"].endswith("do not consent to this proposal.")
    assert first["reply"]["attachment_reads"] == [{
        "attachment": first_name, "bytes": len(expected_bytes[0]), "sha256": first_hash}]
    first_operation = world.state["operations"][-1]
    assert first_operation["displayed_native_card"] == cards[0]
    assert first_operation["snapshot_sha256"] == first_hash
    assert first_operation["attachment_reads"] == first["reply"]["attachment_reads"]
    review_audit = next(event for event in audit.events if event["kind"] == "owner_snapshot_review")
    assert review_audit["snapshot_sha256"] == first_hash
    assert review_audit["attachment"] == first["snapshot_attachment"]
    assert review_audit["attachment_reads"] == first["reply"]["attachment_reads"]
    assert reviewed[0][1]["sha256"] == first_hash

    saved = world.snapshot()
    inbox_root = world.inbox_root
    restored_people = {}
    for key in ("owner", "recipient"):
        person = world.people[key]
        restored_people[key] = CompanyPerson(
            role_brief=person.context["role_brief"],
            business_knowledge=person.context["business_knowledge"],
            known_unknowns=person.context["known_unknowns"],
            authority=person.context["authority"],
            inbox_root=inbox_root / key,
            audit=Audit(),
            episode_runner=owner_runner if key == "owner" else default_runner,
        )
    restored = HarborWorld(
        world.source, world.workspace, inbox_root, restored_people, "owner", Audit(),
        native=native, confirm_snapshot_callback=confirm, state=saved,
    )
    restored_owner = restored.people["owner"]
    assert first_name in restored_owner.session.manifest
    assert restored_owner.attachment_delivery_ledger == [first["snapshot_attachment"]]
    assert restored_owner.attachment_read_ledger == [first["reply"]["attachment_reads"][0]]

    current_card["value"] = cards[1]
    second = await HarborEnterpriseBridge(restored).call("confirm_snapshot", {
        "card_id": "card-exact-native-snapshot", "question": "Please review the changed saved card."})
    second_hash = hashlib.sha256(expected_bytes[1]).hexdigest()
    second_name = f"native-card-snapshot-{second_hash}.json"
    assert second_hash != first_hash
    assert second["snapshot_attachment"]["attachment"] == second_name
    assert second["snapshot_attachment"]["sha256"] == second_hash
    assert (restored_owner.session.inbox / first_name).read_bytes() == expected_bytes[0]
    assert (restored_owner.session.inbox / second_name).read_bytes() == expected_bytes[1]
    assert len(restored_owner.attachment_delivery_ledger) == 2
    assert second["reply"]["attachment_reads"] == [{
        "attachment": second_name, "bytes": len(expected_bytes[1]), "sha256": second_hash}]
    assert reviewed[1][1]["sha256"] == second_hash
    assert native.calls == [
        ("get_insight_card", {"card_id": "card-exact-native-snapshot"}),
        ("get_insight_card", {"card_id": "card-exact-native-snapshot"}),
    ]
    assert not any(name == "approve_insight_card" for name, _ in native.calls)


@pytest.mark.asyncio
async def test_snapshot_at_attachment_limit_is_reviewable_without_truncation(tmp_path):
    card = native_card_snapshot(MAX_CARD_SNAPSHOT_BYTES)
    expected = json.dumps(card, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    assert len(expected) == MAX_CARD_SNAPSHOT_BYTES
    native = FakeMCP([tool("get_insight_card"), tool("approve_insight_card")])
    native.results["get_insight_card"] = card
    reviewed = []

    async def owner_runner(session, **kwargs):
        attachment_name = (await session.specs())[0]["parameters"]["properties"]["attachment"]["enum"][0]
        result = await session.call("read_delivered_attachment", {"attachment": attachment_name})
        reviewed.append(result)
        return episode("I reviewed the complete attachment and do not consent.")

    async def confirm(card_id):
        return (await native.call_tool("get_insight_card", {"card_id": card_id}))[1]

    world, bridge, _, _, _ = build_world(
        tmp_path, owner_runner=owner_runner, native=native, confirm_snapshot_callback=confirm)
    result = await bridge.call("confirm_snapshot", {
        "card_id": card["id"], "question": "Please inspect the exact saved snapshot."})

    assert result["snapshot_bytes"] == MAX_CARD_SNAPSHOT_BYTES
    assert reviewed[0]["text"].encode("utf-8") == expected
    assert reviewed[0]["sha256"] == result["snapshot_sha256"]
    assert result["reply"]["attachment_reads"] == [{
        "attachment": reviewed[0]["attachment"],
        "bytes": MAX_CARD_SNAPSHOT_BYTES,
        "sha256": result["snapshot_sha256"],
    }]
    assert native.calls == [("get_insight_card", {"card_id": card["id"]})]


@pytest.mark.asyncio
async def test_oversized_snapshot_and_unbounded_review_prompt_fail_before_delivery(tmp_path):
    oversized = native_card_snapshot(MAX_CARD_SNAPSHOT_BYTES + 1)
    native = FakeMCP([tool("get_insight_card"), tool("approve_insight_card")])
    native.results["get_insight_card"] = oversized
    callback_calls = []

    async def confirm(card_id):
        callback_calls.append(card_id)
        return (await native.call_tool("get_insight_card", {"card_id": card_id}))[1]

    world, bridge, _, audit, _ = build_world(
        tmp_path, native=native, confirm_snapshot_callback=confirm)
    with pytest.raises(ValueError, match=f"exceeds the {MAX_CARD_SNAPSHOT_BYTES}-byte review limit"):
        await bridge.call("confirm_snapshot", {
            "card_id": oversized["id"], "question": "Review this exact snapshot."})

    assert callback_calls == [oversized["id"]]
    assert world.people["owner"].session.manifest == {}
    assert list(world.people["owner"].session.inbox.iterdir()) == []
    assert world.state["person_replies"] == []
    assert not any(event["kind"] == "owner_snapshot_review" for event in audit.events)
    assert native.calls == [("get_insight_card", {"card_id": oversized["id"]})]
    assert not any(name == "approve_insight_card" for name, _ in native.calls)


@pytest.mark.asyncio
async def test_snapshot_question_bounds_fail_without_fetching_or_delivering(tmp_path):
    callback_calls = []

    async def confirm(card_id):
        callback_calls.append(card_id)
        return {"id": card_id, "version": 1}

    world, bridge, _, _, _ = build_world(tmp_path, confirm_snapshot_callback=confirm)
    with pytest.raises(ValueError, match="question must be non-empty text"):
        await bridge.call("confirm_snapshot", {"card_id": "card-small", "question": "q" * 8_001})

    assert callback_calls == []
    assert world.people["owner"].session.manifest == {}
    assert world.state["person_replies"] == []

    # A valid question can still leave too little room for the attachment instructions.
    card = native_card_snapshot(12_000)

    async def confirm_large(_card_id):
        return card

    world.confirm_snapshot_callback = confirm_large
    with pytest.raises(ValueError, match="leaves no room for bounded exact-snapshot review instructions"):
        await HarborEnterpriseBridge(world).call("confirm_snapshot", {
            "card_id": card["id"], "question": "q" * (MAX_CARD_SNAPSHOT_BYTES // 32)})
    assert world.people["owner"].session.manifest == {}
    assert list(world.people["owner"].session.inbox.iterdir()) == []
    assert world.state["person_replies"] == []


@pytest.mark.asyncio
async def test_messages_copy_exact_files_and_recipient_context_resumes_without_leakage(tmp_path):
    prompts = []
    bytes_by_name = {
        "current.csv": b"period,value\r\nweek-1,7\r\n",
        "next.csv": "period,value\nweek-2,11 — exact\n".encode(),
        "not-delivered.csv": b"private file that must remain unavailable\n",
    }

    async def recipient_runner(session, **kwargs):
        prompt = kwargs["prompt_override"]
        prompts.append(prompt)
        kwargs["audit"].emit("episode.completion", usage=USAGE)
        allowed = (await session.specs())[0]["parameters"]["properties"]["attachment"]["enum"]
        expected_names = (["message-000001/1-current.csv"] if len(prompts) == 1 else
                          ["message-000001/1-current.csv", "message-000002/1-next.csv"]
                          if len(prompts) == 2 else
                          ["message-000001/1-current.csv", "message-000002/1-next.csv",
                           "message-000003/1-next.csv"])
        assert allowed == expected_names
        latest = expected_names[-1]
        read = await session.call("read_delivered_attachment", {"attachment": latest})
        exact = bytes_by_name["current.csv"] if "current.csv" in latest else bytes_by_name["next.csv"]
        assert read["text"].encode() == exact
        assert read["sha256"] == hashlib.sha256(exact).hexdigest()
        with pytest.raises(ValueError, match="not delivered"):
            await session.call("read_delivered_attachment", {"attachment": "not-delivered.csv"})
        return episode(f"I reviewed {Path(latest).name}; the supplied file does not state the period end.",
                       tool_calls=1)

    world, bridge, _, _, _ = build_world(tmp_path, recipient_runner=recipient_runner)
    for name, content in bytes_by_name.items():
        (world.workspace / name).write_bytes(content)
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in bytes_by_name.items()}

    sent1 = await bridge.call("send_message", {"to": "recipient", "body": "Please review this first extract.",
                                                "workspace_files": ["current.csv"], "source_refs": []})
    first = await bridge.call("read_inbox", {"to": "recipient"})
    sent2 = await bridge.call("send_message", {"to": "recipient", "body": "Here is the next extract.",
                                                "workspace_files": ["next.csv"], "source_refs": []})
    second = await bridge.call("read_inbox", {"to": "recipient"})

    assert set(first["replies"][0]["reply"]) == {
        "status", "person_key", "final_message", "error", "attachment_reads"}
    assert first["replies"][0]["reply"]["status"] == "complete"
    assert second["replies"][0]["reply"]["final_message"].endswith("does not state the period end.")
    assert prompts[1]["prior_conversation"] == [
        {"speaker": "analyst", "text": "Please review this first extract."},
        {"speaker": "person", "text": first["replies"][0]["reply"]["final_message"]},
    ]
    assert "not-delivered.csv" not in json.dumps(prompts)
    assert "future" not in json.dumps(prompts).lower()
    for sent, name in ((sent1, "current.csv"), (sent2, "next.csv")):
        attachment = sent["attachments"][0]
        copied = Path(attachment["recipient_path"])
        assert copied.read_bytes() == bytes_by_name[name]
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == hashes[name]
        assert attachment["sha256"] == hashes[name]
    assert [item["attachment_reads"][0]["sha256"] for item in world.state["person_replies"]] == [
        hashes["current.csv"], hashes["next.csv"]]
    assert all("episode" in item and item["known_usage"] for item in world.state["person_replies"])

    saved = world.snapshot()
    restored_prompts = []

    async def resumed_runner(session, **kwargs):
        restored_prompts.append(kwargs["prompt_override"])
        return episode("I have the earlier context and the new file.")

    inbox_root = world.inbox_root
    people = {}
    for key, runner in (("owner", None), ("recipient", resumed_runner)):
        inbox = inbox_root / key
        people[key] = CompanyPerson(
            role_brief=world.people[key].context["role_brief"],
            business_knowledge=world.people[key].context["business_knowledge"],
            known_unknowns=world.people[key].context["known_unknowns"],
            authority=world.people[key].context["authority"], inbox_root=inbox,
            audit=Audit(), episode_runner=runner or default_runner)
    resumed = HarborWorld(world.source, world.workspace, inbox_root, people, "owner", Audit(), state=saved)
    resumed_bridge = HarborEnterpriseBridge(resumed)
    await resumed_bridge.call("send_message", {"to": "recipient", "body": "One more file for your review.",
                                                 "workspace_files": ["next.csv"], "source_refs": []})
    feedback = await resumed_bridge.call("read_inbox", {"to": "recipient"})
    assert feedback["replies"][0]["reply"]["status"] == "complete"
    assert restored_prompts[0]["prior_conversation"] == prompts[1]["prior_conversation"] + [
        {"speaker": "analyst", "text": "Here is the next extract."},
        {"speaker": "person", "text": second["replies"][0]["reply"]["final_message"]},
    ]
    assert people["recipient"].reply_calls == 3
    assert people["recipient"].tool_calls == 2


@pytest.mark.asyncio
async def test_world_delivers_more_than_twenty_files_without_triggering_person_opinions(tmp_path):
    world, bridge, _, _, _ = build_world(tmp_path)
    for index in range(28):
        filename = f"support-{index + 1:02}.csv"
        (world.workspace / filename).write_bytes(f"day,{index + 1}\n".encode())
        result = await bridge.call("send_message", {
            "to": "recipient", "body": f"Here is day {index + 1} support.",
            "workspace_files": [filename], "source_refs": [],
        })
        assert result["delivered"] is True

    recipient = world.people["recipient"]
    assert len(recipient.session.manifest) == 28
    assert len(recipient.attachment_delivery_ledger) == 28
    assert world.state["person_replies"] == []
    assert recipient.reply_calls == 0 and recipient.records == []
    assert len(world.state["messages"]) == 28


@pytest.mark.asyncio
async def test_message_retains_actual_source_day_context_without_rewriting_claim_or_exposing_context(tmp_path):
    context = {"source_cutoff": "2026-10-18T23:59:00Z", "day": 7}
    callback_calls = []
    observed_prompts = []

    def observe_context():
        callback_calls.append("send_message")
        return context

    async def recipient_runner(session, **kwargs):
        observed_prompts.append(kwargs["prompt_override"])
        return episode("I received the note.")

    world, bridge, _, _, _ = build_world(
        tmp_path, recipient_runner=recipient_runner,
        observation_context_callback=observe_context,
    )
    claimed_message = "This report is current through 2040-01-01; please review it."
    sent = await bridge.call("send_message", {
        "to": "recipient", "body": claimed_message,
        "workspace_files": [], "source_refs": [],
    })

    stored = world.state["messages"][0]
    assert stored["body"] == claimed_message
    assert stored["observation_context"] == context
    assert callback_calls == ["send_message"]
    assert "observation_context" not in sent

    inbox = await bridge.call("read_inbox", {"to": "recipient"})
    assert inbox["messages"][0]["body"] == claimed_message
    assert "observation_context" not in inbox["messages"][0]
    assert observed_prompts[0]["incoming"]["message"] == claimed_message
    assert context["source_cutoff"] not in json.dumps(observed_prompts)
    assert context["source_cutoff"] not in json.dumps(inbox)


@pytest.mark.asyncio
async def test_optional_callbacks_are_opaque_audited_and_finish_does_not_gate(tmp_path):
    calls = []

    async def run_checks(arguments):
        calls.append(("run_checks_until_review", arguments))
        return {"opaque": "quiet-day observations only"}

    async def register_recurring(arguments):
        calls.append(("register_recurring_procedure", arguments))
        return {"opaque": "caller-native-registration-result"}

    async def advance():
        calls.append(("advance", {}))
        return {"next_source_state": "caller-selected-current-cutoff"}

    callbacks = {
        "run_checks_until_review": {
            "callback": run_checks, "description": "Caller-owned bounded checks until review.",
            "parameters": {"type": "object", "properties": {"until": {"type": "string"}},
                           "required": ["until"], "additionalProperties": False},
        },
        "register_recurring_procedure": {
            "callback": register_recurring, "description": "Caller-owned native recurring registration.",
            "parameters": {"type": "object", "properties": {"manifest": {"type": "string"}},
                           "required": ["manifest"], "additionalProperties": False},
        },
    }
    world, bridge, _, _, _ = build_world(tmp_path, callbacks=callbacks, advance_callback=advance)
    specs = {item["name"]: item for item in await bridge.specs()}
    assert specs["run_checks_until_review"]["parameters"] == callbacks["run_checks_until_review"]["parameters"]
    assert specs["register_recurring_procedure"]["parameters"] == callbacks["register_recurring_procedure"]["parameters"]

    args = {"until": "an actual analyst-requested review point"}
    checks = await bridge.call("run_checks_until_review", args)
    registration = await bridge.call("register_recurring_procedure", {"manifest": "agent-owned.json"})
    advanced = await bridge.call("finish_day", {})

    assert checks == {"opaque": "quiet-day observations only"}
    assert registration == {"opaque": "caller-native-registration-result"}
    assert advanced == {"next_source_state": "caller-selected-current-cutoff"}
    assert calls == [
        ("run_checks_until_review", args),
        ("register_recurring_procedure", {"manifest": "agent-owned.json"}),
        ("advance", {}),
    ]
    summary = world.snapshot()["day_summaries"][0]
    assert summary["messages_since_prior_advance"] == 0
    assert summary["omissions"] == ["no_message_delivered"]
    assert world.state["operations"][0]["result"] == checks


@pytest.mark.asyncio
async def test_register_query_passes_workspace_file_and_records_unchanged_bytes(tmp_path):
    observed = []

    async def register(path):
        observed.append(path)
        return {"native_registration": "actual-caller-result"}

    world, bridge, _, _, _ = build_world(tmp_path, register_query_callback=register)
    manifest = world.workspace / "proposal.json"
    manifest.write_bytes(b'{"resource":"caller-authored"}\r\n')
    original = manifest.read_bytes()
    result = await bridge.call("register_query", {"manifest_file": "proposal.json"})

    assert observed == [manifest]
    assert manifest.read_bytes() == original
    assert result["unchanged"] is True
    assert result["sha256_before"] == result["sha256_after"] == hashlib.sha256(original).hexdigest()
    with pytest.raises(ValueError, match="inside the current workspace"):
        await bridge.call("register_query", {"manifest_file": "../private.json"})


@pytest.mark.asyncio
async def test_unknown_usage_is_retained_and_inbox_reply_is_never_retried(tmp_path):
    count = 0

    async def recipient_runner(session, **kwargs):
        nonlocal count
        count += 1
        kwargs["audit"].emit("episode.completion", usage={"input_tokens": "unknown"})
        return episode("The reporting period is unclear.", usage=None)

    world, bridge, _, _, _ = build_world(tmp_path, recipient_runner=recipient_runner)
    (world.workspace / "evidence.txt").write_text("Only the delivered file.", encoding="utf-8")
    await bridge.call("send_message", {"to": "recipient", "body": "Please review.",
                                        "workspace_files": ["evidence.txt"], "source_refs": []})
    failed = await bridge.call("read_inbox", {"to": "recipient"})
    second = await bridge.call("read_inbox", {"to": "recipient"})

    public_reply = failed["replies"][0]["reply"]
    assert set(public_reply) == {"status", "person_key", "final_message", "error", "attachment_reads"}
    assert public_reply["status"] == "failed" and public_reply["error"] == "unknown_usage"
    assert public_reply["final_message"] == "The reporting period is unclear."
    assert second == {"messages": [], "replies": []}
    assert count == 1
    full_record = world.state["person_replies"][0]
    assert full_record["usage_status"] == "unknown"
    assert full_record["episode"]["completion_usage_reports"] == [
        {"input_tokens": "unknown"}]
    reply_event = next(event for event in world.audit.events if event["kind"] == "company_person.reply")
    assert reply_event["person_record"] == full_record
    assert world.state["feedback_reads"][0]["reply"] == public_reply


@pytest.mark.asyncio
async def test_world_caps_are_finite_and_budget_failure_is_audited(tmp_path):
    async def owner_runner(session, **kwargs):
        return episode()

    world, bridge, _, audit, _ = build_world(tmp_path, owner_runner=owner_runner, max_tool_calls=1)
    await bridge.call("ask_owner", {"question": "What can you clarify?"})
    with pytest.raises(ValueError, match="tool-call budget exhausted"):
        await bridge.call("ask_owner", {"question": "One more question?"})

    assert len(world.state["tool_events"]) == 1
    assert any(item["kind"] == "tool.budget_exhausted" for item in audit.events)
    with pytest.raises(ValueError, match="finite"):
        HarborWorld(world.source, world.workspace, world.inbox_root, world.people, "owner", audit,
                    max_tool_calls=10_000)


@pytest.mark.asyncio
@pytest.mark.parametrize("allowance,delivered_days", [(96, 16), (192, 28)])
async def test_month_of_multi_file_deliveries_uses_configured_quota_across_restart(
    tmp_path, allowance, delivered_days
):
    world, bridge, source, audit, _roles = build_world(
        tmp_path, max_attachments=allowance
    )
    names = [f"evidence-{index}.csv" for index in range(6)]
    for day in range(delivered_days):
        for index, name in enumerate(names):
            (world.workspace / name).write_text(f"day,section\n{day},{index}\n")
        result = await bridge.call("send_message", {
            "to": "recipient", "body": "A bounded local review package.",
            "workspace_files": names, "source_refs": [],
        })
        assert result["delivered"] is True
        if day == 15:
            saved = world.snapshot()
            people = {key: CompanyPerson(
                **person.context, inbox_root=person.session.inbox,
                audit=Audit(), episode_runner=default_runner,
                max_attachments=allowance,
            ) for key, person in world.people.items()}
            world = HarborWorld(source, world.workspace, world.inbox_root,
                                people, "owner", audit, state=saved)
            bridge = HarborEnterpriseBridge(world)

    recipient = world.people["recipient"]
    assert len(recipient.session.manifest) == delivered_days * 6
    assert recipient.reply_calls == 0
    assert recipient.attachment_read_ledger == []
    for name, (size, digest) in recipient.session.manifest.items():
        raw = (recipient.session.inbox / name).read_bytes()
        assert len(raw) == size
        assert hashlib.sha256(raw).hexdigest() == digest
    if allowance == 96:
        with pytest.raises(ValueError, match="cumulative attachment limit"):
            await bridge.call("send_message", {
                "to": "recipient", "body": "One more package.",
                "workspace_files": names, "source_refs": [],
            })
        assert len(world.state["messages"]) == 16


def test_owner_snapshot_delivery_uses_configured_quota_and_preserves_limit(tmp_path):
    world, _bridge, _source, _audit, _roles = build_world(tmp_path, max_attachments=97)
    owner = world.people["owner"]
    for version in range(97):
        raw = json.dumps({"version": version, "definition": "An exact saved snapshot."}).encode()
        delivery = world._deliver_snapshot_attachment(
            owner, f"review-{version}.json", raw, hashlib.sha256(raw).hexdigest()
        )
        assert delivery["bytes"] == len(raw)
    assert len(owner.session.manifest) == 97
    with pytest.raises(ValueError, match="owner attachment delivery limit"):
        world._deliver_snapshot_attachment(owner, "over-limit.json", b"{}",
                                           hashlib.sha256(b"{}").hexdigest())
    assert not (owner.session.inbox / "over-limit.json").exists()
    assert owner.reply_calls == 0


@pytest.mark.parametrize("field", ["max_attachments", "max_reply_calls", "max_tool_calls"])
def test_world_restore_rejects_silent_changes_to_employee_capacity(tmp_path, field):
    world, _bridge, source, audit, _roles = build_world(tmp_path)
    saved = world.snapshot()
    person = world.people["owner"]
    setattr(person, field, getattr(person, field) + 1)
    with pytest.raises(ValueError, match="different inbox or person context"):
        HarborWorld(source, world.workspace, world.inbox_root,
                    world.people, "owner", audit, state=saved)

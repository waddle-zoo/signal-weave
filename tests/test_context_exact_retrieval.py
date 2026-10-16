"""Exact context retrieval stays bounded and subject to ordinary filters."""

from datetime import datetime, timedelta, timezone

import pytest

from signalweave.models import PrincipalContext, SourceRef
from tests.test_knowledge_mcp import content
from tests.test_knowledge_mcp import setup as make_server
from tests.test_knowledge_store import make_entry


def seed(runtime, entry_id, **kwargs):
    tenant_id = kwargs.pop("tenant_id", "a")
    resource = kwargs.pop("resource", f"{tenant_id}:sales")
    source = SourceRef(key="sales", adapter="company", resource=resource, label="Sales")
    entry = make_entry(
        entry_id, tenant_id=tenant_id, actor="analyst", sources=[source], **kwargs,
    )
    runtime.knowledge.store.append(entry, expected_revision=0)
    return entry


async def retrieve(server, entry_ids, **kwargs):
    _, packet = await server.call_tool(
        "retrieve_domain_context", {"entry_ids": entry_ids, **kwargs},
    )
    return packet


async def test_exact_id_survives_lexical_window_with_overlapping_distractors(tmp_path):
    server, runtime, _, _, judger = make_server(tmp_path)
    for index in range(311):
        seed(runtime, f"a-decoy-{index:03}", title="Needle metric", body="Needle meaning")
    target_id = "opaque target/with punctuation"
    seed(runtime, target_id, title="Needle metric", body="Needle meaning")

    _, lexical = await server.call_tool("retrieve_domain_context", {"query": target_id})
    assert lexical["entries"] == []
    packet = await retrieve(
        server, [target_id], query="needle", source_refs=["company|a:sales"], limit=1,
    )
    assert [entry["id"] for entry in packet["entries"]] == [target_id]
    assert judger.states == []
    assert runtime.card_store.get_card("repeat").status == "approved"


def test_store_treats_quoted_id_as_a_literal_value(tmp_path):
    _, runtime, _, _, _ = make_server(tmp_path)
    opaque = "x' OR 1=1 --"
    seed(runtime, opaque)
    seed(runtime, "neighbor")

    found = runtime.knowledge.store.search("a", "analyst", "", entry_ids=[opaque])
    assert [entry.id for entry in found] == [opaque]


async def test_count_limit_truncates_exact_results(tmp_path):
    server, runtime, _, _, _ = make_server(tmp_path)
    seed(runtime, "one")
    seed(runtime, "two")

    packet = await retrieve(server, ["one", "two"], limit=1)
    assert len(packet["entries"]) == 1
    assert packet["truncated"] is True


async def test_byte_budget_truncates_an_oversized_exact_entry(tmp_path):
    server, runtime, _, _, _ = make_server(tmp_path)
    seed(runtime, "large", body="x" * 3000)

    packet = await retrieve(server, ["large"], max_bytes=4096)
    assert packet["entries"] == []
    assert packet["truncated"] is True


async def test_none_keeps_ordinary_retrieval_results(tmp_path):
    server, runtime, _, _, _ = make_server(tmp_path)
    seed(runtime, "ordinary")

    _, default = await server.call_tool("retrieve_domain_context", {})
    explicit_none = await retrieve(server, None)
    assert explicit_none["entries"] == default["entries"]
    assert explicit_none["freshness"] == default["freshness"]


async def test_exact_ids_return_only_the_current_revision_and_respect_draft_visibility(tmp_path):
    server, _, _, _, _ = make_server(tmp_path)
    _, saved = await server.call_tool("save_domain_context", {"content": content()})
    entry_id = saved["id"]
    _, approved = await server.call_tool("review_domain_context", {
        "entry_id": entry_id, "expected_revision": saved["revision"],
        "action": "approve", "reason": "Owner confirmed.",
    })
    revised = content()
    revised["body"] = "The current draft has changed meaning."
    await server.call_tool("save_domain_context", {
        "content": revised, "entry_id": entry_id,
        "expected_revision": approved["revision"],
    })

    assert (await retrieve(server, [entry_id]))["entries"] == []
    visible = await retrieve(server, [entry_id], include_drafts=True)
    assert [(entry["revision"], entry["content"]["body"]) for entry in visible["entries"]] == [
        (3, "The current draft has changed meaning."),
    ]


async def test_due_exact_entry_is_returned_with_expired_freshness(tmp_path):
    server, runtime, _, _, _ = make_server(tmp_path)
    seed(runtime, "expired", review_after=datetime.now(timezone.utc) - timedelta(days=1))

    packet = await retrieve(server, ["expired"], review_due_only=True)
    assert [entry["id"] for entry in packet["entries"]] == ["expired"]
    assert packet["freshness"]["expired"] == "review_due"


async def test_tenant_private_and_retired_exact_ids_are_omitted(tmp_path):
    server, runtime, _, _, _ = make_server(tmp_path)
    seed(runtime, "foreign", tenant_id="b")
    seed(runtime, "private", readers=["someone-else"])
    seed(runtime, "retired", status="retired")

    packet = await retrieve(server, ["foreign", "private", "retired"])
    assert packet["entries"] == []


async def test_revoked_source_hides_exact_entry(tmp_path):
    server, runtime, assets, _, _ = make_server(tmp_path)
    seed(runtime, "revoked")
    assets.revoked = True

    assert (await retrieve(server, ["revoked"]))["entries"] == []


async def test_unknown_and_hidden_ids_have_the_same_empty_packet(tmp_path):
    server, runtime, _, _, _ = make_server(tmp_path)
    seed(runtime, "hidden", readers=["someone-else"])

    unknown = await retrieve(server, ["unknown-id"])
    hidden = await retrieve(server, ["hidden"])
    for packet in (unknown, hidden):
        packet.pop("captured_at")
        assert packet["entries"] == []
    assert unknown == hidden
    assert "unknown-id" not in str(unknown) and "hidden" not in str(hidden)


async def test_exact_ids_do_not_broaden_query_domain_due_or_anchor_filters(tmp_path):
    server, runtime, _, _, _ = make_server(tmp_path)
    seed(runtime, "target", title="Needle definition", body="Needle body")
    assert [entry["id"] for entry in (await retrieve(
        server, ["target"], query="needle", domain="finance",
        source_refs=["company|a:sales"],
    ))["entries"]] == ["target"]

    for filters in (
        {"query": "absent"}, {"domain": "operations"},
        {"review_due_only": True}, {"source_refs": ["company|a:other"]},
    ):
        assert (await retrieve(server, ["target"], **filters))["entries"] == []


@pytest.mark.parametrize("entry_ids", [
    [], ["id"] * 13, ["same", "same"], [" "], ["x" * 161], ["id", 3], ("id",),
])
def test_store_rejects_malformed_exact_id_lists(tmp_path, entry_ids):
    _, runtime, _, _, _ = make_server(tmp_path)
    with pytest.raises(ValueError, match="entry_ids"):
        runtime.knowledge.store.search("a", "analyst", "", entry_ids=entry_ids)


async def test_mcp_schema_exposes_bounded_optional_entry_ids(tmp_path):
    server, _, _, _, _ = make_server(tmp_path)
    tool = next(item for item in await server.list_tools() if item.name == "retrieve_domain_context")
    branches = tool.inputSchema["properties"]["entry_ids"].get("anyOf", [])
    array = next(branch for branch in branches if branch.get("type") == "array")
    assert array["minItems"] == 1 and array["maxItems"] == 12


@pytest.mark.parametrize("change", ["private", "draft"])
async def test_revision_change_during_source_authorization_is_not_returned(tmp_path, change):
    _, runtime, assets, _, _ = make_server(tmp_path)
    original = seed(runtime, "meaning")
    authorize = assets.authorize

    async def revise(source, **kwargs):
        result = await authorize(source, **kwargs)
        runtime.knowledge.store.append(original.model_copy(update={
            "revision": 2, "status": "draft",
            "content": original.content.model_copy(update={
                "reader_principal_ids": ["analyst"] if change == "private" else [],
            }),
        }), expected_revision=1)
        return result

    assets.authorize = revise
    packet = await runtime.knowledge.retrieve(
        PrincipalContext(principal_id="reader", tenant_id="a"), entry_ids=[original.id],
    )
    assert packet.entries == [] and packet.freshness == {}


async def test_later_authorization_cannot_leave_an_earlier_revoked_entry_in_packet(tmp_path):
    _, runtime, assets, _, _ = make_server(tmp_path)
    original = seed(runtime, "first")
    second = seed(runtime, "second", resource="a:other")
    authorize = assets.authorize

    async def revoke_earlier(source, **kwargs):
        result = await authorize(source, **kwargs)
        if source.resource == "a:other":
            runtime.knowledge.store.append(original.model_copy(update={
                "revision": 2, "content": original.content.model_copy(update={
                    "reader_principal_ids": ["analyst"],
                }),
            }), expected_revision=1)
        return result

    assets.authorize = revoke_earlier
    packet = await runtime.knowledge.retrieve(PrincipalContext(principal_id="reader", tenant_id="a"))
    assert [entry.id for entry in packet.entries] == [second.id]

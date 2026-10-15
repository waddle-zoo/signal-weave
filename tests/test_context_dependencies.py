"""Contract tests for opaque, source-bound card context pins.

All connectors and knowledge are synthetic. These tests exercise authorization
and identity checks only; they never inspect source data or contact a provider.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from signalweave.knowledge import KnowledgeService
from signalweave.knowledge_dependencies import ContextDependencies
from signalweave.knowledge_models import KnowledgeContent, KnowledgeEntry
from signalweave.knowledge_store import SQLiteKnowledgeStore
from signalweave.models import (
    ContextBinding,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    SourceRef,
)
from signalweave.sources import SourceRegistry

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
TENANT = "tenant-a"
OWNER = PrincipalContext(
    principal_id="owner-1", tenant_id=TENANT,
    scopes=["knowledge:write", "knowledge:share", "knowledge:review"],
)
READER = PrincipalContext(principal_id="reader-1", tenant_id=TENANT)


def make_ref(
    resource: str = "chart:net-sales", *, adapter: str = "superset",
    parameters: dict | None = None,
) -> SourceRef:
    return SourceRef(
        key="sales-source", adapter=adapter, resource=resource,
        label="Sales source", parameters=parameters or {},
    )


class AuthorizationOnlyAdapter:
    """Fake source metadata endpoint; any data or catalog access is a test bug."""

    def __init__(self, name: str = "superset", *, namespace: str | None = "workspace-a/schema-1"):
        self.name = name
        self.binding_namespace = namespace
        self.scope = "net sales after refunds"
        self.population = "posted customer orders"
        self.health = "healthy"
        self.capture_time = "2026-10-14T11:00:00Z"
        self.update_time = "2026-10-14T11:05:00Z"
        self.denied: set[tuple[str, str]] = set()
        self.authorization_calls: list[tuple[str, tuple[str, ...], dict]] = []
        self.inspect_calls = 0
        self.list_calls = 0
        self.search_calls = 0

    async def authorize(self, source, *, authorized_tenants=None):
        tenants = tuple(sorted(authorized_tenants or ()))
        self.authorization_calls.append((source.resource, tenants, dict(source.parameters)))
        if any((tenant, source.resource) in self.denied for tenant in tenants):
            return None
        if len(tenants) != 1:
            return None
        return ResourceDescriptor(
            adapter=self.name,
            resource=source.resource,
            kind="chart",
            title="Synthetic source descriptor",
            metadata={
                "captured_at": self.capture_time,
                "updated_at": self.update_time,
                "health": self.health,
            },
            contract=ResourceContract(
                tenant_id=tenants[0],
                domain="sales",
                scope=self.scope,
                population=self.population,
                grain="week",
                metric_names=["net_sales"],
                source_status=self.health,
                freshness_sla_hours=24,
            ),
        )

    async def inspect(self, _source):
        self.inspect_calls += 1
        raise AssertionError("context pinning must not fetch source data")

    async def list_resources(self):
        self.list_calls += 1
        raise AssertionError("context pinning must not scan a source catalog")

    async def search_resources(self, *_args, **_kwargs):
        self.search_calls += 1
        raise AssertionError("context pinning must not query a source catalog")


def make_services(tmp_path, adapters: list[AuthorizationOnlyAdapter] | None = None):
    sources = adapters or [AuthorizationOnlyAdapter()]
    knowledge = KnowledgeService(
        SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite3"),
        SourceRegistry(sources),
    )
    return knowledge, ContextDependencies(knowledge), sources


def add_note(
    knowledge: KnowledgeService,
    *,
    entry_id: str = "context-1",
    tenant_id: str = TENANT,
    status: str = "reviewed",
    kind: str = "definition",
    readers: list[str] | None = None,
    sources: list[SourceRef] | None = None,
    valid_from: datetime | None = NOW - timedelta(days=1),
    review_after: datetime | None = NOW + timedelta(days=30),
    body: str = "Net sales exclude refunds.",
    actor: str = "owner-1",
) -> KnowledgeEntry:
    entry = KnowledgeEntry(
        id=entry_id,
        tenant_id=tenant_id,
        revision=1,
        actor=actor,
        owner_id=actor,
        status=status,
        created_at=NOW,
        content=KnowledgeContent(
            domain="sales",
            title="Net sales definition — PRIVATE TITLE SENTINEL",
            body=body,
            kind=kind,
            sources=sources or [make_ref()],
            provenance=["PRIVATE PROVENANCE SENTINEL"],
            review_after=review_after or NOW + timedelta(days=30),
            valid_from=valid_from,
            reader_principal_ids=readers or [],
        ),
    )
    knowledge.store.append(entry, expected_revision=0)
    return entry


def assert_no_note_content(result: dict, *extra_secrets: str) -> None:
    serialized = json.dumps(result, sort_keys=True)
    for secret in (
        "Net sales definition — PRIVATE TITLE SENTINEL",
        "Net sales exclude refunds.",
        "PRIVATE PROVENANCE SENTINEL",
        *extra_secrets,
    ):
        assert secret not in serialized
    for state in result["entries"]:
        assert set(state) == {
            "entry_id", "revision", "required_for_action", "status",
        }


def append_revision(knowledge: KnowledgeService, entry: KnowledgeEntry, **updates) -> KnowledgeEntry:
    changed_content = updates.pop("content", entry.content)
    next_entry = entry.model_copy(update={
        "revision": entry.revision + 1,
        "actor": OWNER.principal_id,
        "created_at": NOW + timedelta(minutes=1),
        "content": changed_content,
        **updates,
    })
    knowledge.store.append(next_entry, expected_revision=entry.revision)
    return next_entry


def test_context_binding_validates_strict_revision_and_sha256_digests():
    binding = ContextBinding(
        entry_id="context-1", revision=1,
        content_digest="a" * 64, source_digest="b" * 64,
    )
    assert binding.required_for_action is False

    for revision in (0, -1, True, 1.0, "1"):
        with pytest.raises(ValidationError):
            ContextBinding(
                entry_id="context-1", revision=revision,
                content_digest="a" * 64, source_digest="b" * 64,
            )
    for field in ("content_digest", "source_digest"):
        for digest in ("a" * 63, "g" * 64, "A" * 64):
            values = {
                "entry_id": "context-1", "revision": 1,
                "content_digest": "a" * 64, "source_digest": "b" * 64,
            }
            values[field] = digest
            with pytest.raises(ValidationError):
                ContextBinding(**values)

    for required in (0, 1, "true"):
        with pytest.raises(ValidationError):
            ContextBinding(
                entry_id="context-1", revision=1,
                content_digest="a" * 64, source_digest="b" * 64,
                required_for_action=required,
            )


@pytest.mark.asyncio
async def test_pin_is_opaque_shared_reviewed_and_never_fetches_source_data(tmp_path):
    knowledge, dependencies, (adapter,) = make_services(tmp_path)
    add_note(knowledge)

    binding = await dependencies.pin(
        "context-1", 1, READER, required_for_action=True, now=NOW,
    )

    assert binding.entry_id == "context-1"
    assert binding.revision == 1
    assert binding.required_for_action is True
    assert re.fullmatch(r"[0-9a-f]{64}", binding.content_digest)
    assert re.fullmatch(r"[0-9a-f]{64}", binding.source_digest)
    assert "PRIVATE" not in binding.model_dump_json()
    assert adapter.authorization_calls
    assert adapter.inspect_calls == adapter.list_calls == adapter.search_calls == 0

    inspected = await dependencies.inspect([binding], READER, now=NOW)
    assert inspected["required_current"] is True
    assert inspected["entries"] == [{
        "entry_id": "context-1", "revision": 1,
        "required_for_action": True, "status": "current",
    }]
    assert_no_note_content(inspected)
    assert adapter.inspect_calls == adapter.list_calls == adapter.search_calls == 0


@pytest.mark.asyncio
async def test_pin_rejects_unreviewed_private_or_noncurrent_context(tmp_path):
    knowledge, dependencies, _ = make_services(tmp_path)
    add_note(knowledge, entry_id="draft", status="draft")
    add_note(knowledge, entry_id="private", readers=[OWNER.principal_id])
    add_note(knowledge, entry_id="due", review_after=NOW)
    add_note(knowledge, entry_id="future", valid_from=NOW + timedelta(seconds=1))

    for entry_id, principal in (
        ("draft", OWNER), ("private", OWNER), ("due", OWNER), ("future", OWNER),
    ):
        with pytest.raises((ValueError, KeyError)):
            await dependencies.pin(entry_id, 1, principal, now=NOW)


@pytest.mark.asyncio
async def test_required_pin_rejects_hypothesis_but_optional_pin_can_preserve_it(tmp_path):
    knowledge, dependencies, _ = make_services(tmp_path)
    add_note(knowledge, entry_id="hypothesis", kind="hypothesis")

    optional = await dependencies.pin(
        "hypothesis", 1, READER, required_for_action=False, now=NOW,
    )
    assert optional.required_for_action is False
    with pytest.raises(ValueError):
        await dependencies.pin(
            "hypothesis", 1, READER, required_for_action=True, now=NOW,
        )


@pytest.mark.asyncio
async def test_inspection_marks_revision_mutation_superseded_without_leaking_note(tmp_path):
    knowledge, dependencies, _ = make_services(tmp_path)
    entry = add_note(knowledge, body="ORIGINAL BODY SECRET")
    binding = await dependencies.pin(
        entry.id, entry.revision, READER, required_for_action=True, now=NOW,
    )
    append_revision(
        knowledge, entry,
        content=entry.content.model_copy(update={"body": "CHANGED BODY SECRET"}),
    )

    result = await dependencies.inspect([binding], READER, now=NOW)

    assert result["entries"][0]["status"] == "superseded"
    assert result["required_current"] is False
    assert_no_note_content(result, "ORIGINAL BODY SECRET", "CHANGED BODY SECRET")


@pytest.mark.asyncio
async def test_acl_revocation_and_source_denial_become_unavailable_without_disclosure(tmp_path):
    knowledge, dependencies, (adapter,) = make_services(tmp_path)
    entry = add_note(knowledge, body="REVOKED NOTE BODY SECRET")
    binding = await dependencies.pin(
        entry.id, entry.revision, READER, required_for_action=True, now=NOW,
    )
    private_content = entry.content.model_copy(update={
        "body": "PRIVATE REVISION SECRET",
        "reader_principal_ids": [OWNER.principal_id],
    })
    append_revision(knowledge, entry, content=private_content)

    acl_result = await dependencies.inspect([binding], READER, now=NOW)
    assert acl_result["entries"][0]["status"] == "unavailable"
    assert acl_result["required_current"] is False
    assert_no_note_content(acl_result, "REVOKED NOTE BODY SECRET", "PRIVATE REVISION SECRET")

    # A separately pinned, shared note also becomes unavailable when the
    # connector stops authorizing its exact source reference.
    add_note(knowledge, entry_id="source-revoked")
    source_binding = await dependencies.pin(
        "source-revoked", 1, READER, required_for_action=True, now=NOW,
    )
    adapter.denied.add((TENANT, "chart:net-sales"))
    source_result = await dependencies.inspect([source_binding], READER, now=NOW)
    assert source_result["entries"][0]["status"] == "unavailable"
    assert source_result["required_current"] is False
    assert_no_note_content(source_result)


@pytest.mark.asyncio
async def test_same_entry_id_in_another_tenant_cannot_satisfy_a_pin(tmp_path):
    knowledge, dependencies, _ = make_services(tmp_path)
    entry = add_note(knowledge, entry_id="shared-id", tenant_id=TENANT)
    binding = await dependencies.pin(
        entry.id, entry.revision, READER, required_for_action=True, now=NOW,
    )
    other_tenant = PrincipalContext(principal_id=READER.principal_id, tenant_id="tenant-b")
    add_note(knowledge, entry_id="shared-id", tenant_id="tenant-b")

    result = await dependencies.inspect([binding], other_tenant, now=NOW)

    assert result["entries"][0]["status"] != "current"
    assert result["required_current"] is False
    assert_no_note_content(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("rebind", ["descriptor_scope", "workspace_namespace"])
async def test_connector_meaning_or_workspace_rebind_invalidates_pin(tmp_path, rebind):
    knowledge, dependencies, (adapter,) = make_services(tmp_path)
    add_note(knowledge)
    binding = await dependencies.pin(
        "context-1", 1, READER, required_for_action=True, now=NOW,
    )
    if rebind == "descriptor_scope":
        adapter.scope = "gross sales before refunds"
    else:
        adapter.binding_namespace = "workspace-b/schema-2"

    result = await dependencies.inspect([binding], READER, now=NOW)

    assert result["entries"][0]["status"] == "source_changed"
    assert result["required_current"] is False
    assert_no_note_content(result)


@pytest.mark.asyncio
async def test_capture_update_and_health_metadata_do_not_invalidate_pin(tmp_path):
    knowledge, dependencies, (adapter,) = make_services(tmp_path)
    add_note(knowledge)
    binding = await dependencies.pin(
        "context-1", 1, READER, required_for_action=True, now=NOW,
    )
    adapter.capture_time = "2026-10-14T11:59:00Z"
    adapter.update_time = "2026-10-14T11:59:30Z"
    adapter.health = "stale"

    result = await dependencies.inspect([binding], READER, now=NOW)

    assert result["entries"][0]["status"] == "current"
    assert result["required_current"] is True


@pytest.mark.asyncio
async def test_source_parameters_are_part_of_each_pin_identity(tmp_path):
    knowledge, dependencies, _ = make_services(tmp_path)
    north = add_note(
        knowledge, entry_id="north",
        sources=[make_ref(parameters={"region": "north"})],
    )
    south = add_note(
        knowledge, entry_id="south",
        sources=[make_ref(parameters={"region": "south"})],
    )

    north_binding = await dependencies.pin(north.id, 1, READER, now=NOW)
    south_binding = await dependencies.pin(south.id, 1, READER, now=NOW)

    assert north_binding.source_digest != south_binding.source_digest


@pytest.mark.asyncio
async def test_every_source_requires_authorization_and_a_stable_namespace(tmp_path):
    first = AuthorizationOnlyAdapter("superset")
    second = AuthorizationOnlyAdapter("looker", namespace=None)
    knowledge, dependencies, _ = make_services(tmp_path, [first, second])
    add_note(knowledge, sources=[
        make_ref("chart:net-sales", adapter="superset"),
        make_ref("dashboard:finance", adapter="looker"),
    ])

    with pytest.raises(ValueError, match="namespace"):
        await dependencies.pin("context-1", 1, READER, now=NOW)
    assert first.authorization_calls
    assert first.inspect_calls == first.list_calls == first.search_calls == 0
    assert second.inspect_calls == second.list_calls == second.search_calls == 0


@pytest.mark.asyncio
async def test_pin_fails_if_any_exact_source_reference_is_unauthorized(tmp_path):
    knowledge, dependencies, (adapter,) = make_services(tmp_path)
    adapter.denied.add((TENANT, "chart:restricted"))
    add_note(knowledge, sources=[
        make_ref("chart:net-sales"),
        make_ref("chart:restricted"),
    ])

    with pytest.raises(ValueError):
        await dependencies.pin("context-1", 1, READER, now=NOW)

    assert [call[0] for call in adapter.authorization_calls] == [
        "chart:net-sales", "chart:restricted",
    ]
    assert adapter.inspect_calls == adapter.list_calls == adapter.search_calls == 0


@pytest.mark.asyncio
async def test_review_due_and_not_yet_valid_are_explicit_inspection_states(tmp_path):
    knowledge, dependencies, _ = make_services(tmp_path)
    due_entry = add_note(
        knowledge, entry_id="review-due", review_after=NOW + timedelta(days=1),
    )
    future_entry = add_note(
        knowledge, entry_id="not-yet-valid", valid_from=NOW,
        review_after=NOW + timedelta(days=5),
    )
    due_binding = await dependencies.pin(
        due_entry.id, 1, READER, required_for_action=True, now=NOW,
    )
    future_binding = await dependencies.pin(
        future_entry.id, 1, READER, required_for_action=True,
        now=NOW + timedelta(days=1),
    )

    due_result = await dependencies.inspect(
        [due_binding], READER, now=NOW + timedelta(days=2),
    )
    future_result = await dependencies.inspect(
        [future_binding], READER, now=NOW - timedelta(days=1),
    )

    assert due_result["entries"][0]["status"] == "review_due"
    assert due_result["required_current"] is False
    assert future_result["entries"][0]["status"] == "not_yet_valid"
    assert future_result["required_current"] is False
    assert_no_note_content(due_result)
    assert_no_note_content(future_result)


@pytest.mark.asyncio
async def test_optional_stale_binding_does_not_make_required_dependencies_incomplete(tmp_path):
    knowledge, dependencies, _ = make_services(tmp_path)
    required_entry = add_note(knowledge, entry_id="required")
    optional_entry = add_note(knowledge, entry_id="optional")
    required = await dependencies.pin(
        required_entry.id, 1, READER, required_for_action=True, now=NOW,
    )
    optional = await dependencies.pin(
        optional_entry.id, 1, READER, required_for_action=False, now=NOW,
    )
    append_revision(
        knowledge, optional_entry,
        content=optional_entry.content.model_copy(update={"body": "New optional meaning."}),
    )

    result = await dependencies.inspect([required, optional], READER, now=NOW)

    assert [row["status"] for row in result["entries"]] == ["current", "superseded"]
    assert result["required_current"] is True
    assert_no_note_content(result, "New optional meaning.")

"""Independent contract variations for source-linked domain context.

These are deterministic service/MCP unit cases, not company trials or evidence
of agent lift. Source authorization is synthetic and deliberately separate
from source inspection.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from signalweave.knowledge import KnowledgeService
from signalweave.knowledge_models import KnowledgeContent, KnowledgeEntry
from signalweave.knowledge_store import SQLiteKnowledgeStore
from signalweave.models import PrincipalContext, ResourceContract, ResourceDescriptor, SourceRef
from signalweave.sources import SourceRegistry

TENANT = "tenant-sales"
AUTHOR = PrincipalContext(
    principal_id="analyst-17", tenant_id=TENANT,
    scopes=["knowledge:write", "knowledge:share"],
)
OWNER = PrincipalContext(
    principal_id="owner-4", tenant_id=TENANT,
    scopes=["knowledge:write", "knowledge:review"],
)
OTHER = PrincipalContext(
    principal_id="analyst-92", tenant_id=TENANT, scopes=["knowledge:write"],
)


def source_ref(resource: str, *, key: str | None = None) -> SourceRef:
    return SourceRef(
        key=key or resource.replace(":", "-"),
        adapter="superset",
        resource=resource,
        label=resource.replace(":", " ").title(),
    )


class AuthorizationOnlySource:
    """Synthetic native authorization endpoint; inspection is forbidden in these tests."""

    name = "superset"

    def __init__(self) -> None:
        self.descriptors: dict[tuple[str, str], ResourceDescriptor] = {}
        self.overrides: dict[str, ResourceDescriptor] = {}
        self.denied: set[str] = set()
        self.errors: set[str] = set()
        self.parameter_authorizations: dict[tuple[str, str], bool] = {}
        self.authorization_calls: list[tuple[str, tuple[str, ...]]] = []
        self.authorized_refs: list[SourceRef] = []
        self.inspection_calls = 0
        self.list_calls = 0

    def add(
        self,
        resource: str,
        *,
        tenant_id: str = TENANT,
        authorized: bool = True,
    ) -> ResourceDescriptor:
        descriptor = ResourceDescriptor(
            adapter=self.name,
            resource=resource,
            kind="dashboard" if resource.startswith("dashboard:") else "chart",
            title=f"Synthetic {resource}",
            source_url=f"https://bi.invalid/{resource}",
            contract=ResourceContract(
                tenant_id=tenant_id,
                domain="revenue",
                authorized=authorized,
            ),
        )
        self.descriptors[(tenant_id, resource)] = descriptor
        return descriptor

    async def authorize(self, source, *, authorized_tenants=None):
        tenants = tuple(sorted(authorized_tenants or ()))
        self.authorization_calls.append((source.resource, tenants))
        self.authorized_refs.append(source.model_copy(deep=True))
        parameters = json.dumps(source.parameters, sort_keys=True)
        if self.parameter_authorizations.get((source.resource, parameters)) is False:
            return None
        if source.resource in self.errors:
            raise RuntimeError("synthetic private adapter diagnostic")
        if source.resource in self.denied:
            return None
        if source.resource in self.overrides:
            # Lets tests model a buggy/malicious adapter returning a foreign
            # descriptor despite the registry's requested tenant scope.
            return self.overrides[source.resource]
        candidates = tenants or tuple(tenant for tenant, ref in self.descriptors if ref == source.resource)
        for tenant in candidates:
            descriptor = self.descriptors.get((tenant, source.resource))
            if descriptor is not None:
                return descriptor
        return None

    async def inspect(self, _source):
        self.inspection_calls += 1
        raise AssertionError("knowledge operations must authorize, never inspect source data")

    async def list_resources(self):
        self.list_calls += 1
        raise AssertionError("native authorization is available; catalog listing is not allowed")


def make_service(tmp_path, authority: AuthorizationOnlySource | None = None):
    source = authority or AuthorizationOnlySource()
    registry = SourceRegistry([source])
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite3")
    return KnowledgeService(store, registry), source, store


def content(
    sources: list[SourceRef] | None = None,
    *,
    domain: str = "revenue",
    title: str = "Net sales definition",
    body: str = "Finance defines net sales after refunds and sales tax are removed.",
    kind: str = "definition",
    review_after: datetime | None = None,
    valid_from: datetime | None = None,
    readers: list[str] | None = None,
    provenance: list[str] | None = None,
) -> KnowledgeContent:
    return KnowledgeContent(
        domain=domain,
        title=title,
        body=body,
        kind=kind,
        sources=sources or [source_ref("dashboard:14")],
        provenance=provenance or ["Finance metric dictionary, reviewed with owner on 2026-10-14"],
        review_after=review_after or (datetime.now(timezone.utc) + timedelta(days=90)),
        valid_from=valid_from,
        reader_principal_ids=readers or [],
    )


async def approve(service: KnowledgeService, entry: KnowledgeEntry, principal=OWNER):
    return await service.review(
        entry.id,
        entry.revision,
        principal,
        action="approve",
        reason="Owner confirmed the meaning and source scope.",
    )


def insert_reviewed(store, principal, entry_id, value):
    """Preload one synthetic approved row to isolate retrieval limits and filters."""
    entry = KnowledgeEntry(
        id=entry_id,
        tenant_id=principal.tenant_id,
        revision=1,
        content=value,
        status="reviewed",
        actor=principal.principal_id,
        reason="Synthetic fixture owner review",
    )
    store.append(entry, expected_revision=0)
    return entry


async def test_cross_dashboard_freeform_definition_requires_review_and_reuses_exact_anchors(tmp_path):
    service, source, _ = make_service(tmp_path)
    refs = [source_ref("dashboard:14"), source_ref("chart:802")]
    for ref in refs:
        source.add(ref.resource)
    value = content(
        refs,
        title="Recognized net sales across channel and order dashboards",
        body=(
            "Finance defines recognized net sales after refunds and sales tax are removed. "
            "The channel dashboard and order ledger use this same definition; promotions are "
            "reported separately and are not deducted twice."
        ),
        provenance=["Finance glossary, section 4", "Owner review, 2026-10-14"],
    )

    draft = await service.save(value, AUTHOR)
    assert (draft.revision, draft.status, draft.actor) == (1, "draft", AUTHOR.principal_id)
    assert draft.owner_id == AUTHOR.principal_id
    assert (await service.retrieve(AUTHOR, query="recognized net sales")).entries == []

    draft_packet = await service.retrieve(
        AUTHOR, query="recognized net sales", source_refs=["superset|dashboard:14"],
        include_drafts=True,
    )
    assert [entry.id for entry in draft_packet.entries] == [draft.id]
    assert "Drafts and hypotheses" in " ".join(draft_packet.warnings)

    reviewed = await service.review(
        draft.id, draft.revision, OWNER, action="approve",
        reason="Owner confirmed the definition for both dashboards.",
    )
    assert (reviewed.revision, reviewed.status, reviewed.actor) == (2, "reviewed", OWNER.principal_id)
    assert reviewed.content.sources == refs
    for ref in refs:
        packet = await service.retrieve(
            AUTHOR, query="recognized net sales", domain="revenue",
            source_refs=[f"superset|{ref.resource}"],
        )
        assert [entry.id for entry in packet.entries] == [draft.id]
        assert packet.entries[0].content.provenance == value.provenance
        assert packet.freshness[draft.id] == "current"

    assert source.inspection_calls == source.list_calls == 0
    assert all(tenants == (TENANT,) for _, tenants in source.authorization_calls)


@pytest.mark.parametrize("include_drafts", [False, True])
async def test_draft_visibility_is_explicit(include_drafts, tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:visible-draft")
    source.add(ref.resource)
    saved = await service.save(content([ref]), AUTHOR)

    packet = await service.retrieve(
        AUTHOR, query="net sales", include_drafts=include_drafts,
    )
    assert [entry.id for entry in packet.entries] == ([saved.id] if include_drafts else [])
    assert source.inspection_calls == 0


@pytest.mark.parametrize(
    ("left_title", "left_body", "right_title", "right_body"),
    [
        (
            "Gross sales",
            "Finance counts gross sales before refunds and taxes.",
            "Net sales",
            "Finance counts net sales after refunds and taxes.",
        ),
        (
            "Bookings",
            "Finance counts bookings when a customer signs an order.",
            "Recognized revenue",
            "Finance counts recognized revenue when delivery occurs.",
        ),
        (
            "Active customers",
            "The growth team counts customers with a paid event.",
            "Engaged customers",
            "The lifecycle team counts customers with a session event.",
        ),
    ],
)
async def test_conflicting_business_meanings_are_returned_as_separate_attributed_entries(
    left_title, left_body, right_title, right_body, tmp_path
):
    service, source, _ = make_service(tmp_path)
    left_ref, right_ref = source_ref("dashboard:left"), source_ref("dashboard:right")
    source.add(left_ref.resource)
    source.add(right_ref.resource)
    left = await approve(
        service,
        await service.save(
            content([left_ref], title=left_title, body=left_body,
                    provenance=["Finance owner, 2026-10-14"]),
            AUTHOR,
        ),
    )
    right = await approve(
        service,
        await service.save(
            content([right_ref], title=right_title, body=right_body,
                    provenance=["Growth owner, 2026-10-14"]),
            AUTHOR,
        ),
    )

    packet = await service.retrieve(AUTHOR, query="counts")
    by_id = {entry.id: entry for entry in packet.entries}
    assert set(by_id) == {left.id, right.id}
    assert by_id[left.id].content.body == left_body
    assert by_id[right.id].content.body == right_body
    assert by_id[left.id].content.provenance != by_id[right.id].content.provenance
    assert len(packet.entries) == 2  # Retrieval preserves disagreement; it does not reconcile it.


async def test_reviewed_hypothesis_remains_a_hypothesis_with_caution(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("chart:conversion")
    source.add(ref.resource)
    hypothesis = content(
        [ref], title="Possible checkout cause",
        body="A payment-provider change may explain the conversion decline.",
        kind="hypothesis", provenance=["Analyst hypothesis from incident review"],
    )
    await approve(service, await service.save(hypothesis, AUTHOR))

    packet = await service.retrieve(AUTHOR, query="payment provider")
    assert packet.entries[0].status == "reviewed"
    assert packet.entries[0].content.kind == "hypothesis"
    assert any("hypotheses" in warning.lower() for warning in packet.warnings)


async def test_edits_create_new_draft_revisions_and_preserve_history(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:14")
    source.add(ref.resource)
    first = await service.save(content([ref]), AUTHOR)
    second = await service.review(
        first.id, first.revision, OWNER, action="approve", reason="Confirmed by owner."
    )
    replacement = content(
        [ref], title="Updated net sales definition",
        body="Finance now excludes refunded orders and sales tax.",
        provenance=["Owner change request, 2026-10-14"],
    )
    third = await service.save(
        replacement, AUTHOR, entry_id=first.id, expected_revision=second.revision,
    )

    assert [(first.revision, first.status), (second.revision, second.status),
            (third.revision, third.status)] == [(1, "draft"), (2, "reviewed"), (3, "draft")]
    assert first.content.title == "Net sales definition"
    assert second.reason == "Confirmed by owner."
    assert third.content.title == "Updated net sales definition"
    assert third.actor == AUTHOR.principal_id and third.reason == ""
    history = await service.history(first.id, AUTHOR)
    assert [entry.revision for entry in history] == [1, 2, 3]
    assert [entry.status for entry in history] == ["draft", "reviewed", "draft"]
    assert [entry.actor for entry in history] == [AUTHOR.principal_id, OWNER.principal_id, AUTHOR.principal_id]


@pytest.mark.parametrize("stale_revision", [0, 1])
async def test_stale_edit_cas_cannot_replace_latest_revision(stale_revision, tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:cas")
    source.add(ref.resource)
    first = await service.save(content([ref]), AUTHOR)
    current = await approve(service, first)
    stale = content([ref], title="Stale writer", body="This edit was based on an old revision.")

    with pytest.raises(ValueError, match="revision conflict"):
        await service.save(stale, AUTHOR, entry_id=current.id, expected_revision=stale_revision)
    assert service.store.get(TENANT, current.id, AUTHOR.principal_id).revision == current.revision


@pytest.mark.parametrize("stale_revision", [0, 1])
async def test_stale_review_cas_is_rejected_before_reauthorization(stale_revision, tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:review-cas")
    source.add(ref.resource)
    first = await service.save(content([ref]), AUTHOR)
    current = await approve(service, first)
    calls_before = len(source.authorization_calls)

    with pytest.raises(ValueError, match="revision changed"):
        await service.review(
            current.id, stale_revision, OWNER, action="retire", reason="Stale review.",
        )
    assert len(source.authorization_calls) == calls_before
    assert service.store.get(TENANT, current.id, AUTHOR.principal_id).status == "reviewed"


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        ("reject", "No"),
        ("approve", ""),
        ("retire", "   "),
        ("approve", "x" * 2001),
        ("delete", "Requested deletion"),
        ("Approve", "Wrong case"),
    ],
)
async def test_review_requires_bounded_reason_and_supported_action(action, reason, tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:review-validation")
    source.add(ref.resource)
    saved = await service.save(content([ref]), AUTHOR)

    with pytest.raises(ValueError, match="review requires"):
        await service.review(saved.id, saved.revision, OWNER, action=action, reason=reason)
    assert service.store.get(TENANT, saved.id, AUTHOR.principal_id).revision == 1


@pytest.mark.parametrize("expected_revision", [-1, 1])
async def test_new_entry_requires_zero_nonnegative_revision(expected_revision, tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:new-revision")
    source.add(ref.resource)
    with pytest.raises(ValueError, match="expected_revision"):
        await service.save(content([ref]), AUTHOR, expected_revision=expected_revision)
    assert source.authorization_calls == []


async def test_approval_rejects_review_date_already_due(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:stale-review")
    source.add(ref.resource)
    stale_date = datetime.now(timezone.utc) - timedelta(seconds=1)
    saved = await service.save(content([ref], review_after=stale_date), AUTHOR)

    with pytest.raises(ValueError, match="future review date"):
        await service.review(saved.id, saved.revision, OWNER, action="approve", reason="Reviewed.")
    assert service.store.get(TENANT, saved.id, AUTHOR.principal_id).status == "draft"


@pytest.mark.parametrize(
    ("offset_from_now", "valid_from_offset", "expected"),
    [
        (10, -10, "current"),
        (-10, -20, "review_due"),
        (20, 10, "not_yet_valid"),
    ],
)
async def test_freshness_distinguishes_current_due_and_future_effective(
    offset_from_now, valid_from_offset, expected, tmp_path
):
    service, source, store = make_service(tmp_path)
    ref = source_ref("dashboard:freshness")
    source.add(ref.resource)
    now = datetime.now(timezone.utc)
    value = content(
        [ref],
        review_after=now + timedelta(days=offset_from_now),
        valid_from=now + timedelta(days=valid_from_offset),
    )
    insert_reviewed(store, AUTHOR, "freshness", value)

    packet = await service.retrieve(AUTHOR, query="net sales", now=now)
    assert packet.freshness["freshness"] == expected
    if expected != "current":
        assert any("not current" in warning.lower() for warning in packet.warnings)


async def test_review_due_poll_returns_due_entries_and_not_future_reviews(tmp_path):
    service, source, _ = make_service(tmp_path)
    due_ref, future_ref = source_ref("dashboard:due"), source_ref("dashboard:future")
    source.add(due_ref.resource)
    source.add(future_ref.resource)
    now = datetime.now(timezone.utc)
    due = await approve(
        service,
        await service.save(content([due_ref], title="Review due", review_after=now + timedelta(days=2)), AUTHOR),
    )
    future = await approve(
        service,
        await service.save(content([future_ref], title="Review later", review_after=now + timedelta(days=20)), AUTHOR),
    )

    packet = await service.retrieve(
        AUTHOR, domain="revenue", review_due_only=True, now=now + timedelta(days=3),
    )
    assert [entry.id for entry in packet.entries] == [due.id]
    assert future.id not in {entry.id for entry in packet.entries}
    assert packet.freshness[due.id] == "review_due"


async def test_naive_retrieval_clock_is_rejected(tmp_path):
    service, _, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match="aware clock"):
        await service.retrieve(AUTHOR, now=datetime(2026, 10, 14))


@pytest.mark.parametrize("viewer_id", ["analyst-92", "finance-auditor"])
async def test_private_entry_is_indistinguishable_from_absence_to_other_readers(viewer_id, tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:private")
    source.add(ref.resource)
    private = content(
        [ref], title="Private payroll mapping",
        body="Sensitive context: payroll alias is employee-specific.",
        readers=[AUTHOR.principal_id],
    )
    saved = await service.save(private, AUTHOR)
    viewer = PrincipalContext(principal_id=viewer_id, tenant_id=TENANT)
    calls_before = len(source.authorization_calls)

    packet = await service.retrieve(viewer, query="payroll", include_drafts=True)
    assert packet.entries == []
    assert "Private payroll" not in packet.model_dump_json()
    with pytest.raises(KeyError, match="not found") as hidden:
        await service.history(saved.id, viewer)
    with pytest.raises(KeyError, match="not found") as absent:
        await service.history("nonexistent-entry", viewer)
    assert str(hidden.value) == str(absent.value)
    with pytest.raises(KeyError, match="not found"):
        await service.save(private, viewer, entry_id=saved.id, expected_revision=saved.revision)
    assert len(source.authorization_calls) == calls_before
    assert source.inspection_calls == 0


async def test_private_revision_cannot_lock_its_author_out(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:private-owner")
    source.add(ref.resource)
    private = content([ref], readers=[AUTHOR.principal_id])
    saved = await service.save(private, AUTHOR)
    replacement = content([ref], readers=[OTHER.principal_id])

    with pytest.raises(ValueError, match="must remain visible to its author"):
        await service.save(
            replacement, AUTHOR, entry_id=saved.id, expected_revision=saved.revision,
            confirm_visibility_change=True,
        )
    assert service.store.get(TENANT, saved.id, AUTHOR.principal_id).revision == 1


async def test_only_owner_can_edit_even_when_another_writer_can_read_the_entry(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:owner-only-edit")
    source.add(ref.resource)
    saved = await service.save(content([ref]), AUTHOR)
    writer = PrincipalContext(
        principal_id="collaborating-writer", tenant_id=TENANT,
        scopes=["knowledge:write"],
    )

    with pytest.raises(ValueError, match="only the context owner"):
        await service.save(
            content([ref], title="Writer replacement"), writer,
            entry_id=saved.id, expected_revision=saved.revision,
        )
    assert service.store.get(TENANT, saved.id, AUTHOR.principal_id).revision == 1


async def test_clearing_reader_acl_requires_owner_and_explicit_visibility_confirmation(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:reader-acl")
    source.add(ref.resource)
    saved = await service.save(content([ref], readers=[AUTHOR.principal_id, OTHER.principal_id]), AUTHOR)
    assert [entry.id for entry in (await service.retrieve(OTHER, query="net sales", include_drafts=True)).entries] == [saved.id]

    cleared = content([ref], readers=[])
    with pytest.raises(ValueError, match="explicit confirmation"):
        await service.save(cleared, AUTHOR, entry_id=saved.id, expected_revision=saved.revision)
    with pytest.raises(ValueError, match="only the context owner"):
        await service.save(
            cleared, OTHER, entry_id=saved.id, expected_revision=saved.revision,
            confirm_visibility_change=True,
        )

    updated = await service.save(
        cleared, AUTHOR, entry_id=saved.id, expected_revision=saved.revision,
        confirm_visibility_change=True,
    )
    assert updated.revision == 2 and updated.content.reader_principal_ids == []
    assert [entry.id for entry in (await service.retrieve(OTHER, query="net sales", include_drafts=True)).entries] == [saved.id]
    assert [entry.revision for entry in await service.history(saved.id, OTHER)] == [1, 2]


async def test_same_entry_id_is_isolated_between_tenants_and_history(tmp_path):
    service, source, _ = make_service(tmp_path)
    tenant_a = PrincipalContext(principal_id="owner-a", tenant_id="tenant-a")
    tenant_b = PrincipalContext(principal_id="owner-b", tenant_id="tenant-b")
    ref_a, ref_b = source_ref("dashboard:shared"), source_ref("dashboard:shared")
    source.add(ref_a.resource, tenant_id="tenant-a")
    source.add(ref_b.resource, tenant_id="tenant-b")
    store = service.store
    saved_a = insert_reviewed(
        store, tenant_a, "same-id",
        content([ref_a], title="Tenant A definition", body="alpha revenue meaning"),
    )
    saved_b = insert_reviewed(
        store, tenant_b, "same-id",
        content([ref_b], title="Tenant B definition", body="beta revenue meaning"),
    )

    packet_a = await service.retrieve(tenant_a, query="revenue meaning")
    packet_b = await service.retrieve(tenant_b, query="revenue meaning")
    assert [entry.id for entry in packet_a.entries] == [saved_a.id]
    assert [entry.content.title for entry in packet_a.entries] == ["Tenant A definition"]
    assert [entry.id for entry in packet_b.entries] == [saved_b.id]
    assert [entry.content.title for entry in packet_b.entries] == ["Tenant B definition"]
    assert [entry.tenant_id for entry in await service.history("same-id", tenant_a)] == ["tenant-a"]
    assert [entry.tenant_id for entry in await service.history("same-id", tenant_b)] == ["tenant-b"]
    assert {
        tenants
        for resource, tenants in source.authorization_calls
        if resource == "dashboard:shared"
    } == {("tenant-a",), ("tenant-b",)}


@pytest.mark.parametrize("failure", ["missing", "revoked", "foreign-tenant", "wrong-identity", "exception"])
async def test_save_fails_closed_for_unavailable_or_mismatched_source_authority(failure, tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:scope-check")
    if failure == "revoked":
        source.add(ref.resource, authorized=False)
    elif failure == "foreign-tenant":
        source.add(ref.resource, tenant_id="tenant-other")
        source.overrides[ref.resource] = source.descriptors[("tenant-other", ref.resource)]
    elif failure == "wrong-identity":
        source.overrides[ref.resource] = ResourceDescriptor(
            adapter="superset", resource="dashboard:somebody-else", kind="dashboard",
            title="Wrong resource", contract=ResourceContract(tenant_id=TENANT, authorized=True),
        )
    elif failure == "exception":
        source.errors.add(ref.resource)

    with pytest.raises(ValueError, match="sources are not available") as error:
        await service.save(content([ref]), AUTHOR)
    assert "synthetic private adapter diagnostic" not in str(error.value)
    assert source.inspection_calls == source.list_calls == 0


async def test_revoked_source_is_rechecked_and_hidden_from_packet_and_history(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:revocable")
    descriptor = source.add(ref.resource)
    saved = await service.save(content([ref], title="Revoked source note"), AUTHOR)
    reviewed = await approve(service, saved)
    source.descriptors[(TENANT, ref.resource)] = descriptor.model_copy(update={
        "contract": descriptor.contract.model_copy(update={"authorized": False}),
    })
    calls_before = len(source.authorization_calls)

    packet = await service.retrieve(AUTHOR, query="revoked source")
    history = await service.history(reviewed.id, AUTHOR)
    assert packet.entries == []
    assert history == []
    assert "Revoked source note" not in packet.model_dump_json()
    assert len(source.authorization_calls) == calls_before + 2
    assert source.inspection_calls == 0


async def test_revocation_between_save_and_approval_keeps_draft_unapproved(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:revoked-before-review")
    descriptor = source.add(ref.resource)
    draft = await service.save(content([ref]), AUTHOR)
    source.descriptors[(TENANT, ref.resource)] = descriptor.model_copy(update={
        "contract": descriptor.contract.model_copy(update={"authorized": False}),
    })

    with pytest.raises(ValueError, match="sources are not available"):
        await service.review(draft.id, draft.revision, OWNER, action="approve", reason="Review.")
    current = service.store.get(TENANT, draft.id, AUTHOR.principal_id)
    assert (current.revision, current.status) == (1, "draft")


async def test_retirement_rechecks_revoked_source_before_returning_context_body(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:revoked-before-retirement")
    descriptor = source.add(ref.resource)
    saved = await service.save(
        content([ref], title="Sensitive retired context", body="Revenue interpretation from this source."),
        AUTHOR,
    )
    reviewed = await approve(service, saved)
    source.descriptors[(TENANT, ref.resource)] = descriptor.model_copy(update={
        "contract": descriptor.contract.model_copy(update={"authorized": False}),
    })
    calls_before = len(source.authorization_calls)

    with pytest.raises(ValueError, match="sources are not available"):
        await service.review(
            reviewed.id, reviewed.revision, OWNER,
            action="retire", reason="Retirement attempt after source access was revoked.",
        )

    current = service.store.get(TENANT, reviewed.id, AUTHOR.principal_id)
    assert (current.revision, current.status) == (reviewed.revision, "reviewed")
    assert len(source.authorization_calls) == calls_before + 1
    assert source.inspection_calls == source.list_calls == 0


async def test_retrieval_authorizes_shared_source_once_per_packet(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:shared-source")
    source.add(ref.resource)
    for index in range(3):
        saved = await service.save(
            content([ref], title=f"Revenue note {index}", body=f"Revenue context note {index}."),
            AUTHOR,
        )
        await approve(service, saved)
    source.authorization_calls.clear()

    packet = await service.retrieve(AUTHOR, query="revenue context")
    assert len(packet.entries) == 3
    assert source.authorization_calls == [(ref.resource, (TENANT,))]
    assert source.inspection_calls == source.list_calls == 0


async def test_source_authorization_cache_distinguishes_full_reference_parameters(tmp_path):
    service, source, store = make_service(tmp_path)
    public_ref = source_ref("dashboard:parameterized").model_copy(
        update={"parameters": {"region": "public"}}, deep=True,
    )
    restricted_ref = public_ref.model_copy(
        update={"parameters": {"region": "restricted"}}, deep=True,
    )
    source.add(public_ref.resource)
    source.parameter_authorizations[(public_ref.resource, '{"region": "public"}')] = True
    source.parameter_authorizations[(restricted_ref.resource, '{"region": "restricted"}')] = False
    review_after = datetime.now(timezone.utc) + timedelta(days=30)
    insert_reviewed(
        store, AUTHOR, "a-public-parameter", content(
            [public_ref], title="Public region definition", body="shared parameter cache context",
            review_after=review_after,
        ),
    )
    insert_reviewed(
        store, AUTHOR, "b-restricted-parameter", content(
            [restricted_ref], title="Restricted region definition", body="shared parameter cache context",
            review_after=review_after,
        ),
    )
    source.authorization_calls.clear()
    source.authorized_refs.clear()

    packet = await service.retrieve(AUTHOR, query="shared parameter cache context")

    assert [entry.id for entry in packet.entries] == ["a-public-parameter"]
    assert [ref.parameters for ref in source.authorized_refs] == [
        {"region": "public"}, {"region": "restricted"},
    ]
    assert source.authorization_calls == [
        (public_ref.resource, (TENANT,)), (restricted_ref.resource, (TENANT,)),
    ]


async def test_hidden_source_count_does_not_change_public_packet_metadata(tmp_path):
    service, source, store = make_service(tmp_path)
    now = datetime.now(timezone.utc)
    empty_packet = await service.retrieve(AUTHOR, query="revenue context", now=now)
    for index in range(65):
        ref = source_ref(f"dashboard:missing-{index}")
        insert_reviewed(
            store, AUTHOR, f"missing-{index}",
            content([ref], title=f"Missing source note {index}", body="revenue context"),
        )
    source.authorization_calls.clear()

    packet = await service.retrieve(AUTHOR, query="revenue context", limit=30, now=now)
    assert packet.entries == []
    assert packet.truncated is False
    assert len(source.authorization_calls) == 60
    assert len({ref for ref, _ in source.authorization_calls}) == 60
    assert source.inspection_calls == source.list_calls == 0
    empty_metadata = empty_packet.model_dump(mode="json")
    inaccessible_metadata = packet.model_dump(mode="json")
    empty_metadata.pop("captured_at")
    inaccessible_metadata.pop("captured_at")
    assert inaccessible_metadata == empty_metadata


async def test_retrieval_reaches_authorized_context_after_three_pages_of_revoked_notes(tmp_path):
    service, source, store = make_service(tmp_path)
    revoked_ref = source_ref("dashboard:revoked-page")
    allowed_ref = source_ref("dashboard:allowed-page")
    source.add(allowed_ref.resource)
    review_after = datetime.now(timezone.utc) + timedelta(days=30)
    for index in range(201):
        insert_reviewed(
            store, AUTHOR, f"revoked-{index:03d}", content(
                [revoked_ref], title=f"Revoked note {index:03d}", body="page through revoked notes",
                review_after=review_after,
            ),
        )
    insert_reviewed(
        store, AUTHOR, "zzz-allowed", content(
            [allowed_ref], title="Authorized context", body="page through revoked notes",
            review_after=review_after,
        ),
    )

    packet = await service.retrieve(AUTHOR, query="")

    assert [entry.id for entry in packet.entries] == ["zzz-allowed"]
    assert packet.truncated is False
    assert source.authorization_calls == [
        (revoked_ref.resource, (TENANT,)), (allowed_ref.resource, (TENANT,)),
    ]


@pytest.mark.parametrize(
    ("review_days", "valid_days", "expected"),
    [(10, -10, "current"), (-10, -20, "review_due"), (20, 10, "not_yet_valid")],
)
async def test_packet_freshness_is_per_entry_and_dated(review_days, valid_days, expected, tmp_path):
    service, source, store = make_service(tmp_path)
    ref = source_ref("chart:dated-context")
    source.add(ref.resource)
    now = datetime.now(timezone.utc)
    value = content(
        [ref],
        review_after=now + timedelta(days=review_days),
        valid_from=now + timedelta(days=valid_days),
    )
    insert_reviewed(store, AUTHOR, "dated", value)

    packet = await service.retrieve(AUTHOR, query="net sales", now=now)
    assert packet.freshness["dated"] == expected
    assert packet.captured_at == now


@pytest.mark.parametrize("body_length", [100, 1200, 3000, 5500])
@pytest.mark.parametrize("max_bytes", [4096, 8192, 16000, 64000])
async def test_utf8_packet_respects_requested_byte_budget(body_length, max_bytes, tmp_path):
    service, source, store = make_service(tmp_path)
    ref = source_ref(f"chart:budget-{body_length}-{max_bytes}")
    source.add(ref.resource)
    body = "évidence " * (body_length // len("évidence "))
    insert_reviewed(
        store, AUTHOR, f"budget-{body_length}-{max_bytes}",
        content([ref], title="Bounded Unicode context", body=body),
    )

    packet = await service.retrieve(
        AUTHOR, query="bounded unicode", limit=10, max_bytes=max_bytes,
    )
    encoded = packet.model_dump_json().encode("utf-8")
    assert len(encoded) <= max_bytes
    if packet.truncated:
        assert any("Bounded context packet" in warning for warning in packet.warnings)
    assert source.inspection_calls == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0}, "outside its bounds"),
        ({"limit": 31}, "outside its bounds"),
        ({"limit": True}, "outside its bounds"),
        ({"limit": 1.5}, "outside its bounds"),
        ({"max_bytes": 4095}, "outside its bounds"),
        ({"max_bytes": 64001}, "outside its bounds"),
        ({"query": "q" * 2001}, "outside its bounds"),
        ({"domain": "   "}, "bounded nonempty"),
        ({"source_refs": ["superset/dashboard:7"]}, "exact adapter"),
        ({"source_refs": ["|dashboard:7"]}, "exact adapter"),
        ({"source_refs": ["superset|"]}, "exact adapter"),
        ({"source_refs": ["superset|dashboard:7"] * 13}, "exact adapter"),
    ],
)
async def test_retrieval_rejects_out_of_contract_bounds(kwargs, message, tmp_path):
    service, _, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match=message):
        await service.retrieve(AUTHOR, **kwargs)


@pytest.mark.parametrize(
    ("query", "domain", "anchors", "expected"),
    [
        ("recognized net sales", "revenue", ["superset|dashboard:14"], 1),
        ("recognized net sales", "support", ["superset|dashboard:14"], 0),
        ("unrelated staffing", "revenue", ["superset|dashboard:missing"], 0),
        ("unrelated staffing", "revenue", ["superset|dashboard:14"], 1),
    ],
)
async def test_domain_filters_union_of_query_and_exact_anchor_matches(
    query, domain, anchors, expected, tmp_path
):
    service, source, store = make_service(tmp_path)
    ref = source_ref("dashboard:14")
    source.add(ref.resource)
    insert_reviewed(
        store, AUTHOR, "filter-entry",
        content([ref], body="Recognized net sales by channel."),
    )

    packet = await service.retrieve(
        AUTHOR, query=query, domain=domain, source_refs=anchors,
    )
    assert len(packet.entries) == expected


@pytest.mark.parametrize("provenance_count", [1, 4, 8, 12])
async def test_content_utf8_serialization_stays_under_entry_budget(provenance_count):
    value = content(
        provenance=[f"owner note {index}: café, reviewed 2026-10-14" for index in range(provenance_count)],
        body="é" * 5000,
    )
    assert len(value.model_dump_json().encode("utf-8")) <= 24_000


async def test_oversized_content_is_rejected_before_source_authorization(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:oversized")
    source.add(ref.resource)
    with pytest.raises(ValidationError, match="24000-byte budget"):
        content(
            [ref], body="é" * 6000,
            provenance=["p" * 2000 for _ in range(12)],
        )
    assert source.authorization_calls == []


@pytest.mark.parametrize("limit", [0, 51])
async def test_history_limit_is_bounded(limit, tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:history-limit")
    source.add(ref.resource)
    saved = await service.save(content([ref]), AUTHOR)
    with pytest.raises(ValueError, match="history limit"):
        await service.history(saved.id, AUTHOR, limit=limit)


async def test_history_survives_service_restart_and_keeps_revision_provenance(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:durable")
    source.add(ref.resource)
    saved = await service.save(content([ref]), AUTHOR)
    reviewed = await approve(service, saved)
    replacement = await service.save(
        content([ref], title="Revised cross-dashboard meaning"), AUTHOR,
        entry_id=saved.id, expected_revision=reviewed.revision,
    )
    restarted = KnowledgeService(SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite3"), SourceRegistry([source]))

    packet = await restarted.retrieve(
        AUTHOR, query="revised cross dashboard", include_drafts=True,
    )
    history = await restarted.history(saved.id, AUTHOR)
    assert [entry.id for entry in packet.entries] == [saved.id]
    assert [entry.revision for entry in history] == [1, 2, 3]
    assert [entry.actor for entry in history] == [AUTHOR.principal_id, OWNER.principal_id, AUTHOR.principal_id]
    assert replacement.revision == 3


async def test_retirement_removes_current_retrieval_but_preserves_auditable_history(tmp_path):
    service, source, _ = make_service(tmp_path)
    ref = source_ref("dashboard:retire")
    source.add(ref.resource)
    saved = await service.save(content([ref], title="Retirable revenue note"), AUTHOR)
    reviewed = await approve(service, saved)
    retired = await service.review(
        reviewed.id, reviewed.revision, OWNER, action="retire", reason="Definition superseded.",
    )

    packet = await service.retrieve(AUTHOR, query="retirable revenue")
    history = await service.history(retired.id, AUTHOR)
    assert packet.entries == []
    assert [entry.status for entry in history] == ["draft", "reviewed", "retired"]


async def test_context_tools_use_authenticated_request_principal_not_caller_fields(tmp_path):
    from signalweave.mcp_server import create_mcp
    from tests.test_local_investigation import make_runtime

    runtime, _, _ = make_runtime(tmp_path / "runtime")
    source = AuthorizationOnlySource()
    ref = source_ref("dashboard:hosted")
    source.add(ref.resource, tenant_id="tenant-hosted")
    runtime.knowledge = KnowledgeService(
        SQLiteKnowledgeStore(tmp_path / "hosted-knowledge.sqlite3"), SourceRegistry([source])
    )
    trusted = PrincipalContext(
        principal_id="gateway-user", tenant_id="tenant-hosted",
        scopes=["knowledge:write", "knowledge:review", "knowledge:share"],
    )
    request_identity = [trusted]
    resolved = []

    def resolve_principal(ctx):
        assert ctx is not None
        resolved.append(ctx)
        return request_identity[0]

    server = create_mcp(
        runtime,
        profile="agent",
        principal_resolver=resolve_principal,
        require_principal=True,
    )
    tools = {item.name: item for item in await server.list_tools()}
    assert {"save_domain_context", "review_domain_context", "retrieve_domain_context", "get_context_history"} <= tools.keys()
    schema_fields = tools["save_domain_context"].inputSchema["properties"]
    assert "tenant_id" not in schema_fields and "principal_id" not in schema_fields

    _, result = await server.call_tool(
        "save_domain_context", {"content": content([ref]).model_dump(mode="json")},
    )
    assert result["tenant_id"] == trusted.tenant_id
    assert result["actor"] == trusted.principal_id
    request_identity[0] = PrincipalContext(
        principal_id="reviewer-8", tenant_id=trusted.tenant_id,
        scopes=["knowledge:review"],
    )
    _, reviewed = await server.call_tool(
        "review_domain_context",
        {
            "entry_id": result["id"], "expected_revision": result["revision"],
            "action": "approve", "reason": "Authorized reviewer confirmed the context.",
        },
    )
    assert reviewed["actor"] == "reviewer-8" and reviewed["status"] == "reviewed"

    request_identity[0] = trusted
    private_revision = content([ref], readers=[trusted.principal_id])
    _, updated = await server.call_tool(
        "save_domain_context",
        {
            "content": private_revision.model_dump(mode="json"),
            "entry_id": result["id"], "expected_revision": reviewed["revision"],
            "confirm_visibility_change": True,
        },
    )
    assert updated["actor"] == trusted.principal_id
    assert updated["content"]["reader_principal_ids"] == [trusted.principal_id]
    assert resolved and source.authorization_calls == [(ref.resource, (trusted.tenant_id,))] * 3
    assert source.inspection_calls == source.list_calls == 0


@pytest.mark.parametrize(
    "missing_scope", ["knowledge:write", "knowledge:review", "knowledge:share"],
)
async def test_request_scoped_knowledge_tools_require_each_mutation_scope(missing_scope, tmp_path):
    from signalweave.mcp_server import create_mcp
    from tests.test_local_investigation import make_runtime

    runtime, _, _ = make_runtime(tmp_path / "runtime")
    source = AuthorizationOnlySource()
    ref = source_ref("dashboard:missing-scope")
    tenant = "tenant-hosted-scopes"
    source.add(ref.resource, tenant_id=tenant)
    service = KnowledgeService(
        SQLiteKnowledgeStore(tmp_path / "scope-knowledge.sqlite3"), SourceRegistry([source])
    )
    runtime.knowledge = service

    owner = PrincipalContext(
        principal_id="scope-owner", tenant_id=tenant,
        scopes=["knowledge:write", "knowledge:share"],
    )
    if missing_scope == "knowledge:review":
        draft = await service.save(content([ref]), owner)
        request_identity = PrincipalContext(
            principal_id="not-a-reviewer", tenant_id=tenant,
            scopes=["knowledge:write", "knowledge:share"],
        )
    elif missing_scope == "knowledge:share":
        draft = await service.save(content([ref], readers=[owner.principal_id]), owner)
        request_identity = PrincipalContext(
            principal_id=owner.principal_id, tenant_id=tenant,
            scopes=["knowledge:write"],
        )
    else:
        draft = None
        request_identity = PrincipalContext(
            principal_id="cannot-write", tenant_id=tenant,
            scopes=["knowledge:review", "knowledge:share"],
        )

    server = create_mcp(
        runtime,
        profile="agent",
        principal_resolver=lambda _ctx: request_identity,
        require_principal=True,
    )
    calls_before = len(source.authorization_calls)
    with pytest.raises(Exception, match=f"permission denied: {missing_scope}"):
        if missing_scope == "knowledge:review":
            await server.call_tool(
                "review_domain_context",
                {
                    "entry_id": draft.id, "expected_revision": draft.revision,
                    "action": "approve", "reason": "Attempt without review permission.",
                },
            )
        elif missing_scope == "knowledge:share":
            await server.call_tool(
                "save_domain_context",
                {
                    "content": content([ref]).model_dump(mode="json"),
                    "entry_id": draft.id, "expected_revision": draft.revision,
                    "confirm_visibility_change": True,
                },
            )
        else:
            await server.call_tool(
                "save_domain_context", {"content": content([ref]).model_dump(mode="json")},
            )
    assert len(source.authorization_calls) == calls_before
    assert source.inspection_calls == source.list_calls == 0


async def test_write_only_request_can_create_private_context_but_not_public_context(tmp_path):
    from signalweave.mcp_server import create_mcp
    from tests.test_local_investigation import make_runtime

    runtime, _, _ = make_runtime(tmp_path / "runtime")
    source = AuthorizationOnlySource()
    ref = source_ref("dashboard:visibility-scope")
    tenant = "tenant-visibility-scope"
    source.add(ref.resource, tenant_id=tenant)
    runtime.knowledge = KnowledgeService(
        SQLiteKnowledgeStore(tmp_path / "visibility-knowledge.sqlite3"), SourceRegistry([source])
    )
    writer = PrincipalContext(
        principal_id="private-writer", tenant_id=tenant, scopes=["knowledge:write"],
    )
    resolution_count = 0

    def resolve_principal(ctx):
        nonlocal resolution_count
        assert ctx is not None
        resolution_count += 1
        return writer

    server = create_mcp(
        runtime,
        profile="agent",
        principal_resolver=resolve_principal,
        require_principal=True,
    )
    _, private = await server.call_tool(
        "save_domain_context",
        {"content": content([ref], readers=[writer.principal_id]).model_dump(mode="json")},
    )
    assert private["content"]["reader_principal_ids"] == [writer.principal_id]
    assert resolution_count == 1

    resolution_count = 0
    with pytest.raises(Exception, match="permission denied: knowledge:share"):
        await server.call_tool(
            "save_domain_context", {"content": content([ref]).model_dump(mode="json")},
        )
    assert resolution_count == 1
    assert source.authorization_calls == [(ref.resource, (tenant,))]
    assert source.inspection_calls == source.list_calls == 0


async def test_knowledge_mcp_rejects_request_without_authenticated_principal(tmp_path):
    from signalweave.mcp_server import create_mcp
    from tests.test_local_investigation import make_runtime

    runtime, _, _ = make_runtime(tmp_path / "runtime")
    source = AuthorizationOnlySource()
    ref = source_ref("dashboard:unauthenticated")
    source.add(ref.resource)
    runtime.knowledge = KnowledgeService(
        SQLiteKnowledgeStore(tmp_path / "unauth-knowledge.sqlite3"), SourceRegistry([source])
    )
    server = create_mcp(
        runtime,
        profile="agent",
        principal_resolver=lambda _ctx: None,
        require_principal=True,
    )

    with pytest.raises(Exception, match="identity gateway did not provide a principal"):
        await server.call_tool(
            "save_domain_context", {"content": content([ref]).model_dump(mode="json")},
        )
    assert source.authorization_calls == []
    assert source.inspection_calls == source.list_calls == 0


async def test_packet_bytes_and_identity_are_deterministic_for_same_current_entries(tmp_path):
    service, source, store = make_service(tmp_path)
    ref = source_ref("dashboard:stable-packet")
    source.add(ref.resource)
    insert_reviewed(store, AUTHOR, "stable", content([ref], body="Stable reusable definition."))
    now = datetime.now(timezone.utc)

    first = await service.retrieve(AUTHOR, query="reusable definition", now=now)
    second = await service.retrieve(AUTHOR, query="reusable definition", now=now)
    assert first.packet_id == second.packet_id
    assert json.loads(first.model_dump_json()) == json.loads(second.model_dump_json())
    assert first.captured_at == second.captured_at == now

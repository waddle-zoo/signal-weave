from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from signalweave.mcp_server import create_mcp
from signalweave.models import (
    ContextBinding,
    DecisionReceipt,
    InsightCard,
    InsightCardOnboardingReview,
    InsightCardStatus,
    InsightPlan,
    OnboardingCorrection,
    OnboardingCorrectionKind,
    OnboardingDiscoveryReceipt,
    Outcome,
    PrincipalContext,
    ReceiptStatus,
    SourceRef,
)
from signalweave.store import InMemoryDecisionReceiptStore
from tests.test_onboarding import OnboardingJevDouble, SupersetCatalogDouble, make_server

CARD_ID = "revision-contract-card"
CARD_VERSION = 4
PRINCIPAL = PrincipalContext(principal_id="test-principal", tenant_id="default")


class CountingCatalog(SupersetCatalogDouble):
    def __init__(self):
        super().__init__()
        self.calls = Counter()

    async def list_resources(self):
        self.calls["list_resources"] += 1
        return await super().list_resources()

    async def inspect(self, source):
        self.calls["inspect"] += 1
        return await super().inspect(source)


class CountingJev(OnboardingJevDouble):
    def __init__(self):
        self.calls = Counter()

    async def rank_resources(self, *args):
        self.calls["rank_resources"] += 1
        return await super().rank_resources(*args)

    async def compile_plan(self, *args):
        self.calls["compile_plan"] += 1
        return await super().compile_plan(*args)

    async def select_investigation_sources(self, *args):
        self.calls["select_investigation_sources"] += 1
        return await super().select_investigation_sources(*args)

    async def judge(self, *args):
        self.calls["judge"] += 1
        return await super().judge(*args)


def reviewed_card(*, questions=True, status=InsightCardStatus.APPROVED):
    discovery = OnboardingDiscoveryReceipt(
        catalog_provider="fixture-catalog",
        catalog_strategy="selected-source",
        candidate_refs=["superset|dashboard:7", "superset|dashboard:8"],
        candidate_count=2,
        candidate_limit=2,
        evaluator="offline-test",
        principal_id=PRINCIPAL.principal_id,
        principal_tenant=PRINCIPAL.tenant_id,
    )
    review = InsightCardOnboardingReview(
        card_id=CARD_ID,
        status="ready_for_approval",
        readiness_status="ready_for_approval",
        source_selection_fingerprint="a" * 64,
        principal_id=PRINCIPAL.principal_id,
        principal_tenant=PRINCIPAL.tenant_id,
        discovery_receipt=discovery,
        selected_source_refs=["superset|dashboard:7", "superset|dashboard:8"],
    )
    prior_correction = OnboardingCorrection(
        correction_id="prior-correction",
        card_id=CARD_ID,
        card_version=CARD_VERSION - 1,
        kind=OnboardingCorrectionKind.OTHER,
        note="Earlier owner clarification.",
        principal_id=PRINCIPAL.principal_id,
        principal_tenant=PRINCIPAL.tenant_id,
    )
    sources = [
        SourceRef(
            key="sales",
            adapter="superset",
            resource="dashboard:7",
            label="Growth overview",
            parameters={"region": "north-america", "filters": {"channel": ["web", "store"]}},
            required=True,
            required_comparison_keys=["net_sales_previous_week"],
        ),
        SourceRef(
            key="finance-context",
            adapter="superset",
            resource="dashboard:8",
            label="Finance close",
            parameters={"section": "refunds"},
            required=False,
            required_comparison_keys=["refunds_previous_week"],
        ),
    ]
    card = InsightCard(
        id=CARD_ID,
        title="Weekly net sales",
        what_to_watch="Watch weekly net sales for material movement.",
        why_watch="Give Growth and Finance time to investigate a meaningful change.",
        watch_for=["Net sales moves materially."],
        questions=["Which channel explains the change?"] if questions else [],
        evidence_requirements={"watch:1": True},
        decision_guidance="Investigate supported material changes; otherwise ignore.",
        follow_up_guidance="Check channel and refund context before reporting.",
        sources=sources,
        context_bindings=[
            ContextBinding(
                entry_id="reviewed-definition",
                revision=3,
                content_digest="b" * 64,
                source_digest="c" * 64,
                required_for_action=True,
            ),
            ContextBinding(
                entry_id="owner-routing-note",
                revision=2,
                content_digest="d" * 64,
                source_digest="e" * 64,
                required_for_action=False,
            ),
        ],
        comparison_windows=["previous_period"],
        version=CARD_VERSION,
        owner="Growth Analytics",
        retrieval_mode="fixed",
        investigation_mode="none",
        principal_id=PRINCIPAL.principal_id,
        principal_tenant=PRINCIPAL.tenant_id,
        compiled_plan=InsightPlan(
            card_id=CARD_ID,
            card_version=CARD_VERSION,
            selected_source_keys=["sales", "finance-context"],
            comparison_windows=["previous_period"],
            capabilities=["percent_change"],
            watch_for=["Net sales moves materially."],
            questions=["Which channel explains the change?"] if questions else [],
            compiled_by="offline-test",
            card_scope="selected sources only",
        ),
        onboarding_review=review,
        onboarding_review_history=[review],
        onboarding_corrections=[prior_correction],
        status=status,
        approved_by="growth-owner",
        approved_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    return card


def setup_server(tmp_path, *, sqlite=False, questions=True):
    catalog = CountingCatalog()
    judger = CountingJev()
    server = make_server(
        tmp_path,
        judger=judger,
        sqlite=sqlite,
        catalog=catalog,
    )
    runtime = server._test_runtime
    if runtime.decision_receipts is None:
        runtime.decision_receipts = InMemoryDecisionReceiptStore()
        server = create_mcp(runtime, profile="full")
        server._test_runtime = runtime
    card = reviewed_card(questions=questions)
    runtime.card_store.save_card(card)
    return server, runtime, card, catalog, judger


async def revise(server, *, card_id=CARD_ID, version=CARD_VERSION, changes, reason="Owner clarified the recurring policy."):
    _, result = await server.call_tool(
        "revise_insight_card",
        {
            "card_id": card_id,
            "expected_card_version": version,
            "changes": changes,
            "reason": reason,
        },
    )
    return result


def assert_no_source_or_model_calls(catalog, judger):
    assert catalog.calls == Counter()
    assert judger.calls == Counter()


@pytest.mark.parametrize("sqlite", [False, True], ids=["json-store", "sqlite-store"])
async def test_revision_keeps_card_identity_and_scope_and_returns_approved_card_to_draft(
    tmp_path, sqlite
):
    server, runtime, before, catalog, judger = setup_server(tmp_path, sqlite=sqlite)
    receipt = DecisionReceipt(
        receipt_id="historical-receipt-v1",
        idempotency_key="weekly-sales-before-revision",
        card_id=CARD_ID,
        card_version=CARD_VERSION,
        actor=PRINCIPAL.principal_id,
        status=ReceiptStatus.DELIVERY_DISABLED,
        outcome=Outcome.INVESTIGATE,
        delivery_enabled=False,
        result={"summary": "Historical result for the approved version."},
    )
    runtime.decision_receipts.save(receipt)
    _, historical_before = await server.call_tool(
        "get_decision_receipt", {"idempotency_key": receipt.idempotency_key}
    )

    condition = {
        "text": "Net sales declined by at least five percent versus the prior week.",
        "source_key": "sales",
        "comparison_key": "net_sales_current_week",
        "measurement": "change_pct",
        "unit": "percent",
        "threshold": -5.0,
        "comparator": "<=",
    }
    changes = {
        "title": "Weekly net sales movement",
        "what_to_watch": "Watch net sales against the approved weekly comparison.",
        "numeric_conditions": [condition],
    }
    result = await revise(server, changes=changes)
    after = runtime.card_store.get_card(CARD_ID)
    after_json = after.model_dump(mode="json")
    before_json = before.model_dump(mode="json")

    assert result["approval_required"] is True
    assert result["delivery_enabled"] is False
    assert result["next_action"] == "review_insight_card"
    assert result["card"] == after_json
    assert after.id == before.id == CARD_ID
    assert after.version == before.version + 1
    assert after.status is InsightCardStatus.DRAFT
    assert after.approved_by is None
    assert after.approved_at is None
    assert after.compiled_plan is None
    assert after.onboarding_review is None
    assert after.onboarding_review_history == before.onboarding_review_history
    assert after.context_bindings == before.context_bindings

    assert [source.model_dump(mode="json") for source in after.sources] == [
        {
            **before.sources[0].model_dump(mode="json"),
            "required_comparison_keys": [
                "net_sales_current_week",
                "net_sales_previous_week",
            ],
        },
        before.sources[1].model_dump(mode="json"),
    ]
    for prior_source, revised_source in zip(before.sources, after.sources, strict=True):
        assert (
            revised_source.key,
            revised_source.adapter,
            revised_source.resource,
            revised_source.label,
            revised_source.parameters,
            revised_source.required,
        ) == (
            prior_source.key,
            prior_source.adapter,
            prior_source.resource,
            prior_source.label,
            prior_source.parameters,
            prior_source.required,
        )
    assert [item.model_dump(mode="json") for item in after.numeric_conditions] == [
        {**condition, "segment": None, "absolute": False}
    ]

    for field in before_json:
        if field not in {
            *changes,
            "version",
            "status",
            "approved_by",
            "approved_at",
            "compiled_plan",
            "onboarding_review",
            "sources",
            "onboarding_corrections",
        }:
            assert after_json[field] == before_json[field], field
    for field, value in changes.items():
        if field != "numeric_conditions":
            assert after_json[field] == value

    corrections = after.onboarding_corrections
    assert len(corrections) == len(before.onboarding_corrections) + 1
    assert corrections[:-1] == before.onboarding_corrections
    assert corrections[-1].card_id == CARD_ID
    assert corrections[-1].card_version == before.version + 1
    assert corrections[-1].kind is OnboardingCorrectionKind.INTENT_CLARIFIED
    assert corrections[-1].note == "Owner clarified the recurring policy."
    assert corrections[-1].principal_id == PRINCIPAL.principal_id
    assert corrections[-1].principal_tenant == PRINCIPAL.tenant_id

    _, historical_after = await server.call_tool(
        "get_decision_receipt", {"idempotency_key": receipt.idempotency_key}
    )
    assert historical_after["receipt"] == historical_before["receipt"]
    assert historical_after["receipt"]["card_version"] == before.version
    assert historical_after["policy_result_is_historical"] is True
    assert historical_after["policy_action_available"] is False
    assert historical_after["current_card_state"] == {
        "version": after.version,
        "status": "draft",
        "receipt_card_version": before.version,
        "review_required": True,
    }
    assert_no_source_or_model_calls(catalog, judger)


async def test_empty_questions_list_clears_questions(tmp_path):
    server, runtime, before, catalog, judger = setup_server(
        tmp_path, questions=True
    )

    result = await revise(server, changes={"questions": []})

    after = runtime.card_store.get_card(CARD_ID)
    assert result["card"]["questions"] == []
    assert after.questions == []
    assert after.version == before.version + 1
    assert after.watch_for == before.watch_for
    assert after.sources == before.sources
    assert_no_source_or_model_calls(catalog, judger)


@pytest.mark.parametrize(
    ("identity", "message"),
    [
        (PrincipalContext(principal_id="another-owner", tenant_id="default"), "owner"),
        (PrincipalContext(principal_id="test-principal", tenant_id="another-tenant"), "tenant"),
        (None, "authenticated card owner"),
    ],
    ids=["different-principal", "different-tenant", "unscoped"],
)
async def test_only_authenticated_card_owner_can_revise(tmp_path, identity, message):
    server, runtime, before, catalog, judger = setup_server(tmp_path)
    runtime.principal = identity

    with pytest.raises(ToolError, match=message):
        await revise(server, changes={"title": "Unauthorized edit"})

    assert runtime.card_store.get_card(CARD_ID) == before
    assert_no_source_or_model_calls(catalog, judger)


@pytest.mark.parametrize(
    ("version", "changes"),
    [
        (CARD_VERSION - 1, {"title": "Stale revision"}),
        (True, {"title": "Boolean version"}),
        (False, {"title": "Boolean version"}),
    ],
    ids=["stale-version", "true-is-not-an-integer-version", "false-is-not-an-integer-version"],
)
async def test_stale_or_boolean_versions_are_rejected_without_mutation(
    tmp_path, version, changes
):
    server, runtime, before, catalog, judger = setup_server(tmp_path)

    with pytest.raises(ToolError):
        await revise(server, version=version, changes=changes)

    assert runtime.card_store.get_card(CARD_ID) == before
    assert_no_source_or_model_calls(catalog, judger)


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown_policy_field": "no"},
        {"sources": []},
        {"status": "draft"},
        {"delivery_enabled": True},
        {"context_bindings": []},
        {"action_confidence_threshold": 0.9},
        {"retrieval_mode": "expand"},
        {"investigation_mode": "bounded"},
        {"max_source_age_hours": 1},
        {"compiled_plan": None},
        {"approved_by": "another-owner"},
    ],
    ids=[
        "unknown-field",
        "source-identities-and-config",
        "status",
        "delivery-enabled",
        "context-pins",
        "execution-setting",
        "retrieval-setting",
        "investigation-setting",
        "freshness-setting",
        "compiled-plan",
        "approval-metadata",
    ],
)
async def test_non_policy_fields_are_rejected_without_mutation(tmp_path, changes):
    server, runtime, before, catalog, judger = setup_server(tmp_path)

    with pytest.raises(ToolError):
        await revise(server, changes=changes)

    assert runtime.card_store.get_card(CARD_ID) == before
    assert_no_source_or_model_calls(catalog, judger)


@pytest.mark.parametrize(
    "changes",
    [
        {
            "numeric_conditions": [
                {
                    "text": "Use a source outside this card.",
                    "source_key": "unapproved-source",
                    "comparison_key": "net_sales_current_week",
                    "measurement": "change_pct",
                    "unit": "percent",
                    "threshold": -5,
                    "comparator": "<=",
                }
            ]
        },
        {
            "numeric_conditions": [
                {
                    "text": "Invalid comparator.",
                    "source_key": "sales",
                    "comparison_key": "net_sales_current_week",
                    "measurement": "change_pct",
                    "unit": "percent",
                    "threshold": -5,
                    "comparator": "approximately",
                }
            ]
        },
        {
            "numeric_conditions": [
                {
                    "text": "A non-finite threshold is invalid.",
                    "source_key": "sales",
                    "comparison_key": "net_sales_current_week",
                    "measurement": "change_pct",
                    "unit": "percent",
                    "threshold": float("nan"),
                    "comparator": "<=",
                }
            ]
        },
        {"evidence_requirements": {"watch:2": True}},
        {"evidence_requirements": {"watch:1": 1}},
        {"title": "oversize" * 5_000},
    ],
    ids=[
        "numeric-condition-cannot-add-anchor",
        "invalid-numeric-condition",
        "non-finite-number",
        "evidence-requirement-must-reference-existing-slot",
        "evidence-requirement-is-strict-boolean",
        "oversize-patch",
    ],
)
async def test_invalid_or_oversize_policy_patch_is_atomic(tmp_path, changes):
    server, runtime, before, catalog, judger = setup_server(tmp_path)

    with pytest.raises(ToolError):
        await revise(server, changes=changes)

    assert runtime.card_store.get_card(CARD_ID) == before
    assert_no_source_or_model_calls(catalog, judger)


class SameVersionConcurrentMutationStore:
    """Inject a same-version intervening write before delegating to real CAS."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def save_card_if_version(self, card, expected_version, *, expected_card=None):
        concurrent = expected_card.model_copy(
            update={"why_watch": "A concurrent owner edit at the same version."}
        )
        self.inner.save_card(concurrent)
        self.inner.save_card_if_version(
            card,
            expected_version,
            expected_card=expected_card,
        )


@pytest.mark.parametrize("sqlite", [False, True], ids=["json-store", "sqlite-store"])
async def test_revision_snapshot_cas_rejects_same_version_concurrent_change(tmp_path, sqlite):
    server, runtime, before, catalog, judger = setup_server(tmp_path, sqlite=sqlite)
    real_store = runtime.card_store
    runtime.card_store = SameVersionConcurrentMutationStore(real_store)

    with pytest.raises(ToolError, match="changed since expected snapshot"):
        await revise(server, changes={"title": "Should lose concurrent CAS"})

    after_race = real_store.get_card(CARD_ID)
    assert after_race.version == before.version
    assert after_race.why_watch == "A concurrent owner edit at the same version."
    assert after_race.title == before.title
    assert after_race.status is InsightCardStatus.APPROVED
    assert after_race.approved_by == before.approved_by
    assert after_race.compiled_plan == before.compiled_plan
    assert after_race.onboarding_review == before.onboarding_review
    assert_no_source_or_model_calls(catalog, judger)

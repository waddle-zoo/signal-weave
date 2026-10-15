"""Lifecycle contracts through the real tools, not agent efficacy benchmarks."""

from datetime import datetime, timedelta, timezone

import pytest

from signalweave.evaluation import card_acceptance_digest
from signalweave.mcp_server import create_mcp
from signalweave.models import (
    ContextSnapshot,
    DecisionReceipt,
    InsightCardStatus,
    Observation,
    ReceiptStatus,
    ResourceSnapshot,
    SourceRef,
)
from tests.test_knowledge_mcp import content, setup


async def prepared(tmp_path, *, required=True, request_scoped=False):
    server, runtime, assets, identity, judger = setup(tmp_path, request_scoped=request_scoped)
    assets.binding_namespace = "workspace-a"
    assets.reads = 0

    async def inspect(source):
        assets.reads += 1
        descriptor = await assets.authorize(source, authorized_tenants=["a"])
        return ResourceSnapshot(
            source_key=source.key, adapter=source.adapter, resource=source.resource,
            title="Sales", contract=descriptor.contract,
            observations=[Observation(subject="sales", metric="net_sales", current=80, previous=100)],
        )

    assets.inspect = inspect
    runtime.engine.registry = runtime.sources
    card = runtime.card_store.get_card("repeat").model_copy(update={
        "principal_id": "analyst", "principal_tenant": "a",
        "sources": [SourceRef.model_validate(content()["sources"][0])],
    })
    runtime.card_store.save_card(card)
    _, saved = await server.call_tool("save_domain_context", {"content": content()})
    _, reviewed = await server.call_tool("review_domain_context", {
        "entry_id": saved["id"], "expected_revision": 1, "action": "approve", "reason": "Owner confirmed meaning.",
    })
    _, bound = await server.call_tool("bind_insight_context", {
        "card_id": "repeat", "expected_card_version": 1,
        "pins": [{"entry_id": saved["id"], "revision": reviewed["revision"], "required_for_action": required}],
        "reason": "Use the agreed definition for this sales workflow.",
    })
    assert bound["status"] == "draft" and bound["version"] == 2
    assert assets.reads == 0 and not judger.states
    return server, runtime, assets, identity, judger, saved["id"]


def authorize_for_runtime_test(runtime):
    # This test bypasses authoring to isolate the recurring-run contract, not to
    # claim end-to-end onboarding or owner approval has been demonstrated.
    card = runtime.card_store.get_card("repeat")
    runtime.card_store.save_card(card.model_copy(update={"status": InsightCardStatus.APPROVED}))


async def test_binding_is_revisioned_not_approval_and_never_provider_context(tmp_path):
    server, runtime, _, _, _, entry = await prepared(tmp_path)
    card = runtime.card_store.get_card("repeat")
    assert card.approved_at is None and card.compiled_plan is None
    assert card.context_binding_reason == "Use the agreed definition for this sales workflow."
    assert "context_bindings" not in card.execution_payload()
    assert "Net sales excludes" not in str(card.model_dump())
    assert card_acceptance_digest(card) != card_acceptance_digest(card.model_copy(update={"context_bindings": []}))
    with pytest.raises(Exception, match="draft"):
        await server.call_tool("evaluate_insight_card", {"card_id": "repeat"})
    _, checked = await server.call_tool("inspect_insight_context", {"card_id": "repeat"})
    assert checked["entries"] == [{"entry_id": entry, "revision": 2, "required_for_action": True, "status": "current"}]


@pytest.mark.parametrize("change", ["draft", "due", "workspace", "private", "revoked"])
async def test_required_context_change_defers_policy_but_preserves_source_evidence(tmp_path, change):
    server, runtime, assets, _, judger, entry = await prepared(tmp_path)
    authorize_for_runtime_test(runtime)
    if change in {"draft", "due", "private"}:
        updated = content()
        if change == "due":
            updated["review_after"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        if change == "private":
            updated["reader_principal_ids"] = ["analyst"]
        await server.call_tool("save_domain_context", {
            "entry_id": entry, "expected_revision": 2, "content": updated, "confirm_visibility_change": change == "private",
        })
    elif change == "workspace":
        assets.binding_namespace = "workspace-b"
    else:
        assets.revoked = True
    _, result = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "daily"})
    assert result["result"]["outcome"] is None
    assert result["result"]["judgment"]["reason"] == "context_review_required"
    assert result["result"]["judgment"]["provider_call_attempted"] is False
    assert result["receipt"]["status"] == "decision_deferred"
    assert not judger.states
    assert result["current_context_dependencies"]["required_current"] is False
    assert "Net sales excludes" not in str(result)
    assert result["result"].get("source_by_key") or result.get("evidence_access")
    # Revoke blocks the source itself; other context changes retain fresh data.
    if change != "revoked":
        assert assets.reads == 1
    before = assets.reads
    _, replay = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "daily"})
    assert replay["replayed"] and assets.reads == before
    _, receipt = await server.call_tool("get_decision_receipt", {"idempotency_key": "daily"})
    assert receipt["current_context_dependencies"]["required_current"] is False


async def test_advisory_change_warns_without_cancelling_policy(tmp_path):
    server, runtime, assets, _, judger, _ = await prepared(tmp_path, required=False)
    authorize_for_runtime_test(runtime)
    assets.binding_namespace = "workspace-b"
    _, result = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "daily"})
    assert len(judger.states) == 1 and assets.reads == 1
    assert result["current_context_dependencies"]["entries"][0]["status"] == "source_changed"
    assert "Net sales excludes" not in str(judger.states)
    assert "context_bindings" not in str(judger.states)


async def test_old_receipt_remains_historical_after_required_context_changes(tmp_path):
    server, runtime, assets, _, judger, _ = await prepared(tmp_path)
    authorize_for_runtime_test(runtime)
    _, original = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "daily"})
    _, archived_before = await server.call_tool("get_decision_receipt", {"idempotency_key": "daily"})
    assert original["result"]["delivery_methods"]  # route suppression below must not be vacuous
    assert len(judger.states) == 1
    assets.binding_namespace = "workspace-b"
    _, replay = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "daily"})
    assert replay["policy_result_is_historical"] is True
    assert replay["result"]["outcome"] == original["result"]["outcome"]
    assert replay["result"]["delivery_methods"] == []
    assert replay["policy_action_available"] is False
    assert len(judger.states) == 1
    _, receipt = await server.call_tool("get_decision_receipt", {"idempotency_key": "daily"})
    assert not receipt["current_context_dependencies"]["required_current"]
    assert receipt["result"] == archived_before["result"]  # unchanged archived evidence


async def test_hosted_reader_cannot_rebind_or_forge_identity(tmp_path):
    server, runtime, _, identity, _, _ = await prepared(tmp_path, request_scoped=True)
    identity[0] = identity[0].model_copy(update={"principal_id": "reader"})
    with pytest.raises(Exception, match="card owner"):
        await server.call_tool("bind_insight_context", {"card_id": "repeat", "expected_card_version": 2, "pins": [], "reason": "Remove"})
    identity[0] = identity[0].model_copy(update={"principal_id": "analyst", "scopes": []})
    with pytest.raises(Exception, match="knowledge:write"):
        await server.call_tool("bind_insight_context", {"card_id": "repeat", "expected_card_version": 2, "pins": [], "reason": "Remove"})
    assert runtime.card_store.get_card("repeat").version == 2


async def test_changed_dependencies_cannot_approve_or_certify_as_current(tmp_path):
    server, runtime, assets, _, _, _ = await prepared(tmp_path)
    assets.binding_namespace = "workspace-b"
    with pytest.raises(Exception, match="context dependencies"):
        await server.call_tool("approve_insight_card", {"card_id": "repeat"})
    with pytest.raises(Exception, match="context dependencies"):
        await create_mcp(runtime, profile="full").call_tool("evaluate_card_workflow", {"card_id": "repeat", "cases": [{"id": "changed", "expected_outcome": "notify", "resources": []}]})
    # Full-profile readiness uses current dependency state rather than an old digest alone.
    _, readiness = await create_mcp(runtime, profile="full").call_tool("get_enterprise_readiness", {})
    assert any(gate["code"] == "card-context-needs-review" for gate in readiness["gates"])


async def test_preview_and_related_source_resolution_do_not_infer_on_required_stale_context(tmp_path):
    _, runtime, assets, _, judger, _ = await prepared(tmp_path)
    assets.binding_namespace = "workspace-b"
    full = create_mcp(runtime, profile="full")
    _, preview = await full.call_tool("simulate_insight_card", {"card_id": "repeat"})
    assert preview["status"] == "preview_deferred"
    assert preview["result"]["outcome"] is None
    assert preview["result"]["observations"][0]["current"] == 80
    _, expansion = await full.call_tool("resolve_insight_sources", {"card_id": "repeat"})
    assert expansion["status"] == "context_review_required"
    assert not judger.states


async def test_context_change_during_inference_removes_live_action_not_archived_result(tmp_path):
    server, runtime, assets, _, judger, _ = await prepared(tmp_path)
    authorize_for_runtime_test(runtime)
    original_judge = judger.judge

    async def judge_and_reconfigure(*args, **kwargs):
        result = await original_judge(*args, **kwargs)
        assets.binding_namespace = "workspace-b"
        return result

    judger.judge = judge_and_reconfigure
    _, evaluated = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "changed-in-flight"})
    assert evaluated["policy_action_available"] is False
    assert evaluated["result"]["delivery_methods"] == []
    assert evaluated["policy_result_is_historical"] is True
    assert runtime.decision_receipts.get_by_idempotency_key("changed-in-flight").result["delivery_methods"]


async def test_unbinding_during_inference_cannot_erase_the_current_card_guard(tmp_path):
    server, runtime, _, _, judger, _ = await prepared(tmp_path)
    authorize_for_runtime_test(runtime)
    original_judge = judger.judge

    async def judge_and_unbind(*args, **kwargs):
        result = await original_judge(*args, **kwargs)
        await server.call_tool("bind_insight_context", {
            "card_id": "repeat", "expected_card_version": 2, "pins": [],
            "reason": "Owner replaces this workflow and must review version three.",
        })
        return result

    judger.judge = judge_and_unbind
    _, evaluated = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "unbind-in-flight"})
    assert runtime.card_store.get_card("repeat").context_bindings == []
    assert evaluated["policy_action_available"] is False
    assert evaluated["result"]["delivery_methods"] == []
    assert evaluated["current_card_state"] == {"version": 3, "status": "draft", "receipt_card_version": 2, "review_required": True}
    assert runtime.decision_receipts.get_by_idempotency_key("unbind-in-flight").result["delivery_methods"]
    _, receipt = await server.call_tool("get_decision_receipt", {"idempotency_key": "unbind-in-flight"})
    assert receipt["current_card_state"]["review_required"]
    assert receipt["policy_action_available"] is False


async def test_required_context_change_replays_without_reloading_derived_context(tmp_path):
    server, runtime, assets, _, judger, _ = await prepared(tmp_path)
    authorize_for_runtime_test(runtime)

    class Provider:
        calls = 0

        async def get_context(self, card, resources):
            self.calls += 1
            return ContextSnapshot(provider="company", version="reviewed-v1")

    provider = Provider()
    runtime.context_provider = provider
    _, first = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "derived-context"})
    calls = provider.calls
    reads = assets.reads
    assets.binding_namespace = "workspace-b"
    _, replay = await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "derived-context"})
    assert replay["replayed"] and replay["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    assert replay["policy_action_available"] is False
    assert provider.calls == calls and assets.reads == reads and len(judger.states) == 1


async def test_claim_lost_cannot_replay_a_foreign_legacy_receipt_with_empty_fingerprint(tmp_path):
    server, runtime, _, _, judger, _ = await prepared(tmp_path)
    authorize_for_runtime_test(runtime)

    def conflicting_claim(prepared):
        runtime.decision_receipts.save(DecisionReceipt(
            receipt_id="unrelated", card_id="other-tenant-card", card_version=2,
            idempotency_key=prepared.idempotency_key, actor=prepared.actor,
            request_fingerprint="", status=ReceiptStatus.DELIVERY_DISABLED,
            result={"private": "OTHER_TENANT_SENTINEL"},
        ))
        return False

    runtime.decision_receipts.claim = conflicting_claim
    with pytest.raises(Exception, match="already bound") as failure:
        await server.call_tool("evaluate_insight_card", {"card_id": "repeat", "idempotency_key": "raced"})
    assert "OTHER_TENANT_SENTINEL" not in str(failure.value)
    assert not judger.states

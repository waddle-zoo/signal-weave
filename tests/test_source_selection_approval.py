"""Offline adversarial regressions for owner-confirmed source selection.

Use the public MCP functions and real stores; only source/Jev I/O is doubled.
Rejections must leave the persisted card (including its audit) unchanged.
"""

import asyncio
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from test_onboarding import (
    AmbiguousSupersetCatalogDouble,
    BoundedAnchorCatalogDouble,
    ExplicitAnchorJevDouble,
    OnboardingJevDouble,
    SupersetCatalogDouble,
    make_server,
    tool,
)

from signalweave.models import InsightCard
from signalweave.onboarding import InsightAuthoringService

REASON = (
    "Use dashboard:7 for checkout conversion among completed sessions; "
    "dashboard:8 is the finance population and is intentionally excluded."
)
RESOLVABLE = {"definition-conflict", "candidate-selection-review"}


class MutableRankingDouble(OnboardingJevDouble):
    def __init__(self):
        self.scores = {"dashboard:7": 0.94, "dashboard:8": 0.91, "dashboard:9": 0.12}
        self.role = "primary"
        self.rank_started = None
        self.resume_rank = None
        self.compile_started = None
        self.resume_compile = None

    async def compile_plan(self, state, card):
        if self.compile_started is not None:
            self.compile_started.set()
            await self.resume_compile.wait()
        return await super().compile_plan(state, card)

    async def rank_resources(self, goal, resources):
        if self.rank_started is not None:
            self.rank_started.set()
            await self.resume_rank.wait()
        return {
            f"{resource.adapter}|{resource.resource}": self.scores[resource.resource]
            for resource in resources
        }

    async def classify_resource_roles(self, goal, resources):
        return {
            f"{resource.adapter}|{resource.resource}": {"role": self.role, "probability": 0.9}
            for resource in resources
        }


async def draft(server, **overrides):
    arguments = {
        "title": "Owner-confirmed checkout scope",
        "what_to_watch": "Checkout conversion for completed sessions.",
        "why_watch": "Decide whether Growth needs to respond.",
        "watch_for": ["Conversion drops materially."],
        "questions": ["Does checkout conversion warrant a Growth response?"],
        "decision_guidance": "Ignore ordinary variation; notify Growth on a material drop.",
        "sources": [{
            "key": "growth", "adapter": "superset", "resource": "dashboard:7",
            "label": "Growth overview", "parameters": {"chart_ids": ["62"]},
        }],
        "delivery_methods": [{
            "key": "growth-ops", "outcome": "notify", "label": "Growth Ops",
            "destination": "slack://growth-ops",
        }],
        "retrieval_mode": "fixed",
        "investigation_mode": "none",
    }
    arguments.update(overrides)
    return (await tool(server, "draft_insight_card")(**arguments))["card"]["id"]


async def reviewed_case(tmp_path, *, sqlite=False, catalog=None, **draft_options):
    catalog = catalog or AmbiguousSupersetCatalogDouble()
    judger = MutableRankingDouble()
    server = make_server(tmp_path, judger, sqlite=sqlite, catalog=catalog)
    card_id = await draft(server, **draft_options)
    review = (await tool(server, "review_insight_card")(card_id))["review"]
    return server, card_id, review, catalog, judger


def stored(server, card_id):
    return server._test_runtime.card_store.get_card(card_id).model_dump(mode="json")


def save_changed_card(server, card_id, **updates):
    data = stored(server, card_id)
    data.update(updates)
    # A revised policy must not accidentally fail the compiled-plan validator
    # before approval gets a chance to check the review fingerprint.
    data["compiled_plan"] = None
    server._test_runtime.card_store.save_card(InsightCard.model_validate(data))


async def confirm(server, card_id, fingerprint, reason=REASON, **kwargs):
    return await tool(server, "approve_insight_card")(
        card_id, source_selection_fingerprint=fingerprint,
        source_selection_reason=reason, **kwargs,
    )


async def assert_rejected(server, card_id, fingerprint, *, reason=REASON, match):
    before = stored(server, card_id)
    with pytest.raises(ValueError, match=match):
        await confirm(server, card_id, fingerprint, reason)
    assert stored(server, card_id) == before
    assert before["status"] == "draft"
    assert before["approved_by"] is None
    assert before["approved_at"] is None


@pytest.mark.parametrize("sqlite", [False, True], ids=["json", "sqlite"])
async def test_confirmation_persists_exact_scope_and_audit_after_restart(tmp_path, sqlite):
    server, card_id, review, catalog, judger = await reviewed_case(tmp_path, sqlite=sqlite)
    assert {b["code"] for b in review["blockers"]} == RESOLVABLE
    preview = await tool(server, "simulate_insight_card")(card_id)
    assert preview["delivery_enabled"] is False
    before = stored(server, card_id)

    result = await confirm(
        server, card_id, review["source_selection_fingerprint"],
        f"  {REASON}\n", actor="spoofed-owner",
    )
    approved = stored(server, card_id)
    omitted = {"onboarding_review", "onboarding_review_history", "onboarding_corrections", "compiled_plan"}
    assert result["card"] == {k: v for k, v in approved.items() if k not in omitted}
    audit = result["onboarding_review"]
    assert result["status"] == approved["status"] == "approved"
    assert approved["approved_by"] == "test-principal"
    assert approved["approved_at"]
    assert audit["source_selection_confirmation"] == REASON
    assert audit["source_selection_fingerprint"] == review["source_selection_fingerprint"]
    assert set(audit["confirmed_blocker_codes"]) == RESOLVABLE
    assert audit["blockers"] == audit["questions"] == []
    assert audit["readiness_status"] == audit["status"] == "ready_for_approval"
    assert audit["selected_source_refs"] == ["superset|dashboard:7"]
    assert audit["missing_recommended_refs"] == ["superset|dashboard:8"]
    assert audit["ambiguous_candidate_groups"] == review["ambiguous_candidate_groups"]
    assert audit["principal_id"] == "test-principal"
    assert audit["principal_tenant"] == "default"
    assert approved["onboarding_review"] == audit
    assert approved["onboarding_review_history"] == [*before["onboarding_review_history"], audit]
    assert approved["onboarding_review_history"][0]["blockers"] == review["blockers"]
    for field in ("sources", "delivery_methods", "version", "decision_guidance"):
        assert approved[field] == before[field]

    restarted = make_server(tmp_path, judger, sqlite=sqlite, catalog=catalog)
    assert tool(restarted, "get_insight_card")(card_id, include_history=True) == approved


@pytest.mark.parametrize("sqlite", [False, True], ids=["json", "sqlite"])
async def test_legacy_approval_without_confirmation_still_works(tmp_path, sqlite):
    server = make_server(tmp_path, sqlite=sqlite)
    card_id = await draft(server)
    result = await tool(server, "approve_insight_card")(card_id, actor="spoofed-owner")
    assert result["status"] == "approved"
    assert result["card"]["approved_by"] == "test-principal"
    assert result["onboarding_review"]["confirmed_blocker_codes"] == []
    assert result["onboarding_review"]["source_selection_confirmation"] is None


async def test_legacy_call_cannot_silently_resolve_conflicts(tmp_path):
    server, card_id, _, _, _ = await reviewed_case(tmp_path)
    await assert_rejected(server, card_id, None, reason=None, match="definition-conflict")


@pytest.mark.parametrize("blocker", sorted(RESOLVABLE))
async def test_each_confirmable_blocker_can_be_resolved_independently(tmp_path, blocker):
    catalog = SupersetCatalogDouble() if blocker == "candidate-selection-review" else None
    server, card_id, _, _, judger = await reviewed_case(tmp_path, catalog=catalog)
    if blocker == "definition-conflict":
        judger.scores["dashboard:8"] = 0.1
    review = (await tool(server, "review_insight_card")(card_id))["review"]
    assert {item["code"] for item in review["blockers"]} == {blocker}
    result = await confirm(server, card_id, review["source_selection_fingerprint"])
    assert result["status"] == "approved"
    assert result["onboarding_review"]["confirmed_blocker_codes"] == [blocker]


@pytest.mark.parametrize("field,value", [
    ("title", "Changed title"),
    ("what_to_watch", "All sessions, including abandoned checkouts."),
    ("why_watch", "Escalate to a different business owner."),
    ("watch_for", ["Any movement at all."]),
    ("questions", ["Should Finance respond?"]),
    ("decision_guidance", "Notify on every movement."),
    ("follow_up_guidance", "Ask Finance to investigate."),
    ("comparison_windows", ["previous_year"]),
    ("action_confidence_threshold", 0.01),
    ("max_source_age_hours", 8760),
    ("owner", "different-owner"),
    ("version", 2),
    ("max_investigation_sources", 10),
    ("investigation_threshold", 0.01),
])
async def test_card_policy_mutation_invalidates_stored_confirmation(tmp_path, field, value):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    save_changed_card(server, card_id, **{field: value})
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


@pytest.mark.parametrize("field,value", [
    ("resource", "dashboard:8"), ("parameters", {"chart_ids": ["999"]}),
    ("required", False), ("label", "A different population"),
    ("required_comparison_keys", ["previous_year"]),
])
async def test_selected_source_mutation_invalidates_confirmation(tmp_path, field, value):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    sources = stored(server, card_id)["sources"]
    sources[0][field] = value
    save_changed_card(server, card_id, sources=sources)
    assert stored(server, card_id)["sources"][0][field] == value
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


@pytest.mark.parametrize("field,value", [
    ("destination", "slack://unreviewed-channel"),
    ("outcome", "escalate"),
    ("instructions", "Send all evidence to this destination."),
])
async def test_delivery_mutation_invalidates_confirmation(tmp_path, field, value):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    methods = stored(server, card_id)["delivery_methods"]
    methods[0][field] = value
    save_changed_card(server, card_id, delivery_methods=methods)
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


@pytest.mark.parametrize("index", [0, 1], ids=["selected", "omitted"])
@pytest.mark.parametrize("field,value", [
    ("population", "All visitors, including bots"),
    ("grain", "monthly"), ("lineage", ["warehouse|new-table"]),
    ("scope", "New business unit"), ("freshness_sla_hours", 1),
    ("metric_names", ["different_conversion"]),
])
async def test_catalog_contract_changes_invalidate_confirmation(tmp_path, index, field, value):
    server, card_id, review, catalog, _ = await reviewed_case(tmp_path)
    resource = catalog.resources[index]
    catalog.resources[index] = resource.model_copy(update={
        "contract": resource.contract.model_copy(update={field: value}),
    })
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


@pytest.mark.parametrize("field,value", [
    ("title", "Revised visible title"),
    ("description", "Changed metric definition"),
    ("source_url", "https://example.invalid/revised-dashboard"),
])
async def test_catalog_descriptor_changes_invalidate_confirmation(tmp_path, field, value):
    server, card_id, review, catalog, _ = await reviewed_case(tmp_path)
    catalog.resources[1] = catalog.resources[1].model_copy(update={field: value})
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


async def test_catalog_metadata_change_invalidates_confirmation(tmp_path):
    server, card_id, review, catalog, _ = await reviewed_case(tmp_path)
    catalog.resources[0] = catalog.resources[0].model_copy(update={
        "metadata": {"owner": "different-owner", "definition_version": "v2"},
    })
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


@pytest.mark.parametrize("retained", [False, True], ids=["discovered", "retained-anchor"])
async def test_adapter_metadata_is_visible_and_bound_for_discovered_and_retained_anchors(
    tmp_path, retained,
):
    catalog = BoundedAnchorCatalogDouble() if retained else SupersetCatalogDouble()
    index = -1 if retained else 0
    metadata = {"owner": "growth", "definition": {"version": 1, "population": "completed"}}
    resource = catalog.resources[index].model_copy(update={"metadata": metadata})
    catalog.resources[index] = resource
    server = make_server(tmp_path, ExplicitAnchorJevDouble(), catalog=catalog)
    card_id = await draft(server, sources=[{
        "key": "growth", "adapter": resource.adapter,
        "resource": resource.resource, "label": resource.title,
    }])
    review = (await tool(server, "review_insight_card")(card_id))["review"]
    selected = next(candidate for candidate in review["source_candidates"] if candidate["selected"])
    assert selected["metadata"]["adapter_metadata"] == metadata
    assert ("explicit-card-anchor" in selected["retrieval_signals"]) is retained
    assert stored(server, card_id)["onboarding_review"] == review

    changed_metadata = deepcopy(metadata)
    changed_metadata["definition"]["version"] = 2
    catalog.resources[index] = resource.model_copy(update={"metadata": changed_metadata})
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


@pytest.mark.parametrize("change", ["remove", "add"])
async def test_candidate_membership_changes_invalidate_confirmation(tmp_path, change):
    catalog = AmbiguousSupersetCatalogDouble()
    spare = catalog.resources.pop()
    server, card_id, review, catalog, _ = await reviewed_case(tmp_path, catalog=catalog)
    if change == "remove":
        catalog.resources.pop()
    else:
        catalog.resources.append(spare)
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


async def test_scores_roles_order_history_and_corrections_do_not_stale_token(tmp_path):
    server, card_id, review, catalog, judger = await reviewed_case(tmp_path)
    fingerprint = review["source_selection_fingerprint"]
    judger.scores = {"dashboard:7": 0.71, "dashboard:8": 0.98, "dashboard:9": 0.13}
    judger.role = "diagnostic"
    catalog.resources.reverse()
    tool(server, "record_insight_card_correction")(
        card_id, kind="candidate-rejected", source_ref="superset|dashboard:8", note=REASON,
    )
    repeated = (await tool(server, "review_insight_card")(card_id))["review"]
    assert repeated["source_candidates"] != review["source_candidates"]
    assert repeated["source_selection_fingerprint"] == fingerprint
    assert len(stored(server, card_id)["onboarding_review_history"]) == 2
    assert (await confirm(server, card_id, fingerprint))["status"] == "approved"


@pytest.mark.parametrize("kind", ["candidate-rejected", "definition-confirmed"])
async def test_feedback_corrections_alone_never_resolve_blockers(tmp_path, kind):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    tool(server, "record_insight_card_correction")(
        card_id, kind=kind, source_ref="superset|dashboard:8", note=REASON,
    )
    await assert_rejected(server, card_id, None, reason=None, match="definition-conflict")
    current = (await tool(server, "review_insight_card")(card_id))["review"]
    assert current["source_selection_fingerprint"] == review["source_selection_fingerprint"]
    assert {b["code"] for b in current["blockers"]} == RESOLVABLE
    assert current["confirmed_blocker_codes"] == []


@pytest.mark.parametrize("fingerprint,reason", [
    ("valid", None), ("valid", ""), ("valid", " \n\t "),
    (None, REASON), ("", REASON), ("valid", "x" * 4001),
])
async def test_confirmation_requires_both_token_and_bounded_nonblank_reason(
    tmp_path, fingerprint, reason,
):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    if fingerprint == "valid":
        fingerprint = review["source_selection_fingerprint"]
    await assert_rejected(
        server, card_id, fingerprint, reason=reason, match="Provide both",
    )


@pytest.mark.parametrize("token", ["0" * 64, "not-a-review-token", "f" * 65])
async def test_fake_token_is_rejected_without_persisting_audit(tmp_path, token):
    server, card_id, _, _, _ = await reviewed_case(tmp_path)
    await assert_rejected(server, card_id, token, match="stale or missing")


async def test_reason_accepts_unicode_at_documented_length_boundary(tmp_path):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    reason = REASON + "é" * (4000 - len(REASON))
    result = await confirm(server, card_id, review["source_selection_fingerprint"], reason)
    assert result["onboarding_review"]["source_selection_confirmation"] == reason


@pytest.mark.parametrize("stored_review", [None, "legacy-without-fingerprint"])
async def test_fresh_token_requires_matching_persisted_review(tmp_path, stored_review):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    replacement = None
    if stored_review is not None:
        replacement = deepcopy(review)
        replacement.pop("source_selection_fingerprint")
    save_changed_card(server, card_id, onboarding_review=replacement)
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="stale or missing",
    )


async def test_new_fresh_token_cannot_skip_persisting_and_showing_updated_review(tmp_path):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    save_changed_card(server, card_id, decision_guidance="Notify only after owner escalation.")
    runtime = server._test_runtime
    fresh = await InsightAuthoringService(runtime.sources, runtime.engine).review(
        runtime.card_store.get_card(card_id), principal=runtime.principal,
    )
    assert fresh.source_selection_fingerprint != review["source_selection_fingerprint"]
    await assert_rejected(
        server, card_id, fresh.source_selection_fingerprint, match="stale or missing",
    )


async def test_token_cannot_be_replayed_on_another_card(tmp_path):
    server, _, review, _, _ = await reviewed_case(tmp_path)
    other = await draft(server)
    await tool(server, "review_insight_card")(other)
    await assert_rejected(server, other, review["source_selection_fingerprint"], match="stale")


@pytest.mark.parametrize("updates,match", [
    ({"principal_id": "another-user"}, "stale or missing"),
    ({"scopes": ["different-scope"]}, "stale or missing"),
    ({"authorization_source": "different-gateway"}, "stale or missing"),
    ({"tenant_id": "foreign-tenant"}, "outside the authenticated principal tenant"),
])
async def test_confirmation_is_bound_to_trusted_principal(tmp_path, updates, match):
    server, card_id, review, _, _ = await reviewed_case(tmp_path)
    runtime = server._test_runtime
    runtime.principal = runtime.principal.model_copy(update=updates)
    await assert_rejected(server, card_id, review["source_selection_fingerprint"], match=match)


@pytest.mark.parametrize("mutation", ["revoked", "foreign-tenant", "removed"])
async def test_confirmation_cannot_bypass_lost_source_authorization(tmp_path, mutation):
    server, card_id, review, catalog, _ = await reviewed_case(tmp_path)
    if mutation == "removed":
        catalog.resources.pop(0)
    else:
        resource = catalog.resources[0]
        updates = {"authorized": False} if mutation == "revoked" else {"tenant_id": "foreign"}
        catalog.resources[0] = resource.model_copy(update={
            "contract": resource.contract.model_copy(update=updates),
        })
    await assert_rejected(server, card_id, review["source_selection_fingerprint"], match="stale")
    current = (await tool(server, "review_insight_card")(card_id))["review"]
    assert "selection-outside-discovery" in {b["code"] for b in current["blockers"]}
    await assert_rejected(
        server, card_id, current["source_selection_fingerprint"], match="selection-outside-discovery",
    )


@pytest.mark.parametrize("retrieval,investigation", [
    ("expand", "none"), ("fixed", "bounded"), ("expand", "bounded"),
])
async def test_dynamic_modes_cannot_resolve_source_selection(tmp_path, retrieval, investigation):
    server, card_id, review, _, _ = await reviewed_case(
        tmp_path, retrieval_mode=retrieval, investigation_mode=investigation,
    )
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"],
        match="requires retrieval_mode=fixed and investigation_mode=none",
    )


@pytest.mark.parametrize("status", ["stale", "failed", "ambiguous", "unknown"])
@pytest.mark.parametrize("index", [0, 1], ids=["selected", "recommended"])
async def test_confirmation_cannot_resolve_source_health_even_with_current_token(
    tmp_path, status, index,
):
    catalog = AmbiguousSupersetCatalogDouble()
    resource = catalog.resources[index]
    catalog.resources[index] = resource.model_copy(update={
        "contract": resource.contract.model_copy(update={"source_status": status}),
    })
    server, card_id, review, _, _ = await reviewed_case(tmp_path, catalog=catalog)
    assert RESOLVABLE < {b["code"] for b in review["blockers"]}
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="source-health-review",
    )


async def test_fresh_health_blocker_still_fails_when_score_change_preserves_token(tmp_path):
    catalog = AmbiguousSupersetCatalogDouble()
    resource = catalog.resources[2]
    catalog.resources[2] = resource.model_copy(update={
        "contract": resource.contract.model_copy(update={"source_status": "failed"}),
    })
    server, card_id, review, _, judger = await reviewed_case(tmp_path, catalog=catalog)
    assert {b["code"] for b in review["blockers"]} == RESOLVABLE
    judger.scores["dashboard:9"] = 0.99
    # The unhealthy descriptor was already in the reviewed catalog. Only its
    # recommendation changed, so token equality must not suppress fresh blockers.
    await assert_rejected(
        server, card_id, review["source_selection_fingerprint"], match="source-health-review",
    )


async def test_new_health_failure_invalidates_token_and_cannot_be_acknowledged(tmp_path):
    server, card_id, review, catalog, _ = await reviewed_case(tmp_path)
    resource = catalog.resources[0]
    catalog.resources[0] = resource.model_copy(update={
        "contract": resource.contract.model_copy(update={"source_status": "failed"}),
    })
    await assert_rejected(server, card_id, review["source_selection_fingerprint"], match="stale")
    fresh = (await tool(server, "review_insight_card")(card_id))["review"]
    assert fresh["source_selection_fingerprint"] != review["source_selection_fingerprint"]
    await assert_rejected(
        server, card_id, fresh["source_selection_fingerprint"], match="source-health-review",
    )


@pytest.mark.parametrize("options,code", [
    ({"decision_guidance": ""}, "decision-guidance-required"),
    ({"watch_for": [], "questions": []}, "intent-detail-required"),
])
async def test_confirmation_cannot_resolve_missing_policy_or_intent(tmp_path, options, code):
    server, card_id, review, _, _ = await reviewed_case(tmp_path, **options)
    assert RESOLVABLE < {b["code"] for b in review["blockers"]}
    await assert_rejected(server, card_id, review["source_selection_fingerprint"], match=code)


@pytest.mark.parametrize("sqlite", [False, True], ids=["json", "sqlite"])
async def test_card_revision_during_fresh_review_is_not_overwritten_or_approved(tmp_path, sqlite):
    server, card_id, review, _, judger = await reviewed_case(tmp_path, sqlite=sqlite)
    judger.rank_started = asyncio.Event()
    judger.resume_rank = asyncio.Event()
    approval = asyncio.create_task(confirm(server, card_id, review["source_selection_fingerprint"]))
    try:
        await asyncio.wait_for(judger.rank_started.wait(), timeout=5)
        save_changed_card(server, card_id, version=2, decision_guidance="Never notify automatically.")
        changed = stored(server, card_id)
        judger.resume_rank.set()
        try:
            result = await asyncio.wait_for(approval, timeout=5)
        except ValueError:
            result = None
        assert stored(server, card_id) == changed, "approval overwrote a concurrent policy revision"
        assert result is None, "approval accepted a token for a superseded card revision"
    finally:
        judger.resume_rank.set()
        if not approval.done():
            approval.cancel()
        await asyncio.gather(approval, return_exceptions=True)


@pytest.mark.parametrize("sqlite", [False, True], ids=["json", "sqlite"])
@pytest.mark.parametrize("stage", ["review", "approval-compile"])
@pytest.mark.parametrize("mutation", ["same-version-policy", "correction"])
async def test_review_and_compile_awaits_preserve_concurrent_card_changes(
    tmp_path, sqlite, stage, mutation,
):
    server, card_id, review, _, judger = await reviewed_case(tmp_path, sqlite=sqlite)
    started, resume = asyncio.Event(), asyncio.Event()
    if stage == "review":
        judger.rank_started, judger.resume_rank = started, resume
        operation = tool(server, "review_insight_card")(card_id)
        error = "Card changed during review"
    else:
        # Compiled state is intentionally excluded from the selection token.
        # Force the real approval path to await compilation after fresh review.
        save_changed_card(server, card_id, compiled_plan=None)
        judger.compile_started, judger.resume_compile = started, resume
        operation = confirm(server, card_id, review["source_selection_fingerprint"])
        error = "Card changed during approval"
    pending = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        before = stored(server, card_id)
        if mutation == "same-version-policy":
            methods = deepcopy(before["delivery_methods"])
            methods[0]["destination"] = "slack://new-owner-destination"
            save_changed_card(server, card_id, delivery_methods=methods)
        else:
            tool(server, "record_insight_card_correction")(
                card_id, kind="intent-clarified", note="Owner added context during the request.",
            )
        changed = stored(server, card_id)
        assert changed != before
        assert changed["version"] == before["version"]
        assert changed["onboarding_review"] == before["onboarding_review"]
        resume.set()
        with pytest.raises(ValueError, match=error):
            await asyncio.wait_for(pending, timeout=5)
        assert stored(server, card_id) == changed
        assert changed["status"] == "draft"
        restarted = make_server(tmp_path, sqlite=sqlite)
        assert tool(restarted, "get_insight_card")(card_id, include_history=True) == changed
    finally:
        resume.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("name,valid,invalid", [
    ("record_insight_card_correction", "candidate-rejected", "candidate_rejected"),
    ("record_decision_feedback", "useful", "arbitrary-feedback"),
])
def test_correction_and_feedback_kinds_are_advertised_as_bounded_mcp_enums(
    tmp_path, name, valid, invalid,
):
    server = make_server(tmp_path)
    schema = server._tool_manager.get_tool(name).parameters
    field = "card_id" if name == "record_insight_card_correction" else "idempotency_key"
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors({field: "example", "kind": valid}))
    errors = list(validator.iter_errors({field: "example", "kind": invalid}))
    assert any(error.validator == "enum" and list(error.path) == ["kind"] for error in errors)
    assert "kind" in schema["required"]


async def test_correction_tool_rejects_invalid_enum_without_persisting(tmp_path):
    server, card_id, _, _, _ = await reviewed_case(tmp_path)
    before = stored(server, card_id)
    with pytest.raises(ValueError, match="OnboardingCorrectionKind"):
        tool(server, "record_insight_card_correction")(
            card_id, kind="resolve-all-blockers", note=REASON,
        )
    assert stored(server, card_id) == before

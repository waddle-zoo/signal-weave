"""Offline MCP acceptance integrity, not evidence of model quality."""

import copy

import pytest
from test_onboarding import OnboardingJevDouble, make_server, tool

from signalweave.models import Outcome


class AcceptanceDouble(OnboardingJevDouble):
    async def judge(self, state, card, plan, observations):
        result = await super().judge(state, card, plan, observations)
        # An explicit offline transport double, never a production heuristic.
        value = observations[0].current
        outcome = Outcome.IGNORE if value == 0 else Outcome.INSUFFICIENT_DATA if value == 1 else Outcome.NOTIFY
        return result.model_copy(update={
            "outcome": outcome, "probabilities": {outcome.value: 1.0},
            "delivery_methods": [m for m in card.delivery_methods if m.outcome == outcome],
        })


async def setup(tmp_path, *, sqlite=False):
    server = make_server(tmp_path, judger=AcceptanceDouble(), sqlite=sqlite)
    drafted = await tool(server, "draft_insight_card")(
        title="Reviewed investigation", what_to_watch="Checkout conversion",
        why_watch="Route meaningful changes to the operating owner",
        questions=["What changed in the approved checkout population?"],
        decision_guidance="Notify the owner for a meaningful decline; ignore quiet periods; insufficient_data for missing evidence.",
        sources=[{"key": "growth", "adapter": "superset", "resource": "dashboard:7", "label": "Growth"}],
        delivery_methods=[{"key": "owner", "outcome": "notify", "label": "Owner", "destination": "sink:opaque"}],
    )
    card_id = drafted["card"]["id"]
    preview = await tool(server, "simulate_insight_card")(card_id)
    cases = []
    for value, outcome in enumerate(("ignore", "insufficient_data", "notify")):
        resources = copy.deepcopy(preview["resources"])
        resources[0]["observations"][0]["current"] = value
        cases.append({
            "id": f"owner-example-{value}", "resources": resources,
            "expected_outcome": outcome,
            "expected_delivery_method_keys": ["owner"] if outcome == "notify" else [],
            "expected_delivery_destinations": {"owner": "sink:opaque"} if outcome == "notify" else {},
            "required_evidence_source_keys": ["growth"],
            "expected_retrieval_refs": ["superset|dashboard:7"],
        })
    return server, card_id, cases


@pytest.mark.parametrize("sqlite", [False, True])
async def test_acceptance_report_binds_tested_card_before_owner_approval(tmp_path, sqlite):
    server, card_id, cases = await setup(tmp_path, sqlite=sqlite)
    report = await tool(server, "evaluate_card_workflow")(
        card_id, cases, acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
    )
    assert report["acceptance_passed"] is True
    assert tool(server, "get_insight_card")(card_id)["status"] == "draft"
    accepted = await tool(server, "approve_insight_card")(
        card_id, workflow_report_id=report["certification_report_id"],
    )
    assert accepted["workflow_acceptance"] == {
        "status": "passed", "report_id": report["certification_report_id"],
        "human_authorization_required": True,
    }
    assert accepted["status"] == "approved"
    readiness = tool(server, "get_enterprise_readiness")()
    assert readiness["cards"][0]["workflow_certification"]["acceptance_current"] is True
    assert "workflow-acceptance-missing-or-stale" not in {gate["code"] for gate in readiness["gates"]}


@pytest.mark.parametrize("mutation", ["policy", "endpoint", "plan", "source", "version"])
async def test_same_version_edits_cannot_reuse_acceptance(tmp_path, mutation):
    server, card_id, cases = await setup(tmp_path)
    report = await tool(server, "evaluate_card_workflow")(
        card_id, cases, acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
    )
    assert report["acceptance_passed"]
    card = server._test_runtime.card_store.get_card(card_id)
    if mutation == "policy":
        card.decision_guidance = "Notify on every change."
    elif mutation == "endpoint":
        card.delivery_methods[0].destination = "sink:unreviewed"
    elif mutation == "plan":
        card.compiled_plan.capabilities = []
    elif mutation == "source":
        card.sources[0].parameters["chart_ids"] = ["unknown"]
    else:
        card.version += 1
        card.compiled_plan = None
    server._test_runtime.card_store.save_card(card)
    with pytest.raises(ValueError, match="acceptance report"):
        await tool(server, "approve_insight_card")(
            card_id, workflow_report_id=report["certification_report_id"],
        )
    assert server._test_runtime.card_store.get_card(card_id).status.value == "draft"


async def test_preview_and_partial_replay_are_not_acceptance(tmp_path):
    server, card_id, cases = await setup(tmp_path)
    report = await tool(server, "evaluate_card_workflow")(card_id, cases[:1])
    assert report["status"] == "approved"
    with pytest.raises(ValueError, match="acceptance report"):
        await tool(server, "approve_insight_card")(
            card_id, workflow_report_id=report["certification_report_id"],
        )
    # Low-level owner authorization remains available, but cannot claim testing.
    approved = await tool(server, "approve_insight_card")(card_id)
    assert approved["workflow_acceptance"]["status"] == "unassessed"
    ready = tool(server, "get_enterprise_readiness")()
    assert "workflow-acceptance-missing-or-stale" in {gate["code"] for gate in ready["gates"]}


async def test_wrong_endpoint_blocks_acceptance_without_changing_expected_answer(tmp_path):
    server, card_id, cases = await setup(tmp_path)
    cases[-1]["expected_delivery_destinations"] = {"owner": "sink:the-real-owner"}
    report = await tool(server, "evaluate_card_workflow")(
        card_id, cases, acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
    )
    assert report["acceptance_passed"] is False
    with pytest.raises(ValueError, match="acceptance report"):
        await tool(server, "approve_insight_card")(
            card_id, workflow_report_id=report["certification_report_id"],
        )


async def test_acceptance_cannot_supply_foreign_tenant_snapshots(tmp_path):
    server, card_id, cases = await setup(tmp_path)
    cases[0]["resources"][0]["contract"]["tenant_id"] = "other-company"
    with pytest.raises(ValueError, match="outside the authenticated principal"):
        await tool(server, "evaluate_card_workflow")(
            card_id, cases, acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
        )
    assert tool(server, "list_certification_reports")()["count"] == 0


async def test_acceptance_record_cannot_approve_another_card(tmp_path):
    server, card_id, cases = await setup(tmp_path)
    report = await tool(server, "evaluate_card_workflow")(
        card_id, cases, acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
    )
    copy_card = server._test_runtime.card_store.get_card(card_id).model_copy(deep=True)
    copy_card.id = "other-card"
    copy_card.compiled_plan.card_id = copy_card.id
    server._test_runtime.card_store.save_card(copy_card)
    with pytest.raises(ValueError, match="acceptance report"):
        await tool(server, "approve_insight_card")(
            copy_card.id, workflow_report_id=report["certification_report_id"],
        )

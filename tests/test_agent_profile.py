from __future__ import annotations

import pytest
import typesafe_sdk

from signalweave.mcp_server import AGENT_PROFILE_TOOLS, CARD_AUTHORING_GUIDANCE, create_mcp
from signalweave.models import InsightCardStatus, InvestigationMode, PrincipalContext, RetrievalMode
from signalweave.runtime import AgentOwnedJudger, build_runtime
from signalweave.typesafe_adapter import JevJudger
from tests.test_diagnostics import comparison
from tests.test_local_investigation import make_runtime
from tests.test_typesafe_adapter import FakeClient, FakeNoul, FakeScore


def test_default_factory_uses_configured_runtime_without_keyless_mode(monkeypatch, tmp_path):
    runtime, _, _ = make_runtime(tmp_path)
    calls = []

    def configured_runtime(*args, **kwargs):
        calls.append((args, kwargs))
        return runtime

    monkeypatch.setattr("signalweave.mcp_server.build_runtime", configured_runtime)
    server = create_mcp()
    assert calls == [((), {})]
    assert "calls Jev for the card's typed policy judgment" in server.instructions


@pytest.mark.parametrize("profile", ["agent", "full"])
def test_source_health_runtime_is_rejected_before_serving_card_tools(tmp_path, profile):
    runtime, _, _ = make_runtime(tmp_path)
    runtime.engine.judger = AgentOwnedJudger()
    with pytest.raises(RuntimeError, match="source-health runtime cannot serve card decisions"):
        create_mcp(runtime, profile=profile)


def test_authoring_distinguishes_coverage_bindings_from_numeric_analysis_and_example_dates():
    assert "contract.comparison_contracts keys or applicable analytical_comparisons keys" in CARD_AUTHORING_GUIDANCE
    assert "scalar coverage contract does not require a decomposable analytical comparison" in CARD_AUTHORING_GUIDANCE
    assert "Do not leave a known coverage requirement unbound" in CARD_AUTHORING_GUIDANCE
    assert "dates and values of the onboarding example" in CARD_AUTHORING_GUIDANCE
    assert "only when the owner explicitly requests it" in CARD_AUTHORING_GUIDANCE


async def test_agent_profile_exposes_only_the_repeated_analysis_surface(tmp_path):
    runtime, _, _ = make_runtime(tmp_path)
    server = create_mcp(runtime)
    names = {tool.name for tool in await server.list_tools()}

    assert names == AGENT_PROFILE_TOOLS
    assert "evaluate_insight_card" in names
    assert "get_decision_receipt" in names
    assert "prepare_insight_run" not in names
    assert "evaluate_card_workflow" not in names
    assert "propose_metric_query_card" not in names
    assert "calls Jev for the card's typed policy judgment" in server.instructions
    guide = next(tool for tool in await server.list_tools() if tool.name == "get_signalweave_guide")
    assert guide.inputSchema["properties"]["task"]["enum"] == ["start", "monitor"]
    evaluation = next(tool for tool in await server.list_tools() if tool.name == "evaluate_insight_card")
    assert evaluation.inputSchema["properties"]["response_mode"]["default"] == "compact"
    receipt = next(tool for tool in await server.list_tools() if tool.name == "get_decision_receipt")
    assert {"result_path", "offset", "limit"} <= receipt.inputSchema["properties"].keys()

    paths = {getattr(route, "path", None) for route in server.streamable_http_app().routes}
    assert "/webhooks/evaluate" not in paths

    full = create_mcp(runtime, profile="full")
    full_names = {tool.name for tool in await full.list_tools()}
    assert "evaluate_insight_card" in full_names
    full_paths = {getattr(route, "path", None) for route in full.streamable_http_app().routes}
    assert "/webhooks/evaluate" in full_paths


async def test_full_profile_source_handoff_fetches_exact_card_sources_without_jev(tmp_path):
    runtime, source, judger = make_runtime(tmp_path)
    server = create_mcp(runtime, profile="full")

    _, result = await server.call_tool("prepare_insight_run", {"card_id": "repeat"})

    assert result["status"] == "fetched"
    assert result["persisted"] is False
    assert result["jev_used"] is False
    assert result["decision_made"] is False
    assert result["delivery_enabled"] is False
    assert result["card"]["id"] == "repeat"
    assert result["sources"][0]["source_key"] == "measurement"
    assert source.calls == 1
    assert judger.states == []


async def test_prepare_insight_run_rejects_drafts_and_runtime_expansion(tmp_path):
    runtime, _, _ = make_runtime(tmp_path, approved=False)
    server = create_mcp(runtime, profile="full")
    with pytest.raises(Exception, match="owner-approved"):
        await server.call_tool("prepare_insight_run", {"card_id": "repeat"})

    card = runtime.card_store.get_card("repeat").model_copy(
        update={"status": InsightCardStatus.APPROVED, "retrieval_mode": RetrievalMode.EXPAND}
    )
    runtime.card_store.save_card(card)
    with pytest.raises(Exception, match="fixed card sources only"):
        await server.call_tool("prepare_insight_run", {"card_id": "repeat"})

    card = card.model_copy(update={
        "retrieval_mode": RetrievalMode.FIXED,
        "investigation_mode": InvestigationMode.BOUNDED,
    })
    runtime.card_store.save_card(card)
    with pytest.raises(Exception, match="fixed card sources only"):
        await server.call_tool("prepare_insight_run", {"card_id": "repeat"})


async def test_agent_profile_card_lifecycle_runs_approved_card_through_jev(monkeypatch, tmp_path):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Choice", FakeScore)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)

    runtime, source, _ = make_runtime(tmp_path)
    runtime.engine.judger = JevJudger(api_key="synthetic-test-key")
    runtime.principal = PrincipalContext(principal_id="agent", tenant_id="local")
    existing_card = runtime.card_store.get_card("repeat").model_copy(
        update={"principal_tenant": "local"}
    )
    runtime.card_store.save_card(existing_card)
    original_list = source.list_resources

    async def tenant_resources():
        resources = await original_list()
        return [
            item.model_copy(update={
                "contract": item.contract.model_copy(update={
                    "tenant_id": "local",
                    "available_comparison_windows": ["previous_period"],
                })
            })
            for item in resources
        ]

    source.list_resources = tenant_resources
    server = create_mcp(runtime)

    _, existing = await server.call_tool("list_insight_cards", {})
    assert [card["id"] for card in existing["cards"]] == ["repeat"]

    _, candidates = await server.call_tool("search_catalog", {"query": "partition"})
    candidate = candidates["resources"][0]
    assert f"{candidate['adapter']}|{candidate['resource']}" == "measurements|partition"

    _, inspected = await server.call_tool("inspect_resource", {
        "adapter": candidate["adapter"],
        "resource": candidate["resource"],
        "label": candidate["title"],
    })
    assert inspected["analytical_comparisons"]

    _, onboarding = await server.call_tool("onboard_insight_card", {
        "title": "Recurring activity review",
        "what_to_watch": "Changes in activity and its concentration.",
        "why_watch": "Help the operations team decide what deserves follow-up.",
        "decision_guidance": (
            "Ignore movement under 10%. Investigate an unexplained decline. Notify the growth owner "
            "when the comparable total declines at least 10%. Missing or conflicting evidence is "
            "insufficient data and must never notify."
        ),
        "questions": ["What changed in the latest comparison?"],
        "comparison_windows": ["previous_period"],
        "delivery_methods": [{
            "key": "growth-owner",
            "outcome": "notify",
            "label": "Growth owner",
            "destination": "agent://growth-owner",
        }],
        "selected_sources": [{
            "ref": f"{candidate['adapter']}|{candidate['resource']}",
            "key": "measurement",
            "label": candidate["title"],
        }],
    })
    assert onboarding["approval_required"] is True
    card_id = onboarding["card"]["id"]

    _, review = await server.call_tool("review_insight_card", {
        "card_id": card_id,
        "response_mode": "compact",
    })
    assert review["review"]["readiness_status"] == "ready_for_approval", [
        (blocker["code"], blocker["message"])
        for blocker in review["review"]["blockers"]
    ]

    _, approved = await server.call_tool("approve_insight_card", {
        "card_id": card_id,
        "actor": "owner-after-review",
    })
    assert approved["status"] == "approved"

    calls_before = source.calls
    _, first_run = await server.call_tool("evaluate_insight_card", {
        "card_id": card_id,
        "idempotency_key": "growth:day-1",
        "response_mode": "compact",
    })
    assert source.calls == calls_before + 1
    assert first_run["result"]["outcome"] == "notify"
    assert first_run["result"]["analyses"][0]["current"] == 80
    assert first_run["result"]["evaluator"] == "jev-latest"
    assert first_run["result"]["probabilities"]["notify"] == 0.93
    assert first_run["receipt"]["delivery_enabled"] is False
    assert len(FakeClient.calls) == 1
    assert set(FakeClient.calls[0]["questions"]) == {"question_0", "outcome"}

    _, receipt = await server.call_tool("get_decision_receipt", {
        "receipt_id": first_run["receipt"]["receipt_id"],
    })
    assert receipt["result"]["outcome"] == "notify"
    assert len(FakeClient.calls) == 1

    source.data = comparison(
        current_total={"value": 90},
        segments=[
            {"segment": "online", "baseline": {"value": 60}, "current": {"value": 40}},
            {"segment": "store", "baseline": {"value": 40}, "current": {"value": 50}},
        ],
    )
    calls_before = source.calls
    _, next_run = await server.call_tool("evaluate_insight_card", {
        "card_id": card_id,
        "idempotency_key": "growth:day-2",
        "response_mode": "compact",
    })
    assert source.calls == calls_before + 1
    assert next_run["result"]["analyses"][0]["current"] == 90
    assert next_run["result"]["evaluator"] == "jev-latest"
    assert len(FakeClient.calls) == 2
    assert next_run["receipt"]["delivery_enabled"] is False

def test_source_preflight_runtime_is_keyless_but_is_not_the_card_decision_runtime(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_ALLOW_EMPTY_SOURCES", "1")

    runtime = build_runtime(mode="agent")

    assert runtime.engine.judger.name == "agent-owned"

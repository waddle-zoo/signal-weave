"""Offline end-to-end diagnostic for raw Superset shadow readiness.

These tests exercise source-contract gates, not business-outcome quality or
enterprise readiness. Ordinary chart query parameters remain provenance; the
fixture deliberately supplies no SignalWeave metric/population/grain contract.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import Evidence, InsightResult, Outcome, PrincipalContext
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteDecisionReceiptStore, SQLiteInsightCardStore
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient

TENANT_ID = "offline-superset-tenant"
SOURCE_REF = "superset|chart:1"
WINDOW = "previous_period"
IDEMPOTENCY_KEY = "offline-raw-superset-shadow"

QUERY_PARAMS = {
    "datasource": "17__table",
    "metrics": [
        {
            "expressionType": "SQL",
            "sqlExpression": "SUM(order_total)",
            "label": "SUM(order_total)",
        }
    ],
    "granularity_sqla": "month",
    "groupby": ["region"],
    "time_range": "Last 2 months",
    "row_limit": 100,
}

CHART_ROWS = [
    {"month": "2026-09", "region": "North", "SUM(order_total)": 120.0},
    {"month": "2026-10", "region": "North", "SUM(order_total)": 135.0},
    {"month": "2026-09", "region": "South", "SUM(order_total)": 80.0},
    {"month": "2026-10", "region": "South", "SUM(order_total)": 75.0},
]


class RecordingJudge:
    """Deterministic offline provider double; never calls Jev or another service."""

    name = "recording-offline-judge"
    skip_semantic_compile = True

    def __init__(self) -> None:
        self.judge_calls = 0

    async def rank_resources(self, goal: str, resources: list[Any]) -> dict[str, float]:
        del goal
        return {f"{item.adapter}|{item.resource}": 1.0 for item in resources}

    async def compile_plan(self, state: dict[str, Any], card: Any) -> dict[str, Any]:
        del state
        return {
            "capabilities": ["percent_change", "baseline_comparison"],
            "baseline": card.comparison_windows[0],
        }

    async def select_investigation_sources(
        self, state: dict[str, Any], card: Any, plan: Any,
        candidates: list[Any], max_sources: int,
    ) -> dict[str, Any]:
        del state, card, plan, candidates, max_sources
        return {"probability": 0.0, "selections": []}

    async def judge(
        self, state: dict[str, Any], card: Any, plan: Any, observations: list[Any],
    ) -> InsightResult:
        del plan
        self.judge_calls += 1
        return InsightResult(
            card_id=card.id,
            outcome=Outcome.IGNORE,
            summary="Offline contract diagnostic only.",
            rationale="The deterministic test double does not judge business meaning.",
            confidence=1.0,
            probabilities={Outcome.IGNORE.value: 1.0},
            delivery_methods=[],
            evidence=[Evidence.model_validate(item) for item in state["evidence"]],
            observations=observations,
            source_keys=[item["source_key"] for item in state["sources"]],
            evaluator=self.name,
        )


def _server(tmp_path, *, comparison_windows: list[str] | None):
    requests: list[tuple[str, str]] = []
    chart_metadata: dict[str, Any] = {
        "id": "1",
        "slice_name": "Monthly order totals by region",
        "description": "Ordinary saved Superset chart.",
        "viz_type": "table",
        "tenant_id": TENANT_ID,
        "params": QUERY_PARAMS,
    }
    if comparison_windows is not None:
        # This is the only SignalWeave-adjacent declaration in the fixture.
        # It isolates the typed metric/population/grain gate from window support.
        chart_metadata["available_comparison_windows"] = comparison_windows

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/api/v1/chart/1":
            return httpx.Response(200, json={"result": chart_metadata})
        if request.method == "POST" and request.url.path == "/api/v1/chart/data":
            return httpx.Response(200, json={"result": [{"data": CHART_ROWS}]})
        raise AssertionError(f"unexpected offline Superset request: {request.method} {request.url.path}")

    client = SupersetClient(
        "https://superset.offline.test", transport=httpx.MockTransport(handler)
    )
    adapter = SupersetAdapter(client, tenant_id=TENANT_ID)
    sources = SourceRegistry([adapter], authorized_tenants=[TENANT_ID])
    principal = PrincipalContext(
        principal_id="offline-agent-principal", tenant_id=TENANT_ID
    )
    store_path = tmp_path / "signalweave.sqlite"
    judge = RecordingJudge()
    runtime = Runtime(
        card_store=SQLiteInsightCardStore(store_path),
        sources=sources,
        engine=InsightEngine(judge, registry=sources),
        decision_receipts=SQLiteDecisionReceiptStore(store_path),
        principal=principal,
    )
    return create_mcp(runtime, profile="agent"), judge, requests


async def _dispatch_json(server, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call the public MCP JSON surface, not an internal tool function."""
    response = await server.call_tool(name, arguments)
    if isinstance(response, tuple):
        payload = response[1]
        if isinstance(payload, dict):
            return payload
        response = response[0]
    if getattr(response, "isError", False):
        message = " ".join(
            item.text for item in getattr(response, "content", [])
            if getattr(item, "type", None) == "text"
        )
        raise RuntimeError(message or f"MCP tool {name} failed")
    if isinstance(response, dict):
        return response
    text = next(
        item.text for item in response
        if getattr(item, "type", None) == "text"
    )
    return json.loads(text)


async def _onboard(server, outcome: str | None = None) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "title": "Raw Superset shadow readiness",
        "what_to_watch": "Monthly order totals by region",
        "why_watch": "Inspect an ordinary saved chart in a delivery-disabled run.",
        "decision_guidance": (
            "Observe the chart evidence without inferring business definitions."
            if outcome is None
            else {
                "investigate": "Investigate the source evidence when a material movement appears.",
                "notify": "Notify the chart owner when the source evidence supports a material movement.",
                "escalate": "Escalate to the chart owner when the source evidence supports a material movement.",
            }[outcome]
        ),
        "selected_sources": [{"ref": SOURCE_REF, "key": "primary"}],
    }
    if outcome is not None:
        arguments["delivery_methods"] = [{
            "key": outcome,
            "outcome": outcome,
            "label": outcome.title(),
            "destination": f"agent://{outcome}",
        }]
    return await _dispatch_json(server, "onboard_insight_card", arguments)


async def _inspect_chart(server) -> dict[str, Any]:
    return await _dispatch_json(server, "inspect_resource", {
        "adapter": "superset",
        "resource": "chart:1",
        "label": "Monthly order totals by region",
    })


def _assert_raw_chart_has_no_business_contract(snapshot: dict[str, Any]) -> None:
    contract = snapshot["contract"]
    assert contract["roles"] == ["primary"]
    assert not contract.get("metric_names")
    assert not contract.get("metric_definitions")
    assert not contract.get("comparison_contracts")
    assert not contract.get("required_comparison_keys")
    assert not contract.get("population")
    assert not contract.get("grain")
    saved_parameters = snapshot["metadata"]["saved_query_definition"]["parameters"]
    assert saved_parameters["metrics"] == QUERY_PARAMS["metrics"]
    assert saved_parameters["granularity_sqla"] == "month"
    assert saved_parameters["groupby"] == ["region"]
    assert saved_parameters["time_range"] == "Last 2 months"
    assert len(snapshot["observations"]) == 3  # overall series plus the two region series
    assert {item["metric"] for item in snapshot["observations"]} == {"SUM(order_total)"}


@pytest.mark.asyncio
async def test_raw_superset_chart_without_routes_can_run_agent_shadow_without_business_contract(tmp_path):
    server, judge, requests = _server(
        tmp_path, comparison_windows=[WINDOW]
    )
    public_tools = {item.name for item in await server.list_tools()}
    assert {"inspect_resource", "onboard_insight_card", "review_insight_card",
            "approve_insight_card", "evaluate_insight_card", "get_decision_receipt"} <= public_tools

    snapshot = await _inspect_chart(server)
    _assert_raw_chart_has_no_business_contract(snapshot)
    assert snapshot["contract"]["available_comparison_windows"] == [WINDOW]

    draft = await _onboard(server)
    assert draft["card"]["delivery_methods"] == []
    card_id = draft["card"]["id"]
    reviewed = await _dispatch_json(server, "review_insight_card", {"card_id": card_id})
    review = reviewed.get("review", reviewed)
    assert review["readiness_status"] == "ready_for_approval"
    assert "source-contract-required" not in {
        item["code"] for item in review["blockers"]
    }

    approved = await _dispatch_json(server, "approve_insight_card", {"card_id": card_id})
    assert approved["status"] == "approved"
    evaluated = await _dispatch_json(server, "evaluate_insight_card", {
        "card_id": card_id,
        "idempotency_key": IDEMPOTENCY_KEY,
    })
    assert evaluated["receipt"]["delivery_mode"] == "shadow"
    assert evaluated["receipt"]["status"] == "delivery_disabled"
    assert evaluated["receipt"]["delivery_enabled"] is False
    assert evaluated["receipt"]["delivery_method_keys"] == []
    assert evaluated["result"]["delivery_methods"] == []
    assert judge.judge_calls == 1

    persisted = await _dispatch_json(server, "get_decision_receipt", {
        "idempotency_key": IDEMPOTENCY_KEY,
    })
    assert persisted["receipt"]["status"] == "delivery_disabled"
    assert persisted["receipt"]["delivery_mode"] == "shadow"
    assert requests


@pytest.mark.parametrize("outcome", ["notify", "investigate", "escalate"])
@pytest.mark.asyncio
async def test_raw_superset_chart_declared_window_still_blocks_each_action_route_without_typed_contract(
    tmp_path, outcome: str,
):
    server, judge, _requests = _server(tmp_path, comparison_windows=[WINDOW])
    snapshot = await _inspect_chart(server)
    _assert_raw_chart_has_no_business_contract(snapshot)
    assert snapshot["contract"]["available_comparison_windows"] == [WINDOW]

    draft = await _onboard(server, outcome)
    card_id = draft["card"]["id"]
    reviewed = await _dispatch_json(server, "review_insight_card", {"card_id": card_id})
    review = reviewed.get("review", reviewed)
    blocker_codes = {item["code"] for item in review["blockers"]}
    assert review["readiness_status"] == "blocked"
    assert "source-contract-required" in blocker_codes
    assert "comparison-window-mismatch" not in blocker_codes
    assert any(item["refs"] == [SOURCE_REF] for item in review["blockers"]
               if item["code"] == "source-contract-required")

    with pytest.raises(Exception, match="source-contract-required"):
        await _dispatch_json(server, "approve_insight_card", {"card_id": card_id})
    stored = await _dispatch_json(server, "get_insight_card", {"card_id": card_id})
    assert stored["status"] == "draft"
    assert judge.judge_calls == 0


@pytest.mark.asyncio
async def test_raw_superset_undeclared_window_is_a_distinct_route_blocker(tmp_path):
    server, judge, _requests = _server(tmp_path, comparison_windows=None)
    snapshot = await _inspect_chart(server)
    _assert_raw_chart_has_no_business_contract(snapshot)
    assert snapshot["contract"]["available_comparison_windows"] == []

    draft = await _onboard(server, "notify")
    card_id = draft["card"]["id"]
    reviewed = await _dispatch_json(server, "review_insight_card", {"card_id": card_id})
    review = reviewed.get("review", reviewed)
    blocker_codes = {item["code"] for item in review["blockers"]}
    assert "comparison-window-mismatch" in blocker_codes
    assert "source-contract-required" in blocker_codes

    with pytest.raises(Exception, match="comparison-window-mismatch"):
        await _dispatch_json(server, "approve_insight_card", {"card_id": card_id})
    assert judge.judge_calls == 0

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


def _assert_review_keeps_the_adapter_contract_unverified(
    review: dict[str, Any], expected_windows: list[str],
) -> None:
    selected = next(item for item in review["source_candidates"] if item["selected"])
    contract = selected["metadata"]
    assert contract["available_comparison_windows"] == expected_windows
    assert not contract.get("metric_names")
    assert not contract.get("metric_definitions")
    assert not contract.get("comparison_contracts")
    assert not contract.get("required_comparison_keys")
    assert not contract.get("population")
    assert not contract.get("grain")


@pytest.mark.parametrize(
    "comparison_windows",
    [[WINDOW], None],
    ids=["provider-declared-window", "window-undeclared"],
)
@pytest.mark.parametrize(
    "outcome",
    [None, "investigate", "notify", "escalate"],
    ids=["no-route", "investigate-route", "notify-route", "escalate-route"],
)
@pytest.mark.asyncio
async def test_raw_superset_contract_gaps_warn_but_allow_owner_authorized_shadow(
    tmp_path, comparison_windows: list[str] | None, outcome: str | None,
):
    server, judge, requests = _server(tmp_path, comparison_windows=comparison_windows)
    public_tools = {item.name for item in await server.list_tools()}
    assert {"inspect_resource", "onboard_insight_card", "review_insight_card",
            "approve_insight_card", "evaluate_insight_card", "get_decision_receipt"} <= public_tools

    snapshot = await _inspect_chart(server)
    _assert_raw_chart_has_no_business_contract(snapshot)
    expected_windows = comparison_windows or []
    assert snapshot["contract"]["available_comparison_windows"] == expected_windows

    draft = await _onboard(server, outcome)
    card_id = draft["card"]["id"]
    recipients = draft["card"]["delivery_methods"]
    expected_recipients = [] if outcome is None else [{
        "key": outcome,
        "outcome": outcome,
        "label": outcome.title(),
        "destination": f"agent://{outcome}",
        "instructions": "",
    }]
    assert recipients == expected_recipients

    reviewed = await _dispatch_json(server, "review_insight_card", {"card_id": card_id})
    review = reviewed.get("review", reviewed)
    blocker_codes = {item["code"] for item in review["blockers"]}
    assert review["readiness_status"] == "ready_for_approval"
    assert "source-contract-required" not in blocker_codes
    assert "comparison-window-mismatch" not in blocker_codes
    _assert_review_keeps_the_adapter_contract_unverified(review, expected_windows)

    if comparison_windows is None:
        assert any("undeclared" in warning and "unverified" in warning
                   for warning in review["warnings"])
    if outcome is not None:
        contract_warning = next(
            warning for warning in review["warnings"]
            if "metric/comparison meaning is unverified" in warning
        )
        assert SOURCE_REF in contract_warning
        assert "does not certify unattended delivery" in contract_warning
    review_warnings = review["warnings"]

    approved = await _dispatch_json(server, "approve_insight_card", {"card_id": card_id})
    assert approved["status"] == "approved"
    assert approved["workflow_acceptance"]["status"] == "unassessed"
    assert approved["card"]["status"] == "approved"
    assert approved["card"]["approved_by"] == "offline-agent-principal"
    assert approved["card"]["principal_id"] == "offline-agent-principal"
    assert approved["card"]["principal_tenant"] == TENANT_ID
    assert approved["card"]["delivery_methods"] == recipients
    assert approved["onboarding_review"]["warnings"] == review_warnings
    if review_warnings:
        assert approved["card"]["onboarding_warnings"] == review_warnings
    else:
        assert "onboarding_warnings" not in approved["card"]

    compact_card = await _dispatch_json(server, "get_insight_card", {"card_id": card_id})
    assert compact_card["status"] == "approved"
    assert compact_card["delivery_methods"] == recipients
    assert "onboarding_review" not in compact_card
    if review_warnings:
        assert compact_card["onboarding_warnings"] == review_warnings
    else:
        assert "onboarding_warnings" not in compact_card
    full_card = await _dispatch_json(server, "get_insight_card", {
        "card_id": card_id,
        "response_mode": "full",
    })
    assert full_card["delivery_methods"] == recipients
    assert full_card["onboarding_review"]["warnings"] == review_warnings
    assert "onboarding_warnings" not in full_card

    evaluated = await _dispatch_json(server, "evaluate_insight_card", {
        "card_id": card_id,
        "idempotency_key": f"{IDEMPOTENCY_KEY}:{outcome or 'none'}:{comparison_windows is not None}",
    })
    assert evaluated["receipt"]["delivery_mode"] == "shadow"
    assert evaluated["receipt"]["status"] == "delivery_disabled"
    assert evaluated["receipt"]["delivery_enabled"] is False
    assert evaluated["receipt"]["delivery_method_keys"] == []
    assert evaluated["result"]["delivery_methods"] == []
    assert evaluated["result"]["analyses"] == []
    assert evaluated["card"]["status"] == "approved"
    assert evaluated["card"]["delivery_methods"] == recipients
    # Review caveats stay attached to the card envelope, not recast as fresh
    # observations or an adapter-supplied metric/comparison contract.
    if review_warnings:
        assert evaluated["card"]["onboarding_warnings"] == review_warnings
    else:
        assert "onboarding_warnings" not in evaluated["card"]
    assert judge.judge_calls == 1

    persisted = await _dispatch_json(server, "get_decision_receipt", {
        "idempotency_key": evaluated["receipt"]["idempotency_key"],
    })
    assert persisted["receipt"]["status"] == "delivery_disabled"
    assert persisted["receipt"]["delivery_mode"] == "shadow"
    assert (await _dispatch_json(server, "get_insight_card", {"card_id": card_id}))["delivery_methods"] == recipients
    assert requests
    assert {path for _method, path in requests} <= {
        "/api/v1/chart/1",
        "/api/v1/chart/data",
    }

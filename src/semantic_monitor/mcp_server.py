from __future__ import annotations

import inspect
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .models import MonitorCard, Recipient
from .runtime import Runtime, build_runtime
from .scenarios import scenario_catalog


def create_mcp(runtime: Runtime | None = None) -> FastMCP:
    runtime = runtime or build_runtime()
    mcp = FastMCP("superset-semantic-monitor")

    @mcp.tool()
    async def list_dashboards() -> list[dict[str, Any]]:
        """List dashboards available to the current monitor runtime."""
        dashboards = runtime.store.list_dashboards()
        if inspect.isawaitable(dashboards):
            dashboards = await dashboards
        return [
            {
                "id": dashboard.id,
                "title": dashboard.title,
                "description": dashboard.description,
                "owners": dashboard.owners,
            }
            for dashboard in dashboards
        ]

    @mcp.tool()
    async def inspect_dashboard(dashboard_id: str) -> dict[str, Any]:
        """Inspect dashboard charts and normalized observations without making a decision."""
        dashboard = runtime.store.get_dashboard(dashboard_id, include_data=True)
        if inspect.isawaitable(dashboard):
            dashboard = await dashboard
        return dashboard.model_dump(mode="json")

    @mcp.tool()
    async def draft_monitor(
        dashboard_id: str,
        title: str,
        intent: str,
        chart_ids: list[str] | None = None,
        recipients: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Draft a versioned monitoring card from owner intent; no alert is sent."""
        dashboard = runtime.store.get_dashboard(dashboard_id, include_data=False)
        if inspect.isawaitable(dashboard):
            dashboard = await dashboard
        card = MonitorCard(
            id=f"draft-{dashboard_id}-{title.lower().replace(' ', '-')}",
            dashboard_id=dashboard_id,
            title=title,
            intent=intent,
            chart_ids=chart_ids or [chart.id for chart in dashboard.charts],
            recipients=[Recipient.model_validate(recipient) for recipient in (recipients or [])],
        )
        plan = await runtime.engine.compile(card)
        runtime.store.save_card(card)
        return {
            "card": card.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "status": "draft",
        }

    @mcp.tool()
    async def evaluate_monitor(monitor_id: str, scenario: str | None = None) -> dict[str, Any]:
        """Evaluate an approved monitor and return an evidence-backed decision."""
        card = runtime.store.get_card(monitor_id)
        if scenario:
            if not hasattr(runtime.store, "get_dashboard_by_scenario"):
                raise ValueError("scenario evaluation is only available in fixture mode")
            dashboard = runtime.store.get_dashboard_by_scenario(scenario)
        else:
            dashboard = runtime.store.get_dashboard(
                card.dashboard_id, chart_ids=card.chart_ids, include_data=True
            )
        if inspect.isawaitable(dashboard):
            dashboard = await dashboard
        evaluation = await runtime.engine.evaluate(dashboard, card)
        return {
            "card": evaluation.card.model_dump(mode="json"),
            "plan": evaluation.plan.model_dump(mode="json"),
            "decision": evaluation.decision.model_dump(mode="json"),
        }

    @mcp.tool()
    def list_demo_scenarios() -> list[str]:
        """List deterministic local company scenarios used for testing."""
        return sorted(scenario_catalog())

    @mcp.resource("monitor://catalog")
    def monitor_catalog() -> str:
        """Human-readable catalog for an MCP client."""
        return json.dumps(
            {"monitors": [card.model_dump(mode="json") for card in runtime.store.list_cards()]},
            indent=2,
        )

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        """Small liveness endpoint for a container or scheduler."""
        return JSONResponse(
            {"status": "ok", "service": "superset-semantic-monitor", "source": os.getenv("MONITOR_SOURCE", "fixtures")}
        )

    @mcp.custom_route("/webhooks/evaluate", methods=["POST"])
    async def evaluate_webhook(request: Request) -> JSONResponse:
        """Push-triggered evaluation endpoint for Superset alerts or a scheduler."""
        expected_token = os.getenv("PUSH_WEBHOOK_TOKEN")
        if expected_token and request.headers.get("authorization") != f"Bearer {expected_token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        payload = await request.json()
        monitor_id = payload.get("monitor_id")
        if not monitor_id:
            return JSONResponse({"error": "monitor_id is required"}, status_code=400)
        try:
            card = runtime.store.get_card(monitor_id)
            dashboard = runtime.store.get_dashboard(
                card.dashboard_id, chart_ids=card.chart_ids, include_data=True
            )
            if inspect.isawaitable(dashboard):
                dashboard = await dashboard
            evaluation = await runtime.engine.evaluate(dashboard, card)
        except (KeyError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=404)
        return JSONResponse(evaluation.decision.model_dump(mode="json"))

    return mcp


mcp = create_mcp()

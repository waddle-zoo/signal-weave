from __future__ import annotations

import json
import os
import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .models import DeliveryMethod, InsightCard, InsightCardStatus, SourceRef
from .onboarding import InsightAuthoringService, proposal_summary
from .runtime import Runtime, build_runtime


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "insight"


def create_mcp(runtime: Runtime | None = None) -> FastMCP:
    runtime = runtime or build_runtime()
    authoring = InsightAuthoringService(runtime.sources, runtime.engine)
    mcp = FastMCP("signal-weave")

    @mcp.tool()
    async def list_resources(adapter: str | None = None) -> list[dict[str, Any]]:
        """List safe, inspectable resources exposed by installed source adapters."""
        resources = await runtime.sources.list_resources(adapter)
        return [resource.model_dump(mode="json") for resource in resources]

    @mcp.tool()
    async def inspect_resource(
        adapter: str,
        resource: str,
        label: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Inspect one source resource without making an insight decision."""
        source = SourceRef(
            key=f"inspect-{_slug(adapter)}-{_slug(resource)}",
            adapter=adapter,
            resource=resource,
            label=label or resource,
            parameters=parameters or {},
        )
        snapshot = await runtime.sources.inspect(source)
        return snapshot.model_dump(mode="json")

    @mcp.tool()
    async def discover_insight_sources(
        goal: str,
        adapter: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Find bounded, Jev-ranked source candidates for an insight goal."""
        discovery = await authoring.discover(goal, adapter=adapter, limit=limit)
        return discovery.model_dump(mode="json")

    @mcp.tool()
    async def propose_insight_card(
        what_to_watch: str,
        why_watch: str,
        watch_for: list[str] | None = None,
        questions: list[str] | None = None,
        selected_sources: list[dict[str, Any]] | None = None,
        adapter: str | None = None,
        limit: int = 10,
        title: str | None = None,
        comparison_windows: list[str] | None = None,
        delivery_methods: list[dict[str, Any]] | None = None,
        action_confidence_threshold: float = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
    ) -> dict[str, Any]:
        """Propose and save a draft free-form insight card.

        ``selected_sources`` contains refs returned by
        ``discover_insight_sources``; each item may also provide adapter
        parameters such as Superset chart IDs. The result is a draft until a
        human or policy service approves it.
        """
        proposal = await authoring.propose(
            what_to_watch,
            why_watch,
            watch_for=watch_for,
            questions=questions,
            selected_sources=selected_sources,
            adapter=adapter,
            limit=limit,
            title=title,
            comparison_windows=comparison_windows,
            delivery_methods=[
                DeliveryMethod.model_validate(method) for method in (delivery_methods or [])
            ],
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
        )
        stored_card = proposal.card.model_copy(update={"compiled_plan": proposal.plan})
        runtime.card_store.save_card(stored_card)
        proposal = proposal.model_copy(update={"card": stored_card})
        return {
            "proposal": proposal.model_dump(mode="json"),
            "summary": proposal_summary(proposal),
        }

    @mcp.tool()
    async def draft_insight_card(
        title: str,
        what_to_watch: str,
        why_watch: str,
        sources: list[dict[str, Any]],
        watch_for: list[str] | None = None,
        questions: list[str] | None = None,
        delivery_methods: list[dict[str, Any]] | None = None,
        card_id: str | None = None,
        comparison_windows: list[str] | None = None,
        action_confidence_threshold: float = 0.70,
        owner: str | None = None,
        max_source_age_hours: float | None = 24.0,
    ) -> dict[str, Any]:
        """Draft a card over explicit source resources; no push is sent."""
        if not sources:
            raise ValueError("at least one source reference is required")
        source_refs = [SourceRef.model_validate(source) for source in sources]
        card = InsightCard(
            id=card_id or f"card-{_slug(title)}",
            title=title,
            what_to_watch=what_to_watch,
            why_watch=why_watch,
            watch_for=watch_for or [],
            questions=questions or [],
            sources=source_refs,
            comparison_windows=comparison_windows
            or ["previous_period", "trailing_4_period_average"],
            delivery_methods=[
                DeliveryMethod.model_validate(method) for method in (delivery_methods or [])
            ],
            action_confidence_threshold=action_confidence_threshold,
            owner=owner,
            max_source_age_hours=max_source_age_hours,
        )
        plan = await runtime.engine.compile(card)
        card = card.model_copy(update={"compiled_plan": plan})
        runtime.card_store.save_card(card)
        return {
            "card": card.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "status": card.status.value,
        }

    @mcp.tool()
    async def evaluate_insight_card(card_id: str) -> dict[str, Any]:
        """Evaluate an approved card over freshly fetched source snapshots."""
        card = runtime.card_store.get_card(card_id)
        if card.status != InsightCardStatus.APPROVED:
            raise ValueError(
                f"Insight card {card_id} is a draft; simulate it, then approve it before evaluation"
            )
        run = await runtime.engine.evaluate(card)
        return {
            "card": run.card.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "result": run.result.model_dump(mode="json"),
        }

    @mcp.tool()
    async def simulate_insight_card(card_id: str) -> dict[str, Any]:
        """Evaluate a draft without treating the result as an approved push action."""
        card = runtime.card_store.get_card(card_id)
        run = await runtime.engine.evaluate(card)
        return {
            "status": "preview",
            "delivery_enabled": False,
            "card": run.card.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "result": run.result.model_dump(mode="json"),
        }

    @mcp.tool()
    async def approve_insight_card(card_id: str) -> dict[str, Any]:
        """Approve a draft card for later scheduler or webhook evaluation."""
        card = runtime.card_store.get_card(card_id)
        if not card.sources:
            raise ValueError("an insight card needs at least one selected source before approval")
        if card.compiled_plan is None:
            plan = await runtime.engine.compile(card)
            card = card.model_copy(update={"compiled_plan": plan})
            runtime.card_store.save_card(card)
        approved = runtime.card_store.set_card_status(card_id, InsightCardStatus.APPROVED)
        return {
            "status": approved.status.value,
            "card": approved.model_dump(mode="json"),
        }

    @mcp.tool()
    def list_insight_cards(status: str | None = None) -> dict[str, Any]:
        """List stored cards for a client-owned UI or agent."""
        selected_status = InsightCardStatus(status) if status else None
        cards = [
            card
            for card in runtime.card_store.list_cards()
            if selected_status is None or card.status == selected_status
        ]
        return {
            "cards": [card.model_dump(mode="json") for card in cards],
            "count": len(cards),
        }

    @mcp.tool()
    def get_insight_card(card_id: str) -> dict[str, Any]:
        """Return one stored insight card by its stable ID."""
        return runtime.card_store.get_card(card_id).model_dump(mode="json")

    @mcp.resource("insight://catalog")
    def insight_catalog() -> str:
        """Human-readable catalog for an MCP client."""
        return json.dumps(
            {
                "cards": [
                    card.model_dump(mode="json") for card in runtime.card_store.list_cards()
                ]
            },
            indent=2,
        )

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        """Small liveness endpoint for a container or scheduler."""
        return JSONResponse(
            {
                "status": "ok",
                "service": "signal-weave",
                "source_adapters": runtime.sources.adapter_names(),
            }
        )

    @mcp.custom_route("/webhooks/evaluate", methods=["POST"])
    async def evaluate_webhook(request: Request) -> JSONResponse:
        """Push-triggered card evaluation endpoint for schedulers and source alerts."""
        expected_token = os.getenv("PUSH_WEBHOOK_TOKEN")
        if expected_token and request.headers.get("authorization") != f"Bearer {expected_token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        payload = await request.json()
        card_id = payload.get("card_id")
        if not card_id:
            return JSONResponse({"error": "card_id is required"}, status_code=400)
        try:
            card = runtime.card_store.get_card(card_id)
            if card.status != InsightCardStatus.APPROVED:
                return JSONResponse(
                    {
                        "error": (
                            f"Insight card {card_id} is a draft; simulate it, then approve it "
                            "before evaluation"
                        )
                    },
                    status_code=409,
                )
            run = await runtime.engine.evaluate(card)
        except (KeyError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=404)
        return JSONResponse(run.result.model_dump(mode="json"))

    return mcp


# The CLI constructs the server after resolving the runtime and credentials. Keeping module import
# side-effect free lets tests inspect the MCP factory without requiring a production API key.

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .models import (
    ContextSnapshot,
    DecisionReceipt,
    DeliveryMethod,
    InsightCard,
    InsightCardStatus,
    InvestigationMode,
    MetricQueryCard,
    Outcome,
    QueryCardStatus,
    ReceiptStatus,
    RetrievalMode,
    SourceRef,
)
from .onboarding import InsightAuthoringService, proposal_summary
from .query_planner import QueryWindow, compile_query, plan_query
from .runtime import Runtime, build_runtime
from .store import InMemoryDecisionReceiptStore, JsonMetricQueryCardStore


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "insight"


def _evaluation_fingerprint(
    card: InsightCard,
    *,
    actor: str,
    context: ContextSnapshot | None,
) -> str:
    payload = {
        "card_id": card.id,
        "card_version": card.version,
        "actor": actor or "mcp-client",
        "context": (
            context.model_dump(mode="json", exclude={"captured_at"}) if context else None
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_mcp(runtime: Runtime | None = None) -> FastMCP:
    runtime = runtime or build_runtime()
    authoring = InsightAuthoringService(
        runtime.sources, runtime.engine, principal=runtime.principal
    )
    metric_query_store = runtime.metric_query_store or JsonMetricQueryCardStore(
        os.getenv("METRIC_QUERY_CARD_STORE", "data/metric-query-cards.json")
    )
    decision_receipts = runtime.decision_receipts or InMemoryDecisionReceiptStore()
    idempotency_locks: dict[str, asyncio.Lock] = {}
    mcp = FastMCP("signal-weave")

    async def prepare_insight_card(
        card: InsightCard, context: ContextSnapshot | None = None
    ) -> tuple[InsightCard, Any]:
        """Resolve optional related sources without mutating the stored card."""
        bundle = await authoring.resolve_bundle(card, context)
        expanded = card
        if [source.model_dump(mode="json") for source in bundle.selected_sources] != [
            source.model_dump(mode="json") for source in card.sources
        ]:
            expanded = card.model_copy(
                update={"sources": bundle.selected_sources, "compiled_plan": None}
            )
        return expanded, bundle

    async def evaluate_approved_card_once(
        card_id: str,
        *,
        idempotency_key: str | None,
        actor: str,
        context: ContextSnapshot | None = None,
    ) -> dict[str, Any]:
        card = runtime.card_store.get_card(card_id)
        if card.status != InsightCardStatus.APPROVED:
            raise ValueError(
                f"Insight card {card_id} is a draft; simulate it, then approve it before evaluation"
            )
        key = (idempotency_key or f"manual:{card_id}:{uuid4().hex}").strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        fingerprint = _evaluation_fingerprint(card, actor=actor, context=context)
        existing = decision_receipts.get_by_idempotency_key(key)
        if existing is not None:
            if existing.request_fingerprint and existing.request_fingerprint != fingerprint:
                raise ValueError(
                    "idempotency key is already bound to a different card, actor, version, "
                    "or context"
                )
            if existing.status == ReceiptStatus.PREPARED:
                raise ValueError("idempotency key is already being evaluated; retry shortly")
            return {
                "receipt": existing.model_copy(update={"status": ReceiptStatus.REPLAYED}).model_dump(
                    mode="json"
                ),
                "replayed": True,
                "result": existing.result,
            }
        prepared = DecisionReceipt(
            receipt_id=f"receipt-{uuid4().hex}",
            idempotency_key=key,
            request_fingerprint=fingerprint,
            card_id=card.id,
            card_version=card.version,
            actor=actor or "mcp-client",
            status=ReceiptStatus.PREPARED,
        )
        if not decision_receipts.claim(prepared):
            existing = decision_receipts.get_by_idempotency_key(key)
            if existing is not None and existing.request_fingerprint and existing.request_fingerprint != fingerprint:
                raise ValueError(
                    "idempotency key is already bound to a different card, actor, version, "
                    "or context"
                )
            if existing is not None and existing.status == ReceiptStatus.PREPARED:
                raise ValueError("idempotency key is already being evaluated; retry shortly")
            if existing is None:
                raise RuntimeError("unable to claim idempotency key")
            return {
                "receipt": existing.model_copy(update={"status": ReceiptStatus.REPLAYED}).model_dump(
                    mode="json"
                ),
                "replayed": True,
                "result": existing.result,
            }
        try:
            evaluation_card, bundle = await prepare_insight_card(card, context)
            run = await runtime.engine.evaluate(evaluation_card, context_override=context)
            evaluated_result = run.result.model_copy(update={"retrieval": bundle})
            result = evaluated_result.model_dump(mode="json")
        except Exception as error:  # noqa: BLE001 - persist failed claims for replay safety
            decision_receipts.save(
                prepared.model_copy(
                    update={
                        "status": ReceiptStatus.FAILED,
                        "outcome": Outcome.INSUFFICIENT_DATA,
                        "result": {"error": f"{type(error).__name__}: {error}"},
                    }
                )
            )
            raise
        receipt = prepared.model_copy(
            update={
                "status": ReceiptStatus.DELIVERY_DISABLED,
                "outcome": run.result.outcome,
                "delivery_enabled": False,
                "delivery_method_keys": [method.key for method in run.result.delivery_methods],
                "result": result,
            }
        )
        decision_receipts.save(receipt)
        return {
            "receipt": receipt.model_dump(mode="json"),
            "replayed": False,
            "card": run.card.model_dump(mode="json"),
            "retrieval": bundle.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "result": result,
        }

    async def evaluate_approved_card(
        card_id: str,
        *,
        idempotency_key: str | None,
        actor: str,
        context: ContextSnapshot | None = None,
    ) -> dict[str, Any]:
        key = (idempotency_key or f"manual:{card_id}:{uuid4().hex}").strip()
        if not key:
            raise ValueError("idempotency_key must not be empty")
        lock = idempotency_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await evaluate_approved_card_once(
                card_id, idempotency_key=key, actor=actor, context=context
            )

    async def selected_query_sources(selected_sources: list[dict[str, Any]]) -> list[SourceRef]:
        if not selected_sources:
            raise ValueError("metric query cards require at least one selected source")
        catalog = {
            f"{resource.adapter}|{resource.resource}": resource
            for resource in await runtime.sources.list_resources()
        }
        refs: list[SourceRef] = []
        for index, item in enumerate(selected_sources):
            ref = str(item.get("ref") or "")
            if "|" not in ref:
                adapter = str(item.get("adapter") or "")
                resource = str(item.get("resource") or "")
                ref = f"{adapter}|{resource}"
            descriptor = catalog.get(ref)
            if descriptor is None:
                raise ValueError(f"selected metric source is not in the authorized catalog: {ref}")
            adapter, _, resource = ref.partition("|")
            refs.append(
                SourceRef(
                    key=str(item.get("key") or f"source-{index + 1}-{_slug(resource)}"),
                    adapter=adapter,
                    resource=resource,
                    label=str(item.get("label") or descriptor.title),
                    parameters=item.get("parameters") or {},
                    required=bool(item.get("required", True)),
                )
            )
        return refs

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
        retrieval_mode: str = "expand",
        investigation_mode: str = "bounded",
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
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
            retrieval_mode=RetrievalMode(retrieval_mode),
            investigation_mode=InvestigationMode(investigation_mode),
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
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
        retrieval_mode: str = "fixed",
        investigation_mode: str = "none",
        max_investigation_sources: int = 3,
        investigation_threshold: float = 0.60,
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
            retrieval_mode=RetrievalMode(retrieval_mode),
            investigation_mode=InvestigationMode(investigation_mode),
            max_investigation_sources=max_investigation_sources,
            investigation_threshold=investigation_threshold,
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
    async def propose_metric_query_card(
        question: str,
        why: str,
        selected_sources: list[dict[str, Any]],
        requested_dimensions: list[str] | None = None,
        requested_time_grain: str | None = None,
        title: str | None = None,
        card_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a draft plain-language metric card over approved definitions.

        Jev selects a catalog definition and any requested semantic dimensions;
        code then stores the typed plan. SQL is emitted only by
        ``compile_metric_query_card`` with an explicit bounded time window.
        """
        if not question.strip() or not why.strip():
            raise ValueError("question and why are required")
        source_refs = await selected_query_sources(selected_sources)
        selector = getattr(runtime.engine.judger, "select_metric_plan", None)
        if not callable(selector):
            raise RuntimeError("the configured Jev judger does not support metric planning")
        plan = await plan_query(
            registry=runtime.sources,
            selector=runtime.engine.judger,
            goal=f"{question.strip()}\nPurpose: {why.strip()}",
            source_refs=source_refs,
            requested_dimensions=requested_dimensions,
            requested_time_grain=requested_time_grain,
        )
        card_title = (title or question.strip().rstrip("."))[:200] or "Metric query"
        card = MetricQueryCard(
            id=card_id or f"metric-{_slug(card_title)}-{uuid4().hex[:8]}",
            title=card_title,
            question=question,
            why=why,
            sources=source_refs,
            requested_dimensions=requested_dimensions or [],
            requested_time_grain=requested_time_grain,
            query_plan=plan,
        )
        metric_query_store.save_card(card)
        return {"card": card.model_dump(mode="json"), "status": card.status.value}

    @mcp.tool()
    def compile_metric_query_card(
        card_id: str,
        window_start: str,
        window_end: str,
    ) -> dict[str, Any]:
        """Compile a stored metric card into deterministic, bounded SQL."""
        card = metric_query_store.get_card(card_id)
        if card.query_plan is None:
            raise ValueError("metric query card has no approved metric plan")
        compiled = compile_query(card.query_plan, QueryWindow(window_start, window_end))
        return {
            "status": "preview" if card.status == QueryCardStatus.DRAFT else "approved",
            "card": card.model_dump(mode="json"),
            "compiled_query": compiled.model_dump(mode="json"),
        }

    @mcp.tool()
    def approve_metric_query_card(card_id: str, actor: str = "mcp-client") -> dict[str, Any]:
        """Approve a metric card for a caller-owned Trino or SQL executor."""
        card = metric_query_store.get_card(card_id)
        if card.query_plan is None:
            raise ValueError("metric query card needs a resolved metric plan before approval")
        approved = metric_query_store.set_card_status(card_id, QueryCardStatus.APPROVED)
        approved = approved.model_copy(
            update={"approved_by": actor, "approved_at": datetime.now(timezone.utc)}
        )
        metric_query_store.save_card(approved)
        return {"status": approved.status.value, "card": approved.model_dump(mode="json")}

    @mcp.tool()
    def list_metric_query_cards(status: str | None = None) -> dict[str, Any]:
        """List stored metric query cards for a UI or agent."""
        selected_status = QueryCardStatus(status) if status else None
        cards = [
            card
            for card in metric_query_store.list_cards()
            if selected_status is None or card.status == selected_status
        ]
        return {"cards": [card.model_dump(mode="json") for card in cards], "count": len(cards)}

    @mcp.tool()
    def get_metric_query_card(card_id: str) -> dict[str, Any]:
        """Return one stored metric query card."""
        return metric_query_store.get_card(card_id).model_dump(mode="json")

    @mcp.tool()
    async def evaluate_insight_card(
        card_id: str,
        idempotency_key: str | None = None,
        actor: str = "mcp-client",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate an approved card, optionally with a versioned external context view."""
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        return await evaluate_approved_card(
            card_id,
            idempotency_key=idempotency_key,
            actor=actor,
            context=context_snapshot,
        )

    @mcp.tool()
    async def resolve_insight_sources(
        card_id: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Preview the bounded Jev-ranked evidence bundle for a stored card."""
        card = runtime.card_store.get_card(card_id)
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        bundle = await authoring.resolve_bundle(card, context_snapshot)
        return {
            "card": card.model_dump(mode="json"),
            "bundle": bundle.model_dump(mode="json"),
        }

    @mcp.tool()
    async def review_insight_card(
        card_id: str, adapter: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Review a draft's source coverage before a human approves it.

        This is an onboarding review, not an automatic policy change. It shows
        bounded Jev-ranked candidates, why they were surfaced, and which
        recommendations the draft omitted so a client-owned UI or agent can ask
        for confirmation or revise the card.
        """
        card = runtime.card_store.get_card(card_id)
        review = await authoring.review(card, adapter=adapter, limit=limit)
        return {
            "card": card.model_dump(mode="json"),
            "review": review.model_dump(mode="json"),
        }

    @mcp.tool()
    async def simulate_insight_card(
        card_id: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Evaluate a draft without treating the result as an approved push action."""
        card = runtime.card_store.get_card(card_id)
        context_snapshot = (
            ContextSnapshot.model_validate(context).model_copy(update={"trust": "unverified"})
            if context
            else None
        )
        evaluation_card, bundle = await prepare_insight_card(card, context_snapshot)
        run = await runtime.engine.evaluate(evaluation_card, context_override=context_snapshot)
        result = run.result.model_copy(update={"retrieval": bundle})
        return {
            "status": "preview",
            "delivery_enabled": False,
            "card": run.card.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in run.resources],
            "plan": run.plan.model_dump(mode="json"),
            "retrieval": bundle.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }

    @mcp.tool()
    async def approve_insight_card(card_id: str, actor: str = "mcp-client") -> dict[str, Any]:
        """Approve a draft card for later scheduler or webhook evaluation."""
        card = runtime.card_store.get_card(card_id)
        if not card.sources:
            raise ValueError("an insight card needs at least one selected source before approval")
        onboarding_review = await authoring.review(card)
        if onboarding_review.readiness_status != "ready_for_approval":
            codes = ", ".join(blocker.code.value for blocker in onboarding_review.blockers)
            raise ValueError(
                "insight card is not ready for approval; resolve onboarding blockers: "
                + (codes or "human review required")
            )
        if card.compiled_plan is None:
            plan = await runtime.engine.compile(card)
            card = card.model_copy(update={"compiled_plan": plan})
            runtime.card_store.save_card(card)
        approved = runtime.card_store.set_card_status(card_id, InsightCardStatus.APPROVED)
        approved = approved.model_copy(
            update={"approved_by": actor, "approved_at": datetime.now(timezone.utc)}
        )
        runtime.card_store.save_card(approved)
        return {
            "status": approved.status.value,
            "card": approved.model_dump(mode="json"),
            "onboarding_review": onboarding_review.model_dump(mode="json"),
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
        if not expected_token:
            return JSONResponse(
                {"error": "push webhook authentication is not configured"}, status_code=503
            )
        if request.headers.get("authorization") != f"Bearer {expected_token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            max_body_bytes = int(os.getenv("SIGNALWEAVE_MAX_HTTP_BODY_BYTES", "1048576"))
        except ValueError:
            max_body_bytes = 1048576
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse({"error": "invalid content-length"}, status_code=400)
            if declared_length > max_body_bytes:
                return JSONResponse({"error": "request body is too large"}, status_code=413)
        body = await request.body()
        if len(body) > max_body_bytes:
            return JSONResponse({"error": "request body is too large"}, status_code=413)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse({"error": "request body must be valid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "request body must be a JSON object"}, status_code=400)
        card_id = payload.get("card_id")
        if not card_id:
            return JSONResponse({"error": "card_id is required"}, status_code=400)
        idempotency_key = payload.get("idempotency_key") or request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return JSONResponse(
                {"error": "idempotency_key is required for push evaluation"}, status_code=400
            )
        actor = str(request.headers.get("X-SignalWeave-Actor") or "webhook")
        try:
            context = (
                ContextSnapshot.model_validate(payload["context"]).model_copy(
                    update={"trust": "unverified"}
                )
                if payload.get("context")
                else None
            )
            result = await evaluate_approved_card(
                card_id,
                idempotency_key=str(idempotency_key),
                actor=actor,
                context=context,
            )
        except (KeyError, ValueError) as error:
            message = str(error)
            status_code = 409 if "draft" in message or "already being evaluated" in message else 404
            return JSONResponse({"error": str(error)}, status_code=status_code)
        return JSONResponse(result)

    return mcp


# The CLI constructs the server after resolving the runtime and credentials. Keeping module import
# side-effect free lets tests inspect the MCP factory without requiring a production API key.

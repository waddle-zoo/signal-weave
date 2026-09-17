from __future__ import annotations

import inspect
import json
import os
import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .models import MonitorWorkflow, Outcome, Recipient, SourceRef
from .runtime import Runtime, build_runtime


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "workflow"


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def create_mcp(runtime: Runtime | None = None) -> FastMCP:
    runtime = runtime or build_runtime()
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
        """Inspect one source resource without making a workflow decision."""
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
    async def draft_workflow(
        title: str,
        intent: str,
        sources: list[dict[str, Any]],
        recipients: list[dict[str, str]] | None = None,
        comparison_windows: list[str] | None = None,
        investigation_hints: list[str] | None = None,
        materiality_threshold_pct: float = 10.0,
        action_confidence_threshold: float = 0.70,
        materiality_definition: str | None = None,
        outcome_guidance: dict[str, str] | None = None,
        allowed_outcomes: list[str] | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        """Draft a versioned workflow over any installed source resources; no alert is sent.

        Each source has ``key``, ``adapter``, ``resource``, and ``label``. Adapter
        parameters are source-specific; for example Superset accepts ``chart_ids``
        when a dashboard should be narrowed.
        """
        if not sources:
            raise ValueError("at least one source reference is required")
        source_refs = [SourceRef.model_validate(source) for source in sources]
        selected_outcomes = (
            [Outcome(value) for value in allowed_outcomes]
            if allowed_outcomes is not None
            else list(Outcome)
        )
        workflow = MonitorWorkflow(
            id=f"workflow-{_slug(title)}",
            title=title,
            intent=intent,
            sources=source_refs,
            recipients=[Recipient.model_validate(recipient) for recipient in (recipients or [])],
            comparison_windows=comparison_windows
            or ["previous_period", "trailing_4_period_average"],
            investigation_hints=investigation_hints or [],
            materiality_threshold_pct=materiality_threshold_pct,
            action_confidence_threshold=action_confidence_threshold,
            materiality_definition=materiality_definition,
            outcome_guidance=outcome_guidance or {},
            allowed_outcomes=selected_outcomes,
            owner=owner,
        )
        plan = await runtime.engine.compile(workflow)
        runtime.workflow_store.save_workflow(workflow)
        return {
            "workflow": workflow.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "status": "draft",
        }

    @mcp.tool()
    async def evaluate_workflow(workflow_id: str) -> dict[str, Any]:
        """Evaluate an approved workflow over freshly fetched source snapshots."""
        workflow = runtime.workflow_store.get_workflow(workflow_id)
        evaluation = await runtime.engine.evaluate(workflow)
        return {
            "workflow": evaluation.workflow.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in evaluation.resources],
            "plan": evaluation.plan.model_dump(mode="json"),
            "decision": evaluation.decision.model_dump(mode="json"),
        }

    @mcp.resource("workflow://catalog")
    def workflow_catalog() -> str:
        """Human-readable catalog for an MCP client."""
        return json.dumps(
            {
                "workflows": [
                    workflow.model_dump(mode="json")
                    for workflow in runtime.workflow_store.list_workflows()
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
        """Push-triggered workflow evaluation endpoint for schedulers and source alerts."""
        expected_token = os.getenv("PUSH_WEBHOOK_TOKEN")
        if expected_token and request.headers.get("authorization") != f"Bearer {expected_token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        payload = await request.json()
        workflow_id = payload.get("workflow_id") or payload.get("monitor_id")
        if not workflow_id:
            return JSONResponse({"error": "workflow_id is required"}, status_code=400)
        try:
            workflow = runtime.workflow_store.get_workflow(workflow_id)
            evaluation = await runtime.engine.evaluate(workflow)
        except (KeyError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=404)
        return JSONResponse(evaluation.decision.model_dump(mode="json"))

    return mcp


# The CLI constructs the server after resolving the runtime and credentials. Keeping module import
# side-effect free lets tests inspect the MCP factory without requiring a production API key.

from __future__ import annotations

import inspect
import json
import os
import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .models import MonitorWorkflow, Outcome, Recipient, SourceRef, WorkflowStatus
from .onboarding import MonitorAuthoringService, proposal_summary
from .runtime import Runtime, build_runtime


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "workflow"


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def create_mcp(runtime: Runtime | None = None) -> FastMCP:
    runtime = runtime or build_runtime()
    authoring = MonitorAuthoringService(runtime.sources, runtime.engine)
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
    async def discover_monitor_inputs(
        goal: str,
        adapter: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Find bounded, Jev-ranked source candidates for a monitoring goal."""
        discovery = await authoring.discover(goal, adapter=adapter, limit=limit)
        return discovery.model_dump(mode="json")

    @mcp.tool()
    async def propose_monitor_card(
        goal: str,
        selected_sources: list[dict[str, Any]] | None = None,
        adapter: str | None = None,
        limit: int = 10,
        comparison_windows: list[str] | None = None,
        materiality_threshold_pct: float = 10.0,
        materiality_definition: str | None = None,
        recipients: list[dict[str, str]] | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        """Propose and save a draft monitor card from a natural-language goal.

        ``selected_sources`` contains refs returned by ``discover_monitor_inputs``;
        each item may also provide adapter parameters such as Superset chart IDs.
        The result is a draft until a human or policy service approves it.
        """
        proposal = await authoring.propose(
            goal,
            selected_sources=selected_sources,
            adapter=adapter,
            limit=limit,
            comparison_windows=comparison_windows,
            materiality_threshold_pct=materiality_threshold_pct,
            materiality_definition=materiality_definition,
            recipients=[Recipient.model_validate(recipient) for recipient in (recipients or [])],
            owner=owner,
        )
        runtime.workflow_store.save_workflow(proposal.workflow)
        return {
            "proposal": proposal.model_dump(mode="json"),
            "summary": proposal_summary(proposal),
        }

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
        if workflow.status != WorkflowStatus.APPROVED:
            raise ValueError(
                f"Workflow {workflow_id} is a draft; simulate it, then approve it before evaluation"
            )
        evaluation = await runtime.engine.evaluate(workflow)
        return {
            "workflow": evaluation.workflow.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in evaluation.resources],
            "plan": evaluation.plan.model_dump(mode="json"),
            "decision": evaluation.decision.model_dump(mode="json"),
        }

    @mcp.tool()
    async def simulate_monitor_card(workflow_id: str) -> dict[str, Any]:
        """Evaluate a draft without treating the result as an approved push action."""
        workflow = runtime.workflow_store.get_workflow(workflow_id)
        evaluation = await runtime.engine.evaluate(workflow)
        return {
            "status": "preview",
            "delivery_enabled": False,
            "workflow": evaluation.workflow.model_dump(mode="json"),
            "resources": [resource.model_dump(mode="json") for resource in evaluation.resources],
            "plan": evaluation.plan.model_dump(mode="json"),
            "decision": evaluation.decision.model_dump(mode="json"),
        }

    @mcp.tool()
    def approve_monitor_card(workflow_id: str) -> dict[str, Any]:
        """Approve a draft monitor card for later scheduler or webhook evaluation."""
        workflow = runtime.workflow_store.get_workflow(workflow_id)
        if not workflow.sources:
            raise ValueError("a monitor card needs at least one selected source before approval")
        approved = runtime.workflow_store.set_workflow_status(
            workflow_id, WorkflowStatus.APPROVED
        )
        return {
            "status": approved.status.value,
            "workflow": approved.model_dump(mode="json"),
        }

    @mcp.tool()
    def list_monitor_cards(status: str | None = None) -> dict[str, Any]:
        """List stored monitor cards for a client-owned UI or agent."""
        selected_status = WorkflowStatus(status) if status else None
        cards = [
            workflow
            for workflow in runtime.workflow_store.list_workflows()
            if selected_status is None or workflow.status == selected_status
        ]
        return {
            "cards": [workflow.model_dump(mode="json") for workflow in cards],
            "count": len(cards),
        }

    @mcp.tool()
    def get_monitor_card(workflow_id: str) -> dict[str, Any]:
        """Return one stored monitor card by its stable ID."""
        return runtime.workflow_store.get_workflow(workflow_id).model_dump(mode="json")

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
            if workflow.status != WorkflowStatus.APPROVED:
                return JSONResponse(
                    {
                        "error": (
                            f"Workflow {workflow_id} is a draft; simulate it, then approve it "
                            "before evaluation"
                        )
                    },
                    status_code=409,
                )
            evaluation = await runtime.engine.evaluate(workflow)
        except (KeyError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=404)
        return JSONResponse(evaluation.decision.model_dump(mode="json"))

    return mcp


# The CLI constructs the server after resolving the runtime and credentials. Keeping module import
# side-effect free lets tests inspect the MCP factory without requiring a production API key.

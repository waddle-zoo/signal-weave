from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from signalweave.models import ContextFact, ContextSnapshot


class SignalWeaveGateway(Protocol):
    """The small part of the SignalWeave MCP contract used by this agent."""

    async def evaluate(
        self,
        card_id: str,
        *,
        idempotency_key: str,
        context: ContextSnapshot | None = None,
        parent_receipt_id: str | None = None,
        workflow_step_key: str | None = None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class InvestigationRequest:
    """The bounded request given to the agent's evidence tools."""

    card_id: str
    step_number: int
    objective: str
    instructions: str
    required_source_keys: tuple[str, ...]
    evidence_slots: tuple[Mapping[str, Any], ...]
    previous_result: Mapping[str, Any]


@dataclass(frozen=True)
class InvestigationTool:
    """One caller-owned, read-only evidence capability.

    The tool key should correspond to an authorized source key whenever
    possible.  The agent may select tools, but it never gives a tool permission
    to execute an arbitrary query supplied by a model.
    """

    key: str
    description: str
    collect: Callable[[InvestigationRequest], Awaitable[Sequence[ContextFact]]]


class RetrievalPlanner(Protocol):
    async def choose(
        self, request: InvestigationRequest, tools: Sequence[InvestigationTool]
    ) -> Sequence[str]: ...


class RequiredSourcePlanner:
    """Safe local planner used when no external LLM is configured.

    This is not a SignalWeave decision fallback.  It only maps Jev's explicit
    ``required_source_keys`` to tools already supplied by the caller.  If Jev
    did not name a source, all caller-approved tools are available to the
    agent's operator rather than being invented by this example.
    """

    async def choose(
        self, request: InvestigationRequest, tools: Sequence[InvestigationTool]
    ) -> Sequence[str]:
        available = {tool.key for tool in tools}
        selected = [key for key in request.required_source_keys if key in available]
        return selected or [tool.key for tool in tools]


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("gateway response must be a JSON object")
    return value


def parse_tool_selection(text: str, allowed_keys: set[str]) -> list[str]:
    """Parse and allowlist the only output accepted from an LLM planner."""

    payload = _json_object(text)
    keys = payload.get("tool_keys")
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
        raise ValueError("gateway response must contain a string array named tool_keys")
    deduplicated: list[str] = []
    for key in keys:
        if key in allowed_keys and key not in deduplicated:
            deduplicated.append(key)
    return deduplicated


class OpenAICompatiblePlanner:
    """Use an OpenAI-compatible chat gateway only to select known evidence tools.

    The endpoint can be OpenAI, an internal gateway, or another compatible
    provider.  The response is parsed as a closed set and is never used as a
    decision, destination, SQL statement, or user-facing explanation.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def choose(
        self, request: InvestigationRequest, tools: Sequence[InvestigationTool]
    ) -> Sequence[str]:
        import httpx

        catalog = [
            {"key": tool.key, "description": tool.description}
            for tool in tools
        ]
        state = {
            "objective": request.objective,
            "instructions": request.instructions,
            "required_source_keys": list(request.required_source_keys),
            "evidence_slots": [dict(slot) for slot in request.evidence_slots],
            "available_tools": catalog,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Select only read-only evidence tools from the supplied catalog. "
                                "Return JSON exactly as {\"tool_keys\":[\"known-key\"]}. "
                                "Never invent keys and never decide whether to notify."
                            ),
                        },
                        {"role": "user", "content": json.dumps(state, sort_keys=True)},
                    ],
                },
            )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("gateway response did not contain chat completion content") from error
        if not isinstance(content, str):
            raise ValueError("gateway completion content must be text")
        return parse_tool_selection(content, {tool.key for tool in tools})


class ContextCollector(Protocol):
    async def collect(self, request: InvestigationRequest) -> ContextSnapshot: ...


class CatalogContextCollector:
    """Run a bounded, caller-owned evidence tool catalog in parallel."""

    def __init__(
        self,
        tools: Sequence[InvestigationTool],
        *,
        planner: RetrievalPlanner | None = None,
        provider: str = "caller-owned-investigation-agent",
    ) -> None:
        if not tools:
            raise ValueError("at least one investigation tool is required")
        keys = [tool.key for tool in tools]
        if len(keys) != len(set(keys)):
            raise ValueError("investigation tool keys must be unique")
        self.tools = tuple(tools)
        self.planner = planner or RequiredSourcePlanner()
        self.provider = provider

    async def collect(self, request: InvestigationRequest) -> ContextSnapshot:
        warnings: list[str] = []
        try:
            selected_keys = list(await self.planner.choose(request, self.tools))
        except Exception as error:  # noqa: BLE001 - fail closed into visible context warnings
            selected_keys = []
            warnings.append(f"retrieval planner failed: {type(error).__name__}: {error}")

        known = {tool.key for tool in self.tools}
        selected_keys = [key for key in selected_keys if key in known]
        selected = [tool for tool in self.tools if tool.key in selected_keys]
        if not selected:
            warnings.append("no authorized investigation tools were selected")

        async def run_tool(tool: InvestigationTool) -> Sequence[ContextFact]:
            try:
                facts = await tool.collect(request)
            except Exception as error:  # noqa: BLE001 - preserve partial evidence
                warnings.append(f"tool {tool.key} failed: {type(error).__name__}: {error}")
                return []
            exact_source_slot = f"source:{tool.key}"
            evidence_slots = getattr(request, "evidence_slots", ())
            matching_slots = [
                str(slot.get("key"))
                for slot in evidence_slots
                if isinstance(slot, Mapping)
                and tool.key in (slot.get("source_keys") or [])
            ]
            default_slot = (
                exact_source_slot
                if any(
                    str(slot.get("key")) == exact_source_slot
                    for slot in evidence_slots
                    if isinstance(slot, Mapping)
                )
                else matching_slots[0] if len(matching_slots) == 1 else None
            )
            return tuple(
                fact.model_copy(update={"slot_key": default_slot})
                if default_slot and not fact.slot_key
                else fact
                for fact in facts
            )

        batches = await asyncio.gather(*(run_tool(tool) for tool in selected))
        facts = [fact for batch in batches for fact in batch]
        if not facts:
            warnings.append("selected tools returned no evidence facts")
        return ContextSnapshot(
            provider=self.provider,
            version=f"agent-step-{request.step_number}-{uuid4().hex[:10]}",
            facts=facts,
            warnings=warnings,
        )


@dataclass
class AgentStep:
    number: int
    receipt_id: str | None
    outcome: str
    workflow: dict[str, Any]
    context_version: str | None = None


@dataclass
class AgentRun:
    """Inspectable trace of one caller-owned investigation loop."""

    run_id: str
    status: str
    steps: list[AgentStep] = field(default_factory=list)
    final_result: Mapping[str, Any] | None = None
    deliveries: list[Mapping[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "steps": [
                {
                    "number": step.number,
                    "receipt_id": step.receipt_id,
                    "outcome": step.outcome,
                    "workflow": step.workflow,
                    "context_version": step.context_version,
                }
                for step in self.steps
            ],
            "final_result": self.final_result,
            "deliveries": self.deliveries,
            "error": self.error,
        }


class DeliveryAdapter(Protocol):
    async def deliver(
        self, result: Mapping[str, Any], *, card_id: str, run_id: str
    ) -> Sequence[Mapping[str, Any]]: ...


class InvestigationAgent:
    """Run the bounded SignalWeave → evidence → SignalWeave loop.

    SignalWeave owns the outcome and handoff.  This class owns only the loop,
    tool calls, and delivery adapter.  It will never deliver on an
    ``investigate`` result, even if a model or tool claims the issue is obvious.
    """

    def __init__(
        self,
        gateway: SignalWeaveGateway,
        *,
        collector: ContextCollector | None = None,
        delivery: DeliveryAdapter | None = None,
        max_steps: int = 4,
        actor: str = "investigation-agent",
    ) -> None:
        if max_steps < 1 or max_steps > 20:
            raise ValueError("max_steps must be between 1 and 20")
        self.gateway = gateway
        self.collector = collector
        self.delivery = delivery
        self.max_steps = max_steps
        self.actor = actor

    async def run(self, card_id: str, *, run_id: str | None = None) -> AgentRun:
        run = AgentRun(run_id=run_id or f"run-{uuid4().hex}", status="running")
        context: ContextSnapshot | None = None
        parent_receipt_id: str | None = None
        workflow_step_key: str | None = None

        for step_number in range(1, self.max_steps + 1):
            try:
                response = await self.gateway.evaluate(
                    card_id,
                    idempotency_key=f"{run.run_id}:evaluate:{step_number}",
                    context=context,
                    parent_receipt_id=parent_receipt_id,
                    workflow_step_key=workflow_step_key,
                )
            except Exception as error:  # noqa: BLE001 - returned as an inspectable run failure
                run.status = "failed"
                run.error = f"SignalWeave evaluation failed: {type(error).__name__}: {error}"
                return run

            result = response.get("result")
            if not isinstance(result, Mapping):
                run.status = "failed"
                run.error = "SignalWeave response did not contain a result object"
                return run
            workflow = result.get("workflow")
            workflow = dict(workflow) if isinstance(workflow, Mapping) else {}
            receipt = response.get("receipt")
            receipt_id = (
                str(receipt.get("receipt_id"))
                if isinstance(receipt, Mapping) and receipt.get("receipt_id")
                else None
            )
            run.steps.append(
                AgentStep(
                    number=step_number,
                    receipt_id=receipt_id,
                    outcome=str(result.get("outcome", "unknown")),
                    workflow=workflow,
                    context_version=context.version if context else None,
                )
            )

            action = str(workflow.get("action", ""))
            if action == "suppress":
                run.status = "suppressed"
                run.final_result = result
                return run
            if action == "deliver":
                run.final_result = result
                if self.delivery is None:
                    run.status = "ready_for_delivery"
                    return run
                try:
                    run.deliveries = list(
                        await self.delivery.deliver(result, card_id=card_id, run_id=run.run_id)
                    )
                except Exception as error:  # noqa: BLE001 - never hide sink failures
                    run.status = "delivery_failed"
                    run.error = f"delivery failed: {type(error).__name__}: {error}"
                    return run
                run.status = "delivered"
                return run
            if action == "request_review":
                run.status = "needs_review"
                run.final_result = result
                return run
            if action not in {"retrieve_evidence", "repair_source", "re_evaluate"}:
                run.status = "blocked"
                run.final_result = result
                run.error = f"unsupported SignalWeave workflow action: {action or '<missing>'}"
                return run

            if action in {"retrieve_evidence", "repair_source"}:
                if self.collector is None:
                    run.status = "blocked"
                    run.final_result = result
                    run.error = "workflow requires an evidence collector"
                    return run
                request = InvestigationRequest(
                    card_id=card_id,
                    step_number=step_number,
                    objective=str(workflow.get("objective") or ""),
                    instructions=str(workflow.get("instructions") or ""),
                    required_source_keys=tuple(
                        str(key) for key in workflow.get("required_source_keys", [])
                    ),
                    evidence_slots=tuple(
                        slot
                        for slot in workflow.get("evidence_plan", {}).get("slots", [])
                        if isinstance(slot, Mapping)
                    )
                    if isinstance(workflow.get("evidence_plan"), Mapping)
                    else (),
                    previous_result=result,
                )
                try:
                    context = await self.collector.collect(request)
                except Exception as error:  # noqa: BLE001 - preserve a visible blocked state
                    run.status = "blocked"
                    run.final_result = result
                    run.error = f"evidence collection failed: {type(error).__name__}: {error}"
                    return run
                if not context.facts:
                    run.status = "blocked"
                    run.final_result = result
                    run.error = (
                        "evidence collection returned no facts; refusing to re-evaluate or deliver"
                    )
                    return run

            if receipt_id is None:
                run.status = "blocked"
                run.final_result = result
                run.error = "follow-up evaluation requires the parent SignalWeave receipt"
                return run
            parent_receipt_id = receipt_id
            workflow_step_key = str(workflow.get("step_key") or f"step-{step_number}")

        run.status = "max_steps_exceeded"
        run.error = f"no terminal handoff after {self.max_steps} evaluations"
        return run


class InProcessSignalWeaveGateway:
    """Small test/demo gateway around a callable that implements the same contract."""

    def __init__(self, evaluator: Callable[..., Awaitable[Mapping[str, Any]]]) -> None:
        self.evaluator = evaluator

    async def evaluate(self, card_id: str, **kwargs: Any) -> Mapping[str, Any]:
        return await self.evaluator(card_id, **kwargs)

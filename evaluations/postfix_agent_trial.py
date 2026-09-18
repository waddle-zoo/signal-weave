"""Run a post-fix MCP-only Luna agent trial over the enterprise fixture.

This is evaluation code, not product runtime. The agent sees only the MCP tool
schemas and the task brief. Expected source refs stay in the scorer. The
fixture is enriched with tenant-bound ``ResourceContract`` metadata so the
trial exercises the same catalog filtering used by deployments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from evaluations.enterprise_trial import (
    TraceSink,
    _stable_hash,
    audit_trace,
    load_fixture,
)
from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import ResourceContract, ResourceDescriptor, ResourceSnapshot
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import JsonInsightCardStore
from signalweave.typesafe_adapter import JevJudger

DEFAULT_FIXTURE = Path("artifacts/enterprise/full-luna-fixture.json")
ENTERPRISE_TENANTS = {
    "Northstar Commerce": "northstar",
    "Harbor Bank": "harbor",
    "OrbitWorks SaaS": "orbitworks",
}
TENANT_PREFIXES = {
    "northstar": "northstar",
    "harbor": "harbor",
    "orbit": "orbitworks",
    "orbitworks": "orbitworks",
}
VARIANTS = (
    "corroborated_notify",
    "explained_ignore",
    "contradictory_investigate",
    "stale_escalation",
    "missing_baseline",
    "source_failure",
    "definition_mismatch",
)


def _resource_tenant(resource: str) -> str:
    slug = resource.split(":", 1)[-1]
    for prefix, tenant in TENANT_PREFIXES.items():
        if slug.startswith(f"{prefix}-") or slug.startswith(f"scenario-{prefix}-"):
            return tenant
    raise ValueError(f"cannot infer tenant from synthetic resource: {resource}")


def _source_status(metadata: dict[str, Any]) -> str:
    value = str(metadata.get("data_state") or metadata.get("source_status") or "healthy")
    return {
        "failure": "failed",
        "failed": "failed",
        "delayed": "stale",
        "stale": "stale",
        "missing_baseline": "ambiguous",
    }.get(value, "healthy")


def _typed_descriptor(record: dict[str, Any]) -> ResourceDescriptor:
    descriptor = ResourceDescriptor.model_validate(record["descriptor"])
    metadata = dict(descriptor.metadata)
    tenant_id = _resource_tenant(descriptor.resource)
    contract = ResourceContract(
        tenant_id=tenant_id,
        domain=str(metadata.get("domain") or "unknown"),
        scope=f"{tenant_id}:{metadata.get('domain', 'unknown')}:{descriptor.title}",
        metric_names=[descriptor.title, str(metadata.get("linked_dashboard") or "")],
        population=str(metadata.get("population") or "company operating population"),
        grain=str(metadata.get("grain") or "resource-defined grain"),
        freshness_sla_hours=(
            float(metadata["refresh_period_minutes"]) / 60
            if metadata.get("refresh_period_minutes") is not None
            else None
        ),
        lineage=[descriptor.resource],
        roles=[str(metadata.get("owner_team") or "unknown")],
        source_status=_source_status(metadata),
        authorized=True,
    )
    return descriptor.model_copy(update={"contract": contract})


class TenantAwareSyntheticAdapter:
    """Fixture adapter that exposes typed tenant contracts, never hidden labels."""

    def __init__(self, adapter: str, records: list[dict[str, Any]]) -> None:
        self.name = adapter
        self._records = {
            str(record["descriptor"]["resource"]): record
            for record in records
            if record["descriptor"]["adapter"] == adapter
        }

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [
            _typed_descriptor(record)
            for record in sorted(self._records.values(), key=lambda item: item["descriptor"]["title"])
        ]

    async def inspect(self, source) -> ResourceSnapshot:
        record = self._records[source.resource]
        return ResourceSnapshot.model_validate(record["snapshot"]).model_copy(
            update={"source_key": source.key}
        )


def _tool_specs() -> list[dict[str, Any]]:
    source = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "adapter": {"type": "string"},
            "resource": {"type": "string"},
            "label": {"type": "string"},
            "parameters": {"type": "object", "additionalProperties": True},
            "required": {"type": "boolean"},
        },
        "required": ["key", "adapter", "resource", "label"],
        "additionalProperties": False,
    }

    def fn(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": parameters,
            "strict": False,
        }

    return [
        fn(
            "discover_insight_sources",
            "Rank authorized source candidates for a monitoring goal. Use returned refs exactly.",
            {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "adapter": {"type": ["string", "null"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["goal"],
                "additionalProperties": False,
            },
        ),
        fn(
            "list_resources",
            "List the authorized typed source catalog visible to this tenant.",
            {
                "type": "object",
                "properties": {"adapter": {"type": ["string", "null"]}},
                "required": [],
                "additionalProperties": False,
            },
        ),
        fn(
            "inspect_resource",
            "Inspect one authorized source and its evidence. Direct inspection is catalog-checked.",
            {
                "type": "object",
                "properties": {
                    "adapter": {"type": "string"},
                    "resource": {"type": "string"},
                    "label": {"type": ["string", "null"]},
                    "parameters": {"type": ["object", "null"], "additionalProperties": True},
                },
                "required": ["adapter", "resource"],
                "additionalProperties": False,
            },
        ),
        fn(
            "draft_insight_card",
            "Draft a card over the selected source refs. Use at least every source needed to answer the questions.",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "what_to_watch": {"type": "string"},
                    "why_watch": {"type": "string"},
                    "sources": {"type": "array", "items": source, "minItems": 1},
                    "watch_for": {"type": "array", "items": {"type": "string"}},
                    "questions": {"type": "array", "items": {"type": "string"}},
                    "delivery_methods": {"type": "array", "items": {"type": "object"}},
                    "card_id": {"type": ["string", "null"]},
                },
                "required": ["title", "what_to_watch", "why_watch", "sources"],
                "additionalProperties": False,
            },
        ),
        fn(
            "simulate_insight_card",
            "Run a delivery-disabled preview of a draft card.",
            {
                "type": "object",
                "properties": {"card_id": {"type": "string"}},
                "required": ["card_id"],
                "additionalProperties": False,
            },
        ),
        fn(
            "approve_insight_card",
            "Approve a complete draft for evaluation; approval does not deliver anything.",
            {
                "type": "object",
                "properties": {"card_id": {"type": "string"}, "actor": {"type": "string"}},
                "required": ["card_id"],
                "additionalProperties": False,
            },
        ),
        fn(
            "evaluate_insight_card",
            "Evaluate an approved card over fresh source evidence with delivery disabled.",
            {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string"},
                    "idempotency_key": {"type": ["string", "null"]},
                    "actor": {"type": "string"},
                },
                "required": ["card_id"],
                "additionalProperties": False,
            },
        ),
    ]


def _task_prompt(task: dict[str, Any]) -> str:
    brief = task["brief"]
    return f"""You are acting as {brief['persona']['name']} at {brief['enterprise_name']}.

You have access only to SignalWeave MCP tools for this tenant. Do not inspect files,
call source systems directly, invent source identifiers, or use the hidden expected
labels. The catalog is intentionally noisy and contains multiple adapters and
related resources. You must use returned source references exactly.

Business objective: {task['enterprise_objective']}
What to watch: {brief['what_to_watch']}
Why: {brief['why_watch']}
Things to look for: {json.dumps(brief['watch_for'])}
Questions to answer: {json.dumps(brief['questions'])}
Source hints from the owner: {json.dumps(brief.get('source_hints', []))}
Allowed delivery options: {json.dumps(brief['delivery_context'])}

Required workflow:
1. Discover the relevant sources using the goal. Use more than one source when the
   questions require corroboration, quality, freshness, or a related signal.
2. Inspect every candidate you intend to use. If a source is unavailable or not in
   the authorized catalog, do not substitute an invented ref.
3. Draft a complete card preserving the owner's intent, all relevant watch items,
   questions, selected source refs, and allowed delivery methods.
4. Simulate the card, approve it only if complete, then evaluate it.
5. Finish with the evidence-backed result. Never claim a source was inspected unless
   the tool returned it.
"""


@dataclass
class AgentRun:
    task: dict[str, Any]
    session_id: str
    final_text: str
    calls: int
    api_requests: int
    elapsed_ms: float


class ResponsesToolAgent:
    def __init__(self, *, api_key: str, model: str, timeout: float = 90.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.tools = _tool_specs()

    async def run(
        self,
        prompt: str,
        call_tool,
        *,
        max_turns: int = 14,
    ) -> tuple[str, int, int]:
        headers = {
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        request_input: Any = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ]
        api_requests = 0
        tool_calls = 0
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for _turn in range(max_turns):
                body = {
                    "model": self.model,
                    "input": request_input,
                    "tools": self.tools,
                    "tool_choice": "auto",
                    "store": False,
                    "max_output_tokens": 1800,
                }
                response = None
                for attempt in range(3):
                    try:
                        response = await client.post(
                            "https://api.openai.com/v1/responses", headers=headers, json=body
                        )
                        break
                    except httpx.TransportError:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(1.5 * (attempt + 1))
                assert response is not None
                api_requests += 1
                if response.is_error:
                    raise RuntimeError(f"OpenAI Responses API {response.status_code}: {response.text[:500]}")
                payload = response.json()
                calls = [item for item in payload.get("output", []) if item.get("type") == "function_call"]
                if not calls:
                    return self._output_text(payload), tool_calls, api_requests
                outputs = []
                for call in calls:
                    tool_calls += 1
                    try:
                        arguments = json.loads(call.get("arguments") or "{}")
                        if not isinstance(arguments, dict):
                            raise ValueError("tool arguments must be an object")
                        result = await call_tool(call["name"], arguments)
                        output = json.dumps(result, default=str)
                    except Exception as error:  # noqa: BLE001 - return tool errors to the agent
                        output = json.dumps({"error": f"{type(error).__name__}: {error}"})
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.get("call_id"),
                            "output": output,
                        }
                    )
                request_input = [*request_input, *payload.get("output", []), *outputs]
        return "Agent stopped after max_turns without a final message.", tool_calls, api_requests

    @staticmethod
    def _output_text(payload: dict[str, Any]) -> str:
        texts: list[str] = []
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        return "\n".join(texts)


def _load_openai_key(dotenv: str | Path | None) -> str:
    if os.getenv("OPENAI_API_KEY"):
        return str(os.environ["OPENAI_API_KEY"])
    if dotenv:
        for line in Path(dotenv).read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if value and not value.startswith("<"):
                    return value
    raise RuntimeError("set OPENAI_API_KEY or provide --dotenv with OPENAI_API_KEY")


def _load_typesafe_key(path: str | Path | None) -> str:
    if os.getenv("TYPESAFE_API_KEY"):
        return str(os.environ["TYPESAFE_API_KEY"])
    if path:
        value = Path(path).read_text().strip()
        if value:
            return value
    raise RuntimeError("set TYPESAFE_API_KEY or provide --typesafe-key-file")


def _tenant_for_task(task: dict[str, Any]) -> str:
    try:
        return ENTERPRISE_TENANTS[str(task["brief"]["enterprise_name"])]
    except KeyError as error:
        raise ValueError(f"unknown task enterprise: {task['brief']['enterprise_name']}") from error


def _build_runtime(
    fixture: dict[str, Any],
    *,
    tenant: str,
    typesafe_key: str,
    trace: TraceSink,
    actor: str,
    session_id: str,
    store_path: Path,
) -> Runtime:
    from evaluations.enterprise_trial import TracedAdapter, TracedJudger

    records = fixture["resources"]
    adapters = [
        TracedAdapter(
            TenantAwareSyntheticAdapter(adapter, records), trace, actor, session_id
        )
        for adapter in fixture["stats"]["adapters"]
    ]
    registry = SourceRegistry(
        adapters,
        max_concurrency=16,
        authorized_tenants={tenant},
        enforce_catalog=True,
    )
    delegate = JevJudger(api_key=typesafe_key)
    judger = TracedJudger(delegate, trace, actor, session_id)
    return Runtime(
        card_store=JsonInsightCardStore(store_path),
        sources=registry,
        engine=InsightEngine(judger=judger, registry=registry),
    )


def _select_tasks(fixture: dict[str, Any], per_variant: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for task in fixture["tasks"]:
        groups[(task["brief"]["enterprise_name"], task["variant"])].append(task)
    selected: list[dict[str, Any]] = []
    for enterprise in ENTERPRISE_TENANTS:
        for variant in VARIANTS:
            selected.extend(sorted(groups[(enterprise, variant)], key=lambda item: item["id"])[:per_variant])
    return selected


async def _run_session(
    task: dict[str, Any],
    *,
    fixture: dict[str, Any],
    trace: TraceSink,
    agent: ResponsesToolAgent,
    typesafe_key: str,
    store_dir: Path,
) -> AgentRun:
    tenant = _tenant_for_task(task)
    session_id = f"postfix-luna-{task['session_token']}"
    actor = f"luna:{task['persona_id']}"
    trace.emit(
        "session.started",
        actor=actor,
        session_id=session_id,
        payload={
            "task_token": task["session_token"],
            "model": agent.model,
            "evaluator": "luna-agent",
            "tenant_id": tenant,
            "allowed_tools": [tool["name"] for tool in agent.tools],
            "fixture": "typed-enterprise-portfolio",
        },
    )
    runtime = _build_runtime(
        fixture,
        tenant=tenant,
        typesafe_key=typesafe_key,
        trace=trace,
        actor=actor,
        session_id=session_id,
        store_path=store_dir / f"{session_id}.json",
    )
    server = create_mcp(runtime)

    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        started = time.perf_counter()
        trace.emit(
            "mcp.call.started",
            actor=actor,
            session_id=session_id,
            payload={"tool": name, "arguments": arguments},
        )
        try:
            _meta, structured = await server.call_tool(name, arguments)
            result = structured.get("result", structured) if isinstance(structured, dict) else structured
            if hasattr(result, "model_dump"):
                result = result.model_dump(mode="json")
            trace.emit(
                "mcp.call.completed",
                actor=actor,
                session_id=session_id,
                payload={
                    "tool": name,
                    "arguments": arguments,
                    "result": result,
                    "result_hash": _stable_hash(result),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return result
        except Exception as error:  # noqa: BLE001 - the agent must see tool failures
            trace.emit(
                "mcp.call.failed",
                actor=actor,
                session_id=session_id,
                payload={
                    "tool": name,
                    "arguments": arguments,
                    "error": f"{type(error).__name__}: {error}",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return {"error": f"{type(error).__name__}: {error}"}

    started = time.perf_counter()
    final_text, calls, api_requests = await agent.run(_task_prompt(task), call_tool)
    trace.emit(
        "agent.completed",
        actor=actor,
        session_id=session_id,
        payload={
            "model": agent.model,
            "tool_calls": calls,
            "api_requests": api_requests,
            "final_text": final_text,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return AgentRun(task, session_id, final_text, calls, api_requests, (time.perf_counter() - started) * 1000)


def _resource_refs_from_trace(session_events: list[dict[str, Any]]) -> set[str]:
    for event in reversed(session_events):
        if event.get("event_type") != "mcp.call.completed":
            continue
        if event.get("payload", {}).get("tool") != "evaluate_insight_card":
            continue
        result = event.get("payload", {}).get("result", {})
        result = result.get("result", result) if isinstance(result, dict) else {}
        refs = set()
        for evidence in result.get("evidence", []):
            if evidence.get("source_key"):
                refs.add(str(evidence["source_key"]))
        # Evidence source keys are card-owned keys. The card itself is read from the
        # preceding completed evaluate payload only when the engine returns it.
        card = result.get("card", {})
        for source in card.get("sources", []):
            refs.add(f"{source.get('adapter')}|{source.get('resource')}")
        return refs
    return set()


def score_agent_trace(fixture: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    events = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_session[str(event["session_id"])].append(event)
    tasks = {task["session_token"]: task for task in fixture["tasks"]}
    all_tenants = {
        f"{item['descriptor']['adapter']}|{item['descriptor']['resource']}": _resource_tenant(
            item["descriptor"]["resource"]
        )
        for item in fixture["resources"]
    }
    rows: list[dict[str, Any]] = []
    for session_id, session_events in sorted(by_session.items()):
        started = next(
            (event for event in session_events if event.get("event_type") == "session.started"),
            None,
        )
        task = tasks.get(str(started.get("payload", {}).get("task_token"))) if started else None
        if task is None:
            continue
        tenant = _tenant_for_task(task)
        completed = [event for event in session_events if event.get("event_type") == "mcp.call.completed"]
        evaluate = [
            event for event in completed if event.get("payload", {}).get("tool") == "evaluate_insight_card"
        ]
        result = {}
        evaluated_payload: dict[str, Any] = {}
        if evaluate:
            raw = evaluate[-1]["payload"].get("result", {})
            evaluated_payload = raw if isinstance(raw, dict) else {}
            result = evaluated_payload.get("result", evaluated_payload)
        card = evaluated_payload.get("card", {}) if evaluated_payload else {}
        if not card:
            for event in reversed(completed):
                if event.get("payload", {}).get("tool") not in {
                    "draft_insight_card",
                    "propose_insight_card",
                    "approve_insight_card",
                }:
                    continue
                candidate = event.get("payload", {}).get("result", {})
                if isinstance(candidate, dict) and isinstance(candidate.get("card"), dict):
                    card = candidate["card"]
                    break
                proposal = candidate.get("proposal", {}) if isinstance(candidate, dict) else {}
                if isinstance(proposal, dict) and isinstance(proposal.get("card"), dict):
                    card = proposal["card"]
                    break
        card_sources = {
            f"{item.get('adapter')}|{item.get('resource')}"
            for item in card.get("sources", [])
            if item.get("adapter") and item.get("resource")
        }
        expected = set(task["expected_source_resources"])
        inspected = {
            f"{event['payload'].get('adapter')}|{event['payload'].get('resource')}"
            for event in session_events
            if event.get("event_type") == "source.inspect.completed"
        }
        wrong_tenant_attempts = 0
        leaked_wrong_tenant = 0
        for event in completed:
            payload = event.get("payload", {})
            args = payload.get("arguments", {})
            refs = []
            if payload.get("tool") == "inspect_resource" and args.get("adapter") and args.get("resource"):
                refs.append(f"{args['adapter']}|{args['resource']}")
            if payload.get("tool") == "draft_insight_card":
                refs.extend(
                    f"{item.get('adapter')}|{item.get('resource')}"
                    for item in args.get("sources", [])
                    if item.get("adapter") and item.get("resource")
                )
            for ref in refs:
                if all_tenants.get(ref) and all_tenants[ref] != tenant:
                    wrong_tenant_attempts += 1
                    response = payload.get("result", {})
                    if payload.get("tool") == "inspect_resource" and not response.get("error"):
                        leaked_wrong_tenant += 1
        visible_catalog_leaks = 0
        for event in completed:
            payload = event.get("payload", {})
            if payload.get("tool") != "list_resources":
                continue
            resources = payload.get("result", [])
            for resource in resources if isinstance(resources, list) else []:
                contract = resource.get("contract", {})
                if contract.get("tenant_id") != tenant or not contract.get("authorized", False):
                    visible_catalog_leaks += 1
        expected_outcome = task["expected_outcome"]
        actual_outcome = result.get("outcome")
        expected_methods = task["expected_delivery_methods"]
        actual_methods = [item.get("key") for item in result.get("delivery_methods", [])]
        workflow = [
            any(event.get("payload", {}).get("tool") == name for event in completed)
            for name in ("discover_insight_sources", "draft_insight_card", "simulate_insight_card", "approve_insight_card", "evaluate_insight_card")
        ]
        card_complete = bool(
            card.get("what_to_watch")
            and card.get("why_watch")
            and (card.get("watch_for") or card.get("questions"))
            and card_sources
        )
        provenance = bool(result.get("evidence")) and bool(result.get("source_keys")) and bool(inspected)
        exact = (
            all(workflow)
            and card_complete
            and card_sources == expected
            and actual_outcome == expected_outcome
            and actual_methods == expected_methods
            and provenance
        )
        automatic = actual_outcome in {"notify", "escalate"}
        rows.append(
            {
                "session_id": session_id,
                "task_id": task["id"],
                "enterprise": task["brief"]["enterprise_name"],
                "variant": task["variant"],
                "expected_outcome": expected_outcome,
                "actual_outcome": actual_outcome,
                "exact": exact,
                "workflow_complete": all(workflow),
                "card_complete": card_complete,
                "provenance_complete": provenance,
                "expected_source_count": len(expected),
                "selected_source_count": len(card_sources),
                "source_selection_exact": card_sources == expected,
                "required_source_recall": len(card_sources & expected) / len(expected) if expected else 1.0,
                "wrong_tenant_attempts": wrong_tenant_attempts,
                "wrong_tenant_leaks": leaked_wrong_tenant,
                "visible_catalog_leaks": visible_catalog_leaks,
                "automatic_action": automatic,
                "unsafe_automatic_action": automatic and not exact,
                "mcp_calls": len(completed),
            }
        )
    return {
        "session_count": len(rows),
        "exact_decisions": sum(row["exact"] for row in rows),
        "workflow_complete": sum(row["workflow_complete"] for row in rows),
        "card_complete": sum(row["card_complete"] for row in rows),
        "provenance_complete": sum(row["provenance_complete"] for row in rows),
        "source_selection_exact": sum(row["source_selection_exact"] for row in rows),
        "required_source_recall": sum(row["required_source_recall"] for row in rows) / len(rows) if rows else 0.0,
        "wrong_tenant_attempts": sum(row["wrong_tenant_attempts"] for row in rows),
        "wrong_tenant_leaks": sum(row["wrong_tenant_leaks"] for row in rows),
        "visible_catalog_leaks": sum(row["visible_catalog_leaks"] for row in rows),
        "unsafe_automatic_actions": sum(row["unsafe_automatic_action"] for row in rows),
        "trace_integrity": audit_trace(trace_path),
        "rows": rows,
    }


async def run_trial(args: argparse.Namespace) -> dict[str, Any]:
    fixture = load_fixture(args.fixture)
    tasks = _select_tasks(fixture, args.per_variant)
    if args.limit is not None:
        tasks = tasks[: args.limit]
    openai_key = _load_openai_key(args.dotenv)
    typesafe_key = _load_typesafe_key(args.typesafe_key_file)
    trace_path = Path(args.trace)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    store_dir = Path(args.store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    agent = ResponsesToolAgent(api_key=openai_key, model=args.model)
    semaphore = asyncio.Semaphore(args.concurrency)

    async def run_one(task: dict[str, Any]) -> AgentRun:
        async with semaphore:
            try:
                return await _run_session(
                    task,
                    fixture=fixture,
                    trace=TraceSink(
                        trace_path,
                        experiment_id="signalweave-postfix-agent",
                        run_id=args.run_id,
                    ),
                    agent=agent,
                    typesafe_key=typesafe_key,
                    store_dir=store_dir,
                )
            except Exception as error:  # noqa: BLE001 - record provider failures in the trial
                session_id = f"postfix-luna-{task['session_token']}"
                trace = TraceSink(
                    trace_path,
                    experiment_id="signalweave-postfix-agent",
                    run_id=args.run_id,
                )
                trace.emit(
                    "agent.failed",
                    actor=f"luna:{task['persona_id']}",
                    session_id=session_id,
                    payload={"error": f"{type(error).__name__}: {error}"},
                )
                return AgentRun(task, session_id, "", 0, 0, 0.0)

    await asyncio.gather(*(run_one(task) for task in tasks))
    report = score_agent_trace(fixture, trace_path)
    report.update(
        {
            "model": args.model,
            "tasks_requested": len(tasks),
            "per_variant": args.per_variant,
            "fixture": str(args.fixture),
            "independent_labels": True,
            "expected_source_refs_sent_to_agent": False,
            "tenant_catalog_enforced": True,
        }
    )
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the post-fix Luna MCP trial")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--dotenv", type=Path)
    parser.add_argument("--typesafe-key-file", type=Path)
    parser.add_argument("--trace", type=Path, default=Path("artifacts/enterprise/postfix-luna.trace.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/enterprise/postfix-luna.report.json"))
    parser.add_argument("--store-dir", type=Path, default=Path("artifacts/enterprise/postfix-luna-cards"))
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--per-variant", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--run-id", default="postfix-luna")
    return parser


def main() -> None:
    args = _parser().parse_args()
    report = asyncio.run(run_trial(args))
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2, default=str))


if __name__ == "__main__":
    main()

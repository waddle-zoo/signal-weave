"""Fair live Luna comparison for the Northstar multi-step workflow.

The Jev-only replay is intentionally not used as the product claim: Jev is a
typed retrieval/preflight layer, while the frontier agent owns the analytical
interpretation and the caller-owned diagnostic follow-up.  This harness runs
the same Luna agent twice for each case.  The treatment receives only a live
Jev preflight bundle derived from the same card and source snapshots.

Labels and diagnostic facts stay in the parent process.  The diagnostic facts
are exposed to either arm only through the same caller-owned tool after the
agent submits an initial ``investigate`` result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from evaluations.northstar_growth_history_trial import (
    _build_resources,
    _load_period_data,
    load_spec as load_history_spec,
)
from evaluations.northstar_multistep_trial import (
    _case_lookup,
    card_for_trial,
    load_trial_spec,
)
from evaluations.paired_agent_trial import (
    JevRetriever,
    QueryExecutor,
    QueryLedger,
    _digest,
    _load_dotenv_key,
    _preflight_summary,
)
from signalweave.models import InsightCard, Outcome
from signalweave.typesafe_adapter import load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "examples" / "northstar-multistep-trial.json"
DEFAULT_HISTORY_SPEC = ROOT / "examples" / "northstar-growth-historical-decisions.json"
DEFAULT_SEED = ROOT / "evaluations" / "data" / "northstar-multistep-seed"
DEFAULT_REPORT = Path("artifacts/northstar-multistep-paired-trial/report.json")


def _delivery(outcome: str) -> str:
    return {
        "ignore": "none",
        "notify": "leadership",
        "investigate": "analytics",
        "insufficient_data": "data-trust",
        "escalate": "none",
    }[outcome]


def _source_payload(resource: Any) -> dict[str, Any]:
    observations = [item.model_dump(mode="json") for item in resource.observations]
    evidence = [item.model_dump(mode="json") for item in resource.evidence]
    return {
        "ref": resource.source_key,
        "adapter": resource.adapter,
        "resource": resource.resource,
        "kind": "dashboard" if resource.adapter == "superset" else "table",
        "title": resource.title,
        "description": resource.description,
        "contract": resource.contract.model_dump(mode="json"),
        "evidence": " ".join(item.statement for item in resource.evidence),
        "observations": observations,
        "source_evidence": evidence,
    }


def _chart_payload(resource: Any, observation: Any) -> dict[str, Any]:
    return {
        "id": f"{resource.source_key}|{observation.subject_id}",
        "source_ref": resource.source_key,
        "title": observation.subject_label,
        "metric": observation.metric,
        "unit": observation.unit,
        "current": observation.current,
        "baseline": observation.baseline,
        "change_pct": observation.change_pct,
        "dimensions": observation.dimensions,
        "note": (
            f"{observation.subject_label}: current={observation.current}, "
            f"baseline={observation.baseline}, change_pct={observation.change_pct}."
        ),
    }


def build_cases(
    *,
    seed_dir: Path = DEFAULT_SEED,
    spec_path: Path = DEFAULT_SPEC,
    history_spec_path: Path = DEFAULT_HISTORY_SPEC,
) -> list[dict[str, Any]]:
    """Build public case inputs and private labels from separate fixture fields."""

    spec = load_trial_spec(spec_path)
    history = load_history_spec(history_spec_path)
    period = _load_period_data(seed_dir)
    lookup = _case_lookup(history)
    card = card_for_trial(spec)
    cases: list[dict[str, Any]] = []
    for index, scenario in enumerate(spec["scenarios"], start=1):
        key = (str(scenario["period_id"]), str(scenario["base_case_id"]))
        historical = lookup.get(key)
        if historical is None:
            raise ValueError(f"scenario {scenario['id']} does not match history case {key}")
        resources = _build_resources(period, historical.replay_case)
        sources = [_source_payload(resource) for resource in resources]
        charts = [
            _chart_payload(resource, observation)
            for resource in resources
            for observation in resource.observations
        ]
        case_id = f"case-{index:03d}"
        shared_input = {
            "case_id": case_id,
            "scenario_family": "northstar-executive-pulse",
            "tenant": "northstar-outfitters",
            "principal": "growth-monitoring-agent",
            "authorization_scope": "northstar-outfitters:analytics",
            "snapshot_version": f"northstar-multistep-{scenario['period_id']}",
            "card": card.execution_payload(),
            "cached_charts": charts,
            "authorized_source_catalog": [
                {
                    key: source[key]
                    for key in (
                        "ref", "adapter", "resource", "kind", "title", "description", "contract"
                    )
                }
                for source in sources
            ],
            "context_fields": [
                "human-authored-card",
                "cached-source-observations",
                "source-contracts",
                "tenant-and-permission-scope",
                "snapshot-version",
            ],
        }
        cases.append(
            {
                "case_id": case_id,
                "scenario": str(scenario["id"]),
                "shared_input": shared_input,
                "sources": sources,
                "query": {
                    "group": f"northstar-multistep:{scenario['id']}",
                    "bytes_scanned": 2_000_000_000,
                    "cpu_seconds": 180,
                    "evidence_refs": [source["ref"] for source in sources],
                    "finding": "The bounded source query returned the authorized source evidence for this snapshot.",
                },
                "diagnostic_facts": list(scenario.get("diagnostic_facts", []))
                + list(scenario.get("additional_diagnostic_facts") or []),
                "label": {
                    "expected_initial": str(scenario["expected_initial"]),
                    "expected_final": str(scenario["expected_final"]),
                    "initial_delivery": _delivery(str(scenario["expected_initial"])),
                    "final_delivery": _delivery(str(scenario["expected_final"])),
                    "required_final_evidence": list(scenario.get("required_final_evidence", [])),
                },
            }
        )
    return cases


def _public_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        key: case[key]
        for key in ("case_id", "scenario", "shared_input", "sources", "query")
    }


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "strict": False,
    }


def _tool_specs() -> list[dict[str, Any]]:
    return [
        _tool("get_cached_charts", "Return the cached observations available to this workflow.", {}, []),
        _tool(
            "list_authorized_sources",
            "List the tenant-scoped source catalog. Use refs exactly as returned.",
            {},
            [],
        ),
        _tool(
            "inspect_source",
            "Inspect one authorized source and its normalized observations and contract.",
            {"source_ref": {"type": "string"}},
            ["source_ref"],
        ),
        _tool(
            "retrieve_diagnostic_context",
            "Retrieve caller-owned diagnostic and ownership facts after an initial investigate result.",
            {"reason": {"type": "string"}},
            ["reason"],
        ),
        _tool(
            "run_diagnostic_query",
            "Run one bounded read-only source query when the available evidence cannot answer the card.",
            {"reason": {"type": "string"}},
            ["reason"],
        ),
        _tool(
            "submit_analysis",
            "Submit one typed stage of the push-based analysis. Use initial before final.",
            {
                "stage": {"type": "string", "enum": ["initial", "final"]},
                "outcome": {
                    "type": "string",
                    "enum": ["ignore", "notify", "investigate", "insufficient_data", "escalate"],
                },
                "delivery": {"type": "string"},
                "reason": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                "query_justified": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            ["stage", "outcome", "delivery", "reason", "evidence_refs", "query_justified", "confidence"],
        ),
    ]


def _agent_prompt(
    case: dict[str, Any], treatment: bool, retrieval_bundle: dict[str, Any] | None = None
) -> str:
    prompt = f"""You are a scheduled analytical agent for Northstar Outfitters.

No human typed a question. The owner-authored monitoring card woke you up. Use
only the tenant-scoped data and tools supplied here. The card policy is the
authority; do not invent thresholds, recipients, sources, or causal claims.

At the initial stage, inspect the cached charts and any sources needed to apply
the card. Submit exactly one stage=initial analysis. If the result is
investigate and the card needs a why investigation, do not deliver yet: call
retrieve_diagnostic_context, then submit stage=final using the returned facts.
If the initial result is terminal (ignore, notify, insufficient_data, or
escalate), it is also the final result. Do not call the context tool merely to
make a quiet case more interesting. A source being authorized is not evidence
that it is relevant. Distinguish correlation from causation and preserve
provenance in evidence_refs.

The final submission must use a literal delivery key from the card or 'none'.
Use only the allowed tools. Stop after the final stage is accepted.

Shared workflow input:
{json.dumps(case['shared_input'], sort_keys=True)}
"""
    if treatment and retrieval_bundle is not None:
        prompt += (
            "\nSignalWeave Jev preflight bundle (derived from the same input before the agent woke up):\n"
            f"{json.dumps(retrieval_bundle, sort_keys=True)}\n"
            "Treat this as typed retrieval guidance, not as the workflow outcome. Verify source refs and "
            "apply the human-authored card policy yourself. The preflight may include a query result; do "
            "not repeat that exact query."
        )
    return prompt


class MultiStepAgent:
    def __init__(self, *, api_key: str, model: str, timeout: float = 90.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def run(
        self,
        case: dict[str, Any],
        *,
        arm: str,
        treatment: bool,
        retriever: JevRetriever | None,
        executor: QueryExecutor,
        retrieval_bundle: dict[str, Any] | None,
        max_turns: int = 14,
    ) -> dict[str, Any]:
        headers = {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        request_input: list[Any] = [{
            "role": "user",
            "content": [{"type": "input_text", "text": _agent_prompt(case, treatment, retrieval_bundle)}],
        }]
        events: list[dict[str, Any]] = []
        submissions: list[dict[str, Any]] = []
        initial_submission: dict[str, Any] | None = None
        final_submission: dict[str, Any] | None = None
        context_retrieved = False
        context_fact_ids: list[str] = []
        protocol_errors: list[str] = []
        oracle_leaks = 0
        api_requests = 0
        tool_calls = 0
        input_tokens = 0
        output_tokens = 0
        started = time.perf_counter()

        def _record_event(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
            events.append({
                "turn": len(events) + 1,
                "tool": name,
                "arguments": arguments,
                "result_digest": _digest(result),
                "error": "error" in result,
                "result_summary": {
                    key: result[key]
                    for key in ("path", "probabilities", "evidence_refs", "next_step", "context_fact_ids")
                    if key in result
                },
            })

        async def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
            nonlocal initial_submission, final_submission, context_retrieved, context_fact_ids
            if name == "get_cached_charts":
                return {"charts": case["shared_input"]["cached_charts"]}
            if name == "list_authorized_sources":
                return {"sources": case["shared_input"]["authorized_source_catalog"]}
            if name == "inspect_source":
                ref = str(args.get("source_ref", ""))
                source = next((item for item in case["sources"] if item["ref"] == ref), None)
                return (
                    {"source": source, "evidence_refs": [ref]}
                    if source
                    else {"error": "source_ref is not authorized"}
                )
            if name == "retrieve_diagnostic_context":
                context_retrieved = True
                facts = case["diagnostic_facts"]
                context_fact_ids = [str(item["fact_id"]) for item in facts]
                return {
                    "provider": "northstar-diagnostic-systems",
                    "version": f"{case['scenario']}:diagnostic-1",
                    "facts": facts,
                    "evidence_refs": context_fact_ids,
                }
            if name == "run_diagnostic_query":
                return {"query": await executor.execute(reason=str(args.get("reason", "unspecified")))}
            if name == "submit_analysis":
                submission = dict(args)
                stage = str(submission.get("stage", ""))
                if stage not in {"initial", "final"}:
                    protocol_errors.append("invalid stage")
                    return {"error": "stage must be initial or final"}
                if stage == "final" and initial_submission is None:
                    protocol_errors.append("final submitted before initial")
                    return {"error": "submit stage=initial before stage=final"}
                if stage == "initial" and initial_submission is not None:
                    protocol_errors.append("duplicate initial submission")
                    return {"error": "initial stage already submitted"}
                submissions.append(submission)
                if stage == "initial":
                    initial_submission = submission
                    if submission.get("outcome") == "investigate" and case["diagnostic_facts"]:
                        return {"accepted": True, "next_step": "retrieve_diagnostic_context"}
                    final_submission = submission
                    return {"accepted": True, "complete": True}
                if case["diagnostic_facts"] and not context_retrieved:
                    protocol_errors.append("final submitted without diagnostic context")
                    return {"error": "retrieve diagnostic context before final"}
                final_submission = submission
                return {"accepted": True, "complete": True}
            return {"error": f"unknown tool {name}"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for turn in range(max_turns):
                body = {
                    "model": self.model,
                    "input": request_input,
                    "tools": _tool_specs(),
                    "tool_choice": "auto",
                    "store": False,
                    "max_output_tokens": 1600,
                }
                response = await client.post(
                    "https://api.openai.com/v1/responses", headers=headers, json=body
                )
                api_requests += 1
                if response.is_error:
                    raise RuntimeError(f"OpenAI Responses API {response.status_code}: {response.text[:500]}")
                payload = response.json()
                usage = payload.get("usage", {}) or {}
                input_tokens += int(usage.get("input_tokens", 0) or 0)
                output_tokens += int(usage.get("output_tokens", 0) or 0)
                calls = [item for item in payload.get("output", []) if item.get("type") == "function_call"]
                if not calls:
                    protocol_errors.append("agent returned no tool call")
                    break
                outputs = []
                for call in calls:
                    tool_calls += 1
                    name = str(call.get("name"))
                    try:
                        arguments = json.loads(call.get("arguments") or "{}")
                        result = await call_tool(name, arguments)
                    except Exception as error:  # noqa: BLE001 - preserve failures in the denominator
                        arguments = {}
                        result = {"error": f"{type(error).__name__}: {error}"}
                        protocol_errors.append(result["error"])
                    oracle_leaks += sum(
                        field in json.dumps(result, default=str)
                        for field in ("expected_initial", "expected_final", "required_final_evidence")
                    )
                    _record_event(name, arguments, result)
                    outputs.append({
                        "type": "function_call_output",
                        "call_id": call.get("call_id"),
                        "output": json.dumps(result, default=str),
                    })
                request_input = [*request_input, *payload.get("output", []), *outputs]
                if final_submission is not None:
                    break
        return {
            "case_id": case["case_id"],
            "arm": arm,
            "model": self.model,
            "initial_submission": initial_submission,
            "final_submission": final_submission,
            "submissions": submissions,
            "events": events,
            "context_retrieved": context_retrieved,
            "context_fact_ids": context_fact_ids,
            "protocol_errors": protocol_errors,
            "tool_calls": tool_calls,
            "api_requests": api_requests,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "oracle_leaks": oracle_leaks,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "query_calls": executor.calls,
            "shared_input_digest": _digest(case["shared_input"]),
            "prompt_digest": _digest(_agent_prompt(case, False)),
            "tool_schema_digest": _digest(_tool_specs()),
            "preflight": _preflight_summary(retrieval_bundle),
            "jev": (
                {
                    "requests": retriever.requests,
                    "input_tokens": retriever.input_tokens,
                    "output_tokens": retriever.output_tokens,
                }
                if retriever
                else {"requests": 0, "input_tokens": 0, "output_tokens": 0}
            ),
        }


def _refs_from_events(run: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for event in run.get("events", []):
        summary = event.get("result_summary") or {}
        refs.update(str(item) for item in summary.get("evidence_refs", []) or [])
        refs.update(str(item) for item in summary.get("context_fact_ids", []) or [])
    refs.update(str(item) for item in (run.get("preflight") or {}).get("evidence_refs", []) or [])
    return refs


def score_run(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    label = case["label"]
    initial = run.get("initial_submission") or {}
    final = run.get("final_submission") or {}
    evidence = {str(ref) for ref in final.get("evidence_refs", [])}
    required = {str(ref) for ref in label["required_final_evidence"]}
    # A chart-level citation covers its parent source. Agents may cite either
    # the source ref or a concrete chart/observation ref from that source.
    covered = {
        ref
        for ref in required
        if ref in evidence or any(item.startswith(ref + "|") for item in evidence)
    }
    allowed = (
        {str(chart["id"]) for chart in case["shared_input"]["cached_charts"]}
        | {str(source["ref"]) for source in case["sources"]}
        | {str(fact["fact_id"]) for fact in case["diagnostic_facts"]}
    )
    # Source-level citations are already present in the authorized source
    # contract supplied to the agent. They do not need to be repeated by an
    # inspect_source event to be provenance-valid. Chart- and diagnostic-fact
    # citations still need to be present in the public chart catalog or in a
    # retrieved tool result, respectively.
    known = (
        _refs_from_events(run)
        | {str(chart["id"]) for chart in case["shared_input"]["cached_charts"]}
        | {str(source["ref"]) for source in case["sources"]}
    )
    provenance = bool(evidence) and all(ref in allowed and ref in known for ref in evidence)
    expected_initial = label["expected_initial"]
    expected_final = label["expected_final"]
    initial_exact = bool(
        initial
        and initial.get("stage") == "initial"
        and initial.get("outcome") == expected_initial
        and initial.get("delivery") == label["initial_delivery"]
    )
    final_exact = bool(
        final
        and final.get("stage") in {"initial", "final"}
        and final.get("outcome") == expected_final
        and final.get("delivery") == label["final_delivery"]
        and covered == required
        and not evidence - allowed
        and provenance
        and not run.get("protocol_errors")
        and not run.get("oracle_leaks")
    )
    if case["diagnostic_facts"]:
        protocol_ok = bool(run.get("context_retrieved"))
    else:
        protocol_ok = not run.get("context_retrieved")
    # insufficient_data is a terminal, automated abstention. It belongs in
    # the safety denominator: a wrong abstention is still an unsafe automated
    # outcome even though it does not notify a business owner.
    automatic = final.get("outcome") in {"ignore", "notify", "insufficient_data", "escalate"}
    return {
        "case_id": case["case_id"],
        "arm": run["arm"],
        "scenario": case["scenario"],
        "expected_initial": expected_initial,
        "actual_initial": initial.get("outcome"),
        "expected_final": expected_final,
        "actual_final": final.get("outcome"),
        "expected_delivery": label["final_delivery"],
        "actual_delivery": final.get("delivery"),
        "initial_exact": initial_exact,
        "final_exact": final_exact,
        "unsafe_automatic_action": automatic and not final_exact,
        "evidence_recall": round(len(covered) / len(required), 4) if required else 1.0,
        "provenance_complete": provenance,
        "protocol_ok": protocol_ok,
        "context_retrieved": bool(run.get("context_retrieved")),
        "tool_calls": int(run.get("tool_calls", 0)),
        "api_requests": int(run.get("api_requests", 0)),
        "elapsed_ms": float(run.get("end_to_end_elapsed_ms", run.get("elapsed_ms", 0.0))),
        "agent_elapsed_ms": float(run.get("elapsed_ms", 0.0)),
        "preflight_elapsed_ms": float(run.get("preflight_elapsed_ms", 0.0)),
        "query_calls": len(run.get("query_calls", [])),
        "physical_query_executions": sum(not call.get("cache_hit", False) for call in run.get("query_calls", [])),
        "bytes_scanned": sum(int(call.get("bytes_scanned", 0)) for call in run.get("query_calls", [])),
        "cpu_seconds": sum(int(call.get("cpu_seconds", 0)) for call in run.get("query_calls", [])),
        "oracle_leaks": int(run.get("oracle_leaks", 0)),
        "protocol_errors": list(run.get("protocol_errors", [])),
        "jev": run.get("jev", {"requests": 0, "input_tokens": 0, "output_tokens": 0}),
    }


def _summarize(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    selected = [row for row in rows if row["arm"] == arm]
    return {
        "n": len(selected),
        "initial_exact": sum(row["initial_exact"] for row in selected),
        "initial_exact_rate": round(sum(row["initial_exact"] for row in selected) / len(selected), 4) if selected else 0.0,
        "final_exact": sum(row["final_exact"] for row in selected),
        "final_exact_rate": round(sum(row["final_exact"] for row in selected) / len(selected), 4) if selected else 0.0,
        "unsafe_automatic_actions": sum(row["unsafe_automatic_action"] for row in selected),
        "unsafe_automatic_action_rate": round(sum(row["unsafe_automatic_action"] for row in selected) / len(selected), 4) if selected else 0.0,
        "mean_evidence_recall": round(statistics.mean(row["evidence_recall"] for row in selected), 4) if selected else 0.0,
        "protocol_ok": sum(row["protocol_ok"] for row in selected),
        "context_retrieved": sum(row["context_retrieved"] for row in selected),
        "median_elapsed_ms": round(statistics.median(row["elapsed_ms"] for row in selected), 2) if selected else None,
        "median_agent_elapsed_ms": round(statistics.median(row["agent_elapsed_ms"] for row in selected), 2) if selected else None,
        "mean_preflight_elapsed_ms": round(statistics.mean(row["preflight_elapsed_ms"] for row in selected), 2) if selected else 0.0,
        "mean_tool_calls": round(statistics.mean(row["tool_calls"] for row in selected), 2) if selected else 0.0,
        "query_calls": sum(row["query_calls"] for row in selected),
        "physical_query_executions": sum(row["physical_query_executions"] for row in selected),
        "bytes_scanned": sum(row["bytes_scanned"] for row in selected),
        "cpu_seconds": sum(row["cpu_seconds"] for row in selected),
        "oracle_leaks": sum(row["oracle_leaks"] for row in selected),
        "jev_requests": sum(row["jev"]["requests"] for row in selected),
        "jev_input_tokens": sum(row["jev"]["input_tokens"] for row in selected),
        "jev_output_tokens": sum(row["jev"]["output_tokens"] for row in selected),
    }


async def run_trial(args: argparse.Namespace) -> dict[str, Any]:
    cases = build_cases(seed_dir=args.seed_dir, spec_path=args.spec, history_spec_path=args.history_spec)
    openai_key = _load_dotenv_key(args.dotenv, prefer_file=args.prefer_dotenv)
    typesafe_key = load_api_key(args.typesafe_key_file)
    if not typesafe_key:
        raise RuntimeError("paired multi-step trial requires a TypeSafe API key")
    agent = MultiStepAgent(api_key=openai_key, model=args.model)
    order_rng = random.Random(args.seed)
    order_by_case = {
        case["case_id"]: order_rng.choice([("baseline", "treatment"), ("treatment", "baseline")])
        for case in cases
    }
    semaphore = asyncio.Semaphore(args.concurrency)
    raw_runs: list[dict[str, Any]] = []
    ledgers = {"baseline": QueryLedger(), "treatment": QueryLedger()}

    async def one(case: dict[str, Any], arm: str) -> dict[str, Any]:
        async with semaphore:
            treatment = arm == "treatment"
            public_case = _public_case(case)
            retriever = JevRetriever(typesafe_key) if treatment else None
            executor = QueryExecutor(public_case, arm, ledgers[arm])
            preflight_elapsed_ms = 0.0
            try:
                preflight_started = time.perf_counter()
                retrieval_bundle = await retriever.retrieve(public_case, executor) if retriever else None
                preflight_elapsed_ms = round((time.perf_counter() - preflight_started) * 1000, 2)
                result = await agent.run(
                    case,
                    arm=arm,
                    treatment=treatment,
                    retriever=retriever,
                    executor=executor,
                    retrieval_bundle=retrieval_bundle,
                )
                result["preflight_elapsed_ms"] = preflight_elapsed_ms
                result["end_to_end_elapsed_ms"] = round(preflight_elapsed_ms + result["elapsed_ms"], 2)
                return result
            except Exception as error:  # noqa: BLE001 - failures remain in denominator
                return {
                    "case_id": case["case_id"],
                    "arm": arm,
                    "model": args.model,
                    "initial_submission": None,
                    "final_submission": None,
                    "submissions": [],
                    "events": [],
                    "context_retrieved": False,
                    "context_fact_ids": [],
                    "protocol_errors": [f"{type(error).__name__}: {error}"],
                    "tool_calls": 0,
                    "api_requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "oracle_leaks": 0,
                    "elapsed_ms": 0.0,
                    "preflight_elapsed_ms": preflight_elapsed_ms,
                    "end_to_end_elapsed_ms": preflight_elapsed_ms,
                    "query_calls": executor.calls,
                    "shared_input_digest": _digest(case["shared_input"]),
                    # Keep the parity digest stable even when the provider
                    # fails before the agent can return its normal result.
                    "prompt_digest": _digest(_agent_prompt(case, False)),
                    "tool_schema_digest": _digest(_tool_specs()),
                    "preflight": None,
                    "jev": {
                        "requests": retriever.requests if retriever else 0,
                        "input_tokens": retriever.input_tokens if retriever else 0,
                        "output_tokens": retriever.output_tokens if retriever else 0,
                    },
                }

    for case in cases:
        pair = await asyncio.gather(*(one(case, arm) for arm in order_by_case[case["case_id"]]))
        raw_runs.extend(pair)

    case_by_id = {case["case_id"]: case for case in cases}
    scored = [score_run(case_by_id[run["case_id"]], run) for run in raw_runs]
    pairs = []
    for case_id in sorted(case_by_id):
        pair = {row["arm"]: row for row in scored if row["case_id"] == case_id}
        if len(pair) != 2:
            continue
        pairs.append({
            "case_id": case_id,
            "baseline_final_exact": pair["baseline"]["final_exact"],
            "treatment_final_exact": pair["treatment"]["final_exact"],
            "exact_delta": int(pair["treatment"]["final_exact"]) - int(pair["baseline"]["final_exact"]),
            "baseline_elapsed_ms": pair["baseline"]["elapsed_ms"],
            "treatment_elapsed_ms": pair["treatment"]["elapsed_ms"],
            "baseline_query_calls": pair["baseline"]["query_calls"],
            "treatment_query_calls": pair["treatment"]["query_calls"],
        })
    report = {
        "schema_version": 1,
        "trial": "northstar-live-jev-assisted-luna-multistep",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "seed": args.seed,
        "live_jev": True,
        "cases": len(cases),
        "paired_cases_scored": len(pairs),
        "input_parity": {
            "same_shared_input_digest_per_case": all(
                next(run for run in raw_runs if run["case_id"] == case["case_id"] and run["arm"] == "baseline")["shared_input_digest"]
                == next(run for run in raw_runs if run["case_id"] == case["case_id"] and run["arm"] == "treatment")["shared_input_digest"]
                for case in cases
            ),
            "same_base_prompt_digest_per_case": all(
                _digest(_agent_prompt(case, False)) == _digest(_agent_prompt(case, True, None))
                for case in cases
            ),
            "same_model": True,
            "same_connector_snapshots": True,
            "same_diagnostic_context_tool": True,
            "only_treatment_difference": "live Jev preflight bundle before the same Luna agent run",
        },
        "arms": {"baseline": _summarize(scored, "baseline"), "treatment": _summarize(scored, "treatment")},
        "paired_deltas": {
            "mean_final_exact_delta": round(statistics.mean(item["exact_delta"] for item in pairs), 4) if pairs else None,
            "treatment_better": sum(item["exact_delta"] > 0 for item in pairs),
            "same": sum(item["exact_delta"] == 0 for item in pairs),
            "treatment_worse": sum(item["exact_delta"] < 0 for item in pairs),
        },
        "scenario_counts": dict(Counter(case["scenario"] for case in cases)),
        "paired_rows": pairs,
        "raw_runs": raw_runs,
        "scored_rows": scored,
        "limitations": [
            "Northstar data and diagnostic facts are checked-in simulation fixtures, not a customer production log.",
            "The query executor records calibrated work units rather than a live Trino bill.",
            "This trial isolates the Jev-assisted frontier-agent boundary; it does not claim Jev alone performs deep causal analysis.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.output.with_suffix(".md").write_text(render_report(report) + "\n")
    return report


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Northstar paired multi-step Luna trial",
        "",
        f"Model: `{report['model']}`. Cases: **{report['cases']}**; paired runs: **{report['paired_cases_scored']}**.",
        "",
        "| Metric | Luna only | Luna + SignalWeave/Jev |",
        "| --- | ---: | ---: |",
    ]
    for label, key in [
        ("Initial exact rate", "initial_exact_rate"),
        ("Final exact rate", "final_exact_rate"),
        ("Unsafe automatic actions", "unsafe_automatic_actions"),
        ("Mean evidence recall", "mean_evidence_recall"),
        ("Median end-to-end latency (ms)", "median_elapsed_ms"),
        ("Median agent latency (ms)", "median_agent_elapsed_ms"),
        ("Query calls", "query_calls"),
        ("Physical query executions", "physical_query_executions"),
        ("Bytes scanned", "bytes_scanned"),
        ("Jev requests", "jev_requests"),
        ("Jev input tokens", "jev_input_tokens"),
    ]:
        lines.append(
            f"| {label} | {report['arms']['baseline'].get(key)} | {report['arms']['treatment'].get(key)} |"
        )
    lines.extend([
        "",
        f"Paired treatment better / same / worse on final exactness: **{report['paired_deltas']['treatment_better']} / {report['paired_deltas']['same']} / {report['paired_deltas']['treatment_worse']}**.",
        "",
        "This is an internal live-provider comparison. The diagnostic facts remain caller-owned; Jev supplies typed retrieval guidance and Luna performs the analytical interpretation.",
    ])
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--history-spec", type=Path, default=DEFAULT_HISTORY_SPEC)
    parser.add_argument("--dotenv", type=Path)
    parser.add_argument("--prefer-dotenv", action="store_true")
    parser.add_argument("--typesafe-key-file", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--seed", type=int, default=20261004)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    return parser


async def _main(args: argparse.Namespace) -> None:
    report = await run_trial(args)
    print(json.dumps({
        "cases": report["cases"],
        "paired_cases_scored": report["paired_cases_scored"],
        "arms": report["arms"],
        "paired_deltas": report["paired_deltas"],
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))

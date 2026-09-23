"""Run the generated enterprise task matrix through the real MCP registry."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.enterprise_trial import (
    ALLOWED_MCP_TOOLS,
    DEFAULT_CONFIG,
    TraceSink,
    build_experiment_runtime,
    generate_fixture,
    load_fixture,
    render_report,
    score_trace,
)
from signalweave.mcp_server import create_mcp


def _result(structured: Any) -> Any:
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    return structured


async def call_tool(
    server: Any,
    trace: TraceSink,
    *,
    actor: str,
    session_id: str,
    tool: str,
    arguments: dict[str, Any],
) -> Any:
    if tool not in ALLOWED_MCP_TOOLS:
        raise ValueError(f"tool is not allowed: {tool}")
    trace.emit(
        "mcp.call.started",
        actor=actor,
        session_id=session_id,
        payload={"tool": tool, "arguments": arguments},
    )
    started = time.perf_counter()
    try:
        _, structured = await server.call_tool(tool, arguments)
        result = _result(structured)
    except Exception as error:  # noqa: BLE001 - trace and re-raise experiment failures
        trace.emit(
            "mcp.call.failed",
            actor=actor,
            session_id=session_id,
            payload={"tool": tool, "error": f"{type(error).__name__}: {error}"},
        )
        raise
    trace.emit(
        "mcp.call.completed",
        actor=actor,
        session_id=session_id,
        payload={
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return result


async def run_scripted_matrix(
    fixture: dict[str, Any],
    *,
    store_path: str | Path,
    trace_path: str | Path,
    evaluator: str = "research",
    model: str | None = None,
    run_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Exercise every generated task with an MCP-only deterministic operator.

    This is a wiring/load baseline, not a Luna or Jev quality result. It creates
    the same cards a persona is asked to create, but uses hidden task source refs
    so the source/decision contract can be validated over the entire matrix.
    """
    store = Path(store_path)
    trace_path = Path(trace_path)
    if store.exists():
        store.unlink()
    if trace_path.exists():
        trace_path.unlink()
    run_id = run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    tasks = fixture["tasks"][:limit] if limit else fixture["tasks"]
    for task in tasks:
        session_id = f"{run_id}-{task['session_token']}"
        actor = f"persona:{task['persona_id']}"
        trace = TraceSink(
            trace_path,
            experiment_id="signalweave-enterprise-readiness",
            run_id=run_id,
        )
        trace.emit(
            "session.started",
            actor=actor,
            session_id=session_id,
            payload={
                "task_token": task["session_token"],
                "persona_id": task["persona_id"],
                "variant": task["variant"],
                "model": model
                or ("scripted-research-driver" if evaluator == "research" else "jev-latest"),
                "evaluator": evaluator,
                "access": "signal-weave-mcp-only",
            },
        )
        runtime = build_experiment_runtime(
            fixture,
            store_path=store,
            trace=trace,
            actor=actor,
            session_id=session_id,
            evaluator=evaluator,
        )
        server = create_mcp(runtime)
        brief = task["brief"]
        card_id = f"card-{task['session_token']}"
        await call_tool(
            server,
            trace,
            actor=actor,
            session_id=session_id,
            tool="draft_insight_card",
            arguments={
                "card_id": card_id,
                "title": brief["title"],
                "what_to_watch": brief["what_to_watch"],
                "why_watch": brief["why_watch"],
                "watch_for": brief["watch_for"],
                "questions": brief["questions"],
                "decision_guidance": (
                    "Ignore expected or explainable movement. Investigate when the evidence is "
                    "ambiguous or incomplete. Notify or escalate only when fresh evidence and "
                    "the configured delivery policy support it. Treat stale, failed, or missing "
                    "sources as insufficient data rather than as a business signal."
                ),
                "comparison_windows": brief["comparison_windows"],
                "sources": task["source_refs"],
                "delivery_methods": brief["delivery_context"],
                "owner": brief["persona"]["name"],
                "max_source_age_hours": 24.0,
            },
        )
        await call_tool(
            server,
            trace,
            actor=actor,
            session_id=session_id,
            tool="simulate_insight_card",
            arguments={"card_id": card_id},
        )
        await call_tool(
            server,
            trace,
            actor=actor,
            session_id=session_id,
            tool="approve_insight_card",
            arguments={"card_id": card_id},
        )
        await call_tool(
            server,
            trace,
            actor=actor,
            session_id=session_id,
            tool="evaluate_insight_card",
            arguments={"card_id": card_id},
        )
    report = score_trace(fixture, trace_path)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Northstar enterprise MCP matrix")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--fixture", default="artifacts/enterprise/northstar-fixture.json")
    parser.add_argument("--store", default="artifacts/enterprise/matrix-cards.json")
    parser.add_argument("--trace", default="artifacts/enterprise/matrix-trace.jsonl")
    parser.add_argument("--report", default="artifacts/enterprise/matrix-report.json")
    parser.add_argument("--markdown", default="artifacts/enterprise/matrix-report.md")
    parser.add_argument("--evaluator", choices=["research", "jev"], default="research")
    parser.add_argument("--model", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int)
    return parser


async def _main(args: argparse.Namespace) -> None:
    fixture_path = Path(args.fixture)
    if not fixture_path.exists():
        generate_fixture(args.config, fixture_path)
    fixture = load_fixture(fixture_path)
    report = await run_scripted_matrix(
        fixture,
        store_path=args.store,
        trace_path=args.trace,
        evaluator=args.evaluator,
        model=args.model,
        run_id=args.run_id,
        limit=args.limit,
    )
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    Path(args.markdown).write_text(render_report(report))
    print(json.dumps({key: value for key, value in report.items() if key != "sessions"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))

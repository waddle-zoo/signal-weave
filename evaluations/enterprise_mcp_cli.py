"""MCP-only client surface for the enterprise readiness experiment.

Persona agents invoke this command instead of importing SignalWeave or calling
fixture adapters. Each invocation enters the real FastMCP tool registry and
appends a structured trace event before and after the call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from evaluations.enterprise_trial import (
    ALLOWED_MCP_TOOLS,
    DEFAULT_CONFIG,
    TraceSink,
    _stable_hash,
    build_experiment_runtime,
    generate_fixture,
    load_fixture,
    render_report,
    score_trace,
)
from signalweave.mcp_server import create_mcp


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _trace_has_session(path: Path, session_id: str) -> bool:
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        if line.strip() and json.loads(line).get("session_id") == session_id:
            return True
    return False


async def call_mcp(args: argparse.Namespace) -> None:
    fixture = load_fixture(args.fixture)
    trace_path = Path(args.trace)
    run_id = args.run_id or args.session
    trace = TraceSink(trace_path, experiment_id=args.experiment_id, run_id=run_id)
    if args.tool not in ALLOWED_MCP_TOOLS:
        trace.emit(
            "mcp.call.rejected",
            actor=args.actor,
            session_id=args.session,
            payload={"tool": args.tool, "reason": "tool is not allowed in the experiment"},
        )
        raise SystemExit(f"tool is not allowed in the experiment: {args.tool}")
    if not _trace_has_session(trace_path, args.session):
        task_token = args.task_token
        trace.emit(
            "session.started",
            actor=args.actor,
            session_id=args.session,
            payload={
                "task_token": task_token,
                "evaluator": args.evaluator,
                "model": args.model,
                "allowed_tools": list(ALLOWED_MCP_TOOLS),
                "fixture": str(args.fixture),
            },
        )
    try:
        payload = json.loads(args.args_json)
    except json.JSONDecodeError as error:
        raise SystemExit(f"--args-json must be valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise SystemExit("--args-json must contain a JSON object")
    trace.emit(
        "mcp.call.started",
        actor=args.actor,
        session_id=args.session,
        payload={"tool": args.tool, "arguments": payload},
    )
    started = asyncio.get_running_loop().time()
    try:
        runtime = build_experiment_runtime(
            fixture,
            store_path=args.store,
            trace=trace,
            actor=args.actor,
            session_id=args.session,
            evaluator=args.evaluator,
        )
        server = create_mcp(runtime)
        _, structured = await server.call_tool(args.tool, payload)
        result = structured.get("result", structured) if isinstance(structured, dict) else structured
        result = _json_value(result)
    except Exception as error:  # noqa: BLE001 - CLI must trace the failed MCP action
        trace.emit(
            "mcp.call.failed",
            actor=args.actor,
            session_id=args.session,
            payload={
                "tool": args.tool,
                "error": f"{type(error).__name__}: {error}",
                "elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000, 2),
            },
        )
        raise
    trace.emit(
        "mcp.call.completed",
        actor=args.actor,
        session_id=args.session,
        payload={
            "tool": args.tool,
            "arguments": payload,
            "result": result,
            "result_hash": _stable_hash(result),
            "elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000, 2),
        },
    )
    print(json.dumps({"tool": args.tool, "result": result}, indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SignalWeave enterprise MCP experiment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="Generate a synthetic enterprise fixture")
    generate.add_argument("--config", default=str(DEFAULT_CONFIG))
    generate.add_argument("--output", default="artifacts/enterprise/northstar-fixture.json")
    generate.add_argument("--seed", type=int)

    call = subparsers.add_parser("call", help="Call one allowlisted SignalWeave MCP tool")
    call.add_argument("--fixture", required=True)
    call.add_argument("--store", required=True)
    call.add_argument("--trace", required=True)
    call.add_argument("--actor", required=True)
    call.add_argument("--session", required=True)
    call.add_argument("--task-token")
    call.add_argument("--run-id")
    call.add_argument("--experiment-id", default="signalweave-enterprise-readiness")
    call.add_argument("--evaluator", choices=["research", "jev"], default="research")
    call.add_argument("--model", default="gpt-5.6-luna")
    call.add_argument("tool", choices=ALLOWED_MCP_TOOLS)
    call.add_argument("--args-json", default="{}")

    score = subparsers.add_parser("score", help="Score a JSONL trace against hidden task labels")
    score.add_argument("--fixture", required=True)
    score.add_argument("--trace", required=True)
    score.add_argument("--output")

    report = subparsers.add_parser("report", help="Render a scored JSON report as Markdown")
    report.add_argument("--input", required=True)
    report.add_argument("--output", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "generate":
        fixture = generate_fixture(args.config, args.output, seed=args.seed)
        print(json.dumps(fixture["stats"], indent=2, sort_keys=True))
        return
    if args.command == "call":
        asyncio.run(call_mcp(args))
        return
    if args.command == "score":
        report = score_trace(load_fixture(args.fixture), args.trace)
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(payload)
        print(payload, end="")
        return
    if args.command == "report":
        report = json.loads(Path(args.input).read_text())
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(render_report(report))
        print(args.output)
        return
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()

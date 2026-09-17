from __future__ import annotations

import argparse
import asyncio
import json
import os

from .benchmark import (
    render_benchmark_markdown,
    render_benchmark_table,
    run_fixture_benchmark_sync,
    write_benchmark_report,
)
from .proof import render_markdown, render_table, run_fixture_proof_sync, write_report
from .runtime import build_runtime


async def _simulate(scenario: str) -> int:
    runtime = build_runtime(source="fixtures")
    scenarios = sorted(runtime.store.dashboards)
    names = scenarios if scenario == "all" else [scenario]
    for name in names:
        dashboard = runtime.store.get_dashboard_by_scenario(name)
        monitor = next(
            card for card in runtime.store.list_cards() if card.dashboard_id == dashboard.id
        )
        result = await runtime.engine.evaluate(dashboard, monitor)
        print(
            json.dumps(
                {
                    "scenario": name,
                    "decision": result.decision.model_dump(mode="json"),
                    "plan": result.plan.model_dump(mode="json"),
                },
                indent=2,
            )
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulate = subparsers.add_parser("simulate", help="Run local dashboard monitoring scenarios")
    simulate.add_argument("--scenario", default="all")

    serve = subparsers.add_parser("serve", help="Run the MCP server")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))

    prove = subparsers.add_parser(
        "prove", help="Run the representative company scenarios through the engine"
    )
    prove.add_argument("--format", choices=["table", "json", "markdown"], default="table")
    prove.add_argument("--output", help="Write a Markdown proof report to this path")

    benchmark = subparsers.add_parser(
        "benchmark", help="Compare Jev with an optional embedding-plus-reasoning baseline"
    )
    benchmark.add_argument(
        "--systems",
        default="jev",
        help="Comma-separated systems: jev, embedding-reasoning",
    )
    benchmark.add_argument("--repeats", type=int, default=1)
    benchmark.add_argument("--format", choices=["table", "json", "markdown"], default="table")
    benchmark.add_argument("--output", help="Write a Markdown benchmark report to this path")

    args = parser.parse_args()
    if args.command == "simulate":
        raise SystemExit(asyncio.run(_simulate(args.scenario)))
    if args.command == "serve":
        from .mcp_server import create_mcp

        server = create_mcp(build_runtime())
        if args.transport == "stdio":
            server.run(transport="stdio")
        else:
            import uvicorn

            from .auth import BearerTokenMiddleware

            server.settings.host = args.host
            server.settings.port = args.port
            app = server.streamable_http_app()
            api_token = os.getenv("SIGNALWEAVE_API_TOKEN")
            if api_token:
                app.add_middleware(BearerTokenMiddleware, token=api_token)
            uvicorn.run(
                app,
                host=server.settings.host,
                port=server.settings.port,
                log_level=server.settings.log_level.lower(),
            )
    if args.command == "prove":
        mode = "jev"
        results = run_fixture_proof_sync()
        if args.output:
            write_report(results, mode, args.output)
        if args.format == "json":
            print(json.dumps([result.as_json() for result in results], indent=2))
        elif args.format == "markdown":
            print(render_markdown(results, mode))
        else:
            print(render_table(results))
    if args.command == "benchmark":
        systems = [system.strip() for system in args.systems.split(",") if system.strip()]
        results = run_fixture_benchmark_sync(systems, args.repeats)
        if args.output:
            write_benchmark_report(results, args.output)
        if args.format == "json":
            print(json.dumps([result.as_json() for result in results], indent=2))
        elif args.format == "markdown":
            print(render_benchmark_markdown(results))
        else:
            print(render_benchmark_table(results))


if __name__ == "__main__":
    main()

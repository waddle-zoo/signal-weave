from __future__ import annotations

import argparse
import asyncio
import json
import os

from .runtime import build_runtime


async def _simulate(scenario: str, mode: str | None) -> int:
    runtime = build_runtime(mode, source="fixtures")
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
    simulate.add_argument("--mode", choices=["heuristic", "jev"], default=None)

    serve = subparsers.add_parser("serve", help="Run the MCP server")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0"))
    serve.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))

    args = parser.parse_args()
    if args.command == "simulate":
        raise SystemExit(asyncio.run(_simulate(args.scenario, args.mode)))
    if args.command == "serve":
        from .mcp_server import create_mcp

        server = create_mcp(build_runtime())
        if args.transport == "stdio":
            server.run(transport="stdio")
        else:
            server.settings.host = args.host
            server.settings.port = args.port
            server.run(transport="streamable-http")


if __name__ == "__main__":
    main()

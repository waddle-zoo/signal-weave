from __future__ import annotations

import argparse
import os

from .runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SignalWeave MCP server")
    serve = parser.add_subparsers(dest="command", required=True).add_parser(
        "serve", help="Run the MCP server against the configured Superset"
    )
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))

    args = parser.parse_args()
    from .mcp_server import create_mcp

    server = create_mcp(build_runtime())
    if args.transport == "stdio":
        server.run(transport="stdio")
        return

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


if __name__ == "__main__":
    main()

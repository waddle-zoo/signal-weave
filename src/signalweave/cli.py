from __future__ import annotations

import argparse
import os

from .runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SignalWeave MCP server")
    serve = parser.add_subparsers(dest="command", required=True).add_parser(
        "serve", help="Run the MCP server against configured source adapters"
    )
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))

    args = parser.parse_args()
    from .mcp_server import create_mcp
    if args.transport == "stdio":
        server = create_mcp(build_runtime())
        server.run(transport="stdio")
        return

    import uvicorn
    from starlette.responses import JSONResponse

    from .auth import (
        BearerTokenMiddleware,
        OIDCJWTVerifier,
        OIDCSettings,
        principal_from_access_token,
    )

    auth_mode = os.getenv("SIGNALWEAVE_AUTH_MODE", "token").strip().lower()
    if auth_mode not in {"token", "oidc"}:
        raise RuntimeError("SIGNALWEAVE_AUTH_MODE must be token or oidc")
    if auth_mode == "oidc":
        oidc = OIDCSettings.from_env()
        verifier = OIDCJWTVerifier(oidc)
        from mcp.server.auth.middleware.auth_context import get_access_token
        from mcp.server.auth.settings import AuthSettings

        resource_url = os.getenv("SIGNALWEAVE_RESOURCE_SERVER_URL")
        required_scopes = [
            scope.strip()
            for scope in os.getenv("SIGNALWEAVE_OIDC_REQUIRED_SCOPES", "").split(",")
            if scope.strip()
        ]
        auth_settings = AuthSettings(
            issuer_url=oidc.issuer_url,
            resource_server_url=resource_url,
            required_scopes=required_scopes,
            validate_token_resource=False,
        )
        server = create_mcp(
            build_runtime(),
            principal_resolver=lambda _ctx: principal_from_access_token(
                get_access_token(),
                tenant_claim=oidc.tenant_claim,
                authorization_source=f"oidc:{oidc.issuer_url}",
            ),
            auth_settings=auth_settings,
            token_verifier=verifier,
        )
    else:
        server = create_mcp(build_runtime())
    server.settings.host = args.host
    server.settings.port = args.port

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_request):
        return JSONResponse({"status": "ok"})

    app = server.streamable_http_app()
    if auth_mode == "token":
        api_token = os.getenv("SIGNALWEAVE_API_TOKEN")
        if not api_token and os.getenv("SIGNALWEAVE_ALLOW_INSECURE_HTTP") != "1":
            raise RuntimeError(
                "streamable HTTP requires SIGNALWEAVE_API_TOKEN; set "
                "SIGNALWEAVE_ALLOW_INSECURE_HTTP=1 only for an isolated local test"
            )
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

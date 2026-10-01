from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import shlex
import sys
from contextlib import ExitStack, nullcontext
from pathlib import Path

from .local_setup import (
    SetupError,
    agent_config,
    agent_registration,
    doctor,
    initialize,
    local_environment,
    setup_local,
    validate_key_configuration,
)
from .runtime import build_runtime, load_deployment_secret


def _is_loopback_host(host: str) -> bool:
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _http_api_token() -> str | None:
    """Load the streamable-HTTP bearer token from a value or mounted file."""

    return load_deployment_secret("SIGNALWEAVE_API_TOKEN")


def main() -> None:
    distribution = "standalone executable" if getattr(sys, "frozen", False) else "Python CLI"
    parser = argparse.ArgumentParser(description=f"SignalWeave local setup and MCP server ({distribution})")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create private local configuration and state")
    init.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    init.add_argument("--key-file", help="Copy a private TypeSafe key file instead of prompting")
    setup = commands.add_parser("setup", help="Offline wizard: Jev key, source, local identity, and agent config")
    setup.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    setup.add_argument("--non-interactive", action="store_true", help="Never prompt; credentials must exist or use private files")
    setup.add_argument("--key-file", help="Private file containing the TypeSafe key")
    setup.add_argument("--source", choices=["superset", "preset", "mcp", "skip"])
    setup.add_argument("--url", help="Superset or Preset workspace URL")
    setup.add_argument("--username", help="Superset username")
    setup.add_argument("--secret-file", help="Private Superset password or Preset API-token-secret file")
    setup.add_argument("--token-name-file", help="Private Preset API-token-name file")
    setup.add_argument("--manifest", help="Reviewed read-only MCP source manifest (no server is launched)")
    setup.add_argument("--tenant", help="Local tenant identifier (default: existing setting or local)")
    setup.add_argument("--principal", help="Local principal identifier (default: existing setting or local)")
    setup.add_argument("--agent", choices=["codex", "claude"])
    check = commands.add_parser("doctor", help="Check configuration offline; makes no live requests")
    check.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    snippet = commands.add_parser("agent-config", help="Print configuration; never edits agent files")
    snippet.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    snippet.add_argument("--agent", choices=["codex", "claude"], required=True)
    run = commands.add_parser("run", help="Evaluate an approved card once and print its JSON result")
    run.add_argument("card", metavar="CARD")
    run.add_argument("--run-key", required=True, help="Stable idempotency key for this evaluation")
    run.add_argument("--output", type=Path, help="Directory for rendered output")
    run.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    serve = commands.add_parser(
        "serve", help="Run the MCP server against configured source adapters"
    )
    serve.add_argument("--home", help="Load a local home; otherwise use SIGNALWEAVE_HOME or deployment environment")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    args = parser.parse_args()
    try:
        if args.command == "setup":
            options = vars(args).copy()
            options.pop("command")
            home, agent = setup_local(**options)
            print("Local configuration saved. No network requests or source processes were started.")
            print("Local identity scopes this single-user process; it is not provider authentication.")
            print("Credentials and live source access remain unverified. Review and simulate cards before approval.")
            print("To register with your agent, review and run this command:")
            print(agent_registration(home, agent))
            print("Offline check: " + shlex.join(["signalweave", "doctor", "--home", str(home)]))
            return
        if args.command == "init":
            home = initialize(args.home, key_file=args.key_file)
            print(f"Local configuration: {home / 'config.toml'}")
            print(f"Local state directory: {home / 'state'}")
            print("Next: " + shlex.join(["signalweave", "doctor", "--home", str(home)]))
            for agent in ("codex", "claude"):
                print("Agent snippet: " + shlex.join([
                    "signalweave", "agent-config", "--agent", agent, "--home", str(home),
                ]))
            return
        if args.command == "agent-config":
            print(agent_config(args.home, args.agent), end="")
            return
        # Legacy serve remains environment-only unless the caller selects a home.
        context = (
            local_environment(args.home)
            if args.command != "serve" or args.home is not None or "SIGNALWEAVE_HOME" in os.environ
            else nullcontext()
        )
        with context as local_home:
            if args.command == "doctor":
                healthy, messages = doctor()
                print("\n".join(messages))
                if not healthy:
                    raise SystemExit(1)
                return
            if local_home is not None:
                validate_key_configuration()
            if args.command == "run":
                from .local_run import run_card

                if not args.card.strip() or not args.run_key.strip():
                    raise SetupError("CARD and --run-key must not be empty")
                output = args.output.expanduser().absolute() if args.output is not None else None
                result = asyncio.run(run_card(args.card, args.run_key, output_dir=output))
                print(json.dumps(result, ensure_ascii=False))
                return
            args.host = args.host if args.host is not None else os.getenv("MCP_HOST", "127.0.0.1")
            try:
                args.port = args.port if args.port is not None else int(os.getenv("MCP_PORT", "8000"))
            except ValueError:
                raise SetupError("MCP_PORT must be an integer") from None
            if not 1 <= args.port <= 65535:
                raise SetupError("MCP port must be between 1 and 65535")
            _serve(args)
    except SetupError as error:
        print(f"SignalWeave setup error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError:
        # OS errors can expose filenames containing secrets; keep CLI failures bounded.
        print("SignalWeave could not access a required file; check paths and permissions.", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None


def _run_stdio(server) -> None:
    """Let the transport own duplicated handles, never the process standard streams."""
    original_stdin, original_stdout = sys.stdin, sys.stdout
    with ExitStack() as streams:
        stdin = streams.enter_context(os.fdopen(
            os.dup(original_stdin.fileno()), "r", encoding="utf-8", errors="replace",
        ))
        stdout = streams.enter_context(os.fdopen(
            os.dup(original_stdout.fileno()), "w", encoding="utf-8",
        ))
        # MCP re-wraps these buffers and may close them during teardown. Duplicates
        # keep the originals usable for interpreter/PyInstaller shutdown flushing.
        sys.stdin, sys.stdout = stdin, stdout
        try:
            server.run(transport="stdio")
        finally:
            sys.stdin, sys.stdout = original_stdin, original_stdout


def _serve(args: argparse.Namespace) -> None:
    from .mcp_server import create_mcp
    if args.transport == "stdio":
        server = create_mcp(build_runtime())
        _run_stdio(server)
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
            http_principal_resolver=lambda: principal_from_access_token(
                get_access_token(),
                tenant_claim=oidc.tenant_claim,
                authorization_source=f"oidc:{oidc.issuer_url}",
                required_scopes=required_scopes,
            ),
            auth_settings=auth_settings,
            token_verifier=verifier,
            require_principal=True,
        )
    else:
        runtime = build_runtime()
        if runtime.principal is None:
            raise RuntimeError(
                "token-authenticated streamable HTTP requires "
                "SIGNALWEAVE_TENANT_ID and SIGNALWEAVE_PRINCIPAL_ID; use stdio for "
                "an intentionally unscoped local process"
            )
        server = create_mcp(runtime, require_principal=True)
    server.settings.host = args.host
    server.settings.port = args.port

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_request):
        return JSONResponse({"status": "ok"})

    app = server.streamable_http_app()
    if auth_mode == "token":
        api_token = _http_api_token()
        if not api_token and os.getenv("SIGNALWEAVE_ALLOW_INSECURE_HTTP") != "1":
            raise RuntimeError(
                "streamable HTTP requires SIGNALWEAVE_API_TOKEN; set "
                "SIGNALWEAVE_ALLOW_INSECURE_HTTP=1 only for an isolated local test"
            )
        if not api_token and not _is_loopback_host(args.host):
            raise RuntimeError(
                "SIGNALWEAVE_ALLOW_INSECURE_HTTP=1 is only permitted on a loopback host"
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

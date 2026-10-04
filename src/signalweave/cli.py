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

from . import __version__
from .local_setup import (
    SetupError,
    agent_config,
    agent_registration,
    credential_status,
    doctor,
    initialize,
    local_environment,
    set_credential,
    setup_local,
    validate_key_configuration,
)
from .local_status import local_status
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
    parser.add_argument("--version", action="version", version=f"SignalWeave {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create private local configuration and state")
    init.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    init.add_argument("--key-file", help="Copy a private TypeSafe key file instead of prompting")
    setup = commands.add_parser("setup", help="Offline wizard: Jev key, source, local identity, and agent config")
    setup.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    setup.add_argument("--non-interactive", action="store_true", help="Never prompt; credentials must exist or use private files")
    setup.add_argument("--key-file", help="Private file containing the TypeSafe key")
    setup.add_argument("--source", choices=["superset", "preset", "trino", "mcp", "skip"])
    setup.add_argument("--url", help="Superset or Preset workspace URL")
    setup.add_argument("--username", help="Superset username")
    setup.add_argument("--secret-file", help="Private Superset password or Preset API-token-secret file")
    setup.add_argument("--token-name-file", help="Private Preset API-token-name file")
    setup.add_argument("--manifest", help="Reviewed read-only MCP source manifest (no server is launched)")
    setup.add_argument("--catalog-file", help="Private normalized Trino catalog JSON file")
    setup.add_argument("--user", dest="trino_user", help="Trino user")
    setup.add_argument("--catalog", dest="trino_catalog", help="Trino catalog name")
    setup.add_argument("--schema", dest="trino_schema", help="Trino schema name")
    setup.add_argument("--max-rows", dest="trino_max_rows", help="Trino result row limit")
    setup.add_argument("--tenant", help="Local tenant identifier (default: existing setting or local)")
    setup.add_argument("--principal", help="Local principal identifier (default: existing setting or local)")
    setup.add_argument("--agent", choices=["codex", "claude"])
    setup.add_argument("--register-agent", action="store_true", help="Opt in to agent CLI registration; existing entries are not replaced")
    setup.add_argument("--update", action="store_true", help="Allow replacing existing settings or credentials")
    connect = commands.add_parser("connect", help="Register an existing local setup with your agent")
    connect.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    connect.add_argument("agent_name", nargs="?", choices=["codex", "claude"])
    connect.add_argument("--agent", dest="agent_flag", choices=["codex", "claude"])
    check = commands.add_parser("doctor", help="Check configuration offline; optionally probe source access")
    check.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    check.add_argument("--live", action="store_true", help="Run bounded catalog probes; never sends a Jev judgment")
    check.add_argument("--json", action="store_true", help="Print a machine-readable report")
    health = commands.add_parser("health", help="Alias for doctor; check local and optional live source health")
    health.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    health.add_argument("--live", action="store_true", help="Run bounded catalog probes; never sends a Jev judgment")
    health.add_argument("--json", action="store_true", help="Print a machine-readable report")
    status = commands.add_parser("status", help="Show secret-free local setup status")
    status.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    status.add_argument("--json", action="store_true", help="Print a machine-readable report")
    credentials = commands.add_parser("credentials", help="List or rotate private local credentials")
    credentials_sub = credentials.add_subparsers(dest="credentials_command", required=True)
    credentials_list = credentials_sub.add_parser("list", help="Show credential status without secret values")
    credentials_list.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    credentials_list.add_argument("--json", action="store_true", help="Print a machine-readable report")
    credentials_set = credentials_sub.add_parser("set", help="Set or rotate one credential; prompts without echo")
    credentials_set.add_argument("name", help="typesafe, superset-password, preset-token-name, or another supported credential")
    credentials_set.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    credentials_set.add_argument("--file", dest="secret_file", help="Read the secret from a private file")
    connections = commands.add_parser("connections", help="Add, update, or list source connections")
    connections_sub = connections.add_subparsers(dest="connections_command", required=True)
    connections_list = connections_sub.add_parser("list", help="Show configured source endpoints without secrets")
    connections_list.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    connections_list.add_argument("--json", action="store_true", help="Print a machine-readable report")
    for action, update in (("add", False), ("update", True)):
        connection = connections_sub.add_parser(action, help=(
            "Add a source connection" if not update else "Update an existing source connection"
        ))
        connection.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
        connection.add_argument("--source", choices=["superset", "preset", "trino", "mcp", "skip"])
        connection.add_argument("--url", help="Superset or Preset workspace URL")
        connection.add_argument("--username", help="Superset username")
        connection.add_argument("--secret-file", help="Private password or Preset API-token-secret file")
        connection.add_argument("--token-name-file", help="Private Preset API-token-name file")
        connection.add_argument("--manifest", help="Reviewed read-only MCP source manifest")
        connection.add_argument("--catalog-file", help="Private normalized Trino catalog JSON file")
        connection.add_argument("--user", dest="trino_user", help="Trino user")
        connection.add_argument("--catalog", dest="trino_catalog", help="Trino catalog name")
        connection.add_argument("--schema", dest="trino_schema", help="Trino schema name")
        connection.add_argument("--max-rows", dest="trino_max_rows", help="Trino result row limit")
        connection.add_argument("--tenant", help="Local tenant identifier")
        connection.add_argument("--principal", help="Local principal identifier")
        connection.add_argument("--agent", choices=["codex", "claude"])
        connection.add_argument("--non-interactive", action="store_true", help="Never prompt")
        connection.set_defaults(connection_update=update)
    ui = commands.add_parser("ui", help="Open the optional loopback-only local health UI")
    ui.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    ui.add_argument("--host", default="127.0.0.1", help="Loopback host only")
    ui.add_argument("--port", type=int, default=8765)
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
            register = options.pop("register_agent")
            guided_sources = not options.get("non_interactive") and options.get("source") is None
            home, agent = setup_local(**options)
            if guided_sources:
                # A first-time human often has more than one useful system. Keep
                # the wizard in one flow, but reuse the identity and key without
                # asking the same questions again. Each connector still has its
                # own explicit validation and secret boundary.
                from .local_setup import read_config

                while True:
                    if not _ask_yes_no("\nAdd another source? [y/N]: "):
                        break
                    _, configured = read_config(home)
                    home, agent = setup_local(
                        home=home,
                        tenant=configured.get("SIGNALWEAVE_TENANT_ID", "local"),
                        principal=configured.get("SIGNALWEAVE_PRINCIPAL_ID", "local"),
                        agent=agent,
                    )
            print("Local configuration saved. No network requests or source processes were started.")
            print("Local identity scopes this single-user process; it is not provider authentication.")
            print("Credentials and live source access remain unverified. Review and simulate cards before approval.")
            if register:
                _connect_agent(home, agent)
            else:
                print("To register with your agent, review and run this command:")
                print(agent_registration(home, agent))
            print("Status: " + shlex.join(["signalweave", "status", "--home", str(home)]))
            print("Offline check: " + shlex.join(["signalweave", "doctor", "--home", str(home)]))
            print("After adding a source: " + shlex.join(["signalweave", "doctor", "--live", "--home", str(home)]))
            print("Then ask your agent: Use SignalWeave's get_signalweave_guide to help me get my first useful report from my BI sources.")
            return
        if args.command == "connect":
            from .local_setup import read_config

            home, _ = read_config(args.home)
            agent = args.agent_name or args.agent_flag
            if agent is None:
                raise SetupError("Choose an agent: signalweave connect codex or signalweave connect claude")
            _connect_agent(home, agent)
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
        if args.command == "status":
            report = local_status(args.home)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                _print_status(report)
            return
        if args.command == "credentials":
            if args.credentials_command == "list":
                try:
                    values = credential_status(args.home)
                except SetupError as error:
                    raise SetupError(str(error)) from None
                if args.json:
                    print(json.dumps(values, ensure_ascii=False, indent=2))
                else:
                    print("Credentials (values hidden):")
                    for name, value in values.items():
                        print(f"  {name}: {value}")
                return
            destination = set_credential(args.home, args.name, secret_file=args.secret_file)
            print(f"Credential saved privately: {destination}")
            print("Run `signalweave status` to review setup, then `signalweave doctor --live` to test source access.")
            return
        if args.command == "connections":
            if args.connections_command == "list":
                report = local_status(args.home)
                if args.json:
                    print(json.dumps(report.get("connections", []), ensure_ascii=False, indent=2))
                else:
                    _print_connections(report)
                return
            from .local_setup import read_config

            try:
                _, existing = read_config(args.home)
            except SetupError:
                existing = {}
            options = {
                "home": args.home,
                "source": args.source,
                "url": args.url,
                "username": args.username,
                "secret_file": args.secret_file,
                "token_name_file": args.token_name_file,
                "manifest": args.manifest,
                "catalog_file": getattr(args, "catalog_file", None),
                "trino_user": getattr(args, "trino_user", None),
                "trino_catalog": getattr(args, "trino_catalog", None),
                "trino_schema": getattr(args, "trino_schema", None),
                "trino_max_rows": getattr(args, "trino_max_rows", None),
                "tenant": args.tenant or existing.get("SIGNALWEAVE_TENANT_ID", "local"),
                "principal": args.principal or existing.get("SIGNALWEAVE_PRINCIPAL_ID", "local"),
                # Agent registration is a separate explicit command. The
                # connection editor must not ask a human for an unrelated
                # agent choice just to save a source.
                "agent": args.agent or "codex",
                "non_interactive": args.non_interactive,
                "update": args.connection_update,
            }
            home, _ = setup_local(**options)
            print(f"Connection saved in {home / 'config.toml'}")
            print("Run `signalweave status` to review it, then `signalweave doctor --live` to test access.")
            return
        if args.command == "ui":
            if not _is_loopback_host(args.host):
                raise SetupError("The local UI only binds to loopback; use 127.0.0.1 or localhost")
            if not 1 <= args.port <= 65535:
                raise SetupError("UI port must be between 1 and 65535")
            import uvicorn

            from .local_ui import create_local_ui

            print(f"SignalWeave local UI: http://{args.host}:{args.port}/")
            uvicorn.run(
                create_local_ui(args.home),
                host=args.host,
                port=args.port,
                log_level="warning",
            )
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
            if args.command in {"doctor", "health"}:
                healthy, messages = doctor()
                report = {"healthy": healthy, "mode": "offline", "messages": messages}
                if args.live:
                    if healthy:
                        from .local_health import live_health_report

                        live = asyncio.run(live_health_report())
                        report["mode"] = "offline_and_live_source"
                        report["healthy"] = bool(live["healthy"])
                        report["messages"].extend(live["messages"])
                    else:
                        report["messages"].append("Live source checks skipped until offline configuration is healthy.")
                if args.json:
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    print("\n".join(report["messages"]))
                if not healthy:
                    raise SystemExit(1)
                if not report["healthy"]:
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


def _print_status(report: dict[str, object]) -> None:
    print(f"SignalWeave: {str(report.get('status', 'unknown')).replace('_', ' ')}")
    if report.get("home"):
        print(f"Home: {report['home']}")
    if report.get("error"):
        print(f"Setup: {report['error']}")
    jev = report.get("jev")
    if isinstance(jev, dict):
        print(f"Jev: {jev.get('status', 'unknown')} (live judgment check: {jev.get('live_check', 'not run')})")
    agents = report.get("agents")
    if isinstance(agents, dict):
        print(f"Agent: {agents.get('selected', 'not selected')}")
    _print_connections(report)
    credentials = report.get("credentials")
    if isinstance(credentials, dict):
        print("Credentials (values hidden):")
        for name, status in credentials.items():
            print(f"  {name}: {status}")
    next_steps = report.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        print("Next:")
        for step in next_steps:
            print(f"  {step}")


def _ask_yes_no(prompt: str) -> bool:
    """Treat a closed input stream as the safe, non-mutating answer."""
    try:
        return input(prompt).strip().lower() in {"y", "yes"}
    except (EOFError, StopIteration):
        return False


def _print_connections(report: dict[str, object]) -> None:
    connections = report.get("connections", [])
    if not isinstance(connections, list):
        return
    print("Connections:")
    if not connections:
        print("  none")
        return
    for item in connections:
        if not isinstance(item, dict):
            continue
        detail = item.get("endpoint") or item.get("detail") or "not configured"
        print(f"  {item.get('label', item.get('type', 'source'))}: {item.get('status', 'unknown')} ({detail})")


def _connect_agent(home: Path, agent: str) -> None:
    from .client_setup import register_agent

    status = register_agent(home, agent)
    print(status.message)
    if status.outcome in {"registered", "already_configured"}:
        print("Restart or reconnect the agent, then call get_signalweave_guide.")
        return
    if status.command:
        print("Registration was not verified. Review existing entries before running this manual command:")
        print(status.command)
    if status.outcome == "manual_required":
        print("The local setup is unchanged; run the command above, then reconnect the agent.")
        return
    raise SystemExit(1)


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

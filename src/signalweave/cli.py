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
from .cli_output import emphasis, progress
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
    validate_decision_configuration,
)
from .local_status import local_status


def build_runtime(*args, **kwargs):
    """Load decision/source dependencies only when a runtime is requested."""
    from .runtime import build_runtime as create_runtime

    return create_runtime(*args, **kwargs)


def load_deployment_secret(name: str) -> str | None:
    from .runtime import load_deployment_secret as load_secret

    return load_secret(name)


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


class _BuildInfoAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        from .build_info import build_info

        print(json.dumps(build_info(), sort_keys=True))
        parser.exit()


def main() -> None:
    distribution = "standalone executable" if getattr(sys, "frozen", False) else "Python CLI"
    parser = argparse.ArgumentParser(
        description=f"SignalWeave human-first setup, health, and MCP server ({distribution})",
        epilog=(
            "First run: signalweave setup  ->  signalweave health --live  ->  "
            "signalweave ui --open\n"
            "Connect an agent later with: signalweave connect codex | signalweave connect claude"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"SignalWeave {__version__}")
    parser.add_argument("--build-info", action=_BuildInfoAction, nargs=0, default=argparse.SUPPRESS,
                        help="Show the native build's version and source fingerprint")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="Create private local configuration and state (advanced; setup is the normal path)"
    )
    init.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    init.add_argument("--key-file", help="Copy a private TypeSafe key file instead of prompting")
    setup = commands.add_parser(
        "setup",
        help="Guided human setup: connectors, credentials, and agent handoff",
        description=(
            "Walk through a private local setup. Secrets are hidden and stored under "
            "~/.signalweave; no TOML editing is required. Choose Jev, OpenAI Decisions, or ChatGPT-plan Responses."
        ),
    )
    setup.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    setup.add_argument(
        "--profile", choices=["agent", "full"], default=None,
        help="agent is the normal card workflow; full adds advanced tools",
    )
    setup.add_argument("--non-interactive", action="store_true", help="Never prompt; credentials must exist or use private files")
    setup.add_argument("--key-file", help="Private file containing the TypeSafe key")
    setup.add_argument(
        "--decision-provider",
        choices=["jev", "openai-decisions", "chatgpt-plan"],
        help="Card decision backend (interactive setup explains the tradeoffs)",
    )
    setup.add_argument("--openai-key-file", help="Private file containing the OpenAI API key")
    setup.add_argument("--source", choices=["superset", "preset", "trino", "mcp", "skip"])
    setup.add_argument("--url", help="Superset or Preset workspace URL")
    setup.add_argument("--username", help="Superset username")
    setup.add_argument("--secret-file", help="Private Superset password or Preset API-token-secret file")
    setup.add_argument("--token-name-file", help="Private Preset API-token-name file")
    setup.add_argument("--access-token-file", help="Private Preset bearer/access-token file")
    setup.add_argument(
        "--preset-auth", choices=["api-token", "bearer"],
        help="Preset credential mode (defaults to API-token pair; bearer accepts --access-token-file)",
    )
    setup.add_argument("--manifest", help="Reviewed read-only MCP source manifest (no server is launched)")
    setup.add_argument("--catalog-file", help="Private normalized Trino catalog JSON file")
    setup.add_argument("--user", dest="trino_user", help="Trino user")
    setup.add_argument("--catalog", dest="trino_catalog", help="Trino catalog name")
    setup.add_argument("--schema", dest="trino_schema", help="Trino schema name")
    setup.add_argument("--max-rows", dest="trino_max_rows", help="Trino result row limit")
    setup.add_argument("--tenant", help="Local tenant identifier (default: existing setting or local)")
    setup.add_argument("--principal", help="Local principal identifier (default: existing setting or local)")
    setup.add_argument("--agent", choices=["codex", "claude"])
    setup.add_argument(
        "--register-agent", dest="register_agent", action="store_true", default=None,
        help="Register the selected agent in this setup flow when its CLI is available",
    )
    setup.add_argument(
        "--no-register-agent", dest="register_agent", action="store_false",
        help="Save setup without changing agent configuration",
    )
    setup.add_argument("--update", action="store_true", help="Allow replacing existing settings or credentials")
    connect = commands.add_parser(
        "connect", help="Connect an existing local setup to Codex or Claude Code"
    )
    connect.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    connect.add_argument("agent_name", nargs="?", choices=["codex", "claude"])
    connect.add_argument("--agent", dest="agent_flag", choices=["codex", "claude"])
    check = commands.add_parser(
        "doctor", help="Check local configuration; --live probes configured source access"
    )
    check.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    check.add_argument("--live", action="store_true", help="Run bounded catalog probes; never sends a Jev judgment")
    check.add_argument("--json", action="store_true", help="Print a machine-readable report")
    health = commands.add_parser(
        "health", help="Human-readable setup and source health check (doctor alias)"
    )
    health.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    health.add_argument("--live", action="store_true", help="Run bounded catalog probes; never sends a Jev judgment")
    health.add_argument("--json", action="store_true", help="Print a machine-readable report")
    status = commands.add_parser("status", help="Show secret-free local setup status")
    status.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    status.add_argument("--json", action="store_true", help="Print a machine-readable report")
    context = commands.add_parser(
        "context",
        help="Enable, disable, or inspect optional domain-context configuration",
        description=(
            "Manage the optional domain-context feature flag in a configured local home. "
            "This reports configuration only; it does not check live service health."
        ),
    )
    context_sub = context.add_subparsers(dest="context_command", required=True)
    for action, help_text in (
        ("enable", "Enable optional domain context"),
        ("disable", "Disable optional domain context"),
        ("status", "Show domain-context configuration status"),
    ):
        context_action = context_sub.add_parser(action, help=help_text)
        context_action.add_argument(
            "--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)"
        )
        if action == "status":
            context_action.add_argument(
                "--json", action="store_true", help="Print a machine-readable report"
            )
    credentials = commands.add_parser(
        "credentials", help="List or rotate private credentials without editing config"
    )
    credentials_sub = credentials.add_subparsers(dest="credentials_command", required=True)
    credentials_list = credentials_sub.add_parser("list", help="Show credential status without secret values")
    credentials_list.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    credentials_list.add_argument("--json", action="store_true", help="Print a machine-readable report")
    credentials_set = credentials_sub.add_parser("set", help="Set or rotate one credential; prompts without echo")
    credentials_set.add_argument(
        "name",
        help=(
            "typesafe, openai, superset-password, preset-api-token-name, "
            "preset-api-token-secret, preset-access-token, or jev"
        ),
    )
    credentials_set.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    credentials_set.add_argument("--file", dest="secret_file", help="Read the secret from a private file")
    auth = commands.add_parser("auth", help="Manage local ChatGPT-plan sign-in")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    for command, help_text in (
        ("login", "Connect or reconnect ChatGPT-plan access in your browser"),
        ("status", "Show secret-free ChatGPT-plan connection status"),
        ("logout", "Remove local ChatGPT tokens"),
    ):
        auth_command = auth_sub.add_parser(command, help=help_text)
        auth_command.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    connections = commands.add_parser(
        "connections", help="Add, update, or list Superset, Preset, Trino, or MCP sources"
    )
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
        connection.add_argument("--access-token-file", help="Private Preset bearer/access-token file")
        connection.add_argument("--preset-auth", choices=["api-token", "bearer"])
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
    ui.add_argument("--open", action="store_true", help="Open the UI in the default browser")
    snippet = commands.add_parser("agent-config", help="Print configuration; never edits agent files")
    snippet.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    snippet.add_argument("--agent", choices=["codex", "claude"], required=True)
    skills = commands.add_parser("skills", help="Show or explicitly install the bundled agent skill")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_sub.add_parser("show", help="Print the bundled SignalWeave skill instructions")
    skills_install = skills_sub.add_parser("install", help="Install the skill in an explicit agent scope")
    skills_install.add_argument("--agent", choices=["codex", "claude"], required=True)
    skills_install.add_argument("--scope", choices=["project", "user"], default="project")
    remove = commands.add_parser("uninstall", help="Remove the native executable; keep local data unless --purge")
    remove.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    remove.add_argument("--purge", action="store_true", help="Permanently remove this private home's configuration, credentials, cards, and receipts")
    remove.add_argument("--yes", action="store_true", help="Confirm the displayed uninstall plan without prompting")
    run = commands.add_parser(
        "run",
        help="Run an approved insight card once through the configured decision provider",
    )
    run.add_argument("card", metavar="CARD")
    run.add_argument("--run-key", required=True, help="Stable idempotency key for this evaluation")
    run.add_argument("--output", type=Path, help="Directory for rendered output")
    run.add_argument("--home", help="Local home (default: SIGNALWEAVE_HOME or ~/.signalweave)")
    serve = commands.add_parser(
        "serve", help="Run the MCP server against configured source adapters"
    )
    serve.add_argument(
        "--home",
        help="Local home (default: configured ~/.signalweave; otherwise deployment environment)",
    )
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument(
        "--profile",
        choices=["agent", "full"],
        default=None,
        help="MCP tools to expose (default: agent; full adds advanced legacy tools)",
    )
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    if len(sys.argv) == 1:
        selected_home = Path(os.environ.get("SIGNALWEAVE_HOME") or Path.home() / ".signalweave").expanduser()
        existing_home = selected_home / "config.toml"
        sys.argv.append("status" if existing_home.is_file() else "setup")
    queries = commands.add_parser("queries", help="Reuse reviewed SQL through an existing BI connection")
    queries_sub = queries.add_subparsers(dest="queries_command", required=True)
    queries_sub.add_parser("schema", help="Print the reviewed query artifact JSON schema")
    query_import = queries_sub.add_parser("import", help="Review and import fixed query sources; never executes SQL")
    query_import.add_argument("--source", choices=["superset", "preset"], required=True)
    query_import.add_argument("--file", required=True, help="Agent-authored reviewed query catalog JSON")
    query_import.add_argument("--home")
    query_import.add_argument("--yes", action="store_true", help="Confirm this exact reviewed source artifact non-interactively")
    query_import.add_argument("--allow-live-queries", action="store_true", help="Explicitly enable live queries/refresh on the configured Preset connection")
    query_list = queries_sub.add_parser("list", help="List imported queries without executing them")
    query_list.add_argument("--home")
    args = parser.parse_args()
    try:
        if args.command == "queries":
            from .local_queries import import_queries, list_queries
            from .query_source import QueryCatalog

            if args.queries_command == "schema":
                print(json.dumps(QueryCatalog.model_json_schema(), indent=2))
            elif args.queries_command == "list":
                print(json.dumps(list_queries(args.home), indent=2))
            else:
                catalog = import_queries(args.home, args.source, args.file, yes=args.yes,
                                         allow_live_queries=args.allow_live_queries)
                print(f"{len(catalog.queries)} reviewed queries active. Reconnect your agent to load them.")
                print("Ask your agent to inspect the new query sources, review a card, and show a delivery-disabled report.")
            return
        if args.command == "uninstall":
            from .uninstall import uninstall

            uninstall(args.home, purge=args.purge, yes=args.yes)
            return
        if args.command == "skills":
            from .skill_install import SkillInstallError, install_skill, skill_text

            if args.skills_command == "show":
                try:
                    print(skill_text(), end="")
                except SkillInstallError as error:
                    raise SetupError(str(error)) from None
                return
            try:
                status, target = install_skill(args.agent, args.scope)
            except SkillInstallError as error:
                raise SetupError(str(error)) from None
            print(f"SignalWeave skill {status.replace('_', ' ')}: {target}")
            return
        if args.command == "setup":
            options = vars(args).copy()
            options.pop("command")
            register = options.pop("register_agent")
            options["profile"] = (
                options.get("profile") or os.getenv("SIGNALWEAVE_MCP_PROFILE", "agent").strip().lower()
            )
            guided_sources = not options.get("non_interactive") and options.get("source") is None
            if guided_sources:
                print(emphasis("SignalWeave setup"))
                print("Private home: " + str(options.get("home") or Path.home() / ".signalweave"))
                print("Choose a decision provider, then connect the BI sources your agent may read.")
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
            print("\nLocal configuration saved. No source process was started during setup.")
            print(f"Private home: {home}")
            setup_status = local_status(home)
            has_sources = any(item.get("status") == "configured"
                              for item in setup_status.get("connections", []))
            if has_sources:
                print("Next: `signalweave health --live` checks source access, not analytical readiness.")
            else:
                print("No BI source is connected yet. Next: `signalweave connections add`.")
            from .local_setup import read_config

            _, setup_values = read_config(home)
            decision_provider = setup_values.get("SIGNALWEAVE_DECISION_PROVIDER", "jev")
            if decision_provider == "chatgpt-plan" and not options.get("non_interactive"):
                from .chatgpt_auth import auth_status, login

                if auth_status(home)["status"] != "connected":
                    try:
                        login(home)
                        print("ChatGPT plan connected for SignalWeave.")
                    except SetupError as error:
                        print(f"ChatGPT sign-in is still needed: {error}")
                        print("Run `signalweave auth login` when ready; local setup is saved.")
            elif decision_provider == "chatgpt-plan":
                print("Next: run `signalweave auth login` to authorize ChatGPT-plan usage in your browser.")
            if register is True or (register is None and guided_sources and _ask_yes_no(
                f"\nConnect SignalWeave to {agent.title()} now? [Y/n]: ", default=True,
            )):
                # A missing agent CLI or a conflicting existing entry must not
                # discard a successful local setup. The command remains in the
                # output so the user can finish the handoff explicitly.
                connected = _connect_agent(home, agent, required=False)
                if connected:
                    _offer_user_skill(
                        agent,
                        interactive=not options.get("non_interactive") and sys.stdin.isatty(),
                    )
            else:
                print("To register with your agent, review and run this command:")
                print(agent_registration(home, agent))
            print("Status: " + shlex.join(["signalweave", "status", "--home", str(home)]))
            print("Local UI: " + shlex.join(["signalweave", "ui", "--open", "--home", str(home)]))
            print("Then ask your agent: Use SignalWeave's getting-started guide to help me get my first useful report.")
            print("Start with a report. Review its evidence and resolve missing business context before approving a daily card.")
            return
        if args.command == "auth":
            from .chatgpt_auth import auth_status, login, logout

            if args.auth_command == "login":
                state = login(args.home)
                print(f"ChatGPT plan: {state['status']} ({state.get('account') or 'account hidden'})")
                print("Tokens are stored in your private SignalWeave home; they are not Codex CLI credentials.")
            elif args.auth_command == "status":
                state = auth_status(args.home)
                print(f"ChatGPT plan: {state['status']}")
                if state.get("account"):
                    print(f"Account: {state['account']}")
                print(f"Plan usage: {state['plan_usage']}")
            else:
                removed = logout(args.home)
                print("Local ChatGPT tokens removed." if removed else "No local ChatGPT sign-in was saved.")
                print("To revoke remote access too, disconnect SignalWeave in ChatGPT settings.")
            return
        if args.command == "connect":
            from .local_setup import read_config

            home, _ = read_config(args.home)
            agent = args.agent_name or args.agent_flag
            if agent is None:
                raise SetupError("Choose an agent: signalweave connect codex or signalweave connect claude")
            if _connect_agent(home, agent):
                _offer_user_skill(agent, interactive=sys.stdin.isatty())
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
        if args.command == "context":
            from .local_status import context_status

            if args.context_command == "status":
                report = context_status(args.home)
                if args.json:
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    _print_domain_context_status(
                        report, configuration_only=True, heading="Domain-context status:"
                    )
                return

            from .local_setup import configure_domain_context

            enabled = args.context_command == "enable"
            saved_home = configure_domain_context(args.home, enabled=enabled)
            report = context_status(saved_home)
            print(f"Saved domain-context setting: {'enabled' if enabled else 'disabled'}")
            _print_domain_context_status(
                report, configuration_only=True, heading="Effective domain-context configuration:"
            )
            if not enabled:
                print("Stored domain context, cards, and history are kept.")
            print("Restart or reconnect the SignalWeave MCP process for this setting to take effect.")
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

            if args.non_interactive and args.source is None:
                raise SetupError(
                    "Non-interactive connection changes require --source; "
                    "use `--source skip` only with the top-level setup command"
                )

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
                "access_token_file": args.access_token_file,
                "preset_auth": getattr(args, "preset_auth", None),
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
                "agent": args.agent or existing.get("SIGNALWEAVE_AGENT") or "codex",
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

            address = f"http://{args.host}:{args.port}/"
            print(f"SignalWeave local UI: {address}")
            if args.open:
                import webbrowser

                webbrowser.open(address)
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
        # Prefer the human's local profile for a bare `signalweave serve`, while
        # preserving environment-only behavior for deployments that have no local
        # profile. Explicit --home and SIGNALWEAVE_HOME always select local mode.
        default_config = Path.home() / ".signalweave" / "config.toml"
        local_profile_exists = default_config.exists() or default_config.is_symlink()
        context = (
            local_environment(args.home)
            if (
                args.command != "serve"
                or args.home is not None
                or "SIGNALWEAVE_HOME" in os.environ
                or local_profile_exists
            )
            else nullcontext()
        )
        with context as local_home:
            if args.command in {"doctor", "health"}:
                healthy, messages = doctor(local_home)
                report = {"healthy": healthy, "mode": "offline", "messages": messages}
                if args.live:
                    if healthy:
                        from .local_health import live_health_report

                        if not args.json:
                            progress("Checking source access (up to 15 seconds per source)...")
                        live = asyncio.run(live_health_report())
                        report["mode"] = "offline_and_live_source"
                        report["healthy"] = bool(live["healthy"])
                        report["messages"].extend(live["messages"])
                    else:
                        report["messages"].append("Live source checks skipped until offline configuration is healthy.")
                if args.json:
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    print(emphasis("SignalWeave health: " + ("passed" if report["healthy"] else "needs attention")))
                    print("\n".join(report["messages"]))
                if not healthy:
                    raise SystemExit(1)
                if not report["healthy"]:
                    raise SystemExit(1)
                return
            if args.command in {"serve", "run"}:
                if args.command == "serve":
                    selected_profile = (
                        args.profile or os.getenv("SIGNALWEAVE_MCP_PROFILE", "agent").strip().lower()
                    )
                    if selected_profile not in {"agent", "full"}:
                        raise SetupError("SIGNALWEAVE_MCP_PROFILE must be agent or full")
                validate_decision_configuration(local_home)
            elif local_home is not None:
                validate_decision_configuration()
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
    print(emphasis(f"SignalWeave: {str(report.get('status', 'unknown')).replace('_', ' ')}"))
    if report.get("home"):
        print(f"Home: {report['home']}")
    if report.get("error"):
        print(f"Setup: {report['error']}")
    decision = report.get("decision_provider")
    if isinstance(decision, dict):
        print(f"Decision provider: {decision.get('selected', 'not configured')} ({decision.get('status', 'unknown')})")
    jev = report.get("jev")
    if isinstance(jev, dict) and not isinstance(decision, dict):
        print(f"Jev: {jev.get('status', 'unknown')} (live judgment check: {jev.get('live_check', 'not run')})")
    agents = report.get("agents")
    if isinstance(agents, dict):
        print(f"Agent: {agents.get('selected', 'not selected')}")
    domain_context = report.get("domain_context")
    if isinstance(domain_context, dict):
        if domain_context.get("status") in {"blocked", "invalid"} or domain_context.get("environment_override"):
            _print_domain_context_status(domain_context, configuration_only=True)
        else:
            print("Shared context: " + str(domain_context.get("status", "unknown")) + " (configuration only)")
    _print_connections(report)
    credentials = report.get("credentials")
    if isinstance(credentials, dict):
        print("\n" + emphasis("Credentials (values hidden):"))
        visible = {name: status for name, status in credentials.items()
                   if status not in {"not_configured", "missing"}}
        for name, status in visible.items():
            print(f"  {name}: {status}")
        if not visible:
            print("  none configured")
    next_steps = report.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        print("\n" + emphasis("Next:"))
        for step in next_steps:
            print(f"  {step}")


def _print_domain_context_status(
    report: dict[str, object], *, configuration_only: bool, heading: str = "Domain context:",
) -> None:
    """Print only the bounded, nonsecret domain-context status fields."""
    print(heading)
    print(f"  configured: {'yes' if report.get('configured') is True else 'no'}")
    print(f"  enabled: {'yes' if report.get('enabled') is True else 'no'}")
    status = report.get("status")
    if isinstance(status, str) and status in {"enabled", "disabled", "blocked", "invalid"}:
        print(f"  status: {status}")
    else:
        print("  status: invalid")
    print(f"  environment override: {'yes' if report.get('environment_override') is True else 'no'}")
    reason = report.get("reason")
    if isinstance(reason, str) and reason:
        print(f"  reason: {reason}")
    scope = report.get("scope")
    if isinstance(scope, str) and scope:
        print(f"  scope: {scope}")
    if configuration_only:
        print("  Configuration only; this does not check live health.")


def _ask_yes_no(prompt: str, *, default: bool = False) -> bool:
    """Treat a closed input stream as the safe, non-mutating answer."""
    try:
        answer = input(prompt).strip().lower()
        if not answer:
            return default
        return answer in {"y", "yes"}
    except (EOFError, StopIteration):
        return False


def _print_connections(report: dict[str, object]) -> None:
    connections = report.get("connections", [])
    if not isinstance(connections, list):
        return
    print("\n" + emphasis("Connections:"))
    if not connections:
        print("  none")
        return
    for item in connections:
        if not isinstance(item, dict):
            continue
        detail = item.get("endpoint") or item.get("detail") or "not configured"
        print(f"  {item.get('label', item.get('type', 'source'))}: {item.get('status', 'unknown')} ({detail})")


def _connect_agent(home: Path, agent: str, *, required: bool = True) -> bool:
    from .client_setup import register_agent

    status = register_agent(home, agent)
    print(status.message)
    if status.outcome in {"registered", "already_configured"}:
        print("Restart or reconnect the agent, then call get_signalweave_guide.")
        return True
    if status.command:
        if status.outcome == "conflict":
            print("An existing signalweave entry was preserved. Inspect it with your agent's MCP settings;")
            print("remove or rename it only if you intend to replace it, then retry `signalweave connect " + agent + "`.")
        print("Registration was not verified. Review existing entries before running this manual command:")
        print(status.command)
    if status.outcome == "manual_required":
        print("The local setup is unchanged; run the command above, then reconnect the agent.")
        return False
    if not required:
        print("The local setup is saved; finish the agent handoff with the command above.")
        return False
    raise SystemExit(1)


def _offer_user_skill(agent: str, *, interactive: bool) -> None:
    from .skill_install import SkillInstallError, _target, install_skill

    target = _target(agent, "user", None, Path.home())
    command = f"signalweave skills install --agent {agent} --scope user"
    if not interactive:
        print(f"To install the SignalWeave skill for {agent.title()} at {target}, run `{command}`.")
        return

    prompt = (
        f"\nInstall the bundled SignalWeave skill for {agent.title()} in your user scope "
        f"at {target}? [Y/n]: "
    )
    if not _ask_yes_no(prompt, default=True):
        print(f"Skipped skill installation. You can run `{command}` later.")
        return

    try:
        status, installed_target = install_skill(agent, "user")
    except (SkillInstallError, OSError) as error:
        print(f"The agent connection is saved, but the skill was not installed: {error}")
        print(
            "Existing skill contents were not overwritten. Review the path above, "
            f"resolve any conflict or permission issue, then run `{command}`."
        )
        return
    print(f"SignalWeave skill {status.replace('_', ' ')}: {installed_target}")


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

    profile = args.profile or os.getenv("SIGNALWEAVE_MCP_PROFILE", "agent").strip().lower()
    if profile not in {"agent", "full"}:
        raise RuntimeError("SIGNALWEAVE_MCP_PROFILE must be agent or full")
    runtime_mode = os.getenv(
        "SIGNALWEAVE_DECISION_PROVIDER", os.getenv("TYPESAFE_MODE", "jev")
    ).strip().lower()
    if args.transport == "stdio":
        server = create_mcp(build_runtime(mode=runtime_mode), profile=profile)
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
            build_runtime(mode=runtime_mode),
            profile=profile,
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
        runtime = build_runtime(mode=runtime_mode)
        if runtime.principal is None:
            raise RuntimeError(
                "token-authenticated streamable HTTP requires "
                "SIGNALWEAVE_TENANT_ID and SIGNALWEAVE_PRINCIPAL_ID; use stdio for "
                "an intentionally unscoped local process"
            )
        server = create_mcp(runtime, profile=profile, require_principal=True)
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

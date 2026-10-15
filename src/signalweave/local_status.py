"""Secret-free status data for the human local setup experience."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .local_setup import SetupError, credential_status, read_config, resolve_home


def _origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "invalid URL"
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "invalid URL"


def _connection(
    kind: str,
    label: str,
    configured: dict[str, str],
    *,
    url_key: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    url = configured.get(url_key, "").strip() if url_key else ""
    return {
        "type": kind,
        "label": label,
        "status": "configured" if url else "not_configured",
        "endpoint": _origin(url) if url else None,
        "detail": detail,
    }


def local_status(home: str | Path | None = None) -> dict[str, Any]:
    """Build a bounded, secret-free local status report without network calls."""
    root = resolve_home(home)
    try:
        root, configured = read_config(root)
    except (OSError, SetupError) as error:
        return {
            "status": "setup_required",
            "service": "signal-weave",
            "home": str(root),
            "error": str(error),
            "identity": {"tenant": "local", "principal": "local"},
            "jev": {"status": "missing", "mode": "jev", "live_check": "not_run"},
            "connections": [],
            "credentials": {},
            "state": {"backend": "sqlite", "path": "state/signalweave.db"},
            "agents": {"selected": "not selected"},
            "next_steps": ["Run `signalweave setup` to create your private local home."],
        }

    try:
        credentials = credential_status(root)
    except SetupError as error:
        credentials = {"error": str(error)}
    key_ready = credentials.get("TYPESAFE_API_KEY") == "configured"
    profile = configured.get("SIGNALWEAVE_MCP_PROFILE", "agent")
    key_required = profile in {"agent", "full"}
    provider = configured.get(
        "SIGNALWEAVE_DECISION_PROVIDER", configured.get("TYPESAFE_MODE", "jev")
    ).strip().lower()
    openai_ready = credentials.get("OPENAI_API_KEY") == "configured"
    chatgpt = {"status": "not_connected", "account": None, "plan_usage": "not_enabled"}
    if provider == "chatgpt-plan":
        from .chatgpt_auth import auth_status

        chatgpt = auth_status(root)
    decision_ready = (
        provider == "jev" and key_ready
        or provider == "openai-decisions" and openai_ready
        or provider == "chatgpt-plan" and chatgpt["status"] == "connected"
    )
    connections = [
        _connection("superset", "Superset", configured, url_key="SUPERSET_URL"),
        _connection("preset", "Preset", configured, url_key="PRESET_URL"),
        _connection(
            "trino",
            "Trino",
            configured,
            url_key="TRINO_URL",
            detail=(
                "catalog configured"
                if configured.get("TRINO_CATALOG_FILE")
                else "catalog file missing"
            ),
        ),
        {
            "type": "mcp",
            "label": "Company MCP source bridge",
            "status": (
                "configured"
                if configured.get("SIGNALWEAVE_MCP_SOURCES_FILE")
                else "not_configured"
            ),
            "endpoint": None,
            "detail": configured.get("SIGNALWEAVE_MCP_SOURCES_FILE"),
        },
    ]
    configured_connections = [item for item in connections if item["status"] == "configured"]
    if key_required and not decision_ready:
        overall = "setup_required"
    elif not configured_connections:
        overall = "onboarding_only"
    else:
        overall = "ready_for_agent"
    next_steps: list[str] = []
    if key_required and not decision_ready:
        if provider == "jev":
            next_steps.append("Run `signalweave credentials set typesafe`.")
        elif provider == "openai-decisions":
            next_steps.append("Run `signalweave credentials set openai`.")
        elif provider == "chatgpt-plan":
            next_steps.append("Run `signalweave auth login` and approve ChatGPT-plan usage.")
        else:
            next_steps.append("Run `signalweave setup` and choose a decision provider.")
    if not configured_connections:
        next_steps.append("Run `signalweave connections add` to connect a source.")
    if configured_connections:
        next_steps.append("Run `signalweave doctor --live` to test source access.")
        next_steps.append("Run `signalweave connect codex` or `signalweave connect claude`.")
    return {
        "status": overall,
        "service": "signal-weave",
        "home": str(root),
        "identity": {
            "tenant": configured.get("SIGNALWEAVE_TENANT_ID", "local"),
            "principal": configured.get("SIGNALWEAVE_PRINCIPAL_ID", "local"),
        },
        "decision_provider": {
            "selected": provider,
            "status": "configured" if decision_ready else "needs_setup",
            "chatgpt_plan": chatgpt if provider == "chatgpt-plan" else None,
        },
        "jev": {
            "status": "configured" if provider == "jev" and key_ready else "not_selected",
            "mode": "jev",
            "live_check": "not_run",
        },
        "credentials": credentials,
        "connections": connections,
        "state": {
            "backend": configured.get("SIGNALWEAVE_STORE_BACKEND", "sqlite"),
            "path": configured.get("SIGNALWEAVE_STORE_PATH", "state/signalweave.db"),
        },
        "agents": {
            "selected": configured.get("SIGNALWEAVE_AGENT", "not selected"),
            "codex": "run `signalweave connect codex`",
            "claude": "run `signalweave connect claude`",
        },
        "next_steps": next_steps,
    }


__all__ = ["local_status"]

"""Explicit, bounded live checks for the human local setup."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from .runtime import build_runtime


async def live_source_report(*, timeout_seconds: float = 15.0) -> tuple[bool, list[str]]:
    """Probe each configured catalog without making a Jev judgment request.

    A catalog search is deliberately used instead of an insight run: it proves
    source reachability and catalog access while keeping this health check cheap
    and side-effect free. Provider errors are intentionally summarized so a
    secret or signed URL cannot leak into terminal output.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    profile = os.getenv("SIGNALWEAVE_MCP_PROFILE", "agent").strip().lower()
    if profile not in {"agent", "full"}:
        return False, ["SIGNALWEAVE_MCP_PROFILE must be agent or full."]
    runtime = build_runtime(mode="agent" if profile == "agent" else "jev")
    names = runtime.sources.adapter_names()
    if not names:
        return False, ["No source adapters are configured."]
    messages: list[str] = []
    healthy = True
    for name in names:
        try:
            page = await asyncio.wait_for(
                runtime.sources.search_resources(
                    "", adapter_name=name, limit=1
                ),
                timeout=timeout_seconds,
            )
            if getattr(page, "strategy", None) == "adapter-error":
                healthy = False
                messages.append(f"{name}: request failed; check URL, credentials, and access scope.")
                continue
            count = getattr(page, "total_count", None)
            suffix = f"; catalog items visible: {count}" if count is not None else ""
            messages.append(f"{name}: reachable and searchable{suffix}.")
        except asyncio.TimeoutError:
            healthy = False
            messages.append(f"{name}: timed out after {timeout_seconds:g}s.")
        except Exception:
            healthy = False
            messages.append(f"{name}: request failed; check URL, credentials, and access scope.")
    return healthy, messages


async def live_health_report(*, timeout_seconds: float = 15.0) -> dict[str, Any]:
    healthy, messages = await live_source_report(timeout_seconds=timeout_seconds)
    return {"healthy": healthy, "messages": messages}


__all__ = ["live_health_report", "live_source_report"]

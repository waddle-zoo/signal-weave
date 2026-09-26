"""Run a bounded, no-Jev-call Preset connection preflight.

The preflight authenticates the configured Preset connection and reads only one
dashboard catalog page. It deliberately does not inspect chart data, create a
card, call Jev, approve anything, or contact a delivery destination.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from signalweave.preset_adapter import PresetAdapter
from signalweave.runtime import build_runtime


async def run(*, adapter_name: str, page_size: int, output: Path | None = None) -> dict[str, Any]:
    runtime = build_runtime()
    if runtime.principal is None:
        raise RuntimeError(
            "Preset bootstrap requires SIGNALWEAVE_TENANT_ID and "
            "SIGNALWEAVE_PRINCIPAL_ID"
        )
    adapter = runtime.sources._get(adapter_name)
    if not isinstance(adapter, PresetAdapter):
        raise RuntimeError(f"{adapter_name!r} is not a Preset adapter")

    dashboards, provider_count = await adapter.client.list_dashboards_page(
        page=0,
        page_size=page_size,
    )
    judger = runtime.engine.judger
    jev_requests = getattr(getattr(judger, "metrics", None), "requests", 0)
    report = {
        "trial": "preset-bootstrap-check",
        "adapter": adapter_name,
        "tenant_id": runtime.principal.tenant_id,
        "policy": adapter.policy.model_dump(mode="json"),
        "catalog": {
            "page_size": page_size,
            "returned_dashboards": len(dashboards),
            "provider_count": provider_count,
            "has_dashboard": bool(dashboards),
        },
        "checks": {
            "jev_runtime_configured": getattr(judger, "name", None) == "jev-latest",
            "tenant_principal_configured": True,
            "preset_catalog_request_succeeded": True,
            "workspace_has_dashboard": bool(dashboards),
            "jev_calls_made": jev_requests == 0,
        },
        "jev_requests": jev_requests,
        "passed": bool(dashboards)
        and getattr(judger, "name", None) == "jev-latest"
        and jev_requests == 0,
        "not_proven": [
            "chart-level permissions and semantic quality",
            "a human-approved card or Jev shadow decision",
            "managed SignalWeave hosting",
        ],
    }
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", default="preset__preset-env")
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 100:
        parser.error("--page-size must be between 1 and 100")
    report = asyncio.run(
        run(adapter_name=args.adapter, page_size=args.page_size, output=args.output)
    )
    if not report["passed"]:
        raise SystemExit("Preset bootstrap preflight did not pass")


if __name__ == "__main__":
    main()

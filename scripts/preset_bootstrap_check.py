"""Run a bounded, no-Jev-call Preset connection preflight.

The preflight authenticates the configured Preset connection and reads only one
dashboard catalog page by default. With ``--dashboard-id`` and ``--chart-id``
it also probes one dashboard-scoped chart read. It never creates a card, calls
Jev, approves anything, or contacts a delivery destination.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from signalweave.hosted import HostedDataMode
from signalweave.preset_adapter import PresetAdapter
from signalweave.runtime import (
    build_preset_adapter_from_environment,
    validate_preset_environment,
)


def _chart_probe_remediation(error: str | None) -> str | None:
    """Turn a common provider artifact failure into an onboarding action."""

    if error and "query context" in error.lower():
        return (
            "Re-save the chart in Preset so its saved query context is persisted, "
            "then rerun this probe. SignalWeave will not bypass dashboard filter "
            "scope with an unscoped fallback."
        )
    return None


async def run(
    *,
    adapter_name: str | None,
    page_size: int,
    dashboard_id: str | None = None,
    chart_id: str | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    if bool(dashboard_id) != bool(chart_id):
        raise ValueError("dashboard_id and chart_id must be supplied together")
    configuration = validate_preset_environment()
    adapter = build_preset_adapter_from_environment()
    if adapter is None:
        raise RuntimeError("Preset bootstrap requires PRESET_URL")
    if not isinstance(adapter, PresetAdapter):
        raise RuntimeError("the environment adapter is not a Preset adapter")
    if adapter_name is None:
        adapter_name = adapter.name
    elif adapter_name != adapter.name:
        raise RuntimeError(f"{adapter_name!r} is not the configured Preset adapter")

    dashboards, provider_count = await adapter.client.list_dashboards_page(
        page=0,
        page_size=page_size,
    )
    jev_mode_configured = os.getenv("TYPESAFE_MODE", "jev").strip().lower() == "jev"
    jev_requests = 0
    chart_probe: dict[str, Any] | None = None
    if dashboard_id and chart_id:
        if adapter.policy.mode == HostedDataMode.METADATA_ONLY:
            chart_probe = {
                "dashboard_id": dashboard_id,
                "chart_id": chart_id,
                "error": "metadata_only policy forbids chart-data probes",
                "passed": False,
            }
        else:
            snapshot = await adapter.client.dashboard_snapshot(
                dashboard_id,
                include_data=True,
                chart_ids=[chart_id],
            )
            if not snapshot.charts:
                chart_probe = {
                    "dashboard_id": dashboard_id,
                    "chart_id": chart_id,
                    "error": "the dashboard returned no matching chart",
                    "passed": False,
                }
            else:
                chart = snapshot.charts[0]
                remediation = _chart_probe_remediation(chart.error)
                chart_probe = {
                    "dashboard_id": dashboard_id,
                    "chart_id": chart_id,
                    "semantic_status": chart.semantic_status,
                    "observation_count": len(chart.observations),
                    "error": chart.error,
                    "passed": chart.error is None and bool(chart.observations),
                }
                if remediation:
                    chart_probe["remediation"] = remediation
    report = {
        "trial": "preset-bootstrap-check",
        "adapter": adapter_name,
        "tenant_id": configuration["tenant_id"],
        "policy": adapter.policy.model_dump(mode="json"),
        "catalog": {
            "page_size": page_size,
            "returned_dashboards": len(dashboards),
            "provider_count": provider_count,
            "has_dashboard": bool(dashboards),
        },
        "checks": {
            "jev_runtime_configured": jev_mode_configured,
            "identity_scope_configured": True,
            "static_tenant_principal_configured": configuration["principal_mode"] == "static",
            "preset_catalog_request_succeeded": True,
            "workspace_has_dashboard": bool(dashboards),
            "jev_calls_made": jev_requests == 0,
            "dashboard_chart_probe": chart_probe is None or chart_probe["passed"],
        },
        "chart_probe": chart_probe,
        "jev_requests": jev_requests,
        "passed": bool(dashboards)
        and jev_mode_configured
        and jev_requests == 0
        and (chart_probe is None or chart_probe["passed"]),
        "not_proven": [
            "chart-level permissions and semantic quality"
            if chart_probe is None
            else "business usefulness beyond the selected chart probe",
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
    parser.add_argument(
        "--adapter",
        default=None,
        help="Configured Preset adapter name; auto-detects the sole Preset adapter by default",
    )
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--dashboard-id")
    parser.add_argument("--chart-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 100:
        parser.error("--page-size must be between 1 and 100")
    report = asyncio.run(
        run(
            adapter_name=args.adapter,
            page_size=args.page_size,
            dashboard_id=args.dashboard_id,
            chart_id=args.chart_id,
            output=args.output,
        )
    )
    if not report["passed"]:
        raise SystemExit("Preset bootstrap preflight did not pass")


if __name__ == "__main__":
    main()

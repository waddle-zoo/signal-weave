"""Run a bounded, no-Jev-call Preset connection preflight.

The preflight authenticates the configured Preset connection and reads one
bounded dashboard catalog page by default. With ``--dashboard-id`` and
``--chart-id`` it probes one dashboard-scoped chart; with ``--dashboard-id``
alone it checks the full dashboard through the production adapter and reports
chart readiness. ``--dashboard-query`` can select a unique dashboard by title
substring, but ambiguous matches fail closed instead of picking the first
result.
It never creates a card, calls Jev, approves anything, or contacts a delivery
destination.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from signalweave.hosted import HostedDataMode
from signalweave.models import SourceRef
from signalweave.preset_adapter import PresetAdapter
from signalweave.preset_env import preset_environment_file
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


def _remediations(errors: list[str]) -> list[str]:
    values: list[str] = []
    for error in errors:
        remediation = _chart_probe_remediation(error)
        if remediation and remediation not in values:
            values.append(remediation)
    return values


def _provider_failure(error: Exception) -> dict[str, Any]:
    """Return a redacted, actionable provider failure without response content."""

    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        if status_code in {401, 403}:
            category = "authentication_or_permission"
            remediation = (
                "Verify that the Preset API is enabled for the workspace, the token "
                "has access to the selected workspace and read-only assets, and the "
                "configured token mode matches the credential files."
            )
        elif status_code == 429:
            category = "rate_limited"
            remediation = (
                "Wait for the Preset rate-limit window to clear, then rerun the bounded "
                "bootstrap probe; do not increase page size or retry limits to bypass it."
            )
        elif status_code >= 500:
            category = "provider_unavailable"
            remediation = (
                "Confirm the Preset workspace is healthy and rerun the probe; the "
                "connector will keep provider retries bounded."
            )
        else:
            category = "provider_request_rejected"
            remediation = (
                "Inspect the selected Preset resource and data-policy permissions, "
                "then rerun the bounded probe."
            )
        return {
            "category": category,
            "status_code": status_code,
            "error_type": "HTTPStatusError",
            "remediation": remediation,
        }
    if isinstance(error, httpx.RequestError):
        return {
            "category": "transport_error",
            "error_type": type(error).__name__,
            "remediation": (
                "Verify DNS, TLS, egress policy, and the Preset workspace origin, "
                "then rerun the bounded bootstrap probe."
            ),
        }
    return {
        "category": "provider_error",
        "error_type": type(error).__name__,
        "remediation": "Inspect the provider integration logs and rerun the bounded probe.",
    }


def _failure_report(error: Exception) -> dict[str, Any]:
    """Build the no-secret report used when provider bootstrap cannot complete."""

    return {
        "trial": "preset-bootstrap-check",
        "passed": False,
        "failure": _provider_failure(error),
        "checks": {
            "provider_transport_used": False,
            "provider_request_failed": True,
            "jev_calls_made": 0,
        },
        "jev_requests": 0,
        "not_proven": [
            "Preset credentials are accepted by the provider",
            "dashboard/chart permissions and result-shape quality",
            "a human-approved card or Jev shadow decision",
            "managed SignalWeave hosting",
        ],
    }


async def _select_dashboard_by_query(
    client: Any,
    *,
    query: str,
    page_size: int,
    max_pages: int,
) -> tuple[list[dict[str, Any]], int | None, bool]:
    """Resolve a unique dashboard with bounded, provider-side title search.

    The provider's ``count`` is retained so a customer can tell the difference
    between an empty search and a search that was truncated by the safety cap.
    We never silently choose one dashboard from an ambiguous title match.
    """

    if not query.strip():
        raise ValueError("dashboard_query must not be empty")
    matches: list[dict[str, Any]] = []
    provider_count: int | None = None
    for page in range(max_pages):
        batch, count = await client.list_dashboards_page(
            page=page,
            page_size=page_size,
            query=query,
        )
        if provider_count is None and isinstance(count, int):
            provider_count = count
        matches.extend(item for item in batch if isinstance(item, dict))
        if not batch or len(batch) < page_size or (
            isinstance(count, int) and (page + 1) * page_size >= count
        ):
            break
    truncated = isinstance(provider_count, int) and len(matches) < provider_count
    return matches, provider_count, truncated


async def _run_loaded(
    *,
    adapter_name: str | None,
    page_size: int,
    dashboard_id: str | None = None,
    chart_id: str | None = None,
    dashboard_query: str | None = None,
    max_pages: int = 5,
    output: Path | None = None,
) -> dict[str, Any]:
    if chart_id and not dashboard_id:
        raise ValueError("chart_id requires dashboard_id")
    if dashboard_id and dashboard_query:
        raise ValueError("dashboard_id and dashboard_query are mutually exclusive")
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
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

    jev_mode_configured = os.getenv("TYPESAFE_MODE", "jev").strip().lower() == "jev"
    if not jev_mode_configured:
        raise RuntimeError(
            "Preset bootstrap requires TYPESAFE_MODE=jev; refusing provider access"
        )
    provider_requests_before = getattr(adapter.client, "requests_made", None)
    if not isinstance(provider_requests_before, int):
        raise RuntimeError(
            "Preset bootstrap requires a client with provider request telemetry"
        )
    catalog_truncated = False
    catalog_requested = False
    if dashboard_query:
        catalog_requested = True
        dashboards, provider_count, catalog_truncated = await _select_dashboard_by_query(
            adapter.client,
            query=dashboard_query,
            page_size=page_size,
            max_pages=max_pages,
        )
        if len(dashboards) == 1 and dashboards[0].get("id") is not None:
            dashboard_id = str(dashboards[0]["id"])
        elif not dashboards:
            dashboard_id = None
        else:
            dashboard_id = None
    elif dashboard_id:
        # An explicit provider resource is already an onboarding anchor. Do
        # not require a broad catalog permission just to revalidate it; many
        # hosted workspaces expose direct dashboard reads more narrowly than
        # dashboard listing.
        dashboards = []
        provider_count = None
    else:
        catalog_requested = True
        dashboards, provider_count = await adapter.client.list_dashboards_page(
            page=0,
            page_size=page_size,
        )
    provider_requests_after_catalog = getattr(adapter.client, "requests_made", None)
    catalog_requests = (
        provider_requests_after_catalog - provider_requests_before
        if isinstance(provider_requests_after_catalog, int)
        else None
    )
    jev_requests = 0
    chart_probe: dict[str, Any] | None = None
    dashboard_probe: dict[str, Any] | None = None
    selection: dict[str, Any] | None = None
    if dashboard_query:
        selection = {
            "query": dashboard_query,
            "matched_dashboards": [
                {
                    "id": item.get("id"),
                    "title": item.get("dashboard_title"),
                }
                for item in dashboards
            ],
            "max_pages": max_pages,
            "truncated": catalog_truncated,
            "selected_dashboard_id": dashboard_id,
            "passed": (
                len(dashboards) == 1
                and dashboards[0].get("id") is not None
                and not catalog_truncated
            ),
        }
        if not selection["passed"]:
            dashboard_id = None
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
                returned_chart_id = str(getattr(chart, "id", ""))
                if returned_chart_id != str(chart_id):
                    chart_probe = {
                        "dashboard_id": dashboard_id,
                        "chart_id": chart_id,
                        "returned_chart_id": returned_chart_id or None,
                        "error": (
                            "the provider returned a different chart than requested; "
                            "the chart-scope probe cannot be trusted"
                        ),
                        "passed": False,
                    }
                else:
                    remediation = _chart_probe_remediation(chart.error)
                    chart_probe = {
                        "dashboard_id": dashboard_id,
                        "chart_id": chart_id,
                        "returned_chart_id": returned_chart_id,
                        "semantic_status": chart.semantic_status,
                        "observation_count": len(chart.observations),
                        "error": chart.error,
                        "passed": chart.error is None and bool(chart.observations),
                    }
                    if remediation:
                        chart_probe["remediation"] = remediation
    elif dashboard_id:
        if adapter.policy.mode == HostedDataMode.METADATA_ONLY:
            dashboard_probe = {
                "dashboard_id": dashboard_id,
                "error": "metadata_only policy forbids dashboard chart-data probes",
                "passed": False,
            }
        else:
            try:
                snapshot = await adapter.inspect(
                    SourceRef(
                        key="preset-bootstrap-dashboard",
                        adapter=adapter.name,
                        resource=f"dashboard:{dashboard_id}",
                        label=f"Preset dashboard {dashboard_id}",
                    )
                )
            except Exception as error:  # noqa: BLE001 - preflight must return a report
                dashboard_probe = {
                    "dashboard_id": dashboard_id,
                    "error": str(error),
                    "passed": False,
                }
            else:
                quality = snapshot.metadata.get("data_quality", {})
                chart_errors = quality.get("chart_errors", [])
                semantic_issues = quality.get("semantic_issues", [])
                if not isinstance(chart_errors, list):
                    chart_errors = [str(chart_errors)]
                if not isinstance(semantic_issues, list):
                    semantic_issues = [str(semantic_issues)]
                dashboard_probe = {
                    "dashboard_id": dashboard_id,
                    "quality_status": quality.get("status"),
                    "chart_count": quality.get("chart_count", 0),
                    "charts_with_observations": quality.get("charts_with_observations", 0),
                    "chart_errors": chart_errors,
                    "semantic_issues": semantic_issues,
                    "error": snapshot.error,
                    "remediations": _remediations(chart_errors),
                    "passed": (
                        snapshot.error is None
                        and quality.get("status") == "healthy"
                        and not chart_errors
                        and not semantic_issues
                    ),
                }
    provider_requests_after = getattr(adapter.client, "requests_made", None)
    provider_requests_for_bootstrap = (
        provider_requests_after - provider_requests_before
        if isinstance(provider_requests_after, int)
        else None
    )
    provider_transport_used = (
        isinstance(provider_requests_for_bootstrap, int)
        and provider_requests_for_bootstrap > 0
    )
    explicit_anchor = bool(dashboard_id) and not dashboard_query
    target_available = explicit_anchor or bool(dashboards)
    catalog_request_succeeded = (
        isinstance(catalog_requests, int) and catalog_requests > 0
    )
    report = {
        "trial": "preset-bootstrap-check",
        "adapter": adapter_name,
        "tenant_id": configuration["tenant_id"],
        "policy": adapter.policy.model_dump(mode="json"),
        "catalog": {
            "page_size": page_size,
            "max_pages": max_pages if dashboard_query else 1,
            "query": dashboard_query,
            "returned_dashboards": len(dashboards),
            "provider_count": provider_count,
            "has_dashboard": bool(dashboards),
            "truncated": catalog_truncated,
            "requested": catalog_requested,
            "explicit_anchor": explicit_anchor,
        },
        "checks": {
            "jev_runtime_configured": jev_mode_configured,
            "identity_scope_configured": True,
            "static_tenant_principal_configured": configuration["principal_mode"] == "static",
            "preset_catalog_request_succeeded": catalog_request_succeeded,
            "explicit_anchor_bypassed_catalog": explicit_anchor,
            "provider_transport_used": provider_transport_used,
            "workspace_has_dashboard": target_available,
            "dashboard_selection": selection is None or selection["passed"],
            "jev_calls_made": jev_requests == 0,
            "dashboard_chart_probe": chart_probe is None or chart_probe["passed"],
            "dashboard_readiness_probe": (
                dashboard_probe is None or dashboard_probe["passed"]
            ),
        },
        "chart_probe": chart_probe,
        "dashboard_probe": dashboard_probe,
        "selection": selection,
        "provider_requests": {
            "before_bootstrap": provider_requests_before,
            "after_catalog": provider_requests_after_catalog,
            "after_bootstrap": provider_requests_after,
            "catalog_requests": catalog_requests,
            "for_bootstrap": provider_requests_for_bootstrap,
        },
        "jev_requests": jev_requests,
        "passed": target_available
        and jev_mode_configured
        and provider_transport_used
        and (selection is None or selection["passed"])
        and jev_requests == 0
        and (chart_probe is None or chart_probe["passed"])
        and (dashboard_probe is None or dashboard_probe["passed"]),
        "not_proven": [
            (
                "business usefulness beyond the dashboard readiness probe"
                if dashboard_probe is not None and chart_probe is None
                else "chart-level permissions and semantic quality"
                if chart_probe is None
                else "business usefulness beyond the selected chart probe"
            ),
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


async def run(
    *,
    adapter_name: str | None,
    page_size: int,
    dashboard_id: str | None = None,
    chart_id: str | None = None,
    dashboard_query: str | None = None,
    max_pages: int = 5,
    output: Path | None = None,
) -> dict[str, Any]:
    with preset_environment_file():
        try:
            report = await _run_loaded(
                adapter_name=adapter_name,
                page_size=page_size,
                dashboard_id=dashboard_id,
                chart_id=chart_id,
                dashboard_query=dashboard_query,
                max_pages=max_pages,
                output=output,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as error:
            report = _failure_report(error)
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
    parser.add_argument(
        "--page-size",
        type=int,
        default=int(os.getenv("PRESET_BOOTSTRAP_PAGE_SIZE", "20")),
    )
    parser.add_argument(
        "--dashboard-id",
        default=os.getenv("PRESET_BOOTSTRAP_DASHBOARD_ID", "").strip() or None,
    )
    parser.add_argument(
        "--dashboard-query",
        default=os.getenv("PRESET_BOOTSTRAP_DASHBOARD_QUERY", "").strip() or None,
        help=(
            "Select exactly one dashboard whose title contains this text; "
            "ambiguous or truncated matches fail closed"
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=int(os.getenv("PRESET_BOOTSTRAP_MAX_PAGES", "5")),
        help="Maximum provider pages to inspect for --dashboard-query (default: 5)",
    )
    parser.add_argument(
        "--chart-id",
        default=os.getenv("PRESET_BOOTSTRAP_CHART_ID", "").strip() or None,
        help="Probe one chart; omit this flag with --dashboard-id to scan the full dashboard",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 100:
        parser.error("--page-size must be between 1 and 100")
    if not 1 <= args.max_pages <= 100:
        parser.error("--max-pages must be between 1 and 100")
    report = asyncio.run(
        run(
            adapter_name=args.adapter,
            page_size=args.page_size,
            dashboard_id=args.dashboard_id,
            chart_id=args.chart_id,
            dashboard_query=args.dashboard_query,
            max_pages=args.max_pages,
            output=args.output,
        )
    )
    if not report["passed"]:
        raise SystemExit("Preset bootstrap preflight did not pass")


if __name__ == "__main__":
    main()

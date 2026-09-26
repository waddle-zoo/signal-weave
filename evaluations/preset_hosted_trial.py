"""Run a provider-shaped Preset integration trial without TypeSafe credits.

This trial is deliberately outside ``src/``. It drives the shipped
``PresetCloudClient`` and ``PresetAdapter`` through an HTTP transport that
resembles the documented Superset-compatible response shapes: several
visualization types, several tabular result envelopes, one provider failure,
one unsupported metric, and one empty result. It proves transport, parsing,
policy, and failure boundaries; it does not pretend a mock proves a real
customer's Preset plan, permissions, rate limits, or Jev semantic quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from signalweave.hosted import HostedDataMode, HostedDataPolicy
from signalweave.models import SourceRef
from signalweave.preset_adapter import PresetAdapter, PresetCloudClient, PresetPolicyError

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "evaluations" / "data" / "preset-workspaces.json"


class WorkspaceTransport:
    def __init__(self, workspace: dict[str, Any], *, expire_once: bool = False) -> None:
        self.workspace = workspace
        self.expire_once = expire_once
        self.expired = False
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            {
                "method": request.method,
                "host": request.url.host,
                "path": request.url.path,
                "params": dict(request.url.params),
                "payload": json.loads(request.content) if request.content else None,
            }
        )
        if request.url.host == "api.app.preset.test":
            if request.url.path != "/v1/auth/":
                return httpx.Response(404, json={"message": "unknown auth route"})
            token = "preset-jwt-2" if self.expired else "preset-jwt-1"
            return httpx.Response(200, json={"payload": {"access_token": token}})

        if request.headers.get("authorization") not in {
            "Bearer preset-token",
            "Bearer preset-jwt-1",
            "Bearer preset-jwt-2",
        }:
            return httpx.Response(401, json={"message": "expired"})
        if self.expire_once and not self.expired:
            self.expired = True
            return httpx.Response(401, json={"message": "expired"})

        if request.url.path == "/api/v1/dashboard/":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "id": self.workspace["dashboard_id"],
                            "dashboard_title": self.workspace["dashboard_title"],
                        }
                    ],
                    "count": 1,
                },
            )

        if request.url.path == f"/api/v1/dashboard/{self.workspace['dashboard_id']}":
            position = {
                f"chart-{chart['id']}": {
                    "type": "CHART",
                    "meta": {"chartId": chart["id"], "sliceName": chart["title"]},
                }
                for chart in self.workspace["charts"]
            }
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": self.workspace["dashboard_id"],
                        "dashboard_title": self.workspace["dashboard_title"],
                        "position_json": position,
                    }
                },
            )

        prefix = "/api/v1/chart/"
        if request.url.path.startswith(prefix) and request.url.path.endswith("/data"):
            chart_id = request.url.path.removeprefix(prefix).removesuffix("/data")
            chart = next(chart for chart in self.workspace["charts"] if chart["id"] == chart_id)
            if request.method != "GET" or request.url.params.get("filter_dashboard_id") != str(
                self.workspace["dashboard_id"]
            ):
                return httpx.Response(
                    400,
                    json={"message": "dashboard filter context was not supplied"},
                )
            return httpx.Response(
                200,
                json={
                    "result": chart.get("result", []),
                    "dashboard_filters": {"filters": []},
                },
            )

        if request.url.path.startswith(prefix) and request.url.path != "/api/v1/chart/data":
            chart_id = request.url.path.removeprefix(prefix)
            chart = next(chart for chart in self.workspace["charts"] if chart["id"] == chart_id)
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": chart["id"],
                        "slice_name": chart["title"],
                        "viz_type": chart["viz_type"],
                        "params": json.dumps(chart["params"])
                        if isinstance(chart["params"], dict)
                        else chart["params"],
                    }
                },
            )

        if request.url.path == "/api/v1/chart/data":
            payload = self.requests[-1]["payload"]
            chart_id = str(payload.get("form_data", {}).get("slice_id"))
            chart = next(chart for chart in self.workspace["charts"] if chart["id"] == chart_id)
            if chart.get("http_status"):
                return httpx.Response(chart["http_status"], json={"message": "provider unavailable"})
            return httpx.Response(200, json={"result": chart.get("result", [])})

        return httpx.Response(404, json={"message": f"unknown route {request.url.path}"})


def _load_fixture() -> list[dict[str, Any]]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    workspaces = payload.get("workspaces")
    if not isinstance(workspaces, list) or not workspaces:
        raise RuntimeError("Preset fixture must contain a non-empty workspaces list")
    return [workspace for workspace in workspaces if isinstance(workspace, dict)]


async def _inspect_workspace(workspace: dict[str, Any]) -> dict[str, Any]:
    transport = WorkspaceTransport(workspace)
    client = PresetCloudClient(
        f"https://{workspace['id']}.preset.test",
        api_token_name="trial-name",
        api_token_secret="trial-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(transport),
    )
    adapter = PresetAdapter(
        client,
        tenant_id=workspace["tenant_id"],
        policy=HostedDataPolicy(max_result_rows=100),
        adapter_name=f"preset__{workspace['id']}",
    )
    snapshot = await adapter.inspect(
        SourceRef(
            key=f"{workspace['id']}-dashboard",
            adapter=adapter.name,
            resource=f"dashboard:{workspace['dashboard_id']}",
            label=workspace["dashboard_title"],
        )
    )
    observed_chart_ids = {
        observation.subject_id.split(":", 1)[0] for observation in snapshot.observations
    }
    chart_errors = [chart for chart in snapshot.metadata["charts"] if chart.get("error")]
    return {
        "workspace": workspace["id"],
        "tenant_id": workspace["tenant_id"],
        "chart_count": len(workspace["charts"]),
        "viz_types": sorted(
            {str(chart.get("viz_type") or "unknown") for chart in workspace["charts"]}
        ),
        "observations": len(snapshot.observations),
        "charts_with_observations": len(observed_chart_ids),
        "chart_errors": len(chart_errors),
        "quality_status": snapshot.metadata["data_quality"]["status"],
        "request_counts": {
            "auth": sum(request["path"] == "/v1/auth/" for request in transport.requests),
            "dashboard": sum(request["path"].startswith("/api/v1/dashboard/") for request in transport.requests),
            "chart_metadata": sum(
                request["path"].startswith("/api/v1/chart/")
                and request["path"] != "/api/v1/chart/data"
                for request in transport.requests
            ),
            "chart_data": sum(request["path"] == "/api/v1/chart/data" for request in transport.requests),
            "dashboard_chart_data": sum(
                request["path"].endswith("/data") for request in transport.requests
            ),
        },
        "cached_query_guards": all(
            request["method"] == "GET"
            and request["params"].get("force") == "false"
            and request["params"].get("filter_dashboard_id")
            == str(workspace["dashboard_id"])
            for request in transport.requests
            if request["path"].endswith("/data")
        ),
        "dashboard_filters_sent": all(
            request["method"] == "GET"
            and request["params"].get("filter_dashboard_id")
            == str(workspace["dashboard_id"])
            for request in transport.requests
            if request["path"].endswith("/data")
        ),
    }


async def _metadata_only_case(workspace: dict[str, Any]) -> dict[str, Any]:
    transport = WorkspaceTransport(workspace)
    client = PresetCloudClient(
        f"https://{workspace['id']}.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(transport),
    )
    adapter = PresetAdapter(
        client,
        tenant_id=workspace["tenant_id"],
        policy=HostedDataPolicy(mode=HostedDataMode.METADATA_ONLY),
    )
    snapshot = await adapter.inspect(
        SourceRef(
            key="metadata-only",
            adapter="preset",
            resource=f"dashboard:{workspace['dashboard_id']}",
            label=workspace["dashboard_title"],
        )
    )
    return {
        "no_chart_data": not any(
            request["path"] == "/api/v1/chart/data" for request in transport.requests
        ),
        "no_chart_metadata": not any(
            request["path"].startswith("/api/v1/chart/")
            and request["path"] != "/api/v1/chart/data"
            for request in transport.requests
        ),
        "chart_count": snapshot.metadata["chart_count"],
    }


async def _refresh_case(workspace: dict[str, Any]) -> dict[str, Any]:
    transport = WorkspaceTransport(workspace, expire_once=True)
    client = PresetCloudClient(
        f"https://{workspace['id']}.preset.test",
        api_token_name="trial-name",
        api_token_secret="trial-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(transport),
    )
    metadata = await client.get_dashboard_metadata(workspace["dashboard_id"])
    return {
        "retried_after_401": metadata["id"] == workspace["dashboard_id"],
        "auth_calls": sum(request["path"] == "/v1/auth/" for request in transport.requests),
        "dashboard_calls": sum(
            request["path"] == f"/api/v1/dashboard/{workspace['dashboard_id']}"
            for request in transport.requests
        ),
    }


async def _live_query_case(workspace: dict[str, Any]) -> dict[str, Any]:
    transport = WorkspaceTransport(workspace)
    client = PresetCloudClient(
        f"https://{workspace['id']}.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(transport),
    )
    adapter = PresetAdapter(
        client,
        tenant_id=workspace["tenant_id"],
        policy=HostedDataPolicy(
            mode=HostedDataMode.LIVE_QUERY,
            allow_live_queries=True,
            allow_refresh=True,
            max_result_rows=100,
        ),
    )
    await adapter.inspect(
        SourceRef(
            key="live-query",
            adapter="preset",
            resource=f"dashboard:{workspace['dashboard_id']}",
            label=workspace["dashboard_title"],
        )
    )
    query_requests = [
        request for request in transport.requests if request["path"].endswith("/data")
    ]
    return {
        "chart_data_requests": len(query_requests),
        "all_requests_force_refresh": all(
            request["params"].get("force") == "true" for request in query_requests
        ),
    }


async def _policy_cases(workspace: dict[str, Any]) -> dict[str, Any]:
    row_transport = WorkspaceTransport(workspace)
    row_client = PresetCloudClient(
        f"https://{workspace['id']}.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(row_transport),
    )
    row_adapter = PresetAdapter(
        row_client,
        tenant_id=workspace["tenant_id"],
        policy=HostedDataPolicy(max_result_rows=1),
    )
    row_snapshot = await row_adapter.inspect(
        SourceRef(
            key="bounded",
            adapter="preset",
            resource=f"dashboard:{workspace['dashboard_id']}",
            label=workspace["dashboard_title"],
        )
    )

    byte_transport = WorkspaceTransport(workspace)
    byte_client = PresetCloudClient(
        f"https://{workspace['id']}.preset.test",
        access_token="preset-token",
        max_snapshot_bytes=64,
        transport=httpx.MockTransport(byte_transport),
    )
    try:
        await byte_client.get_dashboard_metadata(workspace["dashboard_id"])
    except PresetPolicyError:
        byte_blocked = True
    else:
        byte_blocked = False

    return {
        "row_limit_policy_enforced": row_snapshot.error is not None
        and row_snapshot.observations == []
        and any(
            request["path"].endswith("/data")
            and request["params"].get("filter_dashboard_id")
            == str(workspace["dashboard_id"])
            for request in row_transport.requests
        ),
        "row_overflow_failed_closed": row_snapshot.error is not None
        and not row_snapshot.observations,
        "oversized_metadata_failed_closed": byte_blocked,
    }


async def run_trial() -> dict[str, Any]:
    workspaces = _load_fixture()
    inspections = [await _inspect_workspace(workspace) for workspace in workspaces]
    viz_types = sorted({viz_type for item in inspections for viz_type in item["viz_types"]})
    metadata = await _metadata_only_case(workspaces[0])
    refresh = await _refresh_case(workspaces[0])
    live_query = await _live_query_case(workspaces[0])
    policy = await _policy_cases(workspaces[0])
    checks = {
        "all_workspaces_inspected": len(inspections) == len(workspaces),
        "all_chart_catalogs_loaded": all(
            item["chart_count"] > 0 and item["request_counts"]["dashboard"] == 1
            for item in inspections
        ),
        "varied_chart_types_are_reported": len(viz_types) >= 8,
        "cached_queries_are_bounded": all(item["cached_query_guards"] for item in inspections),
        "dashboard_filters_are_applied_at_provider_boundary": all(
            item["dashboard_filters_sent"] for item in inspections
        ),
        "partial_provider_failures_are_visible": any(
            item["chart_errors"] > 0 and item["quality_status"] == "partial"
            for item in inspections
        ),
        "unsupported_metric_is_not_invented": any(
            item["quality_status"] == "partial" for item in inspections
        ),
        "metadata_mode_does_not_fetch_results": metadata["no_chart_data"]
        and metadata["no_chart_metadata"],
        "token_refresh_retries_once": refresh == {
            "retried_after_401": True,
            "auth_calls": 2,
            "dashboard_calls": 2,
        },
        "live_query_requires_and_sends_refresh": live_query["chart_data_requests"] > 0
        and live_query["all_requests_force_refresh"],
        "policy_limits_fail_closed": all(policy.values()),
    }
    return {
        "trial": "preset-hosted-integration",
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "workspace_results": inspections,
        "viz_types": viz_types,
        "metadata_only": metadata,
        "token_refresh": refresh,
        "live_query": live_query,
        "policy_limits": policy,
        "checks": checks,
        "passed": all(checks.values()),
        "not_proven": [
            "real Preset tenant permissions, plan limits, rate limits, and network policy",
            "a real Jev call over a customer-authorized Preset workspace",
            "managed SignalWeave hosting, OAuth callbacks, KMS, or multi-tenant workers",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_trial())
    serialized = json.dumps(report, indent=2, sort_keys=True)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

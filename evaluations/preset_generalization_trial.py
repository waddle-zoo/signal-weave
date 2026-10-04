"""Stress the Preset adapter with generated, unfamiliar dashboard shapes.

The hand-authored Preset fixture proves named examples. This trial is a
separate generalization check: it generates tenant, dashboard, chart, metric,
visualization, result-envelope, and failure values at runtime, then drives the
production Preset client and adapter. No generated identifier or metric name is
known by the adapter under test.

It is still a provider-contract simulation, not a real Preset or Jev run. Its
purpose is to catch fixture overfitting and silent loss across arbitrary saved
chart metadata and common Superset-compatible tabular envelopes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path
from typing import Any

import httpx

from signalweave.hosted import HostedDataPolicy
from signalweave.models import SourceRef
from signalweave.preset_adapter import PresetAdapter, PresetCloudClient

VIZ_TYPES = (
    "line",
    "bar",
    "pie",
    "heatmap_v2",
    "bubble_v2",
    "pivot_table_v2",
    "table",
    "timeseries",
    "area",
    "big_number_total",
    "histogram",
    "vendor_extension",
)
ENVELOPES = ("data", "records", "rows", "values", "columnar")
PARAM_VARIANTS = (
    "metrics",
    "dict_metric",
    "visual_measures",
    "dimension_count",
    "spatial_count",
    "all_columns",
)
CASES = (
    "explicit",
    "dict_metric",
    "implicit_count",
    "ambiguous_numeric",
    "missing_metric",
    "non_numeric_metric",
    "empty",
    "provider_error",
)


def _rows_for(
    case: str, metric: str, *, offset: int, param_variant: str = "metrics"
) -> list[dict[str, Any]]:
    if case == "empty":
        return []
    if case == "missing_metric":
        return [{"period": f"p-{offset}-0", "other_{offset}": 10}]
    if case == "non_numeric_metric":
        return [{"period": f"p-{offset}-0", metric: "not-a-number"}]
    if case == "ambiguous_numeric":
        return [
            {"period": f"p-{offset}-0", "value_a": 10 + offset, "value_b": 20 + offset},
            {"period": f"p-{offset}-1", "value_a": 12 + offset, "value_b": 19 + offset},
        ]
    if case == "implicit_count":
        return [
            {"segment": "one", "count": 10 + offset},
            {"segment": "two", "count": 12 + offset},
        ]
    rows = [
        {"period": f"p-{offset}-0", metric: 10 + offset},
        {"period": f"p-{offset}-1", metric: 12 + offset},
    ]
    if param_variant == "visual_measures":
        for index, row in enumerate(rows):
            row[f"secondary_{offset}"] = 20 + offset + index
    if param_variant == "dimension_count":
        return [
            {"segment": "one", "count": 10 + offset},
            {"segment": "two", "count": 12 + offset},
        ]
    if param_variant == "spatial_count":
        return [
            {"latitude": 40.0 + offset, "longitude": -73.0 - offset, "count": 10 + offset},
            {"latitude": 41.0 + offset, "longitude": -72.0 - offset, "count": 12 + offset},
        ]
    return rows


def _param_variant(case: str, *, workspace_index: int) -> str:
    variants = {
        "explicit": ("metrics", "visual_measures", "all_columns"),
        "dict_metric": ("dict_metric",),
        "implicit_count": ("metrics", "dimension_count", "spatial_count", "all_columns"),
    }.get(case, ("metrics",))
    return variants[workspace_index % len(variants)]


def _params_for(
    case: str, metric: str, *, workspace_index: int, datasource_id: int, offset: int
) -> tuple[dict[str, Any], str]:
    variant = _param_variant(case, workspace_index=workspace_index)
    datasource = f"{datasource_id}__table"
    if case == "explicit" and variant == "visual_measures":
        return (
            {
                "datasource": datasource,
                "x": metric,
                "y": f"secondary_{offset}",
                "granularity_sqla": "period",
            },
            variant,
        )
    if case == "explicit" and variant == "all_columns":
        return (
            {
                "datasource": datasource,
                "all_columns": ["period", metric],
                "granularity_sqla": "period",
            },
            variant,
        )
    if case == "dict_metric":
        return (
            {
                "datasource": datasource,
                "metrics": [{"label": metric}],
                "granularity_sqla": "period",
            },
            variant,
        )
    if case == "implicit_count" and variant == "dimension_count":
        return ({"datasource": datasource, "column": "segment"}, variant)
    if case == "implicit_count" and variant == "spatial_count":
        return (
            {
                "datasource": datasource,
                "spatial": {"latCol": "latitude", "lonCol": "longitude"},
            },
            variant,
        )
    if case == "implicit_count" and variant == "all_columns":
        return (
            {
                "datasource": datasource,
                "all_columns": ["period", "count"],
                "granularity_sqla": "period",
            },
            variant,
        )
    if case == "implicit_count":
        return (
            {"datasource": {"id": datasource_id, "type": "table"}, "groupby": ["segment"]},
            variant,
        )
    return (
        {"datasource": datasource, "metrics": [metric], "granularity_sqla": "period"},
        variant,
    )


def _envelope(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    if kind == "data":
        return [{"data": rows}]
    if kind in {"records", "rows", "values"}:
        return [{"data": {kind: rows}}]
    columns = list(dict.fromkeys(str(key) for row in rows for key in row))
    return [{"data": {"columns": columns, "data": [[row.get(column) for column in columns] for row in rows]}}]


def _workspaces(*, seed: int, workspace_count: int, charts_per_workspace: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    workspaces: list[dict[str, Any]] = []
    for workspace_index in range(workspace_count):
        suffix = rng.randrange(10_000, 99_999)
        workspace_id = f"workspace-{suffix}-{workspace_index}"
        dashboard_id = f"dashboard-{rng.randrange(10_000, 99_999)}-{workspace_index}"
        charts: list[dict[str, Any]] = []
        for chart_index in range(charts_per_workspace):
            case = CASES[(workspace_index * charts_per_workspace + chart_index) % len(CASES)]
            envelope = ENVELOPES[(workspace_index + chart_index) % len(ENVELOPES)]
            viz_type = VIZ_TYPES[rng.randrange(len(VIZ_TYPES))]
            metric = f"metric_{rng.randrange(1000, 9999)}"
            chart_id = f"chart-{rng.randrange(10_000, 99_999)}-{workspace_index}-{chart_index}"
            params, param_variant = _params_for(
                case,
                metric,
                workspace_index=workspace_index,
                datasource_id=workspace_index + 10,
                offset=workspace_index + chart_index,
            )
            if case == "ambiguous_numeric":
                params = {"datasource": f"{workspace_index + 10}__table"}
                param_variant = "baseline"
            rows = _rows_for(
                case,
                metric,
                offset=workspace_index + chart_index,
                param_variant=param_variant,
            )
            charts.append(
                {
                    "id": chart_id,
                    "title": f"Generated {viz_type} {workspace_index}-{chart_index}",
                    "viz_type": viz_type,
                    "params": params,
                    "result": _envelope(rows, envelope),
                    "case": case,
                    "envelope": envelope,
                    "param_variant": param_variant,
                    "http_status": 503 if case == "provider_error" else None,
                }
            )
        workspaces.append(
            {
                "id": workspace_id,
                "tenant_id": f"tenant-{workspace_index}-{suffix}",
                "dashboard_id": dashboard_id,
                "dashboard_title": f"Generated dashboard {workspace_index} {suffix}",
                "available_comparison_windows": ["previous_period"],
                "charts": charts,
            }
        )
    return workspaces


class GeneratedWorkspaceTransport:
    def __init__(self, workspace: dict[str, Any]) -> None:
        self.workspace = workspace
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "params": dict(request.url.params),
            }
        )
        if request.headers.get("authorization") != "Bearer generated-token":
            return httpx.Response(401, json={"message": "unauthorized"})
        if request.url.path == "/api/v1/dashboard/":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "id": self.workspace["dashboard_id"],
                            "dashboard_title": self.workspace["dashboard_title"],
                            "available_comparison_windows": self.workspace.get(
                                "available_comparison_windows", []
                            ),
                        }
                    ],
                    "count": 1,
                },
            )
        if request.url.path == f"/api/v1/dashboard/{self.workspace['dashboard_id']}":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": self.workspace["dashboard_id"],
                        "dashboard_title": self.workspace["dashboard_title"],
                        "available_comparison_windows": self.workspace.get(
                            "available_comparison_windows", []
                        ),
                        "position_json": {
                            chart["id"]: {
                                "type": "CHART",
                                "meta": {"chartId": chart["id"], "sliceName": chart["title"]},
                            }
                            for chart in self.workspace["charts"]
                        },
                    }
                },
            )
        chart_prefix = "/api/v1/chart/"
        if request.url.path.startswith(chart_prefix) and request.url.path.endswith("/data"):
            chart_id = request.url.path.removeprefix(chart_prefix).removesuffix("/data")
            chart = next(chart for chart in self.workspace["charts"] if chart["id"] == chart_id)
            if request.url.params.get("filter_dashboard_id") != str(self.workspace["dashboard_id"]):
                return httpx.Response(400, json={"message": "dashboard context required"})
            if chart["http_status"]:
                return httpx.Response(chart["http_status"], json={"message": "generated outage"})
            return httpx.Response(
                200,
                json={"result": chart["result"], "dashboard_filters": {"filters": []}},
            )
        if request.url.path.startswith(chart_prefix):
            chart_id = request.url.path.removeprefix(chart_prefix)
            chart = next(chart for chart in self.workspace["charts"] if chart["id"] == chart_id)
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": chart["id"],
                        "slice_name": chart["title"],
                        "viz_type": chart["viz_type"],
                        "params": json.dumps(chart["params"]),
                    }
                },
            )
        return httpx.Response(404, json={"message": f"unknown route {request.url.path}"})


def _check_workspace(workspace: dict[str, Any]) -> dict[str, Any]:
    async def inspect() -> dict[str, Any]:
        transport = GeneratedWorkspaceTransport(workspace)
        client = PresetCloudClient(
            f"https://{workspace['id']}.preset.generated",
            access_token="generated-token",
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
                key=f"{workspace['id']}-source",
                adapter=adapter.name,
                resource=f"dashboard:{workspace['dashboard_id']}",
                label=workspace["dashboard_title"],
            )
        )
        charts_by_id = {item["id"]: item for item in workspace["charts"]}
        actual_by_id = {str(item["id"]): item for item in snapshot.metadata["charts"]}
        failures: list[str] = []
        if set(actual_by_id) != set(charts_by_id):
            failures.append("dashboard chart catalog changed during normalization")
        for chart_id, expected in charts_by_id.items():
            actual = actual_by_id.get(chart_id)
            if actual is None:
                continue
            observations = [item for item in snapshot.observations if item.subject_id.startswith(f"{chart_id}:")]
            if expected["case"] in {"explicit", "dict_metric", "implicit_count"} and not observations:
                failures.append(f"{chart_id}: usable generated metric was lost")
            if expected["case"] in {"missing_metric", "non_numeric_metric", "empty", "provider_error"} and observations:
                failures.append(f"{chart_id}: unusable generated metric became an observation")
            if expected["case"] == "ambiguous_numeric" and actual["semantic_status"] != "partial":
                failures.append(f"{chart_id}: ambiguous numeric result was not review-marked")
        data_requests = [item for item in transport.requests if item["path"].endswith("/data")]
        if not data_requests or not all(
            item["params"].get("filter_dashboard_id") == str(workspace["dashboard_id"])
            and item["params"].get("force") == "false"
            for item in data_requests
        ):
            failures.append("dashboard filter scope or cached query guard was missing")
        return {
            "workspace": workspace["id"],
            "tenant_id": workspace["tenant_id"],
            "charts": len(charts_by_id),
            "observations": len(snapshot.observations),
            "envelopes": sorted({item["envelope"] for item in charts_by_id.values()}),
            "viz_types": sorted({item["viz_type"] for item in charts_by_id.values()}),
            "param_variants": sorted({item["param_variant"] for item in charts_by_id.values()}),
            "quality": snapshot.metadata["data_quality"]["status"],
            "failures": failures,
            "passed": not failures,
        }

    return asyncio.run(inspect())


def run_trial(
    *, seed: int = 20260926, workspace_count: int = 24, charts_per_workspace: int = 8
) -> dict[str, Any]:
    if workspace_count < 1 or charts_per_workspace < len(CASES):
        raise ValueError(f"charts_per_workspace must be at least {len(CASES)}")
    workspaces = _workspaces(
        seed=seed,
        workspace_count=workspace_count,
        charts_per_workspace=charts_per_workspace,
    )
    results = [_check_workspace(workspace) for workspace in workspaces]
    failures = [failure for result in results for failure in result["failures"]]
    report = {
        "trial": "preset-generated-generalization",
        "seed": seed,
        "workspace_count": workspace_count,
        "charts_per_workspace": charts_per_workspace,
        "chart_count": workspace_count * charts_per_workspace,
        "case_coverage": sorted({case for workspace in workspaces for case in (item["case"] for item in workspace["charts"])}),
        "envelope_coverage": sorted({envelope for result in results for envelope in result["envelopes"]}),
        "viz_type_coverage": sorted({viz_type for result in results for viz_type in result["viz_types"]}),
        "param_variant_coverage": sorted(
            {variant for result in results for variant in result["param_variants"]}
        ),
        "results": results,
        "failures": failures,
        "passed": not failures,
        "not_proven": [
            "a real Preset tenant's permissions, plans, rate limits, or network path",
            "live Jev semantic accuracy or business usefulness",
            "managed SignalWeave hosting",
        ],
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--workspaces", type=int, default=24)
    parser.add_argument("--charts-per-workspace", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_trial(
        seed=args.seed,
        workspace_count=args.workspaces,
        charts_per_workspace=args.charts_per_workspace,
    )
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    if not report["passed"]:
        raise SystemExit("generated Preset generalization trial failed")


if __name__ == "__main__":
    main()

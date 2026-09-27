"""Independently review the serialized Preset-to-Jev contract trial."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_NOT_PROVEN = {
    "live Jev semantic accuracy or business usefulness",
    "a real Preset tenant's permissions, plan, rate limits, or network path",
    "managed SignalWeave hosting",
}


def review_report(report: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    if report.get("trial") != "preset-jev-contract":
        findings.append("report is not a Preset-to-Jev contract trial")
    if report.get("synthetic_typesafe_transport") is not True:
        findings.append("report did not identify its synthetic TypeSafe transport")
    if report.get("live_jev_semantics_proven") is not False:
        findings.append("report overstated live Jev semantic proof")
    if report.get("real_preset_tenant_proven") is not False:
        findings.append("report overstated real Preset tenant proof")

    workspaces = report.get("workspaces")
    if not isinstance(workspaces, list) or len(workspaces) < 3:
        findings.append("fewer than three Preset workspace shapes were serialized")
        workspaces = []
    tenants = [
        item.get("tenant_id") for item in workspaces if isinstance(item, dict)
    ]
    if len(tenants) != len(workspaces) or any(
        not isinstance(tenant, str) or not tenant for tenant in tenants
    ):
        findings.append("workspace tenant contracts are missing")
    if len(set(tenants)) != len(tenants):
        findings.append("workspace tenant contracts are not unique")

    total_charts = 0
    total_observations = 0
    total_jev_requests = 0
    viz_types: set[str] = set()
    for index, workspace in enumerate(workspaces):
        if not isinstance(workspace, dict):
            findings.append(f"workspace {index} is not an object")
            continue
        chart_count = workspace.get("chart_count")
        snapshot_observations = workspace.get("snapshot_observations")
        if not isinstance(chart_count, int) or chart_count < 1:
            findings.append(f"workspace {index} has no chart coverage")
        else:
            total_charts += chart_count
        if not isinstance(snapshot_observations, int) or snapshot_observations < 1:
            findings.append(f"workspace {index} has no normalized observations")
        else:
            total_observations += snapshot_observations
        if workspace.get("snapshot_contract_tenant") != workspace.get("tenant_id"):
            findings.append(f"workspace {index} lost its tenant contract")

        result = workspace.get("result")
        focused = workspace.get("focused_healthy_slice")
        typed = workspace.get("typed_judge_input")
        provider = workspace.get("provider_requests")
        if not isinstance(result, dict) or result.get("evaluator") != "jev-latest":
            findings.append(f"workspace {index} full result is not Jev-backed")
        if not isinstance(result, dict) or result.get("outcome") != "insufficient_data":
            findings.append(f"workspace {index} full degraded result was not fail-safe")
        if not isinstance(result, dict) or result.get("evidence", 0) < 1 or result.get(
            "observations", 0
        ) < 1:
            findings.append(f"workspace {index} full result lost evidence")
        if isinstance(result, dict) and isinstance(result.get("jev_requests"), int):
            total_jev_requests += result["jev_requests"]
        else:
            findings.append(f"workspace {index} full result has no Jev request count")

        if not isinstance(focused, dict) or focused.get("quality") != "healthy":
            findings.append(f"workspace {index} focused slice is not healthy")
        if not isinstance(focused, dict) or focused.get("outcome") != "notify":
            findings.append(f"workspace {index} focused slice was not actionable")
        if isinstance(focused, dict) and isinstance(focused.get("jev_requests"), int):
            total_jev_requests += focused["jev_requests"]
        else:
            findings.append(f"workspace {index} focused slice has no Jev request count")

        if not isinstance(typed, dict) or typed.get("received_evidence") is not True:
            findings.append(f"workspace {index} did not send evidence to Jev")
        if not isinstance(typed, dict) or typed.get("received_observations") is not True:
            findings.append(f"workspace {index} did not send observations to Jev")
        if isinstance(typed, dict):
            if not isinstance(typed.get("evidence_items"), int) or typed["evidence_items"] < 1:
                findings.append(f"workspace {index} sent no evidence items to Jev")
            if not isinstance(typed.get("observation_items"), int) or typed[
                "observation_items"
            ] < 1:
                findings.append(f"workspace {index} sent no observation items to Jev")
            viz_types.update(str(item) for item in typed.get("jev_source_viz_types", []))

        if not isinstance(provider, dict) or provider.get("dashboard_filter_context") is not True:
            findings.append(f"workspace {index} lost dashboard filter context")
        if not isinstance(provider, dict) or provider.get("focused_chart_scope_sent") is not True:
            findings.append(f"workspace {index} lost focused chart scope")

    if len(viz_types) < 10:
        findings.append("fewer than ten visualization labels reached Jev")
    if report.get("total_charts") != total_charts:
        findings.append("serialized total_charts is not reproducible")
    if report.get("total_snapshot_observations") != total_observations:
        findings.append("serialized observation total is not reproducible")
    if report.get("total_jev_requests") != total_jev_requests:
        findings.append("serialized Jev request total is not reproducible")
    if report.get("total_jev_requests") != len(workspaces) * 4:
        findings.append("the contract request count is not bounded to two cards per workspace")

    missing_non_claims = REQUIRED_NOT_PROVEN - set(report.get("not_proven", []))
    if missing_non_claims:
        findings.append("report omitted non-claims: " + ", ".join(sorted(missing_non_claims)))
    if report.get("passed") is not True:
        findings.append("trial did not report a passing top-level result")

    return {
        "reviewer": "preset-jev-contract-independent",
        "passed": not findings,
        "findings": findings,
        "workspace_count": len(workspaces),
        "visualization_count": len(viz_types),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    review = review_report(json.loads(args.report.read_text(encoding="utf-8")))
    print(json.dumps(review, indent=2, sort_keys=True))
    if not review["passed"]:
        raise SystemExit("independent Preset-to-Jev contract review failed")


if __name__ == "__main__":
    main()

"""Independently review a serialized Preset hosted-connector trial.

The provider trial exercises the production adapter through a synthetic HTTP
transport. This reviewer does not rerun the adapter or trust the producer's
``passed`` flag; it recomputes the important coverage, policy, transport, and
explicit non-claim invariants from the report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_NOT_PROVEN = {
    "real Preset tenant permissions, plan limits, rate limits, and network policy",
    "a real Jev call over a customer-authorized Preset workspace",
    "managed SignalWeave hosting, OAuth callbacks, KMS, or multi-tenant workers",
}


def review_report(report: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    if report.get("trial") != "preset-hosted-integration":
        findings.append("report is not a Preset hosted integration report")

    workspaces = report.get("workspace_results")
    if not isinstance(workspaces, list) or len(workspaces) < 3:
        findings.append("workspace results are missing or do not cover three shapes")
        workspaces = []
    tenants = {
        item.get("tenant_id")
        for item in workspaces
        if isinstance(item, dict)
    }
    if len(tenants) != len(workspaces) or any(not isinstance(item, str) for item in tenants):
        findings.append("workspace tenant identities are missing or duplicated")

    viz_types = set(report.get("viz_types", []))
    if len(viz_types) < 8:
        findings.append("fewer than eight visualization types were covered")
    partial_workspaces = 0
    for index, item in enumerate(workspaces):
        if not isinstance(item, dict):
            findings.append(f"workspace result {index} is not an object")
            continue
        if not isinstance(item.get("chart_count"), int) or item["chart_count"] < 1:
            findings.append(f"workspace result {index} has no chart catalog")
        request_counts = item.get("request_counts")
        if not isinstance(request_counts, dict):
            findings.append(f"workspace result {index} has no request counts")
        else:
            if request_counts.get("dashboard") != 1:
                findings.append(f"workspace result {index} did not load one dashboard catalog")
            if request_counts.get("chart_data", 0) + request_counts.get(
                "dashboard_chart_data", 0
            ) < 1:
                findings.append(f"workspace result {index} did not fetch chart data")
        if item.get("cached_query_guards") is not True:
            findings.append(f"workspace result {index} lost cached-query guards")
        if item.get("dashboard_filters_sent") is not True:
            findings.append(f"workspace result {index} lost dashboard filter scope")
        if item.get("quality_status") == "partial":
            partial_workspaces += 1

    if partial_workspaces < 1:
        findings.append("no provider-degraded workspace remained visible as partial")

    metadata = report.get("metadata_only")
    if not isinstance(metadata, dict) or metadata.get("no_chart_data") is not True or metadata.get(
        "no_chart_metadata"
    ) is not True:
        findings.append("metadata-only policy did not prove zero chart fetches")

    refresh = report.get("token_refresh")
    if refresh != {
        "retried_after_401": True,
        "auth_calls": 2,
        "dashboard_calls": 2,
    }:
        findings.append("token refresh proof is incomplete")

    live_query = report.get("live_query")
    if not isinstance(live_query, dict) or not isinstance(
        live_query.get("chart_data_requests"), int
    ) or live_query["chart_data_requests"] < 1 or live_query.get(
        "all_requests_force_refresh"
    ) is not True:
        findings.append("live-query refresh policy proof is incomplete")

    policy_limits = report.get("policy_limits")
    if not isinstance(policy_limits, dict) or not policy_limits or not all(
        value is True for value in policy_limits.values()
    ):
        findings.append("bounded row/byte policy proof is incomplete")

    missing_non_claims = REQUIRED_NOT_PROVEN - set(report.get("not_proven", []))
    if missing_non_claims:
        findings.append("report omitted non-claims: " + ", ".join(sorted(missing_non_claims)))
    if report.get("passed") is not True:
        findings.append("trial did not report a passing top-level result")

    return {
        "reviewer": "preset-hosted-integration-independent",
        "passed": not findings,
        "findings": findings,
        "workspace_count": len(workspaces),
        "viz_type_count": len(viz_types),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    review = review_report(report)
    print(json.dumps(review, indent=2, sort_keys=True))
    if not review["passed"]:
        raise SystemExit("independent Preset hosted integration review failed")


if __name__ == "__main__":
    main()

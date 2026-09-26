"""Independently review a generated Preset generalization report.

This reviewer intentionally does not execute the adapter or reuse the trial's
per-chart assertions. It checks the report's completeness, coverage, safe
outcomes, and explicit non-claims so a report cannot pass merely because its
top-level ``passed`` field was set to true.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_CASES = {
    "ambiguous_numeric",
    "dict_metric",
    "empty",
    "explicit",
    "implicit_count",
    "missing_metric",
    "non_numeric_metric",
    "provider_error",
}
REQUIRED_ENVELOPES = {"columnar", "data", "records", "rows", "values"}
REQUIRED_NOT_PROVEN = {
    "a real Preset tenant's permissions, plans, rate limits, or network path",
    "live Jev semantic accuracy or business usefulness",
    "managed SignalWeave hosting",
}


def review_report(report: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    workspace_count = report.get("workspace_count")
    charts_per_workspace = report.get("charts_per_workspace")
    chart_count = report.get("chart_count")
    if not isinstance(workspace_count, int) or workspace_count < 1:
        findings.append("workspace_count is missing or invalid")
    if not isinstance(charts_per_workspace, int) or charts_per_workspace < 8:
        findings.append("charts_per_workspace must cover all generated cases")
    if (
        isinstance(workspace_count, int)
        and isinstance(charts_per_workspace, int)
        and chart_count != workspace_count * charts_per_workspace
    ):
        findings.append("chart_count does not equal workspace_count * charts_per_workspace")
    if not REQUIRED_CASES.issubset(set(report.get("case_coverage", []))):
        findings.append("case coverage is incomplete")
    if not REQUIRED_ENVELOPES.issubset(set(report.get("envelope_coverage", []))):
        findings.append("result-envelope coverage is incomplete")
    workspaces = report.get("results")
    if not isinstance(workspaces, list) or len(workspaces) != workspace_count:
        findings.append("workspace result count does not match workspace_count")
    else:
        for index, result in enumerate(workspaces):
            if not isinstance(result, dict):
                findings.append(f"workspace result {index} is not an object")
                continue
            if result.get("charts") != charts_per_workspace:
                findings.append(f"workspace result {index} has an unexpected chart count")
            if result.get("failures"):
                findings.append(f"workspace result {index} contains trial failures")
            if result.get("passed") is not True:
                findings.append(f"workspace result {index} is not marked passed")
            if result.get("quality") != "partial":
                findings.append(f"workspace result {index} did not exercise degraded data")
    missing_non_claims = REQUIRED_NOT_PROVEN - set(report.get("not_proven", []))
    if missing_non_claims:
        findings.append(
            "report omitted required non-claims: " + ", ".join(sorted(missing_non_claims))
        )
    if report.get("passed") is not True:
        findings.append("trial did not report a passing top-level result")
    return {
        "reviewer": "preset-generalization-independent",
        "passed": not findings,
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    review = review_report(report)
    print(json.dumps(review, indent=2, sort_keys=True))
    if not review["passed"]:
        raise SystemExit("independent Preset generalization review failed")


if __name__ == "__main__":
    main()

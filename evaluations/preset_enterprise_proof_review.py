"""Independently review the aggregate no-credit Preset proof-pack report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_CASES = {
    "hosted_connector",
    "credential_and_tenant_boundary",
    "generated_generalization",
    "jev_contract",
    "runtime_shadow",
}

REQUIRED_NOT_PROVEN = {
    "real Preset plan, credentials, permissions, and rate limits",
    "live Jev semantic accuracy or business usefulness",
    "managed SignalWeave hosting",
}


def review_report(report: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    if report.get("trial") != "preset-enterprise-proof-pack":
        findings.append("report is not the Preset enterprise proof pack")

    scope = report.get("proof_scope")
    if not isinstance(scope, dict):
        findings.append("proof scope is missing")
        scope = {}
    if scope.get("synthetic_preset_transport") is not True:
        findings.append("proof scope did not identify synthetic Preset transport")
    if scope.get("synthetic_typesafe_transport") is not True:
        findings.append("proof scope did not identify synthetic TypeSafe transport")
    if scope.get("live_external_provider_requests") != 0:
        findings.append("proof scope overstates or permits live provider requests")
    if scope.get("live_jev_requests") != 0:
        findings.append("proof scope overstates or permits live Jev requests")
    if scope.get("delivery_enabled") is not False:
        findings.append("proof scope did not remain delivery-disabled")

    cases = report.get("cases")
    if not isinstance(cases, list):
        findings.append("proof cases are missing")
        cases = []
    case_names = [case.get("name") for case in cases if isinstance(case, dict)]
    if set(case_names) != REQUIRED_CASES or len(case_names) != len(REQUIRED_CASES):
        findings.append("proof cases do not cover each required trial exactly once")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            findings.append(f"proof case {index} is not an object")
            continue
        producer = case.get("producer")
        reviewer = case.get("independent_review")
        if not isinstance(producer, dict) or producer.get("passed") is not True:
            findings.append(f"proof case {index} producer did not pass")
        if not isinstance(reviewer, dict) or reviewer.get("passed") is not True:
            findings.append(f"proof case {index} independent reviewer did not pass")
        nested_review = reviewer.get("report") if isinstance(reviewer, dict) else None
        if not isinstance(nested_review, dict) or nested_review.get("passed") is not True:
            findings.append(f"proof case {index} omitted a passing reviewer report")

    missing_non_claims = REQUIRED_NOT_PROVEN - set(report.get("not_proven", []))
    if missing_non_claims:
        findings.append("proof pack omitted non-claims: " + ", ".join(sorted(missing_non_claims)))
    if report.get("passed") is not True:
        findings.append("proof pack did not report a passing producer result")

    return {
        "reviewer": "preset-enterprise-proof-pack-independent",
        "passed": not findings,
        "findings": findings,
        "case_count": len(cases),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    review = review_report(report)
    print(json.dumps(review, indent=2, sort_keys=True))
    if not review["passed"]:
        raise SystemExit("independent Preset enterprise proof review failed")


if __name__ == "__main__":
    main()

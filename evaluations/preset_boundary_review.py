"""Independently review the serialized hosted Preset boundary matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_NOT_PROVEN = {
    "real Preset tenant permissions, plan limits, rate limits, and network policy",
    "live Jev semantic accuracy or customer usefulness",
    "managed SignalWeave hosting, OAuth callbacks, KMS, or multi-tenant workers",
}


def review_report(report: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    if report.get("trial") != "preset-boundary-matrix":
        findings.append("report is not a Preset boundary matrix")
    if report.get("provider_requests") != 0 or report.get("typesafe_requests") != 0:
        findings.append("boundary matrix contacted a provider or TypeSafe")

    credentials = report.get("credential_modes")
    required_credentials = {
        "api_token_builds",
        "bearer_builds",
        "oauth_rejected",
        "mixed_credentials_rejected",
        "connection_record_has_no_secret_material",
    }
    if not isinstance(credentials, dict) or set(credentials) != required_credentials:
        findings.append("credential mode coverage is incomplete")
    elif not all(value is True for value in credentials.values()):
        findings.append("a credential boundary check failed")

    tenants = report.get("tenant_boundary")
    required_tenants = {
        "foreign_connection_rejected",
        "foreign_credential_rejected",
        "foreign_list_is_empty",
        "foreign_authorize_skips_provider",
        "connection_routes_are_distinct",
        "visible_tenants",
    }
    if not isinstance(tenants, dict) or not required_tenants.issubset(tenants):
        findings.append("tenant boundary coverage is incomplete")
    else:
        for key in required_tenants - {"visible_tenants"}:
            if tenants.get(key) is not True:
                findings.append(f"tenant boundary check failed: {key}")
        if tenants.get("visible_tenants") != ["tenant-a"]:
            findings.append("tenant listing was not narrowed to the requested tenant")

    policies = report.get("data_policy")
    if not isinstance(policies, dict):
        findings.append("data policy matrix is missing")
    else:
        modes = policies.get("modes")
        checks = policies.get("checks")
        if not isinstance(modes, dict) or set(modes) != {
            "metadata_only",
            "cached_results",
            "live_query",
        }:
            findings.append("data policy modes are incomplete")
        if not isinstance(checks, dict) or not checks or not all(
            value is True for value in checks.values()
        ):
            findings.append("data policy checks are incomplete")
        if isinstance(modes, dict):
            if modes.get("live_query", {}).get("force_refresh") is not True:
                findings.append("live mode does not force refresh")
            if modes.get("cached_results", {}).get("force_refresh") is not False:
                findings.append("cached mode does not stay cached")

    checks = report.get("checks")
    if not isinstance(checks, dict) or not checks or not all(
        value is True for value in checks.values()
    ):
        findings.append("serialized boundary checks are not all true")
    missing = REQUIRED_NOT_PROVEN - set(report.get("not_proven", []))
    if missing:
        findings.append("report omitted non-claims: " + ", ".join(sorted(missing)))
    if report.get("passed") is not True:
        findings.append("trial did not report a passing result")

    return {
        "reviewer": "preset-boundary-matrix-independent",
        "passed": not findings,
        "findings": findings,
        "check_count": len(checks) if isinstance(checks, dict) else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    review = review_report(json.loads(args.report.read_text(encoding="utf-8")))
    print(json.dumps(review, indent=2, sort_keys=True))
    if not review["passed"]:
        raise SystemExit("independent Preset boundary review failed")


if __name__ == "__main__":
    main()

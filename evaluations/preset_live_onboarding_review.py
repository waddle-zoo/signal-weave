"""Independently review a real Preset onboarding/shadow acceptance report.

The live runner is allowed to talk to the customer workspace and Jev. This
reviewer does not rerun the workflow or trust the runner's top-level ``passed``
flag. It recomputes the safety, tenant, provenance, replay, and non-claim
invariants from the serialized report so a partially successful or mutated
report cannot be mistaken for customer acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_NOT_PROVEN = {
    "business usefulness or correctness without operator labels",
    "provider permission coverage beyond the sources selected by this card",
    "production delivery reliability or autonomous side effects",
    "managed SignalWeave hosting",
}


def _is_nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def review_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return an independent acceptance verdict without making provider calls."""

    findings: list[str] = []
    if report.get("trial") != "preset-live-onboarding-shadow":
        findings.append("report is not a Preset live onboarding shadow report")

    adapter = report.get("adapter")
    tenant_id = report.get("tenant_id")
    if not isinstance(adapter, str) or not adapter:
        findings.append("requested Preset adapter is missing")
    if not isinstance(tenant_id, str) or not tenant_id:
        findings.append("runtime tenant identity is missing")

    onboarding = report.get("onboarding")
    if not isinstance(onboarding, dict):
        findings.append("onboarding response is missing")
        onboarding = {}

    approval_requested = report.get("approval_requested") is True
    if not approval_requested:
        if report.get("passed") is True:
            findings.append("a non-approved report claims acceptance")
        if "approval" in report or "evaluation" in report:
            findings.append("a non-approved report contains post-approval artifacts")
        if not isinstance(report.get("next_action"), str) or not report["next_action"]:
            findings.append("non-approved report has no review next action")
    else:
        contract = report.get("provider_checks", {}).get("onboarding_contract")
        if contract != {"approval_required": True, "delivery_disabled": True}:
            findings.append("approval/delivery onboarding contract is not fail-closed")

        approval = report.get("approval")
        if not isinstance(approval, dict) or approval.get("status") != "approved":
            findings.append("approved report has no approved card state")

        evaluation = report.get("evaluation")
        summary = report.get("summary")
        receipt_lookup = report.get("receipt_lookup")
        checks = report.get("provider_checks")
        if not isinstance(evaluation, dict):
            findings.append("approved report has no evaluation")
            evaluation = {}
        if not isinstance(summary, dict):
            findings.append("approved report has no evaluation summary")
            summary = {}
        if not isinstance(receipt_lookup, dict):
            findings.append("approved report has no receipt lookup")
            receipt_lookup = {}
        if not isinstance(checks, dict):
            findings.append("approved report has no provider checks")
            checks = {}

        result = evaluation.get("result")
        receipt = evaluation.get("receipt")
        resources = evaluation.get("resources")
        replay = report.get("replay")
        if not isinstance(result, dict):
            findings.append("evaluation result is missing")
            result = {}
        if not isinstance(receipt, dict):
            findings.append("evaluation receipt is missing")
            receipt = {}
        if not isinstance(resources, list) or not resources:
            findings.append("evaluation has no source resources")
            resources = []
        if not isinstance(replay, dict) or replay.get("replayed") is not True:
            findings.append("evaluation replay was not recorded as idempotent")

        if summary.get("evaluator") != "jev-latest" or result.get("evaluator") != "jev-latest":
            findings.append("evaluation is not explicitly Jev-backed")
        if not _is_nonempty_list(result.get("evidence")):
            findings.append("evaluation has no evidence")
        if not _is_nonempty_list(result.get("observations")):
            findings.append("evaluation has no observations")
        if summary.get("receipt_status") != "delivery_disabled":
            findings.append("summary receipt is not delivery-disabled")
        if receipt.get("status") != "delivery_disabled":
            findings.append("evaluation receipt is not delivery-disabled")
        if summary.get("delivery_enabled") is not False or receipt.get("delivery_enabled") is not False:
            findings.append("evaluation enabled delivery")
        if receipt_lookup.get("status") != "found":
            findings.append("durable receipt lookup did not find the decision")
        if checks.get("replay_made_no_jev_call") is not True:
            findings.append("replay made an additional Jev call")
        if not isinstance(checks.get("jev_requests_for_first_evaluation"), int) or checks[
            "jev_requests_for_first_evaluation"
        ] < 1:
            findings.append("first evaluation has no recorded Jev request")
        if checks.get("all_resources_use_requested_preset_adapter") is not True:
            findings.append("resources are not all from the requested Preset adapter")
        if checks.get("all_resources_match_runtime_tenant") is not True:
            findings.append("resources are not all bound to the runtime tenant")
        for index, resource in enumerate(resources):
            if not isinstance(resource, dict):
                findings.append(f"resource {index} is not an object")
                continue
            if adapter and resource.get("adapter") != adapter:
                findings.append(f"resource {index} uses a different adapter")
            contract = resource.get("contract")
            if not isinstance(contract, dict) or contract.get("tenant_id") != tenant_id:
                findings.append(f"resource {index} is not bound to the runtime tenant")

        missing_non_claims = REQUIRED_NOT_PROVEN - set(report.get("not_proven", []))
        if missing_non_claims:
            findings.append(
                "report omitted non-claims: " + ", ".join(sorted(missing_non_claims))
            )
        if report.get("passed") is not True:
            findings.append("approved report did not claim a passing acceptance")

    return {
        "reviewer": "preset-live-onboarding-independent",
        "passed": not findings,
        "findings": findings,
        "adapter": adapter,
        "tenant_id": tenant_id,
        "approval_requested": approval_requested,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    review = review_report(report)
    print(json.dumps(review, indent=2, sort_keys=True))
    if not review["passed"]:
        raise SystemExit("independent Preset live onboarding review failed")


if __name__ == "__main__":
    main()

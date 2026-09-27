"""Independently review a real Preset onboarding/shadow acceptance report.

The live runner is allowed to talk to the customer workspace and Jev. This
reviewer does not rerun the workflow or trust the runner's top-level ``passed``
flag. It recomputes the safety, tenant, provenance, replay, and non-claim
invariants from the serialized report so a partially successful or mutated
report cannot be mistaken for customer acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
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


def _digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _path_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        path: count - before.get(path, 0)
        for path, count in after.items()
        if count - before.get(path, 0) > 0
    }


def _check_data_policy(findings: list[str], checks: dict[str, Any]) -> None:
    """Recompute the reported Preset query mode and execution bounds."""

    policy = checks.get("data_policy")
    force_refresh = checks.get("provider_force_refresh")
    if not isinstance(policy, dict):
        findings.append("approved shadow is missing Preset data-policy telemetry")
        return
    mode = policy.get("mode")
    if mode == "metadata_only":
        findings.append("metadata-only policy cannot satisfy a chart-data shadow")
    elif mode == "cached_results":
        if force_refresh is not False:
            findings.append("cached-results policy did not prove force=false")
        if policy.get("allow_live_queries") is not False or policy.get("allow_refresh") is not False:
            findings.append("cached-results policy has live execution permissions enabled")
    elif mode == "live_query":
        if force_refresh is not True:
            findings.append("live-query policy did not prove force=true")
        if policy.get("allow_live_queries") is not True or policy.get("allow_refresh") is not True:
            findings.append("live-query policy lacks explicit execution permissions")
    elif mode not in {"cached_results", "live_query"}:
        findings.append(f"unsupported Preset data-policy mode: {mode!r}")
    maximums = {"max_result_rows": 10_000, "max_snapshot_bytes": 10_000_000}
    for key, maximum in maximums.items():
        value = policy.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > maximum
        ):
            findings.append(f"Preset data-policy bound is invalid: {key}")


def _check_unapproved_draft(
    findings: list[str], report: dict[str, Any], onboarding: dict[str, Any]
) -> None:
    """Verify the non-mutating discovery proof before a human approves it.

    A draft is allowed to remain ``needs_human_review``. It is not allowed to
    be an arbitrary JSON envelope that happens to omit post-approval fields:
    the operator must be able to inspect a real card, a tenant-scoped Preset
    transport, and the policy that approval would use.
    """

    if onboarding.get("status") not in {"ready_for_approval", "needs_human_review"}:
        findings.append("unapproved report has an invalid onboarding status")
    if onboarding.get("approval_required") is not True:
        findings.append("unapproved report does not require explicit approval")
    if onboarding.get("delivery_enabled") is not False:
        findings.append("unapproved report enables delivery")
    card = onboarding.get("card")
    if not isinstance(card, dict) or not isinstance(card.get("id"), str) or not card["id"]:
        findings.append("unapproved report has no persisted card draft")
    if not isinstance(card, dict) or not isinstance(card.get("version"), int):
        findings.append("unapproved report card draft has no version")

    checks = report.get("provider_checks")
    if not isinstance(checks, dict):
        findings.append("unapproved report has no provider checks")
        return
    if checks.get("provider_transport_used") is not True:
        findings.append("unapproved report does not prove a Preset provider request")
    if checks.get("provider_credentials_loaded") is not True:
        findings.append("unapproved report does not prove Preset credentials were loaded")
    if checks.get("provider_secrets_absent_from_artifacts") is not True:
        findings.append("unapproved report does not prove provider secrets stayed out of artifacts")
    for key in ("provider_workspace_origin", "provider_auth_origin"):
        if not isinstance(checks.get(key), str) or not checks[key]:
            findings.append(
                f"unapproved report does not identify the Preset {key.removeprefix('provider_')}"
            )
    _check_data_policy(findings, checks)

    request_count = checks.get("provider_requests_for_onboarding")
    if not isinstance(request_count, int) or request_count < 1:
        findings.append("unapproved report has no recorded Preset onboarding request")
    catalog_searches = checks.get("provider_catalog_searches_for_onboarding")
    if not isinstance(catalog_searches, int) or not 1 <= catalog_searches <= 21:
        findings.append(
            "unapproved report has unbounded Preset catalog search fan-out "
            f"({catalog_searches!r}; expected 1-21)"
        )
    before = checks.get("provider_request_paths_before_onboarding")
    after = checks.get("provider_request_paths_after_onboarding")
    delta = checks.get("provider_request_paths_for_onboarding")
    if not all(isinstance(paths, dict) for paths in (before, after, delta)):
        findings.append("unapproved report is missing provider path telemetry")
        return
    if not all(
        isinstance(path, str) and isinstance(count, int) and count >= 0
        for paths in (before, after, delta)
        for path, count in paths.items()
    ):
        findings.append("unapproved report has invalid provider path telemetry")
        return
    if _path_delta(before, after) != delta:
        findings.append("unapproved Preset path telemetry is inconsistent")
    if isinstance(request_count, int) and sum(delta.values()) != request_count:
        findings.append("unapproved Preset request count disagrees with path telemetry")
    if isinstance(catalog_searches, int) and delta.get("/api/v1/dashboard/", 0) != catalog_searches:
        findings.append("unapproved catalog search count disagrees with path telemetry")


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
        _check_unapproved_draft(findings, report, onboarding)
    else:
        approval_basis = report.get("approval_basis")
        onboarding_card = onboarding.get("card")
        if not isinstance(approval_basis, dict):
            findings.append("approved report has no exact-draft approval basis")
        else:
            if approval_basis.get("exact_draft_reused") is not True:
                findings.append("approval was not bound to the exact reviewed draft")
            if not isinstance(approval_basis.get("review_report"), str) or not approval_basis[
                "review_report"
            ]:
                findings.append("approval basis has no reviewed report path")
            if not isinstance(onboarding_card, dict):
                findings.append("approved report onboarding card is missing")
            else:
                if approval_basis.get("card_id") != onboarding_card.get("id"):
                    findings.append("approval basis card ID disagrees with the onboarding draft")
                if approval_basis.get("card_version") != onboarding_card.get("version"):
                    findings.append(
                        "approval basis card version disagrees with the onboarding draft"
                    )
                if approval_basis.get("reviewed_card_digest") != _digest(onboarding_card):
                    findings.append("approval basis digest does not match the onboarding draft")
                if approval_basis.get("stored_card_digest") != approval_basis.get(
                    "reviewed_card_digest"
                ):
                    findings.append("stored card digest differs from the reviewed draft")
        contract = report.get("provider_checks", {}).get("onboarding_contract")
        if contract != {"approval_required": True, "delivery_disabled": True}:
            findings.append("approval/delivery onboarding contract is not fail-closed")
        if onboarding.get("status") != "ready_for_approval":
            findings.append("approved report did not prove onboarding readiness")

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
        if isinstance(approval_basis, dict):
            reviewed_policy = approval_basis.get("reviewed_data_policy")
            reviewed_force_refresh = approval_basis.get("reviewed_provider_force_refresh")
            current_policy = checks.get("data_policy")
            current_force_refresh = checks.get("provider_force_refresh")
            if not isinstance(reviewed_policy, dict):
                findings.append("approval basis has no reviewed data-policy snapshot")
            else:
                if reviewed_policy != current_policy:
                    findings.append("reviewed data-policy snapshot differs from current policy")
                if reviewed_force_refresh != current_force_refresh:
                    findings.append("reviewed force-refresh mode differs from current policy")
                if approval_basis.get("reviewed_data_policy_digest") != _digest(reviewed_policy):
                    findings.append("reviewed data-policy digest is inconsistent")
            if approval_basis.get("current_data_policy_digest") != _digest(current_policy):
                findings.append("current data-policy digest is inconsistent")
            if approval_basis.get("data_policy_unchanged") is not True:
                findings.append("approval did not prove the reviewed data policy was unchanged")
            reviewed_origin = approval_basis.get("reviewed_provider_workspace_origin")
            current_origin = approval_basis.get("current_provider_workspace_origin")
            report_origin = checks.get("provider_workspace_origin")
            if not isinstance(reviewed_origin, str) or not reviewed_origin:
                findings.append("approval basis has no reviewed Preset workspace origin")
            if not isinstance(current_origin, str) or not current_origin:
                findings.append("approval basis has no current Preset workspace origin")
            if current_origin != report_origin:
                findings.append("approval basis origin differs from current provider checks")
            if reviewed_origin != current_origin:
                findings.append("reviewed Preset workspace origin differs from current origin")
            if approval_basis.get("provider_workspace_unchanged") is not True:
                findings.append("approval did not prove the Preset workspace was unchanged")
            reviewed_auth_origin = approval_basis.get("reviewed_provider_auth_origin")
            current_auth_origin = approval_basis.get("current_provider_auth_origin")
            report_auth_origin = checks.get("provider_auth_origin")
            if not isinstance(reviewed_auth_origin, str) or not reviewed_auth_origin:
                findings.append("approval basis has no reviewed Preset auth origin")
            if not isinstance(current_auth_origin, str) or not current_auth_origin:
                findings.append("approval basis has no current Preset auth origin")
            if current_auth_origin != report_auth_origin:
                findings.append("approval basis auth origin differs from current provider checks")
            if reviewed_auth_origin != current_auth_origin:
                findings.append("reviewed Preset auth origin differs from current auth origin")
            if approval_basis.get("provider_auth_origin_unchanged") is not True:
                findings.append("approval did not prove the Preset auth origin was unchanged")

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
        lookup_receipt = receipt_lookup.get("receipt")
        if not isinstance(lookup_receipt, dict):
            findings.append("durable receipt lookup omitted the receipt")
        else:
            for field in ("receipt_id", "idempotency_key", "card_id", "card_version"):
                if lookup_receipt.get(field) != receipt.get(field):
                    findings.append(f"receipt lookup disagrees on {field}")
        if isinstance(replay, dict):
            replay_receipt = replay.get("receipt")
            if not isinstance(replay_receipt, dict) or replay_receipt.get("status") != "replayed":
                findings.append("idempotent replay did not return a replayed receipt")
        if checks.get("replay_made_no_jev_call") is not True:
            findings.append("replay made an additional Jev call")
        if checks.get("replay_made_no_provider_call") is not True:
            findings.append("replay made an additional Preset provider call")
        if checks.get("provider_transport_used") is not True:
            findings.append("approved shadow did not prove a Preset provider request")
        if not isinstance(checks.get("provider_workspace_origin"), str) or not checks[
            "provider_workspace_origin"
        ]:
            findings.append("approved shadow did not identify the Preset workspace")
        if not isinstance(checks.get("provider_auth_origin"), str) or not checks[
            "provider_auth_origin"
        ]:
            findings.append("approved shadow did not identify the Preset auth origin")
        if checks.get("provider_credentials_loaded") is not True:
            findings.append("approved shadow did not prove Preset credentials were loaded")
        if checks.get("provider_secrets_absent_from_artifacts") is not True:
            findings.append("approved shadow did not prove provider secrets stayed out of artifacts")
        approval_provider_requests = checks.get("provider_requests_for_approval")
        if not isinstance(approval_provider_requests, int) or approval_provider_requests < 1:
            findings.append("approval did not record a Preset provider revalidation")
        approval_jev_requests = checks.get("jev_requests_for_approval")
        if not isinstance(approval_jev_requests, int) or approval_jev_requests < 1:
            findings.append("approval did not record a Jev-backed revalidation")
        _check_data_policy(findings, checks)
        if not isinstance(checks.get("provider_requests_for_onboarding"), int) or checks[
            "provider_requests_for_onboarding"
        ] < 1:
            findings.append("approved shadow has no recorded Preset request")
        catalog_searches = checks.get("provider_catalog_searches_for_onboarding")
        if not isinstance(catalog_searches, int) or not 1 <= catalog_searches <= 21:
            findings.append(
                "approved shadow has unbounded Preset catalog search fan-out "
                f"({catalog_searches!r}; expected 1-21)"
            )
        if not isinstance(checks.get("jev_requests_for_first_evaluation"), int) or checks[
            "jev_requests_for_first_evaluation"
        ] < 1:
            findings.append("first evaluation has no recorded Jev request")
        path_values = [
            checks.get("provider_request_paths_before_onboarding"),
            checks.get("provider_request_paths_after_onboarding"),
            checks.get("provider_request_paths_before_approval"),
            checks.get("provider_request_paths_after_approval"),
            checks.get("provider_request_paths_for_approval"),
            checks.get("provider_request_paths_before_first_evaluation"),
            checks.get("provider_request_paths_after_first_evaluation"),
            checks.get("provider_request_paths_for_first_evaluation"),
        ]
        if not all(
            isinstance(paths, dict)
            and all(
                isinstance(path, str) and isinstance(count, int) and count >= 0
                for path, count in paths.items()
            )
            for paths in path_values
        ):
            findings.append("approved shadow is missing non-secret provider path telemetry")
        else:
            onboarding_delta = _path_delta(
                path_values[0], path_values[1]
            )
            approval_delta = _path_delta(path_values[2], path_values[3])
            evaluation_delta = _path_delta(
                path_values[5], path_values[6]
            )
            if sum(onboarding_delta.values()) != checks.get("provider_requests_for_onboarding"):
                findings.append("onboarding provider request count disagrees with path telemetry")
            if onboarding_delta.get("/api/v1/dashboard/", 0) != catalog_searches:
                findings.append("catalog search count disagrees with onboarding path telemetry")
            if path_values[4] != approval_delta:
                findings.append("approval provider path delta is not reproducible")
            if sum(approval_delta.values()) != checks.get("provider_requests_for_approval"):
                findings.append("approval provider request count disagrees with path telemetry")
            if path_values[7] != evaluation_delta:
                findings.append("first-evaluation provider path delta is not reproducible")
            if sum(evaluation_delta.values()) != checks.get(
                "provider_requests_for_first_evaluation"
            ):
                findings.append("first-evaluation provider request count disagrees with path telemetry")
            data_requests = sum(
                count for path, count in evaluation_delta.items() if path.endswith("/data")
            )
            if data_requests != checks.get("provider_data_requests_for_first_evaluation"):
                findings.append("first-evaluation chart-data count disagrees with path telemetry")
            if data_requests < 1:
                findings.append("approved shadow did not fetch Preset chart data")
        if checks.get("all_resources_use_requested_preset_adapter") is not True:
            findings.append("resources are not all from the requested Preset adapter")
        if checks.get("all_resources_match_runtime_tenant") is not True:
            findings.append("resources are not all bound to the runtime tenant")
        dashboard_resources = [
            resource
            for resource in resources
            if isinstance(resource, dict)
            and str(resource.get("resource", "")).startswith("dashboard:")
        ]
        for index, resource in enumerate(dashboard_resources):
            metadata = resource.get("metadata")
            scope = metadata.get("dashboard_scope") if isinstance(metadata, dict) else None
            if not isinstance(scope, dict):
                findings.append(
                    f"dashboard resource {index} is missing dashboard-scope telemetry"
                )
                continue
            if scope.get("dashboard_scoped_requests", 0) < 1:
                findings.append(
                    f"dashboard resource {index} has no dashboard-scoped Preset request"
                )
            if scope.get("chart_query_fallbacks", 0) != 0:
                findings.append(
                    f"dashboard resource {index} used a chart-query fallback"
                )
        if summary.get("evidence_count") != len(result.get("evidence") or []):
            findings.append("summary evidence count disagrees with the result")
        if summary.get("observation_count") != len(result.get("observations") or []):
            findings.append("summary observation count disagrees with the result")
        if summary.get("receipt_id") != receipt.get("receipt_id"):
            findings.append("summary receipt ID disagrees with the evaluation receipt")
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

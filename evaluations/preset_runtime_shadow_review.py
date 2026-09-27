"""Independently review the full Preset runtime shadow report.

The producer trial exercises the runtime and writes a report. This reviewer
does not rerun its assertions or trust the producer's top-level passed flag.
It recomputes the shape, receipt, tenant, secret, replay, and explicit
non-claim invariants from the serialized report so mutation or dropped-record
failures cannot look like a successful enterprise proof.
"""

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


def _contains_secret(value: Any) -> bool:
    encoded = json.dumps(value, sort_keys=True)
    return any(secret in encoded for secret in ("synthetic-secret", "synthetic-name"))


def _data_requests(requests: Any) -> list[dict[str, Any]]:
    if not isinstance(requests, list):
        return []
    return [
        request
        for request in requests
        if isinstance(request, dict) and str(request.get("path", "")).endswith("/data")
    ]


def _runtime_viz_types(artifact: dict[str, Any]) -> list[str]:
    evaluated = artifact.get("evaluated", {})
    resources = evaluated.get("resources", []) if isinstance(evaluated, dict) else []
    return sorted(
        {
            str(chart.get("viz_type") or "unknown")
            for resource in resources
            if isinstance(resource, dict)
            for metadata in [resource.get("metadata")]
            if isinstance(metadata, dict)
            for chart in metadata.get("charts", [])
            if isinstance(chart, dict)
        }
    )


def _cards(report: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for workspace in report.get("workspaces", []):
        if not isinstance(workspace, dict):
            continue
        for key in ("full_dashboard", "focused_chart"):
            card = workspace.get(key)
            if isinstance(card, dict):
                cards.append(card)
    return cards


def review_report(report: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    workspaces = report.get("workspaces")
    workspace_count = report.get("workspace_count")
    named_count = report.get("named_workspace_count")
    generated_count = report.get("generated_workspace_count")

    if not isinstance(workspaces, list) or not workspaces:
        findings.append("workspaces is missing or empty")
        workspaces = []
    if not isinstance(workspace_count, int) or workspace_count != len(workspaces):
        findings.append("workspace_count does not match serialized workspaces")
    if not isinstance(named_count, int) or not isinstance(generated_count, int):
        findings.append("named/generated workspace counts are missing")
    elif named_count < 1 or generated_count < 1 or named_count + generated_count != len(workspaces):
        findings.append("named/generated workspace counts do not partition workspaces")

    tenant_ids = [
        workspace.get("tenant_id") for workspace in workspaces if isinstance(workspace, dict)
    ]
    if len(tenant_ids) != len(workspaces):
        findings.append("a serialized workspace is not an object")
    if any(not isinstance(tenant_id, str) or not tenant_id for tenant_id in tenant_ids):
        findings.append("a workspace is missing tenant identity")
    if len(set(tenant_ids)) != len(tenant_ids):
        findings.append("workspace tenant identities are not unique")

    cards = _cards(report)
    expected_card_count = len(workspaces) * 2
    if report.get("card_count") != expected_card_count or len(cards) != expected_card_count:
        findings.append("card_count does not match the two serialized cards per workspace")

    for index, workspace in enumerate(workspaces):
        trace = workspace.get("provider_request_trace") if isinstance(workspace, dict) else None
        if not isinstance(trace, list):
            findings.append(f"workspace {index} has no raw provider request trace")
            continue
        catalog_count = sum(
            request.get("path") == "/api/v1/dashboard/"
            for request in trace
            if isinstance(request, dict)
        )
        if workspace.get("provider_catalog_search_requests") != catalog_count:
            findings.append(f"workspace {index} catalog search count is not backed by raw requests")

    for index, workspace in enumerate(workspaces):
        if not isinstance(workspace, dict):
            findings.append(f"workspace {index} is not an object")
            continue
        if workspace.get("adapter") != "preset__preset-env":
            findings.append(f"workspace {index} does not use the environment Preset adapter")
        if not isinstance(workspace.get("discovery_matches"), int) or workspace.get(
            "discovery_matches", 0
        ) < 1:
            findings.append(f"workspace {index} has no discovered dashboard")
        catalog_requests = workspace.get("provider_catalog_search_requests")
        if not isinstance(catalog_requests, int) or not 0 < catalog_requests <= 21:
            findings.append(
                f"workspace {index} has unbounded Preset catalog search fan-out: "
                f"{catalog_requests!r} (expected 1-21)"
            )
        for key in ("full_dashboard", "focused_chart"):
            card = workspace.get(key)
            if not isinstance(card, dict):
                findings.append(f"workspace {index} is missing {key}")
                continue
            if card.get("onboarding_status") != "ready_for_approval":
                findings.append(f"workspace {index} {key} was not ready for approval")
            if card.get("approval_status") != "approved":
                findings.append(f"workspace {index} {key} was not approved")
            if card.get("evaluator") != "jev-latest":
                findings.append(f"workspace {index} {key} was not Jev-backed")
            if card.get("evidence_count", 0) < 1:
                findings.append(f"workspace {index} {key} has no evidence")
            if card.get("receipt_status") != "delivery_disabled":
                findings.append(f"workspace {index} {key} has an unsafe receipt status")
            if card.get("delivery_enabled") is not False:
                findings.append(f"workspace {index} {key} enabled delivery")
            if card.get("receipt_lookup_status") != "found":
                findings.append(f"workspace {index} {key} has no durable receipt lookup")
            if card.get("replayed") is not True or card.get("replay_made_no_jev_call") is not True:
                findings.append(f"workspace {index} {key} failed idempotent replay")
            if card.get("provider_filter_context") is not True:
                findings.append(f"workspace {index} {key} lost dashboard filter context")
            if card.get("secrets_absent_from_mcp_artifacts") is not True:
                findings.append(f"workspace {index} {key} leaked a provider secret to MCP")
            if card.get("secrets_absent_from_jev_state") is not True:
                findings.append(f"workspace {index} {key} leaked a provider secret to Jev")
            if not isinstance(card.get("jev_calls_for_card"), int) or card["jev_calls_for_card"] < 1:
                findings.append(f"workspace {index} {key} has no recorded Jev request")

            trace = card.get("jev_trace")
            if not isinstance(trace, list):
                findings.append(f"workspace {index} {key} has no raw Jev trace")
                trace = []
            if len(trace) != card.get("jev_calls_for_card"):
                findings.append(f"workspace {index} {key} Jev count is not backed by its raw trace")
            if card.get("jev_calls_before_replay") != card.get("jev_calls_after_replay"):
                findings.append(f"workspace {index} {key} replay changed the raw Jev call boundary")
            if card.get("replay_made_no_jev_call") is not (
                card.get("jev_calls_before_replay") == card.get("jev_calls_after_replay")
            ):
                findings.append(f"workspace {index} {key} replay summary is not reproducible")

            artifacts = card.get("mcp_artifacts")
            if not isinstance(artifacts, dict):
                findings.append(f"workspace {index} {key} has no raw MCP artifacts")
                artifacts = {}
            elif _contains_secret(artifacts):
                findings.append(f"workspace {index} {key} raw MCP artifacts contain a provider secret")
            if card.get("secrets_absent_from_mcp_artifacts") is not (
                not _contains_secret(artifacts)
            ):
                findings.append(f"workspace {index} {key} MCP secret summary is not reproducible")
            if _contains_secret(trace):
                findings.append(f"workspace {index} {key} raw Jev state contains a provider secret")
            if card.get("secrets_absent_from_jev_state") is not (not _contains_secret(trace)):
                findings.append(f"workspace {index} {key} Jev secret summary is not reproducible")

            result_payload = card.get("result_payload")
            receipt_payload = card.get("receipt_payload")
            receipt_lookup_payload = card.get("receipt_lookup_payload")
            if not isinstance(result_payload, dict):
                findings.append(f"workspace {index} {key} has no raw result payload")
            else:
                for field in ("outcome", "evaluator"):
                    if result_payload.get(field) != card.get(field):
                        findings.append(f"workspace {index} {key} {field} summary is not backed by raw result")
                payload_evidence = result_payload.get("evidence")
                payload_observations = result_payload.get("observations")
                if not isinstance(payload_evidence, list):
                    findings.append(f"workspace {index} {key} raw result evidence is not a list")
                elif len(payload_evidence) != card.get("evidence_count"):
                    findings.append(f"workspace {index} {key} evidence count is not reproducible")
                if not isinstance(payload_observations, list):
                    findings.append(f"workspace {index} {key} raw result observations are not a list")
                elif len(payload_observations) != card.get("observation_count"):
                    findings.append(f"workspace {index} {key} observation count is not reproducible")
            if not isinstance(receipt_payload, dict):
                findings.append(f"workspace {index} {key} has no raw receipt payload")
            else:
                if receipt_payload.get("status") != card.get("receipt_status"):
                    findings.append(f"workspace {index} {key} receipt status is not reproducible")
                if receipt_payload.get("delivery_enabled") != card.get("delivery_enabled"):
                    findings.append(f"workspace {index} {key} receipt delivery flag is not reproducible")
            if not isinstance(receipt_lookup_payload, dict) or receipt_lookup_payload.get("status") != card.get("receipt_lookup_status"):
                findings.append(f"workspace {index} {key} receipt lookup is not reproducible")

            if trace:
                judge_state = trace[-1].get("state") if isinstance(trace[-1], dict) else None
                if not isinstance(judge_state, dict) or "evidence" not in judge_state or "observations" not in judge_state:
                    findings.append(f"workspace {index} {key} raw Jev trace has no typed evidence handoff")
                elif isinstance(result_payload, dict):
                    if result_payload.get("evidence") != judge_state.get("evidence"):
                        findings.append(f"workspace {index} {key} result evidence differs from Jev handoff")
                    if result_payload.get("observations") != judge_state.get("observations"):
                        findings.append(f"workspace {index} {key} result observations differ from Jev handoff")

            raw_requests = card.get("provider_request_trace")
            data_requests = _data_requests(raw_requests)
            raw_filter_context = bool(data_requests) and all(
                request.get("params", {}).get("filter_dashboard_id") for request in data_requests
            )
            if card.get("provider_filter_context") is not raw_filter_context:
                findings.append(f"workspace {index} {key} provider filter summary is not reproducible")
            expected_viz = _runtime_viz_types(artifacts)
            if card.get("viz_types_reached_runtime") != expected_viz:
                findings.append(f"workspace {index} {key} visualization summary is not reproducible")

    full_outcomes = {
        workspace.get("full_dashboard", {}).get("outcome")
        for workspace in workspaces
        if isinstance(workspace, dict) and isinstance(workspace.get("full_dashboard"), dict)
    }
    focused_outcomes = {
        workspace.get("focused_chart", {}).get("outcome")
        for workspace in workspaces
        if isinstance(workspace, dict) and isinstance(workspace.get("focused_chart"), dict)
    }
    if "insufficient_data" not in full_outcomes:
        findings.append("no full dashboard was independently verified as fail-safe")
    if "notify" not in focused_outcomes:
        findings.append("no focused healthy chart was independently verified as actionable")
    harbor = next(
        (
            workspace
            for workspace in workspaces
            if isinstance(workspace, dict) and workspace.get("workspace") == "harbor-bank"
        ),
        None,
    )
    if not isinstance(harbor, dict) or harbor.get("full_dashboard", {}).get("outcome") != "insufficient_data":
        findings.append("the named provider-outage case did not remain fail-safe")

    if len(
        {
            viz
            for workspace in workspaces
            for viz in (
                workspace.get("full_dashboard", {}).get("viz_types_reached_runtime", [])
                if isinstance(workspace, dict)
                and isinstance(workspace.get("full_dashboard"), dict)
                else []
            )
        }
    ) < 10:
        findings.append("runtime did not reach at least ten visualization labels")

    jev_calls = sum(
        card.get("jev_calls_for_card", 0)
        for card in cards
        if isinstance(card.get("jev_calls_for_card"), int)
    )
    if not isinstance(report.get("total_jev_requests"), int) or report["total_jev_requests"] < jev_calls:
        findings.append("total Jev request count is below per-card recorded requests")
    missing_non_claims = REQUIRED_NOT_PROVEN - set(report.get("not_proven", []))
    if missing_non_claims:
        findings.append("report omitted non-claims: " + ", ".join(sorted(missing_non_claims)))
    if report.get("synthetic_preset_transport") is not True or report.get("synthetic_typesafe_transport") is not True:
        findings.append("report did not identify both synthetic transports")
    if report.get("live_jev_semantics_proven") is not False or report.get("real_preset_tenant_proven") is not False:
        findings.append("report overstated live Jev or real-tenant proof")
    if report.get("passed") is not True:
        findings.append("trial did not report a passing top-level result")

    return {
        "reviewer": "preset-runtime-shadow-independent",
        "passed": not findings,
        "findings": findings,
        "workspace_count": len(workspaces),
        "card_count": len(cards),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    review = review_report(report)
    print(json.dumps(review, indent=2, sort_keys=True))
    if not review["passed"]:
        raise SystemExit("independent Preset runtime shadow review failed")


if __name__ == "__main__":
    main()

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


def _viz_types_from_judge_state(state: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(chart.get("viz_type") or "unknown")
            for source in state.get("sources", [])
            if isinstance(source, dict)
            for metadata in [source.get("metadata")]
            if isinstance(metadata, dict)
            for chart in metadata.get("charts", [])
            if isinstance(chart, dict)
        }
    )


def _dashboard_filter_statuses_from_judge_state(state: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(filter_item.get("status"))
            for source in state.get("sources", [])
            if isinstance(source, dict)
            for metadata in [source.get("metadata")]
            if isinstance(metadata, dict)
            for chart in metadata.get("charts", [])
            if isinstance(chart, dict)
            for filter_item in (chart.get("dashboard_filters") or {}).get("filters", [])
            if isinstance(filter_item, dict) and filter_item.get("status")
        }
    )


def _cache_statuses_from_judge_state(state: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(chart.get("cache_status") or "unknown")
            for source in state.get("sources", [])
            if isinstance(source, dict)
            for metadata in [source.get("metadata")]
            if isinstance(metadata, dict)
            for chart in metadata.get("charts", [])
            if isinstance(chart, dict)
        }
    )


def _data_requests(trace: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for phase in ("snapshot", "focused_snapshot", "full", "focused"):
        phase_requests = trace.get(phase, [])
        if not isinstance(phase_requests, list):
            continue
        requests.extend(
            request
            for request in phase_requests
            if isinstance(request, dict)
            and str(request.get("path", "")).rstrip("/").endswith("/data")
        )
    return requests


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
    cache_statuses: set[str] = set()
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
        result_payload = workspace.get("result_payload")
        focused_payload = workspace.get("focused_result_payload")
        call_trace = workspace.get("jev_call_trace")
        provider_trace = workspace.get("provider_request_trace")
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
            cache_statuses.update(str(item) for item in typed.get("cache_statuses", []))

        if not isinstance(call_trace, dict):
            findings.append(f"workspace {index} has no serialized Jev call trace")
            full_calls: list[dict[str, Any]] = []
            focused_calls: list[dict[str, Any]] = []
        else:
            full_calls = call_trace.get("full", [])
            focused_calls = call_trace.get("focused", [])
            if not isinstance(full_calls, list) or not isinstance(focused_calls, list):
                findings.append(f"workspace {index} has malformed Jev call trace")
                full_calls = full_calls if isinstance(full_calls, list) else []
                focused_calls = focused_calls if isinstance(focused_calls, list) else []

        if isinstance(result, dict) and len(full_calls) != result.get("jev_requests"):
            findings.append(f"workspace {index} full Jev count is not backed by its raw trace")
        if isinstance(focused, dict) and len(focused_calls) != focused.get("jev_requests"):
            findings.append(f"workspace {index} focused Jev count is not backed by its raw trace")

        if full_calls:
            full_judge = full_calls[-1]
            state = full_judge.get("state") if isinstance(full_judge, dict) else None
            if not isinstance(state, dict) or "evidence" not in state or "observations" not in state:
                findings.append(f"workspace {index} raw full Jev trace has no typed judge input")
            else:
                raw_evidence = state.get("evidence")
                raw_observations = state.get("observations")
                if not isinstance(raw_evidence, list) or not isinstance(raw_observations, list):
                    findings.append(f"workspace {index} raw full Jev input is missing evidence or observations")
                else:
                    if isinstance(typed, dict) and typed.get("evidence_items") != len(raw_evidence):
                        findings.append(f"workspace {index} evidence count is not derived from raw Jev input")
                    if isinstance(typed, dict) and typed.get("observation_items") != len(raw_observations):
                        findings.append(f"workspace {index} observation count is not derived from raw Jev input")
                    expected_viz = _viz_types_from_judge_state(state)
                    if isinstance(typed, dict) and typed.get("jev_source_viz_types") != expected_viz:
                        findings.append(f"workspace {index} visualization coverage is not derived from raw Jev input")
                    expected_filter_statuses = _dashboard_filter_statuses_from_judge_state(state)
                    if expected_filter_statuses != ["applied", "not_applied"]:
                        findings.append(
                            f"workspace {index} raw Jev input omitted expected dashboard filter statuses"
                        )
                    if isinstance(typed, dict) and typed.get("dashboard_filter_statuses") != expected_filter_statuses:
                        findings.append(
                            f"workspace {index} dashboard filter metadata is not derived from raw Jev input"
                        )
                    expected_cache_statuses = _cache_statuses_from_judge_state(state)
                    if isinstance(typed, dict) and typed.get("cache_statuses") != expected_cache_statuses:
                        findings.append(
                            f"workspace {index} cache provenance is not derived from raw Jev input"
                        )
                    if isinstance(result_payload, dict):
                        if result_payload.get("evidence") != raw_evidence:
                            findings.append(f"workspace {index} result evidence differs from Jev input evidence")
                        if result_payload.get("observations") != raw_observations:
                            findings.append(f"workspace {index} result observations differ from Jev input observations")
                        if result_payload.get("outcome") != result.get("outcome"):
                            findings.append(f"workspace {index} result outcome summary is not backed by raw result")
                        payload_evidence = result_payload.get("evidence")
                        payload_observations = result_payload.get("observations")
                        if not isinstance(payload_evidence, list):
                            findings.append(f"workspace {index} raw result evidence is not a list")
                        elif len(payload_evidence) != result.get("evidence"):
                            findings.append(f"workspace {index} result evidence count is not reproducible")
                        if not isinstance(payload_observations, list):
                            findings.append(f"workspace {index} raw result observations are not a list")
                        elif len(payload_observations) != result.get("observations"):
                            findings.append(f"workspace {index} result observation count is not reproducible")
                    else:
                        findings.append(f"workspace {index} has no serialized full result payload")
        else:
            findings.append(f"workspace {index} has no full Jev call trace")

        if not isinstance(focused_payload, dict):
            findings.append(f"workspace {index} has no serialized focused result payload")
        elif isinstance(focused, dict):
            if focused_payload.get("outcome") != focused.get("outcome"):
                findings.append(f"workspace {index} focused outcome summary is not backed by raw result")
            if focused_payload.get("evaluator") != "jev-latest":
                findings.append(f"workspace {index} focused raw result is not Jev-backed")

        if not isinstance(provider_trace, dict):
            findings.append(f"workspace {index} has no raw provider request trace")
        else:
            requests = _data_requests(provider_trace)
            dashboard_id = str(workspace.get("dashboard_id", ""))
            if not requests or any(
                request.get("params", {}).get("filter_dashboard_id") != dashboard_id
                for request in requests
            ):
                findings.append(f"workspace {index} raw provider requests lost dashboard filter context")
            if isinstance(provider, dict) and provider.get("dashboard_filter_context") is not all(
                request.get("params", {}).get("filter_dashboard_id") == dashboard_id
                for request in requests
            ):
                findings.append(f"workspace {index} dashboard filter summary is not reproducible")

        if not isinstance(provider, dict) or provider.get("dashboard_filter_context") is not True:
            findings.append(f"workspace {index} lost dashboard filter context")
        if not isinstance(provider, dict) or provider.get("focused_chart_scope_sent") is not True:
            findings.append(f"workspace {index} lost focused chart scope")

    if len(viz_types) < 10:
        findings.append("fewer than ten visualization labels reached Jev")
    if not {"cached", "uncached", "mixed"} <= cache_statuses:
        findings.append("raw Jev inputs omitted one or more cache provenance states")
    if report.get("total_charts") != total_charts:
        findings.append("serialized total_charts is not reproducible")
    if report.get("total_snapshot_observations") != total_observations:
        findings.append("serialized observation total is not reproducible")
    if report.get("total_jev_requests") != total_jev_requests:
        findings.append("serialized Jev request total is not reproducible")
    raw_jev_requests = sum(
        len(workspace.get("jev_call_trace", {}).get("full", []))
        + len(workspace.get("jev_call_trace", {}).get("focused", []))
        for workspace in workspaces
        if isinstance(workspace, dict)
        and isinstance(workspace.get("jev_call_trace"), dict)
        and isinstance(workspace["jev_call_trace"].get("full", []), list)
        and isinstance(workspace["jev_call_trace"].get("focused", []), list)
    )
    if report.get("total_jev_requests") != raw_jev_requests:
        findings.append("serialized Jev request total is not backed by raw traces")
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

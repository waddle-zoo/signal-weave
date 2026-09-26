"""Exercise environment bootstrap through the real MCP shadow-card path.

The Preset HTTP transport and TypeSafe SDK transport are synthetic so this
trial spends no live credits. The runtime, hosted connection factory, MCP
tools, SQLite stores, onboarding review, approval gate, Jev adapter, and
delivery-disabled receipt are production implementations.

This is stronger than a direct adapter contract test, but it is still not a
real-tenant or live-Jev semantic-quality acceptance test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import typesafe_sdk

from evaluations.preset_hosted_trial import WorkspaceTransport, _load_fixture
from evaluations.preset_jev_contract_trial import ContractChoice, ContractClient, ContractNoul
from signalweave.mcp_server import create_mcp
from signalweave.runtime import build_runtime


def _tool(server: Any, name: str) -> Any:
    return server._tool_manager.get_tool(name).fn


@contextmanager
def _runtime_environment(values: dict[str, str]) -> Iterator[None]:
    names = {
        "TYPESAFE_MODE",
        "TYPESAFE_API_KEY",
        "TYPESAFE_API_KEY_FILE",
        "PRESET_URL",
        "PRESET_WORKSPACE",
        "PRESET_TENANT_ID",
        "PRESET_API_BASE_URL",
        "PRESET_API_TOKEN_NAME",
        "PRESET_API_TOKEN_NAME_FILE",
        "PRESET_API_TOKEN_SECRET",
        "PRESET_API_TOKEN_SECRET_FILE",
        "PRESET_ACCESS_TOKEN",
        "PRESET_DATA_MODE",
        "PRESET_ALLOW_LIVE_QUERIES",
        "PRESET_ALLOW_REFRESH",
        "SIGNALWEAVE_TENANT_ID",
        "SIGNALWEAVE_PRINCIPAL_ID",
        "SIGNALWEAVE_STORE_BACKEND",
        "SIGNALWEAVE_STORE_PATH",
        "SUPERSET_URL",
        "TRINO_URL",
        "TRINO_CATALOG_FILE",
    }
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        os.environ.update(values)
        yield
    finally:
        for name in names:
            os.environ.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def _selected_source(discovery: dict[str, Any], *, chart_ids: list[str] | None = None) -> list[dict[str, Any]]:
    matches = discovery.get("matches") or []
    if not matches:
        raise RuntimeError("Preset discovery returned no authorized dashboard candidates")
    match = matches[0]
    selected: dict[str, Any] = {
        "ref": match["ref"],
        "label": match["title"],
    }
    if chart_ids is not None:
        selected["parameters"] = {"chart_ids": chart_ids}
    return [selected]


async def _run_workspace(workspace: dict[str, Any], root: Path) -> dict[str, Any]:
    transport = WorkspaceTransport(workspace)
    adapter_name = "preset__preset-env"
    values = {
        "TYPESAFE_MODE": "jev",
        "TYPESAFE_API_KEY": "synthetic-runtime-key",
        "PRESET_URL": f"https://{workspace['id']}.preset.test",
        "PRESET_WORKSPACE": f"{workspace['id']}-workspace",
        "PRESET_TENANT_ID": workspace["tenant_id"],
        "PRESET_API_BASE_URL": "https://api.app.preset.test",
        "PRESET_API_TOKEN_NAME": "synthetic-name",
        "PRESET_API_TOKEN_SECRET": "synthetic-secret",
        "PRESET_DATA_MODE": "cached_results",
        "PRESET_ALLOW_LIVE_QUERIES": "false",
        "PRESET_ALLOW_REFRESH": "false",
        "SIGNALWEAVE_TENANT_ID": workspace["tenant_id"],
        "SIGNALWEAVE_PRINCIPAL_ID": f"{workspace['id']}-monitoring-agent",
        "SIGNALWEAVE_STORE_BACKEND": "sqlite",
        "SIGNALWEAVE_STORE_PATH": str(root / f"{workspace['id']}.db"),
    }
    with _runtime_environment(values):
        runtime = build_runtime(http_transport=httpx.MockTransport(transport))
        server = create_mcp(runtime)
        discover = _tool(server, "discover_insight_sources")
        onboard = _tool(server, "onboard_insight_card")
        approve = _tool(server, "approve_insight_card")
        evaluate = _tool(server, "evaluate_insight_card")
        get_receipt = _tool(server, "get_decision_receipt")

        goal = "Monitor this dashboard for meaningful movement or incomplete evidence."
        why = "Give the owner one bounded evidence bundle for review."
        common = {
            "what_to_watch": goal,
            "why_watch": why,
            "watch_for": [
                "meaningful movement in the dashboard's saved measures",
                "missing or semantically unsupported chart evidence",
            ],
            "questions": [
                "What changed and which saved charts support it?",
                "Is the evidence complete enough for an owner to act?",
            ],
            "decision_guidance": (
                "Notify only when evidence supports owner review; otherwise investigate "
                "or report insufficient data."
            ),
            "adapter": adapter_name,
            "limit": 10,
            "delivery_methods": [
                {
                    "key": "owner-review",
                    "outcome": "notify",
                    "label": "Owner review",
                    "destination": "slack://shadow-review",
                    "instructions": "Send the evidence bundle to the owner workflow.",
                }
            ],
            "retrieval_mode": "fixed",
            "investigation_mode": "none",
        }

        discovery = await discover(goal, adapter=adapter_name, limit=10)
        full_selection = _selected_source(discovery)
        focused_selection = _selected_source(
            discovery, chart_ids=[str(workspace["charts"][0]["id"])]
        )

        async def run_card(label: str, selected_sources: list[dict[str, Any]]) -> dict[str, Any]:
            before_calls = len(ContractClient.calls)
            onboarding = await onboard(
                **common,
                selected_sources=selected_sources,
                title=f"{workspace['dashboard_title']} {label}",
            )
            card_id = onboarding["card"]["id"]
            approved = await approve(card_id, actor=f"{workspace['id']}-owner")
            key = f"runtime-shadow:{workspace['id']}:{label}"
            evaluated = await evaluate(
                card_id,
                idempotency_key=key,
                actor=f"{workspace['id']}-scheduler",
            )
            replay_calls_before = len(ContractClient.calls)
            replay = await evaluate(
                card_id,
                idempotency_key=key,
                actor=f"{workspace['id']}-scheduler",
            )
            receipt_lookup = get_receipt(idempotency_key=key)
            result = evaluated["result"]
            resources = evaluated.get("resources") or []
            viz_types = sorted(
                {
                    str(chart.get("viz_type") or "unknown")
                    for resource in resources
                    for chart in resource.get("metadata", {}).get("charts", [])
                }
            )
            serialized = json.dumps(
                {"onboarding": onboarding, "approved": approved, "evaluated": evaluated},
                sort_keys=True,
            )
            return {
                "onboarding_status": onboarding["status"],
                "approval_status": approved["status"],
                "card_id": card_id,
                "outcome": result["outcome"],
                "evaluator": result["evaluator"],
                "evidence_count": len(result.get("evidence") or []),
                "observation_count": len(result.get("observations") or []),
                "receipt_status": evaluated["receipt"]["status"],
                "delivery_enabled": evaluated["receipt"]["delivery_enabled"],
                "receipt_lookup_status": receipt_lookup["status"],
                "replayed": replay["replayed"],
                "replay_made_no_jev_call": len(ContractClient.calls) == replay_calls_before,
                "jev_calls_for_card": len(ContractClient.calls) - before_calls,
                "viz_types_reached_runtime": viz_types,
                "provider_filter_context": all(
                    request["params"].get("filter_dashboard_id")
                    == str(workspace["dashboard_id"])
                    for request in transport.requests
                    if request["path"].endswith("/data")
                ),
                "secrets_absent_from_mcp_artifacts": "synthetic-secret" not in serialized,
            }

        full = await run_card("full-dashboard", full_selection)
        focused = await run_card("focused-chart", focused_selection)

    return {
        "workspace": workspace["id"],
        "tenant_id": workspace["tenant_id"],
        "adapter": adapter_name,
        "discovery_matches": len(discovery.get("matches") or []),
        "full_dashboard": full,
        "focused_chart": focused,
        "provider_data_requests": sum(
            request["path"].endswith("/data") for request in transport.requests
        ),
    }


async def run_trial(output: Path | None = None) -> dict[str, Any]:
    original_client = typesafe_sdk.AsyncTypeSafeClient
    original_noul = typesafe_sdk.Noul
    original_choice = typesafe_sdk.Choice
    ContractClient.calls = []
    typesafe_sdk.AsyncTypeSafeClient = ContractClient
    typesafe_sdk.Noul = ContractNoul
    typesafe_sdk.Choice = ContractChoice
    try:
        with tempfile.TemporaryDirectory(prefix="signalweave-preset-runtime-") as directory:
            root = Path(directory)
            workspaces = _load_fixture()
            results = [await _run_workspace(workspace, root) for workspace in workspaces]
    finally:
        typesafe_sdk.AsyncTypeSafeClient = original_client
        typesafe_sdk.Noul = original_noul
        typesafe_sdk.Choice = original_choice

    checks = {
        "all_workspaces_bootstrapped_from_environment": all(
            result["adapter"] == "preset__preset-env" and result["discovery_matches"] > 0
            for result in results
        ),
        "onboarding_and_approval_passed": all(
            card["onboarding_status"] == "ready_for_approval"
            and card["approval_status"] == "approved"
            for result in results
            for card in (result["full_dashboard"], result["focused_chart"])
        ),
        "all_shadow_results_are_jev_backed": all(
            card["evaluator"] == "jev-latest"
            for result in results
            for card in (result["full_dashboard"], result["focused_chart"])
        ),
        "full_dashboards_fail_safe_when_fixture_is_partial": all(
            result["full_dashboard"]["outcome"] == "insufficient_data"
            for result in results
        ),
        "focused_healthy_charts_notify": all(
            result["focused_chart"]["outcome"] == "notify"
            for result in results
        ),
        "every_result_has_evidence": all(
            card["evidence_count"] > 0
            for result in results
            for card in (result["full_dashboard"], result["focused_chart"])
        ),
        "receipts_are_delivery_disabled": all(
            card["receipt_status"] == "delivery_disabled"
            and card["delivery_enabled"] is False
            and card["receipt_lookup_status"] == "found"
            for result in results
            for card in (result["full_dashboard"], result["focused_chart"])
        ),
        "idempotent_replay_does_not_call_jev": all(
            card["replayed"] and card["replay_made_no_jev_call"]
            for result in results
            for card in (result["full_dashboard"], result["focused_chart"])
        ),
        "provider_filter_context_preserved": all(
            card["provider_filter_context"]
            for result in results
            for card in (result["full_dashboard"], result["focused_chart"])
        ),
        "secrets_do_not_enter_mcp_artifacts": all(
            card["secrets_absent_from_mcp_artifacts"]
            for result in results
            for card in (result["full_dashboard"], result["focused_chart"])
        ),
        "varied_chart_types_reach_runtime": len(
            {
                viz
                for result in results
                for viz in result["full_dashboard"]["viz_types_reached_runtime"]
            }
        ) >= 10,
    }
    report = {
        "trial": "preset-runtime-shadow",
        "description": "Environment bootstrap through real MCP onboarding, approval, and Jev shadow receipts.",
        "synthetic_preset_transport": True,
        "synthetic_typesafe_transport": True,
        "live_jev_semantics_proven": False,
        "real_preset_tenant_proven": False,
        "checks": checks,
        "passed": all(checks.values()),
        "workspace_count": len(results),
        "card_count": len(results) * 2,
        "total_jev_requests": len(ContractClient.calls),
        "workspaces": results,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/preset-runtime-shadow-trial.json")
    )
    args = parser.parse_args()
    report = asyncio.run(run_trial(args.output))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the real Preset -> onboarding -> Jev shadow path.

This command intentionally requires a customer-authorized Preset environment
and a TypeSafe key. It is not a fixture benchmark and it does not assert an
expected business outcome. It proves that a human can describe a monitoring
goal, review the returned card, explicitly approve it, and obtain a durable
delivery-disabled Jev receipt from the hosted Preset evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from signalweave.mcp_server import create_mcp
from signalweave.preset_adapter import PresetAdapter
from signalweave.runtime import build_runtime


def _tool(server: Any, name: str) -> Any:
    """Use the same registered MCP tool functions as the deployment test suite."""

    return server._tool_manager.get_tool(name).fn


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") or {}
    receipt = payload.get("receipt") or {}
    return {
        "card_id": payload.get("card", {}).get("id"),
        "outcome": result.get("outcome"),
        "confidence": result.get("confidence"),
        "evaluator": result.get("evaluator"),
        "evidence_count": len(result.get("evidence") or []),
        "observation_count": len(result.get("observations") or []),
        "receipt_id": receipt.get("receipt_id"),
        "receipt_status": receipt.get("status"),
        "delivery_enabled": receipt.get("delivery_enabled"),
        "replayed": payload.get("replayed"),
        "resource_count": len(payload.get("resources") or []),
    }


def _resolve_preset_adapter(runtime: Any, requested: str | None) -> str:
    """Resolve a configured Preset route without assuming its connection ID."""

    names = runtime.sources.adapter_names()
    if requested:
        if requested not in names:
            raise RuntimeError(
                f"adapter {requested!r} is not installed; available adapters: "
                + ", ".join(names)
            )
        candidates = [requested]
    else:
        candidates = [
            name
            for name in names
            if isinstance(runtime.sources._get(name), PresetAdapter)
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                "live Preset acceptance requires exactly one configured Preset adapter; "
                "pass --adapter when multiple hosted connections are installed"
            )
    if not isinstance(runtime.sources._get(candidates[0]), PresetAdapter):
        raise RuntimeError(
            f"{candidates[0]!r} is not a hosted Preset adapter; use the Preset environment route"
        )
    return candidates[0]


async def run_trial(
    *,
    goal: str,
    why: str,
    adapter: str | None,
    limit: int,
    destination: str,
    approve: bool,
    output: Path | None = None,
) -> dict[str, Any]:
    if not goal.strip() or not why.strip():
        raise ValueError("goal and why are required")
    runtime = build_runtime()
    if runtime.principal is None:
        raise RuntimeError(
            "the live acceptance trial requires SIGNALWEAVE_TENANT_ID and "
            "SIGNALWEAVE_PRINCIPAL_ID so the Preset workspace is tenant-scoped"
        )
    if getattr(runtime.engine.judger, "name", None) != "jev-latest":
        raise RuntimeError("the live acceptance trial must run with the jev-latest judger")
    adapter = _resolve_preset_adapter(runtime, adapter)
    server = create_mcp(runtime)
    onboarding = await _tool(server, "onboard_insight_card")(
        what_to_watch=goal,
        why_watch=why,
        adapter=adapter,
        limit=limit,
        title=goal[:120],
        delivery_methods=[
            {
                "key": "owner-review",
                "outcome": "notify",
                "label": "Owner review",
                "destination": destination,
                "instructions": "Send the evidence bundle to the existing owner workflow.",
            }
        ],
    )
    report: dict[str, Any] = {
        "trial": "preset-live-onboarding-shadow",
        "adapter": adapter,
        "tenant_id": runtime.principal.tenant_id if runtime.principal else None,
        "onboarding": onboarding,
        "approval_requested": approve,
        "passed": False,
        "not_proven": [
            "business usefulness or correctness without operator labels",
            "provider permission coverage beyond the sources selected by this card",
            "production delivery reliability or autonomous side effects",
            "managed SignalWeave hosting",
        ],
    }
    if not approve:
        report["next_action"] = (
            "review the onboarding response, then rerun with --approve "
            "or make preset-live-trial-approve"
        )
    else:
        card_id = onboarding["card"]["id"]
        onboarding_contract = {
            "approval_required": onboarding.get("approval_required") is True,
            "delivery_disabled": onboarding.get("delivery_enabled") is False,
        }
        if onboarding["status"] != "ready_for_approval":
            report["next_action"] = "resolve the onboarding blockers before approval"
        else:
            approved = await _tool(server, "approve_insight_card")(
                card_id, actor="preset-shadow-owner"
            )
            idempotency_key = f"preset-shadow:{card_id}:v{approved['card']['version']}"
            metrics = getattr(getattr(runtime.engine, "judger", None), "metrics", None)
            jev_requests_before = getattr(metrics, "requests", None)
            evaluation = await _tool(server, "evaluate_insight_card")(
                card_id,
                idempotency_key=idempotency_key,
                actor="preset-shadow-scheduler",
            )
            jev_requests_after_first = getattr(metrics, "requests", None)
            replay = await _tool(server, "evaluate_insight_card")(
                card_id,
                idempotency_key=idempotency_key,
                actor="preset-shadow-scheduler",
            )
            jev_requests_after_replay = getattr(metrics, "requests", None)
            receipt_lookup = _tool(server, "get_decision_receipt")(
                idempotency_key=idempotency_key
            )
            summary = _summary(evaluation)
            resources = evaluation.get("resources") or []
            preset_resources = [item for item in resources if item.get("adapter") == adapter]
            tenant_scoped_resources = bool(resources) and all(
                item.get("contract", {}).get("tenant_id") == runtime.principal.tenant_id
                for item in resources
            )
            replay_made_no_jev_call = (
                jev_requests_before is not None
                and jev_requests_after_first is not None
                and jev_requests_after_replay is not None
                and jev_requests_after_replay == jev_requests_after_first
            )
            report.update(
                {
                    "approval": {
                        "status": approved["status"],
                        "card_version": approved["card"]["version"],
                    },
                    "evaluation": evaluation,
                    "summary": summary,
                    "replay": replay,
                    "receipt_lookup": receipt_lookup,
                    "provider_checks": {
                        "onboarding_contract": onboarding_contract,
                        "preset_resources": len(preset_resources),
                        "all_resources_use_requested_preset_adapter": bool(resources)
                        and len(preset_resources) == len(resources),
                        "all_resources_match_runtime_tenant": tenant_scoped_resources,
                        "replay_made_no_jev_call": replay_made_no_jev_call,
                    },
                    "passed": (
                        approved["status"] == "approved"
                        and all(onboarding_contract.values())
                        and summary["evaluator"] == "jev-latest"
                        and summary["evidence_count"] > 0
                        and bool(preset_resources)
                        and tenant_scoped_resources
                        and summary["receipt_status"] == "delivery_disabled"
                        and summary["delivery_enabled"] is False
                        and replay.get("replayed") is True
                        and receipt_lookup.get("status") == "found"
                        and replay_made_no_jev_call
                    ),
                }
            )
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True, help="What the owner wants monitored")
    parser.add_argument("--why", required=True, help="Why this monitoring matters")
    parser.add_argument(
        "--adapter",
        default=None,
        help="Configured Preset adapter name; auto-detects the sole Preset adapter by default",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--destination", default="slack://replace-me")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly approve when onboarding reports ready_for_approval, then run shadow",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")
    report = asyncio.run(
        run_trial(
            goal=args.goal,
            why=args.why,
            adapter=args.adapter,
            limit=args.limit,
            destination=args.destination,
            approve=args.approve,
            output=args.output,
        )
    )
    if args.approve and not report["passed"]:
        raise SystemExit("live Preset onboarding/shadow acceptance did not pass")


if __name__ == "__main__":
    main()

"""Exercise the scheduled card path against changing Superset-like snapshots.

This is an evaluation harness, not product logic. It uses the same MCP tools,
source registry, engine, Jev judger, approval gate, and webhook that a deployed
caller uses. The source adapter is a deterministic rotating fixture so the
trial can prove no-change, material-change-with-context, and idempotent replay
without requiring a live Superset instance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from evaluations.cases import load_evaluation_cases
from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import ResourceDescriptor, ResourceSnapshot, SourceRef
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import InMemoryDecisionReceiptStore, JsonInsightCardStore
from signalweave.typesafe_adapter import JevJudger, load_api_key


class RotatingSupersetFixture:
    """Return one preloaded dashboard snapshot per distinct scheduled run."""

    name = "superset"

    def __init__(self, snapshots: list[ResourceSnapshot]) -> None:
        self._snapshots = list(snapshots)
        self._descriptor = ResourceDescriptor(
            adapter=self.name,
            resource="dashboard:dash-revenue",
            kind="dashboard",
            title="Revenue Health",
            description="Executive revenue and driver signals.",
            source_url="http://superset.local/superset/dashboard/dash-revenue/",
        )

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [self._descriptor]

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        if not self._snapshots:
            raise RuntimeError("daily trial received more evaluations than snapshots")
        return self._snapshots.pop(0).model_copy(
            update={"source_key": source.key, "resource": source.resource}
        )


def _snapshot_from_case(case: Any, *, no_change: bool) -> ResourceSnapshot:
    snapshot = case.resources[0]
    if not no_change:
        return snapshot

    changes = {
        "weekly_revenue": (990000.0, -1.0),
        "enterprise_churn_rate": (2.02, 1.0),
        "pipeline_value": (2055000.0, 0.24),
        "new_customers": (118.0, -0.84),
    }
    observations = [
        observation.model_copy(
            update={"current": changes[observation.metric][0], "change_pct": changes[observation.metric][1]}
        )
        if observation.metric in changes
        else observation
        for observation in snapshot.observations
    ]
    return snapshot.model_copy(update={"observations": observations})


def _tool(server: Any, name: str) -> Any:
    return server._tool_manager.get_tool(name).fn


def _compact_response(response: dict[str, Any]) -> dict[str, Any]:
    result = response["result"]
    return {
        "outcome": result["outcome"],
        "confidence": result["confidence"],
        "evaluator": result["evaluator"],
        "delivery_methods": [item["key"] for item in result["delivery_methods"]],
        "observations": len(result["observations"]),
        "evidence_subjects": [item["subject_label"] for item in result["evidence"]],
        "watch_results": result["watch_results"],
        "question_results": result["question_results"],
        "rationale": result["rationale"],
        "receipt_status": response["receipt"]["status"],
        "replayed": response["replayed"],
    }


async def run_trial(output: Path) -> dict[str, Any]:
    api_key = load_api_key()
    if not api_key:
        raise RuntimeError("daily Jev trial requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")
    webhook_token = os.getenv("PUSH_WEBHOOK_TOKEN")
    if not webhook_token:
        raise RuntimeError("daily push trial requires PUSH_WEBHOOK_TOKEN")

    case = next(case for case in load_evaluation_cases() if case.id == "revenue_decline")
    trial_card = case.card.model_copy(
        update={
            "what_to_watch": "Revenue and the driver signals that determine whether Revenue Operations should act.",
            "why_watch": (
                "Ignore ordinary week-to-week movement. Notify only when a substantial revenue "
                "decline is corroborated by a sharp enterprise churn increase."
            ),
            "watch_for": [
                "Revenue has a substantial decline from its baseline.",
                "Enterprise churn increases sharply enough to corroborate the revenue decline.",
                "Pipeline value and new-customer volume remain broadly stable context.",
            ],
            "questions": [
                "Is enterprise churn a plausible driver of a substantial revenue decline?",
                "Does the current evidence warrant a Revenue Operations response?",
            ],
        }
    )
    no_change = _snapshot_from_case(case, no_change=True)
    material_change = _snapshot_from_case(case, no_change=False)
    fixture = RotatingSupersetFixture([no_change, material_change])
    registry = SourceRegistry([fixture])
    judger = JevJudger(api_key=api_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    card_store_path = output.with_suffix(".cards.json")
    runtime = Runtime(
        card_store=JsonInsightCardStore(card_store_path),
        sources=registry,
        engine=InsightEngine(judger=judger, registry=registry),
        decision_receipts=InMemoryDecisionReceiptStore(),
    )
    server = create_mcp(runtime)

    source = trial_card.sources[0]
    started = time.perf_counter()
    draft = await _tool(server, "draft_insight_card")(
        title=trial_card.title,
        what_to_watch=trial_card.what_to_watch,
        why_watch=trial_card.why_watch,
        watch_for=trial_card.watch_for,
        questions=trial_card.questions,
        sources=[source.model_dump(mode="json")],
        delivery_methods=[method.model_dump(mode="json") for method in trial_card.delivery_methods],
        card_id="daily-revenue-health",
    )
    card_id = draft["card"]["id"]
    approved = await _tool(server, "approve_insight_card")(card_id, actor="trial-owner")

    app = server.streamable_http_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://trial") as client:
        headers = {"Authorization": f"Bearer {webhook_token}"}
        no_change_response = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "daily:2026-09-17", "actor": "scheduler"},
            headers=headers,
        )
        replay_response = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "daily:2026-09-17", "actor": "scheduler-retry"},
            headers=headers,
        )
        material_response = await client.post(
            "/webhooks/evaluate",
            json={"card_id": card_id, "idempotency_key": "daily:2026-09-18", "actor": "scheduler"},
            headers=headers,
        )

    no_change_payload = no_change_response.json()
    replay_payload = replay_response.json()
    material_payload = material_response.json()
    material_result = material_payload["result"]
    expected_evidence = {"Weekly Revenue", "Enterprise Churn Rate", "Pipeline Value", "New Customers"}
    checks = {
        "draft_then_explicit_approval": draft["status"] == "draft" and approved["status"] == "approved",
        "no_change_is_ignored": no_change_response.status_code == 200 and no_change_payload["result"]["outcome"] == "ignore",
        "replay_is_idempotent": replay_response.status_code == 200 and replay_payload["replayed"] is True,
        "material_change_notifies": material_response.status_code == 200 and material_result["outcome"] == "notify",
        "configured_route_only": [item["key"] for item in material_result["delivery_methods"]] == ["revenue-operations"],
        "why_evidence_is_complete": expected_evidence.issubset(
            {item["subject_label"] for item in material_result["evidence"]}
        ),
        "all_source_observations_reach_jev": len(material_result["observations"]) == 4,
        "jev_is_evaluator": material_result["evaluator"] == "jev-latest",
        "delivery_remains_caller_owned": material_payload["receipt"]["delivery_enabled"] is False,
    }
    report = {
        "trial": "daily-monitor-mcp-webhook",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "card_id": card_id,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "passed": all(checks.values()),
        "checks": checks,
        "runs": {
            "no_change": _compact_response(no_change_payload),
            "replay": _compact_response(replay_payload),
            "material_change": _compact_response(material_payload),
        },
        "jev_requests": judger.metrics.requests,
        "limitations": [
            "The fixture proves the scheduled card contract, not Superset API correctness.",
            "The source bundle is human-confirmed; autonomous source discovery is a separate benchmark.",
            "Delivery is intentionally disabled and remains caller-owned.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(_markdown(report) + "\n", encoding="utf-8")
    if not report["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise AssertionError(f"daily monitor trial failed: {failed}")
    return report


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Daily monitor MCP/webhook trial",
        "",
        f"- Passed: **{report['passed']}**",
        f"- Jev requests: `{report['jev_requests']}`",
        f"- Elapsed: `{report['elapsed_ms']} ms`",
        "",
        "| Check | Result |",
        "| --- | :---: |",
    ]
    lines.extend(f"| {name} | {'pass' if passed else 'FAIL'} |" for name, passed in report["checks"].items())
    lines.extend(["", "| Run | Outcome | Confidence | Replay | Evidence |", "| --- | --- | ---: | :---: | --- |"])
    for name, run in report["runs"].items():
        lines.append(
            f"| `{name}` | `{run['outcome']}` | {run['confidence']:.2f} | "
            f"{run['replayed']} | {', '.join(run['evidence_subjects'])} |"
        )
    lines.extend(["", "## Limits", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/daily-monitor-trial.json"))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_trial(args.output)), indent=2))


if __name__ == "__main__":
    main()

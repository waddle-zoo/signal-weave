"""Prove the Preset-to-Jev production contract without spending credits.

This evaluation intentionally uses the shipped ``PresetAdapter``,
``InsightEngine``, and ``JevJudger``. Only the TypeSafe SDK transport is
synthetic: it returns typed responses with deterministic probabilities so the
trial can exercise serialization, evidence hand-off, typed result parsing, and
the engine's safety gates without calling the live Jev service.

It is not a semantic-quality benchmark for Jev. A real customer acceptance run
still needs a customer-authorized Preset tenant and a live Jev shadow run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import typesafe_sdk

from evaluations.preset_hosted_trial import FIXTURE, WorkspaceTransport, _load_fixture
from signalweave.engine import InsightEngine
from signalweave.hosted import HostedDataPolicy
from signalweave.models import DeliveryMethod, InsightCard, Outcome, SourceRef
from signalweave.preset_adapter import PresetAdapter, PresetCloudClient
from signalweave.typesafe_adapter import JevJudger


class ContractNoul:
    """Constructor-compatible stand-in for a TypeSafe Noul question."""

    def __init__(self, *, instructions: str, criteria: dict[str, Any]) -> None:
        self.instructions = instructions
        self.criteria = criteria


class ContractChoice:
    """Constructor-compatible stand-in for a TypeSafe Choice question."""

    def __init__(self, *, instructions: str, criteria: dict[str, Any]) -> None:
        self.instructions = instructions
        self.criteria = criteria


class ContractResponse:
    usage = SimpleNamespace(input_tokens=0, output_tokens=0)

    def __init__(self, questions: dict[str, Any]) -> None:
        self.nouls: dict[str, Any] = {}
        self.choices: dict[str, Any] = {}
        self.scores: dict[str, Any] = {}
        for key, question in questions.items():
            if isinstance(question, ContractChoice):
                criteria = list(question.criteria)
                selected = "notify" if "notify" in criteria else (criteria[0] if criteria else "")
                probabilities = {
                    option: (0.93 if option == selected else 0.02) for option in criteria
                }
                self.choices[key] = SimpleNamespace(
                    choice=selected,
                    probabilities=probabilities,
                )
            else:
                self.nouls[key] = SimpleNamespace(noul=0.91)


class ContractClient:
    """Record every production Jev call while returning typed shadow answers."""

    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> ContractClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def system_one(self, *, state: dict[str, Any], questions: dict[str, Any]) -> ContractResponse:
        type(self).calls.append(
            {
                "state": state,
                "question_keys": sorted(questions),
                "question_count": len(questions),
            }
        )
        return ContractResponse(questions)


def _card(workspace: dict[str, Any], source: SourceRef) -> InsightCard:
    return InsightCard(
        id=f"preset-contract-{workspace['id']}",
        title=f"{workspace['dashboard_title']} monitoring",
        what_to_watch=(
            "Monitor the dashboard's saved signals for meaningful movement, "
            "missing data, or evidence that needs owner review."
        ),
        why_watch="Provide one bounded evidence bundle instead of separate chart alarms.",
        watch_for=[
            "meaningful movement in the dashboard's saved measures",
            "missing, empty, or semantically unsupported chart evidence",
        ],
        questions=[
            "What changed and which saved charts support the finding?",
            "Is the evidence complete enough for an owner to act?",
        ],
        decision_guidance=(
            "Notify only when the evidence supports owner review; otherwise investigate "
            "or report insufficient data."
        ),
        sources=[source],
        delivery_methods=[
            DeliveryMethod(
                key="owner-review",
                outcome=Outcome.NOTIFY,
                label="Owner review",
                destination="slack://shadow-review",
                instructions="Send the evidence bundle to the dashboard owner for review.",
            )
        ],
    )


async def _run_workspace(workspace: dict[str, Any]) -> dict[str, Any]:
    transport = WorkspaceTransport(workspace)
    client = PresetCloudClient(
        f"https://{workspace['id']}.preset.test",
        api_token_name="synthetic-name",
        api_token_secret="synthetic-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(transport),
    )
    adapter = PresetAdapter(
        client,
        tenant_id=workspace["tenant_id"],
        policy=HostedDataPolicy(max_result_rows=100),
        adapter_name=f"preset__{workspace['id']}",
    )
    source = SourceRef(
        key=f"{workspace['id']}-dashboard",
        adapter=adapter.name,
        resource=f"dashboard:{workspace['dashboard_id']}",
        label=workspace["dashboard_title"],
    )
    snapshot = await adapter.inspect(source)
    judger = JevJudger(api_key="synthetic-contract-key", max_retries=0)
    engine = InsightEngine(judger=judger)
    full_call_start = len(ContractClient.calls)
    run = await engine.evaluate(_card(workspace, source), [snapshot])
    full_judge_call = ContractClient.calls[full_call_start + 1]

    focused_source = SourceRef(
        key=f"{workspace['id']}-focused",
        adapter=adapter.name,
        resource=f"dashboard:{workspace['dashboard_id']}",
        label=f"{workspace['dashboard_title']} first saved chart",
        parameters={"chart_ids": [str(workspace["charts"][0]["id"])]},
    )
    focused_snapshot = await adapter.inspect(focused_source)
    focused_run = await engine.evaluate(
        _card(workspace, focused_source), [focused_snapshot]
    )

    evidence = full_judge_call["state"].get("evidence", [])
    observations = full_judge_call["state"].get("observations", [])
    source_metadata = full_judge_call["state"].get("sources", [{}])[0].get("metadata", {})
    chart_metadata = source_metadata.get("charts", [])
    jev_source_viz_types = sorted(
        {str(chart.get("viz_type") or "unknown") for chart in chart_metadata}
    )
    quality = snapshot.metadata.get("data_quality", {})
    focused_quality = focused_snapshot.metadata.get("data_quality", {})
    return {
        "workspace": workspace["id"],
        "tenant_id": workspace["tenant_id"],
        "chart_count": len(workspace["charts"]),
        "viz_types": sorted({str(chart.get("viz_type") or "unknown") for chart in workspace["charts"]}),
        "snapshot_observations": len(snapshot.observations),
        "snapshot_evidence": len(snapshot.evidence),
        "snapshot_quality": quality.get("status"),
        "snapshot_contract_tenant": snapshot.contract.tenant_id,
        "result": {
            "evaluator": run.result.evaluator,
            "outcome": run.result.outcome.value,
            "confidence": run.result.confidence,
            "evidence": len(run.result.evidence),
            "observations": len(run.result.observations),
            "jev_requests": run.result.telemetry.jev_requests,
        },
        "focused_healthy_slice": {
            "chart_id": str(workspace["charts"][0]["id"]),
            "quality": focused_quality.get("status"),
            "outcome": focused_run.result.outcome.value,
            "confidence": focused_run.result.confidence,
            "observations": len(focused_run.result.observations),
            "jev_requests": focused_run.result.telemetry.jev_requests,
        },
        "typed_judge_input": {
            "received_evidence": bool(evidence),
            "received_observations": bool(observations),
            "evidence_items": len(evidence),
            "observation_items": len(observations),
            "jev_source_viz_types": jev_source_viz_types,
        },
        "provider_requests": {
            "dashboard_chart_data": sum(
                request["path"].endswith("/data") for request in transport.requests
            ),
            "dashboard_filter_context": all(
                request["params"].get("filter_dashboard_id") == str(workspace["dashboard_id"])
                for request in transport.requests
                if request["path"].endswith("/data")
            ),
            "focused_chart_scope_sent": any(
                request["params"].get("filter_dashboard_id") == str(workspace["dashboard_id"])
                and request["path"].endswith("/data")
                for request in transport.requests
            ),
        },
    }


async def run_trial(output: Path | None = None) -> dict[str, Any]:
    """Run all fixture workspaces through Preset -> production Jev wiring."""

    original_client = typesafe_sdk.AsyncTypeSafeClient
    original_noul = typesafe_sdk.Noul
    original_choice = typesafe_sdk.Choice
    ContractClient.calls = []
    typesafe_sdk.AsyncTypeSafeClient = ContractClient
    typesafe_sdk.Noul = ContractNoul
    typesafe_sdk.Choice = ContractChoice
    try:
        workspaces = _load_fixture()
        results = [await _run_workspace(workspace) for workspace in workspaces]
    finally:
        typesafe_sdk.AsyncTypeSafeClient = original_client
        typesafe_sdk.Noul = original_noul
        typesafe_sdk.Choice = original_choice

    expected_calls = len(workspaces) * 4
    checks = {
        "all_fixture_workspaces_evaluated": len(results) == len(workspaces) > 0,
        "tenant_contracts_remain_isolated": len(
            {result["tenant_id"] for result in results}
        )
        == len(results)
        and all(
            result["snapshot_contract_tenant"] == result["tenant_id"]
            for result in results
        ),
        "production_jev_evaluator": all(
            result["result"]["evaluator"] == "jev-latest" for result in results
        ),
        "typed_jev_calls_are_bounded": len(ContractClient.calls) == expected_calls,
        "judge_received_normalized_evidence": all(
            result["typed_judge_input"]["received_evidence"] for result in results
        ),
        "judge_received_normalized_observations": all(
            result["typed_judge_input"]["received_observations"] for result in results
        ),
        "dashboard_filter_context_preserved": all(
            result["provider_requests"]["dashboard_filter_context"] for result in results
        ),
        "partial_quality_remains_visible": any(
            result["snapshot_quality"] == "partial" for result in results
        ),
        "partial_quality_fails_safe": all(
            result["result"]["outcome"] == "insufficient_data"
            for result in results
            if result["snapshot_quality"] == "partial"
        ),
        "varied_visualization_shapes_reached_jev": len(
            {
                viz
                for result in results
                for viz in result["typed_judge_input"]["jev_source_viz_types"]
            }
        ) >= 10,
        "healthy_slices_produce_actionable_outcomes": all(
            result["focused_healthy_slice"]["quality"] == "healthy"
            and result["focused_healthy_slice"]["outcome"] == "notify"
            for result in results
        ),
    }
    report = {
        "trial": "preset-jev-contract",
        "description": "Preset snapshots passed through the production Jev adapter and safety gates.",
        "fixture": str(FIXTURE.relative_to(FIXTURE.parents[1])),
        "synthetic_typesafe_transport": True,
        "live_jev_semantics_proven": False,
        "real_preset_tenant_proven": False,
        "checks": checks,
        "passed": all(checks.values()),
        "workspace_count": len(results),
        "total_charts": sum(result["chart_count"] for result in results),
        "total_snapshot_observations": sum(result["snapshot_observations"] for result in results),
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
        "--output", type=Path, default=Path("artifacts/preset-jev-contract-trial.json")
    )
    args = parser.parse_args()
    report = asyncio.run(run_trial(args.output))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

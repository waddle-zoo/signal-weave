"""Live Jev MCP onboarding probe for typed source-comparison contracts.

This is intentionally small: it checks that a caller can onboard a card over
different adapter identities, see the typed contract in the review packet, and
run a delivery-disabled preview. It is not an enterprise accuracy claim.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from evaluations.bootstrap_agent_trial import (
    Audit,
    MeasuredJev,
    RequestBudget,
    digest,
    write_exclusive,
)
from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import (
    Evidence,
    Observation,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceComparisonContract,
)
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import JsonInsightCardStore

VERSION = "live-contract-onboarding-v1"
REQUESTS_PER_CARD = 4

CASES = [
    {
        "adapter": "looker",
        "resource": "explore:checkout",
        "title": "Checkout conversion explore",
        "metric": "checkout_conversion",
        "key": "checkout-conversion-previous-period",
        "unit": "fraction",
        "baseline": 0.12,
        "current": 0.08,
        "population": "approved checkout population",
    },
    {
        "adapter": "trino",
        "resource": "query:revenue-per-user",
        "title": "Revenue per user query",
        "metric": "net_revenue_per_user",
        "key": "revenue-per-user-previous-period",
        "unit": "USD",
        "baseline": 84.0,
        "current": 63.0,
        "population": "active customers",
    },
    {
        "adapter": "cloudwatch",
        "resource": "widget:documentdb-performance",
        "title": "DocumentDB performance widget",
        "metric": "query_latency_p95",
        "key": "query-latency-p95-previous-period",
        "unit": "ms",
        "baseline": 120.0,
        "current": 240.0,
        "population": "customer database clusters",
    },
]


class ContractAdapter:
    def __init__(self, spec: dict[str, object], *, complete: bool):
        self.name = str(spec["adapter"])
        self.spec = spec
        self.complete = complete

    def _contract(self) -> ResourceContract:
        spec = self.spec
        return ResourceContract(
            available_comparison_windows=["previous_period"],
            required_comparison_keys=[str(spec["key"])],
            comparison_contracts=[
                SourceComparisonContract(
                    key=str(spec["key"]),
                    metric=str(spec["metric"]),
                    definition=(
                        f"{spec['metric']} over the approved {spec['population']} population"
                    ),
                    population=str(spec["population"]),
                    unit=str(spec["unit"]),
                    comparison_window="previous_period",
                    coverage="complete" if self.complete else "partial",
                    comparable=self.complete,
                    detail="Provider export omitted part of the declared population."
                    if not self.complete
                    else "Provider verified the declared population and window.",
                    query_refs=[f"{self.name}:{spec['resource']}"],
                )
            ],
        )

    async def list_resources(self) -> list[ResourceDescriptor]:
        spec = self.spec
        return [
            ResourceDescriptor(
                adapter=self.name,
                resource=str(spec["resource"]),
                kind="metric",
                title=str(spec["title"]),
                description=f"Typed {spec['metric']} comparison from {self.name}.",
                contract=self._contract(),
            )
        ]

    async def inspect(self, source) -> ResourceSnapshot:
        spec = self.spec
        baseline = float(spec["baseline"])
        current = float(spec["current"])
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=str(spec["title"]),
            observations=[
                Observation(
                    source_key=source.key,
                    subject_id=str(spec["resource"]),
                    subject_label=str(spec["title"]),
                    metric=str(spec["metric"]),
                    unit=str(spec["unit"]),
                    current=current,
                    baseline=baseline,
                    change_pct=100 * (current - baseline) / baseline,
                )
            ],
            evidence=[
                Evidence(
                    source_key=source.key,
                    subject_id=str(spec["resource"]),
                    subject_label=str(spec["title"]),
                    statement=(
                        f"{spec['metric']} current and previous-period values were returned "
                        "by the provider adapter."
                    ),
                    values={"metric": spec["metric"], "unit": spec["unit"]},
                )
            ],
            contract=self._contract(),
        )


def implementation_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    paths = [
        *sorted((root / "src").rglob("*.py")),
        Path(__file__),
        root / "evaluations/bootstrap_agent_trial.py",
    ]
    digest_value = hashlib.sha256()
    for path in paths:
        digest_value.update(str(path.relative_to(root)).encode())
        digest_value.update(path.read_bytes())
    return digest_value.hexdigest()


def public_inputs(cases: list[dict[str, object]], quality_arms: list[str]) -> dict[str, object]:
    return {
        "version": VERSION,
        "cases": [
            {key: value for key, value in spec.items() if key not in {"baseline", "current"}}
            for spec in cases
        ],
        "quality_arms": quality_arms,
        "repeats": 1,
        "delivery_enabled": False,
    }


def _expected(complete: bool) -> str:
    return "investigate" if complete else "insufficient_data"


async def run_case(
    spec: dict[str, object], *, complete: bool, judger, home: Path
) -> dict[str, object]:
    adapter = ContractAdapter(spec, complete=complete)
    registry = SourceRegistry([adapter], authorized_tenants=["default"])
    runtime = Runtime(
        card_store=JsonInsightCardStore(home / "cards.json"),
        sources=registry,
        engine=InsightEngine(judger, registry=registry),
        principal=PrincipalContext(principal_id="trial-owner", tenant_id="default"),
    )
    server = create_mcp(runtime)
    onboard = server._tool_manager.get_tool("onboard_insight_card").fn
    simulate = server._tool_manager.get_tool("simulate_insight_card").fn
    route = {
        "key": "owner",
        "outcome": "investigate",
        "label": "Metric owner",
        "destination": "agent://metric-owner",
    }
    data_route = {
        "key": "data",
        "outcome": "insufficient_data",
        "label": "Data owner",
        "destination": "agent://data-owner",
    }
    onboarding = await onboard(
        what_to_watch=f"Monitor {spec['metric']} for a material regression.",
        why_watch="Investigate a material movement with the typed comparison as evidence.",
        watch_for=[f"{spec['metric']} is materially worse than its previous-period baseline."],
        decision_guidance=(
            "Investigate when the material regression is supported. Ignore stable movement. "
            "If the provider contract is incomplete, repair the source before business action."
        ),
        follow_up_guidance="After the evidence review, the caller decides whether a notification is warranted.",
        selected_sources=[{"ref": f"{spec['adapter']}|{spec['resource']}"}],
        comparison_windows=["previous_period"],
        delivery_methods=[route, data_route],
        retrieval_mode="fixed",
        investigation_mode="none",
    )
    candidates = onboarding["review"]["source_candidates"]
    candidate = next(item for item in candidates if item["resource"] == spec["resource"])
    preview = await simulate(onboarding["card"]["id"])
    result = preview["result"]
    expected = _expected(complete)
    expected_action = "retrieve_evidence" if complete else "repair_source"
    expected_status = "pending" if complete else "blocked"
    workflow = result.get("workflow") or {}
    return {
        "adapter": spec["adapter"],
        "resource": spec["resource"],
        "complete_contract": complete,
        "onboarding_status": onboarding["status"],
        "contract_visible": candidate["metadata"]["comparison_contracts"][0]["key"] == spec["key"],
        "card_key_bound": onboarding["card"]["sources"][0]["required_comparison_keys"]
        == [spec["key"]],
        "delivery_disabled": preview["delivery_enabled"] is False,
        "expected_outcome": expected,
        "outcome": result["outcome"],
        "workflow_action": workflow.get("action"),
        "workflow_status": workflow.get("status"),
        "expected_action": expected_action,
        "expected_workflow_status": expected_status,
        "delivery_method_keys": [item["key"] for item in result["delivery_methods"]],
        "expected_delivery_method_keys": ["owner"] if complete else ["data"],
        "confidence": result.get("confidence"),
        "exact": (
            onboarding["status"] in {"ready_for_approval", "needs_human_review"}
            and candidate["metadata"]["comparison_contracts"][0]["key"] == spec["key"]
            and onboarding["card"]["sources"][0]["required_comparison_keys"] == [spec["key"]]
            and preview["delivery_enabled"] is False
            and result["outcome"] == expected
            and workflow.get("action") == expected_action
            and workflow.get("status") == expected_status
            and [item["key"] for item in result["delivery_methods"]]
            == (["owner"] if complete else ["data"])
        ),
    }


async def execute(
    output: Path,
    key_file: Path,
    cases: list[dict[str, object]],
    quality_arms: list[str],
) -> dict[str, object]:
    inputs = public_inputs(cases, quality_arms)
    attempt_cap = len(cases) * len(quality_arms) * REQUESTS_PER_CARD
    output.mkdir(parents=True, exist_ok=False)
    protocol = {
        "version": VERSION,
        "input_digest": digest(inputs),
        "implementation_sha256": implementation_hash(),
        "code": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "attempt_cap": attempt_cap,
        "scope": "Live MCP onboarding and delivery-disabled simulation across three adapter identities",
        "zero_real_deliveries": True,
    }
    write_exclusive(output / "inputs.json", inputs)
    write_exclusive(output / "protocol.json", protocol)
    audit = Audit(output / "trace.jsonl", (key_file.read_text().strip(),))
    budget = RequestBudget(attempt_cap)
    judger = MeasuredJev(key_file.read_text().strip(), budget, audit)
    results = []
    number = 0
    for spec in cases:
        for complete in (quality == "complete" for quality in quality_arms):
            audit.episode = f"attempt-{number:02d}"
            result = await run_case(
                spec, complete=complete, judger=judger, home=output / f"case-{number:02d}"
            )
            result["attempt"] = number
            results.append(result)
            write_exclusive(output / f"attempt-{number:02d}.json", result)
            number += 1
    report = {
        "version": VERSION,
        "attempts": budget.used,
        "errors": 0,
        "resolved_models": sorted(
            {
                event.get("response", {}).get("model", "unknown")
                for event in audit.events
                if event.get("kind") == "api.response"
            }
        ),
        "exact": sum(item["exact"] for item in results),
        "total": len(results),
        "budget_censored": budget.exhausted,
        "zero_real_deliveries": True,
        "results": results,
    }
    write_exclusive(output / "report.json", report)
    return {
        key: report[key]
        for key in ("attempts", "exact", "total", "resolved_models", "budget_censored")
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--case-index", type=int)
    parser.add_argument("--complete-only", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("This probe requires --live so the onboarding and analysis path uses Jev")
    cases = CASES if args.case_index is None else [CASES[args.case_index]]
    quality_arms = ["complete"] if args.complete_only else ["complete", "partial"]
    print(
        json.dumps(asyncio.run(execute(args.output, args.key_file, cases, quality_arms)), indent=2)
    )


if __name__ == "__main__":
    main()

"""Live Jev trial for retrieval-backed explanations in messy catalogs.

The scenario labels are evaluation-only and are never included in the state
sent to Jev. The trial intentionally mixes related sources, same-name tenant
decoys, weakly related sources, stale data, and a no-diagnostic case.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signalweave.engine import InsightEngine
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    InsightCard,
    Observation,
    Outcome,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.retrieval import resource_ref
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = REPO_ROOT / "evaluations" / "data" / "retrieval-explanation-scenarios.json"


def load_scenarios(path: str | Path = DEFAULT_SCENARIOS) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != 1:
        raise ValueError("retrieval explanation scenarios require schema_version=1")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("retrieval explanation scenarios must be a non-empty list")
    return scenarios


def _asset_items(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    anchor = dict(scenario["anchor"])
    anchor["tenant_id"] = "tenant-a"
    items = [anchor]
    for item in scenario.get("diagnostics", []):
        diagnostic = dict(item)
        diagnostic["tenant_id"] = "tenant-a"
        items.append(diagnostic)
    items.extend(dict(item) for item in scenario.get("decoys", []))
    return items


class ScenarioAdapter:
    name = "superset"

    def __init__(self, scenario: dict[str, Any]):
        self.scenario = scenario
        self.items = {
            f"dashboard:{item['resource'].split(':', 1)[1]}": item
            for item in _asset_items(scenario)
        }

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                adapter=self.name,
                resource=resource,
                kind="dashboard",
                title=str(item["title"]),
                description=str(item.get("description", "")),
                metadata={"scenario_domain": self.scenario["domain"]},
                contract=ResourceContract(
                    tenant_id=str(item.get("tenant_id", "tenant-a")),
                    domain=str(self.scenario["domain"]),
                    roles=["primary"] if resource == self.anchor_resource else ["context"],
                ),
            )
            for resource, item in self.items.items()
        ]

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        item = self.items.get(source.resource)
        if item is None:
            raise ValueError(f"unknown scenario resource: {source.resource}")
        observations: list[Observation] = []
        if "metric" in item:
            observations.append(
                Observation(
                    source_key=source.key,
                    subject_id=str(item["metric"]),
                    subject_label=str(item["title"]),
                    metric=str(item["metric"]),
                    current=float(item["current"]),
                    baseline=float(item["baseline"]),
                    change_pct=float(item["change_pct"]),
                    freshness=item.get("freshness"),
                    attributes={"scenario_domain": self.scenario["domain"]},
                )
            )
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=str(item["title"]),
            observations=observations,
            metadata={"scenario_resource": True},
            captured_at=datetime.now(timezone.utc),
        )

    @property
    def anchor_resource(self) -> str:
        return str(self.scenario["anchor"]["resource"])


class ScenarioContext:
    name = "company-context"

    def __init__(self, scenario: dict[str, Any]):
        self.scenario = scenario

    async def get_context(self, card: InsightCard, resources: list[ResourceSnapshot]):
        del card, resources
        facts = [
            ContextFact(
                fact_id=str(fact["fact_id"]),
                subject_ref=str(fact["subject_ref"]),
                relation=str(fact["relation"]),
                object_ref=fact.get("object_ref"),
                statement=str(fact["statement"]),
                provenance=[str(value) for value in fact.get("provenance", [])],
            )
            for fact in self.scenario.get("context_facts", [])
        ]
        return ContextSnapshot(
            provider=self.name,
            version=f"scenario-{self.scenario['id']}-v1",
            facts=facts,
        )


def build_card(scenario: dict[str, Any]) -> InsightCard:
    expected_outcome = Outcome(str(scenario["expected_outcome"]))
    delivery = []
    for key in scenario.get("expected_delivery", []):
        delivery.append(
            DeliveryMethod(
                key=str(key),
                outcome=expected_outcome,
                label=str(key),
                destination=f"test://{key}",
                instructions=f"Route a {expected_outcome.value} result to {key}.",
            )
        )
    anchor = scenario["anchor"]
    source = SourceRef(
        key="anchor",
        adapter="superset",
        resource=str(anchor["resource"]),
        label=str(anchor["title"]),
        required=True,
    )
    return InsightCard(
        id=f"card-{scenario['id']}",
        title=str(scenario["title"]),
        what_to_watch=str(scenario["what_to_watch"]),
        why_watch=str(scenario["why_watch"]),
        watch_for=[str(value) for value in scenario.get("watch_for", [])],
        questions=[str(value) for value in scenario.get("questions", [])],
        sources=[source],
        delivery_methods=delivery,
        retrieval_mode="fixed",
        investigation_mode="bounded",
        max_investigation_sources=2,
        investigation_threshold=0.60,
    )


async def run_scenario(scenario: dict[str, Any], api_key: str) -> dict[str, Any]:
    adapter = ScenarioAdapter(scenario)
    source_registry = SourceRegistry([adapter], authorized_tenants={"tenant-a"})
    engine = InsightEngine(
        judger=JevJudger(api_key=api_key),
        registry=source_registry,
        context_provider=ScenarioContext(scenario),
        investigation_candidate_limit=40,
    )
    started = time.perf_counter()
    run = await engine.evaluate(build_card(scenario))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    investigation = run.result.investigation
    selected = (
        [resource_ref(item.source) for item in investigation.selected]
        if investigation
        else []
    )
    expected_related = set(str(value) for value in scenario.get("expected_related", []))
    selected_set = set(selected)
    selected_authorized = all(
        descriptor.contract.tenant_id == "tenant-a"
        for descriptor in await source_registry.list_resources()
        if resource_ref(descriptor) in selected_set
    )
    return {
        "id": scenario["id"],
        "domain": scenario["domain"],
        "expected_outcome": scenario["expected_outcome"],
        "actual_outcome": run.result.outcome.value,
        "outcome_exact": run.result.outcome.value == scenario["expected_outcome"],
        "expected_delivery": scenario.get("expected_delivery", []),
        "actual_delivery": [method.key for method in run.result.delivery_methods],
        "delivery_exact": [method.key for method in run.result.delivery_methods]
        == scenario.get("expected_delivery", []),
        "expected_related": sorted(expected_related),
        "selected_related": sorted(selected),
        "related_recall": (
            len(expected_related & selected_set) / len(expected_related)
            if expected_related
            else 1.0
        ),
        "selected_authorized": selected_authorized,
        "context_version": run.result.context.version if run.result.context else None,
        "evidence_findings": [
            {
                "subject_id": finding.subject_id,
                "role": finding.role,
                "suggested_role": finding.suggested_role,
                "probability": finding.probability,
            }
            for finding in run.result.evidence_findings
        ],
        "investigation_warnings": investigation.warnings if investigation else [],
        "latency_ms": elapsed_ms,
        "evaluator": run.result.evaluator,
    }


async def run_trial(
    scenarios: list[dict[str, Any]], *, api_key: str, limit: int | None = None
) -> dict[str, Any]:
    rows = []
    for scenario in scenarios[:limit] if limit else scenarios:
        try:
            rows.append(await run_scenario(scenario, api_key))
        except Exception as error:  # noqa: BLE001 - report provider/scenario failures
            rows.append(
                {
                    "id": scenario["id"],
                    "domain": scenario["domain"],
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    completed = [row for row in rows if "error" not in row]
    return {
        "trial": "retrieval-backed-explanation",
        "scenario_count": len(rows),
        "completed": len(completed),
        "outcome_exact": sum(bool(row.get("outcome_exact")) for row in completed),
        "delivery_exact": sum(bool(row.get("delivery_exact")) for row in completed),
        "authorized_selection_clean": sum(
            bool(row.get("selected_authorized")) for row in completed
        ),
        "mean_related_recall": (
            round(sum(float(row["related_recall"]) for row in completed) / len(completed), 3)
            if completed
            else 0.0
        ),
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live Jev retrieval explanation scenarios")
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    parser.add_argument("--output", default="artifacts/retrieval-explanation-trial.json")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    key = load_api_key()
    if not key:
        raise SystemExit("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
    report = asyncio.run(run_trial(load_scenarios(args.scenarios), api_key=key, limit=args.limit))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    for row in report["results"]:
        print(json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    main()

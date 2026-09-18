"""Independent source-discovery benchmark with authorized tenant boundaries.

This evaluation owns its labels and never passes expected refs into the Jev
request. It measures candidate recall and source identity separately from the
downstream insight decision benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalweave.engine import InsightEngine
from signalweave.models import ResourceContract, ResourceDescriptor
from signalweave.onboarding import InsightAuthoringService
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key


@dataclass(frozen=True)
class DiscoveryCase:
    case_id: str
    tenant_id: str
    goal: str
    expected_refs: tuple[str, ...]
    scope: str


class CatalogAdapter:
    def __init__(self, name: str, resources: list[ResourceDescriptor]) -> None:
        self.name = name
        self.resources = resources

    async def list_resources(self) -> list[ResourceDescriptor]:
        return list(self.resources)

    async def inspect(self, source: Any):
        raise AssertionError(f"discovery-only trial must not inspect {source.resource}")


def build_cases(count: int) -> tuple[list[DiscoveryCase], list[ResourceDescriptor]]:
    tenants = ["harbor", "northstar", "orbit", "pine", "quartz", "radian"]
    patterns = [
        (
            "monthly-revenue",
            "What is net revenue per user type by month, and what source should Finance trust?",
            ("trino", "revenue"),
            ("superset", "growth"),
        ),
        (
            "signup-regression",
            "Signups moved off course last week. Which dashboard and incident context explain why?",
            ("superset", "growth"),
            ("incident", "signup"),
        ),
        (
            "stale-dashboard",
            "Is the executive dashboard stale because its refresh pipeline is late?",
            ("superset", "executive"),
            ("airflow", "refresh"),
        ),
        (
            "warehouse-quality",
            "Can we trust the orders metric given table freshness and quality checks?",
            ("trino", "orders"),
            ("table", "quality"),
        ),
    ]
    scopes = [
        "consumer",
        "enterprise",
        "international",
        "partner",
        "self-serve",
        "platform",
        "mid-market",
        "public-sector",
    ]
    cases: list[DiscoveryCase] = []
    resources: list[ResourceDescriptor] = []
    for index in range(count):
        tenant = tenants[index % len(tenants)]
        pattern_key, goal, primary, context = patterns[index % len(patterns)]
        scope = f"{scopes[index % len(scopes)]} cohort-{index + 1:03d}"
        goal = f"{goal} Focus specifically on the {scope} motion."
        case_id = f"{tenant}-{index + 1:03d}-{pattern_key}"
        expected_refs = tuple(
            f"{adapter}|{adapter}:{tenant}-{kind}-{index + 1:03d}"
            for adapter, kind in (primary, context)
        )
        cases.append(DiscoveryCase(case_id, tenant, goal, expected_refs, scope))
        resources.extend(
            _case_resources(tenant, index + 1, pattern_key, primary, context, scope)
        )
    return cases, resources


def _case_resources(
    tenant: str,
    index: int,
    pattern_key: str,
    primary: tuple[str, str],
    context: tuple[str, str],
    scope: str,
) -> list[ResourceDescriptor]:
    resources: list[ResourceDescriptor] = []
    for adapter, kind in (primary, context):
        resource = f"{adapter}:{tenant}-{kind}-{index:03d}"
        resources.append(
            ResourceDescriptor(
                adapter=adapter,
                resource=resource,
                kind="metric_source",
                title=f"{tenant.title()} {kind.replace('-', ' ')} {pattern_key}",
                description=(
                    f"Approved {kind} source for {pattern_key}; tenant {tenant}; "
                    f"supports the question: {pattern_key.replace('-', ' ')}; scope {scope}."
                ),
                contract=ResourceContract(
                    tenant_id=tenant,
                    domain=pattern_key,
                    scope=scope,
                    metric_names=[pattern_key, kind, "business health"],
                    population="company-owned production records",
                    grain="event-level source facts",
                    roles=["primary" if kind in {"revenue", "growth", "executive", "orders"} else "context"],
                ),
            )
        )
    # Same-tenant near duplicates test semantic matching instead of exact title
    # lookup. Foreign copies verify that the registry boundary removes data
    # before Jev sees it.
    for decoy in range(8):
        adapter = "superset" if decoy % 2 else "trino"
        resources.append(
            ResourceDescriptor(
                adapter=adapter,
                resource=f"{adapter}:{tenant}-decoy-{index:03d}-{decoy}",
                kind="metric_source",
                title=f"{tenant.title()} business health context {decoy}",
                description="Related but not sufficient for the requested question.",
                contract=ResourceContract(
                    tenant_id=tenant,
                    domain="unrelated",
                    scope="other segment",
                    metric_names=["business health"],
                    population="different population",
                    grain="weekly summary",
                    roles=["decoy"],
                ),
            )
        )
    foreign_tenant = "foreign" if tenant != "foreign" else "other"
    for adapter, kind in (primary, context):
        resources.append(
            ResourceDescriptor(
                adapter=adapter,
                resource=f"{adapter}:{foreign_tenant}-{kind}-{index:03d}",
                kind="metric_source",
                title=f"{tenant.title()} {kind.replace('-', ' ')} {pattern_key}",
                description="Cross-tenant decoy with intentionally identical wording.",
                contract=ResourceContract(
                    tenant_id=foreign_tenant,
                    domain=pattern_key,
                    scope=scope,
                    metric_names=[pattern_key, kind],
                    population="another company's records",
                    grain="event-level source facts",
                    roles=["primary"],
                ),
            )
        )
    return resources


async def run_trial(count: int, output: Path) -> dict[str, Any]:
    cases, resources = build_cases(count)
    key = load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
    judger = JevJudger(api_key=key)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for case in cases:
        adapters = [
            CatalogAdapter(
                name,
                [resource for resource in resources if resource.adapter == name],
            )
            for name in sorted({resource.adapter for resource in resources})
        ]
        registry = SourceRegistry(adapters, authorized_tenants=[case.tenant_id])
        service = InsightAuthoringService(
            registry=registry,
            engine=InsightEngine(judger=judger, registry=registry),
            max_candidates=48,
        )
        discovery = await service.discover(case.goal, limit=10)
        returned = [match.ref for match in discovery.matches]
        expected = set(case.expected_refs)
        returned_set = set(returned)
        selected_top_n = returned[: len(expected)]
        rows.append(
            {
                "case_id": case.case_id,
                "tenant_id": case.tenant_id,
                "expected_refs": list(case.expected_refs),
                "returned_refs": returned,
                "selected_top_n": selected_top_n,
                "exact_set": set(selected_top_n) == expected,
                "any_expected": bool(returned_set & expected),
                "all_expected_in_top_k": expected.issubset(returned_set),
                "wrong_tenant_returned": any(
                    match.contract.tenant_id != case.tenant_id for match in discovery.matches
                ),
                "candidate_count": discovery.candidate_count,
                "truncated": discovery.truncated,
                "warnings": discovery.warnings,
            }
        )
    elapsed = time.perf_counter() - started
    report = {
        "evaluator": judger.name,
        "cases": len(rows),
        "resources_before_auth_filter": len(resources),
        "exact_set": sum(row["exact_set"] for row in rows),
        "any_expected": sum(row["any_expected"] for row in rows),
        "all_expected_in_top_k": sum(row["all_expected_in_top_k"] for row in rows),
        "wrong_tenant_returned": sum(row["wrong_tenant_returned"] for row in rows),
        "requests": judger.metrics.requests,
        "input_tokens": judger.metrics.input_tokens,
        "output_tokens": judger.metrics.output_tokens,
        "elapsed_seconds": round(elapsed, 3),
        "independent_labels": True,
        "expected_refs_sent_to_jev": False,
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    markdown = output.with_suffix(".md")
    markdown.write_text(
        "# SignalWeave discovery trial\n\n"
        f"Evaluator: `{judger.name}`; cases: **{len(rows)}**; resources before auth filtering: **{len(resources)}**.\n\n"
        "| Metric | Result |\n| --- | ---: |\n"
        f"| Exact returned set | {report['exact_set']} / {len(rows)} |\n"
        f"| Any expected source in top 10 | {report['any_expected']} / {len(rows)} |\n"
        f"| All expected sources in top 10 | {report['all_expected_in_top_k']} / {len(rows)} |\n"
        f"| Wrong-tenant sources returned | {report['wrong_tenant_returned']} / {len(rows)} |\n\n"
        "Expected references were generated independently and were not sent to Jev. "
        "The registry applied the configured tenant authorization boundary before ranking.\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=24)
    parser.add_argument("--output", type=Path, default=Path("artifacts/discovery-trial.json"))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_trial(args.cases, args.output)), indent=2))


if __name__ == "__main__":
    main()

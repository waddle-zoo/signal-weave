"""Live Jev metric-selection and deterministic SQL compilation trial."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalweave.models import MetricDefinition, ResourceContract, ResourceDescriptor, SourceRef
from signalweave.query_planner import QueryWindow, compile_query, plan_query
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key


@dataclass(frozen=True)
class QueryCase:
    case_id: str
    tenant_id: str
    question: str
    metric_key: str
    dimensions: tuple[str, ...]
    grain: str
    source_resource: str


class CatalogAdapter:
    name = "trino"

    def __init__(self, resources: list[ResourceDescriptor]) -> None:
        self.resources = resources

    async def list_resources(self) -> list[ResourceDescriptor]:
        return list(self.resources)

    async def inspect(self, source: Any):
        raise AssertionError(f"query trial should not execute {source.resource}")


def build_cases(count: int) -> tuple[list[QueryCase], list[ResourceDescriptor]]:
    tenants = ["harbor", "northstar", "orbit", "pine", "quartz", "radian"]
    templates = [
        (
            "net_revenue",
            "What is net revenue per user type by month for cohort {cohort}?",
            ("user_type",),
            "month",
            [
                ("net_revenue", "Net revenue after refunds", "sum", "net_revenue"),
                ("gross_revenue", "Gross billed revenue", "sum", "gross_revenue"),
                ("refund_amount", "Refund amount", "sum", "refund_amount"),
            ],
        ),
        (
            "signup_count",
            "How many new signups occurred by acquisition channel per week for cohort {cohort}?",
            ("acquisition_channel",),
            "week",
            [
                ("signup_count", "New account signups", "count", None),
                ("login_count", "Successful logins", "count", None),
                ("invite_count", "Invitations sent", "count", None),
            ],
        ),
        (
            "activation_rate",
            "What is activation rate by plan tier per month for cohort {cohort}?",
            ("plan_tier",),
            "month",
            [
                ("activation_rate", "Activated accounts divided by eligible accounts", "avg", "activation_rate"),
                ("retention_rate", "Retained accounts divided by eligible accounts", "avg", "retention_rate"),
                ("conversion_rate", "Checkout conversion rate", "avg", "conversion_rate"),
            ],
        ),
        (
            "order_count",
            "What is completed order count by region per day for cohort {cohort}?",
            ("region",),
            "day",
            [
                ("order_count", "Completed customer orders", "count", None),
                ("item_count", "Order line items", "count", None),
                ("shipment_count", "Shipments created", "count", None),
            ],
        ),
    ]
    cases: list[QueryCase] = []
    resources: list[ResourceDescriptor] = []
    for index in range(count):
        tenant = tenants[index % len(tenants)]
        metric_key, question, dimensions, grain, definitions = templates[index % len(templates)]
        cohort = f"cohort-{index + 1:03d}"
        source_resource = f"query:{tenant}-metrics-{index + 1:03d}"
        cases.append(
            QueryCase(
                case_id=f"{tenant}-{index + 1:03d}",
                tenant_id=tenant,
                question=question.format(cohort=cohort),
                metric_key=metric_key,
                dimensions=dimensions,
                grain=grain,
                source_resource=source_resource,
            )
        )
        metric_definitions = [
            MetricDefinition(
                key=key,
                label=label,
                description=f"Approved {label.lower()} definition for {cohort}.",
                relation=f"lakehouse.{tenant}.events_{index + 1:03d}",
                aggregation=aggregation,
                measure_column=measure_column,
                time_column="event_time",
                supported_grains=[grain],
                dimensions={dimensions[0]: dimensions[0], "region": "region", "plan_tier": "plan_tier"},
                partition_column="event_date",
                aliases=[label.lower()],
                population=f"production events for {cohort}",
                grain="one row per event",
            )
            for key, label, aggregation, measure_column in definitions
        ]
        resources.append(
            ResourceDescriptor(
                adapter="trino",
                resource=source_resource,
                kind="metric_catalog",
                title=f"{tenant.title()} approved metrics {cohort}",
                description=f"Metric catalog for the {cohort} business scope.",
                contract=ResourceContract(
                    tenant_id=tenant,
                    domain="analytics",
                    scope=cohort,
                    population=f"production events for {cohort}",
                    grain="one row per event",
                    metric_definitions=metric_definitions,
                    roles=["metric_catalog"],
                ),
            )
        )
    return cases, resources


async def run_trial(count: int, output: Path) -> dict[str, Any]:
    cases, resources = build_cases(count)
    key = load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
    judger = JevJudger(api_key=key)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for case in cases:
        resource = next(item for item in resources if item.resource == case.source_resource)
        registry = SourceRegistry(
            [CatalogAdapter([resource])], authorized_tenants=[case.tenant_id]
        )
        source = SourceRef(
            key="metric-catalog",
            adapter="trino",
            resource=case.source_resource,
            label=resource.title,
        )
        plan = await plan_query(
            registry=registry,
            selector=judger,
            goal=case.question,
            source_refs=[source],
            requested_dimensions=list(case.dimensions),
            requested_time_grain=case.grain,
        )
        compiled = compile_query(
            plan,
            QueryWindow("2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),
        )
        rows.append(
            {
                "case_id": case.case_id,
                "expected_metric_key": case.metric_key,
                "selected_metric_key": plan.metric_key,
                "metric_exact": plan.metric_key == case.metric_key,
                "dimensions_exact": tuple(plan.dimensions) == case.dimensions,
                "grain_exact": plan.time_grain == case.grain,
                "partition_bounded": "event_date" in compiled.scan_guard,
                "select_only": compiled.sql.lstrip().upper().startswith("SELECT"),
                "semicolon_free": ";" not in compiled.sql,
                "query_fingerprint": compiled.fingerprint,
            }
        )
    elapsed = time.perf_counter() - started
    report = {
        "evaluator": judger.name,
        "cases": len(rows),
        "metric_exact": sum(row["metric_exact"] for row in rows),
        "dimensions_exact": sum(row["dimensions_exact"] for row in rows),
        "grain_exact": sum(row["grain_exact"] for row in rows),
        "partition_bounded": sum(row["partition_bounded"] for row in rows),
        "select_only": sum(row["select_only"] for row in rows),
        "semicolon_free": sum(row["semicolon_free"] for row in rows),
        "requests": judger.metrics.requests,
        "input_tokens": judger.metrics.input_tokens,
        "output_tokens": judger.metrics.output_tokens,
        "elapsed_seconds": round(elapsed, 3),
        "independent_labels": True,
        "expected_metric_sent_to_jev": False,
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    output.with_suffix(".md").write_text(
        "# SignalWeave metric-plan trial\n\n"
        f"Evaluator: `{judger.name}`; cases: **{len(rows)}**.\n\n"
        "| Metric | Result |\n| --- | ---: |\n"
        f"| Correct metric definition | {report['metric_exact']} / {len(rows)} |\n"
        f"| Correct dimensions | {report['dimensions_exact']} / {len(rows)} |\n"
        f"| Correct time grain | {report['grain_exact']} / {len(rows)} |\n"
        f"| Partition-bounded | {report['partition_bounded']} / {len(rows)} |\n"
        f"| SELECT-only | {report['select_only']} / {len(rows)} |\n"
        f"| Semicolon-free | {report['semicolon_free']} / {len(rows)} |\n\n"
        "The expected metric labels were held out from the Jev request. SQL was generated only from approved catalog definitions.\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=24)
    parser.add_argument("--output", type=Path, default=Path("artifacts/query-trial.json"))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_trial(args.cases, args.output)), indent=2))


if __name__ == "__main__":
    main()

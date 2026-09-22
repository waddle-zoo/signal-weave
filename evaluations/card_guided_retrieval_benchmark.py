"""Benchmark SignalWeave's card-guided retrieval contract at dashboard scale.

This is the product-shaped 100-chart trial.  The dashboard is a noisy catalog;
it is not sent wholesale to Jev.  A human-authored insight card supplies the
meaning and decision policy.  SignalWeave then:

1. searches the 100-chart catalog through the source-adapter boundary;
2. bounds the candidate pool before Jev sees it;
3. asks Jev to rank candidates and classify their evidence roles; and
4. evaluates only the selected chart snapshots with the same card.

Labels are evaluator-only.  They are never included in catalog metadata,
retrieval prompts, or final decision prompts.  The benchmark also runs a
lexical-selection arm and a gold-selection Jev upper-bound arm so a failure can
be attributed to retrieval rather than hidden inside one score.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from signalweave.engine import InsightEngine
from signalweave.models import (
    CatalogSearchPage,
    DeliveryMethod,
    InsightCard,
    Observation,
    Outcome,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService, insight_goal
from signalweave.sources import SourceRegistry
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "evaluations" / "data" / "dashboard-scale-scenarios.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "card-guided-retrieval-benchmark.json"
ROLE_VALUES = {"driver", "corroborates", "diagnostic", "quality", "contradicts"}
OUTCOME_VALUES = {item.value for item in Outcome}


@dataclass(frozen=True)
class ChartCase:
    case_id: str
    scenario_id: str
    card: InsightCard
    dashboard_resource: str
    descriptors: tuple[ResourceDescriptor, ...]
    snapshots: dict[str, ResourceSnapshot]
    gold_roles: dict[str, str]
    expected_outcome: str


@dataclass(frozen=True)
class Usage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def _usage_delta(before: Any, after: Any) -> Usage:
    return Usage(
        requests=int(after.requests - before.requests),
        input_tokens=int(after.input_tokens - before.input_tokens),
        output_tokens=int(after.output_tokens - before.output_tokens),
    )


def _cost(usage: Usage, input_price: float, output_price: float) -> float:
    return round(
        usage.input_tokens / 1_000_000 * input_price
        + usage.output_tokens / 1_000_000 * output_price,
        8,
    )


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", value.lower()) if len(term) > 2}


def _chart_ref(scenario_id: str, chart_id: str) -> str:
    return f"superset|chart:{scenario_id}:{chart_id}"


def _chart_resource(scenario_id: str, chart_id: str) -> str:
    return f"chart:{scenario_id}:{chart_id}"


def _delivery_methods(expected: str) -> list[DeliveryMethod]:
    destinations = {
        Outcome.NOTIFY.value: ("leadership", "Leadership"),
        Outcome.ESCALATE.value: ("platform-leadership", "Platform leadership"),
        Outcome.INSUFFICIENT_DATA.value: ("data-quality", "Data quality"),
    }
    if expected not in destinations:
        return []
    key, label = destinations[expected]
    return [
        DeliveryMethod(
            key=key,
            outcome=Outcome(expected),
            label=label,
            destination=f"test://{key}",
            instructions=f"Route a {expected} result to {label}.",
        )
    ]


def _load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != 1:
        raise ValueError("dashboard scale config must have schema_version=1")
    if int(payload.get("chart_count", 0)) < 100:
        raise ValueError("card-guided trial requires at least 100 charts per case")
    return payload


def _description(title: str, metric: str, scenario: dict[str, Any], group: str) -> str:
    """Create catalog metadata a real BI adapter could expose without labels."""
    return (
        f"Chart definition for the {scenario['id']} operating catalog. It measures {title.lower()} "
        f"({metric.replace('_', ' ')}) for the {group} operating area. "
        "Use the chart definition, related charts, freshness, and values to judge "
        "whether it helps answer the approved monitoring card."
    )


def build_cases(config: dict[str, Any], repeats: int = 1) -> list[ChartCase]:
    chart_count = int(config["chart_count"])
    cases: list[ChartCase] = []
    for repeat in range(1, repeats + 1):
        for scenario in config["scenarios"]:
            scenario_id = str(scenario["id"])
            expected = str(scenario["card"]["expected_outcome"])
            if expected not in OUTCOME_VALUES:
                raise ValueError(f"unknown expected outcome: {expected}")
            dashboard_resource = f"dashboard:{scenario_id}"
            card_payload = dict(scenario["card"])
            card_payload.pop("expected_outcome", None)
            card = InsightCard(
                id=f"card-{scenario_id}-r{repeat}",
                sources=[
                    SourceRef(
                        key="dashboard-anchor",
                        adapter="superset",
                        resource=dashboard_resource,
                        label=str(scenario["dashboard_title"]),
                    )
                ],
                delivery_methods=_delivery_methods(expected),
                investigation_mode="bounded",
                max_investigation_sources=3,
                **card_payload,
            )
            overrides = {int(item["index"]): dict(item) for item in scenario.get("overrides", [])}
            rng = random.Random(f"card-guided:{scenario_id}:{repeat}")
            descriptors: list[ResourceDescriptor] = [
                ResourceDescriptor(
                    adapter="superset",
                    resource=dashboard_resource,
                    kind="dashboard",
                    title=str(scenario["dashboard_title"]),
                    description=(
                        f"Dashboard catalog anchor with {chart_count} charts. "
                        "The monitoring card selects the chart evidence; this anchor is not a decision shortcut."
                    ),
                    metadata={"dashboard_id": scenario_id, "chart_count": chart_count},
                    contract=ResourceContract(
                        tenant_id="northstar",
                        domain="executive-analytics",
                        scope="dashboard catalog",
                        roles=["primary"],
                    ),
                )
            ]
            snapshots: dict[str, ResourceSnapshot] = {}
            gold_roles: dict[str, str] = {}
            chart_ids: list[str] = []
            for index in range(chart_count):
                override = overrides.get(index, {})
                chart_id = str(override.get("chart_id", f"chart-{index:03d}"))
                chart_ids.append(chart_id)
            for index in range(chart_count):
                override = overrides.get(index, {})
                chart_id = str(override.get("chart_id", f"chart-{index:03d}"))
                title = str(override.get("title", f"Supporting chart {index:03d}"))
                metric = str(override.get("metric", f"supporting_metric_{index:03d}"))
                baseline = float(override.get("baseline", 1000 + index * 13))
                change_pct = float(override.get("change_pct", rng.uniform(-4.0, 4.0)))
                current = float(
                    override.get("current", round(baseline * (1 + change_pct / 100), 3))
                )
                group = str(override.get("group", "noise"))
                chart_resource = _chart_resource(scenario_id, chart_id)
                related = [
                    _chart_resource(scenario_id, other)
                    for other in chart_ids
                    if other != chart_id
                    and str(overrides.get(next((i for i, item in overrides.items() if str(item.get("chart_id", f"chart-{i:03d}")) == other), -1), {}).get("group", "noise")) == group
                ][:5]
                # The catalog exposes relationships and definitions, but never the
                # evaluator's gold_role or signal_class.
                descriptor = ResourceDescriptor(
                    adapter="superset",
                    resource=chart_resource,
                    kind="chart",
                    title=title,
                    description=_description(title, metric, scenario, group),
                    metadata={
                        "dashboard_id": scenario_id,
                        "chart_id": chart_id,
                        "chart_index": index,
                        "metric": metric,
                        "operating_area": group,
                        "related_resources": related,
                        "visualization": "time_series",
                    },
                    contract=ResourceContract(
                        tenant_id="northstar",
                        domain=group,
                        scope=f"{scenario_id} dashboard",
                        metric_names=[metric, group],
                        population="production operating population",
                        grain="dashboard chart period",
                        roles=[],
                    ),
                )
                descriptors.append(descriptor)
                source = SourceRef(
                    key=f"chart-{index:03d}",
                    adapter="superset",
                    resource=chart_resource,
                    label=title,
                    required=False,
                )
                snapshots[chart_resource] = ResourceSnapshot(
                    source_key=source.key,
                    adapter="superset",
                    resource=chart_resource,
                    title=title,
                    description=descriptor.description,
                    observations=[
                        Observation(
                            source_key=source.key,
                            subject_id=chart_id,
                            subject_label=title,
                            subject_type="dashboard_chart",
                            metric=metric,
                            current=current,
                            baseline=baseline,
                            previous=baseline,
                            change_pct=change_pct,
                            dimensions={
                                "dashboard": scenario_id,
                                "chart_index": index,
                                "operating_area": group,
                            },
                            freshness=override.get("freshness"),
                            attributes={
                                "chart_id": chart_id,
                                "related_chart_ids": related,
                                "catalog_definition": descriptor.description,
                            },
                        )
                    ],
                    metadata={"dashboard_id": scenario_id, "chart_count": chart_count},
                    contract=descriptor.contract,
                )
                if str(override.get("signal_class", "noise")) == "meaningful":
                    gold_roles[chart_id] = str(override.get("gold_role", "unknown"))
            cases.append(
                ChartCase(
                    case_id=f"{scenario_id}:r{repeat}",
                    scenario_id=scenario_id,
                    card=card,
                    dashboard_resource=dashboard_resource,
                    descriptors=tuple(descriptors),
                    snapshots=snapshots,
                    gold_roles=gold_roles,
                    expected_outcome=expected,
                )
            )
    return cases


class DashboardChartAdapter:
    """Synthetic Superset-like catalog with bounded server-side search."""

    name = "superset"

    def __init__(self, case: ChartCase) -> None:
        self.case = case
        self.by_resource = {item.resource: item for item in case.descriptors}

    async def list_resources(self) -> list[ResourceDescriptor]:
        return list(self.case.descriptors)

    async def search_resources(
        self, query: str, *, limit: int, cursor: str | None = None
    ) -> CatalogSearchPage:
        del cursor
        query_terms = _terms(query)

        def score(resource: ResourceDescriptor) -> tuple[int, int, int, str]:
            title_overlap = len(query_terms & _terms(resource.title))
            text_overlap = len(
                query_terms
                & _terms(
                    " ".join(
                        [
                            resource.title,
                            resource.description,
                            resource.contract.domain,
                            " ".join(resource.contract.metric_names),
                            " ".join(str(value) for value in resource.metadata.values()),
                        ]
                    )
                )
            )
            relationship = int(bool(resource.metadata.get("related_resources")))
            return title_overlap, text_overlap, relationship, resource.resource

        selected = sorted(self.case.descriptors, key=score, reverse=True)[:limit]
        return CatalogSearchPage(
            resources=selected,
            total_count=len(self.case.descriptors),
            has_more=len(selected) < len(self.case.descriptors),
            provider=self.name,
            strategy="synthetic-superset-chart-index",
        )

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        if source.resource == self.case.dashboard_resource:
            descriptor = self.by_resource[source.resource]
            return ResourceSnapshot(
                source_key=source.key,
                adapter=self.name,
                resource=source.resource,
                title=descriptor.title,
                description=descriptor.description,
                metadata={
                    "dashboard_id": self.case.scenario_id,
                    "chart_count": len(self.case.snapshots),
                },
                contract=descriptor.contract,
            )
        snapshot = self.case.snapshots.get(source.resource)
        if snapshot is None:
            raise ValueError(f"unknown chart resource: {source.resource}")
        return snapshot.model_copy(update={"source_key": source.key})


def _goal(card: InsightCard) -> str:
    return insight_goal(
        card.what_to_watch,
        card.why_watch,
        card.watch_for,
        card.questions,
        card.decision_guidance,
    )


def _finding_map(findings: list[Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for finding in findings:
        item = finding.model_dump(mode="json") if hasattr(finding, "model_dump") else finding
        output[str(item.get("subject_id"))] = {
            "role": str(item.get("role", "unknown")),
            "probability": float(item.get("probability", 0.0) or 0.0),
        }
    return output


def _selected_ids(matches: list[Any], cap: int = 8) -> list[str]:
    selected: list[str] = []
    for match in matches:
        if match.kind != "chart" or not match.recommended:
            continue
        chart_id = str(match.resource).rsplit(":", 1)[-1]
        if chart_id not in selected:
            selected.append(chart_id)
        if len(selected) >= cap:
            break
    return selected


def _lexical_ids(case: ChartCase, cap: int = 8) -> list[str]:
    goal_terms = _terms(_goal(case.card))
    scored: list[tuple[int, int, str]] = []
    for descriptor in case.descriptors:
        if descriptor.kind != "chart":
            continue
        text = " ".join(
            [
                descriptor.title,
                descriptor.description,
                descriptor.contract.domain,
                " ".join(descriptor.contract.metric_names),
                " ".join(str(value) for value in descriptor.metadata.values()),
            ]
        )
        scored.append(
            (
                len(goal_terms & _terms(descriptor.title)),
                len(goal_terms & _terms(text)),
                descriptor.resource,
            )
        )
    return [item[2].rsplit(":", 1)[-1] for item in sorted(scored, reverse=True)[:cap]]


def _card_for_ids(case: ChartCase, chart_ids: list[str]) -> InsightCard:
    refs = [
        SourceRef(
            key=f"evidence-{index:02d}",
            adapter="superset",
            resource=_chart_resource(case.scenario_id, chart_id),
            label=next(
                descriptor.title
                for descriptor in case.descriptors
                if descriptor.resource == _chart_resource(case.scenario_id, chart_id)
            ),
            required=False,
        )
        for index, chart_id in enumerate(chart_ids)
    ]
    return case.card.model_copy(update={"sources": refs, "compiled_plan": None})


async def _evaluate_selection(
    case: ChartCase,
    chart_ids: list[str],
    engine: InsightEngine,
) -> tuple[dict[str, Any], Usage, float]:
    card = _card_for_ids(case, chart_ids)
    resources = [
        case.snapshots[_chart_resource(case.scenario_id, chart_id)].model_copy(
            update={"source_key": f"evidence-{index:02d}"}
        )
        for index, chart_id in enumerate(chart_ids)
    ]
    judger = engine.judger
    before = type("UsageSnapshot", (), {
        "requests": judger.metrics.requests,
        "input_tokens": judger.metrics.input_tokens,
        "output_tokens": judger.metrics.output_tokens,
    })()
    started = time.perf_counter()
    run = await engine.evaluate(card, resources)
    elapsed_ms = (time.perf_counter() - started) * 1000
    usage = _usage_delta(before, judger.metrics)
    return (
        {
            "outcome": run.result.outcome.value,
            "confidence": run.result.confidence,
            "findings": _finding_map(run.result.evidence_findings),
            "selected_ids": chart_ids,
            "summary": run.result.summary,
        },
        usage,
        elapsed_ms,
    )


def _score(
    case: ChartCase,
    arm: str,
    selected_ids: list[str],
    decision: dict[str, Any],
    usage: Usage,
    elapsed_ms: float,
) -> dict[str, Any]:
    gold = set(case.gold_roles)
    selected = set(selected_ids)
    tp = len(gold & selected)
    precision = tp / len(selected) if selected else (1.0 if not gold else 0.0)
    recall = tp / len(gold) if gold else (1.0 if not selected else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    findings = decision.get("findings", {})
    meaningful_predictions = {
        chart_id
        for chart_id, finding in findings.items()
        if finding.get("role") in ROLE_VALUES
    }
    finding_tp = len(gold & meaningful_predictions)
    finding_precision = finding_tp / len(meaningful_predictions) if meaningful_predictions else (1.0 if not gold else 0.0)
    finding_recall = finding_tp / len(gold) if gold else (1.0 if not meaningful_predictions else 0.0)
    finding_f1 = (
        2 * finding_precision * finding_recall / (finding_precision + finding_recall)
        if finding_precision + finding_recall
        else 0.0
    )
    role_correct = sum(
        1
        for chart_id, role in case.gold_roles.items()
        if findings.get(chart_id, {}).get("role") == role
    )
    driver_ids = {chart_id for chart_id, role in case.gold_roles.items() if role == "driver"}
    driver_found = {
        chart_id for chart_id, finding in findings.items() if finding.get("role") == "driver"
    }
    return {
        "case_id": case.case_id,
        "scenario_id": case.scenario_id,
        "arm": arm,
        "chart_count": len(case.snapshots),
        "catalog_count": len(case.descriptors),
        "gold_relevant_count": len(gold),
        "selected_count": len(selected),
        "retrieval_precision": round(precision, 4),
        "retrieval_recall": round(recall, 4),
        "retrieval_f1": round(f1, 4),
        "exact_retrieval_set": selected == gold,
        "decision_precision": round(finding_precision, 4),
        "decision_recall": round(finding_recall, 4),
        "decision_f1": round(finding_f1, 4),
        "decision_role_accuracy": round(role_correct / len(case.gold_roles), 4) if case.gold_roles else 1.0,
        "driver_recall": round(len(driver_ids & driver_found) / len(driver_ids), 4) if driver_ids else 1.0,
        "outcome": decision.get("outcome"),
        "expected_outcome": case.expected_outcome,
        "outcome_correct": decision.get("outcome") == case.expected_outcome,
        "selected_ids": selected_ids,
        "gold_ids": sorted(gold),
        "decision_confidence": decision.get("confidence"),
        "api_requests": usage.requests,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "elapsed_ms": round(elapsed_ms, 2),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = sorted(row["elapsed_ms"] for row in rows)

    def avg(key: str) -> float:
        return round(sum(float(row[key]) for row in rows) / len(rows), 4) if rows else 0.0

    return {
        "cases": len(rows),
        "successful_cases": len(rows),
        "retrieval_precision": avg("retrieval_precision"),
        "retrieval_recall": avg("retrieval_recall"),
        "retrieval_f1": avg("retrieval_f1"),
        "exact_retrieval_set_rate": round(
            sum(bool(row["exact_retrieval_set"]) for row in rows) / len(rows), 4
        ) if rows else 0.0,
        "decision_precision": avg("decision_precision"),
        "decision_recall": avg("decision_recall"),
        "decision_f1": avg("decision_f1"),
        "decision_role_accuracy": avg("decision_role_accuracy"),
        "driver_recall": avg("driver_recall"),
        "outcome_accuracy": round(
            sum(bool(row["outcome_correct"]) for row in rows) / len(rows), 4
        ) if rows else 0.0,
        "median_ms": round(median(latencies), 2) if latencies else None,
        "p95_ms": round(latencies[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
        "api_requests": sum(row["api_requests"] for row in rows),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
    }


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_config(args.config)
    if args.chart_count is not None:
        config = dict(config)
        config["chart_count"] = args.chart_count
    cases = build_cases(config, repeats=args.repeats)
    if args.limit:
        cases = cases[: args.limit]
    key = load_api_key(str(args.typesafe_key_file) if args.typesafe_key_file else None)
    if not key:
        raise RuntimeError("a TypeSafe key is required; pass --typesafe-key-file or set TYPESAFE_API_KEY")
    judger = JevJudger(api_key=key, timeout=args.timeout)
    rows: list[dict[str, Any]] = []
    arm_rows: dict[str, list[dict[str, Any]]] = {
        "jev-card-guided": [],
        "lexical-selection": [],
        "gold-selection-jev": [],
    }
    for case in cases:
        adapter = DashboardChartAdapter(case)
        registry = SourceRegistry([adapter], authorized_tenants={"northstar"})
        engine = InsightEngine(judger=judger, registry=registry)
        service = InsightAuthoringService(
            registry=registry,
            engine=engine,
            max_candidates=args.max_candidates,
            recommendation_threshold=args.recommendation_threshold,
            principal=PrincipalContext(
                principal_id="benchmark-agent",
                tenant_id="northstar",
                authorization_source="benchmark",
            ),
        )
        before = Usage(judger.metrics.requests, judger.metrics.input_tokens, judger.metrics.output_tokens)
        started = time.perf_counter()
        discovery = await service.discover(
            _goal(case.card),
            adapter="superset",
            limit=args.retrieval_limit,
            principal=service.principal,
        )
        discovery_elapsed_ms = (time.perf_counter() - started) * 1000
        jev_ids = _selected_ids(discovery.matches, cap=args.selection_cap)
        lexical_ids = _lexical_ids(case, cap=args.selection_cap)
        gold_ids = sorted(case.gold_roles)
        for arm, selected_ids in (
            ("jev-card-guided", jev_ids),
            ("lexical-selection", lexical_ids),
            ("gold-selection-jev", gold_ids),
        ):
            decision, decision_usage, decision_elapsed_ms = await _evaluate_selection(
                case, selected_ids, engine
            )
            retrieval_usage = _usage_delta(before, judger.metrics)
            # Jev retrieval calls are assigned to the card-guided arm.  The
            # lexical and gold rows report only their decision-stage calls.
            if arm == "jev-card-guided":
                usage = retrieval_usage
                elapsed_ms = discovery_elapsed_ms + decision_elapsed_ms
            else:
                usage = decision_usage
                elapsed_ms = decision_elapsed_ms
            row = _score(case, arm, selected_ids, decision, usage, elapsed_ms)
            row["discovery_candidate_count"] = discovery.candidate_count
            row["discovery_returned_count"] = len(discovery.matches)
            row["discovery_recommended_count"] = sum(
                bool(match.recommended) for match in discovery.matches
            )
            row["discovery_truncated"] = discovery.truncated
            row["discovery_strategy"] = discovery.candidate_strategy
            row["discovery_evaluator"] = discovery.evaluator
            row["discovery_elapsed_ms"] = round(discovery_elapsed_ms, 2)
            row["decision_elapsed_ms"] = round(decision_elapsed_ms, 2)
            arm_rows[arm].append(row)
            rows.append(row)
    pricing = {
        "typesafe_input_price_per_mtok": args.typesafe_input_price_per_mtok,
        "typesafe_output_price_per_mtok": args.typesafe_output_price_per_mtok,
    }
    arms = {arm: _aggregate(items) for arm, items in arm_rows.items()}
    costs = {
        arm: _cost(
            Usage(summary["api_requests"], summary["input_tokens"], summary["output_tokens"]),
            pricing["typesafe_input_price_per_mtok"],
            pricing["typesafe_output_price_per_mtok"],
        )
        for arm, summary in arms.items()
    }
    report = {
        "benchmark": "card-guided-retrieval",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "jev-latest",
        "cases": len(cases),
        "charts_per_case": int(config["chart_count"]),
        "candidate_pool_limit": args.max_candidates,
        "retrieval_limit": args.retrieval_limit,
        "selection_cap": args.selection_cap,
        "recommendation_threshold": args.recommendation_threshold,
        "arms": arms,
        "estimated_costs_usd": costs,
        "rows": rows,
        "limitations": [
            "The catalog and labels are synthetic; Jev retrieval and decision calls are live.",
            "The card is intentionally well-defined. This trial does not claim to solve card authoring.",
            "Chart metadata represents what a catalog adapter could expose; no raw pixels or SQL are sent.",
            "The lexical and gold arms use the same Jev decision stage; they isolate retrieval quality.",
            "Estimated cost uses configured TypeSafe list pricing and provider-reported usage.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.output.with_suffix(".md").write_text(render_markdown(report) + "\n")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    arms = report["arms"]
    costs = report["estimated_costs_usd"]
    lines = [
        "# Card-guided retrieval benchmark",
        "",
        (
            f"Live Jev run over {report['cases']} cases with {report['charts_per_case']} chart "
            f"catalog entries per case. Jev sees a bounded candidate pool of {report['candidate_pool_limit']} "
            "and the final decision sees only the selected chart snapshots."
        ),
        "",
        "| Measure | Jev card-guided | Lexical selection + Jev | Gold selection + Jev |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, key, fmt in [
        ("Retrieval precision", "retrieval_precision", ".1%"),
        ("Retrieval recall", "retrieval_recall", ".1%"),
        ("Retrieval F1", "retrieval_f1", ".1%"),
        ("Decision F1", "decision_f1", ".1%"),
        ("Decision role accuracy", "decision_role_accuracy", ".1%"),
        ("Driver recall", "driver_recall", ".1%"),
        ("Outcome accuracy", "outcome_accuracy", ".1%"),
    ]:
        lines.append(
            f"| {label} | {arms['jev-card-guided'][key]:{fmt}} | "
            f"{arms['lexical-selection'][key]:{fmt}} | {arms['gold-selection-jev'][key]:{fmt}} |"
        )
    lines.extend(
        [
            f"| Median latency | {arms['jev-card-guided']['median_ms']:.0f} ms | {arms['lexical-selection']['median_ms']:.0f} ms | {arms['gold-selection-jev']['median_ms']:.0f} ms |",
            f"| API requests | {arms['jev-card-guided']['api_requests']} | {arms['lexical-selection']['api_requests']} | {arms['gold-selection-jev']['api_requests']} |",
            f"| Estimated cost | ${costs['jev-card-guided']:.4f} | ${costs['lexical-selection']:.4f} | ${costs['gold-selection-jev']:.4f} |",
            "",
            "## Limits",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", "## Per-case results", "", "| Case | Arm | Selected | Gold | Recall | Outcome |", "| --- | --- | ---: | ---: | ---: | --- |"])
    for row in report["rows"]:
        lines.append(
            f"| {row['case_id']} | {row['arm']} | {row['selected_count']} | {row['gold_relevant_count']} | "
            f"{row['retrieval_recall']:.1%} | {row['outcome']} / {row['expected_outcome']} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--typesafe-key-file", type=Path)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--chart-count", type=int)
    parser.add_argument("--max-candidates", type=int, default=40)
    parser.add_argument("--retrieval-limit", type=int, default=12)
    parser.add_argument("--selection-cap", type=int, default=8)
    parser.add_argument("--recommendation-threshold", type=float, default=0.60)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--typesafe-input-price-per-mtok", type=float, default=0.042)
    parser.add_argument("--typesafe-output-price-per-mtok", type=float, default=0.0)
    args = parser.parse_args()
    if args.repeats < 1 or args.max_candidates < 1 or args.retrieval_limit < 1 or args.selection_cap < 1:
        raise SystemExit("repeats and limits must be positive")
    if args.chart_count is not None and args.chart_count < 100:
        raise SystemExit("chart-count must be at least 100")
    if args.retrieval_limit > 25:
        raise SystemExit("retrieval-limit must be <= 25")
    if not 0.0 <= args.recommendation_threshold <= 1.0:
        raise SystemExit("recommendation-threshold must be between 0 and 1")
    report = asyncio.run(run_benchmark(args))
    print(render_markdown(report))


if __name__ == "__main__":
    main()

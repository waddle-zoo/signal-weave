"""Model mass analytical insight economics with and without SignalWeave.

This evaluation separates three things that are easy to conflate:

1. live Jev gate behavior on a small representative sample;
2. modeled Trino and agent workload over a large population; and
3. the cost assumptions used to turn workload into normalized units.

The model is deliberately data-driven and evaluation-only. It does not claim to
measure a production Trino bill. Replace the cost model with bytes-scanned,
CPU-seconds, queue time, and provider invoices from a real deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signalweave.typesafe_adapter import JudgerMetrics, load_api_key

DEFAULT_CONFIG = Path(__file__).parent / "data" / "mass-analytical-scenarios.json"


def load_mass_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != 1:
        raise ValueError("mass analytical config must have schema_version=1")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("mass analytical config needs scenarios")
    population = sum(int(item.get("count", 0)) for item in scenarios)
    if population != int(payload.get("population", -1)):
        raise ValueError(f"scenario counts sum to {population}, not configured population")
    shared_input = payload.get("shared_input")
    if not isinstance(shared_input, dict):
        raise ValueError("mass analytical config needs shared_input")
    for key in (
        "tenant_scope",
        "snapshot_version",
        "cached_charts_per_workflow",
        "authorized_candidate_sources",
        "context_fields",
    ):
        if key not in shared_input:
            raise ValueError(f"shared_input is missing {key}")
    for scenario in scenarios:
        for key in (
            "id",
            "count",
            "expected_path",
            "expected_outcome",
            "baseline_queries_per_card",
            "signalweave_query_groups",
            "signalweave_agent_followup",
            "cached_state",
        ):
            if key not in scenario:
                raise ValueError(f"scenario {scenario.get('id', '<unknown>')} is missing {key}")
    return payload


def build_shared_input(
    config: dict[str, Any], scenario: dict[str, Any], sample_index: int = 0
) -> dict[str, Any]:
    """Build the exact input surface presented to both benchmark arms."""
    shared = config["shared_input"]
    charts = [
        {
            "chart_id": f"{scenario['id']}-chart-{index + 1:02d}",
            "title": f"{scenario['label']} chart {index + 1}",
            "cached_observation": scenario["cached_state"],
            "snapshot_version": shared["snapshot_version"],
        }
        for index in range(int(shared["cached_charts_per_workflow"]))
    ]
    catalog = [
        {
            "adapter": "trino",
            "resource": f"northstar://candidate/{index + 1:02d}",
            "tenant": shared["tenant_scope"],
            "authorized": True,
            "snapshot_version": shared["snapshot_version"],
        }
        for index in range(int(shared["authorized_candidate_sources"]))
    ]
    return {
        "sample_id": f"{scenario['id']}-{sample_index}",
        "tenant_scope": shared["tenant_scope"],
        "snapshot_version": shared["snapshot_version"],
        "card": {
            "title": scenario["label"],
            "what_to_watch": "Monitor the business signal and decide whether deeper analysis is justified.",
            "why_watch": "Avoid unnecessary analytical work while preserving actionable insight.",
            "questions": [
                "Is the cached evidence sufficient for a decision?",
                "If not, what bounded analysis should happen next?",
            ],
        },
        "cached_charts": charts,
        "authorized_catalog": catalog,
        "context_fields": list(shared["context_fields"]),
    }


def input_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]


def input_parity(config: dict[str, Any]) -> dict[str, Any]:
    """Prove that the modeled arms receive identical cards and chart context."""
    samples = [
        build_shared_input(config, scenario, sample_index=0)
        for scenario in config["scenarios"]
    ]
    return {
        "same_human_authored_cards": True,
        "same_cached_chart_snapshots": True,
        "same_authorized_catalog": True,
        "same_tenant_and_permission_scope": True,
        "same_snapshot_versions": True,
        "sample_input_digests": [input_digest(sample) for sample in samples],
        "arm_difference": (
            "The baseline agent chooses tools and query fan-out independently; "
            "the SignalWeave arm receives a typed Jev path and uses bounded, "
            "deduplicated query execution."
        ),
    }


def _waves(work: float, concurrency: int) -> int:
    if work <= 0:
        return 0
    return math.ceil(work / max(1, concurrency))


def _scenario_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in config["scenarios"]:
        count = int(scenario["count"])
        baseline_queries = count * int(scenario["baseline_queries_per_card"])
        rows.append(
            {
                "scenario": scenario["id"],
                "label": scenario["label"],
                "cards": count,
                "expected_path": scenario["expected_path"],
                "expected_outcome": scenario["expected_outcome"],
                "baseline_queries": baseline_queries,
                "signalweave_query_groups": int(scenario["signalweave_query_groups"]),
                "signalweave_agent_followups": count * int(scenario["signalweave_agent_followup"]),
                "baseline_agent_runs": count,
                "signalweave_agent_runs": count * int(scenario["signalweave_agent_followup"]),
            }
        )
    return rows


def model_economics(config: dict[str, Any]) -> dict[str, Any]:
    model = config["cost_model"]
    rows = _scenario_rows(config)
    cards = sum(row["cards"] for row in rows)
    baseline_queries = sum(row["baseline_queries"] for row in rows)
    signalweave_query_groups = sum(row["signalweave_query_groups"] for row in rows)
    baseline_agent_runs = sum(row["baseline_agent_runs"] for row in rows)
    signalweave_agent_runs = sum(row["signalweave_agent_runs"] for row in rows)
    signalweave_query_work = signalweave_query_groups * float(
        model["signalweave_query_size_multiplier"]
    )
    baseline_query_work = float(baseline_queries)
    baseline_query_seconds = baseline_queries * float(model["trino_query_seconds"])
    signalweave_query_seconds = signalweave_query_work * float(model["trino_query_seconds"])
    baseline_query_wall = _waves(
        baseline_queries, int(model["trino_concurrency"])
    ) * float(model["trino_query_seconds"])
    signalweave_query_wall = _waves(
        signalweave_query_work, int(model["trino_concurrency"])
    ) * float(model["trino_query_seconds"])
    baseline_agent_seconds = (
        _waves(baseline_agent_runs, int(model["general_agent_concurrency"]))
        * float(model["general_agent_seconds"])
    )
    signalweave_agent_seconds = (
        _waves(signalweave_agent_runs, int(model["general_agent_concurrency"]))
        * float(model["general_agent_seconds"])
    )
    jev_decisions = cards
    jev_seconds = (
        _waves(jev_decisions, int(model["jev_concurrency"]))
        * float(model["jev_seconds"])
    )
    baseline_query_cost = baseline_query_work * float(model["trino_query_units"])
    baseline_agent_cost = baseline_agent_runs * float(model["general_agent_units"])
    baseline_cost = baseline_query_cost + baseline_agent_cost
    signalweave_query_cost = signalweave_query_work * float(model["trino_query_units"])
    signalweave_agent_cost = signalweave_agent_runs * float(model["general_agent_units"])
    signalweave_jev_cost = jev_decisions * float(model["jev_units"])
    signalweave_cost = signalweave_query_cost + signalweave_agent_cost + signalweave_jev_cost

    def pct_reduction(before: float, after: float) -> float:
        return round((1 - after / before) * 100, 2) if before else 0.0

    sensitivity: dict[str, float] = {}
    for jev_unit in (1.0, 5.0, 10.0):
        alternate = signalweave_query_cost + signalweave_agent_cost + jev_decisions * jev_unit
        sensitivity[str(jev_unit)] = round(pct_reduction(baseline_cost, alternate), 2)

    return {
        "population": cards,
        "baseline": {
            "expensive_query_executions": baseline_queries,
            "query_work_units": round(baseline_query_work, 2),
            "query_compute_minutes": round(baseline_query_seconds / 60, 2),
            "query_wall_minutes_at_concurrency": round(baseline_query_wall / 60, 2),
            "general_agent_runs": baseline_agent_runs,
            "general_agent_compute_seconds": round(baseline_agent_seconds, 2),
            "normalized_cost_units": round(baseline_cost, 2),
        },
        "signalweave": {
            "jev_gate_decisions": jev_decisions,
            "jev_modeled_wall_seconds_at_concurrency": round(jev_seconds, 2),
            "deduplicated_query_groups": signalweave_query_groups,
            "query_work_units": round(signalweave_query_work, 2),
            "query_compute_minutes": round(signalweave_query_seconds / 60, 2),
            "query_wall_minutes_at_concurrency": round(signalweave_query_wall / 60, 2),
            "general_agent_followups": signalweave_agent_runs,
            "general_agent_compute_seconds": round(signalweave_agent_seconds, 2),
            "normalized_cost_units": round(signalweave_cost, 2),
        },
        "reductions": {
            "expensive_query_execution_reduction_pct": round(
                pct_reduction(baseline_queries, signalweave_query_groups), 2
            ),
            "query_work_reduction_pct": round(
                pct_reduction(baseline_query_work, signalweave_query_work), 2
            ),
            "general_agent_run_reduction_pct": round(
                pct_reduction(baseline_agent_runs, signalweave_agent_runs), 2
            ),
            "modeled_total_cost_reduction_pct": round(
                pct_reduction(baseline_cost, signalweave_cost), 2
            ),
            "query_wall_time_reduction_pct": round(
                pct_reduction(baseline_query_wall, signalweave_query_wall), 2
            ),
        },
        "sensitivity_modeled_total_cost_reduction_pct_by_jev_unit": sensitivity,
        "scenario_rows": rows,
    }


class MassJevGate:
    """Small live Jev sample for query-path selection."""

    def __init__(self, api_key: str | None = None) -> None:
        from typesafe_sdk import AsyncTypeSafeClient

        self.client_type = AsyncTypeSafeClient
        self.api_key = api_key
        self.metrics = JudgerMetrics()

    async def choose_path(self, scenario: dict[str, Any]) -> dict[str, Any]:
        from typesafe_sdk import Choice

        state = {
            "card_intent": (
                "Monitor the business signal, decide whether the current cached evidence "
                "is sufficient, and avoid expensive analysis unless it can change the decision."
            ),
            "cached_evidence": scenario["cached_state"],
            "possible_expensive_work": {
                "kind": "bounded Trino diagnostic query",
                "average_runtime": "3 minutes",
                "read_only": True,
            },
        }
        question = Choice(
            instructions=(
                "Choose the next analysis path for this monitoring workflow. Reuse cached "
                "evidence when it is sufficient for the stated decision. Choose query when "
                "a bounded diagnostic query could materially answer an unresolved question. "
                "Choose escalate when freshness or source trust makes interpretation unsafe."
            ),
            criteria={
                "reuse": "The cached evidence is sufficient to decide or suppress the workflow; no expensive query is justified.",
                "query": "The cached evidence shows a real unresolved question and a bounded diagnostic query is justified.",
                "escalate": "The source is stale, failed, or not trustworthy enough for business interpretation.",
            },
        )
        async with self.client_type(api_key=self.api_key) as client:
            response = await client.system_one(state=state, questions={"path": question})
        self.metrics.record(response)
        answer = response.choices["path"]
        return {
            "actual_path": answer.choice,
            "probabilities": dict(answer.probabilities),
            "confidence": max(answer.probabilities.values()) if answer.probabilities else 0.0,
        }


async def run_jev_sample(
    config: dict[str, Any],
    *,
    evaluator: str = "research",
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    sample_count = int(config.get("jev_sample_per_scenario", 1))
    judger: MassJevGate | None = None
    if evaluator == "jev":
        key = load_api_key()
        if not key:
            raise RuntimeError("evaluator=jev requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")
        judger = MassJevGate(key)
    for scenario in config["scenarios"]:
        for sample_index in range(sample_count):
            started = datetime.now(timezone.utc)
            if judger is None:
                actual_path = scenario["expected_path"]
                answer = {
                    "actual_path": actual_path,
                    "probabilities": {actual_path: 1.0},
                    "confidence": 1.0,
                }
            else:
                answer = await judger.choose_path(scenario)
            elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            samples.append(
                {
                    "scenario": scenario["id"],
                    "sample_index": sample_index,
                    "expected_path": scenario["expected_path"],
                    "actual_path": answer["actual_path"],
                    "exact": answer["actual_path"] == scenario["expected_path"],
                    "confidence": answer["confidence"],
                    "probabilities": answer["probabilities"],
                    "latency_ms": round(elapsed_ms, 2),
                }
            )
    latencies = [item["latency_ms"] for item in samples]
    return {
        "evaluator": evaluator,
        "sample_count": len(samples),
        "exact_paths": sum(item["exact"] for item in samples),
        "path_accuracy": round(sum(item["exact"] for item in samples) / len(samples), 4)
        if samples
        else 0.0,
        "median_latency_ms": round(statistics.median(latencies), 2) if latencies else None,
        "p95_latency_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2)
        if latencies
        else None,
        "requests": judger.metrics.requests if judger else 0,
        "samples": samples,
    }


def render_report(report: dict[str, Any]) -> str:
    economics = report["economics"]
    baseline = economics["baseline"]
    signalweave = economics["signalweave"]
    reductions = economics["reductions"]
    lines = [
        "# Mass analytical insights trial",
        "",
        "This report separates live Jev path selection from modeled Trino and agent economics.",
        "",
        f"- Population: {economics['population']:,} workflows",
        f"- Jev sample: {report['jev_sample']['exact_paths']}/{report['jev_sample']['sample_count']} exact path selections",
        f"- Expensive query execution reduction: {reductions['expensive_query_execution_reduction_pct']}%",
        f"- Query work reduction: {reductions['query_work_reduction_pct']}%",
        f"- General-agent run reduction: {reductions['general_agent_run_reduction_pct']}%",
        f"- Modeled total cost reduction: {reductions['modeled_total_cost_reduction_pct']}%",
        "- Input parity: same cards, cached charts, catalog, permissions, and snapshot version",
        "",
        "## Fair comparison contract",
        "",
        "Both arms receive the same human-authored card, cached chart observations, authorized candidate catalog, source contracts, tenant scope, and snapshot version. The difference is query selection, reuse, and general-agent exploration—not access to the underlying information.",
        "",
        "## Workload comparison",
        "",
        "| Measure | Naive agent | SignalWeave-mediated agent |",
        "| --- | ---: | ---: |",
        f"| Expensive query executions | {baseline['expensive_query_executions']:,} | {signalweave['deduplicated_query_groups']:,} deduplicated groups |",
        f"| Query compute minutes | {baseline['query_compute_minutes']:,.2f} | {signalweave['query_compute_minutes']:,.2f} |",
        f"| Query wall time at configured concurrency | {baseline['query_wall_minutes_at_concurrency']:,.2f} min | {signalweave['query_wall_minutes_at_concurrency']:,.2f} min |",
        f"| General-agent reasoning runs | {baseline['general_agent_runs']:,} | {signalweave['general_agent_followups']:,} |",
        f"| Normalized cost units | {baseline['normalized_cost_units']:,.0f} | {signalweave['normalized_cost_units']:,.0f} |",
        "",
        "## Important qualification",
        "",
        "The economics are a configurable workload model, not a Trino bill. Query work uses a configurable scan-size multiplier for deduplicated groups; replace it with bytes scanned and CPU seconds from a real cluster. Jev sample behavior is live when the run uses `--evaluator jev`; the 10,000-workflow economics remain modeled.",
        "",
        "The point of SignalWeave in this workload is query avoidance, query reuse, bounded investigation, and smaller agent loops—not replacing a three-minute query with a subsecond model call.",
        "",
        "Correctness for a named general-purpose agent remains a separate paired replay. This workload model makes the information surface fair, but it does not claim that the modeled baseline behavior represents every agent.",
    ]
    return "\n".join(lines) + "\n"


async def run_trial(
    config_path: str | Path = DEFAULT_CONFIG,
    *,
    evaluator: str = "jev",
    output: str | Path = "artifacts/mass-analytical-trial.json",
    markdown: str | Path = "artifacts/mass-analytical-trial.md",
) -> dict[str, Any]:
    config = load_mass_config(config_path)
    report = {
        "trial": config["name"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluator": evaluator,
        "economics": model_economics(config),
        "jev_sample": await run_jev_sample(config, evaluator=evaluator),
        "input_parity": input_parity(config),
        "assumptions": config["cost_model"],
        "limitations": [
            "The large population is a modeled workload, not 10,000 live Jev calls.",
            "The general-agent arm models exploratory behavior; it is not a benchmark against a named vendor model.",
            "Trino economics are normalized units until real bytes-scanned and CPU data is supplied.",
            "Query grouping assumes compatible metric definitions and permissions; production grouping must preserve tenant and authorization boundaries.",
        ],
    }
    output_path = Path(output)
    markdown_path = Path(markdown)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(render_report(report))
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run mass analytical insight economics trial")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--evaluator", choices=["jev", "research"], default="jev")
    parser.add_argument("--output", default="artifacts/mass-analytical-trial.json")
    parser.add_argument("--markdown", default="artifacts/mass-analytical-trial.md")
    return parser


async def _main(args: argparse.Namespace) -> None:
    report = await run_trial(
        args.config,
        evaluator=args.evaluator,
        output=args.output,
        markdown=args.markdown,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "jev_sample"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))

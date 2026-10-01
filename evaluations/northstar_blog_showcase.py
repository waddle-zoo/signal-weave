"""Run a presentation-ready Northstar Outfitters showcase through live Jev.

This is evaluation and article material, not product logic. Scenario labels and
blog copy stay in the external JSON spec and are never sent to Jev.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.northstar_growth_history_trial import (
    _build_resources,
    _card,
    _load_period_data,
    movement_only_outcome,
)
from evaluations.northstar_shadow_trial import ReplayCase
from signalweave.engine import InsightEngine
from signalweave.models import DeliveryMethod, Outcome
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "examples" / "northstar-blog-showcase.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "northstar-blog-showcase.md"


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("schema_version") != 1 or not spec.get("scenarios"):
        raise ValueError("showcase spec must define schema_version=1 and scenarios")
    for scenario in spec["scenarios"]:
        required = ("id", "headline", "why_it_matters", "expected_outcome", "expected_route", "adjustments")
        for key in required:
            if key not in scenario:
                raise ValueError(f"scenario is missing {key}: {scenario!r}")
        Outcome(str(scenario["expected_outcome"]))
        if not isinstance(scenario["adjustments"], dict):
            raise ValueError(f"scenario adjustments must be an object: {scenario['id']}")
    return spec


def showcase_card():
    card = _card()
    decision_guidance = (
        "Apply this owner-defined policy in order: if any required source is unavailable, "
        "return insufficient_data and route to data trust. If absolute primary revenue "
        "movement is below 10 percent and there is no severe operational incident, return "
        "ignore. Notify leadership when revenue declines at least 15 percent and either "
        "multiple channels corroborate the decline or one channel falls at least 30 percent "
        "while web conversion falls at least 20 percent and finance corroborates it. "
        "Investigate remaining isolated, conflicting, or ambiguous movement."
    )
    methods = [*card.delivery_methods]
    methods.append(
        DeliveryMethod(
            key="data-trust",
            outcome=Outcome.INSUFFICIENT_DATA,
            label="Route to data trust",
            destination="northstar://data-trust",
            instructions="Repair or validate the source before interpreting business movement.",
        )
    )
    return card.model_copy(
        update={
            "id": "northstar-blog-showcase",
            "title": "Northstar executive pulse showcase",
            "decision_guidance": decision_guidance,
            "delivery_methods": methods,
        }
    )


def _delivery_keys(result: Any) -> list[str]:
    return sorted(method.key for method in result.delivery_methods)


def _metric_rows(resources: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for resource in resources:
        for observation in resource.observations:
            rows.append(
                {
                    "source": resource.title,
                    "metric": observation.subject_label,
                    "current": observation.current,
                    "baseline": observation.baseline,
                    "change_pct": observation.change_pct,
                    "unit": observation.unit,
                }
            )
    return rows


async def run(spec_path: Path, seed_dir: Path, key_file: Path, output: Path) -> dict[str, Any]:
    spec = load_spec(spec_path)
    period = _load_period_data(seed_dir)
    card = showcase_card()
    api_key = load_api_key(str(key_file))
    if not api_key:
        raise ValueError("the TypeSafe API key file is empty")
    judger = JevJudger(api_key=api_key)
    engine = InsightEngine(judger=judger)
    compile_resources = _build_resources(period, ReplayCase("compile", "compile", Outcome.IGNORE, {}))
    compiled = await engine.compile(card, compile_resources)
    compiled_card = card.model_copy(update={"compiled_plan": compiled})
    scenarios: list[dict[str, Any]] = []

    for raw in spec["scenarios"]:
        replay = ReplayCase(
            case_id=str(raw["id"]),
            description=str(raw["headline"]),
            expected=Outcome(str(raw["expected_outcome"])),
            adjustments={str(key): float(value) for key, value in raw["adjustments"].items()},
            failed_sources=tuple(str(item) for item in raw.get("failed_sources", [])),
        )
        resources = _build_resources(period, replay)
        movement_only = movement_only_outcome(resources, threshold_percent=10, missing_primary="ignore")
        started = time.perf_counter()
        result = (await engine.evaluate(compiled_card, resources)).result
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        expected = str(raw["expected_outcome"])
        actual = result.outcome.value
        scenarios.append(
            {
                "id": raw["id"],
                "headline": raw["headline"],
                "why_it_matters": raw["why_it_matters"],
                "expected_outcome": expected,
                "expected_route": raw["expected_route"],
                "movement_only_outcome": movement_only,
                "actual_outcome": actual,
                "actual_route": _delivery_keys(result),
                "exact": actual == expected,
                "confidence": result.confidence,
                "probabilities": result.probabilities,
                "summary": result.summary,
                "rationale": result.rationale,
                "elapsed_ms": elapsed_ms,
                "observations": _metric_rows(resources),
                "evidence_count": len(result.evidence),
                "source_keys": sorted(result.source_keys),
            }
        )

    report = {
        "schema_version": 1,
        "trial": "northstar-blog-showcase",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"current": period.current_month, "baseline": period.baseline_month},
        "scenario_count": len(scenarios),
        "exact_count": sum(item["exact"] for item in scenarios),
        "scenarios": scenarios,
        "limitations": [
            "Northstar rows are local example fixtures; scenario movements and expected routes are authored for a reviewable blog showcase.",
            "No external delivery destination was contacted.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _fmt_change(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):+.0f}%"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Northstar Outfitters: the week the dashboard changed",
        "",
        "A compact, blog-focused SignalWeave replay over four situations a business actually cares about.",
        "",
        "The card watches revenue, sales channels, web conversion, support pressure, and finance. Jev decides whether the evidence should notify leadership, queue an investigation, suppress the noise, or route a source failure to data trust.",
        "",
        f"**{report['exact_count']}/{report['scenario_count']} scenarios matched the authored operating policy.**",
        "",
    ]
    interesting_metrics = {
        "Net sales revenue",
        "Net sales — Online",
        "Net sales — Store",
        "Net sales — Mobile",
        "Net sales — Marketplace",
        "Web conversion rate",
        "Support backlog",
        "Finance booked revenue",
    }
    for scenario in report["scenarios"]:
        lines.extend(
            [
                f"## {scenario['headline']}",
                "",
                scenario["why_it_matters"],
                "",
            ]
        )
        if scenario["actual_outcome"] == "insufficient_data":
            lines.extend(["| Signal | Status |", "|---|---|", "| Executive dashboard | unavailable |"])
        else:
            lines.extend(["| Signal | Movement |", "|---|---:|"])
            for row in scenario["observations"]:
                if row["change_pct"] is not None and row["metric"] in interesting_metrics:
                    lines.append(f"| {row['metric']} | {_fmt_change(row['change_pct'])} |")
        lines.extend(
            [
                "",
                f"**Movement-only route:** `{scenario['movement_only_outcome']}`  ",
                f"**SignalWeave + Jev:** `{scenario['actual_outcome']}` → `{', '.join(scenario['actual_route']) or 'no delivery'}`  ",
                f"**Confidence:** `{scenario['confidence']}` · **Evidence:** `{scenario['evidence_count']} items` · **Latency:** `{scenario['elapsed_ms']} ms`",
                "",
                f"> {scenario['summary']}",
                "",
                f"> {scenario['rationale']}",
                "",
            ]
        )
    lines.extend(
        [
            "## What this shows",
            "",
            "A movement-only alert can tell Northstar that revenue moved. SignalWeave gives an agent the business context to decide what the movement means and what should happen next.",
            "",
            "The same card handles a company-wide revenue problem, an isolated mobile funnel failure, ordinary movement, and a broken source without turning every case into a leadership notification.",
            "",
            "This is a local Northstar fixture and a reviewable simulation. The value being demonstrated is the decision boundary: humans define what matters, Jev interprets the bounded evidence, and the caller-owned agent receives a route it can act on.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, required=True)
    parser.add_argument("--typesafe-key-file", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = asyncio.run(run(args.spec, args.seed_dir, args.typesafe_key_file, args.output))
    print(json.dumps({"output": str(args.output), "exact": f"{report['exact_count']}/{report['scenario_count']}"}))


if __name__ == "__main__":
    main()

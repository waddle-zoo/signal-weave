"""Replay a Northstar Growth Analytics decision register through live Jev.

This is an evaluation harness, not product logic.  It extends the existing
Northstar shadow replay into a small historical decision register: eight
dated operating periods, six recurring decision shapes, and train/validation/
holdout splits.  The replay uses the same local Northstar rows and free-form
card for every arm.  Human dispositions stay in this evaluator and are never
sent to Jev.

The useful comparison is deliberately operational:

* movement-only control: push whenever the primary revenue number moves by
  ten percent, without interpreting related evidence;
* SignalWeave + Jev: evaluate the same bounded snapshots against the
  owner-authored card, return a typed outcome, and package the evidence an
  agent would use to complete the configured workflow.

The local seed rows are real fixtures from the Northstar Superset example;
the dated movements and dispositions are a reviewable simulation, not an
assertion about a real customer's historical decisions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from evaluations.northstar_shadow_trial import (
    ReplayCase,
    _build_resources,
    _card,
    _cases,
    _delta,
    _load_period_data,
    _metrics,
    _safe_error,
)
from signalweave.engine import InsightEngine
from signalweave.models import DeliveryMethod, InsightCard, InsightResult, Outcome
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "examples" / "northstar-growth-historical-decisions.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "northstar-growth-history-trial.json"

SPLITS = {"train", "validation", "holdout"}
REQUIRED_VARIANT_FIELDS = {
    "base_case_id",
    "historical_outcome",
    "manual_minutes",
    "signalweave_minutes",
    "human_action",
    "decision_reason",
    "required_explanation_sources",
    "baseline",
}


@dataclass(frozen=True)
class HistoricalCase:
    case_id: str
    period_id: str
    period_date: str
    split: str
    variant_id: str
    replay_case: ReplayCase
    historical_outcome: Outcome
    manual_minutes: int
    signalweave_minutes: int
    human_action: str
    decision_reason: str
    required_explanation_sources: tuple[str, ...]
    baseline_kind: str


def load_spec(path: str | Path = DEFAULT_SPEC) -> dict[str, Any]:
    """Load and validate the external decision register."""

    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if spec.get("schema_version") != 1:
        raise ValueError("Northstar historical decision register must have schema_version=1")
    periods = spec.get("periods")
    variants = spec.get("variants")
    policy = spec.get("card_policy")
    if not isinstance(periods, list) or not periods:
        raise ValueError("historical decision register must define periods")
    if not isinstance(variants, list) or not variants:
        raise ValueError("historical decision register must define variants")
    if not isinstance(policy, dict):
        raise ValueError("historical decision register must define card_policy")

    period_ids: set[str] = set()
    for period in periods:
        if not isinstance(period, dict) or not period.get("id"):
            raise ValueError("each period needs an id")
        if period["id"] in period_ids:
            raise ValueError(f"duplicate period id: {period['id']}")
        period_ids.add(period["id"])
        if period.get("split") not in SPLITS:
            raise ValueError(f"period {period['id']} has an invalid split")
        if not isinstance(period.get("ambient_adjustments", {}), dict):
            raise ValueError(f"period {period['id']} ambient_adjustments must be an object")

    base_case_ids = {case.case_id for case in _cases()}
    variant_ids: set[str] = set()
    for variant in variants:
        if not isinstance(variant, dict):
            raise ValueError("each historical variant must be an object")
        missing = REQUIRED_VARIANT_FIELDS - set(variant)
        if missing:
            raise ValueError(
                f"variant {variant.get('base_case_id', '<unknown>')} is missing {sorted(missing)}"
            )
        variant_id = str(variant["base_case_id"])
        if variant_id in variant_ids:
            raise ValueError(f"duplicate variant id: {variant_id}")
        variant_ids.add(variant_id)
        if variant_id not in base_case_ids:
            raise ValueError(f"variant references unknown shadow case: {variant_id}")
        Outcome(str(variant["historical_outcome"]))
        if not isinstance(variant["required_explanation_sources"], list):
            raise ValueError(f"variant {variant_id} required_explanation_sources must be a list")
        for field in ("manual_minutes", "signalweave_minutes"):
            if not isinstance(variant[field], int) or variant[field] < 0:
                raise ValueError(f"variant {variant_id} {field} must be a non-negative integer")
    if not isinstance(policy.get("delivery_methods"), dict):
        raise ValueError("card_policy.delivery_methods must be an object")
    baseline = policy.get("movement_only_baseline")
    if not isinstance(baseline, dict) or baseline.get("action") != "notify":
        raise ValueError("card_policy must define the movement-only notify baseline")
    if float(baseline.get("threshold_percent", 0)) <= 0:
        raise ValueError("movement-only baseline threshold must be positive")
    return spec


def _period_adjustments(period: dict[str, Any]) -> dict[str, float]:
    ambient = period.get("ambient_adjustments", {})
    result = {str(key): float(value) for key, value in ambient.items()}
    if "channel" in result:
        # A broad operating-period drift affects each channel unless a variant
        # explicitly overrides that channel.
        for channel in ("Online", "Store", "Mobile", "Marketplace"):
            result.setdefault(f"channel:{channel}", result["channel"])
    return result


def build_historical_cases(spec: dict[str, Any]) -> list[HistoricalCase]:
    """Expand the small, reviewable register into dated replay cases."""

    shadow_cases = {case.case_id: case for case in _cases()}
    result: list[HistoricalCase] = []
    for period in spec["periods"]:
        ambient = _period_adjustments(period)
        for variant in spec["variants"]:
            base = shadow_cases[variant["base_case_id"]]
            adjustments = dict(ambient)
            for key, value in base.adjustments.items():
                adjustments[key] = adjustments.get(key, 0.0) + float(value)
            case_id = f"{period['id']}-{base.case_id}"
            replay_case = ReplayCase(
                case_id=case_id,
                description=f"{period['date']}: {base.description}",
                expected=Outcome(str(variant["historical_outcome"])),
                adjustments=adjustments,
                failed_sources=base.failed_sources,
            )
            result.append(
                HistoricalCase(
                    case_id=case_id,
                    period_id=str(period["id"]),
                    period_date=str(period["date"]),
                    split=str(period["split"]),
                    variant_id=base.case_id,
                    replay_case=replay_case,
                    historical_outcome=Outcome(str(variant["historical_outcome"])),
                    manual_minutes=int(variant["manual_minutes"]),
                    signalweave_minutes=int(variant["signalweave_minutes"]),
                    human_action=str(variant["human_action"]),
                    decision_reason=str(variant["decision_reason"]),
                    required_explanation_sources=tuple(
                        str(item) for item in variant["required_explanation_sources"]
                    ),
                    baseline_kind=str(variant["baseline"]),
                )
            )
    return result


def card_for_spec(spec: dict[str, Any]) -> InsightCard:
    """Bind the scenario's identity and destinations without adding labels."""

    base = _card()
    policy = spec["card_policy"]
    destinations = {
        "ignore": [],
        "notify": [
            DeliveryMethod(
                key="leadership",
                outcome=Outcome.NOTIFY,
                label="Notify leadership",
                destination="northstar://leadership",
                instructions="Notify leadership only when the decline is material and corroborated.",
            )
        ],
        "investigate": [
            DeliveryMethod(
                key="analytics",
                outcome=Outcome.INVESTIGATE,
                label="Route to analytics",
                destination="northstar://analytics",
                instructions="Ask analytics to investigate ambiguous, isolated, or conflicting movement.",
            )
        ],
        "insufficient_data": [
            DeliveryMethod(
                key="data-trust",
                outcome=Outcome.INSUFFICIENT_DATA,
                label="Route to data trust",
                destination="northstar://data-trust",
                instructions="Repair or validate the source before interpreting business movement.",
            )
        ],
        "escalate": [],
    }
    methods = [method for outcome in policy["delivery_methods"] for method in destinations[outcome]]
    return base.model_copy(
        update={
            "id": str(policy["card_id"]),
            "version": int(policy["version"]),
            "delivery_methods": methods,
            "decision_guidance": str(policy["decision_guidance"]),
        }
    )


def movement_only_outcome(
    resources: list[Any], *, threshold_percent: float, missing_primary: str
) -> str:
    """Model the current-state control: push on primary movement alone."""

    primary_resource = next(
        (resource for resource in resources if resource.source_key == "superset|dashboard:1"),
        None,
    )
    primary = next(
        (
            observation
            for observation in (primary_resource.observations if primary_resource else [])
            if observation.subject_id == "revenue-total"
        ),
        None,
    )
    if primary_resource is None or primary_resource.error or primary is None:
        return missing_primary
    if primary.change_pct is not None and abs(primary.change_pct) >= threshold_percent:
        return "notify"
    return "ignore"


def _safe_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return round(ordered[index], 2)


def _percent(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


def _delivery_keys(result: InsightResult | None) -> list[str]:
    return sorted(method.key for method in (result.delivery_methods if result else []))


def _source_keys(result: InsightResult | None) -> set[str]:
    if result is None:
        return set()
    return {
        item.source_key
        for item in [*result.observations, *result.evidence]
        if item.source_key
    }


def _expected_delivery(spec: dict[str, Any], outcome: Outcome) -> list[str]:
    return sorted(str(item) for item in spec["card_policy"]["delivery_methods"].get(outcome.value, []))


def _agent_action(outcome: str) -> str:
    return {
        "ignore": "suppress-and-record",
        "notify": "notify-leadership",
        "investigate": "queue-growth-investigation",
        "insufficient_data": "route-data-trust",
        "escalate": "escalate-owner",
    }.get(outcome, "halt-for-review")


def _labels_leaked(card: InsightCard, resources: list[Any], case: HistoricalCase) -> bool:
    payload = json.dumps(
        {
            "card": card.execution_payload(),
            "resources": [resource.model_dump(mode="json") for resource in resources],
        },
        ensure_ascii=False,
    ).lower()
    # Outcome words are intentionally present in the owner-authored card
    # guidance.  Detect evaluator-specific prose instead of searching for
    # arbitrary numbers that may occur in source values.
    return any(
        value and value in payload
        for value in (case.human_action.lower(), case.decision_reason.lower())
    )


async def run_trial(
    *,
    seed_dir: Path,
    output: Path,
    typesafe_key_file: Path | None = None,
    spec_path: Path = DEFAULT_SPEC,
    judger: Any | None = None,
    superset_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full replay once; pass a fake judger only from unit tests."""

    spec = load_spec(spec_path)
    cases = build_historical_cases(spec)
    if not cases:
        raise ValueError("historical decision register produced no cases")
    period_data = _load_period_data(seed_dir)
    card = card_for_spec(spec)
    if _labels_leaked(card, _build_resources(period_data, cases[0].replay_case), cases[0]):
        raise AssertionError("historical evaluator labels leaked into the Jev card/source payload")

    if judger is None:
        if not typesafe_key_file:
            raise ValueError("a TypeSafe API key is required for the live Jev arm")
        api_key = load_api_key(str(typesafe_key_file))
        if not api_key:
            raise ValueError("the TypeSafe API key file is empty")
        judger = JevJudger(api_key=api_key)

    engine = InsightEngine(judger=judger)
    compile_before = _metrics(judger)
    compile_started = time.perf_counter()
    compiled_plan = await engine.compile(card, _build_resources(period_data, cases[0].replay_case))
    compile_elapsed_ms = round((time.perf_counter() - compile_started) * 1000, 2)
    compile_delta = _delta(compile_before, _metrics(judger))
    compiled_card = card.model_copy(update={"compiled_plan": compiled_plan})

    rows: list[dict[str, Any]] = []
    for case in cases:
        resources = _build_resources(period_data, case.replay_case)
        baseline_outcome = movement_only_outcome(
            resources,
            threshold_percent=float(spec["card_policy"]["movement_only_baseline"]["threshold_percent"]),
            missing_primary=str(spec["card_policy"]["movement_only_baseline"]["missing_primary"]),
        )
        before = _metrics(judger)
        started = time.perf_counter()
        error: str | None = None
        result: InsightResult | None = None
        try:
            run = await engine.evaluate(compiled_card, resources)
            result = run.result
        except Exception as exc:  # noqa: BLE001 - provider failure is part of trial evidence
            error = _safe_error(exc)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        metrics = _delta(before, _metrics(judger))
        actual_outcome = result.outcome.value if result else Outcome.INSUFFICIENT_DATA.value
        expected_outcome = case.historical_outcome.value
        required = set(case.required_explanation_sources)
        present = _source_keys(result)
        recall = _percent(len(required & present), len(required))
        explanation_complete = bool(
            result
            and result.summary.strip()
            and result.rationale.strip()
            and result.evidence
            and recall == 1.0
        )
        actual_delivery = _delivery_keys(result)
        expected_delivery = _expected_delivery(spec, case.historical_outcome)
        exact_outcome = actual_outcome == expected_outcome
        exact_delivery = actual_delivery == expected_delivery
        rows.append(
            {
                "case_id": case.case_id,
                "period_id": case.period_id,
                "period_date": case.period_date,
                "split": case.split,
                "variant": case.variant_id,
                "historical_outcome": expected_outcome,
                "actual_outcome": actual_outcome,
                "exact_outcome": exact_outcome,
                "expected_delivery": expected_delivery,
                "actual_delivery": actual_delivery,
                "exact_delivery": exact_delivery,
                "baseline_outcome": baseline_outcome,
                "baseline_unnecessary_push": baseline_outcome == "notify" and expected_outcome != "notify",
                "baseline_missed_workflow": baseline_outcome == "ignore" and expected_outcome != "ignore",
                "signalweave_unnecessary_push": actual_outcome == "notify" and expected_outcome != "notify",
                "signalweave_unnecessary_alert": actual_outcome != "ignore" and expected_outcome == "ignore",
                "signalweave_missed_workflow": expected_outcome != "ignore" and actual_outcome == "ignore",
                "required_explanation_sources": sorted(required),
                "actual_explanation_sources": sorted(present),
                "explanation_source_recall": recall,
                "explanation_complete": explanation_complete,
                "agent_action": _agent_action(actual_outcome),
                "agent_workflow_complete": bool(exact_outcome and exact_delivery and explanation_complete),
                "human_action": case.human_action,
                "decision_reason": case.decision_reason,
                "manual_minutes": case.manual_minutes,
                "signalweave_minutes_model": case.signalweave_minutes,
                "modeled_minutes_saved": case.manual_minutes - case.signalweave_minutes,
                "confidence": result.confidence if result else None,
                "probabilities": result.probabilities if result else {},
                "summary": result.summary if result else None,
                "rationale": result.rationale if result else None,
                "evidence_findings": [finding.model_dump(mode="json") for finding in result.evidence_findings]
                if result
                else [],
                "evidence": [item.model_dump(mode="json") for item in result.evidence] if result else [],
                "telemetry": result.telemetry.model_dump(mode="json") if result else {},
                "elapsed_ms": elapsed_ms,
                "jev_metrics": metrics,
                "error": error,
            }
        )

    def summarize(selected: list[dict[str, Any]]) -> dict[str, Any]:
        latencies = [row["elapsed_ms"] for row in selected if row["error"] is None]
        expected_notify = sum(row["historical_outcome"] == "notify" for row in selected)
        baseline_pushes = sum(row["baseline_outcome"] == "notify" for row in selected)
        signalweave_pushes = sum(row["actual_outcome"] == "notify" for row in selected)
        exact = sum(row["exact_outcome"] for row in selected)
        delivery_exact = sum(row["exact_delivery"] for row in selected)
        complete = sum(row["agent_workflow_complete"] for row in selected)
        baseline_unnecessary = sum(row["baseline_unnecessary_push"] for row in selected)
        signalweave_unnecessary = sum(row["signalweave_unnecessary_push"] for row in selected)
        signalweave_unnecessary_alerts = sum(row["signalweave_unnecessary_alert"] for row in selected)
        baseline_missed = sum(row["baseline_missed_workflow"] for row in selected)
        signalweave_missed = sum(row["signalweave_missed_workflow"] for row in selected)
        return {
            "cases": len(selected),
            "historical_notify_cases": expected_notify,
            "movement_only_pushes": baseline_pushes,
            "signalweave_pushes": signalweave_pushes,
            "movement_only_unnecessary_pushes": baseline_unnecessary,
            "signalweave_unnecessary_pushes": signalweave_unnecessary,
            "signalweave_unnecessary_alerts": signalweave_unnecessary_alerts,
            "movement_only_missed_workflows": baseline_missed,
            "signalweave_missed_workflows": signalweave_missed,
            "movement_only_useful_pushes": sum(
                row["baseline_outcome"] == "notify" and row["historical_outcome"] == "notify"
                for row in selected
            ),
            "signalweave_useful_pushes": sum(
                row["actual_outcome"] == "notify" and row["historical_outcome"] == "notify"
                for row in selected
            ),
            "movement_only_push_precision": _percent(
                sum(row["baseline_outcome"] == "notify" and row["historical_outcome"] == "notify" for row in selected),
                baseline_pushes,
            ),
            "signalweave_push_precision": _percent(
                sum(row["actual_outcome"] == "notify" and row["historical_outcome"] == "notify" for row in selected),
                signalweave_pushes,
            ),
            "exact_outcome_count": exact,
            "exact_outcome_rate": _percent(exact, len(selected)),
            "exact_delivery_count": delivery_exact,
            "exact_delivery_rate": _percent(delivery_exact, len(selected)),
            "explanation_complete_count": sum(row["explanation_complete"] for row in selected),
            "explanation_complete_rate": _percent(sum(row["explanation_complete"] for row in selected), len(selected)),
            "agent_workflow_complete_count": complete,
            "agent_workflow_completion_rate": _percent(complete, len(selected)),
            "mean_explanation_source_recall": round(
                sum(row["explanation_source_recall"] for row in selected) / len(selected), 3
            )
            if selected
            else 0.0,
            "manual_minutes": sum(row["manual_minutes"] for row in selected),
            "signalweave_minutes_model": sum(row["signalweave_minutes_model"] for row in selected),
            "modeled_minutes_saved": sum(row["modeled_minutes_saved"] for row in selected),
            "median_elapsed_ms": round(median(latencies), 2) if latencies else None,
            "p95_elapsed_ms": _safe_p95(latencies),
            "errors": sum(row["error"] is not None for row in selected),
            "jev_requests": sum(row["jev_metrics"]["requests"] for row in selected),
            "jev_input_tokens": sum(row["jev_metrics"]["input_tokens"] for row in selected),
            "jev_output_tokens": sum(row["jev_metrics"]["output_tokens"] for row in selected),
        }

    splits = {
        split: summarize([row for row in rows if row["split"] == split]) for split in ("train", "validation", "holdout")
    }
    variants = {
        variant: summarize([row for row in rows if row["variant"] == variant])
        for variant in sorted({row["variant"] for row in rows})
    }
    report = {
        "schema_version": 1,
        "trial": "northstar-growth-historical-decision-replay",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "team": spec["team"],
        "decision_register": {
            "dataset_id": spec["dataset_id"],
            "spec_path": str(spec_path),
            "period_count": len(spec["periods"]),
            "variant_count": len(spec["variants"]),
            "case_count": len(cases),
            "splits": Counter(case.split for case in cases),
            "labels_withheld_from_jev": True,
        },
        "dataset": {
            "seed_dir": str(seed_dir),
            "current_complete_month": period_data.current_month,
            "baseline_month": period_data.baseline_month,
            "row_counts": period_data.row_counts,
            "observation_count_per_case": sum(
                len(resource.observations)
                for resource in _build_resources(period_data, cases[0].replay_case)
            ),
            "source_keys": sorted(
                resource.source_key
                for resource in _build_resources(period_data, cases[0].replay_case)
            ),
        },
        "design": {
            "signalweave_arm": "the production InsightEngine with live Jev and the same card/resources for every case",
            "control_arm": "movement-only push at the configured primary revenue threshold; no cross-source interpretation",
            "agent_workflow": "typed outcome -> configured delivery route -> evidence bundle with rationale and probabilities",
            "historical_labels": "simulated team dispositions in an external decision register, not sent to Jev",
            "promotion_split": "holdout is evaluated without changing the card or thresholds after train/validation",
        },
        "superset_validation": superset_validation or {"status": "not-run"},
        "compile": {
            "elapsed_ms": compile_elapsed_ms,
            "jev_metrics": compile_delta,
            "card_id": card.id,
            "compiled_by": compiled_plan.compiled_by,
        },
        "overall": summarize(rows),
        "splits": splits,
        "variants": variants,
        "cases": rows,
        "limitations": [
            "The Northstar rows are real local example fixtures; the dated movements and human dispositions are simulated and reviewable, not customer history.",
            "No Slack, email, or incident system was contacted; agent workflow completion means the typed route and evidence bundle were produced for a caller-owned delivery adapter.",
            "The movement-only control is intentionally simple and represents a current-state alerting pattern, not every possible baseline implementation.",
            "Modeled minutes saved are the decision-register estimates; source query time and downstream human response time are not presented as measured savings.",
            "One live Jev model run is evidence for this fixture and card, not a guarantee of correctness for every enterprise card without onboarding and holdout review.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    overall = report["overall"]
    lines = [
        "# Northstar Growth Analytics historical decision replay",
        "",
        "A Jev-backed replay of one simulated team's recurring operating decisions over the real local Northstar example rows.",
        "",
        f"- Cases: **{overall['cases']}** across **{report['decision_register']['period_count']} periods** and **{report['decision_register']['variant_count']} decision shapes**.",
        f"- Holdout exact outcome: **{report['splits']['holdout']['exact_outcome_rate']:.1%}**.",
        f"- Holdout evidence completeness: **{report['splits']['holdout']['explanation_complete_rate']:.1%}**.",
        f"- Holdout workflow completion: **{report['splits']['holdout']['agent_workflow_completion_rate']:.1%}**.",
        "",
        "## What the control misses",
        "",
        f"The movement-only control pushed **{overall['movement_only_pushes']}** times, including **{overall['movement_only_unnecessary_pushes']}** pushes that the team's register says should have been suppressed or investigated first. Its push precision was **{overall['movement_only_push_precision']:.1%}**.",
        "",
        "## SignalWeave + Jev",
        "",
        f"SignalWeave produced **{overall['signalweave_pushes']}** leadership pushes, **{overall['signalweave_unnecessary_alerts']}** unnecessary alerts or routes, and **{overall['signalweave_missed_workflows']}** missed non-ignore workflows. It returned a complete evidence bundle on **{overall['explanation_complete_rate']:.1%}** of cases and completed the typed agent workflow on **{overall['agent_workflow_completion_rate']:.1%}**.",
        "",
        "| Split | Exact outcome | Evidence complete | Workflow complete | Unnecessary pushes | Median ms | p95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split in ("train", "validation", "holdout"):
        item = report["splits"][split]
        lines.append(
            f"| {split} | {item['exact_outcome_rate']:.1%} | {item['explanation_complete_rate']:.1%} | {item['agent_workflow_completion_rate']:.1%} | {item['signalweave_unnecessary_alerts']} | {item['median_elapsed_ms']} | {item['p95_elapsed_ms']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The value under test is not metric detection alone. The control already detects movement. The SignalWeave arm is useful only when it turns the same movement into the right route, explains the cross-source evidence that made the route appropriate, and produces a bundle an agent can deliver without reopening every dashboard.",
            "",
            "## Limits",
            "",
            *[f"- {item}" for item in report["limitations"]],
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, required=True)
    parser.add_argument("--typesafe-key-file", type=Path)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    spec = load_spec(args.spec)
    cases = build_historical_cases(spec)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dataset_id": spec["dataset_id"],
                    "periods": len(spec["periods"]),
                    "variants": len(spec["variants"]),
                    "cases": len(cases),
                    "splits": Counter(case.split for case in cases),
                    "seed_dir": str(args.seed_dir),
                    "live_jev": False,
                },
                indent=2,
                default=str,
            )
        )
        return
    if not args.typesafe_key_file:
        parser.error("--typesafe-key-file is required unless --dry-run is supplied")
    report = asyncio.run(
        run_trial(
            seed_dir=args.seed_dir,
            output=args.output,
            typesafe_key_file=args.typesafe_key_file,
            spec_path=args.spec,
        )
    )
    print(json.dumps(report["overall"], indent=2))


if __name__ == "__main__":
    main()

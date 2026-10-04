"""Run a live Jev multi-step investigation trial over Northstar fixtures.

This is an evaluation harness, not workflow runtime code.  The card and source
snapshots are the same ones used by the single-step historical replay.  The
caller-owned agent is simulated explicitly:

1. evaluate the card with the initial source bundle;
2. follow the typed ``WorkflowHandoff`` without changing the card policy;
3. submit an immutable context snapshot from diagnostic systems; and
4. evaluate the same card again, linked to the parent decision receipt in the
   MCP integration tests.

Scenario labels and expected dispositions live in the external fixture and are
never sent to Jev.  The live run requires a TypeSafe API key; there is no local
heuristic or fake provider mode in the command-line path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from evaluations.northstar_growth_history_trial import (
    HistoricalCase,
    _build_resources,
    _load_period_data,
    build_historical_cases,
)
from evaluations.northstar_growth_history_trial import (
    load_spec as load_history_spec,
)
from evaluations.northstar_shadow_trial import SALES_SOURCE, _card
from signalweave.engine import InsightEngine
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    InsightCard,
    InsightResult,
    InvestigationMode,
    Outcome,
)
from signalweave.typesafe_adapter import JevJudger, JudgerMetrics, load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "examples" / "northstar-multistep-trial.json"
DEFAULT_HISTORY_SPEC = ROOT / "examples" / "northstar-growth-historical-decisions.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "northstar-multistep-trial.json"


def load_trial_spec(path: str | Path = DEFAULT_SPEC) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("multi-step trial fixture must have schema_version=1")
    card = payload.get("card")
    scenarios = payload.get("scenarios")
    if not isinstance(card, dict) or not isinstance(scenarios, list) or not scenarios:
        raise ValueError("multi-step trial fixture needs a card and scenarios")
    required = {"id", "base_case_id", "period_id", "expected_initial", "expected_final", "diagnostic_facts"}
    ids: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict) or required - set(scenario):
            raise ValueError(f"invalid multi-step scenario: {scenario!r}")
        if scenario["id"] in ids:
            raise ValueError(f"duplicate scenario id: {scenario['id']}")
        ids.add(str(scenario["id"]))
        Outcome(str(scenario["expected_initial"]))
        Outcome(str(scenario["expected_final"]))
        if not isinstance(scenario["diagnostic_facts"], list):
            raise ValueError(f"scenario {scenario['id']} diagnostic_facts must be a list")
        requirements = scenario.get("coverage_requirements", [])
        if not isinstance(requirements, list):
            raise ValueError(f"scenario {scenario['id']} coverage_requirements must be a list")
        for requirement in requirements:
            if not isinstance(requirement, dict):
                raise ValueError(f"scenario {scenario['id']} coverage requirement must be an object")
            if not str(requirement.get("source_key", "")).strip():
                raise ValueError(f"scenario {scenario['id']} coverage requirement needs source_key")
            if not isinstance(requirement.get("minimum_count"), int) or requirement["minimum_count"] < 1:
                raise ValueError(
                    f"scenario {scenario['id']} coverage requirement minimum_count must be a positive integer"
                )
            if not str(requirement.get("subject_type", "")).strip():
                raise ValueError(f"scenario {scenario['id']} coverage requirement needs subject_type")
    if not str(card.get("decision_guidance", "")).strip():
        raise ValueError("the trial card must define decision_guidance")
    if not str(card.get("follow_up_guidance", "")).strip():
        raise ValueError("the trial card must define follow_up_guidance")
    return payload


def _observation_coverage(
    scenario: dict[str, Any], resources: list[Any]
) -> list[dict[str, Any]]:
    """Check fixture-declared shape prerequisites before spending live credits."""

    by_source = {resource.source_key: resource for resource in resources}
    checks: list[dict[str, Any]] = []
    for requirement in scenario.get("coverage_requirements", []):
        source_key = str(requirement["source_key"])
        subject_type = str(requirement["subject_type"])
        resource = by_source.get(source_key)
        available_count = sum(
            observation.subject_type == subject_type
            for observation in (resource.observations if resource is not None else [])
        )
        minimum_count = int(requirement["minimum_count"])
        checks.append(
            {
                "source_key": source_key,
                "subject_type": subject_type,
                "available_count": available_count,
                "minimum_count": minimum_count,
                "passed": available_count >= minimum_count,
            }
        )
    return checks


def card_for_trial(spec: dict[str, Any]) -> InsightCard:
    base = _card()
    policy = spec["card"]
    sources = [
        source.model_copy(
            update={"required_comparison_keys": ["net-sales-change"]}
        )
        if source.key == SALES_SOURCE
        else source
        for source in base.sources
    ]
    return base.model_copy(
        update={
            "id": str(policy["id"]),
            "decision_guidance": str(policy["decision_guidance"]),
            "follow_up_guidance": str(policy["follow_up_guidance"]),
            "investigation_mode": InvestigationMode(
                str(policy.get("investigation_mode", "none"))
            ),
            "sources": sources,
            "delivery_methods": [
                *base.delivery_methods,
                DeliveryMethod(
                    key="data-trust",
                    outcome=Outcome.INSUFFICIENT_DATA,
                    label="Route to Data Trust",
                    destination="northstar://data-trust",
                    instructions="Repair or validate the source before interpreting business movement.",
                ),
            ],
        }
    )


def _metrics(judger: Any) -> JudgerMetrics:
    metrics = getattr(judger, "metrics", None)
    if metrics is None:
        return JudgerMetrics()
    return JudgerMetrics(
        requests=int(getattr(metrics, "requests", 0) or 0),
        input_tokens=int(getattr(metrics, "input_tokens", 0) or 0),
        output_tokens=int(getattr(metrics, "output_tokens", 0) or 0),
    )


def _delta(before: JudgerMetrics, after: JudgerMetrics) -> dict[str, int]:
    return {
        "requests": after.requests - before.requests,
        "input_tokens": after.input_tokens - before.input_tokens,
        "output_tokens": after.output_tokens - before.output_tokens,
    }


def _handoff_expectation(outcome: str) -> tuple[str, str]:
    return {
        "ignore": ("suppress", "complete"),
        "notify": ("deliver", "ready"),
        "escalate": ("deliver", "ready"),
        "investigate": ("retrieve_evidence", "pending"),
        "insufficient_data": ("repair_source", "blocked"),
    }[outcome]


def _facts(scenario: dict[str, Any]) -> ContextSnapshot | None:
    # The first list is what the bounded investigation discovers immediately;
    # the optional second list is the same caller-owned investigation returning
    # the validation/cause facts it was asked to retrieve before re-evaluation.
    # Omitting those facts would test an incomplete agent handoff, not the
    # SignalWeave multi-step contract.
    raw_facts = [
        *scenario["diagnostic_facts"],
        *(scenario.get("additional_diagnostic_facts") or []),
    ]
    if not raw_facts:
        return None
    return ContextSnapshot(
        provider="northstar-diagnostic-systems",
        version=f"{scenario['id']}:diagnostic-1",
        trust="trusted",
        facts=[ContextFact.model_validate(fact) for fact in raw_facts],
    )


def _case_lookup(history_spec: dict[str, Any]) -> dict[tuple[str, str], HistoricalCase]:
    return {
        (case.period_id, case.variant_id): case
        for case in build_historical_cases(history_spec)
    }


def _result_summary(result: InsightResult | None) -> dict[str, Any]:
    if result is None:
        return {
            "outcome": Outcome.INSUFFICIENT_DATA.value,
            "workflow": None,
            "delivery_method_keys": [],
            "confidence": None,
            "probabilities": {},
            "evidence_count": 0,
            "context_evidence_count": 0,
        }
    workflow = result.workflow.model_dump(mode="json") if result.workflow else None
    return {
        "outcome": result.outcome.value,
        "workflow": workflow,
        "delivery_method_keys": sorted(method.key for method in result.delivery_methods),
        "confidence": result.confidence,
        "probabilities": result.probabilities,
        "evidence_count": len(result.evidence),
        "context_evidence_count": sum(item.origin == "context" for item in result.evidence),
        "summary": result.summary,
        "rationale": result.rationale,
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
    }


async def run_trial(
    *,
    seed_dir: Path,
    output: Path,
    typesafe_key_file: Path,
    spec_path: Path = DEFAULT_SPEC,
    history_spec_path: Path = DEFAULT_HISTORY_SPEC,
    max_scenarios: int | None = None,
) -> dict[str, Any]:
    trial_spec = load_trial_spec(spec_path)
    history_spec = load_history_spec(history_spec_path)
    period_data = _load_period_data(seed_dir)
    lookup = _case_lookup(history_spec)
    card = card_for_trial(trial_spec)
    api_key = load_api_key(str(typesafe_key_file))
    if not api_key:
        raise ValueError("the TypeSafe API key file is empty")
    judger = JevJudger(api_key=api_key)
    engine = InsightEngine(judger=judger)
    selected_scenarios = trial_spec["scenarios"][:max_scenarios] if max_scenarios else trial_spec["scenarios"]

    compile_before = _metrics(judger)
    compile_started = time.perf_counter()
    compiled_plan = await engine.compile(card)
    compile_elapsed_ms = round((time.perf_counter() - compile_started) * 1000, 2)
    compile_metrics = _delta(compile_before, _metrics(judger))
    compiled_card = card.model_copy(update={"compiled_plan": compiled_plan})

    rows: list[dict[str, Any]] = []
    for scenario in selected_scenarios:
        key = (str(scenario["period_id"]), str(scenario["base_case_id"]))
        case = lookup.get(key)
        if case is None:
            raise ValueError(f"scenario {scenario['id']} does not match a history case: {key}")
        resources = _build_resources(period_data, case.replay_case)
        observation_coverage = _observation_coverage(scenario, resources)
        failed_coverage = [item for item in observation_coverage if not item["passed"]]
        if failed_coverage:
            raise ValueError(
                f"scenario {scenario['id']} cannot be evaluated because its source-shape "
                f"requirements are unmet: {failed_coverage}"
            )
        initial_before = _metrics(judger)
        initial_started = time.perf_counter()
        initial_result: InsightResult | None = None
        initial_error: str | None = None
        try:
            initial_result = (await engine.evaluate(compiled_card, resources)).result
        except Exception as error:  # noqa: BLE001 - provider failure is trial evidence
            initial_error = f"{type(error).__name__}: {error}"
        initial_elapsed_ms = round((time.perf_counter() - initial_started) * 1000, 2)
        initial_metrics = _delta(initial_before, _metrics(judger))
        initial_payload = _result_summary(initial_result)
        initial_expected = str(scenario["expected_initial"])
        initial_handoff = initial_payload["workflow"] or {}
        expected_initial_action, expected_initial_status = _handoff_expectation(initial_expected)
        initial_safe = not (
            initial_expected in {Outcome.INVESTIGATE.value, Outcome.INSUFFICIENT_DATA.value}
            and "leadership" in initial_payload["delivery_method_keys"]
        )

        context = _facts(scenario)
        final_before = _metrics(judger)
        final_started = time.perf_counter()
        final_result: InsightResult | None = None
        final_error: str | None = None
        if context is not None:
            try:
                final_result = (await engine.evaluate(
                    compiled_card, resources, context_override=context
                )).result
            except Exception as error:  # noqa: BLE001 - provider failure is trial evidence
                final_error = f"{type(error).__name__}: {error}"
        final_elapsed_ms = round((time.perf_counter() - final_started) * 1000, 2) if context else 0.0
        final_metrics = _delta(final_before, _metrics(judger)) if context else {"requests": 0, "input_tokens": 0, "output_tokens": 0}
        final_payload = _result_summary(final_result if context else initial_result)
        final_expected = str(scenario["expected_final"])
        final_handoff = final_payload["workflow"] or {}
        expected_final_action, expected_final_status = _handoff_expectation(final_expected)
        final_error = final_error or initial_error if context else initial_error
        initial_exact = initial_error is None and initial_payload["outcome"] == initial_expected
        initial_handoff_exact = initial_error is None and (
            initial_handoff.get("action") == expected_initial_action
            and initial_handoff.get("status") == expected_initial_status
        )
        final_exact = final_error is None and final_payload["outcome"] == final_expected
        final_handoff_exact = final_error is None and (
            final_handoff.get("action") == expected_final_action
            and final_handoff.get("status") == expected_final_status
        )
        context_returned = context is None or final_payload["context_evidence_count"] == len(context.facts)
        rows.append(
            {
                "scenario_id": scenario["id"],
                "period_id": scenario["period_id"],
                "base_case_id": scenario["base_case_id"],
                "expected_initial": initial_expected,
                "expected_final": final_expected,
                "initial": initial_payload,
                "final": final_payload,
                "initial_exact": initial_exact,
                "initial_handoff_exact": initial_handoff_exact,
                "initial_safe": initial_safe,
                "final_exact": final_exact,
                "final_handoff_exact": final_handoff_exact,
                "context_returned": context_returned,
                "context_fact_count": len(context.facts) if context else 0,
                "observation_coverage": observation_coverage,
                "initial_elapsed_ms": initial_elapsed_ms,
                "final_elapsed_ms": final_elapsed_ms,
                "initial_jev_metrics": initial_metrics,
                "final_jev_metrics": final_metrics,
                "initial_error": initial_error,
                "final_error": final_error,
            }
        )

    def count(key: str, selected: list[dict[str, Any]] = rows) -> int:
        return sum(bool(row.get(key)) for row in selected)

    multi_stage_rows = [row for row in rows if row["context_fact_count"] > 0]
    terminal_rows = [row for row in rows if row["context_fact_count"] == 0]
    all_latencies = [
        latency
        for row in rows
        for latency in (row["initial_elapsed_ms"], row["final_elapsed_ms"])
        if latency
    ]
    summary = {
        "scenarios": len(rows),
        "multi_stage_scenarios": len(multi_stage_rows),
        "terminal_single_step_scenarios": len(terminal_rows),
        "initial_exact_outcomes": count("initial_exact"),
        "initial_exact_rate": round(count("initial_exact") / len(rows), 3) if rows else 0.0,
        "initial_handoff_exact": count("initial_handoff_exact"),
        "initial_handoff_exact_rate": round(count("initial_handoff_exact") / len(rows), 3) if rows else 0.0,
        "initial_safety_passes": count("initial_safe"),
        "final_exact_outcomes": count("final_exact"),
        "final_exact_rate": round(count("final_exact") / len(rows), 3) if rows else 0.0,
        "final_handoff_exact": count("final_handoff_exact"),
        "final_handoff_exact_rate": round(count("final_handoff_exact") / len(rows), 3) if rows else 0.0,
        "context_returned": count("context_returned"),
        "context_returned_rate": round(count("context_returned") / len(rows), 3) if rows else 0.0,
        "multi_stage_final_exact": count("final_exact", multi_stage_rows),
        "multi_stage_final_exact_rate": round(count("final_exact", multi_stage_rows) / len(multi_stage_rows), 3) if multi_stage_rows else 0.0,
        "terminal_single_step_exact": count("initial_exact", terminal_rows),
        "terminal_single_step_exact_rate": round(count("initial_exact", terminal_rows) / len(terminal_rows), 3) if terminal_rows else 0.0,
        "median_stage_latency_ms": round(median(all_latencies), 2) if all_latencies else None,
        "jev_requests": judger.metrics.requests,
        "jev_input_tokens": judger.metrics.input_tokens,
        "jev_output_tokens": judger.metrics.output_tokens,
    }
    report = {
        "schema_version": 1,
        "trial": "northstar-live-jev-multistep-workflow",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_jev": True,
        "fixture": str(spec_path),
        "history_fixture": str(history_spec_path),
        "dataset": {
            "seed_dir": str(seed_dir),
            "row_counts": period_data.row_counts,
            "source_keys": sorted(resource.source_key for resource in _build_resources(period_data, next(iter(lookup.values())).replay_case)),
            "labels_withheld_from_jev": True,
        },
        "design": {
            "initial_stage": "Jev judges the owner-authored card over the current source bundle.",
            "agent_stage": "The caller-owned agent follows the typed handoff and supplies an immutable diagnostic context snapshot.",
            "final_stage": "Jev re-evaluates the same card with context evidence; SignalWeave does not execute Slack, ticketing, or remediation.",
            "single_step_compatibility": "Scenarios without diagnostic context retain the original one-evaluation path and receive additive workflow metadata.",
        },
        "card": card.execution_payload(),
        "compile": {"elapsed_ms": compile_elapsed_ms, "jev_metrics": compile_metrics},
        "overall": summary,
        "outcome_counts": dict(Counter(row["final"]["outcome"] for row in rows)),
        "cases": rows,
        "limitations": [
            "Northstar rows and the scenario dispositions are local, reviewable simulation fixtures, not a customer production log.",
            "Diagnostic context is supplied by a simulated caller-owned agent; this trial does not claim that SignalWeave discovers or verifies arbitrary external facts by itself.",
            "The live Jev sample demonstrates this card and evidence shape; generalized adoption still requires each team's own card review and holdout evaluation.",
            "No notification or remediation side effect was executed; delivery remains the caller's responsibility after the typed handoff says deliver.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    overall = report["overall"]
    lines = [
        "# Northstar live Jev multi-step workflow trial",
        "",
        "A live TypeSafe Jev replay of a caller-owned two-stage investigation loop over the local Northstar fixtures.",
        "",
        f"- Scenarios: **{overall['scenarios']}**; multi-stage: **{overall['multi_stage_scenarios']}**; terminal single-step: **{overall['terminal_single_step_scenarios']}**.",
        f"- Initial exact outcome: **{overall['initial_exact_rate']:.1%}**; initial handoff exact: **{overall['initial_handoff_exact_rate']:.1%}**.",
        f"- Final exact outcome: **{overall['final_exact_rate']:.1%}**; final handoff exact: **{overall['final_handoff_exact_rate']:.1%}**.",
        f"- Multi-stage final exact: **{overall['multi_stage_final_exact_rate']:.1%}**; single-step exact: **{overall['terminal_single_step_exact_rate']:.1%}**.",
        "",
        "| Scenario | Initial | Initial handoff | Final | Final handoff | Context returned |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["cases"]:
        initial = row["initial"]
        final = row["final"]
        lines.append(
            f"| {row['scenario_id']} | {initial['outcome']} ({'pass' if row['initial_exact'] else 'fail'}) | {initial.get('workflow', {}).get('action')} ({'pass' if row['initial_handoff_exact'] else 'fail'}) | {final['outcome']} ({'pass' if row['final_exact'] else 'fail'}) | {final.get('workflow', {}).get('action')} ({'pass' if row['final_handoff_exact'] else 'fail'}) | {'yes' if row['context_returned'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The multi-step capability is intentionally a handoff contract, not a second orchestration engine. Jev judges the current evidence and returns typed probabilities; the caller-owned agent retrieves diagnostic facts and submits them back to the same card. SignalWeave exposes the next action and blocks premature delivery when the outcome is investigate or insufficient_data.",
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
    parser.add_argument("--typesafe-key-file", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--history-spec", type=Path, default=DEFAULT_HISTORY_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-scenarios", type=int)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(
        run_trial(
            seed_dir=args.seed_dir,
            output=args.output,
            typesafe_key_file=args.typesafe_key_file,
            spec_path=args.spec,
            history_spec_path=args.history_spec,
            max_scenarios=args.max_scenarios,
        )
    )
    print(json.dumps(report["overall"], indent=2))
    if args.strict and (
        report["overall"]["initial_exact_rate"] < 1.0
        or report["overall"]["final_exact_rate"] < 1.0
        or report["overall"]["initial_handoff_exact_rate"] < 1.0
        or report["overall"]["final_handoff_exact_rate"] < 1.0
    ):
        raise SystemExit("strict multi-step trial gate failed")


if __name__ == "__main__":
    main()

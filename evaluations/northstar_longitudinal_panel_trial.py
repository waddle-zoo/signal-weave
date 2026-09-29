"""Run a longitudinal, live-Jev Northstar panel trial.

This evaluation asks a harder question than whether one card classifies one
snapshot correctly: can a persistent card support a simulated analytical
operating cadence over many months while different role agents hand work to
one another safely?

The panel is simulated as independent role checks around the production
InsightEngine. Jev remains the only semantic decision provider. Expected
dispositions and feedback labels live in the external fixture and never enter
the Jev state. No delivery side effect is executed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.northstar_growth_history_trial import (
    HistoricalCase,
    _build_resources,
    _load_period_data,
    _safe_error,
    build_historical_cases,
    movement_only_outcome,
)
from evaluations.northstar_growth_history_trial import (
    _metrics as history_metrics,
)
from evaluations.northstar_growth_history_trial import (
    load_spec as load_history_spec,
)
from evaluations.northstar_multistep_trial import card_for_trial, load_trial_spec
from signalweave.engine import InsightEngine
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    InsightCard,
    InsightResult,
    Outcome,
)
from signalweave.typesafe_adapter import JevJudger, JudgerMetrics, load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "examples" / "northstar-longitudinal-panel.json"
DEFAULT_HISTORY_SPEC = ROOT / "examples" / "northstar-growth-historical-decisions.json"
DEFAULT_CARD_SPEC = ROOT / "examples" / "northstar-multistep-trial.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "northstar-longitudinal-panel.json"


def load_panel_spec(path: str | Path = DEFAULT_SPEC) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("longitudinal panel fixture must have schema_version=1")
    months = payload.get("months")
    templates = payload.get("decision_templates")
    panel = payload.get("panel")
    if not isinstance(months, list) or not months:
        raise ValueError("longitudinal panel fixture needs months")
    if not isinstance(templates, list) or not templates:
        raise ValueError("longitudinal panel fixture needs decision_templates")
    if not isinstance(panel, list) or not panel:
        raise ValueError("longitudinal panel fixture needs panel roles")
    required_template_fields = {
        "id",
        "base_case_id",
        "expected_initial",
        "expected_final",
        "feedback_kind",
        "manual_minutes",
        "signalweave_minutes",
        "feedback_note",
    }
    template_ids: set[str] = set()
    for template in templates:
        if required_template_fields - set(template):
            raise ValueError(f"invalid decision template: {template!r}")
        if template["id"] in template_ids:
            raise ValueError(f"duplicate decision template: {template['id']}")
        template_ids.add(str(template["id"]))
        Outcome(str(template["expected_initial"]))
        Outcome(str(template["expected_final"]))
    month_ids = {str(month["id"]) for month in months}
    if len(month_ids) != len(months):
        raise ValueError("longitudinal panel months must have unique ids")
    if any("period_id" not in month for month in months):
        raise ValueError("each longitudinal month needs a period_id")
    return payload


def _load_card(
    card_spec_path: str | Path,
    *,
    panel_spec: dict[str, Any],
) -> InsightCard:
    base = card_for_trial(load_trial_spec(card_spec_path))
    data_trust = DeliveryMethod(
        key="data-trust",
        outcome=Outcome.INSUFFICIENT_DATA,
        label="Analytics + Data Trust",
        destination="northstar://analytics-data-trust",
        instructions="Repair or validate the source before interpreting business movement.",
    )
    return base.model_copy(
        update={
            "id": "northstar-growth-longitudinal-v1",
            "delivery_methods": [*base.delivery_methods, data_trust],
            "owner": str(panel_spec["panel"][0]["id"]),
        }
    )


def _context_snapshot(
    template: dict[str, Any],
    month_id: str,
    facts_by_case: dict[str, list[dict[str, Any]]],
    *,
    stage: str,
) -> ContextSnapshot | None:
    facts = facts_by_case.get(str(template["base_case_id"]), [])
    if not facts:
        return None
    return ContextSnapshot(
        provider="northstar-panel-diagnostic-agents",
        version=f"{month_id}:{template['id']}:{stage}",
        trust="trusted",
        facts=[
            ContextFact.model_validate({**fact, "fact_id": f"{month_id}:{stage}:{fact['fact_id']}"})
            for fact in facts
        ],
    )


def _metrics(judger: Any) -> JudgerMetrics:
    return history_metrics(judger)


def _delta(before: JudgerMetrics, after: JudgerMetrics) -> dict[str, int]:
    return {
        "requests": after.requests - before.requests,
        "input_tokens": after.input_tokens - before.input_tokens,
        "output_tokens": after.output_tokens - before.output_tokens,
    }


def _handoff(outcome: str, *, has_guidance: bool = True) -> tuple[str, str]:
    if outcome == Outcome.IGNORE.value:
        return "suppress", "complete"
    if outcome in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}:
        return "deliver", "ready"
    if outcome == Outcome.INSUFFICIENT_DATA.value:
        return "repair_source", "blocked"
    return ("retrieve_evidence", "pending") if has_guidance else ("deliver", "ready")


def _result_payload(result: InsightResult | None) -> dict[str, Any]:
    if result is None:
        return {
            "outcome": Outcome.INSUFFICIENT_DATA.value,
            "delivery_method_keys": [],
            "workflow": None,
            "evidence": [],
            "source_keys": [],
            "context_evidence_count": 0,
            "error": "evaluation did not produce a result",
        }
    return {
        "outcome": result.outcome.value,
        "delivery_method_keys": sorted(method.key for method in result.delivery_methods),
        "workflow": result.workflow.model_dump(mode="json") if result.workflow else None,
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "source_keys": sorted(set(result.source_keys)),
        "context_evidence_count": sum(item.origin == "context" for item in result.evidence),
        "confidence": result.confidence,
        "probabilities": result.probabilities,
        "summary": result.summary,
        "rationale": result.rationale,
        "telemetry": result.telemetry.model_dump(mode="json"),
    }


def _panel_review(
    *,
    card: InsightCard,
    template: dict[str, Any],
    initial: dict[str, Any],
    final: dict[str, Any],
    context_fact_count: int,
    required_sources: set[str],
    actual_evidence_sources: set[str],
) -> dict[str, dict[str, Any]]:
    expected_initial = str(template["expected_initial"])
    expected_final = str(template["expected_final"])
    initial_action, initial_status = _handoff(expected_initial)
    final_action, final_status = _handoff(expected_final)
    initial_workflow = initial.get("workflow") or {}
    final_workflow = final.get("workflow") or {}
    initial_safe = not (
        expected_initial in {Outcome.INVESTIGATE.value, Outcome.INSUFFICIENT_DATA.value}
        and "leadership" in initial.get("delivery_method_keys", [])
    )
    final_safe = not (
        expected_final in {Outcome.INVESTIGATE.value, Outcome.INSUFFICIENT_DATA.value}
        and "leadership" in final.get("delivery_method_keys", [])
    )
    evidence_recall = (
        len(required_sources & actual_evidence_sources) / len(required_sources)
        if required_sources
        else 1.0
    )
    card_ok = all(
        bool(value.strip())
        for value in (card.what_to_watch, card.why_watch, card.decision_guidance, card.follow_up_guidance)
    ) and bool(card.sources) and bool(card.delivery_methods)
    return {
        "curator": {"pass": card_ok, "reason": "card intent, policy, follow-up guidance, sources, and routes are present"},
        "analytics": {
            "pass": (
                initial.get("outcome") == expected_initial
                and final.get("outcome") == expected_final
                and (not context_fact_count or final.get("context_evidence_count") == context_fact_count)
                and evidence_recall == 1.0
            ),
            "reason": "outcomes and evidence coverage match the owner-labeled workflow",
        },
        "data_trust": {
            "pass": (
                (expected_final != Outcome.INSUFFICIENT_DATA.value)
                or final_workflow.get("action") == "repair_source"
            ),
            "reason": "source failures remain blocked and repairable rather than interpreted",
        },
        "operations": {
            "pass": (
                initial_workflow.get("action") == initial_action
                and initial_workflow.get("status") == initial_status
                and final_workflow.get("action") == final_action
                and final_workflow.get("status") == final_status
                and initial_safe
                and final_safe
            ),
            "reason": "the typed handoffs match the stage and do not expose unsafe leadership delivery",
        },
        "communications": {
            "pass": (
                (expected_final == Outcome.NOTIFY.value and "leadership" in final.get("delivery_method_keys", []))
                or (expected_final != Outcome.NOTIFY.value and "leadership" not in final.get("delivery_method_keys", []))
            ),
            "reason": "leadership receives only final notify outcomes",
        },
        "leadership": {
            "pass": expected_final != Outcome.NOTIFY.value or final_workflow.get("action") == "deliver",
            "reason": "a leadership acknowledgement is only simulated after a deliver handoff",
        },
        "feedback": {
            "pass": bool(template.get("feedback_note")) and template.get("feedback_kind") == "useful",
            "reason": "caller-owned feedback is recorded separately from Jev state",
        },
        "adversarial": {
            "pass": initial_safe and final_safe and evidence_recall == 1.0,
            "reason": "independent safety checks find no premature action or evidence omission",
        },
    }


async def run_trial(
    *,
    seed_dir: Path,
    output: Path,
    typesafe_key_file: Path,
    spec_path: Path = DEFAULT_SPEC,
    history_spec_path: Path = DEFAULT_HISTORY_SPEC,
    card_spec_path: Path = DEFAULT_CARD_SPEC,
    max_months: int | None = None,
) -> dict[str, Any]:
    panel_spec = load_panel_spec(spec_path)
    history_spec = load_history_spec(history_spec_path)
    card_spec = load_trial_spec(card_spec_path)
    history_cases = {
        (case.period_id, case.variant_id): case
        for case in build_historical_cases(history_spec)
    }
    diagnostic_by_case = {
        str(scenario["base_case_id"]): list(scenario.get("diagnostic_facts", []))
        for scenario in card_spec["scenarios"]
    }
    additional_diagnostic_by_case = {
        str(scenario["base_case_id"]): list(scenario.get("additional_diagnostic_facts", []))
        for scenario in card_spec["scenarios"]
    }
    templates = panel_spec["decision_templates"]
    months = panel_spec["months"][:max_months] if max_months else panel_spec["months"]
    period_data = _load_period_data(seed_dir)
    card = _load_card(card_spec_path, panel_spec=panel_spec)
    api_key = load_api_key(str(typesafe_key_file))
    if not api_key:
        raise ValueError("the TypeSafe API key file is empty")
    judger = JevJudger(api_key=api_key)
    engine = InsightEngine(judger=judger)
    compile_before = _metrics(judger)
    compile_plan = await engine.compile(card)
    compile_metrics = _delta(compile_before, _metrics(judger))
    compiled_card = card.model_copy(update={"compiled_plan": compile_plan})

    rows: list[dict[str, Any]] = []
    panel_counts: Counter[str] = Counter()
    month_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for month in months:
        month_id = str(month["id"])
        period_id = str(month["period_id"])
        for template in templates:
            scenario = {
                **template,
                **(month.get("overrides", {}).get(str(template["id"]), {})),
            }
            lookup_key = (period_id, str(scenario["base_case_id"]))
            case: HistoricalCase | None = history_cases.get(lookup_key)
            if case is None:
                raise ValueError(f"no historical case for month {month_id}: {lookup_key}")
            resources = _build_resources(period_data, case.replay_case)
            initial_before = _metrics(judger)
            initial_error: str | None = None
            initial_result: InsightResult | None = None
            started = datetime.now(timezone.utc)
            try:
                initial_result = (await engine.evaluate(compiled_card, resources)).result
            except Exception as error:  # noqa: BLE001 - provider failure is trial evidence
                initial_error = _safe_error(error)
            initial_elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
            initial_metrics = _delta(initial_before, _metrics(judger))
            initial = _result_payload(initial_result)

            context = _context_snapshot(
                scenario,
                month_id,
                diagnostic_by_case,
                stage="diagnostic-1",
            )
            final_before = _metrics(judger)
            final_error: str | None = None
            final_result = initial_result
            final_elapsed_ms = 0.0
            context_stage_count = 0
            if context is not None:
                final_started = datetime.now(timezone.utc)
                try:
                    final_result = (await engine.evaluate(
                        compiled_card, resources, context_override=context
                    )).result
                except Exception as error:  # noqa: BLE001 - provider failure is trial evidence
                    final_error = _safe_error(error)
                final_elapsed_ms = (datetime.now(timezone.utc) - final_started).total_seconds() * 1000
                context_stage_count = 1
                additional_facts = additional_diagnostic_by_case.get(
                    str(scenario["base_case_id"]), []
                )
                if final_result is not None and final_result.outcome == Outcome.INVESTIGATE and additional_facts:
                    combined_facts = {
                        str(scenario["base_case_id"]): [
                            *diagnostic_by_case.get(str(scenario["base_case_id"]), []),
                            *additional_facts,
                        ]
                    }
                    second_context = _context_snapshot(
                        scenario,
                        month_id,
                        combined_facts,
                        stage="diagnostic-2",
                    )
                    second_started = datetime.now(timezone.utc)
                    try:
                        final_result = (await engine.evaluate(
                            compiled_card,
                            resources,
                            context_override=second_context,
                        )).result
                        context = second_context
                    except Exception as error:  # noqa: BLE001 - provider failure is trial evidence
                        final_error = _safe_error(error)
                    final_elapsed_ms += (
                        datetime.now(timezone.utc) - second_started
                    ).total_seconds() * 1000
                    context_stage_count = 2
            final = _result_payload(final_result)
            template_required_sources = set(case.required_explanation_sources)
            actual_evidence_sources = {
                str(item.get("source_key"))
                for item in final.get("evidence", [])
                if item.get("source_key")
            }
            panel = _panel_review(
                card=compiled_card,
                template=scenario,
                initial=initial,
                final=final,
                context_fact_count=len(context.facts) if context else 0,
                required_sources=template_required_sources,
                actual_evidence_sources=actual_evidence_sources,
            )
            for role, review in panel.items():
                panel_counts[role] += int(review["pass"])
            baseline = movement_only_outcome(
                resources,
                threshold_percent=float(history_spec["card_policy"]["movement_only_baseline"]["threshold_percent"]),
                missing_primary=str(history_spec["card_policy"]["movement_only_baseline"]["missing_primary"]),
            )
            expected_final = str(scenario["expected_final"])
            signalweave_automatic = final["outcome"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
            baseline_automatic = baseline in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
            parent_id = f"panel-receipt-{month_id}-{scenario['id']}-initial"
            row = {
                "workflow_id": f"{month_id}:{scenario['id']}",
                "month_id": month_id,
                "period_id": period_id,
                "template_id": scenario["id"],
                "card_id": card.id,
                "card_version": card.version,
                "parent_receipt_id": parent_id if context else None,
                "expected_initial": scenario["expected_initial"],
                "expected_final": expected_final,
                "initial": initial,
                "final": final,
                "initial_error": initial_error,
                "final_error": final_error,
                "initial_exact": initial_error is None and initial["outcome"] == scenario["expected_initial"],
                "final_exact": final_error is None and final["outcome"] == expected_final,
                "initial_handoff_exact": initial_error is None and (
                    (initial.get("workflow") or {}).get("action"),
                    (initial.get("workflow") or {}).get("status"),
                ) == _handoff(str(scenario["expected_initial"])),
                "final_handoff_exact": final_error is None and (
                    (final.get("workflow") or {}).get("action"),
                    (final.get("workflow") or {}).get("status"),
                ) == _handoff(expected_final),
                "baseline_outcome": baseline,
                "baseline_unnecessary_automatic": baseline_automatic and expected_final not in {Outcome.NOTIFY.value, Outcome.ESCALATE.value},
                "signalweave_unnecessary_automatic": signalweave_automatic and expected_final not in {Outcome.NOTIFY.value, Outcome.ESCALATE.value},
                "signalweave_missed_automatic": expected_final in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} and not signalweave_automatic,
                "required_explanation_sources": sorted(template_required_sources),
                "actual_evidence_sources": sorted(actual_evidence_sources),
                "evidence_source_recall": round(
                    len(template_required_sources & actual_evidence_sources) / len(template_required_sources), 3
                ) if template_required_sources else 1.0,
                "context_fact_count": len(context.facts) if context else 0,
                "context_evidence_count": final.get("context_evidence_count", 0),
                "context_stage_count": context_stage_count,
                "panel": panel,
                "panel_agreement": sum(review["pass"] for review in panel.values()) == len(panel),
                "feedback": {
                    "recorded_by": "feedback-steward",
                    "kind": scenario["feedback_kind"],
                    "note": scenario["feedback_note"],
                },
                "modeled_manual_minutes": int(template["manual_minutes"]),
                "modeled_signalweave_minutes": int(template["signalweave_minutes"]),
                "modeled_minutes_saved": int(template["manual_minutes"]) - int(template["signalweave_minutes"]),
                "initial_elapsed_ms": round(initial_elapsed_ms, 2),
                "final_elapsed_ms": round(final_elapsed_ms, 2),
                "initial_jev_metrics": initial_metrics,
                "final_jev_metrics": _delta(final_before, _metrics(judger)) if context else {"requests": 0, "input_tokens": 0, "output_tokens": 0},
            }
            rows.append(row)
            month_rows[month_id].append(row)

    def summarize(selected: list[dict[str, Any]]) -> dict[str, Any]:
        latencies = [
            latency
            for row in selected
            for latency in (row["initial_elapsed_ms"], row["final_elapsed_ms"])
            if latency
        ]
        denominator = len(selected)
        return {
            "workflows": denominator,
            "initial_exact": sum(row["initial_exact"] for row in selected),
            "initial_exact_rate": round(sum(row["initial_exact"] for row in selected) / denominator, 3) if denominator else 0.0,
            "final_exact": sum(row["final_exact"] for row in selected),
            "final_exact_rate": round(sum(row["final_exact"] for row in selected) / denominator, 3) if denominator else 0.0,
            "initial_handoff_exact": sum(row["initial_handoff_exact"] for row in selected),
            "final_handoff_exact": sum(row["final_handoff_exact"] for row in selected),
            "panel_agreement": sum(row["panel_agreement"] for row in selected),
            "panel_agreement_rate": round(sum(row["panel_agreement"] for row in selected) / denominator, 3) if denominator else 0.0,
            "evidence_complete": sum(row["evidence_source_recall"] == 1.0 for row in selected),
            "mean_evidence_source_recall": round(sum(row["evidence_source_recall"] for row in selected) / denominator, 3) if denominator else 0.0,
            "unsafe_automatic_actions": sum(row["signalweave_unnecessary_automatic"] for row in selected),
            "missed_automatic_actions": sum(row["signalweave_missed_automatic"] for row in selected),
            "modeled_manual_minutes": sum(row["modeled_manual_minutes"] for row in selected),
            "modeled_signalweave_minutes": sum(row["modeled_signalweave_minutes"] for row in selected),
            "modeled_minutes_saved": sum(row["modeled_minutes_saved"] for row in selected),
            "median_stage_latency_ms": round(statistics.median(latencies), 2) if latencies else None,
            "p95_stage_latency_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
            "errors": sum(bool(row["initial_error"] or row["final_error"]) for row in selected),
        }

    monthly = {month_id: summarize(items) for month_id, items in month_rows.items()}
    panel_summary = {
        role: {
            "passed_reviews": count,
            "reviews": len(rows),
            "pass_rate": round(count / len(rows), 3) if rows else 0.0,
        }
        for role, count in sorted(panel_counts.items())
    }
    baseline_automatic = sum(
        row["baseline_outcome"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} for row in rows
    )
    signalweave_automatic = sum(
        row["final"]["outcome"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} for row in rows
    )
    expected_automatic = sum(
        row["expected_final"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} for row in rows
    )
    report = {
        "schema_version": 1,
        "trial": "northstar-longitudinal-panel-signalweave",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_jev": True,
        "company": panel_spec["company"],
        "design": {
            "months": len(months),
            "decision_templates": len(templates),
            "workflows": len(rows),
            "panel_agents": len(panel_spec["panel"]),
            "persistent_card_id": card.id,
            "persistent_card_version": card.version,
            "labels_withheld_from_jev": True,
            "agent_model": "caller-owned role simulation around the production InsightEngine; Jev is the only semantic decision provider",
            "baseline": "movement-only primary revenue threshold from the historical decision register",
            "multi_step": "initial Jev outcome -> simulated analytics/data-trust retrieval -> trusted context re-evaluation when diagnostic facts exist",
        },
        "panel": panel_spec["panel"],
        "card": card.execution_payload(),
        "compile": {"jev_metrics": compile_metrics, "compiled_by": compile_plan.compiled_by},
        "overall": summarize(rows),
        "baseline_comparison": {
            "expected_automatic_workflows": expected_automatic,
            "baseline_automatic_workflows": baseline_automatic,
            "signalweave_automatic_workflows": signalweave_automatic,
            "baseline_unnecessary_automatic": sum(row["baseline_unnecessary_automatic"] for row in rows),
            "signalweave_unnecessary_automatic": sum(row["signalweave_unnecessary_automatic"] for row in rows),
            "signalweave_missed_automatic": sum(row["signalweave_missed_automatic"] for row in rows),
            "baseline_automatic_precision": round(
                sum(row["baseline_outcome"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} and row["expected_final"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} for row in rows) / baseline_automatic,
                3,
            ) if baseline_automatic else 0.0,
            "signalweave_automatic_precision": round(
                sum(row["final"]["outcome"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} and row["expected_final"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value} for row in rows) / signalweave_automatic,
                3,
            ) if signalweave_automatic else 0.0,
        },
        "panel_summary": panel_summary,
        "monthly": monthly,
        "outcomes": dict(Counter(row["final"]["outcome"] for row in rows)),
        "workflows": rows,
        "limitations": [
            "This is a simulated eight-month operating history over local Northstar fixtures; it is not a customer production log.",
            "Role agents, feedback, acknowledgements, and delivery are simulated around the production engine; no Slack, email, or remediation side effect was executed.",
            "Expected outcomes and feedback labels are external owner rubrics and are not proof that a real team would choose the same disposition without validating its card.",
            "Modeled minutes are scenario assumptions, not measured production savings; query latency and downstream human response time are not included.",
            "A passing panel demonstrates this card, evidence shape, and workflow contract across the trial; it does not establish universal enterprise correctness.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    overall = report["overall"]
    comparison = report["baseline_comparison"]
    lines = [
        "# Northstar longitudinal panel trial",
        "",
        "A live Jev simulation of an eight-month analytical operating cadence with a persistent card and caller-owned role agents.",
        "",
        f"- Workflows: **{overall['workflows']}** across **{report['design']['months']} months**.",
        f"- Final exact outcomes: **{overall['final_exact_rate']:.1%}**; final handoffs exact: **{overall['final_handoff_exact']}/{overall['workflows']}**.",
        f"- Panel agreement: **{overall['panel_agreement_rate']:.1%}**; evidence source recall: **{overall['mean_evidence_source_recall']:.1%}**.",
        f"- Automatic-action precision: baseline **{comparison['baseline_automatic_precision']:.1%}**, SignalWeave **{comparison['signalweave_automatic_precision']:.1%}**.",
        f"- Unnecessary automatic actions: baseline **{comparison['baseline_unnecessary_automatic']}**, SignalWeave **{comparison['signalweave_unnecessary_automatic']}**.",
        f"- Modeled minutes saved: **{overall['modeled_minutes_saved']}**.",
        "",
        "| Month | Workflows | Exact final | Panel agreement | Unsafe automatic | Missed automatic |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for month_id, summary in report["monthly"].items():
        lines.append(
            f"| {month_id} | {summary['workflows']} | {summary['final_exact_rate']:.1%} | {summary['panel_agreement_rate']:.1%} | {summary['unsafe_automatic_actions']} | {summary['missed_automatic_actions']} |"
        )
    lines.extend(
        [
            "",
            "## What this establishes",
            "",
            "The trial tests the operating property SignalWeave is meant to provide: a human-authored card can be carried through repeated periods, turn a bounded evidence bundle into the right typed handoff, pause for caller-owned diagnostics when needed, and return a final bundle that an existing agent can deliver without reopening every dashboard.",
            "",
            "## What it does not establish",
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
    parser.add_argument("--card-spec", type=Path, default=DEFAULT_CARD_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-months", type=int)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(
        run_trial(
            seed_dir=args.seed_dir,
            output=args.output,
            typesafe_key_file=args.typesafe_key_file,
            spec_path=args.spec,
            history_spec_path=args.history_spec,
            card_spec_path=args.card_spec,
            max_months=args.max_months,
        )
    )
    print(json.dumps(report["overall"], indent=2))
    if args.strict and (
        report["overall"]["final_exact_rate"] < 1.0
        or report["overall"]["panel_agreement_rate"] < 1.0
        or report["overall"]["mean_evidence_source_recall"] < 1.0
        or report["baseline_comparison"]["signalweave_unnecessary_automatic"] != 0
        or report["baseline_comparison"]["signalweave_missed_automatic"] != 0
    ):
        raise SystemExit("strict longitudinal panel trial gate failed")


if __name__ == "__main__":
    main()

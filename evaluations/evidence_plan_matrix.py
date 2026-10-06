"""Exercise the generic evidence-plan contract over deliberately varied cases.

This evaluation is intentionally outside ``src``.  It does not pretend to measure
Jev's semantic accuracy: the ``ProtocolJudger`` fixture supplies typed judgments so
the matrix can isolate SignalWeave's contract, evidence accounting, and safety
gates.  Live Jev evaluations are separate and must be reported as such.

The cases use unrelated adapter names and resource shapes to catch accidental
Superset coupling.  Each scenario checks a different boundary:

* cross-source, cross-vendor evidence;
* optional versus required source failure;
* empty or stale source snapshots;
* missing, fulfilled, unanswerable, and unknown evidence slots;
* trusted versus unverified caller context; and
* single-step versus multi-step handoffs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalweave.engine import InsightEngine
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    Evidence,
    InsightCard,
    InsightResult,
    Observation,
    Outcome,
    QuestionStatus,
    ResourceContract,
    ResourceSnapshot,
    SourceRef,
    WatchStatus,
)


@dataclass(frozen=True)
class JudgmentFixture:
    outcome: Outcome
    questions: tuple[QuestionStatus, ...] = ()
    watches: tuple[WatchStatus, ...] = ()


class ProtocolJudger:
    """A typed semantic boundary fixture, not an alternative production evaluator."""

    name = "protocol-coverage-fixture"

    def __init__(self, fixtures: dict[str, JudgmentFixture]) -> None:
        self.fixtures = fixtures

    async def compile_plan(self, state: dict[str, Any], card: InsightCard) -> dict[str, Any]:
        del state
        return {
            "capabilities": [
                "percent_change",
                "freshness_check",
                "cross_source_comparison",
                "question_checks",
                "watch_for_checks",
            ],
            "baseline": card.comparison_windows[0],
        }

    async def judge(
        self,
        state: dict[str, Any],
        card: InsightCard,
        plan: Any,
        observations: list[Observation],
    ) -> InsightResult:
        del plan
        fixture = self.fixtures[card.id]
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        question_results = [
            {
                "key": f"question_{index}",
                "question": question,
                "status": status,
                "probability": {
                    QuestionStatus.SUPPORTED: 0.92,
                    QuestionStatus.NOT_SUPPORTED: 0.08,
                    QuestionStatus.UNKNOWN: 0.50,
                }[status],
            }
            for index, (question, status) in enumerate(
                zip(card.questions, fixture.questions, strict=True), start=1
            )
        ]
        watch_results = [
            {
                "key": f"watch_{index}",
                "watch_for": watch,
                "status": status,
                "probability": {
                    WatchStatus.PRESENT: 0.92,
                    WatchStatus.ABSENT: 0.08,
                    WatchStatus.UNKNOWN: 0.50,
                }[status],
            }
            for index, (watch, status) in enumerate(
                zip(card.watch_for, fixture.watches, strict=True), start=1
            )
        ]
        return InsightResult(
            card_id=card.id,
            outcome=fixture.outcome,
            summary="Typed protocol fixture result.",
            rationale="Structural evidence-plan test; not a semantic model score.",
            confidence=0.92,
            probabilities={fixture.outcome.value: 0.92},
            question_results=question_results,
            watch_results=watch_results,
            evidence=evidence,
            observations=observations,
            source_keys=[item.source_key for item in observations],
            evaluator=self.name,
        )


def _source(
    key: str,
    adapter: str,
    resource: str,
    label: str,
    *,
    required: bool = True,
) -> SourceRef:
    return SourceRef(
        key=key,
        adapter=adapter,
        resource=resource,
        label=label,
        required=required,
    )


def _card(
    card_id: str,
    sources: list[SourceRef],
    *,
    questions: list[str] | None = None,
    watch_for: list[str] | None = None,
    follow_up: str = "",
    delivery_outcomes: tuple[Outcome, ...] = (Outcome.NOTIFY, Outcome.INVESTIGATE, Outcome.ESCALATE),
) -> InsightCard:
    methods = [
        DeliveryMethod(
            key=f"route-{outcome.value}",
            outcome=outcome,
            label=outcome.value.title(),
            destination=f"test://{outcome.value}",
        )
        for outcome in delivery_outcomes
    ]
    return InsightCard(
        id=card_id,
        title=card_id.replace("-", " ").title(),
        what_to_watch="Identify material changes in the owner-selected operating context.",
        why_watch="Provide enough evidence for the caller-owned agent to choose the next safe action.",
        questions=questions or [],
        watch_for=watch_for or [],
        follow_up_guidance=follow_up,
        decision_guidance="Use the typed outcome and evidence plan; do not invent missing evidence.",
        sources=sources,
        delivery_methods=methods,
        owner="coverage-test",
    )


def _resource(
    source: SourceRef,
    *,
    status: str = "healthy",
    populated: bool = True,
    stale: bool = False,
) -> ResourceSnapshot:
    observations: list[Observation] = []
    evidence: list[Evidence] = []
    if populated:
        freshness = "stale: source timestamp exceeds card SLA" if stale else "fresh"
        observations.append(
            Observation(
                source_key=source.key,
                subject_id=f"{source.key}-signal",
                subject_label=source.label,
                metric="material_change",
                current=82.0,
                baseline=100.0,
                change_pct=-18.0,
                freshness=freshness,
                attributes={"source_status": status},
            )
        )
        evidence.append(
            Evidence(
                source_key=source.key,
                subject_id=f"{source.key}-signal",
                subject_label=source.label,
                statement=f"{source.label} contains the current comparison-window evidence.",
            )
        )
    return ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=observations,
        evidence=evidence,
        error="source unavailable" if status == "failed" else None,
        contract=ResourceContract(source_status=status),
    )


def _facts(*slot_keys: str, trust: str = "trusted") -> ContextSnapshot:
    return ContextSnapshot(
        provider="caller-owned-context",
        version="matrix-v1",
        trust=trust,
        facts=[
            ContextFact(
                fact_id=f"fact-{index}",
                slot_key=slot_key,
                subject_ref=f"context|{slot_key}",
                relation="supports",
                statement=f"Caller evidence for {slot_key}.",
                provenance=["matrix-fixture"],
            )
            for index, slot_key in enumerate(slot_keys, start=1)
        ],
    )


def _case_definitions() -> list[tuple[InsightCard, list[ResourceSnapshot], ContextSnapshot | None, JudgmentFixture, dict[str, Any]]]:
    cases: list[tuple[InsightCard, list[ResourceSnapshot], ContextSnapshot | None, JudgmentFixture, dict[str, Any]]] = []

    cross_sources = [
        _source("bi", "superset", "dashboard:growth", "Growth dashboard"),
        _source("semantic", "looker", "explore:commerce", "Commerce explore"),
        _source("notebook", "hex", "project:campaign", "Campaign notebook"),
        _source("warehouse", "trino", "query:funnel", "Funnel query"),
    ]
    card = _card(
        "cross-source-complete",
        cross_sources,
        questions=["Did the conversion funnel change?", "Is the campaign a plausible driver?"],
        watch_for=["A broad movement across the selected sources."],
    )
    cases.append(
        (
            card,
            [_resource(source) for source in cross_sources],
            None,
            JudgmentFixture(
                Outcome.NOTIFY,
                (QuestionStatus.SUPPORTED, QuestionStatus.SUPPORTED),
                (WatchStatus.PRESENT,),
            ),
            {"plan": "complete", "outcome": "notify", "workflow": "deliver"},
        )
    )

    optional_sources = [
        _source("primary", "cloudwatch", "metric:latency", "Latency metrics"),
        _source("deployments", "airflow", "dag:deployments", "Deployment history", required=False),
    ]
    card = _card(
        "optional-source-failure",
        optional_sources,
        questions=["Did latency move materially?"],
        watch_for=["A broad customer-impacting regression."],
    )
    cases.append(
        (
            card,
            [_resource(optional_sources[0]), _resource(optional_sources[1], status="failed")],
            None,
            JudgmentFixture(Outcome.NOTIFY, (QuestionStatus.SUPPORTED,), (WatchStatus.PRESENT,)),
            {
                "plan": "complete",
                "outcome": "notify",
                "optional_slot": "unavailable",
                "workflow": "deliver",
            },
        )
    )

    multistep_sources = [
        _source("sales", "looker", "dashboard:sales", "Sales dashboard"),
        _source("funnel", "trino", "query:purchase-funnel", "Purchase funnel"),
        _source("campaign", "hex", "project:campaign-analysis", "Campaign analysis"),
    ]
    multistep_card = _card(
        "multistep-missing",
        multistep_sources,
        questions=["What explains the movement?", "Did the campaign change conversion?"],
        watch_for=["A material movement requiring investigation."],
        follow_up="Gather the missing diagnostic evidence, then re-evaluate this same card.",
    )
    # This scenario represents a human-authored multi-step workflow whose
    # diagnostic answers must exist before delivery; ordinary questions and
    # watch prompts remain advisory by default.
    multistep_card.evidence_requirements = {
        "question:1": True,
        "question:2": True,
        "watch:1": True,
    }
    cases.append(
        (
            multistep_card,
            [_resource(source) for source in multistep_sources],
            None,
            JudgmentFixture(
                Outcome.NOTIFY,
                (QuestionStatus.UNKNOWN, QuestionStatus.UNKNOWN),
                (WatchStatus.UNKNOWN,),
            ),
            {"plan": "incomplete", "outcome": "investigate", "workflow": "retrieve_evidence"},
        )
    )

    complete_context_card = multistep_card.model_copy(update={"id": "multistep-complete"})
    cases.append(
        (
            complete_context_card,
            [_resource(source) for source in multistep_sources],
            _facts("question:1", "question:2", "watch:1"),
            JudgmentFixture(
                Outcome.NOTIFY,
                # Context association alone no longer asserts semantic completion.
                (QuestionStatus.SUPPORTED, QuestionStatus.SUPPORTED),
                (WatchStatus.PRESENT,),
            ),
            {"plan": "complete", "outcome": "notify", "workflow": "deliver"},
        )
    )

    unanswered_card = multistep_card.model_copy(update={"id": "multistep-unanswered"})
    cases.append(
        (
            unanswered_card,
            [_resource(source) for source in multistep_sources],
            None,
            JudgmentFixture(
                Outcome.NOTIFY,
                (QuestionStatus.NOT_SUPPORTED, QuestionStatus.SUPPORTED),
                (WatchStatus.PRESENT,),
            ),
            {
                "plan": "incomplete",
                "unanswered": "question:1",
                "outcome": "investigate",
                "workflow": "retrieve_evidence",
            },
        )
    )

    failed_source = _source("primary", "dbt", "model:revenue", "Revenue model")
    failed_card = _card(
        "required-source-failure",
        [failed_source],
        questions=["Did revenue move?"],
        follow_up="Repair the source and re-evaluate.",
    )
    cases.append(
        (
            failed_card,
            [_resource(failed_source, status="failed")],
            None,
            JudgmentFixture(Outcome.NOTIFY, (QuestionStatus.SUPPORTED,)),
            {"plan": "blocked", "outcome": "insufficient_data", "workflow": "repair_source"},
        )
    )

    unverified_card = _card(
        "unverified-context",
        [_source("ops", "pagerduty", "service:checkout", "Checkout service")],
        questions=["Is the service the likely owner?"],
        watch_for=["A customer-impacting incident."],
        follow_up="Verify the context, then re-evaluate.",
    )
    cases.append(
        (
            unverified_card,
            [_resource(unverified_card.sources[0])],
            _facts("question:1", "watch:1", trust="unverified"),
            JudgmentFixture(Outcome.NOTIFY, (QuestionStatus.SUPPORTED,), (WatchStatus.PRESENT,)),
            {"plan": "complete", "outcome": "investigate", "workflow": "retrieve_evidence"},
        )
    )

    unknown_slot_card = _card(
        "unknown-slot-warning",
        [_source("quality", "datahub", "dataset:orders", "Orders dataset")],
        questions=["Is the dataset fresh?"],
    )
    cases.append(
        (
            unknown_slot_card,
            [_resource(unknown_slot_card.sources[0])],
            _facts("question:1", "question:99"),
            JudgmentFixture(Outcome.NOTIFY, (QuestionStatus.SUPPORTED,)),
            {
                "plan": "complete",
                "outcome": "notify",
                "warning": "unknown evidence slot",
                "workflow": "deliver",
            },
        )
    )

    single_step_card = _card(
        "single-step-arbitrary-shape",
        [
            _source("hr", "workday", "report:retention", "People retention report"),
            _source("support", "salesforce", "queue:cases", "Support cases"),
        ],
        questions=[],
        watch_for=[],
        delivery_outcomes=(Outcome.INVESTIGATE, Outcome.NOTIFY),
    )
    cases.append(
        (
            single_step_card,
            [_resource(source) for source in single_step_card.sources],
            None,
            JudgmentFixture(Outcome.INVESTIGATE),
            {"plan": "complete", "outcome": "investigate", "workflow": "deliver"},
        )
    )

    stale_source = _source("metric", "prometheus", "query:availability", "Availability")
    stale_card = _card(
        "stale-source",
        [stale_source],
        questions=["Is availability degraded?"],
        delivery_outcomes=(Outcome.NOTIFY, Outcome.ESCALATE, Outcome.INVESTIGATE),
    )
    cases.append(
        (
            stale_card,
            [_resource(stale_source, stale=True)],
            None,
            JudgmentFixture(Outcome.NOTIFY, (QuestionStatus.SUPPORTED,)),
            {"plan": "complete", "outcome": "escalate", "workflow": "deliver"},
        )
    )

    empty_source = _source("lake", "iceberg", "table:events", "Events table")
    empty_card = _card(
        "empty-required-source",
        [empty_source],
        questions=["Is the event stream healthy?"],
        follow_up="Retrieve a fresh snapshot and re-evaluate.",
    )
    cases.append(
        (
            empty_card,
            [_resource(empty_source, populated=False)],
            None,
            JudgmentFixture(Outcome.NOTIFY, (QuestionStatus.UNKNOWN,)),
            {"plan": "blocked", "outcome": "insufficient_data", "workflow": "repair_source"},
        )
    )

    return cases


async def run_matrix() -> dict[str, Any]:
    definitions = _case_definitions()
    fixtures = {card.id: fixture for card, _, _, fixture, _ in definitions}
    engine = InsightEngine(ProtocolJudger(fixtures))
    rows: list[dict[str, Any]] = []
    for card, resources, context, _, expected in definitions:
        result = (await engine.evaluate(card, resources, context_override=context)).result
        plan = result.evidence_plan
        workflow = result.workflow
        slots = {slot.key: slot for slot in plan.slots} if plan else {}
        checks = {
            "plan_status": plan is not None and plan.status == expected["plan"],
            "outcome": result.outcome.value == expected["outcome"],
            "workflow": workflow is not None and workflow.action == expected["workflow"],
        }
        if "optional_slot" in expected:
            checks["optional_slot"] = slots.get("source:deployments") is not None and slots["source:deployments"].status == expected["optional_slot"]
        if "unanswered" in expected:
            checks["unanswered"] = (
                plan is not None and expected["unanswered"] in plan.missing_slot_keys
                and expected["unanswered"] not in plan.conflicting_slot_keys
            )
        if "warning" in expected:
            checks["warning"] = any("unknown evidence slots" in warning for warning in (plan.warnings if plan else []))
        rows.append(
            {
                "case": card.id,
                "adapters": sorted({source.adapter for source in card.sources}),
                "plan_status": plan.status if plan else None,
                "outcome": result.outcome.value,
                "workflow": workflow.action if workflow else None,
                "missing_slots": plan.missing_slot_keys if plan else [],
                "conflicting_slots": plan.conflicting_slot_keys if plan else [],
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    all_adapters = sorted({adapter for row in rows for adapter in row["adapters"]})
    return {
        "evaluation": "evidence-plan-generalization-matrix",
        "semantic_evaluator": "protocol-coverage-fixture",
        "case_count": len(rows),
        "passed_cases": sum(row["passed"] for row in rows),
        "failed_cases": [row["case"] for row in rows if not row["passed"]],
        "adapter_count": len(all_adapters),
        "adapters": all_adapters,
        "claims_supported": [
            "Evidence plans are derived from arbitrary card sources, questions, and watch items.",
            "Required and optional source failures have different safety outcomes.",
            "Caller-owned facts can fulfill named slots without changing the card policy.",
            "Conflicting, unknown, stale, and unverified evidence are visible and fail closed.",
            "Single-step cards retain a terminal handoff while multi-step cards expose retrieval work.",
        ],
        "claims_not_supported": [
            "This fixture does not measure Jev semantic accuracy or calibration.",
            "This fixture does not prove production adapter credentials, source freshness, or query cost.",
        ],
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_matrix())
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if not report["failed_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

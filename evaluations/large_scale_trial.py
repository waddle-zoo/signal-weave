"""Run a live Jev trial over generated, externally-configured company domains.

This is a trial harness, not production decision logic. It deliberately keeps
the oracle here with the generated cases so the production engine never sees
the expected label. Every evaluation still uses InsightEngine and JevJudger.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any

from signalweave.engine import InsightEngine
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    Observation,
    Outcome,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.typesafe_adapter import JevJudger, load_api_key

TRIAL_CLASSES = (
    "corroborated_notify",
    "explained_ignore",
    "contradictory_investigate",
    "stale_escalation",
    "missing_baseline",
    "source_failure",
)


@dataclass(frozen=True)
class TrialCase:
    case_id: str
    domain_id: str
    domain_name: str
    trial_class: str
    resources: list[ResourceSnapshot]
    card: InsightCard
    expected_outcome: Outcome
    expected_delivery_methods: list[str]


@dataclass(frozen=True)
class TrialResult:
    case_id: str
    domain_id: str
    trial_class: str
    expected_outcome: str
    actual_outcome: str
    expected_delivery_methods: list[str]
    actual_delivery_methods: list[str]
    outcome_correct: bool
    decision_correct: bool
    confidence: float | None
    elapsed_ms: float
    requests: int
    error: str | None = None


def load_domains(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text())
    domains = payload.get("domains")
    if not isinstance(domains, list) or not domains:
        raise ValueError("trial domain file must contain a non-empty domains list")
    return domains


def _delivery_methods(domain: dict[str, Any]) -> list[DeliveryMethod]:
    key = str(domain["delivery_target"])
    label = str(domain["name"]) + " Operations"
    return [
        DeliveryMethod(
            key=f"{key}-notify",
            outcome=Outcome.NOTIFY,
            label=label,
            destination=f"slack://{key}",
            instructions=f"Notify {label} when the owner-defined corroborating evidence supports a non-urgent action.",
        ),
        DeliveryMethod(
            key=f"{key}-escalate",
            outcome=Outcome.ESCALATE,
            label=label,
            destination=f"slack://{key}",
            instructions=f"Escalate to {label} for a severe or untrustworthy condition requiring urgent attention.",
        ),
    ]


def _watch_items(primary_title: str, context_title: str, trial_class: str) -> list[str]:
    common = [
        f"{primary_title} is available with a comparable baseline.",
        f"{context_title} provides relevant context for interpreting {primary_title}.",
    ]
    if trial_class == "corroborated_notify":
        return common + [
            f"{primary_title} decreases at least 15% while {context_title} increases at least 20%.",
            "The related signals are fresh and support a non-urgent action.",
        ]
    if trial_class == "explained_ignore":
        return common + [
            f"{primary_title} and {context_title} decrease together within 5 percentage points.",
            "The paired movement is expected and does not need notification.",
        ]
    if trial_class == "contradictory_investigate":
        return common + [
            f"{primary_title} decreases at least 15% without {context_title} corroborating it.",
            "The movement is ambiguous and should be reviewed before notification.",
        ]
    if trial_class == "stale_escalation":
        return common + [f"The source for {primary_title} is stale before values are interpreted."]
    if trial_class == "missing_baseline":
        return common + [f"{primary_title} has no comparable baseline."]
    return common + [f"The source for {primary_title} fails or times out."]


def _questions(primary_title: str, context_title: str, trial_class: str) -> list[str]:
    if trial_class == "stale_escalation":
        return [f"Can {primary_title} be trusted while its source is stale?"]
    if trial_class == "missing_baseline":
        return [f"Can the movement in {primary_title} be compared safely?"]
    if trial_class == "source_failure":
        return [f"Can the card be answered when the {primary_title} source fails?"]
    return [
        f"Does {context_title} explain or corroborate the movement in {primary_title}?",
        f"Is there enough evidence to choose an action for {primary_title}?",
    ]


def _observation(
    source_key: str,
    subject_id: str,
    subject_label: str,
    metric: str,
    *,
    current: float | None,
    baseline: float | None,
    change_pct: float | None,
    freshness: str | None = None,
) -> Observation:
    return Observation(
        source_key=source_key,
        subject_id=subject_id,
        subject_label=subject_label,
        subject_type="metric",
        metric=metric,
        unit="normalized units",
        current=current,
        baseline=baseline,
        change_pct=change_pct,
        freshness=freshness,
        source_url=f"trial://{source_key}/{subject_id}",
    )


def build_trial_cases(domains: list[dict[str, Any]]) -> list[TrialCase]:
    cases: list[TrialCase] = []
    for index, domain in enumerate(domains):
        domain_id = str(domain["id"])
        domain_name = str(domain["name"])
        primary_metric = str(domain["primary_metric"])
        primary_title = str(domain["primary_title"])
        context_metric = str(domain["context_metric"])
        context_title = str(domain["context_title"])
        methods = _delivery_methods(domain)
        primary_baseline = 100.0 + index * 17.0
        context_baseline = 1000.0 + index * 53.0

        for trial_class in TRIAL_CLASSES:
            trial_context_metric = context_metric
            trial_context_title = context_title
            if trial_class == "explained_ignore":
                trial_context_metric = "expected_operating_cycle"
                trial_context_title = f"Expected {domain_name} operating cycle"
            primary_id = f"{domain_id}-{trial_class}-primary"
            context_id = f"{domain_id}-{trial_class}-context"
            primary_current = primary_baseline * 0.82
            context_current = context_baseline
            primary_change = -18.0
            context_change = 0.0
            freshness = None
            primary_baseline_value: float | None = primary_baseline
            context_baseline_value: float | None = context_baseline
            primary_current_value: float | None = primary_current
            context_current_value: float | None = context_current
            primary_error = None
            expected_outcome = Outcome.INVESTIGATE

            if trial_class == "corroborated_notify":
                context_current = context_baseline * 1.35
                context_change = 35.0
                context_current_value = context_current
                expected_outcome = Outcome.NOTIFY
            elif trial_class == "explained_ignore":
                context_current = context_baseline * 0.82
                context_change = -18.0
                context_current_value = context_current
                expected_outcome = Outcome.IGNORE
            elif trial_class == "contradictory_investigate":
                context_current = context_baseline * 1.01
                context_change = 1.0
                context_current_value = context_current
            elif trial_class == "stale_escalation":
                freshness = f"stale: {24 + index}h"
                primary_current_value = primary_baseline
                primary_change = 0.0
                context_current_value = context_baseline
                context_change = 0.0
                expected_outcome = Outcome.ESCALATE
            elif trial_class == "missing_baseline":
                primary_baseline_value = None
                context_baseline_value = None
                primary_change = None
                context_change = None
                expected_outcome = Outcome.INSUFFICIENT_DATA
            elif trial_class == "source_failure":
                primary_current_value = None
                primary_baseline_value = None
                primary_change = None
                primary_error = f"{primary_title} query timed out"
                expected_outcome = Outcome.INSUFFICIENT_DATA

            primary_source_key = f"{domain_id}-{trial_class}-primary-source"
            context_source_key = f"{domain_id}-{trial_class}-context-source"
            context_adapter = ("superset", "sql", "airflow", "table")[index % 4]
            context_resource_prefix = {
                "superset": "dashboard",
                "sql": "query",
                "airflow": "dag",
                "table": "table",
            }[context_adapter]
            primary_observations = [] if primary_error else [
                _observation(
                    primary_source_key,
                    primary_id,
                    primary_title,
                    primary_metric,
                    current=primary_current_value,
                    baseline=primary_baseline_value,
                    change_pct=primary_change,
                    freshness=freshness,
                )
            ]
            context_observations = [
                _observation(
                    context_source_key,
                    context_id,
                    trial_context_title,
                    trial_context_metric,
                    current=context_current_value,
                    baseline=context_baseline_value,
                    change_pct=context_change,
                )
            ]
            primary_resource = ResourceSnapshot(
                source_key=primary_source_key,
                adapter="superset",
                resource=f"dashboard:{domain_id}-{trial_class}",
                title=f"{domain_name} primary signal",
                description=f"Saved Superset dashboard signal for {domain_name}.",
                observations=primary_observations,
                error=primary_error,
                metadata={
                    "provider": "superset",
                    "dashboard_id": f"{domain_id}-{trial_class}",
                    "chart_ids": [primary_id],
                    "related_source_key": context_source_key,
                },
                source_url=f"trial://superset/dashboard/{domain_id}-{trial_class}",
            )
            context_resource = ResourceSnapshot(
                source_key=context_source_key,
                adapter=context_adapter,
                resource=f"{context_resource_prefix}:{domain_id}-{trial_class}-context",
                title=trial_context_title,
                description=f"Generated {context_adapter} context for {domain_name}.",
                observations=context_observations,
                evidence=[
                    Evidence(
                        source_key=context_source_key,
                        subject_id=context_id,
                        subject_label=trial_context_title,
                        statement=(
                            "The card's corroborating context is supplied by the "
                            f"{context_adapter} adapter."
                        ),
                        values={"adapter": context_adapter},
                        source_url=f"trial://{context_adapter}/{context_id}",
                    )
                ],
                metadata={
                    "provider": context_adapter,
                    "related_source_key": primary_source_key,
                },
                source_url=f"trial://{context_adapter}/{context_id}",
            )
            card_id = f"trial-card-{domain_id}-{trial_class}"
            card = InsightCard(
                id=card_id,
                title=f"{domain_name} signal insight",
                what_to_watch=(
                    f"{primary_title} in the {domain_name} operating context, using {trial_context_title} as related evidence."
                ),
                why_watch=(
                    "Decide whether the signal is expected, actionable, ambiguous, or unsafe to interpret, with a path for the owning team to respond."
                ),
                watch_for=_watch_items(primary_title, trial_context_title, trial_class),
                questions=_questions(primary_title, trial_context_title, trial_class),
                sources=[
                    SourceRef(
                        key=primary_source_key,
                        adapter="superset",
                        resource=f"dashboard:{domain_id}-{trial_class}",
                        label=f"{domain_name} primary Superset dashboard",
                        parameters={"chart_ids": [primary_id]},
                    ),
                    SourceRef(
                        key=context_source_key,
                        adapter=context_adapter,
                        resource=f"{context_resource_prefix}:{domain_id}-{trial_class}-context",
                        label=trial_context_title,
                    ),
                ],
                comparison_windows=["previous_period", "trailing_4_period_average"],
                action_confidence_threshold=0.40 if trial_class == "explained_ignore" else 0.70,
                delivery_methods=methods,
            )
            expected_delivery_methods = (
                [
                    next(
                        method.key
                        for method in methods
                        if method.outcome == expected_outcome
                    )
                ]
                if expected_outcome in {Outcome.NOTIFY, Outcome.ESCALATE}
                else []
            )
            cases.append(
                TrialCase(
                    case_id=card_id,
                    domain_id=domain_id,
                    domain_name=domain_name,
                    trial_class=trial_class,
                    resources=[primary_resource, context_resource],
                    card=card,
                    expected_outcome=expected_outcome,
                    expected_delivery_methods=expected_delivery_methods,
                )
            )
    return cases


async def run_trial(
    cases: list[TrialCase], *, repeats: int, concurrency: int, api_key: str
) -> tuple[list[TrialResult], dict[str, Any]]:
    judger = JevJudger(api_key=api_key)
    engine = InsightEngine(judger=judger)
    semaphore = asyncio.Semaphore(concurrency)
    jobs = [(case, repeat + 1) for repeat in range(repeats) for case in cases]

    async def evaluate(case: TrialCase, repeat: int) -> TrialResult:
        del repeat
        async with semaphore:
            before = judger.metrics.requests
            started = time.perf_counter()
            try:
                run = await engine.evaluate(case.card, case.resources)
                result = run.result
                actual_outcome = result.outcome.value
                actual_delivery_methods = [method.key for method in result.delivery_methods]
                error = None
                confidence = result.confidence
            except Exception as exc:  # noqa: BLE001 - trial must record provider failures
                actual_outcome = Outcome.INSUFFICIENT_DATA.value
                actual_delivery_methods = []
                error = f"{type(exc).__name__}: {exc}"
                confidence = None
            return TrialResult(
                case_id=case.case_id,
                domain_id=case.domain_id,
                trial_class=case.trial_class,
                expected_outcome=case.expected_outcome.value,
                actual_outcome=actual_outcome,
                expected_delivery_methods=case.expected_delivery_methods,
                actual_delivery_methods=actual_delivery_methods,
                outcome_correct=actual_outcome == case.expected_outcome.value,
                decision_correct=(
                    actual_outcome == case.expected_outcome.value
                    and actual_delivery_methods == case.expected_delivery_methods
                ),
                confidence=confidence,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
                requests=judger.metrics.requests - before,
                error=error,
            )

    results = list(await asyncio.gather(*(evaluate(case, repeat) for case, repeat in jobs)))
    metrics = {
        "requests": judger.metrics.requests,
        "input_tokens": judger.metrics.input_tokens,
        "output_tokens": judger.metrics.output_tokens,
    }
    return results, metrics


def summarize(results: list[TrialResult], metrics: dict[str, Any], repeats: int) -> dict[str, Any]:
    latencies = sorted(result.elapsed_ms for result in results)
    p95_index = max(0, int(len(latencies) * 0.95) - 1)
    confidences = sorted(result.confidence for result in results if result.confidence is not None)
    by_class: dict[str, list[TrialResult]] = defaultdict(list)
    for result in results:
        by_class[result.trial_class].append(result)
    by_case: dict[str, list[TrialResult]] = defaultdict(list)
    for result in results:
        by_case[result.case_id].append(result)
    automatic_outcomes = {Outcome.IGNORE.value, Outcome.NOTIFY.value, Outcome.ESCALATE.value}
    urgent_outcomes = {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
    expected_actions = {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
    wrong_automatic = [
        result
        for result in results
        if result.actual_outcome in automatic_outcomes
        and result.actual_outcome != result.expected_outcome
    ]
    missed_actions = [
        result
        for result in results
        if result.expected_outcome in expected_actions
        and result.actual_outcome != result.expected_outcome
    ]
    false_urgent = [
        result
        for result in results
        if result.actual_outcome in urgent_outcomes
        and result.expected_outcome not in urgent_outcomes
    ]
    return {
        "cases": len(results),
        "unique_cases": len({result.case_id for result in results}),
        "repeats": repeats,
        "outcome_accuracy": round(sum(result.outcome_correct for result in results) / len(results), 4),
        "exact_decision_accuracy": round(sum(result.decision_correct for result in results) / len(results), 4),
        "errors": sum(result.error is not None for result in results),
        "wrong_automatic_actions": len(wrong_automatic),
        "missed_actionable_cases": len(missed_actions),
        "false_urgent_actions": len(false_urgent),
        "stable_unique_cases": sum(
            len({(item.actual_outcome, tuple(item.actual_delivery_methods)) for item in items}) == 1
            for items in by_case.values()
        ),
        "confidence_min": round(min(confidences), 4) if confidences else None,
        "confidence_median": round(median(confidences), 4) if confidences else None,
        "confidence_p95": round(confidences[max(0, int(len(confidences) * 0.95) - 1)], 4)
        if confidences
        else None,
        "median_ms": round(median(latencies), 2),
        "p95_ms": round(latencies[p95_index], 2),
        "requests": metrics["requests"],
        "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["output_tokens"],
        "class_summary": {
            key: {
                "cases": len(items),
                "outcome_accuracy": round(sum(item.outcome_correct for item in items) / len(items), 4),
                "exact_decision_accuracy": round(sum(item.decision_correct for item in items) / len(items), 4),
                "errors": sum(item.error is not None for item in items),
            }
            for key, items in sorted(by_class.items())
        },
        "domain_outcome_counts": {
            domain: dict(Counter(item.actual_outcome for item in results if item.domain_id == domain))
            for domain in sorted({item.domain_id for item in results})
        },
    }


def render_table(summary: dict[str, Any]) -> str:
    lines = [
        "SignalWeave large-scale live Jev trial",
        "=======================================",
        f"cases={summary['cases']} unique_cases={summary['unique_cases']} repeats={summary['repeats']}",
        f"outcome_accuracy={summary['outcome_accuracy']:.1%} exact_decision_accuracy={summary['exact_decision_accuracy']:.1%}",
        f"median_ms={summary['median_ms']:.2f} p95_ms={summary['p95_ms']:.2f} requests={summary['requests']} errors={summary['errors']}",
        f"wrong_automatic_actions={summary['wrong_automatic_actions']} missed_actionable_cases={summary['missed_actionable_cases']} false_urgent_actions={summary['false_urgent_actions']}",
        f"stable_unique_cases={summary['stable_unique_cases']}/{summary['unique_cases']} confidence_min={summary['confidence_min']:.2f} confidence_median={summary['confidence_median']:.2f} confidence_p95={summary['confidence_p95']:.2f}",
        f"input_tokens={summary['input_tokens']} output_tokens={summary['output_tokens']}",
        "",
        "class                       cases  outcome  exact  errors",
        "--------------------------  -----  -------  -----  ------",
    ]
    for key, value in summary["class_summary"].items():
        lines.append(
            f"{key:<26}  {value['cases']:>5}  {value['outcome_accuracy']:.1%}  "
            f"{value['exact_decision_accuracy']:.1%}  {value['errors']:>6}"
        )
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    domains = load_domains(args.domains)
    cases = build_trial_cases(domains)
    if args.dry_run:
        print(json.dumps({"domains": len(domains), "cases": len(cases), "classes": list(TRIAL_CLASSES)}, indent=2))
        return 0
    api_key = load_api_key()
    if not api_key:
        raise RuntimeError("large-scale trial requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")
    results, metrics = await run_trial(
        cases, repeats=args.repeats, concurrency=args.concurrency, api_key=api_key
    )
    summary = summarize(results, metrics, args.repeats)
    print(render_table(summary))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"summary": summary, "results": [asdict(result) for result in results]}, indent=2) + "\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domains", default="examples/trial-domains.json")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 10:
        raise SystemExit("--repeats must be between 1 and 10")
    if args.concurrency < 1 or args.concurrency > 32:
        raise SystemExit("--concurrency must be between 1 and 32")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

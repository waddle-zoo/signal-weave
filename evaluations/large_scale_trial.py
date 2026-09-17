"""Run a live Jev trial over generated, externally-configured company domains.

This is a trial harness, not production decision logic. It deliberately keeps
the oracle here with the generated cases so the production engine never sees
the expected label. Every evaluation still uses MonitorEngine and JevJudger.
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

from semantic_monitor.engine import MonitorEngine
from semantic_monitor.models import (
    ChartSnapshot,
    DashboardSnapshot,
    MonitorCard,
    Observation,
    Outcome,
    Recipient,
)
from semantic_monitor.typesafe_adapter import JevJudger, load_api_key

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
    dashboard: DashboardSnapshot
    card: MonitorCard
    expected_outcome: Outcome
    expected_recipient: str | None


@dataclass(frozen=True)
class TrialResult:
    case_id: str
    domain_id: str
    trial_class: str
    expected_outcome: str
    actual_outcome: str
    expected_recipient: str | None
    actual_recipient: str | None
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


def _guidance(recipient: str, trial_class: str) -> dict[str, str]:
    common = {
        "investigate": "Use when the signal is ambiguous, contradictory, or incomplete; do not send an automatic notification.",
        "notify": f"Use when the owner-defined corroborating evidence supports a non-urgent action by {recipient}.",
        "escalate": f"Use for a severe or untrustworthy condition requiring urgent attention from {recipient}.",
        "ignore": "Use when the movement is expected, explained by context, or not decision-relevant.",
        "insufficient_data": "Use when source evidence is unavailable or cannot be compared safely.",
    }
    if trial_class == "corroborated_notify":
        common["notify"] = f"Choose notify only when the primary chart change_pct is at or below -15 and the related chart change_pct is at or above 20; both support action by {recipient}."
    elif trial_class == "explained_ignore":
        common["ignore"] = "Choose ignore when the primary and related chart change_pct values are both negative and within 5 percentage points; this paired movement is expected and needs no notification."
    elif trial_class == "contradictory_investigate":
        common["investigate"] = "Choose investigate when the primary chart change_pct is at or below -15 but the related chart change_pct is between -5 and 5; the movement is not corroborated."
    elif trial_class == "stale_escalation":
        common["escalate"] = f"Use when the source is stale; urgent attention from {recipient} is required before interpreting the movement."
    return common


def _recipient(domain: dict[str, Any]) -> Recipient:
    key = str(domain["recipient"])
    return Recipient(key=key, label=str(domain["name"]) + " Operations", destination=f"slack://{key}")


def _allowed_outcomes(trial_class: str) -> list[Outcome]:
    if trial_class == "corroborated_notify":
        return [Outcome.NOTIFY, Outcome.INVESTIGATE]
    if trial_class == "explained_ignore":
        return [Outcome.IGNORE, Outcome.INVESTIGATE]
    if trial_class == "stale_escalation":
        return [Outcome.ESCALATE, Outcome.INVESTIGATE]
    if trial_class in {"missing_baseline", "source_failure"}:
        return [Outcome.INSUFFICIENT_DATA, Outcome.INVESTIGATE]
    return [Outcome.INVESTIGATE, Outcome.NOTIFY, Outcome.IGNORE]


def _materiality_definition(
    primary_title: str, context_title: str, trial_class: str
) -> str:
    if trial_class == "corroborated_notify":
        return (
            f"Treat the movement as material when {primary_title} decreases at least 15% "
            f"versus its comparable baseline and {context_title} increases at least 20%; "
            "both charts must have fresh, comparable evidence."
        )
    if trial_class == "explained_ignore":
        return (
            f"Treat the movement as expected when {primary_title} and {context_title} "
            "decrease together within 5 percentage points; do not notify on that paired movement."
        )
    if trial_class == "contradictory_investigate":
        return (
            f"Treat the movement as ambiguous when {primary_title} decreases at least 15% "
            f"but {context_title} changes less than 5%; require review instead of notifying."
        )
    if trial_class == "stale_escalation":
        return f"Treat the source as unsafe to interpret when {primary_title} is stale; escalate before using its values."
    if trial_class == "missing_baseline":
        return f"Treat {primary_title} as not comparable when its current value has no baseline."
    return f"Treat {primary_title} as unavailable when its source query fails; do not interpret the remaining chart as sufficient."


def _trial_intent(
    domain_name: str, primary_title: str, context_title: str, trial_class: str
) -> str:
    prefix = f"Monitor {primary_title} on the {domain_name} operating dashboard. "
    if trial_class == "corroborated_notify":
        return prefix + (
            f"For this policy, a lower {primary_title} is adverse and a higher {context_title} "
            f"is corroborating adverse context. Notify only when both changes meet the owner-defined materiality."
        )
    if trial_class == "explained_ignore":
        return prefix + (
            f"For this policy, a lower {primary_title} is expected when {context_title} falls with it. "
            "Ignore that paired movement unless the relationship is broken."
        )
    if trial_class == "contradictory_investigate":
        return prefix + (
            f"A lower {primary_title} is adverse, but {context_title} must corroborate it before action. "
            "Investigate an uncorroborated movement."
        )
    if trial_class == "stale_escalation":
        return prefix + f"Escalate when {primary_title} is stale; do not interpret stale values."
    if trial_class == "missing_baseline":
        return prefix + f"Require a comparable baseline for {primary_title}; otherwise report insufficient data."
    return prefix + f"Treat a failed {primary_title} query as insufficient data; do not infer from {context_title}."


def _observation(
    chart_id: str,
    chart_title: str,
    metric: str,
    *,
    current: float | None,
    baseline: float | None,
    change_pct: float | None,
    freshness: str | None = None,
) -> Observation:
    return Observation(
        chart_id=chart_id,
        chart_title=chart_title,
        metric=metric,
        unit="normalized units",
        current=current,
        baseline=baseline,
        change_pct=change_pct,
        freshness=freshness,
        source_url=f"trial://chart/{chart_id}",
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
        recipient = _recipient(domain)
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
                expected_outcome = Outcome.INVESTIGATE
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

            primary_chart = ChartSnapshot(
                id=primary_id,
                title=primary_title,
                metric=primary_metric,
                observations=[]
                if primary_error
                else [
                    _observation(
                        primary_id,
                        primary_title,
                        primary_metric,
                        current=primary_current_value,
                        baseline=primary_baseline_value,
                        change_pct=primary_change,
                        freshness=freshness,
                    )
                ],
                error=primary_error,
                related_chart_ids=[context_id],
            )
            context_chart = ChartSnapshot(
                id=context_id,
                title=trial_context_title,
                metric=trial_context_metric,
                observations=[
                    _observation(
                        context_id,
                        trial_context_title,
                        trial_context_metric,
                        current=context_current_value,
                        baseline=context_baseline_value,
                        change_pct=context_change,
                    )
                ],
                related_chart_ids=[primary_id],
            )
            dashboard_id = f"trial-dashboard-{domain_id}-{trial_class}"
            card_id = f"trial-monitor-{domain_id}-{trial_class}"
            dashboard = DashboardSnapshot(
                id=dashboard_id,
                title=f"{domain_name} operating dashboard",
                description=f"Generated trial dashboard for {domain_name}.",
                owners=[domain_name.lower().replace(" ", "-")],
                charts=[primary_chart, context_chart],
                source_url=f"trial://dashboard/{dashboard_id}",
            )
            guidance = _guidance(recipient.key, trial_class)
            if trial_class == "stale_escalation":
                guidance["escalate"] = f"Choose escalate when the primary chart freshness says stale; urgent attention from {recipient.key} is required before interpreting values."
            card = MonitorCard(
                id=card_id,
                dashboard_id=dashboard_id,
                title=f"{domain_name} signal monitor",
                intent=_trial_intent(domain_name, primary_title, trial_context_title, trial_class),
                chart_ids=[primary_id, context_id],
                comparison_windows=["previous_period", "trailing_4_period_average"],
                investigation_hints=[
                    f"Compare {primary_title} with {trial_context_title}.",
                    "Check freshness and baseline availability before interpreting the movement.",
                ],
                materiality_threshold_pct=15.0,
                action_confidence_threshold=0.40 if trial_class == "explained_ignore" else 0.70,
                materiality_definition=_materiality_definition(
                    primary_title, trial_context_title, trial_class
                ),
                outcome_guidance={
                    outcome: text
                    for outcome, text in guidance.items()
                    if outcome in {item.value for item in _allowed_outcomes(trial_class)}
                },
                allowed_outcomes=_allowed_outcomes(trial_class),
                recipients=[recipient],
            )
            cases.append(
                TrialCase(
                    case_id=card_id,
                    domain_id=domain_id,
                    domain_name=domain_name,
                    trial_class=trial_class,
                    dashboard=dashboard,
                    card=card,
                    expected_outcome=expected_outcome,
                    expected_recipient=recipient.key if expected_outcome in {Outcome.NOTIFY, Outcome.ESCALATE} else None,
                )
            )
    return cases


async def run_trial(
    cases: list[TrialCase], *, repeats: int, concurrency: int, api_key: str
) -> tuple[list[TrialResult], dict[str, Any]]:
    judger = JevJudger(api_key=api_key)
    engine = MonitorEngine(judger=judger)
    semaphore = asyncio.Semaphore(concurrency)
    jobs = [(case, repeat + 1) for repeat in range(repeats) for case in cases]

    async def evaluate(case: TrialCase, repeat: int) -> TrialResult:
        del repeat
        async with semaphore:
            before = judger.metrics.requests
            started = time.perf_counter()
            try:
                evaluation = await engine.evaluate(case.dashboard, case.card)
                decision = evaluation.decision
                actual_outcome = decision.outcome.value
                actual_recipient = decision.recipient_key
                error = None
                confidence = decision.confidence
            except Exception as exc:  # noqa: BLE001 - trial must record provider failures
                actual_outcome = Outcome.INSUFFICIENT_DATA.value
                actual_recipient = None
                error = f"{type(exc).__name__}: {exc}"
                confidence = None
            return TrialResult(
                case_id=case.case_id,
                domain_id=case.domain_id,
                trial_class=case.trial_class,
                expected_outcome=case.expected_outcome.value,
                actual_outcome=actual_outcome,
                expected_recipient=case.expected_recipient,
                actual_recipient=actual_recipient,
                outcome_correct=actual_outcome == case.expected_outcome.value,
                decision_correct=(
                    actual_outcome == case.expected_outcome.value
                    and actual_recipient == case.expected_recipient
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
    confidences = sorted(
        result.confidence for result in results if result.confidence is not None
    )
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
            len({item.actual_outcome for item in items}) == 1
            and len({item.actual_recipient for item in items}) == 1
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

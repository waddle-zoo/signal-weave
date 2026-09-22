"""Benchmark outcome-level monitoring over messy, heterogeneous enterprise context.

This module is evaluation-only.  It does not add business policy to the product
runtime.  It expands a small external scenario catalog into human-authored
cards whose evidence spans BI, operational systems, incidents, deployments,
quality checks, and owner context.  The expected labels stay in the evaluator;
the Jev payload receives only the card and the source observations.

The baseline intentionally represents a common current-state monitor: alert on
any large movement and escalate only on an even larger movement.  It receives
the same sources as SignalWeave but does not interpret their relationships.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
    ResourceContract,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).parent / "data" / "everything-tracking-scenarios.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "everything-tracking-trial.json"


VARIANTS: dict[str, dict[str, Any]] = {
    "material_action": {
        "expected": Outcome.NOTIFY,
        "primary_change": -22.0,
        "corroborating_change": 34.0,
        "diagnostic_change": 18.0,
        "description": "The primary business outcome moved materially and related evidence supports an owner action.",
    },
    "expected_change": {
        "expected": Outcome.IGNORE,
        "primary_change": -18.0,
        "corroborating_change": -17.0,
        "diagnostic_change": 0.0,
        "description": "Several signals moved together during an expected operating pattern.",
    },
    "ambiguous_state": {
        "expected": Outcome.INVESTIGATE,
        "primary_change": -22.0,
        "corroborating_change": 2.0,
        "diagnostic_change": -1.0,
        "description": "The primary movement is material but connected evidence is weak or contradictory.",
    },
    "trust_failure": {
        "expected": Outcome.INSUFFICIENT_DATA,
        "primary_change": -22.0,
        "corroborating_change": 18.0,
        "diagnostic_change": 12.0,
        "description": "The business signals moved, but a required trust or freshness source cannot be used.",
    },
    "urgent_operational_risk": {
        "expected": Outcome.ESCALATE,
        "primary_change": -38.0,
        "corroborating_change": 44.0,
        "diagnostic_change": 58.0,
        "description": "The movement is broad, severe, and supported by an operational risk signal.",
    },
}


@dataclass(frozen=True)
class TrackingCase:
    case_id: str
    company_id: str
    tenant_id: str
    company_shape: str
    workflow_id: str
    domain: str
    variant: str
    card: InsightCard
    resources: list[ResourceSnapshot]
    expected_outcome: str
    expected_evidence_source_keys: list[str]


@dataclass(frozen=True)
class ArmResult:
    case_id: str
    arm: str
    variant: str
    expected_outcome: str
    actual_outcome: str
    expected_evidence_source_keys: list[str]
    actual_evidence_source_keys: list[str]
    evidence_recall: float
    exact_outcome: bool
    safe_automatic_action: bool
    unsafe_automatic_action: bool
    elapsed_ms: float
    requests: int
    confidence: float | None = None
    error: str | None = None


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != 1:
        raise ValueError("everything-tracking scenario file must have schema_version=1")
    if not isinstance(payload.get("companies"), list) or not isinstance(payload.get("workflows"), dict):
        raise ValueError("scenario file must define companies and workflows")
    return payload


def _delivery_methods(company_id: str, domain: str) -> list[DeliveryMethod]:
    owner = f"{company_id} {domain} operations"
    return [
        DeliveryMethod(
            key=f"{company_id}-{domain}-notify",
            outcome=Outcome.NOTIFY,
            label=owner,
            destination=f"slack://{company_id}/{domain}",
            instructions=(
                f"Notify the {owner} owner when the evidence supports a material, non-urgent action."
            ),
        ),
        DeliveryMethod(
            key=f"{company_id}-{domain}-escalate",
            outcome=Outcome.ESCALATE,
            label=f"{owner} leadership",
            destination=f"slack://{company_id}/{domain}/leadership",
            instructions=(
                f"Escalate to {owner} leadership when the evidence indicates severe operational risk or an unsafe source."
            ),
        ),
    ]


def _observation(
    source_key: str,
    label: str,
    metric: str,
    change_pct: float,
    *,
    subject_type: str,
    role: str,
    base: float = 100.0,
) -> Observation:
    return Observation(
        source_key=source_key,
        subject_id=f"{source_key}-subject",
        subject_label=label,
        subject_type=subject_type,
        metric=metric,
        unit="normalized units",
        current=round(base * (1.0 + change_pct / 100.0), 3),
        baseline=base,
        previous=base,
        change_pct=change_pct,
        source_url=f"trial://{source_key}",
        attributes={"evidence_role": role},
    )


def _resource(
    *,
    source_key: str,
    tenant_id: str,
    domain: str,
    adapter: str,
    kind: str,
    resource: str,
    label: str,
    role: str,
    metric: str,
    change_pct: float,
    statement: str,
    required: bool = True,
    error: str | None = None,
    source_status: str = "healthy",
    freshness: str | None = None,
) -> ResourceSnapshot:
    observation = _observation(
        source_key,
        label,
        metric,
        change_pct,
        subject_type=kind,
        role=role,
    )
    if freshness:
        observation = observation.model_copy(update={"freshness": freshness})
    evidence = Evidence(
        source_key=source_key,
        subject_id=f"{source_key}-evidence",
        subject_label=label,
        statement=statement,
        values={"evidence_role": role, "source_kind": kind},
        source_url=f"trial://{source_key}",
    )
    contract = ResourceContract(
        tenant_id=tenant_id,
        domain=domain,
        roles=[role],
        source_status=source_status,
        authorized=True,
    )
    return ResourceSnapshot(
        source_key=source_key,
        adapter=adapter,
        resource=resource,
        title=label,
        description=f"{label} from the {adapter} system.",
        observations=[] if error else [observation],
        evidence=[evidence],
        error=error,
        source_url=f"trial://{adapter}/{resource}",
        contract=contract,
        metadata={"evidence_role": role, "required": required},
        captured_at=datetime.now(timezone.utc),
    )


def _variant_statement(variant: str, role: str, label: str, workflow_title: str) -> str:
    if variant == "material_action":
        if role == "corroborates":
            return f"{label} independently moved in a direction consistent with the {workflow_title} concern."
        if role == "diagnostic":
            return f"{label} contains a connected operating change that could explain the {workflow_title} movement."
        if role == "quality":
            return f"{label} reports current, comparable evidence for the {workflow_title} review."
    if variant == "expected_change":
        if role == "corroborates":
            return f"{label} moved with the primary signal during a planned or expected operating pattern."
        if role == "owner":
            return f"{label} records a planned operating change relevant to the {workflow_title} period."
    if variant == "ambiguous_state":
        if role == "corroborates":
            return f"{label} does not materially corroborate the primary {workflow_title} movement."
        if role == "diagnostic":
            return f"{label} provides mixed or incomplete context for the {workflow_title} movement."
    if variant == "trust_failure" and role == "quality":
        return f"{label} cannot establish freshness or comparability for the {workflow_title} review."
    if variant == "urgent_operational_risk":
        if role == "corroborates":
            return f"{label} shows a broad deterioration consistent with severe {workflow_title} risk."
        if role == "diagnostic":
            return f"{label} contains a severe operating condition connected to the {workflow_title} movement."
    return f"{label} is available as contextual evidence for the {workflow_title} review."


def build_cases(config: dict[str, Any], *, repeats: int = 1) -> list[TrackingCase]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    cases: list[TrackingCase] = []
    variant_order = config.get("variant_order", list(VARIANTS))
    for company in config["companies"]:
        company_id = str(company["id"])
        tenant_id = str(company["tenant_id"])
        shape = str(company["shape"])
        for workflow_id in company["workflows"]:
            workflow = config["workflows"][workflow_id]
            for repeat in range(1, repeats + 1):
                for variant in variant_order:
                    profile = VARIANTS[variant]
                    case_id = f"{company_id}:{workflow_id}:{variant}:r{repeat}"
                    related_specs = list(workflow["related"])
                    # Every outcome-level monitor needs a trust path even when
                    # the business workflow's named sources omit an explicit
                    # data-quality adapter.  This is an evaluation fixture
                    # invariant, not a product policy or vendor branch.
                    if variant == "trust_failure" and not any(
                        str(spec.get("role")) == "quality" for spec in related_specs
                    ):
                        related_specs.append(
                            {
                                "adapter": "quality",
                                "kind": "quality",
                                "role": "quality",
                                "label": "Evidence trust check",
                            }
                        )
                    source_specs = [
                        {
                            "adapter": workflow["primary"]["adapter"],
                            "kind": workflow["primary"]["kind"],
                            "label": workflow["primary"]["label"],
                            "role": "primary",
                            "metric": workflow["primary"]["metric"],
                        },
                        *related_specs,
                        {"adapter": "wiki", "kind": "document", "role": "unknown", "label": "Unrelated policy note"},
                        {"adapter": "calendar", "kind": "calendar", "role": "unknown", "label": "Unrelated team calendar"},
                    ]
                    sources: list[SourceRef] = []
                    resources: list[ResourceSnapshot] = []
                    expected_evidence: list[str] = []
                    for index, spec in enumerate(source_specs):
                        source_key = f"source-{index}"
                        adapter = str(spec["adapter"])
                        kind = str(spec["kind"])
                        role = str(spec["role"])
                        label = str(spec["label"])
                        required = role not in {"unknown"}
                        change = 0.0
                        metric = str(spec.get("metric", f"{role}_signal"))
                        if role == "primary":
                            change = float(profile["primary_change"])
                            expected_evidence.append(source_key)
                        elif role == "corroborates":
                            change = float(profile["corroborating_change"])
                            expected_evidence.append(source_key)
                        elif role == "diagnostic":
                            change = float(profile["diagnostic_change"])
                            if variant in {"material_action", "ambiguous_state", "urgent_operational_risk"}:
                                expected_evidence.append(source_key)
                        elif role == "quality":
                            change = 0.0
                            if variant == "trust_failure":
                                expected_evidence.append(source_key)
                        elif role == "owner":
                            expected_evidence.append(source_key)
                        if role == "unknown":
                            change = 61.0 if index % 2 else -47.0
                        source_resource = f"{kind}:{company_id}:{workflow_id}:{variant}:{repeat}:{index}"
                        source_error = None
                        status = "healthy"
                        freshness = None
                        if variant == "trust_failure" and role == "quality":
                            source_error = "freshness contract unavailable during the scheduled check"
                            status = "unknown"
                            change = 0.0
                        statement = _variant_statement(variant, role, label, str(workflow["title"]))
                        resource = _resource(
                            source_key=source_key,
                            tenant_id=tenant_id,
                            domain=str(workflow["domain"]),
                            adapter=adapter,
                            kind=kind,
                            resource=source_resource,
                            label=label,
                            role=role,
                            metric=metric,
                            change_pct=change,
                            statement=statement,
                            required=required,
                            error=source_error,
                            source_status=status,
                            freshness=freshness,
                        )
                        resources.append(resource)
                        sources.append(
                            SourceRef(
                                key=source_key,
                                adapter=adapter,
                                resource=source_resource,
                                label=label,
                                required=required,
                            )
                        )
                    card = InsightCard(
                        id=f"card-{case_id}",
                        title=f"{company_id} {workflow['title']}",
                        what_to_watch=str(workflow["what_to_watch"]),
                        why_watch=str(workflow["why_watch"]),
                        watch_for=list(workflow["watch_for"]),
                        questions=list(workflow["questions"]),
                        sources=sources,
                        comparison_windows=["previous_period", "trailing_4_period_average"],
                        action_confidence_threshold=0.70,
                        owner=f"{company_id}:{workflow['domain']}",
                        max_source_age_hours=72.0,
                        delivery_methods=_delivery_methods(company_id, str(workflow["domain"])),
                    )
                    cases.append(
                        TrackingCase(
                            case_id=case_id,
                            company_id=company_id,
                            tenant_id=tenant_id,
                            company_shape=shape,
                            workflow_id=workflow_id,
                            domain=str(workflow["domain"]),
                            variant=variant,
                            card=card,
                            resources=resources,
                            expected_outcome=profile["expected"].value,
                            expected_evidence_source_keys=sorted(set(expected_evidence)),
                        )
                    )
    return cases


def movement_only(case: TrackingCase) -> tuple[str, list[str]]:
    """A deliberately simple baseline over the same evidence bundle."""
    if any(resource.error for resource in case.resources if resource.metadata.get("required", True)):
        return Outcome.INSUFFICIENT_DATA.value, []
    changes = [
        abs(observation.change_pct or 0.0)
        for resource in case.resources
        for observation in resource.observations
    ]
    if not changes or max(changes) < 10.0:
        return Outcome.IGNORE.value, []
    if max(changes) >= 30.0:
        return Outcome.ESCALATE.value, []
    return Outcome.NOTIFY.value, []


def _automatic(outcome: str) -> bool:
    return outcome in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}


def _arm_result(
    case: TrackingCase,
    *,
    arm: str,
    outcome: str,
    evidence_source_keys: list[str],
    elapsed_ms: float,
    requests: int,
    confidence: float | None = None,
    error: str | None = None,
) -> ArmResult:
    expected = set(case.expected_evidence_source_keys)
    actual = set(evidence_source_keys)
    recall = len(expected & actual) / len(expected) if expected else 1.0
    unsafe = _automatic(outcome) and case.expected_outcome not in {
        Outcome.NOTIFY.value,
        Outcome.ESCALATE.value,
    }
    return ArmResult(
        case_id=case.case_id,
        arm=arm,
        variant=case.variant,
        expected_outcome=case.expected_outcome,
        actual_outcome=outcome,
        expected_evidence_source_keys=sorted(expected),
        actual_evidence_source_keys=sorted(actual),
        evidence_recall=round(recall, 4),
        exact_outcome=outcome == case.expected_outcome,
        safe_automatic_action=not unsafe,
        unsafe_automatic_action=unsafe,
        elapsed_ms=round(elapsed_ms, 2),
        requests=requests,
        confidence=confidence,
        error=error,
    )


async def run_jev(cases: list[TrackingCase], *, api_key: str, concurrency: int) -> tuple[list[ArmResult], dict[str, int]]:
    judger = JevJudger(api_key=api_key)
    engine = InsightEngine(judger=judger)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: TrackingCase) -> ArmResult:
        async with semaphore:
            before_requests = judger.metrics.requests
            started = time.perf_counter()
            try:
                run = await engine.evaluate(case.card, case.resources)
                result = run.result
                evidence_keys = sorted({item.source_key for item in result.evidence})
                return _arm_result(
                    case,
                    arm="signalweave-jev",
                    outcome=result.outcome.value,
                    evidence_source_keys=evidence_keys,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    requests=judger.metrics.requests - before_requests,
                    confidence=result.confidence,
                )
            except Exception as error:  # noqa: BLE001 - keep provider failures in denominator
                return _arm_result(
                    case,
                    arm="signalweave-jev",
                    outcome=Outcome.INSUFFICIENT_DATA.value,
                    evidence_source_keys=[],
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    requests=judger.metrics.requests - before_requests,
                    error=f"{type(error).__name__}: {error}",
                )

    results = list(await asyncio.gather(*(one(case) for case in cases)))
    return results, {
        "requests": judger.metrics.requests,
        "input_tokens": judger.metrics.input_tokens,
        "output_tokens": judger.metrics.output_tokens,
    }


def run_baseline(cases: list[TrackingCase]) -> list[ArmResult]:
    results: list[ArmResult] = []
    for case in cases:
        started = time.perf_counter()
        outcome, evidence = movement_only(case)
        results.append(
            _arm_result(
                case,
                arm="movement-only",
                outcome=outcome,
                evidence_source_keys=evidence,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                requests=0,
            )
        )
    return results


def summarize(results: list[ArmResult], *, repeats: int, provider: dict[str, int] | None = None) -> dict[str, Any]:
    if not results:
        raise ValueError("cannot summarize an empty trial")
    by_variant: dict[str, list[ArmResult]] = defaultdict(list)
    for result in results:
        by_variant[result.variant].append(result)
    latencies = sorted(result.elapsed_ms for result in results)
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    return {
        "cases": len(results),
        "unique_cases": len({result.case_id for result in results}),
        "repeats": repeats,
        "outcome_accuracy": round(sum(item.exact_outcome for item in results) / len(results), 4),
        "unsafe_automatic_actions": sum(item.unsafe_automatic_action for item in results),
        "safe_automatic_actions": sum(item.safe_automatic_action for item in results),
        "evidence_recall": round(sum(item.evidence_recall for item in results) / len(results), 4),
        "provider_errors": sum(item.error is not None for item in results),
        "median_ms": round(median(latencies), 2),
        "p95_ms": round(p95, 2),
        "requests": sum(item.requests for item in results),
        "provider": provider or {"requests": 0, "input_tokens": 0, "output_tokens": 0},
        "variant_summary": {
            variant: {
                "cases": len(items),
                "outcome_accuracy": round(sum(item.exact_outcome for item in items) / len(items), 4),
                "unsafe_automatic_actions": sum(item.unsafe_automatic_action for item in items),
                "evidence_recall": round(sum(item.evidence_recall for item in items) / len(items), 4),
            }
            for variant, items in sorted(by_variant.items())
        },
    }


def build_report(cases: list[TrackingCase], baseline: list[ArmResult], jev: list[ArmResult], provider: dict[str, int], repeats: int) -> dict[str, Any]:
    baseline_summary = summarize(baseline, repeats=repeats)
    jev_summary = summarize(jev, repeats=repeats, provider=provider)
    baseline_by_case = {item.case_id: item for item in baseline}
    jev_by_case = {item.case_id: item for item in jev}
    paired = {
        "jev_better_outcome": 0,
        "jev_worse_outcome": 0,
        "jev_reduced_unsafe_actions": 0,
        "jev_improved_evidence_recall": 0,
    }
    for case_id, jev_result in jev_by_case.items():
        baseline_result = baseline_by_case[case_id]
        if jev_result.exact_outcome and not baseline_result.exact_outcome:
            paired["jev_better_outcome"] += 1
        if baseline_result.exact_outcome and not jev_result.exact_outcome:
            paired["jev_worse_outcome"] += 1
        if baseline_result.unsafe_automatic_action and not jev_result.unsafe_automatic_action:
            paired["jev_reduced_unsafe_actions"] += 1
        if jev_result.evidence_recall > baseline_result.evidence_recall:
            paired["jev_improved_evidence_recall"] += 1
    return {
        "trial": "everything-tracking-business-value",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "companies": len({case.company_id for case in cases}),
            "company_shapes": sorted({case.company_shape for case in cases}),
            "domains": sorted({case.domain for case in cases}),
            "workflows": len({case.workflow_id for case in cases}),
            "variants": sorted({case.variant for case in cases}),
            "adapters": sorted({resource.adapter for case in cases for resource in case.resources}),
            "sources_per_case": sorted({len(case.resources) for case in cases}),
            "cards_are_free_form": True,
            "expected_labels_sent_to_jev": False,
        },
        "arms": {
            "movement_only": baseline_summary,
            "signalweave_jev": jev_summary,
        },
        "paired": paired,
        "results": {
            "baseline": [asdict(item) for item in baseline],
            "signalweave_jev": [asdict(item) for item in jev],
        },
        "limitations": [
            "The catalog and expected business outcomes are synthetic research fixtures.",
            "The baseline is a movement-only policy, not a named general-purpose agent.",
            "Source observations are generated normalized facts; no production query engine is exercised.",
            "A live Jev result validates this bounded contract, not universal business correctness.",
            "A real deployment still needs domain-owner labels, time-split holdouts, and useful-alert feedback.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    design = report["design"]
    baseline = report["arms"]["movement_only"]
    jev = report["arms"]["signalweave_jev"]
    paired = report["paired"]
    lines = [
        "# Everything-tracking business-value trial",
        "",
        "This is a live Jev evaluation over synthetic but deliberately messy enterprise context. It tests outcome-level monitoring, not metric alerting alone.",
        "",
        f"- Cases: **{design['companies']} companies / {design['workflows']} workflows / {baseline['cases']} cases**",
        f"- Company shapes: `{', '.join(design['company_shapes'])}`",
        f"- Adapters: `{', '.join(design['adapters'])}`",
        f"- Sources per case: `{design['sources_per_case']}`",
        "",
        "## Arm comparison",
        "",
        "| Measure | Movement-only | SignalWeave + Jev |",
        "| --- | ---: | ---: |",
        f"| Exact outcome | {baseline['outcome_accuracy']:.1%} | {jev['outcome_accuracy']:.1%} |",
        f"| Unsafe automatic actions | {baseline['unsafe_automatic_actions']} | {jev['unsafe_automatic_actions']} |",
        f"| Evidence recall | {baseline['evidence_recall']:.1%} | {jev['evidence_recall']:.1%} |",
        f"| Median latency | {baseline['median_ms']:.2f} ms | {jev['median_ms']:.2f} ms |",
        f"| p95 latency | {baseline['p95_ms']:.2f} ms | {jev['p95_ms']:.2f} ms |",
        "",
        "## Paired interpretation",
        "",
        f"- Jev improved exact outcome on `{paired['jev_better_outcome']}` cases and was worse on `{paired['jev_worse_outcome']}`.",
        f"- Jev removed an unsafe automatic action on `{paired['jev_reduced_unsafe_actions']}` cases.",
        f"- Jev improved required evidence recall on `{paired['jev_improved_evidence_recall']}` cases.",
        "",
        "## Variant results",
        "",
        "| Variant | Cases | Movement-only exact | Jev exact | Jev unsafe | Jev evidence recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    baseline_variants = baseline["variant_summary"]
    for variant in sorted(jev["variant_summary"]):
        item = jev["variant_summary"][variant]
        base = baseline_variants[variant]
        lines.append(
            f"| `{variant}` | {item['cases']} | {base['outcome_accuracy']:.1%} | "
            f"{item['outcome_accuracy']:.1%} | {item['unsafe_automatic_actions']} | "
            f"{item['evidence_recall']:.1%} |"
        )
    lines.extend(["", "## Limits", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    cases = build_cases(config, repeats=args.repeats)
    if args.max_cases:
        cases = cases[: args.max_cases]
    baseline = run_baseline(cases)
    if args.dry_run:
        print(json.dumps({"cases": len(cases), "adapters": sorted({resource.adapter for case in cases for resource in case.resources})}, indent=2))
        return 0
    api_key = load_api_key(args.typesafe_key_file)
    if not api_key:
        raise RuntimeError("set TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE for a live Jev trial")
    jev, provider = await run_jev(cases, api_key=api_key, concurrency=args.concurrency)
    report = build_report(cases, baseline, jev, provider, args.repeats)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(render_markdown(report))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--typesafe-key-file")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    if not 1 <= args.concurrency <= 32:
        raise SystemExit("--concurrency must be between 1 and 32")
    if args.max_cases is not None and args.max_cases < 1:
        raise SystemExit("--max-cases must be positive")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

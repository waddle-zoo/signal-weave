"""Live Jev regression for the typed source-comparability gate.

The prior evidence-sufficiency trial showed that prose source documentation was
not enough to route incomplete populations correctly. This trial uses the
adapter-owned ``ResourceContract.comparison_contracts`` path and keeps Jev for
the semantic judgment/explanation. It is a regression over one known business
family, not a general accuracy or enterprise-readiness claim.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import random
import subprocess
from collections import defaultdict
from pathlib import Path

from evaluations import evidence_sufficiency_trial as prior
from evaluations.bootstrap_agent_trial import (
    Audit,
    MeasuredJev,
    RequestBudget,
    digest,
    write_exclusive,
)
from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.evaluation import CardEvaluationCase, CardWorkflowEvaluator
from signalweave.models import InsightCard, SourceComparisonContract

VERSION = "evidence-contract-gate-v1"
ATTEMPT_CAP = 12


def implementation_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    paths = [
        *sorted((root / "src").rglob("*.py")),
        Path(__file__),
        root / "evaluations/bootstrap_agent_trial.py",
        root / "evaluations/evidence_sufficiency_trial.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def schedule() -> list[dict[str, int]]:
    rows = [{"case_index": index, "repeat": repeat} for repeat in range(2) for index in range(6)]
    random.Random(20261004).shuffle(rows)
    return rows


def _members(values: dict[str, object], prefix: str):
    return values.get(f"{prefix}_cluster_population", values.get("cluster_population"))


def _scalar_contract(
    values: dict[str, object], *, metric: str, suffix: str, expected_clusters: list[str]
) -> dict[str, object]:
    baseline = values.get(f"baseline_{suffix}")
    current = values.get(f"current_{suffix}")
    baseline_members = _members(values, "baseline")
    current_members = _members(values, "current")
    if baseline_members is None or current_members is None:
        coverage = "unknown"
        detail = "The provider did not return a baseline or current population membership."
    elif set(baseline_members) != set(expected_clusters) or set(current_members) != set(
        expected_clusters
    ):
        coverage = "partial"
        detail = (
            "The observed baseline/current membership does not equal the expected provider fleet."
        )
    elif baseline is None or current is None:
        coverage = "partial"
        detail = "A required baseline or current measurement is absent."
    else:
        coverage = "complete"
        detail = "The provider verified the expected population and both comparison values."
    return SourceComparisonContract(
        key=f"{metric}-previous-period",
        metric=metric,
        definition=f"{metric} over the expected customer-cluster fleet.",
        population="expected customer-cluster fleet",
        unit="ms",
        comparison_window="previous_period",
        coverage=coverage,
        comparable=coverage == "complete",
        detail=detail,
        query_refs=[f"provider-export:{metric}"],
    ).model_dump(mode="json")


def _contractual_case(
    card_payload: dict[str, object], case_payload: dict[str, object]
) -> tuple[InsightCard, dict[str, object]]:
    card = copy.deepcopy(card_payload)
    source = prior.primary(case_payload)
    values = source["evidence"][0]["values"]
    keys = ["query-p95-latency-previous-period", "replication-lag-previous-period"]
    card["sources"][0]["required_comparison_keys"] = keys
    source["contract"]["required_comparison_keys"] = keys
    source["contract"]["comparison_contracts"] = [
        _scalar_contract(
            values,
            metric="query-p95-latency",
            suffix="p95_ms",
            expected_clusters=prior.EXPECTED_CLUSTERS,
        ),
        _scalar_contract(
            values,
            metric="replication-lag",
            suffix="lag_ms",
            expected_clusters=prior.EXPECTED_CLUSTERS,
        ),
    ]
    typed_card = InsightCard.model_validate(card)
    typed_card = typed_card.model_copy(update={"compiled_plan": base_plan(typed_card)})
    typed_case = copy.deepcopy(case_payload)
    typed_case["card"] = typed_card.model_dump(mode="json")
    typed_case["resources"] = [
        source if item["source_key"] == source["source_key"] else item
        for item in typed_case["resources"]
    ]
    return typed_card, typed_case


def build(trace: Path) -> dict[str, object]:
    matrix = prior.build(trace)
    card = matrix["card"]
    documented = [row["case"] for row in matrix["rows"] if row["arm"] == "documented"]
    if len(documented) != 6:
        raise ValueError("expected six documented source-contract regression cases")
    cases = []
    typed_card = None
    for case in documented:
        typed_card, typed_case = _contractual_case(card, case)
        cases.append(typed_case)
    assert typed_card is not None
    return {"card": typed_card.model_dump(mode="json"), "cases": cases}


def _expected_handoff(outcome: str) -> tuple[str, str]:
    return {
        "ignore": ("suppress", "complete"),
        "investigate": ("retrieve_evidence", "pending"),
        "insufficient_data": ("repair_source", "blocked"),
    }[outcome]


def _score(case: dict[str, object], report: dict[str, object]) -> dict[str, object]:
    result = report["cases"][0]
    expected = case["expected_outcome"]
    expected_action, expected_status = _expected_handoff(expected)
    workflow = result.get("workflow") or {}
    handoff = (
        result.get("outcome") == expected
        and workflow.get("action") == expected_action
        and workflow.get("status") == expected_status
        and set(workflow.get("delivery_method_keys", []))
        == set(case["expected_delivery_method_keys"])
    )
    return {
        "exact": bool(result.get("exact_outcome"))
        and bool(result.get("delivery_exact"))
        and handoff,
        "outcome_exact": bool(result.get("exact_outcome")),
        "delivery_exact": bool(result.get("delivery_exact")),
        "handoff_exact": handoff,
        "expected_outcome": expected,
        "outcome": result.get("outcome"),
        "workflow_action": workflow.get("action"),
        "workflow_status": workflow.get("status"),
        "probabilities": result.get("probabilities", {}),
        "confidence": result.get("confidence"),
        "error": result.get("error"),
        "failure_reasons": result.get("failure_reasons", []),
    }


def _assemble_report(
    results: list[dict[str, object]],
    *,
    attempts: int,
    responses: list[dict[str, object]],
    budget_censored: bool,
) -> dict[str, object]:
    by_case: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in results:
        by_case[item["case_id"]].append(item["score"])
    summary = {
        case_id: {
            "exact": sum(bool(item["exact"]) for item in items),
            "attempts": len(items),
            "errors": sum(item["error"] is not None for item in items),
        }
        for case_id, items in by_case.items()
    }
    models = sorted({event.get("response", {}).get("model", "unknown") for event in responses})
    primary_gate = (
        all(item["score"]["exact"] for item in results)
        and len(results) == ATTEMPT_CAP
        and len(responses) == ATTEMPT_CAP
        and not budget_censored
        and all(item["score"]["error"] is None for item in results)
        and len(models) == 1
        and models != ["unknown"]
    )
    return {
        "summary": summary,
        "attempts": attempts,
        "budget_censored": budget_censored,
        "resolved_models": models,
        "primary_gate": primary_gate,
        "results": results,
    }


async def freeze(trace: Path, output: Path) -> dict[str, object]:
    inputs = build(trace)
    output.mkdir(parents=True, exist_ok=False)
    protocol = {
        "version": VERSION,
        "input_digest": digest(inputs),
        "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "implementation_sha256": implementation_hashes(),
        "code": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "attempt_cap": ATTEMPT_CAP,
        "schedule": schedule(),
        "scope": "Known-family regression of typed adapter comparability admission; no delivery",
        "gate": "All six cases in both repetitions must match outcome, configured route and workflow handoff",
        "retries": 0,
        "zero_real_deliveries": True,
        "comparative_claims": False,
    }
    write_exclusive(output / "inputs.json", inputs)
    write_exclusive(output / "protocol.json", protocol)
    return protocol


async def execute(plan: Path, output: Path, key_file: Path) -> dict[str, object]:
    inputs = json.loads((plan / "inputs.json").read_text())
    protocol = json.loads((plan / "protocol.json").read_text())
    if (
        digest(inputs) != protocol["input_digest"]
        or implementation_hashes() != protocol["implementation_sha256"]
        or protocol["schedule"] != schedule()
        or protocol["attempt_cap"] != ATTEMPT_CAP
    ):
        raise ValueError("Frozen inputs, implementation or schedule changed; freeze a new protocol")
    output.mkdir(parents=True, exist_ok=False)
    write_exclusive(output / "inputs.json", inputs)
    write_exclusive(output / "protocol.json", protocol)
    key = key_file.read_text().strip()
    audit = Audit(output / "trace.jsonl", (key,))
    budget = RequestBudget(ATTEMPT_CAP)
    judger = MeasuredJev(key, budget, audit)
    engine = InsightEngine(judger)
    results = []
    for number, entry in enumerate(protocol["schedule"]):
        case_payload = inputs["cases"][entry["case_index"]]
        case = CardEvaluationCase.model_validate(case_payload)
        audit.episode = f"attempt-{number:03d}"
        report = await CardWorkflowEvaluator(engine, max_concurrency=1).evaluate(
            [case], acceptance_outcomes=[case.expected_outcome]
        )
        serialized = report.model_dump(mode="json")
        item = {
            **entry,
            "case_id": case.id,
            "report": serialized,
            "score": _score(case_payload, serialized),
        }
        results.append(item)
        write_exclusive(output / f"attempt-{number:03d}.json", audit.redact(item))
    responses = [event for event in audit.events if event.get("kind") == "api.response"]
    report = _assemble_report(
        results,
        attempts=budget.used,
        responses=responses,
        budget_censored=budget.exhausted,
    )
    write_exclusive(output / "report.json", audit.redact(report))
    return {
        "summary": report["summary"],
        "attempts": budget.used,
        "resolved_models": report["resolved_models"],
        "primary_gate": report["primary_gate"],
    }


def finalize(output: Path) -> dict[str, object]:
    """Rebuild a report from retained attempts after a reporter-only failure."""
    protocol = json.loads((output / "protocol.json").read_text())
    attempts = [json.loads(path.read_text()) for path in sorted(output.glob("attempt-*.json"))]
    if len(attempts) != ATTEMPT_CAP:
        raise ValueError(f"expected {ATTEMPT_CAP} retained attempts, found {len(attempts)}")
    trace_events = [
        json.loads(line)
        for line in (output / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    responses = [event for event in trace_events if event.get("kind") == "api.response"]
    results = attempts
    report = _assemble_report(
        results,
        attempts=len(attempts),
        responses=responses,
        budget_censored=len(attempts) >= protocol["attempt_cap"] and len(responses) < len(attempts),
    )
    report["report_rebuilt_after_runner_exception"] = True
    report["report_rebuild_reason"] = (
        "All live attempts and API responses were retained; only the original report writer "
        "raised after the final call, so this report was reconstructed without another Jev call."
    )
    write_exclusive(output / "report.json", report)
    return {
        "summary": report["summary"],
        "attempts": report["attempts"],
        "resolved_models": report["resolved_models"],
        "primary_gate": report["primary_gate"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        if args.trace or args.plan or args.key_file or args.live:
            parser.error("Finalize requires --output only")
        print(json.dumps(finalize(args.output), indent=2))
    elif args.live:
        if args.plan is None or args.key_file is None or args.trace:
            parser.error("Live requires --plan and --key-file; no --trace")
        print(json.dumps(asyncio.run(execute(args.plan, args.output, args.key_file)), indent=2))
    else:
        if args.trace is None or args.plan or args.key_file:
            parser.error("Freeze requires --trace only, no key or plan")
        print(json.dumps(asyncio.run(freeze(args.trace, args.output)), indent=2))


if __name__ == "__main__":
    main()

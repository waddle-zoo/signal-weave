"""Frozen source-information/representation experiment; not onboarding proof.

Uses an unchanged retained agent card. Provider documentation is NEW synthetic
information, not a recovered fact about the earlier trial. No production changes.
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
from datetime import datetime, timedelta
from pathlib import Path

from evaluations.bootstrap_agent_trial import (
    Audit,
    MeasuredJev,
    RequestBudget,
    digest,
    write_exclusive,
)
from evaluations.installed_policy_placement_probe import prepare
from signalweave.engine import InsightEngine
from signalweave.evaluation import CardEvaluationCase, CardWorkflowEvaluator
from signalweave.models import Observation

VERSION = "evidence-sufficiency-v1"
EXPECTED_CLUSTERS = ["eu-1", "us-1", "ap-1"]
DEFINITIONS = {
    "baseline_p95_ms": "95th percentile query latency in milliseconds over the baseline window and baseline cluster membership.",
    "current_p95_ms": "95th percentile query latency in milliseconds over the current window and current cluster membership. Same query definition and weighting as baseline.",
    "baseline_lag_ms": "Replication lag in milliseconds over the baseline window and baseline cluster membership.",
    "current_lag_ms": "Replication lag in milliseconds over the current window and current cluster membership. Same lag aggregation as baseline.",
    "cluster_population": "Exported cluster membership shared by baseline and current measurements. Null means membership was not exported. If separate baseline/current memberships are supplied, those take precedence.",
    "affected_regions": "Count of regions with customer-impacting database degradation in the current window, not the number of regions observed. Zero is a measured count; null is unavailable.",
    "single_node_cpu_percent": "CPU utilization percent on one node, not fleet-wide utilization or a customer impact measure.",
}


def implementation_hashes():
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root / "src").rglob("*.py")), Path(__file__),
             root / "evaluations/bootstrap_agent_trial.py", root / "evaluations/installed_policy_placement_probe.py"]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def schedule_for(count):
    schedule = [{"index": i, "repeat": r} for r in range(2) for i in range(count)]
    random.Random(20261003).shuffle(schedule)
    return schedule


def primary(case):
    return next(s for s in case["resources"]
                if "baseline_p95_ms" in s["evidence"][0]["values"])


def document(case):
    result = copy.deepcopy(case)
    source = primary(result)
    clock = datetime.fromisoformat(result["as_of"].replace("Z", "+00:00"))
    source["metadata"]["provider_contract"] = {
        "version": "synthetic-export-contract-v1",
        "provenance": "Synthetic provider specification authored before this experiment; not a real-world attestation.",
        "expected_cluster_population": list(EXPECTED_CLUSTERS),
        "field_definitions": dict(DEFINITIONS),
        "windows": {"baseline": {"start": (clock - timedelta(days=14)).isoformat(), "end": (clock - timedelta(days=7)).isoformat()},
                    "current": {"start": (clock - timedelta(days=7)).isoformat(), "end": clock.isoformat()}},
        "export_semantics": "These are closed UTC reporting windows. Aggregates cover exactly the exported memberships. Absent fields or null values are unavailable, never zero. Cluster membership does not certify coverage of clusters outside that membership.",
    }
    # Expectations are not observed coverage. Keep actual membership in values.
    source["contract"]["population"] = "Expected customer cluster fleet: eu-1, us-1, ap-1. Observed membership is declared in evidence values."
    source["contract"]["grain"] = "Fleet aggregate per closed reporting week; latency is p95, not a mean."
    return result


def normalize(case):
    result = copy.deepcopy(case)
    source = primary(result)
    values = source["evidence"][0]["values"]
    observations = []
    for suffix, metric in (("p95_ms", "query_p95_latency"), ("lag_ms", "replication_lag")):
        current, baseline = values.get(f"current_{suffix}"), values.get(f"baseline_{suffix}")
        change = 100 * (current - baseline) / baseline if current is not None and baseline not in (None, 0) else None
        observations.append(Observation(
            source_key=source["source_key"], subject_id=source["resource"],
            subject_label=source["title"], metric=metric, unit="ms", current=current,
            baseline=baseline, change_pct=change,
            attributes={"field_mapping": {"current": f"current_{suffix}", "baseline": f"baseline_{suffix}"},
                        "provenance": "Deterministic normalization of the retained evidence values; no completeness inference."},
        ).model_dump(mode="json"))
    source["observations"] = observations
    return result


def oracle(case):
    """Fixture rule only, never sent to the model. Does not validate source truth."""
    source = primary(case)
    values = source["evidence"][0]["values"]
    expected = set(source["metadata"]["provider_contract"]["expected_cluster_population"])
    baseline_members = values.get("baseline_cluster_population", values.get("cluster_population"))
    current_members = values.get("current_cluster_population", values.get("cluster_population"))
    fields = ("baseline_p95_ms", "current_p95_ms", "baseline_lag_ms", "current_lag_ms", "affected_regions")
    if (baseline_members is None or current_members is None
            or set(baseline_members) != expected or set(current_members) != expected
            or any(values.get(k) is None for k in fields)):
        return "insufficient_data"
    if (values["current_p95_ms"] * 100 >= values["baseline_p95_ms"] * 120
            and values["current_lag_ms"] >= values["baseline_lag_ms"] * 2
            and values["affected_regions"] >= 2):
        return "investigate"
    return "ignore"


def build(trace: Path):
    card, _, original_cases = prepare(trace)
    if len(original_cases) != 3 or {c["expected_outcome"] for c in original_cases} != {"ignore", "investigate", "insufficient_data"}:
        raise ValueError("Requires the retained operations three-case history")
    event = next(c for c in original_cases if c["expected_outcome"] == "investigate")
    documented = [document(c) for c in original_cases]
    controls = []
    for name in ("partial_membership", "different_memberships", "missing_baseline"):
        # Put missingness on an otherwise actionable signal. A quiet sibling
        # with another conclusively false conjunct could short-circuit the rule.
        case = document(event)
        case["id"] = "case-" + digest(name)[:16]
        values = primary(case)["evidence"][0]["values"]
        if name == "partial_membership":
            values["cluster_population"] = ["eu-1"]
        elif name == "different_memberships":
            values["cluster_population"] = None
            values["baseline_cluster_population"] = list(EXPECTED_CLUSTERS)
            values["current_cluster_population"] = ["eu-1", "us-1"]
        else:
            values["baseline_p95_ms"] = None
        controls.append(case)
    rows = []
    for case in [*documented, *controls]:
        outcome = oracle(case)
        methods = [m for m in card["delivery_methods"] if m["outcome"] == outcome]
        case.update(expected_outcome=outcome,
                    expected_delivery_method_keys=[m["key"] for m in methods],
                    expected_delivery_destinations={m["key"]: m["destination"] for m in methods})
        for arm, payload in (("documented", case), ("documented_typed", normalize(case))):
            rows.append({"arm": arm, "scope": "primary", "case": payload})
    for case in original_cases:
        for arm, payload in (("original", case), ("original_typed", normalize(case))):
            rows.append({"arm": arm, "scope": "diagnostic_legacy_labels", "case": payload})
    # Same card, version, policy, plan and threshold in every cell.
    return {"card": card, "rows": rows}


def score(row, report):
    case = report["cases"][0] if report["cases"] else {}
    wanted = row["case"]["expected_outcome"]
    # follow_up_guidance belongs to the retained card; these are handoffs, not sends.
    mapping = {"ignore": ("suppress", "complete"), "investigate": ("retrieve_evidence", "pending"), "insufficient_data": ("repair_source", "blocked")}
    expected_action, expected_status = mapping[wanted]
    workflow = case.get("workflow") or {}
    actual_action = workflow.get("action")
    handoff_pair = (actual_action, workflow.get("status"))
    actual_keys = set(case.get("actual_delivery_method_keys", []))
    expected_keys = set(row["case"].get("expected_delivery_method_keys", []))
    route_exact = case.get("actual_delivery_destinations") == row["case"].get("expected_delivery_destinations") and actual_keys == expected_keys
    handoff_matches_gold = handoff_pair == (expected_action, expected_status) and set(workflow.get("delivery_method_keys", [])) == expected_keys
    handoff_consistent = handoff_pair == mapping.get(case.get("outcome")) and set(workflow.get("delivery_method_keys", [])) == actual_keys
    return {"exact": report["acceptance_passed"] is True and handoff_matches_gold,
            "outcome_exact": case.get("outcome") == wanted, "route_exact": route_exact,
            "handoff_matches_gold": handoff_matches_gold, "handoff_consistent_with_actual_outcome": handoff_consistent,
            "expected_outcome": wanted, "outcome": case.get("outcome"),
            "expected_workflow_action": expected_action, "workflow_action": actual_action,
            "unnecessary_investigation_handoff": wanted == "ignore" and actual_action == "retrieve_evidence",
            "misdirected_data_repair": wanted == "insufficient_data" and actual_action == "retrieve_evidence",
            "false_sentalert": "not measured; no delivery sink invoked",
            "false_suppression": wanted != "ignore" and actual_action == "suppress",
            "model_support": case.get("confidence"), "probabilities": case.get("probabilities", {}),
            "failure_reasons": case.get("failure_reasons", []), "error": case.get("error")}


async def freeze(trace, output):
    inputs = build(trace)
    output.mkdir(parents=True, exist_ok=False)
    schedule = schedule_for(len(inputs["rows"]))
    protocol = {"version": VERSION, "input_digest": digest(inputs), "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "implementation_sha256": implementation_hashes(),
                "code": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "attempt_cap": len(schedule), "schedule": schedule,
                "scope": "Known-family in-process component experiment, not onboarding, autonomous discovery or customer proof",
                "gate": "Each primary arm passes only if all 6 cases in both repetitions match outcome, exact routes, required evidence/retrieval and workflow handoff; no errors or missing attempts.",
                "zero_real_deliveries": True, "retries": 0,
                "comparative_claims": False}
    write_exclusive(output / "inputs.json", inputs)
    write_exclusive(output / "protocol.json", protocol)
    return protocol


async def execute(plan, output, key_file):
    inputs = json.loads((plan / "inputs.json").read_text())
    protocol = json.loads((plan / "protocol.json").read_text())
    if (digest(inputs) != protocol["input_digest"] or implementation_hashes() != protocol["implementation_sha256"]
            or protocol["schedule"] != schedule_for(len(inputs["rows"]))
            or len(protocol["schedule"]) != protocol["attempt_cap"] or protocol["attempt_cap"] != 36):
        raise ValueError("Frozen inputs or runner changed; freeze a new protocol")
    output.mkdir(parents=True, exist_ok=False)
    write_exclusive(output / "protocol.json", protocol)
    write_exclusive(output / "inputs.json", inputs)
    key = key_file.read_text().strip()
    audit = Audit(output / "trace.jsonl", (key,))
    budget = RequestBudget(protocol["attempt_cap"])
    judger = MeasuredJev(key, budget, audit)
    results = []
    for number, entry in enumerate(protocol["schedule"]):
        row = inputs["rows"][entry["index"]]
        audit.episode = f"attempt-{number:03d}"
        case = CardEvaluationCase.model_validate({**row["case"], "card": inputs["card"]})
        report = await CardWorkflowEvaluator(InsightEngine(judger)).evaluate([case], acceptance_outcomes=[case.expected_outcome])
        serialized = report.model_dump(mode="json")
        result = {**entry, "arm": row["arm"], "scope": row["scope"], "report": serialized, "score": score(row, serialized)}
        results.append(result)
        write_exclusive(output / f"attempt-{number:03d}.json", audit.redact(result))
    by_arm = defaultdict(list)
    for row in results:
        by_arm[row["arm"]].append(row["score"])
    summary = {arm: {"exact": sum(x["exact"] for x in rows), "intended": sum(inputs["rows"][x["index"]]["arm"] == arm for x in protocol["schedule"]),
                     "false_suppression": sum(x["false_suppression"] for x in rows),
                     "unnecessary_investigation_handoffs": sum(x["unnecessary_investigation_handoff"] for x in rows),
                     "misdirected_data_repairs": sum(x["misdirected_data_repair"] for x in rows),
                     "outcome_exact": sum(x["outcome_exact"] for x in rows),
                     "route_exact": sum(x["route_exact"] for x in rows),
                     "handoff_matches_gold": sum(x["handoff_matches_gold"] for x in rows),
                     "handoff_consistent_with_actual_outcome": sum(x["handoff_consistent_with_actual_outcome"] for x in rows),
                     "errors": sum(x["error"] is not None for x in rows)} for arm, rows in by_arm.items()}
    responses = [e for e in audit.events if e.get("kind") == "api.response"]
    models = sorted({e["response"].get("model", "unknown") for e in responses})
    gates = {arm: rows["exact"] == rows["intended"] and rows["errors"] == 0
             and len(responses) == protocol["attempt_cap"] and len(models) == 1 and models != ["unknown"]
             for arm, rows in summary.items() if arm in {"documented", "documented_typed"}}
    result = {"summary": summary, "attempts": budget.used, "budget_censored": budget.exhausted,
              "resolved_models": models, "primary_gates": gates, "results": results}
    write_exclusive(output / "report.json", audit.redact(result))
    return {"summary": summary, "attempts": budget.used, "resolved_models": models, "primary_gates": gates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live:
        if args.plan is None or args.key_file is None or args.trace:
            parser.error("Live requires --plan and --key-file; no --trace")
        result = asyncio.run(execute(args.plan, args.output, args.key_file))
    else:
        if args.trace is None or args.plan or args.key_file:
            parser.error("Freeze requires --trace only, no key or plan")
        result = asyncio.run(freeze(args.trace, args.output))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

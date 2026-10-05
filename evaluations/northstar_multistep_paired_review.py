"""Independent integrity review for the live Northstar multi-step comparison.

The trial runner is intentionally not the authority on its own result.  This
reviewer rebuilds the checked-in cases, recomputes final exactness from raw
submissions, and checks parity/oracle-separation properties before any result
is used in a report.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluations.northstar_multistep_paired_trial import (
    DEFAULT_HISTORY_SPEC,
    DEFAULT_SEED,
    DEFAULT_SPEC,
    _agent_prompt,
    _digest,
    _tool_specs,
    build_cases,
)


def _covered_required(required: set[str], evidence: set[str]) -> set[str]:
    return {
        ref
        for ref in required
        if ref in evidence or any(item.startswith(ref + "|") for item in evidence)
    }


def _known_refs(case: dict[str, Any], run: dict[str, Any]) -> set[str]:
    known = {
        str(chart["id"])
        for chart in case["shared_input"]["cached_charts"]
    }
    known.update(str(source["ref"]) for source in case["sources"])
    for event in run.get("events", []):
        summary = event.get("result_summary") or {}
        known.update(str(ref) for ref in summary.get("evidence_refs", []) or [])
        known.update(str(ref) for ref in summary.get("context_fact_ids", []) or [])
    known.update(str(ref) for ref in (run.get("preflight") or {}).get("evidence_refs", []) or [])
    return known


def _score(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    label = case["label"]
    initial = run.get("initial_submission") or {}
    final = run.get("final_submission") or {}
    evidence = {str(ref) for ref in final.get("evidence_refs", [])}
    required = {str(ref) for ref in label["required_final_evidence"]}
    allowed = (
        {str(chart["id"]) for chart in case["shared_input"]["cached_charts"]}
        | {str(source["ref"]) for source in case["sources"]}
        | {str(fact["fact_id"]) for fact in case["diagnostic_facts"]}
    )
    covered = _covered_required(required, evidence)
    provenance = bool(evidence) and evidence <= _known_refs(case, run) and evidence <= allowed
    # Keep the safety denominator aligned with the trial scorer. A terminal
    # insufficient_data result is an automated abstention; if it is wrong it
    # is still an unsafe automated outcome.
    automatic = final.get("outcome") in {"ignore", "notify", "insufficient_data", "escalate"}
    exact = bool(
        initial
        and initial.get("stage") == "initial"
        and initial.get("outcome") == label["expected_initial"]
        and initial.get("delivery") == label["initial_delivery"]
        and final
        and final.get("stage") in {"initial", "final"}
        and final.get("outcome") == label["expected_final"]
        and final.get("delivery") == label["final_delivery"]
        and covered == required
        and evidence <= allowed
        and provenance
        and not run.get("protocol_errors")
        and not run.get("oracle_leaks")
    )
    return {
        "case_id": case["case_id"],
        "arm": run.get("arm"),
        "scenario": case["scenario"],
        "exact": exact,
        "unsafe_automatic_action": bool(automatic and not exact),
        "evidence_recall": len(covered) / len(required) if required else 1.0,
        "provenance_complete": provenance,
        "protocol_ok": not bool(run.get("protocol_errors")),
        "oracle_leaks": int(run.get("oracle_leaks", 0)),
        "context_retrieved": bool(run.get("context_retrieved")),
        "tool_calls": int(run.get("tool_calls", 0)),
        "api_requests": int(run.get("api_requests", 0)),
        "elapsed_ms": float(run.get("end_to_end_elapsed_ms", run.get("elapsed_ms", 0.0))),
        "agent_elapsed_ms": float(run.get("elapsed_ms", 0.0)),
        "preflight_elapsed_ms": float(run.get("preflight_elapsed_ms", 0.0)),
        "query_calls": len(run.get("query_calls", [])),
        "physical_query_executions": sum(
            not call.get("cache_hit", False) for call in run.get("query_calls", [])
        ),
        "bytes_scanned": sum(int(call.get("bytes_scanned", 0)) for call in run.get("query_calls", [])),
        "cpu_seconds": sum(int(call.get("cpu_seconds", 0)) for call in run.get("query_calls", [])),
        "jev": run.get("jev", {"requests": 0, "input_tokens": 0, "output_tokens": 0}),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    return round(values[middle], 2) if len(values) % 2 else round(
        (values[middle - 1] + values[middle]) / 2, 2
    )


def _summarize(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    selected = [row for row in rows if row["arm"] == arm]
    return {
        "n": len(selected),
        "final_exact": sum(row["exact"] for row in selected),
        "final_exact_rate": round(sum(row["exact"] for row in selected) / len(selected), 4) if selected else 0.0,
        "unsafe_automatic_actions": sum(row["unsafe_automatic_action"] for row in selected),
        "unsafe_automatic_action_rate": round(
            sum(row["unsafe_automatic_action"] for row in selected) / len(selected), 4
        ) if selected else 0.0,
        "mean_evidence_recall": round(
            sum(row["evidence_recall"] for row in selected) / len(selected), 4
        ) if selected else 0.0,
        "protocol_ok": sum(row["protocol_ok"] for row in selected),
        "oracle_leaks": sum(row["oracle_leaks"] for row in selected),
        "median_elapsed_ms": _median([row["elapsed_ms"] for row in selected]),
        "median_agent_elapsed_ms": _median([row["agent_elapsed_ms"] for row in selected]),
        "mean_preflight_elapsed_ms": round(
            sum(row["preflight_elapsed_ms"] for row in selected) / len(selected), 2
        ) if selected else 0.0,
        "mean_tool_calls": round(sum(row["tool_calls"] for row in selected) / len(selected), 2)
        if selected else 0.0,
        "query_calls": sum(row["query_calls"] for row in selected),
        "physical_query_executions": sum(row["physical_query_executions"] for row in selected),
        "bytes_scanned": sum(row["bytes_scanned"] for row in selected),
        "cpu_seconds": sum(row["cpu_seconds"] for row in selected),
        "jev_requests": sum(row["jev"]["requests"] for row in selected),
        "jev_input_tokens": sum(row["jev"]["input_tokens"] for row in selected),
        "jev_output_tokens": sum(row["jev"]["output_tokens"] for row in selected),
    }


def review_report(
    report_path: str | Path,
    *,
    spec_path: str | Path = DEFAULT_SPEC,
    history_spec_path: str | Path = DEFAULT_HISTORY_SPEC,
    seed_dir: str | Path = DEFAULT_SEED,
) -> dict[str, Any]:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in build_cases(
        seed_dir=Path(seed_dir), spec_path=Path(spec_path), history_spec_path=Path(history_spec_path)
    )}
    findings: list[str] = []
    raw_runs = list(report.get("raw_runs", []))
    by_case: dict[str, dict[str, dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []

    if report.get("trial") != "northstar-live-jev-assisted-luna-multistep":
        findings.append("unexpected trial identifier")
    if report.get("live_jev") is not True:
        findings.append("report is not marked live_jev=true")
    if len(raw_runs) != len(cases) * 2:
        findings.append(f"expected {len(cases) * 2} raw runs, found {len(raw_runs)}")

    expected_tool_digest = _digest(_tool_specs())
    for run in raw_runs:
        case_id = str(run.get("case_id"))
        arm = str(run.get("arm"))
        if case_id not in cases:
            findings.append(f"unknown case {case_id!r}")
            continue
        if arm not in {"baseline", "treatment"}:
            findings.append(f"case {case_id} has invalid arm {arm!r}")
            continue
        if arm in by_case.setdefault(case_id, {}):
            findings.append(f"case {case_id} has duplicate {arm} run")
        by_case[case_id][arm] = run
        rows.append(_score(cases[case_id], run))
        if run.get("tool_schema_digest") != expected_tool_digest:
            findings.append(f"case {case_id}/{arm} tool schema differs from checked-in schema")
        if run.get("shared_input_digest") != _digest(cases[case_id]["shared_input"]):
            findings.append(f"case {case_id}/{arm} shared input differs from fixture")
        if run.get("prompt_digest") != _digest(_agent_prompt(cases[case_id], False)):
            findings.append(f"case {case_id}/{arm} base prompt differs from fixture")
        if run.get("oracle_leaks"):
            findings.append(f"case {case_id}/{arm} exposed oracle fields")

    for case_id, arms in by_case.items():
        if set(arms) != {"baseline", "treatment"}:
            findings.append(f"case {case_id} is not paired exactly once")
            continue
        baseline, treatment = arms["baseline"], arms["treatment"]
        for field in ("shared_input_digest", "prompt_digest", "tool_schema_digest", "model"):
            if baseline.get(field) != treatment.get(field):
                findings.append(f"case {case_id} differs across arms in {field}")
        if baseline.get("query_calls") != treatment.get("query_calls"):
            findings.append(f"case {case_id} has non-identical query tool traces across arms")

    recomputed = {
        "baseline": _summarize(rows, "baseline"),
        "treatment": _summarize(rows, "treatment"),
    }
    for arm, summary in recomputed.items():
        stored = report.get("arms", {}).get(arm, {})
        for key, value in summary.items():
            if stored.get(key) != value:
                findings.append(f"stored arms.{arm}.{key}={stored.get(key)!r}, recomputed={value!r}")

    actual_scenarios = Counter(cases[case_id]["scenario"] for case_id in by_case if case_id in cases)
    if dict(actual_scenarios) != report.get("scenario_counts"):
        findings.append("scenario_counts do not match fixture-backed raw runs")
    if report.get("input_parity", {}).get("same_shared_input_digest_per_case") is not True:
        findings.append("stored shared-input parity check failed")
    if report.get("input_parity", {}).get("same_model") is not True:
        findings.append("stored model parity check failed")

    return {
        "review": "northstar-multistep-paired-independent-integrity",
        "passed": not findings,
        "findings": findings,
        "cases": len(cases),
        "raw_runs": len(raw_runs),
        "recomputed_arms": recomputed,
        "recomputed_rows": rows,
        "source_report": str(report_path),
        "source_generated_at": report.get("generated_at"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit the live Northstar paired multi-step trial")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--history-spec", type=Path, default=DEFAULT_HISTORY_SPEC)
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    review = review_report(
        args.report,
        spec_path=args.spec,
        history_spec_path=args.history_spec,
        seed_dir=args.seed_dir,
    )
    output = args.output or args.report.with_name("review.json")
    output.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: review[key] for key in ("review", "passed", "findings", "cases", "raw_runs")}, indent=2))
    return 0 if review["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

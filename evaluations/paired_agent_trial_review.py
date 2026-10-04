"""Independent integrity review for a paired agent trial report.

This module deliberately does not call ``score_run`` or trust the stored arm
summaries. It reconstructs the paired rows from the raw runs, re-applies the
fixture's explicit chart-to-source provenance equivalences, and checks the
properties that make the Luna-versus-SignalWeave comparison fair enough to
interpret.

It is an evaluation reviewer, not product runtime.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evaluations.paired_agent_trial import DEFAULT_CASES, _load_cases


def _covered_required(case: dict[str, Any], evidence: set[str]) -> set[str]:
    equivalents = case.get("evidence_equivalents", {})
    return {
        ref
        for ref in case["label"]["required_evidence"]
        if ref in evidence
        or bool(evidence & {str(alias) for alias in equivalents.get(ref, [])})
    }


def _score(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    submission = run.get("submission") or {}
    evidence = {str(ref) for ref in submission.get("evidence_refs", [])}
    required = set(case["label"]["required_evidence"])
    chart_ids = {chart["id"] for chart in case["shared_input"]["cached_charts"]}
    source_refs = {source["ref"] for source in case["sources"]}
    allowed = chart_ids | source_refs
    covered = _covered_required(case, evidence)
    calls = run.get("query_calls", [])
    inspected = {
        event.get("successful_source_ref")
        for event in run.get("events", [])
        if event.get("successful_source_ref")
    }
    preflight_evidence = {
        str(ref)
        for event in run.get("events", [])
        for ref in (event.get("result_summary") or {}).get("evidence_refs", [])
    }
    preflight_evidence.update(
        str(ref) for ref in (run.get("preflight") or {}).get("evidence_refs", [])
    )
    provenance = bool(evidence) and all(
        ref in chart_ids
        or ref in inspected
        or ref in preflight_evidence
        or any(ref in call.get("evidence_refs", []) for call in calls)
        for ref in evidence
    )
    exact = bool(
        submission
        and submission.get("outcome") == case["label"]["outcome"]
        and submission.get("delivery") == case["label"]["delivery"]
        and covered == required
        and not evidence - allowed
        and provenance
        and bool(submission.get("query_justified")) == bool(calls)
        and (not case["label"]["query_required"] or bool(calls))
    )
    automatic = submission.get("outcome") in {"ignore", "notify", "escalate"}
    return {
        "case_id": case["case_id"],
        "arm": run.get("arm"),
        "scenario": case["scenario"],
        "exact": exact,
        "unsafe_automatic_action": automatic and not exact,
        "evidence_recall": len(covered) / len(required) if required else 1.0,
        "provenance_complete": provenance,
        "query_calls": len(calls),
        "physical_query_executions": sum(not call.get("cache_hit", False) for call in calls),
        "bytes_scanned": sum(int(call.get("bytes_scanned", 0)) for call in calls),
        "cpu_seconds": sum(int(call.get("cpu_seconds", 0)) for call in calls),
        "tool_calls": int(run.get("tool_calls", 0)),
        "api_requests": int(run.get("api_requests", 0)),
        "elapsed_ms": float(run.get("end_to_end_elapsed_ms", run.get("elapsed_ms", 0.0))),
        "agent_elapsed_ms": float(run.get("elapsed_ms", 0.0)),
        "preflight_elapsed_ms": float(run.get("preflight_elapsed_ms", 0.0)),
        "oracle_leaks": int(run.get("oracle_leaks", 0)),
        "error": run.get("error"),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    value = values[middle] if len(values) % 2 else sum(values[middle - 1:middle + 1]) / 2
    return round(value, 2)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 2)


def _summarize(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    selected = [row for row in rows if row["arm"] == arm]
    latencies = sorted(row["elapsed_ms"] for row in selected)
    exact = sum(row["exact"] for row in selected)
    unsafe = sum(row["unsafe_automatic_action"] for row in selected)
    return {
        "n": len(selected),
        "exact_decisions": exact,
        "exact_decision_rate": round(exact / len(selected), 4) if selected else 0.0,
        "unsafe_automatic_actions": unsafe,
        "unsafe_automatic_action_rate": round(unsafe / len(selected), 4) if selected else 0.0,
        "provenance_complete": sum(row["provenance_complete"] for row in selected),
        "mean_required_evidence_recall": round(
            sum(row["evidence_recall"] for row in selected) / len(selected), 4
        ) if selected else 0.0,
        "median_elapsed_ms": (
            round(latencies[len(latencies) // 2], 2)
            if latencies and len(latencies) % 2
            else round(sum(latencies[len(latencies) // 2 - 1:len(latencies) // 2 + 1]) / 2, 2)
            if latencies else None
        ),
        "p95_elapsed_ms": (
            round(latencies[max(0, int(len(latencies) * 0.95) - 1)], 2)
            if latencies else None
        ),
        "median_agent_elapsed_ms": _median(
            [float(row.get("agent_elapsed_ms", row["elapsed_ms"])) for row in selected]
        ),
        "p95_agent_elapsed_ms": _p95(
            [float(row.get("agent_elapsed_ms", row["elapsed_ms"])) for row in selected]
        ),
        "mean_preflight_elapsed_ms": round(
            sum(float(row.get("preflight_elapsed_ms", 0.0)) for row in selected) / len(selected), 2
        ) if selected else 0.0,
        "mean_tool_calls": round(sum(row["tool_calls"] for row in selected) / len(selected), 2)
        if selected else 0.0,
        "mean_api_requests": round(sum(row["api_requests"] for row in selected) / len(selected), 2)
        if selected else 0.0,
        "diagnostic_query_calls": sum(row["query_calls"] for row in selected),
        "physical_query_executions": sum(row["physical_query_executions"] for row in selected),
        "bytes_scanned": sum(row["bytes_scanned"] for row in selected),
        "cpu_seconds": sum(row["cpu_seconds"] for row in selected),
        "oracle_leaks": sum(row["oracle_leaks"] for row in selected),
    }


def _compare_summary(stored: dict[str, Any], recomputed: dict[str, Any]) -> list[str]:
    keys = (
        "n", "exact_decisions", "exact_decision_rate", "unsafe_automatic_actions",
        "unsafe_automatic_action_rate", "provenance_complete", "mean_required_evidence_recall",
        "median_elapsed_ms", "p95_elapsed_ms", "median_agent_elapsed_ms", "p95_agent_elapsed_ms",
        "mean_preflight_elapsed_ms", "mean_tool_calls", "mean_api_requests",
        "diagnostic_query_calls", "physical_query_executions", "bytes_scanned", "cpu_seconds",
        "oracle_leaks",
    )
    return [
        f"stored arms.{key}={stored.get(key)!r} but recomputed={recomputed.get(key)!r}"
        for key in keys
        if stored.get(key) != recomputed.get(key)
    ]


def review_report(report_path: str | Path, cases_path: str | Path = DEFAULT_CASES) -> dict[str, Any]:
    report = json.loads(Path(report_path).read_text())
    cases = {case["case_id"]: case for case in _load_cases(cases_path)}
    runs = list(report.get("raw_runs", []))
    findings: list[str] = []
    rows: list[dict[str, Any]] = []

    if report.get("trial") != "signalweave-paired-agent-retrieval":
        findings.append("report trial identifier is not the paired agent trial")
    if not runs:
        findings.append("report contains no raw runs")

    by_case: dict[str, dict[str, dict[str, Any]]] = {}
    for run in runs:
        case_id = str(run.get("case_id"))
        if case_id not in cases:
            findings.append(f"raw run references unknown case {case_id!r}")
            continue
        arm = str(run.get("arm"))
        if arm not in {"baseline", "treatment"}:
            findings.append(f"case {case_id} has unknown arm {arm!r}")
            continue
        if arm in by_case.setdefault(case_id, {}):
            findings.append(f"case {case_id} has duplicate {arm} run")
        by_case[case_id][arm] = run
        rows.append(_score(cases[case_id], run))

    if set(by_case) != set(report.get("scenario_counts", {})) and report.get("scenario_counts"):
        actual_counts = Counter(cases[case_id]["scenario"] for case_id in by_case)
        if dict(actual_counts) != report["scenario_counts"]:
            findings.append("scenario_counts do not match the raw run selection")

    for case_id, arms in by_case.items():
        if set(arms) != {"baseline", "treatment"}:
            findings.append(f"case {case_id} does not have exactly one baseline and one treatment run")
            continue
        baseline, treatment = arms["baseline"], arms["treatment"]
        if baseline.get("shared_input_digest") != treatment.get("shared_input_digest"):
            findings.append(f"case {case_id} has different shared input digests")
        if baseline.get("prompt_digest") != treatment.get("prompt_digest"):
            findings.append(f"case {case_id} has different base prompt digests")
        if baseline.get("model") != treatment.get("model"):
            findings.append(f"case {case_id} uses different models across arms")
        if baseline.get("tool_schema_digest") != treatment.get("tool_schema_digest"):
            findings.append(f"case {case_id} uses different tool schemas across arms")
        if baseline.get("oracle_leaks", 0) or treatment.get("oracle_leaks", 0):
            findings.append(f"case {case_id} exposed oracle fields to an agent or tool result")
        if baseline.get("error") or treatment.get("error"):
            findings.append(f"case {case_id} contains a provider or harness error")
        if not baseline.get("submission") or not treatment.get("submission"):
            findings.append(f"case {case_id} has an incomplete final submission")

    recomputed_arms = {
        "baseline": _summarize(rows, "baseline"),
        "treatment": _summarize(rows, "treatment"),
    }
    for arm in recomputed_arms:
        findings.extend(
            f"{arm}: {finding}"
            for finding in _compare_summary(report.get("arms", {}).get(arm, {}), recomputed_arms[arm])
        )
    if report.get("oracle_field_exposure_events") != sum(row["oracle_leaks"] for row in rows):
        findings.append("stored oracle exposure total does not match raw runs")
    if report.get("failures"):
        findings.append("report records failures in the scored denominator")

    return {
        "review": "paired-agent-trial-independent-integrity",
        "passed": not findings,
        "findings": findings,
        "cases": len(by_case),
        "raw_runs": len(runs),
        "recomputed_arms": recomputed_arms,
        "recomputed_rows": rows,
        "source_report": str(report_path),
        "source_generated_at": report.get("generated_at"),
        "source_seed": report.get("seed"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit a paired SignalWeave agent trial report")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = review_report(args.report, args.cases)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

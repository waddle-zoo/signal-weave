"""Independent adversarial review for the everything-tracking trial.

The reviewer does not call SignalWeave or reuse its outcome logic.  It checks
the generated report against the scenario oracle for unsafe actions, evidence
coverage, result integrity, and scenario diversity.  It is deliberately a
research reviewer: a passing report means the experiment was scored honestly,
not that the underlying labels are true for a real company.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    from evaluations.everything_tracking_trial import DEFAULT_CONFIG, build_cases, load_config
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from everything_tracking_trial import DEFAULT_CONFIG, build_cases, load_config


@dataclass(frozen=True)
class Finding:
    reviewer: Literal["correctness", "scope", "generalization", "integrity"]
    severity: Literal["error", "warning"]
    message: str
    case_id: str | None = None


ReviewerName = Literal["correctness", "scope", "generalization", "integrity"]
SeverityName = Literal["error", "warning"]


def audit_report(report: dict[str, Any], cases: list[Any]) -> dict[str, Any]:
    findings: list[Finding] = []
    by_case = {case.case_id: case for case in cases}

    def add(
        reviewer: ReviewerName,
        severity: SeverityName,
        message: str,
        case_id: str | None = None,
    ) -> None:
        findings.append(Finding(reviewer, severity, message, case_id))

    design = report.get("design", {})
    if int(design.get("companies", 0)) < 6:
        add("generalization", "error", "fewer than six enterprise shapes were evaluated")
    if len(design.get("adapters", [])) < 10:
        add("generalization", "error", "heterogeneous source coverage is too narrow")
    if min(design.get("sources_per_case", [0])) < 7:
        add("generalization", "error", "cases do not contain enough mixed evidence and decoys")
    expected_case_ids = set(by_case)

    for arm_name, arm_payload in report.get("arms", {}).items():
        arm_results = report.get("results", {}).get("baseline" if arm_name == "movement_only" else arm_name, [])
        is_treatment = arm_name == "signalweave_jev"
        result_ids = [item.get("case_id") for item in arm_results]
        if set(result_ids) != expected_case_ids:
            add("integrity", "error", f"{arm_name} does not contain exactly one result per case")
        if len(result_ids) != len(set(result_ids)):
            add("integrity", "error", f"{arm_name} contains duplicate case results")
        recomputed_exact = 0
        recomputed_unsafe = 0
        recomputed_recall = 0.0
        for item in arm_results:
            case_id = item.get("case_id")
            case = by_case.get(case_id)
            if case is None:
                add("scope", "error", "result refers to a case outside the scenario catalog", case_id)
                continue
            actual = str(item.get("actual_outcome"))
            if actual not in {"ignore", "investigate", "notify", "escalate", "insufficient_data"}:
                add("integrity", "error", f"unknown outcome {actual!r}", case_id)
            expected = str(case.expected_outcome)
            recomputed_exact += actual == expected
            unsafe = actual in {"notify", "escalate"} and expected not in {"notify", "escalate"}
            recomputed_unsafe += unsafe
            if unsafe:
                if is_treatment:
                    add(
                        "correctness",
                        "error",
                        "automatic action was emitted for a non-actionable or untrusted case",
                        case_id,
                    )
            actual_sources = set(item.get("actual_evidence_source_keys", []))
            valid_sources = {resource.source_key for resource in case.resources}
            if not actual_sources <= valid_sources:
                add("scope", "error", "result contains evidence from a source outside the case bundle", case_id)
            expected_sources = set(case.expected_evidence_source_keys)
            recall = len(expected_sources & actual_sources) / len(expected_sources) if expected_sources else 1.0
            recomputed_recall += recall
            if recall < 1.0 and is_treatment:
                add("correctness", "warning", f"required evidence recall was {recall:.1%}", case_id)
            if bool(item.get("unsafe_automatic_action")) != unsafe:
                add("integrity", "error", "reported unsafe-action flag does not match the outcome and oracle", case_id)
            if bool(item.get("exact_outcome")) != (actual == expected):
                add("integrity", "error", "reported exact-outcome flag does not match the oracle", case_id)
        count = len(arm_results)
        if count:
            if abs(float(arm_payload.get("outcome_accuracy", -1)) - recomputed_exact / count) > 1e-4:
                add("integrity", "error", f"{arm_name} outcome accuracy is not reproducible from case results")
            if int(arm_payload.get("unsafe_automatic_actions", -1)) != recomputed_unsafe:
                add("integrity", "error", f"{arm_name} unsafe-action total is not reproducible from case results")
            if abs(float(arm_payload.get("evidence_recall", -1)) - recomputed_recall / count) > 1e-4:
                add("integrity", "error", f"{arm_name} evidence recall is not reproducible from case results")

    if report.get("design", {}).get("expected_labels_sent_to_jev") is not False:
        add("integrity", "error", "the report does not attest that expected labels stayed outside Jev")
    if report.get("arms", {}).get("movement_only", {}).get("requests") != 0:
        add("integrity", "error", "the movement-only baseline unexpectedly used a provider")
    if not report.get("limitations"):
        add("integrity", "warning", "report does not state its synthetic-data limitations")

    return {
        "reviewer": "everything-tracking-adversarial",
        "scenario_count": len(cases),
        "passed": not any(item.severity == "error" for item in findings),
        "findings": [
            {
                "reviewer": item.reviewer,
                "severity": item.severity,
                "message": item.message,
                "case_id": item.case_id,
            }
            for item in findings
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    cases = build_cases(load_config(args.config), repeats=int(report["arms"]["movement_only"]["repeats"]))
    review = audit_report(report, cases)
    print(json.dumps(review, indent=2))
    if not review["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

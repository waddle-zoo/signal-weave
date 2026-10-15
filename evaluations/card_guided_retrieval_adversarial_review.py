"""Audit the live card-guided benchmark without calling a provider.

The benchmark is useful only when retrieval and the final judgment both work.
This reviewer deliberately fails a report that has strong catalog recall but
weak end-to-end decisions, weak evidence roles, or an invalid no-alert case.
It is an acceptance gate, not a claim that synthetic labels represent a real
company.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from evaluations.card_guided_retrieval_benchmark import (
        DEFAULT_CONFIG,
        _load_config,
        build_cases,
    )
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from card_guided_retrieval_benchmark import DEFAULT_CONFIG, _load_config, build_cases

THRESHOLDS = {
    "min_cases": 6,
    "min_retrieval_precision": 0.80,
    "min_retrieval_recall": 0.90,
    "min_outcome_accuracy": 0.90,
    "min_gold_outcome_accuracy": 0.90,
    "min_role_accuracy": 0.80,
    "min_driver_recall": 0.80,
}


def audit_report(
    report: dict[str, Any], *, expected_cases: list[Any] | None = None
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}

    def check(name: str, passed: bool, message: str) -> None:
        checks[name] = passed
        if not passed:
            findings.append({"check": name, "message": message})

    check(
        "benchmark_identity",
        report.get("benchmark")
        in {"card-guided-retrieval", "card-guided-owner-holdout"},
        "Report is not a supported card-guided retrieval benchmark.",
    )
    check(
        "jev_only",
        report.get("model") == "jev-latest",
        "The report must use the live Jev path; a fallback model or fixture is not proof.",
    )
    check(
        "catalog_scale",
        int(report.get("charts_per_case", 0)) >= 1000,
        "The trial must exercise at least 1,000 catalog entries per case.",
    )
    check(
        "case_count",
        int(report.get("cases", 0)) >= THRESHOLDS["min_cases"],
        "The trial must cover the full heterogeneous scenario set.",
    )

    arms = report.get("arms", {})
    guided = arms.get("jev-card-guided", {})
    gold = arms.get("gold-selection-jev", {})
    for name, key in (
        ("guided_arm_present", "jev-card-guided"),
        ("gold_arm_present", "gold-selection-jev"),
        ("lexical_arm_present", "lexical-selection"),
    ):
        check(name, key in arms, f"Required comparison arm {name} is missing.")

    if guided:
        check(
            "guided_retrieval_precision",
            float(guided.get("retrieval_precision", 0.0))
            >= THRESHOLDS["min_retrieval_precision"],
            "Jev card-guided retrieval precision is below the acceptance threshold.",
        )
        check(
            "guided_retrieval_recall",
            float(guided.get("retrieval_recall", 0.0))
            >= THRESHOLDS["min_retrieval_recall"],
            "Jev card-guided retrieval recall is below the acceptance threshold.",
        )
        check(
            "guided_outcome_accuracy",
            float(guided.get("outcome_accuracy", 0.0))
            >= THRESHOLDS["min_outcome_accuracy"],
            "Strong retrieval is not enough: the guided arm does not make the expected decision.",
        )
        check(
            "guided_role_accuracy",
            float(guided.get("decision_role_accuracy", 0.0))
            >= THRESHOLDS["min_role_accuracy"],
            "The promoted evidence roles are not accurate enough to present as explanations.",
        )
        check(
            "guided_driver_recall",
            float(guided.get("driver_recall", 0.0))
            >= THRESHOLDS["min_driver_recall"],
            "The guided arm is missing too many labeled primary drivers.",
        )
    if gold:
        check(
            "gold_decision_accuracy",
            float(gold.get("outcome_accuracy", 0.0))
            >= THRESHOLDS["min_gold_outcome_accuracy"],
            "Even perfect retrieval does not produce the expected decision; the card or judgment contract needs work.",
        )

    rows = report.get("rows", [])
    ignore_rows = [row for row in rows if row.get("expected_outcome") == "ignore"]
    check(
        "no_alert_has_evidence",
        not ignore_rows
        or all(
            row.get("arm") != "gold-selection-jev"
            or int(row.get("selected_count", 0)) > 0
            for row in ignore_rows
        ),
        "The no-alert case must still evaluate normal evidence; zero observations only tests missing-data handling.",
    )
    check(
        "findings_are_recorded",
        not rows
        or all(
            row.get("arm") != "jev-card-guided" or "findings" in row
            for row in rows
        ),
        "Per-observation typed findings are required for independent explanation review.",
    )

    if expected_cases is not None:
        expected_by_id = {case.case_id: case for case in expected_cases}
        reported_case_ids = {
            str(row.get("case_id"))
            for row in rows
            if row.get("case_id") is not None
        }
        check(
            "scenario_catalog_matches",
            reported_case_ids == set(expected_by_id),
            "Reported rows do not cover exactly the independently loaded scenario catalog.",
        )
        labels_match = True
        for row in rows:
            case = expected_by_id.get(row.get("case_id"))
            if case is None:
                labels_match = False
                continue
            if row.get("expected_outcome") != case.expected_outcome:
                labels_match = False
            if row.get("gold_ids") is None or set(row["gold_ids"]) != set(case.gold_roles):
                labels_match = False
            if (
                row.get("gold_evidence_roles") is None
                or row["gold_evidence_roles"] != case.gold_evidence_roles
            ):
                labels_match = False
        check(
            "scenario_labels_verified",
            labels_match,
            "Reported expected outcomes or gold labels do not match the checked-in scenario catalog.",
        )

        aggregates_match = True
        for arm, summary in arms.items():
            arm_rows = [row for row in rows if row.get("arm") == arm]
            if not arm_rows:
                continue
            for key in (
                "retrieval_precision",
                "retrieval_recall",
                "decision_f1",
                "decision_role_accuracy",
                "suggested_role_accuracy",
                "promoted_role_coverage",
                "driver_recall",
                "suggested_driver_recall",
                "outcome_accuracy",
            ):
                if key not in summary or not all(key in row for row in arm_rows):
                    continue
                expected_average = sum(float(row[key]) for row in arm_rows) / len(arm_rows)
                if abs(float(summary[key]) - expected_average) > 1e-4:
                    aggregates_match = False
        check(
            "aggregates_recomputed",
            aggregates_match,
            "One or more reported arm aggregates cannot be reproduced from per-case rows.",
        )

    return {
        "reviewer": "signalweave-card-guided-retrieval-adversarial-v1",
        "status": "pass" if not findings else "fail",
        "checks": checks,
        "findings": findings,
        "thresholds": THRESHOLDS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    expected_cases = build_cases(
        _load_config(args.config), repeats=int(report.get("repeats", 1))
    )
    review = audit_report(report, expected_cases=expected_cases)
    rendered = json.dumps(review, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    raise SystemExit(0 if review["status"] == "pass" else 1)


if __name__ == "__main__":
    main()

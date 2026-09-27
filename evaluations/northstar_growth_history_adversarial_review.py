"""Independent report-only review for the Northstar history replay.

The reviewer does not call Jev and does not share the replay's decision logic.
It checks that the report actually demonstrates the promised operational
property: the control is noisy, SignalWeave does not create unsafe leadership
pushes, and the holdout agent bundle is complete enough to route without a
human reopening every dashboard.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_SPLITS = {"train": 24, "validation": 12, "holdout": 12}


def _finding(severity: str, message: str, *, case_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"severity": severity, "message": message}
    if case_id:
        result["case_id"] = case_id
    return result


def audit_report(report: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    register = report.get("decision_register", {})
    rows = report.get("cases", [])
    overall = report.get("overall", {})
    splits = report.get("splits", {})

    if report.get("trial") != "northstar-growth-historical-decision-replay":
        findings.append(_finding("error", "report is not the Northstar historical decision replay"))
    if register.get("labels_withheld_from_jev") is not True:
        findings.append(_finding("error", "historical labels were not declared withheld from Jev"))
    if register.get("case_count") != 48 or len(rows) != 48:
        findings.append(_finding("error", "report must contain exactly 48 expanded decision cases"))
    if {key: value.get("cases") for key, value in splits.items()} != REQUIRED_SPLITS:
        findings.append(_finding("error", "train/validation/holdout case counts do not match the registered design"))
    if overall.get("movement_only_unnecessary_pushes", 0) <= 0:
        findings.append(_finding("error", "the control did not demonstrate any useless leadership pushes"))

    seen: set[str] = set()
    for row in rows:
        case_id = row.get("case_id")
        if not case_id or case_id in seen:
            findings.append(_finding("error", "case ids must be unique", case_id=case_id))
            continue
        seen.add(case_id)
        if row.get("error"):
            findings.append(_finding("error", f"provider or engine error: {row['error']}", case_id=case_id))
        if row.get("signalweave_unnecessary_push"):
            findings.append(
                _finding(
                    "error",
                    "SignalWeave produced an unnecessary leadership push",
                    case_id=case_id,
                )
            )
        if row.get("signalweave_unnecessary_alert"):
            findings.append(
                _finding(
                    "error",
                    "SignalWeave routed a case that the team's policy says to suppress",
                    case_id=case_id,
                )
            )
        if row.get("signalweave_missed_workflow"):
            findings.append(
                _finding("error", "SignalWeave suppressed a required workflow", case_id=case_id)
            )
        if row.get("explanation_source_recall") != 1.0:
            findings.append(
                _finding("error", "evidence bundle omitted a required source", case_id=case_id)
            )
        if not row.get("explanation_complete"):
            findings.append(_finding("error", "evidence bundle has no complete rationale", case_id=case_id))
        if not row.get("agent_workflow_complete"):
            findings.append(_finding("error", "typed outcome, delivery, or explanation did not complete the agent workflow", case_id=case_id))

    holdout = splits.get("holdout", {})
    for metric in (
        "exact_outcome_rate",
        "exact_delivery_rate",
        "explanation_complete_rate",
        "agent_workflow_completion_rate",
    ):
        if holdout.get(metric) != 1.0:
            findings.append(
                _finding("error", f"holdout {metric} is {holdout.get(metric)!r}, expected 1.0")
            )

    errors = [finding for finding in findings if finding["severity"] == "error"]
    return {
        "review": "northstar-growth-history-adversarial-gate",
        "passed": not errors,
        "findings": findings,
        "summary": {
            "case_count": len(rows),
            "error_count": len(errors),
            "warning_count": len(findings) - len(errors),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    print(json.dumps(audit_report(report), indent=2))


if __name__ == "__main__":
    main()

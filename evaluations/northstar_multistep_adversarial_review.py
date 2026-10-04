"""Independent report-only review for the live Northstar multi-step trial.

This reviewer intentionally does not import the trial's scoring helpers. It
recomputes the safety and integrity claims from the external scenario fixture
and serialized report, looking for premature delivery, missing returned
context, label leakage, and accidental single-step regressions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _finding(severity: str, message: str, *, scenario_id: str | None = None) -> dict[str, Any]:
    finding: dict[str, Any] = {"severity": severity, "message": message}
    if scenario_id:
        finding["scenario_id"] = scenario_id
    return finding


def audit_report(report: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    scenarios = {str(item["id"]): item for item in fixture.get("scenarios", [])}
    rows = report.get("cases", [])
    rows_by_id = {str(row.get("scenario_id")): row for row in rows}

    if report.get("trial") != "northstar-live-jev-multistep-workflow":
        findings.append(_finding("error", "report is not the live Northstar multi-step trial"))
    if report.get("live_jev") is not True:
        findings.append(_finding("error", "trial was not run with live Jev"))
    if report.get("dataset", {}).get("labels_withheld_from_jev") is not True:
        findings.append(_finding("error", "scenario labels were not declared withheld from Jev"))
    if set(rows_by_id) != set(scenarios) or len(rows_by_id) != len(rows):
        findings.append(_finding("error", "report does not contain exactly one unique row per fixture scenario"))
    if report.get("overall", {}).get("jev_requests", 0) <= 0:
        findings.append(_finding("error", "report contains no live Jev requests"))

    expected_actions = {
        "ignore": ("suppress", "complete"),
        "notify": ("deliver", "ready"),
        "escalate": ("deliver", "ready"),
        "investigate": ("retrieve_evidence", "pending"),
        "insufficient_data": ("repair_source", "blocked"),
    }
    for scenario_id, scenario in scenarios.items():
        row = rows_by_id.get(scenario_id)
        if row is None:
            continue
        initial = row.get("initial", {})
        final = row.get("final", {})
        initial_expected = str(scenario["expected_initial"])
        final_expected = str(scenario["expected_final"])
        if row.get("initial_error") or row.get("final_error"):
            findings.append(_finding("error", "live provider or engine error recorded", scenario_id=scenario_id))
        if initial.get("outcome") != initial_expected:
            findings.append(_finding("error", "initial outcome does not match the external scenario oracle", scenario_id=scenario_id))
        if final.get("outcome") != final_expected:
            findings.append(_finding("error", "final outcome does not match the external scenario oracle", scenario_id=scenario_id))
        expected_initial_action, expected_initial_status = expected_actions[initial_expected]
        initial_workflow = initial.get("workflow") or {}
        if (initial_workflow.get("action"), initial_workflow.get("status")) != (
            expected_initial_action,
            expected_initial_status,
        ):
            findings.append(_finding("error", "initial typed handoff does not match the outcome contract", scenario_id=scenario_id))
        expected_final_action, expected_final_status = expected_actions[final_expected]
        final_workflow = final.get("workflow") or {}
        if (final_workflow.get("action"), final_workflow.get("status")) != (
            expected_final_action,
            expected_final_status,
        ):
            findings.append(_finding("error", "final typed handoff does not match the outcome contract", scenario_id=scenario_id))

        if initial_expected in {"investigate", "insufficient_data"} and "leadership" in initial.get("delivery_method_keys", []):
            findings.append(_finding("error", "initial stage exposed leadership delivery before the required next step", scenario_id=scenario_id))
        if final_expected in {"investigate", "insufficient_data"} and "leadership" in final.get("delivery_method_keys", []):
            findings.append(_finding("error", "unresolved final stage exposed leadership delivery", scenario_id=scenario_id))
        fact_count = len(scenario.get("diagnostic_facts", [])) + len(
            scenario.get("additional_diagnostic_facts") or []
        )
        if fact_count and final.get("context_evidence_count") != fact_count:
            findings.append(_finding("error", "final result did not return every supplied diagnostic fact as context evidence", scenario_id=scenario_id))
        if not fact_count and final != initial:
            findings.append(_finding("error", "terminal single-step result changed between initial and final views", scenario_id=scenario_id))
        if not row.get("initial_safe") or not row.get("context_returned"):
            findings.append(_finding("error", "report safety/integrity flag is false", scenario_id=scenario_id))

    overall = report.get("overall", {})
    for metric in (
        "initial_exact_rate",
        "initial_handoff_exact_rate",
        "final_exact_rate",
        "final_handoff_exact_rate",
        "context_returned_rate",
        "multi_stage_final_exact_rate",
        "terminal_single_step_exact_rate",
    ):
        if overall.get(metric) != 1.0:
            findings.append(_finding("error", f"reported {metric} is not 1.0"))

    errors = [item for item in findings if item["severity"] == "error"]
    return {
        "review": "northstar-multistep-adversarial-gate",
        "passed": not errors,
        "findings": findings,
        "summary": {
            "scenario_count": len(rows),
            "error_count": len(errors),
            "warning_count": len(findings) - len(errors),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    review = audit_report(report, fixture)
    print(json.dumps(review, indent=2))
    if not review["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

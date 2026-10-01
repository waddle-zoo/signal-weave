"""Independently audit the longitudinal Northstar panel report.

The producer's scoring code is intentionally not imported. This reviewer
reconstructs the expected workflow matrix from the external fixture and checks
the serialized live report for correctness, safety, longitudinal continuity,
and honest baseline comparison.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _finding(severity: str, message: str, *, workflow_id: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"severity": severity, "message": message}
    if workflow_id:
        item["workflow_id"] = workflow_id
    return item


def audit_report(report: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    months = {str(item["id"]): item for item in fixture.get("months", [])}
    templates = {str(item["id"]): item for item in fixture.get("decision_templates", [])}
    rows = report.get("workflows", [])
    by_id = {str(row.get("workflow_id")): row for row in rows}

    if report.get("trial") != "northstar-longitudinal-panel-signalweave":
        findings.append(_finding("error", "report is not the longitudinal SignalWeave panel trial"))
    if report.get("live_jev") is not True:
        findings.append(_finding("error", "report does not attest to live Jev"))
    if report.get("design", {}).get("labels_withheld_from_jev") is not True:
        findings.append(_finding("error", "owner labels were not declared withheld from Jev"))
    expected_ids = {f"{month_id}:{template_id}" for month_id in months for template_id in templates}
    if set(by_id) != expected_ids or len(by_id) != len(rows):
        findings.append(_finding("error", "report does not contain exactly one unique workflow per month/template pair"))
    if report.get("design", {}).get("persistent_card_id") != "northstar-growth-longitudinal-v1":
        findings.append(_finding("error", "card identity was not persistent across the trial"))
    if report.get("overall", {}).get("errors", 0) != 0:
        findings.append(_finding("error", "the report contains provider or engine errors"))
    if report.get("overall", {}).get("workflows") != len(expected_ids):
        findings.append(_finding("error", "overall workflow count is not reproducible from the fixture"))

    actions = {
        "ignore": ("suppress", "complete"),
        "notify": ("deliver", "ready"),
        "escalate": ("deliver", "ready"),
        "investigate": ("retrieve_evidence", "pending"),
        "insufficient_data": ("repair_source", "blocked"),
    }
    for workflow_id, row in by_id.items():
        month_id, template_id = workflow_id.split(":", 1)
        template = templates.get(template_id)
        month = months.get(month_id)
        if month is not None and template is not None:
            template = {
                **template,
                **month.get("overrides", {}).get(template_id, {}),
            }
        if month is None or template is None:
            findings.append(_finding("error", "workflow references an unknown fixture entry", workflow_id=workflow_id))
            continue
        initial = row.get("initial", {})
        final = row.get("final", {})
        expected_initial = str(template["expected_initial"])
        expected_final = str(template["expected_final"])
        if row.get("initial_error") or row.get("final_error"):
            findings.append(_finding("error", "workflow recorded an evaluation error", workflow_id=workflow_id))
        if initial.get("outcome") != expected_initial:
            findings.append(_finding("error", "initial outcome disagrees with the fixture oracle", workflow_id=workflow_id))
        if final.get("outcome") != expected_final:
            findings.append(_finding("error", "final outcome disagrees with the fixture oracle", workflow_id=workflow_id))
        for label, payload, expected in (
            ("initial", initial, expected_initial),
            ("final", final, expected_final),
        ):
            workflow = payload.get("workflow") or {}
            if (workflow.get("action"), workflow.get("status")) != actions[expected]:
                findings.append(_finding("error", f"{label} typed handoff disagrees with the outcome contract", workflow_id=workflow_id))
        if expected_initial in {"investigate", "insufficient_data"} and "leadership" in initial.get("delivery_method_keys", []):
            findings.append(_finding("error", "initial stage exposed leadership delivery too early", workflow_id=workflow_id))
        if expected_final in {"investigate", "insufficient_data"} and "leadership" in final.get("delivery_method_keys", []):
            findings.append(_finding("error", "final unresolved stage exposed leadership delivery", workflow_id=workflow_id))
        if int(row.get("context_fact_count", 0)) > 0:
            if row.get("context_evidence_count") != row.get("context_fact_count"):
                findings.append(_finding("error", "diagnostic facts were not returned as context evidence", workflow_id=workflow_id))
            if not row.get("parent_receipt_id"):
                findings.append(_finding("error", "multi-stage workflow has no parent receipt link", workflow_id=workflow_id))
        if row.get("evidence_source_recall") != 1.0:
            findings.append(_finding("error", "required evidence source recall was incomplete", workflow_id=workflow_id))
        panel = row.get("panel", {})
        expected_roles = {str(item["group"]) for item in fixture.get("panel", [])}
        if set(panel) != expected_roles or not all(item.get("pass") is True for item in panel.values()):
            findings.append(_finding("error", "the independent role panel did not unanimously pass", workflow_id=workflow_id))
        if row.get("feedback", {}).get("recorded_by") != "feedback-steward":
            findings.append(_finding("error", "feedback was not recorded by the feedback steward", workflow_id=workflow_id))
        if row.get("card_id") != report.get("design", {}).get("persistent_card_id"):
            findings.append(_finding("error", "workflow used a different card identity", workflow_id=workflow_id))

    monthly = report.get("monthly", {})
    for month_id in months:
        summary = monthly.get(month_id)
        if not summary or summary.get("workflows") != len(templates):
            findings.append(_finding("error", "monthly rollup is incomplete", workflow_id=month_id))

    comparison = report.get("baseline_comparison", {})
    if comparison.get("baseline_unnecessary_automatic", 0) <= 0:
        findings.append(_finding("error", "baseline did not demonstrate useless automatic alerts"))
    if comparison.get("signalweave_unnecessary_automatic") != 0:
        findings.append(_finding("error", "SignalWeave produced an unnecessary automatic action"))
    if comparison.get("signalweave_missed_automatic") != 0:
        findings.append(_finding("error", "SignalWeave missed an expected automatic action"))
    if comparison.get("signalweave_automatic_precision", 0) < comparison.get("baseline_automatic_precision", 0):
        findings.append(_finding("error", "SignalWeave automatic precision did not beat the baseline"))

    panel_summary = report.get("panel_summary", {})
    expected_reviews = len(rows)
    for role in {str(item["group"]) for item in fixture.get("panel", [])}:
        if panel_summary.get(role, {}).get("reviews") != expected_reviews:
            findings.append(_finding("error", f"panel summary for {role} is not reproducible"))
        if panel_summary.get(role, {}).get("pass_rate") != 1.0:
            findings.append(_finding("error", f"panel summary for {role} is not unanimous"))

    errors = [item for item in findings if item["severity"] == "error"]
    return {
        "review": "northstar-longitudinal-panel-adversarial-gate",
        "passed": not errors,
        "findings": findings,
        "summary": {
            "workflow_count": len(rows),
            "month_count": len(months),
            "error_count": len(errors),
            "warning_count": len(findings) - len(errors),
            "outcomes": dict(Counter(row.get("final", {}).get("outcome") for row in rows)),
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

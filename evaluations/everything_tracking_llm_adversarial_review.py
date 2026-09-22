"""Independent reviewer for the LLM-versus-SignalWeave benchmark.

The reviewer re-scores provider outputs from the case oracle instead of trusting
the benchmark's reported booleans.  It separates protocol integrity from
promotion readiness: a valid experiment can still be a no-go for automation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from evaluations.everything_tracking_trial import build_cases, load_config

ReviewerName = Literal["integrity", "correctness", "scope", "generalization", "fairness"]
Severity = Literal["error", "warning"]


def _expected_delivery(case: Any) -> list[str]:
    if case.expected_outcome not in {"notify", "escalate"}:
        return []
    return sorted(
        method.key
        for method in case.card.delivery_methods
        if method.outcome.value == case.expected_outcome
    )


def _input_digest(case: Any) -> str:
    sources = []
    for resource in case.resources:
        payload = resource.model_dump(mode="json")
        payload.pop("captured_at", None)
        sources.append(payload)
    payload = {
        "card": case.card.model_dump(mode="json"),
        "sources": sources,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def audit_report(report: dict[str, Any], cases: list[Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    by_case = {case.case_id: case for case in cases}

    def add(reviewer: ReviewerName, severity: Severity, message: str, case_id: str | None = None) -> None:
        findings.append(
            {"reviewer": reviewer, "severity": severity, "message": message, "case_id": case_id}
        )

    design = report.get("design", {})
    if int(design.get("companies", 0)) < 6:
        add("generalization", "error", "fewer than six enterprise shapes were evaluated")
    if len(design.get("adapters", [])) < 30:
        add("generalization", "error", "source diversity is too narrow for the declared everything-tracking claim")
    if design.get("same_card_and_sources_all_arms") is not True:
        add("fairness", "error", "the report does not establish identical card/source inputs")
    if design.get("expected_labels_sent_to_providers") is not False:
        add("fairness", "error", "the report does not establish that labels stayed outside provider input")
    if design.get("direct_llm_and_mediated_llm_same_model") is not True:
        add("fairness", "error", "the direct and mediated LLM arms do not attest to the same model")

    expected_ids = set(by_case)
    recomputed_summaries: dict[str, dict[str, Any]] = {}
    for arm in ("llm-raw", "jev", "llm-signalweave"):
        rows = [row for row in report.get("rows", []) if row.get("arm") == arm]
        row_ids = [row.get("case_id") for row in rows]
        if set(row_ids) != expected_ids:
            add("integrity", "error", f"{arm} does not have exactly one row for every case")
        if len(row_ids) != len(set(row_ids)):
            add("integrity", "error", f"{arm} has duplicate case rows")
        exact = 0
        unsafe = 0
        evidence_recall = 0.0
        errors = 0
        leaks = 0
        for row in rows:
            case_id = row.get("case_id")
            case = by_case.get(case_id)
            if case is None:
                add("scope", "error", "row refers to a case outside the fixture", case_id)
                continue
            if row.get("input_digest") != _input_digest(case):
                add("fairness", "error", "row input digest does not match the case card/source bundle", case_id)
            actual = row.get("actual_outcome")
            actual_delivery = sorted(row.get("actual_delivery", []))
            actual_evidence = set(row.get("actual_evidence_source_keys", []))
            valid_sources = {resource.source_key for resource in case.resources}
            expected_evidence = set(case.expected_evidence_source_keys)
            expected_delivery = _expected_delivery(case)
            exact_expected = bool(
                row.get("error") is None
                and actual == case.expected_outcome
                and actual_delivery == expected_delivery
                and expected_evidence <= actual_evidence
                and actual_evidence <= valid_sources
                and row.get("provenance_valid") is True
                and row.get("oracle_leaks") == 0
            )
            unsafe_expected = actual in {"notify", "escalate"} and not exact_expected
            exact += exact_expected
            unsafe += unsafe_expected
            errors += row.get("error") is not None
            leaks += int(row.get("oracle_leaks", 0) or 0)
            if row.get("error") is not None:
                add("integrity", "error", "provider error occurred during evaluation", case_id)
            evidence_recall += (
                len(expected_evidence & actual_evidence) / len(expected_evidence)
                if expected_evidence
                else 1.0
            )
            if actual_evidence - valid_sources:
                add("scope", "error", "provider cited an evidence source outside the supplied bundle", case_id)
            if bool(row.get("exact")) != exact_expected:
                add("integrity", "error", "reported exact flag does not match independent scoring", case_id)
            if bool(row.get("unsafe_automatic_action")) != unsafe_expected:
                add("integrity", "error", "reported unsafe-action flag does not match independent scoring", case_id)
            if int(row.get("oracle_leaks", 0) or 0) != 0:
                add("fairness", "error", "provider prompt contained an oracle field name", case_id)
            if unsafe_expected and arm in {"jev", "llm-signalweave"}:
                add("correctness", "error", "treated path emitted an unsafe automatic action", case_id)
        count = len(rows)
        recomputed = {
            "cases": count,
            "exact": exact,
            "exact_rate": round(exact / count, 4) if count else 0.0,
            "unsafe_automatic_actions": unsafe,
            "evidence_recall": round(evidence_recall / count, 4) if count else 0.0,
            "errors": errors,
            "oracle_leaks": leaks,
        }
        recomputed_summaries[arm] = recomputed
        reported = report.get("arms", {}).get(arm, {})
        for key in ("cases", "exact", "unsafe_automatic_actions", "errors", "oracle_leaks"):
            if reported.get(key) != recomputed[key]:
                add("integrity", "error", f"{arm} aggregate {key} is not reproducible")
        for key in ("exact_rate", "evidence_recall"):
            if abs(float(reported.get(key, -1)) - recomputed[key]) > 1e-4:
                add("integrity", "error", f"{arm} aggregate {key} is not reproducible")

    paired_ids = {row.get("case_id") for row in report.get("paired_rows", [])}
    if paired_ids != expected_ids:
        add("integrity", "error", "paired rows do not cover every case")

    protocol_errors = [item for item in findings if item["severity"] == "error"]
    safety_counts = {
        arm: recomputed_summaries.get(arm, {}).get("unsafe_automatic_actions", 0)
        for arm in ("llm-raw", "jev", "llm-signalweave")
    }
    promotion_ready = not protocol_errors and all(value == 0 for value in safety_counts.values())
    return {
        "reviewer": "everything-tracking-llm-adversarial",
        "scenario_count": len(cases),
        "protocol_passed": not protocol_errors,
        "promotion_ready": promotion_ready,
        "verdict": "PROMOTE" if promotion_ready else "NO-GO FOR AUTONOMOUS DELIVERY",
        "finding_count": len(findings),
        "finding_counts": dict(Counter(item["severity"] for item in findings)),
        "safety_counts": safety_counts,
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    cases = build_cases(
        load_config(args.config),
        repeats=int(report.get("repeats", 1)),
    )
    review = audit_report(report, cases)
    print(json.dumps(review, indent=2))
    if not review["protocol_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

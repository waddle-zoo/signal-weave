"""Review one operator-labeled Preset shadow result.

The live onboarding runner proves transport, authorization, approval, Jev
provenance, and delivery-disabled replay.  This separate gate adds the one
piece a fixture cannot provide: a human owner labels whether the returned
decision was useful for the stated card.  It never calls Preset or Jev and it
does not claim statistical accuracy from one label.  It produces an auditable
acceptance observation that can be accumulated across a customer holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from signalweave.models import Outcome

try:
    from evaluations.preset_live_onboarding_review import (
        review_report as review_onboarding_report,
    )
except ModuleNotFoundError:  # Direct ``python evaluations/...py`` invocation.
    from preset_live_onboarding_review import review_report as review_onboarding_report


def _digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"could not read {label}: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _evidence_subjects(result: dict[str, Any]) -> set[str]:
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        return set()
    return {
        subject_id
        for item in evidence
        if isinstance(item, dict)
        for subject_id in [item.get("subject_id")]
        if isinstance(subject_id, str) and subject_id
    }


def _delivery_keys(result: dict[str, Any]) -> set[str]:
    delivery_methods = result.get("delivery_methods")
    if not isinstance(delivery_methods, list):
        return set()
    return {
        key
        for item in delivery_methods
        if isinstance(item, dict)
        for key in [item.get("key")]
        if isinstance(key, str) and key
    }


def review_report(
    report: dict[str, Any], assessment: dict[str, Any]
) -> dict[str, Any]:
    """Independently review an operator assessment against one shadow report."""

    findings: list[str] = []
    transport_review = review_report_from_onboarding(report)
    if transport_review["passed"] is not True:
        findings.append("the underlying Preset live shadow report failed independent review")

    if assessment.get("trial") != "preset-live-semantic-assessment":
        findings.append("assessment is not a Preset live semantic assessment")
    reviewer_id = assessment.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        findings.append("assessment has no human reviewer_id")
    note = assessment.get("note")
    if not isinstance(note, str) or not note.strip():
        findings.append("assessment requires a non-empty human note")
    if assessment.get("useful") is not True:
        findings.append("operator did not mark the returned result as useful")

    if assessment.get("report_digest") != _digest(report):
        findings.append("assessment is not bound to the exact shadow report digest")

    tenant_id = report.get("tenant_id")
    if assessment.get("tenant_id") != tenant_id:
        findings.append("assessment tenant does not match the shadow report")
    card = (report.get("onboarding") or {}).get("card")
    if not isinstance(card, dict):
        findings.append("shadow report has no onboarding card")
        card = {}
    for field in ("card_id", "card_version"):
        expected = card.get("id" if field == "card_id" else "version")
        if assessment.get(field) != expected:
            findings.append(f"assessment {field} does not match the shadow card")

    evaluation = report.get("evaluation")
    result = evaluation.get("result") if isinstance(evaluation, dict) else None
    if not isinstance(result, dict):
        findings.append("shadow report has no typed evaluation result")
        result = {}
    actual_outcome = result.get("outcome")
    expected_outcome = assessment.get("expected_outcome")
    try:
        Outcome(expected_outcome)
    except (TypeError, ValueError):
        findings.append("assessment expected_outcome is not a supported SignalWeave outcome")
    if expected_outcome != actual_outcome:
        findings.append(
            f"operator expected outcome {expected_outcome!r}, received {actual_outcome!r}"
        )

    actual_subjects = _evidence_subjects(result)
    required_subjects = assessment.get("required_evidence_subjects", [])
    forbidden_subjects = assessment.get("forbidden_evidence_subjects", [])
    if not isinstance(required_subjects, list) or any(
        not isinstance(subject, str) or not subject for subject in required_subjects
    ):
        findings.append("required_evidence_subjects must be a list of non-empty strings")
        required_subjects = []
    if not isinstance(forbidden_subjects, list) or any(
        not isinstance(subject, str) or not subject for subject in forbidden_subjects
    ):
        findings.append("forbidden_evidence_subjects must be a list of non-empty strings")
        forbidden_subjects = []
    missing_subjects = sorted(set(required_subjects) - actual_subjects)
    forbidden_present = sorted(set(forbidden_subjects) & actual_subjects)
    if missing_subjects:
        findings.append("required evidence is missing: " + ", ".join(missing_subjects))
    if forbidden_present:
        findings.append("forbidden evidence was returned: " + ", ".join(forbidden_present))

    expected_delivery = assessment.get("expected_delivery_method_keys", [])
    if not isinstance(expected_delivery, list) or any(
        not isinstance(key, str) or not key for key in expected_delivery
    ):
        findings.append("expected_delivery_method_keys must be a list of non-empty strings")
        expected_delivery = []
    missing_delivery = sorted(set(expected_delivery) - _delivery_keys(result))
    if missing_delivery:
        findings.append("expected delivery methods are missing: " + ", ".join(missing_delivery))

    return {
        "reviewer": "preset-live-semantic-independent",
        "passed": not findings,
        "findings": findings,
        "reviewer_id": reviewer_id,
        "tenant_id": tenant_id,
        "card_id": card.get("id"),
        "actual_outcome": actual_outcome,
        "expected_outcome": expected_outcome,
        "evidence_subjects": sorted(actual_subjects),
        "required_evidence_subjects": sorted(set(required_subjects)),
        "missing_evidence_subjects": missing_subjects,
    }


def review_report_from_onboarding(report: dict[str, Any]) -> dict[str, Any]:
    """Run the underlying transport/safety reviewer before semantic checks."""

    return review_onboarding_report(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("assessment", type=Path, nargs="?")
    parser.add_argument(
        "--print-report-digest",
        action="store_true",
        help="print the canonical SHA-256 digest to bind into the assessment",
    )
    args = parser.parse_args()
    report = _load_json(args.report, label="shadow report")
    if args.print_report_digest:
        print(_digest(report))
        return
    if args.assessment is None:
        parser.error("assessment is required unless --print-report-digest is used")
    assessment = _load_json(args.assessment, label="semantic assessment")
    review = review_report(report, assessment)
    print(json.dumps(review, indent=2, sort_keys=True))
    if not review["passed"]:
        raise SystemExit("Preset live semantic review failed")


if __name__ == "__main__":
    main()

"""Independent review for the frozen owner-labeled card-guided holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from evaluations.card_guided_owner_holdout import (
        DEFAULT_CONFIG,
        DEFAULT_LABELS,
        load_holdout_cases,
    )
    from evaluations.card_guided_retrieval_adversarial_review import audit_report
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from card_guided_owner_holdout import (
        DEFAULT_CONFIG,
        DEFAULT_LABELS,
        load_holdout_cases,
    )
    from card_guided_retrieval_adversarial_review import audit_report


def review_report(report: dict, expected_cases: list[object]) -> dict:
    review = audit_report(report, expected_cases=expected_cases)
    checks = dict(review["checks"])
    findings = list(review["findings"])
    labels_separate = (
        report.get("benchmark") == "card-guided-owner-holdout"
        and report.get("label_source") == "independent-owner-review-v1"
        and report.get("config") != report.get("labels")
    )
    checks["independent_label_source"] = labels_separate
    if not labels_separate:
        findings.append(
            {
                "check": "independent_label_source",
                "message": "The holdout report must identify a separate owner-label source.",
            }
        )
    return {
        **review,
        "reviewer": "signalweave-card-guided-owner-holdout-adversarial-v1",
        "checks": checks,
        "findings": findings,
        "status": "pass" if not findings else "fail",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    review = review_report(report, load_holdout_cases(args.config, args.labels))
    print(json.dumps(review, indent=2, sort_keys=True))
    raise SystemExit(0 if review["status"] == "pass" else 1)


if __name__ == "__main__":
    main()

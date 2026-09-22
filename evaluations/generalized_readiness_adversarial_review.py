"""Independent pass/fail review for the generalized Jev readiness trial."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def review(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    checks["jev_only"] = report.get("jev_only_product_path") is True and report.get("evaluator") == "jev-latest"
    if not checks["jev_only"]:
        failures.append("trial did not use the Jev-only product path")

    bootstrap = report.get("bootstrap", [])
    checks["bootstrap_ready"] = bool(bootstrap) and all(item.get("status") == "ready" for item in bootstrap)
    if not checks["bootstrap_ready"]:
        failures.append("one or more adapter bootstrap checks were not ready")

    retrieval = report.get("retrieval", {})
    checks["retrieval_certified"] = retrieval.get("status") == "approved"
    if not checks["retrieval_certified"]:
        failures.append("retrieval quality did not meet its promotion thresholds")
    checks["retrieval_candidate_recall"] = retrieval.get("candidate_recall", 0) >= 0.99
    checks["retrieval_recommended_precision"] = retrieval.get("recommended_precision", 0) >= 0.99
    checks["retrieval_recommended_recall"] = retrieval.get("recommended_recall", 0) >= 0.99
    checks["retrieval_no_match"] = retrieval.get("no_match_accuracy", 0) >= 0.99
    checks["retrieval_tenant_isolation"] = retrieval.get("unauthorized_ref_count", 1) == 0
    for name in (
        "retrieval_candidate_recall",
        "retrieval_recommended_precision",
        "retrieval_recommended_recall",
        "retrieval_no_match",
        "retrieval_tenant_isolation",
    ):
        if not checks[name]:
            failures.append(f"retrieval check failed: {name}")
    for case in retrieval.get("cases", []):
        if len(case.get("recommended_refs", [])) != len(set(case.get("recommended_refs", []))):
            failures.append(f"retrieval recommendation duplicated a resource: {case.get('case_id')}")

    workflow = report.get("workflow", {})
    checks["workflow_certified"] = workflow.get("status") == "approved"
    checks["workflow_outcome_accuracy"] = workflow.get("outcome_accuracy", 0) >= 0.99
    checks["workflow_evidence_recall"] = workflow.get("evidence_recall", 0) >= 0.99
    checks["workflow_retrieval_recall"] = workflow.get("retrieval_recall", 0) >= 0.99
    checks["workflow_zero_unsafe"] = workflow.get("unsafe_action_rate", 1) == 0
    checks["workflow_zero_errors"] = workflow.get("error_rate", 1) == 0
    checks["workflow_time_split_disjoint"] = workflow.get("time_split_disjoint") is True
    for name in (
        "workflow_certified",
        "workflow_outcome_accuracy",
        "workflow_evidence_recall",
        "workflow_retrieval_recall",
        "workflow_zero_unsafe",
        "workflow_zero_errors",
        "workflow_time_split_disjoint",
    ):
        if not checks[name]:
            failures.append(f"workflow check failed: {name}")
    for case in workflow.get("cases", []):
        if case.get("unsafe_action") or case.get("error"):
            failures.append(f"unsafe or failed workflow case: {case.get('case_id')}")

    boundary = report.get("adversarial_review_inputs", {})
    checks["labels_not_sent"] = boundary.get("labels_sent_to_jev") is False and not boundary.get("leaked_label_keys")
    checks["native_search_bounded"] = boundary.get("native_catalog_full_scan_calls") == 0
    checks["dataset_digests"] = boundary.get("dataset_digests_present") is True
    checks["time_splits"] = set(boundary.get("time_splits", [])) >= {"train", "holdout", "adversarial"}
    for name in ("labels_not_sent", "native_search_bounded", "dataset_digests", "time_splits"):
        if not checks[name]:
            failures.append(f"boundary check failed: {name}")

    return {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "checks": checks,
        "reviewer": "signalweave-generalized-readiness-adversarial-v1",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/generalized-readiness-adversarial.json"))
    args = parser.parse_args()
    result = review(json.loads(args.report.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

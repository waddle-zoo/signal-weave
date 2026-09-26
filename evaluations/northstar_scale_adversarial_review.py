"""Independent, report-only gate for the scaled Northstar Jev trial."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_SPLITS = {"train", "validation", "holdout", "adversarial"}
REQUIRED_VARIANTS = {
    "corroborated_notify",
    "explained_ignore",
    "contradictory_investigate",
    "stale_escalation",
    "definition_mismatch",
    "missing_baseline",
    "source_failure",
}


def review(report: dict[str, Any]) -> dict[str, Any]:
    """Audit the saved report without re-running Jev or trusting its labels."""
    failures: list[str] = []
    scale = report.get("scale", {})
    retrieval = report.get("retrieval", {})
    bundle_retrieval = report.get("bundle_retrieval", {})
    workflow = report.get("workflow", {})
    bootstrap = report.get("bootstrap", {}).get("report", {})
    review_inputs = report.get("adversarial_review_inputs", {})
    provenance = report.get("evidence_provenance", {})
    variants = set(scale.get("variant_counts", {}))
    splits = set(review_inputs.get("dataset_splits", []))

    if report.get("evaluator") != "jev-latest":
        failures.append("the recorded evaluator is not Jev")
    if report.get("jev_only_product_path") is not True:
        failures.append("the report does not identify a Jev-only product path")
    if provenance.get("mode") == "retrieval-only-with-reused-workflow":
        if provenance.get("retrieval") != "live-jev":
            failures.append("retrieval-only report does not identify live Jev retrieval")
        if provenance.get("workflow") != "reused-approved-live-jev":
            failures.append("retrieval-only report does not identify approved Jev workflow evidence")
        if not provenance.get("reused_workflow_report"):
            failures.append("retrieval-only report has no workflow evidence provenance")
    if scale.get("role_agents", 0) < 40:
        failures.append("the role graph is smaller than the 40-agent Northstar roster")
    if scale.get("workflow_case_count", 0) < 150:
        failures.append("the workflow population is below the higher-scale gate of 150 cases")
    if scale.get("retrieval_case_count", 0) < 150:
        failures.append("the retrieval population is below the higher-scale gate of 150 cases")
    if scale.get("bundle_case_count", 0) < 150:
        failures.append(
            "the graph-assisted bundle population is below the higher-scale gate of 150 cases"
        )
    if not REQUIRED_VARIANTS <= variants:
        failures.append(f"required messy variants are missing: {sorted(REQUIRED_VARIANTS - variants)}")
    if not REQUIRED_SPLITS <= splits:
        failures.append(f"required time splits are missing: {sorted(REQUIRED_SPLITS - splits)}")
    if bootstrap.get("status") != "ready":
        failures.append(f"bootstrap status is {bootstrap.get('status')!r}, not ready")
    if any(item.get("status") != "ready" for item in bootstrap.get("adapters", [])):
        failures.append("at least one adapter bootstrap check is not ready")
    if retrieval.get("status") != "approved":
        failures.append(f"retrieval status is {retrieval.get('status')!r}, not approved")
    if workflow.get("status") != "approved":
        failures.append(f"workflow status is {workflow.get('status')!r}, not approved")
    if retrieval.get("candidate_recall", 0.0) < 1.0:
        failures.append("retrieval candidate recall is below 1.0")
    if retrieval.get("recommended_recall", 0.0) < 0.90:
        failures.append("retrieval recommended recall is below 0.90")
    if retrieval.get("recommended_precision", 0.0) < 0.90:
        failures.append("retrieval recommended precision is below 0.90")
    if retrieval.get("unauthorized_ref_count", 0) != 0:
        failures.append("retrieval returned unauthorized references")
    if not bundle_retrieval:
        failures.append("the report has no graph-assisted bundle retrieval stage")
    if bundle_retrieval.get("status") != "approved":
        failures.append(
            f"bundle retrieval status is {bundle_retrieval.get('status')!r}, not approved"
        )
    if bundle_retrieval.get("candidate_group_recall", 0.0) < 1.0:
        failures.append("graph expansion missed a required related-source group")
    if bundle_retrieval.get("selected_group_recall", 0.0) < 1.0:
        failures.append("Jev bundle selection missed a required related-source group")
    if bundle_retrieval.get("selected_precision", 0.0) < 0.90:
        failures.append("Jev bundle selected precision is below 0.90")
    if bundle_retrieval.get("error_rate", 1.0) != 0.0:
        failures.append("graph-assisted bundle retrieval had an evaluation error")
    if bundle_retrieval.get("unauthorized_ref_count", 0) != 0:
        failures.append("graph-assisted bundle retrieval returned unauthorized references")
    if workflow.get("unsafe_action_rate", 1.0) != 0.0:
        failures.append("workflow emitted at least one unsafe automatic action")
    if workflow.get("error_rate", 1.0) != 0.0:
        failures.append("workflow had at least one evaluation error")
    if workflow.get("evidence_recall", 0.0) < 1.0:
        failures.append("workflow evidence recall is below 1.0")
    if workflow.get("retrieval_recall", 0.0) < 1.0:
        failures.append("workflow retrieval recall is below 1.0")
    if review_inputs.get("labels_sent_to_jev"):
        failures.append("owner labels were present in recorded Jev state")
    if review_inputs.get("leaked_label_keys"):
        failures.append("label-shaped keys were present in recorded Jev state")
    if review_inputs.get("native_catalog_full_scan_calls") != 0:
        failures.append("the native adapter materialized a full catalog")
    if review_inputs.get("candidate_pool_bound") != 40:
        failures.append("the candidate pool bound is not the declared 40")
    if scale.get("catalog", {}).get("virtual_catalog_size_per_adapter", 0) < 100_000:
        failures.append("the virtual native catalog is below 100k resources per adapter")

    warnings: list[str] = []
    if retrieval.get("required_group_recall", 1.0) < 0.90:
        warnings.append(
            "Seedless discovery did not reliably recover every related context group; "
            "the approved card-anchor graph bundle stage is the required production path."
        )
    return {
        "review": "northstar-scale-adversarial-gate",
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "checks": {
            "evaluator": report.get("evaluator"),
            "workflow_cases": scale.get("workflow_case_count"),
            "retrieval_cases": scale.get("retrieval_case_count"),
            "bundle_cases": scale.get("bundle_case_count"),
            "role_agents": scale.get("role_agents"),
            "variants": sorted(variants),
            "splits": sorted(splits),
            "bootstrap_status": bootstrap.get("status"),
            "retrieval_status": retrieval.get("status"),
            "workflow_status": workflow.get("status"),
            "candidate_recall": retrieval.get("candidate_recall"),
            "recommended_precision": retrieval.get("recommended_precision"),
            "recommended_recall": retrieval.get("recommended_recall"),
            "required_group_recall": retrieval.get("required_group_recall"),
            "bundle_status": bundle_retrieval.get("status"),
            "bundle_candidate_group_recall": bundle_retrieval.get("candidate_group_recall"),
            "bundle_selected_group_recall": bundle_retrieval.get("selected_group_recall"),
            "bundle_selected_precision": bundle_retrieval.get("selected_precision"),
            "outcome_accuracy": workflow.get("outcome_accuracy"),
            "evidence_recall": workflow.get("evidence_recall"),
            "unsafe_action_rate": workflow.get("unsafe_action_rate"),
            "error_rate": workflow.get("error_rate"),
            "full_catalog_scans": review_inputs.get("native_catalog_full_scan_calls"),
            "label_leak": review_inputs.get("labels_sent_to_jev"),
            "evidence_mode": provenance.get("mode"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = review(json.loads(args.report.read_text(encoding="utf-8")))
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

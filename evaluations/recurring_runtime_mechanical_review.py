"""Independent mechanical audit for a recurring runtime trial artifact.

This reviewer does not import the runtime scorer and does not read the private
``oracle`` values embedded in the fixture.  It recomputes the selected source
arithmetic from the raw snapshots, then checks the expected route matrix,
report status, provenance, paired-arm identity, replay behavior and telemetry
claims.  It is intentionally boring: a mutated report must fail loudly.
"""

from __future__ import annotations

import argparse
import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

from evaluations.recurring_runtime_transfer_cases import cases
from signalweave.models import ResourceSnapshot

# These are the private review labels for this frozen transfer cohort.  They
# are kept in this reviewer rather than imported from the trial scorer so a
# mutated scorer cannot make its own output pass.  Arithmetic and provenance
# are still recomputed from each period's public source snapshot below.
EXPECTED: dict[str, dict[str, tuple[str, str | None]]] = {
    "canyon-freight": {
        "p03": ("notify", "fleet-operations"),
        "p04": ("ignore", None),
        "p05": ("insufficient_data", "logistics-data"),
        "p06": ("notify", "fleet-operations"),
    },
    "helio-support": {
        "p03": ("notify", "support-quality"),
        "p04": ("notify", "support-quality"),
        "p05": ("ignore", None),
        "p06": ("insufficient_data", "support-data"),
    },
    "lattice-energy": {
        "p03": ("notify", "commercial-operations"),
        "p04": ("ignore", None),
        "p05": ("ignore", None),
        "p06": ("investigate", "commercial-data"),
    },
}


def _primary(company: dict[str, Any], period: dict[str, Any]) -> ResourceSnapshot:
    key = next(
        source["key"]
        for source in company["sources"]
        if source["parameters"].get("business_role") == "reporting"
    )
    return ResourceSnapshot.model_validate(
        next(item for item in period["resources"] if item["source_key"] == key)
    )


def _arithmetic(company: dict[str, Any], period: dict[str, Any]) -> dict[str, Any]:
    comparison = _primary(company, period).analytical_comparisons[0]
    baseline: dict[str, tuple[int, int] | float] = {}
    current: dict[str, tuple[int, int] | float] = {}
    for segment in comparison.segments:
        if comparison.kind == "rate":
            if (
                segment.baseline.numerator is not None
                and segment.baseline.denominator is not None
                and segment.current.numerator is not None
                and segment.current.denominator is not None
            ):
                baseline[segment.segment] = (
                    int(segment.baseline.numerator),
                    int(segment.baseline.denominator),
                )
                current[segment.segment] = (
                    int(segment.current.numerator),
                    int(segment.current.denominator),
                )
        elif segment.baseline.value is not None and segment.current.value is not None:
            baseline[segment.segment] = float(segment.baseline.value)
            current[segment.segment] = float(segment.current.value)

    complete = (
        comparison.coverage == "complete"
        and comparison.comparable
        and set(baseline) == set(current)
    )
    if not complete:
        return {"complete": False}

    if comparison.kind == "rate":
        baseline_total = (
            sum(value[0] for value in baseline.values()),
            sum(value[1] for value in baseline.values()),
        )
        current_total = (
            sum(value[0] for value in current.values()),
            sum(value[1] for value in current.values()),
        )
        baseline_value = float(Fraction(*baseline_total))
        current_value = float(Fraction(*current_total))
        contributions: dict[str, float] = {}
        for segment in sorted(baseline):
            b_num, b_den = baseline[segment]
            c_num, c_den = current[segment]
            b_rate = Fraction(b_num, b_den)
            c_rate = Fraction(c_num, c_den)
            b_weight = Fraction(b_den, baseline_total[1])
            c_weight = Fraction(c_den, current_total[1])
            contributions[segment] = float(
                (b_weight + c_weight) * (c_rate - b_rate) / 2
                + (b_rate + c_rate) * (c_weight - b_weight) / 2
            )
    else:
        baseline_value = sum(baseline.values())
        current_value = sum(current.values())
        contributions = {
            segment: float(current[segment] - baseline[segment])
            for segment in sorted(baseline)
        }
    return {
        "complete": True,
        "baseline": float(baseline_value),
        "current": float(current_value),
        "delta": float(current_value - baseline_value),
        "contributions": contributions,
        "query_refs": list(comparison.query_refs),
        "metric": comparison.metric,
        "unit": comparison.unit,
        "dimension": comparison.dimension,
        "definition": comparison.definition,
        "population": comparison.population,
        "periods": {
            "baseline_start": comparison.baseline_start.isoformat().replace("+00:00", "Z"),
            "baseline_end": comparison.baseline_end.isoformat().replace("+00:00", "Z"),
            "current_start": comparison.current_start.isoformat().replace("+00:00", "Z"),
            "current_end": comparison.current_end.isoformat().replace("+00:00", "Z"),
        },
    }


def _close(left: Any, right: Any) -> bool:
    return (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
        and math.isclose(float(left), float(right), rel_tol=1e-10, abs_tol=1e-12)
    )


def _analysis_errors(submission: dict[str, Any], company: dict[str, Any], period: dict[str, Any]) -> list[str]:
    expected = _arithmetic(company, period)
    complete = [item for item in submission.get("analyses", []) if item.get("status") == "complete"]
    if not expected["complete"]:
        return ["unexpected_complete_analysis"] if complete else []
    if len(complete) != 1:
        return ["analysis_coverage"]
    actual = complete[0]
    errors: list[str] = []
    for field in ("metric", "unit", "dimension"):
        if actual.get(field) != expected[field]:
            errors.append(field)
    for field in ("baseline", "current", "delta"):
        if not _close(actual.get(field), expected[field]):
            errors.append(field)
    actual_contributions = {
        item.get("segment"): item.get("contribution")
        for item in actual.get("contributions", [])
    }
    if set(actual_contributions) != set(expected["contributions"]):
        errors.append("contribution_coverage")
    for segment, value in expected["contributions"].items():
        if not _close(actual_contributions.get(segment), value):
            errors.append("contribution_value")
    if actual.get("query_refs") != expected["query_refs"]:
        errors.append("provenance")
    comparison = actual.get("comparison", {})
    for field in ("definition", "population"):
        if comparison.get(field) != expected[field]:
            errors.append(field)
    for field, value in expected["periods"].items():
        if comparison.get(field) != value:
            errors.append(field)
    return sorted(set(errors))


def audit_report(report: dict[str, Any], companies: list[dict[str, Any]]) -> dict[str, Any]:
    company_by_id = {company["id"]: company for company in companies}
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    errors: list[str] = []
    rows = report.get("results", [])
    for row in rows:
        company_id, arm = row.get("company"), row.get("arm")
        if company_id not in company_by_id or arm not in {"baseline", "signalweave"}:
            errors.append(f"unexpected_row:{company_id}:{arm}")
            continue
        for run in row.get("runs", []):
            key = (company_id, arm, run.get("period"))
            if key in indexed:
                errors.append(f"duplicate_run:{key}")
            indexed[key] = run

    for company in companies:
        expected_cases = EXPECTED[company["id"]]
        for period in company["periods"]:
            if period.get("split") != "holdout":
                continue
            expected_outcome, expected_recipient = expected_cases[period["id"]]
            for arm in ("baseline", "signalweave"):
                key = (company["id"], arm, period["id"])
                run = indexed.get(key)
                if run is None:
                    errors.append(f"missing_run:{key}")
                    continue
                submission = run.get("submission")
                if not isinstance(submission, dict):
                    errors.append(f"missing_submission:{key}")
                    continue
                expected_status = "blocked" if expected_outcome == "insufficient_data" else "complete"
                if submission.get("status") != expected_status:
                    errors.append(f"status:{key}:{submission.get('status')}!= {expected_status}")
                if submission.get("outcome") != expected_outcome:
                    errors.append(f"outcome:{key}:{submission.get('outcome')}!= {expected_outcome}")
                expected_recipients = [] if expected_recipient is None else [expected_recipient]
                if submission.get("recipients") != expected_recipients:
                    errors.append(f"recipients:{key}:{submission.get('recipients')}!= {expected_recipients}")
                errors.extend(
                    f"analysis:{key}:{error}"
                    for error in _analysis_errors(submission, company, period)
                )

    for company in companies:
        for period in company["periods"]:
            if period.get("split") != "holdout":
                continue
            baseline = indexed.get((company["id"], "baseline", period["id"]), {})
            treatment = indexed.get((company["id"], "signalweave", period["id"]), {})
            for field in ("card_digest", "catalog_digest", "analysis_input_digest"):
                if baseline.get(field) != treatment.get(field):
                    errors.append(f"arm_parity:{company['id']}:{period['id']}:{field}")
            if treatment and treatment.get("replay_exact_no_calls") is not True:
                errors.append(f"replay:{company['id']}:{period['id']}")

    if report.get("usage", {}).get("cost_status") != "complete":
        errors.append("usage_incomplete")
    if report.get("protocol_checks", {}).get("no_foreign_tools") is not True:
        errors.append("foreign_tools")
    if report.get("protocol_checks", {}).get("paired_catalog_and_analysis") is not True:
        errors.append("paired_context")
    if report.get("jev_attempts", 0) <= 0:
        errors.append("no_live_jev_attempts")

    unique_errors = sorted(set(errors))
    return {
        "passed": not unique_errors,
        "checked_runs": len(indexed),
        "expected_runs": len(companies) * 4 * 2,
        "errors": unique_errors,
        "independent_of_trial_score": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    ids = sorted({row["company"] for row in report.get("results", [])})
    companies = [company for company in cases() if company["id"] in ids]
    result = audit_report(report, companies)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

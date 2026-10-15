"""Offline, independent adjudication for completed installed-workflow trials.

This is an after-the-fact checker.  It never calls the binary, Jev, or a source
adapter and it never changes the original report.  Its output is deliberately a
small, secret-free JSON summary suitable for attaching to a frozen run.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    if path.exists() and path.suffix != ".gz":
        return json.loads(path.read_text(encoding="utf-8"))
    compressed = path if path.suffix == ".gz" else Path(f"{path}.gz")
    with gzip.open(compressed, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _existing_artifact(path: Path) -> Path | None:
    if path.exists():
        return path
    compressed = Path(f"{path}.gz")
    return compressed if compressed.exists() else None


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fail(checks: dict[str, dict[str, Any]], name: str, detail: Any) -> None:
    checks[name] = {"passed": False, "detail": detail}


def _pass(checks: dict[str, dict[str, Any]], name: str, detail: Any = None) -> None:
    checks[name] = {"passed": True, **({"detail": detail} if detail is not None else {})}


def _all_passed(checks: dict[str, dict[str, Any]]) -> bool:
    return bool(checks) and all(item.get("passed") is True for item in checks.values())


def _walk_strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return {item for child in value.values() for item in _walk_strings(child)}
    if isinstance(value, list):
        return {item for child in value for item in _walk_strings(child)}
    return set()


def _destination_map(card: dict[str, Any]) -> dict[str, str]:
    return {item["key"]: item["destination"] for item in card.get("delivery_methods", [])}


def _expected_destinations(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value.values())
    if isinstance(value, list):
        return set(value)
    return set()


def _actual_evidence_refs(native: dict[str, Any], card: dict[str, Any]) -> set[str]:
    refs = {
        item.get("source_key")
        for item in [*(native.get("evidence") or []), *(native.get("observations") or [])]
        if isinstance(item, dict) and item.get("source_key")
    }
    source_refs = {
        item.get("key"): f"{item.get('adapter')}|{item.get('resource')}"
        for item in card.get("sources", [])
        if item.get("key") and item.get("adapter") and item.get("resource")
    }
    return {source_refs[key] for key in refs if key in source_refs}


def _retrieval_contract(label: dict[str, Any]) -> tuple[set[str], set[str], list[str]]:
    """Return required/permissible refs and label-format failures.

    ``expected_retrieval_refs`` remains the required retrieval set.  An absent
    or null ``allowed_retrieval_refs`` preserves the legacy exact-set contract.
    """
    expected = label.get("expected_retrieval_refs")
    if not isinstance(expected, list) or not all(isinstance(ref, str) and ref for ref in expected):
        return set(), set(), ["expected_retrieval_refs is not a string list"]
    if len(set(expected)) != len(expected):
        return set(), set(), ["expected_retrieval_refs contains duplicates"]
    required = set(expected)
    allowed_value = label.get("allowed_retrieval_refs")
    if allowed_value is None:
        return required, required, []
    if not isinstance(allowed_value, list) or not all(
        isinstance(ref, str) and ref for ref in allowed_value
    ):
        return required, set(), ["allowed_retrieval_refs is not a string list"]
    allowed = set(allowed_value)
    failures: list[str] = []
    if len(allowed) != len(allowed_value):
        failures.append("allowed_retrieval_refs contains duplicates")
    if not required.issubset(allowed):
        failures.append("allowed_retrieval_refs omits required expected refs")
    return required, allowed, failures


def _adjudicate_native(
    period: dict[str, Any], label: dict[str, Any], card: dict[str, Any],
    public_destinations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute the contract from the native payload and private label."""
    output = period.get("result")
    if not isinstance(output, dict):
        return {"passed": False, "reasons": ["missing native result"]}
    native = output.get("result")
    receipt = output.get("receipt")
    report = output.get("report")
    returned_card = output.get("card")
    reasons: list[str] = []
    if not all(isinstance(item, dict) for item in (native, receipt, report, returned_card)):
        return {"passed": False, "reasons": ["native result, receipt, report, and card are required objects"]}

    card_id = card.get("id")
    ids = {
        "card": returned_card.get("id"),
        "native": native.get("card_id"),
        "receipt": receipt.get("card_id"),
        "report": report.get("card_id"),
    }
    if set(ids.values()) != {card_id}:
        reasons.append("card identity is inconsistent")
    if receipt.get("status") != "delivery_disabled":
        reasons.append("receipt is not delivery_disabled")
    if receipt.get("delivery_enabled") is not False:
        reasons.append("receipt delivery_enabled is not false")
    if receipt.get("delivery_mode") != "shadow":
        reasons.append("receipt delivery_mode is not shadow")
    if report.get("status") in {None, "error", "failed"}:
        reasons.append("report has no acceptable native status")
    if report.get("outcome") != native.get("outcome") or receipt.get("outcome") != native.get("outcome"):
        reasons.append("report outcome differs from native outcome")
    if native.get("report") != report:
        reasons.append("native result report differs from output report")
    if returned_card.get("version") != card.get("version") or receipt.get("card_version") != card.get("version"):
        reasons.append("card version is inconsistent")

    expected_outcome = label.get("outcome")
    actual_outcome = native.get("outcome")
    if actual_outcome != expected_outcome:
        reasons.append("outcome differs from private label")

    card_destinations = _destination_map(card)
    public_destinations_by_key = {
        item.get("key"): item.get("destination")
        for item in public_destinations
        if isinstance(item, dict) and item.get("key") and item.get("destination")
    }
    actual_methods = native.get("delivery_methods")
    if not isinstance(actual_methods, list):
        reasons.append("native delivery_methods is not a list")
        actual_methods = []
    actual_keys = {item.get("key") for item in actual_methods if isinstance(item, dict)}
    expected_endpoints = {
        public_destinations_by_key[key]
        for key in label.get("recipients") or []
        if key in public_destinations_by_key
    }
    actual_endpoints = {item.get("destination") for item in actual_methods if isinstance(item, dict)}
    if len(expected_endpoints) != len(set(label.get("recipients") or [])):
        reasons.append("private-label recipient key is absent from public destinations")
    if actual_endpoints != expected_endpoints:
        reasons.append("delivery endpoints differ from private label")
    if sorted(receipt.get("delivery_method_keys", [])) != sorted(actual_keys):
        reasons.append("receipt delivery method keys differ from native methods")
    for item in actual_methods:
        if not isinstance(item, dict) or card_destinations.get(item.get("key")) != item.get("destination"):
            reasons.append("native delivery destination is not the card-authorized destination")
            break

    actual_refs = _actual_evidence_refs(native, card)
    required_refs = set(label.get("required_evidence_refs") or [])
    if not required_refs.issubset(actual_refs):
        reasons.append("required private-label evidence refs are missing")
    if not native.get("evidence"):
        reasons.append("native evidence is empty")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "expected_outcome": expected_outcome,
        "actual_outcome": actual_outcome,
        "expected_recipients": sorted(label.get("recipients") or []),
        "actual_recipients": sorted(actual_keys),
        "expected_recipient_destinations": sorted(expected_endpoints),
        "actual_recipient_destinations": sorted(actual_endpoints),
        "required_evidence_refs": sorted(required_refs),
        "actual_evidence_refs": sorted(actual_refs),
        "report_status": report.get("status"),
    }


def _trace_events(path: Path) -> tuple[list[dict[str, Any]], list[int]]:
    events: list[dict[str, Any]] = []
    malformed: list[int] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        compressed = Path(f"{path}.gz")
        if not compressed.exists():
            return events, malformed
        with gzip.open(compressed, "rt", encoding="utf-8") as stream:
            lines = stream.read().splitlines()
    for line_number, line in enumerate(lines, 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            malformed.append(line_number)
            continue
        if isinstance(item, dict):
            events.append(item)
        else:
            malformed.append(line_number)
    return events, malformed


def _calibration(
    events: list[dict[str, Any]], scenario: dict[str, Any], card: dict[str, Any]
) -> dict[str, Any]:
    owner_examples = scenario.get("owner_examples", [])
    required_label_fields = (
        "expected_outcome", "expected_delivery_destinations", "required_evidence_refs",
        "expected_retrieval_refs",
    )
    missing_labels = [
        item.get("id")
        for item in owner_examples
        if not all(field in item for field in required_label_fields)
    ]
    if missing_labels:
        return {"passed": False, "status": "invalid_labels", "case_count": 0,
                "failures": [f"explicit labels missing: {missing_labels}"]}
    owner_by_id = {item.get("id"): item for item in owner_examples}
    label_failures: list[str] = []
    retrieval_contracts: dict[str, tuple[set[str], set[str]]] = {}
    for item in owner_examples:
        required, allowed, failures = _retrieval_contract(item)
        if failures:
            label_failures.extend(f"{item.get('id')}: {failure}" for failure in failures)
        else:
            retrieval_contracts[item.get("id")] = (required, allowed)
    if label_failures:
        return {"passed": False, "status": "invalid_labels", "case_count": 0,
                "failures": label_failures}
    workflow_results = [
        event.get("result")
        for event in events
        if event.get("kind") == "tool.result"
        and event.get("name") == "evaluate_card_workflow"
        and isinstance(event.get("result"), dict)
    ]
    if not workflow_results:
        return {"passed": False, "status": "missing", "case_count": 0, "failures": ["no traced calibration result"]}
    result = workflow_results[-1]
    failures: list[str] = []
    case_scores: list[dict[str, Any]] = []
    if result.get("status") != "approved":
        failures.append("calibration status is not approved")
    if result.get("acceptance_passed") is not True:
        failures.append("calibration acceptance_passed is not true")
    actual_ids = {case.get("case_id") for case in result.get("cases", []) if isinstance(case, dict)}
    expected_ids = set(owner_by_id)
    if actual_ids != expected_ids:
        failures.append("calibration case set differs from frozen owner examples")
    for case in result.get("cases", []):
        if not isinstance(case, dict):
            failures.append("malformed calibration case")
            continue
        expected = owner_by_id.get(case.get("case_id"))
        if expected is None:
            continue
        expected_destinations = _expected_destinations(expected.get("expected_delivery_destinations"))
        actual_destinations = set((case.get("actual_delivery_destinations") or {}).values())
        actual_refs = set(case.get("actual_retrieval_refs") or [])
        required_refs, allowed_refs = retrieval_contracts[case.get("case_id")]
        if case.get("outcome") != expected.get("expected_outcome"):
            failures.append(f"{case.get('case_id')}: outcome")
        if actual_destinations != expected_destinations:
            failures.append(f"{case.get('case_id')}: destinations")
        allowed_count = len(actual_refs & allowed_refs)
        retrieval_precision = allowed_count / len(actual_refs) if actual_refs else (1.0 if not required_refs else 0.0)
        retrieval_recall = (
            len(actual_refs & required_refs) / len(required_refs)
            if required_refs else 1.0
        )
        if not required_refs.issubset(actual_refs):
            failures.append(f"{case.get('case_id')}: missing required retrieval refs")
        if not actual_refs.issubset(allowed_refs):
            failures.append(f"{case.get('case_id')}: forbidden retrieval refs")
        case_scores.append({
            "case_id": case.get("case_id"),
            "required_retrieval_refs": sorted(required_refs),
            "allowed_retrieval_refs": sorted(allowed_refs),
            "actual_retrieval_refs": sorted(actual_refs),
            "retrieval_precision": retrieval_precision,
            "retrieval_recall": retrieval_recall,
        })
        # Evidence keys are card-owned aliases; map them back to canonical refs.
        key_to_ref = {
            item.get("key"): f"{item.get('adapter')}|{item.get('resource')}"
            for item in card.get("sources", [])
        }
        actual_evidence = {key_to_ref[key] for key in case.get("actual_evidence_source_keys", []) if key in key_to_ref}
        if not set(expected.get("required_evidence_refs") or []).issubset(actual_evidence):
            failures.append(f"{case.get('case_id')}: evidence refs")
    return {
        "passed": not failures,
        "status": result.get("status"),
        "case_count": len(result.get("cases", [])),
        "failures": failures,
        "cases": case_scores,
        "certification_report_id": result.get("certification_report_id"),
    }


def adjudicate(run_dir: Path) -> dict[str, Any]:
    protocol = _load(run_dir / "protocol.json")
    scenarios = _load(run_dir / "frozen-scenarios.json")
    events, malformed_trace_lines = _trace_events(run_dir / "trace.jsonl")
    checks: dict[str, dict[str, Any]] = {}
    if malformed_trace_lines:
        _fail(checks, "trace_integrity", {"malformed_lines": malformed_trace_lines})
    else:
        _pass(checks, "trace_integrity")
    if not protocol.get("binary_sha256") or not protocol.get("harness_sha256"):
        _fail(checks, "recorded_hashes", "binary_sha256 and harness_sha256 are required")
    else:
        _pass(checks, "recorded_hashes")
    recorded_dataset_digest = protocol.get("dataset_sha256")
    if recorded_dataset_digest is not None:
        actual_dataset_digest = _digest(scenarios)
        if actual_dataset_digest != recorded_dataset_digest:
            _fail(checks, "dataset_integrity", {
                "recorded": recorded_dataset_digest,
                "actual": actual_dataset_digest,
            })
        else:
            _pass(checks, "dataset_integrity")

    jev_requests = [e for e in events if e.get("kind") == "api.request" and e.get("provider") == "jev"]
    jev_rejected = [e for e in events if e.get("kind") == "api.rejected" and e.get("provider") == "jev"]
    raw_budget = {
        "paid_attempts": len(jev_requests),
        "rejected_attempts": len(jev_rejected),
        "limit": protocol.get("jev_attempt_limit"),
    }
    if not isinstance(raw_budget["limit"], int) or raw_budget["paid_attempts"] > raw_budget["limit"]:
        _fail(checks, "raw_jev_budget", raw_budget)
    else:
        _pass(checks, "raw_jev_budget", raw_budget)

    companies: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_id = scenario.get("scenario_id")
        onboarding_path = _existing_artifact(run_dir / f"{scenario_id}-onboarding.json")
        company_result_path = _existing_artifact(run_dir / f"{scenario_id}-result.json")
        company_result = _load(company_result_path) if company_result_path else {}
        onboarding = _load(onboarding_path) if onboarding_path else {
            key: company_result.get(key)
            for key in ("card", "owner_reviews", "notes", "card_fingerprint", "compiled_plan_fingerprint")
            if key in company_result
        }
        card = onboarding.get("card") if isinstance(onboarding, dict) else None
        company_checks: dict[str, dict[str, Any]] = {}
        if not isinstance(card, dict):
            _fail(company_checks, "card_recorded", "onboarding card missing")
            card = {}
        else:
            _pass(company_checks, "card_recorded")
        trace_for_company = [event for event in events if event.get("episode", "").startswith(f"{scenario_id}/")]
        reviews = onboarding.get("owner_reviews") if isinstance(onboarding, dict) else []
        final_review = reviews[-1] if isinstance(reviews, list) and reviews and isinstance(reviews[-1], dict) else {}
        final_fingerprint = final_review.get("approval_fingerprint")
        matching_bindings = [
            event for event in trace_for_company
            if event.get("kind") == "review.binding"
            and event.get("approval_fingerprint") == final_fingerprint
            and event.get("approved") is True
            and event.get("binding_status") == "matched"
        ]
        owner_approved = bool(final_fingerprint) and final_review.get("approved") is True \
            and final_review.get("binding_status") == "matched" \
            and final_review.get("synthetic") is True \
            and final_review.get("real_human_approval") is False \
            and bool(matching_bindings)
        if owner_approved:
            _pass(company_checks, "owner_review_approved", {"prior_reviews": max(0, len(reviews) - 1)})
        else:
            _fail(company_checks, "owner_review_approved", "final card/notes approval fingerprint is not matched and approved")

        calibration = _calibration(trace_for_company, scenario, card)
        if calibration["passed"]:
            _pass(company_checks, "calibration_independent", calibration)
        else:
            _fail(company_checks, "calibration_independent", calibration)

        periods = scenario.get("private", {}).get("periods", {})
        expected_period_ids = set(periods)
        period_records: dict[str, dict[str, Any]] = {}
        for period_id in expected_period_ids:
            path = _existing_artifact(run_dir / f"{scenario_id}-{period_id}.json")
            if path:
                period_records[period_id] = _load(path)
        for row in company_result.get("periods", []) if isinstance(company_result, dict) else []:
            if isinstance(row, dict) and row.get("period_id") in expected_period_ids and row.get("result"):
                period_records.setdefault(row["period_id"], row)
        if set(period_records) != expected_period_ids:
            _fail(company_checks, "future_period_set", {"missing": sorted(expected_period_ids - set(period_records)), "extra": sorted(set(period_records) - expected_period_ids)})
        else:
            _pass(company_checks, "future_period_set", {"count": len(expected_period_ids)})

        onboarding_strings = {s for event in trace_for_company if event.get("episode", "").endswith("/onboarding") for s in _walk_strings(event)}
        leaked = sorted(expected_period_ids & onboarding_strings)
        if leaked:
            _fail(company_checks, "future_intent_not_leaked_onboarding", leaked)
        else:
            _pass(company_checks, "future_intent_not_leaked_onboarding")

        rows = []
        for period_id, label in periods.items():
            period = period_records.get(period_id)
            if period is None:
                continue
            rows.append({"period_id": period_id, **_adjudicate_native(
                period, label, card, scenario.get("public", {}).get("destinations", [])
            )})
        failed_rows = [row for row in rows if not row["passed"]]
        if failed_rows or len(rows) != len(expected_period_ids):
            _fail(company_checks, "native_periods_independent", {"completed": len(rows), "expected": len(expected_period_ids), "failed": failed_rows})
        else:
            _pass(company_checks, "native_periods_independent", {"count": len(rows)})

        raw_plans = []
        missing_plans = []
        for period_id in expected_period_ids:
            payload = period_records.get(period_id, {})
            plan = payload.get("result", {}).get("plan")
            if plan is None:
                missing_plans.append(period_id)
            else:
                raw_plans.append(plan)
        approved_plan = card.get("compiled_plan")
        if approved_plan is None or missing_plans:
            _fail(company_checks, "compiled_plan_stability", {
                "status": "unassessed",
                "reason": "raw monitoring output is missing compiled_plan",
                "missing_periods": sorted(missing_plans),
                "observations": len(raw_plans),
            })
        elif any(_digest(plan) != _digest(approved_plan) for plan in raw_plans):
            _fail(company_checks, "compiled_plan_stability", "raw monitoring compiled_plan differs from saved approved card")
        else:
            _pass(company_checks, "compiled_plan_stability", {"observations": len(raw_plans), "source": "native_period_outputs"})

        report_statuses = Counter()
        for row in rows:
            payload = period_records.get(row["period_id"], {})
            report_statuses[payload.get("result", {}).get("report", {}).get("status")] += 1
        companies.append({
            "scenario_id": scenario_id,
            "checks": company_checks,
            "calibration": calibration,
            "periods": rows,
            "qualitative_scope": {
                "report_statuses": dict(report_statuses),
                "note": "Native adjudication does not certify report prose, causal claims, numeric-claim quality, usability, or customer outcomes.",
            },
            "passed": _all_passed(company_checks),
        })

    passed = _all_passed(checks) and bool(companies) and all(company["passed"] for company in companies)
    return {
        "adjudicator": "installed_workflow_review-v1",
        "run_dir_name": run_dir.name,
        "original_report_preserved": True,
        "offline_only": True,
        "checks": checks,
        "companies": companies,
        "summary": {
            "passed": passed,
            "companies": len(companies),
            "periods": sum(len(company["periods"]) for company in companies),
            "raw_jev_paid_attempts": len(jev_requests),
            "raw_jev_rejected_attempts": len(jev_rejected),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline adjudication of an installed workflow trial")
    parser.add_argument("runfolder", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = adjudicate(args.runfolder)
    descriptor = args.output.open("x", encoding="utf-8")
    with descriptor:
        json.dump(result, descriptor, indent=2, ensure_ascii=False, allow_nan=False)
        descriptor.write("\n")
    return 0 if result["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

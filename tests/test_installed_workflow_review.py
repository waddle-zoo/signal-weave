from __future__ import annotations

import gzip
import json
from pathlib import Path

from evaluations.installed_workflow_review import _digest, adjudicate


def test_compressed_evidence_recomputes_identically(tmp_path):
    run = _fixture(tmp_path)
    expected = adjudicate(run)
    for path in list(run.iterdir()):
        if path.suffix in {".json", ".jsonl"}:
            path.with_suffix(path.suffix + ".gz").write_bytes(gzip.compress(path.read_bytes(), mtime=0))
            path.unlink()
    assert adjudicate(run) == expected


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _refresh_dataset_digest(run: Path) -> None:
    protocol = json.loads((run / "protocol.json").read_text(encoding="utf-8"))
    scenarios = json.loads((run / "frozen-scenarios.json").read_text(encoding="utf-8"))
    protocol["dataset_sha256"] = _digest(scenarios)
    _write(run / "protocol.json", protocol)


def _fixture(tmp_path: Path, *, bad_native: bool = False, no_plan_trace: bool = False,
             period_id: str = "future-1") -> Path:
    run = tmp_path / "run"
    run.mkdir(parents=True)
    scenario_id = "company"
    source_ref = "company_mcp|resource-1"
    card_id = "card-1"
    card = {
        "id": card_id,
        "version": 1,
        "status": "approved",
        "compiled_plan": {"selected_source_keys": ["sales"]},
        "sources": [{"key": "sales", "adapter": "company_mcp", "resource": "resource-1"}],
        "delivery_methods": [{"key": "leadership", "destination": "slack://leadership"}],
    }
    scenario = {
        "scenario_id": scenario_id,
        "public": {
            "periods": [{"period_id": period_id}],
            "destinations": [{"key": "leadership", "destination": "slack://leadership"}],
        },
        "private": {"periods": {period_id: {"outcome": "notify", "recipients": ["leadership"], "required_evidence_refs": [source_ref]}}},
        "owner_examples": [{
            "id": "week-01-case",
            "expected_outcome": "notify",
            "expected_delivery_destinations": ["slack://leadership"],
            "required_evidence_refs": [source_ref],
            "expected_retrieval_refs": [source_ref],
        }],
    }
    protocol = {"binary_sha256": "bin", "harness_sha256": {"runner": "hash"}, "jev_attempt_limit": 2}
    onboarding = {
        "card": card,
        "owner_reviews": [{"approved": True, "binding_status": "matched", "synthetic": True, "real_human_approval": False, "approval_fingerprint": "fp"}],
    }
    calibration = {
        "status": "approved",
        "acceptance_passed": True,
        "certification_report_id": "cert-1",
        "cases": [{
            "case_id": "week-01-case",
            "outcome": "notify",
            "actual_delivery_destinations": {"leadership": "slack://leadership"},
            "actual_delivery_method_keys": ["leadership"],
            "actual_evidence_source_keys": ["sales"],
            "actual_retrieval_refs": [source_ref],
        }],
    }
    period_outcome = "ignore" if bad_native else "notify"
    period = {
        "result": {
            "receipt": {"card_id": card_id, "card_version": 1, "status": "delivery_disabled", "delivery_enabled": False, "delivery_mode": "shadow", "outcome": period_outcome, "delivery_method_keys": [] if bad_native else ["leadership"]},
            "card": {"id": card_id, "version": 1, "compiled_plan": card["compiled_plan"]},
            "plan": card["compiled_plan"],
            "result": {"card_id": card_id, "outcome": period_outcome, "delivery_methods": [] if bad_native else [{"key": "leadership", "destination": "slack://leadership"}], "evidence": [{"source_key": "sales"}], "observations": []},
            "report": {"card_id": card_id, "outcome": period_outcome, "status": "partial"},
        }
    }
    period["result"]["result"]["report"] = period["result"]["report"]
    trace = [
        {"episode": "company/onboarding", "kind": "tool.result", "name": "evaluate_card_workflow", "result": calibration},
        {"episode": "company/onboarding", "kind": "tool.result", "name": "get_insight_card", "result": {"compiled_plan": card["compiled_plan"]}},
        {"episode": f"company/{period_id}", "kind": "tool.result", "name": "get_insight_card", "result": {"compiled_plan": card["compiled_plan"]}},
        {"kind": "api.request", "provider": "jev"},
        {"episode": "company/onboarding", "kind": "review.binding", "approval_fingerprint": "fp", "approved": True, "binding_status": "matched"},
    ]
    if no_plan_trace:
        trace = [event for event in trace if event.get("name") != "get_insight_card"]
        period["result"].pop("plan")
    _write(run / "protocol.json", protocol)
    _write(run / "frozen-scenarios.json", [scenario])
    _refresh_dataset_digest(run)
    _write(run / f"{scenario_id}-onboarding.json", onboarding)
    _write(run / f"{scenario_id}-{period_id}.json", period)
    (run / "trace.jsonl").write_text("\n".join(json.dumps(item) for item in trace) + "\n", encoding="utf-8")
    return run


def test_independent_adjudication_passes_and_ignores_cached_flags(tmp_path):
    result = adjudicate(_fixture(tmp_path))
    assert result["summary"]["passed"] is True
    assert result["checks"]["dataset_integrity"]["passed"] is True
    assert result["companies"][0]["periods"][0]["passed"] is True


def test_private_label_mismatch_fails_even_with_native_shape(tmp_path):
    result = adjudicate(_fixture(tmp_path, bad_native=True))
    assert result["summary"]["passed"] is False
    assert result["companies"][0]["periods"][0]["passed"] is False


def test_missing_compiled_plan_trace_is_unassessed_and_not_passed(tmp_path):
    result = adjudicate(_fixture(tmp_path, no_plan_trace=True))
    company = result["companies"][0]
    assert company["checks"]["compiled_plan_stability"]["passed"] is False
    assert company["checks"]["compiled_plan_stability"]["detail"]["status"] == "unassessed"
    assert result["summary"]["passed"] is False


def test_cli_output_is_exclusive_and_secret_free(tmp_path):
    run = _fixture(tmp_path)
    result = adjudicate(run)
    output = tmp_path / "adjudication.json"
    output.write_text(json.dumps(result), encoding="utf-8")
    assert "api_key" not in output.read_text(encoding="utf-8").lower()
    assert "raw_response" not in output.read_text(encoding="utf-8").lower()


def test_card_report_identity_and_delivery_contract_are_independent_checks(tmp_path):
    run = _fixture(tmp_path)
    period_path = run / "company-future-1.json"
    period = json.loads(period_path.read_text(encoding="utf-8"))
    period["result"]["report"]["card_id"] = "wrong-card"
    period["result"]["receipt"]["delivery_enabled"] = True
    period_path.write_text(json.dumps(period), encoding="utf-8")
    result = adjudicate(run)
    reasons = result["companies"][0]["periods"][0]["reasons"]
    assert "card identity is inconsistent" in reasons
    assert "receipt delivery_enabled is not false" in reasons


def test_calibration_is_recomputed_from_case_payload_not_cached_pass_flag(tmp_path):
    run = _fixture(tmp_path)
    trace_path = run / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        if event.get("name") == "evaluate_card_workflow":
            event["result"]["acceptance_passed"] = True
            event["result"]["cases"][0]["outcome"] = "ignore"
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    result = adjudicate(run)
    calibration = result["companies"][0]["calibration"]
    assert calibration["passed"] is False
    assert "week-01-case: outcome" in calibration["failures"]


def test_raw_budget_count_is_from_proxy_events(tmp_path):
    run = _fixture(tmp_path)
    trace_path = run / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    events.extend({"kind": "api.request", "provider": "jev"} for _ in range(2))
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    result = adjudicate(run)
    assert result["summary"]["raw_jev_paid_attempts"] == 3
    assert result["checks"]["raw_jev_budget"]["passed"] is False


def test_recipient_labels_resolve_public_keys_but_native_alias_must_use_card_endpoint(tmp_path):
    run = _fixture(tmp_path)
    onboarding_path = run / "company-onboarding.json"
    onboarding = json.loads(onboarding_path.read_text(encoding="utf-8"))
    onboarding["card"]["delivery_methods"][0]["key"] = "leadership_alias"
    onboarding_path.write_text(json.dumps(onboarding), encoding="utf-8")
    period_path = run / "company-future-1.json"
    period = json.loads(period_path.read_text(encoding="utf-8"))
    period["result"]["result"]["delivery_methods"][0]["key"] = "leadership_alias"
    period["result"]["receipt"]["delivery_method_keys"] = ["leadership_alias"]
    period_path.write_text(json.dumps(period), encoding="utf-8")
    result = adjudicate(run)
    assert result["companies"][0]["periods"][0]["passed"] is True


def test_calibration_requires_exact_retrieval_and_explicit_labels(tmp_path):
    run = _fixture(tmp_path)
    trace_path = run / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        if event.get("name") == "evaluate_card_workflow":
            event["result"]["cases"][0]["actual_retrieval_refs"].append("company_mcp|extra")
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    result = adjudicate(run)
    assert result["companies"][0]["calibration"]["passed"] is False
    assert "week-01-case: forbidden retrieval refs" in result["companies"][0]["calibration"]["failures"]

    run = _fixture(tmp_path / "missing", no_plan_trace=True)
    frozen_path = run / "frozen-scenarios.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    del frozen[0]["owner_examples"][0]["expected_retrieval_refs"]
    frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
    result = adjudicate(run)
    assert result["companies"][0]["calibration"]["status"] == "invalid_labels"


def test_allowed_retrieval_refs_permit_optional_source_present_or_absent(tmp_path):
    run = _fixture(tmp_path)
    frozen_path = run / "frozen-scenarios.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    label = frozen[0]["owner_examples"][0]
    required = label["expected_retrieval_refs"][0]
    optional = "company_mcp|optional-context"
    label["allowed_retrieval_refs"] = [required, optional]
    _write(frozen_path, frozen)
    _refresh_dataset_digest(run)

    result = adjudicate(run)
    calibration = result["companies"][0]["calibration"]
    assert calibration["passed"] is True
    assert calibration["cases"][0]["retrieval_precision"] == 1.0
    assert calibration["cases"][0]["retrieval_recall"] == 1.0

    trace_path = run / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        if event.get("name") == "evaluate_card_workflow":
            event["result"]["cases"][0]["actual_retrieval_refs"].append(optional)
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    result = adjudicate(run)
    calibration = result["companies"][0]["calibration"]
    assert calibration["passed"] is True
    assert calibration["cases"][0]["retrieval_precision"] == 1.0
    assert calibration["cases"][0]["retrieval_recall"] == 1.0


def test_allowed_retrieval_refs_reject_missing_required_and_duplicate_labels(tmp_path):
    run = _fixture(tmp_path)
    frozen_path = run / "frozen-scenarios.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    label = frozen[0]["owner_examples"][0]
    label["allowed_retrieval_refs"] = ["company_mcp|optional-context"]
    _write(frozen_path, frozen)
    _refresh_dataset_digest(run)
    result = adjudicate(run)
    assert result["companies"][0]["calibration"]["status"] == "invalid_labels"
    assert "omits required expected refs" in result["companies"][0]["calibration"]["failures"][0]

    label["allowed_retrieval_refs"] = [label["expected_retrieval_refs"][0]] * 2
    _write(frozen_path, frozen)
    _refresh_dataset_digest(run)
    result = adjudicate(run)
    assert result["companies"][0]["calibration"]["status"] == "invalid_labels"
    assert "contains duplicates" in result["companies"][0]["calibration"]["failures"][0]


def test_duplicate_expected_retrieval_labels_are_rejected(tmp_path):
    run = _fixture(tmp_path)
    frozen_path = run / "frozen-scenarios.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    label = frozen[0]["owner_examples"][0]
    required = label["expected_retrieval_refs"][0]
    label["expected_retrieval_refs"] = [required, required]
    _write(frozen_path, frozen)
    _refresh_dataset_digest(run)

    result = adjudicate(run)
    calibration = result["companies"][0]["calibration"]
    assert calibration["status"] == "invalid_labels"
    assert "expected_retrieval_refs contains duplicates" in calibration["failures"][0]


def test_optional_only_allowed_refs_with_empty_actual_retrieval_are_precise(tmp_path):
    run = _fixture(tmp_path)
    frozen_path = run / "frozen-scenarios.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    label = frozen[0]["owner_examples"][0]
    label["expected_retrieval_refs"] = []
    label["allowed_retrieval_refs"] = ["company_mcp|optional-context"]
    _write(frozen_path, frozen)
    _refresh_dataset_digest(run)

    trace_path = run / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        if event.get("name") == "evaluate_card_workflow":
            event["result"]["cases"][0]["actual_retrieval_refs"] = []
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    result = adjudicate(run)
    calibration = result["companies"][0]["calibration"]
    assert calibration["passed"] is True
    assert calibration["cases"][0]["retrieval_precision"] == 1.0
    assert calibration["cases"][0]["retrieval_recall"] == 1.0


def test_actual_missing_required_retrieval_ref_fails_valid_label(tmp_path):
    run = _fixture(tmp_path)
    frozen_path = run / "frozen-scenarios.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    label = frozen[0]["owner_examples"][0]
    required = label["expected_retrieval_refs"][0]
    label["allowed_retrieval_refs"] = [required, "company_mcp|optional-context"]
    _write(frozen_path, frozen)
    _refresh_dataset_digest(run)

    trace_path = run / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        if event.get("name") == "evaluate_card_workflow":
            event["result"]["cases"][0]["actual_retrieval_refs"] = ["company_mcp|optional-context"]
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    result = adjudicate(run)
    calibration = result["companies"][0]["calibration"]
    assert calibration["passed"] is False
    assert "week-01-case: missing required retrieval refs" in calibration["failures"]
    assert calibration["cases"][0]["retrieval_precision"] == 1.0
    assert calibration["cases"][0]["retrieval_recall"] == 0.0


def test_forbidden_retrieval_ref_fails_even_when_optional_refs_are_allowed(tmp_path):
    run = _fixture(tmp_path)
    frozen_path = run / "frozen-scenarios.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    required = frozen[0]["owner_examples"][0]["expected_retrieval_refs"][0]
    frozen[0]["owner_examples"][0]["allowed_retrieval_refs"] = [required, "company_mcp|optional-context"]
    _write(frozen_path, frozen)
    _refresh_dataset_digest(run)
    trace_path = run / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        if event.get("name") == "evaluate_card_workflow":
            event["result"]["cases"][0]["actual_retrieval_refs"].append("company_mcp|forbidden")
    trace_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    result = adjudicate(run)
    calibration = result["companies"][0]["calibration"]
    assert calibration["passed"] is False
    assert "week-01-case: forbidden retrieval refs" in calibration["failures"]
    assert calibration["cases"][0]["retrieval_precision"] == 0.5
    assert calibration["cases"][0]["retrieval_recall"] == 1.0


def test_frozen_label_tampering_fails_dataset_integrity(tmp_path):
    run = _fixture(tmp_path)
    frozen_path = run / "frozen-scenarios.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    frozen[0]["owner_examples"][0]["allowed_retrieval_refs"] = [
        frozen[0]["owner_examples"][0]["expected_retrieval_refs"][0],
        "company_mcp|tampered",
    ]
    _write(frozen_path, frozen)
    result = adjudicate(run)
    assert result["checks"]["dataset_integrity"]["passed"] is False
    assert result["summary"]["passed"] is False


def test_shadow_receipt_and_malformed_trace_fail_closed(tmp_path):
    run = _fixture(tmp_path)
    period_path = run / "company-future-1.json"
    period = json.loads(period_path.read_text(encoding="utf-8"))
    period["result"]["receipt"]["status"] = "delivered"
    period_path.write_text(json.dumps(period), encoding="utf-8")
    (run / "trace.jsonl").write_text((run / "trace.jsonl").read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")
    result = adjudicate(run)
    assert result["checks"]["trace_integrity"]["passed"] is False
    assert result["companies"][0]["periods"][0]["passed"] is False


def test_opaque_period_ids_are_resolved_exactly(tmp_path):
    result = adjudicate(_fixture(tmp_path, period_id="period-807f72037c82b250d232"))
    assert result["summary"]["passed"] is True
    assert result["companies"][0]["checks"]["future_period_set"]["passed"] is True


def test_prior_owner_rejection_does_not_override_final_bound_approval(tmp_path):
    run = _fixture(tmp_path)
    path = run / "company-onboarding.json"
    onboarding = json.loads(path.read_text(encoding="utf-8"))
    approved = onboarding["owner_reviews"][0]
    onboarding["owner_reviews"] = [
        {"approved": False, "binding_status": "matched", "synthetic": True,
         "real_human_approval": False, "approval_fingerprint": "old-fp"},
        approved,
    ]
    path.write_text(json.dumps(onboarding), encoding="utf-8")
    result = adjudicate(run)
    check = result["companies"][0]["checks"]["owner_review_approved"]
    assert check["passed"] is True
    assert check["detail"]["prior_reviews"] == 1

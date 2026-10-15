"""Audit retained live results; these assertions do not make new model calls."""

import gzip
import hashlib
import json
from pathlib import Path

from signalweave.models import InsightCard


def test_retained_repair_has_three_frozen_cards_and_twelve_exact_native_results():
    root = Path(__file__).resolve().parents[1] / "docs/evidence/bootstrap-empirical-repair-v2-01"
    manifest = json.loads((root / "manifest.json").read_text())
    report = json.loads((root / "report.json").read_text())
    events = [json.loads(line) for line in gzip.decompress(
        (root / "events.jsonl.gz").read_bytes(),
    ).decode().splitlines()]
    assert report["status"] == "complete" and report["freeze_verified"]
    assert report["fixture_digest_before"] == report["fixture_digest_after"]
    assert manifest["authoring_regression"] and manifest["max_jev_attempts"] == 40
    assert report["recomputed_score"]["status"] == "not_run"
    assert len(manifest["companies"]) == 3
    checked = 0
    for company in manifest["companies"]:
        author = report["bootstrap_quality"][company["id"]]
        assert author["status"] == "accepted"
        assert author["episode"]["status"] == "complete"
        assert author["episode"]["exit_code"] == 0 and not author["episode"]["foreign_tools"]
        card = InsightCard.model_validate(author["accepted_card"])
        acceptance = author["acceptance_report"]
        assert acceptance["acceptance_passed"]
        # Audit the historical schema, not a newly approved current-schema card.
        # Adding numeric_conditions intentionally changes today's acceptance
        # digest. Do not rewrite the frozen evidence or preserve old approval.
        payload = card.execution_payload()
        assert "numeric_conditions" not in author["accepted_card"]
        assert payload.pop("numeric_conditions") == []
        historical = {
            "execution_payload": payload,
            "delivery_methods": [method.model_dump(mode="json") for method in card.delivery_methods],
            "principal_id": card.principal_id, "principal_tenant": card.principal_tenant,
            "compiled_plan": card.compiled_plan.model_dump(mode="json") if card.compiled_plan else None,
        }
        digest = hashlib.sha256(json.dumps(historical, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        assert acceptance["card_execution_digests"][card.id] == digest
        arm = report["execution_comparison"][company["id"]]
        assert arm["expert_native_jev"] is None and arm["raw_luna"] == []
        assert not arm["paired_with_authored_card"]
        cases = {case["case_id"]: case for case in arm["treatment_native_jev"]["cases"]}
        assert len(cases) == len(company["holdout_cases"]) == 4
        for expected in company["holdout_cases"]:
            actual = cases[expected["id"]]
            assert actual["outcome"] == expected["expected_outcome"]
            assert set(actual["actual_delivery_method_keys"]) == set(expected["expected_delivery_method_keys"])
            assert actual["actual_delivery_destinations"] == expected["expected_delivery_destinations"]
            assert set(expected["required_evidence_source_keys"]) <= set(actual["actual_evidence_source_keys"])
            assert not actual["failure_reasons"] and actual["error"] is None
            checked += 1
    requests = [event for event in events if event["kind"] == "api.request"]
    assert sum(event["provider"] == "jev" for event in requests) == report["jev_attempts"] == 28
    assert sum(event["provider"] == "openai" for event in requests) == 3
    assert checked == 12
    # Keep the rejected draft/test visible rather than counting only successes.
    tests = [event for event in events if event["kind"] == "tool.result" and event["name"] == "test_card"]
    assert len(tests) == 4 and sum(event["result"]["accepted"] for event in tests) == 3
    assert any(event["kind"] == "tool.result" and event["name"] == "propose_card"
               and "invalid_candidate_schema" in event["result"].get("message", "") for event in events)

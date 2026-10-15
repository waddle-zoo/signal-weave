import gzip
import hashlib
import json
from pathlib import Path

from evaluations import evidence_contract_gate_trial as trial


def retained_trace(tmp_path):
    source = (
        Path(__file__).resolve().parents[1]
        / "docs/evidence/installed-workflow-2026-10-03/installed-workflow-transfer-live-11/trace.jsonl.gz"
    )
    path = tmp_path / "trace.jsonl"
    path.write_bytes(gzip.decompress(source.read_bytes()))
    return path


def test_typed_trial_binds_every_required_comparison_to_an_adapter_contract(tmp_path):
    matrix = trial.build(retained_trace(tmp_path))

    assert len(matrix["cases"]) == 6
    required = {
        "query-p95-latency-previous-period",
        "replication-lag-previous-period",
    }
    for case in matrix["cases"]:
        source = next(
            item
            for item in case["resources"]
            if item["source_key"] == "source-company-mcp-resource-83e1aa966aadc508241c"
        )
        assert set(source["contract"]["required_comparison_keys"]) == required
        contracts = {item["key"]: item for item in source["contract"]["comparison_contracts"]}
        assert set(contracts) == required
        if case["expected_outcome"] == "insufficient_data":
            assert any(
                item["coverage"] != "complete" or not item["comparable"]
                for item in contracts.values()
            )
        else:
            assert all(
                item["coverage"] == "complete" and item["comparable"] for item in contracts.values()
            )


def test_report_assembly_requires_all_retained_calls_and_does_not_crash():
    results = [
        {
            "case_id": "case-1",
            "score": {"exact": True, "error": None},
        }
        for _ in range(trial.ATTEMPT_CAP)
    ]
    responses = [{"response": {"model": "jev-1.13.0"}} for _ in range(trial.ATTEMPT_CAP)]

    report = trial._assemble_report(
        results,
        attempts=trial.ATTEMPT_CAP,
        responses=responses,
        budget_censored=False,
    )

    assert report["primary_gate"] is True
    assert report["summary"] == {"case-1": {"exact": 12, "attempts": 12, "errors": 0}}


def test_live_requests_do_not_contain_evaluator_labels():
    root = Path(__file__).resolve().parents[1] / "docs/evidence/evidence-contract-gate-2026-10-04"
    labels = (
        "expected_outcome",
        "expected_delivery_method_keys",
        "case_index",
        "repeat",
        "primary_gate",
    )
    trace = gzip.decompress((root / "trace.jsonl.gz").read_bytes()).decode()
    events = [json.loads(line) for line in trace.splitlines()]
    requests = [event for event in events if event["kind"] == "api.request"]
    assert len(requests) == trial.ATTEMPT_CAP
    assert not any(
        label in json.dumps(event["questions"]) for event in requests for label in labels
    )


def test_archived_live_evidence_is_hash_complete_and_gate_passes():
    root = Path(__file__).resolve().parents[1] / "docs/evidence/evidence-contract-gate-2026-10-04"
    manifest = json.loads((root / "manifest.json").read_text())
    decoded = {}
    for name, record in manifest["artifacts"].items():
        archive = (root / name).read_bytes()
        assert hashlib.sha256(archive).hexdigest() == record["archive_sha256"]
        raw = gzip.decompress(archive) if name.endswith(".gz") else archive
        assert hashlib.sha256(raw).hexdigest() == record["source_sha256"]
        decoded[name.removesuffix(".gz")] = raw

    protocol = json.loads(decoded["protocol.json"])
    inputs = json.loads(decoded["inputs.json"])
    report = json.loads(decoded["report.json"])
    events = [json.loads(line) for line in decoded["trace.jsonl"].splitlines()]
    assert trial.digest(inputs) == protocol["input_digest"]
    assert len(report["results"]) == protocol["attempt_cap"] == 12
    assert report["primary_gate"] is True
    assert report["report_rebuilt_after_runner_exception"] is True
    assert len([event for event in events if event["kind"] == "api.request"]) == 12
    assert len([event for event in events if event["kind"] == "api.response"]) == 12
    assert manifest["real_deliveries"] == 0

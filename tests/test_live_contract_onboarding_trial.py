import gzip
import hashlib
import json
from pathlib import Path

from evaluations import live_contract_onboarding_trial as trial


def test_probe_request_cap_matches_current_local_onboarding_stages():
    inputs = trial.public_inputs([trial.CASES[0]], ["complete", "partial"])
    assert trial.REQUESTS_PER_CARD == 4
    assert len(inputs["cases"]) == 1
    assert inputs["quality_arms"] == ["complete", "partial"]


def test_archived_live_onboarding_runs_are_hash_complete_and_delivery_disabled():
    root = Path(__file__).resolve().parents[1] / "docs/evidence/live-contract-onboarding-2026-10-04"
    manifest = json.loads((root / "manifest.json").read_text())
    for run, metadata in manifest["runs"].items():
        folder = root / run
        for name, record in metadata["artifacts"].items():
            archive = (folder / name).read_bytes()
            raw = gzip.decompress(archive) if name.endswith(".gz") else archive
            assert hashlib.sha256(archive).hexdigest() == record["archive_sha256"]
            assert hashlib.sha256(raw).hexdigest() == record["source_sha256"]

        if run == "failed-budget-probe":
            assert "report.json" not in metadata["artifacts"]
            continue
        report = json.loads((folder / "report.json").read_text())
        assert report["exact"] == report["total"]
        assert report["budget_censored"] is False
        assert report["resolved_models"] == ["jev-1.13.0"]
        assert all(item["delivery_disabled"] for item in report["results"])
        trace = gzip.decompress((folder / "trace.jsonl.gz").read_bytes()).decode()
        requests = [
            json.loads(line)
            for line in trace.splitlines()
            if json.loads(line)["kind"] == "api.request"
        ]
        assert not any(
            label in json.dumps(event["questions"])
            for event in requests
            for label in ("expected_outcome", "expected_delivery_method_keys")
        )

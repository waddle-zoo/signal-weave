import copy
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from evaluations import evidence_sufficiency_trial as trial
from signalweave.evaluation import CardEvaluationCase


@pytest.fixture
def retained_trace(tmp_path):
    import gzip
    source = Path(__file__).resolve().parents[1] / "docs/evidence/installed-workflow-2026-10-03/installed-workflow-transfer-live-11/trace.jsonl.gz"
    path = tmp_path / "trace.jsonl"
    path.write_bytes(gzip.decompress(source.read_bytes()))
    return path


def test_frozen_matrix_uses_one_unchanged_card_and_valid_historical_inputs(retained_trace):
    original, _, cases = trial.prepare(retained_trace)
    matrix = trial.build(retained_trace)
    assert matrix["card"] == original
    assert Counter(r["arm"] for r in matrix["rows"]) == {
        "documented": 6, "documented_typed": 6, "original": 3, "original_typed": 3,
    }
    raw = [r["case"] for r in matrix["rows"] if r["arm"] == "original"]
    assert raw == cases
    for row in matrix["rows"]:
        CardEvaluationCase.model_validate({**row["case"], "card": original})


def test_normalization_preserves_raw_values_and_never_imputes_missing_baseline(retained_trace):
    matrix = trial.build(retained_trace)
    documented = [r for r in matrix["rows"] if r["arm"] == "documented"]
    for row in documented:
        case = row["case"]
        before = copy.deepcopy(case)
        typed = trial.normalize(case)
        observations = trial.primary(typed).pop("observations")
        trial.primary(typed)["observations"] = []
        assert typed == before == case
        values = trial.primary(case)["evidence"][0]["values"]
        for obs, suffix in zip(observations, ("p95_ms", "lag_ms"), strict=True):
            assert obs["current"] == values[f"current_{suffix}"]
            assert obs["baseline"] == values[f"baseline_{suffix}"]
            if values[f"baseline_{suffix}"] is None:
                assert obs["change_pct"] is None


def test_documentation_is_invariant_and_has_no_action_labels(retained_trace):
    rows = trial.build(retained_trace)["rows"]
    primary_rows = [r for r in rows if r["arm"] == "documented"]
    contracts = [trial.primary(r["case"])["metadata"]["provider_contract"] for r in primary_rows]
    for contract in contracts:
        assert contract["field_definitions"] == trial.DEFINITIONS
        assert contract["expected_cluster_population"] == trial.EXPECTED_CLUSTERS
        assert not {"expected_outcome", "ignore", "investigate", "insufficient_data"} & set(json.dumps(contract).split())
    contracts[0]["expected_cluster_population"].clear()
    assert len(trial.EXPECTED_CLUSTERS) == 3


def test_negative_controls_remove_decisive_information_from_an_actionable_case(retained_trace):
    rows = trial.build(retained_trace)["rows"]
    controls = [r["case"] for r in rows if r["arm"] == "documented" and r["case"]["id"].startswith("case-")]
    assert len(controls) == 3
    for case in controls:
        values = trial.primary(case)["evidence"][0]["values"]
        assert values["current_p95_ms"] == 140 and values["current_lag_ms"] == 80 and values["affected_regions"] == 3
        assert trial.oracle(case) == "insufficient_data"
        assert case["expected_outcome"] == "insufficient_data"
        repaired = copy.deepcopy(case)
        v = trial.primary(repaired)["evidence"][0]["values"]
        v.update(cluster_population=list(trial.EXPECTED_CLUSTERS), baseline_p95_ms=100)
        v.pop("baseline_cluster_population", None)
        v.pop("current_cluster_population", None)
        assert trial.oracle(repaired) == "investigate"


async def test_freeze_is_offline_and_live_rejects_tampering(retained_trace, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Should not instantiate live Jev")
    monkeypatch.setattr(trial, "MeasuredJev", forbidden)
    plan = tmp_path / "plan"
    protocol = await trial.freeze(retained_trace, plan)
    assert protocol["attempt_cap"] == 36
    assert Counter(x["index"] for x in protocol["schedule"]) == {i: 2 for i in range(18)}
    with pytest.raises(FileExistsError):
        await trial.freeze(retained_trace, plan)
    inputs = json.loads((plan / "inputs.json").read_text())
    inputs["card"]["action_confidence_threshold"] = 0
    (plan / "inputs.json").write_text(json.dumps(inputs))
    with pytest.raises(ValueError, match="Frozen inputs"):
        await trial.execute(plan, tmp_path / "live", tmp_path / "no-key-read")
    assert not (tmp_path / "live").exists()


def test_acceptance_alone_does_not_pass_wrong_workflow_handoff():
    row = {"case": {"expected_outcome": "ignore"}}
    report = {"acceptance_passed": True, "cases": [{"outcome": "ignore", "workflow": {"action": "retrieve_evidence"}}]}
    assert trial.score(row, report)["exact"] is False
    assert trial.score(row, report)["unnecessary_investigation_handoff"] is True


def test_product_consistent_fallback_still_fails_the_owners_intended_handoff():
    row = {"case": {"expected_outcome": "insufficient_data", "expected_delivery_method_keys": ["data"],
                    "expected_delivery_destinations": {"data": "data-team"}}}
    report = {"acceptance_passed": False, "cases": [{"outcome": "investigate",
              "actual_delivery_method_keys": ["business"], "actual_delivery_destinations": {"business": "business-team"},
              "workflow": {"action": "retrieve_evidence", "status": "pending", "delivery_method_keys": ["business"]}}]}
    result = trial.score(row, report)
    assert result["handoff_consistent_with_actual_outcome"] is True
    assert not any(result[k] for k in ("exact", "outcome_exact", "route_exact", "handoff_matches_gold"))
    assert result["misdirected_data_repair"] is True
    assert result["false_sentalert"].startswith("not measured")


@pytest.mark.parametrize("mutation", [{"status": "pending"}, {"delivery_method_keys": ["unexpected"]}])
def test_suppression_needs_complete_status_and_no_recipients(mutation):
    row = {"case": {"expected_outcome": "ignore", "expected_delivery_method_keys": [], "expected_delivery_destinations": {}}}
    report = {"acceptance_passed": True, "cases": [{"outcome": "ignore", "actual_delivery_method_keys": [],
              "actual_delivery_destinations": {}, "workflow": {"action": "suppress", "status": "complete",
                                                                "delivery_method_keys": [], **mutation}}]}
    assert trial.score(row, report)["exact"] is False


def test_retained_live_evidence_matches_raw_responses_and_frozen_denominators():
    """Audit a failed experiment, not a mock model or a new accuracy claim."""
    root = Path(__file__).resolve().parents[1] / "docs/evidence/evidence-sufficiency-2026-10-03"
    manifest = json.loads((root / "manifest.json").read_text())
    decoded = {}
    for name, record in manifest["artifacts"].items():
        blob = (root / name).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == record["archive_sha256"]
        raw = gzip.decompress(blob) if name.endswith(".gz") else blob
        assert hashlib.sha256(raw).hexdigest() == record["source_sha256"]
        decoded[name.removesuffix(".gz")] = raw
    protocol = json.loads(decoded["protocol.json"])
    inputs = json.loads(decoded["inputs.json"])
    report = json.loads(decoded["report.json"])
    assert trial.digest(inputs) == protocol["input_digest"]
    events = [json.loads(line) for line in decoded["trace.jsonl"].splitlines()]
    requests = [e for e in events if e["kind"] == "api.request"]
    responses = [e for e in events if e["kind"] == "api.response"]
    assert len(requests) == len(responses) == len(report["results"]) == protocol["attempt_cap"] == 36
    assert len({e["request_id"] for e in requests}) == 36
    assert {e["request_id"] for e in requests} == {e["request_id"] for e in responses}
    successes = Counter()
    for number, (entry, result) in enumerate(zip(protocol["schedule"], report["results"], strict=True)):
        row = inputs["rows"][entry["index"]]
        assert (result["index"], result["repeat"]) == (entry["index"], entry["repeat"])
        episode = f"attempt-{number:03d}"
        request = next(e for e in requests if e["episode"] == episode)
        response = next(e for e in responses if e["episode"] == episode)
        assert request["request_id"] == response["request_id"]
        # Gold labels are evaluator-only, unlike the common owner policy.
        serialized_request = json.dumps(request)
        for label in ("expected_outcome", "expected_delivery_destinations", "expected_retrieval_refs"):
            assert label not in serialized_request
        case = result["report"]["cases"][0]
        answer = response["response"]["answers"]["outcome"]
        assert case["probabilities"] == answer["probabilities"]
        support = answer["probabilities"][answer["choice"]]
        assert case["confidence"] == support
        expected_routing = "investigate" if support < inputs["card"]["action_confidence_threshold"] else answer["choice"]
        assert case["outcome"] == expected_routing
        assert result["score"] == trial.score(row, result["report"])
        successes[row["arm"]] += result["score"]["exact"]
    assert dict(successes) == {arm: value["exact"] for arm, value in report["summary"].items()}
    assert report["primary_gates"] == {"documented": False, "documented_typed": False}

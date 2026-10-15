"""Offline contract tests for the retained-request policy ablation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import typesafe_sdk

from evaluations import native_policy_ablation as ablation


def _trial_fixture(root: Path) -> tuple[Path, list[str]]:
    trial = root / "pilot"
    trial.mkdir()
    periods = []
    events = []
    period_ids = [f"period-{index:02d}" for index in range(1, 5)]
    choices = ("ignore", "notify", "investigate", "ignore")

    for index, period_id in enumerate(period_ids, start=1):
        request_id = f"request-{index:02d}"
        choice = choices[index - 1]
        model = f"jev-fixture-model-{index}"
        state = {
            "card": {
                "id": f"card-{period_id}",
                "decision_guidance": "Follow the complete approved owner policy.",
                "action_confidence_threshold": 0.7,
                "attributes": {"owner": "analytics", "approved": True},
            },
            "policy": {"ordered_rules": ["quiet", "notify", "fallback"]},
            "observations": [{"metric": "orders", "value": index * 10}],
            "sources": [
                {
                    "key": "orders",
                    "metadata": {"connector_hint": "fixture", "tags": ["retained"]},
                    "descriptor": {"name": "Orders", "kind": "table"},
                    "attributes": {"grain": "day", "currency": "USD"},
                    "contract": {"freshness_hours": 24, "required_fields": ["date", "orders"]},
                    "context": {"definition": "settled orders"},
                    "evidence": [{"ref": "query:orders", "value": index * 10}],
                    "errors": [],
                },
                {"key": "support", "descriptor": {"name": "Support"}, "errors": ["partial"]},
            ],
            "attributes": {"tenant": "synthetic", "run_mode": "retrospective"},
            "contracts": {"outcomes": ["ignore", "notify", "investigate"]},
            "context": {"measurement_window": period_id, "delivery_enabled": False},
            "evidence": [{"ref": "receipt:fixture", "period": period_id}],
            "source_errors": [{"source": "support", "kind": "partial"}],
        }
        questions = {
            "watch_orders": {
                "instructions": "Assess the orders watch item.",
                "criteria": {"present": "present", "absent": "absent", "unknown": "unknown"},
            },
            "outcome": {
                "instructions": "Use the original owner-policy outcome wording.",
                "criteria": {
                    "ignore": "Original quiet criterion.",
                    "notify": "Original notify criterion.",
                    "investigate": "Original investigation criterion.",
                },
                "response_type": "choice",
                "required": True,
            },
            "source_quality": {"instructions": "Assess source quality as recorded."},
        }
        probabilities = {name: (0.85 if name == choice else 0.075)
                         for name in ("ignore", "notify", "investigate")}
        periods.append({
            "period_id": period_id,
            "treatment": {"score": {"expected_outcome": f"private-oracle-label-{period_id}"}},
        })
        events.append({
            "kind": "api.request", "provider": "jev", "request_id": request_id,
            "episode": f"pilot/{period_id}/treatment", "model": model,
            "state": state, "questions": questions,
        })
        events.append({
            "kind": "api.response", "provider": "jev", "request_id": request_id,
            "response": {
                "model": model,
                "answers": {"outcome": {"choice": choice, "probabilities": probabilities}},
            },
        })

    (trial / "report.json").write_text(json.dumps({"status": "completed", "periods": periods}))
    # Reverse response order so load_cases must bind on request_id, not position.
    requests = [event for event in events if event["kind"] == "api.request"]
    responses = [event for event in events if event["kind"] == "api.response"]
    (trial / "trace.jsonl").write_text("\n".join(
        json.dumps(event) for event in [*requests, *reversed(responses)]
    ) + "\n")
    return trial, period_ids


@pytest.fixture
def offline_sdk(monkeypatch):
    control = SimpleNamespace(options=[], calls=[], response_models=[])
    sdk_retry_policy = typesafe_sdk.RetryPolicy

    class StrictClient:
        def __init__(self, *, api_key, timeout, retry, base_url):
            assert api_key == "fixture-only-key"
            assert timeout == 30
            assert isinstance(retry, sdk_retry_policy)
            assert retry.max_retries == 0
            assert base_url == "https://api.typesafe.ai"
            control.options.append({"api_key": api_key, "timeout": timeout,
                                    "retry": retry, "base_url": base_url})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def system_one(self, *, state, questions, model):
            control.calls.append({"state": state, "questions": questions, "model": model})
            index = len(control.calls) - 1
            response_model = (control.response_models[index]
                              if index < len(control.response_models)
                              and control.response_models[index] is not None else model)
            choices = questions["outcome"]["criteria"]
            choice = next(iter(choices))
            probabilities = {name: (0.9 if name == choice else 0.1 / (len(choices) - 1))
                             for name in choices}
            return {
                "model": response_model,
                "answers": {"outcome": {"choice": choice, "probabilities": probabilities}},
            }

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", StrictClient)
    return control


def test_load_cases_binds_four_retained_responses_by_request_id(tmp_path):
    trial, period_ids = _trial_fixture(tmp_path)

    cases = ablation.load_cases(trial)

    assert [case["period_id"] for case in cases] == period_ids
    assert len(cases) == 4
    assert [case["baseline"]["answers"]["outcome"]["choice"] for case in cases] == [
        "ignore", "notify", "investigate", "ignore",
    ]
    assert all(case["baseline"]["model"] == case["model"] for case in cases)
    assert all(case["threshold"] == 0.7 for case in cases)

    trace_path = trial / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    trace_path.write_text("\n".join(
        json.dumps(event) for event in events
        if not (event["kind"] == "api.response" and event["request_id"] == "request-03")
    ) + "\n")
    with pytest.raises(ValueError, match="request/response"):
        ablation.load_cases(trial)


@pytest.mark.parametrize(("arm", "policy_change", "metadata_change"), [
    ("policy_selection", True, False),
    ("contract_facts", False, True),
    ("policy_selection_contract_facts", True, True),
])
def test_each_arm_changes_only_its_declared_input_fields(
    tmp_path, arm, policy_change, metadata_change,
):
    trial, _ = _trial_fixture(tmp_path)
    case = ablation.load_cases(trial)[0]
    original_state = copy.deepcopy(case["state"])
    original_questions = copy.deepcopy(case["questions"])

    state, questions = ablation.variant(case, arm)

    expected_state = copy.deepcopy(original_state)
    if metadata_change:
        source = expected_state["sources"][0]
        source.pop("metadata")
        source["metadata_omitted_for_experiment"] = True
    assert state == expected_state
    assert state["card"] == original_state["card"]
    for field in ("policy", "observations", "attributes", "contracts", "context",
                  "evidence", "source_errors"):
        assert state[field] == original_state[field]
    assert "metadata_omitted_for_experiment" not in state["sources"][1]

    if policy_change:
        assert questions.keys() == original_questions.keys()
        assert questions["outcome"]["instructions"] != original_questions["outcome"]["instructions"]
        assert questions["outcome"]["criteria"].keys() == original_questions["outcome"]["criteria"].keys()
        assert all(questions["outcome"]["criteria"][key] != original_questions["outcome"]["criteria"][key]
                   for key in original_questions["outcome"]["criteria"])
        restored = copy.deepcopy(questions)
        restored["outcome"]["instructions"] = original_questions["outcome"]["instructions"]
        restored["outcome"]["criteria"] = original_questions["outcome"]["criteria"]
        assert restored == original_questions
    else:
        assert questions == original_questions

    assert case["state"] == original_state
    assert case["questions"] == original_questions


async def test_dry_run_uses_cached_baselines_without_constructing_sdk(
    tmp_path, offline_sdk,
):
    trial, _ = _trial_fixture(tmp_path)
    cases = ablation.load_cases(trial)

    report = await ablation.run(trial, tmp_path / "dry-run", live=False, key_file=None)

    assert report["status"] == "dry_run"
    assert report["physical_requests"] == 0
    assert report["results"] == [
        {"period_id": case["period_id"], "arm": "cached_baseline",
         "expected": case["expected"],
         **ablation.assessment(case["baseline"]["answers"]["outcome"],
                               case["threshold"], case["expected"])}
        for case in cases
    ]
    assert offline_sdk.options == []
    assert offline_sdk.calls == []


async def test_live_mock_obeys_sdk_contract_cap_and_keeps_labels_out_of_payloads(
    tmp_path, offline_sdk,
):
    trial, _ = _trial_fixture(tmp_path)
    key_file = tmp_path / "fixture-key"
    key_file.write_text("fixture-only-key\n")

    report = await ablation.run(
        trial, tmp_path / "live-mock", live=True, key_file=key_file,
    )

    assert ablation.MAX_REQUESTS == 12
    assert report["physical_requests"] == 12
    assert len(offline_sdk.options) == 1
    assert len(offline_sdk.calls) == 12
    assert len(report["results"]) == 16
    loaded_cases = ablation.load_cases(trial)
    cases = {case["period_id"]: case for case in loaded_cases}
    private_labels = [case["expected"] for case in loaded_cases]
    candidate_rows = [row for row in report["results"] if row["arm"] != "cached_baseline"]
    for row, call in zip(candidate_rows, offline_sdk.calls, strict=True):
        case = cases[row["period_id"]]
        state, questions = ablation.variant(case, row["arm"])
        assert call == {"state": state, "questions": questions, "model": case["model"]}
        serialized_payload = json.dumps({"state": call["state"], "questions": call["questions"]})
        assert all(label not in serialized_payload for label in private_labels)
        assert "expected" not in call["state"]
        assert "expected" not in call["questions"]


async def test_oversized_candidate_is_marked_local_without_model_call(
    tmp_path, monkeypatch, offline_sdk,
):
    trial, _ = _trial_fixture(tmp_path)
    key_file = tmp_path / "fixture-key"
    key_file.write_text("fixture-only-key\n")
    original_estimator = ablation.estimate_json_tokens

    def oversized_metadata_projection(payload):
        is_second_case = payload["state"]["card"]["id"] == "card-period-02"
        metadata_was_removed = "metadata_omitted_for_experiment" in payload["state"]["sources"][0]
        is_contract_facts_only = (
            payload["questions"]["outcome"]["instructions"]
            == "Use the original owner-policy outcome wording."
        )
        if is_second_case and metadata_was_removed and is_contract_facts_only:
            return ablation.DEFAULT_MAX_JEV_INPUT_TOKENS + 1
        return original_estimator(payload)

    monkeypatch.setattr(ablation, "estimate_json_tokens", oversized_metadata_projection)

    report = await ablation.run(
        trial, tmp_path / "oversized", live=True, key_file=key_file,
    )

    oversized_rows = [row for row in report["results"]
                      if row.get("status") == "local_preflight_not_run"]
    assert len(oversized_rows) == 1
    assert oversized_rows[0]["period_id"] == "period-02"
    assert oversized_rows[0]["arm"] == "contract_facts"
    assert oversized_rows[0]["estimated_tokens"] == ablation.DEFAULT_MAX_JEV_INPUT_TOKENS + 1
    assert report["physical_requests"] == len(offline_sdk.calls) == 11


async def test_model_version_mismatch_is_reported_without_assessment(
    tmp_path, offline_sdk,
):
    trial, _ = _trial_fixture(tmp_path)
    key_file = tmp_path / "fixture-key"
    key_file.write_text("fixture-only-key\n")
    offline_sdk.response_models = ["unexpected-model"]

    report = await ablation.run(
        trial, tmp_path / "model-mismatch", live=True, key_file=key_file,
    )

    changed = [row for row in report["results"] if row.get("status") == "model_changed"]
    assert len(changed) == 1
    assert changed[0]["period_id"] == "period-01"
    assert changed[0]["arm"] == "policy_selection"
    assert "selected" not in changed[0]
    assert report["physical_requests"] == len(offline_sdk.calls) == 12


async def test_empty_key_is_rejected_before_sdk_construction(tmp_path, offline_sdk):
    trial, _ = _trial_fixture(tmp_path)
    key_file = tmp_path / "empty-key"
    key_file.write_text(" \n\t")

    with pytest.raises(ValueError, match="Empty Jev key"):
        await ablation.run(
            trial, tmp_path / "empty-key-run", live=True, key_file=key_file,
        )

    assert offline_sdk.options == []
    assert offline_sdk.calls == []

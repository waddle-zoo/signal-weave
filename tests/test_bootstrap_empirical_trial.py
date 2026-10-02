"""Offline contracts for the bounded empirical bootstrap worker."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from evaluations import bootstrap_empirical_trial as trial
from evaluations import codex_trial_transport
from evaluations.bootstrap_agent_trial import Audit, BudgetExceeded, RequestBudget
from signalweave.models import InsightResult, Outcome


class _ExpectedOutcomeJudger:
    """Offline-only judger for exercising the real native runner plumbing."""

    name = "fixture-expected-outcome-only"

    def __init__(self, labels):
        self.labels = labels

    async def judge(self, state, card, plan, observations):
        del plan
        period_id = state["sources"][0]["metadata"]["period_id"]
        label = self.labels[period_id]
        outcome = Outcome(label["expected_outcome"])
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            delivery_methods=[
                method for method in card.delivery_methods
                if method.key in label["expected_delivery_method_keys"]
            ],
            summary="Test-only injected expected outcome.",
            rationale="Test-only injected expected outcome; not a Jev result.",
            confidence=0.99,
            probabilities={outcome.value: 0.99},
            watch_results=[
                {"key": f"watch_{index}", "watch_for": watch, "status": "present", "probability": 0.99}
                for index, watch in enumerate(card.watch_for)
            ],
            question_results=[
                {"key": f"question_{index}", "question": question, "status": "supported", "probability": 0.99}
                for index, question in enumerate(card.questions)
            ],
            evidence=state["evidence"],
            observations=observations,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )


def _accepted_report(company, card):
    return SimpleNamespace(
        acceptance_passed=True,
        status="approved",
        case_count=3,
        error_count=0,
        outcome_accuracy=1.0,
        evidence_recall=1.0,
        retrieval_recall=1.0,
        retrieval_precision=1.0,
        unsafe_action_rate=0.0,
        preflight_blockers=[],
        acceptance_outcomes=trial.acceptance_outcomes(company),
        card_execution_digests={card.id: trial.card_acceptance_digest(card)},
        cases=[],
    )


def _flat_intent(company, **overrides):
    card = company["expert_card"]
    intent = {
        "title": card["title"],
        "what_to_watch": card["what_to_watch"],
        "why_watch": card["why_watch"],
        "decision_guidance": card["decision_guidance"],
        "source_keys": [source["key"] for source in company["sources"]],
        "routes": [
            {"destination_key": method["key"], "outcome": method["outcome"]}
            for method in card["delivery_methods"]
        ],
        "watch_for": card["watch_for"],
        "questions": card["questions"],
    }
    return {**intent, **overrides}


def test_runner_uses_one_fixture_worker_and_dynamic_setup_outcomes():
    companies = trial.build_companies()
    assert trial.build_companies.__module__ == "evaluations.bootstrap_empirical_trial"
    assert len(companies) == 3
    assert all(len(item["setup_cases"]) == 3 for item in companies)
    assert all(len(item["holdout_cases"]) == 4 for item in companies)
    assert any("investigate" in {value.value for value in trial.acceptance_outcomes(item)} for item in companies)
    assert not hasattr(trial, "_company")
    assert not hasattr(trial, "_snapshot")
    assert not hasattr(trial, "_case")


def test_public_projections_keep_setup_labels_but_never_holdout_labels_or_expert_card():
    company = trial.build_companies()[0]
    public = trial.public_company(company)
    encoded = json.dumps(public)
    assert "expert_card" not in encoded
    assert len(public["setup_examples"]) == 3
    assert all("expected_outcome" in case for case in public["setup_examples"])

    session = trial.RawLunaSession(company, company["holdout_cases"][0], None, notes="")
    prompt = json.dumps(session.public)
    assert "expert_card" not in prompt
    holdout_prompt = json.dumps(session.public["current_holdout"])
    assert "expected_outcome" not in holdout_prompt
    assert "expected_delivery_destinations" not in holdout_prompt


def test_routes_are_copied_from_case_labels_not_source_keys():
    for company in trial.build_companies():
        destinations = {item["key"]: item["destination"] for item in company["destinations"]}
        for case in [*company["setup_cases"], *company["holdout_cases"]]:
            keys = set(case["expected_delivery_method_keys"])
            assert set(case["expected_delivery_destinations"]) == keys
            assert case["expected_delivery_destinations"] == {key: destinations[key] for key in keys}


@pytest.mark.parametrize("value", [None, 25.0])
def test_candidate_requires_fixed_snapshot_age_contract(value):
    company = trial.build_companies()[0]
    card = dict(company["expert_card"])
    card["max_source_age_hours"] = value
    with pytest.raises(ValueError, match="max_source_age_hours"):
        trial._candidate(card, company)


def test_historical_engine_sets_clock_from_each_case_capture(monkeypatch):
    company = trial.build_companies()[0]
    resource = trial.ResourceSnapshot.model_validate(company["holdout_cases"][0]["resources"][0])
    engine = trial.HistoricalClockEngine(SimpleNamespace())
    seen = {}

    async def fake_base_evaluate(self, card, resources=None, context_override=None, principal=None):
        seen["clock"] = self.clock()
        return "ok"

    monkeypatch.setattr(trial.InsightEngine, "evaluate", fake_base_evaluate)
    assert __import__("asyncio").run(engine.evaluate(None, [resource])) == "ok"
    assert seen["clock"] == resource.captured_at


@pytest.mark.asyncio
async def test_author_proposal_schema_is_flat_draft_intent():
    session = trial.AuthorSession(trial.build_companies()[0], SimpleNamespace(), Audit())
    spec = (await session.specs())[0]

    assert set(spec["parameters"]["required"]) == {
        "title", "what_to_watch", "why_watch", "decision_guidance", "source_keys", "routes",
    }
    assert "card" not in spec["parameters"]["properties"]
    assert spec["parameters"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_native_raw_evidence_uses_real_engine_and_serializes_all_four_runs():
    audit = Audit()
    for company in trial.build_companies():
        card = trial.InsightCard.model_validate(company["expert_card"])
        labels = {
            resource["metadata"]["period_id"]: case
            for case in company["holdout_cases"]
            for resource in [case["resources"][0]]
        }
        raw = []
        report = await trial.run_native_holdout(
            company,
            card,
            _ExpectedOutcomeJudger(labels),
            audit=audit,
            raw_output=raw,
        )
        assert report.case_count == 4
        assert [item["case_id"] for item in raw] == [case["id"] for case in company["holdout_cases"]]
        assert all(set(item) == {"case_id", "run"} for item in raw)
        assert all(set(item["run"]) == {"card", "resources", "plan", "result"} for item in raw)
        json.dumps(raw)
    native_events = [event for event in audit.events if event["kind"] == "native.result"]
    assert len(native_events) == 12


@pytest.mark.asyncio
async def test_author_uses_custom_prompt_and_conservative_codex_timeout(monkeypatch):
    company = trial.build_companies()[0]
    observed = {}

    async def fake_evaluate(card, company, judger):
        card.compiled_plan = trial.InsightCard.model_validate(company["expert_card"]).compiled_plan
        return _accepted_report(company, card)

    async def fake_episode(session, **kwargs):
        observed.update(kwargs)
        assert session.submission is None
        bridge = codex_trial_transport.TrialMCP(session, kwargs["audit"], await session.specs(), max_calls=8)
        for name, arguments in (
            ("propose_card", _flat_intent(company)),
            ("test_card", {}),
            ("finish_setup", {"notes": "Use the accepted owner policy."}),
        ):
            response = await bridge.call(name, arguments)
            assert not response.isError, response.content
        return {"status": "complete", "error": None, "exit_code": 0, "foreign_tools": [], "tool_calls": bridge.calls}

    monkeypatch.setattr(trial, "evaluate_candidate", fake_evaluate)
    monkeypatch.setattr(codex_trial_transport, "codex_episode", fake_episode)
    result = await trial.author_company(
        company,
        judger=SimpleNamespace(),
        budget=RequestBudget(2),
        audit=Audit(),
    )
    assert result["status"] == "accepted"
    assert observed["instructions_override"] == trial.AUTHOR_INSTRUCTIONS
    assert observed["timeout_seconds"] == trial.CODEX_EPISODE_TIMEOUT_SECONDS == 180
    assert "expert_card" not in json.dumps(observed["prompt_override"])
    assert "holdout_cases" not in json.dumps(observed["prompt_override"])


@pytest.mark.asyncio
async def test_candidate_attempt_is_reserved_before_paid_evaluation_and_invalid_schema_is_cheap(monkeypatch):
    company = trial.build_companies()[0]
    session = trial.AuthorSession(company, SimpleNamespace(), Audit())
    with pytest.raises(ValueError, match="invalid_candidate_schema"):
        await session.call("propose_card", {"not": "a DraftIntent"})
    assert session.candidate_evaluations == 0
    await session.call("propose_card", _flat_intent(company))

    async def fails(*args, **kwargs):
        raise TimeoutError("offline provider")

    monkeypatch.setattr(trial, "evaluate_candidate", fails)
    first = await session.call("test_card", {})
    assert first["accepted"] is False
    with pytest.raises(ValueError, match="unchanged_candidate_would_repeat_evaluation"):
        await session.call("test_card", {})
    assert session.candidate_evaluations == 1

    await session.call("propose_card", _flat_intent(company, title="revised"))
    second = await session.call("test_card", {})
    assert second["accepted"] is False
    assert session.candidate_evaluations == 2


@pytest.mark.asyncio
async def test_failed_or_invalid_reproposal_cannot_reuse_stale_acceptance(monkeypatch):
    company = trial.build_companies()[0]
    session = trial.AuthorSession(company, SimpleNamespace(), Audit())

    async def accepted(card, company, judger):
        card.compiled_plan = trial.InsightCard.model_validate(company["expert_card"]).compiled_plan
        return _accepted_report(company, card)

    monkeypatch.setattr(trial, "evaluate_candidate", accepted)
    await session.call("propose_card", _flat_intent(company))
    assert (await session.call("test_card", {}))["accepted"] is True
    with pytest.raises(ValueError, match="invalid_candidate_schema"):
        await session.call("propose_card", {"invalid": True})
    with pytest.raises(ValueError, match="strict_setup_acceptance_required"):
        await session.call("finish_setup", {"notes": "stale acceptance must not finish"})

    await session.call("propose_card", _flat_intent(company, title="repaired"))

    async def failed(*args, **kwargs):
        raise TimeoutError("candidate provider failure")

    monkeypatch.setattr(trial, "evaluate_candidate", failed)
    assert (await session.call("test_card", {}))["accepted"] is False
    with pytest.raises(ValueError, match="strict_setup_acceptance_required"):
        await session.call("finish_setup", {"notes": "failed repair must not finish"})


@pytest.mark.asyncio
async def test_acceptance_digest_binds_current_candidate_signature(monkeypatch):
    company = trial.build_companies()[0]
    session = trial.AuthorSession(company, SimpleNamespace(), Audit())

    async def accepted(card, company, judger):
        card.compiled_plan = trial.InsightCard.model_validate(company["expert_card"]).compiled_plan
        return _accepted_report(company, card)

    monkeypatch.setattr(trial, "evaluate_candidate", accepted)
    await session.call("propose_card", _flat_intent(company))
    assert (await session.call("test_card", {}))["accepted"] is True
    session.candidate.title = "mutated after acceptance"
    with pytest.raises(ValueError, match="strict_setup_acceptance_required"):
        await session.call("finish_setup", {"notes": "mutation must invalidate"})


@pytest.mark.asyncio
async def test_raw_submission_uses_strict_json_and_citation_allowlist():
    company = trial.build_companies()[0]
    session = trial.RawLunaSession(company, company["holdout_cases"][0], None, notes="")
    with pytest.raises(ValueError, match="uninspected_evidence_ref"):
        await session.call("submit_analysis", {
            "outcome": "ignore",
            "recipients": [],
            "evidence_refs": ["not|a-source"],
            "explanation": "No external notification.",
        })
    assert session.submission is None
    refs = [f"{item['adapter']}|{item['resource']}" for item in company["sources"]]
    result = await session.call("submit_analysis", {
        "outcome": "ignore",
        "recipients": [],
        "evidence_refs": refs,
        "explanation": "No external notification.",
    })
    assert result == {"recorded": True, "delivery_enabled": False}
    assert session.submission["outcome"] == "ignore"


def test_incomplete_raw_episode_cannot_score_as_a_win():
    company = trial.build_companies()[0]
    case = company["holdout_cases"][0]
    refs = [f"{item['adapter']}|{item['resource']}" for item in company["sources"]]
    row = {
        "complete": False,
        "episode": {"status": "failed", "error": "foreign_tools"},
        "submission": {
            "outcome": case["expected_outcome"],
            "recipients": case["expected_delivery_method_keys"],
            "evidence_refs": refs,
            "explanation": "apparently correct but incomplete episode",
        },
    }
    assert trial.score_raw_submission(company, case, row)["exact"] is False


@pytest.mark.asyncio
async def test_offline_run_is_exclusive_and_makes_no_paid_calls(tmp_path):
    output = tmp_path / "trial"
    report = await trial.run_trial(output)
    assert report["status"] == "not_run"
    assert report["paid_calls_made"] is False
    assert (output / "manifest.json").exists()
    assert (output / "report.json").exists()
    with pytest.raises(FileExistsError):
        await trial.run_trial(output)


@pytest.mark.asyncio
async def test_failed_native_case_keeps_later_success_in_its_own_slot(monkeypatch):
    engine = trial.RecordingHistoricalClockEngine(SimpleNamespace())
    engine.case_ids = ["case-a", "case-b"]
    successful_run = SimpleNamespace(model_dump=lambda mode="json": {"case": "b"})
    calls = 0

    async def fake_historical(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("first case failed")
        return successful_run

    monkeypatch.setattr(trial.HistoricalClockEngine, "evaluate", fake_historical)
    with pytest.raises(TimeoutError):
        await engine.evaluate(None, [])
    assert await engine.evaluate(None, []) is successful_run
    assert engine.raw_runs[0] == {"case_id": "case-a", "error": "TimeoutError"}
    assert engine.raw_runs[1]["case_id"] == "case-b"
    assert engine.raw_runs[1]["run"] is successful_run


@pytest.mark.asyncio
async def test_jev_budget_counts_failed_provider_calls_without_retry(monkeypatch):
    budget = RequestBudget(2)
    audit = Audit()
    jev = trial.TrialJev("offline-key", budget, audit)

    async def fail_provider(*args, **kwargs):
        raise TimeoutError("offline provider")

    monkeypatch.setattr(trial.JevJudger, "_system_one_with_retry", fail_provider)
    for _ in range(2):
        with pytest.raises(TimeoutError):
            await jev._system_one_with_retry(state={}, questions={}, stage="judgment")
    assert budget.used == 2
    assert len([event for event in audit.events if event["kind"] == "api.error"]) == 2
    with pytest.raises(BudgetExceeded):
        await jev._system_one_with_retry(state={}, questions={}, stage="judgment")
    assert budget.used == 2


def test_live_freeze_detects_dataset_and_code_mutations(monkeypatch):
    companies = trial.build_companies()
    original = trial.source_freeze()
    fixture_hash = trial.digest(companies)
    changed_data = trial.build_companies()
    changed_data[0]["brief"] += " changed"
    with pytest.raises(RuntimeError, match="fixture_data_freeze_changed"):
        trial._assert_live_freeze(changed_data, fixture_hash, original)

    monkeypatch.setattr(trial, "source_freeze", lambda: {"changed": True})
    with pytest.raises(RuntimeError, match="code_prompt_dependency_freeze_changed"):
        trial._assert_live_freeze(companies, fixture_hash, original)


def test_candidate_requires_only_declared_required_sources_and_rejects_other_changes():
    company = copy.deepcopy(trial.build_companies()[1])
    optional_key = next(item["key"] for item in company["sources"] if not item["required"])
    card = copy.deepcopy(company["expert_card"])
    card["sources"] = [item for item in card["sources"] if item["key"] != optional_key]
    card["compiled_plan"] = None
    assert optional_key not in {item.key for item in trial._candidate(card, company).sources}

    unknown = copy.deepcopy(card)
    unknown["sources"].append(copy.deepcopy(company["sources"][0]))
    unknown["sources"][-1]["key"] = "unapproved-source"
    with pytest.raises(ValueError, match="unapproved source"):
        trial._candidate(unknown, company)

    changed = copy.deepcopy(card)
    changed["sources"][0]["resource"] += "-changed"
    with pytest.raises(ValueError, match="changed source declaration"):
        trial._candidate(changed, company)


def test_candidate_accepts_explicit_route_key_when_label_and_endpoint_are_exact():
    company = copy.deepcopy(trial.build_companies()[0])
    card = copy.deepcopy(company["expert_card"])
    card["delivery_methods"][0]["key"] = "explicit-method-key"
    card["compiled_plan"] = None

    candidate = trial._candidate(card, company)

    assert candidate.delivery_methods[0].key == "explicit-method-key"
    assert candidate.delivery_methods[0].label == company["destinations"][0]["label"]


def test_public_card_payload_keeps_compiled_plan_but_strips_approval_history():
    card = trial.InsightCard.model_validate(trial.build_companies()[0]["expert_card"])
    payload = trial.public_card_payload(card)
    assert payload["compiled_plan"] is not None
    assert "onboarding_review" not in payload
    assert "onboarding_review_history" not in payload
    assert "status" not in payload
    assert "approved_by" not in payload


def test_paid_calls_are_derived_from_audited_requests_even_when_failed():
    assert trial.has_paid_audit_requests(Audit()) is False
    failed_codex = Audit()
    failed_codex.emit("api.request", provider="openai", request_id=-1)
    failed_codex.emit("api.error", provider="openai", request_id=-1, error_type="TimeoutError")
    assert trial.has_paid_audit_requests(failed_codex) is True


@pytest.mark.asyncio
async def test_candidate_audit_and_failed_author_result_retain_full_artifacts(monkeypatch):
    company = trial.build_companies()[0]
    audit = Audit()

    async def fake_evaluate(card, company, judger):
        card.compiled_plan = trial.InsightCard.model_validate(company["expert_card"]).compiled_plan
        return _accepted_report(company, card)

    async def failed_episode(session, **kwargs):
        bridge = codex_trial_transport.TrialMCP(session, kwargs["audit"], await session.specs(), max_calls=8)
        assert (await bridge.call("propose_card", _flat_intent(company))).isError is False
        result = await bridge.call("test_card", {})
        assert result.isError is False
        return {"status": "failed", "error": "timeout", "exit_code": 1, "foreign_tools": []}

    monkeypatch.setattr(trial, "evaluate_candidate", fake_evaluate)
    monkeypatch.setattr(codex_trial_transport, "codex_episode", failed_episode)
    result = await trial.author_company(
        company, judger=SimpleNamespace(), budget=RequestBudget(2), audit=audit
    )

    evaluated = [event for event in audit.events if event["kind"] == "candidate.evaluated"]
    assert len(evaluated) == 1
    assert evaluated[0]["candidate"]["compiled_plan"] is not None
    assert evaluated[0]["acceptance_report"]["card_execution_digests"]
    assert result["status"] == "failed"
    assert result["accepted_card"] is None
    assert result["last_candidate"]["compiled_plan"] is not None
    assert result["acceptance_report"]["card_execution_digests"]

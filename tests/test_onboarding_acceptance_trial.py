"""Offline fixture judger tests: contract plumbing, explicitly not semantic proof."""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
import typesafe_sdk

from evaluations import onboarding_acceptance_trial as harness
from signalweave.evaluation import CardWorkflowEvaluator, card_acceptance_digest


def read_events(output):
    return [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]


@pytest.fixture(autouse=True)
def no_live_transport(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("Offline tests must not create a real Jev client")

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", forbidden)
    monkeypatch.setattr(harness, "load_api_key", lambda _: "offline-secret-never-persist")


@pytest.fixture
def fixture_judger(monkeypatch):
    """Canned answers by ordinal, not a semantic heuristic or evidence of accuracy."""
    # Plumbing tests must not race concurrent edits in the shared checkout.
    # The dedicated source-freeze test below still exercises real working bytes.
    monkeypatch.setattr(harness, "source_freeze", lambda: {
        "git_revision": "offline-fixture", "git_status": "",
        "source_sha256": {"offline-fixture": "0" * 64}, "dependencies": {},
    })
    control = SimpleNamespace(calls=[], options=[], fail_at=None, interrupt_at=None,
                              wrong_at=None, output=None)

    class FixtureClient:
        def __init__(self, **kwargs):
            control.options.append(kwargs)
            assert kwargs["retry"].max_retries == 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def system_one(self, *, state, questions):
            index = len(control.calls)
            control.calls.append({"state": state, "questions": questions})
            if control.output:
                events = read_events(control.output)
                # The request survives even if transport never returns.
                assert events[-1]["event"] == "request"
                assert events[-1]["request_id"] == index + 1
                assert events[-1]["state"] == state
            if index == control.interrupt_at:
                raise asyncio.CancelledError("offline-secret-never-persist")
            if index == control.fail_at:
                raise ConnectionError("Authorization: Bearer offline-secret-never-persist")
            selected = ("present", "absent", "unknown", "unknown")[index % 4]
            if index == control.wrong_at:
                selected = "absent"
            outcome = {"present": "notify", "absent": "ignore", "unknown": "insufficient_data"}[selected]
            return SimpleNamespace(
                model="offline-fixture-not-semantic-proof",
                choices={
                    "watch_0": SimpleNamespace(choice=selected, confidence=.98, probabilities={
                        option: .98 if option == selected else .01
                        for option in ("present", "absent", "unknown")}),
                    "outcome": SimpleNamespace(choice=outcome, confidence=.97, probabilities={
                        option: .97 if option == outcome else .01
                        for option in questions["outcome"].criteria}),
                }, nouls={}, scores={}, usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FixtureClient)
    return control


def test_reuses_exact_reviewed_evidence_and_one_card_per_company():
    companies = harness.cases()
    original = {name: (card, resource, state)
                for name, card, resource, state in harness.reviewed_cases()}
    assert set(companies) == {"commerce", "operations", "customer-success"}
    ids = set()
    for company, group in companies.items():
        assert len(group) == 4
        assert {case.expected_outcome for case in group} == set(harness.ACCEPTANCE_OUTCOMES)
        assert len({harness.digest(case.card.model_dump(mode="json")) for case in group}) == 1
        assert len({card_acceptance_digest(case.card) for case in group}) == 1
        ids.add(group[0].card.id)
        for case in group:
            old_card, resource, state = original[case.id]
            assert case.resources[0].model_dump(exclude={"captured_at"}) == resource.model_dump(exclude={"captured_at"})
            assert case.card.watch_for == old_card.watch_for
            assert case.card.decision_guidance == old_card.decision_guidance
            assert case.card.id == case.card.compiled_plan.card_id == f"{company}-operating-check"
            assert case.expected_outcome == harness.EXPECTED_OUTCOMES[state]
            assert case.expected_delivery_destinations is not None
            assert case.expected_delivery_method_keys == list(case.expected_delivery_destinations)
    assert len(ids) == 3


async def test_opt_in_and_exclusive_output_before_credentials(monkeypatch, tmp_path):
    def no_key(_):
        pytest.fail("must reject before reading credentials")

    monkeypatch.setattr(harness, "load_api_key", no_key)
    output = tmp_path / "exclusive"
    with pytest.raises(ValueError, match="opt-in"):
        await harness.trial(output, "unused")
    assert not output.exists()
    output.mkdir()
    with pytest.raises(FileExistsError):
        await harness.trial(output, "unused", live=True)
    assert not list(output.iterdir())


async def test_fixture_run_and_offline_report_recompute(fixture_judger, tmp_path):
    output = fixture_judger.output = tmp_path / "fixture-plumbing-only"
    assert await harness.trial(output, "unused", live=True)
    saved = json.loads((output / "report.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    assert saved["passed"] and saved["attempts"] == 12
    assert saved["external_delivery"] is False
    assert saved["novice_bootstrap_proof"] is saved["luna_advantage_established"] is False
    assert len(fixture_judger.calls) == len(fixture_judger.options) == 12
    assert all(report["acceptance_passed"] for report in saved["companies"].values())
    assert all(report["case_count"] == 4 for report in saved["companies"].values())
    for company, report in saved["companies"].items():
        card = harness.cases()[company][0].card
        assert report["card_execution_digests"] == {card.id: card_acceptance_digest(card)}
        assert manifest["card_execution_digests"][card.id] == card_acceptance_digest(card)
    review = await harness.recompute(output)
    assert review["passed"]
    assert len(fixture_judger.calls) == 12  # Recompute cannot make a request.
    events = read_events(output)
    assert [event["event"] for event in events] == ["request", "response", "result"] * 12
    assert all(event["resolved_model"] == "offline-fixture-not-semantic-proof"
               for event in events if event["event"] == "response")
    for path in output.iterdir():
        assert "offline-secret-never-persist" not in path.read_text()


async def test_labels_never_enter_real_question_construction(fixture_judger, tmp_path):
    output = tmp_path / "no-leak"
    assert await harness.trial(output, "unused", live=True)
    all_cases = [case for group in harness.cases().values() for case in group]
    for event in read_events(output):
        if event["event"] != "request":
            continue
        encoded = json.dumps({"state": event["state"], "questions": event["questions"]})
        for case in all_cases:
            assert case.id not in encoded
        for label in ("expected_outcome", "expected_delivery_destinations", "expected_watch",
                      "label_source", "case_id", "acceptance_outcomes", "dataset_id"):
            assert label not in encoded


async def test_changed_labels_do_not_change_request(fixture_judger, tmp_path):
    group = harness.cases()["commerce"]
    output = tmp_path / "label-mutation"
    output.mkdir()
    journal = harness.Journal(output)
    judger = harness.RecordedJudger("offline-secret-never-persist", journal)
    try:
        original = await CardWorkflowEvaluator(
            harness.RecordedEngine(judger, group, journal), max_concurrency=1,
        ).evaluate(group, acceptance_outcomes=harness.ACCEPTANCE_OUTCOMES)
        changed = [case.model_copy(deep=True) for case in group]
        changed[0].expected_delivery_destinations = {"owner": "agent://label-only-canary"}
        replay = await CardWorkflowEvaluator(
            harness.RecordedEngine(judger, changed, journal), max_concurrency=1,
        ).evaluate(changed, acceptance_outcomes=harness.ACCEPTANCE_OUTCOMES)
    finally:
        journal.close()
    assert original.acceptance_passed and not replay.acceptance_passed
    requests = [event for event in read_events(output) if event["event"] == "request"]
    assert requests[0]["state"] == requests[4]["state"]
    assert requests[0]["questions"] == requests[4]["questions"]
    assert "label-only-canary" not in json.dumps(requests)


@pytest.mark.parametrize("budget,case_budget,stage", [(12, 0, "judgment"), (0, 1, "judgment"), (0, 0, "compile")])
async def test_request_budget_enforced_before_transport(tmp_path, budget, case_budget, stage):
    journal = harness.Journal(tmp_path)
    judger = harness.RecordedJudger("offline-secret-never-persist", journal)
    judger.attempts, judger.case_attempts = budget, case_budget
    try:
        with pytest.raises(harness.TrialExecutionError, match="budget"):
            await judger._system_one_with_retry(state={}, questions={}, stage=stage)
    finally:
        journal.close()
    assert not read_events(tmp_path)


async def test_transport_failure_is_counted_persisted_redacted_and_not_retried(fixture_judger, tmp_path):
    output = fixture_judger.output = tmp_path / "failed-case"
    fixture_judger.fail_at = 1
    assert not await harness.trial(output, "unused", live=True)
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "complete"
    assert report["attempts"] == len(fixture_judger.calls) == 12
    assert report["companies"]["commerce"]["error_count"] == 1
    assert report["companies"]["commerce"]["acceptance_passed"] is False
    events = read_events(output)
    assert len([event for event in events if event["event"] == "response"]) == 11
    failure = next(event for event in events if event["event"] == "request_error")
    assert failure["error_type"] == "ConnectionError"
    for path in output.iterdir():
        assert "offline-secret-never-persist" not in path.read_text()
        assert "Authorization: Bearer" not in path.read_text()


async def test_interruption_keeps_completed_company_and_pending_request(fixture_judger, tmp_path):
    output = fixture_judger.output = tmp_path / "interrupted"
    fixture_judger.interrupt_at = 4
    with pytest.raises(asyncio.CancelledError):
        await harness.trial(output, "unused", live=True)
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "interrupted" and not report["passed"]
    assert report["companies"]["commerce"]["acceptance_passed"]
    assert report["attempts"] == 5
    assert len([event for event in read_events(output) if event["event"] == "request"]) == 5
    assert len([event for event in read_events(output) if event["event"] == "response"]) == 4


async def test_first_setup_failure_leaves_redacted_non_green_report(monkeypatch, tmp_path):
    def fail(_):
        raise ValueError("offline-secret-never-persist")

    monkeypatch.setattr(harness, "load_api_key", fail)
    output = tmp_path / "setup-failed"
    assert not await harness.trial(output, "unused", live=True)
    report = json.loads((output / "report.json").read_text())
    assert report["error_type"] == "ValueError"
    assert not report["passed"] and report["attempts"] == 0
    assert "offline-secret-never-persist" not in (output / "report.json").read_text()


async def test_recompute_rejects_forged_green_report(fixture_judger, tmp_path):
    fixture_judger.wrong_at = 0
    output = tmp_path / "wrong-judgment"
    assert not await harness.trial(output, "unused", live=True)
    path = output / "report.json"
    forged = json.loads(path.read_text())
    forged["passed"] = True
    forged["companies"]["commerce"]["acceptance_passed"] = True
    forged["companies"]["commerce"]["outcome_accuracy"] = 1
    forged["companies"]["commerce"]["cases"][0]["exact_outcome"] = True
    path.write_text(json.dumps(forged))
    review = await harness.recompute(output)
    assert not review["passed"]
    assert not review["checks"]["commerce:report"]
    assert not review["checks"]["commerce:acceptance"]
    assert len(fixture_judger.calls) == 12


async def test_trial_still_rejects_source_change(fixture_judger, monkeypatch, tmp_path):
    freezes = iter([
        {"source_sha256": {"source.py": "before"}},
        {"source_sha256": {"source.py": "after"}},
    ])
    monkeypatch.setattr(harness, "source_freeze", lambda: next(freezes))
    output = tmp_path / "source-changed"
    assert not await harness.trial(output, "unused", live=True)
    report = json.loads((output / "report.json").read_text())
    assert report["sources_unchanged"] is False
    assert [key for key, passed in report["checks"].items() if not passed] == ["sources_unchanged"]


def test_freeze_hashes_working_bytes_including_dirty_sources(monkeypatch, tmp_path):
    source = tmp_path / "src/signalweave/engine.py"
    source.parent.mkdir(parents=True)
    source.write_text("dirty working bytes")
    paths = ["evaluations/onboarding_acceptance_trial.py", "evaluations/watch_evidence_trial.py",
             "examples/investigation_agent/onboarding.py",
             "tests/test_onboarding_acceptance_trial.py", "pyproject.toml", "uv.lock",
             "README.md", "AGENTS.md"]
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness, "__file__", str(tmp_path / paths[0]))
    monkeypatch.setattr(harness.subprocess, "check_output", lambda args, **kw:
                        " M src/signalweave/engine.py" if "status" in args else "test-head")
    frozen = harness.source_freeze()
    assert frozen["source_sha256"]["src/signalweave/engine.py"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert frozen["git_status"].startswith(" M ")
    helper = tmp_path / "examples/investigation_agent/onboarding.py"
    assert frozen["source_sha256"][str(helper.relative_to(tmp_path))] == hashlib.sha256(helper.read_bytes()).hexdigest()
    helper.write_text("changed caller-owned bridge")
    assert harness.source_freeze()["source_sha256"] != frozen["source_sha256"]
    helper.write_text("fixture")
    source.write_text("changed after freeze")
    assert harness.source_freeze()["source_sha256"] != frozen["source_sha256"]

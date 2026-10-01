"""Offline harness contracts, not measured model performance."""

import asyncio
import json
import socket
import ssl
from collections import Counter
from types import SimpleNamespace

import pytest
import typesafe_sdk

from evaluations import question_answerability_trial as research
from signalweave.compiler import base_plan
from signalweave.models import InsightCard
from signalweave.typesafe_adapter import JevJudger


@pytest.fixture(autouse=True)
def no_network_or_credentials(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network and real credentials are forbidden in these tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", forbidden)
    monkeypatch.setattr(research, "load_api_key", lambda _: "offline-test")


def response(old=.9, candidate=.9):
    return SimpleNamespace(
        nouls={"old": SimpleNamespace(noul=old), "candidate": SimpleNamespace(noul=candidate)},
        model="offline-contract", usage=SimpleNamespace(input_tokens=41, output_tokens=7),
    )


def assert_label_free(state):
    forbidden = {"id", "domain", "variant", "reference_answer", "expected_accept", "expected_status", "labels"}
    if isinstance(state, dict):
        assert not forbidden.intersection(state)
        for value in state.values():
            assert_label_free(value)
    elif isinstance(state, list):
        for value in state:
            assert_label_free(value)


def test_fixture_coverage_count_labels_and_scope():
    fixture = list(research.cases())
    assert len(fixture) == research.LIMIT == 20
    assert len({case["id"] for case in fixture}) == 20
    assert Counter(case["domain"] for case in fixture[:16]) == {
        "support_denominator": 4, "release_rollback": 4,
        "finance_approval": 4, "cluster_coverage": 4,
    }
    for domain in {case["domain"] for case in fixture[:16]}:
        group = [case for case in fixture[:16] if case["domain"] == domain]
        assert {case["variant"] for case in group} == {"answer_yes", "answer_no", "missing", "conflicting"}
        assert len({case["state"]["insight_card"]["questions"][0] for case in group}) == 1
        for case in group:
            positive = case["variant"] in {"answer_yes", "answer_no"}
            assert case["expected_accept"] is positive
            assert case["expected_status"] == ("supported" if positive else "not_supported")
            assert case["reference_answer"] == {"answer_yes": "yes", "answer_no": "no"}.get(case["variant"])
    assert {case["variant"] for case in fixture[16:]} == {
        "partial_compound_question", "wrong_population", "open_numeric_answer", "causal_why_from_time",
    }
    assert sum(case["expected_accept"] for case in fixture) == 9
    for case in fixture:
        assert_label_free(case["state"])
        assert case["id"] not in json.dumps(case["state"])
        assert "questions" not in case["state"]
        assert len(case["state"]["insight_card"]["questions"]) == 1
        assert case["state"]["sources"] == [{"status": "healthy"}]
    by_id = {case["id"]: case for case in fixture}
    assert "zero" in json.dumps(by_id["support_denominator-answer_no"]["state"])
    missing = by_id["cluster_coverage-missing"]
    assert "lists east and west" in json.dumps(missing["state"])
    assert not missing["expected_accept"]


def test_numeric_edge_is_precomputed_and_not_a_yes_no_truth_label():
    case = next(c for c in research.cases() if c["variant"] == "open_numeric_answer")
    analysis = case["state"]["analyses"][0]
    assert analysis["value"] == 100 * analysis["inputs"]["met_sla"] / analysis["inputs"]["eligible_tickets"] == 75
    assert case["reference_answer"] == 75 and case["expected_accept"]
    assert analysis["status"] == "complete" and analysis["limitations"]
    assert all(not c["expected_accept"] for c in list(research.cases())[16:] if c != case)


@pytest.mark.parametrize("index", [0, 1])
async def test_old_template_matches_captured_production_question(monkeypatch, index):
    class Captured(Exception):
        pass

    captured = {}

    async def transport(self, *, state, questions, stage):
        captured.update(questions)
        assert stage == "judgment"
        raise Captured

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    owner_questions = [
        "Had the finance owner approved the settled refund batch?",
        "What percentage of eligible tickets met SLA?",
    ]
    card = InsightCard(
        id="offline-card", title="Offline template contract",
        what_to_watch="Supplied evidence", why_watch="Answer the owner questions",
        questions=owner_questions, sources=[],
    )
    with pytest.raises(Captured):
        await JevJudger(api_key="offline-test", max_retries=0).judge(
            {"insight_card": card.execution_payload()}, card, base_plan(card), [],
        )
    actual = JevJudger._question_budget_payload({"old": captured[f"question_{index}"]})
    copied = JevJudger._question_budget_payload(research.questions(owner_questions[index], index))
    assert actual["old"] == copied["old"]
    assert actual["old"]["criteria"]["true"] == owner_questions[index]


def test_candidate_instructions_embed_question_and_define_answer_existence():
    for case in research.cases():
        question = case["state"]["insight_card"]["questions"][0]
        pair = JevJudger._question_budget_payload(research.questions(question))
        assert set(pair) == set(research.ARMS)
        candidate = pair["candidate"]
        assert candidate["type"] == pair["old"]["type"] == "noul"
        assert repr(question) in candidate["instructions"]
        assert "insight_card.questions[0]" in candidate["instructions"]
        assert "no, zero" in candidate["criteria"]["true"]
        assert "Missing, conflicting, inapplicable" in candidate["criteria"]["false"]
        for limit in ("population", "period", "compound", "Code owns arithmetic", "causation", "complete coverage"):
            assert limit in candidate["instructions"]


@pytest.mark.parametrize("value,status", [
    (0, "not_supported"), (.30, "not_supported"), (.300001, "unknown"),
    (.5, "unknown"), (.699999, "unknown"), (.70, "supported"), (1, "supported"),
])
def test_frozen_thresholds(value, status):
    result = research.decode(SimpleNamespace(noul=value))
    assert research.SUPPORTED == JevJudger.item_threshold == .70
    assert research.NOT_SUPPORTED == .30
    assert result["status"] == status
    assert result["valid"] and result["probability"] == value
    assert result["accept"] is (status == "supported")
    # Match production at ordinary boundaries without inheriting 1 - .70's
    # floating-point rounding into the explicitly frozen .30 research threshold.
    assert JevJudger(api_key="offline-test")._question_result(0, "Question?", value).status.value == status


@pytest.mark.parametrize("value", [
    None, True, False, "0.9", [], {}, -.1, 1.1,
    float("nan"), float("inf"), float("-inf"), 10**1000,
])
def test_malformed_values_fail_closed_and_retain_json_diagnostics(value):
    result = research.decode(SimpleNamespace(noul=value))
    assert not result["valid"] and not result["accept"]
    assert result["status"] == "unknown" and result["probability"] is None
    assert result["raw"]["noul"] == research.safe_raw(value)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("answer", [None, {}, SimpleNamespace(choice="yes"), .9])
def test_missing_or_wrong_answer_shape_never_accepts(answer):
    assert not research.decode(answer)["accept"]


def test_comparison_separates_answerability_truth_unknown_and_malformed():
    fixture = list(research.cases())
    no = next(c for c in fixture if c["variant"] == "answer_no")
    missing = next(c for c in fixture if c["variant"] == "missing")
    decoded = {"old": research.decode(SimpleNamespace(noul=.1)), "candidate": research.decode(SimpleNamespace(noul=.9))}
    comparison = research.compare(decoded, no)
    assert not comparison["old"]["exact"] and comparison["candidate"]["exact"]
    assert not comparison["old"]["would_accept"] and comparison["candidate"]["would_accept"]
    assert research.compare(decoded, missing)["old"]["exact"]
    decoded["old"] = research.decode(SimpleNamespace(noul=.5))
    assert not research.compare(decoded, missing)["old"]["exact"]
    assert research.compare(decoded, missing)["old"]["acceptance_matches"]
    decoded["old"] = research.decode(None)
    assert not research.compare(decoded, missing)["old"]["acceptance_matches"]


async def test_one_paired_request_per_state_budget_before_await(monkeypatch):
    calls = []

    async def transport(self, *, state, questions, stage):
        assert self.attempts == len(calls) + 1
        assert self._max_retries == 0
        calls.append((state, questions))
        return response(.2, .9)

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    probe = research.Probe("offline-test")
    fixture = list(research.cases())
    for case in fixture:
        result = await probe.check(case["state"])
        assert result["model"] == "offline-contract"
        assert result["usage"] == {"input_tokens": 41, "output_tokens": 7}
        assert result["answers"]["old"]["raw"]["noul"] == .2
        assert result["answers"]["candidate"]["raw"]["noul"] == .9
    with pytest.raises(RuntimeError, match="budget"):
        await probe.check(fixture[0]["state"])
    assert len(calls) == probe.attempts == probe.metrics.requests == 20
    for (state, pair), case in zip(calls, fixture, strict=True):
        assert state is case["state"]
        assert_label_free(state)
        assert set(pair) == set(research.ARMS)


async def test_both_retry_layers_disabled_and_failures_consume_budget(monkeypatch):
    calls = []

    class FailingClient:
        def __init__(self, **kwargs):
            assert kwargs["retry"].max_retries == 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def system_one(self, **kwargs):
            calls.append(kwargs)
            raise ssl.SSLError("sensitive error text")

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FailingClient)
    probe = research.Probe("offline-test")
    for case in research.cases():
        with pytest.raises(ssl.SSLError):
            await probe.check(case["state"])
    with pytest.raises(RuntimeError, match="budget"):
        await probe.check({})
    assert len(calls) == probe.attempts == 20
    assert probe.metrics.requests == 0


@pytest.mark.parametrize("nouls", [None, [], {}, {"old": SimpleNamespace(noul=float("nan"))}])
async def test_malformed_response_container_is_not_an_answer(monkeypatch, nouls):
    async def transport(self, **kwargs):
        return SimpleNamespace(nouls=nouls, usage=None)

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    result = await research.Probe("offline-test").check(next(research.cases())["state"])
    assert all(not a["valid"] and not a["accept"] for a in result["answers"].values())
    assert result["model"] is None and result["usage"]["input_tokens"] is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, asyncio.CancelledError])
async def test_interruption_leaves_reserved_pending_request(tmp_path, monkeypatch, interruption):
    output = tmp_path / "interrupted"

    async def transport(self, **kwargs):
        stored = json.loads((output / "report.json").read_text())
        assert stored["attempts_reserved"] == 1
        assert stored["cases"][0]["status"] == "pending"
        assert stored["cases"][0]["questions"] and stored["cases"][0]["state"]
        raise interruption

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    with pytest.raises(interruption):
        await research.trial(output, tmp_path / "unused")
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "running" and not report["passed"]
    assert report["attempts_reserved"] == 1 and report["planned_cases"] == 20
    assert report["cases"][0]["status"] == "pending"


async def test_errors_type_only_and_never_count_as_correct_negatives(tmp_path, monkeypatch):
    async def transport(self, **kwargs):
        raise OSError("never persist this credential or server error")

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    output = tmp_path / "failed"
    await research.trial(output, tmp_path / "unused")
    encoded = (output / "report.json").read_text()
    assert "never persist" not in encoded
    report = json.loads(encoded)
    assert report["status"] == "complete" and not report["passed"]
    assert report["attempts"] == report["attempts_reserved"] == len(report["cases"]) == 20
    assert report["successful_requests"] == 0
    assert all(row["error_type"] == "OSError" and row["seconds"] >= 0 for row in report["cases"])
    for arm in research.ARMS:
        assert report["summary"][arm]["denominator"] == report["summary"][arm]["errors"] == 20
        assert report["summary"][arm]["exact"] == 0
        assert report["summary"][arm]["false_support"] == 0
        assert report["summary"][arm]["false_refusal"] == 0
        assert report["summary"][arm]["probability_unknown"] == 0
        assert report["summary"][arm]["invalid_answers"] == 0


async def test_successful_report_is_reproducible_paired_and_exclusive(tmp_path, monkeypatch):
    calls = []
    fixture = list(research.cases())

    async def transport(self, *, state, questions, stage):
        case = fixture[len(calls)]
        calls.append(state)
        return response(.9 if case["reference_answer"] == "yes" else .1,
                        .9 if case["expected_accept"] else .1)

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    output = tmp_path / "complete"
    await research.trial(output, tmp_path / "unused")
    original = (output / "report.json").read_bytes()
    report = json.loads(original)
    assert report["dataset_sha256"] == research.digest(fixture)
    for key in ("source_sha256", "production_adapter_sha256", "questions_sha256"):
        assert len(report[key]) == 64
    assert report["status"] == "complete" and report["passed"]
    assert report["gate"] == research.GATE
    assert not report["external_delivery"] and report["max_retries"] == 0
    assert report["thresholds"] == {"supported_gte": .70, "not_supported_lte": .30}
    assert report["input_tokens"] == 20 * 41 and report["output_tokens"] == 20 * 7
    assert report["summary"]["candidate"]["exact"] == 20
    assert report["summary"]["candidate"]["passed"]
    assert report["summary"]["old"]["exact"] == 15
    assert not report["summary"]["old"]["passed"]
    assert report["summary"]["old"]["false_refusal"] == 4
    assert report["summary"]["candidate"]["false_refusal"] == 0
    assert report["summary"]["candidate"]["false_support"] == 0
    assert report["summary"]["candidate_only_correct"] == 5
    assert report["summary"]["old_only_correct"] == 0
    for row in report["cases"]:
        assert row["status"] == "complete" and row["seconds"] >= 0
        assert row["response"]["model"] == "offline-contract"
        assert row["questions"] == JevJudger._question_budget_payload(research.questions(row["state"]["insight_card"]["questions"][0]))
    assert report["questions_sha256"] == research.digest([row["questions"] for row in report["cases"]])
    with pytest.raises(FileExistsError):
        await research.trial(output, tmp_path / "unused")
    assert (output / "report.json").read_bytes() == original and len(calls) == 20


def test_summary_separates_false_support_refusal_uncertainty_and_invalid():
    fixture = list(research.cases())
    known_no = next(c for c in fixture if c["variant"] == "answer_no")
    missing = next(c for c in fixture if c["variant"] == "missing")
    rows = []
    for case, value in ((known_no, .1), (missing, .9), (missing, .5), (known_no, .5), (known_no, None)):
        answers = {arm: research.decode(SimpleNamespace(noul=value)) for arm in research.ARMS}
        rows.append({
            **case, "status": "complete", "response": {"answers": answers},
            "comparison": research.compare(answers, case),
        })
    rows.append({**missing, "status": "error", "error_type": "OSError"})
    rows.append({**missing, "status": "pending"})
    summary = research.summarize(rows, 20)
    for arm in research.ARMS:
        assert summary[arm]["false_support"] == 1
        assert summary[arm]["false_refusal"] == 1
        assert summary[arm]["probability_unknown"] == 2
        assert summary[arm]["invalid_answers"] == 1
        assert summary[arm]["errors"] == 1
        assert summary[arm]["exact"] == 0 and not summary[arm]["passed"]


async def test_candidate_unknown_fails_gate_even_when_old_is_perfect(tmp_path, monkeypatch):
    fixture = list(research.cases())

    async def transport(self, **kwargs):
        case = fixture[self.attempts - 1]
        correct = .9 if case["expected_accept"] else .1
        return response(correct, .5 if self.attempts == 1 else correct)

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    output = tmp_path / "candidate-unknown"
    await research.trial(output, tmp_path / "unused")
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "complete" and not report["passed"]
    assert report["summary"]["old"]["passed"]
    assert report["summary"]["candidate"]["exact"] == 19
    assert report["summary"]["candidate"]["probability_unknown"] == 1
    assert report["summary"]["candidate"]["false_support"] == 0
    assert not report["summary"]["candidate"]["passed"]


async def test_oversized_fixture_rejected_before_key_or_dispatch(tmp_path, monkeypatch):
    fixture = list(research.cases())
    monkeypatch.setattr(research, "cases", lambda: fixture + [fixture[0]])

    def forbidden(_):
        raise AssertionError("Must reject before accessing credentials")

    monkeypatch.setattr(research, "load_api_key", forbidden)
    with pytest.raises(ValueError, match="budget"):
        await research.trial(tmp_path / "oversized", tmp_path / "unused")
    assert not (tmp_path / "oversized").exists()

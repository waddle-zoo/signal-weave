"""Offline scoring/accounting checks for the report-only development cohort."""

import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from evaluations import reviewed_setup_report_trial as trial
from evaluations.bootstrap_agent_trial import Audit
from evaluations.bootstrap_scenarios import public_episode
from signalweave.models import SourceRef
from tests.test_card_revision_mcp import reviewed_card


def _response(inputs=100, cached=30, output=10):
    return {"kind": "api.response", "provider": "openai", "usage": {
        "input_tokens": inputs, "input_tokens_details": {"cached_tokens": cached}, "output_tokens": output,
    }}


def test_both_arms_get_same_accepted_policy_and_owner_context_without_labels():
    public = public_episode(trial.clarified_development_scenario())
    card = reviewed_card()
    context = trial.common_context(public, card)
    assert context == {"accepted_policy": card.execution_payload(),
                       "owner_answers": public["owner_answers"], "glossary": public["glossary"]}
    assert not {"private", "periods", "snapshots", "labels"} & context.keys()


def test_usage_keeps_onboarding_costs_and_never_counts_unknown_current_as_zero():
    onboarding = {"input_tokens": 500, "cached_input_tokens": 100,
                  "uncached_input_tokens": 400, "output_tokens": 50, "responses": 6}
    events = [{"kind": "api.request", "provider": "openai"}, _response()]
    result = trial.summarize_usage(SimpleNamespace(events=events), onboarding)
    assert result["usage_known"]
    assert result["usage_including_accepted_onboarding"]["input_tokens"] == 600
    assert result["usage_including_accepted_onboarding"]["responses"] == 7
    events.extend([{"kind": "api.request", "provider": "openai"},
                   {"kind": "api.error", "provider": "openai"}])
    result = trial.summarize_usage(SimpleNamespace(events=events), onboarding)
    assert not result["usage_known"]
    assert result["usage"] == result["usage_including_accepted_onboarding"] == {"status": "unknown"}
    assert result["known_partial_usage"]["input_tokens"] == 100


def test_invocation_checks_fingerprint_and_between_invocation_budget(tmp_path):
    executable = tmp_path / "fake-executable"
    executable.write_bytes(b"offline fingerprint only")
    expected = hashlib.sha256(executable.read_bytes()).hexdigest()
    audit = Audit()
    trial.before_invocation(audit, trial.LIMITS, executable, expected)
    with pytest.raises(RuntimeError, match="executable changed"):
        trial.before_invocation(audit, trial.LIMITS, executable, "0" * 64)
    audit.events.extend([{"kind": "api.request", "provider": "openai"},
                         _response(inputs=trial.LIMITS["between_invocation_input_stop"], cached=0)])
    with pytest.raises(RuntimeError, match="stop reached"):
        trial.before_invocation(audit, trial.LIMITS, executable, expected)


def test_report_scoring_does_not_fabricate_owner_tool_calls():
    scenario = trial.clarified_development_scenario()
    period = scenario["public"]["periods"][0]
    label = scenario["private"]["periods"][period["period_id"]]
    refs = label["required_evidence_refs"]
    fact = label["required_numeric_facts"][0]
    expected = label["numeric_facts"][fact]
    submission = {"outcome": label["outcome"], "recipients": label["recipients"], "evidence_refs": refs,
                  "numeric_claims": [{"fact": fact, "value": expected["value"], "unit": expected["unit"],
                                      "evidence_refs": refs}], "summary": "Attainment is unchanged; volume alone is not adverse."}
    score = trial.score_report(scenario, period["period_id"], submission, set(refs))
    assert not score["owner_question_topic_coverage_complete"]
    assert not score["exact_including_owner_lookup"]
    assert "missing_owner_policy_lookup" in score["errors"]
    assert score["owner_context_supplied"]
    assert score["report_exact"]
    assert score["report_errors"] == []
    wrong = trial.score_report(scenario, period["period_id"], {**submission, "outcome": "notify"}, set(refs))
    assert not wrong["report_exact"]


@pytest.mark.parametrize("live", [False, True], ids=["zero-model-preflight", "fake-live-sequence"])
async def test_entire_runner_preserves_equal_context_and_uses_fresh_reports(monkeypatch, tmp_path, live):
    scenario = trial.clarified_development_scenario()
    card = reviewed_card().model_copy(update={"principal_tenant": scenario["scenario_id"]})
    source_public = public_episode(scenario)["catalog"][0]
    card.sources = [SourceRef(key="primary", adapter=source_public["adapter"],
                              resource=source_public["resource"], label=source_public["title"])]
    onboarding = {"input_tokens": 500, "cached_input_tokens": 100,
                  "uncached_input_tokens": 400, "output_tokens": 50, "responses": 6}
    accepted = {"scenario_sha256": hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest(),
                "usage": onboarding}
    binary = tmp_path / "native"
    codex = tmp_path / "codex"
    binary.write_bytes(b"offline-native")
    codex.write_bytes(b"offline-codex")
    (tmp_path / "unused-key").write_text("synthetic-offline-key-not-a-credential")
    original_report, original_trace = tmp_path / "accepted-report", tmp_path / "accepted-trace"
    original_report.write_text("immutable original fixture checked by loader tests")
    original_trace.write_text("immutable trace checked by loader tests")
    captured = []

    class Native:
        async def list_tools(self):
            return [SimpleNamespace(name=name, description="offline transport fixture",
                                    inputSchema={"type": "object"})
                    for name in ("get_insight_card", "evaluate_insight_card", "revise_insight_card")]

        async def call_tool(self, name, arguments):
            if name == "get_insight_card":
                return [], card.model_dump(mode="json")
            if name == "inspect_resource":
                return [], (await self.adapter.inspect(card.sources[0])).model_dump(mode="json")
            assert name == "evaluate_insight_card"
            await self.adapter.inspect(card.sources[0])
            return [], {"receipt": {"card_id": card.id, "card_version": card.version,
                                    "idempotency_key": arguments["idempotency_key"], "status": "delivery_disabled"},
                        "result": {"card_id": card.id}}

    @asynccontextmanager
    async def native_context(binary, key_file, public, adapter, audit, root, *, request_budget):
        native = Native()
        native.adapter = adapter
        yield native, "offline installed skill"

    async def pinned(path):
        return {"path": str(codex), "sha256": hashlib.sha256(codex.read_bytes()).hexdigest()}

    async def fake_episode(session, **kwargs):
        assert live, "preflight must never start an agent"
        captured.append(kwargs)
        audit = kwargs["audit"]
        audit.emit("api.request", provider="openai")
        audit.events.append(_response())
        key = kwargs["prompt_override"]["idempotency_key"]
        if session.native:
            await session.call("evaluate_insight_card", {"card_id": card.id, "idempotency_key": key})
        else:
            await session.adapter.inspect(card.sources[0])
        period_id = session.adapter.period_context["period_id"]
        label = scenario["private"]["periods"][period_id]
        await session.call("submit_analysis", {"outcome": label["outcome"], "recipients": label["recipients"],
                                               "evidence_refs": label["required_evidence_refs"], "summary": "Offline harness fixture only."})
        return {"status": "complete"}

    monkeypatch.setattr(trial, "load_reviewed_setup", lambda *args: (accepted, card))
    monkeypatch.setattr(trial, "restore_reviewed_card", lambda *args: None)
    monkeypatch.setattr(trial, "verify_binary", lambda path: {"binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
    monkeypatch.setattr(trial, "pinned_codex", pinned)
    monkeypatch.setattr(trial, "native_context", native_context)
    monkeypatch.setattr(trial, "codex_episode", fake_episode)
    args = SimpleNamespace(binary=str(binary), codex_executable=str(codex), key_file=str(tmp_path / "unused-key"),
                           accepted_report=str(original_report), accepted_trace=str(original_trace),
                           output=str(tmp_path / "output"), run=live)
    report = await trial.run(args)
    assert "failure" not in report
    assert report["completed"]
    assert report["agent_invocations_started"] == (6 if live else 0)
    assert report["provider_attempts"] == 0  # These are offline doubles, not live proof.
    assert report["usage_including_accepted_onboarding"]["responses"] == (12 if live else 6)
    if live:
        assert len(report["episodes"]) == 6
        assert all(e["approved_card_execution_verified"] for e in report["episodes"] if e["arm"] == "signalweave")
        assert all(captured[index]["prompt_override"]["accepted_context"] ==
                   captured[index + 1]["prompt_override"]["accepted_context"] for index in range(0, 6, 2))
        assert [entry["period_id"] for entry in report["episodes"][::2]] == [p["period_id"] for p in scenario["public"]["periods"]]

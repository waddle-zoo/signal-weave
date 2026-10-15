"""Offline scoring/accounting checks for the report-only development cohort."""

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime
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


def test_interpretation_repair_is_separate_treatment_only_budget_without_changing_paired_limits():
    original = dict(trial.LIMITS)
    protocol, limits, arms = trial.cohort_settings("interpretation-repair-v1")
    assert protocol == "handoff-interpretation-v1"
    assert arms == (True,)
    assert limits["agent_invocations"] == 3
    assert limits["jev_attempts"] == 3
    assert limits["between_invocation_input_stop"] == 300_000
    assert limits["between_invocation_uncached_stop"] == 90_000
    assert trial.LIMITS == original
    assert trial.cohort_settings("paired") == (trial.PROTOCOL, original, (False, True))
    with pytest.raises(ValueError):
        trial.cohort_settings("resume-v1")


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


def test_actual_tool_inventory_pins_shared_contracts_and_exposes_package_difference():
    common = {"name": "read_company_asset", "parameters": {"type": "object"}}
    native = {"name": "inspect_resource", "parameters": {"type": "object"}}
    report = {}
    trial.record_tool_inventory(report, "baseline", [common])
    trial.record_tool_inventory(report, "signalweave", [common, native])
    trial.record_tool_inventory(report, "signalweave", [native, common])
    assert report["treatment_additional_tools"] == ["inspect_resource"]
    with pytest.raises(ValueError, match="changed between periods"):
        trial.record_tool_inventory(report, "signalweave", [common])
    with pytest.raises(ValueError, match="differ between arms"):
        trial.record_tool_inventory(
            {"report_tool_inventories": {"baseline": report["report_tool_inventories"]["baseline"]}},
            "signalweave", [native],
        )
    with pytest.raises(ValueError, match="duplicate"):
        trial.record_tool_inventory({}, "baseline", [common, common])


@pytest.mark.parametrize("live,cohort,expected_reports", [
    (False, "paired", 0), (True, "paired", 6),
    (False, "calendar-paired-v1", 0), (True, "calendar-paired-v1", 6),
    (False, "grounded-reports-v2", 0), (True, "grounded-reports-v2", 6),
    (False, "human-readout-v1", 0), (True, "human-readout-v1", 6),
    (False, "interpretation-repair-v1", 0), (True, "interpretation-repair-v1", 3),
], ids=["paired-preflight", "paired-sequence", "calendar-preflight", "calendar-sequence",
        "grounded-preflight", "grounded-sequence",
        "human-preflight", "human-sequence",
        "repair-preflight", "repair-sequence"])
async def test_entire_runner_preserves_equal_context_and_uses_fresh_reports(monkeypatch, tmp_path, live, cohort, expected_reports):
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
    period_contexts = []

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
        period_contexts.append(dict(session.adapter.period_context))
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
        submission = {"outcome": label["outcome"], "recipients": label["recipients"],
                      "summary": "Offline harness fixture only."}
        if cohort == "human-readout-v1":
            schema = session.submission_schema()
            assert set(schema["properties"]) == {"outcome", "recipients", "summary"}
            await session.call("record_report", submission)
        else:
            await session.call("submit_analysis", {**submission, "evidence_refs": label["required_evidence_refs"]})
        return {"status": "complete"}

    monkeypatch.setattr(trial, "load_reviewed_setup", lambda *args: (accepted, card))
    monkeypatch.setattr(trial, "restore_reviewed_card", lambda *args: None)
    monkeypatch.setattr(trial, "verify_binary", lambda path: {"binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
    monkeypatch.setattr(trial, "pinned_codex", pinned)
    monkeypatch.setattr(trial, "native_context", native_context)
    monkeypatch.setattr(trial, "codex_episode", fake_episode)
    args = SimpleNamespace(binary=str(binary), codex_executable=str(codex), key_file=str(tmp_path / "unused-key"),
                           accepted_report=str(original_report), accepted_trace=str(original_trace),
                           output=str(tmp_path / "output"), run=live, cohort=cohort)
    report = await trial.run(args)
    assert "failure" not in report
    assert report["completed"]
    assert report["agent_invocations_started"] == expected_reports
    assert report["provider_attempts"] == 0  # These are offline doubles, not live proof.
    assert report["usage_including_accepted_onboarding"]["responses"] == expected_reports + 6
    if cohort == "human-readout-v1":
        assert report["treatment_additional_tools"] == ["evaluate_insight_card", "get_insight_card"]
        assert set(report["report_tool_inventories"]) == {"baseline", "signalweave"}
    if live:
        assert len(report["episodes"]) == expected_reports
        assert all(e["approved_card_execution_verified"] for e in report["episodes"] if e["arm"] == "signalweave")
        if cohort in {"paired", "calendar-paired-v1", "grounded-reports-v2", "human-readout-v1"}:
            assert all(captured[index]["prompt_override"]["accepted_context"] ==
                       captured[index + 1]["prompt_override"]["accepted_context"] for index in range(0, 6, 2))
            periods = report["episodes"][::2]
            if cohort in {"calendar-paired-v1", "grounded-reports-v2", "human-readout-v1"}:
                assert report["protocol"] == cohort
                assert report["cohort_clock_semantics"]["measurement_rebase"] == "one shared whole-week UTC offset"
                assert report["cohort_clock_semantics"]["source_capture_age"] == (
                    "preserved relative to each fixture period as_of"
                )
                assert all(period_contexts[index] == period_contexts[index + 1]
                           for index in range(0, 6, 2))
                assert all(datetime.fromisoformat(context["as_of"]) <=
                           datetime.fromisoformat(context["captured_at"]) for context in period_contexts)
                assert all("as_of is the measurement cutoff" in item["instructions_override"]
                           and "captured_at" in item["instructions_override"] for item in captured)
                assert all(datetime.fromisoformat(context["as_of"]).weekday() == 0
                           and datetime.fromisoformat(context["as_of"]).time() == datetime.min.time()
                           for context in period_contexts)
                if cohort == "grounded-reports-v2":
                    definitions = scenario["public"]["submission_contract"]
                    assert all(item["prompt_override"]["submission_contract"] == definitions for item in captured)
                elif cohort == "human-readout-v1":
                    assert report["planned_episode_count"] == 6
                    assert report["report_sink"] == "record_report"
                    assert all("structured_score" not in entry for entry in report["episodes"])
                    assert all(entry["routing_diagnostics"]["outcome_correct"] for entry in report["episodes"])
                    assert all("numeric_vocabulary" not in item["prompt_override"]
                               and "measurement_definitions" in item["prompt_override"] for item in captured)
                    assert all("submit_analysis" not in item["instructions_override"] for item in captured)
                else:
                    assert all("submission_contract" not in item["prompt_override"] for item in captured)
            else:
                assert "cohort_clock_semantics" not in report
        else:
            assert all(entry["arm"] == "signalweave" for entry in report["episodes"])
            assert report["protocol"] == "handoff-interpretation-v1"
            assert all("both arms" not in item.lower() and "versus the control" not in item.lower()
                       for item in report["limitations"])
            assert all("both arms" not in item["instructions_override"].lower() for item in captured)
            periods = report["episodes"]
        assert [entry["period_id"] for entry in periods] == [p["period_id"] for p in scenario["public"]["periods"]]
    if cohort in {"calendar-paired-v1", "grounded-reports-v2", "human-readout-v1"}:
        assert report["cohort_clock_semantics"]["measurement_rebase"] == "one shared whole-week UTC offset"
    else:
        assert "cohort_clock_semantics" not in report

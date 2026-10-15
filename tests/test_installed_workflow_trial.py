import copy
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import public_scenario
from evaluations.installed_northstar_cases import build_northstar
from evaluations.installed_workflow_trial import (
    SHARED_SOURCE_PRODUCT_TOOLS,
    BaseExceptionGroup,
    InstalledSession,
    _company_failure_status,
    _invalid_preflight_report,
    _is_binary_identity_failure,
    _root_cause_summary,
    _verify_binary_stage,
    assert_default_agent_profile,
    bind_examples,
    bundle_visible_refs,
    expected_human_clarification,
    expected_human_clarification_record,
    monitoring_instructions,
    onboarding_instructions,
    score_native,
)
from signalweave.mcp_server import AGENT_PROFILE_TOOLS
from tests.test_northstar_growth_history_trial import _write_seed_dir


def test_offline_cli_freezes_selected_transfer_seed_without_inference(tmp_path, monkeypatch):
    from evaluations.installed_transfer_cases import build_transfers
    from evaluations.installed_workflow_trial import main

    binary = tmp_path / "offline-binary"
    binary.write_text("hash-only; not executed without --live")
    metadata = {"source_sha256": "synthetic-source", "binary_sha256": "synthetic-binary",
                "version": "offline-test", "git_commit": "test", "dirty": True, "frozen": False}
    monkeypatch.setattr("evaluations.installed_workflow_trial.verify_binary", lambda _: metadata)
    output = tmp_path / "frozen"
    monkeypatch.setattr(sys, "argv", ["trial", "--suite", "transfer", "--seed", "20261007",
                                   "--company-index", "3", "--binary", str(binary),
                                   "--output", str(output),
                                   "--author-model", "gpt-6-luna", "--author-effort", "xhigh",
                                   "--recurring-agent-model", "gpt-6-luna",
                                   "--recurring-agent-effort", "xhigh",
                                   "--reviewer-model", "gpt-6-luna", "--reviewer-effort", "xhigh"])
    main()
    protocol = json.loads((output / "protocol.json").read_text())
    assert protocol["fixture_seed"] == 20261007
    assert protocol["companies"] == 1 and protocol["monitoring_cases"] == 3
    assert protocol["live"] is False
    assert protocol["binary_build"] == metadata
    assert json.loads((output / "preflight.json").read_text())["binary_build"] == metadata
    assert protocol["models"] == {
        "author": {"model": "gpt-6-luna", "effort": "xhigh"},
        "recurring_agent": {"model": "gpt-6-luna", "effort": "xhigh"},
        "reviewer": {"model": "gpt-6-luna", "effort": "xhigh"},
    }
    assert protocol["comparison"] == "paired_final_business_outcome_runtime"
    assert protocol["monitoring_limits_per_arm"] == {
        "max_turns": 60, "max_tool_calls": 100, "timeout_seconds": 360,
    }
    assert protocol["mcp_profile"] == "agent"
    assert json.loads((output / "frozen-scenarios.json").read_text()) == [build_transfers(20261007)[3]]


def test_binary_identity_change_is_rejected(monkeypatch):
    monkeypatch.setattr("evaluations.installed_workflow_trial.verify_binary",
                        lambda _: {"source_sha256": "changed"})
    with pytest.raises(RuntimeError, match="changed after preflight"):
        _verify_binary_stage(Path("synthetic-binary"), {"source_sha256": "original"}, [], "setup")


@pytest.fixture
def card():
    return {"id": "card-test", "version": 1, "compiled_plan": {"card_id": "card-test"},
            "sources": [{"key": "alias", "adapter": "company_mcp", "resource": "r"}],
            "delivery_methods": [{"key": "owner", "destination": "slack://simulation-owner"}]}


def example():
    return {"id": "history", "expected_outcome": "notify",
            "expected_delivery_destinations": {"original-route-key": "slack://simulation-owner"},
            "required_evidence_refs": ["company_mcp|r"],
            "expected_retrieval_refs": ["company_mcp|r"],
            "resources": [{"adapter": "company_mcp", "resource": "r", "source_key": "r",
                           "title": "Resource", "source_url": None,
                           "contract": {"freshness_sla_hours": None},
                           "captured_at": "2026-01-01T00:00:00Z",
                           "observations": [{"source_key": "r", "metric": "revenue", "current": 8}],
                           "evidence": [{"source_key": "r", "statement": "Observed"}]}]}


def test_examples_project_only_identity_without_mutating_owner_inputs(card):
    original = example()
    saved = copy.deepcopy(original)
    result, = bind_examples([original], card)
    assert original == saved
    assert result["resources"][0]["observations"] == [
        {"source_key": "alias", "metric": "revenue", "current": 8}
    ]
    assert result["expected_delivery_destinations"] == {"owner": "slack://simulation-owner"}
    assert result["required_evidence_source_keys"] == ["alias"]
    assert result["expected_outcome"] == "notify"


def test_bundle_visibility_counts_only_sources_present_in_evidence_or_provenance():
    card = {"sources": [
        {"key": "primary", "adapter": "company_mcp", "resource": "sales"},
        {"key": "quality", "adapter": "company_mcp", "resource": "quality"},
        {"key": "unused", "adapter": "company_mcp", "resource": "catalog-only"},
    ]}
    evaluation = {
        "result": {"evidence": [{"source_key": "primary"}], "observations": []},
        "report": {"provenance": [{"source_key": "quality"},
                                    {"source_key": "external", "query_refs": ["evil|ref"]}]},
    }
    assert bundle_visible_refs(evaluation, card) == {
        "company_mcp|sales", "company_mcp|quality",
    }


def test_cannot_silently_drop_needed_evidence_or_owner_route(card):
    missing = copy.deepcopy(card)
    missing["sources"] = []
    with pytest.raises(ValueError, match="omits"):
        bind_examples([example()], missing)
    missing = copy.deepcopy(card)
    missing["delivery_methods"] = []
    with pytest.raises(ValueError, match="destination"):
        bind_examples([example()], missing)


def native_output(card):
    report = {"card_id": card["id"], "outcome": "notify"}
    return {"card": {k: copy.deepcopy(v) for k, v in card.items() if k != "compiled_plan"},
            "plan": copy.deepcopy(card["compiled_plan"]), "report": report,
            "receipt": {"card_id": card["id"], "card_version": card["version"],
                        "delivery_enabled": False, "delivery_mode": "shadow", "status": "delivery_disabled",
                        "outcome": "notify", "delivery_method_keys": ["owner"]},
            "result": {"card_id": card["id"], "outcome": "notify", "report": copy.deepcopy(report),
                       "evidence": [{"source_key": "alias"}], "delivery_methods": card["delivery_methods"]},
            "passed": True}


def test_native_scoring_recomputes_result_not_flags(card):
    label = {"outcome": "notify", "recipients": ["owner"], "required_evidence_refs": ["company_mcp|r"]}
    destinations = [{"key": "owner", "destination": "slack://simulation-owner"}]
    output = native_output(card)
    assert score_native(output, card, label, destinations)["exact"]
    output["result"]["outcome"] = "ignore"
    assert not score_native(output, card, label, destinations)["exact"]
    output["result"]["outcome"] = "notify"
    output["result"]["evidence"] = []
    assert not score_native(output, card, label, destinations)["exact"]


@pytest.mark.parametrize("section,field,value", [
    ("receipt", "delivery_enabled", True), ("receipt", "status", "delivered"),
    ("result", "card_id", "another-card"), ("report", "outcome", "ignore"),
    ("plan", "card_id", "mutated"), ("receipt", "card_version", 2),
])
def test_native_scoring_rejects_wrong_identity_delivery_and_plan(card, section, field, value):
    output = native_output(card)
    output[section][field] = value
    label = {"outcome": "notify", "recipients": ["owner"], "required_evidence_refs": ["company_mcp|r"]}
    assert not score_native(output, card, label,
                            [{"key": "owner", "destination": "slack://simulation-owner"}])["exact"]


async def test_native_scorer_uses_actual_mcp_serialization_contract(tmp_path):
    # Offline double controls the model only. The real MCP creates the response;
    # this is a serialization test, not semantic-correctness evidence.
    from test_mcp_acceptance import setup, tool
    server, card_id, _ = await setup(tmp_path)
    await tool(server, "approve_insight_card")(card_id)
    card = tool(server, "get_insight_card")(card_id)
    output = await tool(server, "evaluate_insight_card")(card_id, idempotency_key="shape-test")
    assert "compiled_plan" not in output["card"]
    assert output["plan"] == card["compiled_plan"]
    label = {"outcome": output["result"]["outcome"], "recipients": ["owner"],
             "required_evidence_refs": ["superset|dashboard:7"]}
    assert score_native(output, card, label, [{"key": "owner", "destination": "sink:opaque"}])["exact"]


def test_empty_failure_never_counts_as_correct_missing_data(card):
    label = {"outcome": "insufficient_data", "recipients": [], "required_evidence_refs": []}
    assert not score_native({}, card, label, [])["exact"]


def test_unknown_recipient_rejected(card):
    label = {"outcome": "notify", "recipients": ["owner"], "required_evidence_refs": ["company_mcp|r"]}
    output = {"result": {"outcome": "notify", "evidence": [{"source_key": "alias"}],
                         "delivery_methods": [{"destination": "slack://unapproved"}]}}
    assert not score_native(output, card, label, [{"key": "owner", "destination": "slack://simulation-owner"}])["routes_correct"]


def test_onboarding_instructions_use_minimal_default_agent_flow():
    class Server:
        instructions = "Product-native instructions"
    text = onboarding_instructions(Server())
    for tool in ("get_signalweave_guide", "search_catalog", "inspect_resource",
                 "onboard_insight_card", "review_insight_card", "sign-off",
                 "request_synthetic_owner_approval", "approve_insight_card",
                 "evaluate_insight_card"):
        assert tool in text
    assert "exact selected_sources refs" in text
    assert "numeric_conditions are optional" in text
    assert "exact comparison key appears in the inspected source's analytical_comparisons" in text
    assert "Never invent a comparison key from an observation or metric name" in text
    assert "retain the owner's complete rule in decision_guidance" in text
    assert "A pending rule pauses recurring automation and card approval, not useful current analysis" in text
    assert "Do not imply distinct source populations are one cohort" in text
    assert "Before pausing for an unresolved alert rule" in text
    assert "exactly once per monitoring period" in text
    for hidden_tool in ("simulate_insight_card", "preview_investigation_report",
                        "evaluate_card_workflow", "get_owner_examples", "workflow_report_id"):
        assert hidden_tool not in text
    assert "Product-native instructions" in text


async def test_default_profile_is_verified_and_not_expanded():
    server = SimpleNamespace(list_tools=AsyncMock(return_value=[
        SimpleNamespace(name=name) for name in sorted(AGENT_PROFILE_TOOLS)
    ]))
    assert await assert_default_agent_profile(server) == sorted(AGENT_PROFILE_TOOLS)
    server.list_tools.return_value.append(SimpleNamespace(name="simulate_insight_card"))
    with pytest.raises(RuntimeError, match="default agent profile"):
        await assert_default_agent_profile(server)


async def test_baseline_and_treatment_get_identical_default_profile_sources():
    public = {"scenario_id": "test", "company": "Test", "brief": "brief", "glossary": {},
              "owner_topics": [], "destinations": [], "numeric_vocabulary": [],
              "submission_contract": {}, "owner_answers": {}}
    server = SimpleNamespace(list_tools=AsyncMock(return_value=[
        SimpleNamespace(name=name, description=f"{name} description",
                        inputSchema={"type": "object"})
        for name in sorted(AGENT_PROFILE_TOOLS)
    ]))
    adapter = SimpleNamespace(name="company_mcp")
    treatment = InstalledSession(public, adapter, server, True)
    baseline = InstalledSession(public, adapter, server, False)
    treatment.phase = baseline.phase = "monitoring"
    treatment_specs = {item["name"]: item for item in await treatment.specs()}
    baseline_specs = {item["name"]: item for item in await baseline.specs()}
    assert SHARED_SOURCE_PRODUCT_TOOLS <= treatment_specs.keys()
    assert SHARED_SOURCE_PRODUCT_TOOLS <= baseline_specs.keys()
    assert all(treatment_specs[name] == baseline_specs[name]
               for name in SHARED_SOURCE_PRODUCT_TOOLS)
    assert "evaluate_insight_card" not in treatment_specs
    assert "evaluate_insight_card" not in baseline_specs


async def test_run_trial_pairs_final_reports_and_propagates_model_settings(tmp_path, monkeypatch):
    from evaluations.installed_transfer_cases import DEFAULT_SEED, build_transfers
    from evaluations.installed_workflow_trial import run_trial

    scenario = copy.deepcopy(build_transfers(DEFAULT_SEED)[0])
    scenario["public"]["periods"] = scenario["public"]["periods"][:1]
    kept_period = scenario["public"]["periods"][0]["period_id"]
    scenario["private"]["periods"] = {kept_period: scenario["private"]["periods"][kept_period]}
    binary_identity = {"source_sha256": "synthetic-source", "binary_sha256": "synthetic-binary",
                       "version": "offline-test", "git_commit": "test", "dirty": True, "frozen": False}
    verify_calls = []

    def verify(_binary):
        verify_calls.append("verify")
        return binary_identity

    monkeypatch.setattr("evaluations.installed_workflow_trial.verify_binary", verify)
    card_data = {
        "id": "paired-card", "version": 1, "status": "approved",
        "compiled_plan": {"card_id": "paired-card"},
        "sources": [{"key": "primary", "adapter": "company_mcp", "resource": "primary"}],
        "delivery_methods": [{"key": "route", "destination": "slack://owner"}],
    }

    class Server:
        instructions = "synthetic default-agent instructions"

        def __init__(self):
            self.calls = []

        async def list_tools(self):
            return [SimpleNamespace(name=name, description=name, inputSchema={"type": "object"})
                    for name in sorted(AGENT_PROFILE_TOOLS)]

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            if name == "get_insight_card":
                return [], card_data
            if name == "evaluate_insight_card":
                return [], {"card": {k: v for k, v in card_data.items() if k != "compiled_plan"},
                            "plan": card_data["compiled_plan"], "report": {}, "receipt": {}, "result": {}}
            raise AssertionError(name)

    server = Server()

    @asynccontextmanager
    async def installed_server(**_kwargs):
        yield server

    monkeypatch.setattr("evaluations.installed_trial_transport.installed_server", installed_server)
    invocations = []

    async def fake_episode(session, **kwargs):
        invocations.append({"phase": session.phase, "episode": kwargs["audit"].episode,
                            "model": kwargs["model"], "effort": kwargs["effort"],
                            "tools": {tool["name"] for tool in await session.specs()},
                            "bundle": kwargs.get("bundle")})
        if session.phase == "onboarding":
            session.setup_complete = True
            session.card_id = card_data["id"]
            session.notes = "synthetic shared policy notes"
            session.owner_topics = set(session.public["owner_topics"])
            session.data_signoff = {"status": "ready"}
            return {"status": "complete", "error": None, "exit_code": 0,
                    "foreign_tools": [], "model": kwargs["model"], "effort": kwargs["effort"]}
        session.submission = {}
        return {"status": "complete", "error": None, "exit_code": 0,
                "foreign_tools": [], "model": kwargs["model"], "effort": kwargs["effort"]}

    monkeypatch.setattr("evaluations.installed_workflow_trial.codex_episode", fake_episode)
    key_file = tmp_path / "synthetic-key"
    key_file.write_text("synthetic-secret")
    report = await run_trial(
        [scenario], binary=Path("synthetic-binary"), key_file=key_file,
        output=tmp_path / "paired-run", live=True, jev_budget=1,
        author_model="gpt-6-luna", author_effort="xhigh",
        recurring_agent_model="gpt-6-luna", recurring_agent_effort="xhigh",
        reviewer_model="gpt-6-luna", reviewer_effort="xhigh",
    )

    assert len(verify_calls) == 3  # preflight, before setup, before report certification
    assert [call["phase"] for call in invocations] == ["onboarding", "monitoring", "monitoring"]
    assert all((call["model"], call["effort"]) == ("gpt-6-luna", "xhigh")
               for call in invocations)
    baseline, treatment = sorted(invocations[1:], key=lambda call: "baseline" not in call["episode"])
    assert SHARED_SOURCE_PRODUCT_TOOLS <= baseline["tools"]
    assert SHARED_SOURCE_PRODUCT_TOOLS <= treatment["tools"]
    assert "evaluate_insight_card" not in treatment["tools"]
    assert "evaluate_insight_card" not in baseline["tools"]
    assert baseline["bundle"] is None and treatment["bundle"] is not None
    assert sum(name == "evaluate_insight_card" for name, _ in server.calls) == 1
    row, = report["companies"][0]["periods"]
    assert set(row["outcome_comparison"]) >= {"baseline", "treatment", "treatment_minus_baseline_exact"}
    assert row["outcome_comparison"]["same_model_effort"] is True
    assert row["outcome_comparison"]["same_card_digest"] is True
    assert row["outcome_comparison"]["same_notes_digest"] is True
    assert row["outcome_comparison"]["baseline"]["observed"] is False
    assert row["outcome_comparison"]["baseline"]["exact"] is None
    assert row["outcome_comparison"]["treatment"]["observed"] is False
    assert row["outcome_comparison"]["treatment"]["exact"] is None
    assert row["outcome_comparison"]["treatment_minus_baseline_exact"] is None
    assert report["summary"]["intended"] == 1
    assert report["summary"]["observed_business_cases"] == 0
    assert report["summary"]["not_run_business_cases"] == 1
    assert report["summary"]["agent_accuracy"] is None


def test_expected_human_clarification_is_a_pause_not_setup_success():
    expected = {"state": "needs_human_clarification", "unknown_owner_topics": ["materiality"]}
    episode = {"status": "failed", "error": "no_structured_submission",
               "final_message": "Human decision needed: define materiality.", "foreign_tools": []}
    assert expected_human_clarification(expected, {"materiality"}, episode)
    assert not expected_human_clarification(expected, set(), episode)
    assert not expected_human_clarification(
        expected, {"materiality"}, {**episode, "foreign_tools": ["shell"]}
    )
    assert not expected_human_clarification(
        expected, {"materiality"}, {**episode, "status": "complete"}
    )


def test_nested_exception_groups_are_flattened_redacted_and_bounded():
    error = BaseExceptionGroup(
        "TaskGroup",
        [
            ValueError("provider rejected key super-secret-token"),
            BaseExceptionGroup("nested", [OSError("connection reset")]),
        ],
    )
    summary = _root_cause_summary(error, Audit(secrets=("super-secret-token",)))
    assert [(item["type"], item["message"]) for item in summary] == [
        ("ValueError", "provider rejected key [REDACTED]"),
        ("OSError", "connection reset"),
    ]
    bounded = _root_cause_summary(
        BaseExceptionGroup("many", [ValueError(str(index)) for index in range(8)]),
        Audit(), max_causes=2,
    )
    assert [item["message"] for item in bounded] == [
        "0", "1", "Additional exception causes omitted.",
    ]


def test_binary_preflight_failure_retains_intended_denominator_without_accuracy(tmp_path):
    scenarios = [{"public": {"periods": [{}, {}, {}]}}]
    report = _invalid_preflight_report(
        scenarios=scenarios, binary=Path("stale-binary"), output=tmp_path / "invalid",
        model_settings={"author": {"model": "gpt-6-luna", "effort": "xhigh"}},
        fixture_seed=None,
        error=ValueError("Binary is stale: source fingerprint mismatch"),
    )
    assert report["status"] == "invalid_preflight"
    assert report["preflight"]["agent_calls"] == 0
    assert report["business_accuracy_status"] == "not_observed"
    assert report["summary"]["intended"] == 3
    assert report["summary"]["not_run_business_cases"] == 3
    assert report["summary"]["agent_accuracy"] is None
    assert _is_binary_identity_failure(report["preflight"]["root_causes"])
    assert _company_failure_status([], agent_calls=0) == "not_run"
    assert _company_failure_status(
        report["preflight"]["root_causes"], agent_calls=0
    ) == "invalid_preflight"


def test_expected_hil_pause_preserves_current_message_and_defers_future_label_scoring():
    expected = {"state": "needs_human_clarification", "unknown_owner_topics": ["materiality"]}
    episode = {
        "status": "failed", "error": "no_structured_submission",
        "final_message": "Current: sales fell 12% in the inspected monthly dashboard. Ask owner how to route it.",
        "foreign_tools": [],
    }
    record = expected_human_clarification_record(
        expected, {"materiality"}, episode,
        inspected_refs={"company_mcp|northstar-dashboard"}, future_period_count=42,
    )
    assert record["onboarding_state"] == "needs_human_clarification"
    assert record["preapproval_current_report"] == {
        "final_message": episode["final_message"],
        "inspected_source_refs": ["company_mcp|northstar-dashboard"],
        "scoring": "not_independently_scored",
    }
    assert record["future_monitoring"] == {
        "state": "not_run_pending_owner_answer", "periods_not_scored": 42,
    }
    assert "outcome" not in record and "expected_outcome" not in record


def test_monitoring_instructions_make_caller_agent_responsible_for_final_report():
    class Server:
        instructions = "Product-native instructions"
    text = monitoring_instructions(Server())
    assert "independent final business report" in text
    assert "Do not assume either arm is correct" in text
    assert "Do not turn blank/undeclared optional metadata" in text
    assert "instead of adding a new company-wide completeness prerequisite" in text
    assert "Use the calculate tool for each required arithmetic expression" in text
    assert "verify segment contributions sum to" in text
    assert "leave canonical metric numeric_claims empty" in text
    assert "business.destinations[].key" in text
    assert "Never submit the card-local delivery_methods[].key" in text
    assert "submit_analysis records a proposed report only" in text
    assert "source-supported numeric facts from the provided vocabulary" in text
    assert "do not choose ignore or insufficient_data" in text


def test_session_public_projection_excludes_future_measurements_without_server_init(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"), smoke=True)
    public = public_scenario(scenario)
    public["periods"][0]["snapshots"][next(iter(public["periods"][0]["snapshots"]))]["metadata"][
        "future_canary"
    ] = "must-not-reach-author"
    audit = Audit(tmp_path / "audit.jsonl", ("test-secret",))
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    session = InstalledSession(public, adapter, None, True)

    assert not {"periods", "snapshots", "catalog", "owner_answers"} & session.public.keys()
    assert "must-not-reach-author" not in str(session.public)

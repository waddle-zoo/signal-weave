"""Offline adversarial contract tests for clarified setup and monitoring episodes."""

import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from evaluations import domain_context_onboarding_trial as onboarding_trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import build_scenarios, public_episode
from evaluations.domain_context_onboarding_trial import (
    Episode,
    RecurringEpisode,
    clarified_development_scenario,
    pinned_codex,
    public_brief,
)

SEED = 20261015
POPULATION_FACT = "all parcels due, including overdue undelivered parcels"
MONITORING_NOTES = "Use the reviewed dispatch definition and report only supported evidence."
APPROVED_CARD_ID = "approved-card"
RUN_KEY = "offline-monitor-period-1"


class FakeNativeBoundary:
    """A local stand-in for MCP calls; it never starts the native server."""

    def __init__(self, *, result=None, error=None):
        self.result = result if result is not None else {}
        self.error = error
        names = (
            "get_signalweave_guide",
            "list_insight_cards",
            "get_insight_card",
            "evaluate_insight_card",
            "get_decision_receipt",
            "approve_insight_card",
            "review_domain_context",
            "record_insight_card_correction",
        )
        self.tools = [
            SimpleNamespace(
                name=name,
                description="Offline fake native tool.",
                inputSchema={"type": "object", "properties": {}},
            )
            for name in names
        ]
        self.calls = []

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append({"name": name, "arguments": deepcopy(arguments)})
        if self.error is not None:
            raise self.error
        if name != "evaluate_insight_card":
            raise AssertionError(f"unexpected fake native call: {name}")
        return None, self.result


def _workflow(
    *,
    native=None,
    notes=MONITORING_NOTES,
    approved_card_id=APPROVED_CARD_ID,
    run_key=RUN_KEY,
):
    scenario = clarified_development_scenario()
    public = public_episode(scenario)
    audit = Audit()
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    adapter.set_period(scenario["public"]["periods"][0], datetime.now(timezone.utc))
    return scenario, public, adapter, RecurringEpisode(
        public,
        adapter,
        native,
        notes=notes,
        approved_card_id=approved_card_id if native else None,
        run_key=run_key if native else None,
    )


def test_clarified_fixture_is_the_new_company_one_dev_seed_without_mutating_builder_output():
    original = build_scenarios(seed=SEED, split="dev", connector_profile=True)
    original_copy = deepcopy(original)

    scenario = clarified_development_scenario()

    assert scenario["scenario_id"] == original[1]["scenario_id"]
    assert scenario["public"]["company"] == "Pine Courier"
    assert original == original_copy
    assert build_scenarios(seed=SEED, split="dev", connector_profile=True) == original
    assert "source_scope" not in original[1]["public"]["owner_topics"]
    assert "population" not in original[1]["public"]["glossary"]


async def test_population_fact_is_equally_retrievable_from_glossary_and_owner_answer():
    scenario = clarified_development_scenario()
    public = public_episode(scenario)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    setup = Episode(public, adapter)

    glossary = await setup.call("read_company_glossary", {})
    owner = await setup.call("ask_owner", {"topic": "source_scope"})

    assert "source_scope" in public["owner_topics"]
    assert glossary["definitions"]["population"] == owner["answer"]
    assert POPULATION_FACT in glossary["definitions"]["population"]
    assert POPULATION_FACT in owner["answer"]


def test_agent_opening_has_no_private_labels_or_future_period_payloads():
    scenario = clarified_development_scenario()
    future_period_id = scenario["public"]["periods"][0]["period_id"]
    sentinel = "PRIVATE_FUTURE_LABEL_SENTINEL_20261015"
    scenario["private"]["periods"][future_period_id]["opening_probe"] = sentinel

    brief = public_brief(public_episode(scenario))

    assert set(brief) == {"scenario_id", "company", "brief", "owner_topics", "destinations"}
    assert not {
        "private", "glossary", "owner_answers", "period", "periods", "catalog",
        "numeric_vocabulary", "submission_contract",
    } & brief.keys()
    assert sentinel not in json.dumps(brief)
    assert future_period_id not in json.dumps(brief)


async def test_monitoring_is_a_fresh_phase_with_equal_read_notes_and_calculator_access():
    scenario, public, adapter, baseline = _workflow()
    native = FakeNativeBoundary()
    treatment = RecurringEpisode(public, adapter, native, notes=MONITORING_NOTES)

    assert Episode.phase == "onboarding"
    assert baseline.phase == treatment.phase == "monitoring"
    assert baseline is not treatment
    assert baseline.setup_complete is False and treatment.setup_complete is False

    baseline_tools = await baseline.specs()
    treatment_tools = await treatment.specs()
    baseline_names = {tool["name"] for tool in baseline_tools}
    treatment_names = {tool["name"] for tool in treatment_tools}
    setup_tools = {"ask_owner", "save_working_notes", "request_owner_approval", "finish_setup"}
    assert setup_tools.isdisjoint(baseline_names)
    assert setup_tools.isdisjoint(treatment_names)
    assert "calculate" in baseline_names & treatment_names
    assert "submit_analysis" in baseline_names & treatment_names

    outputs = []
    for episode in (baseline, treatment):
        catalog = await episode.call("list_company_assets", {})
        asset = catalog["assets"][0]
        source = await episode.call(
            "read_company_asset",
            {"ref": f"{asset['adapter']}|{asset['resource']}"},
        )
        glossary = await episode.call("read_company_glossary", {})
        notes = await episode.call("read_working_notes", {})
        calculation = await episode.call("calculate", {"expression": "2 + 3 * 4"})
        outputs.append((catalog, source, glossary, notes, calculation))

    assert outputs[0] == outputs[1]
    assert outputs[0][3] == {"id": "working", "notes": MONITORING_NOTES}
    assert outputs[0][4] == {"value": 14.0}
    assert native.calls == []


async def test_monitoring_rejects_owner_clarification_and_policy_writes():
    _, public, adapter, _ = _workflow()
    native = FakeNativeBoundary()
    episode = RecurringEpisode(public, adapter, native, notes=MONITORING_NOTES)
    attempts = (
        ("ask_owner", {"topic": "source_scope"}),
        ("save_working_notes", {"notes": "Replace the reviewed policy."}),
        ("request_owner_approval", {"kind": "notes", "id": "working", "summary": "Approve this."}),
        ("finish_setup", {"card_ids": [], "message": "Finish again.", "unresolved": []}),
        ("approve_insight_card", {"card_id": "card-1"}),
        ("review_domain_context", {"entry_id": "context-1", "action": "approve"}),
        ("record_insight_card_correction", {"card_id": "card-1", "correction": "Change policy."}),
    )

    for name, arguments in attempts:
        with pytest.raises(ValueError, match="analysis only|unavailable"):
            await episode.call(name, arguments)

    assert episode.owner_requests == []
    assert episode.notes == MONITORING_NOTES
    assert native.calls == []
    assert episode.native_calls == []


async def test_native_evaluation_is_passthrough_and_recorded_at_the_boundary():
    native_result = {
        "result": {
            "card_id": APPROVED_CARD_ID,
            "outcome": "investigate",
            "native_marker": [1, 2, 3],
        },
        "receipt": {
            "card_id": APPROVED_CARD_ID,
            "idempotency_key": RUN_KEY,
            "status": "delivery_disabled",
        },
    }
    native = FakeNativeBoundary(result=native_result)
    _, _, _, episode = _workflow(native=native)
    arguments = {"card_id": APPROVED_CARD_ID, "idempotency_key": RUN_KEY}

    result = await episode.call("evaluate_insight_card", arguments)

    assert result is native_result
    assert episode.evaluation_verified is True
    assert native.calls == [{"name": "evaluate_insight_card", "arguments": arguments}]
    assert episode.native_calls == [{
        "name": "evaluate_insight_card",
        "arguments": arguments,
        "result": native_result,
    }]


@pytest.mark.parametrize(
    ("arguments", "approved_card_id", "run_key"),
    [
        ({"card_id": "another-card", "idempotency_key": RUN_KEY}, APPROVED_CARD_ID, RUN_KEY),
        ({"card_id": APPROVED_CARD_ID, "idempotency_key": "another-run"}, APPROVED_CARD_ID, RUN_KEY),
        ({"card_id": APPROVED_CARD_ID, "idempotency_key": RUN_KEY}, None, RUN_KEY),
        ({"card_id": APPROVED_CARD_ID, "idempotency_key": RUN_KEY}, APPROVED_CARD_ID, None),
    ],
)
async def test_native_evaluation_rejects_wrong_or_missing_identity_without_dispatch(
    arguments, approved_card_id, run_key
):
    native = FakeNativeBoundary(result={})
    _, _, _, episode = _workflow(
        native=native,
        approved_card_id=approved_card_id,
        run_key=run_key,
    )

    with pytest.raises(ValueError, match="exact reviewed card"):
        await episode.call("evaluate_insight_card", arguments)

    assert native.calls == []
    assert episode.native_calls == []
    assert episode.evaluation_verified is False


def _native_response(*, receipt_card=APPROVED_CARD_ID, receipt_key=RUN_KEY,
                     status="delivery_disabled", result_card=APPROVED_CARD_ID):
    return {
        "result": {"card_id": result_card, "outcome": "investigate"},
        "receipt": {
            "card_id": receipt_card,
            "idempotency_key": receipt_key,
            "status": status,
        },
    }


@pytest.mark.parametrize(
    "native_result",
    [
        _native_response(receipt_card="different-card"),
        _native_response(receipt_key="different-run"),
        _native_response(status="deferred"),
        _native_response(result_card="different-card"),
    ],
    ids=["receipt-card-mismatch", "receipt-key-mismatch", "deferred", "result-card-mismatch"],
)
async def test_native_response_mismatch_or_deferment_is_passthrough_but_unverified(native_result):
    native = FakeNativeBoundary(result=native_result)
    _, _, _, episode = _workflow(native=native)
    arguments = {"card_id": APPROVED_CARD_ID, "idempotency_key": RUN_KEY}

    result = await episode.call("evaluate_insight_card", arguments)

    assert result is native_result
    assert episode.evaluation_verified is False
    assert native.calls == [{"name": "evaluate_insight_card", "arguments": arguments}]
    assert episode.native_calls == [{
        "name": "evaluate_insight_card",
        "arguments": arguments,
        "result": native_result,
    }]


async def test_native_evaluation_errors_propagate_without_fallback_or_recorded_success():
    native_error = RuntimeError("native evaluation failed at the adapter boundary")
    native = FakeNativeBoundary(error=native_error)
    _, _, _, episode = _workflow(native=native)

    with pytest.raises(RuntimeError) as raised:
        await episode.call(
            "evaluate_insight_card",
            {"card_id": APPROVED_CARD_ID, "idempotency_key": RUN_KEY},
        )

    assert raised.value is native_error
    assert native.calls == [{
        "name": "evaluate_insight_card",
        "arguments": {"card_id": APPROVED_CARD_ID, "idempotency_key": RUN_KEY},
    }]
    assert episode.native_calls == []


def _valid_submission(recipient="business-owner"):
    return {
        "outcome": "investigate",
        "recipients": [recipient],
        "evidence_refs": ["company_mcp|dispatch-export"],
        "numeric_claims": [{
            "fact": "parcels_due",
            "value": 12.5,
            "unit": "parcels",
            "evidence_refs": ["company_mcp|dispatch-export"],
        }],
        "claims": [{
            "claim_type": "observation",
            "evidence_refs": ["company_mcp|dispatch-export"],
            "statement": "The current export reports parcels due.",
        }],
        "summary": "The current dispatch export needs review; confirm the supported scope before acting.",
    }


async def test_submission_is_schema_valid_finite_and_has_a_human_report():
    _, public, adapter, episode = _workflow()
    recipient = public["destinations"][0]["key"]
    submission = _valid_submission(recipient)
    schema = next(
        tool["parameters"]
        for tool in await episode.specs()
        if tool["name"] == "submit_analysis"
    )
    assert recipient in schema["properties"]["recipients"]["items"]["enum"]

    result = await episode.call("submit_analysis", submission)

    assert result == {"recorded": True, "delivery_enabled": False}
    assert episode.submission["outcome"] == submission["outcome"]
    assert episode.submission["summary"].strip()
    assert math.isfinite(episode.submission["numeric_claims"][0]["value"])
    json.dumps(episode.submission, allow_nan=False)

    blank_report = RecurringEpisode(public, adapter, notes=MONITORING_NOTES)
    invalid_report = _valid_submission(recipient)
    invalid_report["summary"] = "  "
    with pytest.raises(ValueError, match="human-facing report"):
        await blank_report.call("submit_analysis", invalid_report)
    assert blank_report.submission is None

    invalid_schema = _valid_submission(recipient)
    invalid_schema["extra_field"] = "must be rejected"
    with pytest.raises(ValueError):
        await blank_report.call("submit_analysis", invalid_schema)
    assert blank_report.submission is None


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
async def test_submission_rejects_non_finite_numeric_claims(non_finite):
    _, public, _, episode = _workflow()
    submission = _valid_submission(public["destinations"][0]["key"])
    submission["numeric_claims"][0]["value"] = non_finite

    with pytest.raises(ValueError):
        await episode.call("submit_analysis", submission)

    assert episode.submission is None


async def test_pinned_codex_checks_exact_version_and_executable_hash(tmp_path, monkeypatch):
    executable = tmp_path / "codex-cli"
    executable.write_bytes(b"offline codex executable fixture")
    calls = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"codex-cli 0.162.0-alpha.2\n", None

    async def create_subprocess_exec(*arguments, **kwargs):
        calls.append((arguments, kwargs))
        return Process()

    monkeypatch.setattr(onboarding_trial.asyncio, "create_subprocess_exec", create_subprocess_exec)

    identity = await pinned_codex(str(executable))

    assert identity == {
        "path": str(executable.resolve()),
        "version": "codex-cli 0.162.0-alpha.2",
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }
    assert calls == [((str(executable.resolve()), "--version"), {
        "stdout": onboarding_trial.asyncio.subprocess.PIPE,
        "stderr": onboarding_trial.asyncio.subprocess.DEVNULL,
    })]


async def test_pinned_codex_rejects_wrong_cli_version(tmp_path, monkeypatch):
    executable = tmp_path / "codex-cli"
    executable.write_bytes(b"offline codex executable fixture")

    class Process:
        returncode = 0

        async def communicate(self):
            return b"codex-cli 0.163.0\n", None

    async def create_subprocess_exec(*arguments, **kwargs):
        return Process()

    monkeypatch.setattr(onboarding_trial.asyncio, "create_subprocess_exec", create_subprocess_exec)

    with pytest.raises(ValueError, match="requires its preregistered Codex CLI"):
        await pinned_codex(str(executable))


async def test_pinned_codex_rejects_executable_hash_change_during_version_check(tmp_path, monkeypatch):
    executable = tmp_path / "codex-cli"
    executable.write_bytes(b"original executable bytes")

    class Process:
        returncode = 0

        async def communicate(self):
            executable.write_bytes(b"changed executable bytes")
            return b"codex-cli 0.162.0-alpha.2\n", None

    async def create_subprocess_exec(*arguments, **kwargs):
        return Process()

    monkeypatch.setattr(onboarding_trial.asyncio, "create_subprocess_exec", create_subprocess_exec)

    with pytest.raises(ValueError, match="changed during identity verification"):
        await pinned_codex(str(executable))

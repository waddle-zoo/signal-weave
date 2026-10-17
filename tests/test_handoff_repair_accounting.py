"""Offline accounting and payload-isolation contracts for owner-handoff-v2."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from evaluations import domain_context_onboarding_trial as trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import public_episode
from tests.test_owner_handoff_workflow import install_owner_handoff_runner_fakes

TRACE_PAYLOAD_SENTINEL = "RETAINED_TRACE_PROMPT_MUST_NEVER_BE_FORWARDED"
PINNED_REPAIR_TRACE_SHA256 = "532070437a6f9ced1e6f5e0668fba1d0b5d7f4c9012ce9512916dc0bb61d173d"


def retained_trace_events():
    """A synthetic trace with the retained attempt's accounting, never its contents."""
    return [
        {
            "kind": "api.request",
            "provider": "openai",
            "request_id": "prior-1",
            "prompt": TRACE_PAYLOAD_SENTINEL,
        },
        {
            "kind": "api.response",
            "provider": "openai",
            "request_id": "prior-1",
            "usage": {
                "input_tokens": 200_000,
                "input_tokens_details": {"cached_tokens": 150_000},
                "output_tokens": 2_200,
            },
        },
        {
            "kind": "api.request",
            "provider": "openai",
            "request_id": "prior-2",
            "prompt": TRACE_PAYLOAD_SENTINEL,
        },
        {
            "kind": "api.response",
            "provider": "openai",
            "request_id": "prior-2",
            "usage": {
                "input_tokens": 177_916,
                "input_tokens_details": {"cached_tokens": 154_896},
                "output_tokens": 2_105,
            },
        },
    ]


def write_synthetic_trace(tmp_path, monkeypatch, events=None):
    payload = "".join(
        json.dumps(event, sort_keys=True) + "\n"
        for event in (retained_trace_events() if events is None else events)
    ).encode()
    path = tmp_path / "synthetic-retained-trace.jsonl"
    path.write_bytes(payload)
    # Override the pinned identity only for this synthetic, fully offline fixture.
    monkeypatch.setattr(trial, "HANDOFF_REPAIR_PRIOR_SHA256", hashlib.sha256(payload).hexdigest())
    return path, payload


def v2_args(path):
    return SimpleNamespace(
        owner_handoff=True,
        cohort_id="owner-handoff-v2",
        charge_trace=str(path),
    )


def test_repair_cohort_keeps_the_exact_retained_trace_identity():
    assert trial.HANDOFF_REPAIR_PRIOR_SHA256 == PINNED_REPAIR_TRACE_SHA256


def test_load_handoff_charge_returns_only_verified_usage_metadata(tmp_path, monkeypatch):
    path, _ = write_synthetic_trace(tmp_path, monkeypatch)

    charge = trial.load_handoff_charge(path)

    assert charge == {
        "trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "usage": {
            "input_tokens": 377_916,
            "cached_input_tokens": 304_896,
            "uncached_input_tokens": 73_020,
            "output_tokens": 4_305,
            "responses": 2,
        },
        "invocations": 2,
        "provider_attempts": 0,
        "classification": "invalid shared-schema harness; not a product comparison",
    }
    assert TRACE_PAYLOAD_SENTINEL not in json.dumps(charge)


def test_retained_trace_hash_mismatch_is_rejected(tmp_path):
    path = tmp_path / "changed-trace.jsonl"
    path.write_text('{"kind":"api.request","provider":"openai"}\n')

    with pytest.raises(ValueError, match="retained invalid v1 trace, unchanged"):
        trial.load_handoff_charge(path)


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("provider_error", "unknown prior usage"),
        ("missing_invocation", "exactly two known prior invocations"),
        ("jev_attempt", "exactly two known prior invocations"),
        ("invalid_usage", "missing or invalid agent usage"),
    ],
)
def test_load_handoff_charge_rejects_unchargeable_trace_states(
    tmp_path, monkeypatch, defect, message
):
    events = deepcopy(retained_trace_events())
    if defect == "provider_error":
        events.append({"kind": "api.error", "provider": "openai"})
    elif defect == "missing_invocation":
        events.remove(
            next(
                event
                for event in events
                if event["kind"] == "api.request" and event["request_id"] == "prior-2"
            )
        )
    elif defect == "jev_attempt":
        events.append({"kind": "api.request", "provider": "jev"})
    elif defect == "invalid_usage":
        events[1]["usage"]["input_tokens_details"]["cached_tokens"] = 200_001
    path, _ = write_synthetic_trace(tmp_path, monkeypatch, events)

    with pytest.raises(ValueError, match=message):
        trial.load_handoff_charge(path)


def test_owner_workflow_settings_selects_v2_caps_and_preserves_v1_defaults(tmp_path, monkeypatch):
    path, _ = write_synthetic_trace(tmp_path, monkeypatch)

    legacy_id, legacy_limits, legacy_charge = trial.owner_workflow_settings(
        SimpleNamespace(owner_handoff=True)
    )
    cohort_id, limits, prior_charge = trial.owner_workflow_settings(v2_args(path))

    assert legacy_id == "owner-handoff-v1"
    assert legacy_limits == trial.OWNER_HANDOFF_LIMITS
    assert legacy_limits["between_invocation_input_stop"] == 1_200_000
    assert legacy_limits["between_invocation_uncached_stop"] == 180_000
    assert legacy_charge is None
    assert cohort_id == "owner-handoff-v2"
    assert limits["codex_invocations"] == 8
    assert limits["between_invocation_input_stop"] == 1_600_000
    assert limits["between_invocation_uncached_stop"] == 250_000
    assert {
        key: limits[key]
        for key in trial.OWNER_HANDOFF_LIMITS
        if key not in {"between_invocation_input_stop", "between_invocation_uncached_stop"}
    } == {
        key: value
        for key, value in trial.OWNER_HANDOFF_LIMITS.items()
        if key not in {"between_invocation_input_stop", "between_invocation_uncached_stop"}
    }
    assert prior_charge["invocations"] == 2
    assert trial.OWNER_HANDOFF_LIMITS["between_invocation_input_stop"] == 1_200_000
    assert trial.OWNER_HANDOFF_LIMITS["between_invocation_uncached_stop"] == 180_000


@pytest.mark.parametrize(
    "args",
    [
        SimpleNamespace(owner_handoff=True, cohort_id="owner-handoff-v2", charge_trace=None),
        SimpleNamespace(owner_handoff=False, cohort_id="owner-handoff-v2", charge_trace="unused"),
        SimpleNamespace(owner_handoff=True, cohort_id=None, charge_trace="unused"),
    ],
)
def test_v2_selector_requires_handoff_mode_and_charge_trace(args):
    with pytest.raises(ValueError):
        trial.owner_workflow_settings(args)


@pytest.mark.parametrize("stage", ["first", "second"])
async def test_serialized_schema_guard_accepts_both_handoff_stages(stage):
    scenario = trial.clarified_development_scenario()
    public = public_episode(scenario)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    session = trial.HandoffEpisode(
        public,
        adapter,
        stage=stage,
        owner_answers=public["owner_answers"] if stage == "second" else None,
    )

    trial.validate_owner_handoff_schemas(await session.specs(), public["owner_topics"][0])


async def test_serialized_schema_guard_rejects_unbounded_owner_topic_and_restricted_notes():
    scenario = trial.clarified_development_scenario()
    public = public_episode(scenario)
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    session = trial.HandoffEpisode(public, adapter, stage="first")
    tools = await session.specs()

    unbounded_topic = deepcopy(tools)
    next(tool for tool in unbounded_topic if tool["name"] == "ask_owner")["parameters"][
        "properties"
    ]["topic"] = {"type": "string"}
    with pytest.raises(ValueError, match="owner topics must remain bounded"):
        trial.validate_owner_handoff_schemas(unbounded_topic, public["owner_topics"][0])

    restricted_notes = deepcopy(tools)
    next(tool for tool in restricted_notes if tool["name"] == "save_working_notes")["parameters"][
        "properties"
    ]["notes"] = {"enum": ["fixed text"], "type": "string"}
    with pytest.raises(ValidationError):
        trial.validate_owner_handoff_schemas(restricted_notes, public["owner_topics"][0])


async def test_v2_charges_old_usage_without_forwarding_trace_payload(monkeypatch, tmp_path):
    path, _ = write_synthetic_trace(tmp_path, monkeypatch)
    args, state = install_owner_handoff_runner_fakes(monkeypatch, tmp_path)
    args.cohort_id = "owner-handoff-v2"
    args.charge_trace = str(path)
    prompts = []
    fake_codex_episode = trial.codex_episode

    async def capture_prompt(session, **kwargs):
        prompts.append(deepcopy(kwargs.get("prompt_override")))
        return await fake_codex_episode(session, **kwargs)

    monkeypatch.setattr(trial, "codex_episode", capture_prompt)

    report = await trial.run_owner_workflow(args)

    assert "failure" not in report
    assert report["protocol"] == "owner-handoff-v2"
    assert report["pair_status"] == "both_reports_complete"
    assert len(state.invocation_order) == report["agent_invocations_started"] == 8
    assert report["usage"]["responses"] == 8
    assert report["usage"]["input_tokens"] == 800
    assert report["charged_prior_attempt"]["usage"]["input_tokens"] == 377_916
    assert report["charged_prior_attempt"]["invocations"] == 2
    assert report["limits"]["combined_invocation_cap"] == 10
    assert report["cumulative_usage_including_invalid_attempt"] == {
        "input_tokens": 378_716,
        "cached_input_tokens": 304_896,
        "uncached_input_tokens": 73_820,
        "output_tokens": 4_385,
        "responses": 10,
    }
    assert state.native.evaluations[0]["idempotency_key"].startswith("owner-handoff-v2:")
    assert TRACE_PAYLOAD_SENTINEL not in json.dumps(prompts)
    assert TRACE_PAYLOAD_SENTINEL not in json.dumps(report["charged_prior_attempt"])


async def test_v2_cumulative_input_stop_includes_prior_tokens_before_next_invocation(
    monkeypatch, tmp_path
):
    path, _ = write_synthetic_trace(tmp_path, monkeypatch)
    args, state = install_owner_handoff_runner_fakes(monkeypatch, tmp_path)
    args.cohort_id = "owner-handoff-v2"
    args.charge_trace = str(path)
    monkeypatch.setattr(
        trial,
        "HANDOFF_REPAIR_LIMITS",
        {**trial.HANDOFF_REPAIR_LIMITS, "between_invocation_input_stop": 377_917},
    )

    report = await trial.run_owner_workflow(args)

    assert report["pair_status"] == "incomplete"
    assert "between-invocation token threshold reached" in report["failure"]
    assert state.invocation_order == ["baseline-owner-handoff-first"]
    assert report["agent_invocations_started"] == report["usage"]["responses"] == 1
    assert report["usage"]["input_tokens"] == 100
    assert report["cumulative_usage_including_invalid_attempt"]["input_tokens"] == 378_016
    assert report["limits"]["between_invocation_input_stop"] == 377_917


async def test_v2_unknown_current_usage_stops_and_is_not_reported_as_zero(monkeypatch, tmp_path):
    path, _ = write_synthetic_trace(tmp_path, monkeypatch)
    args, state = install_owner_handoff_runner_fakes(monkeypatch, tmp_path, missing_usage_at=0)
    args.cohort_id = "owner-handoff-v2"
    args.charge_trace = str(path)

    report = await trial.run_owner_workflow(args)

    assert report["pair_status"] == "incomplete"
    assert "unknown invocation usage" in report["failure"]
    assert state.invocation_order == ["baseline-owner-handoff-first"]
    assert report["agent_invocations_started"] == 1
    assert report["usage_known"] is False
    assert report["usage"] == {"status": "unknown"}
    assert report["known_partial_usage"] == {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "responses": 0,
    }
    assert report["cumulative_usage_including_invalid_attempt"] == {"status": "unknown"}

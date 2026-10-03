"""Offline transport doubles test isolation/contracts, not reviewer quality."""

import copy
import json
import math

import pytest
from pydantic import ValidationError
from test_codex_trial_transport import fake_episode as fake_episode

from evaluations import bootstrap_owner_review as reviewer
from evaluations import codex_trial_transport as transport
from evaluations.bootstrap_agent_trial import MODEL, Audit, RequestBudget, canonical, digest
from signalweave.diagnostics import AnalyticalComparison
from signalweave.models import ResourceSnapshot

REAL_CODEX_EPISODE = transport.codex_episode
COMPLETE = {"status": "complete", "error": None, "exit_code": 0,
            "foreign_tools": [], "tool_calls": 1, "seconds": 1.25, "transport": "codex_cli"}


@pytest.fixture(autouse=True)
def no_live_transport(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Test must install an offline transport double")

    monkeypatch.setattr(transport, "codex_episode", forbidden)


@pytest.fixture
def inputs():
    return {
        "public": {
            "brief": "Investigate a material service degradation with the business owner.",
            "glossary": {"eligible": "Customer traffic only; exclude internal tests."},
            "destinations": [{"key": "business", "label": "Business owner",
                              "destination": "slack://business"}],
            "catalog": ["SECRET_CATALOG"], "onboarding": {"snapshot": "SECRET_SNAPSHOT"},
            "periods": ["SECRET_FUTURE"], "private": "SECRET_LABEL",
            "scoring": "SECRET_SCORE", "owner_answers": {"secret": "WRONG_OWNER_SOURCE"},
        },
        "owner_answers": {"materiality": "Investigate to business when latency increases at least 20%."},
        "artifact": {
            "notes": "Customer traffic only. Investigate to business at a 20% latency increase.",
            "card": {
                "decision_guidance": "Investigate to business at a 20% latency increase.",
                "numeric_conditions": [{
                    "text": "Latency delta reaches 20%.", "source_key": "source-a",
                    "comparison_key": "comparison-a", "measurement": "delta",
                    "threshold": 0.20, "unit": "ratio", "comparator": ">=",
                }],
                "sources": [{
                    "key": "source-a", "adapter": "company_mcp", "resource": "metric:latency",
                    "required_comparison_keys": ["comparison-a"],
                }],
                "delivery_methods": [{"key": "business", "outcome": "investigate",
                                      "label": "Business owner", "destination": "slack://business"}],
                "compiled_plan": {"cached_result": "SECRET_CACHED_RESULT"},
                "onboarding_review": {"result": "SECRET_PREVIOUS_REVIEW"},
                "status": "approved", "private": "SECRET_CARD_LABEL",
            },
            "score": "SECRET_ARTIFACT_SCORE",
        },
    }


async def test_label_safe_payload_same_episode_audit_hashes_and_counters(monkeypatch, inputs):
    before = copy.deepcopy(inputs)
    audit, budget = Audit(episode="company:arm:onboarding"), RequestBudget(5)
    observed = {}

    async def episode(session, **kwargs):
        observed.update(kwargs)
        assert session.phase == "monitoring" and session.treatment is False
        assert session.submission is None
        assert not hasattr(session, "adapter") and not hasattr(session, "server")
        specs = await session.specs()
        assert [spec["name"] for spec in specs] == ["record_owner_review"]
        bridge = transport.TrialMCP(session, audit, specs, kwargs["max_tool_calls"])
        response = await bridge.call("record_owner_review", {
            "approved": True, "reasons": ["Outcome, threshold and actual business route match."],
        })
        assert not response.isError
        assert session.submission["approved"] is True
        return copy.deepcopy(COMPLETE)

    monkeypatch.setattr(transport, "codex_episode", episode)
    result = await reviewer.review_owner_artifact(**inputs, audit=audit, budget=budget)

    payload = observed["prompt_override"]
    assert set(payload) == {"owner_policy", "source_context", "execution_contract", "artifact"}
    assert set(payload["owner_policy"]) == {"brief", "glossary", "destinations", "owner_answers"}
    assert payload["owner_policy"]["owner_answers"] == inputs["owner_answers"]
    assert payload["source_context"] == {
        "available": False, "catalog": [], "inspected_sources": []}
    assert payload["execution_contract"]["runtime_settings"]["action_confidence_threshold"] == 0.70
    assert payload["execution_contract"]["runtime_settings"]["investigation_threshold"] == 0.60
    assert payload["execution_contract"]["numeric_bindings"][0]["measurement"] == "delta"
    assert payload["execution_contract"]["numeric_bindings"][0]["semantics"] == "delta"
    assert "action_confidence_threshold" not in payload["artifact"]["card"]
    assert "investigation_threshold" not in payload["artifact"]["card"]
    assert payload["artifact"]["card"]["delivery_methods"] == inputs["artifact"]["card"]["delivery_methods"]
    assert payload["artifact"]["card"]["numeric_conditions"] == inputs["artifact"]["card"]["numeric_conditions"]
    assert "SECRET_" not in canonical(payload) and "WRONG_OWNER_SOURCE" not in canonical(payload)
    assert observed["instructions_override"] == reviewer.REVIEW_INSTRUCTIONS
    assert observed["effort"] == "high" and observed["timeout_seconds"] == 90
    assert observed["max_tool_calls"] == 2 and observed["key"] == ""
    assert observed["audit"] is audit and observed["budget"] is budget
    assert result["approved"] is True and result["episode"] == COMPLETE
    assert result["synthetic"] is True
    assert result["human_approval"] is result["policy_guarantee"] is False
    assert result["reasons"] == result["review"]["reasons"]
    assert result["input_digest"] == digest(payload)
    assert result["artifact_digest"] == digest(inputs["artifact"])
    assert result["instructions_digest"] == digest(reviewer.REVIEW_INSTRUCTIONS)
    assert [event["kind"] for event in audit.events] == ["review.request", "tool.result", "review.result"]
    assert {event["episode"] for event in audit.events} == {"company:arm:onboarding"}
    assert audit.events[0]["model"] == MODEL == "gpt-5.6-luna"
    assert audit.events[-1]["approved"] is True
    assert audit.events[-1]["episode_result"] == COMPLETE
    assert "SECRET_" not in canonical(audit.events)
    assert inputs == before


async def test_baseline_notes_need_no_card_and_rejection_retains_actionable_reasons(monkeypatch, inputs):
    inputs["artifact"] = {"notes": "Notify the business owner on any change."}

    async def episode(session, **kwargs):
        assert kwargs["prompt_override"]["artifact"] == inputs["artifact"]
        assert "do NOT require a card" in kwargs["instructions_override"]
        await session.call("record_owner_review", {
            "approved": False,
            "reasons": ["Restore investigate rather than notify and the owner's 20% threshold."],
        })
        return COMPLETE

    monkeypatch.setattr(transport, "codex_episode", episode)
    result = await reviewer.review_owner_artifact(**inputs, audit=Audit(), budget=RequestBudget(1))
    assert result["approved"] is False
    assert result["reasons"] == result["review"]["reasons"]
    assert "20%" in result["reasons"][0]
    assert result["episode"]["status"] == "complete"  # A completed rejection is not a transport failure.


@pytest.mark.parametrize("arguments", [
    {}, {"approved": True}, {"reasons": ["Reason"]},
    *[{"approved": value, "reasons": ["Reason"]} for value in (1, 0, "true", None, [], {})],
    *[{"approved": True, "reasons": value} for value in (
        [], "Reason", [123], [None], [""], ["   "], ["x" * 601], ["Reason"] * 9,
    )],
    {"approved": True, "reasons": ["Reason"], "rewrite": "New policy"},
])
async def test_strict_review_schema_and_direct_call_reject_invalid_arguments(arguments):
    session, audit = reviewer.OwnerReviewSession(), Audit()
    with pytest.raises(ValidationError):
        await session.call("record_owner_review", arguments)
    assert session.submission is None
    bridge = transport.TrialMCP(session, audit, await session.specs(), max_calls=2)
    result = await bridge.call("record_owner_review", arguments)
    assert result.isError and session.submission is None
    assert bridge.calls == 1


async def test_only_record_tool_and_no_second_submission():
    session = reviewer.OwnerReviewSession()
    with pytest.raises(ValueError, match="Only record"):
        await session.call("inspect_source", {})
    assert session.submission is None
    arguments = {"approved": False, "reasons": ["x" * 600] * 8}
    await session.call("record_owner_review", arguments)
    with pytest.raises(ValueError, match="already recorded"):
        await session.call("record_owner_review", {"approved": True, "reasons": ["Changed mind"]})
    assert session.submission == arguments


@pytest.mark.parametrize("floor", [0, 0.5, -1, True, "0.7", float("nan"), float("inf"), 1.1])
def test_execution_contract_cannot_lower_frozen_study_floor(inputs, floor):
    inputs["artifact"]["card"]["action_confidence_threshold"] = floor
    with pytest.raises(ValueError, match="cannot lower or disable"):
        reviewer.review_payload(**inputs)


def test_execution_settings_do_not_replace_owner_thresholds(inputs):
    inputs["artifact"]["card"]["action_confidence_threshold"] = 0.9
    payload = reviewer.review_payload(**inputs)
    assert payload["execution_contract"]["runtime_settings"]["action_confidence_threshold"] == 0.9
    assert "20%" in payload["owner_policy"]["owner_answers"]["materiality"]


@pytest.mark.parametrize("fault", ["failed", "error", "exit", "bool-exit", "foreign", "budget", "exception",
                                       "missing", "malformed", "malformed-episode"])
async def test_failed_or_missing_review_cannot_approve_even_after_positive_tool(monkeypatch, inputs, fault):
    audit, budget = Audit(secrets=("never-log-this-exception",)), RequestBudget(1)

    async def episode(session, **kwargs):
        if fault != "missing":
            await session.call("record_owner_review", {"approved": True, "reasons": ["Policy matches."]})
        result = copy.deepcopy(COMPLETE)
        if fault == "failed":
            result["status"] = "failed"
        elif fault == "error":
            result["error"] = "codex_error"
        elif fault == "exit":
            result["exit_code"] = 1
        elif fault == "bool-exit":
            result["exit_code"] = False
        elif fault == "foreign":
            result["foreign_tools"] = ["shell"]
        elif fault == "budget":
            budget.exhausted = True
        elif fault == "exception":
            audit.emit("tool.result", name="record_owner_review", result=session.submission)
            raise RuntimeError("never-log-this-exception")
        elif fault == "malformed":
            session.submission = {"approved": "true", "reasons": ["Malformed response"]}
        elif fault == "malformed-episode":
            return None
        return result

    monkeypatch.setattr(transport, "codex_episode", episode)
    result = await reviewer.review_owner_artifact(**inputs, audit=audit, budget=budget)
    assert result["approved"] is False
    assert result["reasons"] and "No valid completed" in result["reasons"][0]
    assert audit.events[-1]["kind"] == "review.result"
    assert audit.events[-1]["approved"] is False
    assert "never-log-this-exception" not in canonical(audit.events)
    if fault == "exception":
        assert result["episode"]["error"] == "RuntimeError"
        assert result["episode"]["tool_calls"] == 1
        assert result["review"]["approved"] is True  # Retained, but cannot grant approval.


@pytest.mark.parametrize("fault", ["notes", "card", "answer-type", "answer-length", "answer-count", "payload"])
async def test_invalid_or_oversized_input_is_audited_without_transport(monkeypatch, inputs, fault):
    if fault == "notes":
        inputs["artifact"]["notes"] = "x" * 20_001
    elif fault == "card":
        inputs["artifact"]["card"] = "Not an object"
    elif fault == "answer-type":
        inputs["owner_answers"] = {"policy": {"labels": "Do not serialize"}}
    elif fault == "answer-length":
        inputs["owner_answers"] = {"policy": "x" * 8001}
    elif fault == "answer-count":
        inputs["owner_answers"] = {str(i): "policy" for i in range(51)}
    else:
        inputs["public"]["brief"] = "x" * reviewer.MAX_PROMPT_CHARACTERS
    called = False

    async def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("No dispatch on invalid input")

    monkeypatch.setattr(transport, "codex_episode", forbidden)
    audit = Audit()
    result = await reviewer.review_owner_artifact(**inputs, audit=audit, budget=RequestBudget(1))
    assert not called
    assert result["approved"] is False
    assert result["episode"]["error"] == "invalid_review_input"
    assert result["episode"]["tool_calls"] == 0
    assert [event["kind"] for event in audit.events] == ["review.request", "review.result"]


async def test_actual_transport_overrides_need_no_adapter_and_use_luna_high(monkeypatch, inputs, fake_episode):
    # Retain real codex_episode/TrialMCP; mock only process and local-server transport.
    monkeypatch.setattr(transport, "codex_episode", REAL_CODEX_EPISODE)
    lines = 0

    async def readline():
        nonlocal lines
        lines += 1
        if lines == 1:
            result = await fake_episode.bridge.call("record_owner_review", {
                "approved": True, "reasons": ["Policy and configured route match."],
            })
            assert not result.isError
            return json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 0,
            }}).encode() + b"\n"
        return b""

    fake_episode.process.stdout.readline.side_effect = readline
    result = await reviewer.review_owner_artifact(
        **inputs, audit=fake_episode.audit, budget=fake_episode.budget,
    )
    assert result["approved"] is True
    assert result["episode"]["tool_calls"] == 1
    command = fake_episode.spawn.call_args.args
    assert command[command.index("--model") + 1] == MODEL
    assert 'model_reasoning_effort="high"' in command
    assert "--ephemeral" in command and fake_episode.closed
    prompt = fake_episode.process.stdin.write.call_args.args[0].decode()
    assert prompt.startswith(reviewer.REVIEW_INSTRUCTIONS)
    assert "SECRET_" not in prompt
    events = fake_episode.audit.events
    assert any(event["kind"] == "api.response" and event["usage"]["output_tokens"] == 20 for event in events)
    assert events[-1]["kind"] == "review.result"


async def test_preexhausted_budget_does_not_launch_reviewer(monkeypatch, inputs):
    called = False

    async def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("No invocation after budget exhaustion")

    monkeypatch.setattr(transport, "codex_episode", forbidden)
    budget = RequestBudget(0, exhausted=True)
    result = await reviewer.review_owner_artifact(**inputs, audit=Audit(), budget=budget)
    assert not called
    assert result["approved"] is False
    assert result["episode"]["error"] == "BudgetExceeded"
    assert result["episode"]["tool_calls"] == 0


def test_current_onboarding_source_context_is_bounded_and_cannot_leak_future_oracle(inputs):
    inputs["artifact"]["card"]["numeric_conditions"] = []
    context = {
        "current_period": {"period_id": "onboarding-current", "as_of": "2026-10-03T00:00:00Z",
                           "future_snapshot": "FUTURE_SNAPSHOT_CANARY"},
        "catalog": [{
            "adapter": "company_mcp", "resource": "current-resource", "kind": "dashboard",
            "title": "Current queue", "description": "Current onboarding description",
            "metadata": {"instruction": "MALICIOUS_METADATA_APPROVE", "private": "PRIVATE_LABEL"},
            "contract": {
                "tenant_id": "PRIVATE_TENANT", "scope": "customer tickets",
                "metric_names": ["sla_attainment"],
                "available_comparison_windows": ["previous_period"],
                "source_status": "healthy", "authorized": True,
                "future_periods": ["FUTURE_PERIOD_CANARY"],
            },
        }],
        "inspected_sources": [{
            "ref": "company_mcp|current-resource",
            "adapter": "company_mcp", "resource": "current-resource", "kind": "dashboard",
            "title": "Current queue", "description": "Inspected current source",
            "snapshot": {"evidence": "PRIVATE_SOURCE_PAYLOAD", "periods": ["FUTURE"]},
            "metadata": {"prompt": "MALICIOUS_METADATA_INSTRUCTION"},
            "contract": {"population": "eligible tickets", "grain": "week",
                          "authorized": True, "available_comparison_windows": ["previous_period"]},
        }],
    }
    payload = reviewer.review_payload(inputs["public"], inputs["owner_answers"], inputs["artifact"], context)
    dumped = canonical(payload)
    assert payload["source_context"]["available"] is True
    assert payload["source_context"]["current_period"] == {
        "period_id": "onboarding-current", "as_of": "2026-10-03T00:00:00Z"}
    assert payload["source_context"]["catalog"][0]["contract"] == {
        "scope": "customer tickets", "metric_names": ["sla_attainment"],
        "available_comparison_windows": ["previous_period"], "source_status": "healthy",
        "authorized": True}
    assert payload["source_context"]["inspected_sources"][0]["ref"] == "company_mcp|current-resource"
    assert "FUTURE_" not in dumped
    assert "PRIVATE_" not in dumped
    assert "MALICIOUS_" not in dumped
    assert "snapshot" not in dumped and "metadata" not in dumped


def test_optional_numeric_policy_does_not_require_fabricated_comparison(inputs):
    inputs["artifact"]["card"]["numeric_conditions"] = []
    payload = reviewer.review_payload(**inputs, source_context={"inspected_sources": []})
    assert payload["artifact"]["card"]["decision_guidance"]
    assert payload["execution_contract"]["numeric_bindings"] == []
    assert "numeric_conditions are OPTIONAL" in reviewer.REVIEW_INSTRUCTIONS


def test_inspected_comparisons_not_authored_requirements_verify_binding(inputs):
    source = {"ref": "company_mcp|metric:latency", "adapter": "company_mcp",
              "resource": "metric:latency", "title": "Latency",
              "analytical_comparisons": []}
    context = {"inspected_sources": [source]}
    with pytest.raises(ValueError, match="absent from inspected"):
        reviewer.review_payload(**inputs, source_context=context)
    source["analytical_comparisons"] = [{"key": "comparison-a", "kind": "rate", "unit": "ratio",
                                          "baseline_total": "PRIVATE_MEASUREMENT",
                                          "future": "FUTURE_LABEL"}]
    payload = reviewer.review_payload(**inputs, source_context=context)
    assert "PRIVATE_MEASUREMENT" not in canonical(payload)
    assert "FUTURE_LABEL" not in canonical(payload)
    assert payload["execution_contract"]["numeric_bindings_verified_against_inspection"]
    inputs["artifact"]["card"]["numeric_conditions"][0]["measurement"] = "within_effect"
    reviewer.review_payload(**inputs, source_context=context)
    source["analytical_comparisons"][0]["kind"] = "additive"
    with pytest.raises(ValueError, match="Rate effects"):
        reviewer.review_payload(**inputs, source_context=context)
    source["analytical_comparisons"][0]["unit"] = "milliseconds"
    with pytest.raises(ValueError, match="unit differs"):
        reviewer.review_payload(**inputs, source_context=context)


def test_uninspected_numeric_source_is_not_verified_by_card(inputs):
    with pytest.raises(ValueError, match="must be inspected"):
        reviewer.review_payload(**inputs, source_context={"inspected_sources": []})


@pytest.fixture
def comparison_source_context():
    comparison = AnalyticalComparison.model_validate({
        "key": "comparison-a", "metric": "latency", "definition": "Eligible request latency",
        "population": "Customer requests", "unit": "ratio", "dimension": "channel",
        "kind": "rate", "baseline_start": "2026-08-01T00:00:00Z",
        "baseline_end": "2026-08-08T00:00:00Z", "current_start": "2026-08-08T00:00:00Z",
        "current_end": "2026-08-15T00:00:00Z", "coverage": "complete",
        "comparable": True, "disjoint_segments": True, "query_refs": ["QUERY_CANARY"],
        "baseline_total": {"numerator": 82, "denominator": 100},
        "current_total": {"numerator": 28, "denominator": 100},
        "segments": [{"segment": "SEGMENT_CANARY", "baseline": {"numerator": 82, "denominator": 100},
                      "current": {"numerator": 28, "denominator": 100}}],
    })
    snapshot = ResourceSnapshot(
        source_key="source-a", adapter="company_mcp", resource="metric:latency", title="Latency",
        analytical_comparisons=[comparison], metadata={"private_label": "PRIVATE_CANARY"},
    ).model_dump(mode="json")
    snapshot["ref"] = "company_mcp|metric:latency"
    return {"inspected_sources": [snapshot]}


@pytest.mark.parametrize("baseline", [False, True])
@pytest.mark.parametrize("coverage", ["complete", "partial", "unknown"])
@pytest.mark.parametrize("flag", [False, True])
def test_comparison_flags_from_real_snapshot_are_preserved_without_measurements(
    inputs, comparison_source_context, baseline, coverage, flag,
):
    if baseline:
        inputs["artifact"].pop("card")
    comparison = comparison_source_context["inspected_sources"][0]["analytical_comparisons"][0]
    comparison.update(coverage=coverage, comparable=flag, disjoint_segments=not flag)
    original = copy.deepcopy(comparison_source_context)
    payload = reviewer.review_payload(**inputs, source_context=comparison_source_context)
    projected = payload["source_context"]["inspected_sources"][0]["analytical_comparisons"][0]
    assert projected == {
        **{key: comparison[key] for key in reviewer.COMPARISON_DESCRIPTION_FIELDS},
        "coverage": coverage, "comparable": flag, "disjoint_segments": not flag,
    }
    assert "CANARY" not in canonical(payload)
    assert payload["owner_policy"]["owner_answers"] == inputs["owner_answers"]
    assert comparison_source_context == original
    comparison["comparable"] = not flag
    assert digest(payload) != digest(reviewer.review_payload(**inputs, source_context=comparison_source_context))


def test_comparison_projection_does_not_synthesize_omitted_flags(comparison_source_context):
    comparison = comparison_source_context["inspected_sources"][0]["analytical_comparisons"][0]
    for field in ("coverage", "comparable", "disjoint_segments"):
        comparison.pop(field)
    projected = reviewer.project_source_context(comparison_source_context)
    assert projected["inspected_sources"][0]["analytical_comparisons"][0] == {
        key: comparison[key] for key in reviewer.COMPARISON_DESCRIPTION_FIELDS
    }


@pytest.mark.parametrize("field, invalid", [
    (field, value) for field in ("comparable", "disjoint_segments")
    for value in (None, 0, 1, "true", "false", [], {})
] + [("coverage", value) for value in (None, True, 0, "all", "Complete", " complete ", [], {})])
def test_comparison_flags_reject_invalid_types_and_enums(comparison_source_context, field, invalid):
    comparison_source_context["inspected_sources"][0]["analytical_comparisons"][0][field] = invalid
    with pytest.raises(ValueError, match=rf"comparison\.{field}"):
        reviewer.project_source_context(comparison_source_context)


def test_source_context_is_optional_and_policy_remains_separate(inputs):
    payload = reviewer.review_payload(inputs["public"], inputs["owner_answers"], inputs["artifact"])
    assert payload["owner_policy"]["owner_answers"] == inputs["owner_answers"]
    assert payload["source_context"]["available"] is False
    assert "source_context" in reviewer.REVIEW_INSTRUCTIONS
    assert "owner_policy" in reviewer.REVIEW_INSTRUCTIONS
    assert "Do not reject a faithful quiet/ignore rule" in reviewer.REVIEW_INSTRUCTIONS


def test_execution_contract_rejects_unbound_numeric_conditions_and_exposes_typed_semantics(inputs):
    inputs["artifact"]["card"]["numeric_conditions"][0].update({
        "text": "Within-segment effect reaches 20%.",
        "measurement": "delta",
    })
    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"]
    )
    binding = payload["execution_contract"]["numeric_bindings"][0]
    assert binding["measurement"] == "delta"
    assert binding["semantics"] == "delta"
    assert "free-text label" in reviewer.REVIEW_INSTRUCTIONS

    inputs["artifact"]["card"]["numeric_conditions"][0].update({
        "text": "Within-segment effect reaches 20%.",
        "measurement": "contribution", "segment": None,
    })
    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"]
    )
    binding = payload["execution_contract"]["numeric_bindings"][0]
    assert binding["measurement"] == "contribution"
    assert binding["segment"] is None
    assert binding["semantics"] == "any matching segment contribution"


def test_execution_contract_is_present_for_baseline_without_card(inputs):
    inputs["artifact"] = {"notes": "The owner policy is unchanged."}
    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"]
    )
    assert payload["execution_contract"]["source_bindings"] == []
    assert payload["execution_contract"]["numeric_bindings"] == []
    assert payload["execution_contract"]["runtime_settings"]["action_confidence_threshold"] == 0.70
    assert payload["execution_contract"]["numeric_condition_schema"] == (
        reviewer.NumericCondition.model_json_schema()
    )


def test_public_source_projection_accepts_real_nullable_contract_defaults():
    projected = reviewer.project_source_context({
        "catalog": [{
            "adapter": "company_mcp", "resource": "r", "kind": "dashboard", "title": "R",
            "description": "Current source", "contract": {"freshness_sla_hours": None},
        }],
        "inspected_sources": [],
    })
    assert projected["catalog"][0]["contract"] == {}


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_public_source_projection_rejects_non_finite_freshness(value):
    with pytest.raises(ValueError, match="freshness_sla_hours"):
        reviewer.project_source_context({
            "catalog": [{
                "adapter": "company_mcp", "resource": "r", "kind": "dashboard", "title": "R",
                "contract": {"freshness_sla_hours": value},
            }],
            "inspected_sources": [],
        })


@pytest.mark.parametrize("bad_context", [
    {"catalog": "not-a-list"},
    {"catalog": [{"adapter": "company_mcp", "resource": "r", "title": "t",
                   "contract": {"authorized": "yes"}}]},
    {"inspected_sources": [{"adapter": "company_mcp", "resource": "r"}]},
])
def test_malformed_source_context_is_rejected_before_dispatch(inputs, bad_context):
    with pytest.raises(ValueError):
        reviewer.review_payload(inputs["public"], inputs["owner_answers"],
                                inputs["artifact"], bad_context)

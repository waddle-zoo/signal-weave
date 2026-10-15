"""Adversarial contract tests for the one-card native onboarding smoke.

These exercise the runner's real public methods with local fixture adapters and
fake MCP/CLI boundaries. They do not launch Codex, a native binary, or a model.
"""

from __future__ import annotations

import copy
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations import domain_context_onboarding_trial as trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import build_scenarios, public_episode
from signalweave.knowledge_mcp import KNOWLEDGE_TOOLS
from signalweave.mcp_server import AGENT_PROFILE_TOOLS
from signalweave.models import InsightCard, InsightCardStatus, SourceRef

NATIVE_TOOL_NAMES = AGENT_PROFILE_TOOLS | KNOWLEDGE_TOOLS
COMMON_TOOL_NAMES = {
    "list_company_assets",
    "read_company_asset",
    "read_company_glossary",
    "ask_owner",
    "save_working_notes",
    "read_working_notes",
    "request_owner_approval",
    "finish_setup",
}


def _public():
    return public_episode(build_scenarios(seed=20261001)[0])


def _adapter(public):
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    adapter.set_period(public["period"], datetime.fromisoformat(public["period"]["as_of"]))
    return adapter


class FakeNative:
    instructions = "native default-agent instructions"

    def __init__(self, adapter=None, tenant="synthetic-company"):
        self.calls = []
        self.adapter = adapter
        self.card = InsightCard(
            id="card-1",
            title="Reviewed card",
            what_to_watch="A bounded signal",
            why_watch="Owner policy context",
            status=InsightCardStatus.DRAFT,
            principal_id="onboarding-owner",
            principal_tenant=tenant,
        ).model_dump(mode="json")

    async def list_tools(self):
        return [
            SimpleNamespace(
                name=name,
                description=f"actual-profile placeholder: {name}",
                inputSchema={"type": "object", "properties": {"marker": {"const": name}}},
            )
            for name in sorted(NATIVE_TOOL_NAMES)
        ]

    async def call_tool(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if name == "get_insight_card":
            return [], copy.deepcopy(self.card)
        if name == "get_context_history":
            return [], {"entry_id": args["entry_id"], "sentinel": "saved-context"}
        if name == "approve_insight_card":
            self.card["status"] = InsightCardStatus.APPROVED.value
        if name == "inspect_resource":
            descriptor = next(
                item
                for item in self.adapter.catalog
                if item.adapter == args["adapter"] and item.resource == args["resource"]
            )
            snapshot = await self.adapter.inspect(
                SourceRef(
                    key=descriptor.resource,
                    adapter=descriptor.adapter,
                    resource=descriptor.resource,
                    label=descriptor.title,
                )
            )
            return [], snapshot.model_dump(mode="json")
        return [], {"ok": True, "name": name}


def test_public_brief_is_a_real_allowlist_not_a_string_scrub():
    public = _public()
    public["glossary"]["private_definition"] = "GLOSSARY_SECRET_9f31"
    public["owner_answers"]["routing"] = "OWNER_ANSWER_SECRET_7ac2"
    public["future_periods"] = [{"period_id": "FUTURE_PERIOD_SECRET_82d1"}]
    public["period"]["snapshots"] = [{"observation": "CURRENT_ROW_SECRET_60be"}]
    public["private_labels"] = {"outcome": "PRIVATE_LABEL_SECRET_1bd0"}

    brief = trial.public_brief(public)

    assert set(brief) == {"scenario_id", "company", "brief", "owner_topics", "destinations"}
    assert brief["owner_topics"] == public["owner_topics"]
    encoded = json.dumps(brief)
    for sentinel in (
        "GLOSSARY_SECRET_9f31",
        "OWNER_ANSWER_SECRET_7ac2",
        "FUTURE_PERIOD_SECRET_82d1",
        "CURRENT_ROW_SECRET_60be",
        "PRIVATE_LABEL_SECRET_1bd0",
    ):
        assert sentinel not in encoded


@pytest.mark.asyncio
async def test_both_arms_keep_the_same_source_owner_and_notes_tools_and_data():
    public = _public()
    baseline = trial.Episode(public, _adapter(public))
    native = FakeNative()
    treatment = trial.Episode(public, _adapter(public), native)

    baseline_specs = {tool["name"]: tool for tool in await baseline.specs()}
    treatment_specs = {tool["name"]: tool for tool in await treatment.specs()}
    assert set(baseline_specs) == COMMON_TOOL_NAMES
    assert set(treatment_specs) == COMMON_TOOL_NAMES | NATIVE_TOOL_NAMES
    assert len(NATIVE_TOOL_NAMES) == 16
    assert {name: treatment_specs[name] for name in COMMON_TOOL_NAMES} == baseline_specs

    # The ordinary source interface and owner answer service are equal; answers
    # are returned only after an explicit ask, and notes remain arm-local.
    baseline_assets = await baseline.call("list_company_assets", {})
    treatment_assets = await treatment.call("list_company_assets", {})
    assert baseline_assets == treatment_assets
    assert baseline.owner_requests == treatment.owner_requests == []
    baseline_answer = await baseline.call("ask_owner", {"topic": "metric_scope"})
    treatment_answer = await treatment.call("ask_owner", {"topic": "metric_scope"})
    assert baseline_answer == treatment_answer
    assert baseline.owner_requests == treatment.owner_requests == [{"topic": "metric_scope"}]
    baseline_saved = await baseline.call("save_working_notes", {"notes": "baseline-only note"})
    treatment_saved = await treatment.call("save_working_notes", {"notes": "treatment-only note"})
    assert (
        baseline_saved["approval_target"]
        == treatment_saved["approval_target"]
        == {
            "kind": "notes",
            "id": "working",
        }
    )
    assert baseline_saved["id"] == treatment_saved["id"] == "working"
    assert await baseline.call("read_working_notes", {}) == {
        "id": baseline_saved["id"],
        "notes": "baseline-only note",
    }
    assert await treatment.call("read_working_notes", {}) == {
        "id": treatment_saved["id"],
        "notes": "treatment-only note",
    }


@pytest.mark.asyncio
async def test_setup_consent_is_bound_to_saved_artifact_and_never_authorizes_evaluation():
    public = _public()
    native = FakeNative()
    session = trial.Episode(public, _adapter(public), native)

    with pytest.raises(ValueError, match="does not authorize evaluation"):
        await session.call("evaluate_insight_card", {"card_id": "card-1"})
    assert not native.calls
    with pytest.raises(ValueError, match="consent"):
        await session.call("approve_insight_card", {"card_id": "card-1"})

    await session.call("save_working_notes", {"notes": "approved notes"})
    with pytest.raises(ValueError, match="consent"):
        await session.call("review_domain_context", {"entry_id": "context-1", "action": "approve"})
    await session.call(
        "request_owner_approval",
        {
            "kind": "context",
            "id": "context-1",
            "summary": "Review this saved context.",
        },
    )
    assert session.owner_requests[-1]["saved_artifact"] == {
        "entry_id": "context-1",
        "sentinel": "saved-context",
    }
    with pytest.raises(ValueError, match="consent"):
        await session.call("review_domain_context", {"entry_id": "context-2", "action": "approve"})
    await session.call("review_domain_context", {"entry_id": "context-1", "action": "approve"})

    await session.call(
        "request_owner_approval",
        {
            "kind": "card",
            "id": "card-1",
            "summary": "Review this saved card.",
        },
    )
    assert session.owner_requests[-1]["saved_artifact"]["title"] == "Reviewed card"
    approved_artifact_snapshot = copy.deepcopy(session.owner_requests[-1]["saved_artifact"])
    assert approved_artifact_snapshot["status"] == InsightCardStatus.DRAFT.value
    await session.call("approve_insight_card", {"card_id": "card-1"})
    assert native.card["status"] == InsightCardStatus.APPROVED.value
    assert session.owner_requests[-1]["saved_artifact"] == approved_artifact_snapshot
    result = await session.call(
        "finish_setup",
        {
            "card_ids": ["card-1"],
            "message": "Setup is ready for independent review.",
            "unresolved": [],
        },
    )
    assert result == {
        "recorded": True,
        "semantic_review": "pending",
        "delivery_enabled": False,
        "handoff_state": "awaiting_independent_review",
        "automation_proven": False,
    }
    assert session.setup["handoff_state"] == "awaiting_independent_review"
    assert session.setup_complete
    assert not any(name == "evaluate_insight_card" for name, _ in native.calls)


@pytest.mark.asyncio
async def test_unresolved_context_handoff_is_parallel_without_synthetic_consent():
    public = _public()
    baseline = trial.Episode(public, _adapter(public))
    native = FakeNative()
    treatment = trial.Episode(public, _adapter(public), native)

    unresolved = ["Confirm who may receive the report."]
    with pytest.raises(ValueError, match="save reusable notes"):
        await baseline.call(
            "finish_setup",
            {"card_ids": [], "message": "Follow up on audience scope.", "unresolved": unresolved},
        )

    await baseline.call("save_working_notes", {"notes": "Audience scope remains owner-confirmed."})
    baseline_result = await baseline.call(
        "finish_setup",
        {"card_ids": [], "message": "Follow up on audience scope.", "unresolved": unresolved},
    )
    treatment_result = await treatment.call(
        "finish_setup",
        {
            "card_ids": ["card-1"],
            "message": "Follow up on audience scope.",
            "unresolved": unresolved,
        },
    )

    expected = {
        "recorded": True,
        "semantic_review": "pending",
        "delivery_enabled": False,
        "handoff_state": "awaiting_owner_context",
        "automation_proven": False,
    }
    assert baseline_result == treatment_result == expected
    assert (
        baseline.setup["handoff_state"]
        == treatment.setup["handoff_state"]
        == "awaiting_owner_context"
    )
    assert baseline.setup_complete and treatment.setup_complete
    assert baseline.owner_requests == treatment.owner_requests == []
    assert baseline.approvals == treatment.approvals == {}
    assert treatment.notes == ""
    assert native.card["status"] == InsightCardStatus.DRAFT.value
    assert not any(
        name in {"approve_insight_card", "evaluate_insight_card"} for name, _ in native.calls
    )
    assert treatment_result["semantic_review"] == "pending"


@pytest.mark.asyncio
async def test_native_unresolved_handoff_uses_saved_card_without_duplicate_working_notes():
    public = _public()
    native = FakeNative()
    treatment = trial.Episode(public, _adapter(public), native)

    result = await treatment.call(
        "finish_setup",
        {
            "card_ids": ["card-1"],
            "message": "Follow up on audience scope.",
            "unresolved": ["Confirm who may receive the report."],
        },
    )

    assert result["handoff_state"] == "awaiting_owner_context"
    assert result["semantic_review"] == "pending"
    assert result["automation_proven"] is False
    assert treatment.notes == ""
    assert native.card["status"] == InsightCardStatus.DRAFT.value
    assert treatment.owner_requests == []
    assert treatment.approvals == {}
    assert not any(
        name in {"approve_insight_card", "evaluate_insight_card"} for name, _ in native.calls
    )


def test_usage_budget_reports_cached_and_uncached_separately_and_stops_on_unknown():
    events = [
        {
            "kind": "api.response",
            "provider": "openai",
            "usage": {
                "input_tokens": 120,
                "input_tokens_details": {"cached_tokens": 75},
                "output_tokens": 9,
            },
        }
    ]
    assert trial.usage_totals(events) == {
        "input_tokens": 120,
        "cached_input_tokens": 75,
        "uncached_input_tokens": 45,
        "output_tokens": 9,
        "responses": 1,
    }
    assert (
        trial.budget_stop([{"kind": "api.error", "provider": "openai"}])
        == "unknown_usage_or_agent_error"
    )
    assert (
        trial.budget_stop([{"kind": "api.response", "provider": "openai", "usage": {}}])
        == "unknown_usage"
    )

    old_input, old_uncached = trial.MAX_INPUT, trial.MAX_UNCACHED
    try:
        trial.MAX_INPUT, trial.MAX_UNCACHED = 1_000, 40
        assert trial.budget_stop(events) == "between_episode_token_threshold"
        trial.MAX_INPUT, trial.MAX_UNCACHED = 100, 1_000
        assert trial.budget_stop(events) == "between_episode_token_threshold"
    finally:
        trial.MAX_INPUT, trial.MAX_UNCACHED = old_input, old_uncached


def test_prior_invalid_invocation_is_charged_to_cumulative_budget():
    prior = {
        "kind": "api.response",
        "provider": "openai",
        "usage": {
            "input_tokens": 173_288,
            "input_tokens_details": {"cached_tokens": 149_504},
            "output_tokens": 40,
        },
    }
    below_limits = {
        "kind": "api.response",
        "provider": "openai",
        "usage": {
            "input_tokens": 326_711,
            "input_tokens_details": {"cached_tokens": 275_496},
            "output_tokens": 20,
        },
    }
    at_limits = {
        "kind": "api.response",
        "provider": "openai",
        "usage": {
            "input_tokens": 326_712,
            "input_tokens_details": {"cached_tokens": 275_496},
            "output_tokens": 20,
        },
    }

    assert trial.usage_totals([prior]) == {
        "input_tokens": 173_288,
        "cached_input_tokens": 149_504,
        "uncached_input_tokens": 23_784,
        "output_tokens": 40,
        "responses": 1,
    }
    assert trial.budget_stop([prior, below_limits]) is None
    assert trial.budget_stop([prior, at_limits]) == "between_episode_token_threshold"


@pytest.mark.asyncio
async def test_native_setup_uses_private_home_and_project_skill_without_personal_registration(
    tmp_path,
    monkeypatch,
):
    public = _public()
    audit = Audit()
    seen = {"commands": [], "jev_budget": None, "stdio": None}
    personal_home = str(tmp_path / "personal-home")
    personal_codex_home = str(tmp_path / "personal-codex-home")
    monkeypatch.setenv("HOME", personal_home)
    monkeypatch.setenv("CODEX_HOME", personal_codex_home)

    @asynccontextmanager
    async def fake_source_server(_session):
        yield "http://127.0.0.1:19001/source"

    @asynccontextmanager
    async def fake_jev_proxy(_audit, budget):
        seen["jev_budget"] = budget.limit
        yield "http://127.0.0.1:19002/jev"

    monkeypatch.setattr(trial, "_source_server", fake_source_server)
    monkeypatch.setattr(trial, "_jev_proxy", fake_jev_proxy)
    monkeypatch.setattr(
        trial, "_manifest", lambda _public, _url: {"connections": [{"context_namespace": ""}]}
    )

    class Process:
        returncode = 0

        async def wait(self):
            return 0

    skill_text = "---\nname: signalweave\n---\nExact installed test skill bytes.\n"

    async def fake_spawn(*command, cwd, env, **_kwargs):
        seen["commands"].append((command, Path(cwd), dict(env)))
        if command[1:3] == ("skills", "install"):
            path = Path(cwd) / ".agents" / "skills" / "signalweave" / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(skill_text)
        return Process()

    monkeypatch.setattr(trial.asyncio, "create_subprocess_exec", fake_spawn)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    @asynccontextmanager
    async def fake_stdio(params, **_kwargs):
        seen["stdio"] = params
        yield (object(), object())

    monkeypatch.setattr(trial, "stdio_client", fake_stdio)
    monkeypatch.setattr(trial, "ClientSession", lambda *_streams: Client())
    monkeypatch.setattr(trial, "_initialize_mcp_session", _init_result)

    async with trial.native_context(
        Path("/synthetic/signalweave"),
        Path("/synthetic/key"),
        public,
        _adapter(public),
        audit,
        tmp_path,
    ) as (native, installed_skill):
        assert native.instructions == "native profile instructions"
        assert installed_skill == skill_text

    setup_command, project_command = seen["commands"]
    assert "--home" in setup_command[0]
    assert str(tmp_path / "native-home") == setup_command[0][setup_command[0].index("--home") + 1]
    assert "--no-register-agent" in setup_command[0]
    assert "--profile" in setup_command[0] and "agent" in setup_command[0]
    assert project_command[0][1:7] == (
        "skills",
        "install",
        "--agent",
        "codex",
        "--scope",
        "project",
    )
    assert project_command[1] == tmp_path
    assert seen["jev_budget"] == 0
    assert seen["stdio"].args == ["serve", "--home", str(tmp_path / "native-home")]
    for _command, _cwd, child_env in seen["commands"]:
        assert "HOME" not in child_env and "CODEX_HOME" not in child_env
    assert "HOME" not in seen["stdio"].env and "CODEX_HOME" not in seen["stdio"].env
    assert os.environ["HOME"] == personal_home
    assert os.environ["CODEX_HOME"] == personal_codex_home
    assert audit.events[-1]["agent_registration"] is False
    assert audit.events[-1]["skill_sha256"]


async def _init_result(_session):
    return SimpleNamespace(instructions="native profile instructions")


@pytest.mark.asyncio
async def test_preflight_and_bounded_pair_keep_labels_out_of_prompts_and_scores(
    tmp_path, monkeypatch
):
    scenario = build_scenarios(seed=20261001, connector_profile=True)[0]
    scenario["public"]["owner_answers"]["metric_scope"] = "PRIVATE_OWNER_ANSWER_4cf9"
    scenario["public"]["glossary"]["private_definition"] = "PRIVATE_GLOSSARY_7a20"
    scenario["private"]["periods"][next(iter(scenario["private"]["periods"]))]["outcome"] = (
        "PRIVATE_FINAL_LABEL_19bf"
    )

    def fixture_builder(*, seed, connector_profile=False, **_kwargs):
        assert seed == 20261001
        assert connector_profile is True
        return [scenario]

    monkeypatch.setattr(trial, "build_scenarios", fixture_builder)
    monkeypatch.setattr(trial, "verify_binary", lambda _binary: {"sha256": "synthetic-binary"})

    installed_skill = "---\nname: signalweave\n---\nExact current skill bytes.\n"

    @asynccontextmanager
    async def fake_native_context(_binary, _key, public, adapter, _audit, _root):
        yield FakeNative(adapter, public["scenario_id"]), installed_skill

    monkeypatch.setattr(trial, "native_context", fake_native_context)
    prior_trace = tmp_path / "invalid-prior-trace.jsonl"
    prior_trace.write_text(
        json.dumps(
            {
                "kind": "api.response",
                "provider": "openai",
                "usage": {
                    "input_tokens": 173_288,
                    "input_tokens_details": {"cached_tokens": 149_504},
                    "output_tokens": 40,
                },
            }
        )
        + "\n"
    )
    args = SimpleNamespace(
        binary=Path("/synthetic/signalweave"),
        key_file=Path("/synthetic/key"),
        codex_executable="/synthetic/codex",
        output=tmp_path / "preflight",
        prior_trace=prior_trace,
        run=False,
    )

    async def forbidden_model_call(*_args, **_kwargs):
        pytest.fail("preflight must not call Codex")

    monkeypatch.setattr(trial, "codex_episode", forbidden_model_call)
    preflight = await trial.run(args)
    assert preflight["preflight_only"] is True
    assert preflight["episodes"] == []
    assert preflight["limits"]["invocations"] == 2
    assert preflight["limits"]["tools_per_invocation"] == 24
    assert preflight["limits"]["seconds_per_invocation"] == 240
    assert preflight["limits"]["jev_requests"] == 0
    assert preflight["schema_bytes"]["baseline"] > 0
    assert preflight["schema_bytes"]["signalweave"] > preflight["schema_bytes"]["baseline"]

    calls = []

    async def fake_codex(session, **kwargs):
        calls.append((session, kwargs))
        saved_notes = await session.call(
            "save_working_notes", {"notes": f"notes for {kwargs['audit'].episode}"}
        )
        read_notes = await session.call("read_working_notes", {})
        assert read_notes["id"] == saved_notes["id"] == saved_notes["approval_target"]["id"]
        if session.treatment:
            await session.call(
                "request_owner_approval",
                {
                    "kind": "card",
                    "id": "card-1",
                    "summary": "Review the saved card.",
                },
            )
            await session.call("approve_insight_card", {"card_id": "card-1"})
            await session.call(
                "finish_setup",
                {
                    "card_ids": ["card-1"],
                    "message": "Setup complete.",
                    "unresolved": [],
                },
            )
        else:
            await session.call(
                "request_owner_approval",
                {
                    "kind": "notes",
                    "id": saved_notes["approval_target"]["id"],
                    "summary": "Review the saved notes.",
                },
            )
            await session.call(
                "finish_setup", {"card_ids": [], "message": "Setup complete.", "unresolved": []}
            )
        kwargs["audit"].emit(
            "api.response",
            provider="openai",
            usage={
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 50},
                "output_tokens": 10,
            },
        )
        return {
            "status": "complete",
            "final_message": "The word notify here is not a decision label.",
        }

    monkeypatch.setattr(trial, "codex_episode", fake_codex)
    args.output = tmp_path / "bounded-run"
    args.run = True
    report = await trial.run(args)

    assert len(calls) == 2
    assert [call[0].treatment for call in calls] == [False, True]
    for session, kwargs in calls:
        assert kwargs["max_turns"] == 24
        assert kwargs["max_tool_calls"] == 24
        assert kwargs["max_output_tokens"] == 3000
        assert kwargs["timeout_seconds"] == 240
        assert kwargs["codex_executable"] == "/synthetic/codex"
        assert kwargs["prompt_override"]["owner_topics"] == [
            *scenario["public"]["owner_topics"],
            "context_review",
        ]
        prompt_json = json.dumps(kwargs["prompt_override"])
        for sentinel in (
            "PRIVATE_OWNER_ANSWER_4cf9",
            "PRIVATE_GLOSSARY_7a20",
            "PRIVATE_FINAL_LABEL_19bf",
        ):
            assert sentinel not in prompt_json
        specs = {spec["name"] for spec in await session.specs()}
        assert set(specs) == (
            COMMON_TOOL_NAMES | NATIVE_TOOL_NAMES if session.treatment else COMMON_TOOL_NAMES
        )
        if session.treatment:
            assert installed_skill in kwargs["instructions_override"]
            assert FakeNative.instructions in kwargs["instructions_override"]
        else:
            assert installed_skill not in kwargs["instructions_override"]

    assert report["content_review"] == "pending independent review"
    assert all("setup" in episode for episode in report["episodes"])
    assert all(episode["setup"] is not None for episode in report["episodes"])
    assert all(
        "outcome_matches" not in episode and "score" not in episode
        for episode in report["episodes"]
    )
    assert "PRIVATE_FINAL_LABEL_19bf" not in json.dumps(report)
    assert report["usage"] == {
        "input_tokens": 200,
        "cached_input_tokens": 100,
        "uncached_input_tokens": 100,
        "output_tokens": 20,
        "responses": 2,
    }
    assert report["usage_known"] is True
    assert report["limits"]["invocations"] == 2
    assert report["charged_prior_attempt"]["usage"] == {
        "input_tokens": 173_288,
        "cached_input_tokens": 149_504,
        "uncached_input_tokens": 23_784,
        "output_tokens": 40,
        "responses": 1,
    }
    assert report["cumulative_usage_including_invalid_attempt"] == {
        "input_tokens": 173_488,
        "cached_input_tokens": 149_604,
        "uncached_input_tokens": 23_884,
        "output_tokens": 60,
        "responses": 3,
    }

    missing_usage_calls = []

    async def fake_codex_without_usage(_session, **_kwargs):
        missing_usage_calls.append(True)
        return {"status": "complete", "final_message": "No usage event was recorded."}

    monkeypatch.setattr(trial, "codex_episode", fake_codex_without_usage)
    args.output = tmp_path / "missing-usage"
    stopped = await trial.run(args)
    assert len(missing_usage_calls) == 1
    assert stopped["agent_invocations_started"] == 1
    assert len(stopped["episodes"]) == 1
    assert stopped["stopped"] == "missing_agent_usage"
    assert stopped["usage_known"] is False

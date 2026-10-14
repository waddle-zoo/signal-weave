from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from evaluations.native_superset_card_journey import (
    BUSINESS_QUESTIONS,
    DATA_READ_TOOLS,
    DISCOVERY_TOOLS,
    MAX_DATA_READS,
    MAX_EPISODE_TOOL_CALLS,
    MAX_EPISODE_TURNS,
    MONITOR_TOOLS,
    SETUP_TOOLS,
    SHARED_SOURCE_TOOLS,
    CardJourneySession,
    _owner_approval,
    _run_episode,
    _source_budget_summary,
    build_actor_prompt,
    instructions_for,
    load_installed_skill,
    run,
    skill_path,
)


class NativeTools:
    def __init__(self, names):
        self.names = names

    async def list_tools(self):
        return [
            SimpleNamespace(name=name, description=name, inputSchema={"type": "object"})
            for name in self.names
        ]


@pytest.mark.asyncio
async def test_baseline_and_treatment_share_identical_superset_tool_contracts():
    names = set(SETUP_TOOLS) | set(MONITOR_TOOLS) | {"approve_insight_card", "simulate_insight_card"}
    baseline = CardJourneySession(None, stage="baseline")
    setup = CardJourneySession(None, NativeTools(names), stage="setup")
    baseline_specs, setup_specs = await baseline.specs(), await setup.specs()
    common_baseline = {s["name"]: s for s in baseline_specs if s["name"] in SHARED_SOURCE_TOOLS}
    common_setup = {s["name"]: s for s in setup_specs if s["name"] in SHARED_SOURCE_TOOLS}
    assert common_setup == common_baseline
    assert set(common_baseline) == SHARED_SOURCE_TOOLS
    assert "approve_insight_card" not in {s["name"] for s in setup_specs}
    assert "simulate_insight_card" not in {s["name"] for s in setup_specs}


@pytest.mark.asyncio
async def test_onboarding_and_monitor_tool_surfaces_are_separate_and_default_profile_bounded():
    native = NativeTools(set(SETUP_TOOLS) | set(MONITOR_TOOLS) | {
        "approve_insight_card", "simulate_insight_card", "preview_investigation_report",
    })
    setup_names = {spec["name"] for spec in await CardJourneySession(None, native, stage="setup").specs()}
    monitor_names = {spec["name"] for spec in await CardJourneySession(None, native, stage="monitor").specs()}
    assert SETUP_TOOLS <= setup_names
    assert "approve_insight_card" not in setup_names
    assert "evaluate_insight_card" not in setup_names
    assert MONITOR_TOOLS <= monitor_names
    assert "approve_insight_card" not in monitor_names
    assert "simulate_insight_card" not in setup_names | monitor_names
    assert "preview_investigation_report" not in setup_names | monitor_names


@pytest.mark.asyncio
async def test_discovery_calls_do_not_consume_the_data_read_budget(monkeypatch):
    async def fake_parent_call(self, name, arguments):
        return {"tool": name}

    monkeypatch.setattr(
        "evaluations.native_superset_card_journey.ReportSession.call", fake_parent_call
    )
    session = CardJourneySession(None, stage="setup", max_data_reads=3)
    for _ in range(12):
        await session.call("find_dashboards", {"query": ""})
    for _ in range(12):
        await session.call("search_catalog", {"query": "online"})

    for name in ("read_dashboard", "read_chart_rows", "inspect_resource"):
        await session.call(name, {})

    assert DISCOVERY_TOOLS == {"find_dashboards", "search_catalog"}
    assert DATA_READ_TOOLS == {"read_dashboard", "read_chart_rows", "inspect_resource"}
    assert session.discovery_calls == 24
    assert session.discovery_calls_by_tool == {"find_dashboards": 12, "search_catalog": 12}
    assert session.data_reads == 3
    assert session.data_reads_by_tool == {
        "read_dashboard": 1,
        "read_chart_rows": 1,
        "inspect_resource": 1,
    }
    summary = _source_budget_summary(session)
    assert summary["discovery_calls"] == 24
    assert summary["data_read_calls"] == 3
    assert summary["data_read_cap"] == 3
    with pytest.raises(ValueError, match="data_read_budget_exhausted"):
        await session.call("read_dashboard", {})


@pytest.mark.asyncio
async def test_all_arms_keep_the_same_sixty_data_read_cap_and_episode_limits(monkeypatch):
    assert MAX_DATA_READS == 60
    assert MAX_EPISODE_TURNS == 20
    assert MAX_EPISODE_TOOL_CALLS == 60
    native = NativeTools(SETUP_TOOLS | MONITOR_TOOLS)
    sessions = [
        CardJourneySession(None, stage="baseline"),
        CardJourneySession(None, native, stage="setup"),
        CardJourneySession(None, native, stage="monitor"),
    ]
    assert {session.max_data_reads for session in sessions} == {MAX_DATA_READS}
    assert all(_source_budget_summary(session)["data_read_cap"] == MAX_DATA_READS for session in sessions)

    observed_limits = []

    async def fake_codex_episode(session, **kwargs):
        observed_limits.append((kwargs["max_turns"], kwargs["max_tool_calls"]))
        return {"status": "complete"}

    monkeypatch.setattr("evaluations.native_superset_card_journey.codex_episode", fake_codex_episode)
    for session in sessions:
        await _run_episode(
            session,
            audit=SimpleNamespace(episode=None),
            stage=session.stage,
            prompt={},
            skill="---\nname: signalweave\n---\n",
        )
    assert observed_limits == [(20, 60)] * 3


def test_three_questions_are_live_evidence_prompts_without_expected_classes_or_thresholds():
    assert len(BUSINESS_QUESTIONS) == 3
    actor_prompt = build_actor_prompt("Owner definitions and policy supplied for this trial.")
    text = str(actor_prompt)
    assert all(question in text for question in BUSINESS_QUESTIONS)
    assert "expected_outcome" not in text
    assert "ground_truth" not in text
    assert "case_label" not in text
    assert "10%" not in text


def test_baseline_can_browse_the_catalog_with_an_empty_dashboard_query():
    instructions = instructions_for(
        "baseline", "---\nname: signalweave\ndescription: test\n---\n"
    )
    assert "find_dashboards with an empty query" in instructions
    assert "instead of repeating title synonyms" in instructions


def test_skill_is_read_from_installed_user_scope_and_supplied_verbatim_to_both_arms(tmp_path):
    path = skill_path(tmp_path)
    path.parent.mkdir(parents=True)
    skill = "---\nname: signalweave\ndescription: trial skill\n---\nUse exact sources.\n"
    path.write_text(skill, encoding="utf-8")
    loaded, digest = load_installed_skill(tmp_path)
    assert loaded == skill
    assert digest == hashlib.sha256(skill.encode()).hexdigest()
    assert skill in instructions_for("baseline", loaded)
    assert skill in instructions_for("setup", loaded)
    assert skill in instructions_for("monitor", loaded)


def test_missing_or_wrong_installed_skill_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="did not install"):
        load_installed_skill(tmp_path)
    path = skill_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: other\n---\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="frontmatter"):
        load_installed_skill(tmp_path)


@pytest.mark.asyncio
async def test_owner_approval_requires_interactive_confirmation_and_reason(monkeypatch):
    class Native:
        calls = []

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return [], {"status": "approved"}

    native = Native()
    session = CardJourneySession(None, native, stage="setup")
    session.card = {
        "id": "draft-1",
        "retrieval_mode": "fixed",
        "investigation_mode": "none",
        "sources": [{"key": "primary"}],
    }
    session.review = {"readiness_status": "ready_for_approval"}
    monkeypatch.setattr("evaluations.native_superset_card_journey.sys.stdin", SimpleNamespace(isatty=lambda: False))
    result = await _owner_approval(native, session, "superset")
    assert result["status"] == "awaiting_owner"
    assert native.calls == []


@pytest.mark.asyncio
async def test_owner_approval_does_not_acknowledge_dynamic_scope_or_oversized_cards(monkeypatch):
    class Native:
        calls = []

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return [], {"status": "approved"}

    monkeypatch.setattr("evaluations.native_superset_card_journey.sys.stdin", SimpleNamespace(isatty=lambda: True))
    native = Native()
    session = CardJourneySession(None, native, stage="setup")
    session.card = {
        "id": "dynamic-draft",
        "retrieval_mode": "expand",
        "investigation_mode": "none",
        "sources": [{"key": "primary"}],
    }
    session.review = {"readiness_status": "ready_for_approval"}
    result = await _owner_approval(native, session, "superset")
    assert result["status"] == "not_approved"
    assert "dynamic scope" in result["reason"]
    assert native.calls == []


@pytest.mark.asyncio
async def test_trial_does_not_start_without_explicit_execute_flag():
    with pytest.raises(SystemExit, match="No provider calls"):
        await run(SimpleNamespace(execute=False))

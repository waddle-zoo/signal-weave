import copy
from types import SimpleNamespace

import pytest

from evaluations.agent_workflow_cohort import build_cohort
from evaluations.bootstrap_agent_trial import ToolSession, agent_context, common_tools
from evaluations.bootstrap_scenarios import public_scenario


@pytest.fixture
def dialogue():
    public = public_scenario(build_cohort()[3])
    events = []
    adapter = SimpleNamespace(name="company_mcp", audit=SimpleNamespace(
        emit=lambda kind, **values: events.append({"kind": kind, **values})))
    return public, ToolSession(public, adapter, None, False), events


@pytest.mark.asyncio
async def test_script_revealed_only_by_explicit_same_topic_followup(dialogue):
    public, session, events = dialogue
    original = copy.deepcopy(public)
    assert "owner_followup_answers" not in agent_context(public)
    assert session._owner_review_answers() == {}
    first = await session.call("ask_owner", {"topic": "materiality"})
    assert first["answer"] == public["owner_answers"]["materiality"]
    repeated = await session.call("ask_owner", {"topic": "materiality"})
    assert repeated == first
    assert session._owner_review_answers() == {"materiality": first["answer"]}
    clarified = await session.call("ask_owner", {
        "topic": "materiality", "question": "What about complete cases outside the joint criteria?"})
    assert clarified["answer"] == public["owner_followup_answers"]["materiality"]
    assert session._owner_review_answers() == {"materiality": clarified["answer"]}
    assert [event["scripted_clarification"] for event in events] == [False, False, True]
    assert [event["turn"] for event in events] == [1, 2, 3]
    assert public == original


@pytest.mark.asyncio
async def test_first_question_does_not_advance_script_or_disclose_other_topics(dialogue):
    public, session, _ = dialogue
    answer = await session.call("ask_owner", {
        "topic": "materiality", "question": "Which movements need attention?"})
    assert answer["answer"] == public["owner_answers"]["materiality"]
    assert "routing" not in session._owner_review_answers()


@pytest.mark.asyncio
async def test_owner_not_available_in_autonomous_monitoring(dialogue):
    _, session, events = dialogue
    session.phase = "monitoring"
    answer = await session.call("ask_owner", {
        "topic": "materiality", "question": "Please resolve the fallback."})
    assert answer["known"] is False
    assert session.owner_turns == 0
    assert events == []


@pytest.mark.asyncio
async def test_scripted_owner_turn_cap_and_input_bounds(dialogue):
    _, session, _ = dialogue
    with pytest.raises(ValueError, match="Owner question"):
        await session.call("ask_owner", {"topic": "materiality", "question": " "})
    for _ in range(16):
        await session.call("ask_owner", {"topic": "materiality"})
    with pytest.raises(ValueError, match="sixteen-turn cap"):
        await session.call("ask_owner", {"topic": "materiality"})
    assert session.owner_turns == 16


def test_followup_schema_is_shared_and_optional(dialogue):
    public, _, _ = dialogue
    tools = common_tools(agent_context(public), phase="onboarding")
    owner = next(tool for tool in tools if tool["name"] == "ask_owner")
    assert owner["parameters"]["required"] == ["topic"]
    assert owner["parameters"]["properties"]["question"]["maxLength"] == 4000

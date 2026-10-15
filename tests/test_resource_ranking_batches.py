from types import SimpleNamespace

import pytest
import typesafe_sdk

from signalweave.models import ContextFact, ContextSnapshot, ResourceContract, ResourceDescriptor
from signalweave.typesafe_adapter import JevJudger, JevPayloadError


class FakeNoul:
    def __init__(self, *, instructions, criteria):
        self.instructions = instructions
        self.criteria = criteria


class FakeClient:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def system_one(self, *, state, questions):
        type(self).calls.append({"state": state, "questions": questions})
        return SimpleNamespace(
            nouls={
                key: SimpleNamespace(noul=0.91 if index == 0 else 0.08)
                for index, key in enumerate(questions)
            },
            usage=SimpleNamespace(input_tokens=20, output_tokens=3),
        )


@pytest.fixture
def fake_typesafe(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    return FakeClient


def _resource(index: int, context_ref: str | None = None, description: str = ""):
    return ResourceDescriptor(
        adapter="superset",
        resource=f"chart:opaque-{index}",
        kind="chart",
        title=f"Candidate {index}",
        description=description,
        contract=ResourceContract(lineage=[context_ref] if context_ref else []),
    )


def _context(endpoint: str) -> ContextSnapshot:
    return ContextSnapshot(
        provider="offline-test-context",
        version="v1",
        facts=[
            ContextFact(
                fact_id="requires-operating-context",
                subject_ref="superset|dashboard:opaque-anchor",
                relation="requires_related_context",
                object_ref=endpoint,
                statement="The approved dashboard is interpreted with this operating context.",
            )
        ],
    )


def _context_overflow_inputs(judger: JevJudger, resources, context):
    endpoint = context.facts[0].object_ref
    for goal_length in range(0, 6001, 3):
        goal = "g" * goal_length
        state = judger._resource_ranking_state(goal, resources)
        state["context"] = context.model_dump(mode="json")
        base_questions = judger._resource_questions(resources)
        actual_questions = judger._resource_ranking_questions(resources, state)
        two_resource_state = judger._resource_ranking_batch_state(state, resources[:2])
        two_resource_questions = judger._resource_ranking_questions(resources[:2], state)
        single_states = [
            judger._resource_ranking_batch_state(state, [resource]) for resource in resources
        ]
        single_questions = [
            judger._resource_ranking_questions([resource], state) for resource in resources
        ]
        if (
            not judger._request_over_budget(state, base_questions)
            and judger._request_over_budget(state, actual_questions)
            and not judger._request_over_budget(two_resource_state, two_resource_questions)
            and all(
                not judger._request_over_budget(single_state, questions)
                for single_state, questions in zip(single_states, single_questions, strict=True)
            )
        ):
            return goal, state, endpoint
    raise AssertionError("could not construct a context-only overflow boundary")


@pytest.mark.asyncio
async def test_context_instruction_is_in_preflight_and_batches_keep_canonical_context_edges(
    fake_typesafe,
):
    endpoint = "context:opaque-approved-endpoint"
    resources = [_resource(index, endpoint) for index in range(3)]
    context = _context(endpoint)
    judger = JevJudger(api_key="offline-test", max_input_tokens=1_300)
    goal, original_state, _ = _context_overflow_inputs(judger, resources, context)

    assert "context" in original_state
    assert len(original_state["candidate_resources"]) == 3
    scores = await judger.rank_resources_with_context(goal, resources, context)

    assert scores == {
        "superset|chart:opaque-0": 0.91,
        "superset|chart:opaque-1": 0.08,
        "superset|chart:opaque-2": 0.91,
    }
    assert len(fake_typesafe.calls) == 2
    for call in fake_typesafe.calls:
        state = call["state"]
        questions = call["questions"]
        assert state["goal"] == goal
        assert state["context"] == original_state["context"]
        assert 1 <= len(state["candidate_resources"]) <= 2
        assert all(
            candidate["ref"] == f"{candidate['adapter']}|{candidate['resource']}"
            for candidate in state["candidate_resources"]
        )
        assert all(
            endpoint in candidate["contract"]["lineage"]
            for candidate in state["candidate_resources"]
        )
        assert all(
            question.instructions.endswith(
                " If context is supplied, treat its versioned facts and provenance as "
                "first-class evidence: a candidate connected to an approved context "
                "endpoint may be relevant even when its wording does not match the goal."
            )
            for question in questions.values()
        )
        assert not judger._request_over_budget(state, questions)


@pytest.mark.asyncio
async def test_oversized_single_candidate_fails_before_dispatch(fake_typesafe):
    judger = JevJudger(api_key="offline-test", max_input_tokens=1_024)
    resources = [_resource(0)]

    with pytest.raises(JevPayloadError) as error:
        await judger.rank_resources("g" * 10_000, resources)

    assert error.value.stage == "onboarding"
    assert error.value.observed_tokens > error.value.budget_tokens
    assert fake_typesafe.calls == []


@pytest.mark.asyncio
async def test_all_batches_are_preflighted_before_first_dispatch(fake_typesafe):
    judger = JevJudger(
        api_key="offline-test",
        max_input_tokens=1_024,
    )
    resources = [_resource(0), _resource(1, description="x" * 4_000)]
    goal = "g" * 900
    state = judger._resource_ranking_state(goal, resources)
    first_state = judger._resource_ranking_batch_state(state, [resources[0]])
    first_questions = judger._resource_ranking_questions([resources[0]], state)
    second_state = judger._resource_ranking_batch_state(state, [resources[1]])
    second_questions = judger._resource_ranking_questions([resources[1]], state)
    assert not judger._request_over_budget(first_state, first_questions)
    assert judger._request_over_budget(second_state, second_questions)

    with pytest.raises(JevPayloadError):
        await judger.rank_resources(goal, resources)

    assert fake_typesafe.calls == []


@pytest.mark.asyncio
async def test_non_context_resource_ranking_keeps_existing_single_request_prompt(fake_typesafe):
    judger = JevJudger(api_key="offline-test")
    resources = [_resource(0)]
    expected = judger._resource_questions(resources)["resource_0"].instructions

    scores = await judger.rank_resources("ordinary catalog goal", resources)

    assert scores == {"superset|chart:opaque-0": 0.91}
    assert len(fake_typesafe.calls) == 1
    call = fake_typesafe.calls[0]
    assert "context" not in call["state"]
    assert call["state"]["candidate_resources"][0]["ref"] == "superset|chart:opaque-0"
    assert call["questions"]["resource_0"].instructions == expected

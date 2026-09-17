from types import SimpleNamespace

import pytest
import typesafe_sdk

from semantic_monitor.models import ResourceDescriptor
from semantic_monitor.typesafe_adapter import JevJudger


class FakeNoul:
    def __init__(self, *, instructions, criteria):
        self.instructions = instructions
        self.criteria = criteria


class FakeResponse:
    usage = SimpleNamespace(input_tokens=41, output_tokens=7)

    def __init__(self, questions):
        self.nouls = {
            key: SimpleNamespace(noul=0.91 if key == "resource_0" else 0.08)
            for key in questions
        }


class FakeClient:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def system_one(self, *, state, questions):
        self.calls.append({"state": state, "questions": questions})
        return FakeResponse(questions)


@pytest.mark.asyncio
async def test_jev_rank_resources_uses_typed_questions_and_returns_probabilities(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(api_key="synthetic-test-key", timeout=3)
    resources = [
        ResourceDescriptor(
            adapter="superset",
            resource="dashboard:growth",
            kind="dashboard",
            title="Growth funnel",
            description="Revenue and conversion health.",
        ),
        ResourceDescriptor(
            adapter="superset",
            resource="dashboard:people",
            kind="dashboard",
            title="People operations",
            description="Hiring and retention.",
        ),
    ]

    scores = await judger.rank_resources("Monitor revenue risk", resources)

    assert scores == {
        "superset|dashboard:growth": 0.91,
        "superset|dashboard:people": 0.08,
    }
    assert len(FakeClient.calls) == 1
    call = FakeClient.calls[0]
    assert call["state"]["goal"] == "Monitor revenue risk"
    assert len(call["state"]["candidate_resources"]) == 2
    assert set(call["questions"]) == {"resource_0", "resource_1"}
    assert all(isinstance(question, FakeNoul) for question in call["questions"].values())
    assert judger.metrics.requests == 1
    assert judger.metrics.input_tokens == 41
    assert judger.metrics.output_tokens == 7

from types import SimpleNamespace

import pytest
import typesafe_sdk

from signalweave.compiler import base_plan
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    InvestigationMode,
    Observation,
    Outcome,
    ResourceDescriptor,
    SourceRef,
)
from signalweave.typesafe_adapter import JevJudger


class FakeNoul:
    def __init__(self, *, instructions, criteria):
        self.instructions = instructions
        self.criteria = criteria


class FakeScore:
    def __init__(self, *, instructions, criteria):
        self.instructions = instructions
        self.criteria = criteria


class FakeResponse:
    usage = SimpleNamespace(input_tokens=41, output_tokens=7)

    def __init__(self, questions):
        self.nouls = {}
        self.choices = {}
        self.scores = {}
        for key in questions:
            if key == "baseline":
                self.choices[key] = SimpleNamespace(choice="previous_period")
                continue
            if key == "time_grain":
                self.choices[key] = SimpleNamespace(choice="month")
                continue
            if key == "metric":
                self.choices[key] = SimpleNamespace(
                    choice="candidate-1", probabilities={"candidate-1": 0.91}
                )
                continue
            if key == "outcome":
                self.choices[key] = SimpleNamespace(
                    choice="notify",
                    probabilities={
                        "ignore": 0.05,
                        "investigate": 0.10,
                        "notify": 0.93,
                    },
                )
                continue
            if key == "need_investigation":
                self.nouls[key] = SimpleNamespace(noul=0.94)
                continue
            if key.startswith("candidate_"):
                self.scores[key] = SimpleNamespace(score=3.6, confidence=0.91)
                continue
            if key.startswith("evidence_"):
                self.choices[key] = SimpleNamespace(
                    choice="driver",
                    probabilities={"driver": 0.91, "unknown": 0.04},
                )
                continue
            if key == "resource_0":
                probability = 0.91
            elif key.startswith("resource_"):
                probability = 0.08
            elif key.startswith("watch_"):
                probability = 0.91
            elif key.startswith("question_"):
                probability = 0.83
            elif key.startswith("use_"):
                probability = 0.91
            elif key == "outcome_notify":
                probability = 0.93
            elif key == "outcome_ignore":
                probability = 0.05
            elif key == "outcome_investigate":
                probability = 0.10
            else:
                probability = 0.08
            self.nouls[key] = SimpleNamespace(noul=probability)


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

    scores = await judger.rank_resources("Understand revenue risk", resources)

    assert scores == {
        "superset|dashboard:growth": 0.91,
        "superset|dashboard:people": 0.08,
    }
    assert len(FakeClient.calls) == 1
    call = FakeClient.calls[0]
    assert call["state"]["goal"] == "Understand revenue risk"
    assert len(call["state"]["candidate_resources"]) == 2
    assert set(call["questions"]) == {"resource_0", "resource_1"}
    assert all(isinstance(question, FakeNoul) for question in call["questions"].values())
    assert judger.metrics.requests == 1
    assert judger.metrics.input_tokens == 41
    assert judger.metrics.output_tokens == 7


@pytest.mark.asyncio
async def test_jev_compiles_and_judges_free_form_card_items(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(api_key="synthetic-test-key", timeout=3)
    source = SourceRef(
        key="sales-signals",
        adapter="superset",
        resource="dashboard:7",
        label="Sales signals",
    )
    card = InsightCard(
        id="card-free-form",
        title="Sales pulse",
        what_to_watch="Revenue and the related signals that explain whether sales are on course.",
        why_watch="Help the revenue team decide what deserves attention this week.",
        watch_for=["Revenue falls while a related signal corroborates the movement."],
        questions=["Is there enough evidence to notify the revenue team?"],
        sources=[source],
        delivery_methods=[
            DeliveryMethod(
                key="revenue-team",
                outcome=Outcome.NOTIFY,
                label="Revenue team",
                destination="slack://revenue-team",
            )
        ],
    )
    compile_state = {
        "card": card.model_dump(mode="json"),
        "insight_card": card.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json")],
        "available_capabilities": [
            {"key": "percent_change", "description": "Compare current and baseline values."},
            {"key": "related_context_check", "description": "Use related source context."},
        ],
    }

    compiled = await judger.compile_plan(compile_state, card)
    plan = base_plan(card).model_copy(
        update={
            "capabilities": compiled["capabilities"],
            "comparison_windows": [compiled["baseline"]],
        }
    )
    observation = Observation(
        source_key=source.key,
        subject_id="revenue",
        subject_label="Revenue",
        metric="revenue",
        unit="USD",
        current=820.0,
        baseline=1000.0,
        change_pct=-18.0,
    )
    evidence = Evidence(
        source_key=source.key,
        subject_id=observation.subject_id,
        subject_label=observation.subject_label,
        statement="Revenue is down 18% versus the previous period.",
    )
    result = await judger.judge(
        {
            "card": card.model_dump(mode="json"),
            "insight_card": card.model_dump(mode="json"),
            "insight_plan": plan.model_dump(mode="json"),
            "observations": [observation.model_dump(mode="json")],
            "evidence": [evidence.model_dump(mode="json")],
        },
        card,
        plan,
        [observation],
    )

    assert compiled["capabilities"] == ["percent_change", "related_context_check"]
    assert compiled["baseline"] == "previous_period"
    assert result.outcome == Outcome.NOTIFY
    assert result.watch_results[0].status.value == "present"
    assert result.question_results[0].status.value == "supported"
    assert result.observations == [observation]
    assert len(FakeClient.calls) == 2
    judge_call = FakeClient.calls[1]
    assert set(judge_call["questions"]) == {
        "watch_0",
        "question_0",
        "outcome",
    }
    assert judge_call["state"]["insight_card"]["what_to_watch"] == card.what_to_watch
    assert judge_call["state"]["insight_card"]["questions"] == card.questions
    assert "owner-authored card guidance" in judge_call["questions"]["outcome"].criteria["ignore"]


@pytest.mark.asyncio
async def test_jev_selects_bounded_followup_sources_with_scores(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    monkeypatch.setattr(typesafe_sdk, "Score", FakeScore)
    judger = JevJudger(api_key="synthetic-test-key", timeout=3)
    card = InsightCard(
        id="card-investigation",
        title="Revenue pulse",
        what_to_watch="Revenue movement and its operational explanation.",
        why_watch="Decide whether Revenue Operations should respond.",
        sources=[
            SourceRef(
                key="anchor", adapter="superset", resource="dashboard:exec", label="Executive"
            )
        ],
        investigation_mode=InvestigationMode.BOUNDED,
    )
    plan = base_plan(card)
    candidate = ResourceDescriptor(
        adapter="superset",
        resource="dashboard:billing",
        kind="dashboard",
        title="Billing operations",
        description="Checkout failures and payment health.",
    )

    result = await judger.select_investigation_sources(
        {
            "observations": [{"metric": "revenue", "change_pct": -18}],
            "evidence": [],
        },
        card,
        plan,
        [candidate],
        1,
    )

    assert result["probability"] == 0.94
    assert result["selections"][0]["ref"] == "superset|dashboard:billing"
    assert result["selections"][0]["score"] == 0.9
    call = FakeClient.calls[0]
    assert isinstance(call["questions"]["candidate_0"], FakeScore)
    assert call["state"]["candidate_resources"][0]["title"] == "Billing operations"


@pytest.mark.asyncio
async def test_jev_bounded_judgment_returns_typed_evidence_findings(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(api_key="synthetic-test-key", timeout=3)
    source = SourceRef(
        key="anchor", adapter="superset", resource="dashboard:exec", label="Executive"
    )
    card = InsightCard(
        id="card-bounded-judgment",
        title="Revenue pulse",
        what_to_watch="Revenue movement.",
        why_watch="Support an operating decision.",
        sources=[source],
        investigation_mode=InvestigationMode.BOUNDED,
    )
    plan = base_plan(card)
    item = Observation(
        source_key="anchor",
        subject_id="revenue",
        subject_label="Revenue",
        metric="revenue",
        current=80,
        baseline=100,
        change_pct=-20,
    )

    result = await judger.judge(
        {
            "card": card.model_dump(mode="json"),
            "insight_card": card.model_dump(mode="json"),
            "insight_plan": plan.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json")],
            "evidence": [],
        },
        card,
        plan,
        [item],
    )

    assert result.evidence_findings[0].role == "driver"
    assert result.evidence_findings[0].probability == 0.91
    assert "evidence_0" in FakeClient.calls[0]["questions"]

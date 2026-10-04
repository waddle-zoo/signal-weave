import ssl
from types import SimpleNamespace

import pytest
import typesafe_sdk

from signalweave.compiler import base_plan
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    Evidence,
    InsightCard,
    InvestigationMode,
    Observation,
    Outcome,
    ResourceDescriptor,
    SourceRef,
)
from signalweave.typesafe_adapter import (
    JevJudger,
    JevPayloadError,
    estimate_json_tokens,
    load_api_key,
)


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
            if key.startswith("role_"):
                self.choices[key] = SimpleNamespace(
                    choice="diagnostic",
                    probabilities={"diagnostic": 0.88, "unknown": 0.04},
                )
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
            if key.startswith("watch_"):
                self.choices[key] = SimpleNamespace(
                    choice="present", probabilities={"present": .91, "absent": .04, "unknown": .05},
                )
                continue
            if key == "resource_0":
                probability = 0.91
            elif key.startswith("resource_"):
                probability = 0.08
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


async def test_low_confidence_rationale_separates_jev_selection_from_code_fallback(monkeypatch):
    async def transport(self, **kwargs):
        return SimpleNamespace(
            choices={"outcome": SimpleNamespace(choice="insufficient_data", probabilities={
                "ignore": .31, "investigate": .0, "insufficient_data": .69,
            })}, nouls={}, usage=None,
        )

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    card = InsightCard(id="uncertain", title="Uncertain evidence", what_to_watch="Supplied context",
                       why_watch="Review before action", sources=[], action_confidence_threshold=.7)
    result = await JevJudger(api_key="offline-test").judge({"evidence": []}, card, base_plan(card), [])
    assert result.outcome == Outcome.INVESTIGATE
    assert result.probabilities["investigate"] == 0
    assert result.confidence == .69
    assert "selected=insufficient_data, support=0.69" in result.rationale
    assert "routed=investigate" in result.rationale
    assert "confidence threshold" in result.rationale


async def test_computed_contribution_contract_and_action_criteria_are_policy_bound(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    card = InsightCard(
        id="generic", title="Capacity review", what_to_watch="Capacity by segment",
        why_watch="Apply the configured policy", sources=[],
        decision_guidance="Only notify when the total changes; segment changes alone are advisory.",
        delivery_methods=[DeliveryMethod(key="team", label="Capacity team", outcome=Outcome.NOTIFY,
                                         destination="agent://team")])
    original = {"analyses": [{"delta": 0, "contributions": []}], "card": card.model_dump(mode="json"), "evidence": []}
    await JevJudger(api_key="offline-test").judge(original, card, base_plan(card), [])
    call = FakeClient.calls[0]
    assert "computed_analysis_semantics" not in original
    meanings = call["state"]["computed_analysis_semantics"]
    assert "not a percentage share" in meanings["contribution"]
    assert "not any single segment" in meanings["within_effect"]
    assert "change in group weights" in meanings["mix_effect"]
    assert "not automatically an action trigger" in meanings["policy"]
    criterion = call["questions"]["outcome"].criteria["notify"]
    assert "decision_guidance" in criterion and "trigger conditions and exceptions" in criterion
    assert "Capacity team" in criterion
    assert card.action_confidence_threshold == .7


@pytest.mark.parametrize("value", ["replace-me", "placeholder", "your-typesafe-key"])
def test_load_api_key_rejects_copied_example_sentinel(monkeypatch, value):
    monkeypatch.setenv("TYPESAFE_API_KEY", value)

    with pytest.raises(ValueError, match="real deployment value"):
        load_api_key()


def test_load_api_key_accepts_nonempty_test_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    assert load_api_key() == "test-key"


@pytest.mark.asyncio
async def test_jev_retries_transient_transport_failures(monkeypatch):
    class FlakyClient(FakeClient):
        attempts = 0

        async def system_one(self, *, state, questions):
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise ssl.SSLError("transient test failure")
            return await super().system_one(state=state, questions=questions)

    FlakyClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FlakyClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(
        api_key="synthetic-test-key",
        timeout=3,
        max_retries=1,
    )

    scores = await judger.rank_resources(
        "Understand revenue risk",
        [
            ResourceDescriptor(
                adapter="superset",
                resource="dashboard:growth",
                kind="dashboard",
                title="Growth funnel",
            )
        ],
    )

    assert scores == {"superset|dashboard:growth": 0.91}
    assert FlakyClient.attempts == 2
    assert len(FlakyClient.calls) == 1


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
async def test_jev_always_pins_the_production_model(monkeypatch):
    class CapturingClient(FakeClient):
        init_kwargs = []

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            type(self).init_kwargs.append(kwargs)

    CapturingClient.init_kwargs = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", CapturingClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(api_key="synthetic-test-key")

    await judger.rank_resources(
        "Understand revenue risk",
        [
            ResourceDescriptor(
                adapter="superset",
                resource="dashboard:growth",
                kind="dashboard",
                title="Growth funnel",
            )
        ],
    )

    assert CapturingClient.init_kwargs[-1]["model"] == "jev-latest"
    assert CapturingClient.init_kwargs[-1]["retry"].max_retries == 0


@pytest.mark.asyncio
async def test_jev_discovery_payload_budget_fails_before_transport(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(api_key="synthetic-test-key", max_payload_bytes=1_024)
    resource = ResourceDescriptor(
        adapter="preset",
        resource="dashboard:verbose",
        kind="dashboard",
        title="Verbose dashboard",
        description="x" * 3_000,
    )

    with pytest.raises(JevPayloadError, match="onboarding Jev payload exceeded") as error_info:
        await judger.rank_resources("monitor the dashboard", [resource])

    assert error_info.value.stage == "onboarding"
    assert FakeClient.calls == []
    assert judger.metrics.requests == 0


@pytest.mark.asyncio
async def test_jev_question_payload_budget_fails_before_transport(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(api_key="synthetic-test-key", max_payload_bytes=1_024)

    with pytest.raises(JevPayloadError, match="judgment Jev payload exceeded") as error_info:
        await judger._system_one_with_retry(
            state={"goal": "small"},
            stage="judgment",
            questions={
                "dynamic_card_question": FakeNoul(
                    instructions="x" * 3_000,
                    criteria={"true": "supported", "false": "not supported"},
                )
            },
        )

    assert error_info.value.stage == "judgment"
    assert FakeClient.calls == []
    assert judger.metrics.requests == 0
    assert judger.metrics.payload_bytes == 0


@pytest.mark.asyncio
async def test_jev_context_rank_includes_versioned_graph_facts(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(api_key="synthetic-test-key", timeout=3)
    resource = ResourceDescriptor(
        adapter="trino",
        resource="query:fulfillment",
        kind="query",
        title="Fulfillment context",
    )
    context = ContextSnapshot(
        provider="company-graph",
        version="graph-v2",
        facts=[
            ContextFact(
                fact_id="edge-1",
                subject_ref="superset|dashboard:payments",
                relation="requires_related_context",
                object_ref="superset|dashboard:fulfillment",
                statement="Payments uses Fulfillment context.",
            )
        ],
    )

    scores = await judger.rank_resources_with_context(
        "Monitor authorization rate", [resource], context
    )

    assert scores == {"trino|query:fulfillment": 0.91}
    assert FakeClient.calls[0]["state"]["context"]["version"] == "graph-v2"
    assert FakeClient.calls[0]["state"]["context"]["facts"][0]["object_ref"] == (
        "superset|dashboard:fulfillment"
    )
    assert "context" in FakeClient.calls[0]["state"]


@pytest.mark.asyncio
async def test_jev_classifies_bounded_resource_roles_with_probabilities(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Choice", FakeScore)
    judger = JevJudger(api_key="synthetic-test-key", timeout=3)
    resources = [
        ResourceDescriptor(
            adapter="superset",
            resource="dashboard:growth",
            kind="dashboard",
            title="Growth funnel",
        ),
        ResourceDescriptor(
            adapter="trino",
            resource="table:events",
            kind="table",
            title="Raw events",
        ),
    ]

    roles = await judger.classify_resource_roles("Understand revenue risk", resources)

    assert roles == {
        "superset|dashboard:growth": {"role": "diagnostic", "probability": 0.88},
        "trino|table:events": {"role": "diagnostic", "probability": 0.88},
    }
    assert set(FakeClient.calls[-1]["questions"]) == {"role_0", "role_1"}


@pytest.mark.asyncio
async def test_jev_role_batch_preflight_uses_the_real_question_shape(monkeypatch):
    """Role classification cannot bypass the token guard with short probe text."""
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Choice", FakeScore)
    judger = JevJudger(
        api_key="synthetic-test-key",
        timeout=3,
        max_retries=0,
        max_input_tokens=3_000,
    )
    resources = [
        ResourceDescriptor(
            adapter="preset",
            resource=f"dashboard:{index}",
            kind="dashboard",
            title=f"Dashboard {index}",
            description="dashboard context " * 20,
            metadata={"catalog_note": "n" * 700, "scope": f"scope-{index}"},
        )
        for index in range(40)
    ]

    roles = await judger.classify_resource_roles("Understand business risk", resources)

    assert len(roles) == len(resources)
    request_tokens = [
        estimate_json_tokens(
            {
                "state": call["state"],
                "questions": judger._question_budget_payload(call["questions"]),
            }
        )
        for call in FakeClient.calls
    ]
    assert len(FakeClient.calls) > 1
    assert max(request_tokens) <= judger.max_input_tokens


@pytest.mark.asyncio
async def test_jev_compiles_and_judges_free_form_card_items(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(
        api_key="synthetic-test-key", timeout=3, evidence_role_classification=True
    )
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
    # Explicit role classification is an opt-in diagnostic path. The normal
    # product path sends Jev the frontier agent's evidence for one final policy
    # judgment instead of asking it to analyze each observation.
    assert len(FakeClient.calls) == 2
    judge_call = FakeClient.calls[1]
    assert set(judge_call["questions"]) == {
        "watch_0",
        "question_0",
        "evidence_0",
        "outcome",
    }
    assert result.evidence_findings[0].role == "driver"
    assert judge_call["state"]["card"]["what_to_watch"] == card.what_to_watch
    assert "insight_card" not in judge_call["state"]
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
    assert "onboarding_review" not in call["state"]["card"]
    assert "principal_tenant" not in call["state"]["card"]
    assert all(
        "destination" not in method
        for method in call["state"]["card"]["delivery_methods"]
    )


@pytest.mark.asyncio
async def test_jev_bounded_judgment_returns_typed_evidence_findings(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    monkeypatch.setattr(typesafe_sdk, "Noul", FakeNoul)
    judger = JevJudger(
        api_key="synthetic-test-key", timeout=3, evidence_role_classification=True
    )
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


@pytest.mark.asyncio
async def test_jev_wide_dashboard_chunks_input_and_keeps_all_evidence_findings(monkeypatch):
    """A wide connector snapshot must not become one provider-context request."""
    FakeClient.calls = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", FakeClient)
    judger = JevJudger(
        api_key="synthetic-test-key",
        timeout=3,
        max_retries=0,
        max_input_tokens=3_000,
        evidence_role_classification=True,
    )
    source = SourceRef(
        key="wide-dashboard",
        adapter="preset",
        resource="dashboard:wide",
        label="Wide dashboard",
    )
    card = InsightCard(
        id="wide-dashboard-card",
        title="Wide dashboard review",
        what_to_watch="Material business movement and the evidence that explains it.",
        why_watch="Notify the owner when trustworthy evidence warrants action.",
        watch_for=["A material condition is present."],
        questions=["What changed and what explains it?"],
        decision_guidance="Notify when evidence is material and trustworthy; investigate otherwise.",
        sources=[source],
        delivery_methods=[
            DeliveryMethod(
                key="owner",
                outcome=Outcome.NOTIFY,
                label="Owner",
                destination="agent://owner",
            )
        ],
    )
    observations = [
        Observation(
            source_key=source.key,
            subject_id=f"chart-{index}",
            subject_label=f"Chart {index}",
            metric=f"metric-{index % 12}",
            current=100 + index,
            baseline=90 + index,
            change_pct=10.0,
            dimensions={"region": f"region-{index % 6}"},
            attributes={"connector_payload": "x" * 1_500},
        )
        for index in range(48)
    ]
    state = {
        "card": card.execution_payload(),
        "insight_card": card.execution_payload(),
        "insight_plan": base_plan(card).model_dump(mode="json"),
        "sources": [
            {
                "source_key": source.key,
                "adapter": source.adapter,
                "resource": source.resource,
                "title": source.label,
                "metadata": {"raw_connector_error": "e" * 100_000},
            }
        ],
        "observations": [item.model_dump(mode="json") for item in observations],
        "evidence": [
            {
                "source_key": source.key,
                "subject_id": item.subject_id,
                "subject_label": item.subject_label,
                "statement": "detail " * 100,
                "values": {"metric": item.metric},
                "source_url": "https://provider.example/" + "u" * 500,
            }
            for item in observations
        ],
        "analyses": [
            {"source_key": source.key, "metric": f"metric-{index}", "delta": index}
            for index in range(24)
        ],
        "source_errors": [],
        "context": None,
        "numeric_conditions": [],
    }

    result = await judger.judge(state, card, base_plan(card), observations)

    request_tokens = [
        estimate_json_tokens(
            {
                "state": call["state"],
                "questions": judger._question_budget_payload(call["questions"]),
            }
        )
        for call in FakeClient.calls
    ]
    final_call = FakeClient.calls[-1]
    assert len(FakeClient.calls) > 2
    assert max(request_tokens) <= judger.max_input_tokens
    assert len(result.evidence_findings) == len(observations)
    assert "evidence_rollup" in final_call["state"]
    assert "observations" not in final_call["state"]
    assert "evidence" not in final_call["state"]
    assert final_call["state"]["evidence_rollup"]["classified_count"] == len(observations)

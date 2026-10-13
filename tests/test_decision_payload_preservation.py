from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
import typesafe_sdk

from evaluations.native_cadence_cases import build_cadence_scenario
from signalweave.compiler import base_plan
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    Observation,
    Outcome,
    QuestionResult,
    ResourceContract,
    ResourceSnapshot,
    SourceComparisonContract,
    SourceRef,
    WatchResult,
)
from signalweave.typesafe_adapter import (
    DEFAULT_MAX_JEV_INPUT_TOKENS,
    JevJudger,
    JevPayloadError,
    estimate_json_tokens,
)

CARD_SOURCE_REFS = [
    {
        "key": "source-company-mcp-resource-fd7ced0b3305cf92db4a",
        "adapter": "company_mcp",
        "resource": "resource-fd7ced0b3305cf92db4a",
        "label": "Northstar Executive Pulse",
        "required": True,
    },
    {
        "key": "source-company-mcp-resource-bc5e054e60461fb10b8e",
        "adapter": "company_mcp",
        "resource": "resource-bc5e054e60461fb10b8e",
        "label": "Northstar Web Funnel",
        "required": True,
    },
    {
        "key": "source-company-mcp-resource-2ecd7a55803804422a3e",
        "adapter": "company_mcp",
        "resource": "resource-2ecd7a55803804422a3e",
        "label": "Northstar Finance Daily",
        "required": True,
    },
    {
        "key": "source-company-mcp-resource-bcc430dd0048c951ef1a",
        "adapter": "company_mcp",
        "resource": "resource-bcc430dd0048c951ef1a",
        "label": "Northstar Support Operations",
        "required": True,
    },
]

DECISION_GUIDANCE = (
    "Retrospective review of archived monthly closes only, not a current alert. Preserve the "
    "sources' measurement dates and cutoffs; the replay gateway timestamp is not warehouse "
    "freshness. Use Executive Pulse's generated monthly channel ledger balances in USD as the "
    "metric of record; they are not actual order-line records and establish no unique orders, "
    "customers, settlement, or whole-company sales. Compare the previous complete calendar "
    "month. If Executive Pulse is unavailable or lacks the needed sales comparison, or its "
    "total does not reconcile to the complete declared channel partition, return "
    "insufficient_data and route to data trust. Ignore absolute source-reported net-sales "
    "changes below 10%. For a net-sales decline of at least 15%, notify leadership only when "
    "at least two sales channels decline and either source-reported Web Funnel conversion or "
    "Finance Daily revenue also declines. All other material movements, including declines "
    "from 10% to below 15%, declines without that corroboration, and increases outside the "
    "under-10% ignore band, default to investigate through analytics, not silence. Ignore "
    "routes to no destination. No severe-incident exception applies: no incident feed is "
    "approved, and Support backlog is not incident status or severity. Keep Sales, Web, "
    "Finance, and Support populations separate; never row-join or claim a shared cohort. "
    "Support backlog is diagnostic only."
)


def _captured_onboarding_card() -> InsightCard:
    return InsightCard.model_validate(
        {
            "id": "card-northstar-archived-monthly-close-policy-30222495",
            "title": "Northstar Archived Monthly Close Policy",
            "what_to_watch": (
                "Retrospectively assess Executive Pulse generated monthly channel-ledger net sales "
                "against the previous complete calendar month, with channel direction and separate "
                "Web Funnel conversion and Finance Daily revenue as corroboration. Keep Support "
                "backlog diagnostic only."
            ),
            "why_watch": (
                "Apply the reviewed owner policy to archived monthly-close fixture measurements. "
                "This is a retrospective review, not a current alert or statement of current company "
                "conditions. Preserve each source's measurement cutoff and keep Sales, Web, Finance, "
                "and Support populations separate."
            ),
            "watch_for": [
                "Executive Pulse total generated monthly net sales in USD and its complete channel partition",
                "Direction of each Executive Pulse sales channel",
                "Web Funnel source-reported conversion rate, treated as a separate population",
                "Finance Daily source-reported revenue, treated as a separate population",
                "Support backlog as a separate diagnostic measure, never incident status or severity",
            ],
            "questions": [],
            "numeric_conditions": [],
            "evidence_requirements": {},
            "decision_guidance": DECISION_GUIDANCE,
            "follow_up_guidance": "",
            "sources": CARD_SOURCE_REFS,
            "comparison_windows": ["previous_period"],
            "action_confidence_threshold": 0.7,
            "owner": "Northstar Outfitters Co.",
            "version": 1,
            "max_source_age_hours": None,
            "delivery_methods": [
                {
                    "key": "leadership",
                    "outcome": "notify",
                    "label": "Leadership",
                    "destination": "slack://simulation-leadership",
                    "instructions": "",
                },
                {
                    "key": "analytics",
                    "outcome": "investigate",
                    "label": "Analytics",
                    "destination": "slack://simulation-analytics",
                    "instructions": "",
                },
                {
                    "key": "data-trust",
                    "outcome": "insufficient_data",
                    "label": "Data trust",
                    "destination": "slack://simulation-data-trust",
                    "instructions": "",
                },
            ],
            "retrieval_mode": "fixed",
            "investigation_mode": "none",
            "max_investigation_sources": 3,
            "investigation_threshold": 0.6,
        }
    )


def _cadence_state(*, reverse_metadata: bool = False, card: InsightCard | None = None):
    scenario, _registration = build_cadence_scenario()
    card = card or _captured_onboarding_card()
    snapshots_by_resource = {
        snapshot["resource"]: snapshot
        for snapshot in scenario["public"]["periods"][0]["snapshots"].values()
    }
    sources = []
    observations = []
    evidence = []
    for source_ref in card.sources:
        raw = deepcopy(snapshots_by_resource[source_ref.resource])
        raw["source_key"] = source_ref.key
        if reverse_metadata:
            raw["metadata"] = dict(reversed(list(raw["metadata"].items())))
        for observation in raw["observations"]:
            observation["source_key"] = source_ref.key
        for item in raw["evidence"]:
            item["source_key"] = source_ref.key
        snapshot = ResourceSnapshot.model_validate(raw)
        sources.append(snapshot)
        observations.extend(snapshot.observations)
        evidence.extend(item.model_dump(mode="json") for item in snapshot.evidence)

    state = {
        "insight_plan": base_plan(card).model_dump(mode="json"),
        "sources": sources,
        "observations": [item.model_dump(mode="json") for item in observations],
        "evidence": evidence,
        "analyses": [],
        "source_errors": [],
        "numeric_conditions": [],
    }
    return state, card, observations, sources


class OfflineResponse:
    usage = SimpleNamespace(input_tokens=1, output_tokens=1)

    def __init__(self, questions):
        self.choices = {}
        self.nouls = {}
        for key in questions:
            if key == "outcome":
                self.choices[key] = SimpleNamespace(
                    choice="investigate",
                    probabilities={
                        "ignore": 0.05,
                        "investigate": 0.9,
                        "insufficient_data": 0.03,
                        "notify": 0.02,
                    },
                )
            elif key.startswith("watch_"):
                self.choices[key] = SimpleNamespace(
                    choice="unknown",
                    probabilities={"present": 0.1, "absent": 0.1, "unknown": 0.8},
                )
            elif key.startswith("question_"):
                self.nouls[key] = SimpleNamespace(noul=0.5)


class OfflineClient:
    calls = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def system_one(self, *, state, questions):
        self.calls.append({"state": state, "questions": questions})
        return OfflineResponse(questions)


@pytest.mark.asyncio
async def test_cadence_card_default_compaction_preserves_complete_decision_packet(monkeypatch):
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", OfflineClient)
    OfflineClient.calls = []
    judger = JevJudger(api_key="offline-test", max_input_tokens=DEFAULT_MAX_JEV_INPUT_TOKENS)
    first_state, card, observations, sources = _cadence_state()
    second_state, _, _, _ = _cadence_state(reverse_metadata=True)
    assert judger._request_over_budget(
        judger._lossless_judgment_state(first_state, card, observations), {}
    )

    await judger.judge(first_state, card, base_plan(card), observations)
    await judger.judge(second_state, card, base_plan(card), observations)

    assert len(observations) == 9
    assert len(card.watch_for) == 5
    assert len(DECISION_GUIDANCE) > 800
    assert DEFAULT_MAX_JEV_INPUT_TOKENS == 12_000
    first_call, second_call = OfflineClient.calls
    packet = first_call["state"]
    assert packet == second_call["state"]
    assert packet["card"]["decision_guidance"] == DECISION_GUIDANCE
    assert packet["card"]["watch_for"] == card.watch_for
    assert packet["card"]["comparison_windows"] == card.comparison_windows
    assert packet["observations"] == [item.model_dump(mode="json") for item in observations]
    assert len(packet["observations"]) == 9
    assert len(packet["evidence"]) == 9
    assert all(
        not {"baseline", "current", "change_pct"}.intersection(item.get("values", {}))
        for item in packet["evidence"]
    )
    plan = packet["insight_plan"]
    assert plan["_references"] == {
        "card_id": "card.id",
        "card_version": "card.version",
        "selected_source_keys": "card.sources[*].key",
        "comparison_windows": "card.comparison_windows",
        "watch_for": "card.watch_for",
        "questions": "card.questions",
        "delivery_method_keys": "card.delivery_methods[*].key",
    }
    assert plan["capabilities"] == base_plan(card).capabilities
    assert all(
        not judger._request_over_budget(call["state"], call["questions"])
        for call in OfflineClient.calls
    )
    assert judger.metrics.requests == len(OfflineClient.calls)

    expected_sources = {item.source_key: item for item in sources}
    for compact_source in packet["sources"]:
        expected = expected_sources[compact_source["source_key"]]
        assert compact_source["contract"] == expected.contract.model_dump(mode="json")
        assert len(str(compact_source["metadata"])) < len(str(expected.metadata))

    request_tokens = estimate_json_tokens(
        {
            "state": packet,
            "questions": judger._question_budget_payload(first_call["questions"]),
        }
    )
    assert request_tokens <= DEFAULT_MAX_JEV_INPUT_TOKENS


def test_compact_plan_keeps_values_that_are_not_exact_card_duplicates():
    _state, card, _observations, _sources = _cadence_state()
    plan = base_plan(card).model_dump(mode="json")
    plan["watch_for"] = ["A distinct execution-plan watch condition."]
    compact = JevJudger._compact_judgment_plan_payload(plan, JevJudger._judgment_card_payload(card))

    assert compact["watch_for"] == plan["watch_for"]
    assert "watch_for" not in compact["_references"]


@pytest.mark.asyncio
async def test_compact_packet_over_local_budget_fails_before_client_call(monkeypatch):
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", OfflineClient)
    OfflineClient.calls = []
    state, card, observations, _sources = _cadence_state()
    judger = JevJudger(api_key="offline-test", max_input_tokens=1_024)

    with pytest.raises(JevPayloadError, match="configured budget"):
        await judger.judge(state, card, base_plan(card), observations)

    assert OfflineClient.calls == []


def _foreign_generic_state(watch_count: int, *, policy: str = "Review stated monthly movement."):
    source_ref = SourceRef(
        key="telemetry|resource:monthly-generation",
        adapter="telemetry",
        resource="resource:monthly-generation",
        label="Monthly generation",
    )
    comparison = SourceComparisonContract(
        key="monthly-generation",
        metric="generation_mwh",
        definition="Total metered generation in megawatt-hours.",
        population="All metered sites in the fictional region.",
        unit="MWh",
        comparison_window="prior-month",
        coverage="complete",
        comparable=True,
        detail="Same reporting month boundaries and site population.",
        query_refs=["metered-generation-v1"],
    )
    contract = ResourceContract(
        tenant_id="test-tenant",
        domain="renewable-energy",
        scope="Fictional monthly generation ledger.",
        metric_names=["generation_mwh"],
        comparison_contracts=[comparison],
        available_comparison_windows=["prior-month"],
        population="All metered sites in the fictional region.",
        grain="One monthly total per region.",
        source_status="healthy",
    )
    source = ResourceSnapshot(
        source_key=source_ref.key,
        adapter=source_ref.adapter,
        resource=source_ref.resource,
        title=source_ref.label,
        metadata={"capture_id": "capture-01", "read_mode": "read-only"},
        source_url="simulation-ledger://renewables/monthly-generation",
        contract=contract,
    )
    observation = Observation(
        source_key=source_ref.key,
        subject_id="region-north",
        subject_label="Northern region",
        metric="generation_mwh",
        unit="MWh",
        current=120.5,
        baseline=100.25,
        previous=100.25,
        change_pct=20.1995012469,
        comparison_baselines={"prior-month": 100.25, "prior-year": 94.0},
        dimensions={"reporting_month": "2026-01", "region": "north"},
        freshness="Historical measurement window; query capture freshness is separate.",
        source_url=source.source_url,
        attributes={"coverage_ratio": 1.0, "precision": 0.1, "quality_status": "verified"},
    )
    card = InsightCard(
        id="monthly-generation-review",
        title="Monthly generation review",
        what_to_watch="Review source-reported monthly generation.",
        why_watch="Check each owner-authored condition against the source contract.",
        watch_for=[f"Condition {index:03d} is present." for index in range(watch_count)],
        questions=["Is the measurement interval stated?", "Is the source contract complete?"],
        decision_guidance=policy,
        sources=[source_ref],
        comparison_windows=["prior-month"],
        delivery_methods=[
            DeliveryMethod(
                key="analysis",
                outcome=Outcome.INVESTIGATE,
                label="Analysis",
                destination="local://analysis",
            )
        ],
    )
    state = {
        "insight_plan": base_plan(card).model_dump(mode="json"),
        "sources": [source],
        "observations": [observation.model_dump(mode="json")],
        "evidence": [],
    }
    return state, card, [observation], [source]


@pytest.mark.asyncio
async def test_one_hundred_foreign_watch_items_batch_over_identical_complete_state(monkeypatch):
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", OfflineClient)
    OfflineClient.calls = []
    state, card, observations, sources = _foreign_generic_state(100)
    judger = JevJudger(api_key="offline-test", max_input_tokens=DEFAULT_MAX_JEV_INPUT_TOKENS)

    result = await judger.judge(state, card, base_plan(card), observations)

    calls = OfflineClient.calls
    assert len(calls) > 1
    assert all(call["state"] == calls[0]["state"] for call in calls)
    packet = calls[0]["state"]
    assert packet["card"]["decision_guidance"] == card.decision_guidance
    assert packet["card"]["watch_for"] == card.watch_for
    assert packet["observations"] == [item.model_dump(mode="json") for item in observations]
    assert packet["sources"][0]["contract"] == sources[0].contract.model_dump(mode="json")
    assert packet["insight_plan"]["_references"]["watch_for"] == "card.watch_for"

    requested_ids = [key for call in calls for key in call["questions"]]
    expected_ids = [
        *(f"watch_{index}" for index in range(100)),
        "question_0",
        "question_1",
        "outcome",
    ]
    assert sorted(requested_ids) == sorted(expected_ids)
    assert requested_ids.count("outcome") == 1
    assert all(not judger._request_over_budget(call["state"], call["questions"]) for call in calls)
    for prior, following in zip(calls, calls[1:], strict=False):
        first_next_question = next(iter(following["questions"].items()))
        enlarged = {**prior["questions"], first_next_question[0]: first_next_question[1]}
        assert judger._request_over_budget(prior["state"], enlarged)

    assert result.outcome == Outcome.INVESTIGATE
    assert len(result.watch_results) == 100
    assert [item.key for item in result.watch_results] == [f"watch_{i}" for i in range(100)]
    assert [item.key for item in result.question_results] == ["question_0", "question_1"]
    assert all(isinstance(item, WatchResult) for item in result.watch_results)
    assert all(isinstance(item, QuestionResult) for item in result.question_results)
    assert judger.metrics.requests == len(calls)
    assert judger.metrics.input_tokens == len(calls)
    assert judger.metrics.output_tokens == len(calls)


@pytest.mark.asyncio
async def test_individual_question_over_budget_fails_before_any_provider_call(monkeypatch):
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", OfflineClient)
    OfflineClient.calls = []
    state, card, observations, _sources = _foreign_generic_state(1)
    state["context"] = {"source_context": "x" * 40_000}
    judger = JevJudger(api_key="offline-test", max_input_tokens=DEFAULT_MAX_JEV_INPUT_TOKENS)

    with pytest.raises(JevPayloadError, match="configured budget"):
        await judger.judge(state, card, base_plan(card), observations)

    assert OfflineClient.calls == []
    assert judger.metrics.requests == 0


def test_unclassified_observations_are_not_counted_as_classified():
    state, card, observations, sources = _cadence_state()
    state["sources"] = sources
    summary = JevJudger._compact_synthesis_state(
        state,
        card,
        base_plan(card),
        observations,
        {},
    )

    assert summary["evidence_rollup"]["observation_count"] == 9
    assert summary["evidence_rollup"]["classified_count"] == 0
    assert summary["evidence_rollup"]["unclassified_count"] == 9


def test_foreign_domain_contract_survives_lower_budget_metadata_compaction():
    source_ref = SourceRef(
        key="telemetry|resource:generation-monthly",
        adapter="telemetry",
        resource="resource:generation-monthly",
        label="Monthly renewable generation",
    )
    comparison = SourceComparisonContract(
        key="monthly-generation",
        metric="generation_mwh",
        definition="Total metered generation in megawatt-hours.",
        population="All metered sites in the fictional region.",
        unit="MWh",
        comparison_window="prior-month",
        coverage="complete",
        comparable=True,
        detail="Same reporting month boundaries and site population.",
        query_refs=["metered-generation-v1"],
    )
    contract = ResourceContract(
        tenant_id="test-tenant",
        domain="renewable-energy",
        scope="Fictional monthly generation ledger.",
        metric_names=["generation_mwh"],
        comparison_contracts=[comparison],
        available_comparison_windows=["prior-month"],
        population="All metered sites in the fictional region.",
        grain="One monthly total per region.",
        source_status="healthy",
    )
    source = ResourceSnapshot(
        source_key=source_ref.key,
        adapter=source_ref.adapter,
        resource=source_ref.resource,
        title=source_ref.label,
        metadata={
            "capture_id": "capture-01",
            "capture_history": [{"capture_id": "capture-01", "detail": "read-only"}],
        },
        source_url="simulation-ledger://renewables/monthly-generation",
        contract=contract,
    )
    observation = Observation(
        source_key=source_ref.key,
        subject_id="region-north",
        subject_label="Northern region",
        metric="generation_mwh",
        unit="MWh",
        current=120.5,
        baseline=100.25,
        previous=100.25,
        change_pct=20.1995012469,
        comparison_baselines={"prior-month": 100.25, "prior-year": 94.0},
        dimensions={"reporting_month": "2026-01", "region": "north"},
        freshness="Historical measurement window; query capture freshness is separate.",
        source_url=source.source_url,
        attributes={"coverage_ratio": 1.0, "precision": 0.1, "quality_status": "verified"},
    )
    card = InsightCard(
        id="monthly-generation-review",
        title="Monthly generation review",
        what_to_watch="Review source-reported monthly generation.",
        why_watch="Confirm movement with its complete source contract.",
        watch_for=["The source-reported monthly generation total."],
        decision_guidance="Investigate material source-reported movement.",
        sources=[source_ref],
        comparison_windows=["prior-month"],
        delivery_methods=[
            DeliveryMethod(
                key="analysis",
                outcome=Outcome.INVESTIGATE,
                label="Analysis",
                destination="local://analysis",
            )
        ],
    )
    state = {
        "sources": [source],
        "observations": [observation.model_dump(mode="json")],
        "evidence": [],
        "insight_plan": base_plan(card).model_dump(mode="json"),
    }
    judger = JevJudger(api_key="offline-test", max_input_tokens=4_000)

    packet = JevJudger._compact_judgment_state(state, card, [observation])

    assert packet["sources"][0]["contract"] == contract.model_dump(mode="json")
    assert packet["observations"][0] == observation.model_dump(mode="json")
    assert packet["card"]["comparison_windows"] == ["prior-month"]
    assert not judger._request_over_budget(packet, {})


def test_evidence_deduplication_prefers_core_float_over_conflicting_attribute():
    observation = Observation(
        source_key="ledger",
        subject_id="amount",
        subject_label="Gross revenue",
        metric="gross_revenue",
        current=12.5,
        baseline=10.25,
        attributes={"current": 999.0},
    )
    evidence = Evidence(
        source_key="ledger",
        subject_id="amount",
        subject_label="Gross revenue",
        statement="The source reports gross revenue.",
        values={"current": 999.0},
    )

    result = JevJudger._judgment_evidence_payload({"evidence": [evidence]}, [observation])

    assert result[0]["values"] == {"current": 999.0}


def test_missing_metric_evidence_requires_matching_label_but_explicit_metric_binds():
    observations = [
        Observation(
            source_key="ledger",
            subject_id="amount",
            subject_label="Gross revenue",
            metric="gross_revenue",
            current=42.5,
            baseline=40.0,
        ),
        Observation(
            source_key="ledger",
            subject_id="amount",
            subject_label="Net revenue",
            metric="net_revenue",
            current=42.5,
            baseline=40.0,
        ),
    ]
    evidence = [
        Evidence(
            source_key="ledger",
            subject_id="amount",
            subject_label="Gross/net amount",
            statement="An ambiguously labeled amount.",
            values={"current": 42.5, "baseline": 40.0},
        ),
        Evidence(
            source_key="ledger",
            subject_id="amount",
            subject_label="Gross revenue",
            statement="The gross revenue amount.",
            values={"current": 42.5, "baseline": 40.0},
        ),
        Evidence(
            source_key="ledger",
            subject_id="amount",
            subject_label="Net amount",
            statement="The explicitly bound net revenue amount.",
            values={"metric": "net_revenue", "current": 42.5, "baseline": 40.0},
        ),
    ]

    result = JevJudger._judgment_evidence_payload({"evidence": evidence}, observations)

    assert result[0]["values"] == {"current": 42.5, "baseline": 40.0}
    assert result[1]["values"] == {}
    assert result[2]["values"] == {}


def test_chunked_role_evidence_uses_global_metricless_label_binding():
    observations = [
        Observation(
            source_key="ledger",
            subject_id="amount",
            subject_label="Gross revenue",
            metric="gross_revenue",
            current=42.5,
        ),
        Observation(
            source_key="ledger",
            subject_id="amount",
            subject_label="Net revenue",
            metric="net_revenue",
            current=42.5,
        ),
    ]
    evidence = {
        "source_key": "ledger",
        "subject_id": "amount",
        "subject_label": "Gross revenue",
        "statement": "Gross revenue reported for the period.",
        "values": {"current": 42.5},
        "origin": "source",
    }
    state = {"evidence": [evidence]}

    gross_chunk = JevJudger._evidence_for_role_chunk(state, observations[:1], observations)
    net_chunk = JevJudger._evidence_for_role_chunk(state, observations[1:], observations)

    assert gross_chunk == [evidence]
    assert net_chunk == []

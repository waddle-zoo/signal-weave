from datetime import datetime, timedelta, timezone

import pytest

from evaluations.cases import load_evaluation_cases
from signalweave.engine import InsightEngine
from signalweave.models import (
    ContextFact,
    ContextSnapshot,
    DeliveryMethod,
    InsightCard,
    InsightPlan,
    InsightResult,
    Observation,
    Outcome,
    ResourceContract,
    ResourceSnapshot,
    SourceRef,
)


def evaluation_catalog():
    return {case.id: case for case in load_evaluation_cases()}


class JevTestDouble:
    """Test-only stand-in for Jev; expected labels live in evaluations/data."""

    name = "jev-test-double"

    async def compile_plan(self, state, card):
        del state
        return {
            "capabilities": ["percent_change", "baseline_comparison", "freshness_check"],
            "baseline": card.comparison_windows[0],
        }

    async def judge(self, state, card, plan, observations):
        case = next(case for case in load_evaluation_cases() if case.card.id == card.id)
        return InsightResult(
            card_id=card.id,
            outcome=Outcome(case.expected_outcome),
            summary="Test double result from the checked-in labeled case.",
            rationale="Test double result from the checked-in labeled case.",
            confidence=0.99,
            probabilities={case.expected_outcome: 0.99, "other": 0.01},
            delivery_methods=[
                method
                for method in card.delivery_methods
                if method.key in case.expected_delivery_methods
            ],
            evidence=state["evidence"],
            observations=observations,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )


class SafetyTestDouble:
    """Test-only semantic stub used to exercise code-owned safety gates."""

    name = "jev-safety-test-double"

    async def compile_plan(self, state, card):
        del state
        return {
            "capabilities": ["percent_change", "baseline_comparison", "freshness_check"],
            "baseline": card.comparison_windows[0],
        }

    async def judge(self, state, card, plan, observations):
        del plan
        assert all(isinstance(item, dict) for item in state["evidence"])
        return InsightResult(
            card_id=card.id,
            outcome=Outcome.INVESTIGATE,
            summary="Test-only neutral semantic result.",
            rationale="Test-only neutral semantic result.",
            confidence=0.99,
            probabilities={Outcome.INVESTIGATE.value: 0.99},
            evidence=state["evidence"],
            observations=observations,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )


def card_for(
    *,
    card_id: str,
    title: str,
    source: SourceRef,
    delivery_methods: list[DeliveryMethod] | None = None,
    watch_for: list[str] | None = None,
    questions: list[str] | None = None,
    comparison_windows: list[str] | None = None,
    **kwargs,
) -> InsightCard:
    return InsightCard(
        id=card_id,
        title=title,
        what_to_watch=kwargs.pop("what_to_watch", title),
        why_watch=kwargs.pop("why_watch", "Support a defined operating decision."),
        sources=[source],
        delivery_methods=delivery_methods or [],
        watch_for=watch_for or [],
        questions=questions or [],
        comparison_windows=comparison_windows
        or ["previous_period", "trailing_4_period_average"],
        **kwargs,
    )


async def evaluate(scenario: str):
    case = evaluation_catalog()[scenario]
    return await InsightEngine(JevTestDouble()).evaluate(case.card, case.resources)


async def test_revenue_decline_is_notified():
    run = await evaluate("revenue_decline")
    assert run.result.outcome == Outcome.NOTIFY
    assert [method.key for method in run.result.delivery_methods] == ["revenue-operations"]
    assert run.result.evidence


async def test_seasonal_movement_is_ignored():
    run = await evaluate("seasonal_normal")
    assert run.result.outcome == Outcome.IGNORE
    assert run.result.delivery_methods == []


async def test_mobile_issue_delivers_to_all_matching_methods():
    run = await evaluate("mobile_conversion")
    assert run.result.outcome == Outcome.NOTIFY
    assert [method.key for method in run.result.delivery_methods] == [
        "growth",
        "engineering-oncall",
    ]


async def test_stale_data_escalates_to_configured_method():
    run = await evaluate("data_freshness")
    assert run.result.outcome == Outcome.ESCALATE
    assert [method.key for method in run.result.delivery_methods] == ["data-platform"]
    assert run.result.evidence[0].values["freshness"]


async def test_stale_contract_status_cannot_notify_without_freshness_attribute():
    class NotifyJudger(SafetyTestDouble):
        async def judge(self, state, card, plan, observations):
            result = await super().judge(state, card, plan, observations)
            return result.model_copy(update={"outcome": Outcome.NOTIFY, "confidence": 0.99})

    source = SourceRef(
        key="stale-contract",
        adapter="sql",
        resource="query:metric",
        label="Stale metric",
    )
    card = card_for(
        card_id="card-stale-contract",
        title="Stale contract metric",
        source=source,
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Operations",
                destination="slack://ops",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        contract=ResourceContract(source_status="stale"),
        observations=[
            Observation(
                source_key=source.key,
                subject_id="metric",
                subject_label="Metric",
                metric="metric",
                current=82,
                baseline=100,
                change_pct=-18,
            )
        ],
    )

    run = await InsightEngine(NotifyJudger()).evaluate(card, [resource])

    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.delivery_methods == []


async def test_unverified_context_cannot_authorize_automatic_action():
    class NotifyJudger(SafetyTestDouble):
        async def judge(self, state, card, plan, observations):
            result = await super().judge(state, card, plan, observations)
            return result.model_copy(update={"outcome": Outcome.NOTIFY, "confidence": 0.99})

    source = SourceRef(
        key="context-source",
        adapter="sql",
        resource="query:metric",
        label="Metric",
    )
    card = card_for(
        card_id="card-unverified-context",
        title="Context-sensitive metric",
        source=source,
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Operations",
                destination="slack://ops",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[
            Observation(
                source_key=source.key,
                subject_id="metric",
                subject_label="Metric",
                metric="metric",
                current=82,
                baseline=100,
                change_pct=-18,
            )
        ],
    )
    context = ContextSnapshot(
        provider="caller",
        version="unverified-1",
        trust="unverified",
        facts=[
            ContextFact(
                fact_id="fact-1",
                subject_ref="sql|query:metric",
                relation="owned_by",
                object_ref="team:ops",
                statement="Operations owns this metric.",
            )
        ],
    )

    run = await InsightEngine(NotifyJudger()).evaluate(card, [resource], context)

    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.delivery_methods == []


async def test_ambiguous_source_cannot_take_an_automatic_route():
    class AmbiguousNotifyJudger(SafetyTestDouble):
        async def judge(self, state, card, plan, observations):
            result = await super().judge(state, card, plan, observations)
            return result.model_copy(update={"outcome": Outcome.NOTIFY, "confidence": 0.99})

    source = SourceRef(
        key="ambiguous-source",
        adapter="sql",
        resource="query:metric",
        label="Ambiguous metric",
    )
    card = card_for(
        card_id="card-ambiguous-source",
        title="Ambiguous metric comparison",
        source=source,
        watch_for=["The metric definition is comparable."],
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Operations",
                destination="slack://ops",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[
            Observation(
                source_key=source.key,
                subject_id="metric",
                subject_label="Metric",
                metric="metric",
                current=82,
                baseline=100,
                change_pct=-18,
                attributes={"source_status": "ambiguous"},
            )
        ],
    )
    run = await InsightEngine(AmbiguousNotifyJudger()).evaluate(card, [resource])
    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.delivery_methods == []


async def test_low_confidence_notify_is_safely_downgraded():
    class LowConfidenceJudger(JevTestDouble):
        name = "test-low-confidence"

        async def judge(self, state, card, plan, observations):
            result = await super().judge(state, card, plan, observations)
            return result.model_copy(update={"outcome": Outcome.NOTIFY, "confidence": 0.2})

    case = evaluation_catalog()["revenue_decline"]
    run = await InsightEngine(LowConfidenceJudger()).evaluate(case.card, case.resources)
    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.delivery_methods == []


async def test_missing_baseline_is_not_treated_as_ignore():
    source = SourceRef(
        key="current-source",
        adapter="sql",
        resource="query:current",
        label="Current value query",
    )
    card = card_for(
        card_id="card-no-baseline",
        title="Current-only insight",
        source=source,
        watch_for=["The current value can be compared to a prior value."],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[
            Observation(
                source_key=source.key,
                subject_id="current-value",
                subject_label="Current value",
                metric="current_value",
                current=100,
            )
        ],
    )
    run = await InsightEngine(SafetyTestDouble()).evaluate(card, [resource])
    assert run.result.outcome == Outcome.INSUFFICIENT_DATA


async def test_unavailable_comparison_window_preserves_adapter_baseline():
    class TrailingWindowJudger(SafetyTestDouble):
        async def compile_plan(self, state, card):
            del state
            return {
                "capabilities": ["percent_change", "baseline_comparison"],
                "baseline": card.comparison_windows[-1],
            }

    source = SourceRef(
        key="single-window-source",
        adapter="sql",
        resource="query:metric",
        label="Metric query",
    )
    card = card_for(
        card_id="card-single-window",
        title="Single-window comparison",
        source=source,
        comparison_windows=["previous_period", "trailing_4_period_average"],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[
            Observation(
                source_key=source.key,
                subject_id="metric",
                subject_label="Metric",
                metric="metric",
                current=110,
                baseline=100,
            )
        ],
    )
    run = await InsightEngine(TrailingWindowJudger()).evaluate(card, [resource])
    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.observations[0].baseline == 100
    assert run.result.observations[0].change_pct == 10


async def test_source_failure_is_not_treated_as_ignore():
    source = SourceRef(
        key="broken-query",
        adapter="sql",
        resource="query:revenue",
        label="Revenue query",
    )
    card = card_for(
        card_id="card-source-error",
        title="Unavailable source insight",
        source=source,
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Ops",
                destination="slack://ops",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        error="query timeout",
    )
    run = await InsightEngine(SafetyTestDouble()).evaluate(card, [resource])
    assert run.result.outcome == Outcome.INSUFFICIENT_DATA
    assert run.result.delivery_methods == []
    assert "timeout" in run.result.evidence[-1].statement


async def test_partial_required_source_is_not_automatically_interpreted():
    source = SourceRef(
        key="partial-dashboard",
        adapter="superset",
        resource="dashboard:revenue",
        label="Revenue dashboard",
    )
    card = card_for(
        card_id="card-partial-dashboard",
        title="Partial dashboard",
        source=source,
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Ops",
                destination="slack://ops",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        metadata={
            "data_quality": {
                "status": "partial",
                "chart_count": 2,
                "charts_with_observations": 1,
                "chart_errors": ["Chart 2 unavailable"],
                "missing_baseline_chart_ids": [],
            }
        },
        observations=[
            Observation(
                source_key=source.key,
                subject_id="revenue",
                subject_label="Revenue",
                metric="revenue",
                current=110,
                baseline=100,
                change_pct=10,
            )
        ],
    )

    run = await InsightEngine(SafetyTestDouble()).evaluate(card, [resource])
    assert run.result.outcome == Outcome.INSUFFICIENT_DATA
    assert run.result.delivery_methods == []
    assert any("partial evidence" in item.statement for item in run.result.evidence)


async def test_optional_related_source_does_not_block_required_evidence():
    required = SourceRef(
        key="dashboard-anchor",
        adapter="superset",
        resource="dashboard:anchor",
        label="Dashboard anchor",
    )
    related = SourceRef(
        key="related-context",
        adapter="superset",
        resource="dashboard:related",
        label="Related context",
        required=False,
    )
    card = card_for(
        card_id="card-optional-context",
        title="Optional context",
        source=required,
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Operations",
                destination="slack://ops",
            )
        ],
    ).model_copy(update={"sources": [required, related]})

    class NotifyJudger(SafetyTestDouble):
        async def judge(self, state, card, plan, observations):
            result = await super().judge(state, card, plan, observations)
            return result.model_copy(update={"outcome": Outcome.NOTIFY, "confidence": 0.99})

    resources = [
        ResourceSnapshot(
            source_key=required.key,
            adapter=required.adapter,
            resource=required.resource,
            title=required.label,
            observations=[
                Observation(
                    source_key=required.key,
                    subject_id="revenue",
                    subject_label="Revenue",
                    metric="revenue",
                    current=110,
                    baseline=100,
                    change_pct=10,
                )
            ],
        ),
        ResourceSnapshot(
            source_key=related.key,
            adapter=related.adapter,
            resource=related.resource,
            title=related.label,
            observations=[
                Observation(
                    source_key=related.key,
                    subject_id="context",
                    subject_label="Context",
                    metric="context",
                    current=12,
                )
            ],
        ),
    ]

    run = await InsightEngine(NotifyJudger()).evaluate(card, resources)
    assert run.result.outcome == Outcome.NOTIFY
    assert [method.key for method in run.result.delivery_methods] == ["ops"]


async def test_empty_required_source_is_not_automatic():
    source = SourceRef(
        key="empty-source",
        adapter="sql",
        resource="query:revenue",
        label="Revenue query",
    )
    card = card_for(
        card_id="card-empty-source",
        title="Empty source insight",
        source=source,
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Ops",
                destination="slack://ops",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
    )
    run = await InsightEngine(SafetyTestDouble()).evaluate(card, [resource])
    assert run.result.outcome == Outcome.INSUFFICIENT_DATA
    assert run.result.delivery_methods == []
    assert "no observations or evidence" in run.result.evidence[-1].statement


async def test_old_required_source_snapshot_is_not_automatic():
    source = SourceRef(
        key="old-source",
        adapter="sql",
        resource="query:revenue",
        label="Revenue query",
    )
    card = card_for(
        card_id="card-old-source",
        title="Old source insight",
        source=source,
        delivery_methods=[
            DeliveryMethod(
                key="ops",
                outcome=Outcome.NOTIFY,
                label="Ops",
                destination="slack://ops",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        captured_at=datetime.now(timezone.utc) - timedelta(hours=25),
        observations=[
            Observation(
                source_key=source.key,
                subject_id="revenue",
                subject_label="Revenue",
                metric="revenue",
                current=90,
                baseline=100,
                change_pct=-10,
            )
        ],
    )
    run = await InsightEngine(SafetyTestDouble()).evaluate(card, [resource])
    assert run.result.outcome == Outcome.INSUFFICIENT_DATA
    assert run.result.delivery_methods == []
    assert "hours old" in run.result.evidence[-1].statement


async def test_semantic_outcome_without_matching_delivery_method_is_downgraded():
    class UnconfiguredNotifyJudger(SafetyTestDouble):
        async def judge(self, state, card, plan, observations):
            result = await super().judge(state, card, plan, observations)
            return result.model_copy(update={"outcome": Outcome.NOTIFY})

    source = SourceRef(
        key="signal",
        adapter="sql",
        resource="query:signal",
        label="Signal",
    )
    card = card_for(card_id="card-unconfigured-notify", title="Signal", source=source)
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[
            Observation(
                source_key=source.key,
                subject_id="signal",
                subject_label="Signal",
                metric="signal",
                current=1,
                baseline=1,
                change_pct=0,
            )
        ],
    )
    run = await InsightEngine(UnconfiguredNotifyJudger()).evaluate(card, [resource])
    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.delivery_methods == []
    assert "unavailable outcome" in run.result.rationale


async def test_selected_comparison_window_recomputes_change():
    source = SourceRef(
        key="metric-source",
        adapter="sql",
        resource="query:metric",
        label="Metric",
    )
    card = card_for(
        card_id="card-trailing-baseline",
        title="Trailing baseline insight",
        source=source,
        comparison_windows=["trailing_4_period_average"],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[
            Observation(
                source_key=source.key,
                subject_id="metric",
                subject_label="Metric",
                metric="metric",
                current=150,
                baseline=100,
                change_pct=50,
                comparison_baselines={"trailing_4_period_average": 120},
            )
        ],
    )
    run = await InsightEngine(SafetyTestDouble()).evaluate(card, [resource])
    observation = run.result.observations[0]
    assert run.plan.comparison_windows == ["trailing_4_period_average"]
    assert observation.baseline == 120
    assert observation.change_pct == 25.0


async def test_stored_compiled_plan_is_used_without_recompiling():
    class CompileMustNotRun(SafetyTestDouble):
        async def compile_plan(self, state, card):
            raise AssertionError("an approved stored plan must not be recompiled")

    source = SourceRef(
        key="stored-source",
        adapter="sql",
        resource="query:stored",
        label="Stored source",
    )
    plan = InsightPlan(
        card_id="card-stored-plan",
        selected_source_keys=[source.key],
        comparison_windows=["previous_period"],
        capabilities=["percent_change"],
        watch_for=[],
        questions=[],
        delivery_method_keys=[],
        compiled_by="jev-onboarding-test-double",
        card_scope="Investigate this stored plan.",
    )
    card = InsightCard(
        id=plan.card_id,
        title="Stored plan insight",
        what_to_watch="Stored metric movement.",
        why_watch="Verify the persisted compiled plan is used.",
        sources=[source],
        compiled_plan=plan,
        status="approved",
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[
            Observation(
                source_key=source.key,
                subject_id="stored",
                subject_label="Stored metric",
                metric="stored_metric",
                current=110,
                baseline=100,
                change_pct=10,
            )
        ],
    )
    run = await InsightEngine(CompileMustNotRun()).evaluate(card, [resource])
    assert run.plan == plan


def test_card_rejects_compiled_plan_from_another_version():
    source = SourceRef(
        key="versioned-source",
        adapter="sql",
        resource="query:versioned",
        label="Versioned source",
    )
    plan = InsightPlan(
        card_id="card-versioned",
        selected_source_keys=[source.key],
        comparison_windows=["previous_period"],
        capabilities=["percent_change"],
        card_scope="Versioned card.",
    )
    with pytest.raises(ValueError, match="card version"):
        InsightCard(
            id=plan.card_id,
            title="Versioned insight",
            what_to_watch="A versioned signal.",
            why_watch="Verify that a stale plan cannot be reused.",
            sources=[source],
            version=2,
            compiled_plan=plan,
        )


def test_card_requires_unique_delivery_methods():
    source = SourceRef(
        key="source",
        adapter="sql",
        resource="query:signal",
        label="Signal",
    )
    with pytest.raises(ValueError, match="delivery method keys"):
        card_for(
            card_id="duplicate-delivery-methods",
            title="Duplicate delivery methods",
            source=source,
            delivery_methods=[
                DeliveryMethod(key="ops", outcome=Outcome.NOTIFY, label="Ops", destination="#ops"),
                DeliveryMethod(key="ops", outcome=Outcome.ESCALATE, label="Ops again", destination="#ops"),
            ],
        )


async def test_plan_compilation_is_bounded():
    run = await evaluate("revenue_decline")
    assert run.plan.capabilities
    assert all(capability != "arbitrary_sql" for capability in run.plan.capabilities)


async def test_unfamiliar_metric_flows_through_without_metric_specific_logic():
    source = SourceRef(
        key="latency-source",
        adapter="superset",
        resource="chart:latency-p95",
        label="P95 API latency",
    )
    card = card_for(
        card_id="card-api-latency",
        title="API latency insight",
        source=source,
        what_to_watch="P95 API latency.",
        why_watch="Escalate a platform issue when the latency movement is actionable.",
        watch_for=["P95 API latency increases materially."],
        delivery_methods=[
            DeliveryMethod(
                key="platform",
                outcome=Outcome.NOTIFY,
                label="Platform",
                destination="slack://platform",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=[
            Observation(
                source_key=source.key,
                subject_id="latency-p95",
                subject_label="P95 API latency",
                metric="p95_api_latency",
                unit="milliseconds",
                current=900,
                baseline=500,
                change_pct=80,
            )
        ],
    )
    run = await InsightEngine(SafetyTestDouble()).evaluate(card, [resource])
    assert run.plan.capabilities == ["percent_change", "baseline_comparison", "freshness_check"]
    assert run.result.observations[0].metric == "p95_api_latency"
    assert run.result.evidence[0].values["change_pct"] == 80


async def test_heterogeneous_sources_are_composed_without_provider_logic():
    sources = [
        SourceRef(key="exec-dashboard", adapter="superset", resource="dashboard:7", label="Executive dashboard"),
        SourceRef(key="quality-query", adapter="sql", resource="query:data-quality", label="Data quality query"),
        SourceRef(key="load-dag", adapter="airflow", resource="dag:warehouse-load", label="Warehouse load DAG"),
        SourceRef(key="table-check", adapter="table", resource="table:warehouse.orders", label="Orders table"),
    ]
    resources = [
        ResourceSnapshot(
            source_key=source.key,
            adapter=source.adapter,
            resource=source.resource,
            title=source.label,
            observations=[
                Observation(
                    source_key=source.key,
                    subject_id=source.key,
                    subject_label=source.label,
                    metric="health_signal",
                    current=110,
                    baseline=100,
                    change_pct=10,
                )
            ],
            metadata={"provider": source.adapter},
        )
        for source in sources
    ]
    card = InsightCard(
        id="card-heterogeneous",
        title="Cross-system order health",
        what_to_watch="The dashboard, data quality query, load DAG, and table checks.",
        why_watch="Investigate when these sources disagree.",
        watch_for=["The sources disagree about order health."],
        questions=["Which source is most relevant to the discrepancy?"],
        sources=sources,
    )
    run = await InsightEngine(SafetyTestDouble()).evaluate(card, resources)
    assert run.plan.selected_source_keys == [source.key for source in sources]
    assert {observation.source_key for observation in run.result.observations} == {
        source.key for source in sources
    }
    assert run.resources[1].metadata["provider"] == "sql"


async def test_all_observations_are_sent_even_when_only_some_are_priority():
    source = SourceRef(
        key="many-metrics",
        adapter="superset",
        resource="dashboard:many",
        label="Many metrics",
    )
    card = card_for(
        card_id="card-many-metrics",
        title="Many metrics",
        source=source,
        watch_for=["The metric that matters to the operating decision is identified."],
        questions=["Which metric is off course?", "Why might it be off course?"],
    )
    observations = [
        Observation(
            source_key=source.key,
            subject_id=f"metric-{index}",
            subject_label=f"Metric {index}",
            metric=f"metric_{index}",
            current=100 + index,
            baseline=100,
            change_pct=0 if index == 0 else float(index),
        )
        for index in range(100)
    ]
    resource = ResourceSnapshot(
        source_key=source.key,
        adapter=source.adapter,
        resource=source.resource,
        title=source.label,
        observations=observations,
    )
    seen: dict[str, object] = {}

    class InspectingJudger(SafetyTestDouble):
        async def judge(self, state, card, plan, observations):
            seen["state_observation_count"] = len(state["observations"])
            seen["state_watch_for"] = state["card"]["watch_for"]
            seen["state_questions"] = state["card"]["questions"]
            return await super().judge(state, card, plan, observations)

    run = await InsightEngine(InspectingJudger()).evaluate(card, [resource])
    assert seen["state_observation_count"] == 100
    assert seen["state_watch_for"] == card.watch_for
    assert seen["state_questions"] == card.questions
    assert len(run.result.observations) == 100

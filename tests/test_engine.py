import pytest

from evaluations.cases import load_evaluation_cases
from semantic_monitor.engine import MonitorEngine
from semantic_monitor.models import (
    Decision,
    MonitorWorkflow,
    Observation,
    Outcome,
    ResourceSnapshot,
    SourceRef,
)


def evaluation_catalog():
    return {case.id: case for case in load_evaluation_cases()}


class JevTestDouble:
    """Test-only stand-in for Jev; expected labels live in evaluations/data."""

    name = "jev-test-double"

    async def compile_plan(self, state, workflow):
        del state, workflow
        return {"operations": ["percent_change", "baseline_comparison", "freshness_check"]}

    async def judge(self, state, workflow, plan, observations):
        del plan
        case = next(
            case for case in load_evaluation_cases() if case.workflow.id == workflow.id
        )
        return Decision(
            outcome=case.expected_outcome,
            recipient_key=case.expected_recipient,
            rationale="Test double result from the checked-in labeled case.",
            confidence=0.99,
            probabilities={case.expected_outcome: 0.99, "other": 0.01},
            evidence=state["evidence"],
            observations=observations,
            workflow_id=workflow.id,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )


class SafetyTestDouble:
    """Test-only semantic stub used to exercise code-owned safety gates."""

    name = "jev-safety-test-double"

    async def compile_plan(self, state, workflow):
        del state, workflow
        return {"operations": ["percent_change", "baseline_comparison", "freshness_check"]}

    async def judge(self, state, workflow, plan, observations):
        del plan
        assert all(isinstance(item, dict) for item in state["evidence"])
        return Decision(
            outcome=Outcome.INVESTIGATE,
            rationale="Test-only neutral semantic result.",
            confidence=0.99,
            probabilities={Outcome.INVESTIGATE.value: 0.99},
            evidence=state["evidence"],
            observations=observations,
            workflow_id=workflow.id,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )


async def evaluate(scenario: str):
    case = evaluation_catalog()[scenario]
    return await MonitorEngine(JevTestDouble()).evaluate(case.workflow, case.resources)


async def test_revenue_decline_is_notified():
    result = await evaluate("revenue_decline")
    assert result.decision.outcome == Outcome.NOTIFY
    assert result.decision.recipient_key == "revenue-operations"
    assert result.decision.evidence


async def test_seasonal_movement_is_ignored():
    result = await evaluate("seasonal_normal")
    assert result.decision.outcome == Outcome.IGNORE


async def test_mobile_issue_is_notified():
    result = await evaluate("mobile_conversion")
    assert result.decision.outcome == Outcome.NOTIFY
    assert result.decision.recipient_key == "growth"


async def test_stale_data_escalates():
    result = await evaluate("data_freshness")
    assert result.decision.outcome == Outcome.ESCALATE
    assert result.decision.evidence[0].values["freshness"]


async def test_low_confidence_notify_is_safely_downgraded():
    class LowConfidenceJudger(JevTestDouble):
        name = "test-low-confidence"

        async def judge(self, state, workflow, plan, observations):
            decision = await super().judge(state, workflow, plan, observations)
            return decision.model_copy(update={"outcome": Outcome.NOTIFY, "confidence": 0.2})

    case = evaluation_catalog()["revenue_decline"]
    result = await MonitorEngine(LowConfidenceJudger()).evaluate(case.workflow, case.resources)
    assert result.decision.outcome == Outcome.INVESTIGATE


async def test_missing_baseline_is_not_treated_as_noop():
    workflow = MonitorWorkflow(
        id="workflow-no-baseline",
        title="Current-only workflow",
        intent="Notify when this value changes.",
        sources=[
            SourceRef(
                key="current-source",
                adapter="sql",
                resource="query:current",
                label="Current value query",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key="current-source",
        adapter="sql",
        resource="query:current",
        title="Current value query",
        observations=[
            Observation(
                source_key="current-source",
                subject_id="current-value",
                subject_label="Current value",
                metric="current_value",
                current=100,
            )
        ],
    )
    result = await MonitorEngine(SafetyTestDouble()).evaluate(workflow, [resource])
    assert result.decision.outcome == Outcome.INSUFFICIENT_DATA


async def test_source_failure_is_not_treated_as_ignore():
    workflow = MonitorWorkflow(
        id="workflow-source-error",
        title="Unavailable source workflow",
        intent="Notify when revenue moves materially.",
        sources=[
            SourceRef(
                key="broken-query",
                adapter="sql",
                resource="query:revenue",
                label="Revenue query",
            )
        ],
    )
    resource = ResourceSnapshot(
        source_key="broken-query",
        adapter="sql",
        resource="query:revenue",
        title="Revenue query",
        error="query timeout",
    )
    result = await MonitorEngine(SafetyTestDouble()).evaluate(workflow, [resource])
    assert result.decision.outcome == Outcome.INSUFFICIENT_DATA
    assert result.decision.recipient_key is None
    assert "timeout" in result.decision.evidence[-1].statement


async def test_unapproved_recipient_cannot_be_notified():
    class UnapprovedRecipientJudger(SafetyTestDouble):
        name = "test-unapproved-recipient"

        async def judge(self, state, workflow, plan, observations):
            decision = await super().judge(state, workflow, plan, observations)
            return decision.model_copy(
                update={"outcome": Outcome.NOTIFY, "recipient_key": "not-allowlisted"}
            )

    case = evaluation_catalog()["revenue_decline"]
    result = await MonitorEngine(UnapprovedRecipientJudger()).evaluate(
        case.workflow, case.resources
    )
    assert result.decision.outcome == Outcome.INVESTIGATE
    assert result.decision.recipient_key is None


def test_workflow_requires_safe_fallback_and_unique_recipients():
    with pytest.raises(ValueError, match="allowed_outcomes"):
        MonitorWorkflow(
            id="unsafe-workflow",
            title="Unsafe",
            intent="Monitor it.",
            allowed_outcomes=[Outcome.NOTIFY],
        )

    with pytest.raises(ValueError, match="unique"):
        MonitorWorkflow(
            id="duplicate-recipients",
            title="Duplicate recipients",
            intent="Monitor it.",
            recipients=[
                {"key": "ops", "label": "Ops", "destination": "#ops"},
                {"key": "ops", "label": "Ops again", "destination": "#ops"},
            ],
        )


async def test_plan_compilation_is_bounded():
    result = await evaluate("revenue_decline")
    assert result.plan.operations
    assert all(operation != "arbitrary_sql" for operation in result.plan.operations)


async def test_unfamiliar_metric_flows_through_without_metric_specific_logic():
    workflow = MonitorWorkflow(
        id="workflow-api-latency",
        title="API latency workflow",
        intent="Escalate when p95 API latency materially increases.",
        sources=[
            SourceRef(
                key="latency-source",
                adapter="superset",
                resource="chart:latency-p95",
                label="P95 API latency",
            )
        ],
        materiality_definition="Material means p95 latency is at least 50% above baseline.",
        recipients=[
            {"key": "platform", "label": "Platform", "destination": "slack://platform"}
        ],
    )
    resource = ResourceSnapshot(
        source_key="latency-source",
        adapter="superset",
        resource="chart:latency-p95",
        title="P95 API latency",
        observations=[
            Observation(
                source_key="latency-source",
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
    result = await MonitorEngine(SafetyTestDouble()).evaluate(workflow, [resource])
    assert result.plan.operations == ["percent_change", "baseline_comparison", "freshness_check"]
    assert result.decision.observations[0].metric == "p95_api_latency"
    assert result.decision.evidence[0].values["change_pct"] == 80


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
    workflow = MonitorWorkflow(
        id="workflow-heterogeneous",
        title="Cross-system order health",
        intent="Investigate when the dashboard, data quality query, load DAG, and table checks disagree.",
        sources=sources,
    )
    result = await MonitorEngine(SafetyTestDouble()).evaluate(workflow, resources)
    assert result.plan.selected_source_keys == [source.key for source in sources]
    assert {observation.source_key for observation in result.decision.observations} == {
        source.key for source in sources
    }
    assert result.resources[1].metadata["provider"] == "sql"

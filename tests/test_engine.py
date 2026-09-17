import pytest

from evaluations.cases import load_evaluation_cases
from semantic_monitor.engine import MonitorEngine
from semantic_monitor.models import (
    ChartSnapshot,
    DashboardSnapshot,
    Decision,
    MonitorCard,
    Observation,
    Outcome,
)


def scenario_catalog():
    return {case.id: case.dashboard.model_copy(deep=True) for case in load_evaluation_cases()}


def default_cards():
    return {
        case.monitor_card.id: case.monitor_card.model_copy(deep=True)
        for case in load_evaluation_cases()
    }


class JevTestDouble:
    """Test-only stand-in for Jev; expected labels live in evaluations/data."""

    name = "jev-test-double"

    async def compile_plan(self, state, card):
        del state, card
        return {"operations": ["percent_change", "baseline_comparison", "freshness_check"]}

    async def judge(self, state, card, plan, observations):
        del plan
        case = next(case for case in load_evaluation_cases() if case.monitor_card.id == card.id)
        return Decision(
            outcome=case.expected_outcome,
            recipient_key=case.expected_recipient,
            rationale="Test double result from the checked-in labeled case.",
            confidence=0.99,
            probabilities={case.expected_outcome: 0.99, "other": 0.01},
            evidence=state["evidence"],
            observations=observations,
            monitor_id=card.id,
            dashboard_id=card.dashboard_id,
            evaluator=self.name,
        )


class SafetyTestDouble:
    """Test-only semantic stub used to exercise code-owned safety gates."""

    name = "jev-safety-test-double"

    async def compile_plan(self, state, card):
        del state, card
        return {"operations": ["percent_change", "baseline_comparison", "freshness_check"]}

    async def judge(self, state, card, plan, observations):
        del plan
        assert all(isinstance(item, dict) for item in state["evidence"])
        return Decision(
            outcome=Outcome.INVESTIGATE,
            rationale="Test-only neutral semantic result.",
            confidence=0.99,
            probabilities={Outcome.INVESTIGATE.value: 0.99},
            evidence=state["evidence"],
            observations=observations,
            monitor_id=card.id,
            dashboard_id=card.dashboard_id,
            evaluator=self.name,
        )


async def evaluate(scenario: str):
    dashboards = scenario_catalog()
    cards = default_cards()
    dashboard = dashboards[scenario]
    card = next(card for card in cards.values() if card.dashboard_id == dashboard.id)
    return await MonitorEngine(JevTestDouble()).evaluate(dashboard, card)


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

        async def judge(self, state, card, plan, observations):
            decision = await super().judge(state, card, plan, observations)
            return decision.model_copy(update={"outcome": Outcome.NOTIFY, "confidence": 0.2})

    dashboards = scenario_catalog()
    card = default_cards()["monitor-revenue"]
    result = await MonitorEngine(LowConfidenceJudger()).evaluate(
        dashboards["revenue_decline"], card
    )
    assert result.decision.outcome == Outcome.INVESTIGATE


async def test_missing_baseline_is_not_treated_as_noop():
    dashboard = DashboardSnapshot(
        id="dash-no-baseline",
        title="Current-only dashboard",
        charts=[
            ChartSnapshot(
                id="chart-current",
                title="Current value",
                metric="current_value",
                observations=[
                    Observation(
                        chart_id="chart-current",
                        chart_title="Current value",
                        metric="current_value",
                        current=100,
                    )
                ],
            )
        ],
    )
    card = MonitorCard(
        id="monitor-no-baseline",
        dashboard_id=dashboard.id,
        title="Current-only monitor",
        intent="Notify when this value changes.",
        chart_ids=["chart-current"],
    )
    result = await MonitorEngine(SafetyTestDouble()).evaluate(dashboard, card)
    assert result.decision.outcome == Outcome.INSUFFICIENT_DATA


async def test_source_failure_is_not_treated_as_ignore():
    dashboard = DashboardSnapshot(
        id="dash-source-error",
        title="Unavailable dashboard",
        charts=[
            ChartSnapshot(
                id="chart-broken",
                title="Broken chart",
                metric="revenue",
                error="Data unavailable from Superset: timeout",
            )
        ],
    )
    card = MonitorCard(
        id="monitor-source-error",
        dashboard_id=dashboard.id,
        title="Broken monitor",
        intent="Notify when revenue moves materially.",
        chart_ids=["chart-broken"],
    )

    result = await MonitorEngine(SafetyTestDouble()).evaluate(dashboard, card)

    assert result.decision.outcome == Outcome.INSUFFICIENT_DATA
    assert result.decision.recipient_key is None
    assert "timeout" in result.decision.evidence[-1].statement


async def test_unapproved_recipient_cannot_be_notified():
    class UnapprovedRecipientJudger(SafetyTestDouble):
        name = "test-unapproved-recipient"

        async def judge(self, state, card, plan, observations):
            decision = await super().judge(state, card, plan, observations)
            return decision.model_copy(
                update={"outcome": Outcome.NOTIFY, "recipient_key": "not-allowlisted"}
            )

    dashboard = scenario_catalog()["revenue_decline"]
    card = default_cards()["monitor-revenue"]
    result = await MonitorEngine(UnapprovedRecipientJudger()).evaluate(dashboard, card)

    assert result.decision.outcome == Outcome.INVESTIGATE
    assert result.decision.recipient_key is None


def test_monitor_card_requires_safe_fallback_and_unique_recipients():
    with pytest.raises(ValueError, match="allowed_outcomes"):
        MonitorCard(
            id="unsafe-card",
            dashboard_id="dashboard",
            title="Unsafe",
            intent="Monitor it.",
            allowed_outcomes=[Outcome.NOTIFY],
        )

    with pytest.raises(ValueError, match="unique"):
        MonitorCard(
            id="duplicate-recipients",
            dashboard_id="dashboard",
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
    dashboard = DashboardSnapshot(
        id="dash-api-latency",
        title="API reliability",
        charts=[
            ChartSnapshot(
                id="latency-p95",
                title="P95 API latency",
                metric="p95_api_latency",
                observations=[
                    Observation(
                        chart_id="latency-p95",
                        chart_title="P95 API latency",
                        metric="p95_api_latency",
                        unit="milliseconds",
                        current=900,
                        baseline=500,
                        change_pct=80,
                    )
                ],
            )
        ],
    )
    card = MonitorCard(
        id="monitor-api-latency",
        dashboard_id=dashboard.id,
        title="API latency monitor",
        intent="Escalate when p95 API latency materially increases.",
        chart_ids=["latency-p95"],
        materiality_definition="Material means p95 latency is at least 50% above baseline.",
        recipients=[
            {"key": "platform", "label": "Platform", "destination": "slack://platform"}
        ],
    )

    result = await MonitorEngine(SafetyTestDouble()).evaluate(dashboard, card)

    assert result.plan.operations == ["percent_change", "baseline_comparison", "freshness_check"]
    assert result.decision.observations[0].metric == "p95_api_latency"
    assert result.decision.evidence[0].values["change_pct"] == 80

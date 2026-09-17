from semantic_monitor.engine import MonitorEngine
from semantic_monitor.models import (
    ChartSnapshot,
    DashboardSnapshot,
    MonitorCard,
    Observation,
    Outcome,
)
from semantic_monitor.scenarios import default_cards, scenario_catalog
from semantic_monitor.typesafe_adapter import HeuristicJudger


async def evaluate(scenario: str):
    dashboards = scenario_catalog()
    cards = default_cards()
    dashboard = dashboards[scenario]
    card = next(card for card in cards.values() if card.dashboard_id == dashboard.id)
    return await MonitorEngine(HeuristicJudger()).evaluate(dashboard, card)


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
    class LowConfidenceJudger(HeuristicJudger):
        name = "test-low-confidence"

        async def judge(self, state, card, plan, observations):
            decision = await HeuristicJudger().judge(state, card, plan, observations)
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
    result = await MonitorEngine(HeuristicJudger()).evaluate(dashboard, card)
    assert result.decision.outcome == Outcome.INSUFFICIENT_DATA


async def test_plan_compilation_is_bounded():
    result = await evaluate("revenue_decline")
    assert "cross_chart_comparison" in result.plan.operations
    assert all(operation != "arbitrary_sql" for operation in result.plan.operations)

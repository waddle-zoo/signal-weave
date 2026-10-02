"""Numerical checks reach Jev and the writer without replacing semantic decisions."""

from types import SimpleNamespace

import pytest

from examples.investigation_agent.briefing import build_briefing_writer_input
from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.models import InsightCard, ResourceSnapshot
from signalweave.reporting import build_investigation_report, render_investigation_report
from signalweave.typesafe_adapter import JevJudger
from tests.test_reporting import comparison


@pytest.mark.parametrize("broken", [False, True])
async def test_checks_are_recomputed_and_healthy_before_jev_and_writer(monkeypatch, broken):
    calls = []

    async def transport(self, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices={"outcome": SimpleNamespace(
            choice="notify", probabilities={"ignore": .01, "notify": .97,
                                            "investigate": .01, "insufficient_data": .01},
        )}, nouls={}, usage=None)

    monkeypatch.setattr(JevJudger, "_system_one_with_retry", transport)
    card = InsightCard(
        id="numeric-integration", title="Volume review", what_to_watch="Approved volume",
        why_watch="Review material losses", decision_guidance="Notify when total decline is at least 20.",
        sources=[{"key": "a", "adapter": "fixture", "resource": "r", "label": "Approved",
                  "required_comparison_keys": ["volume-by-channel"]}],
        numeric_conditions=[{"text": "Total decline is at least 20", "source_key": "a",
                             "comparison_key": "volume-by-channel", "measurement": "delta",
                             "unit": "count", "threshold": -20, "comparator": "<="}],
        delivery_methods=[{"key": "owner", "outcome": "notify", "label": "Owner", "destination": "agent://owner"}],
    )
    card.compiled_plan = base_plan(card)
    snapshot = ResourceSnapshot(source_key="a", adapter="fixture", resource="r", title="Volume",
                                analytical_comparisons=[comparison()],
                                error="Provider unavailable" if broken else None)
    run = await InsightEngine(JevJudger(api_key="offline-test")).evaluate(card, [snapshot])
    assert len(calls) == 1
    state = calls[0]["state"]
    assert state["numeric_conditions"][0]["status"] == ("unknown" if broken else "true")
    assert "not standalone action rules" in state["numeric_condition_semantics"]
    assert "numeric_conditions" in calls[0]["questions"]["outcome"].instructions
    assert run.result.outcome.value == ("insufficient_data" if broken else "notify")
    report = build_investigation_report(card, run.result, [snapshot])
    assert report.numeric_conditions[0].status == ("unknown" if broken else "true")
    writer = build_briefing_writer_input(report, render_investigation_report(report), [])
    check = writer["report"]["numeric_conditions"][0]
    if not broken:
        assert check["value"] == -20
        assert check["analysis_input_digest"]
        assert check["query_refs"] == ["query:volume-total", "query:volume-segments"]


def test_bad_report_cannot_smuggle_true_numeric_checks():
    from tests.test_reporting import card, complete_analysis, healthy_resources, result

    configured = InsightCard.model_validate({**card().model_dump(), "numeric_conditions": [{
        "text": "Large increase", "source_key": "sales", "comparison_key": "volume-by-channel",
        "measurement": "delta", "unit": "count", "threshold": 100, "comparator": ">",
    }]})
    report = build_investigation_report(configured, result(complete_analysis().model_copy(
        update={"delta": 9999})), healthy_resources())
    assert report.status == "blocked"
    assert report.numeric_conditions[0].status == "unknown"
    assert report.numeric_conditions[0].value is None

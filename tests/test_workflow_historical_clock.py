"""Offline historical-clock isolation for supplied workflow snapshots."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from test_mcp_acceptance import setup
from test_onboarding import tool

from signalweave.engine import InsightEngine
from signalweave.evaluation import CardEvaluationCase, CardWorkflowEvaluator, WorkflowCaseInput
from signalweave.models import (
    ContextSnapshot,
    InsightCard,
    InsightResult,
    Observation,
    Outcome,
    ResourceContract,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.sources import SourceRegistry


class ClockJev:
    name = "clock-test-jev"

    def __init__(self):
        self.states = []
        self.select_calls = 0

    async def compile_plan(self, state, card):
        await asyncio.sleep(0)
        return {"capabilities": [], "baseline": card.comparison_windows[0]}

    async def judge(self, state, card, plan, observations):
        await asyncio.sleep(0)
        self.states.append(state)
        outcome = Outcome.IGNORE
        return InsightResult(
            card_id=card.id,
            outcome=outcome,
            summary="clock test",
            rationale="clock test",
            confidence=1.0,
            probabilities={outcome.value: 1.0},
            evidence=state["evidence"],
            observations=observations,
            evaluator=self.name,
        )

    async def select_investigation_sources(self, state):
        self.select_calls += 1
        raise AssertionError("historical replay selected a live follow-up source")


class NoContext:
    name = "must-not-load"

    def __init__(self):
        self.calls = 0

    async def get_context(self, card, resources):
        self.calls += 1
        return None


def _card(*, bounded: bool = False) -> InsightCard:
    return InsightCard(
        id="clock-card",
        title="Clock test",
        what_to_watch="Orders",
        why_watch="Historical freshness",
        decision_guidance="Ignore unchanged orders.",
        sources=[SourceRef(key="orders", adapter="test", resource="orders", label="Orders")],
        comparison_windows=["previous_period"],
        max_source_age_hours=24,
        investigation_mode="bounded" if bounded else "none",
    )


def _snapshot(captured_at: datetime) -> ResourceSnapshot:
    return ResourceSnapshot(
        source_key="orders",
        adapter="test",
        resource="orders",
        title="Orders",
        captured_at=captured_at,
        source_captured_at=captured_at,
        contract=ResourceContract(source_status="healthy"),
        observations=[Observation(
            source_key="orders", subject_id="orders", subject_label="Orders",
            metric="orders", current=10, baseline=10, change_pct=0,
        )],
    )


def _case(case_id: str, as_of: datetime, *, captured_at: datetime | None = None,
          bounded: bool = False) -> CardEvaluationCase:
    return CardEvaluationCase(
        id=case_id,
        card=_card(bounded=bounded),
        resources=[_snapshot(captured_at or (as_of - timedelta(hours=1)))],
        as_of=as_of,
        expected_outcome=Outcome.IGNORE,
        expected_retrieval_refs=["test|orders"],
    )


@pytest.mark.asyncio
async def test_historical_as_of_makes_snapshot_fresh_but_omitted_clock_is_stale():
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    judger = ClockJev()
    engine = InsightEngine(judger)
    historical = _case("historical", as_of)
    report = await CardWorkflowEvaluator(engine).evaluate([historical])
    assert report.cases[0].exact_outcome
    assert report.cases[0].as_of == as_of
    assert len(judger.states) == 1

    live_clock_case = historical.model_copy(update={"as_of": None})
    live_report = await CardWorkflowEvaluator(engine).evaluate([live_clock_case])
    assert live_report.cases[0].outcome == Outcome.INSUFFICIENT_DATA


@pytest.mark.asyncio
async def test_stale_snapshot_remains_blocked_at_historical_clock():
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    case = _case("stale", as_of, captured_at=as_of - timedelta(hours=25))
    report = await CardWorkflowEvaluator(InsightEngine(ClockJev())).evaluate([case])
    assert report.cases[0].outcome == Outcome.INSUFFICIENT_DATA


@pytest.mark.asyncio
async def test_parallel_historical_cases_have_isolated_clocks():
    first = datetime(2026, 1, 2, tzinfo=timezone.utc)
    second = datetime(2026, 2, 2, tzinfo=timezone.utc)
    judger = ClockJev()
    original_clock = datetime(2030, 1, 1, tzinfo=timezone.utc)
    engine = InsightEngine(judger, clock=lambda: original_clock)
    report = await CardWorkflowEvaluator(engine, max_concurrency=2).evaluate([
        _case("first", first), _case("second", second),
    ])
    assert [case.exact_outcome for case in report.cases] == [True, True]
    assert all(case.outcome == Outcome.IGNORE for case in report.cases)
    assert engine.clock() == original_clock


def test_current_capture_and_historical_as_of_are_mutually_exclusive():
    with pytest.raises(ValueError, match="as_of cannot be combined"):
        WorkflowCaseInput(
            id="current",
            expected_outcome=Outcome.IGNORE,
            capture_current_sources=True,
            resources=[],
            as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_mcp_rejects_current_capture_as_of_before_source_query(tmp_path):
    server, card_id, _ = await setup(tmp_path)

    async def forbidden(*args, **kwargs):
        raise AssertionError("historical clock validation must precede source query")

    server._test_runtime.sources.resolve = forbidden
    with pytest.raises(ValueError, match="as_of cannot be combined"):
        await tool(server, "evaluate_card_workflow")(card_id, [{
            "id": "current-with-clock",
            "expected_outcome": "ignore",
            "capture_current_sources": True,
            "as_of": "2026-01-02T00:00:00Z",
        }])


def test_future_snapshot_rejected_before_evaluation():
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="future snapshots"):
        _case("future", as_of, captured_at=as_of + timedelta(seconds=1))


def test_future_context_rejected_before_historical_replay():
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    base = _case("future-context", as_of)
    with pytest.raises(ValueError, match="future context"):
        CardEvaluationCase.model_validate({
            **base.model_dump(mode="python"),
            "context": ContextSnapshot(
                provider="test",
                version="present",
                captured_at=as_of + timedelta(seconds=1),
            ),
        })


@pytest.mark.asyncio
async def test_future_context_model_copy_is_blocked_in_preflight():
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    case = _case("future-context-preflight", as_of).model_copy(update={
        "context": ContextSnapshot(
            provider="test", version="present",
            captured_at=as_of + timedelta(seconds=1),
        ),
    })
    judger = ClockJev()
    report = await CardWorkflowEvaluator(InsightEngine(judger)).evaluate([case])
    assert report.preflight_blockers == [
        "future-context-preflight: context captured_at is after historical as_of"
    ]
    assert judger.states == []


@pytest.mark.asyncio
async def test_historical_as_of_changes_input_digest_and_result_row():
    base = datetime(2026, 1, 2, tzinfo=timezone.utc)
    engine = InsightEngine(ClockJev())
    captured_at = base - timedelta(hours=1)
    first = await CardWorkflowEvaluator(engine).evaluate([
        _case("same", base, captured_at=captured_at),
    ])
    second = await CardWorkflowEvaluator(engine).evaluate([
        _case("same", base + timedelta(days=1), captured_at=captured_at),
    ])
    assert first.input_digest != second.input_digest
    assert first.cases[0].as_of == base
    assert second.cases[0].as_of == base + timedelta(days=1)


@pytest.mark.asyncio
async def test_historical_replay_does_not_fetch_sources_or_context():
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    judger = ClockJev()
    context = NoContext()
    engine = InsightEngine(judger, registry=SourceRegistry([]), context_provider=context)
    report = await CardWorkflowEvaluator(engine).evaluate([_case("snapshot-only", as_of)])
    assert report.error_count == 0
    assert len(judger.states) == 1
    assert context.calls == 0


@pytest.mark.asyncio
async def test_historical_bounded_card_does_not_select_follow_up_sources():
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    judger = ClockJev()
    engine = InsightEngine(judger, registry=SourceRegistry([]))
    report = await CardWorkflowEvaluator(engine).evaluate([_case(
        "bounded-snapshot-only", as_of, bounded=True,
    )])
    assert report.cases[0].outcome == Outcome.IGNORE
    assert report.cases[0].exact_outcome
    assert judger.select_calls == 0

import json

import pytest

from signalweave.engine import InsightEngine
from signalweave.local_run import run_card
from signalweave.models import (
    DeliveryMethod,
    InsightCard,
    InsightCardStatus,
    InsightResult,
    Observation,
    Outcome,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteDecisionReceiptStore, SQLiteInsightCardStore
from tests.test_diagnostics import comparison


class MeasurementSource:
    name = "measurements"

    def __init__(self, data):
        self.data = data
        self.calls = 0

    async def list_resources(self):
        return [ResourceDescriptor(adapter=self.name, resource="partition", kind="query", title="Partition")]

    async def inspect(self, source):
        self.calls += 1
        return ResourceSnapshot(source_key=source.key, adapter=self.name, resource=source.resource,
                                title=source.label, analytical_comparisons=[self.data])


class InspectingJudger:
    name = "test-only-judger"

    def __init__(self):
        self.states = []

    async def compile_plan(self, state, card):
        return {"capabilities": ["dimension_contribution"], "baseline": "previous_period"}

    async def judge(self, state, card, plan, observations):
        self.states.append(state)
        return InsightResult(card_id=card.id, outcome=Outcome.NOTIFY, confidence=.99,
                             summary="Test transport", rationale="Test transport",
                             evidence=state["evidence"], observations=observations,
                             source_keys=plan.selected_source_keys, evaluator=self.name)


def make_runtime(tmp_path, data=None, approved=True):
    source = MeasurementSource(data or comparison())
    registry = SourceRegistry([source])
    judger = InspectingJudger()
    store = SQLiteInsightCardStore(tmp_path / "runtime.db")
    store.save_card(InsightCard(
        id="repeat", title="Repeatable investigation", what_to_watch="Changes in activity",
        why_watch="Understand concentration", comparison_windows=["previous_period"],
        sources=[SourceRef(key="measurement", adapter=source.name, resource="partition", label="Partition")],
        status=InsightCardStatus.APPROVED if approved else InsightCardStatus.DRAFT,
        delivery_methods=[DeliveryMethod(key="owner", outcome=Outcome.NOTIFY, label="Owner", destination="agent://owner")],
    ))
    runtime = Runtime(card_store=store, sources=registry, engine=InsightEngine(judger, registry),
                      decision_receipts=SQLiteDecisionReceiptStore(tmp_path / "runtime.db"))
    return runtime, source, judger


async def test_local_run_reuses_production_receipt_and_replays_without_calls(tmp_path):
    runtime, source, judger = make_runtime(tmp_path)
    first = await run_card("repeat", "period:1", tmp_path / "outputs", runtime=runtime)
    assert first["result"]["analyses"][0]["delta"] == -20
    assert judger.states[0]["analyses"][0]["delta"] == -20
    assert first["receipt"]["delivery_enabled"] is False
    replay = await run_card("repeat", "period:1", tmp_path / "outputs", runtime=runtime)
    assert replay["replayed"] is True
    assert source.calls == 1
    assert len(judger.states) == 1
    from pathlib import Path
    assert json.loads(Path(replay["artifacts"]["result"]).read_text())["analyses"][0]["delta"] == -20
    assert "accounting" in Path(replay["artifacts"]["brief"]).read_text()
    assert Path(replay["artifacts"]["brief"]).stat().st_mode & 0o777 == 0o600
    await run_card("repeat", "period:2", runtime=runtime)
    assert source.calls == 2


async def test_failed_decomposition_blocks_automatic_notification(tmp_path):
    runtime, _, _ = make_runtime(tmp_path, comparison(current_total={"value": 999}))
    result = await run_card("repeat", "bad-total", runtime=runtime)
    assert result["result"]["outcome"] == "insufficient_data"
    assert result["result"]["analyses"][0]["status"] == "insufficient_data"
    assert result["result"]["delivery_methods"] == []


async def test_draft_cannot_be_run_locally(tmp_path):
    runtime, source, _ = make_runtime(tmp_path, approved=False)
    with pytest.raises(Exception, match="approve"):
        await run_card("repeat", "draft", runtime=runtime)
    assert source.calls == 0


async def test_snapshot_budget_strips_analytical_rows(tmp_path):
    runtime, source, _ = make_runtime(tmp_path)
    runtime.sources._max_snapshot_bytes = 100
    snapshot = await runtime.sources.inspect(SourceRef(key="measurement", adapter=source.name,
                                                       resource="partition", label="Partition"))
    assert snapshot.error
    assert snapshot.analytical_comparisons == []


@pytest.mark.parametrize("status,allowed", [
    ("stale", {"investigate", "escalate"}),
    ("ambiguous", {"investigate"}),
    ("failed", {"insufficient_data"}),
])
async def test_analysis_only_sources_obey_health_gates(tmp_path, status, allowed):
    runtime, source, _ = make_runtime(tmp_path)
    original = source.inspect

    async def inspect(reference):
        snapshot = await original(reference)
        snapshot.contract.source_status = status
        return snapshot

    source.inspect = inspect
    response = await run_card("repeat", "health", runtime=runtime)
    assert response["result"]["outcome"] in allowed


async def test_missing_required_comparison_is_not_silently_omitted(tmp_path):
    runtime, source, _ = make_runtime(tmp_path)
    card = runtime.card_store.get_card("repeat")
    card.sources[0].required_comparison_keys = ["not-returned"]
    runtime.card_store.save_card(card)
    response = await run_card("repeat", "missing", runtime=runtime)
    assert response["result"]["outcome"] == "insufficient_data"


async def test_matching_analysis_satisfies_current_only_observation(tmp_path):
    runtime, source, _ = make_runtime(tmp_path)
    original = source.inspect

    async def inspect(reference):
        snapshot = await original(reference)
        snapshot.observations = [Observation(source_key=reference.key, metric=source.data.metric,
                                            subject_id=source.data.key, current=80)]
        return snapshot

    source.inspect = inspect
    response = await run_card("repeat", "bound", runtime=runtime)
    assert response["result"]["outcome"] == "notify"


async def test_unselected_required_analysis_still_blocks(tmp_path):
    from signalweave.models import InsightPlan
    runtime, source, _ = make_runtime(tmp_path, comparison(coverage="partial"))
    card = runtime.card_store.get_card("repeat")
    snapshot = await source.inspect(card.sources[0])
    plan = InsightPlan(card_id=card.id, selected_source_keys=[], comparison_windows=["previous_period"],
                       capabilities=[], card_scope="Test excluded required source")
    materials = runtime.engine._evaluation_materials(card, plan, [snapshot], None, None)
    assert materials.blocking_source_errors
    assert materials.analyses[0].status == "insufficient_data"


async def test_evidence_plan_does_not_fulfill_invalid_analytical_slot(tmp_path):
    runtime, _, _ = make_runtime(tmp_path, comparison(coverage="partial"))
    response = await run_card("repeat", "partial", runtime=runtime)
    assert response["result"]["evidence_plan"]["status"] != "complete"


async def test_contradictory_matched_observation_blocks_instead_of_getting_exempted(tmp_path):
    runtime, source, _ = make_runtime(tmp_path)
    original = source.inspect

    async def inspect(reference):
        snapshot = await original(reference)
        snapshot.observations = [Observation(source_key=reference.key, subject_id=source.data.key,
                                            metric=source.data.metric, current=999)]
        return snapshot

    source.inspect = inspect
    response = await run_card("repeat", "conflicting", runtime=runtime)
    assert response["result"]["outcome"] == "insufficient_data"
    assert response["result"]["evidence_plan"]["status"] == "blocked"


async def test_missing_evidence_cannot_be_reported_as_absence(tmp_path):
    from signalweave.models import WatchResult, WatchStatus
    runtime, _, judger = make_runtime(tmp_path, comparison(coverage="partial"))
    card = runtime.card_store.get_card("repeat")
    card.watch_for = ["Activity changed"]
    runtime.card_store.save_card(card)
    original = judger.judge

    async def judge(*args):
        result = await original(*args)
        return result.model_copy(update={"watch_results": [WatchResult(key="watch_1", watch_for="Activity changed",
                                                                      status=WatchStatus.ABSENT, probability=.01)]})

    judger.judge = judge
    response = await run_card("repeat", "missing-watch", runtime=runtime)
    assert response["result"]["watch_results"][0]["status"] == "unknown"
    assert all(slot["status"] != "fulfilled" for slot in response["result"]["evidence_plan"]["slots"] if slot["role"] == "watch")


@pytest.mark.parametrize("failure", ["partial", "duplicate"])
async def test_context_cannot_fulfill_failed_analytical_slot(tmp_path, failure):
    from signalweave.models import ContextFact, ContextSnapshot, EvidenceSlot, InsightPlan
    runtime, source, _ = make_runtime(tmp_path, comparison(coverage="partial" if failure == "partial" else "complete"))
    card = runtime.card_store.get_card("repeat")
    snapshot = await source.inspect(card.sources[0])
    if failure == "duplicate":
        snapshot.analytical_comparisons.append(source.data)
    plan = InsightPlan(card_id=card.id, selected_source_keys=["measurement"], comparison_windows=["previous_period"],
                       capabilities=[], card_scope="Numerical evidence", evidence_slots=[EvidenceSlot(
                           key="primary", role="primary", source_keys=["measurement"], required=True, question="Fetch comparison")])
    context = ContextSnapshot(provider="reviewed-context", version="1", facts=[ContextFact(
        fact_id="claim", slot_key="primary", subject_ref="measurement|partition", relation="says",
        statement="Source should be available")])
    materials = runtime.engine._evaluation_materials(card, plan, [snapshot], context, None)
    result = InsightResult(card_id=card.id, outcome=Outcome.NOTIFY, summary="test", rationale="test", evaluator="test", analyses=materials.analyses)
    evidence_plan = runtime.engine._build_evidence_plan(card=card, plan=plan, result=result, resources=[snapshot], context=context,
                                                        source_errors=materials.source_errors)
    assert evidence_plan.status == "blocked"
    assert evidence_plan.slots[0].status == "unavailable"

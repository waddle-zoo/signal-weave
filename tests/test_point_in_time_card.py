import pytest
from pydantic import ValidationError

from signalweave.compiler import base_plan, compile_with_typesafe
from signalweave.engine import InsightEngine
from signalweave.models import (
    InsightCard,
    InsightResult,
    Observation,
    ResourceContract,
    ResourceSnapshot,
    SourceComparisonContract,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService
from tests.test_diagnostics import comparison
from tests.test_onboarding import SupersetCatalogDouble, make_server, tool


def _card(*, windows=None, source=None, **changes):
    values = {
        "id": "point-in-time-queue",
        "title": "Queue state",
        "what_to_watch": "Current unanswered ticket count",
        "why_watch": "Identify work that still needs a response.",
        "sources": [source or SourceRef(
            key="queue",
            adapter="superset",
            resource="dashboard:7",
            label="Queue state",
        )],
    }
    if windows is not None:
        values["comparison_windows"] = windows
    values.update(changes)
    return InsightCard(**values)


async def test_empty_windows_compile_to_current_only_plan_and_validate_cached_plan():
    card = _card(windows=[])
    plan = base_plan(card)

    assert plan.comparison_windows == []
    assert "percent_change" not in plan.capabilities
    assert "baseline_comparison" not in plan.capabilities
    assert plan.capabilities == ["freshness_check"]
    source_slot = next(slot for slot in plan.evidence_slots if slot.role == "primary")
    assert "currently reported" in source_slot.question
    assert "comparison window" not in source_slot.question
    assert "current observation" in source_slot.completion_criteria
    assert "comparison window" not in source_slot.completion_criteria

    cached = card.model_copy(update={"compiled_plan": plan})
    assert InsightCard.model_validate(cached.model_dump()) == cached
    assert await InsightEngine(object()).compile(cached) == plan

    multi_source = _card(windows=[], source=SourceRef(
        key="queue", adapter="superset", resource="dashboard:7", label="Queue state",
    ))
    multi_source.sources.append(SourceRef(
        key="owners", adapter="superset", resource="dashboard:8", label="Owners",
    ))
    # Current evidence can be checked across sources without a prior period.
    assert "cross_source_comparison" in base_plan(multi_source).capabilities


async def test_optional_plan_suggestions_cannot_reintroduce_comparative_capabilities():
    class PlanSuggestions:
        name = "test-suggestions"

        async def compile_plan(self, state, card):
            del state, card
            return {
                "capabilities": [
                    "percent_change", "baseline_comparison", "cross_source_comparison",
                    "seasonality_check", "dimension_contribution", "freshness_check",
                ],
                "baseline": "unrequested-period",
            }

    plan = await compile_with_typesafe(_card(windows=[]), PlanSuggestions())

    assert plan.comparison_windows == []
    assert plan.capabilities == ["cross_source_comparison", "freshness_check"]


def test_empty_windows_cannot_clear_required_or_numeric_comparisons():
    source = SourceRef(
        key="queue",
        adapter="superset",
        resource="dashboard:7",
        label="Queue state",
        required_comparison_keys=["queue-count-prior-period"],
    )
    with pytest.raises(ValidationError, match="required_comparison_keys"):
        _card(windows=[], source=source)

    with pytest.raises(ValidationError, match="numeric_conditions"):
        _card(
            windows=[],
            source=source,
            numeric_conditions=[{
                "text": "Queue count declined versus the prior period.",
                "source_key": "queue",
                "comparison_key": "queue-count-prior-period",
                "measurement": "change_pct",
                "unit": "percent",
                "threshold": -10,
                "comparator": "<=",
            }],
        )


async def test_cached_empty_plan_is_rejected_for_comparative_card():
    card = _card(windows=["previous_period"])
    plan = base_plan(card).model_copy(update={"comparison_windows": []})
    tampered = card.model_copy(update={"compiled_plan": plan})

    with pytest.raises(ValueError, match="compiled_plan comparison windows"):
        InsightCard.model_validate(tampered.model_dump())
    with pytest.raises(ValueError, match="compiled_plan comparison windows"):
        await InsightEngine(object()).compile(tampered)


async def test_engine_keeps_only_current_values_and_ignores_unrequested_comparisons():
    card = _card(windows=[])
    plan = base_plan(card)
    resource = ResourceSnapshot(
        source_key="queue",
        adapter="superset",
        resource="dashboard:7",
        title="Queue state",
        observations=[Observation(
            source_key="queue",
            subject_id="unanswered",
            subject_label="Unanswered",
            metric="unanswered_count",
            unit="tickets",
            current=0,
            baseline=24,
            previous=20,
            change_pct=-100,
            comparison_baselines={"previous_period": 18},
            freshness="fresh",
        )],
        analytical_comparisons=[comparison(comparison_window="unrequested-period")],
    )

    materials = InsightEngine(object())._evaluation_materials(card, plan, [resource], None, None)

    observation = materials.observations[0]
    assert observation.current == 0
    assert observation.baseline is None
    assert observation.previous is None
    assert observation.change_pct is None
    assert observation.comparison_baselines == {}
    assert materials.analyses == []
    evidence = next(item for item in materials.evidence if item.subject_id == "unanswered")
    assert evidence.statement == "Unanswered is currently 0 tickets."
    assert "baseline" not in evidence.statement.lower()
    assert "change" not in evidence.statement.lower()
    assert "baseline" not in evidence.values
    assert "change_pct" not in evidence.values
    current_table = next(item for item in materials.evidence if item.subject_id == "volume-by-channel")
    assert current_table.origin == "source" and current_table.values["current_total"]["value"] == 80
    assert "baseline_total" not in current_table.values
    assert materials.source_errors == []
    # Current-only evaluation uses copies; the adapter's snapshots stay raw.
    assert resource.observations[0].baseline == 24
    assert resource.observations[0].previous == 20
    assert resource.observations[0].change_pct == -100
    assert resource.observations[0].comparison_baselines == {"previous_period": 18}
    assert resource.analytical_comparisons[0].comparison_window == "unrequested-period"


async def test_point_card_preserves_current_facts_carried_only_in_a_comparison_table():
    card = _card(windows=[])
    supplied = comparison("rate", coverage="partial", comparable=False,
        current_total={"numerator": 28, "denominator": 100},
        baseline_total={"numerator": None, "denominator": None})
    resource = ResourceSnapshot(source_key="queue", adapter="superset", resource="dashboard:7",
                                title="Reported current aggregate", analytical_comparisons=[supplied])
    materials = InsightEngine(object())._evaluation_materials(card, base_plan(card), [resource], None, None)
    assert materials.analyses == [] and materials.source_errors == []
    item, = materials.evidence
    assert item.origin == "source" and item.provenance == supplied.query_refs
    assert item.values["current_total"] == {"value": None, "numerator": 28, "denominator": 100}
    assert item.values["current_start"] == "2026-08-08T00:00:00Z"
    assert item.values["source_comparison_coverage"] == "partial"
    assert "baseline_total" not in item.values and "comparable" not in item.values
    assert all("baseline" not in segment for segment in item.values["segments"])
    assert resource.analytical_comparisons[0].baseline_total.numerator is None
    slots = InsightEngine._build_evidence_plan(card=card, plan=base_plan(card), resources=[resource], context=None,
        source_errors=materials.source_errors, result=InsightResult(card_id=card.id, outcome="ignore",
            confidence=0.9, evaluator="test-double-not-live", summary="Test-only source-slot check", rationale="No provider judgment was requested"))
    assert slots.slots[0].status == "fulfilled"


async def test_point_current_inputs_do_not_bypass_resource_provenance_checks():
    from types import SimpleNamespace

    from signalweave.sources import SourceRegistry

    card = _card(windows=[])
    resource = ResourceSnapshot(source_key="queue", adapter="superset", resource="dashboard:7",
        title="Reported current aggregate", analytical_comparisons=[comparison(query_refs=["superset|chart:unread"])])
    engine = InsightEngine(object(), SourceRegistry([SimpleNamespace(name="superset")]))
    materials = engine._evaluation_materials(card, base_plan(card), [resource], None, None)
    current = next(item for item in materials.evidence if item.subject_id == "volume-by-channel")
    assert current.values["current_total"]["value"] == 80
    assert any(item["quality_status"] == "provenance_incomplete" for item in materials.blocking_source_errors)


async def test_empty_current_comparison_inputs_do_not_become_a_measured_zero():
    card = _card(windows=[])
    supplied = comparison(current_total={}, segments=[{"segment": "unknown", "current": {}, "baseline": {"value": 10}}])
    resource = ResourceSnapshot(source_key="queue", adapter="superset", resource="dashboard:7",
                                title="Unavailable current values", analytical_comparisons=[supplied])
    materials = InsightEngine(object())._evaluation_materials(card, base_plan(card), [resource], None, None)
    assert materials.evidence == [] and materials.analyses == []
    slots = InsightEngine._build_evidence_plan(card=card, plan=base_plan(card), resources=[resource], context=None,
        source_errors=materials.source_errors, result=InsightResult(card_id=card.id, outcome="insufficient_data",
            confidence=0.9, evaluator="test-double-not-live", summary="Test-only source-slot check", rationale="No provider judgment was requested"))
    assert slots.slots[0].status == "pending"


async def test_review_and_engine_keep_required_scalar_comparison_gates(tmp_path):
    key = "queue-count-prior-period"
    scalar = SourceComparisonContract(
        key=key,
        metric="unanswered_count",
        definition="Unanswered tickets in the approved queue.",
        population="All active tickets",
        unit="tickets",
        comparison_window="previous_period",
        coverage="partial",
        comparable=False,
        detail="The export is incomplete.",
    )
    catalog = SupersetCatalogDouble()
    catalog.resources[0].contract = ResourceContract(
        available_comparison_windows=["previous_period"],
        comparison_contracts=[scalar],
        required_comparison_keys=[key],
    )
    server = make_server(tmp_path, catalog=catalog)
    created = await tool(server, "onboard_insight_card")(
        what_to_watch="Unanswered ticket count",
        why_watch="Route an incomplete queue export for review.",
        selected_sources=[{"ref": "superset|dashboard:7"}],
        comparison_windows=["previous_period"],
        retrieval_mode="fixed",
    )
    card = server._test_runtime.card_store.get_card(created["card"]["id"])
    tampered = card.model_copy(update={"comparison_windows": [], "compiled_plan": None})
    authoring = InsightAuthoringService(server._test_runtime.sources, server._test_runtime.engine)
    discovery = await authoring.discover("Unanswered ticket count")
    review = authoring.build_onboarding_review(tampered, discovery).model_dump(mode="json")

    assert any(item["code"] == "comparison-window-mismatch" for item in review["blockers"])
    runtime_snapshot = ResourceSnapshot(
        source_key=card.sources[0].key,
        adapter=card.sources[0].adapter,
        resource=card.sources[0].resource,
        title=card.sources[0].label,
        observations=[Observation(metric="unanswered_count", current=0)],
        contract=ResourceContract(comparison_contracts=[scalar]),
    )
    errors = server._test_runtime.engine._source_errors(tampered, [runtime_snapshot])
    quality_statuses = {item.get("quality_status") for item in errors}
    assert "comparison_window_mismatch" in quality_statuses
    assert "comparison_incomplete" in quality_statuses

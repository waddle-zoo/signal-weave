from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluations.card_guided_retrieval_benchmark import (
    DashboardChartAdapter,
    _card_for_ids,
    _lexical_ids,
    build_cases,
)


def _config() -> dict:
    path = Path(__file__).parents[1] / "evaluations" / "data" / "dashboard-scale-scenarios.json"
    config = json.loads(path.read_text())
    config["chart_count"] = 100
    return config


def test_builds_a_100_chart_catalog_without_evaluator_labels_in_metadata() -> None:
    case = build_cases(_config(), repeats=1)[0]
    assert len(case.snapshots) == 100
    assert len(case.descriptors) == 101  # dashboard anchor + 100 charts
    assert case.gold_roles
    assert case.gold_evidence_roles
    assert all(
        case.card.evidence_requirements.get(f"question:{index}") is False
        for index in range(1, len(case.card.questions) + 1)
    )
    assert all(
        case.card.evidence_requirements.get(f"watch:{index}") is False
        for index in range(1, len(case.card.watch_for) + 1)
    )
    assert all(
        observation.freshness == "fresh; complete; comparable"
        and observation.attributes["quality_status"] == "healthy"
        for snapshot in case.snapshots.values()
        for observation in snapshot.observations
    )
    for descriptor in case.descriptors:
        assert "gold_role" not in descriptor.metadata
        assert "signal_class" not in descriptor.metadata
        assert "gold_role" not in descriptor.description
    public_payload = json.dumps(
        {
            "card": case.card.model_dump(mode="json"),
            "descriptors": [item.model_dump(mode="json") for item in case.descriptors],
            "snapshots": [item.model_dump(mode="json") for item in case.snapshots.values()],
        }
    )
    for hidden_key in ("gold_role", "gold_evidence_role", "signal_class", "expected_outcome"):
        assert hidden_key not in public_payload


@pytest.mark.asyncio
async def test_adapter_returns_bounded_search_results_and_inspects_selected_chart() -> None:
    case = build_cases(_config(), repeats=1)[0]
    adapter = DashboardChartAdapter(case)
    page = await adapter.search_resources(case.card.what_to_watch, limit=40)
    assert len(page.resources) == 40
    assert page.total_count == 101
    assert page.has_more is True
    selected = _lexical_ids(case, cap=3)
    card = _card_for_ids(case, selected)
    snapshot = await adapter.inspect(card.sources[0])
    assert snapshot.observations
    assert snapshot.observations[0].subject_id == selected[0]


def test_stale_quality_override_is_explicitly_exposed_to_the_judgment() -> None:
    case = build_cases(_config(), repeats=1)[3]
    stale = case.snapshots["chart:payment-data-trust:payment-data-freshness"].observations[0]

    assert stale.freshness == "stale by 29 hours"
    assert stale.attributes["quality_status"] == "stale"
    assert stale.attributes["comparability"] == "same reporting period and population"

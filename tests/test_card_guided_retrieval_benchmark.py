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
    for descriptor in case.descriptors:
        assert "gold_role" not in descriptor.metadata
        assert "signal_class" not in descriptor.metadata
        assert "gold_role" not in descriptor.description


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

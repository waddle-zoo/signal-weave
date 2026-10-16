from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest

from signalweave.diagnostics import AnalyticalComparison, PeriodValue, SegmentPair
from signalweave.models import (
    Evidence,
    Observation,
    ResourceContract,
    ResourceSnapshot,
    SourceComparisonContract,
    SourceRef,
)
from signalweave.sources import (
    SourceRegistry,
    _without_agent_query_definitions,
)


class SnapshotAdapter:
    name = "superset"

    def __init__(self, snapshot: ResourceSnapshot) -> None:
        self.snapshot = snapshot

    async def list_resources(self):
        return []

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        del source
        return self.snapshot


def _snapshot(metadata: dict[str, Any] | None = None) -> ResourceSnapshot:
    return ResourceSnapshot(
        source_key="primary",
        adapter="superset",
        resource="dashboard:7",
        title="Revenue",
        observations=[
            Observation(
                source_key="primary",
                subject_id="net-sales",
                subject_label="Net sales",
                metric="net_sales",
                current=12,
                baseline=10,
            )
        ],
        analytical_comparisons=[
            AnalyticalComparison(
                key="net-sales-by-region",
                metric="net_sales",
                definition="Net sales by region",
                population="orders",
                unit="USD",
                dimension="region",
                kind="additive",
                baseline_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                baseline_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
                current_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
                current_end=datetime(2026, 2, 28, tzinfo=timezone.utc),
                coverage="complete",
                disjoint_segments=True,
                comparable=True,
                query_refs=["query:net-sales"],
                baseline_total=PeriodValue(value=10),
                current_total=PeriodValue(value=12),
                segments=[
                    SegmentPair(
                        segment="north",
                        baseline=PeriodValue(value=10),
                        current=PeriodValue(value=12),
                    )
                ],
            )
        ],
        evidence=[
            Evidence(
                source_key="primary",
                subject_id="quality",
                subject_label="Data quality",
                statement="One late partition is excluded.",
            )
        ],
        metadata=metadata
        if metadata is not None
        else {"data_quality": {"status": "partial", "note": "One late partition."}},
        contract=ResourceContract(
            tenant_id="tenant-a",
            domain="revenue",
            scope="completed orders",
            metric_names=["net_sales"],
            comparison_contracts=[
                SourceComparisonContract(
                    key="net-sales-by-region",
                    metric="net_sales",
                    definition="Net sales by region",
                    population="orders",
                    unit="USD",
                    comparison_window="previous_period",
                    coverage="complete",
                    comparable=True,
                )
            ],
            roles=["primary"],
        ),
    )


def _payload_bytes(snapshot: ResourceSnapshot) -> int:
    payload = json.dumps(snapshot.model_dump(mode="json"), separators=(",", ":"))
    return len(payload.encode("utf-8"))


async def _inspect(snapshot: ResourceSnapshot, *, max_bytes: int) -> ResourceSnapshot:
    registry = SourceRegistry(
        [SnapshotAdapter(snapshot)],
        enforce_catalog=False,
        max_snapshot_bytes=max_bytes,
    )
    return await registry.inspect(
        SourceRef(
            key="primary",
            adapter="superset",
            resource="dashboard:7",
            label="Revenue",
        )
    )


@pytest.mark.asyncio
async def test_snapshot_within_budget_is_returned_without_optional_metadata_changes():
    snapshot = _snapshot()

    result = await _inspect(snapshot, max_bytes=_payload_bytes(snapshot))

    assert result is snapshot
    assert result.error is None
    assert "signalweave_budget" not in result.metadata


@pytest.mark.asyncio
async def test_optional_query_definitions_are_removed_before_budget_failure_and_facts_survive():
    metadata = {
        "saved_query_definition": {
            "audience": "agent",
            "parameters": {"all_columns": ["x" * 5_000]},
        },
        "data_quality": {"status": "partial", "note": "Preserve this limitation."},
        "charts": [
            {
                "id": "62",
                "semantic_status": "extracted",
                "saved_query_definition": {
                    "audience": "agent",
                    "parameters": {"all_columns": ["y" * 4_000]},
                },
            }
        ],
    }
    snapshot = _snapshot(metadata)
    original = snapshot.model_dump(mode="json")
    reduced_metadata, removed = _without_agent_query_definitions(snapshot.metadata)
    assert removed is True
    reduced = snapshot.model_copy(update={"metadata": reduced_metadata})
    budget = _payload_bytes(reduced) + 512
    assert _payload_bytes(snapshot) > budget

    result = await _inspect(snapshot, max_bytes=budget)

    assert result.error is None
    assert result.observations == snapshot.observations
    assert result.evidence == snapshot.evidence
    assert result.analytical_comparisons == snapshot.analytical_comparisons
    assert result.contract == snapshot.contract
    assert "saved_query_definition" not in result.metadata
    assert result.metadata["data_quality"] == metadata["data_quality"]
    assert result.metadata["charts"] == [{"id": "62", "semantic_status": "extracted"}]
    omission = result.metadata["signalweave_budget"]
    assert omission["status"] == "optional_metadata_omitted"
    assert omission["omitted_metadata"] == ["saved_query_definition"]
    assert _payload_bytes(result) <= budget
    assert snapshot.model_dump(mode="json") == original


@pytest.mark.asyncio
async def test_exact_cleaned_snapshot_boundary_preserves_facts_without_oversize_flag():
    snapshot = _snapshot(
        {
            "saved_query_definition": {
                "audience": "agent",
                "parameters": {"all_columns": ["x" * 2_000]},
            },
            "data_quality": {"status": "partial"},
        }
    )
    cleaned_metadata, removed = _without_agent_query_definitions(snapshot.metadata)
    assert removed is True
    cleaned = snapshot.model_copy(update={"metadata": cleaned_metadata})
    exact_budget = _payload_bytes(cleaned)
    assert _payload_bytes(snapshot) > exact_budget

    result = await _inspect(snapshot, max_bytes=exact_budget)

    assert result.error is None
    assert result.observations == snapshot.observations
    assert result.evidence == snapshot.evidence
    assert result.analytical_comparisons == snapshot.analytical_comparisons
    assert result.contract == snapshot.contract
    assert result.metadata == cleaned_metadata
    assert _payload_bytes(result) == exact_budget


@pytest.mark.asyncio
async def test_core_snapshot_still_fails_when_optional_query_definitions_cannot_fit_it():
    snapshot = _snapshot(
        {
            "saved_query_definition": {
                "audience": "agent",
                "parameters": {"all_columns": ["x" * 2_000]},
            },
            "data_quality": {"status": "partial", "note": "z" * 5_000},
        }
    )
    cleaned_metadata, removed = _without_agent_query_definitions(snapshot.metadata)
    assert removed is True
    cleaned = snapshot.model_copy(update={"metadata": cleaned_metadata})
    budget = _payload_bytes(cleaned) - 1
    assert _payload_bytes(snapshot) > budget

    result = await _inspect(snapshot, max_bytes=budget)

    assert result.error is not None and "payload budget" in result.error
    assert result.observations == []
    assert result.evidence == []
    assert result.analytical_comparisons == []
    assert result.contract == snapshot.contract
    assert result.metadata["signalweave_budget"]["status"] == "exceeded"


@pytest.mark.asyncio
async def test_large_chart_fanout_removes_each_bounded_optional_definition():
    definition = {
        "audience": "agent",
        "parameters": {"all_columns": ["x" * 7_800]},
    }
    encoded_definition = json.dumps(definition, separators=(",", ":")).encode("utf-8")
    assert len(encoded_definition) <= 8_192
    metadata = {
        "charts": [
            {
                "id": str(index),
                "semantic_status": "extracted",
                "saved_query_definition": deepcopy(definition),
            }
            for index in range(130)
        ],
        "data_quality": {"status": "complete"},
    }
    snapshot = _snapshot(metadata)
    budget = 1_000_000
    assert _payload_bytes(snapshot) > budget

    result = await _inspect(snapshot, max_bytes=budget)

    assert result.error is None
    assert len(result.metadata["charts"]) == 130
    assert all("saved_query_definition" not in chart for chart in result.metadata["charts"])
    assert all(chart["semantic_status"] == "extracted" for chart in result.metadata["charts"])
    assert result.observations == snapshot.observations
    assert result.evidence == snapshot.evidence
    assert result.analytical_comparisons == snapshot.analytical_comparisons
    assert result.contract == snapshot.contract
    assert _payload_bytes(result) <= budget


def test_helper_does_not_remove_unmarked_business_query_definitions():
    metadata = {
        "saved_query_definition": {"statement": "Business definition", "audience": "owner"},
        "charts": [
            {"saved_query_definition": {"statement": "Unmarked business metadata"}},
            {"saved_query_definition": {"audience": "human", "statement": "Keep"}},
        ],
    }

    copied, removed = _without_agent_query_definitions(metadata)

    assert removed is False
    assert copied == metadata
    assert copied is not metadata
    assert copied["charts"] is not metadata["charts"]


def test_helper_handles_malformed_root_and_chart_shapes_without_mutation():
    metadata = {
        "saved_query_definition": {"audience": "agent", "parameters": {}},
        "charts": [
            None,
            "not a chart object",
            {"id": "missing-definition"},
            {"id": "null-definition", "saved_query_definition": None},
            {"id": "bad-definition", "saved_query_definition": ["agent"]},
            {"id": "unmarked", "saved_query_definition": {"audience": "human"}},
            {"id": "marked", "saved_query_definition": {"audience": "agent"}},
        ],
    }
    original = deepcopy(metadata)

    copied, removed = _without_agent_query_definitions(metadata)

    assert removed is True
    assert "saved_query_definition" not in copied
    assert copied["charts"] == [
        None,
        "not a chart object",
        {"id": "missing-definition"},
        {"id": "null-definition", "saved_query_definition": None},
        {"id": "bad-definition", "saved_query_definition": ["agent"]},
        {"id": "unmarked", "saved_query_definition": {"audience": "human"}},
        {"id": "marked"},
    ]
    assert metadata == original
    assert copied is not metadata
    assert copied["charts"] is not metadata["charts"]

    malformed_charts = {
        "saved_query_definition": "not a definition object",
        "charts": {"0": {"saved_query_definition": {"audience": "agent"}}},
    }
    malformed_copy, malformed_removed = _without_agent_query_definitions(malformed_charts)
    assert malformed_removed is False
    assert malformed_copy == malformed_charts

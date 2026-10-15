"""SourceRegistry contract merge tests for direct trusted adapters."""

import pytest

from signalweave.models import (
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceComparisonContract,
    SourceRef,
)
from signalweave.sources import SourceRegistry


def _comparison(**updates):
    return SourceComparisonContract(
        key="daily-revenue",
        metric="net_revenue",
        definition="Settled revenue for eligible commerce orders.",
        population="Eligible commerce orders",
        unit="USD",
        comparison_window="previous_period",
        coverage="complete",
        comparable=True,
        detail="Reviewed catalog definition.",
        query_refs=["catalog:revenue"],
    ).model_copy(update=updates)


class DirectTrustedAdapter:
    """Small in-process adapter; exercises the real SourceRegistry merge path."""

    name = "trusted_metrics"

    def __init__(self, descriptor, snapshot):
        self.descriptor = descriptor
        self.snapshot = snapshot
        self.inspect_calls = 0

    async def list_resources(self):
        return [self.descriptor.model_copy(deep=True)]

    async def inspect(self, source):
        self.inspect_calls += 1
        return self.snapshot.model_copy(deep=True)


@pytest.fixture
def trusted_source():
    descriptor = ResourceDescriptor(
        adapter=DirectTrustedAdapter.name,
        resource="metric:daily-revenue",
        kind="metric",
        title="Daily revenue",
        contract=ResourceContract(
            source_status="healthy",
            comparison_contracts=[_comparison()],
        ),
    )
    snapshot = ResourceSnapshot(
        source_key="daily-revenue-source",
        adapter=DirectTrustedAdapter.name,
        resource=descriptor.resource,
        title=descriptor.title,
        contract=ResourceContract(
            source_status="healthy",
            comparison_contracts=[_comparison(
                coverage="partial",
                comparable=False,
                detail="Latest capture omits two eligible days.",
                query_refs=["runtime:revenue-42"],
            )],
        ),
    )
    adapter = DirectTrustedAdapter(descriptor, snapshot)
    source = SourceRef(
        key="revenue",
        adapter=adapter.name,
        resource=descriptor.resource,
        label=descriptor.title,
    )
    return {
        "adapter": adapter,
        "registry": SourceRegistry([adapter]),
        "source": source,
        "descriptor": descriptor,
        "snapshot": snapshot,
    }


@pytest.mark.parametrize("runtime_order", [("partial", "complete"), ("complete", "partial")])
async def test_duplicate_runtime_keys_fail_closed_and_keep_catalog_meaning(
    trusted_source, runtime_order,
):
    catalog = trusted_source["descriptor"].contract.comparison_contracts[0]
    runtime = {
        "partial": _comparison(
            metric="unreviewed_metric",
            definition="Conflicting partial runtime definition.",
            population="Different runtime population",
            unit="EUR",
            comparison_window="unreviewed_window",
            coverage="partial",
            comparable=False,
            detail="Runtime partial assertion.",
            query_refs=["runtime:partial"],
        ),
        "complete": _comparison(
            metric="another_unreviewed_metric",
            definition="Conflicting complete runtime definition.",
            population="Another runtime population",
            unit="records",
            comparison_window="another_unreviewed_window",
            coverage="complete",
            comparable=True,
            detail="Runtime complete assertion.",
            query_refs=["runtime:complete"],
        ),
    }
    trusted_source["adapter"].snapshot = trusted_source["snapshot"].model_copy(
        update={"contract": ResourceContract(comparison_contracts=[runtime[key] for key in runtime_order])}
    )

    result = await trusted_source["registry"].inspect(trusted_source["source"])

    assert trusted_source["adapter"].inspect_calls == 1
    assert len(result.contract.comparison_contracts) == 1
    merged = result.contract.comparison_contracts[0]
    assert (merged.metric, merged.definition, merged.population, merged.unit) == (
        catalog.metric, catalog.definition, catalog.population, catalog.unit,
    )
    assert merged.comparison_window == catalog.comparison_window
    assert merged.coverage == "unknown"
    assert merged.comparable is False
    assert merged.query_refs == []
    assert "not unique" in merged.detail


async def test_duplicate_catalog_keys_are_emitted_once_with_unknown_quality(trusted_source):
    catalog = trusted_source["descriptor"].contract.comparison_contracts[0]
    duplicate = catalog.model_copy(update={
        "coverage": "partial",
        "comparable": False,
        "query_refs": ["catalog:duplicate"],
    })
    trusted_source["adapter"].descriptor = trusted_source["descriptor"].model_copy(update={
        "contract": ResourceContract(comparison_contracts=[catalog, duplicate]),
    })

    result = await trusted_source["registry"].inspect(trusted_source["source"])

    assert len(result.contract.comparison_contracts) == 1
    merged = result.contract.comparison_contracts[0]
    assert merged.definition == catalog.definition
    assert merged.metric == catalog.metric
    assert merged.coverage == "unknown"
    assert merged.comparable is False
    assert merged.query_refs == []
    assert "not unique" in merged.detail


async def test_unknown_configured_source_health_cannot_be_upgraded_by_healthy_snapshot(
    trusted_source,
):
    trusted_source["adapter"].descriptor = trusted_source["descriptor"].model_copy(update={
        "contract": trusted_source["descriptor"].contract.model_copy(
            update={"source_status": "unknown"}
        ),
    })
    trusted_source["adapter"].snapshot = trusted_source["snapshot"].model_copy(update={
        "contract": trusted_source["snapshot"].contract.model_copy(
            update={"source_status": "healthy"}
        ),
    })

    result = await trusted_source["registry"].inspect(trusted_source["source"])

    assert result.contract.source_status == "unknown"


async def test_unique_partial_runtime_coverage_and_comparability_are_preserved(trusted_source):
    current = _comparison(
        coverage="partial",
        comparable=False,
        detail="Latest capture omits two eligible days.",
        query_refs=["runtime:revenue-42"],
    )
    trusted_source["adapter"].snapshot = trusted_source["snapshot"].model_copy(update={
        "contract": ResourceContract(comparison_contracts=[current]),
    })

    result = await trusted_source["registry"].inspect(trusted_source["source"])

    assert len(result.contract.comparison_contracts) == 1
    merged = result.contract.comparison_contracts[0]
    assert merged.definition == trusted_source["descriptor"].contract.comparison_contracts[0].definition
    assert merged.coverage == "partial"
    assert merged.comparable is False
    assert merged.detail == "Latest capture omits two eligible days."
    assert merged.query_refs == ["runtime:revenue-42"]

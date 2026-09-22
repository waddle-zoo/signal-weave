from __future__ import annotations

import pytest

from evaluations.documentdb_performance_trial import _build_registry, load_fixture
from signalweave.models import SourceRef


def test_documentdb_fixture_keeps_card_and_expected_labels_outside_product_src():
    fixture = load_fixture()

    assert fixture["expected_outcome"] == "investigate"
    assert len(fixture["expected_related_refs"]) == 4
    assert fixture["card"]["sources"][0]["adapter"] == "cloudwatch"
    assert {item["descriptor"]["adapter"] for item in fixture["resources"]} == {
        "cloudwatch",
        "deployments",
        "incidents",
        "ownership",
        "runbooks",
    }


@pytest.mark.asyncio
async def test_documentdb_adapters_use_native_search_and_authorized_inspection():
    fixture = load_fixture()
    registry, adapters = _build_registry(fixture)

    page = await registry.search_resources(
        "customer impacting DocumentDB performance regression",
        limit=40,
        authorized_tenants=[fixture["tenant_id"]],
    )
    assert page.strategy == "multi-adapter-search"
    assert len(page.resources) == len(fixture["resources"])
    assert all(adapter.list_calls == 0 for adapter in adapters)

    snapshot = await registry.inspect(
        SourceRef(
            key="cloudwatch-performance",
            adapter="cloudwatch",
            resource="metric-group:docdb-performance",
            label="DocumentDB customer performance metrics",
        ),
        authorized_tenants=[fixture["tenant_id"]],
    )
    assert len(snapshot.observations) == 4
    assert all(adapter.list_calls == 0 for adapter in adapters)

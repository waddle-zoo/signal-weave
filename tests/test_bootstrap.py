import pytest

from signalweave.bootstrap import (
    AdapterBootstrapSpec,
    BootstrapCapability,
    BootstrapManifest,
    BootstrapService,
)
from signalweave.models import (
    CatalogSearchPage,
    Observation,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.sources import SourceRegistry


class NativeAdapter:
    name = "superset"

    async def list_resources(self):
        return [self.descriptor]

    async def search_resources(self, query, *, limit, cursor=None):
        del query, cursor
        return CatalogSearchPage(
            resources=[self.descriptor][:limit],
            total_count=1,
            provider="superset-catalog",
            strategy="server-search",
        )

    async def inspect(self, source: SourceRef):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=source.label,
            observations=[
                Observation(
                    source_key=source.key,
                    subject_id="orders",
                    subject_label="Orders",
                    metric="orders",
                    current=10,
                    baseline=9,
                )
            ],
        )

    @property
    def descriptor(self):
        return ResourceDescriptor(
            adapter=self.name,
            resource="dashboard:orders",
            kind="dashboard",
            title="Orders dashboard",
            metadata={"related_resources": ["superset|dashboard:quality"]},
            contract=ResourceContract(
                tenant_id="northstar",
                freshness_sla_hours=24,
                lineage=["table:orders"],
                metric_names=["orders"],
            ),
        )


class LocalScanAdapter(NativeAdapter):
    name = "local"

    async def search_resources(self, query, *, limit, cursor=None):
        page = await super().search_resources(query, limit=limit, cursor=cursor)
        return page.model_copy(update={"strategy": "local-scan-fallback"})


@pytest.mark.asyncio
async def test_bootstrap_reports_ready_native_adapter_capabilities():
    report = await BootstrapService(SourceRegistry([NativeAdapter()])).assess(
        BootstrapManifest(
            tenant_id="northstar",
            adapters=[
                AdapterBootstrapSpec(
                    adapter="superset",
                    probe_goal="orders dashboard",
                    required_capabilities=[
                        BootstrapCapability.CATALOG,
                        BootstrapCapability.SEARCH,
                        BootstrapCapability.INSPECT,
                        BootstrapCapability.TENANT_SCOPE,
                        BootstrapCapability.FRESHNESS,
                        BootstrapCapability.LINEAGE,
                        BootstrapCapability.METRIC_DEFINITIONS,
                    ],
                )
            ],
        )
    )

    assert report.status == "ready"
    result = report.adapters[0]
    assert result.sample_ref == "superset|dashboard:orders"
    assert result.inspected_sample is True
    assert all(result.capabilities.values())
    assert report.blockers == []


@pytest.mark.asyncio
async def test_bootstrap_blocks_when_required_native_search_is_missing():
    report = await BootstrapService(SourceRegistry([LocalScanAdapter()])).assess(
        BootstrapManifest(
            tenant_id="northstar",
            adapters=[
                AdapterBootstrapSpec(
                    adapter="local",
                    probe_goal="orders dashboard",
                    required_capabilities=[BootstrapCapability.SEARCH],
                )
            ],
        )
    )

    assert report.status == "blocked"
    assert any("search" in blocker for blocker in report.blockers)
    assert any("local-scan-fallback" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_bootstrap_rejects_manifest_tenant_mismatch():
    service = BootstrapService(SourceRegistry([NativeAdapter()]))
    with pytest.raises(ValueError, match="tenant_id"):
        await service.assess(
            BootstrapManifest(
                tenant_id="northstar",
                adapters=[
                    AdapterBootstrapSpec(adapter="superset", probe_goal="orders dashboard")
                ],
            ),
            principal=PrincipalContext(principal_id="user", tenant_id="other"),
        )

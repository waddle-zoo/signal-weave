from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Protocol

from .models import ResourceDescriptor, ResourceSnapshot, SourceRef


class SourceAdapter(Protocol):
    """A bounded read adapter. Execution policy stays with the adapter."""

    name: str

    async def list_resources(self) -> list[ResourceDescriptor]: ...

    async def inspect(self, source: SourceRef) -> ResourceSnapshot: ...


class SourceRegistry:
    """Resolve insight-card source refs through explicitly installed adapters."""

    def __init__(
        self,
        adapters: Iterable[SourceAdapter] = (),
        *,
        max_concurrency: int = 8,
        authorized_tenants: Iterable[str] | None = None,
        enforce_catalog: bool = True,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._adapters: dict[str, SourceAdapter] = {}
        self._max_concurrency = max_concurrency
        self._authorized_tenants = (
            frozenset(authorized_tenants) if authorized_tenants is not None else None
        )
        self._enforce_catalog = enforce_catalog
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: SourceAdapter) -> None:
        if not adapter.name:
            raise ValueError("source adapters require a non-empty name")
        if adapter.name in self._adapters:
            raise ValueError(f"source adapter already registered: {adapter.name}")
        self._adapters[adapter.name] = adapter

    def adapter_names(self) -> list[str]:
        return sorted(self._adapters)

    @property
    def authorized_tenants(self) -> frozenset[str] | None:
        return self._authorized_tenants

    async def list_resources(self, adapter_name: str | None = None) -> list[ResourceDescriptor]:
        adapters = (
            [self._get(adapter_name)]
            if adapter_name
            else [self._adapters[name] for name in sorted(self._adapters)]
        )
        resources: list[ResourceDescriptor] = []
        for adapter in adapters:
            resources.extend(await adapter.list_resources())
        return [resource for resource in resources if self._is_authorized(resource)]

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        adapter = self._get(source.adapter)
        if self._enforce_catalog:
            catalog = {
                resource.resource: resource
                for resource in await self.list_resources(source.adapter)
            }
            descriptor = catalog.get(source.resource)
            if descriptor is None:
                return ResourceSnapshot(
                    source_key=source.key,
                    adapter=source.adapter,
                    resource=source.resource,
                    title=source.label,
                    error=(
                        "source is not present in the authorized adapter catalog; "
                        "rediscover it before inspection"
                    ),
                )
        snapshot = await adapter.inspect(source)
        if self._enforce_catalog:
            descriptor = catalog[source.resource]
            snapshot = snapshot.model_copy(
                update={
                    "contract": descriptor.contract,
                    "source_url": snapshot.source_url or descriptor.source_url,
                }
            )
        return snapshot

    async def resolve(self, sources: Iterable[SourceRef]) -> list[ResourceSnapshot]:
        """Fetch sources independently so one broken source is visible to the engine."""
        source_list = list(sources)
        catalog: dict[tuple[str, str], ResourceDescriptor] = {}
        catalog_errors: dict[str, str] = {}
        for adapter_name in sorted({source.adapter for source in source_list}):
            try:
                for resource in await self.list_resources(adapter_name):
                    catalog[(resource.adapter, resource.resource)] = resource
            except Exception as error:  # noqa: BLE001 - isolate one catalog outage
                catalog_errors[adapter_name] = f"{type(error).__name__}: {error}"
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def resolve_one(source: SourceRef) -> ResourceSnapshot:
            try:
                self._get(source.adapter)
            except Exception as error:  # noqa: BLE001 - preserve adapter failure as evidence
                return ResourceSnapshot(
                    source_key=source.key,
                    adapter=source.adapter,
                    resource=source.resource,
                    title=source.label,
                    error=f"{type(error).__name__}: {error}",
                )
            if source.adapter in catalog_errors:
                return ResourceSnapshot(
                    source_key=source.key,
                    adapter=source.adapter,
                    resource=source.resource,
                    title=source.label,
                    error=(
                        "authorized source catalog unavailable for adapter "
                        f"{source.adapter}: {catalog_errors[source.adapter]}"
                    ),
                )
            descriptor = catalog.get((source.adapter, source.resource))
            if self._enforce_catalog and descriptor is None:
                return ResourceSnapshot(
                    source_key=source.key,
                    adapter=source.adapter,
                    resource=source.resource,
                    title=source.label,
                    error=(
                        "source is not present in the authorized adapter catalog; "
                        "rediscover it before evaluation"
                    ),
                )
            try:
                async with semaphore:
                    snapshot = await self.inspect(source)
            except Exception as error:  # noqa: BLE001 - source failure becomes typed evidence
                return ResourceSnapshot(
                    source_key=source.key,
                    adapter=source.adapter,
                    resource=source.resource,
                    title=source.label,
                    error=f"{type(error).__name__}: {error}",
                )
            if snapshot.source_key != source.key:
                snapshot = snapshot.model_copy(update={"source_key": source.key})
            if descriptor is not None:
                snapshot = snapshot.model_copy(
                    update={
                        "contract": descriptor.contract,
                        "source_url": snapshot.source_url or descriptor.source_url,
                    }
                )
            if snapshot.adapter != source.adapter or snapshot.resource != source.resource:
                return snapshot.model_copy(
                    update={
                        "source_key": source.key,
                        "adapter": source.adapter,
                        "resource": source.resource,
                        "error": (
                            "adapter returned a snapshot for a different source: "
                            f"{snapshot.adapter}|{snapshot.resource}"
                        ),
                    }
                )
            return snapshot

        return list(await asyncio.gather(*(resolve_one(source) for source in source_list)))

    def _is_authorized(self, resource: ResourceDescriptor) -> bool:
        if not resource.contract.authorized:
            return False
        if (
            self._authorized_tenants is not None
            and resource.contract.tenant_id not in self._authorized_tenants
        ):
            return False
        return True

    def _get(self, name: str | None) -> SourceAdapter:
        if not name:
            raise ValueError("source adapter is required")
        try:
            return self._adapters[name]
        except KeyError as error:
            available = ", ".join(self.adapter_names()) or "none"
            raise ValueError(
                f"source adapter is not installed: {name} (available: {available})"
            ) from error

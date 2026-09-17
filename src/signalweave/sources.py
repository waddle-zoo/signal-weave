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
        self, adapters: Iterable[SourceAdapter] = (), *, max_concurrency: int = 8
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._adapters: dict[str, SourceAdapter] = {}
        self._max_concurrency = max_concurrency
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

    async def list_resources(self, adapter_name: str | None = None) -> list[ResourceDescriptor]:
        adapters = (
            [self._get(adapter_name)]
            if adapter_name
            else [self._adapters[name] for name in sorted(self._adapters)]
        )
        resources: list[ResourceDescriptor] = []
        for adapter in adapters:
            resources.extend(await adapter.list_resources())
        return resources

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        return await self._get(source.adapter).inspect(source)

    async def resolve(self, sources: Iterable[SourceRef]) -> list[ResourceSnapshot]:
        """Fetch sources independently so one broken source is visible to the engine."""
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def resolve_one(source: SourceRef) -> ResourceSnapshot:
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
            return snapshot

        return list(await asyncio.gather(*(resolve_one(source) for source in sources)))

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

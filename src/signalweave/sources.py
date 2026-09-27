from __future__ import annotations

import asyncio
import base64
import inspect
import json
import re
from collections.abc import Iterable
from typing import Protocol

from .models import (
    CatalogSearchPage,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)


def _catalog_terms(resource: ResourceDescriptor) -> set[str]:
    """Extract bounded lexical terms for adapters without native search.

    This is only candidate recall.  It is deliberately not a relevance decision;
    Jev still ranks the bounded pool in the onboarding and retrieval layers.
    """
    values = [
        resource.adapter,
        resource.resource,
        resource.kind,
        resource.title,
        resource.description,
        resource.contract.domain,
        resource.contract.scope,
        resource.contract.population,
        resource.contract.grain,
        *resource.contract.metric_names,
        *resource.contract.roles,
        *resource.contract.lineage,
        *(str(value) for value in resource.metadata.values()),
    ]
    return {
        term
        for value in values
        for term in re.findall(r"[a-z0-9]+", str(value).lower())
        if len(term) > 2
    }


def _bounded_local_search(
    query: str, resources: list[ResourceDescriptor], limit: int
) -> list[ResourceDescriptor]:
    query_terms = {
        term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2
    }
    ranked = sorted(
        resources,
        key=lambda resource: (
            len(query_terms & _catalog_terms(resource)),
            len(query_terms & {
                term
                for term in re.findall(r"[a-z0-9]+", resource.title.lower())
                if len(term) > 2
            }),
            resource.title.lower(),
            resource.resource,
        ),
        reverse=True,
    )
    return ranked[:limit]


def _encode_multi_adapter_cursor(
    next_cursors: dict[str, str], total_counts: dict[str, int], page_size: int
) -> str:
    """Encode bounded continuation state without exposing provider internals."""
    payload = json.dumps(
        {
            "version": 1,
            "next": next_cursors,
            "totals": total_counts,
            "page_size": page_size,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    cursor = "multi:" + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    if len(cursor) > 500:
        raise ValueError("multi-adapter catalog cursor exceeded the 500-character limit")
    return cursor


def _decode_multi_adapter_cursor(
    cursor: str,
) -> tuple[dict[str, str], dict[str, int], int]:
    """Validate and decode registry-owned continuation state."""
    if not cursor.startswith("multi:"):
        raise ValueError("multi-adapter catalog cursors must use the registry format")
    token = cursor.removeprefix("multi:")
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("invalid multi-adapter catalog cursor") from error
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("unsupported multi-adapter catalog cursor")
    next_cursors = payload.get("next")
    total_counts = payload.get("totals")
    page_size = payload.get("page_size")
    if (
        not isinstance(next_cursors, dict)
        or not isinstance(total_counts, dict)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= 500
    ):
        raise ValueError("invalid multi-adapter catalog cursor payload")
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in next_cursors.items()
    ):
        raise ValueError("multi-adapter catalog cursors must contain string provider cursors")
    if any(
        not isinstance(key, str) or not isinstance(value, int) or value < 0
        for key, value in total_counts.items()
    ):
        raise ValueError("multi-adapter catalog totals must contain non-negative integers")
    return dict(next_cursors), dict(total_counts), page_size


class SourceAdapter(Protocol):
    """A bounded read adapter. Execution policy stays with the adapter."""

    name: str

    async def list_resources(self) -> list[ResourceDescriptor]: ...

    async def inspect(self, source: SourceRef) -> ResourceSnapshot: ...

    # Optional native authorization lookup. Adapters with server-side search
    # should implement this so inspecting one discovered source does not force
    # a full catalog scan. SourceRegistry uses a safe list fallback for older
    # adapters that do not expose it yet.
    async def authorize(
        self,
        source: SourceRef,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceDescriptor | None: ...

    # Optional relationship-aware expansion. Adapters that own a graph or
    # native lineage index can return a bounded neighborhood around approved
    # card sources without forcing SignalWeave to scan their catalog. The
    # method is intentionally optional so existing adapters remain valid.
    async def expand_related_resources(
        self,
        related_refs: list[str],
        *,
        limit: int,
        authorized_tenants: Iterable[str] | None = None,
    ) -> CatalogSearchPage: ...


class SourceRegistry:
    """Resolve insight-card source refs through explicitly installed adapters."""

    def __init__(
        self,
        adapters: Iterable[SourceAdapter] = (),
        *,
        max_concurrency: int = 8,
        authorized_tenants: Iterable[str] | None = None,
        enforce_catalog: bool = True,
        max_snapshot_bytes: int = 1_000_000,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if max_snapshot_bytes < 1:
            raise ValueError("max_snapshot_bytes must be positive")
        self._adapters: dict[str, SourceAdapter] = {}
        self._max_concurrency = max_concurrency
        self._authorized_tenants = (
            frozenset(authorized_tenants) if authorized_tenants is not None else None
        )
        self._enforce_catalog = enforce_catalog
        self._max_snapshot_bytes = max_snapshot_bytes
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

    async def list_resources(
        self,
        adapter_name: str | None = None,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> list[ResourceDescriptor]:
        tenant_scope = self._tenant_scope(authorized_tenants)
        if tenant_scope is not None and not tenant_scope:
            return []
        adapters = (
            [self._get(adapter_name)]
            if adapter_name
            else [self._adapters[name] for name in sorted(self._adapters)]
        )
        adapters = [
            adapter for adapter in adapters if self._adapter_is_in_scope(adapter, tenant_scope)
        ]
        resources: list[ResourceDescriptor] = []
        for adapter in adapters:
            resources.extend(await adapter.list_resources())
        return [resource for resource in resources if self._is_authorized(resource, tenant_scope)]

    async def search_resources(
        self,
        query: str,
        *,
        adapter_name: str | None = None,
        limit: int = 40,
        cursor: str | None = None,
        authorized_tenants: Iterable[str] | None = None,
    ) -> CatalogSearchPage:
        """Search the authorized catalog without forcing a full materialization.

        Adapters that own a server-side search or graph index should implement
        ``search_resources``.  Existing adapters fall back to ``list_resources``
        and are explicitly marked as ``local-scan-fallback`` so the caller can
        measure and replace that path before claiming enterprise scale.
        """
        if not query.strip():
            raise ValueError("catalog search query must not be empty")
        if not 1 <= limit <= 500:
            raise ValueError("catalog search limit must be between 1 and 500")
        multi_cursor: tuple[dict[str, str], dict[str, int]] | None = None
        if cursor and not adapter_name:
            multi_cursor = _decode_multi_adapter_cursor(cursor)
        tenant_scope = self._tenant_scope(authorized_tenants)
        if tenant_scope is not None and not tenant_scope:
            return CatalogSearchPage(
                total_count=0,
                provider="signalweave",
                strategy="tenant-scope-empty",
            )
        adapters = (
            [self._get(adapter_name)]
            if adapter_name
            else [self._adapters[name] for name in sorted(self._adapters)]
        )
        adapters = [
            adapter for adapter in adapters if self._adapter_is_in_scope(adapter, tenant_scope)
        ]
        if multi_cursor is not None:
            next_cursors, _, _ = multi_cursor
            adapters = [adapter for adapter in adapters if adapter.name in next_cursors]
            if not adapters:
                raise ValueError("multi-adapter catalog cursor has no active providers")
        if not adapters:
            return CatalogSearchPage(
                total_count=0,
                provider="signalweave",
                strategy="empty-catalog",
            )
        multi_mode = adapter_name is None and (multi_cursor is not None or len(adapters) > 1)
        per_adapter_limit = (
            multi_cursor[2]
            if multi_cursor is not None
            else max(1, (limit + len(adapters) - 1) // len(adapters))
        )
        pages: list[tuple[SourceAdapter, CatalogSearchPage]] = []
        for adapter in adapters:
            search = getattr(adapter, "search_resources", None)
            try:
                if callable(search):
                    supports_tenant_scope = tenant_scope is None or _accepts_keyword(
                        search, "authorized_tenants"
                    )
                    provider_cursor = (
                        cursor
                        if adapter_name
                        else (multi_cursor[0].get(adapter.name) if multi_cursor else None)
                    )
                    search_kwargs: dict[str, object] = {
                        "limit": per_adapter_limit,
                        "cursor": provider_cursor,
                    }
                    if tenant_scope is not None and supports_tenant_scope:
                        search_kwargs["authorized_tenants"] = sorted(tenant_scope)
                    page = await search(query, **search_kwargs)
                    page = (
                        page
                        if isinstance(page, CatalogSearchPage)
                        else CatalogSearchPage.model_validate(page)
                    )
                else:
                    resources = await adapter.list_resources()
                    authorized = [
                        resource
                        for resource in resources
                        if self._is_authorized(resource, tenant_scope)
                    ]
                    visible = _bounded_local_search(query, authorized, per_adapter_limit)
                    page = CatalogSearchPage(
                        resources=visible,
                        total_count=len(authorized),
                        has_more=len(authorized) > len(visible),
                        provider=adapter.name,
                        strategy="local-scan-fallback",
                        warnings=[
                            f"Adapter {adapter.name} does not implement bounded catalog search; "
                            "the catalog was locally scanned and lexically bounded before Jev ranking."
                        ],
                    )
            except Exception as error:  # noqa: BLE001 - isolate one provider outage
                pages.append(
                    (
                        adapter,
                        CatalogSearchPage(
                            total_count=0,
                            provider=adapter.name,
                            strategy="adapter-error",
                            warnings=[
                                f"Adapter {adapter.name} catalog search failed: "
                                f"{type(error).__name__}: {error}"
                            ],
                        ),
                    )
                )
                continue
            visible = [
                resource for resource in page.resources
                if self._is_authorized(resource, tenant_scope)
            ]
            if tenant_scope is not None and callable(search) and not supports_tenant_scope:
                # The provider returned an unscoped page. Filtering resources
                # is necessary but not sufficient: total_count may still
                # reveal another tenant's catalog size. A tenant-aware adapter
                # must opt into the keyword before claiming complete coverage.
                page = page.model_copy(
                    update={
                        "total_count": len(visible),
                        "warnings": [
                            *page.warnings,
                            f"Adapter {adapter.name} did not accept authorized_tenants; "
                            "catalog count was redacted and coverage requires a "
                            "tenant-aware search implementation.",
                        ],
                    }
                )
            pages.append(
                (adapter, page.model_copy(update={"resources": visible[:per_adapter_limit]}))
            )
        if len(adapters) > 1:
            # Give every installed adapter a chance to contribute candidates.  A
            # simple concatenation would let alphabetically earlier adapters
            # consume the entire bounded pool and hide relevant sources in later
            # systems (for example, SQL or Superset behind Airflow).
            resources = []
            for index in range(per_adapter_limit):
                for _, page in pages:
                    if index < len(page.resources) and len(resources) < limit:
                        resources.append(page.resources[index])
        else:
            resources = list(pages[0][1].resources)
        page = pages[0][1] if len(pages) == 1 and not multi_mode else None
        if page is not None:
            total_count = page.total_count
            has_more = page.has_more
            next_cursor = page.next_cursor
            warnings = list(page.warnings)
        else:
            previous_totals = multi_cursor[1] if multi_cursor else {}
            total_counts = {
                **previous_totals,
                **{adapter.name: page.total_count for adapter, page in pages},
            }
            next_cursors = {
                adapter.name: page.next_cursor
                for adapter, page in pages
                if page.has_more and page.next_cursor
            }
            total_count = sum(total_counts.values())
            has_more = bool(next_cursors) or any(page.has_more for _, page in pages)
            next_cursor = (
                _encode_multi_adapter_cursor(
                    next_cursors, total_counts, per_adapter_limit
                )
                if has_more and next_cursors
                else None
            )
            warnings = [warning for _, page in pages for warning in page.warnings]
            if any(page.has_more and not page.next_cursor for _, page in pages):
                warnings.append(
                    "At least one adapter reported more catalog results without a cursor; "
                    "that adapter was not continued."
                )
        return CatalogSearchPage(
            resources=resources,
            total_count=total_count,
            has_more=has_more,
            next_cursor=next_cursor,
            provider=(page.provider if page is not None else "signalweave"),
            strategy=(page.strategy if page is not None else "multi-adapter-search"),
            warnings=warnings,
        )

    async def expand_related_resources(
        self,
        related_refs: Iterable[str],
        *,
        limit: int = 40,
        authorized_tenants: Iterable[str] | None = None,
    ) -> CatalogSearchPage:
        """Ask installed adapters for a bounded relationship neighborhood.

        This is deliberately separate from lexical catalog search. A graph or
        native lineage index may know that a deployment, query, dashboard, or
        ownership record is related to an approved source even when none of
        their names overlap. Adapters that do not implement the optional
        method contribute no candidates and never trigger a local full scan.
        """
        if not 1 <= limit <= 500:
            raise ValueError("related-resource limit must be between 1 and 500")
        seeds = sorted({str(ref) for ref in related_refs if str(ref).strip()})
        if not seeds:
            return CatalogSearchPage(
                total_count=0,
                provider="signalweave",
                strategy="no-related-expansion",
            )
        tenant_scope = self._tenant_scope(authorized_tenants)
        if tenant_scope is not None and not tenant_scope:
            return CatalogSearchPage(
                total_count=0,
                provider="signalweave",
                strategy="tenant-scope-empty",
            )
        adapters = [
            self._adapters[name]
            for name in sorted(self._adapters)
            if self._adapter_is_in_scope(self._adapters[name], tenant_scope)
        ]
        if not adapters:
            return CatalogSearchPage(
                total_count=0,
                provider="signalweave",
                strategy="empty-catalog",
            )
        per_adapter_limit = max(1, (limit + len(adapters) - 1) // len(adapters))
        pages: list[CatalogSearchPage] = []
        warnings: list[str] = []
        for adapter in adapters:
            expand = getattr(adapter, "expand_related_resources", None)
            if not callable(expand):
                continue
            try:
                page = await expand(
                    seeds,
                    limit=per_adapter_limit,
                    authorized_tenants=authorized_tenants,
                )
                page = (
                    page
                    if isinstance(page, CatalogSearchPage)
                    else CatalogSearchPage.model_validate(page)
                )
            except Exception as error:  # noqa: BLE001 - isolate optional graph outages
                warnings.append(
                    f"Adapter {adapter.name} related expansion failed: "
                    f"{type(error).__name__}: {error}"
                )
                continue
            visible = [
                resource
                for resource in page.resources
                if self._is_authorized(resource, tenant_scope)
            ]
            pages.append(page.model_copy(update={"resources": visible[:per_adapter_limit]}))
            warnings.extend(page.warnings)
        resources: list[ResourceDescriptor] = []
        seen: set[tuple[str, str]] = set()
        for index in range(per_adapter_limit):
            for page in pages:
                if index >= len(page.resources):
                    continue
                resource = page.resources[index]
                identity = (resource.adapter, resource.resource)
                if identity in seen or len(resources) >= limit:
                    continue
                seen.add(identity)
                resources.append(resource)
        return CatalogSearchPage(
            resources=resources,
            total_count=sum(page.total_count for page in pages),
            has_more=any(page.has_more for page in pages),
            provider="signalweave-related-expansion",
            strategy="multi-adapter-related-expansion",
            warnings=warnings,
        )

    async def inspect(
        self,
        source: SourceRef,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceSnapshot:
        adapter = self._get(source.adapter)
        descriptor: ResourceDescriptor | None = None
        if self._enforce_catalog:
            descriptor = await self._authorize_descriptor(
                adapter, source, authorized_tenants=authorized_tenants
            )
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
        if self._enforce_catalog and descriptor is not None:
            snapshot = snapshot.model_copy(
                update={
                    "contract": descriptor.contract,
                    "source_url": snapshot.source_url or descriptor.source_url,
                }
            )
        return self._enforce_snapshot_budget(snapshot)

    async def authorize(
        self,
        source: SourceRef,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceDescriptor | None:
        """Authorize one source ref without fetching its data snapshot.

        Onboarding uses this path to retain an explicit human anchor in a
        bounded review. It verifies identity and tenant scope while avoiding a
        live query or inspection, so a temporary source outage is handled by
        the later workflow evaluation gate instead of corrupting card setup.
        """
        adapter = self._get(source.adapter)
        if not self._enforce_catalog:
            return ResourceDescriptor(
                adapter=source.adapter,
                resource=source.resource,
                kind="explicit-card-anchor",
                title=source.label,
            )
        return await self._authorize_descriptor(
            adapter,
            source,
            authorized_tenants=authorized_tenants,
        )

    def _enforce_snapshot_budget(self, snapshot: ResourceSnapshot) -> ResourceSnapshot:
        """Keep oversized adapter payloads out of Jev and fail them closed."""
        encoded = json.dumps(snapshot.model_dump(mode="json"), separators=(",", ":"))
        observed_bytes = len(encoded.encode("utf-8"))
        if observed_bytes <= self._max_snapshot_bytes:
            return snapshot
        return snapshot.model_copy(
            update={
                "observations": [],
                "evidence": [],
                "metadata": {
                    "signalweave_budget": {
                        "status": "exceeded",
                        "max_snapshot_bytes": self._max_snapshot_bytes,
                        "observed_snapshot_bytes": observed_bytes,
                    }
                },
                "error": (
                    "source snapshot exceeded the SignalWeave payload budget "
                    f"({observed_bytes} > {self._max_snapshot_bytes} bytes)"
                ),
            }
        )

    async def resolve(
        self,
        sources: Iterable[SourceRef],
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> list[ResourceSnapshot]:
        """Fetch sources independently so one broken source is visible to the engine."""
        source_list = list(sources)
        catalog: dict[tuple[str, str], ResourceDescriptor] = {}
        catalog_errors: dict[tuple[str, str], str] = {}
        for adapter_name in sorted({source.adapter for source in source_list}):
            try:
                adapter = self._get(adapter_name)
            except Exception as error:  # noqa: BLE001 - preserve missing adapter per source
                message = f"{type(error).__name__}: {error}"
                for source in [item for item in source_list if item.adapter == adapter_name]:
                    catalog_errors[(adapter_name, source.resource)] = message
                continue
            for source in [item for item in source_list if item.adapter == adapter_name]:
                try:
                    descriptor = await self._authorize_descriptor(
                        adapter, source, authorized_tenants=authorized_tenants
                    )
                    if descriptor is not None:
                        catalog[(descriptor.adapter, descriptor.resource)] = descriptor
                except Exception as error:  # noqa: BLE001 - isolate one catalog outage
                    catalog_errors[(adapter_name, source.resource)] = (
                        f"{type(error).__name__}: {error}"
                    )
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
            catalog_error = catalog_errors.get((source.adapter, source.resource))
            if catalog_error is not None:
                return ResourceSnapshot(
                    source_key=source.key,
                    adapter=source.adapter,
                    resource=source.resource,
                    title=source.label,
                    metadata={
                        "signalweave_resolution": {
                            "authorized": False,
                            "reason": "catalog-unavailable",
                        }
                    },
                    error=(
                        "authorized source catalog unavailable for adapter "
                        f"{source.adapter}: {catalog_error}"
                    ),
                )
            descriptor = catalog.get((source.adapter, source.resource))
            if self._enforce_catalog and descriptor is None:
                return ResourceSnapshot(
                    source_key=source.key,
                    adapter=source.adapter,
                    resource=source.resource,
                    title=source.label,
                    metadata={
                        "signalweave_resolution": {
                            "authorized": False,
                            "reason": "not-in-authorized-catalog",
                        }
                    },
                    error=(
                        "source is not present in the authorized adapter catalog; "
                        "rediscover it before evaluation"
                    ),
                )
            try:
                async with semaphore:
                    snapshot = await self.inspect(
                        source, authorized_tenants=authorized_tenants
                    )
            except Exception as error:  # noqa: BLE001 - source failure becomes typed evidence
                return ResourceSnapshot(
                    source_key=source.key,
                    adapter=source.adapter,
                    resource=source.resource,
                    title=source.label,
                    source_url=descriptor.source_url if descriptor is not None else None,
                    contract=descriptor.contract if descriptor is not None else ResourceContract(),
                    metadata={
                        "signalweave_resolution": {
                            "authorized": descriptor is not None,
                            "reason": "inspection-failed",
                        }
                    },
                    error=f"{type(error).__name__}: {error}",
                )
            if snapshot.source_key != source.key:
                snapshot = snapshot.model_copy(update={"source_key": source.key})
            if descriptor is not None:
                metadata = dict(snapshot.metadata)
                metadata["signalweave_resolution"] = {
                    "authorized": True,
                    "reason": "authorized",
                }
                snapshot = snapshot.model_copy(
                    update={
                        "contract": descriptor.contract,
                        "source_url": snapshot.source_url or descriptor.source_url,
                        "metadata": metadata,
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

    def _tenant_scope(
        self, authorized_tenants: Iterable[str] | None
    ) -> frozenset[str] | None:
        if authorized_tenants is None:
            return self._authorized_tenants
        return frozenset(authorized_tenants)

    async def _authorize_descriptor(
        self,
        adapter: SourceAdapter,
        source: SourceRef,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceDescriptor | None:
        """Authorize one opaque source ref with a bounded adapter operation."""

        tenant_scope = self._tenant_scope(authorized_tenants)
        if tenant_scope is not None and not tenant_scope:
            return None
        if not self._adapter_is_in_scope(adapter, tenant_scope):
            return None
        authorize = getattr(adapter, "authorize", None)
        if callable(authorize):
            descriptor = await authorize(source, authorized_tenants=tenant_scope)
            if descriptor is None:
                return None
            if not self._is_authorized(descriptor, tenant_scope):
                return None
            return descriptor
        catalog = {
            resource.resource: resource
            for resource in await self.list_resources(
                adapter.name, authorized_tenants=authorized_tenants
            )
        }
        return catalog.get(source.resource)

    @staticmethod
    def _is_authorized(
        resource: ResourceDescriptor, tenant_scope: frozenset[str] | None
    ) -> bool:
        if not resource.contract.authorized:
            return False
        if tenant_scope is not None and resource.contract.tenant_id not in tenant_scope:
            return False
        return True

    @staticmethod
    def _adapter_is_in_scope(
        adapter: SourceAdapter, tenant_scope: frozenset[str] | None
    ) -> bool:
        """Avoid contacting a tenant-bound adapter outside the request scope.

        Filtering returned descriptors is not enough for a shared deployment:
        calling a foreign adapter can still touch another tenant's provider,
        consume credentials, or expose timing/error side channels. Shipped
        hosted adapters publish ``tenant_id``; adapters without that optional
        attribute retain the existing descriptor-level authorization path.
        """
        if tenant_scope is None:
            return True
        adapter_tenant = getattr(adapter, "tenant_id", None)
        return adapter_tenant is None or str(adapter_tenant) in tenant_scope

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


def _accepts_keyword(function: object, keyword: str) -> bool:
    """Return whether an adapter search method can receive a scope keyword."""

    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == keyword or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )

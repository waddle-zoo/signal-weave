"""Read-only Looker Cloud connector for dashboards and Looks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from .hosted import HostedDataMode, HostedDataPolicy
from .models import (
    CatalogSearchPage,
    Evidence,
    Observation,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)


class LookerCloudClient:
    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_type: str = "token",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30,
    ) -> None:
        if not access_token and not (client_id and client_secret):
            raise ValueError("Looker requires access_token or client_id and client_secret")
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_type = token_type
        self.transport = transport
        self.timeout = timeout

    async def _login(self) -> str:
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout, transport=self.transport
        ) as client:
            response = await client.post(
                "/api/4.0/login",
                params={"client_id": self.client_id, "client_secret": self.client_secret},
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if not token:
                raise ValueError("Looker login response did not contain access_token")
            self.access_token = str(token)
            return self.access_token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self.access_token:
            await self._login()
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"{self.token_type} {self.access_token}"},
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
            if response.status_code == 401 and self.client_id and self.client_secret:
                self.access_token = None
                await self._login()
                response = await client.request(
                    method,
                    path,
                    headers={"Authorization": f"{self.token_type} {self.access_token}"},
                    **kwargs,
                )
            response.raise_for_status()
            return response

    async def search_dashboards(self, *, limit: int = 100, offset: int = 0, title: str | None = None):
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if title:
            params["title"] = title
        payload = (await self._request("GET", "/api/4.0/dashboards/search", params=params)).json()
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    async def search_looks(self, *, limit: int = 100, offset: int = 0, title: str | None = None):
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if title:
            params["title"] = title
        payload = (await self._request("GET", "/api/4.0/looks/search", params=params)).json()
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any]:
        payload = (await self._request("GET", f"/api/4.0/dashboards/{dashboard_id}")).json()
        return payload if isinstance(payload, dict) else {}

    async def get_look(self, look_id: str) -> dict[str, Any]:
        payload = (await self._request("GET", f"/api/4.0/look/{look_id}")).json()
        return payload if isinstance(payload, dict) else {}

    async def run_look(self, look_id: str, *, use_cache: bool) -> list[dict[str, Any]]:
        payload = (
            await self._request(
                "GET",
                f"/api/4.0/look/{look_id}/run/json",
                params={"cache": "true" if use_cache else "false"},
            )
        ).json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        rows = payload.get("data") if isinstance(payload, dict) else None
        return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _contract(tenant_id: str, *, role: str = "primary") -> ResourceContract:
    return ResourceContract(tenant_id=tenant_id, domain="bi", roles=[role])


def _resource_id(resource: str, expected: str) -> str:
    kind, separator, identifier = resource.partition(":")
    if kind != expected or not separator or not identifier:
        raise ValueError(f"Looker resources must use {expected}:<id>")
    return identifier


def _observations(source_key: str, rows: list[dict[str, Any]], limit: int) -> list[Observation]:
    result: list[Observation] = []
    for index, row in enumerate(rows[:limit]):
        for metric, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result.append(
                    Observation(
                        source_key=source_key,
                        subject_id=f"row-{index}",
                        subject_label=str(row.get("label") or row.get("name") or index),
                        subject_type="looker_result",
                        metric=str(metric),
                        current=float(value),
                        dimensions={
                            str(key): item
                            for key, item in row.items()
                            if key != metric and not isinstance(item, (int, float, bool))
                        },
                    )
                )
    return result


class LookerAdapter:
    name = "looker"

    def __init__(
        self,
        client: LookerCloudClient,
        *,
        tenant_id: str,
        policy: HostedDataPolicy | None = None,
        adapter_name: str = "looker",
    ) -> None:
        self.client = client
        self.tenant_id = tenant_id
        self.policy = policy or HostedDataPolicy()
        self.name = adapter_name
        self.provider_name = "looker"

    def _descriptor(self, item: dict[str, Any], kind: str) -> ResourceDescriptor:
        identifier = str(item.get("id") or item.get("dashboard_id") or item.get("look_id") or "")
        if not identifier:
            raise ValueError(f"Looker {kind} metadata did not expose an id")
        return ResourceDescriptor(
            adapter=self.name,
            resource=f"{kind}:{identifier}",
            kind=kind,
            title=str(item.get("title") or item.get("dashboard_title") or item.get("model") or identifier),
            description=str(item.get("description") or ""),
            source_url=item.get("url"),
            metadata={"owner": item.get("user_name") or item.get("owner")},
            contract=_contract(self.tenant_id),
        )

    async def list_resources(self) -> list[ResourceDescriptor]:
        dashboards = await self.client.search_dashboards()
        looks = await self.client.search_looks()
        return [self._descriptor(item, "dashboard") for item in dashboards] + [
            self._descriptor(item, "look") for item in looks
        ]

    async def search_resources(
        self,
        query: str,
        *,
        limit: int,
        cursor: str | None = None,
        authorized_tenants: Iterable[str] | None = None,
    ) -> CatalogSearchPage:
        if authorized_tenants is not None and self.tenant_id not in set(authorized_tenants):
            return CatalogSearchPage(provider=self.name, strategy="looker-tenant-denied", total_count=0)
        offset = int(cursor or 0)
        dashboards = await self.client.search_dashboards(limit=limit, offset=offset, title=query.strip() or None)
        resources = [self._descriptor(item, "dashboard") for item in dashboards]
        return CatalogSearchPage(
            resources=resources,
            total_count=len(resources),
            has_more=len(resources) >= limit,
            next_cursor=str(offset + len(resources)) if len(resources) >= limit else None,
            provider=self.name,
            strategy="looker-server-search",
        )

    async def authorize(
        self,
        source: SourceRef,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceDescriptor | None:
        if authorized_tenants is not None and self.tenant_id not in set(authorized_tenants):
            return None
        if source.resource.startswith("dashboard:"):
            return self._descriptor(await self.client.get_dashboard(_resource_id(source.resource, "dashboard")), "dashboard")
        if source.resource.startswith("look:"):
            return self._descriptor(await self.client.get_look(_resource_id(source.resource, "look")), "look")
        raise ValueError("Looker resources must use dashboard:<id> or look:<id>")

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        if source.resource.startswith("dashboard:"):
            identifier = _resource_id(source.resource, "dashboard")
            payload = await self.client.get_dashboard(identifier)
            title = str(payload.get("title") or payload.get("dashboard_title") or identifier)
            return ResourceSnapshot(
                source_key=source.key,
                adapter=self.name,
                resource=source.resource,
                title=title,
                description=str(payload.get("description") or ""),
                evidence=[
                    Evidence(
                        source_key=source.key,
                        subject_id=identifier,
                        subject_label=title,
                        statement=f"Looker dashboard {title} is accessible to the connected instance.",
                        values={"dashboard_id": identifier, "element_count": len(payload.get("dashboard_elements") or [])},
                        source_url=payload.get("url"),
                    )
                ],
                metadata={
                    "provider": self.provider_name,
                    "data_policy_mode": self.policy.mode.value,
                    "dashboard_id": identifier,
                },
                source_url=payload.get("url"),
                contract=_contract(self.tenant_id),
            )
        identifier = _resource_id(source.resource, "look")
        payload = await self.client.get_look(identifier)
        title = str(payload.get("title") or identifier)
        rows: list[dict[str, Any]] = []
        error: str | None = None
        if self.policy.mode != HostedDataMode.METADATA_ONLY:
            rows = await self.client.run_look(
                identifier, use_cache=self.policy.mode == HostedDataMode.CACHED_RESULTS
            )
        if self.policy.mode == HostedDataMode.LIVE_QUERY and not self.policy.allow_live_queries:
            error = "Looker live query blocked by connection policy"
            rows = []
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=title,
            description=str(payload.get("description") or ""),
            observations=_observations(source.key, rows, self.policy.max_result_rows),
            evidence=[
                Evidence(
                    source_key=source.key,
                    subject_id=identifier,
                    subject_label=title,
                    statement=f"Looker Look {title} was retrieved under the connection policy.",
                    values={"look_id": identifier, "query": payload.get("query")},
                    source_url=payload.get("url"),
                )
            ],
            metadata={
                "provider": self.provider_name,
                "data_policy_mode": self.policy.mode.value,
                "look_id": identifier,
            },
            error=error,
            source_url=payload.get("url"),
            contract=_contract(self.tenant_id),
        )

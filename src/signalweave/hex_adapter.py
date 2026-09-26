"""Read-only Hex Cloud connector.

Hex projects are treated as analytical artifacts.  SignalWeave can inspect
published project metadata and recent runs, but it never mutates a project and
never executes a fresh run unless the connection policy explicitly permits it.
"""

from __future__ import annotations

import re
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


class HexCloudClient:
    def __init__(
        self,
        base_url: str,
        *,
        access_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30,
    ) -> None:
        if not access_token:
            raise ValueError("Hex requires an access token")
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.transport = transport
        self.timeout = timeout

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

    async def list_projects_page(
        self, *, after: str | None = None, limit: int = 100
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {"limit": limit}
        if after:
            params["after"] = after
        payload = (await self._request("GET", "/api/v1/projects", params=params)).json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)], None
        rows = payload.get("values") or payload.get("projects") or payload.get("results") or []
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        next_page = pagination.get("after") if isinstance(pagination, dict) else None
        return (
            [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else [],
            str(next_page) if next_page else None,
        )

    async def list_projects(self, *, max_pages: int = 100) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        limit = 100
        after: str | None = None
        for _ in range(max_pages):
            rows, next_page = await self.list_projects_page(after=after, limit=limit)
            projects.extend(rows)
            if not rows or not next_page:
                break
            after = next_page
        return projects

    async def get_project(self, project_id: str) -> dict[str, Any]:
        payload = (await self._request("GET", f"/api/v1/projects/{project_id}")).json()
        return payload.get("project", payload) if isinstance(payload, dict) else {}

    async def list_runs(self, project_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        payload = (
            await self._request(
                "GET", f"/api/v1/projects/{project_id}/runs", params={"limit": limit}
            )
        ).json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        rows = payload.get("runs") or payload.get("results") or payload.get("data") or []
        return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []

    async def get_cell_output(self, cell_id: str) -> dict[str, Any]:
        payload = (await self._request("GET", f"/api/v1/cells/{cell_id}/output")).json()
        return payload if isinstance(payload, dict) else {}

    async def run_project(self, project_id: str, *, use_cached_sql_results: bool = True) -> dict[str, Any]:
        payload = (
            await self._request(
                "POST",
                f"/api/v1/projects/{project_id}/runs",
                json={"useCachedSqlResults": use_cached_sql_results},
            )
        ).json()
        return payload.get("run", payload) if isinstance(payload, dict) else {}


def _contract(tenant_id: str, *, role: str = "primary") -> ResourceContract:
    return ResourceContract(tenant_id=tenant_id, domain="bi", roles=[role])


def _project_id(resource: str) -> str:
    kind, separator, identifier = resource.partition(":")
    if kind != "project" or not separator or not identifier:
        raise ValueError("Hex resources must use project:<id>")
    return identifier


def _observations_from_rows(source_key: str, rows: list[dict[str, Any]]) -> list[Observation]:
    observations: list[Observation] = []
    for index, row in enumerate(rows[:500]):
        numeric = {
            key: float(value)
            for key, value in row.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        for metric, current in numeric.items():
            observations.append(
                Observation(
                    source_key=source_key,
                    subject_id=f"row-{index}",
                    subject_label=str(row.get("name") or row.get("label") or index),
                    subject_type="hex_result",
                    metric=metric,
                    current=current,
                    dimensions={
                        str(key): value
                        for key, value in row.items()
                        if key != metric and not isinstance(value, (int, float, bool))
                    },
                )
            )
    return observations


class HexAdapter:
    name = "hex"

    def __init__(
        self,
        client: HexCloudClient,
        *,
        tenant_id: str,
        policy: HostedDataPolicy | None = None,
        adapter_name: str = "hex",
    ) -> None:
        self.client = client
        self.tenant_id = tenant_id
        self.policy = policy or HostedDataPolicy()
        self.name = adapter_name
        self.provider_name = "hex"

    @staticmethod
    def _project_title(project: dict[str, Any]) -> str:
        return str(project.get("name") or project.get("title") or project.get("projectId") or "Untitled project")

    def _descriptor(self, project: dict[str, Any]) -> ResourceDescriptor:
        project_id = str(project.get("projectId") or project.get("id") or "")
        if not project_id:
            raise ValueError("Hex project metadata did not expose a project id")
        return ResourceDescriptor(
            adapter=self.name,
            resource=f"project:{project_id}",
            kind="project",
            title=self._project_title(project),
            description=str(project.get("description") or ""),
            source_url=project.get("url"),
            metadata={
                "owner": project.get("owner") or project.get("ownerEmail"),
                "status": project.get("status") or project.get("publicationStatus"),
            },
            contract=_contract(self.tenant_id),
        )

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [self._descriptor(project) for project in await self.client.list_projects()]

    async def search_resources(
        self,
        query: str,
        *,
        limit: int,
        cursor: str | None = None,
        authorized_tenants: Iterable[str] | None = None,
    ) -> CatalogSearchPage:
        if authorized_tenants is not None and self.tenant_id not in set(authorized_tenants):
            return CatalogSearchPage(
                provider=self.name,
                strategy="hex-tenant-denied",
                total_count=0,
            )
        projects, next_page = await self.client.list_projects_page(
            after=cursor, limit=limit
        )
        terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
        resources = [
            self._descriptor(project)
            for project in projects
            if not terms
            or terms.intersection(
                set(
                    re.findall(
                        r"[a-z0-9]+",
                        " ".join(
                            str(project.get(key) or "")
                            for key in ("title", "name", "description", "id")
                        ).lower(),
                    )
                )
            )
        ]
        has_more = bool(next_page)
        return CatalogSearchPage(
            resources=resources,
            total_count=len(resources),
            has_more=has_more,
            next_cursor=next_page if has_more else None,
            provider=self.name,
            strategy="hex-paginated-filter",
            warnings=[
                "Hex project listing is cursor-paginated but does not expose native text search; "
                "this page was filtered locally and callers must continue the cursor for coverage."
            ],
        )

    async def authorize(
        self,
        source: SourceRef,
        *,
        authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceDescriptor | None:
        if authorized_tenants is not None and self.tenant_id not in set(authorized_tenants):
            return None
        return self._descriptor(await self.client.get_project(_project_id(source.resource)))

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        project_id = _project_id(source.resource)
        project = await self.client.get_project(project_id)
        title = self._project_title(project)
        evidence = [
            Evidence(
                source_key=source.key,
                subject_id=project_id,
                subject_label=title,
                statement=f"Hex project {title} is accessible to the connected workspace.",
                values={
                    "project_id": project_id,
                    "published": project.get("published") or project.get("publicationStatus"),
                },
                source_url=project.get("url"),
            )
        ]
        metadata: dict[str, Any] = {
            "provider": self.provider_name,
            "project_id": project_id,
            "data_policy_mode": self.policy.mode.value,
        }
        observations: list[Observation] = []
        error: str | None = None
        if self.policy.mode != HostedDataMode.METADATA_ONLY:
            runs = await self.client.list_runs(project_id, limit=20)
            latest = runs[0] if runs else None
            if latest:
                metadata["latest_run"] = {
                    key: latest.get(key)
                    for key in ("runId", "status", "startedAt", "completedAt", "url")
                    if latest.get(key) is not None
                }
                cell_ids = source.parameters.get("cell_ids") or []
                if not isinstance(cell_ids, list) or not all(isinstance(item, str) for item in cell_ids):
                    raise ValueError("Hex source parameters.cell_ids must be a list of strings")
                for cell_id in cell_ids[:20]:
                    output = await self.client.get_cell_output(cell_id)
                    result = output.get("result") if isinstance(output, dict) else None
                    rows = result.get("rows", []) if isinstance(result, dict) else []
                    if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                        observations.extend(_observations_from_rows(source.key, rows))
            if self.policy.mode == HostedDataMode.LIVE_QUERY:
                if not self.policy.allow_live_queries:
                    error = "Hex live query blocked by connection policy"
                elif not latest or latest.get("status") not in {"completed", "succeeded", "success"}:
                    latest = await self.client.run_project(project_id)
                    metadata["fresh_run"] = {
                        key: latest.get(key)
                        for key in ("runId", "status", "startedAt", "completedAt", "url")
                        if latest.get(key) is not None
                    }
        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=title,
            description=str(project.get("description") or ""),
            observations=observations[: self.policy.max_result_rows],
            evidence=evidence,
            metadata=metadata,
            error=error,
            source_url=project.get("url"),
            contract=_contract(self.tenant_id),
        )

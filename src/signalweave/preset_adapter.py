"""Preset Cloud API client and adapter.

Preset Cloud exposes Superset-compatible dashboard/chart endpoints on the
customer workspace.  Authentication is kept separate from the source adapter:
the client exchanges an API token for a short-lived workspace JWT, while the
generic adapter turns the resulting artifacts into SignalWeave snapshots.
"""

from __future__ import annotations

from typing import Any

import httpx

from .hosted import HostedDataMode, HostedDataPolicy
from .superset_adapter import SupersetAdapter
from .superset_client import SupersetClient


class PresetPolicyError(ValueError):
    """Raised when a provider response violates the connection data policy."""


class PresetCloudClient(SupersetClient):
    """Read-only Preset Cloud client with API-token or bearer authentication."""

    def __init__(
        self,
        workspace_url: str,
        *,
        access_token: str | None = None,
        api_token_name: str | None = None,
        api_token_secret: str | None = None,
        api_base_url: str = "https://api.app.preset.io",
        max_result_rows: int | None = None,
        max_snapshot_bytes: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not access_token and not (api_token_name and api_token_secret):
            raise ValueError("Preset requires access_token or api token name and secret")
        super().__init__(workspace_url)
        self._token = access_token
        self._api_token_name = api_token_name
        self._api_token_secret = api_token_secret
        self.api_base_url = api_base_url.rstrip("/")
        self.max_result_rows = max_result_rows
        self.max_snapshot_bytes = max_snapshot_bytes
        self._force_refresh = False
        self._transport = transport

    def constrain_response_limits(self, *, max_result_rows: int, max_snapshot_bytes: int) -> None:
        """Apply the connection policy without allowing a caller to loosen client limits."""

        self.max_result_rows = (
            max_result_rows
            if self.max_result_rows is None
            else min(self.max_result_rows, max_result_rows)
        )
        self.max_snapshot_bytes = (
            max_snapshot_bytes
            if self.max_snapshot_bytes is None
            else min(self.max_snapshot_bytes, max_snapshot_bytes)
        )

    def set_query_mode(self, *, force_refresh: bool) -> None:
        """Set the explicit provider query mode selected by the connection policy."""

        self._force_refresh = force_refresh

    async def _auth_headers(self, force_refresh: bool = False) -> dict[str, str]:
        if self._token and not force_refresh:
            return {"Authorization": f"Bearer {self._token}"}
        if not self._api_token_name or not self._api_token_secret:
            raise RuntimeError("Preset access token is unavailable")
        async with self._auth_lock:
            if self._token and not force_refresh:
                return {"Authorization": f"Bearer {self._token}"}
            async with httpx.AsyncClient(
                base_url=self.api_base_url,
                timeout=20,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    "/v1/auth/",
                    json={"name": self._api_token_name, "secret": self._api_token_secret},
                )
                response.raise_for_status()
                payload = response.json()
                token = payload.get("payload", {}).get("access_token")
                if not token:
                    raise ValueError("Preset auth response did not contain payload.access_token")
                self._token = str(token)
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers,
            transport=self._transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
            if response.status_code == 401 and self._api_token_name:
                self._token = None
                response = await client.request(
                    method,
                    path,
                    headers=await self._auth_headers(force_refresh=True),
                    **kwargs,
                )
            response.raise_for_status()
            if (
                self.max_snapshot_bytes is not None
                and len(response.content) > self.max_snapshot_bytes
            ):
                raise PresetPolicyError(
                    "Preset response exceeded the configured max_snapshot_bytes limit"
                )
            return response

    async def chart_data(self, chart: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch saved chart results with a hard row bound and no forced refresh.

        Preset's Superset-compatible endpoint may return several result envelopes.
        We cap the request and reject a provider response that ignores the cap;
        silently truncating a time series would create a false current value.
        """

        payload = self._saved_query_context(chart) or self._query_context(chart)
        if self.max_result_rows is not None:
            for query in payload.get("queries", []):
                if isinstance(query, dict):
                    requested = query.get("row_limit")
                    query["row_limit"] = min(
                        self.max_result_rows,
                        int(requested) if isinstance(requested, int) else self.max_result_rows,
                    )
        payload["force"] = self._force_refresh
        response = await self._request("POST", "/api/v1/chart/data", timeout=60, json=payload)
        result = response.json().get("result", [])
        envelopes = [result] if isinstance(result, dict) else result if isinstance(result, list) else []
        if self.max_result_rows is not None:
            row_count = sum(
                len(self._rows_from_result_item(item))
                for item in envelopes
                if isinstance(item, dict)
            )
            if row_count > self.max_result_rows:
                raise PresetPolicyError(
                    "Preset chart response exceeded the configured max_result_rows limit"
                )
        return [item for item in envelopes if isinstance(item, dict)]


class PresetAdapter(SupersetAdapter):
    """Preset-hosted dashboard adapter using the generic Superset artifact shape."""

    def __init__(
        self,
        client: PresetCloudClient,
        *,
        tenant_id: str,
        policy: HostedDataPolicy | None = None,
        adapter_name: str = "preset",
    ) -> None:
        super().__init__(
            client,
            adapter_name=adapter_name,
            tenant_id=tenant_id,
            provider_name="preset",
        )
        self.policy = policy or HostedDataPolicy()
        client.constrain_response_limits(
            max_result_rows=self.policy.max_result_rows,
            max_snapshot_bytes=self.policy.max_snapshot_bytes,
        )
        client.set_query_mode(force_refresh=self.policy.mode == HostedDataMode.LIVE_QUERY)

    async def _inspect_dashboard(self, source, dashboard_id):
        if self.policy.mode.value == "metadata_only":
            snapshot = await self.client.dashboard_snapshot(
                dashboard_id, include_data=False, chart_ids=source.parameters.get("chart_ids")
            )
            return self._metadata_only_snapshot(source, snapshot)
        if self.policy.mode.value == "live_query" and not self.policy.allow_live_queries:
            raise ValueError("Preset live queries are disabled by the connection policy")
        snapshot = await super()._inspect_dashboard(source, dashboard_id)
        return snapshot.model_copy(
            update={
                "adapter": self.name,
                "contract": self._contract(),
                "metadata": {**snapshot.metadata, "provider": self.provider_name},
            }
        )

    def _metadata_only_snapshot(self, source, dashboard):
        from .models import Evidence, ResourceSnapshot

        return ResourceSnapshot(
            source_key=source.key,
            adapter=self.name,
            resource=source.resource,
            title=dashboard.title,
            description=dashboard.description,
            evidence=[
                Evidence(
                    source_key=source.key,
                    subject_id=chart.id,
                    subject_label=chart.title,
                    statement=f"Preset chart {chart.title} is present on the dashboard.",
                    values={
                        "metric": chart.metric,
                        "metrics": chart.metrics,
                        "viz_type": chart.viz_type,
                        "semantic_status": chart.semantic_status,
                    },
                    source_url=dashboard.source_url,
                )
                for chart in dashboard.charts
            ],
            metadata={
                "provider": self.provider_name,
                "data_policy_mode": self.policy.mode.value,
                "dashboard_id": dashboard.id,
                "chart_count": len(dashboard.charts),
            },
            source_url=dashboard.source_url,
            captured_at=dashboard.captured_at,
            contract=self._contract(),
        )

    def _contract(self):
        from .models import ResourceContract

        return ResourceContract(tenant_id=self.tenant_id, domain="bi", roles=["primary"])

    async def _inspect_chart(self, source, chart_id):
        if self.policy.mode.value == "metadata_only":
            chart = await self.client.get_chart_metadata(chart_id)
            from .models import Evidence, ResourceSnapshot

            title = str(chart.get("slice_name") or chart_id)
            return ResourceSnapshot(
                source_key=source.key,
                adapter=self.name,
                resource=source.resource,
                title=title,
                description=str(chart.get("description") or ""),
                evidence=[
                    Evidence(
                        source_key=source.key,
                        subject_id=str(chart_id),
                        subject_label=title,
                        statement=f"Preset chart {title} metadata was retrieved.",
                        values={"metric": "unknown"},
                        source_url=chart.get("url"),
                    )
                ],
                metadata={"provider": self.provider_name, "data_policy_mode": self.policy.mode.value},
                source_url=chart.get("url"),
                contract=self._contract(),
            )
        snapshot = await super()._inspect_chart(source, chart_id)
        return snapshot.model_copy(
            update={
                "adapter": self.name,
                "contract": self._contract(),
                "metadata": {**snapshot.metadata, "provider": self.provider_name},
            }
        )

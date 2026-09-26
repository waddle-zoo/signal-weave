"""Preset Cloud API client and adapter.

Preset Cloud exposes Superset-compatible dashboard/chart endpoints on the
customer workspace.  Authentication is kept separate from the source adapter:
the client exchanges an API token for a short-lived workspace JWT, while the
generic adapter turns the resulting artifacts into SignalWeave snapshots.
"""

from __future__ import annotations

from typing import Any

import httpx

from .hosted import HostedDataPolicy
from .superset_adapter import SupersetAdapter
from .superset_client import SupersetClient


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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not access_token and not (api_token_name and api_token_secret):
            raise ValueError("Preset requires access_token or api token name and secret")
        super().__init__(workspace_url)
        self._token = access_token
        self._api_token_name = api_token_name
        self._api_token_secret = api_token_secret
        self.api_base_url = api_base_url.rstrip("/")
        self._transport = transport

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
            return response


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
                    values={"metric": chart.metric},
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

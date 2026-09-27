"""Preset Cloud API client and adapter.

Preset Cloud exposes Superset-compatible dashboard/chart endpoints on the
customer workspace.  Authentication is kept separate from the source adapter:
the client exchanges an API token for a short-lived workspace JWT, while the
generic adapter turns the resulting artifacts into SignalWeave snapshots.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

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
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        for field_name, url in {
            "Preset workspace_url": workspace_url,
            "Preset api_base_url": api_base_url,
        }.items():
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError(f"{field_name} must use https")
            if parsed.username or parsed.password:
                raise ValueError(f"{field_name} must not contain credentials")
            if parsed.path not in {"", "/"}:
                raise ValueError(f"{field_name} must be an origin without a path")
            if parsed.query or parsed.fragment:
                raise ValueError(
                    f"{field_name} must be an origin without query or fragment"
                )
        if access_token and (api_token_name or api_token_secret):
            raise ValueError("Preset requires exactly one authentication mode")
        if not access_token and not (api_token_name and api_token_secret):
            raise ValueError("Preset requires access_token or api token name and secret")
        if max_retries < 0:
            raise ValueError("Preset max_retries must be non-negative")
        if retry_backoff_seconds < 0:
            raise ValueError("Preset retry_backoff_seconds must be non-negative")
        super().__init__(workspace_url)
        self._token = access_token
        self._api_token_name = api_token_name
        self._api_token_secret = api_token_secret
        self.api_base_url = api_base_url.rstrip("/")
        self.max_result_rows = max_result_rows
        self.max_snapshot_bytes = max_snapshot_bytes
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
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
            await self._exchange_token()
        return {"Authorization": f"Bearer {self._token}"}

    async def _exchange_token(self) -> None:
        """Exchange the configured API token for one short-lived JWT.

        Callers that need to coordinate a refresh must hold ``_auth_lock``.
        Keeping the exchange separate lets a 401 waiter reuse a token another
        concurrent request obtained while it was waiting on that lock.
        """

        async with httpx.AsyncClient(
            base_url=self.api_base_url,
            timeout=20,
            transport=self._transport,
        ) as client:
            response = await self._request_with_retries(
                client,
                "POST",
                "/v1/auth/",
                json={"name": self._api_token_name, "secret": self._api_token_secret},
            )
            response.raise_for_status()
            payload = response.json()
            auth_payload = payload.get("payload") if isinstance(payload, dict) else None
            token = (
                auth_payload.get("access_token")
                if isinstance(auth_payload, dict)
                else None
            )
            if not isinstance(token, str) or not token.strip():
                raise ValueError("Preset auth response did not contain payload.access_token")
            self._token = token

    async def _refresh_after_401(self, stale_token: str | None) -> dict[str, str]:
        """Refresh once for all requests that observed the same stale token."""

        if not self._api_token_name or not self._api_token_secret:
            raise RuntimeError("Preset access token is unavailable")
        async with self._auth_lock:
            # Another request may have refreshed while this one waited. Reuse
            # that newer token instead of creating another auth exchange.
            if self._token and self._token != stale_token:
                return {"Authorization": f"Bearer {self._token}"}
            self._token = None
            await self._exchange_token()
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
        request_kwargs = dict(kwargs)
        request_headers = dict(headers)
        supplied_headers = request_kwargs.pop("headers", None)
        if supplied_headers:
            request_headers.update(supplied_headers)
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=self._transport,
        ) as client:
            response = await self._request_with_retries(
                client,
                method,
                path,
                headers=request_headers,
                **request_kwargs,
            )
            if response.status_code == 401 and self._api_token_name:
                stale_authorization = request_headers.get("Authorization", "")
                stale_token = stale_authorization.removeprefix("Bearer ") or None
                request_headers = dict(await self._refresh_after_401(stale_token))
                response = await self._request_with_retries(
                    client,
                    method,
                    path,
                    headers=request_headers,
                    **request_kwargs,
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

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        value = response.headers.get("retry-after")
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        return min(max(seconds, 0.0), 5.0)

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        response = await client.request(method, path, **kwargs)
        retries = 0
        while response.status_code == 429 or 500 <= response.status_code <= 599:
            if retries >= self.max_retries:
                break
            retry_after = self._retry_after_seconds(response)
            delay = (
                retry_after
                if retry_after is not None
                else min(self.retry_backoff_seconds * (2**retries), 5.0)
            )
            if delay:
                await asyncio.sleep(delay)
            response = await client.request(method, path, **kwargs)
            retries += 1
        return response

    async def chart_data(
        self,
        chart: dict[str, Any],
        *,
        dashboard_id: int | str | None = None,
        allow_unscoped_fallback: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch chart results with a hard response bound.

        Preset's Superset-compatible endpoint may return several result envelopes.
        Dashboard reads use Preset's chart-specific endpoint so its dashboard
        filter scope and access checks are applied. Standalone reads use the
        saved query endpoint. We reject a provider response that ignores the
        configured response cap; silently truncating a time series would create
        a false current value.
        """

        # Preset's dashboard endpoint is the only accepted dashboard-scoped
        # path. It must never fall back to an unfiltered POST query.
        del allow_unscoped_fallback
        if dashboard_id is not None:
            response = await self._request(
                "GET",
                f"/api/v1/chart/{chart['id']}/data",
                timeout=60,
                params={
                    "format": "json",
                    "type": "full",
                    "force": "true" if self._force_refresh else "false",
                    # Preset Cloud documents the singular spelling. The
                    # generic Superset client uses the upstream plural form.
                    "filter_dashboard_id": str(dashboard_id),
                },
            )
        else:
            payload = self._saved_query_context(chart) or self._query_context(chart)
            if self.max_result_rows is not None:
                for query in payload.get("queries", []):
                    if isinstance(query, dict):
                        requested = query.get("row_limit")
                        query["row_limit"] = min(
                            self.max_result_rows,
                            int(requested)
                            if isinstance(requested, int)
                            else self.max_result_rows,
                        )
            payload["force"] = self._force_refresh
            response = await self._request(
                "POST", "/api/v1/chart/data", timeout=60, json=payload
            )
        if response.status_code == 202:
            raise PresetPolicyError(
                "Preset returned an asynchronous chart response; polling is not enabled "
                "for this bounded connector"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise PresetPolicyError("Preset chart response was not valid JSON") from error
        if not isinstance(body, dict):
            raise PresetPolicyError("Preset chart response was not a JSON object")
        if dashboard_id is not None and not isinstance(body.get("dashboard_filters"), dict):
            raise PresetPolicyError(
                "Preset dashboard-filter response did not include dashboard_filters metadata"
            )
        if "result" not in body:
            raise PresetPolicyError("Preset chart response did not include a result envelope")
        result = body["result"]
        if not isinstance(result, (dict, list)):
            raise PresetPolicyError(
                "Preset chart response contained an unsupported result envelope"
            )
        if isinstance(result, list) and any(not isinstance(item, dict) for item in result):
            raise PresetPolicyError(
                "Preset chart response contained a non-object result envelope"
            )
        envelopes = [result] if isinstance(result, dict) else result
        successful_statuses = {"success", "completed", "complete", "ok"}
        for item in envelopes:
            status = item.get("status")
            normalized_status = str(status).strip().lower() if status is not None else ""
            if normalized_status and normalized_status not in successful_statuses:
                raise PresetPolicyError(
                    "Preset chart response reported an unsupported or non-success "
                    f"query status: {status}"
                )
            provider_error = item.get("error")
            if provider_error not in (None, False, ""):
                raise PresetPolicyError(
                    "Preset chart response reported a query error"
                )
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
            return self._enforce_dashboard_budget(
                source, self._metadata_only_snapshot(source, snapshot)
            )
        if self.policy.mode.value == "live_query" and not self.policy.allow_live_queries:
            raise ValueError("Preset live queries are disabled by the connection policy")
        snapshot = await super()._inspect_dashboard(source, dashboard_id)
        scoped_snapshot = snapshot.model_copy(
            update={
                "adapter": self.name,
                "contract": self._contract(),
                "metadata": {**snapshot.metadata, "provider": self.provider_name},
            }
        )
        return self._enforce_dashboard_budget(source, scoped_snapshot)

    def _enforce_dashboard_budget(self, source, snapshot):
        """Keep the aggregate Jev input bounded across dashboard fan-out.

        The HTTP client bounds each chart response, but a dashboard can contain
        hundreds of charts. Without an aggregate check, a valid per-chart
        response set could still create an oversized Jev request. Dropping the
        entire evidence payload is safer than sending an incomplete slice that
        could look like a complete dashboard analysis.
        """

        snapshot_bytes = len(
            json.dumps(
                snapshot.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if snapshot_bytes <= self.policy.max_snapshot_bytes:
            return snapshot

        chart_count = snapshot.metadata.get("chart_count")
        if not isinstance(chart_count, int):
            chart_count = len(snapshot.metadata.get("charts", []))
        metadata = {
            "provider": self.provider_name,
            "data_policy_mode": self.policy.mode.value,
            "dashboard_id": snapshot.metadata.get("dashboard_id"),
            "parameters": source.parameters,
            "data_quality": {
                "status": "failed",
                "reason": "dashboard_snapshot_bytes_exceeded",
                "snapshot_bytes": snapshot_bytes,
                "max_snapshot_bytes": self.policy.max_snapshot_bytes,
                "chart_count": chart_count,
            },
        }
        return snapshot.model_copy(
            update={
                "title": snapshot.title[:200],
                "description": "",
                "observations": [],
                "evidence": [],
                "metadata": metadata,
                "error": (
                    "Preset dashboard snapshot exceeded the configured "
                    "max_snapshot_bytes limit; no partial evidence was sent to Jev"
                ),
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

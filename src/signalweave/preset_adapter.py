"""Preset Cloud API client and adapter.

Preset Cloud exposes Superset-compatible dashboard/chart endpoints on the
customer workspace.  Authentication is kept separate from the source adapter:
the client exchanges an API token for a short-lived workspace JWT, while the
generic adapter turns the resulting artifacts into SignalWeave snapshots.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import httpx

from .hosted import HostedDataMode, HostedDataPolicy, validate_hosted_origin
from .superset_adapter import SupersetAdapter
from .superset_client import SupersetClient


class PresetPolicyError(ValueError):
    """Raised when a provider response violates the connection data policy."""


DEFAULT_PRESET_MAX_RESULT_ROWS = 500
DEFAULT_PRESET_MAX_SNAPSHOT_BYTES = 1_000_000
DEFAULT_PRESET_MAX_RETRIES = 2
MAX_PRESET_RETRIES = 5
MAX_PRESET_RETRY_BACKOFF_SECONDS = 5.0


class PresetCloudClient(SupersetClient):
    """Read-only Preset Cloud client with API-token or bearer authentication."""

    _DASHBOARD_FILTER_STATUSES = frozenset(
        {
            "applied",
            "not_applied",
            "not_applied_uses_default_to_first_item_prequery",
        }
    )

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
        max_retries: int = DEFAULT_PRESET_MAX_RETRIES,
        retry_backoff_seconds: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        for field_name, url in {
            "Preset workspace_url": workspace_url,
            "Preset api_base_url": api_base_url,
        }.items():
            validate_hosted_origin(url, field_name=field_name)
        if access_token and (api_token_name or api_token_secret):
            raise ValueError("Preset requires exactly one authentication mode")
        if not access_token and not (api_token_name and api_token_secret):
            raise ValueError("Preset requires access_token or api token name and secret")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= MAX_PRESET_RETRIES
        ):
            raise ValueError(
                "Preset max_retries must be an integer between 0 and "
                f"{MAX_PRESET_RETRIES}"
            )
        if (
            isinstance(retry_backoff_seconds, bool)
            or not isinstance(retry_backoff_seconds, (int, float))
            or not math.isfinite(retry_backoff_seconds)
            or not 0 <= retry_backoff_seconds <= MAX_PRESET_RETRY_BACKOFF_SECONDS
        ):
            raise ValueError(
                "Preset retry_backoff_seconds must be finite and between 0 and "
                f"{MAX_PRESET_RETRY_BACKOFF_SECONDS:g}"
            )
        if max_result_rows is not None and max_result_rows < 1:
            raise ValueError("Preset max_result_rows must be positive")
        if max_snapshot_bytes is not None and max_snapshot_bytes < 1:
            raise ValueError("Preset max_snapshot_bytes must be positive")
        super().__init__(workspace_url)
        self._token = access_token
        self._api_token_name = api_token_name
        self._api_token_secret = api_token_secret
        self.api_base_url = api_base_url.rstrip("/")
        self._explicit_result_limit = max_result_rows is not None
        self._explicit_snapshot_limit = max_snapshot_bytes is not None
        self.max_result_rows = (
            DEFAULT_PRESET_MAX_RESULT_ROWS
            if max_result_rows is None
            else max_result_rows
        )
        self.max_snapshot_bytes = (
            DEFAULT_PRESET_MAX_SNAPSHOT_BYTES
            if max_snapshot_bytes is None
            else max_snapshot_bytes
        )
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._force_refresh = False
        self._transport = transport
        self._requests_made = 0
        self._request_path_counts: dict[str, int] = {}

    @property
    def requests_made(self) -> int:
        """Return the number of provider HTTP attempts made by this client.

        This is deployment telemetry, not response content.  The live
        acceptance runner uses it to prove that a reported customer shadow
        actually crossed the configured Preset transport instead of being
        satisfied by a cached or synthetic adapter response.
        """

        return self._requests_made

    @property
    def request_path_counts(self) -> dict[str, int]:
        """Return non-secret counts by provider path for acceptance telemetry."""

        return dict(self._request_path_counts)

    def constrain_response_limits(self, *, max_result_rows: int, max_snapshot_bytes: int) -> None:
        """Apply the connection policy without allowing a caller to loosen client limits."""

        self.max_result_rows = (
            min(self.max_result_rows, max_result_rows)
            if self._explicit_result_limit
            else max_result_rows
        )
        self.max_snapshot_bytes = (
            min(self.max_snapshot_bytes, max_snapshot_bytes)
            if self._explicit_snapshot_limit
            else max_snapshot_bytes
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
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
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
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
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
        if not math.isfinite(seconds):
            return None
        return min(max(seconds, 0.0), 5.0)

    @staticmethod
    def _reported_row_counts(item: dict[str, Any]) -> list[int]:
        """Read provider row-count metadata without trusting malformed values."""

        counts: list[int] = []
        payloads: list[dict[str, Any]] = [item]
        nested = item.get("data")
        if isinstance(nested, dict):
            payloads.append(nested)
        for payload in payloads:
            for key in ("rowcount", "sql_rowcount"):
                value = payload.get(key)
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise PresetPolicyError(
                        f"Preset chart response contained an invalid {key} value"
                    )
                if isinstance(value, float) and not math.isfinite(value):
                    raise PresetPolicyError(
                        f"Preset chart response contained an invalid {key} value"
                    )
                try:
                    integer_value = int(value)
                except (OverflowError, ValueError):
                    raise PresetPolicyError(
                        f"Preset chart response contained an invalid {key} value"
                    ) from None
                if value < 0 or integer_value != value:
                    raise PresetPolicyError(
                        f"Preset chart response contained an invalid {key} value"
                    )
                counts.append(integer_value)
        return counts

    @staticmethod
    def _validate_raw_saved_query_context(chart: dict[str, Any]) -> None:
        """Reject malformed saved context before generic normalization can hide it."""

        if "query_context" in chart and chart.get("query_context") is not None:
            raw_context = chart["query_context"]
            if isinstance(raw_context, str):
                try:
                    raw_context = json.loads(raw_context)
                except json.JSONDecodeError:
                    raise PresetPolicyError(
                        "Preset saved query context was not valid JSON"
                    ) from None
            if not isinstance(raw_context, dict):
                raise PresetPolicyError(
                    "Preset saved query context was not a JSON object"
                )
            raw_queries = raw_context.get("queries")
            if not isinstance(raw_queries, list) or not raw_queries or any(
                not isinstance(query, dict) for query in raw_queries
            ):
                raise PresetPolicyError(
                    "Preset saved query context did not contain a usable queries list"
                )
            query_values = [
                query.get("row_limit") for query in raw_queries if isinstance(query, dict)
            ]
        else:
            raw_params = chart.get("params")
            query_values = [raw_params.get("row_limit")] if isinstance(raw_params, dict) else []

        for requested in query_values:
            if requested is None:
                continue
            if isinstance(requested, bool):
                raise PresetPolicyError(
                    "Preset saved query context contained an invalid row_limit"
                )
            if isinstance(requested, float) and not requested.is_integer():
                raise PresetPolicyError(
                    "Preset saved query context contained an invalid row_limit"
                )
            try:
                int(requested)
            except (TypeError, ValueError):
                raise PresetPolicyError(
                    "Preset saved query context contained an invalid row_limit"
                ) from None

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        response = await self._request_stream_bounded(client, method, path, **kwargs)
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
            response = await self._request_stream_bounded(client, method, path, **kwargs)
            retries += 1
        return response

    async def _request_stream_bounded(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Read one provider response without buffering beyond the byte policy."""

        self._requests_made += 1
        self._request_path_counts[path] = self._request_path_counts.get(path, 0) + 1
        chunks: list[bytes] = []
        observed_bytes = 0
        async with client.stream(method, path, **kwargs) as response:
            async for chunk in response.aiter_bytes():
                observed_bytes += len(chunk)
                if (
                    self.max_snapshot_bytes is not None
                    and observed_bytes > self.max_snapshot_bytes
                ):
                    raise PresetPolicyError(
                        "Preset response exceeded the configured max_snapshot_bytes limit"
                    )
                chunks.append(chunk)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=b"".join(chunks),
                request=response.request,
                extensions=response.extensions,
            )

    async def chart_data(
        self,
        chart: dict[str, Any],
        *,
        dashboard_id: int | str | None = None,
        allow_unscoped_fallback: bool = False,
        scope_telemetry: dict[str, int] | None = None,
        response_telemetry: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch chart results with a hard response bound.

        Preset's Superset-compatible endpoint may return several result envelopes.
        Dashboard reads use Preset's chart-specific endpoint so its dashboard
        filter scope and access checks are applied. Some Preset charts imported
        from virtual datasets have no saved query context; when the dashboard
        metadata proves that no native filters can alter the result, the generic
        client's bounded unscoped fallback is safe and preserves that scope in
        telemetry. Standalone reads use the saved query endpoint. We reject a
        provider response that ignores the configured response cap; silently
        truncating a time series would create a false current value.
        """

        used_unscoped_fallback = False
        if dashboard_id is not None:
            try:
                response = await self._request(
                    "GET",
                    f"/api/v1/chart/{chart['id']}/data/",
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
            except httpx.HTTPStatusError as error:
                if (
                    not allow_unscoped_fallback
                    or error.response.status_code != 400
                    or "query context saved" not in error.response.text.lower()
                ):
                    raise
                response = await self._request(
                    "POST",
                    "/api/v1/chart/data",
                    timeout=60,
                    json=self._bounded_saved_query_payload(chart),
                )
                used_unscoped_fallback = True
            if scope_telemetry is not None:
                scope_telemetry["dashboard_scoped_requests"] = (
                    scope_telemetry.get("dashboard_scoped_requests", 0) + 1
                )
                if used_unscoped_fallback:
                    scope_telemetry["chart_query_fallbacks"] = (
                        scope_telemetry.get("chart_query_fallbacks", 0) + 1
                    )
        else:
            response = await self._request(
                "POST",
                "/api/v1/chart/data",
                timeout=60,
                json=self._bounded_saved_query_payload(chart),
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
        if dashboard_id is not None and not used_unscoped_fallback:
            raw_dashboard_filters = body.get("dashboard_filters")
            if not isinstance(raw_dashboard_filters, dict):
                raise PresetPolicyError(
                    "Preset dashboard-filter response did not include dashboard_filters metadata"
                )
            dashboard_filters = self._normalize_dashboard_filters(raw_dashboard_filters)
            if response_telemetry is not None:
                response_telemetry["dashboard_filters"] = dashboard_filters
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
        try:
            cache_status = self._cache_status_from_result_envelopes(envelopes)
        except ValueError as error:
            raise PresetPolicyError(str(error)) from error
        if response_telemetry is not None:
            response_telemetry["cache_status"] = cache_status
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
            row_count = 0
            for item in envelopes:
                row_count += len(self._rows_from_result_item(item))
                reported_counts = self._reported_row_counts(item)
                if reported_counts:
                    row_count = max(row_count, max(reported_counts))
            if row_count > self.max_result_rows:
                raise PresetPolicyError(
                    "Preset chart response exceeded the configured max_result_rows limit"
                )
        return [item for item in envelopes if isinstance(item, dict)]

    def _bounded_saved_query_payload(self, chart: dict[str, Any]) -> dict[str, Any]:
        """Build one bounded saved-query payload for standalone or safe fallback reads."""

        self._validate_raw_saved_query_context(chart)
        payload = self._saved_query_context(chart) or self._query_context(chart)
        queries = payload.get("queries")
        if not isinstance(queries, list) or not queries or any(
            not isinstance(query, dict) for query in queries
        ):
            raise PresetPolicyError(
                "Preset saved query context did not contain a usable queries list"
            )
        if self.max_result_rows is not None:
            for query in queries:
                requested = query.get("row_limit")
                if isinstance(requested, bool):
                    raise PresetPolicyError(
                        "Preset saved query context contained an invalid row_limit"
                    )
                if requested is None:
                    bounded = self.max_result_rows
                else:
                    try:
                        bounded = int(requested)
                    except (TypeError, ValueError):
                        raise PresetPolicyError(
                            "Preset saved query context contained an invalid row_limit"
                        ) from None
                query["row_limit"] = max(1, min(self.max_result_rows, bounded))
        payload["force"] = self._force_refresh
        return payload

    @classmethod
    def _normalize_dashboard_filters(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """Retain only the provider's safe, decision-relevant filter metadata."""

        raw_filters = payload.get("filters")
        if not isinstance(raw_filters, list):
            raise PresetPolicyError(
                "Preset dashboard_filters metadata did not contain a filters list"
            )
        filters: list[dict[str, str | None]] = []
        for item in raw_filters:
            if not isinstance(item, dict):
                raise PresetPolicyError(
                    "Preset dashboard_filters metadata contained a malformed filter"
                )
            filter_id = item.get("id")
            name = item.get("name")
            status = item.get("status")
            column = item.get("column")
            if (
                not isinstance(filter_id, str)
                or not filter_id
                or not isinstance(name, str)
                or not name
                or not isinstance(status, str)
                or status not in cls._DASHBOARD_FILTER_STATUSES
                or (column is not None and not isinstance(column, str))
            ):
                raise PresetPolicyError(
                    "Preset dashboard_filters metadata contained an invalid filter contract"
                )
            filters.append(
                {"id": filter_id, "name": name, "column": column, "status": status}
            )
        return {"filters": filters}


class PresetAdapter(SupersetAdapter):
    """Preset-hosted dashboard adapter using the generic Superset artifact shape."""

    def __init__(
        self,
        client: PresetCloudClient,
        *,
        tenant_id: str,
        policy: HostedDataPolicy | None = None,
        adapter_name: str = "preset",
        max_search_fallback_terms: int = 6,
    ) -> None:
        super().__init__(
            client,
            adapter_name=adapter_name,
            tenant_id=tenant_id,
            provider_name="preset",
            max_search_fallback_terms=max_search_fallback_terms,
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
                "contract": self._contract(
                    available_comparison_windows=snapshot.contract.available_comparison_windows
                ),
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
            contract=self._contract(
                available_comparison_windows=dashboard.available_comparison_windows
            ),
        )

    def _contract(self, *, available_comparison_windows: list[str] | None = None):
        from .models import ResourceContract

        return ResourceContract(
            tenant_id=self.tenant_id,
            domain="bi",
            available_comparison_windows=list(available_comparison_windows or []),
            roles=["primary"],
        )

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
                contract=self._contract(
                    available_comparison_windows=SupersetClient.comparison_windows_from_metadata(
                        chart
                    )
                ),
            )
        snapshot = await super()._inspect_chart(source, chart_id)
        return snapshot.model_copy(
            update={
                "adapter": self.name,
                "contract": self._contract(
                    available_comparison_windows=snapshot.contract.available_comparison_windows
                ),
                "metadata": {**snapshot.metadata, "provider": self.provider_name},
            }
        )

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from signalweave.hex_adapter import HexAdapter, HexCloudClient
from signalweave.hosted import (
    HostedAuthMode,
    HostedConnection,
    HostedDataMode,
    HostedDataPolicy,
    HostedProvider,
    InMemoryCredentialVault,
    InMemoryHostedConnectionStore,
    SQLiteHostedConnectionStore,
    build_hosted_adapter,
)
from signalweave.looker_adapter import LookerAdapter, LookerCloudClient
from signalweave.mcp_server import create_mcp
from signalweave.models import PrincipalContext, SourceRef
from signalweave.preset_adapter import PresetAdapter, PresetCloudClient, PresetPolicyError
from signalweave.runtime import build_runtime


def connection(provider: HostedProvider, tenant: str = "northstar") -> HostedConnection:
    return HostedConnection(
        id=f"{tenant}-{provider.value}",
        tenant_id=tenant,
        provider=provider,
        base_url=f"https://{provider.value}.{tenant}.example",
        external_workspace=f"{tenant}-workspace",
        credential_ref=f"vault://{tenant}/{provider.value}",
        auth_mode=HostedAuthMode.API_TOKEN
        if provider == HostedProvider.PRESET
        else HostedAuthMode.BEARER,
    )


def test_connection_record_contains_reference_not_secret():
    item = connection(HostedProvider.PRESET)
    serialized = json.dumps(item.model_dump(mode="json"))

    assert item.credential_ref.startswith("vault://")
    assert "secret" not in serialized.lower()
    assert "access_token" not in serialized.lower()


def test_hosted_connection_requires_https_without_inline_credentials():
    with pytest.raises(ValueError, match="must use https"):
        HostedConnection.model_validate(
            {**connection(HostedProvider.PRESET).model_dump(), "base_url": "http://preset.local"}
        )
    with pytest.raises(ValueError, match="must not contain credentials"):
        HostedConnection.model_validate(
            {
                **connection(HostedProvider.PRESET).model_dump(),
                "base_url": "https://user:secret@preset.example",
            }
        )
    with pytest.raises(ValueError, match="without query or fragment"):
        HostedConnection.model_validate(
            {
                **connection(HostedProvider.PRESET).model_dump(),
                "base_url": "https://preset.example/?access_token=leak",
            }
        )
    with pytest.raises(ValueError, match="without a path"):
        HostedConnection.model_validate(
            {
                **connection(HostedProvider.PRESET).model_dump(),
                "base_url": "https://preset.example/workspace",
            }
        )
    with pytest.raises(ValueError, match="valid https origin"):
        HostedConnection.model_validate(
            {
                **connection(HostedProvider.PRESET).model_dump(),
                "base_url": "https://preset.example:not-a-port",
            }
        )


def test_hosted_connection_metadata_cannot_be_used_as_a_secret_store():
    with pytest.raises(ValueError, match="metadata must not contain credential fields"):
        HostedConnection.model_validate(
            {
                **connection(HostedProvider.PRESET).model_dump(),
                "metadata": {"api_token_secret": "do-not-store"},
            }
        )


def test_preset_client_requires_secure_provider_urls():
    with pytest.raises(ValueError, match="workspace_url must use https"):
        PresetCloudClient(
            "http://workspace.preset.test",
            access_token="preset-token",
        )
    with pytest.raises(ValueError, match="api_base_url must use https"):
        PresetCloudClient(
            "https://workspace.preset.test",
            access_token="preset-token",
            api_base_url="http://api.preset.test",
        )
    with pytest.raises(ValueError, match="workspace_url must be an origin"):
        PresetCloudClient(
            "https://workspace.preset.test/?token=leak",
            access_token="preset-token",
        )
    with pytest.raises(ValueError, match="api_base_url must be an origin"):
        PresetCloudClient(
            "https://workspace.preset.test",
            access_token="preset-token",
            api_base_url="https://api.preset.test/#token",
        )
    with pytest.raises(ValueError, match="workspace_url must be an origin without a path"):
        PresetCloudClient(
            "https://workspace.preset.test/workspace",
            access_token="preset-token",
        )
    with pytest.raises(ValueError, match="api_base_url must be an origin without a path"):
        PresetCloudClient(
            "https://workspace.preset.test",
            access_token="preset-token",
            api_base_url="https://api.preset.test/api",
        )
    with pytest.raises(ValueError, match="workspace_url must be a valid https origin"):
        PresetCloudClient(
            "https://workspace.preset.test:not-a-port",
            access_token="preset-token",
        )
    with pytest.raises(ValueError, match="api_base_url must be a valid https origin"):
        PresetCloudClient(
            "https://workspace.preset.test",
            access_token="preset-token",
            api_base_url="https://api.preset.test:not-a-port",
        )


def test_connection_store_is_tenant_scoped():
    store = InMemoryHostedConnectionStore()
    item = connection(HostedProvider.PRESET)
    store.save(item)

    assert store.get(item.id, tenant_id=item.tenant_id).id == item.id
    with pytest.raises(KeyError, match="not available"):
        store.get(item.id, tenant_id="other-company")
    assert store.list(tenant_id="other-company") == []


def test_external_workspace_label_does_not_change_provider_endpoint():
    item = connection(HostedProvider.PRESET).model_copy(
        update={"external_workspace": "misleading-display-label"}
    )
    vault = InMemoryCredentialVault(
        {item.credential_ref: {"access_token": "preset-token"}},
        tenant_by_ref={item.credential_ref: item.tenant_id},
    )

    adapter = build_hosted_adapter(
        item.model_copy(update={"auth_mode": HostedAuthMode.BEARER}), vault
    )

    assert adapter.client.base_url == item.base_url


def test_sqlite_connection_store_persists_metadata_without_credentials(tmp_path):
    path = tmp_path / "connections.db"
    store = SQLiteHostedConnectionStore(str(path))
    item = connection(HostedProvider.LOOKER)
    store.save(item)

    restored = SQLiteHostedConnectionStore(str(path)).get(item.id, tenant_id=item.tenant_id)
    assert restored == item
    assert b"preset-secret" not in path.read_bytes()
    with pytest.raises(KeyError):
        store.get(item.id, tenant_id="other-company")


def test_policy_refuses_live_mode_without_explicit_permission():
    with pytest.raises(ValueError, match="allow_live_queries"):
        HostedDataPolicy(mode=HostedDataMode.LIVE_QUERY)


def test_policy_refuses_live_mode_without_refresh_permission():
    with pytest.raises(ValueError, match="allow_refresh"):
        HostedDataPolicy(mode=HostedDataMode.LIVE_QUERY, allow_live_queries=True)


def test_policy_refuses_live_permissions_in_non_live_modes():
    with pytest.raises(ValueError, match="requires live_query mode"):
        HostedDataPolicy(
            mode=HostedDataMode.METADATA_ONLY,
            allow_live_queries=True,
        )
    with pytest.raises(ValueError, match="requires live_query mode"):
        HostedDataPolicy(
            mode=HostedDataMode.CACHED_RESULTS,
            allow_refresh=True,
        )


def test_policy_rejects_unowned_retention_fields():
    with pytest.raises(ValueError, match="extra_forbidden"):
        HostedDataPolicy.model_validate({"retention_hours": 24})


@pytest.mark.asyncio
async def test_preset_cloud_token_exchange_and_dashboard_snapshot():
    calls: list[tuple[str, str, dict[str, str], bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), dict(request.headers), request.content))
        if request.url.host == "api.app.preset.test":
            assert request.url.path == "/v1/auth/"
            assert json.loads(request.content) == {"name": "preset-name", "secret": "preset-secret"}
            return httpx.Response(200, json={"payload": {"access_token": "preset-jwt"}})
        assert request.headers["authorization"] == "Bearer preset-jwt"
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Growth",
                        "position_json": {
                            "chart-101": {"type": "CHART", "meta": {"chartId": 101}}
                        },
                    }
                },
            )
        if request.url.path == "/api/v1/chart/101/data":
            assert request.method == "GET"
            assert request.url.params["filter_dashboard_id"] == "7"
            assert request.url.params["force"] == "false"
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "data": [
                                {
                                    "day": "2026-09-01",
                                    "revenue": 100,
                                    "provider_internal_note": "do-not-retain",
                                },
                                {
                                    "day": "2026-09-02",
                                    "revenue": 120,
                                    "provider_internal_note": "do-not-retain",
                                },
                            ]
                        }
                    ],
                    "dashboard_filters": {"filters": []},
                },
            )
        if request.url.path == "/api/v1/chart/101":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 101,
                        "slice_name": "Revenue",
                        "params": '{"datasource":"17__table","metrics":["revenue"],"granularity_sqla":"day"}',
                    }
                },
            )
        raise AssertionError(f"unexpected Preset request: {request.method} {request.url}")

    client = PresetCloudClient(
        "https://northstar-workspace.app.preset.test",
        api_token_name="preset-name",
        api_token_secret="preset-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(handler),
    )
    adapter = PresetAdapter(client, tenant_id="northstar")
    snapshot = await adapter.inspect(
        SourceRef(key="growth", adapter="preset", resource="dashboard:7", label="Growth")
    )

    assert snapshot.adapter == "preset"
    assert snapshot.contract.tenant_id == "northstar"
    assert snapshot.observations[0].metric == "revenue"
    assert snapshot.observations[0].current == 120
    assert snapshot.metadata["dashboard_scope"] == {
        "dashboard_scoped_requests": 1,
        "chart_query_fallbacks": 0,
    }
    assert "do-not-retain" not in json.dumps(snapshot.model_dump(mode="json"))
    assert len([call for call in calls if call[1].endswith("/v1/auth/")]) == 1
    assert client.requests_made == len(calls)
    assert client.request_path_counts["/v1/auth/"] == 1
    assert client.request_path_counts["/api/v1/dashboard/7"] == 1
    assert client.request_path_counts["/api/v1/chart/101"] == 1
    assert client.request_path_counts["/api/v1/chart/101/data"] == 1


@pytest.mark.asyncio
async def test_preset_auth_exchange_retries_transient_provider_failure():
    auth_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls
        if request.url.host == "api.app.preset.test":
            auth_calls += 1
            if auth_calls == 1:
                return httpx.Response(503, headers={"Retry-After": "0"}, json={"message": "busy"})
            return httpx.Response(200, json={"payload": {"access_token": "preset-jwt"}})
        assert request.headers["authorization"] == "Bearer preset-jwt"
        return httpx.Response(200, json={"result": {"id": 7, "dashboard_title": "Growth"}})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        api_token_name="preset-name",
        api_token_secret="preset-secret",
        api_base_url="https://api.app.preset.test",
        max_retries=1,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    metadata = await client.get_dashboard_metadata(7)

    assert metadata["id"] == 7
    assert auth_calls == 2


@pytest.mark.asyncio
async def test_preset_client_does_not_follow_workspace_redirects():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            307,
            headers={"location": "https://attacker.example/collect"},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-jwt",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.list_dashboards_page(page=0, page_size=20)

    assert len(requests) == 1
    assert requests[0].url.host == "workspace.app.preset.test"
    assert requests[0].headers["authorization"] == "Bearer preset-jwt"


@pytest.mark.asyncio
async def test_preset_client_does_not_follow_token_exchange_redirects():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            307,
            headers={"location": "https://attacker.example/collect"},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        api_token_name="preset-name",
        api_token_secret="preset-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_dashboard_metadata(7)

    assert len(requests) == 1
    assert requests[0].url.host == "api.app.preset.test"
    assert json.loads(requests[0].content) == {
        "name": "preset-name",
        "secret": "preset-secret",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [[], {"payload": []}, {"payload": {}}, {"payload": {"access_token": []}}],
)
async def test_preset_auth_exchange_rejects_malformed_token_shapes(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.app.preset.test"
        return httpx.Response(200, json=payload)

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        api_token_name="preset-name",
        api_token_secret="preset-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="payload.access_token"):
        await client.get_dashboard_metadata(7)


@pytest.mark.asyncio
async def test_preset_standalone_chart_keeps_saved_query_post_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/chart/data"
        payload = json.loads(request.content)
        assert payload["force"] is False
        assert payload["form_data"]["slice_id"] == 101
        return httpx.Response(200, json={"result": [{"data": [{"revenue": 120}]}]})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    result = await client.chart_data(
        {"id": 101, "params": {"metrics": ["revenue"], "datasource": "17__table"}}
    )

    assert result == [{"data": [{"revenue": 120}]}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query_context", "message"),
    [
        ('{"datasource": {"id": 17}}', "usable queries list"),
        ('{"queries": ["not-an-object"]}', "usable queries list"),
        ("{not-json", "not valid JSON"),
        ("[]", "not a JSON object"),
    ],
)
async def test_preset_malformed_saved_query_context_fails_before_provider_call(
    query_context, message
):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("malformed saved query context must fail before provider I/O")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match=message):
        await client.chart_data(
            {
                "id": 101,
                "query_context": query_context,
                "params": {"metrics": ["revenue"], "datasource": "17__table"},
            }
        )
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"row_limit": True}, {"row_limit": "not-an-int"}])
async def test_preset_malformed_fallback_row_limit_fails_before_provider_call(params):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid fallback row_limit must fail before provider I/O")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="invalid row_limit"):
        await client.chart_data(
            {"id": 101, "params": {**params, "metrics": ["revenue"]}}
        )
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_limit", [0, -10, 100])
async def test_preset_saved_query_row_limit_is_positive_and_bounded(requested_limit):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        expected = 1 if requested_limit <= 0 else 10
        assert payload["queries"][0]["row_limit"] == expected
        return httpx.Response(200, json={"result": [{"data": []}]})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_result_rows=10,
        transport=httpx.MockTransport(handler),
    )

    result = await client.chart_data(
        {
            "id": 101,
            "query_context": json.dumps(
                {
                    "queries": [{"row_limit": requested_limit}],
                    "datasource": {"id": 17, "type": "table"},
                }
            ),
            "params": {"metrics": ["revenue"], "datasource": "17__table"},
        }
    )

    assert result == [{"data": []}]


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_limit", [True, "not-an-int"])
async def test_preset_malformed_saved_row_limit_fails_before_provider_call(requested_limit):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid row_limit must fail before provider I/O")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_result_rows=10,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="invalid row_limit"):
        await client.chart_data(
            {
                "id": 101,
                "query_context": json.dumps(
                    {
                        "queries": [{"row_limit": requested_limit}],
                        "datasource": {"id": 17, "type": "table"},
                    }
                ),
                "params": {"metrics": ["revenue"], "datasource": "17__table"},
            }
        )
    assert calls == 0


@pytest.mark.asyncio
async def test_preset_metadata_only_never_fetches_chart_data():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Growth",
                        "position_json": {
                            "chart-101": {"type": "CHART", "meta": {"chartId": 101}}
                        },
                    }
                },
            )
        raise AssertionError(f"unexpected metadata-only request: {request.url}")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="oauth-token",
        transport=httpx.MockTransport(handler),
    )
    adapter = PresetAdapter(
        client,
        tenant_id="northstar",
        policy=HostedDataPolicy(mode=HostedDataMode.METADATA_ONLY),
    )
    snapshot = await adapter.inspect(
        SourceRef(key="growth", adapter="preset", resource="dashboard:7", label="Growth")
    )

    assert snapshot.observations == []
    assert snapshot.metadata["data_policy_mode"] == "metadata_only"
    assert "/api/v1/chart/101" not in paths
    assert "/api/v1/chart/data" not in paths


@pytest.mark.asyncio
async def test_preset_explicit_dashboard_authorization_does_not_scan_catalog():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Growth",
                        "description": "Executive growth view",
                    }
                },
            )
        raise AssertionError(f"explicit authorization must not scan Preset catalog: {request.url}")

    adapter = PresetAdapter(
        PresetCloudClient(
            "https://workspace.app.preset.test",
            access_token="preset-token",
            transport=httpx.MockTransport(handler),
        ),
        tenant_id="northstar",
    )

    descriptor = await adapter.authorize(
        SourceRef(key="growth", adapter="preset", resource="dashboard:7", label="Growth"),
        authorized_tenants={"northstar"},
    )

    assert descriptor is not None
    assert descriptor.resource == "dashboard:7"
    assert descriptor.contract.tenant_id == "northstar"
    assert paths == ["/api/v1/dashboard/7"]


@pytest.mark.asyncio
async def test_preset_tenant_mismatch_abstains_before_provider_contact():
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError(f"foreign-tenant authorization contacted Preset: {request.url}")

    adapter = PresetAdapter(
        PresetCloudClient(
            "https://workspace.app.preset.test",
            access_token="preset-token",
            transport=httpx.MockTransport(handler),
        ),
        tenant_id="northstar",
    )

    descriptor = await adapter.authorize(
        SourceRef(key="growth", adapter="preset", resource="dashboard:7", label="Growth"),
        authorized_tenants={"harbor-bank"},
    )

    assert descriptor is None
    assert provider_calls == 0


@pytest.mark.asyncio
async def test_preset_metadata_only_honors_selected_chart_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Growth",
                        "position_json": {
                            "revenue": {"type": "CHART", "meta": {"chartId": 101}},
                            "orders": {"type": "CHART", "meta": {"chartId": 102}},
                        },
                    }
                },
            )
        raise AssertionError(f"metadata-only must not fetch chart routes: {request.url}")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )
    adapter = PresetAdapter(
        client,
        tenant_id="northstar",
        policy=HostedDataPolicy(mode=HostedDataMode.METADATA_ONLY),
    )

    snapshot = await adapter.inspect(
        SourceRef(
            key="growth",
            adapter="preset",
            resource="dashboard:7",
            label="Growth",
            parameters={"chart_ids": ["102"]},
        )
    )

    assert snapshot.metadata["chart_count"] == 1
    assert snapshot.evidence[0].subject_id == "102"


@pytest.mark.asyncio
async def test_preset_api_token_refreshes_once_after_expiry():
    auth_calls = 0
    resource_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls, resource_calls
        if request.url.host == "api.app.preset.test":
            auth_calls += 1
            return httpx.Response(
                200,
                json={"payload": {"access_token": f"preset-jwt-{auth_calls}"}},
            )
        resource_calls += 1
        if resource_calls == 1:
            assert request.headers["authorization"] == "Bearer preset-jwt-1"
            return httpx.Response(401, json={"message": "expired"})
        assert request.headers["authorization"] == "Bearer preset-jwt-2"
        return httpx.Response(200, json={"result": {"id": 7, "dashboard_title": "Growth"}})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        api_token_name="preset-name",
        api_token_secret="preset-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(handler),
    )

    metadata = await client.get_dashboard_metadata(7)

    assert metadata["id"] == 7
    assert auth_calls == 2
    assert resource_calls == 2


@pytest.mark.asyncio
async def test_preset_concurrent_expiry_uses_one_refresh_exchange():
    auth_calls = 0
    resource_calls = 0
    stale_requests = 0
    stale_requests_released = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls, resource_calls, stale_requests
        if request.url.host == "api.app.preset.test":
            auth_calls += 1
            return httpx.Response(
                200,
                json={"payload": {"access_token": f"preset-jwt-{auth_calls}"}},
            )

        resource_calls += 1
        if request.headers["authorization"] == "Bearer preset-jwt-1":
            stale_requests += 1
            if stale_requests == 2:
                stale_requests_released.set()
            await stale_requests_released.wait()
            return httpx.Response(401, json={"message": "expired"})
        assert request.headers["authorization"] == "Bearer preset-jwt-2"
        return httpx.Response(
            200,
            json={"result": {"id": request.url.path.rsplit("/", 1)[-1], "dashboard_title": "Growth"}},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        api_token_name="preset-name",
        api_token_secret="preset-secret",
        api_base_url="https://api.app.preset.test",
        transport=httpx.MockTransport(handler),
    )

    metadata = await asyncio.gather(
        client.get_dashboard_metadata(7),
        client.get_dashboard_metadata(8),
    )

    assert [item["id"] for item in metadata] == ["7", "8"]
    assert auth_calls == 2
    assert resource_calls == 4


@pytest.mark.asyncio
async def test_preset_retries_after_token_refresh_with_the_new_token():
    auth_calls = 0
    resource_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_calls, resource_calls
        if request.url.host == "api.app.preset.test":
            auth_calls += 1
            return httpx.Response(
                200,
                json={"payload": {"access_token": f"preset-jwt-{auth_calls}"}},
            )
        resource_calls += 1
        if resource_calls == 1:
            assert request.headers["authorization"] == "Bearer preset-jwt-1"
            return httpx.Response(401, json={"message": "expired"})
        if resource_calls == 2:
            assert request.headers["authorization"] == "Bearer preset-jwt-2"
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "busy"})
        assert request.headers["authorization"] == "Bearer preset-jwt-2"
        return httpx.Response(200, json={"result": {"id": 7, "dashboard_title": "Growth"}})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        api_token_name="preset-name",
        api_token_secret="preset-secret",
        api_base_url="https://api.app.preset.test",
        max_retries=1,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    metadata = await client.get_dashboard_metadata(7)

    assert metadata["id"] == 7
    assert auth_calls == 2
    assert resource_calls == 3


@pytest.mark.asyncio
async def test_preset_retries_transient_rate_limit_with_bounded_backoff():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "busy"})
        return httpx.Response(200, json={"result": {"id": 7, "dashboard_title": "Growth"}})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_retries=1,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    metadata = await client.get_dashboard_metadata(7)

    assert metadata["id"] == 7
    assert calls == 2


@pytest.mark.asyncio
async def test_preset_does_not_retry_non_transient_client_errors():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, json={"message": "forbidden"})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_retries=3,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_dashboard_metadata(7)

    assert calls == 1


@pytest.mark.asyncio
async def test_preset_rejects_provider_result_that_ignores_row_policy():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Growth",
                        "position_json": {"chart": {"type": "CHART", "meta": {"chartId": 101}}},
                    }
                },
            )
        if request.url.path == "/api/v1/chart/101":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 101,
                        "slice_name": "Revenue",
                        "params": '{"datasource":"17__table","metrics":["revenue"],"granularity_sqla":"day"}',
                    }
                },
            )
        if request.url.path == "/api/v1/chart/101/data":
            assert request.method == "GET"
            assert request.url.params["filter_dashboard_id"] == "7"
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "data": [
                                {"day": "2026-09-01", "revenue": 100},
                                {"day": "2026-09-02", "revenue": 120},
                            ]
                        }
                    ],
                    "dashboard_filters": {"filters": []},
                },
            )
        raise AssertionError(f"unexpected Preset request: {request.url}")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )
    adapter = PresetAdapter(
        client,
        tenant_id="northstar",
        policy=HostedDataPolicy(max_result_rows=1),
    )

    snapshot = await adapter.inspect(
        SourceRef(key="growth", adapter="preset", resource="dashboard:7", label="Growth")
    )

    assert snapshot.observations == []
    assert snapshot.metadata["data_quality"]["status"] == "failed"
    assert "max_result_rows" in snapshot.error


@pytest.mark.asyncio
async def test_preset_dashboard_budget_fails_closed_after_chart_fanout():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/dashboard/7":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 7,
                        "dashboard_title": "Growth",
                        "position_json": {
                            "chart": {"type": "CHART", "meta": {"chartId": 101}}
                        },
                    }
                },
            )
        if request.url.path == "/api/v1/chart/101":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": 101,
                        "slice_name": "Revenue",
                        "params": '{"datasource":"17__table","metrics":["revenue"],"granularity_sqla":"day"}',
                    }
                },
            )
        if request.url.path == "/api/v1/chart/101/data":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "data": [
                                {"day": f"2026-09-{index:02d}", "revenue": index * 10}
                                for index in range(1, 11)
                            ]
                        }
                    ],
                    "dashboard_filters": {"filters": []},
                },
            )
        raise AssertionError(f"unexpected Preset request: {request.url}")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )
    adapter = PresetAdapter(
        client,
        tenant_id="northstar",
        policy=HostedDataPolicy(max_result_rows=20, max_snapshot_bytes=1024),
    )

    snapshot = await adapter.inspect(
        SourceRef(key="growth", adapter="preset", resource="dashboard:7", label="Growth")
    )

    assert snapshot.observations == []
    assert snapshot.evidence == []
    assert snapshot.metadata["data_quality"] == {
        "status": "failed",
        "reason": "dashboard_snapshot_bytes_exceeded",
        "snapshot_bytes": snapshot.metadata["data_quality"]["snapshot_bytes"],
        "max_snapshot_bytes": 1024,
        "chart_count": 1,
    }
    assert snapshot.metadata["data_quality"]["snapshot_bytes"] > 1024
    assert "no partial evidence" in snapshot.error
    assert len(
        json.dumps(
            snapshot.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ) <= 1024


@pytest.mark.asyncio
async def test_preset_dashboard_read_fails_closed_without_filter_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": [{"data": [{"revenue": 120}]}]})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="dashboard_filters"):
        await client.chart_data(
            {"id": 101, "params": {"metrics": ["revenue"]}},
            dashboard_id="7",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"result": "not-tabular"},
        {"result": [None]},
        {"payload": []},
    ],
)
async def test_preset_rejects_malformed_result_envelopes(body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="result envelope"):
        await client.chart_data(
            {
                "id": 101,
                "params": {"metrics": ["revenue"], "datasource": "17__table"},
            },
        )


@pytest.mark.asyncio
async def test_preset_rejects_invalid_chart_json_as_policy_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="not valid JSON"):
        await client.chart_data(
            {
                "id": 101,
                "params": {"metrics": ["revenue"], "datasource": "17__table"},
            },
        )


@pytest.mark.asyncio
async def test_preset_async_chart_response_fails_closed_instead_of_becoming_no_data():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/v1/chart/101/data"
        return httpx.Response(
            202,
            json={
                "job_id": "job-1",
                "result_url": "https://untrusted.example/result/job-1",
                "status": "pending",
            },
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="asynchronous chart response"):
        await client.chart_data(
            {"id": 101, "params": {"metrics": ["revenue"]}},
            dashboard_id="7",
        )
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        "failed",
        "pending",
        "running",
        "scheduled",
        "stopped",
        "timed_out",
        "error",
        "future-provider-state",
    ],
)
async def test_preset_non_success_query_status_fails_closed_inside_http_200(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": [{"status": status, "data": []}]},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="unsupported or non-success query status"):
        await client.chart_data(
            {"id": 101, "params": {"metrics": ["revenue"], "datasource": "17__table"}},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, "success", "completed", "complete", "ok"])
async def test_preset_known_success_query_status_remains_supported(status):
    def handler(request: httpx.Request) -> httpx.Response:
        item = {"data": []}
        if status is not None:
            item["status"] = status
        return httpx.Response(200, json={"result": [item]})

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    assert await client.chart_data(
        {"id": 101, "params": {"metrics": ["revenue"], "datasource": "17__table"}},
    ) == [{"data": [], **({"status": status} if status is not None else {})}]


@pytest.mark.asyncio
@pytest.mark.parametrize("row_count_key", ["rowcount", "sql_rowcount"])
async def test_preset_provider_reported_row_count_cannot_bypass_result_limit(row_count_key):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": [{"data": [{"revenue": 1}], row_count_key: 11}]},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_result_rows=10,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="max_result_rows"):
        await client.chart_data(
            {"id": 101, "params": {"metrics": ["revenue"], "datasource": "17__table"}},
        )


@pytest.mark.asyncio
async def test_preset_standalone_client_has_safe_default_row_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": [{"data": [{"revenue": index} for index in range(501)]}]},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="max_result_rows"):
        await client.chart_data(
            {"id": 101, "params": {"metrics": ["revenue"], "datasource": "17__table"}},
        )


def test_preset_adapter_applies_policy_without_widening_explicit_client_caps():
    default_client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
    )
    PresetAdapter(
        default_client,
        tenant_id="northstar",
        policy=HostedDataPolicy(max_result_rows=2_000, max_snapshot_bytes=2_000_000),
    )
    assert default_client.max_result_rows == 2_000
    assert default_client.max_snapshot_bytes == 2_000_000

    explicitly_bounded_client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_result_rows=10,
        max_snapshot_bytes=64,
    )
    PresetAdapter(
        explicitly_bounded_client,
        tenant_id="northstar",
        policy=HostedDataPolicy(max_result_rows=2_000, max_snapshot_bytes=2_000_000),
    )
    assert explicitly_bounded_client.max_result_rows == 10
    assert explicitly_bounded_client.max_snapshot_bytes == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [True, -1, 1.5, "11", float("nan"), float("inf")])
async def test_preset_invalid_provider_reported_row_count_fails_closed(bad_value):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps(
            {"result": [{"data": [], "rowcount": bad_value}]},
            allow_nan=True,
        ).encode()
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "application/json"},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_result_rows=10,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="invalid rowcount"):
        await client.chart_data(
            {"id": 101, "params": {"metrics": ["revenue"], "datasource": "17__table"}},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_error", ["query failed", {"message": "query failed"}])
async def test_preset_embedded_query_error_fails_closed_inside_http_200(provider_error):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": [{"error": provider_error, "data": []}]},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="query error"):
        await client.chart_data(
            {"id": 101, "params": {"metrics": ["revenue"], "datasource": "17__table"}},
        )


@pytest.mark.asyncio
async def test_preset_rejects_oversized_response_before_parsing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{" + b"x" * 128 + b"}")

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_snapshot_bytes=64,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="max_snapshot_bytes"):
        await client.get_dashboard_metadata(7)


@pytest.mark.asyncio
async def test_preset_auth_exchange_respects_response_byte_limit_before_token_parsing():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.app.preset.test"
        return httpx.Response(
            200,
            content=b'{"payload":{"access_token":"preset-jwt"}}' + b"x" * 64,
            headers={"content-type": "application/json"},
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        api_token_name="preset-name",
        api_token_secret="preset-secret",
        api_base_url="https://api.app.preset.test",
        max_snapshot_bytes=64,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="max_snapshot_bytes"):
        await client.get_dashboard_metadata(7)


@pytest.mark.asyncio
async def test_preset_response_byte_limit_is_checked_across_stream_chunks():
    class ChunkedResponseStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{" + b"x" * 40
            yield b"y" * 40 + b"}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=ChunkedResponseStream(),
        )

    client = PresetCloudClient(
        "https://workspace.app.preset.test",
        access_token="preset-token",
        max_snapshot_bytes=64,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PresetPolicyError, match="max_snapshot_bytes"):
        await client.get_dashboard_metadata(7)


@pytest.mark.asyncio
async def test_hex_adapter_reads_published_run_without_starting_one():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer hex-token"
        if request.url.path == "/api/v1/projects":
            return httpx.Response(200, json={"projects": [{"projectId": "retention", "name": "Retention"}]})
        if request.url.path == "/api/v1/projects/retention":
            return httpx.Response(200, json={"project": {"projectId": "retention", "name": "Retention", "published": True}})
        if request.url.path == "/api/v1/projects/retention/runs":
            return httpx.Response(
                200,
                json={"runs": [{"runId": "run-1", "status": "completed"}]},
            )
        if request.url.path == "/api/v1/cells/cell-1/output":
            return httpx.Response(
                200,
                json={"result": {"rows": [{"segment": "SMB", "retained": 0.71}]}},
            )
        raise AssertionError(f"unexpected Hex request: {request.url}")

    adapter = HexAdapter(
        HexCloudClient(
            "https://app.hex.test",
            access_token="hex-token",
            transport=httpx.MockTransport(handler),
        ),
        tenant_id="northstar",
    )
    resources = await adapter.list_resources()
    snapshot = await adapter.inspect(
        SourceRef(key="retention", adapter="hex", resource="project:retention", label="Retention")
        .model_copy(update={"parameters": {"cell_ids": ["cell-1"]}})
    )

    assert resources[0].contract.tenant_id == "northstar"
    assert snapshot.observations[0].metric == "retained"
    assert snapshot.observations[0].current == 0.71


@pytest.mark.asyncio
async def test_hex_project_catalog_uses_provider_cursor_pagination():
    cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("after")
        cursors.append(cursor)
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "values": [{"id": "project-1", "title": "Revenue"}],
                    "pagination": {"after": "cursor-2"},
                },
            )
        assert cursor == "cursor-2"
        return httpx.Response(
            200,
            json={"values": [{"id": "project-2", "title": "Retention"}], "pagination": {"after": None}},
        )

    adapter = HexAdapter(
        HexCloudClient(
            "https://app.hex.test",
            access_token="hex-token",
            transport=httpx.MockTransport(handler),
        ),
        tenant_id="northstar",
    )

    resources = await adapter.list_resources()

    assert [resource.resource for resource in resources] == ["project:project-1", "project:project-2"]
    assert cursors == [None, "cursor-2"]


@pytest.mark.asyncio
async def test_looker_cached_look_uses_cache_flag():
    paths: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.url.path, dict(request.url.params)))
        assert request.headers["authorization"] == "token looker-token"
        if request.url.path == "/api/4.0/look/42":
            return httpx.Response(200, json={"id": 42, "title": "Conversion", "query": {"model": "growth"}})
        if request.url.path == "/api/4.0/look/42/run/json":
            assert request.url.params["cache"] == "true"
            return httpx.Response(200, json=[{"week": "2026-09-01", "conversion": 0.18}])
        raise AssertionError(f"unexpected Looker request: {request.url}")

    adapter = LookerAdapter(
        LookerCloudClient(
            "https://growth.cloud.looker.test",
            access_token="looker-token",
            transport=httpx.MockTransport(handler),
        ),
        tenant_id="northstar",
    )
    snapshot = await adapter.inspect(
        SourceRef(key="conversion", adapter="looker", resource="look:42", label="Conversion")
    )

    assert snapshot.contract.tenant_id == "northstar"
    assert snapshot.observations[0].metric == "conversion"
    assert paths[-1][1]["cache"] == "true"


def test_factory_requires_vault_and_builds_tenant_bound_adapters():
    vault = InMemoryCredentialVault(
        {
            "vault://northstar/preset": {
                "name": "preset-name",
                "secret": "preset-secret",
            },
            "vault://northstar/hex": {"access_token": "hex-token"},
            "vault://northstar/looker": {"access_token": "looker-token"},
        },
        tenant_by_ref={
            "vault://northstar/preset": "northstar",
            "vault://northstar/hex": "northstar",
            "vault://northstar/looker": "northstar",
        },
    )

    preset = connection(HostedProvider.PRESET)
    hex_connection = connection(HostedProvider.HEX)
    looker = connection(HostedProvider.LOOKER)
    # Keep the external workspace names distinct while the credential refs stay explicit.
    hex_connection = hex_connection.model_copy(update={"credential_ref": "vault://northstar/hex"})
    looker = looker.model_copy(update={"credential_ref": "vault://northstar/looker"})

    assert isinstance(build_hosted_adapter(preset, vault), PresetAdapter)
    assert isinstance(build_hosted_adapter(hex_connection, vault), HexAdapter)
    assert isinstance(build_hosted_adapter(looker, vault), LookerAdapter)


def test_factory_enforces_hex_and_looker_auth_modes():
    hex_item = connection(HostedProvider.HEX)
    with pytest.raises(ValueError, match="Hex connections require BEARER"):
        build_hosted_adapter(
            hex_item.model_copy(update={"auth_mode": HostedAuthMode.API_TOKEN}),
            InMemoryCredentialVault(
                {hex_item.credential_ref: {"access_token": "hex-token"}},
                tenant_by_ref={hex_item.credential_ref: hex_item.tenant_id},
            ),
        )
    with pytest.raises(ValueError, match="unsupported fields"):
        build_hosted_adapter(
            hex_item,
            InMemoryCredentialVault(
                {hex_item.credential_ref: {"access_token": "hex-token", "secret": "extra"}},
                tenant_by_ref={hex_item.credential_ref: hex_item.tenant_id},
            ),
        )

    looker_item = connection(HostedProvider.LOOKER)
    oauth_item = looker_item.model_copy(update={"auth_mode": HostedAuthMode.OAUTH})
    oauth_vault = InMemoryCredentialVault(
        {
            oauth_item.credential_ref: {
                "client_id": "looker-client",
                "client_secret": "looker-secret",
            }
        },
        tenant_by_ref={oauth_item.credential_ref: oauth_item.tenant_id},
    )
    assert isinstance(build_hosted_adapter(oauth_item, oauth_vault), LookerAdapter)
    with pytest.raises(ValueError, match="unsupported"):
        build_hosted_adapter(
            oauth_item,
            InMemoryCredentialVault(
                {oauth_item.credential_ref: {"access_token": "looker-token"}},
                tenant_by_ref={oauth_item.credential_ref: oauth_item.tenant_id},
            ),
        )

    with pytest.raises(ValueError, match="only string key/value pairs"):
        build_hosted_adapter(
            hex_item,
            InMemoryCredentialVault(
                {hex_item.credential_ref: {"access_token": 123}},  # type: ignore[dict-item]
                tenant_by_ref={hex_item.credential_ref: hex_item.tenant_id},
            ),
        )
    with pytest.raises(ValueError, match="unsupported"):
        build_hosted_adapter(
            looker_item,
            InMemoryCredentialVault(
                {
                    looker_item.credential_ref: {
                        "access_token": "looker-token",
                        "client_secret": "unexpected",
                    }
                },
                tenant_by_ref={looker_item.credential_ref: looker_item.tenant_id},
            ),
        )


def test_factory_rejects_cross_tenant_credential_reference():
    northstar = connection(HostedProvider.PRESET, tenant="northstar")
    harbor = connection(HostedProvider.PRESET, tenant="harbor-bank").model_copy(
        update={"credential_ref": northstar.credential_ref}
    )
    vault = InMemoryCredentialVault(
        {
            northstar.credential_ref: {
                "name": "northstar-name",
                "secret": "northstar-secret",
            }
        },
        tenant_by_ref={northstar.credential_ref: northstar.tenant_id},
    )

    with pytest.raises(KeyError, match="not available in tenant harbor-bank"):
        build_hosted_adapter(harbor, vault)


def test_same_provider_connections_get_distinct_source_routes():
    from signalweave.hosted import hosted_adapter_name

    first = connection(HostedProvider.PRESET, tenant="northstar")
    second = connection(HostedProvider.PRESET, tenant="harbor-bank")

    assert hosted_adapter_name(first) != hosted_adapter_name(second)
    assert hosted_adapter_name(first).startswith("preset__")


def test_long_connection_ids_keep_source_routes_collision_resistant():
    from signalweave.hosted import hosted_adapter_name

    common_prefix = "customer-" + ("x" * 120)
    first = connection(HostedProvider.PRESET).model_copy(
        update={"id": common_prefix + "-alpha"}
    )
    second = connection(HostedProvider.PRESET).model_copy(
        update={"id": common_prefix + "-beta"}
    )

    first_route = hosted_adapter_name(first)
    second_route = hosted_adapter_name(second)

    assert first_route != second_route
    assert len(first_route) <= 80
    assert len(second_route) <= 80
    assert first_route.startswith("preset__")
    assert second_route.startswith("preset__")


def test_runtime_can_register_hosted_connections_without_global_provider_config(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))
    item = connection(HostedProvider.PRESET)
    vault = InMemoryCredentialVault(
        {item.credential_ref: {"name": "preset-name", "secret": "preset-secret"}},
        tenant_by_ref={item.credential_ref: item.tenant_id},
    )

    runtime = build_runtime(
        hosted_connections=[item],
        credential_vault=vault,
    )

    assert runtime.sources.adapter_names() == ["preset__northstar-preset"]


def test_runtime_bootstraps_one_preset_connection_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_WORKSPACE", "workspace")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME", "preset-name")
    monkeypatch.setenv("PRESET_API_TOKEN_SECRET", "preset-secret")
    monkeypatch.setenv("SIGNALWEAVE_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_PRINCIPAL_ID", "signalweave-agent")
    monkeypatch.setenv("PRESET_DATA_MODE", "metadata_only")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    runtime = build_runtime()

    assert runtime.sources.adapter_names() == ["preset__preset-env"]
    adapter = runtime.sources._adapters["preset__preset-env"]
    assert isinstance(adapter, PresetAdapter)
    assert adapter.tenant_id == "northstar"
    assert adapter.policy.mode == HostedDataMode.METADATA_ONLY
    assert adapter.client._api_token_name == "preset-name"
    assert adapter.client._api_token_secret == "preset-secret"
    assert runtime.principal is not None
    assert runtime.principal.tenant_id == "northstar"
    assert runtime.sources.authorized_tenants == frozenset({"northstar"})


def test_runtime_rejects_token_preset_bootstrap_without_trusted_principal(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "preset-token")
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="token-authenticated Preset deployments"):
        build_runtime()


def test_runtime_bootstraps_oidc_preset_without_static_principal(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "preset-token")
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "oidc")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_ISSUER_URL", "https://id.example.com")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_AUDIENCE", "signalweave")
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    runtime = build_runtime()

    assert isinstance(runtime.sources._adapters["preset__preset-env"], PresetAdapter)
    assert runtime.principal is None
    assert runtime.sources.authorized_tenants == frozenset({"northstar"})


def test_runtime_rejects_incomplete_preset_environment_bootstrap(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.delenv("PRESET_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("PRESET_API_TOKEN_NAME", raising=False)
    monkeypatch.delenv("PRESET_API_TOKEN_SECRET", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="PRESET_ACCESS_TOKEN"):
        build_runtime()


def test_runtime_rejects_insecure_preset_workspace_url(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "http://workspace.local")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "bearer-token")
    monkeypatch.setenv("SIGNALWEAVE_ALLOW_INSECURE_PROVIDER", "1")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="PRESET_URL must use https"):
        build_runtime()


def test_runtime_rejects_insecure_preset_auth_url(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "bearer-token")
    monkeypatch.setenv("PRESET_API_BASE_URL", "http://api.local")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="PRESET_API_BASE_URL must use https"):
        build_runtime()


@pytest.mark.parametrize("variable", ["PRESET_RETAIN_RAW_RESULTS", "PRESET_RETENTION_HOURS"])
def test_runtime_rejects_unowned_preset_retention_environment(monkeypatch, tmp_path, variable):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.app.preset.io")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "bearer-token")
    monkeypatch.setenv(variable, "24" if variable.endswith("HOURS") else "false")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="unsupported"):
        build_runtime()


def test_preset_factory_enforces_declared_auth_mode():
    item = connection(HostedProvider.PRESET)
    bearer_vault = InMemoryCredentialVault(
        {item.credential_ref: {"access_token": "token"}},
        tenant_by_ref={item.credential_ref: item.tenant_id},
    )
    with pytest.raises(ValueError, match="API_TOKEN"):
        build_hosted_adapter(item, bearer_vault)

    bearer_item = item.model_copy(update={"auth_mode": HostedAuthMode.BEARER})
    bearer_adapter = build_hosted_adapter(bearer_item, bearer_vault)
    assert isinstance(bearer_adapter, PresetAdapter)

    oauth_item = item.model_copy(update={"auth_mode": HostedAuthMode.OAUTH})
    api_vault = InMemoryCredentialVault(
        {item.credential_ref: {"name": "name", "secret": "secret"}},
        tenant_by_ref={item.credential_ref: item.tenant_id},
    )
    with pytest.raises(ValueError, match="OAuth"):
        build_hosted_adapter(oauth_item, api_vault)

    with pytest.raises(ValueError, match="unsupported fields"):
        build_hosted_adapter(
            item,
            InMemoryCredentialVault(
                {item.credential_ref: {"name": "name", "secret": "secret", "refresh_token": "token"}},
                tenant_by_ref={item.credential_ref: item.tenant_id},
            ),
        )

    with pytest.raises(ValueError, match="unsupported fields"):
        build_hosted_adapter(
            bearer_item,
            InMemoryCredentialVault(
                {item.credential_ref: {"access_token": "token", "client_secret": "secret"}},
                tenant_by_ref={item.credential_ref: item.tenant_id},
            ),
        )


def test_runtime_rejects_explicit_hosted_connection_tenant_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_PRINCIPAL_ID", "agent")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))
    item = connection(HostedProvider.PRESET, tenant="harbor-bank")
    vault = InMemoryCredentialVault(
        {item.credential_ref: {"name": "name", "secret": "secret"}},
        tenant_by_ref={item.credential_ref: item.tenant_id},
    )

    with pytest.raises(RuntimeError, match="must match SIGNALWEAVE_TENANT_ID"):
        build_runtime(hosted_connections=[item], credential_vault=vault)


def test_runtime_rejects_mixed_preset_credential_modes(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "bearer-token")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME", "preset-name")
    monkeypatch.setenv("PRESET_API_TOKEN_SECRET", "preset-secret")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="exactly one Preset credential mode"):
        build_runtime()


def test_runtime_rejects_preset_and_signalweave_tenant_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_TENANT_ID", "harbor-bank")
    monkeypatch.setenv("SIGNALWEAVE_PRINCIPAL_ID", "agent")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "bearer-token")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="must match SIGNALWEAVE_TENANT_ID"):
        build_runtime()


def test_runtime_rejects_preset_bootstrap_without_tenant_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.delenv("PRESET_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN", "bearer-token")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="requires PRESET_TENANT_ID"):
        build_runtime()


def test_runtime_reads_preset_secrets_from_mounted_files(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_PRINCIPAL_ID", "signalweave-agent")
    name_file = tmp_path / "preset-name"
    secret_file = tmp_path / "preset-secret"
    name_file.write_text("preset-name\n", encoding="utf-8")
    secret_file.write_text("preset-secret\n", encoding="utf-8")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME_FILE", str(name_file))
    monkeypatch.setenv("PRESET_API_TOKEN_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    runtime = build_runtime()
    adapter = runtime.sources._adapters["preset__preset-env"]

    assert adapter.client._api_token_name == "preset-name"
    assert adapter.client._api_token_secret == "preset-secret"


def test_runtime_reads_preset_bearer_token_from_mounted_file(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_TENANT_ID", "northstar")
    monkeypatch.setenv("SIGNALWEAVE_PRINCIPAL_ID", "signalweave-agent")
    access_file = tmp_path / "preset-access-token"
    access_file.write_text("preset-access-token\n", encoding="utf-8")
    monkeypatch.setenv("PRESET_ACCESS_TOKEN_FILE", str(access_file))
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    runtime = build_runtime()
    adapter = runtime.sources._adapters["preset__preset-env"]

    assert adapter.client._token == "preset-access-token"
    assert adapter.client._api_token_name is None
    assert adapter.client._api_token_secret is None


def test_runtime_rejects_secret_value_and_secret_file_together(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME", "preset-name")
    name_file = tmp_path / "preset-name"
    name_file.write_text("other-name\n", encoding="utf-8")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME_FILE", str(name_file))
    monkeypatch.setenv("PRESET_API_TOKEN_SECRET", "preset-secret")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="only one"):
        build_runtime()


def test_shared_runtime_requires_explicit_tenant_scope_for_multiple_connections(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))
    first = connection(HostedProvider.PRESET, tenant="northstar")
    second = connection(HostedProvider.PRESET, tenant="harbor-bank")
    vault = InMemoryCredentialVault(
        {
            first.credential_ref: {"name": "northstar-name", "secret": "northstar-secret"},
            second.credential_ref: {"name": "harbor-name", "secret": "harbor-secret"},
        },
        tenant_by_ref={
            first.credential_ref: first.tenant_id,
            second.credential_ref: second.tenant_id,
        },
    )

    runtime = build_runtime(
        hosted_connections=[first, second],
        credential_vault=vault,
    )

    assert runtime.sources.adapter_names() == [
        "preset__harbor-bank-preset",
        "preset__northstar-preset",
    ]
    assert awaitable_resources_are_empty(runtime)


@pytest.mark.asyncio
async def test_shared_runtime_mcp_principal_never_contacts_foreign_preset(
    monkeypatch, tmp_path
):
    requests: list[tuple[str, str, str]] = []
    tenants = {
        "northstar": {"dashboard_id": "northstar-dashboard", "token": "northstar-jwt"},
        "harbor-bank": {"dashboard_id": "harbor-dashboard", "token": "harbor-jwt"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host.removesuffix(".preset.test")
        if request.url.host == "api.app.preset.test":
            credentials = json.loads(request.content)
            tenant = next(
                tenant
                for tenant, values in tenants.items()
                if credentials == {"name": f"{tenant}-name", "secret": f"{tenant}-secret"}
            )
            requests.append((tenant, request.method, request.url.path))
            return httpx.Response(
                200, json={"payload": {"access_token": tenants[tenant]["token"]}}
            )
        if host not in tenants:
            return httpx.Response(404, json={"message": "unknown workspace"})
        tenant = tenants[host]
        requests.append((host, request.method, request.url.path))
        if request.headers.get("authorization") != f"Bearer {tenant['token']}":
            return httpx.Response(401, json={"message": "wrong tenant token"})
        if request.url.path == "/api/v1/dashboard/":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "id": tenant["dashboard_id"],
                            "dashboard_title": f"{host} dashboard",
                        }
                    ],
                    "count": 1,
                },
            )
        return httpx.Response(404, json={"message": "unexpected route"})

    def hosted_connection(tenant: str) -> HostedConnection:
        return HostedConnection(
            id=f"{tenant}-preset",
            tenant_id=tenant,
            provider=HostedProvider.PRESET,
            base_url=f"https://{tenant}.preset.test",
            external_workspace=f"{tenant}-workspace",
            credential_ref=f"vault://{tenant}/preset",
            auth_mode=HostedAuthMode.API_TOKEN,
        )

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))
    connections = [hosted_connection(tenant) for tenant in tenants]
    vault = InMemoryCredentialVault(
        {
            connection.credential_ref: {
                "name": f"{tenant}-name",
                "secret": f"{tenant}-secret",
                "api_base_url": "https://api.app.preset.test",
            }
            for tenant, connection in zip(tenants, connections, strict=True)
        },
        tenant_by_ref={
            connection.credential_ref: tenant
            for tenant, connection in zip(tenants, connections, strict=True)
        },
    )

    runtime = build_runtime(
        hosted_connections=connections,
        credential_vault=vault,
        http_transport=httpx.MockTransport(handler),
    )
    server = create_mcp(
        runtime,
        principal_resolver=lambda _ctx: PrincipalContext(
            principal_id="northstar-agent", tenant_id="northstar"
        ),
    )
    list_resources = server._tool_manager.get_tool("list_resources").fn
    inspect_resource = server._tool_manager.get_tool("inspect_resource").fn

    visible = await list_resources(ctx=object())
    foreign = await inspect_resource(
        adapter="preset__harbor-bank-preset",
        resource="dashboard:harbor-dashboard",
        ctx=object(),
    )

    assert {item["contract"]["tenant_id"] for item in visible} == {"northstar"}
    assert foreign["error"] is not None
    assert {item[0] for item in requests} == {"northstar"}
    assert all("harbor" not in item[0] for item in requests)


def awaitable_resources_are_empty(runtime):
    """Keep the test synchronous while documenting the safe default contract."""
    import asyncio

    return asyncio.run(runtime.sources.list_resources()) == []

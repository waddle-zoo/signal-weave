from __future__ import annotations

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
from signalweave.models import SourceRef
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


def test_connection_store_is_tenant_scoped():
    store = InMemoryHostedConnectionStore()
    item = connection(HostedProvider.PRESET)
    store.save(item)

    assert store.get(item.id, tenant_id=item.tenant_id).id == item.id
    with pytest.raises(KeyError, match="not available"):
        store.get(item.id, tenant_id="other-company")
    assert store.list(tenant_id="other-company") == []


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
                    ]
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
    assert "do-not-retain" not in json.dumps(snapshot.model_dump(mode="json"))
    assert len([call for call in calls if call[1].endswith("/v1/auth/")]) == 1


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
                    ]
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
        }
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


def test_same_provider_connections_get_distinct_source_routes():
    from signalweave.hosted import hosted_adapter_name

    first = connection(HostedProvider.PRESET, tenant="northstar")
    second = connection(HostedProvider.PRESET, tenant="harbor-bank")

    assert hosted_adapter_name(first) != hosted_adapter_name(second)
    assert hosted_adapter_name(first).startswith("preset__")


def test_runtime_can_register_hosted_connections_without_global_provider_config(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))
    item = connection(HostedProvider.PRESET)
    vault = InMemoryCredentialVault(
        {item.credential_ref: {"name": "preset-name", "secret": "preset-secret"}}
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
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_WORKSPACE", "workspace")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME", "preset-name")
    monkeypatch.setenv("PRESET_API_TOKEN_SECRET", "preset-secret")
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
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "signalweave.db"))

    with pytest.raises(RuntimeError, match="PRESET_URL must use https"):
        build_runtime()


def test_runtime_rejects_insecure_preset_auth_url(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.app.preset.io")
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
    bearer_vault = InMemoryCredentialVault({item.credential_ref: {"access_token": "token"}})
    with pytest.raises(ValueError, match="API_TOKEN"):
        build_hosted_adapter(item, bearer_vault)

    bearer_item = item.model_copy(update={"auth_mode": HostedAuthMode.BEARER})
    bearer_adapter = build_hosted_adapter(bearer_item, bearer_vault)
    assert isinstance(bearer_adapter, PresetAdapter)

    oauth_item = item.model_copy(update={"auth_mode": HostedAuthMode.OAUTH})
    api_vault = InMemoryCredentialVault(
        {item.credential_ref: {"name": "name", "secret": "secret"}}
    )
    with pytest.raises(ValueError, match="OAuth"):
        build_hosted_adapter(oauth_item, api_vault)


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
        {item.credential_ref: {"name": "name", "secret": "secret"}}
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


def test_runtime_reads_preset_secrets_from_mounted_files(monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("SUPERSET_URL", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://workspace.us-east-1.app.preset.io")
    monkeypatch.setenv("PRESET_TENANT_ID", "northstar")
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
        }
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


def awaitable_resources_are_empty(runtime):
    """Keep the test synchronous while documenting the safe default contract."""
    import asyncio

    return asyncio.run(runtime.sources.list_resources()) == []

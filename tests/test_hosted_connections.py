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
from signalweave.preset_adapter import PresetAdapter, PresetCloudClient
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
        if request.url.path == "/api/v1/chart/data":
            return httpx.Response(
                200,
                json={"result": [{"data": [{"day": "2026-09-01", "revenue": 100}, {"day": "2026-09-02", "revenue": 120}]}]},
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
    assert len([call for call in calls if call[1].endswith("/v1/auth/")]) == 1


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
                "access_token": "preset-token",
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
    vault = InMemoryCredentialVault({item.credential_ref: {"access_token": "preset-token"}})

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
            first.credential_ref: {"access_token": "northstar-token"},
            second.credential_ref: {"access_token": "harbor-token"},
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

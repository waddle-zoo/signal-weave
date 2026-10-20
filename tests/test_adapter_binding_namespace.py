from types import SimpleNamespace

import pytest

from signalweave.hex_adapter import HexAdapter, HexCloudClient
from signalweave.looker_adapter import LookerAdapter, LookerCloudClient
from signalweave.mcp_source import (
    EnvReference,
    HTTPTransport,
    MCPConnection,
    MCPResource,
    MCPSourceAdapter,
    StdioTransport,
)
from signalweave.models import MetricDefinition, ResourceContract, ResourceDescriptor
from signalweave.preset_adapter import PresetAdapter, PresetCloudClient
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient
from signalweave.trino_adapter import TrinoQueryAdapter


def test_superset_and_preset_bind_to_normalized_workspace_not_credentials():
    first = SupersetAdapter(
        SupersetClient("https://alice:one@bi.example/superset?token=first#section")
    )
    rotated = SupersetAdapter(
        SupersetClient("https://bob:two@bi.example/superset?token=rotated#other")
    )
    moved = SupersetAdapter(SupersetClient("https://bi-other.example/superset"))

    assert first.binding_namespace == rotated.binding_namespace
    assert first.binding_namespace != moved.binding_namespace
    assert len(first.binding_namespace) == 64

    preset = PresetAdapter(
        PresetCloudClient("https://workspace-a.preset.test", access_token="first"),
        tenant_id="tenant-a",
    )
    preset_rotated = PresetAdapter(
        PresetCloudClient("https://workspace-a.preset.test", access_token="rotated"),
        tenant_id="tenant-a",
    )
    preset_moved = PresetAdapter(
        PresetCloudClient("https://workspace-b.preset.test", access_token="first"),
        tenant_id="tenant-a",
    )
    assert preset.binding_namespace == preset_rotated.binding_namespace
    assert preset.binding_namespace != preset_moved.binding_namespace


def test_hex_and_looker_use_stable_connection_workspace_identity_not_secrets():
    def hex_namespace(workspace, token):
        client = HexCloudClient("https://app.hex.test", access_token=token)
        client.connection = SimpleNamespace(
            provider="hex", id="hex-connection-1", external_workspace=workspace,
            base_url="https://app.hex.test",
        )
        return HexAdapter(client, tenant_id="tenant-a").binding_namespace

    def looker_namespace(workspace, secret):
        client = LookerCloudClient(
            "https://analytics.looker.test", client_id="client-1", client_secret=secret,
        )
        client.connection = SimpleNamespace(
            provider="looker", id="looker-connection-1", external_workspace=workspace,
            base_url="https://analytics.looker.test",
        )
        return LookerAdapter(client, tenant_id="tenant-a").binding_namespace

    assert hex_namespace("workspace-1", "token-one") == hex_namespace("workspace-1", "token-two")
    assert hex_namespace("workspace-1", "token-one") != hex_namespace("workspace-2", "token-one")
    assert looker_namespace("instance-1", "secret-one") == looker_namespace("instance-1", "secret-two")
    assert looker_namespace("instance-1", "secret-one") != looker_namespace("instance-2", "secret-one")

    hex_client = HexCloudClient("https://app.hex.test", access_token="token")
    looker_client = LookerCloudClient("https://analytics.looker.test", access_token="token")
    assert HexAdapter(hex_client, tenant_id="tenant-a", adapter_name="hex__conn-a").binding_namespace != HexAdapter(
        hex_client, tenant_id="tenant-a", adapter_name="hex__conn-b",
    ).binding_namespace
    assert LookerAdapter(looker_client, tenant_id="tenant-a", adapter_name="looker__conn-a").binding_namespace != LookerAdapter(
        looker_client, tenant_id="tenant-a", adapter_name="looker__conn-b",
    ).binding_namespace


class TrinoExecutor:
    def __init__(self, base_url=None, catalog=None, schema=None):
        if base_url is not None:
            self.base_url = base_url
        self.catalog = catalog
        self.schema = schema

    async def execute(self, _sql, _parameters):
        return []


def test_trino_namespace_requires_endpoint_and_tracks_warehouse_scope():
    def namespace(base_url, catalog="hive", schema="analytics"):
        return TrinoQueryAdapter(
            [], TrinoExecutor(base_url, catalog=catalog, schema=schema),
        ).binding_namespace

    baseline = namespace("https://user:pw@trino.example:8443/coordinator?ticket=one#fragment")
    assert baseline == namespace("https://other:secret@trino.example:8443/coordinator?ticket=two#other")
    assert baseline != namespace("https://trino-west.example:8443/coordinator")
    assert baseline != namespace("https://trino.example:8443/coordinator", catalog="iceberg")
    assert baseline != namespace("https://trino.example:8443/coordinator", schema="finance")

    relation_only = ResourceDescriptor(
        adapter="trino", resource="query:orders", kind="metric_query", title="Orders",
        contract=ResourceContract(metric_definitions=[MetricDefinition(
            key="orders", label="Orders", relation="warehouse.analytics.orders",
            aggregation="count", time_column="created_at",
        )]),
    )
    assert TrinoQueryAdapter([relation_only], TrinoExecutor(catalog="hive", schema="analytics")).binding_namespace is None


def _mcp_connection(transport, context_namespace=None):
    descriptor = ResourceDescriptor(
        adapter="company_metrics", resource="measurement:orders", kind="measurement",
        title="Orders", contract=ResourceContract(tenant_id="tenant-a"),
    )
    return MCPConnection(
        name="company_metrics", tenant_id="tenant-a", read_only=True, transport=transport,
        context_namespace=context_namespace,
        resources=[MCPResource(
            descriptor=descriptor, source_key="orders", tool="read_orders",
        )],
    )


def _mcp_namespace(transport, context_namespace=None):
    return MCPSourceAdapter(_mcp_connection(transport, context_namespace)).binding_namespace


def test_stdio_mcp_namespace_requires_owner_assertion_and_never_reads_environment_values(monkeypatch):
    transport = StdioTransport(
        type="stdio", command=["python", "-m", "company.connector", "--workspace", "from-env"],
        env={"UPSTREAM_ROUTE": EnvReference(env="UPSTREAM_ROUTE_VALUE")},
    )
    assert _mcp_namespace(transport) is None

    monkeypatch.setattr(EnvReference, "resolve", lambda _self: pytest.fail("namespace resolved an env value"))
    monkeypatch.setenv("UPSTREAM_ROUTE_VALUE", "workspace-one")
    first = _mcp_namespace(transport, "company-prod")
    monkeypatch.setenv("UPSTREAM_ROUTE_VALUE", "workspace-two")
    assert first == _mcp_namespace(transport, "company-prod")
    assert first != _mcp_namespace(transport, "company-staging")


def test_http_mcp_namespace_fails_closed_for_opaque_routing_and_uses_explicit_context(monkeypatch):
    query_url = "https://mcp.example:8443/metrics?workspace=finance"
    assert _mcp_namespace(HTTPTransport(type="streamable-http", url=query_url)) is None
    assert _mcp_namespace(HTTPTransport(
        type="streamable-http", url="https://mcp.example/metrics",
        headers={"X-Workspace": EnvReference(env="MCP_WORKSPACE")},
    )) is None

    first_transport = HTTPTransport(
        type="streamable-http", url=query_url,
        headers={"Authorization": EnvReference(env="MCP_AUTH")},
    )
    rotated_credential = HTTPTransport(
        type="streamable-http", url="https://mcp.example:8443/metrics?token=rotated",
        headers={"Authorization": EnvReference(env="MCP_AUTH")},
    )
    changed_path = HTTPTransport(
        type="streamable-http", url="https://mcp.example:8443/other?workspace=finance",
        headers={"Authorization": EnvReference(env="MCP_AUTH")},
    )
    first = _mcp_namespace(first_transport, "finance-prod")
    assert first == _mcp_namespace(rotated_credential, "finance-prod")
    assert first != _mcp_namespace(changed_path, "finance-prod")
    assert first != _mcp_namespace(first_transport, "finance-staging")

    monkeypatch.setenv("MCP_ENDPOINT", "https://mcp.example/finance?token=one")
    from_reference = HTTPTransport(
        type="streamable-http", url=EnvReference(env="MCP_ENDPOINT"),
    )
    assert _mcp_namespace(from_reference) is None
    monkeypatch.setattr(EnvReference, "resolve", lambda _self: pytest.fail("namespace resolved an env value"))
    reference_namespace = _mcp_namespace(from_reference, "finance-prod")
    monkeypatch.setenv("MCP_ENDPOINT", "https://other.example/marketing?tenant=two")
    assert reference_namespace == _mcp_namespace(from_reference, "finance-prod")


def test_http_namespace_without_opaque_routing_uses_endpoint_and_normalization():
    first = HTTPTransport(type="streamable-http", url="https://alice:secret@mcp.example:443/metrics")
    normalized = HTTPTransport(type="streamable-http", url="https://mcp.example/metrics/")
    moved = HTTPTransport(type="streamable-http", url="https://mcp.example/other")
    assert _mcp_namespace(first) == _mcp_namespace(normalized)
    assert _mcp_namespace(first) != _mcp_namespace(moved)
    assert _mcp_namespace(HTTPTransport(type="streamable-http", url="https://[invalid")) is None


def test_old_adapter_fakes_without_a_verifiable_namespace_remain_constructible():
    class BareClient:
        pass

    class OriginlessExecutor:
        async def execute(self, _sql, _parameters):
            return []

    assert SupersetAdapter(BareClient()).binding_namespace is None
    assert HexAdapter(BareClient(), tenant_id="tenant-a").binding_namespace is None
    assert LookerAdapter(BareClient(), tenant_id="tenant-a").binding_namespace is None
    assert TrinoQueryAdapter([], OriginlessExecutor()).binding_namespace is None

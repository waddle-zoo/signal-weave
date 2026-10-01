import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from mcp import types

from signalweave.mcp_source import build_mcp_sources
from signalweave.models import SourceRef
from signalweave.sources import SourceRegistry


@pytest.fixture
def manifest():
    return {"version": 1, "connections": [{
        "name": "company_metrics", "tenant_id": "tenant-a", "read_only": True,
        "transport": {"type": "stdio", "command": [sys.executable, "server.py"]},
        "resources": [{
            "descriptor": {
                "adapter": "company_metrics", "resource": "measurement:orders",
                "kind": "measurement", "title": "Orders",
                "contract": {"tenant_id": "tenant-a", "metric_names": ["orders"],
                             "grain": "day", "freshness_sla_hours": 24},
            },
            "source_key": "upstream-orders", "tool": "read_measurement",
            "arguments": {"measurement": "orders", "window": {"days": 7}},
        }],
    }]}


@pytest.fixture
def payload():
    return {
        "source_key": "upstream-orders", "adapter": "company_metrics",
        "resource": "measurement:orders", "title": "Remote title",
        "captured_at": "2000-01-01T00:00:00Z",
        "source_captured_at": "2026-09-29T12:00:00Z",
        "contract": {"tenant_id": "tenant-a", "grain": "untrusted grain"},
        "observations": [{"source_key": "upstream-orders", "metric": "orders",
                          "current": 120, "baseline": 100}],
        "evidence": [{"source_key": "upstream-orders", "statement": "Completed orders"}],
    }


@pytest.fixture
def source():
    return SourceRef(key="card-orders", adapter="company_metrics",
                     resource="measurement:orders", label="Card label")


@pytest.fixture
def comparison():
    return {
        "key": "orders-region", "metric": "orders", "definition": "Completed orders",
        "population": "Production orders", "unit": "count", "dimension": "region",
        "kind": "additive", "baseline_start": "2026-09-27T00:00:00Z",
        "baseline_end": "2026-09-28T00:00:00Z", "current_start": "2026-09-28T00:00:00Z",
        "current_end": "2026-09-29T00:00:00Z", "coverage": "complete",
        "disjoint_segments": True, "comparable": True, "query_refs": ["approved-orders"],
        "baseline_total": {"value": 100}, "current_total": {"value": 120},
        "segments": [{"segment": "all", "baseline": {"value": 100}, "current": {"value": 120}}],
    }


class FakeTransport:
    def __init__(self, payload, *, is_error=False, error=None, delay=0):
        self.result = types.CallToolResult(structuredContent=payload, content=[], isError=is_error)
        self.error = error
        self.delay = delay
        self.calls = []
        self.opens = 0
        self.closed = 0
        self.initialized = 0

    @asynccontextmanager
    async def __call__(self, connection):
        self.opens += 1
        try:
            yield self
        finally:
            self.closed += 1

    async def initialize(self):
        self.initialized += 1

    async def call_tool(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        arguments["window"]["days"] = 999
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result.model_copy(deep=True)


def build(tmp_path, manifest, fake=None):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(manifest))
    kwargs = {"transport_factory": fake} if fake is not None else {}
    return build_mcp_sources(str(path), **kwargs)


async def test_fixed_call_rebinds_all_keys_and_owns_contract(tmp_path, manifest, payload, source):
    fake = FakeTransport(payload)
    adapter, = build(tmp_path, manifest, fake)
    catalog = await adapter.list_resources()
    catalog[0].contract.tenant_id = "attacker"
    descriptor = await adapter.authorize(source, authorized_tenants={"tenant-a"})
    descriptor.contract.grain = "attacker"
    before = datetime.now(timezone.utc)
    first = await adapter.inspect(source)
    second = await adapter.inspect(source.model_copy(update={"key": "another-card"}))
    assert first.error is None
    assert first.source_key == first.observations[0].source_key == first.evidence[0].source_key == source.key
    assert second.source_key == second.observations[0].source_key == "another-card"
    assert first.contract.tenant_id == "tenant-a"
    assert first.contract.grain == "day"
    assert first.title == "Orders"
    assert first.captured_at >= before
    assert first.source_captured_at.isoformat() == "2026-09-29T12:00:00+00:00"
    assert fake.calls == [("read_measurement", {"measurement": "orders", "window": {"days": 7}})] * 2
    assert fake.initialized == fake.closed == 2


@pytest.mark.parametrize("override", [
    {"adapter": "other"}, {"resource": "measurement:other"},
    {"parameters": {"tool": "delete_all"}}, {"parameters": {"arguments": {}}},
    {"parameters": {"url": "https://unapproved.invalid"}}, {"parameters": {"limit": 1}},
])
async def test_caller_cannot_expand_authority(tmp_path, manifest, payload, source, override):
    fake = FakeTransport(payload)
    adapter, = build(tmp_path, manifest, fake)
    reference = source.model_copy(update=override)
    assert await adapter.authorize(reference) is None
    assert (await adapter.inspect(reference)).error == "MCP source is not authorized"
    assert fake.opens == 0


async def test_tenant_and_disabled_resource_authorization_precede_io(tmp_path, manifest, payload, source):
    fake = FakeTransport(payload)
    adapter, = build(tmp_path, manifest, fake)
    for tenants in ({"tenant-b"}, set()):
        assert await adapter.authorize(source, authorized_tenants=tenants) is None
        assert (await adapter.inspect(source, authorized_tenants=tenants)).error
        registry = SourceRegistry([adapter], authorized_tenants=tenants)
        assert await registry.list_resources() == []
        assert (await registry.inspect(source)).error
    manifest["connections"][0]["resources"][0]["descriptor"]["contract"]["authorized"] = False
    disabled, = build(tmp_path, manifest, fake)
    assert await disabled.list_resources() == []
    assert (await disabled.inspect(source)).error
    assert fake.opens == 0


@pytest.mark.parametrize("field,value", [
    ("adapter", "foreign"), ("resource", "measurement:foreign"),
    ("source_key", "foreign"), ("contract", {"tenant_id": "foreign"}),
    ("contract", {}), ("contract", {"tenant_id": "tenant-a", "authorized": False}),
    ("observations", [{"source_key": "foreign", "metric": "orders", "current": 1}]),
    ("observations", [{"metric": "orders", "current": 1}]),
    ("evidence", [{"source_key": "foreign", "statement": "untrusted"}]),
])
async def test_hostile_identity_fails_closed(tmp_path, manifest, payload, source, field, value):
    payload[field] = value
    adapter, = build(tmp_path, manifest, FakeTransport(payload))
    snapshot = await adapter.inspect(source)
    assert snapshot.error == "MCP snapshot identity contract mismatch"
    assert snapshot.contract.tenant_id == "tenant-a"
    assert snapshot.source_key == source.key
    assert snapshot.observations == snapshot.evidence == []
    assert snapshot.metadata == {}


async def test_response_cannot_upgrade_configured_health(tmp_path, manifest, payload, source):
    entry = manifest["connections"][0]["resources"][0]
    entry["descriptor"]["contract"]["source_status"] = "stale"
    adapter, = build(tmp_path, manifest, FakeTransport(payload))
    assert (await adapter.inspect(source)).contract.source_status == "stale"
    payload["contract"]["source_status"] = "failed"
    adapter, = build(tmp_path, manifest, FakeTransport(payload))
    assert (await adapter.inspect(source)).contract.source_status == "failed"


@pytest.mark.parametrize("kind", ["exception", "is_error", "snapshot_error", "invalid", "text_only"])
async def test_errors_never_expose_payloads(tmp_path, manifest, payload, source, kind, caplog):
    sentinel = "credential-sentinel@private-endpoint.invalid"
    fake = FakeTransport(payload)
    if kind == "exception":
        fake.error = RuntimeError(sentinel)
    elif kind == "is_error":
        fake.result.isError = True
        fake.result.content = [types.TextContent(type="text", text=sentinel)]
    elif kind == "snapshot_error":
        fake.result.structuredContent["error"] = sentinel
    elif kind == "invalid":
        fake.result.structuredContent["observations"] = sentinel
    else:
        fake.result.structuredContent = None
        fake.result.content = [types.TextContent(type="text", text=json.dumps(payload))]
    adapter, = build(tmp_path, manifest, fake)
    with caplog.at_level(logging.DEBUG):
        result = await adapter.inspect(source)
    assert result.error
    assert result.observations == result.evidence == []
    assert sentinel not in result.model_dump_json() + caplog.text
    assert fake.closed == 1


@pytest.mark.parametrize("pointer", ["/data/a~1b/~0rows/0", ""])
async def test_structured_wrapper_pointer(tmp_path, manifest, payload, source, pointer):
    manifest["connections"][0]["resources"][0]["snapshot_pointer"] = pointer
    wrapped = {"data": {"a/b": {"~rows": [payload]}}} if pointer else payload
    adapter, = build(tmp_path, manifest, FakeTransport(wrapped))
    assert (await adapter.inspect(source)).error is None


async def test_missing_pointer_is_failure(tmp_path, manifest, payload, source):
    manifest["connections"][0]["resources"][0]["snapshot_pointer"] = "/absent"
    adapter, = build(tmp_path, manifest, FakeTransport(payload))
    assert (await adapter.inspect(source)).error


async def test_default_child_key_cannot_impersonate_explicit_binding(tmp_path, manifest, payload, source):
    manifest["connections"][0]["resources"][0]["source_key"] = "unknown"
    payload["source_key"] = "unknown"
    payload["observations"][0].pop("source_key")
    payload["evidence"] = []
    adapter, = build(tmp_path, manifest, FakeTransport(payload))
    assert (await adapter.inspect(source)).error == "MCP snapshot identity contract mismatch"


async def test_invalid_analytical_table_fails_closed(tmp_path, manifest, payload, source, comparison):
    comparison["segments"][0]["baseline"]["value"] = "not-a-number"
    payload["analytical_comparisons"] = [comparison]
    adapter, = build(tmp_path, manifest, FakeTransport(payload))
    result = await adapter.inspect(source)
    assert result.error
    assert result.analytical_comparisons == result.observations == result.evidence == []


@pytest.mark.parametrize("part", ["structured", "content", "wrapper"])
async def test_entire_result_has_byte_budget(tmp_path, manifest, payload, source, part):
    manifest["connections"][0]["max_response_bytes"] = 1024
    fake = FakeTransport(payload)
    if part == "structured":
        fake.result.structuredContent["metadata"] = {"large": "é" * 2000}
    elif part == "content":
        fake.result.content = [types.TextContent(type="text", text="x" * 2000)]
    else:
        manifest["connections"][0]["resources"][0]["snapshot_pointer"] = "/data"
        fake.result.structuredContent = {"data": payload, "unused": "x" * 2000}
    adapter, = build(tmp_path, manifest, fake)
    result = await adapter.inspect(source)
    assert result.error == "MCP response exceeded the byte limit"
    assert result.observations == []


async def test_timeout_closes_transport_and_cancellation_propagates(tmp_path, manifest, payload, source):
    manifest["connections"][0]["timeout_seconds"] = 0.03
    fake = FakeTransport(payload, delay=10)
    adapter, = build(tmp_path, manifest, fake)
    started = time.monotonic()
    assert (await adapter.inspect(source)).error == "MCP source request timed out"
    assert time.monotonic() - started < 1
    assert fake.closed == 1
    task = asyncio.create_task(adapter.inspect(source))
    await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.closed == 2


@pytest.mark.parametrize("mutation", [
    "duplicate_name", "duplicate_resource", "tenant", "adapter", "no_tenant",
    "no_contract", "no_read_only", "write_enabled", "shell_string", "literal_header",
    "unknown_field", "pointer", "nan", "zero_timeout", "huge_budget",
])
def test_bad_manifest_is_redacted(tmp_path, manifest, mutation):
    connection = manifest["connections"][0]
    entry = connection["resources"][0]
    if mutation == "duplicate_name":
        manifest["connections"].append(deepcopy(connection))
    elif mutation == "duplicate_resource":
        connection["resources"].append(deepcopy(entry))
    elif mutation in {"tenant", "adapter"}:
        if mutation == "tenant":
            entry["descriptor"]["contract"]["tenant_id"] = "secret-sentinel"
        else:
            entry["descriptor"]["adapter"] = "secret-sentinel"
    elif mutation == "no_tenant":
        del entry["descriptor"]["contract"]["tenant_id"]
    elif mutation == "no_contract":
        del entry["descriptor"]["contract"]
    elif mutation == "no_read_only":
        del connection["read_only"]
    elif mutation == "write_enabled":
        connection["read_only"] = False
    elif mutation == "shell_string":
        connection["transport"]["command"] = "echo secret-sentinel"
    elif mutation == "literal_header":
        connection["transport"] = {"type": "streamable-http", "url": "https://private.invalid",
                                   "headers": {"Authorization": "secret-sentinel"}}
    elif mutation == "unknown_field":
        entry["allow_parameters"] = True
    elif mutation == "pointer":
        entry["snapshot_pointer"] = "/bad~2"
    elif mutation == "nan":
        entry["arguments"]["bad"] = float("nan")
    elif mutation == "zero_timeout":
        connection["timeout_seconds"] = 0
    else:
        connection["max_response_bytes"] = 100_000_000
    with pytest.raises(ValueError, match="^Invalid MCP source manifest$") as error:
        build(tmp_path, manifest)
    assert "secret-sentinel" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("raw", [b'{"version":1,"version":1,"connections":[]}', b"x" * 1_000_001, b"{bad"])
def test_manifest_load_is_bounded_and_rejects_duplicate_json_keys(tmp_path, raw):
    path = tmp_path / "sources.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="^Invalid MCP source manifest$"):
        build_mcp_sources(str(path))


async def test_http_env_references_and_no_redirects(tmp_path, manifest, payload, source, monkeypatch):
    import signalweave.mcp_source as bridge

    monkeypatch.setenv("TEST_MCP_URL", "https://private.invalid/mcp")
    monkeypatch.setenv("TEST_MCP_TOKEN", "Bearer test-only-token")
    manifest["connections"][0]["transport"] = {
        "type": "streamable-http", "url": {"env": "TEST_MCP_URL"},
        "headers": {"Authorization": {"env": "TEST_MCP_TOKEN"}},
    }
    seen = {}

    @asynccontextmanager
    async def http_transport(url, *, http_client):
        seen["settings_match"] = (
            url == "https://private.invalid/mcp"
            and http_client.headers["Authorization"] == "Bearer test-only-token"
            and not http_client.follow_redirects and not http_client.trust_env
        )
        yield None, None, None

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def send_request(self, request, result_type):
            assert request.root.params.name == "read_measurement"
            return types.CallToolResult(structuredContent=payload, content=[])

    monkeypatch.setattr(bridge, "streamable_http_client", http_transport)
    monkeypatch.setattr(bridge, "ClientSession", Session)
    adapter, = build(tmp_path, manifest)
    assert (await adapter.inspect(source)).error is None
    assert seen["settings_match"]
    monkeypatch.delenv("TEST_MCP_TOKEN")
    result = await adapter.inspect(source)
    assert result.error
    assert "private.invalid" not in result.model_dump_json()
    assert "TEST_MCP_TOKEN" not in result.model_dump_json()


@pytest.mark.parametrize("analytical_only", [False, True])
async def test_real_sdk_stdio_read_and_stderr_redaction(
    tmp_path, manifest, payload, source, comparison, capfd, caplog, analytical_only,
):
    if analytical_only:
        payload["observations"] = []
        payload["evidence"] = []
        payload["analytical_comparisons"] = [comparison]
    script = tmp_path / "mock_server.py"
    script.write_text(
        "import os, sys\n"
        "from mcp.server.fastmcp import FastMCP\n"
        "server = FastMCP('local-contract-test')\n"
        "@server.tool()\n"
        "def read_measurement(measurement: str, window: dict) -> dict[str, object]:\n"
        "    assert measurement == 'orders' and window == {'days': 7}\n"
        "    assert os.environ['SERVER_TEST_TOKEN'] == 'test-only-sentinel'\n"
        "    print('test-only-sentinel', file=sys.stderr)\n"
        f"    return {payload!r}\n"
        "server.run(transport='stdio')\n"
    )
    from unittest.mock import patch

    connection = manifest["connections"][0]
    connection["transport"] = {
        "type": "stdio", "command": [sys.executable, str(script)],
        "env": {"SERVER_TEST_TOKEN": {"env": "BRIDGE_TEST_TOKEN"}},
    }
    connection["timeout_seconds"] = 10
    with patch.dict("os.environ", {"BRIDGE_TEST_TOKEN": "test-only-sentinel"}):
        adapter, = build(tmp_path, manifest)
        with caplog.at_level(logging.DEBUG):
            result = await SourceRegistry([adapter], authorized_tenants={"tenant-a"}).inspect(source)
    assert result.error is None
    if analytical_only:
        assert result.observations == result.evidence == []
        assert len(result.analytical_comparisons) == 1
        assert result.analytical_comparisons[0].current_total.value == 120
        assert result.analytical_comparisons[0].query_refs == ["approved-orders"]
    else:
        assert result.observations[0].current == 120
        assert result.observations[0].source_key == source.key
    captured = capfd.readouterr()
    assert "test-only-sentinel" not in captured.out + captured.err + caplog.text

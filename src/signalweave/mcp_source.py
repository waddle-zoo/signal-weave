"""Deployment-configured MCP reads with an explicit SignalWeave measurement contract."""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import urlsplit

import anyio
import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ResourceContract, ResourceDescriptor, ResourceSnapshot, SourceRef
from .source_identity import namespace_fingerprint, namespace_uri

_MAX_MANIFEST_BYTES = 1_000_000
_bridge_io = ContextVar("signalweave_mcp_source_io", default=False)


class _QuietBridgeLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # SDK transport diagnostics can contain raw protocol data and credentials.
        # Context inheritance covers SDK child tasks without muting other requests.
        return not _bridge_io.get()


_quiet_logs = _QuietBridgeLogs()
for _logger_name in (
    "mcp.client.stdio", "mcp.client.streamable_http", "mcp.shared.session", "client",
    "httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
    "httpcore.proxy", "httpcore.socks",
):
    logging.getLogger(_logger_name).addFilter(_quiet_logs)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class EnvReference(_Config):
    env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=200)

    def resolve(self) -> str:
        value = os.environ.get(self.env)
        if not value:
            raise ValueError("MCP source environment reference is unavailable")
        return value


class StdioTransport(_Config):
    type: Literal["stdio"]
    command: list[str] = Field(min_length=1, max_length=100, repr=False)
    env: dict[str, EnvReference] = Field(default_factory=dict, max_length=100, repr=False)

    @model_validator(mode="after")
    def validate_command(self) -> StdioTransport:
        if not self.command[0].strip() or any("\x00" in part for part in self.command):
            raise ValueError("invalid MCP command")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in self.env):
            raise ValueError("invalid MCP environment name")
        return self


class HTTPTransport(_Config):
    type: Literal["streamable-http"]
    url: str | EnvReference = Field(repr=False)
    headers: dict[str, EnvReference] = Field(default_factory=dict, max_length=100, repr=False)

    @model_validator(mode="after")
    def validate_headers(self) -> HTTPTransport:
        if any(not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key) for key in self.headers):
            raise ValueError("invalid MCP header name")
        return self


class MCPResource(_Config):
    descriptor: ResourceDescriptor
    source_key: str = Field(min_length=1, max_length=120)
    tool: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict, repr=False)
    snapshot_pointer: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_registration(self) -> MCPResource:
        if self.snapshot_pointer and (
            not self.snapshot_pointer.startswith("/")
            or re.search(r"~(?![01])", self.snapshot_pointer)
        ):
            raise ValueError("invalid snapshot JSON pointer")
        if "contract" not in self.descriptor.model_fields_set:
            raise ValueError("descriptor requires an explicit contract")
        if "tenant_id" not in self.descriptor.contract.model_fields_set:
            raise ValueError("descriptor requires an explicit tenant")
        return self


class MCPConnection(_Config):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    tenant_id: str = Field(min_length=1, max_length=160)
    context_namespace: str | None = Field(default=None, min_length=1, max_length=200)
    read_only: Literal[True]
    transport: Annotated[StdioTransport | HTTPTransport, Field(discriminator="type", repr=False)]
    resources: list[MCPResource] = Field(min_length=1, max_length=500)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300, allow_inf_nan=False)
    max_response_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)

    @model_validator(mode="after")
    def validate_bindings(self) -> MCPConnection:
        if self.context_namespace is not None and (
            self.context_namespace != self.context_namespace.strip()
            or any(ord(char) < 32 for char in self.context_namespace)
        ):
            raise ValueError("invalid MCP context namespace")
        resources: set[str] = set()
        for entry in self.resources:
            descriptor = entry.descriptor
            if descriptor.adapter != self.name or descriptor.contract.tenant_id != self.tenant_id:
                raise ValueError("MCP descriptor identity does not match its connection")
            if not descriptor.resource.strip() or len(descriptor.resource) > 500:
                raise ValueError("invalid MCP resource identity")
            if descriptor.resource in resources:
                raise ValueError("duplicate MCP resource identity")
            resources.add(descriptor.resource)
        return self


class _Manifest(_Config):
    version: Literal[1]
    connections: list[MCPConnection] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_names(self) -> _Manifest:
        names = [connection.name for connection in self.connections]
        if len(names) != len(set(names)):
            raise ValueError("duplicate MCP adapter name")
        return self


class MCPReadSession(Protocol):
    async def initialize(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult: ...


TransportFactory = Callable[[MCPConnection], AbstractAsyncContextManager[MCPReadSession]]


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous JSON object")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("unrepresentable JSON number")
    return parsed


def _result_payload(result: types.CallToolResult) -> Any:
    # MCP content may be text-only even when that text is serialized JSON.
    # Prefer an explicit structured channel; never rescue an invalid one by
    # guessing which of several alternate representations is authoritative.
    if result.structuredContent is not None:
        return result.structuredContent
    if len(result.content) != 1 or not isinstance(result.content[0], types.TextContent):
        raise ValueError("one JSON text block required without structured content")
    return json.loads(result.content[0].text, object_pairs_hook=_unique_json_object,
                      parse_constant=_reject_json_constant, parse_float=_finite_json_float)


class _SDKReadSession:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def initialize(self) -> Any:
        return await self._session.initialize()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        # Use the public typed request API: ClientSession.call_tool also discovers
        # remote tool schemas. This bridge uses only the deployment-owned contract.
        return await self._session.send_request(
            types.ClientRequest(types.CallToolRequest(
                params=types.CallToolRequestParams(name=name, arguments=arguments)
            )),
            types.CallToolResult,
        )


def _http_settings(transport: HTTPTransport) -> tuple[str, dict[str, str]]:
    url = transport.url.resolve() if isinstance(transport.url, EnvReference) else transport.url
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"} or not parsed.hostname
        or parsed.username is not None or parsed.password is not None or parsed.fragment
        or any(ord(char) <= 32 for char in url)
    ):
        raise ValueError("invalid MCP HTTP endpoint")
    headers = {name: ref.resolve() for name, ref in transport.headers.items()}
    if any("\r" in value or "\n" in value for value in headers.values()):
        raise ValueError("invalid MCP HTTP header")
    return url, headers


@asynccontextmanager
async def sdk_transport(connection: MCPConnection) -> AsyncIterator[MCPReadSession]:
    """Open one SDK session; no shell, ambient HTTP credentials, or redirects."""
    transport = connection.transport
    timeout = timedelta(seconds=connection.timeout_seconds)
    if isinstance(transport, StdioTransport):
        parameters = StdioServerParameters(
            command=transport.command[0], args=transport.command[1:],
            env={name: ref.resolve() for name, ref in transport.env.items()},
        )
        with open(os.devnull, "w") as errlog:
            async with stdio_client(parameters, errlog=errlog) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timeout) as session:
                    yield _SDKReadSession(session)
    else:
        url, headers = _http_settings(transport)
        async with httpx.AsyncClient(
            headers=headers, timeout=connection.timeout_seconds,
            follow_redirects=False, trust_env=False,
        ) as client:
            async with streamable_http_client(url, http_client=client) as (read, write, _):
                async with ClientSession(read, write, read_timeout_seconds=timeout) as session:
                    yield _SDKReadSession(session)


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _pointer(value: Any, pointer: str) -> Any:
    for encoded in pointer.split("/")[1:] if pointer else []:
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise ValueError("invalid snapshot wrapper")
    return value


class MCPSourceAdapter:
    """Read explicitly registered resources; callers cannot change transport or calls."""

    def __init__(self, connection: MCPConnection, *, transport_factory: TransportFactory = sdk_transport):
        self._connection = connection.model_copy(deep=True)
        self.name = connection.name
        self.tenant_id = connection.tenant_id
        self._resources = {entry.descriptor.resource: entry for entry in self._connection.resources}
        self._transport_factory = transport_factory

    @property
    def binding_namespace(self) -> str | None:
        transport = self._connection.transport
        if isinstance(transport, StdioTransport):
            # Stdio's upstream routing may be hidden in environment values or
            # executable behavior. Only an operator-reviewed assertion can
            # establish its namespace; never resolve or hash secret values.
            if not self._connection.context_namespace:
                return None
            return namespace_fingerprint({
                "transport": transport.type,
                "tenant": self.tenant_id,
                "context_namespace": self._connection.context_namespace,
            })

        # A URL env reference, query string, or header reference can route to
        # a workspace/tenant. Such values are opaque and may be credentials;
        # do not resolve or hash them to manufacture a namespace.
        url_parts = None
        if isinstance(transport.url, str):
            try:
                url_parts = urlsplit(transport.url)
            except ValueError:
                return None
        has_opaque_routing = (
            isinstance(transport.url, EnvReference)
            or bool(transport.headers)
            or bool(url_parts and url_parts.query)
        )
        if has_opaque_routing and not self._connection.context_namespace:
            return None
        try:
            endpoint = namespace_uri(transport.url) if isinstance(transport.url, str) else None
        except (TypeError, ValueError):
            return None
        identity: dict[str, str] = {"transport": transport.type, "tenant": self.tenant_id}
        if endpoint:
            identity["endpoint"] = endpoint
        if self._connection.context_namespace:
            identity["context_namespace"] = self._connection.context_namespace
        return namespace_fingerprint(identity)

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [entry.descriptor.model_copy(deep=True) for entry in self._resources.values()
                if entry.descriptor.contract.authorized]

    async def authorize(
        self, source: SourceRef, *, authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceDescriptor | None:
        entry = self._resources.get(source.resource)
        if (
            source.adapter != self.name or source.parameters or entry is None
            or not entry.descriptor.contract.authorized
            or (authorized_tenants is not None and self.tenant_id not in authorized_tenants)
        ):
            return None
        return entry.descriptor.model_copy(deep=True)

    async def inspect(
        self, source: SourceRef, *, authorized_tenants: Iterable[str] | None = None,
    ) -> ResourceSnapshot:
        source = source.model_copy(deep=True)
        descriptor = await self.authorize(source, authorized_tenants=authorized_tenants)
        if descriptor is None:
            return self._failure(source, None, "MCP source is not authorized")
        entry = self._resources[source.resource]
        token = _bridge_io.set(True)
        try:
            with anyio.fail_after(self._connection.timeout_seconds):
                async with self._transport_factory(self._connection.model_copy(deep=True)) as session:
                    await session.initialize()
                    result = await session.call_tool(entry.tool, deepcopy(entry.arguments))
            if result.isError:
                return self._failure(source, descriptor, "MCP read tool reported an error")
            if _json_size(result.model_dump(mode="json", by_alias=True)) > self._connection.max_response_bytes:
                return self._failure(source, descriptor, "MCP response exceeded the byte limit")
            payload = _pointer(_result_payload(result), entry.snapshot_pointer)
            snapshot = ResourceSnapshot.model_validate(payload)
            identity_mismatches: list[str] = []
            if snapshot.adapter != descriptor.adapter:
                identity_mismatches.append("adapter")
            if snapshot.resource != descriptor.resource:
                identity_mismatches.append("resource")
            if snapshot.source_key != entry.source_key:
                identity_mismatches.append("source_key")
            if "contract" not in snapshot.model_fields_set:
                identity_mismatches.append("contract")
            if (
                "tenant_id" not in snapshot.contract.model_fields_set
                or snapshot.contract.tenant_id != self.tenant_id
            ):
                identity_mismatches.append("contract.tenant_id")
            if not snapshot.contract.authorized:
                identity_mismatches.append("contract.authorized")
            if any("source_key" not in item.model_fields_set or item.source_key != entry.source_key
                   for item in snapshot.observations):
                identity_mismatches.append("observations[].source_key")
            if any("source_key" not in item.model_fields_set or item.source_key != entry.source_key
                   for item in snapshot.evidence):
                identity_mismatches.append("evidence[].source_key")
            if identity_mismatches:
                fields = ", ".join(dict.fromkeys(identity_mismatches))
                return self._failure(
                    source,
                    descriptor,
                    f"MCP snapshot identity contract mismatch (fields: {fields})",
                )
            if snapshot.error is not None:
                return self._failure(source, descriptor, "MCP snapshot reported an error")
            snapshot.source_key = source.key
            for item in [*snapshot.observations, *snapshot.evidence]:
                item.source_key = source.key
            current_comparisons = {
                comparison.key: comparison for comparison in snapshot.contract.comparison_contracts
            }
            comparison_counts = Counter(
                comparison.key for comparison in snapshot.contract.comparison_contracts
            )
            comparison_contracts = []
            for declared in descriptor.contract.comparison_contracts:
                current = current_comparisons.get(declared.key)
                if current is None or comparison_counts[declared.key] != 1:
                    comparison_contracts.append(declared.model_copy(deep=True, update={
                        "coverage": "unknown",
                        "comparable": False,
                        "detail": "The live snapshot supplied no unique quality assertion for this declared comparison.",
                        "query_refs": [],
                    }))
                    continue
                # The manifest owns meaning and authority; the source supplies
                # this run's coverage, comparability and evidence references.
                # A changed definition is unresolved, not silently reauthorized.
                same_meaning = all(
                    getattr(current, field) == getattr(declared, field)
                    for field in ("metric", "definition", "population", "unit", "comparison_window")
                )
                comparison_contracts.append(declared.model_copy(deep=True, update={
                    "coverage": current.coverage if same_meaning else "unknown",
                    "comparable": current.comparable if same_meaning else False,
                    "detail": current.detail if same_meaning else (
                        "Live comparison definition differs from the reviewed manifest; review the source binding."
                    ),
                    "query_refs": list(current.query_refs),
                }))
            severity = {"healthy": 0, "ambiguous": 1, "stale": 2, "unknown": 3, "failed": 4}
            snapshot.contract = descriptor.contract.model_copy(deep=True, update={
                "source_status": max(
                    (snapshot.contract.source_status, descriptor.contract.source_status),
                    key=severity.__getitem__,
                ),
                "comparison_contracts": comparison_contracts,
            })
            snapshot.title = descriptor.title
            snapshot.description = descriptor.description
            snapshot.captured_at = datetime.now(timezone.utc)
            if _json_size(snapshot.model_dump(mode="json")) > self._connection.max_response_bytes:
                return self._failure(source, descriptor, "MCP snapshot exceeded the byte limit")
            return snapshot
        except TimeoutError:
            return self._failure(source, descriptor, "MCP source request timed out")
        except Exception:
            # Never propagate remote payloads, exception text, URLs or validation inputs.
            return self._failure(source, descriptor, "MCP source request or snapshot validation failed")
        finally:
            _bridge_io.reset(token)

    def _failure(
        self, source: SourceRef, descriptor: ResourceDescriptor | None, message: str,
    ) -> ResourceSnapshot:
        contract = descriptor.contract.model_copy(deep=True) if descriptor else ResourceContract(
            tenant_id=self.tenant_id, authorized=False,
        )
        contract.source_status = "failed"
        return ResourceSnapshot(
            source_key=source.key, adapter=self.name, resource=source.resource,
            title=descriptor.title if descriptor else "Unavailable MCP source",
            contract=contract, error=message,
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest field")
        result[key] = value
    return result


def build_mcp_sources(
    config_path: str, *, transport_factory: TransportFactory = sdk_transport,
) -> list[MCPSourceAdapter]:
    """Load a bounded deployment-owned JSON manifest without contacting MCP servers."""
    try:
        with Path(config_path).open("rb") as stream:
            raw = stream.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise ValueError("manifest too large")
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        _json_size(payload)  # Reject NaN/Infinity even inside fixed arguments/metadata.
        manifest = _Manifest.model_validate(payload)
        return [MCPSourceAdapter(connection, transport_factory=transport_factory)
                for connection in manifest.connections]
    except Exception:
        raise ValueError("Invalid MCP source manifest") from None

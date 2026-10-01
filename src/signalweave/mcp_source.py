"""Deployment-configured MCP reads with an explicit SignalWeave measurement contract."""

from __future__ import annotations

import json
import logging
import os
import re
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
    read_only: Literal[True]
    transport: Annotated[StdioTransport | HTTPTransport, Field(discriminator="type", repr=False)]
    resources: list[MCPResource] = Field(min_length=1, max_length=500)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300, allow_inf_nan=False)
    max_response_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)

    @model_validator(mode="after")
    def validate_bindings(self) -> MCPConnection:
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
            payload = _pointer(result.structuredContent, entry.snapshot_pointer)
            snapshot = ResourceSnapshot.model_validate(payload)
            if (
                snapshot.adapter != descriptor.adapter or snapshot.resource != descriptor.resource
                or snapshot.source_key != entry.source_key
                or "contract" not in snapshot.model_fields_set
                or "tenant_id" not in snapshot.contract.model_fields_set
                or snapshot.contract.tenant_id != self.tenant_id
                or not snapshot.contract.authorized
                or any("source_key" not in item.model_fields_set or item.source_key != entry.source_key
                       for item in [*snapshot.observations, *snapshot.evidence])
            ):
                return self._failure(source, descriptor, "MCP snapshot identity contract mismatch")
            if snapshot.error is not None:
                return self._failure(source, descriptor, "MCP snapshot reported an error")
            snapshot.source_key = source.key
            for item in [*snapshot.observations, *snapshot.evidence]:
                item.source_key = source.key
            snapshot.contract = descriptor.contract.model_copy(deep=True, update={
                "source_status": (snapshot.contract.source_status
                                  if snapshot.contract.source_status != "healthy"
                                  else descriptor.contract.source_status),
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

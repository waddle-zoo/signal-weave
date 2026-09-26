"""Hosted source connections and provider-neutral credential boundaries.

The hosted path deliberately keeps credentials outside cards, MCP arguments,
and persisted connection records.  A cloud control plane stores only a
credential reference and asks a vault for the secret when constructing a
short-lived source adapter.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator


class HostedProvider(StrEnum):
    PRESET = "preset"
    HEX = "hex"
    LOOKER = "looker"


class HostedAuthMode(StrEnum):
    OAUTH = "oauth"
    BEARER = "bearer"
    API_TOKEN = "api_token"


class HostedDataMode(StrEnum):
    METADATA_ONLY = "metadata_only"
    CACHED_RESULTS = "cached_results"
    LIVE_QUERY = "live_query"


class HostedDataPolicy(BaseModel):
    """Data movement and execution limits for one hosted connection."""

    mode: HostedDataMode = HostedDataMode.CACHED_RESULTS
    allow_live_queries: bool = False
    allow_refresh: bool = False
    retain_raw_results: bool = False
    max_result_rows: int = Field(default=500, ge=1, le=10_000)
    max_snapshot_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)
    retention_hours: int = Field(default=24, ge=0, le=8_760)

    @model_validator(mode="after")
    def validate_execution_policy(self) -> HostedDataPolicy:
        if self.mode == HostedDataMode.LIVE_QUERY and not self.allow_live_queries:
            raise ValueError("live_query mode requires allow_live_queries=true")
        if self.mode == HostedDataMode.LIVE_QUERY and not self.allow_refresh:
            raise ValueError("live_query mode requires allow_refresh=true")
        if self.retention_hours == 0 and self.retain_raw_results:
            raise ValueError("raw results cannot be retained when retention_hours is zero")
        return self


class HostedConnection(BaseModel):
    """A tenant-scoped reference to a customer-owned hosted BI workspace.

    ``credential_ref`` is intentionally opaque.  Secrets must live in a vault,
    never in this model, an insight card, or an MCP tool payload.
    """

    id: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=160)
    provider: HostedProvider
    base_url: str = Field(min_length=8, max_length=2_000)
    external_workspace: str = Field(min_length=1, max_length=240)
    credential_ref: str = Field(min_length=1, max_length=500)
    auth_mode: HostedAuthMode
    policy: HostedDataPolicy = Field(default_factory=HostedDataPolicy)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def validate_url(self) -> HostedConnection:
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("hosted connection base_url must be an HTTP(S) URL")
        return self


class HostedCredentialVault(Protocol):
    """Minimal vault contract used by the adapter factory."""

    def get(self, credential_ref: str) -> Mapping[str, str]: ...


class InMemoryCredentialVault:
    """Test/local vault; production deployments should provide KMS-backed storage."""

    def __init__(self, credentials: Mapping[str, Mapping[str, str]] | None = None) -> None:
        self._credentials = {
            ref: dict(values) for ref, values in (credentials or {}).items()
        }

    def put(self, credential_ref: str, values: Mapping[str, str]) -> None:
        if not credential_ref.strip():
            raise ValueError("credential_ref must not be empty")
        if not values:
            raise ValueError("credential values must not be empty")
        self._credentials[credential_ref] = dict(values)

    def get(self, credential_ref: str) -> Mapping[str, str]:
        try:
            return dict(self._credentials[credential_ref])
        except KeyError as error:
            raise KeyError(f"credential reference is not available: {credential_ref}") from error


class HostedConnectionStore(Protocol):
    def save(self, connection: HostedConnection) -> None: ...

    def get(self, connection_id: str, *, tenant_id: str) -> HostedConnection: ...

    def list(self, *, tenant_id: str) -> list[HostedConnection]: ...


def hosted_adapter_name(connection: HostedConnection) -> str:
    """Return a stable routing name when one process serves multiple connections."""

    suffix = re.sub(r"[^a-z0-9_-]+", "-", connection.id.lower()).strip("-_")
    return f"{connection.provider.value}__{suffix}"[:80]


class InMemoryHostedConnectionStore:
    """Tenant-safe reference store used by local deployments and tests."""

    def __init__(self) -> None:
        self._connections: dict[str, HostedConnection] = {}

    def save(self, connection: HostedConnection) -> None:
        existing = self._connections.get(connection.id)
        if existing and existing.tenant_id != connection.tenant_id:
            raise ValueError("connection id already belongs to another tenant")
        self._connections[connection.id] = connection

    def get(self, connection_id: str, *, tenant_id: str) -> HostedConnection:
        connection = self._connections.get(connection_id)
        if connection is None or connection.tenant_id != tenant_id:
            raise KeyError(f"hosted connection is not available in tenant {tenant_id}")
        return connection

    def list(self, *, tenant_id: str) -> list[HostedConnection]:
        return [
            connection
            for connection in self._connections.values()
            if connection.tenant_id == tenant_id
        ]


class SQLiteHostedConnectionStore:
    """Durable connection metadata store; credentials remain in the vault."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._initialize()

    def _initialize(self) -> None:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS hosted_connections (
                    connection_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def save(self, connection: HostedConnection) -> None:
        payload = json.dumps(connection.model_dump(mode="json"), sort_keys=True)
        database = sqlite3.connect(self.path, timeout=30)
        try:
            existing = database.execute(
                "SELECT tenant_id FROM hosted_connections WHERE connection_id = ?",
                (connection.id,),
            ).fetchone()
            if existing is not None and existing[0] != connection.tenant_id:
                raise ValueError("connection id already belongs to another tenant")
            database.execute(
                """
                INSERT INTO hosted_connections(connection_id, tenant_id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(connection_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    payload = excluded.payload
                """,
                (connection.id, connection.tenant_id, payload),
            )
            database.commit()
        finally:
            database.close()

    def get(self, connection_id: str, *, tenant_id: str) -> HostedConnection:
        database = sqlite3.connect(self.path, timeout=30)
        try:
            row = database.execute(
                "SELECT payload FROM hosted_connections WHERE connection_id = ? AND tenant_id = ?",
                (connection_id, tenant_id),
            ).fetchone()
        finally:
            database.close()
        if row is None:
            raise KeyError(f"hosted connection is not available in tenant {tenant_id}")
        return HostedConnection.model_validate(json.loads(row[0]))

    def list(self, *, tenant_id: str) -> list[HostedConnection]:
        database = sqlite3.connect(self.path, timeout=30)
        try:
            rows = database.execute(
                "SELECT payload FROM hosted_connections WHERE tenant_id = ? ORDER BY connection_id",
                (tenant_id,),
            ).fetchall()
        finally:
            database.close()
        return [HostedConnection.model_validate(json.loads(row[0])) for row in rows]


def build_hosted_adapter(
    connection: HostedConnection,
    vault: HostedCredentialVault,
    *,
    transport: Any | None = None,
):
    """Build one tenant-bound adapter without exposing its credential.

    Imports are intentionally local so deployments that only install the
    shipped Superset path do not pay for provider-specific initialization.
    """

    if not connection.enabled:
        raise ValueError(f"hosted connection {connection.id} is disabled")
    credentials = dict(vault.get(connection.credential_ref))
    if connection.provider == HostedProvider.PRESET:
        from .preset_adapter import PresetAdapter, PresetCloudClient

        client = PresetCloudClient(
            connection.base_url,
            access_token=credentials.get("access_token"),
            api_token_name=credentials.get("name"),
            api_token_secret=credentials.get("secret"),
            api_base_url=credentials.get("api_base_url", "https://api.app.preset.io"),
            transport=transport,
        )
        return PresetAdapter(
            client,
            tenant_id=connection.tenant_id,
            policy=connection.policy,
            adapter_name=hosted_adapter_name(connection),
        )
    if connection.provider == HostedProvider.HEX:
        from .hex_adapter import HexAdapter, HexCloudClient

        client = HexCloudClient(
            connection.base_url,
            access_token=credentials.get("access_token"),
            transport=transport,
        )
        return HexAdapter(
            client,
            tenant_id=connection.tenant_id,
            policy=connection.policy,
            adapter_name=hosted_adapter_name(connection),
        )
    if connection.provider == HostedProvider.LOOKER:
        from .looker_adapter import LookerAdapter, LookerCloudClient

        client = LookerCloudClient(
            connection.base_url,
            access_token=credentials.get("access_token"),
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
            token_type=credentials.get("token_type", "token"),
            transport=transport,
        )
        return LookerAdapter(
            client,
            tenant_id=connection.tenant_id,
            policy=connection.policy,
            adapter_name=hosted_adapter_name(connection),
        )
    raise ValueError(f"unsupported hosted provider: {connection.provider}")


def build_hosted_adapters(
    connections: Iterable[HostedConnection],
    vault: HostedCredentialVault,
    *,
    transport: Any | None = None,
) -> list[Any]:
    return [
        build_hosted_adapter(connection, vault, transport=transport)
        for connection in connections
    ]

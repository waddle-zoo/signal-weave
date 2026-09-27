"""Hosted source connections and provider-neutral credential boundaries.

The hosted path deliberately keeps credentials outside cards, MCP arguments,
and persisted connection records.  A cloud control plane stores only a
credential reference and asks a vault for the secret when constructing a
short-lived source adapter.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    model_config = ConfigDict(extra="forbid")

    mode: HostedDataMode = HostedDataMode.CACHED_RESULTS
    allow_live_queries: bool = False
    allow_refresh: bool = False
    max_result_rows: int = Field(default=500, ge=1, le=10_000)
    max_snapshot_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)

    @model_validator(mode="after")
    def validate_execution_policy(self) -> HostedDataPolicy:
        if self.mode == HostedDataMode.LIVE_QUERY and not self.allow_live_queries:
            raise ValueError("live_query mode requires allow_live_queries=true")
        if self.mode == HostedDataMode.LIVE_QUERY and not self.allow_refresh:
            raise ValueError("live_query mode requires allow_refresh=true")
        if self.mode != HostedDataMode.LIVE_QUERY and self.allow_live_queries:
            raise ValueError(
                "allow_live_queries=true requires live_query mode; refusing a contradictory policy"
            )
        if self.mode != HostedDataMode.LIVE_QUERY and self.allow_refresh:
            raise ValueError(
                "allow_refresh=true requires live_query mode; refusing a contradictory policy"
            )
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
    external_workspace: str = Field(
        min_length=1,
        max_length=240,
        description=(
            "Descriptive provider workspace label; the tenant-bound credential and "
            "validated base_url are the authorization boundary."
        ),
    )
    credential_ref: str = Field(min_length=1, max_length=500)
    auth_mode: HostedAuthMode
    policy: HostedDataPolicy = Field(default_factory=HostedDataPolicy)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def validate_url(self) -> HostedConnection:
        try:
            parsed = urlsplit(self.base_url)
            # Accessing ``port`` validates malformed numeric ports. Without
            # this, a direct hosted connection could survive model validation
            # and fail only when its adapter first opens a socket.
            _validated_port = parsed.port
        except ValueError as error:
            raise ValueError("hosted connection base_url must be a valid https origin") from error
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("hosted connection base_url must use https")
        if parsed.username or parsed.password:
            raise ValueError("hosted connection base_url must not contain credentials")
        if parsed.path not in {"", "/"}:
            raise ValueError("hosted connection base_url must be an origin without a path")
        if parsed.query or parsed.fragment:
            raise ValueError(
                "hosted connection base_url must be an origin without query or fragment"
            )
        return self

    @model_validator(mode="after")
    def validate_metadata(self) -> HostedConnection:
        """Keep the safe metadata escape hatch from becoming a secret store."""

        sensitive_fragments = (
            "access_token",
            "api_token",
            "authorization",
            "client_secret",
            "credential",
            "password",
            "secret",
            "token",
        )
        for key in self.metadata:
            normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if any(fragment in normalized for fragment in sensitive_fragments):
                raise ValueError(
                    "hosted connection metadata must not contain credential fields"
                )
        return self


class HostedCredentialVault(Protocol):
    """Tenant-scoped vault contract used by the adapter factory.

    The reference is intentionally opaque.  A vault must independently bind
    it to the requested tenant; SignalWeave must not infer ownership from a
    reference string or trust a caller-controlled naming convention.
    """

    def get(self, credential_ref: str, *, tenant_id: str) -> Mapping[str, str]: ...


class InMemoryCredentialVault:
    """Test/local vault; production deployments should provide KMS-backed storage."""

    def __init__(
        self,
        credentials: Mapping[str, Mapping[str, str]] | None = None,
        *,
        tenant_by_ref: Mapping[str, str] | None = None,
    ) -> None:
        self._credentials = {
            ref: dict(values) for ref, values in (credentials or {}).items()
        }
        self._tenant_by_ref = dict(tenant_by_ref or {})

    def put(
        self,
        credential_ref: str,
        values: Mapping[str, str],
        *,
        tenant_id: str,
    ) -> None:
        if not credential_ref.strip():
            raise ValueError("credential_ref must not be empty")
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        if not values:
            raise ValueError("credential values must not be empty")
        self._credentials[credential_ref] = dict(values)
        self._tenant_by_ref[credential_ref] = tenant_id

    def get(self, credential_ref: str, *, tenant_id: str) -> Mapping[str, str]:
        owner = self._tenant_by_ref.get(credential_ref)
        if owner is None:
            raise KeyError(
                f"credential reference has no tenant binding: {credential_ref}"
            )
        if owner != tenant_id:
            raise KeyError(
                f"credential reference is not available in tenant {tenant_id}"
            )
        try:
            return dict(self._credentials[credential_ref])
        except KeyError as error:
            raise KeyError(f"credential reference is not available: {credential_ref}") from error


class HostedConnectionStore(Protocol):
    def save(self, connection: HostedConnection) -> None: ...

    def get(self, connection_id: str, *, tenant_id: str) -> HostedConnection: ...

    def list(self, *, tenant_id: str) -> list[HostedConnection]: ...


def hosted_adapter_name(connection: HostedConnection) -> str:
    """Return a stable, collision-resistant route for one hosted connection."""

    suffix = re.sub(r"[^a-z0-9_-]+", "-", connection.id.lower()).strip("-_")
    route = f"{connection.provider.value}__{suffix}"
    if len(route) <= 80:
        return route
    digest = hashlib.sha256(connection.id.encode("utf-8")).hexdigest()[:12]
    return f"{route[:80 - len(digest) - 1]}-{digest}"


def _preset_credentials(
    connection: HostedConnection, credentials: Mapping[str, str]
) -> tuple[str | None, str | None, str | None]:
    """Validate the credential shape declared by a Preset connection."""

    allowed_fields = {"api_base_url"}
    access_token = credentials.get("access_token")
    token_name = credentials.get("name")
    token_secret = credentials.get("secret")
    if connection.auth_mode == HostedAuthMode.API_TOKEN:
        allowed_fields.update({"name", "secret"})
        unexpected = sorted(set(credentials) - allowed_fields)
        if unexpected:
            raise ValueError(
                "Preset API_TOKEN credentials contain unsupported fields: "
                + ", ".join(unexpected)
            )
        if access_token or not (token_name and token_secret):
            raise ValueError(
                "Preset API_TOKEN connections require name and secret credentials only"
            )
        return None, token_name, token_secret
    if connection.auth_mode == HostedAuthMode.BEARER:
        allowed_fields.add("access_token")
        unexpected = sorted(set(credentials) - allowed_fields)
        if unexpected:
            raise ValueError(
                "Preset BEARER credentials contain unsupported fields: "
                + ", ".join(unexpected)
            )
        if not access_token or token_name or token_secret:
            raise ValueError("Preset BEARER connections require an access_token only")
        return access_token, None, None
    raise ValueError("Preset OAuth connections are not supported by this adapter")


def _validated_credential_map(credentials: Mapping[str, str]) -> dict[str, str]:
    """Keep untrusted vault implementations inside the string credential contract."""

    values = dict(credentials)
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in values.items()
    ):
        raise ValueError("hosted credentials must contain only string key/value pairs")
    return values


def _validated_hex_credentials(
    connection: HostedConnection, credentials: Mapping[str, str]
) -> str:
    """Validate the Hex bearer contract before constructing a provider client."""

    if connection.auth_mode != HostedAuthMode.BEARER:
        raise ValueError("Hex connections require BEARER authentication")
    unexpected = sorted(set(credentials) - {"access_token"})
    if unexpected:
        raise ValueError(
            "Hex BEARER credentials contain unsupported fields: "
            + ", ".join(unexpected)
        )
    access_token = credentials.get("access_token")
    if not access_token:
        raise ValueError("Hex BEARER connections require an access_token only")
    return access_token


def _validated_looker_credentials(
    connection: HostedConnection, credentials: Mapping[str, str]
) -> tuple[str | None, str | None, str | None, str]:
    """Validate Looker's bearer or client-credential login contract."""

    access_token = credentials.get("access_token")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    if connection.auth_mode == HostedAuthMode.BEARER:
        unexpected = sorted(set(credentials) - {"access_token", "token_type"})
        if unexpected:
            raise ValueError(
                "Looker BEARER credentials contain unsupported fields: "
                + ", ".join(unexpected)
            )
        if not access_token or client_id or client_secret:
            raise ValueError("Looker BEARER connections require an access_token only")
    elif connection.auth_mode == HostedAuthMode.OAUTH:
        unexpected = sorted(set(credentials) - {"client_id", "client_secret", "token_type"})
        if unexpected:
            raise ValueError(
                "Looker OAuth credentials contain unsupported fields: "
                + ", ".join(unexpected)
            )
        if access_token or not (client_id and client_secret):
            raise ValueError(
                "Looker OAuth connections require client_id and client_secret only"
            )
    else:
        raise ValueError("Looker API_TOKEN authentication is not supported")
    token_type = credentials.get("token_type", "token")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}", token_type):
        raise ValueError("Looker token_type must be a simple HTTP auth scheme")
    return access_token, client_id, client_secret, token_type


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
    credentials = _validated_credential_map(
        vault.get(connection.credential_ref, tenant_id=connection.tenant_id)
    )
    if connection.provider == HostedProvider.PRESET:
        from .preset_adapter import PresetAdapter, PresetCloudClient

        access_token, api_token_name, api_token_secret = _preset_credentials(
            connection, credentials
        )
        client = PresetCloudClient(
            connection.base_url,
            access_token=access_token,
            api_token_name=api_token_name,
            api_token_secret=api_token_secret,
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

        access_token = _validated_hex_credentials(connection, credentials)
        client = HexCloudClient(
            connection.base_url,
            access_token=access_token,
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

        access_token, client_id, client_secret, token_type = _validated_looker_credentials(
            connection, credentials
        )
        client = LookerCloudClient(
            connection.base_url,
            access_token=access_token,
            client_id=client_id,
            client_secret=client_secret,
            token_type=token_type,
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

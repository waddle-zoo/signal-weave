"""Prove the tenant, credential, and data-policy boundary of hosted Preset.

This is an evidence-producing trial, not a provider or Jev accuracy benchmark.
It constructs the shipped production factories and clients, then serializes the
boundary invariants an operator needs to inspect before enabling a connection.
No provider request or TypeSafe request is made.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

import httpx

from signalweave.hex_adapter import HexCloudClient
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
    hosted_adapter_name,
)
from signalweave.looker_adapter import LookerCloudClient
from signalweave.models import SourceRef

ROOT = Path(__file__).resolve().parent.parent


def _connection(
    tenant_id: str,
    *,
    auth_mode: HostedAuthMode,
    provider: HostedProvider = HostedProvider.PRESET,
) -> HostedConnection:
    return HostedConnection(
        id=f"{tenant_id}-{provider.value}",
        tenant_id=tenant_id,
        provider=provider,
        base_url=f"https://{tenant_id}.{provider.value}.example",
        external_workspace=f"{tenant_id}-display-label",
        credential_ref=f"vault://{tenant_id}/{provider.value}",
        auth_mode=auth_mode,
    )


class _RequestCounter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise AssertionError(f"provider was contacted before authorization: {request.url}")


def _credential_checks() -> dict[str, bool]:
    api_connection = _connection("tenant-a", auth_mode=HostedAuthMode.API_TOKEN)
    bearer_connection = _connection("tenant-b", auth_mode=HostedAuthMode.BEARER)
    vault = InMemoryCredentialVault(
        {
            api_connection.credential_ref: {"name": "opaque-name", "secret": "opaque-secret"},
            bearer_connection.credential_ref: {"access_token": "opaque-access-token"},
        },
        tenant_by_ref={
            api_connection.credential_ref: api_connection.tenant_id,
            bearer_connection.credential_ref: bearer_connection.tenant_id,
        },
    )

    api_adapter = build_hosted_adapter(api_connection, vault)
    bearer_adapter = build_hosted_adapter(bearer_connection, vault)
    serialized = json.dumps(api_connection.model_dump(mode="json"), sort_keys=True)

    try:
        mixed_credentials = InMemoryCredentialVault(
            {
                api_connection.credential_ref: {
                    "name": "opaque-name",
                    "secret": "opaque-secret",
                    "access_token": "wrong-mode",
                }
            },
            tenant_by_ref={api_connection.credential_ref: api_connection.tenant_id},
        )
        build_hosted_adapter(api_connection, mixed_credentials)
    except ValueError:
        mixed_rejected = True
    else:
        mixed_rejected = False

    oauth_connection = api_connection.model_copy(update={"auth_mode": HostedAuthMode.OAUTH})
    try:
        build_hosted_adapter(oauth_connection, vault)
    except ValueError:
        oauth_rejected = True
    else:
        oauth_rejected = False

    return {
        "api_token_builds": api_adapter.client.base_url == api_connection.base_url,
        "bearer_builds": bearer_adapter.client.base_url == bearer_connection.base_url,
        "oauth_rejected": oauth_rejected,
        "mixed_credentials_rejected": mixed_rejected,
        "connection_record_has_no_secret_material": "opaque-secret" not in serialized
        and "opaque-access-token" not in serialized,
    }


def _provider_credential_checks() -> dict[str, bool]:
    """Exercise mode-specific contracts for the other shipped hosted factories."""

    hex_connection = _connection(
        "tenant-hex", auth_mode=HostedAuthMode.BEARER, provider=HostedProvider.HEX
    )
    hex_vault = InMemoryCredentialVault(
        {hex_connection.credential_ref: {"access_token": "hex-token"}},
        tenant_by_ref={hex_connection.credential_ref: hex_connection.tenant_id},
    )
    hex_bearer_builds = (
        build_hosted_adapter(hex_connection, hex_vault).__class__.__name__ == "HexAdapter"
    )
    try:
        build_hosted_adapter(
            hex_connection.model_copy(update={"auth_mode": HostedAuthMode.API_TOKEN}),
            hex_vault,
        )
    except ValueError:
        hex_auth_mismatch_rejected = True
    else:
        hex_auth_mismatch_rejected = False
    try:
        build_hosted_adapter(
            hex_connection,
            InMemoryCredentialVault(
                {
                    hex_connection.credential_ref: {
                        "access_token": "hex-token",
                        "secret": "extra",
                    }
                },
                tenant_by_ref={hex_connection.credential_ref: hex_connection.tenant_id},
            ),
        )
    except ValueError:
        hex_extra_fields_rejected = True
    else:
        hex_extra_fields_rejected = False

    looker_connection = _connection(
        "tenant-looker", auth_mode=HostedAuthMode.BEARER, provider=HostedProvider.LOOKER
    )
    looker_bearer_vault = InMemoryCredentialVault(
        {looker_connection.credential_ref: {"access_token": "looker-token"}},
        tenant_by_ref={looker_connection.credential_ref: looker_connection.tenant_id},
    )
    looker_bearer_builds = (
        build_hosted_adapter(looker_connection, looker_bearer_vault).__class__.__name__
        == "LookerAdapter"
    )
    looker_oauth = looker_connection.model_copy(update={"auth_mode": HostedAuthMode.OAUTH})
    looker_oauth_vault = InMemoryCredentialVault(
        {
            looker_oauth.credential_ref: {
                "client_id": "looker-client",
                "client_secret": "looker-secret",
            }
        },
        tenant_by_ref={looker_oauth.credential_ref: looker_oauth.tenant_id},
    )
    looker_oauth_builds = (
        build_hosted_adapter(looker_oauth, looker_oauth_vault).__class__.__name__
        == "LookerAdapter"
    )
    try:
        build_hosted_adapter(
            looker_connection.model_copy(update={"auth_mode": HostedAuthMode.API_TOKEN}),
            looker_bearer_vault,
        )
    except ValueError:
        looker_api_token_rejected = True
    else:
        looker_api_token_rejected = False
    try:
        build_hosted_adapter(
            looker_connection,
            InMemoryCredentialVault(
                {
                    looker_connection.credential_ref: {
                        "access_token": "looker-token",
                        "client_secret": "extra",
                    }
                },
                tenant_by_ref={looker_connection.credential_ref: looker_connection.tenant_id},
            ),
        )
    except ValueError:
        looker_extra_fields_rejected = True
    else:
        looker_extra_fields_rejected = False
    return {
        "hex_bearer_builds": hex_bearer_builds,
        "hex_auth_mismatch_rejected": hex_auth_mismatch_rejected,
        "hex_extra_fields_rejected": hex_extra_fields_rejected,
        "looker_bearer_builds": looker_bearer_builds,
        "looker_oauth_builds": looker_oauth_builds,
        "looker_api_token_rejected": looker_api_token_rejected,
        "looker_extra_fields_rejected": looker_extra_fields_rejected,
    }


async def _direct_client_boundary_checks() -> dict[str, bool]:
    """Exercise provider clients without going through HostedConnection."""

    checks: dict[str, bool] = {}
    cases = (
        ("hex", HexCloudClient, {"access_token": "hex-token"}),
        ("looker", LookerCloudClient, {"access_token": "looker-token"}),
    )
    for name, client_type, kwargs in cases:
        rejected: list[bool] = []
        for value in (
            "http://provider.example",
            "https://provider.example/workspace",
            "https://provider.example/?token=leak",
            "https://user:secret@provider.example",
            "https://provider.example:not-a-port",
            "https://your-workspace.<region>.provider",
        ):
            try:
                client_type(value, **kwargs)
            except ValueError:
                rejected.append(True)
            else:
                rejected.append(False)
        checks[f"{name}_direct_client_rejects_unsafe_origins"] = all(rejected)

    redirect_cases = (
        ("hex", HexCloudClient("https://app.hex.test", access_token="hex-token")),
        (
            "looker",
            LookerCloudClient(
                "https://growth.cloud.looker.test", access_token="looker-token"
            ),
        ),
    )
    for name, client in redirect_cases:
        requests = 0

        def redirect_handler(request: httpx.Request) -> httpx.Response:
            nonlocal requests
            requests += 1
            return httpx.Response(
                302,
                headers={"location": "https://attacker.example/collect"},
                request=request,
            )

        client.transport = httpx.MockTransport(redirect_handler)
        try:
            if name == "hex":
                await client.list_projects_page()
            else:
                await client.search_looks()
        except httpx.HTTPStatusError:
            pass
        checks[f"{name}_redirect_is_not_followed"] = requests == 1

    placeholder_connection = _connection(
        "tenant-sample", auth_mode=HostedAuthMode.BEARER, provider=HostedProvider.HEX
    )
    try:
        build_hosted_adapter(
            placeholder_connection,
            InMemoryCredentialVault(
                {placeholder_connection.credential_ref: {"access_token": "replace-me"}},
                tenant_by_ref={
                    placeholder_connection.credential_ref: placeholder_connection.tenant_id
                },
            ),
        )
    except ValueError:
        checks["direct_factory_rejects_placeholder_credentials"] = True
    else:
        checks["direct_factory_rejects_placeholder_credentials"] = False

    vault = InMemoryCredentialVault(
        {"vault://tenant-a/shared": {"access_token": "tenant-a-token"}},
        tenant_by_ref={"vault://tenant-a/shared": "tenant-a"},
    )
    try:
        vault.put(
            "vault://tenant-a/shared",
            {"access_token": "tenant-b-token"},
            tenant_id="tenant-b",
        )
    except ValueError:
        checks["local_vault_rejects_cross_tenant_rebind"] = True
    else:
        checks["local_vault_rejects_cross_tenant_rebind"] = False
    return checks


async def _tenant_checks() -> dict[str, object]:
    first = _connection("tenant-a", auth_mode=HostedAuthMode.BEARER)
    second = _connection("tenant-b", auth_mode=HostedAuthMode.BEARER)
    vault = InMemoryCredentialVault(
        {
            first.credential_ref: {"access_token": "tenant-a-token"},
            second.credential_ref: {"access_token": "tenant-b-token"},
        },
        tenant_by_ref={
            first.credential_ref: first.tenant_id,
            second.credential_ref: second.tenant_id,
        },
    )
    store = InMemoryHostedConnectionStore()
    store.save(first)
    store.save(second)

    try:
        store.get(first.id, tenant_id=second.tenant_id)
    except KeyError:
        foreign_connection_rejected = True
    else:
        foreign_connection_rejected = False

    try:
        vault.get(first.credential_ref, tenant_id=second.tenant_id)
    except KeyError:
        foreign_credential_rejected = True
    else:
        foreign_credential_rejected = False

    transport = _RequestCounter()
    adapter = build_hosted_adapter(
        first,
        vault,
        transport=httpx.MockTransport(transport),
    )
    result = await adapter.authorize(
        SourceRef(
            key="foreign-scope-check",
            adapter=adapter.name,
            resource="dashboard:1001",
            label="foreign dashboard",
        ),
        authorized_tenants={second.tenant_id},
    )

    return {
        "foreign_connection_rejected": foreign_connection_rejected,
        "foreign_credential_rejected": foreign_credential_rejected,
        "foreign_list_is_empty": store.list(tenant_id="tenant-c")==[],
        "foreign_authorize_skips_provider": result is None,
        "connection_routes_are_distinct": hosted_adapter_name(first)
        != hosted_adapter_name(second),
        "provider_requests": transport.calls,
        "visible_tenants": sorted(
            connection.tenant_id for connection in store.list(tenant_id="tenant-a")
        ),
    }


def _storage_check() -> bool:
    connection = _connection("tenant-storage", auth_mode=HostedAuthMode.BEARER)
    with tempfile.TemporaryDirectory(prefix="signalweave-boundary-") as directory:
        path = Path(directory) / "connections.sqlite"
        store = SQLiteHostedConnectionStore(str(path))
        store.save(connection)
        serialized_db = path.read_bytes()
        restored = SQLiteHostedConnectionStore(str(path)).get(
            connection.id, tenant_id=connection.tenant_id
        )
    return restored == connection and b"opaque-secret" not in serialized_db


def _policy_checks() -> dict[str, object]:
    policies = {
        "metadata_only": HostedDataPolicy(mode=HostedDataMode.METADATA_ONLY),
        "cached_results": HostedDataPolicy(mode=HostedDataMode.CACHED_RESULTS),
        "live_query": HostedDataPolicy(
            mode=HostedDataMode.LIVE_QUERY,
            allow_live_queries=True,
            allow_refresh=True,
        ),
    }
    client_modes: dict[str, dict[str, object]] = {}
    for name, policy in policies.items():
        connection = _connection(f"policy-{name}", auth_mode=HostedAuthMode.BEARER)
        vault = InMemoryCredentialVault(
            {connection.credential_ref: {"access_token": "policy-token"}},
            tenant_by_ref={connection.credential_ref: connection.tenant_id},
        )
        adapter = build_hosted_adapter(
            connection.model_copy(update={"policy": policy}), vault
        )
        client_modes[name] = {
            "mode": policy.mode.value,
            "force_refresh": adapter.client._force_refresh,
            "allow_live_queries": policy.allow_live_queries,
            "allow_refresh": policy.allow_refresh,
            "max_result_rows": policy.max_result_rows,
            "max_snapshot_bytes": policy.max_snapshot_bytes,
        }
    checks = {
        "metadata_only_does_not_force_refresh": client_modes["metadata_only"][
            "force_refresh"
        ]
        is False,
        "cached_results_do_not_force_refresh": client_modes["cached_results"][
            "force_refresh"
        ]
        is False,
        "live_query_forces_refresh": client_modes["live_query"]["force_refresh"] is True,
        "live_query_has_explicit_permissions": client_modes["live_query"][
            "allow_live_queries"
        ]
        and client_modes["live_query"]["allow_refresh"],
        "all_modes_have_bounded_limits": all(
            item["max_result_rows"] <= 10_000 and item["max_snapshot_bytes"] <= 10_000_000
            for item in client_modes.values()
        ),
    }
    return {"modes": client_modes, "checks": checks}


async def run_trial() -> dict[str, object]:
    credentials = _credential_checks()
    provider_credentials = _provider_credential_checks()
    direct_clients = await _direct_client_boundary_checks()
    tenants = await _tenant_checks()
    policies = _policy_checks()
    checks = {
        **{f"credential_{key}": value for key, value in credentials.items()},
        **{f"provider_credential_{key}": value for key, value in provider_credentials.items()},
        **{f"direct_client_{key}": value for key, value in direct_clients.items()},
        **{f"tenant_{key}": value for key, value in tenants.items() if isinstance(value, bool)},
        **{f"policy_{key}": value for key, value in policies["checks"].items()},
        "tenant_provider_requests": tenants["provider_requests"] == 0,
        "sqlite_metadata_is_secret_free": _storage_check(),
    }
    return {
        "trial": "preset-boundary-matrix",
        "credential_modes": credentials,
        "provider_credentials": provider_credentials,
        "direct_client_boundary": direct_clients,
        "tenant_boundary": tenants,
        "data_policy": policies,
        "checks": checks,
        "provider_requests": tenants["provider_requests"],
        "typesafe_requests": 0,
        "passed": all(value is True for value in checks.values()),
        "not_proven": [
            "real Preset tenant permissions, plan limits, rate limits, and network policy",
            "live Jev semantic accuracy or customer usefulness",
            "managed SignalWeave hosting, OAuth callbacks, KMS, or multi-tenant workers",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_trial())
    serialized = json.dumps(report, indent=2, sort_keys=True)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit("Preset boundary matrix failed")


if __name__ == "__main__":
    main()

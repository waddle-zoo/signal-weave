"""End-to-end proof for the native OIDC-protected MCP surface."""

from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings

from signalweave.auth import OIDCJWTVerifier, OIDCSettings, principal_from_access_token
from signalweave.engine import InsightEngine
from signalweave.hosted import (
    HostedAuthMode,
    HostedConnection,
    HostedProvider,
    InMemoryCredentialVault,
)
from signalweave.mcp_server import create_mcp
from signalweave.models import InsightCard, InsightCardStatus, SourceRef
from signalweave.runtime import Runtime, build_runtime
from signalweave.sources import SourceRegistry
from signalweave.store import JsonInsightCardStore


class NoopJev:
    name = "jev-http-integration-test"

    async def compile_plan(self, state, card):
        del state, card
        return {"capabilities": [], "baseline": "previous_period"}

    async def judge(self, state, card, plan, observations):
        del state, card, plan, observations
        raise AssertionError("the list-card auth proof must not evaluate a card")


def _card(card_id: str, tenant: str) -> InsightCard:
    return InsightCard(
        id=card_id,
        title=f"{tenant} card",
        what_to_watch="Changes in the operating picture.",
        why_watch="The owner needs a bounded daily signal.",
        principal_id=f"{tenant}-user",
        principal_tenant=tenant,
    )


def _oidc_fixture() -> tuple[httpx.AsyncClient, OIDCJWTVerifier, callable]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
    public_jwk = {**json.loads(public_jwk), "kid": "integration-key", "alg": "RS256"}
    settings = OIDCSettings(
        issuer_url="https://issuer.integration.test",
        audience="signalweave",
        tenant_claim="tenant_id",
        jwks_ttl_seconds=300,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={"jwks_uri": "https://issuer.integration.test/keys"},
            )
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    verifier = OIDCJWTVerifier(settings, http_client=client)

    def token(*, tenant: str = "tenant-a", scopes: str = "insights:read insights:run") -> str:
        now = int(time.time())
        claims = {
            "iss": settings.issuer_url,
            "aud": settings.audience,
            "sub": f"{tenant}-user",
            "tenant_id": tenant,
            "scope": scopes,
            "iat": now,
            "exp": now + 300,
        }
        return jwt.encode(
            claims,
            private_key,
            algorithm="RS256",
            headers={"kid": "integration-key"},
        )

    return client, verifier, token


def _payload(response: httpx.Response) -> dict:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data_lines = [
            line.removeprefix("data: ")
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert data_lines, response.text
        return json.loads(data_lines[-1])
    return response.json()


@pytest.mark.asyncio
async def test_signed_oidc_token_scopes_the_real_mcp_http_surface(tmp_path):
    oidc_client, verifier, token = _oidc_fixture()
    cards = JsonInsightCardStore(tmp_path / "cards.json")
    cards.save_card(_card("card-a", "tenant-a"))
    cards.save_card(
        _card("card-b", "tenant-b").model_copy(
            update={
                "status": InsightCardStatus.APPROVED,
                "sources": [
                    SourceRef(
                        key="tenant-b-source",
                        adapter="superset",
                        resource="dashboard:private",
                        label="Private dashboard",
                    )
                ],
            }
        )
    )
    runtime = Runtime(
        card_store=cards,
        sources=SourceRegistry(),
        engine=InsightEngine(NoopJev()),
    )
    server = create_mcp(
        runtime,
        principal_resolver=lambda _ctx: principal_from_access_token(
            get_access_token(), required_scopes=["insights:read"]
        ),
        http_principal_resolver=lambda: principal_from_access_token(
            get_access_token(), required_scopes=["insights:read"]
        ),
        auth_settings=AuthSettings(
            issuer_url="https://issuer.integration.test",
            resource_server_url=None,
            required_scopes=["insights:read"],
            validate_token_resource=False,
        ),
        token_verifier=verifier,
    )
    server.settings.transport_security.allowed_hosts = ["localhost"]
    app = server.streamable_http_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            headers = {
                "authorization": f"Bearer {token()}",
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            }
            initialize = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "integration-test", "version": "1"},
                    },
                },
            )
            assert initialize.status_code == 200, initialize.text
            session_id = initialize.headers.get("mcp-session-id")
            assert session_id

            call_headers = {**headers, "mcp-session-id": session_id}
            listed = await client.post(
                "/mcp",
                headers=call_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "list_insight_cards", "arguments": {}},
                },
            )
            assert listed.status_code == 200, listed.text
            body = _payload(listed)
            result = body["result"]
            text_block = next(
                block["text"] for block in result["content"] if block["type"] == "text"
            )
            card_payload = json.loads(text_block)
            assert card_payload["count"] == 1
            assert [card["id"] for card in card_payload["cards"]] == ["card-a"]

            missing_scope = await client.post(
                "/mcp",
                headers={
                    **headers,
                    "authorization": f"Bearer {token(scopes='insights:run')}",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "integration-test", "version": "1"},
                    },
                },
            )
            assert missing_scope.status_code == 403

            webhook = await client.post(
                "/webhooks/evaluate",
                headers={"authorization": f"Bearer {token()}"},
                json={"card_id": "card-b", "idempotency_key": "tenant-boundary"},
            )
            assert webhook.status_code == 404
            assert "outside the authenticated principal tenant" in webhook.json()["error"]

    await oidc_client.aclose()


@pytest.mark.asyncio
async def test_oidc_request_tenant_selects_only_matching_preset_connection(
    monkeypatch, tmp_path
):
    oidc_client, verifier, token = _oidc_fixture()
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.delenv("PRESET_URL", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_TENANT_ID", raising=False)
    monkeypatch.delenv("SIGNALWEAVE_PRINCIPAL_ID", raising=False)
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "oidc")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_ISSUER_URL", "https://issuer.integration.test")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_AUDIENCE", "signalweave")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "cards.db"))
    tenants = {
        "tenant-a": {"dashboard_id": "dashboard-a", "jwt": "jwt-a"},
        "tenant-b": {"dashboard_id": "dashboard-b", "jwt": "jwt-b"},
    }
    provider_calls: list[tuple[str, str, str]] = []

    def provider_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.app.preset.test":
            credentials = json.loads(request.content)
            tenant = next(
                tenant
                for tenant in tenants
                if credentials
                == {"name": f"{tenant}-name", "secret": f"{tenant}-secret"}
            )
            provider_calls.append((tenant, request.method, request.url.path))
            return httpx.Response(
                200, json={"payload": {"access_token": tenants[tenant]["jwt"]}}
            )

        tenant = request.url.host.removesuffix(".preset.test")
        if tenant not in tenants:
            return httpx.Response(404, json={"message": "unknown workspace"})
        provider_calls.append((tenant, request.method, request.url.path))
        if request.headers.get("authorization") != f"Bearer {tenants[tenant]['jwt']}":
            return httpx.Response(401, json={"message": "wrong tenant token"})
        if request.url.path == "/api/v1/dashboard/":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "id": tenants[tenant]["dashboard_id"],
                            "dashboard_title": f"{tenant} dashboard",
                        }
                    ],
                    "count": 1,
                },
            )
        return httpx.Response(404, json={"message": "unexpected route"})

    connections = [
        HostedConnection(
            id=f"{tenant}-preset",
            tenant_id=tenant,
            provider=HostedProvider.PRESET,
            base_url=f"https://{tenant}.preset.test",
            external_workspace=f"{tenant}-workspace",
            credential_ref=f"vault://{tenant}/preset",
            auth_mode=HostedAuthMode.API_TOKEN,
        )
        for tenant in tenants
    ]
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
        http_transport=httpx.MockTransport(provider_handler),
    )
    assert runtime.principal is None
    assert runtime.sources.authorized_tenants == frozenset()
    server = create_mcp(
        runtime,
        principal_resolver=lambda _ctx: principal_from_access_token(
            get_access_token(), required_scopes=["insights:read"]
        ),
        http_principal_resolver=lambda: principal_from_access_token(
            get_access_token(), required_scopes=["insights:read"]
        ),
        auth_settings=AuthSettings(
            issuer_url="https://issuer.integration.test",
            resource_server_url=None,
            required_scopes=["insights:read"],
            validate_token_resource=False,
        ),
        token_verifier=verifier,
    )
    server.settings.transport_security.allowed_hosts = ["localhost"]
    app = server.streamable_http_app()

    async def list_resources_for(tenant: str, request_id: int) -> list[dict]:
        headers = {
            "authorization": f"Bearer {token(tenant=tenant)}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            initialize = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "preset-oidc-test", "version": "1"},
                    },
                },
            )
            assert initialize.status_code == 200, initialize.text
            session_id = initialize.headers["mcp-session-id"]
            listed = await client.post(
                "/mcp",
                headers={**headers, "mcp-session-id": session_id},
                json={
                    "jsonrpc": "2.0",
                    "id": request_id + 1,
                    "method": "tools/call",
                    "params": {"name": "list_resources", "arguments": {}},
                },
            )
            assert listed.status_code == 200, listed.text
            body = _payload(listed)
            return [
                json.loads(block["text"])
                for block in body["result"]["content"]
                if block["type"] == "text"
            ]

    async with app.router.lifespan_context(app):
        tenant_a_resources = await list_resources_for("tenant-a", 10)
        tenant_b_resources = await list_resources_for("tenant-b", 20)

    assert [item["contract"]["tenant_id"] for item in tenant_a_resources] == ["tenant-a"]
    assert [item["resource"] for item in tenant_a_resources] == ["dashboard:dashboard-a"]
    assert [item["contract"]["tenant_id"] for item in tenant_b_resources] == ["tenant-b"]
    assert [item["resource"] for item in tenant_b_resources] == ["dashboard:dashboard-b"]
    assert {call[0] for call in provider_calls} == {"tenant-a", "tenant-b"}
    assert set(provider_calls) == {
        ("tenant-a", "POST", "/v1/auth/"),
        ("tenant-a", "GET", "/api/v1/dashboard/"),
        ("tenant-b", "POST", "/v1/auth/"),
        ("tenant-b", "GET", "/api/v1/dashboard/"),
    }

    await oidc_client.aclose()


@pytest.mark.asyncio
async def test_oidc_http_uses_production_environment_preset_bootstrap(monkeypatch, tmp_path):
    oidc_client, verifier, token = _oidc_fixture()
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_API_KEY_FILE", raising=False)
    monkeypatch.setenv("PRESET_URL", "https://tenant-a.preset.test")
    monkeypatch.setenv("PRESET_TENANT_ID", "tenant-a")
    monkeypatch.setenv("PRESET_API_TOKEN_NAME", "tenant-a-name")
    monkeypatch.setenv("PRESET_API_TOKEN_SECRET", "tenant-a-secret")
    monkeypatch.delenv("PRESET_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("PRESET_API_BASE_URL", "https://api.app.preset.test")
    monkeypatch.setenv("SIGNALWEAVE_AUTH_MODE", "oidc")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_ISSUER_URL", "https://issuer.integration.test")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_AUDIENCE", "signalweave")
    monkeypatch.setenv("SIGNALWEAVE_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SIGNALWEAVE_STORE_PATH", str(tmp_path / "cards.db"))

    provider_calls: list[tuple[str, str, str]] = []

    def provider_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.app.preset.test":
            provider_calls.append(("tenant-a", request.method, request.url.path))
            assert json.loads(request.content) == {
                "name": "tenant-a-name",
                "secret": "tenant-a-secret",
            }
            return httpx.Response(200, json={"payload": {"access_token": "tenant-a-jwt"}})
        provider_calls.append((request.url.host.removesuffix(".preset.test"), request.method, request.url.path))
        assert request.url.host == "tenant-a.preset.test"
        assert request.headers["authorization"] == "Bearer tenant-a-jwt"
        if request.url.path == "/api/v1/dashboard/":
            return httpx.Response(
                200,
                json={
                    "result": [{"id": "dashboard-a", "dashboard_title": "Tenant A"}],
                    "count": 1,
                },
            )
        return httpx.Response(404, json={"message": "unexpected route"})

    runtime = build_runtime(http_transport=httpx.MockTransport(provider_handler))
    assert runtime.principal is None
    assert runtime.sources.authorized_tenants == frozenset({"tenant-a"})
    server = create_mcp(
        runtime,
        principal_resolver=lambda _ctx: principal_from_access_token(
            get_access_token(), required_scopes=["insights:read"]
        ),
        http_principal_resolver=lambda: principal_from_access_token(
            get_access_token(), required_scopes=["insights:read"]
        ),
        auth_settings=AuthSettings(
            issuer_url="https://issuer.integration.test",
            resource_server_url=None,
            required_scopes=["insights:read"],
            validate_token_resource=False,
        ),
        token_verifier=verifier,
    )
    server.settings.transport_security.allowed_hosts = ["localhost"]
    app = server.streamable_http_app()

    async def list_resources_for(tenant: str, request_id: int) -> list[dict]:
        headers = {
            "authorization": f"Bearer {token(tenant=tenant)}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            initialize = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "production-bootstrap-test", "version": "1"},
                    },
                },
            )
            assert initialize.status_code == 200, initialize.text
            listed = await client.post(
                "/mcp",
                headers={**headers, "mcp-session-id": initialize.headers["mcp-session-id"]},
                json={
                    "jsonrpc": "2.0",
                    "id": request_id + 1,
                    "method": "tools/call",
                    "params": {"name": "list_resources", "arguments": {}},
                },
            )
            assert listed.status_code == 200, listed.text
            body = _payload(listed)
            return [
                json.loads(block["text"])
                for block in body["result"]["content"]
                if block["type"] == "text"
            ]

    async with app.router.lifespan_context(app):
        tenant_a_resources = await list_resources_for("tenant-a", 30)
        calls_after_tenant_a = list(provider_calls)
        tenant_b_resources = await list_resources_for("tenant-b", 40)

    assert [item["resource"] for item in tenant_a_resources] == ["dashboard:dashboard-a"]
    assert tenant_b_resources == []
    assert provider_calls == calls_after_tenant_a
    assert set(provider_calls) == {
        ("tenant-a", "POST", "/v1/auth/"),
        ("tenant-a", "GET", "/api/v1/dashboard/"),
    }

    await oidc_client.aclose()

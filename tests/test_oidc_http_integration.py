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
from signalweave.mcp_server import create_mcp
from signalweave.models import InsightCard, InsightCardStatus, SourceRef
from signalweave.runtime import Runtime
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

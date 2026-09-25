import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from signalweave.auth import (
    BearerTokenMiddleware,
    OIDCJWTVerifier,
    OIDCSettings,
    principal_from_access_token,
)
from signalweave.cli import _is_loopback_host


async def ok(request):
    return JSONResponse({"ok": True})


def make_app():
    app = Starlette(routes=[Route("/healthz", ok), Route("/private", ok)])
    app.add_middleware(BearerTokenMiddleware, token="local-test-token")
    return app


def test_insecure_http_is_only_allowed_on_loopback_hosts():
    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("::1") is True
    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("0.0.0.0") is False
    assert _is_loopback_host("10.0.0.4") is False


@pytest.mark.asyncio
async def test_bearer_token_protects_http_surface_but_keeps_health_public():
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/private")).status_code == 401
        response = await client.get(
            "/private", headers={"authorization": "Bearer local-test-token"}
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def oidc_fixture():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
    public_jwk = {**json.loads(public_jwk), "kid": "test-key", "alg": "RS256"}
    settings = OIDCSettings(
        issuer_url="https://issuer.example.test",
        audience="signalweave",
        tenant_claim="tenant_id",
        jwks_ttl_seconds=300,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={"jwks_uri": "https://issuer.example.test/keys"},
            )
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    verifier = OIDCJWTVerifier(settings, http_client=client)

    def token(**overrides):
        claims = {
            "iss": settings.issuer_url,
            "aud": settings.audience,
            "sub": "user-123",
            "tenant_id": "tenant-a",
            "scope": "insights:read insights:run",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})

    return client, verifier, token


@pytest.mark.asyncio
async def test_oidc_verifier_validates_signature_issuer_audience_and_refreshes_jwks():
    client, verifier, token = oidc_fixture()
    try:
        access_token = await verifier.verify_token(token())
        assert access_token is not None
        assert access_token.subject == "user-123"
        assert access_token.scopes == ["insights:read", "insights:run"]
        principal = principal_from_access_token(access_token)
        assert principal.principal_id == "user-123"
        assert principal.tenant_id == "tenant-a"
        assert principal.authorization_source == "oidc"
        with pytest.raises(RuntimeError, match="missing required scopes"):
            principal_from_access_token(access_token, required_scopes=["admin"])
        assert await verifier.verify_token(token(aud="other-service")) is None
        assert await verifier.verify_token(token(iss="https://other-issuer.example.test")) is None
        assert await verifier.verify_token(token(exp=int(time.time()) - 1)) is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_oidc_verifier_and_principal_fail_closed_without_tenant_claim():
    client, verifier, token = oidc_fixture()
    try:
        access_token = await verifier.verify_token(token(tenant_id=None))
        assert access_token is not None
        with pytest.raises(RuntimeError, match="missing required tenant claim"):
            principal_from_access_token(access_token)
        assert await verifier.verify_token("not-a-jwt") is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_native_mcp_auth_keeps_health_public_and_mcp_protected():
    class RejectAllVerifier:
        async def verify_token(self, token):
            del token
            return None

    server = FastMCP(
        "auth-test",
        auth=AuthSettings(
            issuer_url="https://issuer.example.test",
            resource_server_url=None,
            required_scopes=[],
            validate_token_resource=False,
        ),
        token_verifier=RejectAllVerifier(),
    )

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_request):
        return JSONResponse({"status": "ok"})

    app = server.streamable_http_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        health = await client.get("/healthz")
        protected = await client.post("/mcp", json={})

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert protected.status_code == 401


def test_oidc_settings_require_tls_and_explicit_identity_configuration(monkeypatch):
    monkeypatch.setenv("SIGNALWEAVE_OIDC_ISSUER_URL", "http://issuer.example.test")
    monkeypatch.setenv("SIGNALWEAVE_OIDC_AUDIENCE", "signalweave")
    with pytest.raises(RuntimeError, match="must use https"):
        OIDCSettings.from_env()

    monkeypatch.setenv("SIGNALWEAVE_ALLOW_INSECURE_OIDC", "1")
    settings = OIDCSettings.from_env()
    assert settings.issuer_url == "http://issuer.example.test"


@pytest.mark.asyncio
async def test_oidc_verifier_preserves_a_trailing_slash_issuer():
    client, verifier, token = oidc_fixture()
    verifier.settings = OIDCSettings(
        issuer_url="https://issuer.example.test/",
        audience="signalweave",
        tenant_claim="tenant_id",
        jwks_ttl_seconds=300,
    )
    try:
        access_token = await verifier.verify_token(token(iss="https://issuer.example.test/"))
        assert access_token is not None
    finally:
        await client.aclose()

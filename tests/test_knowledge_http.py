"""Actual MCP HTTP/JWT middleware with a synthetic signed issuer, not customer SSO."""

import json
import time

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings

from signalweave.auth import OIDCJWTVerifier, OIDCSettings, principal_from_access_token
from signalweave.knowledge import KnowledgeService
from signalweave.knowledge_store import SQLiteKnowledgeStore
from signalweave.mcp_server import create_mcp
from signalweave.sources import SourceRegistry
from tests.test_knowledge_mcp import DomainAssets, content
from tests.test_local_investigation import make_runtime
from tests.test_oidc_http_integration import _oidc_fixture, _payload


def _signed_context_oidc_fixture():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update(kid="context-http-key", alg="RS256")
    settings = OIDCSettings(
        issuer_url="https://context-issuer.integration.test",
        audience="signalweave",
        tenant_claim="tenant_id",
        jwks_ttl_seconds=300,
    )

    def handler(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"jwks_uri": "https://context-issuer.integration.test/keys"})
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [public_jwk]})
        return httpx.Response(404)

    issuer_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    verifier = OIDCJWTVerifier(settings, http_client=issuer_client)

    def token(*, tenant, subject, scopes):
        now = int(time.time())
        claims = {
            "iss": settings.issuer_url,
            "aud": settings.audience,
            "sub": subject,
            "tenant_id": tenant,
            "scope": scopes,
            "iat": now,
            "exp": now + 300,
        }
        return jwt.encode(
            claims,
            private_key,
            algorithm="RS256",
            headers={"kid": "context-http-key"},
        )

    return issuer_client, verifier, token


async def test_signed_http_identity_enforces_context_curation_and_isolation(tmp_path):
    issuer_client, verifier, token = _oidc_fixture()
    runtime, _, judger = make_runtime(tmp_path)
    runtime.sources = SourceRegistry([DomainAssets()])
    runtime.knowledge = KnowledgeService(SQLiteKnowledgeStore(tmp_path / "shared.db"), runtime.sources)
    server = create_mcp(
        runtime, require_principal=True,
        principal_resolver=lambda _ctx: principal_from_access_token(get_access_token()),
        auth_settings=AuthSettings(
            issuer_url="https://issuer.integration.test", required_scopes=["insights:read"],
            resource_server_url=None,
            validate_token_resource=False,
        ), token_verifier=verifier,
    )
    server.settings.transport_security.allowed_hosts = ["localhost"]
    app = server.streamable_http_app()
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
                assert (await client.post("/mcp", json={})).status_code == 401

                async def call(name, arguments, *, scopes, tenant="tenant-a"):
                    headers = {
                        "authorization": "Bearer " + token(tenant=tenant, scopes=scopes),
                        "accept": "application/json, text/event-stream",
                    }
                    initialized = await client.post("/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                            "protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "context-http-proof", "version": "1"},
                        },
                    })
                    assert initialized.status_code == 200, initialized.text
                    headers["mcp-session-id"] = initialized.headers["mcp-session-id"]
                    await client.post("/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "method": "notifications/initialized",
                    })
                    response = await client.post("/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    })
                    assert response.status_code == 200, response.text
                    return _payload(response)["result"]

                args = {"content": content("tenant-a")}
                rejected = await call("save_domain_context", args, scopes="insights:read")
                assert rejected["isError"] and "knowledge:write" in str(rejected)
                rejected = await call("save_domain_context", args, scopes="insights:read knowledge:write")
                assert rejected["isError"] and "knowledge:share" in str(rejected)
                writer = "insights:read knowledge:write knowledge:share"
                saved = (await call("save_domain_context", args, scopes=writer))["structuredContent"]
                assert saved["owner_id"] == "tenant-a-user" and saved["tenant_id"] == "tenant-a"
                review = {"entry_id": saved["id"], "expected_revision": 1,
                          "action": "approve", "reason": "Synthetic owner confirmation"}
                rejected = await call("review_domain_context", review, scopes=writer)
                assert rejected["isError"] and "knowledge:review" in str(rejected)
                approved = (await call("review_domain_context", review, scopes=writer + " knowledge:review"))["structuredContent"]
                assert approved["status"] == "reviewed" and approved["revision"] == 2
                same = (await call("retrieve_domain_context", {"query": "net sales"}, scopes="insights:read"))["structuredContent"]
                foreign = (await call("retrieve_domain_context", {"query": "net sales"}, scopes="insights:read", tenant="tenant-b"))["structuredContent"]
                assert [entry["id"] for entry in same["entries"]] == [saved["id"]]
                assert foreign["entries"] == [] and "Net sales" not in str(foreign)
                assert judger.states == []
    finally:
        await issuer_client.aclose()


async def test_signed_http_context_binding_is_owner_scoped_tenant_isolated_and_body_free(tmp_path):
    issuer_client, verifier, token = _signed_context_oidc_fixture()
    runtime, _, judger = make_runtime(tmp_path)
    assets = DomainAssets()
    assets.binding_namespace = "workspace-a"
    runtime.sources = SourceRegistry([assets])
    runtime.knowledge = KnowledgeService(SQLiteKnowledgeStore(tmp_path / "shared.db"), runtime.sources)
    card = runtime.card_store.get_card("repeat").model_copy(update={
        "principal_id": "tenant-a-owner",
        "principal_tenant": "tenant-a",
    })
    runtime.card_store.save_card(card)
    server = create_mcp(
        runtime, require_principal=True,
        principal_resolver=lambda _ctx: principal_from_access_token(get_access_token()),
        auth_settings=AuthSettings(
            issuer_url="https://context-issuer.integration.test", required_scopes=["insights:read"],
            resource_server_url=None, validate_token_resource=False,
        ), token_verifier=verifier,
    )
    server.settings.transport_security.allowed_hosts = ["localhost"]
    app = server.streamable_http_app()
    owner_scopes = "insights:read knowledge:write knowledge:share knowledge:review"
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                async def call(name, arguments, *, tenant="tenant-a", subject="tenant-a-owner", scopes="insights:read"):
                    headers = {
                        "authorization": "Bearer " + token(tenant=tenant, subject=subject, scopes=scopes),
                        "accept": "application/json, text/event-stream",
                    }
                    initialized = await client.post("/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                            "protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "context-binding-proof", "version": "1"},
                        },
                    })
                    assert initialized.status_code == 200, initialized.text
                    headers["mcp-session-id"] = initialized.headers["mcp-session-id"]
                    await client.post("/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "method": "notifications/initialized",
                    })
                    response = await client.post("/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    })
                    assert response.status_code == 200, response.text
                    return _payload(response)["result"]

                note_body = "PRIVATE_CONTEXT_BODY_CANARY: net sales excludes refunds."
                entry_content = content("tenant-a")
                entry_content["body"] = note_body
                saved = (await call(
                    "save_domain_context", {"content": entry_content}, scopes=owner_scopes,
                ))["structuredContent"]
                reviewed = (await call("review_domain_context", {
                    "entry_id": saved["id"], "expected_revision": 1,
                    "action": "approve", "reason": "Owner confirmed the definition.",
                }, scopes=owner_scopes))["structuredContent"]
                assert reviewed["status"] == "reviewed" and reviewed["revision"] == 2

                denied_scope = await call("bind_insight_context", {
                    "card_id": "repeat", "expected_card_version": 1, "pins": [],
                    "reason": "Missing write authority.",
                })
                assert denied_scope["isError"] and "knowledge:write" in str(denied_scope)

                bound = await call("bind_insight_context", {
                    "card_id": "repeat", "expected_card_version": 1,
                    "pins": [{
                        "entry_id": saved["id"], "revision": reviewed["revision"],
                        "required_for_action": True,
                    }],
                    "reason": "Use the owner-reviewed sales definition.",
                }, scopes=owner_scopes)
                assert bound["structuredContent"]["status"] == "draft"
                assert bound["structuredContent"]["version"] == 2

                non_owner = await call("bind_insight_context", {
                    "card_id": "repeat", "expected_card_version": 2, "pins": [],
                    "reason": "Attempted rebind by another tenant member.",
                }, subject="tenant-a-reader", scopes=owner_scopes)
                assert non_owner["isError"] and "only the card owner" in str(non_owner)

                checked = await call("inspect_insight_context", {"card_id": "repeat"})
                assert checked["structuredContent"]["entries"] == [{
                    "entry_id": saved["id"], "revision": 2,
                    "required_for_action": True, "status": "current",
                }]
                card_result = await call("get_insight_card", {"card_id": "repeat"})
                assert "context_bindings" not in runtime.card_store.get_card("repeat").execution_payload()
                assert note_body not in str(bound) + str(checked) + str(card_result)

                other_tenant = await call(
                    "retrieve_domain_context", {"query": "net sales", "include_drafts": True},
                    tenant="tenant-b", subject="tenant-b-owner",
                )
                assert other_tenant["structuredContent"]["entries"] == []
                foreign_card = await call(
                    "inspect_insight_context", {"card_id": "repeat"},
                    tenant="tenant-b", subject="tenant-b-owner",
                )
                assert foreign_card["isError"] and "current tenant" in str(foreign_card)
                assert note_body not in str(other_tenant) + str(foreign_card)
                assert runtime.card_store.get_card("repeat").version == 2
                assert judger.states == []  # binding and inspection never invoke Jev
    finally:
        await issuer_client.aclose()

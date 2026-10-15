"""Actual MCP HTTP/JWT middleware with a synthetic signed issuer, not customer SSO."""

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings

from signalweave.auth import principal_from_access_token
from signalweave.knowledge import KnowledgeService
from signalweave.knowledge_store import SQLiteKnowledgeStore
from signalweave.mcp_server import create_mcp
from signalweave.sources import SourceRegistry
from tests.test_knowledge_mcp import DomainAssets, content
from tests.test_local_investigation import make_runtime
from tests.test_oidc_http_integration import _oidc_fixture, _payload


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

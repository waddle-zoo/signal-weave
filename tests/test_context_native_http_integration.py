"""Opt-in frozen HTTP/JWT context lifecycle, not customer SSO or business lift.

Starts only test-owned loopback processes. The issuer is synthetic; Superset
metadata authorization and native MCP/storage/authentication are real. No model
inference or analytical chart query is authorized.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from scripts.binary_provenance import verify_binary


def local_fixture_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("native HTTP check requires a loopback Superset fixture URL")
    return value.rstrip("/")


@pytest.mark.parametrize("url", ["https://bi.example.com", "http://127.0.0.1.evil.test",
                                 "https://admin:secret@localhost", "http://localhost/?token=secret",
                                 "http://localhost/#secret", "http://localhost/remote-proxy", "file:///tmp"])
def test_http_proof_rejects_nonlocal_or_credential_bearing_fixture_urls(url):
    with pytest.raises(ValueError, match="loopback"):
        local_fixture_url(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:18089/", "https://localhost:18089", "http://[::1]:18089"])
def test_http_proof_allows_explicit_loopback_fixtures(url):
    assert local_fixture_url(url) == url.rstrip("/")


@asynccontextmanager
async def signed_issuer():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="native-http-test", alg="RS256")
    requests = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{listener.getsockname()[1]}"

    async def respond(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/.well-known/openid-configuration":
            return JSONResponse({"jwks_uri": base + "/keys"})
        if request.url.path == "/keys":
            return JSONResponse({"keys": [jwk]})
        return JSONResponse({"error": "provider calls forbidden in this check"}, status_code=503)

    app = Starlette(routes=[Route("/{path:path}", respond, methods=["GET", "POST"])])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise AssertionError("test issuer exited before startup")
                await asyncio.sleep(0.02)

        def token(subject="curator", tenant="context-http-a", scopes="insights:read", **overrides):
            now = int(time.time())
            return jwt.encode({
                "iss": base, "aud": "signalweave", "sub": subject,
                "tenant_id": tenant, "scope": scopes, "iat": now, "exp": now + 600,
                **overrides,
            }, key, algorithm="RS256", headers={"kid": jwk["kid"]})

        yield base, token, requests
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 10)
        finally:
            listener.close()


@asynccontextmanager
async def native_http(binary, home, env, log_path):
    # The CLI accepts a port, not an inherited listening socket. Fail closed if
    # another process takes this ephemeral port; never terminate by port/name.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with log_path.open("a") as log:
        log_path.chmod(0o600)
        log_start = log.tell()
        process = await asyncio.create_subprocess_exec(
            str(binary), "serve", "--home", str(home), "--transport", "streamable-http",
            "--host", "127.0.0.1", "--port", str(port),
            env=env, cwd=home.parent, stdout=log, stderr=log,
        )
        try:
            async with asyncio.timeout(45), httpx.AsyncClient(trust_env=False) as client:
                while True:
                    assert process.returncode is None, "native HTTP process exited; inspect private test log"
                    # A healthy unrelated listener is not proof that our child
                    # bound this port. Observe this launch's bind before using it.
                    if f"Uvicorn running on {base}" not in log_path.read_text()[log_start:]:
                        await asyncio.sleep(0.05)
                        continue
                    try:
                        ready = await client.get(base + "/healthz", timeout=0.5)
                        if ready.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.05)
            yield base
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 10)
                except TimeoutError:
                    process.kill()
                    await process.wait()


@asynccontextmanager
async def remote_session(base, token):
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token}, trust_env=False, timeout=20,
    ) as client:
        async with streamable_http_client(base + "/mcp", http_client=client) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=timedelta(seconds=20)) as session:
                await session.initialize()
                yield session


async def call(session, name, arguments):
    result = await session.call_tool(name, arguments)
    return result, result.structuredContent or (
        json.loads(result.content[0].text) if not result.isError else None
    )


@pytest.mark.skipif(
    os.getenv("RUN_CONTEXT_HTTP_INTEGRATION") != "1",
    reason="requires the current native binary and an explicit local Superset fixture",
)
async def test_current_native_http_context_reuse_roles_and_restart(tmp_path, record_property):
    async with asyncio.timeout(240):
        await exercise_native_http(tmp_path, record_property)


async def exercise_native_http(tmp_path, record_property):
    # Validate before even running setup: ambient credentials must never be sent
    # to a remote URL by an opt-in local protocol check.
    superset_url = local_fixture_url(os.getenv("SUPERSET_URL", "http://127.0.0.1:18089"))
    binary = Path(os.environ["SIGNALWEAVE_BINARY"]).resolve()
    identity = verify_binary(binary)
    assert identity["frozen"]
    home = tmp_path / "native-home"
    password = tmp_path / "superset-password"
    password.write_text(os.getenv("SUPERSET_PASSWORD", "admin"))
    password.chmod(0o600)
    startup_key = tmp_path / "synthetic-startup-key"
    startup_key.write_text("synthetic-context-http-no-inference")
    startup_key.chmod(0o600)
    env = {name: value for name, value in os.environ.items()
           if name in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    env["SIGNALWEAVE_KNOWLEDGE_ENABLED"] = "1"
    setup = await asyncio.create_subprocess_exec(
        str(binary), "setup", "--home", str(home), "--non-interactive",
        "--key-file", str(startup_key),
        "--source", "superset", "--url", superset_url,
        "--username", os.getenv("SUPERSET_USERNAME", "admin"), "--secret-file", str(password),
        "--tenant", "context-http-a", "--principal", "local-setup-identity",
        "--agent", "codex", "--no-register-agent",
        env=env, cwd=tmp_path, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(setup.wait(), 60)
    finally:
        if setup.returncode is None:
            setup.kill()
            await setup.wait()
    assert setup.returncode == 0, "isolated native setup failed"
    log_path = tmp_path / "native-http.log"
    async with signed_issuer() as (issuer, token, requests):
        env.update(
            SIGNALWEAVE_AUTH_MODE="oidc", SIGNALWEAVE_ALLOW_INSECURE_OIDC="1",
            SIGNALWEAVE_OIDC_ISSUER_URL=issuer, SIGNALWEAVE_OIDC_AUDIENCE="signalweave",
            SIGNALWEAVE_OIDC_REQUIRED_SCOPES="insights:read",
            TYPESAFE_BASE_URL=issuer + "/forbidden-provider", TYPESAFE_MAX_RETRIES="0",
        )
        def curator():
            # Mint at use, including after restart. Host suspension or slow
            # native extraction must not turn a valid-identity protocol check
            # into accidental use of an expired fixture token. Explicit expiry
            # rejection remains covered by the invalid-credential cases below.
            return token(scopes="insights:read knowledge:write knowledge:share knowledge:review")
        content = {
            "domain": "native-http-proof", "title": "Shared protocol context",
            "body": "SYNTHETIC_HTTP_CONTEXT: check measurement periods separately, not a metric definition.",
            "kind": "observation", "provenance": ["Synthetic HTTP protocol fixture"],
            "sources": [{"key": "fixture", "adapter": "superset", "resource": "chart:1", "label": "Fixture chart"}],
            "review_after": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        }
        async with native_http(binary, home, env, log_path) as base:
            async with httpx.AsyncClient(trust_env=False) as client:
                for credential in (None, "invalid", token(aud="wrong-audience"), token(exp=int(time.time()) - 60)):
                    headers = {"Authorization": "Bearer " + credential} if credential else {}
                    response = await client.post(base + "/mcp", headers=headers, json={})
                    assert response.status_code == 401
                    assert content["body"] not in response.text
            async with remote_session(base, curator()) as session:
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert "save_domain_context" in tools and len(tools) == 17
                result, saved = await call(session, "save_domain_context", {"content": content})
                assert not result.isError
                assert saved["actor"] == saved["owner_id"] == "curator"
                assert saved["tenant_id"] == "context-http-a"
                result, reviewed = await call(session, "review_domain_context", {
                    "entry_id": saved["id"], "expected_revision": 1, "action": "approve",
                    "reason": "Synthetic review, not business certification.",
                })
                assert not result.isError and reviewed["revision"] == 2
            # A different client/subject reuses reviewed memory, not creator identity.
            async with remote_session(base, token(subject="reporting-agent")) as session:
                result, packet = await call(session, "retrieve_domain_context", {"query": "protocol context"})
                assert not result.isError and [entry["id"] for entry in packet["entries"]] == [saved["id"]]
                denied, _ = await call(session, "save_domain_context", {"content": content})
                assert denied.isError and "knowledge:write" in str(denied.content)
            async with remote_session(base, token(subject="foreign-agent", tenant="context-http-b")) as session:
                result, foreign = await call(session, "retrieve_domain_context", {"query": "protocol context"})
                assert not result.isError and foreign["entries"] == []
                assert content["body"] not in json.dumps(foreign)
        async with native_http(binary, home, env, log_path) as base:
            async with remote_session(base, token(subject="reporting-agent")) as session:
                result, reopened = await call(session, "retrieve_domain_context", {"query": "protocol context"})
                assert not result.isError and [entry["revision"] for entry in reopened["entries"]] == [2]
                assert reopened["entries"][0]["id"] == saved["id"]
            async with remote_session(base, curator()) as session:
                edited_content = {
                    **content, "body": "SYNTHETIC_HTTP_REVISION: the owner must review this changed note.",
                    "review_after": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                }
                result, edited = await call(session, "save_domain_context", {
                    "entry_id": saved["id"], "expected_revision": 2, "content": edited_content,
                })
                assert not result.isError and edited["status"] == "draft" and edited["revision"] == 3
            async with remote_session(base, token(subject="reporting-agent")) as session:
                result, current = await call(session, "retrieve_domain_context", {"query": "protocol context"})
                assert not result.isError and current["entries"] == []
                result, due = await call(session, "retrieve_domain_context", {
                    "review_due_only": True, "include_drafts": True,
                })
                assert not result.isError and [entry["id"] for entry in due["entries"]] == [saved["id"]]
                assert due["freshness"] == {saved["id"]: "review_due"}
                assert due["entries"][0]["revision"] == 3
                assert due["entries"][0]["content"]["body"] == edited_content["body"]
        assert ("GET", "/.well-known/openid-configuration") in requests
        assert ("GET", "/keys") in requests
        assert all(method == "GET" and path in {"/.well-known/openid-configuration", "/keys"}
                   for method, path in requests), "unexpected inference/issuer request"
    logs = log_path.read_text()
    assert f"GET {superset_url}/api/v1/" in logs
    assert "POST https://api.typesafe.ai/" not in logs
    for field in ("git_commit", "source_sha256", "binary_sha256"):
        record_property("native_" + field, identity[field])
    record_property("provider_attempts", 0)
    record_property("transport", "native-http-synthetic-oidc-local-superset-metadata")

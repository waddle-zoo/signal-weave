"""Bounded transport for evaluation-only installed-binary trials.

This module deliberately owns process setup and loopback plumbing only.  It does
not contain a trial agent loop, private labels, or a fixture-backed source.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from evaluations import bootstrap_agent_trial
from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter, RequestBudget
from signalweave.models import SourceRef

MCP_INITIALIZE_TIMEOUT_SECONDS = 30


class InstalledServer:
    """Small FastMCP-compatible facade over an initialized binary ClientSession."""

    def __init__(self, session: ClientSession, instructions: str | None, audit: Audit):
        self._session = session
        self.instructions = instructions or ""
        self._audit = audit

    async def list_tools(self) -> list[types.Tool]:
        return list((await self._session.list_tools()).tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> tuple[list[Any], Any]:
        result = await self._session.call_tool(name, args)
        structured = result.structuredContent
        if structured is None:
            for block in result.content:
                text = getattr(block, "text", None)
                if text is None:
                    continue
                try:
                    structured = json.loads(text)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                break
        if result.isError:
            details = self._audit.redact(
                [
                    bootstrap_agent_trial.json_value(block.model_dump(mode="json"))
                    if hasattr(block, "model_dump")
                    else str(block)
                    for block in result.content
                ]
            )
            message = json.dumps(details, ensure_ascii=False, allow_nan=False)[:2000]
            raise RuntimeError(f"installed MCP tool returned an error: {message}")
        return result.content, structured


async def _initialize_mcp_session(session: ClientSession) -> Any:
    """Bound only the protocol handshake; ordinary tool calls keep their contract."""
    try:
        async with asyncio.timeout(MCP_INITIALIZE_TIMEOUT_SECONDS):
            return await session.initialize()
    except TimeoutError as error:
        raise RuntimeError(
            f"installed MCP initialize timed out after {MCP_INITIALIZE_TIMEOUT_SECONDS:g} seconds"
        ) from error


def _private_file(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)


def _private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    path.chmod(0o700)


def _minimal_environment(home: Path, *, jev_url: str | None = None) -> dict[str, str]:
    environment = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(home / "tmp"),
        "TYPESAFE_MAX_RETRIES": "0",
    }
    if jev_url:
        environment["TYPESAFE_BASE_URL"] = jev_url
    return environment


class _SourceSession:
    def __init__(self, adapter: PublicSourceAdapter, audit: Audit, tenant: str):
        self.adapter, self.audit, self.tenant = adapter, audit, tenant

    async def read_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ref = arguments.get("ref")
        if not isinstance(ref, str) or "|" not in ref:
            raise ValueError("invalid source reference")
        adapter, resource = ref.split("|", 1)
        snapshot = await self.adapter.inspect(
            SourceRef(
                key=resource,
                adapter=adapter,
                resource=resource,
                label=resource,
            )
        )
        return snapshot.model_dump(mode="json")


@asynccontextmanager
async def _source_server(session: _SourceSession) -> AsyncIterator[str]:
    server = Server("company-mcp")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="read_snapshot",
                description="Read the current approved source snapshot.",
                inputSchema={
                    "type": "object",
                    "properties": {"ref": {"type": "string"}},
                    "required": ["ref"],
                    "additionalProperties": False,
                },
            )
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if name != "read_snapshot":
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="unknown source tool")],
                isError=True,
            )
        try:
            payload = await session.read_snapshot(arguments)
        except Exception:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="source read failed")],
                isError=True,
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload))],
            structuredContent=payload,
        )

    manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)
    route = "/" + secrets.token_urlsafe(24)

    class Handler:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    app = Starlette(routes=[Route(route, endpoint=Handler())], lifespan=lifespan)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    uvicorn_server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    task = asyncio.create_task(uvicorn_server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not uvicorn_server.started:
                if task.done():
                    await task
                    raise RuntimeError("source MCP failed to start")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}{route}"
    finally:
        uvicorn_server.should_exit = True
        await task
        sock.close()


def _manifest(public: dict[str, Any], source_url: str) -> dict[str, Any]:
    tenant = public["scenario_id"]
    resources = []
    for item in public["catalog"]:
        descriptor = dict(item)
        contract = dict(descriptor.get("contract") or {})
        contract["tenant_id"] = tenant
        descriptor["contract"] = contract
        resource = descriptor["resource"]
        resources.append(
            {
                "descriptor": descriptor,
                "source_key": resource,
                "tool": "read_snapshot",
                "arguments": {"ref": f"company_mcp|{resource}"},
            }
        )
    return {
        "version": 1,
        "connections": [
            {
                "name": "company_mcp",
                "tenant_id": tenant,
                "read_only": True,
                "transport": {"type": "streamable-http", "url": source_url},
                "resources": resources,
            }
        ],
    }


async def _run_setup(
    binary: Path, root: Path, home: Path, key: Path, manifest: Path, tenant: str
) -> None:
    command = [
        str(binary),
        "setup",
        "--non-interactive",
        "--home",
        str(home),
        "--key-file",
        str(key),
        "--source",
        "mcp",
        "--manifest",
        str(manifest),
        "--tenant",
        tenant,
        "--principal",
        "installed-trial",
        "--agent",
        "codex",
    ]
    completed = await asyncio.to_thread(
        subprocess.run,
        command,
        cwd=str(root),
        env=_minimal_environment(home),
        text=True,
        capture_output=True,
        timeout=90,
    )
    if completed.returncode:
        raise RuntimeError("installed binary setup failed")


async def _jev_proxy_handler(request: Request) -> Response:
    proxy: _JevProxy = request.app.state.proxy
    if request.method != "POST" or request.path_params.get("route") != proxy.route:
        return JSONResponse({"error": "not_found"}, status_code=404)
    body = await request.body()
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    model = payload.get("model") or "jev-latest"
    state, questions = payload.get("state"), payload.get("questions")
    try:
        proxy.budget.claim()
    except bootstrap_agent_trial.BudgetExceeded:
        proxy.audit.emit(
            "api.rejected",
            provider="jev",
            transport="http_proxy",
            model=model,
            reason="global_api_request_budget_exhausted",
        )
        return JSONResponse({"error": "budget_exhausted"}, status_code=429)
    request_id = proxy.budget.used
    proxy.audit.emit(
        "api.request",
        provider="jev",
        request_id=request_id,
        transport="http_proxy",
        model=model,
        state=state,
        questions=questions,
    )
    started = time.perf_counter()
    try:
        authorization = request.headers.get("authorization")
        headers = {"content-type": "application/json", "accept": "application/json"}
        if authorization:
            headers["authorization"] = authorization
        async with httpx.AsyncClient(
            base_url="https://api.typesafe.ai",
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post("/v1/systemone", content=body, headers=headers)
        if response.is_redirect:
            raise RuntimeError("upstream_redirect_rejected")
        response_payload: Any = None
        try:
            response_payload = response.json()
        except ValueError:
            pass
        usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
        if response.is_success:
            resolved_model = (
                response_payload.get("model", model)
                if isinstance(response_payload, dict)
                else model
            )
            proxy.audit.emit(
                "api.response",
                provider="jev",
                request_id=request_id,
                model=resolved_model,
                response=response_payload,
                usage=usage,
                seconds=time.perf_counter() - started,
            )
        else:
            proxy.audit.emit(
                "api.error",
                provider="jev",
                request_id=request_id,
                model=model,
                error_type=f"HTTP_{response.status_code}",
                usage=usage,
                usage_known=False,
                seconds=time.perf_counter() - started,
            )
        return Response(
            response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json"),
        )
    except Exception as error:
        proxy.audit.emit(
            "api.error",
            provider="jev",
            request_id=request_id,
            model=model,
            error_type=type(error).__name__,
            usage_known=False,
            seconds=time.perf_counter() - started,
        )
        return JSONResponse({"error": "upstream_request_failed"}, status_code=502)


class _JevProxy:
    def __init__(self, audit: Audit, budget: RequestBudget):
        self.audit, self.budget = audit, budget
        self.route = secrets.token_urlsafe(24)


@asynccontextmanager
async def _jev_proxy(audit: Audit, budget: RequestBudget) -> AsyncIterator[str]:
    proxy = _JevProxy(audit, budget)
    app = Starlette(routes=[Route("/{route}/v1/systemone", _jev_proxy_handler, methods=["POST"])])
    app.state.proxy = proxy
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Jev proxy failed to start")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}/{proxy.route}"
    finally:
        server.should_exit = True
        await task
        sock.close()


@asynccontextmanager
async def installed_server(
    *,
    binary: Path,
    key_file: Path,
    public: dict[str, Any],
    adapter: PublicSourceAdapter,
    audit: Audit,
    budget: RequestBudget,
    work: Path,
) -> AsyncIterator[InstalledServer]:
    """Set up and serve one installed trial binary in an isolated private home."""
    work = work.resolve()
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="installed-trial-", dir=work) as temporary:
        root = Path(temporary).resolve()
        home, tmp = root / "home", root / "home" / "tmp"
        _private_dir(home)
        _private_dir(tmp)
        private_key = root / "typesafe.key"
        _private_file(private_key, key_file.read_text(encoding="utf-8"))
        audit.secrets = tuple(dict.fromkeys((*audit.secrets, private_key.read_text().strip())))
        source_session = _SourceSession(adapter, audit, public["scenario_id"])
        async with _source_server(source_session) as source_url:
            manifest = root / "company-mcp.json"
            _private_file(manifest, json.dumps(_manifest(public, source_url), allow_nan=False))
            await _run_setup(
                binary.resolve(), root, home, private_key, manifest, public["scenario_id"]
            )
            async with _jev_proxy(audit, budget) as jev_url:
                environment = _minimal_environment(home, jev_url=jev_url)
                parameters = StdioServerParameters(
                    command=str(binary.resolve()),
                    args=["serve", "--home", str(home)],
                    cwd=str(root),
                    env=environment,
                )
                with open(os.devnull, "w", encoding="utf-8") as errlog:
                    async with stdio_client(parameters, errlog=errlog) as (read, write):
                        async with ClientSession(read, write) as session:
                            initialized = await _initialize_mcp_session(session)
                            instructions = getattr(initialized, "instructions", None)
                            yield InstalledServer(session, instructions, audit)

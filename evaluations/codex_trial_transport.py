"""Evaluation-only Codex CLI transport using saved login and a scoped local MCP.

No OAuth extraction, direct API key, production agent loop, or fixture file access.
The parent retains private labels, credentials and mutable trial state.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import tempfile
import time
from contextlib import asynccontextmanager

import uvicorn
from jsonschema import validate
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route

DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "plugins", "hooks", "multi_agent",
    "browser_use", "computer_use", "image_generation", "view_image",
    "memories", "skill_search", "workspace_dependencies", "shell_snapshot",
    "code_mode", "sleep_tool", "goals",
)


def codex_command(cwd: str, url: str, *, model: str, effort: str) -> list[str]:
    command = ["codex", "exec", "--ignore-user-config", "--ephemeral", "--json",
               "--skip-git-repo-check", "--sandbox", "read-only", "--cd", cwd,
               "--model", model, "-c", f'model_reasoning_effort="{effort}"',
               "-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0",
               "-c", "features.skip_host_skill_discovery=true",
               "-c", "features.code_mode_host=true",
               "-c", "memories.use_memories=false", "-c", "memories.generate_memories=false",
               "-c", "mcp_servers={}",
               "-c", f'mcp_servers.trial.url={json.dumps(url)}',
               "-c", "mcp_servers.trial.required=true",
               "-c", 'mcp_servers.trial.default_tools_approval_mode="approve"',
               "-c", "mcp_servers.trial.tool_timeout_sec=120",
               "-c", 'approval_policy="never"']
    for feature in DISABLED_FEATURES:
        command.extend(["--disable", feature])
    return command + ["-"]


def child_environment() -> dict[str, str]:
    # Do not pass Jev, API, gateway or source secrets into the agent process.
    return {key: value for key, value in os.environ.items()
            if key in {"HOME", "PATH", "TMPDIR", "CODEX_HOME", "LANG", "LC_ALL",
                       "SSL_CERT_FILE", "SSL_CERT_DIR"}}


class TrialMCP:
    def __init__(self, session, audit, specs: list[dict], max_calls: int):
        self.session, self.audit = session, audit
        self.specs = {spec["name"]: spec for spec in specs}
        self.max_calls = max_calls
        self.calls = 0
        self.exhausted = False
        self.lock = asyncio.Lock()
        self.server = Server("signalweave-trial")

        @self.server.list_tools()
        async def list_tools():
            return [types.Tool(name=spec["name"], description=spec["description"],
                               inputSchema=spec["parameters"]) for spec in self.specs.values()]

        @self.server.call_tool(validate_input=False)
        async def call_tool(name: str, arguments: dict):
            return await self.call(name, arguments)

    async def call(self, name: str, arguments: dict):
        # Serialize state mutations/approval, equally for both arms.
        async with self.lock:
            if self.calls >= self.max_calls:
                self.exhausted = True
                self.audit.emit("tool.rejected", name=name, reason="tool_call_budget_exhausted")
                raise ValueError("tool_call_budget_exhausted; stop now")
            self.calls += 1
            started = time.perf_counter()
            failed = False
            audited_arguments = arguments
            try:
                try:
                    json.dumps(arguments, allow_nan=False)
                except (ValueError, TypeError):
                    audited_arguments = {"invalid_json_value": True}
                    raise ValueError("Arguments must contain only finite JSON values") from None
                if name not in self.specs:
                    raise ValueError("tool not available")
                validate(arguments, self.specs[name]["parameters"])
                if self.session.submission is not None or (
                    self.session.phase == "onboarding" and self.session.setup_complete
                ):
                    raise ValueError("episode already submitted; stop now")
                result = await self.session.call(name, arguments)
            except Exception as error:
                failed = True
                result = {"error": type(error).__name__,
                          "message": self.audit.redact(str(error)[:2000])}
            self.audit.emit("tool.result", name=name, arguments=audited_arguments, result=result,
                            actor_role=getattr(self.session, "audit_role", "author"),
                            seconds=time.perf_counter() - started)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result))],
                isError=failed)


@asynccontextmanager
async def serve_trial(bridge: TrialMCP):
    manager = StreamableHTTPSessionManager(bridge.server, stateless=True, json_response=True)
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
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("trial MCP failed to start")
                await asyncio.sleep(.01)
        yield f"http://127.0.0.1:{port}{route}"
    finally:
        server.should_exit = True
        await task
        sock.close()


async def codex_episode(session, *, key, effort, budget, audit, max_turns,
                        max_tool_calls, max_output_tokens, bundle=None,
                        timeout_seconds=360, instructions_override=None,
                        prompt_override=None) -> dict:
    from evaluations.bootstrap_agent_trial import COMMON_SYSTEM, MODEL, canonical

    if instructions_override is not None or prompt_override is not None:
        if instructions_override is None or prompt_override is None:
            raise ValueError("Custom research episodes require both instructions and prompt")
        prompt = instructions_override + "\n" + canonical(prompt_override)
    else:
        instructions = COMMON_SYSTEM
        if session.treatment:
            instructions += (
                " SignalWeave is available. For setup, call get_signalweave_guide first. Then onboard or draft a card from the brief "
                "and owner answers; inspect with get_insight_card, then use dry-run simulate_insight_card or preview_investigation_report, "
                "resolve blockers, request_synthetic_owner_approval, then approve_insight_card. "
                "Save notes and finish_setup with the card ID. Approval is simulated, not real "
                "human validation.\nProduction MCP instructions:\n" + (session.server.instructions or ""))
        if getattr(session, "owner_reviewer", None) is not None:
            instructions += (
                " Before finishing onboarding, save notes then request_synthetic_owner_approval. "
                "An independent model compares your notes (and card when present) with the original owner answers. "
                "Correct rejected artifacts explicitly and request review again, at most three attempts. "
                "Both arms need that review; it is not actual human approval. Changed notes/cards invalidate it. "
                "For SignalWeave, inspect and use simulate_insight_card or preview_investigation_report before requesting review. "
                "After the synthetic owner accepts the policy, call approve_insight_card without workflow_report_id "
                "for this delivery-disabled shadow trial, keep acceptance unassessed, then finish_setup. "
                "This does not waive source, policy, authorization or simulation blockers and never enables actual delivery.")
        instructions += ("\nUse only the trial MCP tools. No filesystem, shell, web or other "
                         "tools. After finish_setup or submit_analysis succeeds, stop immediately.")
        prompt = instructions + "\n" + canonical({
            "phase": session.phase, "period": session.adapter.period_context,
            "business": session.public, "saved_notes": session.notes,
            "signalweave_evaluation": bundle})
    bridge = TrialMCP(session, audit, await session.specs(), max_tool_calls)
    # Distinct IDs from positive Jev request IDs. A Codex invocation is NOT an API request.
    request_id = -(1 + sum(e["kind"] == "api.request" and e.get("provider") == "openai"
                          for e in audit.events))
    audit.emit("api.request", provider="openai", request_id=request_id,
               transport="codex_cli", accounting_unit="agent_invocation", model=MODEL,
               prompt=prompt, tools=list(bridge.specs.values()))
    started = time.perf_counter()
    usage = None
    error = None
    foreign_tools = []
    exit_code = None
    with tempfile.TemporaryDirectory(prefix="signalweave-agent-") as cwd:
        async with serve_trial(bridge) as url:
            process = await asyncio.create_subprocess_exec(
                *codex_command(cwd, url, model=MODEL, effort=effort),
                env=child_environment(), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=8 * 1024 * 1024)

            async def read_errors():
                while line := await process.stderr.readline():
                    audit.emit("codex.stderr", text=line.decode(errors="replace")[:8000])

            errors_task = asyncio.create_task(read_errors())
            try:
                async with asyncio.timeout(timeout_seconds):
                    process.stdin.write(prompt.encode())
                    await process.stdin.drain()
                    process.stdin.close()
                    while line := await process.stdout.readline():
                        event = json.loads(line)
                        audit.emit("codex.event", event=event)
                        if event.get("type") == "turn.completed":
                            usage = event.get("usage")
                        if event.get("type") in {"turn.failed", "error"}:
                            error = "codex_error"
                        item = event.get("item", {})
                        if item.get("type") in {"command_execution", "web_search", "file_change"}:
                            foreign_tools.append(item["type"])
                        if item.get("type") == "mcp_tool_call" and item.get("server") != "trial":
                            foreign_tools.append(str(item.get("server")))
                        if foreign_tools or bridge.exhausted or budget.exhausted:
                            error = "foreign_tool_used" if foreign_tools else "budget_exhausted"
                            break
                    if error:
                        process.terminate()
                    await process.wait()
            except TimeoutError:
                error = "episode_timeout"
                process.kill()
                await process.wait()
            except Exception as failure:
                # Keep counters even when stdout parsing fails after tools ran.
                error = type(failure).__name__
                if process.returncode is None:
                    process.kill()
                await process.wait()
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                await errors_task
                exit_code = process.returncode
    if isinstance(usage, dict):
        normalized = dict(usage)
        normalized["input_tokens_details"] = {"cached_tokens": usage.get("cached_input_tokens", 0)}
        audit.emit("api.response", provider="openai", request_id=request_id,
                   transport="codex_cli", usage=normalized, seconds=time.perf_counter() - started)
    else:
        audit.emit("api.error", provider="openai", request_id=request_id,
                   error_type=error or "missing_usage", usage_known=False)
    done = session.setup_complete if session.phase == "onboarding" else session.submission is not None
    success = done and not error and exit_code == 0
    elapsed = time.perf_counter() - started
    return {"status": "complete" if success else "failed", "error": error if success else
            error or ("codex_exit" if exit_code else "no_structured_submission"),
            "tool_calls": bridge.calls, "seconds": elapsed,
            "response_timeout_seconds": timeout_seconds,
            "timeout_scope": "stdin_stdout_and_process_wait_excluding_startup_and_cleanup",
            "wall_time_overrun_seconds": max(0., elapsed - timeout_seconds),
            "transport": "codex_cli", "exit_code": exit_code, "foreign_tools": foreign_tools}

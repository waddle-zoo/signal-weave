"""Evaluation-only Codex CLI transport using saved login and a scoped local MCP.

No OAuth extraction, direct API key, production agent loop, or fixture file access.
The parent retains private labels, credentials and mutable trial state.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import socket
import tempfile
import time
from contextlib import asynccontextmanager, nullcontext

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
# Opt-in accounting uses a bounded window; the third rejection requests termination.
ACCOUNTING_DRAIN_SECONDS = 5.0
ACCOUNTING_DRAIN_ABORT_AFTER_REJECTIONS = 3
MAX_RESOURCE_DISCOVERY_CALLS = 4


def scoped_resource_discovery(item: dict) -> bool:
    """Recognize only metadata listing for this command's sole configured MCP.

    This is an opt-in research control, not permission to read resources or use
    other built-in tools. Keep legacy/closed protocols on their strict default.
    """
    arguments = item.get("arguments")
    identifier = item.get("id")
    return (
        item.get("server") in ("codex", "trial")
        and isinstance(item.get("tool"), str)
        and item.get("tool") in {"list_mcp_resources", "list_mcp_resource_templates"}
        and isinstance(identifier, str) and 0 < len(identifier) <= 200
        and isinstance(arguments, dict) and set(arguments) <= {"server", "cursor"}
        and (arguments.get("server") is None or arguments.get("server") == "trial")
        and (arguments.get("cursor") is None or isinstance(arguments["cursor"], str)
             and len(arguments["cursor"]) <= 4096)
    )


def normalized_codex_usage(usage: object) -> dict | None:
    if not isinstance(usage, dict):
        return None
    counts = (usage.get("input_tokens"), usage.get("output_tokens"),
              usage.get("cached_input_tokens"))
    if any(type(count) is not int or count < 0 for count in counts):
        return None
    input_tokens, _, cached_input_tokens = counts
    if cached_input_tokens > input_tokens:
        return None
    normalized = dict(usage)
    normalized["input_tokens_details"] = {"cached_tokens": cached_input_tokens}
    return normalized


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


async def verify_trial_registry(executable, cwd, url):
    """Inspect configuration without inference; explicitly disable merged peers.

    `mcp_servers={}` is not a deletion operator in the pinned CLI. Never expose
    full inventory output: entries can contain configured credential material.
    """
    base = [str(executable), "mcp", "list", "--json", "--disable", "apps", "--disable", "plugins"]

    async def inventory(settings):
        command = list(base)
        for setting in settings:
            command.extend(["-c", setting])
        process = await asyncio.create_subprocess_exec(*command, cwd=cwd, env=child_environment(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), 30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode:
            raise ValueError("Cannot verify configured MCP registry; no inference admitted")
        rows = json.loads(stdout)
        if not isinstance(rows, list) or any(not isinstance(row, dict)
                or not isinstance(row.get("name"), str) or not row["name"] or len(row["name"]) > 256
                or type(row.get("enabled")) is not bool for row in rows):
            raise ValueError("Invalid MCP registry inventory; no inference admitted")
        if len({row["name"] for row in rows}) != len(rows):
            raise ValueError("Ambiguous configured MCP names; no inference admitted")
        if any(row.get("transport", {}).get("type") not in {"stdio", "streamable_http"} for row in rows):
            raise ValueError("Unknown MCP transport kind; no inference admitted")
        return [{"name": row["name"], "enabled": row["enabled"],
                 "transport_type": row["transport"]["type"]} for row in rows]

    original = await inventory([])
    if any(row["name"] == "trial" for row in original):
        raise ValueError("Existing trial configuration could retain credentials; no inference admitted")
    # Use a TOML value rather than quoted dotted CLI paths, and give disabled
    # peers inert transports so the same override also parses with user config
    # ignored. Never copy a peer's command, URL or credentials to process args.
    entries = []
    for row in sorted(original, key=lambda row: row["name"]):
        transport = ('command="signalweave-disabled-no-launch"' if row["transport_type"] == "stdio"
                     else 'url="http://127.0.0.1:9/disabled"')
        entries.append(f'{json.dumps(row["name"])}={{enabled=false,{transport}}}')
    entries.append(f'trial={{enabled=true,url={json.dumps(url)},required=true,tool_timeout_sec=120,default_tools_approval_mode="approve"}}')
    overrides = ["mcp_servers={" + ",".join(entries) + "}"]
    checked = await inventory(["mcp_servers={}", f"mcp_servers.trial.url={json.dumps(url)}", *overrides])
    if [row["name"] for row in checked if row["enabled"]] != ["trial"]:
        raise ValueError("Configured discovery registry is not isolated; no inference admitted")
    checked.sort(key=lambda row: row["name"])
    return {"overrides": overrides, "registry": checked,
            "registry_sha256": hashlib.sha256(json.dumps(checked, sort_keys=True).encode()).hexdigest(),
            "enabled_servers": ["trial"], "scope": "Configured MCP inventory, not proof of analytical correctness"}


class TrialMCP:
    def __init__(self, session, audit, specs: list[dict], max_calls: int, *,
                 accounting_drain: bool = False, report_remaining_budget: bool = False):
        self.session, self.audit = session, audit
        self.specs = {spec["name"]: spec for spec in specs}
        self.max_calls = max_calls
        self.accounting_drain = accounting_drain
        self.report_remaining_budget = report_remaining_budget
        self.calls = 0
        self.ingress_calls = 0
        self.exhausted = False
        self.rejected_calls = 0
        self.exhaustion_event = asyncio.Event()
        self.rejection_limit_event = asyncio.Event()
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
        ingress_call = None
        if self.accounting_drain:
            # This records bridge-handler entry, not network packet completion.
            self.ingress_calls += 1
            ingress_call = self.ingress_calls
            self.audit.emit("tool.ingress", name=name, ingress_call=ingress_call,
                            stage="bridge_handler_entered")
        try:
            await self.lock.acquire()
        except asyncio.CancelledError:
            if self.accounting_drain:
                self.audit.emit("tool.cancelled", name=name, ingress_call=ingress_call,
                                stage="waiting_for_bridge_lock",
                                reason="cancelled_before_dispatch")
            raise
        try:
            return await self._call_locked(name, arguments)
        finally:
            self.lock.release()

    async def _call_locked(self, name: str, arguments: dict):
        # Serialize state mutations/approval, equally for both arms.
        if self.calls >= self.max_calls:
            self.exhausted = True
            if self.accounting_drain:
                self.exhaustion_event.set()
                self.rejected_calls += 1
                if self.rejected_calls == ACCOUNTING_DRAIN_ABORT_AFTER_REJECTIONS:
                    self.rejection_limit_event.set()
                self.audit.emit("tool.rejected", name=name,
                                reason="tool_call_budget_exhausted")
                return types.CallToolResult(
                    content=[types.TextContent(
                        type="text",
                        text=json.dumps({"error": "ValueError",
                                         "message": "tool_call_budget_exhausted; stop now"}),
                    )],
                    isError=True,
                )
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
        content = [types.TextContent(type="text", text=json.dumps(result))]
        if self.report_remaining_budget:
            content.append(types.TextContent(type="text", text=(
                f"Research tool budget: {max(0, self.max_calls - self.calls)} company-tool calls remain. "
                "The final publication/submission also uses a call; reserve one. "
                "This is operational status, not business/source evidence."
            )))
        return types.CallToolResult(content=content, isError=failed)


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
    server.capture_signals = nullcontext
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
                        prompt_override=None, model: str | None = None,
                        codex_executable: str = "codex",
                        accounting_drain: bool = False,
                        allow_trial_resource_discovery: bool = False,
                        expected_registry_sha256: str | None = None,
                        report_remaining_budget: bool = False,
                        strict_single_turn_usage: bool = False) -> dict:
    from evaluations.bootstrap_agent_trial import (
        COMMON_SYSTEM,
        MODEL,
        SIGNALWEAVE_BUNDLE_INSTRUCTIONS,
        canonical,
    )
    selected_model = model or MODEL
    if not selected_model or not effort:
        raise ValueError("Codex model and reasoning effort must be nonempty")
    shared_card = getattr(session, "shared_card", None)

    if instructions_override is not None or prompt_override is not None:
        if instructions_override is None or prompt_override is None:
            raise ValueError("Custom research episodes require both instructions and prompt")
        # Custom research episodes are still allowed to receive the same
        # precomputed SignalWeave handoff as the canonical episode path.  The
        # old branch silently discarded ``bundle`` whenever a caller supplied
        # a custom prompt, which made a treatment agent re-read connectors and
        # invalidated comparisons that claimed to measure a preflight bundle.
        payload = dict(prompt_override) if isinstance(prompt_override, dict) else {"input": prompt_override}
        if shared_card is not None:
            payload["shared_card"] = shared_card
        if bundle is not None:
            payload["signalweave_evaluation"] = bundle
        prompt = instructions_override + "\n" + canonical(payload)
    else:
        instructions = COMMON_SYSTEM
        if session.treatment:
            instructions += (
                " SignalWeave is available. For setup, call get_signalweave_guide first. Then use bootstrap_insight_card "
                "with the plain-language goal, purpose, policy and routing guidance from the brief and owner answers. "
                "Use response_mode='compact' on bootstrap_insight_card, onboard_insight_card, propose_insight_card, "
                "get_insight_card, review_insight_card, resolve_insight_sources, simulate_insight_card, and "
                "preview_investigation_report during normal agent work; use response_mode='full' only when an "
                "operator explicitly asks for the exhaustive audit packet. Compact mode preserves typed policy, "
                "source identity, rankings, evidence and approval facts while removing duplicated catalog payloads. "
                "Inspect the selected source and its analytical comparisons before finalizing the card. "
                "For every explicit threshold, pass an exact numeric_conditions binding when the inspected source exposes "
                "the comparison: use measurement=change_pct with unit=percent for relative thresholds, or the source's "
                "exact unit for signed delta/level checks. First pass selected_sources with an exact adapter|resource ref "
                "and a short card-local key such as primary or quality; numeric_conditions.source_key must equal that key, "
                "while comparison_key must be copied exactly from the inspected analytical_comparisons key, never from a "
                "time-window label. Use the exact source-declared comparison window identifier such as previous_period. "
                "For every owner-approved route, pass a delivery_methods entry with the exact destination key/URL from the "
                "owner directory; prose alone does not configure a route. Then inspect with get_insight_card, use dry-run simulate_insight_card or preview_investigation_report, "
                "resolve blockers, request_synthetic_owner_approval, then approve_insight_card. For a card with "
                "retrieval_mode=expand or investigation_mode=bounded, review and approve against the full authorized "
                "catalog by omitting adapter; use an adapter scope only for a fixed, single-connector card. "
                "If the card explicitly uses retrieval_mode=expand or investigation_mode=bounded, "
                "the owner must acknowledge that bounded dynamic scope: pass the current review "
                "fingerprint, source-selection reason, and dynamic_scope_acknowledged=true. "
                "When the owner asks to connect related signals or investigate why a movement happened, "
                "preserve that intent with retrieval_mode=expand. Use investigation_mode=bounded only when the "
                "owner asks for an additional source-based why/driver investigation beyond the approved anchors "
                "and relationship-linked context; a multi-source card does not require a second follow-up stage. "
                "Otherwise use investigation_mode=none; do not silently narrow retrieval scope. "
                "Selecting one metric source is not the same as owner-confirming anchor-only scope: inspect "
                "adapter-published relationship candidates and retain required partition, deployment, lineage, "
                "quality, or ownership context before choosing fixed. "
                "Inspect the full review's recommended corroborating or diagnostic candidates and explicitly anchor "
                "any source the policy names as required context; bounded expansion must not silently substitute an "
                "archive, sandbox, forecast, or other population. "
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
        if session.treatment and bundle is not None:
            instructions += SIGNALWEAVE_BUNDLE_INSTRUCTIONS
        if session.phase == "monitoring" and shared_card is not None:
            instructions += (
                " Both arms were given the identical owner-reviewed card snapshot in the opening context. "
                "The baseline has no SignalWeave tools and must execute that policy with ordinary "
                "connector tools; the SignalWeave arm must use its card-backed evaluation bundle. "
                "Do not silently replace the card policy."
            )
        instructions += ("\nUse only the trial MCP tools. No filesystem, shell, web or other "
                         "tools. After finish_setup or submit_analysis succeeds, stop immediately.")
        prompt = instructions + "\n" + canonical({
            "phase": session.phase, "period": session.adapter.period_context,
            "business": session.public, "saved_notes": session.notes,
            "shared_card": shared_card,
            "signalweave_evaluation": bundle})
    bridge = TrialMCP(session, audit, await session.specs(), max_tool_calls,
                      accounting_drain=accounting_drain, report_remaining_budget=report_remaining_budget)
    # Distinct IDs from positive Jev request IDs. A Codex invocation is NOT an API request.
    request_id = -(1 + sum(e["kind"] == "api.request" and e.get("provider") == "openai"
                          for e in audit.events))
    audit.emit("api.request", provider="openai", request_id=request_id,
               transport="codex_cli", accounting_unit="agent_invocation",
               model=selected_model, effort=effort,
               prompt=prompt, tools=list(bridge.specs.values()))
    started = time.perf_counter()
    usage = None
    usage_reports = []
    error = None
    foreign_tools = []
    resource_discovery_ids = set()
    resource_discovery_attempt_ids = set()
    registry_isolation = None
    final_message = ""
    exit_code = None
    with tempfile.TemporaryDirectory(prefix="signalweave-agent-") as cwd:
        async with serve_trial(bridge) as url:
            command = codex_command(cwd, url, model=selected_model, effort=effort)
            command[0] = codex_executable
            if allow_trial_resource_discovery:
                registry_isolation = await verify_trial_registry(codex_executable, cwd, url)
                if expected_registry_sha256 and registry_isolation["registry_sha256"] != expected_registry_sha256:
                    raise ValueError("Configured MCP inventory changed after preflight; no inference admitted")
                for override in registry_isolation["overrides"]:
                    command[-1:-1] = ["-c", override]
                audit.emit("codex.registry_isolation", **registry_isolation)
            process = await asyncio.create_subprocess_exec(
                *command,
                env=child_environment(), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=8 * 1024 * 1024)

            async def read_errors():
                while line := await process.stderr.readline():
                    audit.emit("codex.stderr", text=line.decode(errors="replace")[:8000])

            def record_event(line):
                nonlocal usage, error, final_message
                event = json.loads(line)
                audit.emit("codex.event", event=event)
                if event.get("type") == "turn.completed":
                    usage = event.get("usage")
                    usage_reports.append(usage)
                if event.get("type") in {"turn.failed", "error"}:
                    error = "codex_error"
                item = event.get("item", {})
                if item.get("type") in {"command_execution", "web_search", "file_change"}:
                    foreign_tools.append(item["type"])
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    final_message = item["text"]
                if item.get("type") == "mcp_tool_call" and (
                    item.get("server") != "trial"
                    or registry_isolation and (not isinstance(item.get("tool"), str) or item["tool"] not in bridge.specs)
                ):
                    if registry_isolation and scoped_resource_discovery(item):
                        identifier = item["id"]
                        if identifier not in resource_discovery_attempt_ids:
                            resource_discovery_attempt_ids.add(identifier)
                            if len(resource_discovery_ids) >= MAX_RESOURCE_DISCOVERY_CALLS:
                                foreign_tools.append("resource_discovery_budget_exhausted")
                                audit.emit("codex.resource_discovery_rejected", name=item["tool"],
                                           item_id=identifier, reason="metadata_budget_exhausted")
                            else:
                                resource_discovery_ids.add(identifier)
                                audit.emit("codex.resource_discovery", name=item["tool"],
                                           arguments=item["arguments"], item_id=identifier,
                                           meaning="metadata only; not a company tool or source read")
                    else:
                        foreign_tools.append(str(item.get("server")))
                return event

            errors_task = asyncio.create_task(read_errors())
            output_task = None
            signal_tasks = []
            try:
                async with asyncio.timeout(timeout_seconds):
                    process.stdin.write(prompt.encode())
                    await process.stdin.drain()
                    process.stdin.close()
                    if not accounting_drain:
                        while line := await process.stdout.readline():
                            record_event(line)
                            # In the local-MCP comparison this budget limits live Jev
                            # requests, not the Codex subscription-backed agent. A
                            # depleted Jev budget must be recorded as treatment
                            # censoring; it must not kill the baseline agent (or a
                            # reviewer) and bias the paired cohort by run order.
                            if foreign_tools or bridge.exhausted:
                                error = "foreign_tool_used" if foreign_tools else "tool_call_budget_exhausted"
                                break
                        if error:
                            process.terminate()
                    else:
                        loop = asyncio.get_running_loop()
                        output_task = asyncio.create_task(process.stdout.readline())
                        exhausted_task = asyncio.create_task(bridge.exhaustion_event.wait())
                        rejection_task = asyncio.create_task(bridge.rejection_limit_event.wait())
                        signal_tasks.extend((exhausted_task, rejection_task))
                        drain_deadline = None
                        while True:
                            waiters = {output_task, rejection_task}
                            if drain_deadline is None:
                                waiters.add(exhausted_task)
                            remaining = (None if drain_deadline is None else
                                         max(0.0, drain_deadline - loop.time()))
                            ready, _ = await asyncio.wait(
                                waiters, timeout=remaining,
                                return_when=asyncio.FIRST_COMPLETED)
                            if not ready:
                                error = "tool_call_budget_exhausted"
                                process.terminate()
                                break
                            if output_task in ready:
                                line = output_task.result()
                                if not line:
                                    if bridge.exhausted:
                                        error = "tool_call_budget_exhausted"
                                    break
                                record_event(line)
                                if foreign_tools:
                                    error = "foreign_tool_used"
                                    process.terminate()
                                    break
                                if bridge.exhausted:
                                    error = "tool_call_budget_exhausted"
                                    if drain_deadline is None:
                                        drain_deadline = loop.time() + ACCOUNTING_DRAIN_SECONDS
                                elif error == "codex_error":
                                    process.terminate()
                                    break
                                output_task = asyncio.create_task(process.stdout.readline())
                            if rejection_task in ready:
                                error = "tool_call_budget_exhausted"
                                process.terminate()
                                break
                            if exhausted_task in ready:
                                error = "tool_call_budget_exhausted"
                                if drain_deadline is None:
                                    drain_deadline = loop.time() + ACCOUNTING_DRAIN_SECONDS
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
                for task in [output_task, *signal_tasks]:
                    if task is not None and not task.done():
                        task.cancel()
                pending_tasks = [task for task in [output_task, *signal_tasks]
                                 if task is not None]
                if pending_tasks:
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
                await errors_task
                exit_code = process.returncode
    normalized_usage = normalized_codex_usage(usage)
    if strict_single_turn_usage and len(usage_reports) != 1:
        normalized_usage = None
        error = error or "ambiguous_codex_turn_usage"
    if normalized_usage is not None:
        audit.emit("api.response", provider="openai", request_id=request_id,
                   transport="codex_cli", model=selected_model, effort=effort,
                   usage=normalized_usage, seconds=time.perf_counter() - started)
    else:
        audit.emit("api.error", provider="openai", request_id=request_id,
                   model=selected_model, effort=effort,
                   error_type=error or ("missing_usage" if usage is None else "invalid_usage"),
                   usage_known=False)
    done = session.setup_complete if session.phase == "onboarding" else session.submission is not None
    success = done and not error and exit_code == 0
    elapsed = time.perf_counter() - started
    return {"status": "complete" if success else "failed", "error": error if success else
            error or ("codex_exit" if exit_code else "no_structured_submission"),
            "final_message": audit.redact(final_message[:12000]),
            "tool_calls": bridge.calls, "seconds": elapsed,
            "resource_discovery_calls": len(resource_discovery_ids),
            "resource_discovery_attempts": len(resource_discovery_attempt_ids),
            "completion_usage_reports": usage_reports,
            "registry_isolation": registry_isolation,
            "observed_tool_calls_including_discovery": (
                bridge.ingress_calls if accounting_drain else bridge.calls
            ) + len(resource_discovery_attempt_ids),
            "response_timeout_seconds": timeout_seconds,
            "timeout_scope": "stdin_stdout_and_process_wait_excluding_startup_and_cleanup",
            "wall_time_overrun_seconds": max(0., elapsed - timeout_seconds),
            "transport": "codex_cli", "model": selected_model, "effort": effort,
            "exit_code": exit_code, "foreign_tools": foreign_tools}

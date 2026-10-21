"""Opt-in full Northstar company journey using the current native and real MCP.

This is a simulated-owner, retrospective whole-product exercise. Its seven
cohorts are selected from the complete finalized warehouse; neither the source
nor the MCP is time-isolated, and it is not an as-known-at-the-time backtest.
Preparation and preflight are zero-provider. Each arm gets one persistent
Codex agent and one attempt; actor execution requires an exact independent
review of the frozen study and preflight artifacts.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import date, timedelta
from pathlib import Path, PurePosixPath

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations import enterprise_full_journey as pine
from evaluations import northstar_workspace_journey as setup
from evaluations.bootstrap_agent_trial import Audit, RequestBudget, function
from evaluations.codex_trial_transport import codex_episode
from evaluations.harbor_workflow_actor import WorkspaceSourceActor, _tool_spec
from evaluations.harbor_workflow_journey import provider_usage
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _jev_proxy,
    _minimal_environment,
    _private_file,
)
from evaluations.northstar_source_authoring import public_paths
from evaluations.raw_superset_onboarding import usage_snapshot
from scripts.binary_provenance import ROOT, verify_binary
from signalweave.mcp_server import AGENT_PROFILE_TOOLS
from signalweave.query_source import load_query_catalog

PROTOCOL = "northstar-retrospective-enterprise-journey-v2"
ORDER = ("baseline", "signalweave")
PERIOD_ENDS = (
    "2026-08-03", "2026-08-10", "2026-08-17", "2026-08-24",
    "2026-08-31", "2026-09-07", "2026-09-14",
)
LIMITS = {
    "actors": 2,
    "attempts_per_arm": 1,
    # One evaluation can use multiple token-budgeted question batches. The
    # original nine-call research cap manufactured 429s during a seven-period
    # run. Provision eight batches per period plus eight setup/recovery calls;
    # this is a ceiling, not a target or permission to retry into a better score.
    "jev_requests_total": 64,
    "seconds_per_actor": 1800,
    "mcp_calls_per_actor": 120,
    "workspace_calls_per_actor": 100,
    "between_actor_input_stop": 20_000_000,
    "between_actor_uncached_stop": 750_000,
}
LOCAL_TOOLS = frozenset({
    "ask_dispatch_owner", "confirm_workflow", "send_message", "read_inbox", "finish_period",
})
IMPORT_TOOL = "operator_import_query"
METHOD_FILES = (
    "evaluations/northstar_enterprise_journey.py",
    "evaluations/northstar_workspace_journey.py",
    "evaluations/northstar_source_authoring.py",
    "evaluations/pine_courier_onboarding.py",
    "evaluations/enterprise_full_journey.py",
    "evaluations/codex_trial_transport.py",
    "evaluations/codex_workspace.py",
    "evaluations/harbor_workflow_actor.py",
    "evaluations/harbor_workflow_journey.py",
    "evaluations/installed_trial_transport.py",
    "evaluations/native_human_superset_journey.py",
    "evaluations/raw_superset_onboarding.py",
    "evaluations/redwood_workspace_compatibility.py",
    "evaluations/domain_context_onboarding_trial.py",
    "src/signalweave/query_source.py",
    "src/signalweave/local_queries.py",
    "src/signalweave/cli.py",
    "src/signalweave/mcp_server.py",
    "scripts/binary_provenance.py",
    "docs/query-sources.md",
    "docs/mcp-source-bridge.md",
    "skills/signalweave/SKILL.md",
)

OWNER_POLICY = (
    "I lead Dispatch. For each weekly reporting period, count all shipments whose promised_date "
    "falls in the stated half-open seven-day window. Damage rate is damaged shipments divided by "
    "shipments in that cohort. Investigate for Dispatch when the rate is above 2.0% and there are "
    "at least 400 shipments. A period needs represented promised_date coverage on all seven days; "
    "otherwise do not call it clear and send the specific coverage gap separately to Data Operations. "
    "Dispatch gets a concise digest every week, even when nothing crosses the rule. Carrier splits "
    "are investigation leads, not causes. Do not claim a cause, a fix, or that anyone acted unless "
    "the evidence establishes it. These are retrospective selections from the complete finalized "
    "warehouse: later shipment outcomes may already be present. This is not an as-known-at-the-time "
    "or real-time test, and the query period end is not a freshness override."
)

COMMON = (
    "You are a capable BI/data expert helping a fictional Northstar Dispatch lead replace a manual "
    "weekly delivery review. This is a complete seven-period retrospective product-use exercise, "
    "not a customer study. The current period is the only period disclosed at a time. Use the "
    "current reporting window as [period_start, period_end) on promised_date, with period_end "
    "exclusive. The source is the complete finalized historical warehouse and is not row-filtered "
    "by period; later shipment outcomes may already exist. This is NOT as-known-at-the-time data, "
    "future isolation, or a real-time backtest. The query clock only selects this reporting period; "
    "do not rebase source freshness or claim point-in-time availability. The native retrieval time "
    "is the actual current retrieval time. Ask the simulated owner about business intent and obtain "
    "explicit consent before relying on a proposed workflow. Discover and inspect evidence using "
    "the supplied 27 read-only community Superset tools and your own persistent workspace. Keep "
    "measured findings separate from hypotheses; carrier differences do not prove causes. Make a "
    "useful Dispatch digest for every period and separately involve Data Operations for a supported "
    "coverage/data gap. Do not invent a fix, a human action, or a business result. Deliver only to "
    "the local simulated inboxes, read the replies, incorporate useful feedback in later updates, "
    "and advance only through finish_period. Source IDs in a message remain locators; only explicit "
    "workspace-file paths are copied into recipient-accessible local attachments. Preserve your "
    "own working SQL, notes, calculations and reusable procedure in this workspace. No web, other "
    "projects, credentials, external delivery, source writes, schedules, or hidden fixtures. Finish "
    "with a concise human handoff and durable working notes."
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".northstar-journey-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def period_window(index: int) -> tuple[str, str]:
    end = date.fromisoformat(PERIOD_ENDS[index])
    return (end - timedelta(days=7)).isoformat(), end.isoformat()


def method() -> dict[str, str]:
    return {name: setup._sha(ROOT / name) for name in METHOD_FILES}


def _human_readable_artifacts(inventory: dict) -> list[str]:
    return [name for name in inventory if Path(name).suffix.lower() in {".md", ".txt"}]


def _require_source_docker_context() -> None:
    if os.environ.get("DOCKER_CONTEXT") != "desktop-linux":
        raise ValueError(
            "Run this Northstar journey with DOCKER_CONTEXT=desktop-linux so warehouse checks "
            "bind the already-verified local source daemon without changing global Docker settings"
        )


def task(arm: str, index: int = 0) -> tuple[str, dict]:
    start, end = period_window(index)
    instructions = COMMON
    if arm == "signalweave":
        instructions += (
            " Read the installed .agents/skills/signalweave/SKILL.md, query-sources.md, and "
            "queries-schema.json. Start with the actual native guide and the company evidence. "
            "Author your own reviewed SQL catalog in this workspace using the current schema and "
            "the source's inspected definitions. Use an explicit query clock and the quoted "
            "{{cutoff_date}} token for the current period end; include the half-open promised_date "
            "cohort and enough denominators/coverage/breakdowns for the owner's policy. The source "
            "is finalized historical data, not point-in-time ingestion history. Ask "
            "operator_import_query to import that exact file into this isolated native home; the "
            "operator will not author, rewrite, validate the business meaning of, or repair your "
            "SQL. Count each import as an admin action. Inspect the imported source and result. Aim "
            "to create and review a card, show its actual saved version and source scope to the "
            "simulated owner, obtain consent, and use native approval/evaluation when the actual "
            "workflow permits. Prefer the same approved card once per period with distinct keys "
            "when it remains usable. If setup, review, approval or evaluation fails, is deferred, "
            "or needs native-supported repair, preserve the error and continue with the best "
            "supported human report; never claim an approval/evaluation that did not occur. On "
            "finish_period the trusted native query "
            "process is restarted with the next explicit period end; no source or freshness policy "
            "is changed. Do not expose answer labels or infer that the explicit query clock changes "
            "the source's actual retrieval time."
        )
    prompt = {
        "request": (
            "I lead Dispatch and manually review weekly delivery performance. Help me make the "
            "review useful, repeatable and appropriately qualified; investigate meaningful damage "
            "signals, keep routine digests coming, and involve Data Operations separately when "
            "coverage is incomplete. Ask what you need, show the procedure before relying on it, "
            "and run it through the periods I provide. Use only local simulated inboxes."
        ),
        "current_reporting_period": {
            "period_start_inclusive": start,
            "period_end_exclusive": end,
            "field": "promised_date",
            "interpretation": "retrospective finalized-cohort selector, not a source as-of clock",
        },
    }
    return instructions, prompt


def _json_result(value):
    if isinstance(value, dict) and isinstance(value.get("result"), str):
        try:
            return json.loads(value["result"])
        except json.JSONDecodeError:
            return value
    return value


def _selected_database(value) -> dict:
    decoded = _json_result(value)
    rows = decoded.get("result") if isinstance(decoded, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Superset did not return its database inventory")
    matches = [row for row in rows if isinstance(row, dict) and row.get("database_name") == "Northstar Lakehouse"]
    if len(matches) != 1:
        raise ValueError("Expected one Northstar Lakehouse connection")
    row = matches[0]
    if any(row.get(flag) is not False for flag in ("allow_dml", "allow_ctas", "allow_cvas")):
        raise ValueError("Northstar source must keep DML, CTAS and CVAS disabled")
    if type(row.get("id")) is not int or row["id"] < 1:
        raise ValueError("Northstar source database id is invalid")
    return {"id": row["id"], "name": row["database_name"], "allow_dml": False,
            "allow_ctas": False, "allow_cvas": False}


def _native_query_schema(binary: Path, home: Path, workspace: Path) -> dict:
    process = subprocess.run(
        [str(binary), "queries", "schema"], cwd=workspace,
        env=_minimal_environment(home), capture_output=True, text=True, timeout=30,
    )
    if process.returncode:
        raise ValueError("Current native `queries schema` command failed")
    try:
        schema = json.loads(process.stdout)
    except json.JSONDecodeError:
        raise ValueError("Current native query schema was not JSON") from None
    if not isinstance(schema, dict) or schema.get("title") != "QueryCatalog":
        raise ValueError("Current native query schema did not identify QueryCatalog")
    save(workspace / "queries-schema.json", schema)
    reference = ROOT / "docs/query-sources.md"
    shutil.copyfile(reference, workspace / "query-sources.md")
    os.chmod(workspace / "query-sources.md", 0o600)
    return {"schema_sha256": _sha(workspace / "queries-schema.json"),
            "reference_sha256": _sha(workspace / "query-sources.md")}


def _prior_attempts(previous: Path) -> dict:
    """Keep the closed pair and its costs visible before a fresh forward check."""
    previous = Path(previous).resolve(strict=True)
    study = setup.shared.read(previous / "study.json")
    if study.get("protocol") != PROTOCOL or study.get("reporting_period_ends") != list(PERIOD_ENDS):
        raise ValueError("Forward check needs the same company's retained seven-period study")
    records = {arm: setup.shared.read(previous / f"{arm}.json") for arm in ORDER}
    for arm, record in records.items():
        if record.get("protocol") != PROTOCOL or record.get("arm") != arm:
            raise ValueError("Prior terminal record does not identify the expected arm")
        _check_prior_baseline(record)
    return {
        "root": str(previous), "study_sha256": _sha(previous / "study.json"),
        "terminal_sha256": {arm: _sha(previous / f"{arm}.json") for arm in ORDER},
        "usage": {arm: record["usage"] for arm, record in records.items()},
        "seconds": {arm: record.get("seconds") for arm, record in records.items()},
        "provider_requests": {arm: record.get("provider_requests") for arm, record in records.items()},
        "source_identity": {key: study[key] for key in (
            "warehouse", "source_revision", "source_environment", "binary",
        )},
        "limitation": (
            "Fresh forward treatment after a simulator repair, not a replacement or rescore of "
            "either prior attempt. Retain all prior costs; no clean paired efficiency claim."
        ),
    }


async def prepare(root, binary, codex, key_file, source_executable, source_checkout,
                  url="http://127.0.0.1:18089", *, treatment_only=False, prior_study=None,
                  first_arm="baseline"):
    """Reuse the actual isolated Superset/native/Codex setup; zero paid calls."""
    _require_source_docker_context()
    if first_arm not in ORDER or (treatment_only and first_arm != "baseline"):
        raise ValueError("Select a valid paired first arm; standalone checks have no paired order")
    paired_order = [first_arm, *(arm for arm in ORDER if arm != first_arm)]
    if treatment_only != (prior_study is not None):
        raise ValueError("A forward treatment check requires --treatment-only and --prior-study together")
    prior_attempts = _prior_attempts(prior_study) if treatment_only else None
    root = Path(root).absolute()
    await setup.prepare(
        root, binary, codex, key_file, source_executable, source_checkout, url,
        codex_identity_resolver=pine.first.pinned_codex,
    )
    study = setup.shared.read(root / "study.json")
    bootstrap = {key: study.get(key) for key in (
        "protocol", "method", "limits", "binary", "installed_binary", "source_executable",
        "source_executable_sha256", "source_environment", "source_revision", "source_checkout",
        "url", "codex", "registry_sha256", "warehouse", "wizard", "registration_verified",
        "analytical_sql_preflight",
    )}
    async with setup.servers(study, root, Audit(), RequestBudget(0), False) as (source, _):
        source_names = {_tool_spec(tool)["name"] for tool in await source.list_tools()}
        if not setup.SOURCE_TOOLS <= source_names:
            raise ValueError("The current community Superset MCP is missing an allowed analytical tool")
        _, databases = await source.call_tool("superset_database_list", {"get_all": True})
    database = _selected_database(databases)
    schema_files = _native_query_schema(Path(study["installed_binary"]),
        root / "human-home/.signalweave", root / "signalweave/workspace")
    study.update(
        protocol=PROTOCOL,
        method=method(),
        limits=LIMITS,
        order=["signalweave"] if treatment_only else paired_order,
        comparison=("fresh forward treatment only; retained prior pair, not a new paired baseline"
                    if treatment_only else f"{first_arm} first, one attempt each"),
        bootstrap=bootstrap,
        source_tool_names=sorted(setup.SOURCE_TOOLS),
        source_tool_server_count=len(source_names),
        source_tool_exposed_count=len(setup.SOURCE_TOOLS),
        analytical_database=database,
        native_query_reference=schema_files,
        reporting_period_ends=list(PERIOD_ENDS),
        reporting_window="seven-day half-open [end-7d, end) cohort on promised_date",
        source_time_semantics=(
            "Complete finalized historical warehouse; retrospective period selector only. "
            "No ingestion-time isolation, as-known-at-the-time claim, or real-time backtest. "
            "Native retrieval timestamp remains actual current retrieval time."
        ),
        policy_scope=(
            "Simulated owner policy: damage rate >2.0% with >=400 shipments merits Dispatch "
            "investigation; all seven promised-date days must be represented for a clear period; "
            "coverage gaps go separately to Data Operations; carrier splits are leads, not causes; "
            "Dispatch gets a routine digest every period. Formative whole-product exercise, not "
            "an independent test of a threshold selected after source inspection."
        ),
        claim_limits=(
            "No customer, real-owner, real-time, future-blinding, fresh-as-of, cost-win, or "
            "recurrence-value claim is implied by this simulated journey."
        ),
        scope=(
            "One fresh forward SignalWeave attempt with its prior pair retained across seven retrospective "
            if treatment_only else
            "One fresh paired attempt in the declared arm order across seven retrospective "
        ) + (
            "Northstar delivery cohorts, using the current downloaded native, isolated Codex "
            "setup, the existing 137-tool community Superset server with its frozen 27-tool "
            "read-only analytical allowlist exposed to both arms, simulated Dispatch/Data Operations "
            "and local inboxes. No warehouse changes or external delivery."
        ),
    )
    if prior_attempts is not None:
        if any(study[key] != value for key, value in prior_attempts["source_identity"].items()):
            raise ValueError("Forward check source or native identity differs from the retained pair")
        study["prior_attempts"] = prior_attempts
    for arm in ORDER:
        workspace = root / arm / "workspace"
        response_dir = workspace / "tool-responses"
        response_dir.mkdir(mode=0o700, exist_ok=True)
        response_dir.chmod(0o700)
        # setup.prepare's initial proof uses its default empty read-only profile.
        # Recompute the canonical SDK/interpreter/capture grants for this exact
        # workspace and use the identical list for preflight and actor launch.
        read_paths = list(map(str, public_paths(workspace)))
        if arm == "signalweave":
            read_paths.append(str((workspace / ".agents").resolve(strict=True)))
        sandbox = await asyncio.to_thread(
            setup.sandbox_preflight, study["codex"]["path"], workspace,
            root / "private-canary.txt", (Path(study["key_file"]),),
            readonly_paths=read_paths,
        )
        study["arms"][arm] = {
            **study["arms"].get(arm, {}),
            "sandbox": sandbox,
            "read_paths": read_paths,
            "initial_inventory": setup.workspace_inventory(workspace),
        }
    study["reference_files"] = {
        "signalweave/workspace/query-sources.md": schema_files["reference_sha256"],
        "signalweave/workspace/queries-schema.json": schema_files["schema_sha256"],
    }
    # The reused setup flow already creates study.json. Replace it atomically
    # with the complete actor profile instead of using the create-only helper.
    save(root / "study.json", study)
    return {"prepared": True, "actors": 0, "provider_requests": 0,
            "source_tools_available": len(setup.SOURCE_TOOLS), "binary": study["binary"]}


def verify(study: dict, root: Path) -> None:
    _require_source_docker_context()
    if study.get("protocol") != PROTOCOL or study.get("method") != method() or study.get("limits") != LIMITS:
        raise ValueError("Frozen Northstar journey method changed")
    if study.get("order") == ["signalweave"]:
        retained = study.get("prior_attempts", {})
        if not retained or _prior_attempts(Path(retained["root"])) != retained:
            raise ValueError("Retained forward-check ledger changed")
    elif study.get("order") not in (list(ORDER), list(reversed(ORDER))):
        raise ValueError("Unknown actor order")
    bootstrap = study["bootstrap"]
    if verify_binary(Path(study["installed_binary"]), ROOT) != study["binary"]:
        raise ValueError("The installed native candidate changed")
    if setup._sha(Path(study["codex"]["path"])) != study["codex"]["sha256"]:
        raise ValueError("The isolated Codex executable changed")
    if setup._sha(Path(study["source_executable"])) != study["source_executable_sha256"]:
        raise ValueError("The community Superset MCP executable changed")
    if setup.source_environment_identity(study["source_executable"]) != study["source_environment"]:
        raise ValueError("The installed community Superset MCP environment changed")
    if setup.warehouse_fingerprint() != study["warehouse"]:
        raise ValueError("The Northstar source warehouse changed")
    if bootstrap.get("registration_verified") is not True or not study.get("analytical_database"):
        raise ValueError("The isolated native registration or company source was not verified")
    for arm in ORDER:
        workspace = root / arm / "workspace"
        expected_paths = [*map(str, public_paths(workspace))]
        if arm == "signalweave":
            expected_paths.append(str((workspace / ".agents").resolve(strict=True)))
        if study["arms"][arm].get("read_paths") != expected_paths:
            raise ValueError("Frozen workspace read grants differ from the sandbox-preflight profile")
        proof = study["arms"][arm].get("sandbox", {})
        if not all(proof.get(key) is True for key in (
            "workspace_read_write", "private_read_write_denied", "command_network_denied",
        )):
            raise ValueError("The frozen actor sandbox preflight did not pass")
    for relative, expected in study["reference_files"].items():
        if setup._sha(root / relative) != expected:
            raise ValueError("Treatment's current query-source reference changed")


class ClockedNativeConnection(pine.NativeConnection):
    """Pine's task-owned stdio RPC with the trusted explicit period clock."""

    def __init__(self, binary, home, audit, proxy, period_end):
        super().__init__(binary, home, audit, proxy)
        self.period_end = date.fromisoformat(period_end).isoformat()

    def select_period(self, period_end: str) -> None:
        self.period_end = date.fromisoformat(period_end).isoformat()

    def child_environment(self) -> dict[str, str]:
        env = _minimal_environment(self.home, jev_url=self.proxy)
        env["PINE_SOURCE_PYTHONPATH"] = str(ROOT)
        env["SIGNALWEAVE_QUERY_AS_OF_DATE"] = self.period_end
        return env

    async def _restart(self):
        if self.stack:
            await self.stack.aclose()
        self.stack = AsyncExitStack()
        params = StdioServerParameters(
            command=str(self.binary), args=["serve", "--home", str(self.home)],
            env=self.child_environment(), cwd=str(ROOT),
        )
        streams = await self.stack.enter_async_context(stdio_client(params))
        session = await self.stack.enter_async_context(ClientSession(*streams))
        initialized = await _initialize_mcp_session(session)
        self.server = InstalledServer(session, initialized.instructions, self.audit)
        self.instructions = self.server.instructions
        names = {tool.name for tool in await self.server.list_tools()}
        if names != AGENT_PROFILE_TOOLS:
            raise ValueError("Expected exact normal native agent profile after reconnect")


@asynccontextmanager
async def sessions(study, root, arm, audit, budget):
    async with setup.servers(study, root, audit, budget, False) as (source, _):
        if arm == "baseline":
            yield source, None
            return
        async with AsyncExitStack() as stack:
            proxy = await stack.enter_async_context(_jev_proxy(audit, budget))
            native = ClockedNativeConnection(
                Path(study["installed_binary"]), root / "human-home/.signalweave", audit,
                proxy, PERIOD_ENDS[0],
            )
            await native.restart()
            try:
                yield source, native
            finally:
                await native.close()


def _tool_schema(arm: str) -> list[dict]:
    text = {"type": "string", "minLength": 1}
    ref_array = {"type": "array", "maxItems": 20, "items": text}
    tools = [
        function("ask_dispatch_owner",
            "Ask the simulated Dispatch owner about business rules or retrospective scope. The answer contains no measured period results or causes.",
            {"question": {**text, "maxLength": 2000}}, ("question",)),
        function("confirm_workflow",
            "Show the proposed procedure and include card_id when asking about a saved card. If the exact saved card is successfully fetched and displayed, "
            "the simulated owner explicitly authorizes you to call native approve_insight_card for that saved version, policy, and exact source scope. "
            "This is authority to make the real native call, not a card status change or evaluation. Without a displayed card, consent is procedure-only. "
            "Neither consent validates SQL/calculations or authorizes scheduling or external delivery.",
            {"summary": {**text, "maxLength": 6000}, "card_id": {"type": "string", "minLength": 1}}, ("summary",)),
        function("send_message",
            "Deliver a real message only to a local simulated inbox. source_refs are retained as locators and are not "
            "automatically resolved, copied, or guaranteed clickable. workspace_files must be relative paths inside "
            "your workspace; those exact files are copied into recipient-accessible simulated inbox attachments with SHA-256 hashes. "
            "Use files when the recipient needs their contents; keep source locators distinct from file attachments.",
            {"to": {"type": "string", "enum": ["dispatch", "data-operations"]},
             "body": {**text, "maxLength": 6000}, "source_refs": ref_array,
             "workspace_files": ref_array}, ("to", "body", "source_refs", "workspace_files")),
        function("read_inbox", "Read local simulated recipient messages, acknowledgements and non-answer feedback.", {}, ()),
        function("finish_period",
            "Finish after sending the period's Dispatch digest. Reading recipient feedback is optional and observed, not required. "
            "Reveals only the next reporting window, then advances the trusted explicit query clock and reconnects native; never changes source rows.",
            {}, ()),
    ]
    if arm == "signalweave":
        tools.append(function(IMPORT_TOOL,
            "Count one simulated administrator action: import your exact agent-authored query JSON file using the installed native "
            "`queries import --source superset --yes --file ...` command, then restart/reconnect. This does not author, rewrite, "
            "semantically review or repair SQL. The file must be inside your workspace, use the current native QueryCatalog schema, "
            "the prepared Northstar database, and explicit `{{cutoff_date}}` clock semantics.",
            {"proposal_path": {**text, "maxLength": 1000}}, ("proposal_path",)))
    return tools


class NorthstarWorld:
    """Simulated owner/admin/inboxes; no expected results or analysis oracle."""

    def __init__(self, source, root: Path, arm: str, native=None):
        self.source, self.root, self.arm, self.native = source, Path(root), arm, native
        self.workspace = self.root / arm / "workspace"
        self.day = 0
        self.started = time.monotonic()
        self.owner_questions, self.owner_confirmations = [], []
        self.operations, self.messages, self.feedback_reads = [], [], []
        self.native_observations = []
        self.inbox_read_message_ids: set[str] = set()
        self.imported_query_sha256 = None
        self.database_id = None
        self.hidden_mcp_calls = 0
        self.draft_created = False
        self.card_id = None
        self.reviewed_card_id = None
        self.confirmed_card_id = None
        self.displayed_card = None
        self.approved_card_id = None
        self.evaluations: dict[int, list[str]] = {i: [] for i in range(len(PERIOD_ENDS))}
        self.inbox_read_periods: set[int] = set()
        self.done = False
        self.failed_clock_advance = False

    @property
    def period_end(self):
        return PERIOD_ENDS[self.day]

    @property
    def period_start(self):
        return period_window(self.day)[0]

    def snapshot(self):
        return {
            "arm": self.arm,
            "current_period_index": self.day,
            "current_period_end": self.period_end if not self.done else PERIOD_ENDS[-1],
            "owner_questions": self.owner_questions,
            "owner_confirmations": self.owner_confirmations,
            "operator_actions": self.operations,
            "internal_mcp_calls": self.hidden_mcp_calls,
            "native_observations": self.native_observations,
            "messages": self.messages,
            "feedback_reads": self.feedback_reads,
            "feedback_read_message_ids": sorted(self.inbox_read_message_ids),
            "evaluations_by_period": self.evaluations,
            "feedback_coverage": len({
                message["period_end_exclusive"] for message in self.messages
                if message["id"] in self.inbox_read_message_ids
            }),
            "all_sent_feedback_read": all(
                message["id"] in self.inbox_read_message_ids for message in self.messages
            ),
            "complete": self.done,
            "clock_advance_failed": self.failed_clock_advance,
        }

    def record(self):
        save(self.root / f"world-{self.arm}.json", self.snapshot())

    def observe_native(self, name: str, args: dict, result: dict | None = None, error=None) -> None:
        card_id = args.get("card_id")
        key = args.get("idempotency_key")
        observation = {
            "period_index": self.day,
            "period_end_exclusive": self.period_end,
            "tool": name,
            "card_id": card_id,
            "idempotency_key": key,
            "succeeded": error is None,
            "error_type": type(error).__name__ if error else None,
        }
        if isinstance(result, dict):
            artifact = result.get("_caller_artifact")
            if isinstance(artifact, dict):
                observation["response_sha256"] = artifact.get("sha256")
            observation["result_card_id"] = _find_card_id(result)
        self.native_observations.append(observation)
        if name == "evaluate_insight_card":
            self.evaluations[self.day].append(key if isinstance(key, str) else "")
        if error is not None:
            return
        if name == "onboard_insight_card":
            self.draft_created = True
            found = _find_card_id(result)
            if found:
                self.card_id = found
        elif name == "review_insight_card":
            self.reviewed_card_id = card_id
            if card_id:
                self.card_id = card_id
        elif name == "revise_insight_card":
            if card_id:
                self.card_id = card_id
            self.reviewed_card_id = None
            self.confirmed_card_id = None
            self.displayed_card = None
        elif name == "approve_insight_card":
            self.approved_card_id = card_id

    async def call(self, name: str, args: dict, delegate: WorkspaceSourceActor | None = None):
        if self.done:
            raise ValueError("The seven-period journey is complete")
        if name == "ask_dispatch_owner":
            item = {"question": args["question"], "answer": OWNER_POLICY,
                    "period_end": self.period_end, "consent": False}
            self.owner_questions.append(item)
            return item
        if name == "confirm_workflow":
            card = None
            card_id = args.get("card_id")
            card_read_error = None
            self.confirmed_card_id = None
            self.displayed_card = None
            if self.arm == "signalweave" and self.native and delegate and card_id:
                self.hidden_mcp_calls += 1
                try:
                    fetched_card = await delegate.call("get_insight_card", {"card_id": card_id})
                    card = _find_saved_card(fetched_card, card_id)
                    if card is not None:
                        self.displayed_card = card
                        self.confirmed_card_id = card_id
                    else:
                        card = None
                        card_read_error = "CardIdentityMismatch"
                except Exception as exc:  # noqa: BLE001 - owner may still consent to a fallback procedure
                    card_read_error = type(exc).__name__
            consent = (
                "I consent to the described procedure for local retrospective shadow runs and local "
                "simulated inbox delivery. This procedure consent does not itself change card status. "
                "If no saved card was displayed, this is procedure-only consent. This is "
                "fictional consent only; it does not validate SQL, data quality, calculations, causes, "
                "or real-company delivery, and does not authorize scheduling."
            )
            approval_authorization = None
            if card is not None:
                sources = card.get("sources")
                if (isinstance(sources, list) and sources
                        and all(isinstance(source, dict) and source.get("adapter") and source.get("resource")
                                for source in sources)
                        and isinstance(card.get("title"), str)
                        and isinstance(card.get("version"), int)
                        and not isinstance(card.get("version"), bool)):
                    source_refs = [f"{source['adapter']}|{source['resource']}" for source in sources]
                    approval_authorization = {
                        "action": "call_native_approve_insight_card",
                        "card_id": card_id,
                        "title": card["title"],
                        "version": card["version"],
                        "source_refs": source_refs,
                        "source_scope": sources,
                    }
                    fingerprint = card.get("onboarding_review", {}).get("source_selection_fingerprint")
                    if fingerprint:
                        approval_authorization["source_selection_fingerprint"] = fingerprint
                    consent += (
                        f" Yes: I explicitly authorize you to call the real native approve_insight_card tool for "
                        f"this exact displayed saved card, {card['title']} version {card['version']}, its saved "
                        f"policy, and this exact source scope: {', '.join(source_refs)}. This is permission to make "
                        "that native call after review; it does not itself change approval status, evaluate the card, "
                        "schedule it, or send externally."
                    )
            event = {"summary": args["summary"], "card_id": card_id, "saved_card": card,
                     "card_read_error": card_read_error, "period_end": self.period_end,
                     "consent": consent}
            if approval_authorization:
                event["approval_authorization"] = approval_authorization
            self.owner_confirmations.append(event)
            return event
        if name == IMPORT_TOOL:
            if self.arm != "signalweave" or not self.native:
                raise ValueError("The baseline does not use the SignalWeave operator import path")
            return await self._import_query(args["proposal_path"])
        if name == "send_message":
            if not self.owner_confirmations:
                raise ValueError("Obtain simulated owner consent before delivering any weekly message")
            if args["to"] not in {"dispatch", "data-operations"} or not isinstance(args["body"], str) \
                    or not args["body"].strip() or len(args["body"]) > 6000:
                raise ValueError("Use a bounded message to a local simulated recipient")
            source_refs = args["source_refs"]
            file_refs = args["workspace_files"]
            message_id = f"{self.arm}-message-{len(self.messages) + 1}"
            folder = self.root / self.arm / "inbox" / message_id
            attachments = _copy_workspace_evidence(self.workspace, folder, file_refs)
            message = {
                "id": message_id,
                "period_start_inclusive": self.period_start,
                "period_end_exclusive": self.period_end,
                "to": args["to"],
                "body": args["body"],
                "source_refs": list(source_refs),
                "attachments": attachments,
                "seconds_since_actor_start": time.monotonic() - self.started,
            }
            self.messages.append(message)
            return {"delivered": True, "message_id": message_id,
                    "destination": f"simulation://{args['to']}",
                    "source_refs_retained_as_locators": list(source_refs),
                    "attachments": attachments}
        if name == "read_inbox":
            current = [message for message in self.messages
                       if message["id"] not in self.inbox_read_message_ids]
            replies = [{
                "reply_to": message["id"], "from": message["to"],
                "body": (
                    "Received. Please lead future notes with the reporting dates, denominator and "
                    "coverage, and make routine digest versus investigation clear. Keep measured "
                    "findings separate from carrier leads."
                    if message["to"] == "dispatch" else
                    "Received the coverage concern. Please name the exact date/field gap and what "
                    "remains unknown; this acknowledgement is not evidence of a repair."
                ),
            } for message in current]
            self.feedback_reads.append({"period_end": self.period_end, "messages": current, "replies": replies})
            if current:
                self.inbox_read_periods.update(
                    PERIOD_ENDS.index(message["period_end_exclusive"]) for message in current
                )
                self.inbox_read_message_ids.update(message["id"] for message in current)
            return {"messages": current, "replies": replies}
        if name == "finish_period":
            if not any(m["period_end_exclusive"] == self.period_end and m["to"] == "dispatch" for m in self.messages):
                raise ValueError("Deliver the routine Dispatch digest before finishing this period")
            if self.day == len(PERIOD_ENDS) - 1:
                self.done = True
                self.record()
                return {"engagement_complete": True,
                        "next": "Preserve the reusable working procedure and leave a concise human handoff."}
            next_day = self.day + 1
            next_end = PERIOD_ENDS[next_day]
            if self.native:
                self.native.select_period(next_end)
                try:
                    await self.native.restart()
                except Exception:
                    self.failed_clock_advance = True
                    raise
            self.day = next_day
            self.record()
            start, end = period_window(self.day)
            return {
                "period_start_inclusive": start,
                "period_end_exclusive": end,
                "field": "promised_date",
                "interpretation": "retrospective finalized-cohort selector; not source as-of availability",
                "request": "Run the next weekly review, investigate what merits attention, deliver the routine Dispatch digest and any separately supported Data Operations coverage note, read and use available feedback as helpful, then finish_period.",
            }
        raise ValueError("tool not available")

    async def _import_query(self, proposal_path: str):
        path = _workspace_file(self.workspace, proposal_path)
        before = _sha(path)
        try:
            catalog = load_query_catalog(path)
        except Exception as exc:  # noqa: BLE001 - the actor may repair its own artifact
            raise ValueError("The file must match the current native query catalog schema") from exc
        if any(
            query.database_id != self.database_id
            or query.clock is None
            or query.clock.kind != "explicit"
            or "{{cutoff_date}}" not in query.sql
            for query in catalog.queries
        ):
            raise ValueError("Use the prepared Northstar database and explicit {{cutoff_date}} clock on every query")
        env = _minimal_environment(self.native.home, jev_url=self.native.proxy)
        env["PINE_SOURCE_PYTHONPATH"] = str(ROOT)
        env["SIGNALWEAVE_QUERY_AS_OF_DATE"] = self.period_end
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            str(self.native.binary), "queries", "import", "--source", "superset", "--yes",
            "--file", str(path), "--home", str(self.native.home),
            cwd=str(self.workspace), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 90)
        after = _sha(path)
        event = {
            "action": "queries import",
            "source": "superset",
            "proposal_sha256_before": before,
            "proposal_sha256_after": after,
            "returncode": process.returncode,
            "seconds": time.monotonic() - started,
            "sql_authored_or_rewritten_by_operator": False,
            "stdout": stdout.decode(errors="replace")[:3000],
            "stderr": stderr.decode(errors="replace")[:3000],
        }
        self.operations.append(event)
        self.record()
        if before != after:
            raise ValueError("Operator import changed the actor-authored proposal file")
        if process.returncode:
            return {"imported": False, "query_count": len(catalog.queries),
                    "proposal_sha256": before, "operator_action_count": len(self.operations),
                    "reconnected": False, "returncode": process.returncode,
                    "stdout": stdout.decode(errors="replace")[:2000],
                    "stderr": stderr.decode(errors="replace")[:2000],
                    "next": "Native query import failed; inspect this CLI response and decide what to do next."}
        self.native.select_period(self.period_end)
        try:
            await self.native.restart()
        except Exception:
            self.record()
            raise
        self.imported_query_sha256 = before
        self.record()
        return {"imported": True, "query_count": len(catalog.queries),
                "proposal_sha256": before, "operator_action_count": len(self.operations),
                "returncode": process.returncode,
                "stdout": stdout.decode(errors="replace")[:2000],
                "stderr": stderr.decode(errors="replace")[:2000],
                "reconnected": True, "next": "Inspect the imported query source and actual result before card review."}

def _find_card_id(value):
    if isinstance(value, dict):
        for key in ("card_id", "insight_card_id"):
            if isinstance(value.get(key), str) and value[key]:
                return value[key]
        if isinstance(value.get("id"), str) and value.get("object") in {"insight_card", "card"}:
            return value["id"]
        for nested in value.values():
            found = _find_card_id(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_card_id(nested)
            if found:
                return found
    return None


def _find_saved_card(value, card_id):
    """Unwrap common MCP envelopes and return only the exact requested saved card."""
    if isinstance(value, dict):
        if (value.get("id") == card_id and isinstance(value.get("title"), str)
                and isinstance(value.get("version"), int)):
            return value
        for nested in value.values():
            found = _find_saved_card(nested, card_id)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_saved_card(nested, card_id)
            if found is not None:
                return found
    return None


def _workspace_file(workspace: Path, reference: str) -> Path:
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("Use a relative file path inside the current workspace")
    relative = PurePosixPath(reference)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Workspace file references must stay inside the current workspace")
    candidate = Path(workspace).joinpath(*relative.parts)
    cursor = Path(workspace)
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Workspace file references cannot use symlinks")
    path = candidate.resolve(strict=True)
    if not path.is_relative_to(Path(workspace).resolve(strict=True)) or not path.is_file():
        raise ValueError("Workspace evidence must be an ordinary file within the current workspace")
    if path.stat().st_size > 16_000_000:
        raise ValueError("A single simulated inbox attachment is limited to 16 MB")
    return path


def _copy_workspace_evidence(workspace: Path, destination: Path, references: list[str]) -> list[dict]:
    if len(references) > 20:
        raise ValueError("At most 20 workspace evidence files can be attached")
    if not references:
        return []
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    destination.chmod(0o700)
    copied = []
    for index, reference in enumerate(references):
        source = _workspace_file(workspace, reference)
        target = destination / f"{index + 1}-{source.name}"
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
        source_hash, copy_hash = _sha(source), _sha(target)
        if source_hash != copy_hash:
            raise ValueError("Workspace evidence copy failed SHA-256 verification")
        copied.append({"original_workspace_path": reference,
                       "recipient_path": str(target), "filename": source.name,
                       "bytes": target.stat().st_size, "sha256": copy_hash})
    return copied


class NorthstarJourneyBridge:
    """Add the small human-world surface to the existing 27-tool workspace bridge."""

    def __init__(self, source, audit, world: NorthstarWorld, *, native=None):
        self.world = world
        self.base = WorkspaceSourceActor(source, audit, world.workspace,
            source_tools=setup.SOURCE_TOOLS, native=native)
        self.treatment = native is not None
        self.phase = "whole_journey"
        self.setup_complete = False
        self.submission = None
        self.lock = asyncio.Lock()
        self._local = _tool_schema(world.arm)
        self.total_mcp_actions = 0

    async def specs(self):
        specs = [*await self.base.specs(), *self._local]
        names = [item["name"] for item in specs]
        if len(names) != len(set(names)):
            raise ValueError("Company, native, and simulated-world tool names must be unique")
        return specs

    async def call(self, name: str, arguments: dict):
        async with self.lock:
            self.total_mcp_actions += 1
            hidden = int(name == "confirm_workflow" and self.world.arm == "signalweave"
                         and bool(arguments.get("card_id")))
            if self.total_mcp_actions + self.world.hidden_mcp_calls + hidden > LIMITS["mcp_calls_per_actor"]:
                raise ValueError("Combined visible and internal MCP action budget exhausted")
            if name in LOCAL_TOOLS or name == IMPORT_TOOL:
                result = await self.world.call(name, arguments, self.base)
            else:
                try:
                    result = await self.base.call(name, arguments)
                except Exception as exc:
                    if not name.startswith("company_"):
                        self.world.observe_native(name, arguments, error=exc)
                    self.world.record()
                    raise
                if not name.startswith("company_"):
                    self.world.observe_native(name, arguments, result=result)
            self.world.record()
            return result


@asynccontextmanager
async def actor_sessions(study, root, arm, audit, budget):
    async with setup.servers(study, root, audit, budget, False) as (source, _):
        if arm == "baseline":
            yield source, None
            return
        async with AsyncExitStack() as stack:
            proxy = await stack.enter_async_context(_jev_proxy(audit, budget))
            native = ClockedNativeConnection(Path(study["installed_binary"]),
                root / "human-home/.signalweave", audit, proxy, PERIOD_ENDS[0])
            await native.restart()
            try:
                yield source, native
            finally:
                await native.close()


async def preflight(root: Path):
    root = Path(root).absolute()
    study = setup.shared.read(root / "study.json")
    study_hash = setup._sha(root / "study.json")
    result = {"passed": False, "study_sha256": study_hash, "provider_requests": 0,
              "native_child_task_restart_verified": False, "company_select_verified": False,
              "source_scope": "current 27-tool allowlist; raw historical data remains unrestricted by period"}
    audit, budget = Audit(path=root / "preflight.jsonl"), RequestBudget(0)
    try:
        verify(study, root)
        async with setup.servers(study, root, audit, budget, False) as (source, _):
            available = {_tool_spec(tool)["name"] for tool in await source.list_tools()}
            if not setup.SOURCE_TOOLS <= available:
                raise ValueError("Current company MCP is missing part of the frozen 27-tool analytical allowlist")
            _, databases = await source.call_tool("superset_database_list", {"get_all": True})
            database = _selected_database(databases)
            if database != study["analytical_database"]:
                raise ValueError("Northstar database identity or read-only flags changed")
            _, query = await source.call_tool("superset_sqllab_execute", {
                "database_id": database["id"], "sql": "SELECT 1 AS northstar_source_probe",
            })
            decoded = _json_result(query)
            if not isinstance(decoded, dict) or decoded.get("data") != [{"northstar_source_probe": 1}]:
                raise ValueError("The current community SQL tool did not return the read-only probe")
            result["company_select_verified"] = True
            result["community_tool_count"] = len(available)
            result["exposed_analytical_tool_count"] = len(setup.SOURCE_TOOLS)
            result["database"] = database
        async with actor_sessions(study, root, "signalweave", audit, budget) as (_, native):
            assert native is not None
            native.select_period(PERIOD_ENDS[0])
            await native.restart()
            await asyncio.create_task(native.restart())
            tools = await asyncio.create_task(native.list_tools())
            if {tool.name for tool in tools} != AGENT_PROFILE_TOOLS:
                raise ValueError("Cross-task native reconnect did not expose the exact normal profile")
            await asyncio.create_task(native.call_tool("list_insight_cards", {}))
            result["native_child_task_restart_verified"] = True
            result["native_period_clock"] = PERIOD_ENDS[0]
        if budget.used:
            raise ValueError("Preflight unexpectedly made a provider request")
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - failed zero-provider preflight is retained
        result["error"] = {"type": type(exc).__name__, "message": str(exc)[:1500]}
    result["provider_requests"] = budget.used
    setup.shared.write(root / "preflight.json", audit.redact(result))
    return result


def _admission(root: Path, review: Path, study: dict) -> None:
    preflight_path = root / "preflight.json"
    if not review.is_file() or not preflight_path.is_file():
        raise ValueError("Exact independent review of study.json and preflight.json is required before actors")
    admission = setup.shared.read(review)
    checked = setup.shared.read(preflight_path)
    if (
        admission.get("approved") is not True
        or not isinstance(admission.get("reviewer"), str)
        or not admission["reviewer"].strip()
        or admission.get("study_sha256") != setup._sha(root / "study.json")
        or admission.get("preflight_sha256") != setup._sha(preflight_path)
        or checked.get("passed") is not True
        or checked.get("provider_requests") != 0
        or checked.get("study_sha256") != setup._sha(root / "study.json")
    ):
        raise ValueError("Admission does not approve the exact passing zero-provider frozen study/preflight")


def _check_prior_baseline(record: dict) -> None:
    if record.get("usage", {}).get("known") is not True:
        raise ValueError("Baseline usage is unknown; preserve it without launching treatment")
    if record.get("inputs_unchanged") is not True:
        raise ValueError("Baseline changed frozen source or method inputs; preserve it without launching treatment")
    usage = record["usage"].get("usage", {})
    for key, bound in (("input_tokens", "between_actor_input_stop"),
                       ("uncached_input_tokens", "between_actor_uncached_stop")):
        count = usage.get(key)
        if type(count) is not int or count < 0:
            raise ValueError("Baseline token usage is incomplete; preserve it without launching treatment")
        if count >= LIMITS[bound]:
            raise ValueError("Between-actor token stop reached")


def _check_actor_order(study: dict, root: Path, arm: str) -> None:
    order = study["order"]
    if arm not in order:
        raise ValueError("Unknown arm")
    prior = []
    for name in order:
        record_path, claim_path = root / f"{name}.json", root / f"{name}.claimed"
        if claim_path.exists() and not record_path.exists():
            raise ValueError("A prior actor attempt is unreported; do not retry or continue")
        if record_path.is_file():
            prior.append(setup.shared.read(record_path))
    if len(prior) >= len(order) or order[len(prior)] != arm:
        raise ValueError("One attempt per arm in the frozen study order")
    if prior:
        _check_prior_baseline(prior[0])


def research_censoring(events: list[dict]) -> dict:
    """Keep research-manufactured provider failures separate from product faults."""
    rejected = sum(
        event.get("kind") == "api.rejected" and event.get("provider") == "jev"
        and event.get("reason") == "global_api_request_budget_exhausted"
        for event in events
    )
    return {
        "jev_request_budget_rejections": rejected,
        "provider_budget_bound": bool(rejected),
        "interpretation": (
            "Harness injected HTTP 429s; not a clean native reliability or efficiency comparison"
            if rejected else "No research provider-request rejection observed; business review remains required"
        ),
    }


async def actor(root: Path, arm: str, review: Path | None = None):
    root = Path(root).absolute()
    review = Path(review) if review else root / "admission-review.json"
    study = setup.shared.read(root / "study.json")
    verify(study, root)
    _admission(root, review, study)
    _check_actor_order(study, root, arm)
    if setup.workspace_inventory(root / arm / "workspace") != study["arms"][arm]["initial_inventory"]:
        raise ValueError("Actor starting workspace changed")
    _private_file(root / f"{arm}.claimed", PROTOCOL)
    jev_limit = LIMITS["jev_requests_total"] if arm == "signalweave" else 0
    audit, budget = Audit(path=root / f"{arm}.jsonl"), RequestBudget(jev_limit)
    result = {"protocol": PROTOCOL, "arm": arm, "process_complete": False,
              "errors": [], "frontier_invocations": 0, "episode_complete": False}
    started = time.monotonic()
    world = None
    bridge = None
    try:
        async with actor_sessions(study, root, arm, audit, budget) as (source, native):
            world = NorthstarWorld(source, root, arm, native)
            world.database_id = study["analytical_database"]["id"]
            bridge = NorthstarJourneyBridge(source, audit, world, native=native)
            instructions, prompt = task(arm)
            result["frontier_invocations"] = 1
            result["episode"] = await codex_episode(
                bridge, key="", model="gpt-6-luna", effort="xhigh", budget=budget, audit=audit,
                max_turns=1, max_tool_calls=LIMITS["mcp_calls_per_actor"], max_output_tokens=1,
                instructions_override=instructions, prompt_override=prompt,
                timeout_seconds=LIMITS["seconds_per_actor"], codex_executable=study["codex"]["path"],
                accounting_drain=True, report_remaining_budget=True, allow_trial_resource_discovery=True,
                expected_registry_sha256=study["registry_sha256"], strict_single_turn_usage=True,
                enforce_wall_response_timeout=True, finish_on_final_message=True,
                workspace_dir=str(root / arm / "workspace"),
                workspace_read_paths=study["arms"][arm]["read_paths"],
                max_workspace_tool_calls=LIMITS["workspace_calls_per_actor"],
            )
            world.record()
            result["episode_complete"] = result["episode"].get("status") == "complete"
            if native:
                try:
                    _, result["final_cards"] = await native.call_tool("list_insight_cards", {})
                except Exception as exc:  # noqa: BLE001 - native reporting is post-episode evidence
                    result["final_card_collection_error"] = {
                        "type": type(exc).__name__, "message": str(exc)[:1000],
                    }
    except Exception as exc:  # noqa: BLE001 - keep the one actual attempt, no retry
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)[:2000]})
    finally:
        if world is not None:
            try:
                world.record()
                result["world"] = world.snapshot()
                result["dispatch_periods_covered"] = len({
                    message["period_end_exclusive"] for message in world.messages
                    if message["to"] == "dispatch"
                })
                result["feedback_periods_read"] = world.snapshot()["feedback_coverage"]
                result["feedback_reads_count"] = len(world.feedback_reads)
            except Exception as exc:  # noqa: BLE001 - preserve record failures without masking usage
                result["world_record_error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
            if bridge is not None:
                result["mcp_actions_total"] = bridge.total_mcp_actions + world.hidden_mcp_calls
        try:
            result["workspace_files"] = setup.workspace_inventory(root / arm / "workspace")
            result["human_readable_artifacts"] = _human_readable_artifacts(result["workspace_files"])
            result["collection_complete"] = True
        except Exception as exc:  # noqa: BLE001 - artifact inventory is posthoc evidence
            result["collection_complete"] = False
            result["collection_error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        result["seconds"] = time.monotonic() - started
        result["usage"] = usage_snapshot(audit.events, result["frontier_invocations"])
        result["provider"] = provider_usage(audit, budget.used)
        result["provider_requests"] = budget.used
        result["research_censoring"] = research_censoring(audit.events)
        try:
            verify(study, root)
            result["inputs_unchanged"] = True
        except Exception as exc:  # noqa: BLE001 - source changes invalidate the result
            result["inputs_unchanged"] = False
            result["errors"].append({"type": type(exc).__name__, "message": str(exc)[:1500]})
        result["process_complete"] = bool(
            result.get("episode_complete") and world is not None and world.done
            and result["inputs_unchanged"]
        )
        setup.shared.write(root / f"{arm}.json", audit.redact(result))
    return {key: result.get(key) for key in ("arm", "process_complete", "seconds", "usage", "provider_requests", "errors")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Run fresh isolated native setup and freeze the study")
    prep.add_argument("--root", type=Path, required=True)
    prep.add_argument("--binary", type=Path, required=True, help="Fresh downloaded candidate; it is verified, not copied from Pine")
    prep.add_argument("--codex", type=Path, required=True)
    prep.add_argument("--key-file", type=Path, required=True)
    prep.add_argument("--source-executable", type=Path, required=True)
    prep.add_argument("--source-checkout", type=Path, required=True)
    prep.add_argument("--url", default="http://127.0.0.1:18089")
    prep.add_argument("--first-arm", choices=ORDER, default="baseline",
                      help="Freeze paired order before execution; use both orders across repetitions")
    prep.add_argument("--treatment-only", action="store_true", help="Fresh forward treatment; does not replace prior results")
    prep.add_argument("--prior-study", type=Path, help="Retained terminal records and costs for a forward treatment")
    for name in ("preflight", "actor"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
    actor_parser = commands.choices["actor"]
    actor_parser.add_argument("--arm", choices=ORDER, required=True)
    actor_parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    values = vars(args)
    operation = values.pop("command")
    if operation == "prepare":
        result = asyncio.run(prepare(**values))
    elif operation == "preflight":
        result = asyncio.run(preflight(**values))
    else:
        result = asyncio.run(actor(**values))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

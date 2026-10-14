"""Opt-in paired card-onboarding and source-drilldown trial on local Superset.

The run path uses a checksummed native archive, the real setup wizard, Codex,
the bundled user-scope skill, the normal agent MCP profile, and authenticated
read-only Superset HTTP. It contains no fixture source or expected-outcome
labels. Approval is an explicit interactive owner action after the draft and
current review are displayed; delivery and scheduling are never performed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit
from evaluations.codex_trial_transport import codex_episode
from evaluations.installed_trial_transport import InstalledServer, _initialize_mcp_session
from evaluations.native_human_superset_journey import ReportSession, terminal_setup
from scripts.binary_provenance import verify_binary
from signalweave.superset_adapter import SupersetAdapter
from signalweave.superset_client import SupersetClient

BUSINESS_QUESTIONS = (
    "What does the latest source period show about net sales and the online contribution?",
    "Which platform or funnel step best explains the observed digital-commerce pattern, if the source supports that comparison?",
    "Are there source-quality, freshness, coverage, or comparability facts that limit confidence in the business readout?",
)

SHARED_SOURCE_TOOLS = frozenset({
    "find_dashboards", "read_dashboard", "read_chart_rows", "submit_report",
})
DISCOVERY_TOOLS = frozenset({"find_dashboards", "search_catalog"})
DATA_READ_TOOLS = frozenset({"read_dashboard", "read_chart_rows", "inspect_resource"})
MAX_DATA_READS = 60
MAX_EPISODE_TURNS = 20
MAX_EPISODE_TOOL_CALLS = 60
SETUP_TOOLS = frozenset({
    "get_signalweave_guide", "search_catalog", "inspect_resource",
    "onboard_insight_card", "review_insight_card", "list_insight_cards", "get_insight_card",
})
MONITOR_TOOLS = frozenset({
    "get_signalweave_guide", "list_insight_cards", "get_insight_card",
    "evaluate_insight_card", "get_decision_receipt",
})

COMMON_INSTRUCTIONS = (
    "You are a business-intelligence analyst using the real, read-only Superset source tools. "
    "The business owner supplied the context in the task; do not invent metric definitions, "
    "comparison windows, thresholds, recipients, or desired outcomes. Answer all three questions "
    "from inspected evidence. Treat returned periods and comparison coverage exactly as reported; "
    "a recent bucket is not proof of a complete/comparable period. Follow up with direct Superset "
    "chart-row reads when they can resolve a question, and label those rows as saved-chart query "
    "scope rather than dashboard-filtered context. Keep observed facts separate from hypotheses, "
    "and do not call data fresh or stale from request time alone; require a source timestamp and applicable SLA. "
    "Catalog discovery calls are tracked separately from source data-read calls; use the available "
    "60 data-read tool calls to inspect definitions and rows rather than repeating catalog searches. "
    "cite source titles/links and dates, and state missing evidence instead of reassuring. "
    "The current evidence may or may not support a quiet, business-change, or data-quality conclusion; "
    "no category is predetermined, and do not synthesize missing cases. "
    "Do not schedule or send anything. Use only the trial tools; no shell, web, filesystem, or other tools. "
)

SETUP_INSTRUCTIONS = (
    "This is the onboarding phase. Start with the SignalWeave guide and existing cards. Search and "
    "inspect the smallest plausible source set, compare source meaning/population/grain and declared "
    "capabilities with the owner's question, then create one draft with onboard_insight_card and "
    "review it. Preserve only owner-confirmed policy; use exact catalog references and declared "
    "parameters. The three questions in the task are the requested recurring report sections. "
    "Keep the approved source scope fixed and small. Do not invent thresholds or comparison windows "
    "when the source does not declare them. Do not call simulation or full-profile tools. Do not "
    "approve: the owner must inspect the exact draft and review outside this agent turn. Finish with "
    "submit_report summarizing the card ID, exact source scope, review readiness/blockers, and any "
    "unresolved owner question, then stop."
)

BASELINE_INSTRUCTIONS = (
    "This is the strong general-agent baseline: SignalWeave tools are not available in this arm. "
    "Use the exact same installed SignalWeave skill and the same read-only source helpers as the "
    "other arm. If targeted dashboard searches miss, use find_dashboards with an empty query to "
    "browse the catalog instead of repeating title synonyms. Produce the same three-part evidence-backed readout and a concise repeatable "
    "approach, but do not claim that a card was saved, approved, or evaluated. Finish with "
    "submit_report, then stop."
)

MONITOR_INSTRUCTIONS = (
    "This is the post-approval run. Start with the monitor guide, inspect the approved card, and "
    "call evaluate_insight_card exactly once with the supplied new idempotency key and no copied "
    "source observations in context. Read the typed outcome together with its source coverage and "
    "periods. Then use the same direct Superset source helpers available to the baseline for a "
    "bounded drilldown across the three questions. Do not reinterpret a quality warning as a new "
    "business action rule, and do not infer quiet/event/data-issue labels from the task wording. "
    "Finish with submit_report, then stop."
)


def skill_path(home: Path) -> Path:
    """User-scope Codex skill path used by the native installer in the isolated home."""
    return home / ".agents" / "skills" / "signalweave" / "SKILL.md"


def load_installed_skill(home: Path) -> tuple[str, str]:
    path = skill_path(home)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(
            "The fresh setup did not install the bundled user-scope SignalWeave skill; "
            "do not count this as an agent-plus-skill run."
        )
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\nname: signalweave\n") or not content.strip():
        raise RuntimeError("Installed skill content is missing the expected SignalWeave frontmatter")
    return content, hashlib.sha256(content.encode("utf-8")).hexdigest()


def instructions_for(stage: str, skill_text: str) -> str:
    """Supply the actual packaged skill verbatim to both ephemeral Codex arms.

    The evaluation transport disables host skill discovery, so merely installing
    the skill would not put it in the model context. The trial reads the installed
    file and explicitly supplies that same content to baseline and treatment.
    """
    if stage == "baseline":
        task_rules = BASELINE_INSTRUCTIONS
    elif stage == "setup":
        task_rules = SETUP_INSTRUCTIONS
    elif stage == "monitor":
        task_rules = MONITOR_INSTRUCTIONS
    else:
        raise ValueError(f"unknown journey stage: {stage}")
    return (
        COMMON_INSTRUCTIONS
        + "\n\nInstalled SignalWeave skill (verbatim):\n<signalweave-skill>\n"
        + skill_text
        + "\n</signalweave-skill>\n\n"
        + task_rules
    )


def build_actor_prompt(owner_context: str) -> dict[str, Any]:
    return {
        "request": (
            "Prepare a useful current, source-backed response to these three recurring business "
            "questions, then explain what the owner must confirm before unattended action:\n"
            + "\n".join(f"{index}. {question}" for index, question in enumerate(BUSINESS_QUESTIONS, 1))
        ),
        "owner_context": owner_context,
        "source_environment": "Northstar local Superset at the operator-supplied URL; discover assets from the live catalog, not IDs in the task.",
    }


class CardJourneySession(ReportSession):
    """Existing real Superset helpers plus a stage-bounded native tool surface."""

    def __init__(self, adapter, native=None, *, stage: str, max_data_reads: int = MAX_DATA_READS):
        super().__init__(adapter, native)
        self.stage = stage
        self.max_data_reads = max_data_reads
        self.discovery_calls = 0
        self.discovery_calls_by_tool: dict[str, int] = {}
        self.data_reads = 0
        self.data_reads_by_tool: dict[str, int] = {}
        self.card: dict[str, Any] | None = None
        self.review: dict[str, Any] | None = None
        self.review_adapter: str | None = None
        self.evaluation: dict[str, Any] | None = None

    async def specs(self):
        specs = await super().specs()
        if self.native is None:
            allowed = SHARED_SOURCE_TOOLS
        elif self.stage == "setup":
            allowed = SHARED_SOURCE_TOOLS | SETUP_TOOLS
        elif self.stage == "monitor":
            allowed = SHARED_SOURCE_TOOLS | MONITOR_TOOLS
        else:
            raise ValueError(f"unsupported tool stage: {self.stage}")
        return [spec for spec in specs if spec["name"] in allowed]

    async def call(self, name: str, arguments: dict[str, Any]):
        if name in DISCOVERY_TOOLS:
            self.discovery_calls += 1
            self.discovery_calls_by_tool[name] = self.discovery_calls_by_tool.get(name, 0) + 1
        if name in DATA_READ_TOOLS:
            if self.data_reads >= self.max_data_reads:
                raise ValueError("data_read_budget_exhausted; state the remaining evidence gap")
            self.data_reads += 1
            self.data_reads_by_tool[name] = self.data_reads_by_tool.get(name, 0) + 1
        if name == "approve_insight_card":
            raise ValueError("owner approval is a separate human action in this trial")
        if name == "evaluate_insight_card":
            if self.evaluation is not None:
                raise ValueError("evaluate_insight_card may be called only once per run")
        result = await super().call(name, arguments)
        if name == "onboard_insight_card" and isinstance(result, dict):
            card = result.get("card")
            if isinstance(card, dict):
                self.card = card
        elif name == "review_insight_card" and isinstance(result, dict):
            card = result.get("card")
            review = result.get("review")
            if isinstance(card, dict):
                self.card = card
            if isinstance(review, dict):
                self.review = review
            adapter = arguments.get("adapter")
            self.review_adapter = adapter if isinstance(adapter, str) else None
        elif name == "evaluate_insight_card" and isinstance(result, dict):
            self.evaluation = result
        return result


def _card_id(session: CardJourneySession) -> str | None:
    if session.card and isinstance(session.card.get("id"), str):
        return session.card["id"]
    return None


def _review_readiness(session: CardJourneySession) -> str | None:
    return session.review.get("readiness_status") if session.review else None


async def _run_episode(session, *, audit: Audit, stage: str, prompt: dict[str, Any], skill: str):
    audit.episode = stage
    return await codex_episode(
        session,
        key="",
        effort="xhigh",
        model="gpt-6-luna",
        budget=None,
        audit=audit,
        max_turns=MAX_EPISODE_TURNS,
        max_tool_calls=MAX_EPISODE_TOOL_CALLS,
        max_output_tokens=7000,
        timeout_seconds=480,
        instructions_override=instructions_for(stage, skill),
        prompt_override=prompt,
    )


def _source_budget_summary(session: CardJourneySession) -> dict[str, Any]:
    return {
        "discovery_calls": session.discovery_calls,
        "discovery_calls_by_tool": dict(session.discovery_calls_by_tool),
        "data_read_calls": session.data_reads,
        "data_read_calls_by_tool": dict(session.data_reads_by_tool),
        "data_read_cap": session.max_data_reads,
        "episode_tool_call_cap": MAX_EPISODE_TOOL_CALLS,
    }


async def _owner_approval(native, session: CardJourneySession, adapter: str | None):
    card_id = _card_id(session)
    if not card_id or not session.review:
        return {"status": "not_ready", "reason": "draft card or current review missing"}
    readiness = _review_readiness(session)
    if readiness not in {"ready_for_approval", "needs_human_review"}:
        return {
            "status": "not_approved",
            "reason": "current review is blocked or missing; resolve blockers with the owner",
            "readiness_status": readiness,
        }
    sources = session.card.get("sources")
    if (
        session.card.get("retrieval_mode") != "fixed"
        or session.card.get("investigation_mode") != "none"
        or not isinstance(sources, list)
        or not 1 <= len(sources) <= 3
    ):
        return {
            "status": "not_approved",
            "reason": "trial requires a reviewed fixed card with one to three exact sources; dynamic scope is not auto-acknowledged",
        }
    if not sys.stdin.isatty():
        return {
            "status": "awaiting_owner",
            "reason": "interactive terminal required to review and explicitly approve the exact draft",
        }

    print("\nReview this exact draft and current source review before approval:")
    print(json.dumps({"card": session.card, "review": session.review}, indent=2, ensure_ascii=False))
    confirmation = await asyncio.to_thread(
        input, f"\nType APPROVE {card_id} to authorize this exact card and source scope: "
    )
    if confirmation.strip() != f"APPROVE {card_id}":
        return {"status": "not_approved", "reason": "explicit owner confirmation not supplied"}
    actor = (await asyncio.to_thread(
        input, "Owner name/ID for the local audit record (not identity-verified): "
    )).strip()
    if not actor or len(actor) > 240:
        return {"status": "not_approved", "reason": "owner audit label missing or too long"}
    reason = (await asyncio.to_thread(
        input, "Owner reason for selecting these sources/definitions (required): "
    )).strip()
    if not reason or len(reason) > 4000:
        return {"status": "not_approved", "reason": "owner selection reason missing or too long"}
    arguments: dict[str, Any] = {
        "card_id": card_id,
        "actor": actor,
        "use_current_source_selection_review": True,
        "source_selection_reason": reason,
    }
    if adapter:
        arguments["adapter"] = adapter
    try:
        _, result = await native.call_tool("approve_insight_card", arguments)
    except Exception as error:  # preserve a fail-closed approval rejection in the report
        return {
            "status": "approval_rejected",
            "error_type": type(error).__name__,
            "reason": str(error)[:2000],
        }
    if not isinstance(result, dict) or result.get("status") != "approved":
        return {"status": "approval_rejected", "result": result}
    return {
        "status": "approved",
        "card_id": card_id,
        "operator_confirmation": confirmation.strip(),
        "operator_name": actor,
        "source_selection_reason": reason,
        "result": result,
    }


async def run(args: argparse.Namespace) -> None:
    if not args.execute:
        raise SystemExit("No provider calls are made unless --execute is explicitly supplied.")
    owner_context = args.owner_context_file.read_text(encoding="utf-8").strip()
    if not owner_context:
        raise ValueError("owner context file must contain real owner-provided context")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = output / "human-home"
    install = home / ".local" / "bin"
    install.mkdir(mode=0o700, parents=True)
    archive = args.archive.resolve()
    expected = archive.with_name(archive.name + ".sha256").read_text().split()[0]
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError("Downloaded archive checksum does not match")
    with tarfile.open(archive) as package:
        entry = package.getmember("signalweave")
        if not entry.isfile():
            raise ValueError("Expected regular native binary")
        stream = package.extractfile(entry)
        assert stream is not None
        binary = install / "signalweave"
        binary.write_bytes(stream.read())
        binary.chmod(0o700)
    identity = verify_binary(binary)
    key = args.key_file.read_text(encoding="utf-8").strip()
    audit = Audit(path=output / "audit.jsonl", secrets=(key,))
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    env.update(
        HOME=str(home), CODEX_HOME=str(home / ".codex"),
        PATH=str(install) + os.pathsep + env.get("PATH", ""),
        TYPESAFE_MAX_RETRIES="0",
    )
    (home / ".codex").mkdir(mode=0o700)
    result: dict[str, Any] = {
        "binary": identity,
        "archive_sha256": expected,
        "archive_origin": args.archive_origin,
        "trial_scope": "fresh native setup; real Codex with installed shipped skill; paired source tools; live read-only Superset HTTP; explicit human approval; one delivery-disabled card evaluation; direct chart drilldown",
        "questions": list(BUSINESS_QUESTIONS),
        "owner_context_sha256": hashlib.sha256(owner_context.encode("utf-8")).hexdigest(),
        "owner_context_was_supplied_by_operator": True,
        "source_access_accounting": {
            "discovery_tools": sorted(DISCOVERY_TOOLS),
            "direct_data_read_tools": sorted(DATA_READ_TOOLS),
            "direct_data_read_tool_call_cap_per_episode": MAX_DATA_READS,
            "native_onboarding_review_evaluation_internal_reads_instrumented": False,
            "total_warehouse_or_source_cost_comparison_supported": False,
        },
        "limitations": [
            "Northstar is the local seeded Superset fixture, not production customer data.",
            "No expected outcomes, class labels, or numeric thresholds are embedded in the actor prompt.",
            "No external message or schedule is created; a current snapshot is not a recurrence-quality claim.",
            "Shared source-helper HTTP counts exclude native MCP source HTTP and auth/login requests.",
            "Discovery calls (find_dashboards/search_catalog) are tracked separately and do not consume the 60-call data-read cap; read_dashboard, read_chart_rows, and inspect_resource do.",
            "Native MCP source HTTP is not instrumented in these per-tool counters; neither shared-helper HTTP counts nor tool-call counts are a total warehouse-cost measure.",
            "Source requests performed internally by onboard_insight_card, review_insight_card, or evaluate_insight_card do not increment the direct data-read cap and are not instrumented.",
            "Each Codex episode is limited to 20 turns and 60 tool calls; onboarding/evaluation may make additional native source requests outside the shared-helper HTTP counter.",
            "The evaluation transport disables host skill discovery; the installed package skill is supplied verbatim to both arms.",
            "The interactive owner name is an operator-supplied audit label, not an authenticated identity.",
        ],
    }

    def checkpoint():
        (output / "results.json").write_text(json.dumps(audit.redact(result), indent=2, ensure_ascii=False))

    result["wizard"] = terminal_setup(binary, env, key, args.superset_url)
    checkpoint()
    if result["wizard"]["returncode"] or result["wizard"]["pending_prompts"]:
        raise RuntimeError("Native setup did not finish; see redacted results")
    skill, skill_sha = load_installed_skill(home)
    result["skill"] = {
        "installed_path": str(skill_path(home)),
        "sha256": skill_sha,
        "same_verbatim_skill_given_to_both_arms": True,
    }
    inventory = subprocess.run(
        ["codex", "mcp", "list", "--json"], env=env,
        capture_output=True, text=True, timeout=30,
    )
    result["agent_inventory"] = {
        "returncode": inventory.returncode,
        "entries": json.loads(inventory.stdout) if inventory.returncode == 0 else [],
    }
    checkpoint()
    if inventory.returncode or not any(
        item.get("name") == "signalweave" and item.get("enabled")
        for item in result["agent_inventory"]["entries"]
    ):
        raise RuntimeError("Fresh native registration not verified")
    for command in (("status", "--json"), ("health", "--live", "--json")):
        proc = subprocess.run(
            ["signalweave", *command], env=env, cwd=home,
            capture_output=True, text=True, timeout=120,
        )
        result[command[0]] = {
            "returncode": proc.returncode,
            "output": json.loads(proc.stdout) if proc.stdout else {},
        }
        checkpoint()
        if proc.returncode or (command[0] == "health" and not result["health"]["output"].get("healthy")):
            raise RuntimeError(f"Fresh setup {command[0]} check failed")

    prompt = build_actor_prompt(owner_context)

    baseline_adapter = SupersetAdapter(SupersetClient(args.superset_url, "admin", "admin"), tenant_id="local")
    baseline = CardJourneySession(baseline_adapter, stage="baseline")
    result["baseline"] = {
        "episode": await _run_episode(baseline, audit=audit, stage="baseline", prompt=prompt, skill=skill),
        "submission": baseline.submission,
        **_source_budget_summary(baseline),
        "shared_source_helper_http_attempts": baseline.adapter.client.requests_made,
        "shared_source_helper_request_paths": baseline.adapter.client.request_path_counts,
        "shared_tool_names": sorted(SHARED_SOURCE_TOOLS),
    }
    checkpoint()

    async with stdio_client(StdioServerParameters(command=str(binary), args=["serve"], env=env)) as streams:
        async with ClientSession(*streams) as client:
            initialized = await _initialize_mcp_session(client)
            native = InstalledServer(client, initialized.instructions, audit)
            setup_adapter = SupersetAdapter(SupersetClient(args.superset_url, "admin", "admin"), tenant_id="local")
            setup = CardJourneySession(setup_adapter, native, stage="setup")
            setup_episode = await _run_episode(setup, audit=audit, stage="setup", prompt=prompt, skill=skill)
            result["onboarding"] = {
                "episode": setup_episode,
                "submission": setup.submission,
                "card": setup.card,
                "review": setup.review,
                "review_readiness": _review_readiness(setup),
                **_source_budget_summary(setup),
                "shared_source_helper_http_attempts": setup_adapter.client.requests_made,
                "shared_source_helper_request_paths": setup_adapter.client.request_path_counts,
                "shared_tool_names": sorted(SHARED_SOURCE_TOOLS),
                "native_setup_tools": sorted(SETUP_TOOLS),
            }
            checkpoint()
            if setup.submission is None or not _card_id(setup) or setup.review is None:
                result["owner_approval"] = {"status": "not_approved", "reason": "agent did not complete draft and review"}
                checkpoint()
                return

            approval = await _owner_approval(native, setup, setup.review_adapter)
            result["owner_approval"] = approval
            checkpoint()
            if approval.get("status") != "approved":
                return

            monitor_adapter = SupersetAdapter(SupersetClient(args.superset_url, "admin", "admin"), tenant_id="local")
            monitor = CardJourneySession(monitor_adapter, native, stage="monitor")
            monitor_prompt = {
                **prompt,
                "approved_card_id": approval["card_id"],
                "new_idempotency_key": "native-superset-" + secrets.token_hex(12),
            }
            monitor_episode = await _run_episode(
                monitor, audit=audit, stage="monitor", prompt=monitor_prompt, skill=skill
            )
            result["treatment"] = {
                "episode": monitor_episode,
                "submission": monitor.submission,
                "typed_evaluation": monitor.evaluation,
                **_source_budget_summary(monitor),
                "shared_source_helper_http_attempts": monitor_adapter.client.requests_made,
                "shared_source_helper_request_paths": monitor_adapter.client.request_path_counts,
                "shared_tool_names": sorted(SHARED_SOURCE_TOOLS),
                "native_monitor_tools": sorted(MONITOR_TOOLS),
            }
            checkpoint()
    result["binary_after"] = verify_binary(binary)
    checkpoint()
    print(json.dumps({
        "output": str(output),
        "baseline_status": result["baseline"]["episode"].get("status"),
        "onboarding_readiness": result["onboarding"].get("review_readiness"),
        "owner_approval": result.get("owner_approval", {}).get("status"),
        "treatment_status": result.get("treatment", {}).get("episode", {}).get("status"),
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-origin", choices=["github-actions", "local-build"], required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--owner-context-file", type=Path, required=True)
    parser.add_argument("--superset-url", default="http://127.0.0.1:18089")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Explicitly enable live model calls and interactive owner approval")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

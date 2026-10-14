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
import copy
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit
from evaluations.codex_trial_transport import codex_episode
from evaluations.installed_trial_transport import InstalledServer, _initialize_mcp_session
from evaluations.native_human_superset_journey import ReportSession, terminal_setup
from scripts.binary_provenance import verify_binary
from signalweave.models import SourceRef
from signalweave.sources import SourceRegistry
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


def verify_capture_imports() -> dict[str, Any]:
    """Reject mixed checkout imports before credentials, network, or models."""
    checkout = Path(__file__).resolve().parents[1]
    expected = checkout / "src" / "signalweave"
    checked = 0
    for name, module in tuple(sys.modules.items()):
        if name != "signalweave" and not name.startswith("signalweave."):
            continue
        filename = getattr(module, "__file__", None)
        if not filename or not Path(filename).resolve().is_relative_to(expected):
            raise RuntimeError(
                "Mixed SignalWeave checkout imports; run with this checkout's src on "
                "PYTHONPATH or use its uv environment before starting the live trial."
            )
        checked += 1
    return {"checkout": str(checkout), "package_root": str(expected), "modules_checked": checked}
DISCOVERY_TOOLS = frozenset({"find_dashboards", "search_catalog"})
DATA_READ_TOOLS = frozenset({"read_dashboard", "read_chart_rows", "inspect_resource"})
MAX_DATA_READS = 60
MAX_EPISODE_TURNS = 20
MAX_EPISODE_TOOL_CALLS = 60
MAX_PAIRED_REPORT_WORDS = 300
MAX_PAIRED_SNAPSHOT_BYTES = 4_000_000
NATIVE_MAX_SOURCE_SNAPSHOT_BYTES = 1_000_000
MAX_RECEIPT_PAGE_CALLS = 200
MAX_RECEIPT_PATH_DEPTH = 8
RECEIPT_PAGE_LIMIT = 100
MAX_SNAPSHOT_MISMATCH_PATHS = 100
PAIRED_REPETITIONS = 2
PAIRED_POLICY_MODES = ("original_policy", "skill_guided_deferred")
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

PAIRED_BASELINE_INSTRUCTIONS = (
    "This is a paired recurring readout. You receive the exact same owner-reviewed card, review, "
    "owner notes, three questions, and captured Superset source-response snapshot as the other "
    "arm. The snapshot came from real read-only Superset HTTP; it is a set of request-time captures, "
    "not an atomic warehouse snapshot or an as-of guarantee. Use only its approved card scope. "
    "Produce one human-facing readout of at most 300 words, including its panel. Include the three "
    "sections, a compact panel with what the owner asked to watch, actual numeric conditions, "
    "approved sources, and review limits, plus source-linked numeric claims. Do not claim the card "
    "was evaluated or that a typed policy decision exists. Do not assume a quiet, business-change, "
    "or data-quality category; use one only when the source evidence and owner policy support it. "
    "Do not invent thresholds or causes. The frozen source ResourceSnapshots are the shared "
    "baseline evidence. Use their facts when they cover a claim; the shared source tools remain "
    "available for deeper or otherwise needed drilldown, but do not repeat BI reads solely to "
    "duplicate facts already covered. Compare supplemental drilldown with the frozen snapshots "
    "and report conflicts rather than silently choosing one. Cite the captured source titles/links and "
    "periods. Finish with submit_report, then stop."
)

PAIRED_TREATMENT_PREFIX = (
    "This is a paired recurring readout using the same owner-reviewed card, review, owner notes, "
    "three questions, and captured Superset source-response snapshot as the baseline. The shared "
    "snapshot consists of real read-only Superset HTTP responses captured at request time; it is "
    "not an atomic warehouse snapshot or an as-of guarantee. Use source facts from the evaluation "
    "receipt when they cover a claim; its ResourceSnapshots are the same frozen snapshots exposed "
    "through the shared source tools. Those tools remain equally available for deeper or otherwise "
    "needed drilldown, but do not repeat BI reads solely to duplicate covered facts. Compare any "
    "supplemental drilldown with the frozen snapshots and report conflicts rather than silently "
    "choosing one. Produce one human-facing readout of at most "
    "300 words including a compact card panel with actual outcome/judgment status (or no judgment), "
    "numeric-condition statuses, and approved-source coverage/limits; then answer the three "
    "business questions with cited numeric/source claims. Keep any typed judgment separate from "
    "source facts. A deferred judgment is not a policy "
    "outcome; never invent one. Do not assume a quiet, business-change, or data-quality category; "
    "use one only when source evidence and owner policy support it. Do not invent thresholds or causes. "
)

PAIRED_TREATMENT_MODES = {
    "original_policy": (
        "Apply the original card policy path: call evaluate_insight_card once with the supplied "
        "idempotency key. If the result is deferred, state that no typed judgment was produced; "
        "do not consume deferred receipt pages in this mode. Continue only from the same shared "
        "source tools and clearly separate the missing judgment from evidence."
    ),
    "skill_guided_deferred": (
        "Apply the shipped-skill deferred path: call evaluate_insight_card once with the supplied "
        "idempotency key. If result.judgment.status is deferred, that is no typed policy outcome. "
        "Follow the installed skill and the returned root-level evidence_access pointers, starting "
        "with any included observation_facts. The approved source ResourceSnapshots are already "
        "frozen for both arms; the shared source tools remain equally available for deeper or needed "
        "drilldown. Do not repeat BI reads only to duplicate facts already covered by those snapshots. "
        "Page only a specific omitted contract, quality detail, or observation "
        "attribute needed to support a claim or resolve a material unknown; do not exhaustively fetch "
        "source_by_key, source_contracts, and duplicate observation/evidence representations. "
        "Do not force a policy result or use readout facts to alter the card policy. If a typed "
        "judgment is returned instead, report it as-is."
    ),
}


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
    elif stage == "paired-baseline":
        task_rules = PAIRED_BASELINE_INSTRUCTIONS
    elif stage.startswith("paired-treatment-"):
        mode = stage.removeprefix("paired-treatment-")
        if mode not in PAIRED_TREATMENT_MODES:
            raise ValueError(f"unknown paired treatment policy mode: {mode}")
        task_rules = PAIRED_TREATMENT_PREFIX + PAIRED_TREATMENT_MODES[mode] + " Finish with submit_report, then stop."
    else:
        raise ValueError(f"unknown journey stage: {stage}")
    common = (
        "You are a business-intelligence analyst using the trial's captured, read-only Superset "
        "source-response snapshot. The business owner supplied the context in the task; do not "
        "invent metric definitions, comparison windows, thresholds, recipients, or desired outcomes. "
        "Answer all three questions from inspected evidence. Treat returned periods and comparison "
        "coverage exactly as reported; a recent bucket is not proof of a complete/comparable period. "
        "The shared read-only source tools remain equally available for deeper or needed drilldown "
        "inside the approved card scope. The dashboard source snapshot is frozen and shared across "
        "arms; use its facts when they cover a claim, without repeating reads just to duplicate them. "
        "Supplemental saved-chart query rows are separately captured and replayed identically; label "
        "their query scope and report conflicts with the ResourceSnapshot rather than silently "
        "choosing one. Missing evidence is a gap, not permission to expand scope. "
        "Keep observed facts separate from hypotheses; request-time capture timestamps are not "
        "warehouse freshness. Cite source titles/links and periods. No messages or schedules. Use "
        "only the supplied trial tools; no shell, web, filesystem, or other tools."
        if stage.startswith("paired-") else COMMON_INSTRUCTIONS
    )
    return (
        common
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


def build_paired_prompt(
    *,
    owner_context: str,
    card: dict[str, Any],
    review: dict[str, Any],
    owner_notes: str,
    snapshot: dict[str, Any],
    repeat: int,
    policy_mode: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if repeat not in {1, 2}:
        raise ValueError("paired recurring readouts are limited to two repeats")
    prompt: dict[str, Any] = {
        "request": (
            "Prepare one concise, source-backed readout using the same captured source responses "
            f"for repeat {repeat}; this is a repeat analysis of one captured dataset, not a new "
            "reporting period. Answer these same three questions:\n"
            + "\n".join(
                f"{index}. {question}"
                for index, question in enumerate(BUSINESS_QUESTIONS, 1)
            )
            + "\nThe final report must be at most 300 words, include a compact card panel with the "
            "owner's actual numeric conditions (if any), and cite source-backed numeric claims."
        ),
        "owner_context": owner_context,
        "reviewed_card": copy.deepcopy(card),
        "source_review": copy.deepcopy(review),
        "owner_notes": owner_notes,
        "source_snapshot": {
            "sha256": snapshot["snapshot_sha256"],
            "captured_at_started": snapshot["captured_at_started"],
            "captured_at_finished": snapshot["captured_at_finished"],
            "timestamps_are_query_capture_times_not_warehouse_as_of": True,
        },
        "source_environment": "Real read-only Superset HTTP response snapshot from the approved card scope; no external delivery.",
    }
    if policy_mode is not None:
        if policy_mode not in PAIRED_POLICY_MODES or not idempotency_key:
            raise ValueError("treatment prompts require a known policy mode and idempotency key")
        prompt["approved_card_id"] = card.get("id")
        prompt["new_idempotency_key"] = idempotency_key
        prompt["paired_policy_mode"] = policy_mode
    return prompt


def card_panel(
    evaluation: dict[str, Any] | None,
    *,
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract a compact, non-inventive policy panel from the native response."""
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    receipt = evaluation.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    result = evaluation.get("result")
    result = result if isinstance(result, dict) else {}
    judgment_state = result.get("judgment_state")
    judgment_state = judgment_state if isinstance(judgment_state, dict) else {}
    judgment = result.get("judgment")
    judgment = judgment if isinstance(judgment, dict) else {}
    numeric_conditions = result.get("numeric_conditions")
    if numeric_conditions is None:
        numeric_conditions = judgment_state.get(
            "numeric_conditions", (card or {}).get("numeric_conditions")
        )
    receipt_status = receipt.get("status")
    judgment_status = judgment.get("status")
    deferred = receipt_status == "decision_deferred" or judgment_status == "deferred"
    failed_without_judgment = receipt_status == "failed" or bool(result.get("error"))
    return {
        "receipt_status": receipt_status,
        "judgment_status": (
            "deferred" if deferred else
            "failed_no_judgment" if failed_without_judgment else judgment_status
        ),
        "outcome": None if deferred or failed_without_judgment else result.get("outcome", receipt.get("outcome")),
        "probabilities": None if deferred or failed_without_judgment else result.get("probabilities"),
        "input_budget": judgment.get("input_budget"),
        "provider_call_attempts": judgment.get("provider_call_attempts"),
        "provider_call_attempt_scope": judgment.get("attempt_scope"),
        "provider_call_attempted": judgment.get("provider_call_attempted"),
        "provider_attempt_fields_semantics": (
            "Reported current-judgment attempts only; this does not confirm provider receipt or billing."
        ),
        "receipt_id": receipt.get("receipt_id"),
        "source_keys": result.get("source_keys"),
        "source_contracts": result.get("source_contracts"),
        "evidence_access": evaluation.get("evidence_access"),
        "numeric_conditions": numeric_conditions,
        "approved_sources": [
            {key: source.get(key) for key in ("key", "adapter", "resource", "label")}
            for source in (card or {}).get("sources", [])
            if isinstance(source, dict)
        ],
    }


_BUSINESS_SNAPSHOT_FIELDS = (
    "observations", "analytical_comparisons", "evidence", "error",
)
_SOURCE_DEFINITION_FIELDS = (
    "source_key", "adapter", "resource", "title", "description",
    "metadata", "source_url", "source_captured_at", "contract",
)
_RESOURCE_SNAPSHOT_FIELDS = (
    "source_key", "adapter", "resource", "title", "description",
    "observations", "analytical_comparisons", "evidence", "metadata",
    "error", "source_url", "captured_at", "source_captured_at", "contract",
)


def _digest_json(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _full_snapshot_digest(snapshot: dict[str, Any]) -> str:
    """Digest the exact serialized ResourceSnapshot, including capture times."""
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_digest_pair(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        "business_data_sha256": _digest_json({
            key: snapshot.get(key) for key in _BUSINESS_SNAPSHOT_FIELDS
        }),
        "source_definition_sha256": _digest_json({
            key: snapshot.get(key) for key in _SOURCE_DEFINITION_FIELDS
        }),
    }


def _snapshot_field_statuses(
    helper: dict[str, Any], native: dict[str, Any], fields: tuple[str, ...],
) -> dict[str, str]:
    return {
        field: (
            "equal"
            if field in helper and field in native
            and _digest_json(helper[field]) == _digest_json(native[field])
            else "different"
        )
        for field in fields
    }


def _snapshot_mismatch_paths(
    helper: dict[str, Any],
    native: dict[str, Any],
    fields: tuple[str, ...],
    *,
    max_paths: int = MAX_SNAPSHOT_MISMATCH_PATHS,
) -> dict[str, dict[str, Any]]:
    """Return bounded JSON paths only; never copy mismatching source values."""
    missing = object()
    differences: dict[str, dict[str, Any]] = {}

    def pointer(parts: list[str | int]) -> str:
        return "/" + "/".join(
            str(part).replace("~", "~0").replace("/", "~1") for part in parts
        )

    for field in fields:
        left = helper.get(field, missing)
        right = native.get(field, missing)
        if left is not missing and right is not missing and _digest_json(left) == _digest_json(right):
            continue
        paths: list[str] = []
        truncated = False

        def visit(a: Any, b: Any, parts: list[str | int], paths: list[str]) -> None:
            nonlocal truncated
            if len(paths) >= max_paths:
                truncated = True
                return
            if a is missing or b is missing:
                paths.append(pointer(parts))
                return
            if isinstance(a, dict) and isinstance(b, dict):
                keys = sorted(set(a) | set(b), key=str)
                for key in keys:
                    if len(paths) >= max_paths:
                        truncated = True
                        return
                    visit(a.get(key, missing), b.get(key, missing), [*parts, str(key)], paths)
                return
            if isinstance(a, list) and isinstance(b, list):
                for index in range(max(len(a), len(b))):
                    if len(paths) >= max_paths:
                        truncated = True
                        return
                    visit(
                        a[index] if index < len(a) else missing,
                        b[index] if index < len(b) else missing,
                        [*parts, index],
                        paths,
                    )
                return
            if type(a) is not type(b) or a != b:
                paths.append(pointer(parts))

        visit(left, right, [field], paths)
        if paths:
            differences[field] = {"paths": paths, "truncated": truncated}
    return differences


def compare_paired_source_snapshots(
    helper_by_key: dict[str, dict[str, Any]],
    native_by_key: dict[str, dict[str, Any]] | None,
    *,
    native_status: str,
    receipt_page_calls: int = 0,
    helper_status: str = "available",
    native_issue: dict[str, Any] | None = None,
    helper_issue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare only matching typed source snapshots; never infer parity from absence."""
    comparison: dict[str, Any] = {
        "status": "unverified",
        "native_snapshot_status": native_status,
        "native_snapshot_issue": native_issue,
        "helper_snapshot_status": helper_status,
        "helper_snapshot_issue": helper_issue,
        "receipt_page_calls": receipt_page_calls,
        "receipt_reads_are_local_read_only_and_do_not_rerun_sources_or_models": True,
        "capture_times_excluded_from_digests": ["/captured_at (ResourceSnapshot receive time only)"],
        "business_data_digest_scope": list(_BUSINESS_SNAPSHOT_FIELDS),
        "source_definition_digest_scope": list(_SOURCE_DEFINITION_FIELDS),
        "source_definition_limit": (
            "ResourceSnapshot identity, metadata (including chart cache status), source_captured_at, "
            "and contract are compared. Raw saved-chart query params are not in the native receipt; "
            "they remain present in the shared frozen helper snapshot and are identical to both arms."
        ),
        "helper_snapshot_is_frozen_but_native_evaluation_uses_separate_live_reads": True,
        "parity_gate_requires_all_resource_snapshot_fields_equal_before_readout_episodes": True,
        "atomic_warehouse_snapshot_or_total_source_cost_claim": False,
        "per_source": {},
    }
    if native_by_key is None or helper_status != "available":
        return comparison

    helper_keys = set(helper_by_key)
    native_keys = set(native_by_key)
    comparison["helper_source_keys"] = sorted(helper_keys)
    comparison["native_source_keys"] = sorted(native_keys)
    for key in sorted(helper_keys | native_keys):
        helper = helper_by_key.get(key)
        native = native_by_key.get(key)
        if not isinstance(helper, dict) or not isinstance(native, dict):
            comparison["per_source"][key] = {
                "business_data_status": "unverified",
                "source_definition_status": "unverified",
            }
            continue
        helper_missing = sorted(set(_RESOURCE_SNAPSHOT_FIELDS) - set(helper))
        native_missing = sorted(set(_RESOURCE_SNAPSHOT_FIELDS) - set(native))
        if helper_missing or native_missing:
            comparison["per_source"][key] = {
                "business_data_status": "unverified",
                "source_definition_status": "unverified",
                "snapshot_completeness": {
                    "status": "incomplete",
                    "helper_missing_fields": helper_missing,
                    "native_missing_fields": native_missing,
                },
            }
            continue
        helper_digests = _snapshot_digest_pair(helper)
        native_digests = _snapshot_digest_pair(native)
        comparison["per_source"][key] = {
            "business_data_status": (
                "equal" if helper_digests["business_data_sha256"] == native_digests["business_data_sha256"]
                else "different"
            ),
            "snapshot_completeness": {"status": "complete"},
            "source_definition_status": (
                "equal" if helper_digests["source_definition_sha256"] == native_digests["source_definition_sha256"]
                else "different"
            ),
            "business_data_fields": _snapshot_field_statuses(
                helper, native, _BUSINESS_SNAPSHOT_FIELDS,
            ),
            "business_data_mismatch_paths": _snapshot_mismatch_paths(
                helper, native, _BUSINESS_SNAPSHOT_FIELDS,
            ),
            "source_definition_fields": _snapshot_field_statuses(
                helper, native, _SOURCE_DEFINITION_FIELDS,
            ),
            "source_definition_mismatch_paths": _snapshot_mismatch_paths(
                helper, native, _SOURCE_DEFINITION_FIELDS,
            ),
            "helper_digests": helper_digests,
            "native_digests": native_digests,
        }

    def aggregate(field: str) -> str:
        statuses = [item[field] for item in comparison["per_source"].values()]
        if not statuses or "unverified" in statuses:
            return "unverified"
        if "different" in statuses:
            return "different"
        return "equal"

    comparison["business_data_status"] = aggregate("business_data_status")
    comparison["source_definition_status"] = aggregate("source_definition_status")
    comparison["status"] = (
        "different"
        if helper_keys != native_keys
        or "different" in {
            comparison["business_data_status"], comparison["source_definition_status"],
        }
        else "equal"
        if comparison["business_data_status"] == comparison["source_definition_status"] == "equal"
        else "unverified"
    )
    return comparison


class ReceiptPageReadError(RuntimeError):
    def __init__(self, reason: str, path: list[str], *, error_type: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.path = list(path)
        self.error_type = error_type


class ReceiptPageReader:
    """Reassemble only requested receipt subtrees from byte-bounded result pages."""

    def __init__(
        self,
        native: InstalledServer,
        *,
        max_calls: int = MAX_RECEIPT_PAGE_CALLS,
    ) -> None:
        self.native = native
        self.max_calls = max_calls
        self.calls = 0
        self.elapsed_seconds = 0.0
        self.idempotency_key: str | None = None
        self.expected_receipt_id: str | None = None

    def select_receipt(self, idempotency_key: str, receipt_id: str | None = None) -> None:
        if not idempotency_key:
            raise ValueError("receipt paging requires the saved idempotency key")
        self.idempotency_key = idempotency_key
        self.expected_receipt_id = receipt_id

    async def _page(self, path: list[str], offset: int) -> dict[str, Any]:
        if not 1 <= len(path) <= MAX_RECEIPT_PATH_DEPTH:
            raise ReceiptPageReadError("result_path_depth_exceeded", path)
        if self.calls >= self.max_calls:
            raise ReceiptPageReadError("receipt_page_call_budget_exhausted", path)
        if not self.idempotency_key:
            raise ReceiptPageReadError("idempotency_key_unavailable", path)
        started = time.perf_counter()
        try:
            _, response = await self.native.call_tool("get_decision_receipt", {
                "idempotency_key": self.idempotency_key,
                "result_path": path,
                "offset": offset,
                "limit": RECEIPT_PAGE_LIMIT,
            })
        except Exception as error:  # noqa: BLE001 - retain only safe failure metadata
            self.calls += 1
            self.elapsed_seconds += time.perf_counter() - started
            raise ReceiptPageReadError(
                "receipt_page_read_failed", path, error_type=type(error).__name__
            ) from None
        self.calls += 1
        self.elapsed_seconds += time.perf_counter() - started
        if not isinstance(response, dict) or response.get("status") != "found":
            raise ReceiptPageReadError("receipt_not_found", path)
        receipt = response.get("receipt")
        if not isinstance(receipt, dict):
            raise ReceiptPageReadError("receipt_metadata_missing", path)
        if receipt.get("idempotency_key") != self.idempotency_key:
            raise ReceiptPageReadError("idempotency_key_mismatch", path)
        if (
            self.expected_receipt_id is not None
            and receipt.get("receipt_id") != self.expected_receipt_id
        ):
            raise ReceiptPageReadError("receipt_id_mismatch", path)
        page = response.get("result_page")
        if (
            not isinstance(page, dict)
            or page.get("path") != path
            or page.get("offset") != offset
        ):
            raise ReceiptPageReadError("malformed_receipt_page", path)
        return page

    async def read_object_keys(self, path: list[str]) -> list[str]:
        keys: list[str] = []
        offset = 0
        total: int | None = None
        for _ in range(self.max_calls + 1):
            page = await self._page(path, offset)
            if page.get("kind") != "object" or not isinstance(page.get("items"), list):
                raise ReceiptPageReadError("expected_object_page", path)
            page_total = page.get("total")
            if isinstance(page_total, bool) or not isinstance(page_total, int):
                raise ReceiptPageReadError("malformed_page_total", path)
            if total is None:
                total = page_total
            elif total != page_total:
                raise ReceiptPageReadError("page_total_changed", path)
            items = page["items"]
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                    raise ReceiptPageReadError("malformed_object_entry", path)
                keys.append(item["key"])
            oversized = page.get("oversized_item")
            if oversized is not None:
                child_path = oversized.get("path") if isinstance(oversized, dict) else None
                index = oversized.get("index") if isinstance(oversized, dict) else None
                if (
                    not isinstance(child_path, list)
                    or len(child_path) != len(path) + 1
                    or child_path[:-1] != path
                    or not isinstance(child_path[-1], str)
                    or isinstance(index, bool)
                    or not isinstance(index, int)
                    or index != offset + len(items)
                ):
                    raise ReceiptPageReadError("malformed_oversized_branch", path)
                keys.append(child_path[-1])
                offset = index + 1
                continue
            if not page.get("has_more"):
                if total is None or len(keys) != total or len(set(keys)) != total:
                    raise ReceiptPageReadError("object_keys_incomplete", path)
                return keys
            next_offset = page.get("next_offset")
            if (
                not items
                or next_offset != offset + len(items)
                or next_offset <= offset
            ):
                raise ReceiptPageReadError("object_page_did_not_advance", path)
            offset = next_offset
        raise ReceiptPageReadError("receipt_page_call_budget_exhausted", path)

    async def read_value(self, path: list[str]) -> Any:
        if not 1 <= len(path) <= MAX_RECEIPT_PATH_DEPTH:
            raise ReceiptPageReadError("result_path_depth_exceeded", path)
        first = await self._page(path, 0)
        kind = first.get("kind")
        total = first.get("total")
        items = first.get("items")
        if kind not in {"object", "list", "scalar"} or not isinstance(items, list):
            raise ReceiptPageReadError("malformed_receipt_page", path)
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ReceiptPageReadError("malformed_page_total", path)
        if kind == "scalar":
            if first.get("oversized_item") is not None:
                raise ReceiptPageReadError("oversized_scalar_unreadable", path)
            if total != 1 or len(items) != 1 or first.get("has_more"):
                raise ReceiptPageReadError("scalar_page_incomplete", path)
            return items[0]

        object_values: dict[str, Any] = {}
        list_values: dict[int, Any] = {}
        offset = 0
        page = first
        while True:
            if page.get("kind") != kind or page.get("total") != total:
                raise ReceiptPageReadError("page_shape_changed", path)
            items = page.get("items")
            if not isinstance(items, list):
                raise ReceiptPageReadError("malformed_page_items", path)
            for relative_index, item in enumerate(items):
                absolute_index = offset + relative_index
                if kind == "object":
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get("key"), str)
                        or "value" not in item
                        or item["key"] in object_values
                    ):
                        raise ReceiptPageReadError("malformed_object_entry", path)
                    object_values[item["key"]] = item["value"]
                else:
                    if absolute_index in list_values:
                        raise ReceiptPageReadError("duplicate_list_index", path)
                    list_values[absolute_index] = item

            oversized = page.get("oversized_item")
            if oversized is not None:
                child_path = oversized.get("path") if isinstance(oversized, dict) else None
                index = oversized.get("index") if isinstance(oversized, dict) else None
                if (
                    not isinstance(child_path, list)
                    or len(child_path) != len(path) + 1
                    or child_path[:-1] != path
                    or isinstance(index, bool)
                    or not isinstance(index, int)
                    or index != offset + len(items)
                    or (kind == "object" and not isinstance(child_path[-1], str))
                    or (
                        kind == "list"
                        and (not child_path[-1].isascii() or not child_path[-1].isdecimal()
                             or int(child_path[-1]) != index)
                    )
                ):
                    raise ReceiptPageReadError("malformed_oversized_branch", path)
                nested = await self.read_value(child_path)
                if kind == "object":
                    key = child_path[-1]
                    if key in object_values:
                        raise ReceiptPageReadError("duplicate_object_key", child_path)
                    object_values[key] = nested
                else:
                    if index in list_values:
                        raise ReceiptPageReadError("duplicate_list_index", child_path)
                    list_values[index] = nested
                offset = index + 1
            elif page.get("has_more"):
                next_offset = page.get("next_offset")
                if (
                    not items
                    or next_offset != offset + len(items)
                    or next_offset <= offset
                ):
                    raise ReceiptPageReadError("page_did_not_advance", path)
                offset = next_offset
            else:
                values_count = len(object_values) if kind == "object" else len(list_values)
                if values_count != total:
                    raise ReceiptPageReadError("section_incomplete", path)
                if kind == "object":
                    return object_values
                if set(list_values) != set(range(total)):
                    raise ReceiptPageReadError("list_indexes_incomplete", path)
                return [list_values[index] for index in range(total)]
            page = await self._page(path, offset)

    async def read_selected_object(
        self,
        path: list[str],
        selected_fields: tuple[str, ...],
    ) -> dict[str, Any]:
        selected = set(selected_fields)
        values: dict[str, Any] = {}
        seen: set[str] = set()
        offset = 0
        total: int | None = None
        for _ in range(self.max_calls + 1):
            page = await self._page(path, offset)
            if page.get("kind") != "object" or not isinstance(page.get("items"), list):
                raise ReceiptPageReadError("expected_object_page", path)
            page_total = page.get("total")
            if isinstance(page_total, bool) or not isinstance(page_total, int):
                raise ReceiptPageReadError("malformed_page_total", path)
            if total is None:
                total = page_total
            elif total != page_total:
                raise ReceiptPageReadError("page_total_changed", path)
            items = page["items"]
            for item in items:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("key"), str)
                    or "value" not in item
                    or item["key"] in seen
                ):
                    raise ReceiptPageReadError("malformed_object_entry", path)
                key = item["key"]
                seen.add(key)
                if key in selected:
                    values[key] = item["value"]
            oversized = page.get("oversized_item")
            if oversized is not None:
                child_path = oversized.get("path") if isinstance(oversized, dict) else None
                index = oversized.get("index") if isinstance(oversized, dict) else None
                if (
                    not isinstance(child_path, list)
                    or len(child_path) != len(path) + 1
                    or child_path[:-1] != path
                    or not isinstance(child_path[-1], str)
                    or isinstance(index, bool)
                    or not isinstance(index, int)
                    or index != offset + len(items)
                    or child_path[-1] in seen
                ):
                    raise ReceiptPageReadError("malformed_oversized_branch", path)
                key = child_path[-1]
                seen.add(key)
                if key in selected:
                    values[key] = await self.read_value(child_path)
                offset = index + 1
            elif page.get("has_more"):
                next_offset = page.get("next_offset")
                if not items or next_offset != offset + len(items) or next_offset <= offset:
                    raise ReceiptPageReadError("page_did_not_advance", path)
                offset = next_offset
            else:
                if total is None or len(seen) != total:
                    raise ReceiptPageReadError("object_section_incomplete", path)
                missing = selected - values.keys()
                if missing:
                    missing_key = sorted(missing)[0]
                    raise ReceiptPageReadError("snapshot_field_missing", [*path, missing_key])
                return {key: values[key] for key in selected_fields}
        raise ReceiptPageReadError("receipt_page_call_budget_exhausted", path)


_SOURCE_SNAPSHOT_FIELDS = _RESOURCE_SNAPSHOT_FIELDS


def _complete_resource_snapshot_map(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(snapshot, dict)
            and set(_RESOURCE_SNAPSHOT_FIELDS) <= set(snapshot)
            for snapshot in value.values()
        )
    )


async def native_source_snapshots_for_comparison(
    native: InstalledServer,
    evaluation: dict[str, Any] | None,
    *,
    idempotency_key: str | None = None,
    reader: ReceiptPageReader | None = None,
) -> tuple[dict[str, dict[str, Any]] | None, str, int, dict[str, Any] | None]:
    """Read only typed ResourceSnapshot fields from a saved deferred receipt."""
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    result = evaluation.get("result")
    result = result if isinstance(result, dict) else {}
    direct = result.get("source_by_key")
    if _complete_resource_snapshot_map(direct):
        return direct, "available_in_evaluation", 0, None

    receipt = evaluation.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    key = idempotency_key or receipt.get("idempotency_key")
    if not isinstance(key, str) or not key:
        return None, "receipt_idempotency_key_unavailable", 0, None

    page_reader = reader or ReceiptPageReader(native)
    page_reader.select_receipt(key, receipt.get("receipt_id"))
    calls_before = page_reader.calls
    try:
        source_keys = await page_reader.read_object_keys(["source_by_key"])
        sources = {
            source_key: await page_reader.read_selected_object(
                ["source_by_key", source_key], _SOURCE_SNAPSHOT_FIELDS
            )
            for source_key in source_keys
        }
    except ReceiptPageReadError as error:
        issue = {"reason": error.reason, "path": error.path}
        if error.error_type:
            issue["error_type"] = error.error_type
        return None, "unverified_receipt_source_snapshot", page_reader.calls - calls_before, issue
    return (
        sources,
        (
            "available_from_deferred_receipt"
            if (receipt.get("status") == "decision_deferred"
                or (isinstance(result.get("judgment"), dict)
                    and result["judgment"].get("status") == "deferred"))
            else "available_from_decision_receipt"
        ),
        page_reader.calls - calls_before,
        None,
    )


def helper_source_snapshots_by_key(
    snapshot: PairedSourceSnapshot,
    card: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Join frozen dashboard ResourceSnapshots to the exact approved card aliases."""
    sources: dict[str, dict[str, Any]] = {}
    for source in card.get("sources", []):
        if not isinstance(source, dict):
            continue
        key = source.get("key")
        resource = source.get("resource")
        if not isinstance(key, str) or not isinstance(resource, str):
            continue
        dashboard_id = resource.removeprefix("dashboard:")
        item = snapshot.dashboards.get(dashboard_id)
        if isinstance(item, dict):
            sources[key] = item
    return sources


def validate_source_snapshots_for_card(
    sources: dict[str, dict[str, Any]] | None,
    card: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Require complete typed snapshots for exactly the approved source aliases."""
    refs = [SourceRef.model_validate(item) for item in card.get("sources", [])]
    expected = {source.key: source for source in refs}
    if not expected or sources is None or set(sources) != set(expected):
        raise ValueError("preflight ResourceSnapshots do not cover exactly the approved source aliases")
    validated: dict[str, dict[str, Any]] = {}
    for key, source in expected.items():
        snapshot = sources[key]
        if not isinstance(snapshot, dict) or not set(_RESOURCE_SNAPSHOT_FIELDS) <= set(snapshot):
            raise ValueError(f"preflight ResourceSnapshot is incomplete for approved alias {key}")
        if (
            snapshot.get("source_key") != key
            or snapshot.get("adapter") != source.adapter
            or snapshot.get("resource") != source.resource
        ):
            raise ValueError(f"preflight ResourceSnapshot identity differs for approved alias {key}")
        validated[key] = copy.deepcopy(snapshot)
    return validated


async def run_native_preflight(
    native: InstalledServer,
    *,
    card: dict[str, Any],
    idempotency_key: str,
    reader: ReceiptPageReader,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]] | None, str, int, dict[str, Any] | None]:
    """Make the one paid evaluation before readout agents; retain source snapshots only for baseline."""
    card_id = card.get("id")
    if not isinstance(card_id, str) or not card_id:
        raise ValueError("approved card id is required for paired preflight")
    started = time.perf_counter()
    _, evaluation = await native.call_tool("evaluate_insight_card", {
        "card_id": card_id,
        "idempotency_key": idempotency_key,
        "response_mode": "compact",
    })
    evaluation_seconds = time.perf_counter() - started
    if not isinstance(evaluation, dict):
        raise RuntimeError("native preflight returned no structured evaluation")
    receipt = evaluation.get("receipt")
    if (
        not isinstance(receipt, dict)
        or receipt.get("idempotency_key") != idempotency_key
        or receipt.get("card_id") != card_id
        or evaluation.get("replayed") is not False
    ):
        raise RuntimeError("native preflight did not create the expected fresh card receipt")
    sources, status, page_calls, issue = await native_source_snapshots_for_comparison(
        native,
        evaluation,
        idempotency_key=idempotency_key,
        reader=reader,
    )
    if sources is not None:
        try:
            sources = validate_source_snapshots_for_card(sources, card)
        except ValueError as error:
            sources = None
            status = "unverified_preflight_resource_snapshots"
            issue = {"reason": str(error)}
    result = evaluation.get("result")
    result = result if isinstance(result, dict) else {}
    judgment = result.get("judgment")
    judgment = judgment if isinstance(judgment, dict) else {}
    summary = {
        "status": "source_snapshots_available" if sources is not None else "source_snapshots_unverified",
        "idempotency_key": idempotency_key,
        "receipt_id": receipt.get("receipt_id"),
        "receipt_status": receipt.get("status"),
        "replayed": evaluation.get("replayed"),
        "native_evaluate_tool_calls": 1,
        "native_evaluate_wall_seconds": evaluation_seconds,
        "source_snapshot_status": status,
        "source_snapshot_keys": sorted(sources) if sources is not None else None,
        "receipt_snapshot_page_calls": page_calls,
        "receipt_snapshot_page_elapsed_seconds": reader.elapsed_seconds,
        "reported_provider_call_attempts": judgment.get("provider_call_attempts"),
        "reported_provider_call_attempt_scope": judgment.get("attempt_scope"),
        "reported_provider_call_attempted": judgment.get("provider_call_attempted"),
        "provider_attempt_fields_are_not_billing_or_provider_receipt_confirmation": True,
        "native_superset_internal_http_attempts": None,
        "native_superset_internal_http_attempts_note": "The evaluation API does not expose its adapter HTTP attempt count; unknown is not zero.",
        "issue": issue,
    }
    return summary, sources, status, page_calls, issue


def helper_source_snapshots_from_audit(
    audit_path: Path,
    approved_sources: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], str, dict[str, Any] | None, dict[str, int]]:
    """Recover only baseline read_dashboard snapshots; reject missing or conflicting repeats."""
    expected = {
        source.get("key"): source.get("resource")
        for source in approved_sources
        if isinstance(source, dict)
        and isinstance(source.get("key"), str)
        and isinstance(source.get("resource"), str)
    }
    snapshots: dict[str, dict[str, Any]] = {}
    digests: dict[str, dict[str, str]] = {}
    counts: dict[str, int] = {}
    malformed_lines = 0
    with audit_path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if (
                not isinstance(event, dict)
                or event.get("kind") != "tool.result"
                or event.get("episode") != "paired-baseline"
                or event.get("name") != "read_dashboard"
            ):
                continue
            snapshot = event.get("result")
            if not isinstance(snapshot, dict):
                continue
            key = snapshot.get("source_key")
            if key not in expected or snapshot.get("resource") != expected[key]:
                continue
            snapshot_digests = _snapshot_digest_pair(snapshot)
            counts[key] = counts.get(key, 0) + 1
            if key in digests and digests[key] != snapshot_digests:
                return snapshots, "conflicting", {
                    "reason": "replayed_helper_snapshot_digest_changed",
                    "source_key": key,
                }, counts
            snapshots.setdefault(key, snapshot)
            digests.setdefault(key, snapshot_digests)
    missing = sorted(set(expected) - set(snapshots))
    if malformed_lines or missing:
        return snapshots, "incomplete", {
            "reason": "helper_audit_snapshot_missing_or_malformed",
            "missing_source_keys": missing,
            "malformed_line_count": malformed_lines,
        }, counts
    if not expected:
        return {}, "incomplete", {"reason": "approved_source_scope_missing"}, counts
    return snapshots, "available", None, counts


def source_tool_snapshot_parity_from_events(
    events: list[dict[str, Any]],
    approved_sources: list[dict[str, Any]],
    *,
    expected_modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Verify both agent arms received the same full replayed ResourceSnapshots."""
    expected = {
        source.get("key"): source.get("resource")
        for source in approved_sources
        if isinstance(source, dict)
        and isinstance(source.get("key"), str)
        and isinstance(source.get("resource"), str)
    }
    samples: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for event in events:
        if (
            not isinstance(event, dict)
            or event.get("kind") != "tool.result"
            or event.get("name") != "read_dashboard"
        ):
            continue
        episode = event.get("episode")
        if episode == "paired-baseline":
            arm = "baseline"
        elif isinstance(episode, str) and episode.startswith("paired-treatment-"):
            arm = episode.removeprefix("paired-treatment-")
        else:
            continue
        snapshot = event.get("result")
        if not isinstance(snapshot, dict):
            continue
        key = snapshot.get("source_key")
        if key not in expected or snapshot.get("resource") != expected[key]:
            continue
        samples.setdefault(arm, {}).setdefault(key, {}).setdefault(
            _full_snapshot_digest(snapshot), snapshot
        )
        counts.setdefault(arm, {})[key] = counts.setdefault(arm, {}).get(key, 0) + 1

    modes = sorted(mode for mode in samples if mode != "baseline")
    per_mode: dict[str, Any] = {}
    for mode in modes:
        per_source: dict[str, Any] = {}
        semantic_comparison = compare_paired_source_snapshots(
            {
                key: next(iter(versions.values()))
                for key, versions in samples.get("baseline", {}).items()
                if versions
            },
            {
                key: next(iter(versions.values()))
                for key, versions in samples.get(mode, {}).items()
                if versions
            },
            native_status="audited_shared_source_tool_replay",
        )
        for key in sorted(expected):
            baseline_versions = samples.get("baseline", {}).get(key, {})
            treatment_versions = samples.get(mode, {}).get(key, {})
            if not baseline_versions or not treatment_versions:
                status = "unverified"
            elif (
                len(baseline_versions) == 1
                and len(treatment_versions) == 1
                and set(baseline_versions) == set(treatment_versions)
            ):
                status = "equal"
            else:
                status = "different"
            field_comparison = semantic_comparison.get("per_source", {}).get(key, {})
            per_source[key] = {
                "status": status,
                "baseline_read_count": counts.get("baseline", {}).get(key, 0),
                "treatment_read_count": counts.get(mode, {}).get(key, 0),
                "baseline_snapshot_sha256": next(iter(baseline_versions), None),
                "treatment_snapshot_sha256": next(iter(treatment_versions), None),
                "business_data_fields": field_comparison.get("business_data_fields"),
                "business_data_mismatch_paths": field_comparison.get("business_data_mismatch_paths"),
                "source_definition_fields": field_comparison.get("source_definition_fields"),
                "source_definition_mismatch_paths": field_comparison.get("source_definition_mismatch_paths"),
            }
        statuses = [item["status"] for item in per_source.values()]
        mode_status = (
            "different" if "different" in statuses
            else "unverified" if not statuses or "unverified" in statuses
            else "equal"
        )
        per_mode[mode] = {"status": mode_status, "per_source": per_source}

    mode_statuses = [item["status"] for item in per_mode.values()]
    overall = (
        "different" if "different" in mode_statuses
        else "unverified" if not modes
        or (expected_modes is not None and set(modes) != set(expected_modes))
        or "unverified" in mode_statuses
        else "equal"
    )
    return {
        "status": overall,
        "comparison": "audited read_dashboard outputs, baseline versus each treatment mode",
        "source_snapshot_fields": list(_RESOURCE_SNAPSHOT_FIELDS),
        "capture_timestamps_included": True,
        "catalog_contract_and_metadata_quality_are_included": True,
        "per_mode": per_mode,
    }


def source_tool_snapshot_parity_from_audit(
    audit_path: Path,
    approved_sources: list[dict[str, Any]],
    *,
    expected_modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    malformed_lines = 0
    with audit_path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if isinstance(event, dict):
                events.append(event)
    result = source_tool_snapshot_parity_from_events(
        events, approved_sources, expected_modes=expected_modes,
    )
    result["malformed_audit_line_count"] = malformed_lines
    if malformed_lines and result["status"] == "equal":
        result["status"] = "unverified"
        result["issue"] = "malformed_audit_lines_could_hide_source_reads"
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _posthoc_output_path(results_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = results_path.with_name(f"posthoc-source-parity-{stamp}.json")
    suffix = 1
    while candidate.exists():
        candidate = results_path.with_name(f"posthoc-source-parity-{stamp}-{suffix}.json")
        suffix += 1
    return candidate


class CardJourneySession(ReportSession):
    """Existing real Superset helpers plus a stage-bounded native tool surface."""

    def __init__(
        self,
        adapter,
        native=None,
        *,
        stage: str,
        max_data_reads: int = MAX_DATA_READS,
        source_snapshot: PairedSourceSnapshot | None = None,
        max_report_words: int | None = None,
        expected_replay_key: str | None = None,
        expected_replay_card_id: str | None = None,
        expected_replay_receipt_id: str | None = None,
    ):
        super().__init__(adapter, native)
        self.stage = stage
        self.max_data_reads = max_data_reads
        self.source_snapshot = source_snapshot
        self.max_report_words = max_report_words
        self.expected_replay_key = expected_replay_key
        self.expected_replay_card_id = expected_replay_card_id
        self.expected_replay_receipt_id = expected_replay_receipt_id
        self.discovery_calls = 0
        self.discovery_calls_by_tool: dict[str, int] = {}
        self.data_reads = 0
        self.data_reads_by_tool: dict[str, int] = {}
        self.card: dict[str, Any] | None = None
        self.review: dict[str, Any] | None = None
        self.review_adapter: str | None = None
        self.evaluation: dict[str, Any] | None = None
        self.native_tool_calls_by_name: dict[str, int] = {}
        self.native_tool_elapsed_seconds_by_name: dict[str, float] = {}

    async def _call_native_tool(self, name: str, arguments: dict[str, Any]):
        started = time.perf_counter()
        try:
            return await super().call(name, arguments)
        finally:
            self.native_tool_calls_by_name[name] = self.native_tool_calls_by_name.get(name, 0) + 1
            self.native_tool_elapsed_seconds_by_name[name] = (
                self.native_tool_elapsed_seconds_by_name.get(name, 0.0)
                + (time.perf_counter() - started)
            )

    async def _assert_preflight_receipt_available(self) -> None:
        if not self.expected_replay_key:
            return
        response = await self._call_native_tool("get_decision_receipt", {
            "idempotency_key": self.expected_replay_key,
            "result_path": ["card_id"],
            "offset": 0,
            "limit": 1,
        })
        receipt = response.get("receipt") if isinstance(response, dict) else None
        if (
            not isinstance(response, dict)
            or response.get("status") != "found"
            or not isinstance(receipt, dict)
            or receipt.get("idempotency_key") != self.expected_replay_key
            or receipt.get("card_id") != self.expected_replay_card_id
            or receipt.get("receipt_id") != self.expected_replay_receipt_id
            or receipt.get("status") == "prepared"
        ):
            raise ValueError("paired preflight receipt is unavailable; refusing a possible new evaluation")

    async def specs(self):
        specs = await super().specs()
        if self.native is None and self.stage in {"baseline", "paired-baseline"}:
            allowed = SHARED_SOURCE_TOOLS
        elif self.stage == "setup":
            allowed = SHARED_SOURCE_TOOLS | SETUP_TOOLS
        elif self.stage in {"monitor", "paired-treatment"}:
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
            if self.expected_replay_key:
                if (
                    set(arguments) - {"card_id", "idempotency_key", "response_mode"}
                    or arguments.get("card_id") != self.expected_replay_card_id
                    or arguments.get("idempotency_key") != self.expected_replay_key
                    or arguments.get("response_mode", "compact") != "compact"
                ):
                    raise ValueError("paired evaluation must replay the exact preflight card/key without context")
            if self.evaluation is not None:
                raise ValueError("evaluate_insight_card may be called only once per run")
            if name == "evaluate_insight_card" and self.expected_replay_key:
                await self._assert_preflight_receipt_available()
        if name == "submit_report" and self.max_report_words is not None:
            report = arguments.get("report")
            words = len(report.split()) if isinstance(report, str) else 0
            if words > self.max_report_words:
                raise ValueError(
                    f"report_word_limit_exceeded: {words} words; maximum is "
                    f"{self.max_report_words}. Condense the report and submit again."
                )
            references = arguments.get("evidence_refs")
            if not isinstance(references, list) or not references:
                raise ValueError("source_references_required: cite at least one captured source")
        if self.source_snapshot is not None and name in {
            "find_dashboards", "read_dashboard", "read_chart_rows"
        }:
            result = self.source_snapshot.call(name, arguments)
        elif self.native is not None and name in (SETUP_TOOLS | MONITOR_TOOLS):
            result = await self._call_native_tool(name, arguments)
        else:
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
            if self.expected_replay_key and result.get("replayed") is not True:
                raise ValueError("preflight evaluation was not replayed; refusing to count it as treatment")
            if self.expected_replay_key:
                receipt = result.get("receipt")
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("idempotency_key") != self.expected_replay_key
                    or receipt.get("receipt_id") != self.expected_replay_receipt_id
                ):
                    raise ValueError("treatment evaluation did not return the preflight receipt")
            self.evaluation = result
        return result


class PairedSourceSnapshot:
    """Immutable-in-practice replay of one real Superset capture for paired agents."""

    def __init__(
        self,
        *,
        dashboards: dict[str, dict[str, Any]],
        charts: dict[str, dict[str, Any]],
        resources: list[dict[str, Any]],
        manifest: dict[str, Any],
    ) -> None:
        self.dashboards = copy.deepcopy(dashboards)
        self.charts = copy.deepcopy(charts)
        self.resources = copy.deepcopy(resources)
        self.manifest = copy.deepcopy(manifest)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "find_dashboards":
            query = str(arguments.get("query", "")).strip().casefold()
            matches = [
                resource for resource in self.resources
                if not query or query in str(resource.get("title", "")).casefold()
                or query in str(resource.get("resource", "")).casefold()
                or query in str(resource.get("metadata", {}).get("approved_label", "")).casefold()
                or any(
                    term in " ".join((
                        str(resource.get("title", "")),
                        str(resource.get("resource", "")),
                        str(resource.get("metadata", {}).get("approved_label", "")),
                    )).casefold()
                    for term in query.split()
                )
            ]
            return {
                "resources": copy.deepcopy(matches),
                "total_count": len(matches),
                "has_more": False,
                "next_cursor": None,
                "provider": "superset",
                "strategy": "approved-card-snapshot",
                "warnings": ["Catalog results are restricted to this approved card's source scope."],
            }
        if name == "read_dashboard":
            dashboard_id = str(arguments.get("id", "")).removeprefix("dashboard:")
            if not dashboard_id.isdigit() or dashboard_id not in self.dashboards:
                raise ValueError("dashboard is outside the captured approved source scope")
            return copy.deepcopy(self.dashboards[dashboard_id])
        if name == "read_chart_rows":
            chart_id = str(arguments.get("id", "")).removeprefix("chart:")
            item = self.charts.get(chart_id)
            if item is None:
                raise ValueError("chart is outside the captured approved source scope")
            offset = arguments.get("offset", 0)
            limit = arguments.get("limit", 100)
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValueError("Invalid source row offset")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 250:
                raise ValueError("Invalid source row limit")
            rows = item["rows"]
            end = min(len(rows), offset + limit)
            return {
                **{key: copy.deepcopy(value) for key, value in item.items() if key != "rows"},
                "rows": copy.deepcopy(rows[offset:end]),
                "returned_query_row_count": len(rows),
                "offset": offset,
                "next_offset": end if end < len(rows) else None,
                "coverage": "partial_query_rows" if offset or end < len(rows) else "all_returned_query_rows",
            }
        raise ValueError(f"tool is not part of the paired source snapshot: {name}")


async def capture_paired_source_snapshot(
    adapter: SupersetAdapter,
    card: dict[str, Any],
    *,
    max_data_reads: int = MAX_DATA_READS,
    max_bytes: int = MAX_PAIRED_SNAPSHOT_BYTES,
) -> PairedSourceSnapshot:
    """Capture only the approved dashboard scope once, then replay it to both arms."""
    source_refs = card.get("sources")
    if not isinstance(source_refs, list) or not 1 <= len(source_refs) <= 3:
        raise ValueError("paired snapshot requires one to three approved card sources")
    if max_data_reads < 1 or max_bytes < 1:
        raise ValueError("paired snapshot data-read and byte caps must be positive")
    validated_sources = [SourceRef.model_validate(item) for item in source_refs]
    if any(
        source.adapter != "superset" or not source.resource.startswith("dashboard:")
        for source in validated_sources
    ):
        raise ValueError("paired Superset snapshot supports only approved dashboard sources")
    if len(validated_sources) > max_data_reads:
        raise ValueError("paired_snapshot_data_read_budget_exhausted")

    started_at = datetime.now(timezone.utc)
    http_before = adapter.client.requests_made
    http_paths_before = dict(adapter.client.request_path_counts)
    dashboards: dict[str, dict[str, Any]] = {}
    charts: dict[str, dict[str, Any]] = {}
    resources: list[dict[str, Any]] = []
    captured: list[dict[str, Any]] = []
    source_snapshot_sha256_by_key: dict[str, str] = {}
    registry = SourceRegistry(
        [adapter],
        max_snapshot_bytes=NATIVE_MAX_SOURCE_SNAPSHOT_BYTES,
    )
    registry_started_at = datetime.now(timezone.utc)
    resource_snapshots = await registry.resolve(validated_sources)
    registry_finished_at = datetime.now(timezone.utc)
    data_read_calls = len(validated_sources)
    captured.append({
        "kind": "production_source_registry_resolve",
        "resource_count": len(validated_sources),
        "request_started_at": registry_started_at.isoformat(),
        "request_finished_at": registry_finished_at.isoformat(),
    })

    for source, resource_snapshot in zip(validated_sources, resource_snapshots, strict=True):
        dashboard_id = source.resource.removeprefix("dashboard:")
        if not dashboard_id.isdigit() or dashboard_id in dashboards:
            raise ValueError("approved dashboard references must be unique numeric IDs")
        dashboard = resource_snapshot.model_dump(mode="json")
        dashboards[dashboard_id] = dashboard
        source_snapshot_sha256_by_key[source.key] = _full_snapshot_digest(dashboard)

        snapshot_metadata = dashboard.get("metadata", {})
        chart_metadata = snapshot_metadata.get("charts", []) if isinstance(snapshot_metadata, dict) else []
        if not isinstance(chart_metadata, list):
            raise ValueError("approved dashboard snapshot did not return a chart list")
        descriptor = {
            "adapter": "superset",
            "resource": source.resource,
            "kind": "dashboard",
            "title": dashboard.get("title", source.label),
            "description": dashboard.get("description", ""),
            "source_url": dashboard.get("source_url"),
            "metadata": {
                "approved_source_key": source.key,
                "approved_label": source.label,
                "approved_parameters": copy.deepcopy(source.parameters),
            },
            "contract": dashboard.get("contract", {}),
        }
        resources.append(descriptor)

        for chart_summary in chart_metadata:
            if not isinstance(chart_summary, dict):
                continue
            chart_id = str(chart_summary.get("id", ""))
            if not chart_id.isdigit() or chart_id in charts:
                continue
            if data_read_calls >= max_data_reads:
                raise ValueError("paired_snapshot_data_read_budget_exhausted")
            request_started = datetime.now(timezone.utc)
            chart = await adapter.client.get_chart_metadata(chart_id)
            envelopes = await adapter.client.chart_data(chart)
            rows = [
                row
                for envelope in envelopes
                for row in adapter.client._rows_from_result_item(envelope)
            ]
            request_finished = datetime.now(timezone.utc)
            data_read_calls += 1
            charts[chart_id] = {
                "chart_id": chart_id,
                "title": chart.get("slice_name"),
                "chart_metadata": copy.deepcopy(chart),
                "saved_query_definition": chart.get("params"),
                "rows": rows,
                "query_response_metadata": [
                    {key: copy.deepcopy(value) for key, value in envelope.items() if key != "data"}
                    for envelope in envelopes
                    if isinstance(envelope, dict)
                ],
                "scope": "standalone saved chart query, not dashboard filter context",
            }
            captured.append({
                "kind": "chart_query",
                "resource": f"chart:{chart_id}",
                "request_started_at": request_started.isoformat(),
                "request_finished_at": request_finished.isoformat(),
            })

    finished_at = datetime.now(timezone.utc)
    http_paths_after = dict(adapter.client.request_path_counts)
    http_path_counts = {
        path: count - http_paths_before.get(path, 0)
        for path, count in http_paths_after.items()
        if count - http_paths_before.get(path, 0) > 0
    }
    digest_payload = {"dashboards": dashboards, "charts": charts, "resources": resources}
    snapshot_bytes = json.dumps(
        digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    if len(snapshot_bytes) > max_bytes:
        raise ValueError("paired_snapshot_payload_budget_exhausted")
    fingerprint = hashlib.sha256(snapshot_bytes).hexdigest()
    manifest = {
        "status": "captured",
        "snapshot_sha256": fingerprint,
        "captured_at_started": started_at.isoformat(),
        "captured_at_finished": finished_at.isoformat(),
        "capture_is_atomic": False,
        "timestamps_are_query_capture_times_not_warehouse_as_of": True,
        "approved_sources": [source.resource for source in (SourceRef.model_validate(item) for item in source_refs)],
        "source_snapshot_capture_method": (
            "production SourceRegistry.resolve using the configured SupersetAdapter; "
            "catalog-owned contract merge and resolution metadata are retained"
        ),
        "source_snapshot_fields": list(_RESOURCE_SNAPSHOT_FIELDS),
        "source_snapshot_sha256_by_key": source_snapshot_sha256_by_key,
        "native_per_source_snapshot_byte_cap": NATIVE_MAX_SOURCE_SNAPSHOT_BYTES,
        "dashboard_count": len(dashboards),
        "chart_query_count": len(charts),
        "snapshot_payload_bytes": len(snapshot_bytes),
        "snapshot_payload_byte_cap": max_bytes,
        "data_read_calls": data_read_calls,
        "data_read_cap": max_data_reads,
        "superset_http_attempts": adapter.client.requests_made - http_before,
        "superset_http_request_counts_by_path": http_path_counts,
        "captured_requests": captured,
    }
    return PairedSourceSnapshot(
        dashboards=dashboards,
        charts=charts,
        resources=resources,
        manifest=manifest,
    )


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


async def _run_paired_recurring(
    *,
    args: argparse.Namespace,
    native: InstalledServer,
    audit: Audit,
    owner_context: str,
    skill: str,
    card: dict[str, Any],
    review: dict[str, Any],
    owner_notes: str,
) -> dict[str, Any]:
    capture_adapter = SupersetAdapter(
        SupersetClient(args.superset_url, "admin", "admin"), tenant_id="local"
    )
    capture_started = time.perf_counter()
    snapshot = await capture_paired_source_snapshot(capture_adapter, card)
    snapshot_capture_seconds = time.perf_counter() - capture_started
    idempotency_key = f"paired-superset-preflight-{secrets.token_hex(12)}"
    preflight_reader = ReceiptPageReader(native)
    preflight, native_sources, native_source_status, preflight_page_calls, native_issue = (
        await run_native_preflight(
            native,
            card=card,
            idempotency_key=idempotency_key,
            reader=preflight_reader,
        )
    )
    source_comparison = compare_paired_source_snapshots(
        helper_source_snapshots_by_key(snapshot, card),
        native_sources,
        native_status=native_source_status,
        receipt_page_calls=preflight_page_calls,
        native_issue=native_issue,
    )
    parity_gate_passed = source_comparison["status"] == "equal"
    paired: dict[str, Any] = {
        "phase": "paired-recurring",
        "treatment_recipe_version": "skill-guided-deferred-v3-same-key-preflight",
        "historical_explicit_deferred_trial_preserved_separately": True,
        "comparison_design": "one complete production Superset helper capture is frozen for both arms; one native preflight evaluation is source-snapshot-compared before readout episodes; only a full ResourceSnapshot match admits the readouts; treatment modes replay that one preflight key",
        "mode_interpretation": (
            "Both treatment modes run the same candidate binary, approved card, notes, source tools, "
            "and frozen source responses. original_policy does not consume deferred receipt pages. "
            "skill_guided_deferred follows the currently shipped skill and pages only relevant omitted "
            "details. This is a changed recipe from the archived explicit_deferred trial, whose prompt "
            "required exhaustive paging; do not pool or relabel those earlier results. It is not a "
            "comparison against the prior binary/runtime."
        ),
        "snapshot": snapshot.manifest,
        "preflight": preflight,
        "preflight_source_snapshot_comparison": source_comparison,
        "paired_input_parity_gate": {
            "status": "passed" if parity_gate_passed else "failed",
            "readout_episodes_started": 0,
            "comparison_scope": "all ResourceSnapshot fields except only the root captured_at receive timestamp; includes nested timestamps, source_captured_at, metadata/cache status, contracts, observations, evidence, and source errors",
            "saved_chart_params_and_query_response_metadata": "retained in the complete frozen helper tool snapshot and replayed identically to both arms; not asserted to be present in the native receipt",
            "baseline_receives": "approved card, review, owner notes, questions, and frozen source-tool snapshot only; no native evaluation or policy judgment",
            "treatment_receives": "same frozen source-tool snapshot plus evaluate_insight_card replay of the exact preflight key",
        },
        "fresh_wizard_runs_in_this_phase": 1,
        "preflight_receipt_snapshot_page_call_cap_total": MAX_RECEIPT_PAGE_CALLS,
        "report_word_limit": MAX_PAIRED_REPORT_WORDS,
        "report_word_count_method": "whitespace-delimited words in submitted report only",
        "repeat_count": PAIRED_REPETITIONS,
        "policy_modes": list(PAIRED_POLICY_MODES),
        "limitations": [
            "The shared dashboard/chart responses are captured from real read-only Superset HTTP and replayed identically to every readout agent; the capture is not atomic.",
            "Capture timestamps are request-time observations, not warehouse as-of timestamps or freshness proof.",
            "The native preflight uses separate live approved-source reads. Readout episodes start only if every ResourceSnapshot business and definition field matches the frozen helper snapshot; any difference or unavailable field stops the paired analysis before readout model calls.",
            "Only the root ResourceSnapshot captured_at receive-time is excluded from parity hashes. Root source_captured_at and all nested timestamps, metadata/cache state, quality warnings, and contracts remain in the comparison.",
            "Raw saved-chart query parameters and query-response metadata are preserved in the shared helper fixture because the receipt does not contain them; no receipt-only substitution is made for the source-tool outputs.",
            "A matching snapshot is not proof of an atomic warehouse state, identical HTTP request sequence, or total connector-cost parity. Native adapter HTTP subrequests are not exposed by the evaluation API.",
            "No numeric outcome labels or expected business classes are supplied; two repeats are descriptive, not a generalization sample.",
            "No source-cost savings claim is made. One-time helper capture, native preflight, receipt pages, and agent calls are measured separately; the native preflight is included in treatment all-in.",
            "The trial tool prevents reports over 300 whitespace-delimited words from being submitted.",
            "The skill_guided_deferred recipe follows shipped evidence-access guidance; it does not require exhaustive receipt paging or duplicate representations.",
        ],
        "repeats": [],
    }
    if not parity_gate_passed:
        paired["comparison_status"] = "ineligible_source_snapshot_mismatch_or_unverified"
        paired["measurement_accounting"] = {
            "categories_are_disjoint": True,
            "shared_helper_capture_wall_seconds": snapshot_capture_seconds,
            "shared_helper_superset_http_attempts": snapshot.manifest["superset_http_attempts"],
            "native_preflight_evaluate_calls": 1,
            "native_preflight_evaluate_wall_seconds": preflight["native_evaluate_wall_seconds"],
            "native_preflight_receipt_page_calls": preflight_page_calls,
            "native_preflight_receipt_page_elapsed_seconds": preflight_reader.elapsed_seconds,
            "native_preflight_internal_superset_http_attempts": None,
            "readout_agent_model_calls": 0,
            "source_cost_savings_claim": False,
            "treatment_all_in_includes_preflight": True,
            "treatment_all_in_measured_seconds_subtotal": (
                snapshot_capture_seconds
                + preflight["native_evaluate_wall_seconds"]
                + preflight_reader.elapsed_seconds
            ),
        }
        return paired

    treatment_episode_seconds: list[float] = []
    baseline_episode_seconds: list[float] = []
    treatment_native_calls: dict[str, int] = {}
    treatment_native_call_seconds: dict[str, float] = {}
    for repeat, mode in enumerate(PAIRED_POLICY_MODES, start=1):
        baseline = CardJourneySession(
            None,
            stage="paired-baseline",
            source_snapshot=snapshot,
            max_report_words=MAX_PAIRED_REPORT_WORDS,
        )
        baseline_prompt = build_paired_prompt(
            owner_context=owner_context,
            card=card,
            review=review,
            owner_notes=owner_notes,
            snapshot=snapshot.manifest,
            repeat=repeat,
        )
        baseline_started = time.perf_counter()
        baseline_episode = await _run_episode(
            baseline,
            audit=audit,
            stage="paired-baseline",
            prompt=baseline_prompt,
            skill=skill,
        )
        baseline_episode_seconds.append(time.perf_counter() - baseline_started)

        treatment = CardJourneySession(
            None,
            native,
            stage="paired-treatment",
            source_snapshot=snapshot,
            max_report_words=MAX_PAIRED_REPORT_WORDS,
            expected_replay_key=idempotency_key,
            expected_replay_card_id=card["id"],
            expected_replay_receipt_id=preflight["receipt_id"],
        )
        treatment_prompt = build_paired_prompt(
            owner_context=owner_context,
            card=card,
            review=review,
            owner_notes=owner_notes,
            snapshot=snapshot.manifest,
            repeat=repeat,
            policy_mode=mode,
            idempotency_key=idempotency_key,
        )
        treatment_started = time.perf_counter()
        treatment_episode = await _run_episode(
            treatment,
            audit=audit,
            stage=f"paired-treatment-{mode}",
            prompt=treatment_prompt,
            skill=skill,
        )
        treatment_episode_seconds.append(time.perf_counter() - treatment_started)
        for name, count in treatment.native_tool_calls_by_name.items():
            treatment_native_calls[name] = treatment_native_calls.get(name, 0) + count
        for name, seconds in treatment.native_tool_elapsed_seconds_by_name.items():
            treatment_native_call_seconds[name] = treatment_native_call_seconds.get(name, 0.0) + seconds
        treatment_evaluation = treatment.evaluation or {}
        treatment_receipt = treatment_evaluation.get("receipt")
        treatment_receipt = treatment_receipt if isinstance(treatment_receipt, dict) else {}
        replay_verified = (
            treatment_evaluation.get("replayed") is True
            and treatment_receipt.get("idempotency_key") == idempotency_key
            and treatment_receipt.get("receipt_id") == preflight["receipt_id"]
            and treatment_receipt.get("card_id") == card["id"]
        )
        treatment_source_comparison = copy.deepcopy(source_comparison)
        treatment_source_comparison["treatment_replay_status"] = (
            "same_preflight_receipt_replayed" if replay_verified else "unverified_treatment_replay"
        )
        if not replay_verified:
            treatment_source_comparison["status"] = "unverified"
        baseline_report = baseline.submission.get("report") if baseline.submission else None
        treatment_report = treatment.submission.get("report") if treatment.submission else None
        paired["repeats"].append({
            "repeat": repeat,
            "policy_mode": mode,
            "idempotency_key": idempotency_key,
            "snapshot_sha256": snapshot.manifest["snapshot_sha256"],
            "baseline": {
                "episode": baseline_episode,
                "submission": baseline.submission,
                "report_word_count": len(baseline_report.split()) if isinstance(baseline_report, str) else None,
                **_source_budget_summary(baseline),
                "source_snapshot_replayed": True,
                "source_snapshot_sha256": snapshot.manifest["snapshot_sha256"],
                "shared_tool_names": sorted(SHARED_SOURCE_TOOLS),
                "episode_wall_seconds": baseline_episode_seconds[-1],
            },
            "treatment": {
                "episode": treatment_episode,
                "submission": treatment.submission,
                "report_word_count": len(treatment_report.split()) if isinstance(treatment_report, str) else None,
                "card_panel": card_panel(treatment.evaluation, card=card),
                "native_policy_mode": mode,
                **_source_budget_summary(treatment),
                "source_snapshot_replayed": True,
                "source_snapshot_sha256": snapshot.manifest["snapshot_sha256"],
                "native_source_snapshot_comparison": treatment_source_comparison,
                "shared_tool_names": sorted(SHARED_SOURCE_TOOLS),
                "native_monitor_tools": sorted(MONITOR_TOOLS),
                "episode_wall_seconds": treatment_episode_seconds[-1],
                "native_tool_calls_by_name": treatment.native_tool_calls_by_name,
                "native_tool_elapsed_seconds_by_name": treatment.native_tool_elapsed_seconds_by_name,
                "same_preflight_receipt_replay_verified": replay_verified,
            },
        })
    paired["comparison_status"] = "eligible_source_snapshot_parity_verified"
    paired["paired_input_parity_gate"]["readout_episodes_started"] = 2 * len(PAIRED_POLICY_MODES)
    snapshot_fingerprint_reused = len({
        arm["source_snapshot_sha256"]
        for item in paired["repeats"]
        for arm in (item["baseline"], item["treatment"])
    }) == 1
    source_tool_parity = source_tool_snapshot_parity_from_events(
        audit.events,
        [item for item in card.get("sources", []) if isinstance(item, dict)],
        expected_modes=PAIRED_POLICY_MODES,
    )
    paired["snapshot_manifest_fingerprint_reused_across_episodes"] = snapshot_fingerprint_reused
    paired["shared_agent_source_tool_snapshot_parity"] = source_tool_parity
    paired["shared_helper_snapshot_replayed_identically"] = snapshot_fingerprint_reused
    paired["measurement_accounting"] = {
        "categories_are_disjoint": True,
        "shared_helper_capture": {
            "wall_seconds": snapshot_capture_seconds,
            "superset_http_attempts": snapshot.manifest["superset_http_attempts"],
            "superset_request_counts_by_path": snapshot.manifest["superset_http_request_counts_by_path"],
            "source_capture_data_read_calls": snapshot.manifest["data_read_calls"],
            "agent_tool_calls_use_frozen_responses": True,
            "source_cost_savings_claim": False,
        },
        "native_preflight": preflight,
        "baseline_agent": {
            "episode_wall_seconds_total": sum(baseline_episode_seconds),
            "native_tool_calls": 0,
            "live_superset_http_attempts_during_episode": 0,
        },
        "treatment_agent": {
            "episode_wall_seconds_total": sum(treatment_episode_seconds),
            "native_tool_calls_by_name": treatment_native_calls,
            "native_tool_elapsed_seconds_by_name": treatment_native_call_seconds,
            "evaluate_insight_card_calls_are_cached_replays": (
                treatment_native_calls.get("evaluate_insight_card", 0) == PAIRED_REPETITIONS
            ),
            "live_superset_http_attempts_during_episode": 0,
        },
        "treatment_all_in": {
            "includes_shared_helper_capture": True,
            "includes_native_preflight": True,
            "includes_preflight_receipt_snapshot_pages": True,
            "native_preflight_evaluate_calls": preflight["native_evaluate_tool_calls"],
            "native_preflight_evaluate_wall_seconds": preflight["native_evaluate_wall_seconds"],
            "native_preflight_receipt_page_calls": preflight_page_calls,
            "native_preflight_receipt_page_elapsed_seconds": preflight_reader.elapsed_seconds,
            "shared_helper_capture_wall_seconds": snapshot_capture_seconds,
            "shared_helper_superset_http_attempts": snapshot.manifest["superset_http_attempts"],
            "agent_episode_wall_seconds_total": sum(treatment_episode_seconds),
            "measured_wall_seconds_subtotal": (
                snapshot_capture_seconds
                + preflight["native_evaluate_wall_seconds"]
                + preflight_reader.elapsed_seconds
                + sum(treatment_episode_seconds)
            ),
            "native_superset_internal_http_attempts": None,
            "source_cost_savings_claim": False,
        },
        "limitations": [
            "The shared helper capture is counted once as experiment input preparation and included in treatment all-in; the separate time/call categories are not added twice.",
            "Native evaluation's internal Superset HTTP attempts are not exposed and remain unknown, not zero.",
            "Provider call attempt fields are reported as returned; they do not confirm provider receipt or billing.",
            "No total source-cost parity or source-cost savings inference is made from frozen replay.",
        ],
    }
    return paired


async def verify_saved_paired_results(results_path: Path) -> dict[str, Any]:
    """Verify prepared-source parity from the saved trial and durable receipts only."""
    results_path = results_path.resolve()
    results_sha256_before = _sha256_file(results_path)
    results = json.loads(results_path.read_text(encoding="utf-8"))
    paired = results.get("paired_recurring")
    if not isinstance(paired, dict) or not isinstance(paired.get("repeats"), list):
        raise ValueError("saved results do not contain paired-recurring repeats")

    artifact_dir = results_path.parent
    audit_path = artifact_dir / "audit.jsonl"
    home = artifact_dir / "human-home"
    signalweave_home = home / ".signalweave"
    binary = home / ".local" / "bin" / "signalweave"
    if not audit_path.is_file() or not binary.is_file():
        raise FileNotFoundError("saved audit or isolated native binary is missing beside results")

    approved_sources = []
    for repeat in paired["repeats"]:
        panel = (repeat.get("treatment") or {}).get("card_panel") or {}
        if isinstance(panel.get("approved_sources"), list):
            approved_sources = panel["approved_sources"]
            if approved_sources:
                break
    helper_sources, helper_status, helper_issue, helper_read_counts = (
        helper_source_snapshots_from_audit(audit_path, approved_sources)
    )
    saved_modes = tuple(dict.fromkeys(
        item.get("policy_mode")
        for item in paired["repeats"]
        if isinstance(item, dict) and isinstance(item.get("policy_mode"), str)
    ))
    agent_source_tool_parity = source_tool_snapshot_parity_from_audit(
        audit_path, approved_sources, expected_modes=saved_modes,
    )

    expected_binary = (results.get("binary") or {}).get("binary_sha256")
    binary_sha256 = _sha256_file(binary)
    if not isinstance(expected_binary, str) or binary_sha256 != expected_binary:
        raise ValueError("isolated native binary does not match the saved trial identity")

    env = {
        key: os.environ[key]
        for key in ("PATH", "TMPDIR", "LANG", "LC_ALL")
        if key in os.environ
    }
    env.update(
        HOME=str(home),
        CODEX_HOME=str(home / ".codex"),
        TYPESAFE_MAX_RETRIES="0",
    )
    audit = Audit()
    reader: ReceiptPageReader | None = None
    comparisons: list[dict[str, Any]] = []
    async with stdio_client(StdioServerParameters(
        command=str(binary),
        args=["serve", "--transport", "stdio", "--home", str(signalweave_home)],
        env=env,
    )) as streams:
        async with ClientSession(*streams) as client:
            initialized = await _initialize_mcp_session(client)
            native = InstalledServer(client, initialized.instructions, audit)
            reader = ReceiptPageReader(native, max_calls=MAX_RECEIPT_PAGE_CALLS)
            for repeat in paired["repeats"]:
                treatment = repeat.get("treatment") or {}
                panel = treatment.get("card_panel") or {}
                episode = treatment.get("episode") or {}
                idempotency_key = repeat.get("idempotency_key")
                evaluation = {
                    "receipt": {
                        "receipt_id": panel.get("receipt_id"),
                        "status": panel.get("receipt_status"),
                    },
                    "result": {
                        "judgment": {"status": panel.get("judgment_status")},
                    },
                }
                native_sources, native_status, page_calls, native_issue = (
                    await native_source_snapshots_for_comparison(
                        native,
                        evaluation,
                        idempotency_key=idempotency_key,
                        reader=reader,
                    )
                )
                comparison = compare_paired_source_snapshots(
                    helper_sources,
                    native_sources,
                    native_status=native_status,
                    receipt_page_calls=page_calls,
                    helper_status=helper_status,
                    native_issue=native_issue,
                    helper_issue=helper_issue,
                )
                comparisons.append({
                    "repeat": repeat.get("repeat"),
                    "policy_mode": repeat.get("policy_mode"),
                    "idempotency_key": idempotency_key,
                    "receipt_id": panel.get("receipt_id"),
                    "agent_episode": {
                        "status": episode.get("status"),
                        "error": episode.get("error"),
                        "submission_present": treatment.get("submission") is not None,
                    },
                    "native_source_snapshot_comparison": comparison,
                })

    page_calls_total = reader.calls if reader else 0
    statuses = [
        item["native_source_snapshot_comparison"]["status"]
        for item in comparisons
    ]
    overall_parity = (
        "equal" if statuses and all(status == "equal" for status in statuses)
        else "different" if any(status == "different" for status in statuses)
        else "unverified"
    )
    results_sha256_after = _sha256_file(results_path)
    report = {
        "verification_kind": "posthoc_saved_receipt_source_parity",
        "status": "complete" if statuses and all(status != "unverified" for status in statuses) else "partial_unverified",
        "source_snapshot_parity": overall_parity,
        "does_not_rewrite_original_results": True,
        "original_results_sha256": results_sha256_before,
        "original_results_unchanged": results_sha256_before == results_sha256_after,
        "audit_sha256": _sha256_file(audit_path),
        "native_binary_sha256": binary_sha256,
        "native_binary_matches_saved_trial": True,
        "receipt_access": {
            "mode": "fresh isolated native MCP process; get_decision_receipt by saved idempotency key only",
            "local_home": str(signalweave_home),
            "result_paths_read": ["source_by_key/<approved-alias>/<ResourceSnapshot-field>"],
            "receipt_page_limit": RECEIPT_PAGE_LIMIT,
            "max_result_path_depth": MAX_RECEIPT_PATH_DEPTH,
            "max_get_decision_receipt_calls_total": MAX_RECEIPT_PAGE_CALLS,
            "get_decision_receipt_calls": page_calls_total,
            "evaluate_insight_card_calls": 0,
            "provider_calls": 0,
            "source_adapter_calls": 0,
        },
        "helper_snapshot_audit": {
            "status": helper_status,
            "read_dashboard_result_counts_by_source": helper_read_counts,
            "issue": helper_issue,
        },
        "shared_agent_source_tool_snapshot_parity": agent_source_tool_parity,
        "comparisons": comparisons,
        "interpretation_limits": [
            "This verifies only selected typed ResourceSnapshot fields against the separately captured helper response, excluding capture timestamps.",
            "It does not establish an atomic warehouse snapshot, identical underlying HTTP requests, a total source-cost comparison, or a causal/product win.",
            "A saved treatment with no submitted report remains an incomplete agent episode even if its source digests match.",
            "A scalar too large for the receipt page API, a missing field, path-depth limit, or page-call cap is recorded as unverified at the exact path; no missing value is inferred.",
        ],
    }
    output_path = _posthoc_output_path(results_path)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return {"output": str(output_path), "status": report["status"], "source_snapshot_parity": overall_parity,
            "get_decision_receipt_calls": page_calls_total}


async def run(args: argparse.Namespace) -> None:
    if not args.execute:
        raise SystemExit("No provider calls are made unless --execute is explicitly supplied.")
    capture_imports = verify_capture_imports()
    phase = getattr(args, "phase", "original")
    if phase not in {"original", "paired-recurring"}:
        raise ValueError("phase must be original or paired-recurring")
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
        "phase": phase,
        "binary": identity,
        "coordinator_capture_imports": capture_imports,
        "archive_sha256": expected,
        "archive_origin": args.archive_origin,
        "trial_scope": (
            "fresh native setup; real Codex with installed shipped skill; approved card; paired recurring readouts; captured live read-only Superset HTTP; explicit human approval; delivery disabled"
            if phase == "paired-recurring"
            else "fresh native setup; real Codex with installed shipped skill; paired source tools; live read-only Superset HTTP; explicit human approval; one delivery-disabled card evaluation; direct chart drilldown"
        ),
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
            (
                "No external message or schedule is created; a current snapshot is not a recurrence-quality claim."
                if phase == "original"
                else "No external message or schedule is created; two repeats are descriptive, not a recurrence-quality claim or superiority test."
            ),
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

    if phase == "original":
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

            if phase == "paired-recurring":
                approved_card = approval.get("result", {}).get("card")
                if not isinstance(approved_card, dict):
                    raise RuntimeError("Explicit approval did not return the approved card")
                owner_notes = approval.get("source_selection_reason", "")
                result["paired_recurring"] = await _run_paired_recurring(
                    args=args,
                    native=native,
                    audit=audit,
                    owner_context=owner_context,
                    skill=skill,
                    card=approved_card,
                    review=setup.review,
                    owner_notes=owner_notes,
                )
                checkpoint()
                result["binary_after"] = verify_binary(binary)
                checkpoint()
                print(json.dumps({
                    "output": str(output),
                    "phase": phase,
                    "owner_approval": "approved",
                    "repeat_count": len(result["paired_recurring"]["repeats"]),
                    "shared_helper_snapshot_replayed_identically": result["paired_recurring"]["shared_helper_snapshot_replayed_identically"],
                }))
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
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--archive-origin", choices=["github-actions", "local-build"])
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--owner-context-file", type=Path)
    parser.add_argument("--superset-url", default="http://127.0.0.1:18089")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--verify-saved-results",
        type=Path,
        help="Read only saved trial results/audit and durable receipts; does not evaluate cards or call sources/providers.",
    )
    parser.add_argument(
        "--phase",
        choices=("original", "paired-recurring"),
        default="original",
        help="Keep the historical one-shot comparison, or run two matched recurring readout pairs after approval.",
    )
    parser.add_argument("--execute", action="store_true", help="Explicitly enable live model calls and interactive owner approval")
    args = parser.parse_args()
    if args.verify_saved_results is not None:
        if args.execute:
            parser.error("--verify-saved-results cannot be combined with --execute")
        print(json.dumps(asyncio.run(verify_saved_paired_results(args.verify_saved_results))))
        return
    required = ("archive", "archive_origin", "key_file", "owner_context_file", "output")
    missing = [name.replace("_", "-") for name in required if getattr(args, name) is None]
    if missing:
        parser.error("the following arguments are required for a trial run: " + ", ".join("--" + name for name in missing))
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

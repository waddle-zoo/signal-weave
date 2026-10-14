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
MAX_PAIRED_REPORT_WORDS = 300
MAX_PAIRED_SNAPSHOT_BYTES = 4_000_000
PAIRED_REPETITIONS = 2
PAIRED_POLICY_MODES = ("original_policy", "explicit_deferred")
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
    "Do not invent thresholds or causes. Use the "
    "shared source tools for any needed drilldown and cite the captured source titles/links and "
    "periods. Finish with submit_report, then stop."
)

PAIRED_TREATMENT_PREFIX = (
    "This is a paired recurring readout using the same owner-reviewed card, review, owner notes, "
    "three questions, and captured Superset source-response snapshot as the baseline. The shared "
    "snapshot consists of real read-only Superset HTTP responses captured at request time; it is "
    "not an atomic warehouse snapshot or an as-of guarantee. Use the approved scope and the same "
    "source tools for numeric facts in the report. Produce one human-facing readout of at most "
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
    "explicit_deferred": (
        "Apply the explicit deferred path: call evaluate_insight_card once with the supplied "
        "idempotency key. If result.judgment.status is deferred, follow result.evidence_access: "
        "page every relevant advertised result_path with get_decision_receipt, offset, and limit, "
        "following next_offset until complete. Include source_by_key, source_contracts, and the "
        "advertised judgment_state observation/evidence pages before analysis. Use those materials "
        "only as evidence for your frontier analysis. They are not a typed policy "
        "outcome; do not invent one. Compare source claims with the same shared source snapshot. "
        "If a typed judgment is returned instead, report that as-is and do not force a deferral."
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
    elif stage in {"paired-treatment-original_policy", "paired-treatment-explicit_deferred"}:
        mode = stage.removeprefix("paired-treatment-")
        task_rules = PAIRED_TREATMENT_PREFIX + PAIRED_TREATMENT_MODES[mode] + " Finish with submit_report, then stop."
    else:
        raise ValueError(f"unknown journey stage: {stage}")
    common = (
        "You are a business-intelligence analyst using the trial's captured, read-only Superset "
        "source-response snapshot. The business owner supplied the context in the task; do not "
        "invent metric definitions, comparison windows, thresholds, recipients, or desired outcomes. "
        "Answer all three questions from inspected evidence. Treat returned periods and comparison "
        "coverage exactly as reported; a recent bucket is not proof of a complete/comparable period. "
        "Follow up with direct source-tool reads only inside the approved snapshot; missing snapshot "
        "coverage is a gap, not permission to expand scope. Label saved-chart query rows as such. "
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
        "provider_request_count": judgment.get("provider_request_count"),
        "judgment_request_sent": judgment.get("judgment_request_sent"),
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


_CAPTURE_TIME_FIELDS = frozenset({"captured_at", "source_captured_at"})
_BUSINESS_SNAPSHOT_FIELDS = (
    "observations", "analytical_comparisons", "evidence", "error",
)
_SOURCE_DEFINITION_FIELDS = (
    "source_key", "adapter", "resource", "title", "description",
    "metadata", "source_url", "contract",
)


def _without_capture_times(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_capture_times(item)
            for key, item in value.items()
            if key not in _CAPTURE_TIME_FIELDS
        }
    if isinstance(value, list):
        return [_without_capture_times(item) for item in value]
    return value


def _digest_json(value: Any) -> str:
    encoded = json.dumps(
        _without_capture_times(value), sort_keys=True, separators=(",", ":"),
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


def compare_paired_source_snapshots(
    helper_by_key: dict[str, dict[str, Any]],
    native_by_key: dict[str, dict[str, Any]] | None,
    *,
    native_status: str,
    receipt_page_calls: int = 0,
) -> dict[str, Any]:
    """Compare only matching typed source snapshots; never infer parity from absence."""
    comparison: dict[str, Any] = {
        "status": "unverified",
        "native_snapshot_status": native_status,
        "receipt_page_calls": receipt_page_calls,
        "receipt_reads_are_local_read_only_and_do_not_rerun_sources_or_models": True,
        "capture_times_excluded_from_digests": sorted(_CAPTURE_TIME_FIELDS),
        "business_data_digest_scope": list(_BUSINESS_SNAPSHOT_FIELDS),
        "source_definition_digest_scope": list(_SOURCE_DEFINITION_FIELDS),
        "source_definition_limit": (
            "ResourceSnapshot identity, metadata, and contract only; raw saved-chart query params "
            "are not compared because the native receipt does not expose them."
        ),
        "helper_snapshot_is_frozen_but_native_evaluation_uses_separate_live_reads": True,
        "atomic_warehouse_snapshot_or_total_source_cost_claim": False,
        "per_source": {},
    }
    if native_by_key is None:
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
        helper_digests = _snapshot_digest_pair(helper)
        native_digests = _snapshot_digest_pair(native)
        comparison["per_source"][key] = {
            "business_data_status": (
                "equal" if helper_digests["business_data_sha256"] == native_digests["business_data_sha256"]
                else "different"
            ),
            "source_definition_status": (
                "equal" if helper_digests["source_definition_sha256"] == native_digests["source_definition_sha256"]
                else "different"
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
            comparison["business_data_status"], comparison["source_definition_status"]
        }
        else "equal"
        if comparison["business_data_status"] == comparison["source_definition_status"] == "equal"
        else "unverified"
    )
    return comparison


async def native_source_snapshots_for_comparison(
    native: InstalledServer,
    evaluation: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]] | None, str, int]:
    """Read deferred prepared snapshots from the durable local receipt, if available."""
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    result = evaluation.get("result")
    result = result if isinstance(result, dict) else {}
    direct = result.get("source_by_key")
    if isinstance(direct, dict) and all(isinstance(value, dict) for value in direct.values()):
        return direct, "available_in_evaluation", 0

    receipt = evaluation.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    judgment = result.get("judgment")
    judgment = judgment if isinstance(judgment, dict) else {}
    if not (
        receipt.get("status") == "decision_deferred"
        or judgment.get("status") == "deferred"
    ):
        return None, "not_exposed_for_non_deferred_result", 0
    receipt_id = receipt.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id:
        return None, "deferred_receipt_id_unavailable", 0

    sources: dict[str, dict[str, Any]] = {}
    offset = 0
    total: int | None = None
    page_calls = 0
    for _ in range(20):
        try:
            _, response = await native.call_tool("get_decision_receipt", {
                "receipt_id": receipt_id,
                "result_path": ["source_by_key"],
                "offset": offset,
                "limit": 100,
            })
        except Exception:  # noqa: BLE001 - report unavailable without leaking receipt contents
            return None, "receipt_page_read_failed", page_calls
        page_calls += 1
        if not isinstance(response, dict) or response.get("status") != "found":
            return None, "receipt_page_unavailable", page_calls
        page = response.get("result_page")
        if not isinstance(page, dict) or page.get("kind") != "object":
            return None, "source_snapshot_section_unavailable", page_calls
        if page.get("oversized_item") is not None:
            return None, "source_snapshot_page_contains_oversized_item", page_calls
        items = page.get("items")
        if not isinstance(items, list):
            return None, "source_snapshot_page_malformed", page_calls
        if total is None:
            total = page.get("total") if isinstance(page.get("total"), int) else None
        for item in items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("key"), str)
                or not isinstance(item.get("value"), dict)
                or item["key"] in sources
            ):
                return None, "source_snapshot_page_malformed", page_calls
            sources[item["key"]] = item["value"]
        next_offset = page.get("next_offset")
        if not page.get("has_more"):
            if total is None or len(sources) != total:
                return None, "source_snapshot_page_incomplete", page_calls
            return sources, "available_from_deferred_receipt", page_calls
        expected_next = offset + len(items)
        if not items or next_offset != expected_next or expected_next <= offset:
            return None, "source_snapshot_page_incomplete", page_calls
        offset = expected_next
    return None, "source_snapshot_page_limit_reached", page_calls


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
    ):
        super().__init__(adapter, native)
        self.stage = stage
        self.max_data_reads = max_data_reads
        self.source_snapshot = source_snapshot
        self.max_report_words = max_report_words
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
            if self.evaluation is not None:
                raise ValueError("evaluate_insight_card may be called only once per run")
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

    started_at = datetime.now(timezone.utc)
    http_before = adapter.client.requests_made
    dashboards: dict[str, dict[str, Any]] = {}
    charts: dict[str, dict[str, Any]] = {}
    resources: list[dict[str, Any]] = []
    captured: list[dict[str, str]] = []
    data_read_calls = 0

    for raw_source in source_refs:
        source = SourceRef.model_validate(raw_source)
        if source.adapter != "superset" or not source.resource.startswith("dashboard:"):
            raise ValueError("paired Superset snapshot supports only approved dashboard sources")
        dashboard_id = source.resource.removeprefix("dashboard:")
        if not dashboard_id.isdigit() or dashboard_id in dashboards:
            raise ValueError("approved dashboard references must be unique numeric IDs")
        if data_read_calls >= max_data_reads:
            raise ValueError("paired_snapshot_data_read_budget_exhausted")
        request_started = datetime.now(timezone.utc)
        resource_snapshot = await adapter.inspect(source)
        dashboard = resource_snapshot.model_dump(mode="json")
        request_finished = datetime.now(timezone.utc)
        data_read_calls += 1
        dashboards[dashboard_id] = dashboard
        captured.append({
            "kind": "dashboard",
            "resource": source.resource,
            "request_started_at": request_started.isoformat(),
            "request_finished_at": request_finished.isoformat(),
        })

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
                "saved_query_definition": chart.get("params"),
                "rows": rows,
                "scope": "standalone saved chart query, not dashboard filter context",
            }
            captured.append({
                "kind": "chart_query",
                "resource": f"chart:{chart_id}",
                "request_started_at": request_started.isoformat(),
                "request_finished_at": request_finished.isoformat(),
            })

    finished_at = datetime.now(timezone.utc)
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
        "dashboard_count": len(dashboards),
        "chart_query_count": len(charts),
        "snapshot_payload_bytes": len(snapshot_bytes),
        "snapshot_payload_byte_cap": max_bytes,
        "data_read_calls": data_read_calls,
        "data_read_cap": max_data_reads,
        "superset_http_attempts": adapter.client.requests_made - http_before,
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
    snapshot = await capture_paired_source_snapshot(capture_adapter, card)
    paired: dict[str, Any] = {
        "phase": "paired-recurring",
        "comparison_design": "same reviewed card, owner notes, three questions, and exact frozen Superset helper responses in both arms; two repeats; treatment policy mode varies by repeat; native evaluation separately reads live approved sources",
        "mode_interpretation": "Both treatment modes run the same candidate binary. original_policy means the agent does not consume a deferred receipt bundle; explicit_deferred means it pages and uses the bundle when the candidate returns decision_deferred. This is not a comparison against the prior binary/runtime.",
        "snapshot": snapshot.manifest,
        "fresh_wizard_runs_in_this_phase": 1,
        "report_word_limit": MAX_PAIRED_REPORT_WORDS,
        "report_word_count_method": "whitespace-delimited words in submitted report only",
        "repeat_count": PAIRED_REPETITIONS,
        "policy_modes": list(PAIRED_POLICY_MODES),
        "limitations": [
            "The shared dashboard/chart responses are captured from real read-only Superset HTTP and replayed identically to all four readout agents; the capture is not atomic.",
            "Capture timestamps are request-time observations, not warehouse as-of timestamps or freshness proof.",
            "Native evaluation performs separate live approved-source reads; those are not instrumented or redirected through the frozen helper snapshot. The report compares per-source ResourceSnapshot digests when the durable deferred receipt exposes them, excluding captured_at and source_captured_at; otherwise parity is unverified.",
            "Business-data digests cover observations, analytical comparisons, evidence, and source error state. Source-definition digests cover ResourceSnapshot identity, metadata, and contract; raw saved-chart query params are not compared because the native receipt does not expose them.",
            "A matching digest means those prepared ResourceSnapshot fields matched the earlier captured helper response; it does not prove an atomic warehouse snapshot, identical underlying HTTP requests, or total source-cost parity.",
            "No numeric outcome labels or expected business classes are supplied; two repeats are descriptive, not a generalization sample.",
            "Direct helper and native internal reads do not support a total warehouse-cost comparison.",
            "The trial tool prevents reports over 300 whitespace-delimited words from being submitted.",
        ],
        "repeats": [],
    }
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
        baseline_episode = await _run_episode(
            baseline,
            audit=audit,
            stage="paired-baseline",
            prompt=baseline_prompt,
            skill=skill,
        )

        idempotency_key = f"paired-superset-{repeat}-{secrets.token_hex(12)}"
        treatment = CardJourneySession(
            None,
            native,
            stage="paired-treatment",
            source_snapshot=snapshot,
            max_report_words=MAX_PAIRED_REPORT_WORDS,
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
        treatment_episode = await _run_episode(
            treatment,
            audit=audit,
            stage=f"paired-treatment-{mode}",
            prompt=treatment_prompt,
            skill=skill,
        )
        native_sources, native_source_status, receipt_page_calls = (
            await native_source_snapshots_for_comparison(native, treatment.evaluation)
        )
        source_comparison = compare_paired_source_snapshots(
            helper_source_snapshots_by_key(snapshot, card),
            native_sources,
            native_status=native_source_status,
            receipt_page_calls=receipt_page_calls,
        )
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
                "native_source_snapshot_comparison": source_comparison,
                "shared_tool_names": sorted(SHARED_SOURCE_TOOLS),
                "native_monitor_tools": sorted(MONITOR_TOOLS),
            },
        })
    paired["shared_helper_snapshot_replayed_identically"] = len({
        arm["source_snapshot_sha256"]
        for item in paired["repeats"]
        for arm in (item["baseline"], item["treatment"])
    }) == 1
    return paired


async def run(args: argparse.Namespace) -> None:
    if not args.execute:
        raise SystemExit("No provider calls are made unless --execute is explicitly supplied.")
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
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-origin", choices=["github-actions", "local-build"], required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--owner-context-file", type=Path, required=True)
    parser.add_argument("--superset-url", default="http://127.0.0.1:18089")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("original", "paired-recurring"),
        default="original",
        help="Keep the historical one-shot comparison, or run two matched recurring readout pairs after approval.",
    )
    parser.add_argument("--execute", action="store_true", help="Explicitly enable live model calls and interactive owner approval")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

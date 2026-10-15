"""Paired, natural recurring-MCP trial over the registered monthly cadence fixture.

The default live run uses production MCP guidance over four registered stage-gate
periods. The agent calls tools itself and owns its final assessment; the harness
does not precompute a decision. Optional-tools mode retains the earlier
availability ablation. Messages stay in a caller-owned local mock outbox.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import tempfile
import time
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.bootstrap_agent_trial import (
    Audit,
    PublicSourceAdapter,
    RequestBudget,
    canonical,
    digest,
    function,
    write_exclusive,
)
from evaluations.bootstrap_owner_review import review_owner_artifact
from evaluations.bootstrap_scenarios import public_scenario
from evaluations.codex_trial_transport import codex_episode
from evaluations.installed_first_report_trial import _file_hash, _git_sha
from evaluations.installed_trial_transport import installed_server
from evaluations.installed_workflow_trial import (
    InstalledSession,
    assert_default_agent_profile,
    onboarding_instructions,
)
from scripts.binary_provenance import verify_binary
from signalweave.models import SourceRef

VERSION = "native-cadence-v3"
MODEL = "gpt-6-luna"
EFFORT = "xhigh"
ONBOARDING_TIMEOUT_SECONDS = 900
RECURRING_TIMEOUT_SECONDS = 360
RETROSPECTIVE_SCOPE = (
    "This is a retrospective monthly-close review of archived fixture measurements, not a current alert. "
    "Preserve each measurement cutoff; a replay gateway read now is not a warehouse freshness claim."
)
QUIET_OUTCOMES = frozenset({"ignore", "quiet"})
PRODUCTION_GUIDED_MODE = "production-guided"
OPTIONAL_TOOL_MODE = "optional-tools"
GUIDANCE_MODES = frozenset({PRODUCTION_GUIDED_MODE, OPTIONAL_TOOL_MODE})
PRODUCTION_NATIVE_TOOLS = frozenset({
    "get_signalweave_guide", "list_insight_cards",
    "get_insight_card", "evaluate_insight_card", "get_decision_receipt",
})
OPTIONAL_NATIVE_TOOLS = frozenset({
    "get_insight_card", "evaluate_insight_card", "get_decision_receipt",
})
NATIVE_TOOLS = PRODUCTION_NATIVE_TOOLS
NATIVE_DECISION_TOOLS = frozenset({"evaluate_insight_card", "get_decision_receipt"})
EXECUTION_MODES = frozenset({"agent-tool", "decision-first"})
PRODUCTION_COMMON_INSTRUCTIONS = (
    "You are the caller-owned agent for a retrospective archived business review, not a current alert. "
    "Use the same frozen reviewed card, saved notes, and source catalog provided to both arms. "
    "Inspect current-period evidence and compute only as useful. Make an independent assessment from evidence; "
    "a typed card decision is input, not proof, and you may disagree when same-period evidence supports it. "
    "Do not force an outcome or invent causes. For quiet, finish_run with no recipients; otherwise choose only "
    "canonical owner-directory recipients and write a factual summary of at most 120 words with period, source scope, why, "
    "and next step. Distinguish historical measurements from the replay read time. finish_run only writes to "
    "the local mock outbox; no external notification is sent."
)
COMMON_INSTRUCTIONS = (
    "You are the caller-owned agent for a read-only recurring business review. "
    "This is an archived monthly-close replay, not a current alert. Treat "
    "simulation_as_of as the historical measurement cutoff; query_capture_at is "
    "only the simulated MCP fetch time and does not establish fresh warehouse data. "
    "Apply the reviewed card and saved notes. Inspect the selected month's evidence only as needed; "
    "compute only when useful. A native card result is optional evidence, not an order: "
    "you may override it when same-period source evidence supports a different outcome. "
    "For a quiet result, finish_run with no recipients; this creates no human message. "
        "Otherwise choose only canonical recipients from the owner directory and write a "
        "concise factual summary of at most 120 words: state the period and source scope, "
    "why it matters, and the next step. Do not invent causes. Distinguish the current "
    "period from any historical or replay evidence. finish_run stores only in a local "
    "mock outbox; no external message is sent. There is no required tool or calculation.")


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _iso_clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _pilot_indices(registration: Any) -> list[int]:
    raw = _field(registration, "pilot_indices")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise ValueError("registration.pilot_indices must contain the four stage-gate indices")
    if any(type(index) is not int for index in raw) or len(set(raw)) != 4:
        raise ValueError("registration.pilot_indices must be four unique integer indices")
    return list(raw)


def select_periods(scenario: dict, registration: Any, cases: int | str = 4) -> list[dict]:
    """Select public periods and private labels separately; labels never enter prompts."""
    if cases not in {4, 12, "all"}:
        raise ValueError("cases must be 4 (stage gate), 12, or 'all'")
    public, private = scenario.get("public"), scenario.get("private")
    if not isinstance(public, dict) or not isinstance(private, dict):
        raise ValueError("cadence scenario must have public and private sections")
    periods = public.get("periods")
    labels = private.get("periods")
    if (not isinstance(periods, list) or not periods or not isinstance(labels, dict)
            or (cases != "all" and len(periods) != 12)):
        raise ValueError("cadence fixture must provide public periods and a private label map; legacy selection requires twelve")
    clocks = [_iso_clock(period["as_of"]) for period in periods]
    if any(b <= a for a, b in zip(clocks, clocks[1:], strict=False)):
        raise ValueError("cadence periods must have strictly increasing measurement cutoffs")
    if cases != "all" and any((b.year * 12 + b.month) - (a.year * 12 + a.month) != 1
                             for a, b in zip(clocks, clocks[1:], strict=False)):
        raise ValueError("cadence periods must be consecutive monthly closes")
    indices = _pilot_indices(registration) if cases == 4 else list(range(len(periods)))
    if any(index < 0 or index >= len(periods) for index in indices):
        raise ValueError("registration pilot index is outside the cadence period list")
    selected = []
    for index in indices:
        period = copy.deepcopy(periods[index])
        period_id = period.get("period_id")
        if not isinstance(period_id, str) or period_id not in labels:
            raise ValueError("each selected period must have one private expected label")
        selected.append({"index": index, "period": period, "label": copy.deepcopy(labels[period_id])})
    return selected


def expected_result(label: dict) -> tuple[str, list[str], str | None]:
    """Map the fixture's private class to its product outcome, for scoring only."""
    outcome = label.get("outcome")
    category = label.get("class", label.get("category", label.get("condition")))
    if outcome is None:
        outcome = {"quiet": "ignore", "missing": "insufficient_data"}.get(category, category)
    if outcome in {"quiet"}:
        outcome = "ignore"
    if outcome == "missing":
        outcome = "insufficient_data"
    recipients = label.get("recipients", [])
    if not isinstance(outcome, str) or not isinstance(recipients, list):
        raise ValueError("private label must define an outcome and recipient list")
    return outcome, list(recipients), category


def _directory(destinations: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in destinations:
        key, endpoint = item.get("key"), item.get("destination")
        if not isinstance(key, str) or not key or not isinstance(endpoint, str) or not endpoint:
            raise ValueError("recipient directory entries need canonical keys and destinations")
        if key in result and result[key] != endpoint:
            raise ValueError("recipient directory has conflicting canonical keys")
        result[key] = endpoint
    return result


def make_outbox_submission(
    arguments: dict,
    *,
    destinations: list[dict],
    allowed_outcomes: list[str],
    inspected_refs: set[str],
    evidence_aliases: Mapping[str, str] | None = None,
    period_id: str,
    arm: str,
) -> tuple[dict, list[dict]]:
    """Validate a caller-owned report and create zero or one message per route."""
    directory = _directory(destinations)
    outcome = arguments.get("outcome")
    recipients = arguments.get("recipients")
    summary = arguments.get("summary")
    evidence_refs = arguments.get("evidence_refs")
    if outcome not in allowed_outcomes:
        raise ValueError("outcome is not in the public card outcome contract")
    if not isinstance(recipients, list) or len(set(recipients)) != len(recipients):
        raise ValueError("recipients must be a unique list of canonical directory keys")
    if set(recipients) - set(directory):
        raise ValueError("recipients must resolve through the supplied owner directory")
    if not isinstance(summary, str) or len(summary.split()) > 120:
        raise ValueError("summary must be text of at most 120 words")
    if (not isinstance(evidence_refs, list)
            or any(not isinstance(ref, str) for ref in evidence_refs)
            or len(set(evidence_refs)) != len(evidence_refs)):
        raise ValueError("evidence_refs must be a unique list")
    aliases = evidence_aliases or {}
    normalized_refs = [aliases.get(ref, ref) for ref in evidence_refs]
    if set(normalized_refs) - inspected_refs:
        raise ValueError("evidence_refs must cite a source inspected or a successful current-run receipt")
    normalized_refs = list(dict.fromkeys(normalized_refs))
    if outcome in QUIET_OUTCOMES:
        if recipients:
            raise ValueError("quiet outcomes must have no recipients")
        messages = []
    else:
        if not recipients or not summary.strip() or not evidence_refs:
            raise ValueError("actionable outcomes need recipients, a summary, and current evidence refs")
        messages = [
            {"owner": "caller_owned_agent", "sink": "local_mock_outbox",
             "period_id": period_id, "arm": arm, "recipient_key": key,
             "destination": directory[key], "summary": summary,
             "evidence_refs": list(normalized_refs), "external_send_attempted": False}
            for key in recipients
        ]
    submission = {"outcome": outcome, "recipients": list(recipients),
                  "summary": summary.strip(), "evidence_refs": list(normalized_refs)}
    return submission, messages


class TimedSourceAdapter(PublicSourceAdapter):
    def set_period(self, period: dict, clock: datetime) -> None:
        """Replay an old monthly close without rewriting its business timestamps."""
        captured_at = clock.astimezone(timezone.utc)
        captured_text = captured_at.isoformat()
        self.clock = captured_at
        self.period_context = {
            "period_id": period["period_id"],
            # Owner-review context expects the conventional period schema.
            # This remains the historical business cutoff, not the replay read time.
            "as_of": period["as_of"],
            "simulation_as_of": period["as_of"],
            "query_capture_at": captured_text,
            "time_basis": "historical_fixture_replay",
        }
        self.snapshots = copy.deepcopy(period["snapshots"])
        self.successful_inspected_refs: set[str] = set()
        for snapshot in self.snapshots.values():
            metadata = snapshot.setdefault("metadata", {})
            original_capture = snapshot.get("source_captured_at")
            metadata["native_cadence_replay"] = {
                "historical_fixture": True,
                "warehouse_freshness_asserted": False,
                "gateway_response_captured_at": captured_text,
                "original_saved_source_capture": original_capture,
            }
            # Only the synthetic gateway receipt is new. Measurement rows,
            # event times, month/cutoff fields, and freshness annotations stay as saved.
            snapshot["captured_at"] = captured_text
            snapshot["source_captured_at"] = captured_text
        self.inspected.clear()
        self.inspections = 0

    async def inspect(self, source):
        started = time.perf_counter()
        try:
            snapshot = await super().inspect(source)
            ref = f"{source.adapter}|{source.resource}"
            if snapshot.error is None:
                self.successful_inspected_refs.add(ref)
            return snapshot
        finally:
            self.audit.emit("source.timing", ref=f"{source.adapter}|{source.resource}",
                            seconds=time.perf_counter() - started)


class CadenceSession(InstalledSession):
    def __init__(self, public, adapter, server, treatment, *, arm: str,
                 guidance_mode: str = PRODUCTION_GUIDED_MODE, **kwargs):
        if guidance_mode not in GUIDANCE_MODES:
            raise ValueError(f"guidance_mode must be one of {sorted(GUIDANCE_MODES)}")
        # The registered cadence fixture has no benchmark numeric vocabulary;
        # common tool-schema construction still expects an empty one.
        public = {**public, "numeric_vocabulary": public.get("numeric_vocabulary", [])}
        super().__init__(public, adapter, server, treatment, **kwargs)
        self.arm, self.guidance_mode = arm, guidance_mode
        self.outbox: list[dict] = []
        self.native_results: list[dict] = []
        self.evidence_aliases: dict[str, str] = {}
        self.source_url_refs: dict[str, set[str]] = {}
        self.current_idempotency_key: str | None = None

    def _record_snapshot_urls(self, snapshot: dict, ref: str, source_keys: set[str]) -> None:
        source_url = snapshot.get("source_url")
        if isinstance(source_url, str) and source_url:
            self.source_url_refs.setdefault(source_url, set()).add(ref)
        for source_key, evidence_url in _reported_source_url_bindings(snapshot):
            if source_key in source_keys:
                self.source_url_refs.setdefault(evidence_url, set()).add(ref)

    async def specs(self):
        specs = await super().specs()
        if self.phase == "monitoring":
            specs = [spec for spec in specs if spec["name"] != "submit_analysis"]
        tools = await self.server.list_tools()
        available = {tool.name: tool for tool in tools}
        descriptions = {
            "search_catalog": "Search the shared read-only source catalog; results are candidates, not a decision.",
            "inspect_resource": "Inspect one authorized resource in the shared read-only source catalog.",
            "get_insight_card": "Read the frozen reviewed card and policy by stable ID.",
            "evaluate_insight_card": (
                "Optionally evaluate the approved card against current sources in shadow mode. "
                "This may call the configured decision provider; use only if helpful. It is not required."),
            "get_decision_receipt": "Optionally recover a prior durable decision; this does not rerun sources or models.",
        }
        active_native_tools = (PRODUCTION_NATIVE_TOOLS if self.guidance_mode == PRODUCTION_GUIDED_MODE
                               else OPTIONAL_NATIVE_TOOLS)
        if self.phase == "monitoring" and self.treatment:
            enabled = active_native_tools & available.keys()
            self.allowed_product |= set(enabled)
            for name in enabled:
                tool = available[name]
                specs.append({"type": "function", "name": name,
                              "description": (tool.description
                                              if self.guidance_mode == PRODUCTION_GUIDED_MODE
                                              else descriptions.get(name, tool.description)),
                              "parameters": tool.inputSchema, "strict": False})
        if self.guidance_mode == OPTIONAL_TOOL_MODE:
            for spec in specs:
                if spec["name"] in descriptions:
                    spec["description"] = descriptions[spec["name"]]
        if self.phase == "monitoring":
            specs.append(function(
                "finish_run",
                "Record this period's final caller-owned assessment. Quiet outcomes create no message; "
                "other outcomes create one local mock-outbox message per canonical recipient. Never sends externally.",
                {"outcome": {"type": "string", "enum": self.public["submission_contract"]["outcomes"]},
                 "recipients": {"type": "array", "items": {"type": "string",
                                  "enum": [item["key"] for item in self.public["destinations"]]},
                                "uniqueItems": True},
                 "summary": {"type": "string"},
                 "evidence_refs": {"type": "array", "items": {"type": "string"},
                                   "uniqueItems": True}},
                ["outcome", "recipients", "summary", "evidence_refs"],
            ))
        return specs

    async def call(self, name, arguments):
        if name == "search_catalog":
            page = await self.registry.search_resources(
                str(arguments.get("query", "")),
                adapter_name=arguments.get("adapter"),
                limit=int(arguments.get("limit", 25)),
                cursor=arguments.get("cursor"),
                authorized_tenants=[self.tenant_id],
            )
            result = page.model_dump(mode="json")
            self.adapter.audit.emit("shared_source_tool", name=name, arm=self.arm,
                                    refs=[f"{item.get('adapter')}|{item.get('resource')}"
                                          for item in result.get("resources", [])])
            return result
        if name == "inspect_resource":
            adapter, resource = arguments["adapter"], arguments["resource"]
            source = SourceRef(key=f"inspect-{digest([adapter, resource])[:16]}",
                               adapter=adapter, resource=resource,
                               label=arguments.get("label") or resource,
                               parameters=arguments.get("parameters") or {})
            snapshot = await self.registry.inspect(source, authorized_tenants=[self.tenant_id])
            ref = f"{adapter}|{resource}"
            self.agent_inspected.add(ref)
            result = snapshot.model_dump(mode="json")
            self.evidence_aliases[source.key] = ref
            self.evidence_aliases[ref] = ref
            if isinstance(result.get("source_key"), str):
                self.evidence_aliases[result["source_key"]] = ref
            self._record_snapshot_urls(
                result, ref, {source.key, resource, result.get("source_key")})
            self.adapter.audit.emit("shared_source_tool", name=name, arm=self.arm, ref=ref)
            return result
        if name == "finish_run" and self.phase == "monitoring":
            period_id = self.adapter.period_context["period_id"]
            evidence_refs = set(self.agent_inspected) | set(self.adapter.inspected)
            evidence_aliases = dict(self.evidence_aliases)
            native_aliases = _current_native_evidence_aliases(
                self, self.shared_card or {}, self.current_idempotency_key or "",
                source_url_refs=self.source_url_refs)
            evidence_aliases.update(native_aliases)
            evidence_refs.update(native_aliases.values())
            for source_url, refs in self.source_url_refs.items():
                if len(refs) > 1:
                    evidence_aliases.pop(source_url, None)
            if self.current_idempotency_key:
                evidence_refs |= _current_receipt_refs(
                    self, self.shared_card or {}, self.current_idempotency_key)
            # Keep current canonical refs accepted even when cited through an alias.
            evidence_aliases.update({ref: ref for ref in evidence_refs})
            result, messages = make_outbox_submission(
                arguments,
                destinations=self.public["destinations"],
                allowed_outcomes=self.public["submission_contract"]["outcomes"],
                inspected_refs=evidence_refs,
                evidence_aliases=evidence_aliases,
                period_id=period_id,
                arm=self.arm,
            )
            self.submission = result
            self.outbox.extend(messages)
            self.adapter.audit.emit("local_mock_outbox", period_id=period_id, arm=self.arm,
                                    message_count=len(messages), recipient_keys=result["recipients"])
            return {"recorded": True, "message_count": len(messages),
                    "external_send_attempted": False}
        active_native_tools = (PRODUCTION_NATIVE_TOOLS if self.guidance_mode == PRODUCTION_GUIDED_MODE
                               else OPTIONAL_NATIVE_TOOLS)
        if name in active_native_tools and self.phase == "monitoring" and self.treatment:
            started = time.perf_counter()
            try:
                result = await self.product(name, arguments)
            except Exception as error:
                if name in {"evaluate_insight_card", "get_decision_receipt"}:
                    self.native_results.append({"name": name, "arguments": copy.deepcopy(arguments),
                                                "returned": False,
                                                "error_type": type(error).__name__})
                raise
            finally:
                self.adapter.audit.emit("native_product_tool_timing", name=name,
                                        seconds=time.perf_counter() - started)
            if name in {"evaluate_insight_card", "get_decision_receipt"}:
                self.native_results.append({"name": name, "arguments": copy.deepcopy(arguments),
                                            "returned": True, "result": copy.deepcopy(result)})
            return result
        result = await super().call(name, arguments)
        if name in {"inspect_source", "analyze_source"} and self.phase == "monitoring":
            ref = arguments["ref"]
            snapshot = result.get("snapshot", {}) if isinstance(result, dict) else {}
            self.evidence_aliases[ref] = ref
            source_key = snapshot.get("source_key") if isinstance(snapshot, dict) else None
            if isinstance(source_key, str) and source_key:
                self.evidence_aliases[source_key] = ref
            resource = ref.split("|", 1)[-1]
            if isinstance(snapshot, dict):
                self._record_snapshot_urls(snapshot, ref, {resource, source_key})
        return result


class _MessageReviewSession:
    phase = "narrative_review"
    treatment = False
    setup_complete = False
    submission = None
    shared_card = None

    def __init__(self, message_ids: list[str]):
        self.message_ids = message_ids

    async def specs(self):
        return [function("review_messages",
                         "Submit exactly one independent evidence-based classification for every supplied message_id. "
                         "verdict and rationale are required; issues may be omitted and defaults to an empty list.",
                         {"reviews": {"type": "array", "items": {
                             "type": "object", "additionalProperties": False,
                             "properties": {
                                 "message_id": {"type": "string", "enum": self.message_ids},
                                 "verdict": {"type": "string", "enum": ["supported", "needs_attention", "cannot_assess"]},
                                 "issues": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                                 "rationale": {"type": "string"}},
                             "required": ["message_id", "verdict", "rationale"]},
                           "minItems": len(self.message_ids), "maxItems": len(self.message_ids)}},
                         ["reviews"])]

    async def call(self, name, arguments):
        if name != "review_messages":
            raise ValueError("unknown review tool")
        rows = arguments.get("reviews")
        ids = ([row.get("message_id") for row in rows]
               if isinstance(rows, list) and all(isinstance(row, dict) for row in rows) else [])
        if len(ids) != len(set(ids)) or set(ids) != set(self.message_ids):
            raise ValueError("review every supplied message exactly once")
        normalized = []
        for row in rows:
            if (not isinstance(row, dict) or set(row) - {"message_id", "verdict", "issues", "rationale"}
                    or row.get("verdict") not in {"supported", "needs_attention", "cannot_assess"}
                    or not isinstance(row.get("rationale"), str) or not row["rationale"].strip()):
                raise ValueError("each review needs a valid verdict and non-empty rationale")
            issues = row.get("issues", [])
            if (not isinstance(issues, list) or len(issues) > 5
                    or any(not isinstance(issue, str) for issue in issues)):
                raise ValueError("issues must be omitted or a list of at most five strings")
            normalized.append({**row, "issues": list(issues)})
        self.submission = {"reviews": normalized}
        return {"recorded": True, "review_count": len(rows)}


def _expected_score(submission: dict | None, label: dict, outbox: list[dict], *,
                    evidence_mode: str = "none", proof_refs: list[str] | None = None) -> dict:
    expected_outcome, expected_recipients, category = expected_result(label)
    proof_refs = proof_refs or []
    if submission is None:
        return {"observed": False, "category": category, "expected_outcome": expected_outcome,
                "expected_recipients": expected_recipients, "outcome_correct": None,
                "routing_correct": None, "expected_outbox_count": (
                    0 if expected_outcome in QUIET_OUTCOMES else len(expected_recipients)),
                "actual_outbox_count": len(outbox), "outbox_count_correct": None,
                "evidence_mode": evidence_mode, "primary_current_proof": evidence_mode != "none",
                "primary_current_proof_refs": proof_refs}
    expected_count = 0 if expected_outcome in QUIET_OUTCOMES else len(expected_recipients)
    actual_recipients = submission.get("recipients", [])
    actual_quiet = submission.get("outcome") in QUIET_OUTCOMES
    quiet_grade_eligible = not actual_quiet or (evidence_mode != "none" and bool(proof_refs))
    return {"observed": True, "category": category, "expected_outcome": expected_outcome,
            "actual_outcome": submission.get("outcome"), "outcome_correct": (
                submission.get("outcome") == expected_outcome if quiet_grade_eligible else None),
            "expected_recipients": expected_recipients,
            "actual_recipients": actual_recipients,
            "routing_correct": (set(actual_recipients) == set(expected_recipients)
                                if quiet_grade_eligible else None),
            "expected_outbox_count": expected_count, "actual_outbox_count": len(outbox),
            "outbox_count_correct": (len(outbox) == expected_count if quiet_grade_eligible else None),
            "quiet_grade_eligible": quiet_grade_eligible,
            "evidence_mode": evidence_mode, "primary_current_proof": evidence_mode != "none",
            "primary_current_proof_refs": proof_refs}


def _card_primary_refs(card: dict | None, catalog: list[Any]) -> dict[str, str]:
    """Map card source aliases only where the public catalog declares role=primary."""
    if not isinstance(card, dict):
        return {}
    sources = card.get("sources")
    if not isinstance(sources, list):
        return {}
    primary_catalog_refs = set()
    for item in catalog:
        contract = _field(item, "contract")
        roles = _field(contract, "roles", [])
        adapter, resource = _field(item, "adapter"), _field(item, "resource")
        if (isinstance(roles, (list, tuple)) and "primary" in roles
                and isinstance(adapter, str) and isinstance(resource, str)):
            primary_catalog_refs.add(f"{adapter}|{resource}")
    refs = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        key, adapter, resource = source.get("key"), source.get("adapter"), source.get("resource")
        ref = f"{adapter}|{resource}"
        if (all(isinstance(value, str) and value for value in (key, adapter, resource))
                and ref in primary_catalog_refs):
            refs[key] = ref
    return refs


def _valid_current_native_result(response: dict, card: dict, expected_key: str) -> tuple[dict, dict] | None:
    receipt = response.get("receipt") if isinstance(response, dict) else None
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(receipt, dict) or not isinstance(result, dict):
        return None
    if (receipt.get("idempotency_key") != expected_key
            or receipt.get("card_id") != card.get("id")
            or receipt.get("card_version") != card.get("version")
            or receipt.get("status") not in {"delivery_disabled", "replayed"}
            or receipt.get("delivery_enabled") is not False
            or receipt.get("delivery_mode") != "shadow"
            or result.get("card_id") != card.get("id")
            or not isinstance(result.get("outcome"), str)):
        return None
    return receipt, result


def _valid_current_receipt_page(call: dict, card: dict, expected_key: str) -> tuple[dict, dict] | None:
    response = call.get("result")
    receipt = response.get("receipt") if isinstance(response, dict) else None
    page = response.get("result_page") if isinstance(response, dict) else None
    arguments = call.get("arguments")
    if (call.get("name") != "get_decision_receipt" or not isinstance(arguments, dict)
            or not isinstance(receipt, dict) or not isinstance(page, dict)
            or response.get("status") != "found"
            or arguments.get("receipt_id") != receipt.get("receipt_id")
            or receipt.get("idempotency_key") != expected_key
            or receipt.get("card_id") != card.get("id")
            or receipt.get("card_version") != card.get("version")
            or receipt.get("status") not in {"delivery_disabled", "replayed"}
            or receipt.get("delivery_enabled") is not False
            or receipt.get("delivery_mode") != "shadow"
            or not isinstance(page.get("path"), list)
            or page.get("kind") not in {"list", "object"}
            or not isinstance(page.get("items"), list)):
        return None
    return receipt, page


def _reported_source_keys(value: Any) -> set[str]:
    keys = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            key = item.get("source_key")
            if isinstance(key, str):
                keys.add(key)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return keys


def _reported_source_url_bindings(value: Any) -> set[tuple[str, str]]:
    bindings = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            source_key, source_url = item.get("source_key"), item.get("source_url")
            if (isinstance(source_key, str) and source_key
                    and isinstance(source_url, str) and source_url):
                bindings.add((source_key, source_url))
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return bindings


def _native_primary_refs(response: dict, card: dict, expected_key: str,
                         primary_refs: dict[str, str]) -> set[str]:
    """Accept only a successful, on-card native result bound to this exact run key."""
    valid = _valid_current_native_result(response, card, expected_key)
    if valid is None:
        return set()
    _, result = valid
    aliases = {
        item.get("source_key") for item in [*result.get("evidence", []),
                                             *result.get("observations", [])]
        if isinstance(item, dict) and isinstance(item.get("source_key"), str)
    }
    successful_resource_aliases = {
        item.get("source_key") for item in response.get("resources", [])
        if isinstance(item, dict) and item.get("error") is None
        and isinstance(item.get("source_key"), str)
    }
    aliases |= successful_resource_aliases
    return {primary_refs[key] for key in aliases if key in primary_refs}


def _native_review_evidence(response: dict, card: dict, expected_key: str) -> dict | None:
    valid = _valid_current_native_result(response, card, expected_key)
    if valid is None:
        return None
    receipt, result = valid
    return {
        "receipt": {key: receipt.get(key) for key in
                    ("receipt_id", "idempotency_key", "card_id", "card_version", "status")},
        "decision": {key: result.get(key) for key in
                     ("outcome", "summary", "rationale", "source_keys", "evidence", "observations")},
    }


def _native_success_count(session: CadenceSession, card: dict, expected_key: str) -> int:
    return sum(call.get("returned") is True and _valid_current_native_result(
        call.get("result", {}), card, expected_key) is not None for call in session.native_results)


def _current_native_evidence_aliases(session: CadenceSession, card: dict,
                                     expected_key: str, *,
                                     source_url_refs: dict[str, set[str]] | None = None) -> dict[str, str]:
    """Resolve only aliases bound to this card and its validated current receipt."""
    source_refs = {
        source["key"]: f"{source['adapter']}|{source['resource']}"
        for source in card.get("sources", []) if isinstance(source, dict)
        if all(isinstance(source.get(field), str) and source[field]
               for field in ("key", "adapter", "resource"))
    }
    aliases: dict[str, str] = {}
    url_refs = source_url_refs if source_url_refs is not None else {}
    for call in session.native_results:
        if call.get("returned") is not True:
            continue
        page_valid = _valid_current_receipt_page(call, card, expected_key)
        if page_valid is not None:
            receipt, page = page_valid
            source_keys = _reported_source_keys(page["items"])
            source_url_records = _reported_source_url_bindings(page["items"])
        else:
            valid = _valid_current_native_result(call.get("result", {}), card, expected_key)
            if valid is None:
                continue
            receipt, result = valid
            reported_source_keys = result.get("source_keys", [])
            source_keys = set(reported_source_keys) if isinstance(reported_source_keys, list) else set()
            source_keys.update(_reported_source_keys(result.get("evidence", [])))
            source_keys.update(_reported_source_keys(result.get("observations", [])))
            source_keys.update(_reported_source_keys(call["result"].get("resources", [])))
            source_url_records = _reported_source_url_bindings([
                result.get("evidence", []), result.get("observations", []),
                call["result"].get("resources", []),
            ])
        receipt_id = receipt.get("receipt_id")
        if isinstance(receipt_id, str) and receipt_id:
            aliases[receipt_id] = f"receipt:{expected_key}"
        for key in source_keys:
            if isinstance(key, str) and key in source_refs:
                aliases[key] = source_refs[key]
        for key, source_url in source_url_records:
            if key in source_refs:
                url_refs.setdefault(source_url, set()).add(source_refs[key])
    for source_url, refs in url_refs.items():
        if len(refs) == 1:
            aliases[source_url] = next(iter(refs))
    return aliases


def _current_receipt_refs(session: CadenceSession, card: dict, expected_key: str) -> set[str]:
    return {f"receipt:{expected_key}"} if _native_success_count(session, card, expected_key) else set()


def _required_card_source_refs(card: dict) -> dict[str, tuple[str, str]] | None:
    sources = card.get("sources")
    if not isinstance(sources, list):
        return None
    required = {}
    for source in sources:
        if not isinstance(source, dict):
            return None
        is_required = source.get("required", True)
        if type(is_required) is not bool:
            return None
        if not is_required:
            continue
        key, adapter, resource = (source.get("key"), source.get("adapter"),
                                  source.get("resource"))
        if not all(isinstance(value, str) and value for value in (key, adapter, resource)):
            return None
        if key in required:
            return None
        required[key] = (adapter, resource)
    return required


def _unit_interval_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= 1
    except OverflowError:
        return False


def _explicit_source_issue(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    values = item.get("values")
    details = [item, values] if isinstance(values, dict) else [item]
    for detail in details:
        if detail.get("error") or detail.get("message") or detail.get("blocking") is True:
            return True
        status = detail.get("quality_status")
        if status not in (None, "", "healthy", "complete"):
            return True
    return False


def _required_source_has_quality_issue(response: dict, result: dict,
                                       contracts_by_key: dict[str, dict],
                                       required_keys: set[str]) -> bool:
    for key in required_keys:
        source_contract = contracts_by_key[key].get("contract")
        if isinstance(source_contract, dict):
            status = source_contract.get("source_status")
            if (status is not None and status != "healthy") or source_contract.get("authorized") is False:
                return True

    for collection in (result.get("source_errors"), result.get("evidence"),
                       response.get("resources")):
        if isinstance(collection, list) and any(
            isinstance(item, dict) and item.get("source_key") in required_keys
            and _explicit_source_issue(item)
            for item in collection
        ):
            return True

    observations = result.get("observations")
    if isinstance(observations, list):
        for item in observations:
            if not isinstance(item, dict) or item.get("source_key") not in required_keys:
                continue
            attributes = item.get("attributes")
            status = attributes.get("source_status") if isinstance(attributes, dict) else None
            freshness = item.get("freshness")
            if ((status is not None and status != "healthy")
                    or isinstance(freshness, str) and "stale" in freshness.lower()):
                return True
    return False


def _required_source_evidence_keys(result: dict) -> set[str]:
    keys = set()
    for collection_name in ("evidence", "observations"):
        collection = result.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if (isinstance(item, dict) and isinstance(item.get("source_key"), str)
                    and item.get("source_key") and not _explicit_source_issue(item)):
                keys.add(item["source_key"])
    return keys


def _native_handoff_complete(response: dict, result: dict) -> bool:
    access = response.get("evidence_access")
    if access is None:
        access = result.get("evidence_access")
    if access is None:
        return True
    if not isinstance(access, dict) or access.get("complete") is not True:
        return False
    for field in ("source_contract_coverage", "observation_coverage"):
        section = access.get(field)
        if section is not None and (
            not isinstance(section, dict) or section.get("coverage") != "complete_section"
        ):
            return False
    return True


def _decision_first_quiet_eligibility(session: CadenceSession, response: Any,
                                      expected_key: str) -> dict:
    """Allow a no-frontier quiet only on a bound, fully covered native result."""
    valid = _valid_current_native_result(response, session.shared_card or {}, expected_key)
    if valid is None:
        return {"eligible": False, "reason": "invalid_current_receipt",
                "valid_current_result": False, "evidence_mode": "none", "proof_refs": []}
    receipt, result = valid
    if (not isinstance(receipt.get("receipt_id"), str)
            or not receipt["receipt_id"].strip()):
        return {"eligible": False, "reason": "missing_receipt_id",
                "valid_current_result": False, "evidence_mode": "none", "proof_refs": []}
    if result.get("outcome") != "ignore":
        return {"eligible": False, "reason": "native_non_ignore",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}
    delivery_methods = result.get("delivery_methods")
    if not isinstance(delivery_methods, list) or delivery_methods:
        return {"eligible": False, "reason": "native_ignore_has_delivery_methods",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}
    if not _native_handoff_complete(response, result):
        return {"eligible": False, "reason": "incomplete_receipt_handoff",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}

    card = session.shared_card or {}
    required_refs = _required_card_source_refs(card)
    if not required_refs:
        return {"eligible": False, "reason": "required_source_coverage_unavailable",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}

    confidence = result.get("confidence")
    threshold = card.get("action_confidence_threshold", 0.70)
    if confidence is None:
        return {"eligible": False, "reason": "confidence_missing",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}
    if not _unit_interval_number(confidence) or not _unit_interval_number(threshold):
        return {"eligible": False, "reason": "confidence_invalid",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}
    if confidence < threshold:
        return {"eligible": False, "reason": "confidence_below_threshold",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}

    source_contracts = result.get("source_contracts")
    if not isinstance(source_contracts, list):
        return {"eligible": False, "reason": "required_source_contracts_missing",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}
    contracts_by_key = {}
    for item in source_contracts:
        if isinstance(item, dict) and item.get("source_key") in required_refs:
            contracts_by_key.setdefault(item["source_key"], []).append(item)
    if any(
        len(contracts_by_key.get(key, [])) != 1
        or (contracts_by_key[key][0].get("adapter"), contracts_by_key[key][0].get("resource"))
        != source_ref
        for key, source_ref in required_refs.items()
    ):
        return {"eligible": False, "reason": "required_source_contracts_incomplete",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}

    if _required_source_has_quality_issue(response, result,
                                          {key: items[0] for key, items in contracts_by_key.items()},
                                          set(required_refs)):
        return {"eligible": False, "reason": "required_source_quality_unhealthy",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}

    if not set(required_refs).issubset(_required_source_evidence_keys(result)):
        return {"eligible": False, "reason": "required_source_evidence_incomplete",
                "valid_current_result": True, "evidence_mode": "none", "proof_refs": []}
    # Controller routing uses the card's required scope. Benchmark grading below
    # intentionally keeps its separate catalog-role-based primary-source proof.
    proof_refs = sorted({f"{adapter}|{resource}" for adapter, resource in required_refs.values()})
    return {"eligible": True, "reason": None, "valid_current_result": True,
            "evidence_mode": "required_card_sources_current_run", "proof_refs": proof_refs}


async def _decision_first_preflight(session: CadenceSession, audit: Audit) -> dict:
    """Run one native decision before the frontier, shortcutting only complete quiet."""
    expected_key = session.current_idempotency_key or ""
    card = session.shared_card or {}
    started = time.perf_counter()
    event_offset = len(audit.events)
    call_offset = len(session.native_results)
    response = None
    error_type = None
    eligibility = {"eligible": False, "reason": "missing_current_card_or_run_key",
                   "valid_current_result": False, "evidence_mode": "none", "proof_refs": []}
    if isinstance(card.get("id"), str) and card["id"] and expected_key:
        try:
            response = await session.call("evaluate_insight_card", {
                "card_id": card["id"], "idempotency_key": expected_key,
            })
        except Exception as error:  # failure is evidence for the normal agent fallback
            error_type = type(error).__name__
            eligibility["reason"] = "native_call_failed"
        else:
            eligibility = _decision_first_quiet_eligibility(session, response, expected_key)

    status = "fallback"
    if eligibility["eligible"]:
        try:
            await session.call("finish_run", {
                "outcome": "ignore", "recipients": [], "summary": "",
                "evidence_refs": [f"receipt:{expected_key}"],
            })
        except Exception as error:  # do not suppress the agent's recovery path
            session.submission = None
            session.outbox.clear()
            error_type = type(error).__name__
            eligibility = {**eligibility, "eligible": False,
                           "reason": "quiet_handoff_failed"}
        else:
            if (session.submission is not None
                    and session.submission.get("outcome") == "ignore"
                    and not session.outbox):
                status = "quiet_shortcut"
            else:
                session.submission = None
                session.outbox.clear()
                eligibility = {**eligibility, "eligible": False,
                               "reason": "quiet_handoff_not_recorded"}

    events = audit.events[event_offset:]
    calls = session.native_results[call_offset:]
    result = response.get("result") if isinstance(response, dict) else None
    receipt = response.get("receipt") if isinstance(response, dict) else None
    record = {
        "attempted": bool(calls), "status": status,
        "fallback_reason": eligibility.get("reason"),
        "valid_current_result": eligibility.get("valid_current_result", False),
        "native_outcome": result.get("outcome") if isinstance(result, dict) else None,
        "receipt_id": receipt.get("receipt_id") if isinstance(receipt, dict) else None,
        "evidence_mode": eligibility.get("evidence_mode", "none"),
        "proof_refs": eligibility.get("proof_refs", []),
        "attempts": len(calls),
        "responses": sum(call.get("returned") is True for call in calls),
        "error_type": error_type,
        "seconds": time.perf_counter() - started,
        "usage": _usage(events),
        "overhead": _overhead(events),
        "_bundle": response,
    }
    audit.emit("decision_first.preflight", status=status,
               fallback_reason=record["fallback_reason"], attempts=record["attempts"],
               seconds=record["seconds"], evidence_mode=record["evidence_mode"])
    return record


def _native_judgment_score(native_results: list[dict], card: dict, label: dict,
                           destinations: list[dict], expected_key: str) -> dict:
    """Score the current typed judgment separately from API/tool transport success."""
    current = {}
    signatures = set()
    for call in native_results:
        if call.get("returned") is not True:
            continue
        valid = _valid_current_native_result(call.get("result", {}), card, expected_key)
        if valid is None:
            continue
        receipt, result = valid
        receipt_id = receipt.get("receipt_id") or expected_key
        current[receipt_id] = result
        delivery_methods = result.get("delivery_methods", [])
        signatures.add((result.get("outcome"), canonical(
            delivery_methods if isinstance(delivery_methods, list) else [])))
    if not current:
        return {"observed": False, "outcome_correct": None, "routing_correct": None}
    if len(signatures) != 1:
        return {"observed": False, "status": "conflicting_current_receipt_results",
                "receipt_count": len(current), "outcome_correct": None, "routing_correct": None}
    result = next(iter(current.values()))
    expected_outcome, expected_recipients, _category = expected_result(label)
    directory = {item["destination"]: item["key"] for item in destinations}
    delivery_methods = result.get("delivery_methods", [])
    actual_recipients = {
        directory.get(method.get("destination"), f"UNAUTHORIZED:{method.get('destination')}")
        for method in (delivery_methods if isinstance(delivery_methods, list) else [])
        if isinstance(method, dict)
    }
    actual_outcome = result.get("outcome")
    return {"observed": True, "receipt_count": len(current),
            "actual_outcome": actual_outcome, "expected_outcome": expected_outcome,
            "outcome_correct": actual_outcome == expected_outcome,
            "actual_recipients": sorted(actual_recipients),
            "expected_recipients": sorted(expected_recipients),
            "routing_correct": actual_recipients == set(expected_recipients)}


def _evidence_proof(session: CadenceSession, *, expected_key: str) -> tuple[str, list[str]]:
    primary_refs = _card_primary_refs(session.shared_card, session.adapter.catalog)
    if not primary_refs:
        return "none", []
    successful_reads = set(getattr(session.adapter, "successful_inspected_refs", set()))
    read_proof = set(primary_refs.values()) & successful_reads
    if read_proof == set(primary_refs.values()):
        return "primary_source_inspected_current_run", sorted(read_proof)
    native_proof = set()
    for call in session.native_results:
        if call.get("returned") is True:
            native_proof |= _native_primary_refs(call.get("result", {}), session.shared_card,
                                                 expected_key, primary_refs)
    if native_proof == set(primary_refs.values()):
        return "native_bundle_current_run", sorted(native_proof)
    return "none", sorted(read_proof | native_proof)


def product_use_status(arm: str, native_attempts: int, native_valid_results: int) -> str:
    if arm != "treatment":
        return "not_applicable"
    if native_valid_results:
        return "native_current_result_available"
    return "native_attempt_failed" if native_attempts else "product_not_used"


def _native_decision_tool_error_count(calls: list[dict]) -> int:
    return sum(call.get("returned") is False for call in calls)


def _native_tool_argument_validation_error_count(events: list[dict],
                                                dispatched_calls: list[dict]) -> int:
    """Count audited schema rejects that never reached CadenceSession.call."""
    dispatched = Counter(
        (call.get("name"), canonical(call.get("arguments", {})))
        for call in dispatched_calls
    )
    failures = 0
    for event in events:
        result = event.get("result")
        if (event.get("kind") != "tool.result"
                or event.get("name") not in NATIVE_DECISION_TOOLS
                or not isinstance(result, dict)
                or result.get("error") != "ValidationError"):
            continue
        signature = (event.get("name"), canonical(event.get("arguments", {})))
        if dispatched[signature]:
            dispatched[signature] -= 1
        else:
            failures += 1
    return failures


def _episode_prompt(session: CadenceSession, period: dict, *,
                    controller_preflight: dict | None = None) -> dict:
    prompt = {"phase": "monitoring", "business": session.public,
              "period": session.adapter.period_context,
              "saved_notes": session.notes,
              "evaluation_idempotency_key": session.current_idempotency_key
              or f"{session.tenant_id}/{period['period_id']}",
              "delivery": "local_mock_outbox_only"}
    if controller_preflight is not None:
        prompt["decision_first_preflight"] = {
            "status": controller_preflight["status"],
            "fallback_reason": controller_preflight["fallback_reason"],
            "valid_current_result": controller_preflight["valid_current_result"],
            "error_type": controller_preflight["error_type"],
            "native_bundle": controller_preflight["_bundle"],
        }
    return prompt


def _monitoring_instructions(session: CadenceSession, *, decision_first_fallback: bool = False) -> str:
    if session.guidance_mode == OPTIONAL_TOOL_MODE:
        instructions = COMMON_INSTRUCTIONS
    elif not session.treatment:
        instructions = PRODUCTION_COMMON_INSTRUCTIONS
    else:
        instructions = (PRODUCTION_COMMON_INSTRUCTIONS
                        + "\n\nInstalled default-agent MCP instructions (verbatim):\n"
                        + (session.server.instructions or ""))
    if decision_first_fallback:
        instructions += (
            "\n\nA controller preflight result is included as candidate evidence. Verify its "
            "card/version/run-key binding and explicit coverage before relying on it. If it is "
            "invalid, stale, partial, or non-quiet, recover with the available approved source "
            "and receipt tools as needed. Make your own caller-owned final submission; do not "
            "treat the controller result as an order."
        )
    return instructions


def _usage(events: list[dict]) -> dict:
    result = {"codex_cli": {"invocations": 0, "responses": 0, "successes": 0, "errors": 0,
                            "input_tokens": 0, "output_tokens": 0,
                            "unknown_usage": 0, "wall_seconds": 0.0},
              "jev": {"attempts": 0, "responses": 0, "successes": 0, "errors": 0,
                      "failed_attempts": 0, "input_tokens": 0, "output_tokens": 0,
                      "unknown_usage": 0, "wall_seconds": 0.0}}
    responded: set[tuple[str, int]] = set()
    for event in events:
        provider, kind = event.get("provider"), event.get("kind")
        if provider == "openai" and event.get("transport") == "codex_cli":
            row = result["codex_cli"]
            if kind == "api.request":
                row["invocations"] += 1
            elif kind == "api.response":
                row["responses"] += 1
                row["successes"] += 1
                usage = event.get("usage") or {}
                row["input_tokens"] += usage.get("input_tokens", 0) or 0
                row["output_tokens"] += usage.get("output_tokens", 0) or 0
                row["wall_seconds"] += event.get("seconds", 0) or 0
                responded.add(("codex_cli", event["request_id"]))
            elif kind == "api.error":
                row["errors"] += 1
                row["wall_seconds"] += event.get("seconds", 0) or 0
        elif provider == "jev":
            row = result["jev"]
            if kind == "api.request":
                row["attempts"] += 1
            elif kind == "api.error":
                row["errors"] += 1
                row["failed_attempts"] += 1
                row["wall_seconds"] += event.get("seconds", 0) or 0
            elif kind == "api.response":
                row["responses"] += 1
                row["successes"] += 1
                usage = event.get("usage") or {}
                row["input_tokens"] += usage.get("input_tokens", 0) or 0
                row["output_tokens"] += usage.get("output_tokens", 0) or 0
                row["wall_seconds"] += event.get("seconds", 0) or 0
                responded.add(("jev", event["request_id"]))
    result["codex_cli"]["unknown_usage"] = sum(
        event.get("kind") == "api.request" and event.get("provider") == "openai"
        and event.get("transport") == "codex_cli"
        and ("codex_cli", event["request_id"]) not in responded for event in events)
    result["jev"]["unknown_usage"] = sum(
        event.get("kind") == "api.request" and event.get("provider") == "jev"
        and ("jev", event["request_id"]) not in responded for event in events)
    return result


def _overhead(events: list[dict]) -> dict:
    native = [event for event in events if event.get("kind") == "native_product_tool_timing"]
    source = [event for event in events if event.get("kind") == "source.timing"]
    return {"native_product_calls": len(native),
            "native_product_tool_wall_seconds": sum(e.get("seconds", 0) for e in native),
            "source_reads": len(source),
            "source_read_wall_seconds": sum(e.get("seconds", 0) for e in source)}


def _completed_pair_count(results: list[dict]) -> int:
    completed = set()
    for row in results:
        if (not isinstance(row, dict) or row.get("treatment_assigned") is not True
                or not isinstance(row.get("period_id"), str)):
            continue
        if (isinstance(row.get("baseline"), dict)
                and row["baseline"].get("completed") is True
                and isinstance(row.get("treatment"), dict)
                and row["treatment"].get("completed") is True):
            completed.add(row["period_id"])
    return len(completed)


def _all_assigned_pairs_complete(results: list[dict], selected: list[dict]) -> bool:
    expected_ids = [case["period"]["period_id"] for case in selected]
    if len(results) != len(expected_ids) or len(set(expected_ids)) != len(expected_ids):
        return False
    rows = {row.get("period_id"): row for row in results if isinstance(row, dict)}
    if len(rows) != len(results) or set(rows) != set(expected_ids):
        return False
    return all(
        rows[period_id].get("treatment_assigned") is True
        and isinstance(rows[period_id].get("baseline"), dict)
        and rows[period_id]["baseline"].get("completed") is True
        and isinstance(rows[period_id].get("treatment"), dict)
        and rows[period_id]["treatment"].get("completed") is True
        for period_id in expected_ids
    )


def _narrative_reviews_complete(review: dict, outbox: list[dict]) -> bool:
    if not isinstance(review, dict):
        return False
    reviews = review.get("reviews")
    if not isinstance(reviews, list):
        return False
    if not outbox:
        return review.get("status") == "not_applicable_no_messages" and not reviews
    batches = review.get("batches")
    if (review.get("status") != "completed" or not isinstance(batches, list)
            or not batches or any(not isinstance(batch, dict)
                                  or batch.get("status") != "completed" for batch in batches)):
        return False
    expected_ids = {f"M{index:02d}" for index in range(1, len(outbox) + 1)}
    if len(reviews) != len(expected_ids):
        return False
    by_id = {item.get("message_id"): item for item in reviews if isinstance(item, dict)}
    return (set(by_id) == expected_ids and len(by_id) == len(reviews)
            and all(item.get("verdict") in {"supported", "needs_attention", "cannot_assess"}
                    and isinstance(item.get("rationale"), str) and item["rationale"].strip()
                    for item in by_id.values()))


def _trial_completion_status(*, setup_complete: bool, results: list[dict],
                             selected: list[dict], narrative_review: dict,
                             outbox: list[dict], postflight: Any) -> str:
    if not setup_complete:
        return "onboarding_incomplete"
    if (_all_assigned_pairs_complete(results, selected)
            and _narrative_reviews_complete(narrative_review, outbox)
            and bool(postflight)):
        return "completed"
    return "partial"


async def _review_messages(messages: list[dict], *, public: dict, card: dict, notes: str,
                           evidence_by_period: dict, audit: Audit, budget: RequestBudget) -> dict:
    if not messages:
        return {"status": "not_applicable_no_messages", "reviews": []}
    review_rows = []
    for index, message in enumerate(messages, start=1):
        period = evidence_by_period[message["period_id"]]
        review_rows.append({"message_id": message.get("message_id", f"M{index:02d}"),
                            "recipient_key": message["recipient_key"],
                            "summary": message["summary"],
                            "evidence_refs": message["evidence_refs"],
                            "period_id": message["period_id"],
                            "as_of": period["as_of"],
                            "supporting_sources": [period["sources"][ref]
                                                   for ref in message["evidence_refs"]
                                                   if ref in period["sources"]]})
    session = _MessageReviewSession([row["message_id"] for row in review_rows])
    payload = {"owner_brief": public["brief"], "glossary": public.get("glossary", {}),
               "reviewed_card": card, "saved_notes": notes, "messages": review_rows}
    audit.episode = "independent-narrative-review"
    episode = await codex_episode(
        session, key="", model=MODEL, effort=EFFORT, budget=budget, audit=audit,
        max_turns=2, max_tool_calls=2, max_output_tokens=3000, timeout_seconds=360,
        instructions_override=(
            "Independently review each proposed local-outbox message against only its cited same-period archived "
            "source evidence, the reviewed policy, and the owner's brief. Do not see or infer hidden expected "
            "labels. Assess factual support, period/scope clarity, unsupported causal claims, and whether the "
            "next step is clear. Do not judge whether the outcome or route matches a hidden label. This is a "
            "qualitative reviewer, not a keyword checklist; explain uncertainty and do not force a positive verdict. "
            "Submit exactly one structured row for every supplied message_id, choosing supported, needs_attention, "
            "or cannot_assess as warranted by the evidence; each row needs a verdict and rationale, while issues "
            "may be omitted when empty. If the tool rejects a submission for a schema or validation error, you may "
            "make at most one schema-correction retry: fix only the invalid field or shape and preserve the "
            "substantive verdict and rationale. Stop after an accepted structured submission. Do not substitute "
            "prose for the tool call, and do not force a positive verdict."),
        prompt_override=payload,
    )
    submitted = session.submission is not None
    status = ("completed" if episode.get("status") == "complete" and submitted
              else "no_structured_submission" if episode.get("status") == "complete"
              else "not_completed")
    return {"status": status, "episode": episode,
            "reviews": session.submission.get("reviews", []) if submitted else []}


async def run_trial(scenario: dict, registration: Any, *, binary: Path,
                    key_file: Path | None, output: Path, cases: int | str = 4,
                    jev_budget: int = 20, live: bool = False,
                    guidance_mode: str = PRODUCTION_GUIDED_MODE,
                    execution_mode: str = "agent-tool",
                    workflow_skill: str | None = None,
                    transport: str = "stdio", review_batch_size: int = 12) -> dict:
    if guidance_mode not in GUIDANCE_MODES:
        raise ValueError(f"guidance_mode must be one of {sorted(GUIDANCE_MODES)}")
    if execution_mode not in EXECUTION_MODES:
        raise ValueError(f"execution_mode must be one of {sorted(EXECUTION_MODES)}")
    selected = select_periods(scenario, registration, cases)
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError("invalid native transport")
    if type(review_batch_size) is not int or not 1 <= review_batch_size <= 20:
        raise ValueError("review_batch_size must be from 1 to 20")
    binary = Path(binary)
    build = verify_binary(binary)
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    public = public_scenario(scenario)
    study_scope = scenario.get("study_scope", RETROSPECTIVE_SCOPE)
    public["brief"] = f"{public['brief'].rstrip()}\n\nTrial scope: {study_scope}"
    public["require_agent_data_signoff"] = True
    pilot = _pilot_indices(registration)
    active_native_tools = (PRODUCTION_NATIVE_TOOLS if guidance_mode == PRODUCTION_GUIDED_MODE
                           else OPTIONAL_NATIVE_TOOLS)
    protocol = {
        "version": VERSION, "code": _git_sha(), "dataset_sha256": digest(scenario),
        "registration_pilot_indices": pilot,
        "selected_indices": [row["index"] for row in selected],
        "selected_period_ids": [row["period"]["period_id"] for row in selected],
        "company_count": 1, "fixture_period_count": len(public["periods"]),
        "cadence": scenario.get("cadence", "consecutive monthly closes"), "cold_onboarding": True,
        "execution_mode": execution_mode,
        "native_transport": transport,
        "workflow_skill_sha256": digest(workflow_skill) if workflow_skill else None,
        "workflow_skill_delivery": "explicit bundled skill text in the agent instructions; not automatic skill discovery" if workflow_skill else None,
        "review_batch_size": review_batch_size,
        "study_scope": study_scope,
        "scheduler_claim": "No real scheduler, cadence execution, or current warehouse freshness is tested.",
        "card_and_notes_frozen_after_onboarding": True,
        "models": {"onboarding": {"model": MODEL, "effort": EFFORT},
                   "recurring_baseline": {"model": MODEL, "effort": EFFORT},
                   "recurring_treatment": {"model": MODEL, "effort": EFFORT},
                   "independent_owner_and_narrative_review": {"model": MODEL, "effort": EFFORT}},
        "tool_limits_per_episode": {"max_tool_calls": 100, "timeout_seconds": RECURRING_TIMEOUT_SECONDS},
        "onboarding_episode_limits": {
            "max_tool_calls": 100, "timeout_seconds": ONBOARDING_TIMEOUT_SECONDS,
        },
        "jev_attempt_limit": jev_budget,
        "replay_clock": {
            "simulation_as_of": "Original historical monthly close; preserved verbatim.",
            "query_capture_at": "One real UTC timestamp shared by both arms per case.",
            "snapshot_mutation": "Only top-level captured_at/source_captured_at are stamped as a new synthetic gateway response; all measurement rows, business dates, cutoffs, and freshness annotations stay unchanged.",
            "freshness_claim": "Gateway replay receipt is not a warehouse freshness assertion.",
        },
        "comparison": "intention_to_treat_with_actual_native_use_reported_separately",
        "native_measurement_semantics": {
            "jev_successes": "Provider transport responses only; not policy correctness.",
            "native_valid_current_results": "Returned receipt/result matched the current idempotency key, frozen card ID/version, and shadow-delivery contract; not judgment correctness.",
            "native_judgment": "Post-run typed outcome and canonical routing scored against the private label; labels are not provided to either agent.",
            "frontier_submission": "Scored separately as the caller-owned final outcome and routing after any evidence-based recovery.",
            "decision_first_ignore_shortcut": "Only a current card/version/run-key-bound ignore with complete required-source evidence and receipt coverage may skip the treatment frontier; every other result falls back to the same frontier and source tools.",
        },
        "narrative_review_protocol": {
            "max_tool_calls": 2,
            "schema_correction_retries": 1,
            "required_fields": ["message_id", "verdict", "rationale"],
            "issues_optional_default": [],
            "missing_verdict_or_rationale_is_failure": True,
            "positive_verdict_forced": False,
        },
        "treatment_guidance": {
            "mode": guidance_mode,
            "baseline_instructions": ("production common goal" if guidance_mode == PRODUCTION_GUIDED_MODE
                                      else "COMMON_INSTRUCTIONS"),
            "treatment_instructions": (
                "production common goal + installed server.initialize.instructions verbatim"
                if guidance_mode == PRODUCTION_GUIDED_MODE else "COMMON_INSTRUCTIONS; server instructions omitted"
            ),
            "tool_definition_strategy": (
                "installed default-profile Tool.description and inputSchema passed unchanged"
                if guidance_mode == PRODUCTION_GUIDED_MODE
                else "installed inputSchema with legacy optional-tool study descriptions"
            ),
            "runtime_capture": "onboarding.json records exact installed server instructions and native tool definitions",
            "native_tools_available": sorted(active_native_tools),
            "profile_scope": "Restricted non-authoring default-profile monitoring subset: shared source tools plus guide, list/get card, evaluation, and receipt; card authoring/review/approval mutations are withheld.",
            "excluded_default_profile_tools": [
                "onboard_insight_card", "review_insight_card", "approve_insight_card"
            ],
            "mutation_tools_exposed": [],
            "harness_auto_evaluation": execution_mode == "decision-first",
            "native_tool_use_required_by_harness": execution_mode == "decision-first",
        },
        "treatment_native_tools": sorted(active_native_tools),
        "precomputed_bundle": False, "native_tool_use_required": execution_mode == "decision-first",
        "decision_first_controller": ("One current card evaluation precedes the treatment frontier; valid complete ignore may short-circuit, while failures, non-ignore, or incomplete coverage are handed to the same frontier as candidate evidence. No private labels participate." if execution_mode == "decision-first" else None),
        "delivery_enabled": False, "sink": "caller_owned_agent_local_mock_outbox",
        "source_data": "synthetic registered company MCP fixture; not customer or live BI data",
        "shared_source_transport": "Both arms use the same local typed SourceRegistry/PublicSourceAdapter for catalog search and inspection; this is not a real third-party connector. Treatment card evaluation still runs through the installed SignalWeave server over the same fixture.",
        "expansion": "No automatic expansion from the four-period stage gate.",
        "binary_preflight": build,
    }
    harness_paths = ("evaluations/native_cadence_trial.py", "evaluations/installed_workflow_trial.py",
                     "evaluations/installed_trial_transport.py", "evaluations/bootstrap_agent_trial.py",
                     "evaluations/codex_trial_transport.py", "scripts/binary_provenance.py")
    protocol["harness_sha256"] = {path: _file_hash(Path(__file__).resolve().parents[1] / path)
                                  for path in harness_paths}
    write_exclusive(output / "protocol.json", protocol)
    if not live:
        report = {"status": "dry_run", "protocol": protocol, "binary_verifications": [build]}
        write_exclusive(output / "report.json", report)
        return report
    if key_file is None or not 1 <= jev_budget <= 100:
        raise ValueError("live run requires --key-file and a Jev budget from 1 to 100")
    secret = Path(key_file).read_text(encoding="utf-8").strip()
    if not secret:
        raise ValueError("empty Jev key")
    audit = Audit(output / "trace.jsonl", (secret,))
    budget = RequestBudget(jev_budget)
    results: list[dict] = []
    outbox: list[dict] = []
    evidence_by_period: dict[str, dict] = {}
    card = None
    notes = ""
    setup_complete = False
    profile_tools: list[str] = []
    product_adapter = TimedSourceAdapter(public["catalog"], public["scenario_id"], audit)
    start_trial = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="native-cadence-trial-") as temporary:
            work = Path(temporary).resolve()
            onboarding_period = public["onboarding"]
            product_adapter.set_period(onboarding_period, datetime.now(timezone.utc))
            audit.episode = f"{public['scenario_id']}/onboarding"

            async def owner_reviewer(**kwargs):
                return await review_owner_artifact(**kwargs, audit=audit, budget=budget,
                                                   model=MODEL, effort=EFFORT)

            async with installed_server(binary=binary, key_file=Path(key_file), public=public,
                                        adapter=product_adapter, audit=audit, budget=budget,
                                        work=work, transport=transport) as server:
                profile_tools = await assert_default_agent_profile(server)
                installed_tools = await server.list_tools()
                installed_native_definitions = {
                    tool.name: {"description": tool.description, "inputSchema": tool.inputSchema}
                    for tool in installed_tools if tool.name in PRODUCTION_NATIVE_TOOLS
                }
                treatment = CadenceSession(public, product_adapter, server, True,
                                           owner_reviewer=owner_reviewer, arm="treatment",
                                           guidance_mode=guidance_mode)
                started = time.perf_counter()
                onboarding = await codex_episode(
                    treatment, key="", model=MODEL, effort=EFFORT, budget=budget, audit=audit,
                    max_turns=50, max_tool_calls=100, max_output_tokens=6000,
                    timeout_seconds=ONBOARDING_TIMEOUT_SECONDS,
                    instructions_override=((
                        "Use the installed SignalWeave default agent MCP and the shipped workflow skill below. "
                        "The owner is simulated via ask_owner. Save reusable notes, sign_off_data_foundation, "
                        "request_synthetic_owner_approval, then finish_setup with the approved card ID. "
                        "These trial support tools record simulated sign-off, not real human authorization. "
                        "\nInstalled MCP instructions:\n" + (server.instructions or "")
                        + "\nShipped SignalWeave skill:\n" + workflow_skill
                        if workflow_skill else onboarding_instructions(server))
                        + " For this simulation, the human owner is available through ask_owner; use it for missing business answers. An ordinary chat question receives no simulated reply. Do not infer policy from reviewer output."
                        + " Make the reviewed card and saved notes explicitly describe this as a retrospective review of archived reporting periods, not a current alert. "
                          "Preserve source measurement dates and cutoffs; do not claim warehouse freshness. "
                          "Use simulation_as_of for measurement dates; query_capture_at is only the replay gateway timestamp."),
                    prompt_override={"phase": "onboarding", "business": treatment.public,
                                     "period": product_adapter.period_context},
                )
                onboarding_seconds = time.perf_counter() - started
                setup_complete = treatment.setup_complete and onboarding.get("status") == "complete"
                notes = treatment.notes
                onboarding_record = {"episode": onboarding, "seconds": onboarding_seconds,
                                     "completed": setup_complete,
                                     "owner_reviews": treatment.owner_review_records,
                                     "data_signoff": treatment.data_signoff,
                                     "mcp_profile_tools": profile_tools,
                                     "installed_server_instructions": server.instructions,
                                     "installed_native_tool_definitions": installed_native_definitions}
                if setup_complete:
                    card = await treatment.product("get_insight_card", {"card_id": treatment.card_id})
                    card_digest = digest(card)
                    notes_digest = digest(notes)
                    onboarding_record.update(card=card, card_digest=card_digest,
                                             notes_digest=notes_digest)
                    baseline_adapter = TimedSourceAdapter(public["catalog"], public["scenario_id"], audit)
                    baseline = CadenceSession(public, baseline_adapter, server, False,
                                              owner_reviewer=owner_reviewer, arm="baseline",
                                              guidance_mode=guidance_mode)
                    baseline.phase = "monitoring"
                    baseline.setup_complete = True
                    baseline.notes = notes
                    baseline.shared_card = copy.deepcopy(card)
                    baseline.owner_topics = set(treatment.owner_topics)
                    baseline.data_signoff = copy.deepcopy(treatment.data_signoff)
                    treatment.phase = "monitoring"
                    treatment.shared_card = copy.deepcopy(card)
                    frozen_card, frozen_notes = card_digest, notes_digest
                    for selected_case in selected:
                        period, label = selected_case["period"], selected_case["label"]
                        period_id = period["period_id"]
                        row = {"index": selected_case["index"], "period_id": period_id,
                               "as_of": period["as_of"], "treatment_assigned": True,
                               "baseline": None, "treatment": None}
                        # One capture clock and identical historical source rows are shared by
                        # both arms; this never converts the monthly close into a current alert.
                        replay_capture_at = datetime.now(timezone.utc)
                        product_adapter.set_period(period, replay_capture_at)
                        baseline_adapter.set_period(period, replay_capture_at)
                        row["query_capture_at"] = replay_capture_at.isoformat()
                        row["time_basis"] = "historical_fixture_replay"
                        order = ("baseline", "treatment") if len(results) % 2 == 0 else ("treatment", "baseline")
                        native_review_sources = {}
                        for arm in order:
                            session = baseline if arm == "baseline" else treatment
                            session.adapter = baseline_adapter if arm == "baseline" else product_adapter
                            session.phase = "monitoring"
                            session.submission = None
                            session.outbox = []
                            session.agent_inspected.clear()
                            session.evidence_aliases.clear()
                            session.source_url_refs.clear()
                            session.phase_owner_topics.clear()
                            session.shared_card = copy.deepcopy(card)
                            session.native_results = []
                            session.current_idempotency_key = f"{session.tenant_id}/{period_id}"
                            audit.episode = f"{public['scenario_id']}/{period_id}/{arm}"
                            arm_offset = len(audit.events)
                            arm_started = time.perf_counter()
                            controller_preflight = None
                            if arm == "treatment" and execution_mode == "decision-first":
                                controller_preflight = await _decision_first_preflight(session, audit)
                            frontier_offset = len(audit.events)
                            episode = None
                            episode_seconds = None
                            if (controller_preflight is not None
                                    and controller_preflight["status"] == "quiet_shortcut"):
                                complete = (session.submission is not None
                                            and session.submission.get("outcome") == "ignore"
                                            and not session.outbox)
                            else:
                                started = time.perf_counter()
                                episode = await codex_episode(
                                    session, key="", model=MODEL, effort=EFFORT,
                                    budget=budget, audit=audit, max_turns=40,
                                    max_tool_calls=100, max_output_tokens=4500,
                                    timeout_seconds=RECURRING_TIMEOUT_SECONDS, bundle=None,
                                    instructions_override=(_monitoring_instructions(
                                        session, decision_first_fallback=controller_preflight is not None)
                                        + ("\nShipped SignalWeave skill:\n" + workflow_skill
                                           if workflow_skill and session.treatment else "")),
                                    prompt_override=_episode_prompt(
                                        session, period, controller_preflight=controller_preflight),
                                )
                                episode_seconds = time.perf_counter() - started
                                complete = (episode.get("status") == "complete"
                                            and not episode.get("error")
                                            and episode.get("exit_code") == 0
                                            and not episode.get("foreign_tools")
                                            and session.submission is not None)
                            events = audit.events[arm_offset:]
                            episode_events = audit.events[frontier_offset:]
                            arm_usage = _usage(events)
                            usage = _usage(episode_events) if episode is not None else None
                            jev_attempts = arm_usage["jev"]["attempts"]
                            native_calls = [e for e in events if e.get("kind") == "tool.result"
                                            and e.get("name") in NATIVE_TOOLS]
                            decision_calls = [call for call in session.native_results
                                              if call.get("name") in NATIVE_DECISION_TOOLS]
                            decision_tool_events = [event for event in events
                                                    if event.get("kind") == "tool.result"
                                                    and event.get("name") in NATIVE_DECISION_TOOLS]
                            argument_validation_errors = _native_tool_argument_validation_error_count(
                                decision_tool_events, decision_calls)
                            native_valid_results = _native_success_count(
                                session, card, session.current_idempotency_key)
                            native_tool_errors = _native_decision_tool_error_count(decision_calls)
                            api_status = product_use_status(arm, len(decision_calls), native_valid_results)
                            native_judgment = _native_judgment_score(
                                session.native_results, card, label, public["destinations"],
                                session.current_idempotency_key)
                            evidence_mode, proof_refs = _evidence_proof(
                                session, expected_key=session.current_idempotency_key)
                            audit.emit("evidence.proof", period_id=period_id, arm=arm,
                                       evidence_mode=evidence_mode,
                                       primary_current_proof=(evidence_mode != "none"), refs=proof_refs)
                            score = _expected_score(session.submission, label, session.outbox,
                                                    evidence_mode=evidence_mode, proof_refs=proof_refs)
                            for call in session.native_results:
                                review_evidence = _native_review_evidence(
                                    call.get("result", {}), card, session.current_idempotency_key)
                                if review_evidence is not None:
                                    ref = f"receipt:{session.current_idempotency_key}"
                                    native_review_sources[ref] = review_evidence
                            score["observed"] = bool(complete and session.submission is not None)
                            if not complete:
                                score["outcome_correct"] = score["routing_correct"] = score["outbox_count_correct"] = None
                            entry = {"completed": complete, "episode": episode,
                                     "frontier_invoked": episode is not None,
                                     "submission": copy.deepcopy(session.submission),
                                     "outbox": copy.deepcopy(session.outbox), "score": score,
                                     "source_reads": sorted(session.agent_inspected | session.adapter.inspected),
                                     "evidence_mode": evidence_mode,
                                     "primary_current_proof": evidence_mode != "none",
                                     "primary_current_proof_refs": proof_refs,
                                     "native_api_tool_calls": (
                                         len(native_calls)
                                         + (controller_preflight["attempts"]
                                            if controller_preflight else 0)),
                                     "native_decision_usage": {
                                         "tool_attempts": (len(decision_tool_events)
                                                            + (controller_preflight["attempts"]
                                                               if controller_preflight else 0)),
                                         "tool_argument_validation_errors": argument_validation_errors,
                                         "attempts": len(decision_calls),
                                         "responses": sum(call.get("returned") is True for call in decision_calls),
                                         "valid_current_results": native_valid_results,
                                         "errors": native_tool_errors,
                                         "invalid_responses": sum(call.get("returned") is True
                                                                  for call in decision_calls)
                                         - native_valid_results,
                                     },
                                     "native_judgment": native_judgment,
                                     "evaluate_tool_calls": (
                                         sum(e.get("name") == "evaluate_insight_card"
                                             for e in native_calls)
                                         + (controller_preflight["attempts"]
                                            if controller_preflight else 0)),
                                     "native_valid_current_results": native_valid_results,
                                     "jev_attempts": jev_attempts,
                                     "product_use_status": api_status,
                                     "episode_seconds": episode_seconds,
                                     "arm_seconds": time.perf_counter() - arm_started,
                                     "usage": usage,
                                     "overhead": _overhead(episode_events) if episode is not None else None}
                            if controller_preflight is not None:
                                entry["decision_first_preflight"] = {
                                    key: value for key, value in controller_preflight.items()
                                    if key != "_bundle"
                                }
                            row[arm] = entry
                            outbox.extend(copy.deepcopy(session.outbox))
                        sources = dict(native_review_sources)
                        for source_adapter in (product_adapter, baseline_adapter):
                            for ref in set(row["baseline"]["source_reads"] + row["treatment"]["source_reads"]):
                                if ref in source_adapter.snapshots:
                                    sources[ref] = copy.deepcopy(source_adapter.snapshots[ref])
                        evidence_by_period[period_id] = {"as_of": period["as_of"], "sources": sources}
                        treatment_card = await treatment.product("get_insight_card", {"card_id": treatment.card_id})
                        row["frozen_card_unchanged"] = digest(treatment_card) == frozen_card
                        row["frozen_notes_unchanged"] = digest(treatment.notes) == frozen_notes
                        row["arm_order"] = list(order)
                        row["paired"] = {"same_model_effort": True,
                                          "same_card_digest": digest(treatment.shared_card) == digest(baseline.shared_card),
                                          "same_notes_digest": digest(treatment.notes) == digest(baseline.notes)}
                        results.append(row)
                write_exclusive(output / "onboarding.json", audit.redact(onboarding_record))
                if setup_complete:
                    flat_outbox = [{**message, "message_id": f"M{index:02d}"}
                                   for index, message in enumerate(outbox, start=1)]
                    reviews = []
                    review_batches = []
                    for offset in range(0, len(flat_outbox), review_batch_size):
                        messages = flat_outbox[offset:offset + review_batch_size]
                        batch = await _review_messages(
                            messages, public=treatment.public, card=card, notes=notes,
                            evidence_by_period={message["period_id"]: evidence_by_period[message["period_id"]]
                                                for message in messages}, audit=audit, budget=budget)
                        reviews.extend(batch.get("reviews", []))
                        review_batches.append(batch)
                    narrative_review = {"status": ("not_applicable_no_messages" if not review_batches else
                        "completed" if all(batch.get("status") == "completed" for batch in review_batches)
                        else "incomplete"),
                        "reviews": reviews, "batches": review_batches}
                else:
                    narrative_review = {"status": "not_run_onboarding_incomplete", "reviews": []}
        audit.episode = "trial-complete"
    except Exception as error:
        audit.episode = "trial-error"
        audit.emit("trial.error", error_type=type(error).__name__, message=str(error)[:1200])
        narrative_review = {"status": "not_run", "reviews": []}
    postflight = None
    try:
        postflight = verify_binary(binary)
    except Exception as error:
        audit.emit("binary.postflight.error", error_type=type(error).__name__, message=str(error)[:1200])
    review_by_id = {item["message_id"]: item for item in narrative_review.get("reviews", [])}
    for index, message in enumerate(outbox, start=1):
        review = review_by_id.get(f"M{index:02d}")
        if review is None:
            continue
        matched = next((row for row in results if row["period_id"] == message["period_id"]), None)
        if matched and isinstance(matched.get(message["arm"]), dict):
            matched[message["arm"]].setdefault("narrative_reviews", []).append(review)
    treatment_observed = [row for row in results if row.get("treatment", {}).get("score", {}).get("observed")]
    baseline_observed = [row for row in results if row.get("baseline", {}).get("score", {}).get("observed")]
    treatment_native_available = [row for row in results if row.get("treatment", {}).get(
        "product_use_status") == "native_current_result_available"]
    report = {
        "status": _trial_completion_status(
            setup_complete=setup_complete, results=results, selected=selected,
            narrative_review=narrative_review, outbox=outbox, postflight=postflight,
        ),
        "protocol": protocol, "onboarding_complete": setup_complete,
        "card_digest": digest(card) if card else None, "notes_digest": digest(notes) if setup_complete else None,
        "periods": results, "local_mock_outbox": outbox,
        "narrative_review": narrative_review,
        "summary": {
            "intended_cases": len(selected), "paired_cases": _completed_pair_count(results),
            "treatment_assigned": sum(
                row.get("treatment_assigned") is True for row in results),
            "treatment_observed": len(treatment_observed),
            "baseline_observed": len(baseline_observed),
            "decision_first_preflight_attempts": sum(
                row.get("treatment", {}).get("decision_first_preflight", {}).get("attempts", 0)
                for row in results),
            "decision_first_quiet_shortcuts": sum(
                row.get("treatment", {}).get("decision_first_preflight", {}).get("status")
                == "quiet_shortcut" for row in results),
            "decision_first_preflight_seconds": sum(
                row.get("treatment", {}).get("decision_first_preflight", {}).get("seconds", 0.0)
                for row in results),
            "treatment_frontier_invoked": sum(
                row.get("treatment", {}).get("frontier_invoked") is True for row in results),
            "treatment_outcome_correct": sum(r["treatment"]["score"].get("outcome_correct") is True for r in results if r.get("treatment")),
            "treatment_routing_correct": sum(r["treatment"]["score"].get("routing_correct") is True for r in results if r.get("treatment")),
            "baseline_outcome_correct": sum(r["baseline"]["score"].get("outcome_correct") is True for r in results if r.get("baseline")),
            "baseline_routing_correct": sum(r["baseline"]["score"].get("routing_correct") is True for r in results if r.get("baseline")),
            "treatment_native_current_result_available": len(treatment_native_available),
            "treatment_native_judgments_observed": sum(
                r.get("treatment", {}).get("native_judgment", {}).get("observed") is True for r in results),
            "treatment_native_judgment_outcome_correct": sum(
                r.get("treatment", {}).get("native_judgment", {}).get("outcome_correct") is True for r in results),
            "treatment_native_judgment_outcome_incorrect": sum(
                r.get("treatment", {}).get("native_judgment", {}).get("outcome_correct") is False for r in results),
            "treatment_native_judgment_routing_correct": sum(
                r.get("treatment", {}).get("native_judgment", {}).get("routing_correct") is True for r in results),
            "treatment_native_attempt_failed": sum(
                r.get("treatment", {}).get("product_use_status") == "native_attempt_failed" for r in results),
            "treatment_product_not_used": sum(r.get("treatment", {}).get("product_use_status") == "product_not_used" for r in results),
            "treatment_native_attempts": sum(
                r.get("treatment", {}).get("native_decision_usage", {}).get("attempts", 0) for r in results),
            "treatment_native_tool_attempts": sum(
                r.get("treatment", {}).get("native_decision_usage", {}).get("tool_attempts", 0)
                for r in results),
            "treatment_native_tool_argument_validation_errors": sum(
                r.get("treatment", {}).get("native_decision_usage", {}).get(
                    "tool_argument_validation_errors", 0) for r in results),
            "treatment_native_decision_tool_errors": sum(
                r.get("treatment", {}).get("native_decision_usage", {}).get("errors", 0)
                for r in results),
            "treatment_native_valid_current_results": sum(
                r.get("treatment", {}).get("native_decision_usage", {}).get("valid_current_results", 0)
                for r in results),
            "quiet_grade_ineligible": sum(
                r.get(arm, {}).get("score", {}).get("quiet_grade_eligible") is False
                for r in results for arm in ("baseline", "treatment") if r.get(arm)),
            "outbox_message_count": len(outbox), "quiet_zero_message_workflows": sum(
                entry.get("submission", {}).get("outcome") in QUIET_OUTCOMES
                and not entry.get("outbox")
                for row in results for entry in (row.get("baseline") or {}, row.get("treatment") or {})),
        },
        "jev_attempts": budget.used, "jev_budget_censored": budget.exhausted,
        "usage": _usage(audit.events), "overhead": _overhead(audit.events),
        "binary_verifications": {"preflight": build, "postflight": postflight},
        "elapsed_seconds": time.perf_counter() - start_trial,
        "limitations": ["Synthetic source fixture and simulated owner/reviewers; not customer evidence or real human approval.",
                        "Retrospective monthly-close replay does not demonstrate a real 12-month scheduler or current warehouse freshness.",
                        "Shared catalog search and source inspection are a local typed fixture adapter, not a live third-party MCP connector.",
                        "Local mock outbox only; no Slack or other external delivery was attempted.",
                        "Narrative quality is an independent qualitative model review, not a keyword score."],
    }
    write_exclusive(output / "report.json", audit.redact(report))
    write_exclusive(output / "binary-verifications.json", {"preflight": build, "postflight": postflight})
    return report


def load_cadence_fixture() -> tuple[dict, Any]:
    try:
        from evaluations.native_cadence_cases import build_cadence_scenario
    except ImportError as error:
        raise RuntimeError("native_cadence_cases.build_cadence_scenario is unavailable") from error
    scenario, registration = build_cadence_scenario()
    return scenario, registration


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("dist/signalweave"))
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, choices=[4, 12], default=4)
    parser.add_argument("--jev-budget", type=int, default=20)
    parser.add_argument("--guidance-mode", choices=sorted(GUIDANCE_MODES),
                         default=PRODUCTION_GUIDED_MODE,
                         help="Production server guidance by default; optional-tools preserves the earlier study guidance")
    parser.add_argument("--execution-mode", choices=sorted(EXECUTION_MODES),
                        default="agent-tool",
                        help="Use the natural agent-tool caller, or experimentally preflight native decisions before the treatment frontier")
    parser.add_argument("--live", action="store_true", help="Run isolated native onboarding and recurring MCP episodes")
    args = parser.parse_args()
    if args.live and args.key_file is None:
        parser.error("--live requires --key-file")
    if not 1 <= args.jev_budget <= 20:
        parser.error("--jev-budget must be between 1 and 20")
    scenario, registration = load_cadence_fixture()
    report = asyncio.run(run_trial(scenario, registration, binary=args.binary.resolve(),
                                   key_file=args.key_file, output=args.output,
                                   cases=args.cases, jev_budget=args.jev_budget, live=args.live,
                                   guidance_mode=args.guidance_mode,
                                   execution_mode=args.execution_mode))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

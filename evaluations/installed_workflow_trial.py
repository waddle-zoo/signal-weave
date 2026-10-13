"""Default-agent onboarding and paired final-report comparison over shadow evidence.

Research only. No reference card is installed and no private future label is
available to the author, the binary, or the source server.
"""
from __future__ import annotations

import argparse
import asyncio
import builtins
import copy
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from exceptiongroup import BaseExceptionGroup
except ImportError:  # Python 3.11+ provides the same type in builtins.
    BaseExceptionGroup = getattr(builtins, "BaseExceptionGroup", ())

from evaluations.bootstrap_agent_trial import (
    COMMON_SYSTEM,
    MODEL,
    PRODUCT_TOOLS,
    Audit,
    PublicSourceAdapter,
    RequestBudget,
    ToolSession,
    card_fingerprint,
    digest,
    usage_summary,
    write_exclusive,
)
from evaluations.bootstrap_owner_review import review_owner_artifact
from evaluations.bootstrap_scenarios import public_scenario, score_submission
from evaluations.codex_trial_transport import codex_episode
from evaluations.installed_first_report_trial import _file_hash, _git_sha
from scripts.binary_provenance import verify_binary
from signalweave.mcp_server import AGENT_PROFILE_TOOLS

VERSION = "installed-workflow-v20"
SHARED_SOURCE_PRODUCT_TOOLS = frozenset({"search_catalog", "inspect_resource"})


def expected_human_clarification(expected: dict, unknown_topics: set[str], episode: dict) -> bool:
    """Recognize a deliberate onboarding pause without counting it as setup success."""

    topics = set(expected.get("unknown_owner_topics", []))
    return bool(
        expected.get("state") == "needs_human_clarification"
        and topics
        and topics <= unknown_topics
        and episode.get("status") == "failed"
        and episode.get("error") == "no_structured_submission"
        and bool(episode.get("final_message", "").strip())
        and not episode.get("foreign_tools")
    )


def expected_human_clarification_record(
    expected: dict, unknown_topics: set[str], episode: dict, *,
    inspected_refs: set[str], future_period_count: int,
) -> dict | None:
    """Capture an expected HIL pause without scoring unapproved future periods."""
    if not expected_human_clarification(expected, unknown_topics, episode):
        return None
    return {
        "onboarding_state": "needs_human_clarification",
        "onboarding_expected_pause": True,
        "unresolved_owner_topics": sorted(expected["unknown_owner_topics"]),
        "preapproval_current_report": {
            "final_message": episode.get("final_message", ""),
            "inspected_source_refs": sorted(inspected_refs),
            "scoring": "not_independently_scored",
        },
        "future_monitoring": {
            "state": "not_run_pending_owner_answer",
            "periods_not_scored": future_period_count,
        },
    }


def _verify_binary_stage(binary: Path, expected: dict, checks: list[dict], stage: str) -> dict:
    current = verify_binary(Path(binary))
    if current != expected:
        raise RuntimeError(f"installed trial binary changed after preflight ({stage})")
    checks.append({"stage": stage, "metadata": current})
    return current


def _root_cause_summary(error: BaseException, audit: Audit, *, max_causes: int = 5,
                        max_message_chars: int = 320, max_nodes: int = 32) -> list[dict[str, str]]:
    """Flatten nested exception groups into bounded, redacted leaf diagnostics."""
    pending: list[BaseException] = [error]
    causes: list[dict[str, str]] = []
    truncated = False
    visited = 0
    while pending and len(causes) < max_causes and visited < max_nodes:
        current = pending.pop(0)
        visited += 1
        if isinstance(current, BaseExceptionGroup):
            children = current.exceptions
            allowed = min(max_causes + 1, max(0, max_nodes - visited - len(pending)))
            if len(children) > allowed:
                truncated = True
            pending[0:0] = children[:allowed]
            continue
        message = audit.redact(str(current))
        safe_message = " ".join(message.split())[:max_message_chars]
        causes.append({
            "type": type(current).__name__[:80],
            "message": safe_message or "No exception message.",
        })
    if pending or truncated or visited >= max_nodes:
        causes.append({"type": "truncated", "message": "Additional exception causes omitted."})
    return causes


def _agent_call_count(events: list[dict]) -> int:
    return sum(
        event.get("kind") == "api.request"
        and event.get("provider") == "openai"
        and event.get("transport") == "codex_cli"
        for event in events
    )


def _is_binary_identity_failure(root_causes: list[dict[str, str]]) -> bool:
    text = " ".join(cause.get("message", "") for cause in root_causes).lower()
    return (
        "binary" in text
        and any(marker in text for marker in ("stale", "fingerprint", "changed", "build-info", "metadata"))
    ) or (
        "source" in text
        and any(marker in text for marker in ("fingerprint", "sha256"))
        and any(marker in text for marker in ("mismatch", "changed", "differs", "stale"))
    )


def _company_failure_status(root_causes: list[dict[str, str]], agent_calls: int) -> str:
    if _is_binary_identity_failure(root_causes):
        return "invalid_preflight"
    if agent_calls == 0:
        return "not_run"
    return "onboarding_or_runtime_incomplete"


def _invalid_preflight_report(*, scenarios, binary, output, model_settings, fixture_seed,
                              error: Exception) -> dict:
    """Write a no-agent preflight record without assigning business accuracy."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    audit = Audit()
    root_causes = _root_cause_summary(error, audit)
    intended = sum(len(scenario["public"]["periods"]) for scenario in scenarios)
    protocol = {
        "version": VERSION, "code": _git_sha(),
        "dataset_sha256": digest(scenarios), "fixture_seed": fixture_seed,
        "companies": len(scenarios), "monitoring_cases": intended,
        "models": model_settings, "comparison": "paired_final_business_outcome_runtime",
        "mcp_profile": "agent", "live": True, "delivery_enabled": False,
        "binary_identity_status": "invalid_preflight",
    }
    preflight = {
        "status": "invalid_preflight", "source_match": False,
        "binary_path": str(Path(binary)), "agent_calls": 0,
        "error_type": type(error).__name__, "root_causes": root_causes,
        "not_run_reason": "Binary identity could not be verified before any agent call.",
    }
    report = {
        "status": "invalid_preflight", "protocol": protocol, "preflight": preflight,
        "companies": [], "binary_verifications": [], "passed": False,
        "business_accuracy_status": "not_observed",
        "summary": {
            "onboarding_total": len(scenarios), "intended": intended,
            "agent_calls": 0, "observed_business_cases": 0,
            "not_run_business_cases": intended, "agent_correct": 0,
            "agent_accuracy": None, "baseline_accuracy": None,
            "observed_baseline_business_cases": 0,
            "paired_observed_business_cases": 0,
            "final_outcome_comparisons": 0,
        },
    }
    write_exclusive(output / "protocol.json", protocol)
    write_exclusive(output / "frozen-scenarios.json", scenarios)
    write_exclusive(output / "preflight.json", preflight)
    write_exclusive(output / "report.json", report)
    return report


def bind_examples(examples: list[dict], card: dict) -> list[dict]:
    """Identity projection only: never create measurements, policy or labels."""
    sources = {f"{s['adapter']}|{s['resource']}": s for s in card["sources"]}
    methods = {d["destination"]: d["key"] for d in card["delivery_methods"]}
    result = copy.deepcopy(examples)
    for case in result:
        resources = []
        for snapshot in case["resources"]:
            ref = f"{snapshot['adapter']}|{snapshot['resource']}"
            if ref not in sources:
                continue
            key = sources[ref]["key"]
            snapshot["source_key"] = key
            for collection in ("observations", "evidence"):
                for item in snapshot.get(collection, []):
                    item["source_key"] = key
            resources.append(snapshot)
        case["resources"] = resources
        expected = case["expected_delivery_destinations"]
        endpoints = list(expected.values()) if isinstance(expected, dict) else list(expected)
        if any(endpoint not in methods for endpoint in endpoints):
            raise ValueError("Card lacks an owner-required delivery destination; preserve all owner routes.")
        case["expected_delivery_destinations"] = {methods[endpoint]: endpoint for endpoint in endpoints}
        case["expected_delivery_method_keys"] = sorted(case["expected_delivery_destinations"])
        # Labels use canonical refs; the chosen card owns aliases.
        required = case.pop("required_evidence_refs", [])
        if any(ref not in sources for ref in required):
            raise ValueError("Card omits an owner-required evidence source; preserve recurring context.")
        case["required_evidence_source_keys"] = [sources[ref]["key"] for ref in required]
        if "expected_retrieval_refs" not in case:
            raise ValueError("Owner examples need explicit retrieval labels; never derive them from model selection.")
    return result


def bundle_visible_refs(evaluation: dict, card: dict) -> set[str]:
    """Return source refs actually present in the agent-visible SignalWeave bundle."""
    aliases = {
        source["key"]: f"{source['adapter']}|{source['resource']}"
        for source in card.get("sources", [])
    }
    visible: set[str] = set()

    def add_record(record: object) -> None:
        if not isinstance(record, dict):
            return
        source_key = record.get("source_key")
        if isinstance(source_key, str) and source_key in aliases:
            visible.add(aliases[source_key])
        for field in ("provenance", "query_refs"):
            refs = record.get(field, [])
            if isinstance(refs, list):
                visible.update(ref for ref in refs if isinstance(ref, str) and "|" in ref)

    for section in (evaluation.get("result") or {}, evaluation.get("report") or {}):
        if not isinstance(section, dict):
            continue
        for field in ("evidence", "observations", "numeric_claims", "provenance"):
            records = section.get(field, [])
            if isinstance(records, list):
                for record in records:
                    add_record(record)
    return visible & set(aliases.values())


class InstalledSession(ToolSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_inspected: set[str] = set()
        self.unknown_owner_topics: set[str] = set()

    async def specs(self):
        specs = await super().specs()
        if self.treatment and self.phase == "monitoring":
            specs = [spec for spec in specs if spec["name"] not in PRODUCT_TOOLS]
        allowed = set(SHARED_SOURCE_PRODUCT_TOOLS)
        if self.treatment and self.phase == "onboarding":
            allowed |= set(PRODUCT_TOOLS)
        tools = await self.server.list_tools()
        available = {tool.name for tool in tools}
        self.allowed_product = allowed & available if self.treatment else set()
        for tool in tools:
            if tool.name in allowed:
                specs.append({"type": "function", "name": tool.name,
                              "description": tool.description, "parameters": tool.inputSchema,
                              "strict": False})
        # The same default-profile source MCP schemas are offered to both arms.
        # Prefer them over the harness's generic search schema when names overlap.
        unique = {}
        for spec in specs:
            unique[spec["name"]] = spec
        if self.treatment and self.phase == "onboarding":
            review_tool = unique.get("request_synthetic_owner_approval")
            if review_tool:
                review_tool["description"] = (
                    "After inspecting the current card and saving policy notes, request an "
                    "independent synthetic owner-policy review. This default-agent trial has "
                    "no simulate or preview tool; the runner performs one delivery-disabled "
                    "native evaluation after approval. This is not human approval or certification."
                )
        return list(unique.values())

    async def call(self, name, arguments):
        if name == "ask_owner" and self.phase == "onboarding":
            result = await super().call(name, arguments)
            if result.get("known") is False:
                self.unknown_owner_topics.add(str(arguments.get("topic", "")))
            return result
        if (name == "request_synthetic_owner_approval" and self.treatment
                and self.phase == "onboarding"):
            card_id = arguments["card_id"]
            card = await self.product("get_insight_card", {"card_id": card_id})
            fingerprint = card_fingerprint(card)
            if self.reviewed.get(card_id) != fingerprint:
                return {"approved": False, "card_id": card_id,
                        "missing_prerequisites": ["get_insight_card"],
                        "next_actions": [{"tool": "get_insight_card", "arguments": {"card_id": card_id}}],
                        "synthetic": True, "human_approval": False}
            if self.owner_reviewer is None:
                raise ValueError("Default-agent trial requires independent synthetic owner review")
            review = await self.semantic_owner_review(card)
            accepted = review.get("approved") is True
            if accepted:
                self.owner_approvals[card_id] = self.approval_fingerprint(card)
            return {"card_id": card_id, "approved": accepted,
                    "synthetic": True, "policy_correctness_validated": False,
                    "human_approval": False, "owner_review": review,
                    "reason": "Independent synthetic review of current owner policy, card, and notes; "
                              "not actual human approval or certification."}
        if (name == "finish_setup" and self.treatment and self.phase == "onboarding"):
            if not self.notes or not self.adapter.inspected or not self.owner_topics:
                raise ValueError("Inspect sources, consult owner and save reusable notes first")
            if (self.require_agent_data_signoff
                    and (not self.data_signoff or self.data_signoff.get("status") != "ready")):
                raise ValueError("The agent data expert must sign off from inspected sources before setup can finish")
            card_id = arguments.get("card_id")
            if not card_id:
                raise ValueError("Treatment requires a saved approved card")
            card = await self.product("get_insight_card", {"card_id": card_id})
            if card.get("status") != "approved":
                raise ValueError("Card must be explicitly approved before shadow evaluation")
            if (self.owner_reviewer is not None
                    and self.semantic_approval != self.approval_fingerprint(card)):
                return {"setup_complete": False,
                        "reason": "Current card/notes need independent owner review.",
                        "next_tools": ["request_synthetic_owner_approval", "finish_setup"]}
            self.card_id = card_id
            self.setup_source_context = self.owner_source_context()
            self.setup_complete = True
            return {"setup_complete": True, "card_id": card_id,
                    "data_expert_signoff": copy.deepcopy(self.data_signoff),
                    "shadow_evaluation": "one delivery-disabled native evaluation per period",
                    "human_approval": "independent synthetic owner review; not actual human authorization"}
        if name in SHARED_SOURCE_PRODUCT_TOOLS:
            result = await self.product(name, arguments)
            if name == "inspect_resource":
                self.agent_inspected.add(f"{arguments['adapter']}|{arguments['resource']}")
            return result
        if self.phase == "monitoring" and name in {"inspect_source", "analyze_source"}:
            result = await super().call(name, arguments)
            self.agent_inspected.add(arguments["ref"])
            return result
        return await super().call(name, arguments)


def score_native(output: dict, card: dict, label: dict, destinations: list[dict]) -> dict:
    """Recompute from native result, not saved pass flags or the final LLM prose."""
    result = output.get("result") or {}
    methods = result.get("delivery_methods", [])
    directory = {d["destination"]: d["key"] for d in destinations}
    actual_destinations = [d.get("destination") for d in methods]
    actual = {directory.get(endpoint, f"UNAUTHORIZED:{endpoint}") for endpoint in actual_destinations}
    refs = {s["key"]: f"{s['adapter']}|{s['resource']}" for s in card["sources"]}
    present = {refs.get(item.get("source_key")) for item in
               [*result.get("evidence", []), *result.get("observations", [])]}
    required = set(label["required_evidence_refs"])
    outcome_correct = result.get("outcome") == label["outcome"]
    routes_correct = actual == set(label["recipients"])
    evidence_complete = required <= present and bool(result.get("evidence"))
    receipt, report, returned_card = (output.get(name) or {} for name in ("receipt", "report", "card"))
    identity_valid = bool(card.get("id")) and all(
        value == card["id"] for value in
        (result.get("card_id"), report.get("card_id"), receipt.get("card_id"), returned_card.get("id"))
    ) and receipt.get("card_version") == card.get("version")
    delivery_disabled = (receipt.get("delivery_enabled") is False
                         and receipt.get("delivery_mode") == "shadow"
                         and receipt.get("status") == "delivery_disabled")
    consistency = (report.get("outcome") == receipt.get("outcome") == result.get("outcome")
                   and result.get("report") == report
                   and sorted(receipt.get("delivery_method_keys", [])) == sorted(d.get("key", "") for d in methods))
    plan_unchanged = bool(card.get("compiled_plan")) and output.get("plan") == card["compiled_plan"]
    return {"exact": bool(outcome_correct and routes_correct and evidence_complete
                          and identity_valid and delivery_disabled and consistency and plan_unchanged),
            "identity_valid": identity_valid, "delivery_disabled": delivery_disabled,
            "consistency": consistency, "plan_unchanged": plan_unchanged,
            "outcome_correct": outcome_correct, "routes_correct": routes_correct,
            "evidence_complete": evidence_complete, "missing_evidence": sorted(required - present),
            "expected_outcome": label["outcome"], "actual_outcome": result.get("outcome"),
            "expected_recipients": label["recipients"], "actual_recipients": sorted(actual),
            "scope": "Native route and source-presence contract; not narrative or causal correctness."}


async def assert_default_agent_profile(server) -> list[str]:
    names = {tool.name for tool in await server.list_tools()}
    expected = set(AGENT_PROFILE_TOOLS)
    if names != expected:
        raise RuntimeError("installed binary did not expose the certified default agent profile")
    return sorted(names)


def onboarding_instructions(server) -> str:
    return (
        "You are authoring a reusable, delivery-disabled policy in the installed SignalWeave "
        "default agent profile. Use only the tools offered in this trial. First call "
        "get_signalweave_guide(task='start'). Ask the owner for the policy and use "
        "search_catalog plus inspect_resource to verify candidate sources. Call "
        "onboard_insight_card with the owner's intent and exact selected_sources refs copied "
        "from inspected resources. numeric_conditions are optional: include one only when its "
        "exact comparison key appears in the inspected source's analytical_comparisons; if no "
        "applicable comparison is declared, omit numeric_conditions and retain the owner's "
        "complete rule in decision_guidance. Never invent a comparison key from an observation "
        "or metric name, and do not invent or change a threshold. Review the stored draft with "
        "review_insight_card and resolve "
        "its actual blockers; do not treat optional blank metadata as a blocker by itself. Read "
        "the complete review result. Save concise policy notes, then record data-expert sign-off "
        "using only inspected refs, including unresolved ambiguities. Request the independent "
        "call request_synthetic_owner_approval for the synthetic owner-policy review, then "
        "call approve_insight_card only when it accepts the "
        "current card and notes. Before pausing for an unresolved alert rule, give a concise "
        "current report from the inspected onboarding evidence, with each source's own "
        "supported scope and period. Do not imply distinct source populations are one cohort "
        "or make a wider company-wide claim. A pending rule pauses recurring automation and "
        "card approval, not useful current analysis. Ask the human owner the precise missing "
        "policy question; do not broaden an ambiguous fallback into an unstated universal rule. "
        "Finish setup with that card ID only after approval. The runner then calls "
        "evaluate_insight_card exactly once per monitoring period in shadow mode and supplies "
        "that result to a separate final-report agent. Do not fetch future periods or claim real "
        "human approval, certification, or delivery readiness. If a material ambiguity remains, "
        "stop and explain the required human clarification.\n"
        "Installed default-profile instructions:\n" + getattr(server, "instructions", "")
    )


def monitoring_instructions(server, *, treatment: bool = True) -> str:
    if treatment:
        opening = (
            " You are the caller-owned analytics agent producing the final business assessment. "
            "Use the current SignalWeave evaluation bundle as evidence and typed triage input; "
            "apply the owner's card, saved policy notes, measurements, and stated routes to "
            "form the final outcome. Reconcile disagreements against source evidence. "
        )
        evidence = (
            "Use the bundle's source facts and computed analyses; inspect only additional "
            "authorized sources needed to answer the owner's questions. "
        )
        product_instructions = ""
    else:
        opening = (
            " This is the notes-only baseline arm. The same owner-reviewed card, saved policy "
            "notes, company context, source catalog, and approved destinations are provided. "
            "Retrieve current evidence with the shared catalog and source tools, then form the "
            "final business outcome from the owner's policy and measurements. "
        )
        evidence = (
            "Use search_catalog, inspect_resource, inspect_source, and "
            "analyze_source to retrieve authorized current-period evidence as needed. "
        )
        product_instructions = ""
    return COMMON_SYSTEM + opening + (
        "The frozen shared_card is the owner's policy for both arms. The treatment receives the "
        "native SignalWeave evaluation bundle; the baseline does not. Both must produce an "
        "independent final business report from the same policy and source tools. Do not assume "
        "either arm is correct. Calculate requested comparisons "
        "explicitly from source values, not by copying numbers from prose. Use the calculate "
        "tool for each required arithmetic expression and verify the result before submission. "
        "For additive metrics, calculate each row's metric, sum rows independently for each "
        "period, calculate current minus baseline, then verify segment contributions sum to "
        "the total delta. If the identities do not reconcile, do not submit the disputed "
        "number; explain the mismatch. For rates, use the owner-defined numerator and "
        "denominator at the same grain, and never average subgroup rates unless the owner's "
        "definition calls for that. Distinguish accounting decomposition and timing association "
        "from causal proof, and cite only source refs available in the provided evidence or "
        "inspected in this period. " + evidence +
        "Do not turn blank/undeclared optional metadata (such as population, grain, or scope) "
        "into proof that records are missing or coverage is incomplete. Require an explicit "
        "source-reported gap, a missing required source/value, or an owner/card rule that "
        "requires the absent metadata before choosing insufficient_data. When the owner has "
        "defined the metric and the returned source provides the requested comparison, report "
        "the source-reported calculation with a precise scope qualification instead of adding "
        "a new company-wide completeness prerequisite. Do not extrapolate beyond that source. "
        "Before adding canonical numeric_claims, confirm the evidence validates every core "
        "part of the owner's metric definition. If a required definition is explicitly unknown "
        "or contradicted, choose the policy's data-quality outcome, leave canonical metric "
        "numeric_claims empty, and state exactly what cannot be validated; do not turn a raw "
        "computed total into the business metric. Match the card's delivery_methods[].destination "
        "URI exactly to business.destinations[].destination, then submit that matching "
        "business.destinations[].key. Never submit the card-local delivery_methods[].key, a "
        "human label, or the URI itself. Submit one structured report with the final policy outcome, canonical recipient keys, "
        "source-supported numeric facts from the provided vocabulary, claims, and evidence refs. "
        "If the data supports an actionable outcome, do not choose ignore or insufficient_data "
        "only because some optional catalog metadata is blank; qualify the scope and route the "
        "work that can be done. Never send notifications: "
        "submit_analysis records a proposed report only. Do not use private future labels. "
        "\nInstalled MCP instructions:\n" + product_instructions)


async def run_trial(scenarios, *, binary, key_file, output, jev_budget=100, live=False,
                    stage_gate=6, fixture_seed=None, author_model: str = MODEL,
                    author_effort: str = "low", recurring_agent_model: str | None = None,
                    recurring_agent_effort: str | None = None, reviewer_model: str | None = None,
                    reviewer_effort: str = "high"):
    recurring_model = recurring_agent_model or author_model
    recurring_effort = recurring_agent_effort or author_effort
    selected_reviewer_model = reviewer_model or MODEL
    model_settings = {
        "author": {"model": author_model, "effort": author_effort},
        "recurring_agent": {"model": recurring_model, "effort": recurring_effort},
        "reviewer": {"model": selected_reviewer_model, "effort": reviewer_effort},
    }
    if any(not settings["model"] or not settings["effort"] for settings in model_settings.values()):
        raise ValueError("Every trial model and reasoning effort must be nonempty")
    binary = Path(binary)
    try:
        binary_build = verify_binary(binary)
    except Exception as error:
        return _invalid_preflight_report(
            scenarios=scenarios, binary=binary, output=output,
            model_settings=model_settings, fixture_seed=fixture_seed, error=error,
        )
    binary_checks = [{"stage": "preflight", "metadata": binary_build}]
    repo = Path(__file__).resolve().parents[1]
    harness_files = (
        "evaluations/installed_workflow_trial.py", "evaluations/installed_trial_transport.py",
        "evaluations/installed_northstar_cases.py", "evaluations/installed_transfer_cases.py",
        "evaluations/bootstrap_agent_trial.py", "evaluations/northstar_onboarding_gap_trial.py",
        "evaluations/bootstrap_owner_review.py", "evaluations/codex_trial_transport.py",
        "scripts/binary_provenance.py",
    )
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    protocol = {
        "version": VERSION, "code": _git_sha(), "binary_sha256": binary_build["binary_sha256"],
        "binary_build": binary_build,
        "harness_sha256": {name: _file_hash(repo / name) for name in harness_files},
        "dataset_sha256": digest(scenarios), "fixture_seed": fixture_seed,
        "jev_attempt_limit": jev_budget, "stop_expansion_after_first_cases": stage_gate,
        "models": model_settings,
        "author_model": author_model, "author_effort": author_effort,
        "recurring_agent_model": recurring_model, "recurring_agent_effort": recurring_effort,
        "owner_review_model": selected_reviewer_model, "owner_review_effort": reviewer_effort,
        "reviewer_model": selected_reviewer_model, "reviewer_effort": reviewer_effort,
        "comparison": "paired_final_business_outcome_runtime",
        "mcp_profile": "agent", "expected_agent_profile_tools": sorted(AGENT_PROFILE_TOOLS),
        "shared_source_tools": sorted(SHARED_SOURCE_PRODUCT_TOOLS | {
            "list_catalog", "search_catalog", "inspect_source", "analyze_source", "calculate", "ask_owner"
        }),
        "pairing_design": "Both monitoring arms use the same recurring model/effort, reviewed card, notes, and source tools; treatment gets the runner's single native evaluation bundle.",
        "companies": len(scenarios),
        "monitoring_cases": sum(len(s["public"]["periods"]) for s in scenarios),
        "expert_cards_seeded": False, "historical_examples_supplied": False,
        "live": live, "delivery_enabled": False,
        "limits": [
            "Known synthetic families, not new customer evidence.",
            "Runtime comparison only: the notes-only baseline receives the treatment-authored reviewed card and notes; onboarding quality is not compared.",
            "Both arms receive the same default-profile source tools, catalog, destinations, model, effort, and shared card. The treatment also receives its native SignalWeave evaluation bundle.",
            "One delivery-disabled native evaluation is run per monitoring period; the final agent report is scored separately.",
            "No measured comparative cost/latency advantage or real user usability claim.",
            "Read-only synthetic MCP source; not a fresh Superset extraction or arbitrary MCP auto-normalization.",
            "Metadata mappings are supplied, not auto-discovered from raw enterprise data.",
            "Owner review is a synthetic policy review, not real human approval or data-quality certification.",
        ],
    }
    write_exclusive(output / "protocol.json", protocol)
    write_exclusive(output / "frozen-scenarios.json", scenarios)
    write_exclusive(output / "preflight.json", {
        "binary_build": binary_build, "source_match": True,
        "required_mcp_profile": "agent", "expected_agent_profile_tools": sorted(AGENT_PROFILE_TOOLS),
    })
    if not live:
        return {"status": "dry_run", **protocol}
    from evaluations.installed_trial_transport import installed_server

    secret = key_file.read_text().strip()
    if not secret:
        raise ValueError("Empty Jev key")
    audit = Audit(output / "trace.jsonl", (secret,))
    budget = RequestBudget(jev_budget)
    all_results = []
    for scenario in scenarios:
        company_event_offset = len(audit.events)
        public = public_scenario(scenario)
        public["require_agent_data_signoff"] = True
        adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
        adapter.set_period(public["onboarding"], datetime.now(timezone.utc))
        audit.episode = public["scenario_id"] + "/onboarding"
        company_result = {"scenario_id": public["scenario_id"], "onboarding_complete": False,
                          "status": "pending", "periods": []}
        all_results.append(company_result)

        async def reviewer(**kwargs):
            return await review_owner_artifact(
                **kwargs, audit=audit, budget=budget,
                model=selected_reviewer_model, effort=reviewer_effort,
            )

        with tempfile.TemporaryDirectory(prefix="signalweave-installed-workflow-") as temporary:
            try:
                _verify_binary_stage(binary, binary_build, binary_checks,
                                     f"before_live_setup:{public['scenario_id']}")
                async with installed_server(binary=binary, key_file=key_file, public=public,
                                            adapter=adapter, audit=audit, budget=budget,
                                            work=Path(temporary).resolve()) as server:
                    profile_tools = await assert_default_agent_profile(server)
                    session = InstalledSession(public, adapter, server, True,
                                               owner_reviewer=reviewer)
                    started = time.perf_counter()
                    episode = await codex_episode(
                        session, key="", model=author_model, effort=author_effort,
                        budget=budget, audit=audit, max_turns=50,
                        max_tool_calls=60, max_output_tokens=6000, timeout_seconds=360,
                        instructions_override=onboarding_instructions(server),
                        prompt_override={"phase": "onboarding", "business": session.public,
                                         "period": adapter.period_context})
                    company_result.update(onboarding=episode, onboarding_seconds=time.perf_counter() - started,
                                          owner_reviews=session.owner_review_records,
                                          onboarding_complete=session.setup_complete, notes=session.notes,
                                          mcp_profile="agent", mcp_profile_tools=profile_tools)
                    if not session.setup_complete or episode.get("foreign_tools"):
                        expected_pause = scenario["private"].get("onboarding_expectation", {})
                        pause_record = expected_human_clarification_record(
                            expected_pause, session.unknown_owner_topics, episode,
                            inspected_refs=session.agent_inspected,
                            future_period_count=len(public["periods"]),
                        )
                        if pause_record is not None:
                            company_result.update(pause_record, status="human_clarification_pending")
                            company_result["agent_calls"] = _agent_call_count(
                                audit.events[company_event_offset:]
                            )
                            write_exclusive(
                                output / f"{public['scenario_id']}-onboarding.json",
                                audit.redact(company_result),
                            )
                            write_exclusive(
                                output / f"{public['scenario_id']}-result.json",
                                audit.redact(company_result),
                            )
                            continue
                        raise ValueError("onboarding_incomplete_or_foreign_tools")
                    card = await session.product("get_insight_card", {"card_id": session.card_id})
                    company_result["card"] = card
                    frozen_card = card_fingerprint(card)
                    frozen_plan = digest(card.get("compiled_plan"))
                    company_result["card_fingerprint"] = frozen_card
                    company_result["compiled_plan_fingerprint"] = frozen_plan
                    write_exclusive(output / f"{public['scenario_id']}-onboarding.json", company_result)
                    session.phase = "monitoring"
                    baseline_adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
                    baseline_session = InstalledSession(
                        public, baseline_adapter, server, False, owner_reviewer=reviewer
                    )
                    baseline_session.phase = "monitoring"
                    baseline_session.setup_complete = True
                    baseline_session.notes = session.notes
                    baseline_session.owner_topics = set(session.owner_topics)
                    baseline_session.data_signoff = copy.deepcopy(session.data_signoff)
                    baseline_session.shared_card = copy.deepcopy(card)
                    for period_index, period in enumerate(public["periods"]):
                        if period_index == stage_gate and not all(
                            r.get("outcome_comparison", {}).get("baseline", {}).get("exact")
                            and r.get("outcome_comparison", {}).get("treatment", {}).get("exact")
                            for r in company_result["periods"]
                        ):
                            raise ValueError("initial_stage_failed; remaining intended cases retained as not run")
                        period_clock = datetime.now(timezone.utc)
                        adapter.set_period(period, period_clock)
                        baseline_adapter.set_period(period, period_clock)
                        episode_id = f"{public['scenario_id']}/{period['period_id']}"
                        audit.episode = episode_id
                        row = {"period_id": period["period_id"], "completed": False,
                               "exact": False, "result": None}
                        result = None
                        begin, offset = time.perf_counter(), len(audit.events)
                        try:
                            current = await session.product("get_insight_card", {"card_id": session.card_id})
                            if (card_fingerprint(current) != frozen_card
                                    or digest(current.get("compiled_plan")) != frozen_plan):
                                raise ValueError("frozen_card_changed")
                            try:
                                result = await session.product("evaluate_insight_card", {
                                    "card_id": session.card_id, "idempotency_key": episode_id,
                                    "response_mode": "compact",
                                })
                                audit.emit("system.evaluation", response=result)
                                row["native_score"] = score_native(
                                    result, card, scenario["private"]["periods"][period["period_id"]],
                                    public["destinations"],
                                )
                                row["result"] = result
                            except Exception as error:
                                row["native_evaluation_error"] = type(error).__name__
                                row["native_evaluation_root_causes"] = _root_cause_summary(error, audit)
                                audit.emit("system.evaluation.error", error_type=type(error).__name__)

                            order = ("baseline", "treatment") if period_index % 2 == 0 else ("treatment", "baseline")
                            arm_results = {}
                            for arm in order:
                                arm_session = baseline_session if arm == "baseline" else session
                                arm_session.phase = "monitoring"
                                arm_session.submission = None
                                arm_session.agent_inspected.clear()
                                arm_session.phase_owner_topics.clear()
                                arm_session.shared_card = copy.deepcopy(card)
                                audit.episode = f"{episode_id}/{arm}"
                                episode = None
                                score = {"exact": False, "valid_submission": False,
                                         "errors": ["agent_episode_not_completed"]}
                                complete = False
                                visible_refs: set[str] = set()
                                arm_root_causes = []
                                try:
                                    episode = await codex_episode(
                                        arm_session, key="", model=recurring_model,
                                        effort=recurring_effort, budget=budget, audit=audit,
                                        max_turns=20, max_tool_calls=30, max_output_tokens=5000,
                                        timeout_seconds=180,
                                        bundle=result if arm == "treatment" else None,
                                        instructions_override=monitoring_instructions(
                                            server, treatment=arm == "treatment",
                                        ),
                                        prompt_override={
                                            "phase": "monitoring", "business": arm_session.public,
                                            "period": arm_session.adapter.period_context,
                                            "saved_notes": arm_session.notes,
                                        },
                                    )
                                    complete = bool(
                                        episode.get("status") == "complete"
                                        and episode.get("error") in (None, "")
                                        and episode.get("exit_code") == 0
                                        and not episode.get("foreign_tools")
                                        and arm_session.submission is not None
                                    )
                                    visible_refs = set(arm_session.agent_inspected)
                                    if arm == "treatment" and result is not None:
                                        visible_refs |= bundle_visible_refs(result, card)
                                    score = score_submission(
                                        scenario, period["period_id"], arm_session.submission or {},
                                        inspected_refs=visible_refs,
                                        asked_owner_topics=(arm_session.owner_topics |
                                                            arm_session.phase_owner_topics),
                                    )
                                    if not complete:
                                        score["exact"] = False
                                except Exception as error:
                                    arm_root_causes = _root_cause_summary(error, audit)
                                    audit.emit("agent.arm.error", arm=arm,
                                               error_type=type(error).__name__,
                                               root_causes=arm_root_causes)
                                observed = bool(complete and score.get("valid_submission") is True)
                                arm_results[arm] = {
                                    "completed": complete, "observed": observed,
                                    "exact": bool(score.get("exact")) if observed else None,
                                    "model": episode.get("model") if episode else None,
                                    "effort": episode.get("effort") if episode else None,
                                    "episode": episode, "submission": arm_session.submission,
                                    "score": score, "visible_refs": sorted(visible_refs),
                                    "source_reads": len(arm_session.agent_inspected),
                                    "root_causes": arm_root_causes,
                                }
                            treatment_result = arm_results["treatment"]
                            baseline_result = arm_results["baseline"]
                            treatment_submission = treatment_result["submission"] or {}
                            baseline_submission = baseline_result["submission"] or {}
                            row.update(
                                completed=treatment_result["completed"],
                                observed=treatment_result["observed"],
                                exact=treatment_result["exact"],
                                agent_episode=treatment_result["episode"],
                                submission=treatment_result["submission"],
                                score=treatment_result["score"],
                                agent_visible_refs=treatment_result["visible_refs"],
                                baseline=baseline_result,
                                treatment=treatment_result,
                                agent_order=list(order),
                                shared_card_digest=digest(card),
                                source_reads={
                                    "baseline_agent": baseline_result["source_reads"],
                                    "treatment_agent": treatment_result["source_reads"],
                                    "native_evaluation": adapter.inspections,
                                },
                                outcome_comparison={
                                    "baseline": {
                                        "observed": baseline_result["observed"],
                                        "exact": baseline_result["exact"],
                                        "outcome": baseline_submission.get("outcome"),
                                        "recipients": baseline_submission.get("recipients"),
                                    },
                                    "treatment": {
                                        "observed": treatment_result["observed"],
                                        "exact": treatment_result["exact"],
                                        "outcome": treatment_submission.get("outcome"),
                                        "recipients": treatment_submission.get("recipients"),
                                    },
                                    "treatment_minus_baseline_exact": (
                                        int(treatment_result["exact"]) - int(baseline_result["exact"])
                                        if treatment_result["observed"] and baseline_result["observed"]
                                        else None
                                    ),
                                    "same_model_effort": (
                                        bool(baseline_result["model"] and treatment_result["model"]
                                        and baseline_result["effort"] and treatment_result["effort"]
                                        and baseline_result["model"] == treatment_result["model"]
                                        and baseline_result["effort"] == treatment_result["effort"]
                                        )
                                    ),
                                    "same_card_digest": (
                                        digest(baseline_session.shared_card)
                                        == digest(session.shared_card)
                                    ),
                                    "same_notes_digest": (
                                        digest(baseline_session.notes) == digest(session.notes)
                                    ),
                                },
                            )
                        except Exception as error:
                            row["error_type"] = type(error).__name__
                            row["root_causes"] = _root_cause_summary(error, audit)
                            row["error"] = row["root_causes"]
                            audit.emit("episode.error", error_type=type(error).__name__,
                                       root_causes=row["root_causes"])
                        audit.episode = episode_id
                        row.update(seconds=time.perf_counter() - begin,
                                   usage=usage_summary(audit.events[offset:]))
                        company_result["periods"].append(row)
                        write_exclusive(output / f"{public['scenario_id']}-{period['period_id']}.json", audit.redact(row))
                        print(json.dumps({"company": public["company"], "period": period["period_id"],
                                          "exact": row["exact"], "error_type": row.get("error_type")}), flush=True)
            except Exception as error:
                root_causes = _root_cause_summary(error, audit)
                company_result["error_type"] = type(error).__name__
                company_result["root_causes"] = root_causes
                company_result["error"] = root_causes
                calls_so_far = _agent_call_count(audit.events[company_event_offset:])
                company_result["status"] = _company_failure_status(root_causes, calls_so_far)
                if company_result["status"] == "invalid_preflight":
                    binary_checks.append({"stage": "before_live_setup", "status": "failed",
                                          "root_causes": root_causes})
                audit.emit("company.error", error_type=type(error).__name__,
                           root_causes=root_causes, status=company_result["status"])
        company_result["agent_calls"] = _agent_call_count(audit.events[company_event_offset:])
        if company_result["status"] == "pending":
            company_result["status"] = (
                "completed" if len(company_result["periods"]) == len(public["periods"])
                else "partial"
            )
        present = {row["period_id"] for row in company_result["periods"]}
        company_result["periods"].extend({"period_id": p["period_id"], "completed": False,
                                           "observed": False, "exact": None,
                                           "status": "not_run",
                                           "error_type": company_result.get("error_type", "not_run")}
                                          for p in public["periods"] if p["period_id"] not in present)
        write_exclusive(output / f"{public['scenario_id']}-result.json", audit.redact(company_result))
    rows = [r for company in all_results for r in company["periods"]]
    certification_error = None
    try:
        _verify_binary_stage(binary, binary_build, binary_checks, "before_report_certification")
    except Exception as error:
        certification_error = _root_cause_summary(error, audit)
        binary_checks.append({"stage": "before_report_certification", "status": "failed",
                              "root_causes": certification_error})

    intended = protocol["monitoring_cases"]
    treatment_observed = [row for row in rows if row.get("observed") is True]
    baseline_observed = [
        row for row in rows
        if row.get("outcome_comparison", {}).get("baseline", {}).get("observed") is True
    ]
    paired_observed = [
        row for row in rows
        if row.get("observed") is True
        and row.get("outcome_comparison", {}).get("baseline", {}).get("observed") is True
    ]
    treatment_correct = sum(row.get("exact") is True for row in treatment_observed)
    baseline_correct = sum(
        row["outcome_comparison"]["baseline"].get("exact") is True
        for row in baseline_observed
    )
    paired_both_correct = sum(
        row.get("exact") is True
        and row["outcome_comparison"]["baseline"].get("exact") is True
        for row in paired_observed
    )
    agent_calls = sum(company.get("agent_calls", 0) for company in all_results)
    has_invalid_preflight = any(company.get("status") == "invalid_preflight" for company in all_results)
    if certification_error:
        report_status = (
            "invalid_preflight" if _is_binary_identity_failure(certification_error)
            else "not_certified"
        )
        accuracy_status = "invalidated_by_provenance"
    elif has_invalid_preflight:
        report_status, accuracy_status = "invalid_preflight", "not_observed"
    elif agent_calls == 0:
        report_status, accuracy_status = "not_run", "not_observed"
    elif len(treatment_observed) == intended and len(baseline_observed) == intended:
        report_status, accuracy_status = "completed", "observed"
    elif any(company.get("onboarding_expected_pause") is True for company in all_results):
        report_status = "human_clarification_pending"
        accuracy_status = "observed" if treatment_observed else "not_observed"
    else:
        report_status = "partial"
        accuracy_status = "observed" if treatment_observed else "not_observed"

    report = {"status": report_status, "business_accuracy_status": accuracy_status,
              "preflight": {"status": "passed", "binary_build": binary_build},
              "certification_error": certification_error,
              "protocol": protocol, "companies": all_results,
              "summary": {"onboarding_complete": sum(c["onboarding_complete"] for c in all_results),
                          "expected_human_clarification": sum(
                              c.get("onboarding_expected_pause") is True for c in all_results
                          ),
                          "future_periods_deferred_for_owner_clarification": sum(
                              c.get("future_monitoring", {}).get("periods_not_scored", 0)
                              for c in all_results
                          ),
                          "onboarding_total": len(scenarios),
                          "agent_calls": agent_calls,
                          "agent_correct": treatment_correct,
                          "observed_business_cases": len(treatment_observed),
                          "agent_accuracy": (
                              treatment_correct / len(treatment_observed)
                              if treatment_observed and accuracy_status == "observed" else None
                          ),
                          "baseline_correct": baseline_correct,
                          "observed_baseline_business_cases": len(baseline_observed),
                          "baseline_accuracy": (
                              baseline_correct / len(baseline_observed)
                              if baseline_observed and accuracy_status == "observed" else None
                          ),
                          "paired_both_correct": paired_both_correct,
                          "paired_observed_business_cases": len(paired_observed),
                          "not_run_business_cases": intended - len(treatment_observed),
                          "not_run_baseline_business_cases": intended - len(baseline_observed),
                          "final_outcome_comparisons": len(paired_observed),
                          "native_correct": sum(r.get("native_score", {}).get("exact", False) for r in rows),
                          "completed": sum(r.get("completed", False) for r in rows),
                          "intended": intended},
              "jev_attempts": budget.used, "budget_censored": budget.exhausted,
              "binary_verifications": binary_checks,
              "usage": usage_summary(audit.events),
              "passed": accuracy_status == "observed" and len(paired_observed) == intended
              and paired_both_correct == intended and not budget.exhausted,
              "scope": "Default-agent synthetic onboarding and paired final business reports over shadow evidence; not enterprise completion."}
    write_exclusive(output / "binary-verifications.json", binary_checks)
    write_exclusive(output / "report.json", audit.redact(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--seed-dir", type=Path)
    parser.add_argument("--seed", type=int, help="Transfer fixture seed; defaults to the recorded regression seed.")
    parser.add_argument("--suite", choices=["northstar", "transfer"], default="northstar")
    parser.add_argument("--company-index", action="append", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--jev-budget", type=int, default=100)
    parser.add_argument("--author-model", default=MODEL)
    parser.add_argument("--author-effort", default="low")
    parser.add_argument("--recurring-agent-model")
    parser.add_argument("--recurring-agent-effort")
    parser.add_argument("--reviewer-model")
    parser.add_argument("--reviewer-effort", default="high")
    args = parser.parse_args()
    if args.live and args.key_file is None:
        parser.error("--live requires --key-file")
    if not 1 <= args.jev_budget <= 250:
        parser.error("budget must be between 1 and 250")
    if args.suite == "northstar":
        if args.seed_dir is None or args.company_index is not None or args.seed is not None:
            parser.error("northstar requires --seed-dir and does not accept --company-index or --seed")
        from evaluations.installed_northstar_cases import build_northstar
        scenarios = [build_northstar(args.seed_dir, smoke=args.smoke)]
    else:
        if args.smoke or args.seed_dir is not None:
            parser.error("transfer uses --company-index for bounded probes, not --smoke/--seed-dir")
        from evaluations.installed_transfer_cases import DEFAULT_SEED, build_transfers
        args.seed = DEFAULT_SEED if args.seed is None else args.seed
        scenarios = build_transfers(args.seed)
        if args.company_index is not None:
            if len(set(args.company_index)) != len(args.company_index) or any(i not in range(len(scenarios)) for i in args.company_index):
                parser.error("Company indices must be unique and in range")
            scenarios = [s for i, s in enumerate(scenarios) if i in args.company_index]
    report = asyncio.run(run_trial(scenarios, binary=args.binary.resolve(), key_file=args.key_file,
                                   output=args.output, jev_budget=args.jev_budget, live=args.live,
                                   fixture_seed=args.seed, author_model=args.author_model,
                                   author_effort=args.author_effort,
                                   recurring_agent_model=args.recurring_agent_model,
                                   recurring_agent_effort=args.recurring_agent_effort,
                                   reviewer_model=args.reviewer_model,
                                   reviewer_effort=args.reviewer_effort))
    print(json.dumps({k: v for k, v in report.items() if k not in {"companies", "protocol"}}, indent=2))


if __name__ == "__main__":
    main()

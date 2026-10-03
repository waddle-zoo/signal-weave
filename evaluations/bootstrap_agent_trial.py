"""Opt-in live bootstrap trial: Luna over BI tools versus Luna + SignalWeave/Jev.

No prewritten cards, model fallback, oracle-in-prompt, or simulated latency. This
is an evaluation caller, not a product agent. Run --preflight before spending.
Output directories are exclusive: interrupted/partial runs are retained and must
not be resumed as if their missing attempts were free. Both arms retain notes.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import copy
import hashlib
import json
import math
import operator
import os
import random
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import msgspec
from dotenv import dotenv_values

from evaluations.bootstrap_scenarios import (
    DEFAULT_SEED,
    _Submission,
    ask_owner,
    build_scenarios,
    dataset_digest,
    public_scenario,
    score_submission,
)
from signalweave.diagnostics import analyze_comparison
from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import PrincipalContext, ResourceDescriptor, ResourceSnapshot, SourceRef
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import JsonInsightCardStore, JsonMetricQueryCardStore
from signalweave.typesafe_adapter import JevJudger

MODEL = "gpt-5.6-luna"
ARMS = ("luna_bi", "luna_signalweave_jev")
PRICES = {
    "assumption_date": "2026-09-30",
    "currency": "USD",
    "per_million_tokens": {"luna_input": .20, "luna_cached_input": .02,
                           "luna_output": 1.20, "jev_input": .042, "jev_output": 0.0},
    "sources": ["https://developers.openai.com/api/docs/models/gpt-5.6-luna",
                "https://docs.typesafe.ai/models"],
    "scope": "Small-context standard pricing; estimated token charges, not billed invoices. "
             "Failed requests with missing usage have unknown cost, never assumed free.",
}
PRODUCT_TOOLS = frozenset({
    "get_signalweave_guide", "onboard_insight_card", "propose_insight_card", "draft_insight_card",
    "discover_insight_sources", "review_insight_card", "get_insight_card",
    "list_insight_cards", "list_resources", "inspect_resource", "resolve_insight_sources",
    "simulate_insight_card", "preview_investigation_report", "evaluate_card_workflow",
    "approve_insight_card", "evaluate_insight_card", "get_decision_receipt",
    "record_insight_card_correction",
})
COMMON_SYSTEM = (
    "You are a business analytics agent in a synthetic, read-only company trial. "
    "This trial is caller-managed, delivery-disabled shadow evaluation, not production "
    "certification or permission to notify anyone. Onboarding prepares a reviewed policy "
    "for later shadow observations. No independent historical acceptance snapshots are supplied: "
    "record acceptance as unassessed, do not invent examples, and do not claim unattended "
    "delivery is ready. A successful synthetic owner review authorizes this trial's shadow "
    "setup only, not production approval or correctness. "
    "Start from the ordinary business brief, not a supplied monitoring card. "
    "During onboarding, ask the owner for unclear metric scope, materiality, routing, and policy. "
    "The owner is simulated: obtain answers by calling ask_owner, never by ending "
    "with questions in chat. Those tool responses are the owner's answers. "
    "Inspect the catalog and relevant sources; do not trust a chart title alone. "
    "Use only current-period evidence for measurements; saved notes may preserve policy "
    "and source knowledge, not stale measurements. Calculators are available to both arms. "
    "During monitoring, reuse the validated policies in saved notes; ask_owner only for "
    "new ambiguity. Current-period evidence provided in a tool result or evaluation bundle "
    "can be reused without fetching it again; inspect more sources if needed to validate "
    "the analysis. The supplied period as_of is the simulated current clock. "
    "Do not infer causality from correlation or fill missing populations with zeros. "
    "Model uncertainty is not proof of missing records: distinguish unresolved semantic "
    "judgments from source-reported gaps and cite evidence for either claim. "
    "Do not perform external notifications. Recipients are authorized destination keys, "
    "not invented people or URLs. Citations use adapter|resource refs actually inspected. "
    "Include every per-claim citation in the top-level evidence_refs too. Canonical numeric "
    "claims require a known applicable population; if source coverage is incomplete, keep "
    "provisional displayed values qualified in prose rather than asserting them as business facts. "
    "If configuring a delivery method, copy the destination provided in business.destinations; "
    "final submitted recipients use those destinations' keys, not their URLs. "
    "In each monitoring result report the metric delta and useful decomposition/driver "
    "facts when supported, including mix and within effects for rate comparisons. "
    "Use numeric_vocabulary identifiers and units for numeric_claims; do not claim unavailable "
    "facts. Tag claims honestly as observation, accounting_decomposition, association, "
    "hypothesis or causal. Evidence needs to support both the quantities and their meaning. "
    "During onboarding, save reusable notes and call finish_setup when ready. "
    "A draft or an edited draft is not completion: repeat inspection, preview "
    "and independent review after changes. A correctable tool error or first review rejection "
    "is not terminal while the stated correction budget remains. Never bypass approval; "
    "ask the simulated owner through ask_owner for missing business policy. "
    "During monitoring, call submit_analysis to finish; prose alone is not a submission."
)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, msgspec.Struct):
        return msgspec.to_builtins(value)
    return value


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class RequestBudget:
    limit: int
    used: int = 0
    exhausted: bool = False

    def claim(self) -> None:
        if self.used >= self.limit:
            self.exhausted = True
            raise BudgetExceeded("global_api_request_budget_exhausted")
        self.used += 1  # Failed requests count too. No automatic retries.


@dataclass
class Audit:
    path: Path | None = None
    secrets: tuple[str, ...] = ()
    events: list[dict] = field(default_factory=list)
    episode: str = "preflight"

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            for secret in self.secrets:
                if secret:
                    value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def emit(self, kind: str, **payload: Any) -> None:
        text = canonical(self.redact({"kind": kind, "episode": self.episode, **json_value(payload)}))
        event = json.loads(text)
        self.events.append(event)
        if self.path:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(text + "\n")
                stream.flush()


class MeasuredJev(JevJudger):
    """Production Jev calls with an attempt budget and evaluation-only wire audit."""

    def __init__(self, key: str, budget: RequestBudget, audit: Audit):
        super().__init__(api_key=key, max_retries=0)
        self.budget, self.audit = budget, audit

    async def _system_one_with_retry(self, *, state, questions, stage):
        self.budget.claim()
        request_id = self.budget.used
        started = time.perf_counter()
        self.audit.emit("api.request", provider="jev", request_id=request_id,
                        model=self.name, stage=stage, state=state,
                        questions=self._question_budget_payload(questions))
        try:
            response = await super()._system_one_with_retry(
                state=state, questions=questions, stage=stage)
        except Exception as error:
            self.audit.emit("api.error", provider="jev", request_id=request_id,
                            error_type=type(error).__name__, seconds=time.perf_counter() - started,
                            usage_known=False)
            raise
        self.audit.emit("api.response", provider="jev", request_id=request_id,
                        response=json_value(response), usage=json_value(getattr(response, "usage", None)),
                        seconds=time.perf_counter() - started)
        return response


def calculate(expression: str) -> float:
    """Small arithmetic helper, not eval/exec or model-generated code execution."""
    if len(expression) > 4000:
        raise ValueError("expression too long")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 500:
        raise ValueError("too many arithmetic terms")
    operations = {ast.Add: operator.add, ast.Sub: operator.sub,
                  ast.Mult: operator.mul, ast.Div: operator.truediv}

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return (-1 if isinstance(node.op, ast.USub) else 1) * visit(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](visit(node.left), visit(node.right))
        raise ValueError("Only numeric literals, parentheses and + - * / are allowed")

    result = visit(tree)
    if not math.isfinite(result):
        raise ValueError("nonfinite result")
    return result


def shift_timestamps(value: Any, delta) -> Any:
    """Rebase the synthetic clock equally, preserving freshness ages and intervals."""
    if isinstance(value, dict):
        return {key: shift_timestamps(item, delta) for key, item in value.items()}
    if isinstance(value, list):
        return [shift_timestamps(item, delta) for item in value]
    if isinstance(value, str) and "T" in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo:
                return (parsed + delta).isoformat()
        except ValueError:
            pass
    return value


class PublicSourceAdapter:
    """A single-period public view; future snapshots/labels are not retained here."""

    name = "company_mcp"

    def __init__(self, catalog: list[dict], tenant: str, audit: Audit):
        self.audit = audit
        self.catalog = []
        for item in catalog:
            descriptor = ResourceDescriptor.model_validate(item)
            # Trusted synthetic transport identity only, not semantic enrichment.
            descriptor.contract.tenant_id = tenant
            self.catalog.append(descriptor)
        self.snapshots: dict[str, dict] = {}
        self.inspected: set[str] = set()
        self.inspections = 0

    def set_period(self, period: dict, clock: datetime) -> None:
        self.clock = clock
        self.period_context = {"period_id": period["period_id"], "as_of": clock.isoformat()}
        delta = clock - datetime.fromisoformat(period["as_of"])
        self.snapshots = shift_timestamps(copy.deepcopy(period["snapshots"]), delta)
        self.inspected.clear()
        self.inspections = 0

    async def list_resources(self):
        return [item.model_copy(deep=True) for item in self.catalog]

    async def inspect(self, source: SourceRef):
        ref = f"{source.adapter}|{source.resource}"
        allowed = {f"{item.adapter}|{item.resource}": item for item in self.catalog}
        if ref not in allowed or source.parameters:
            raise ValueError("unknown source or unsupported parameters")
        result = ResourceSnapshot.model_validate(self.snapshots[ref])
        result.source_key = source.key
        result.contract.tenant_id = allowed[ref].contract.tenant_id
        # Transport source-key normalization, not fabricated evidence. Nested
        # provenance IDs must follow the caller's key just as top-level IDs do.
        result.evidence = [item.model_copy(update={"source_key": source.key})
                           for item in result.evidence]
        result.observations = [item.model_copy(update={"source_key": source.key})
                               for item in result.observations]
        self.inspected.add(ref)
        self.inspections += 1
        self.audit.emit("source.read", ref=ref, snapshot=result.model_dump(mode="json"))
        return result


def function(name: str, description: str, properties: dict, required=()) -> dict:
    return {"type": "function", "name": name, "description": description, "strict": False,
            "parameters": {"type": "object", "properties": properties,
                           "required": list(required), "additionalProperties": False}}


def common_tools(public: dict, phase: str) -> list[dict]:
    text = {"type": "string"}
    tools = [
        function("list_catalog", "List the same read-only BI source catalog available to both arms.", {}),
        function("inspect_source", "Read one current-period source; cite adapter|resource exactly.",
                 {"ref": text}, ["ref"]),
        function("analyze_source", "Read source and compute verified accounting/rate decompositions "
                 "if it exports analytical comparisons. Available to both arms, no semantic judgment.",
                 {"ref": text}, ["ref"]),
        function("calculate", "Evaluate bounded numerical arithmetic (+ - * /); no code execution.",
                 {"expression": text}, ["expression"]),
        function("ask_owner", "Ask the human owner's known policies, not missing measurements or answers.",
                 {"topic": {"type": "string", "enum": public["owner_topics"]}}, ["topic"]),
        function("save_notes", "Replace durable agent notes for subsequent periods. Preserve context "
    "and policy, not current numbers as future truth. Same facility in both arms.",
                 {"notes": text}, ["notes"]),
    ]
    if phase == "onboarding":
        tools.append(function("finish_setup", "Finish onboarding after inspection and policy lookup. "
                              "Treatment requires an explicitly approved, dry-run-tested card; "
                              "baseline uses its durable notes and leaves card_id null.",
                              {"card_id": {"type": ["string", "null"]}}, []))
    else:
        schema = _Submission.model_json_schema()
        # Declare the public contract equally for both arms, never period labels.
        numeric_schema = next(value for value in schema["$defs"].values()
                              if "fact" in value.get("properties", {}))
        numeric_schema["properties"]["fact"]["enum"] = public["numeric_vocabulary"]
        tools.append({"type": "function", "name": "submit_analysis", "strict": False,
                      "description": "Submit the final current-period evidence-backed analysis. "
                      "This records proposed recipients only; it never sends a notification.",
                      "parameters": schema})
    return tools


def agent_context(public: dict) -> dict:
    # No whole-scenario serialization: future periods, snapshots and owner answers
    # must be fetched through bounded current-period/source/owner tools.
    return {key: copy.deepcopy(public[key]) for key in
            ("company", "brief", "glossary", "owner_topics", "destinations",
             "numeric_vocabulary", "submission_contract")}


def card_fingerprint(card: dict) -> str:
    ignored = {"compiled_plan", "onboarding_reviews", "onboarding_review", "status",
               "onboarding_review_history", "onboarding_corrections",
               "approved_at", "approved_by", "updated_at", "created_at"}
    return digest({key: val for key, val in card.items() if key not in ignored})


class ToolSession:
    def __init__(self, public: dict, adapter: PublicSourceAdapter, server, treatment: bool,
                 *, owner_reviewer=None):
        self.public = agent_context(public)
        self.owner = {"owner_answers": copy.deepcopy(public["owner_answers"])}
        self.adapter, self.server, self.treatment = adapter, server, treatment
        self.notes = ""
        self.owner_topics: set[str] = set()
        self.reviewed: dict[str, str] = {}
        self.simulated: dict[str, str] = {}
        self.owner_approvals: dict[str, str] = {}
        self.card_id: str | None = None
        self.setup_complete = False
        self.submission: dict | None = None
        self.phase = "onboarding"
        self.allowed_product: set[str] = set()
        self.owner_reviewer = owner_reviewer
        self.owner_review_records: list[dict] = []
        self.owner_review_attempts = 0
        self.semantic_approval: str | None = None
        self.setup_source_context: dict | None = None

    def owner_source_context(self) -> dict:
        from evaluations.bootstrap_owner_review import project_source_context

        if self.setup_complete and self.setup_source_context is not None:
            return copy.deepcopy(self.setup_source_context)
        # Only the current episode is retained by this adapter. Never serialize
        # the scenario, payload measurements, future periods or private labels.
        return project_source_context({
            "catalog": [item.model_dump(mode="json") for item in self.adapter.catalog],
            "inspected_sources": [
                {**self.adapter.snapshots[ref], "ref": ref}
                for ref in sorted(self.adapter.inspected) if ref in self.adapter.snapshots
            ],
            "current_period": self.adapter.period_context,
        })

    def approval_fingerprint(self, card: dict | None) -> str:
        if self.owner_reviewer is None:
            return card_fingerprint(card or {})
        return digest({"card": card_fingerprint(card) if card else None, "notes": self.notes,
                       "owner_answers": self.owner["owner_answers"],
                       "source_context_digest": digest(self.owner_source_context()),
                       "public_owner_context": {key: self.public[key] for key in
                                                ("brief", "glossary", "destinations")}})

    async def semantic_owner_review(self, card: dict | None) -> dict:
        """Research-only, capped independent review of the original owner text.

        Does not authenticate a human or inspect future evidence/expected labels.
        Both arms pay for reviews; fingerprint changes require a fresh review.
        """
        if not self.notes:
            return {"approved": False, "reasons": ["Save reusable notes before owner review."]}
        # The public directory is an exact caller-supplied mapping, not a semantic
        # judgment. Opaque endpoints are legal; substituting their key is not.
        # This check changes future research admission, not frozen v4 scores.
        if card is not None:
            destinations: dict[str, str] = {}
            errors = []
            for entry in self.public["destinations"]:
                key, destination = entry["key"], entry["destination"]
                if key in destinations and destinations[key] != destination:
                    errors.append(f"The supplied destination directory conflicts for key {key!r}.")
                destinations[key] = destination
            for method in card.get("delivery_methods", []):
                key = method.get("key")
                if key not in destinations or method.get("destination") != destinations[key]:
                    errors.append(f"Delivery method {key!r} must copy its exact supplied destination, not its key or an inferred endpoint.")
            if errors:
                decision = {"approved": False, "directory_validation": "rejected", "reasons": errors,
                            "synthetic": True, "real_human_approval": False}
                self.adapter.audit.emit("review.directory", card_id=card.get("id"), **decision)
                return decision
        fingerprint = self.approval_fingerprint(card)
        previous = next((r for r in self.owner_review_records if r["approval_fingerprint"] == fingerprint), None)
        if previous is not None:
            if previous["approved"]:
                self.semantic_approval = fingerprint
            return {**previous, "replayed": True}
        if self.semantic_approval == fingerprint:
            return {"approved": True, "replayed": True, "approval_fingerprint": fingerprint}
        if self.owner_review_attempts >= 3:
            return {"approved": False, "reasons": ["Three-attempt owner-review budget exhausted."],
                    "budget_exhausted": True}
        self.owner_review_attempts += 1
        reservation = {"approval_fingerprint": fingerprint, "approved": False,
                       "binding_status": "review_pending", "synthetic": True,
                       "real_human_approval": False}
        self.owner_review_records.append(reservation)
        artifact = {"notes": self.notes}
        if card is not None:
            artifact["card"] = copy.deepcopy(card)
        try:
            decision = await self.owner_reviewer(
                public=copy.deepcopy(self.public),
                source_context=self.owner_source_context(),
                owner_answers=copy.deepcopy(self.owner["owner_answers"]), artifact=artifact)
        except Exception as error:
            decision = {"approved": False, "reasons": ["Owner review failed."],
                        "error_type": type(error).__name__}
        if not isinstance(decision, dict):
            decision = {"approved": False, "reasons": ["Malformed owner review."]}
        decision = {**decision, "approval_fingerprint": fingerprint,
                    "approved": decision.get("approved") is True,
                    "synthetic": True, "real_human_approval": False}
        reservation.update(decision)
        decision = reservation
        # Retain the paid attempt even if the binding fetch fails or is cancelled.
        proposed_acceptance = decision["approved"]
        decision.update(approved=False, binding_status="pending")
        try:
            latest_card = await self.product("get_insight_card", {"card_id": card["id"]}) if card else None
            if fingerprint != self.approval_fingerprint(latest_card):
                decision.update(binding_status="changed", reasons=["Draft or notes changed during owner review."])
            else:
                decision.update(approved=proposed_acceptance, binding_status="matched")
        except Exception as error:
            decision.update(binding_status="failed", binding_error_type=type(error).__name__,
                            reasons=["Could not validate the current draft binding."])
        finally:
            self.adapter.audit.emit("review.binding", approval_fingerprint=fingerprint,
                                    approved=decision["approved"], binding_status=decision["binding_status"],
                                    card_id=card["id"] if card else None)
        if decision.get("approved") is True:
            self.semantic_approval = fingerprint
        return decision

    async def assert_current_owner_review(self) -> None:
        if self.owner_reviewer is None:
            return
        card = await self.product("get_insight_card", {"card_id": self.card_id}) if self.treatment else None
        if self.semantic_approval != self.approval_fingerprint(card):
            raise ValueError("Current policy has no matching independent owner review")

    async def specs(self) -> list[dict]:
        specs = common_tools(self.public, self.phase)
        if self.owner_reviewer is not None and self.phase != "onboarding":
            specs = [tool for tool in specs if tool["name"] != "save_notes"]
        if self.owner_reviewer is not None and self.phase == "onboarding":
            specs.append(function("request_synthetic_owner_approval",
                "After saving notes, request independent simulated-owner review against original answers. "
                "Rejections explain what needs correction. Three review attempts per arm/company. "
                "This is model review, not actual human authorization. Treatment must inspect and run a current-card dry-run "
                "the card first with simulate_insight_card or preview_investigation_report; baseline reviews notes and leaves card_id null.",
                {"card_id": {"type": ["string", "null"]}}))
        if self.treatment:
            # Schemas stay coupled to real runtime code, never copied benchmark versions.
            self.allowed_product = set(PRODUCT_TOOLS)
            if self.phase != "onboarding":
                self.allowed_product &= {"get_insight_card", "resolve_insight_sources",
                                         "evaluate_insight_card", "get_decision_receipt"}
            elif self.owner_reviewer is None:
                specs.append(function("request_synthetic_owner_approval",
                                      "Present the inspected card and current-card dry-run (simulate_insight_card or preview_investigation_report) to the simulated owner "
                                      "for procedural approval. This logs a mock human decision; "
                                      "it does not certify semantic correctness or consult expected answers.",
                                      {"card_id": {"type": "string"}}, ["card_id"]))
            for tool in await self.server.list_tools():
                if tool.name in self.allowed_product:
                    specs.append({"type": "function", "name": tool.name,
                                  "description": tool.description, "parameters": tool.inputSchema,
                                  "strict": False})
        return specs

    async def product(self, name: str, arguments: dict) -> Any:
        _content, structured = await self.server.call_tool(name, arguments)
        return json_value(structured)

    async def call(self, name: str, arguments: dict) -> Any:
        if name == "list_catalog":
            return {"resources": [item.model_dump(mode="json")
                                  for item in await self.adapter.list_resources()]}
        if name in {"inspect_source", "analyze_source"}:
            adapter, resource = arguments["ref"].split("|", 1)
            source = SourceRef(key=resource, adapter=adapter, resource=resource, label=resource)
            snapshot = await self.adapter.inspect(source)
            result = {"ref": arguments["ref"], "snapshot": snapshot.model_dump(mode="json")}
            if name == "analyze_source":
                result["analyses"] = [analyze_comparison(source.key, item).model_dump(mode="json")
                                      for item in snapshot.analytical_comparisons]
            return result
        if name == "calculate":
            return {"value": calculate(arguments["expression"])}
        if name == "ask_owner":
            self.owner_topics.add(arguments["topic"])
            return ask_owner(self.owner, arguments["topic"])
        if name == "save_notes":
            if self.owner_reviewer is not None and self.phase != "onboarding":
                raise ValueError("Reviewed policy notes are frozen during monitoring in both trial arms")
            if not isinstance(arguments["notes"], str) or len(arguments["notes"]) > 20000:
                raise ValueError("notes must be text up to 20000 characters")
            self.notes = arguments["notes"]
            return {"saved": True}
        if name == "finish_setup" and self.phase == "onboarding":
            if not self.notes or not self.adapter.inspected or not self.owner_topics:
                raise ValueError("Inspect sources, consult owner and save reusable notes first")
            card_id = arguments.get("card_id")
            if self.treatment:
                if not card_id:
                    raise ValueError("Treatment requires a saved approved card")
                card = await self.product("get_insight_card", {"card_id": card_id})
                if card.get("status") != "approved" or card_id not in self.simulated:
                    raise ValueError("Card must pass dry run and explicit synthetic approval")
                self.card_id = card_id
            if self.owner_reviewer is not None:
                card = (await self.product("get_insight_card", {"card_id": card_id})) if self.treatment else None
                if self.semantic_approval != self.approval_fingerprint(card):
                    return {"setup_complete": False, "reason": "Current card/notes need independent owner review.",
                            "next_tools": ["request_synthetic_owner_approval", "finish_setup"]}
            self.setup_source_context = self.owner_source_context()
            self.setup_complete = True
            return {"setup_complete": True, "card_id": self.card_id,
                    "human_approval": ("independent simulated-owner model review; not actual human authorization"
                                       if self.owner_reviewer is not None else
                                       "synthetic procedural approval, not proof of policy correctness")}
        if name == "submit_analysis" and self.phase == "monitoring":
            parsed = _Submission.model_validate(arguments).model_dump(mode="json")
            if any(c["fact"] not in self.public["numeric_vocabulary"] for c in parsed["numeric_claims"]):
                raise ValueError("Use exact numeric_vocabulary fact identifiers, without values or prose: "
                                 + ", ".join(self.public["numeric_vocabulary"]))
            cited = set(parsed["evidence_refs"])
            claim_refs = {ref for claim in [*parsed["numeric_claims"], *parsed["claims"]]
                          for ref in claim["evidence_refs"]}
            uninspected = (cited | claim_refs) - self.adapter.inspected
            if uninspected:
                raise ValueError("Citations must be exact current-period refs actually inspected: "
                                 + ", ".join(sorted(uninspected)))
            if claim_refs - cited:
                raise ValueError("Include each per-claim citation in top-level evidence_refs: "
                                 + ", ".join(sorted(claim_refs - cited)))
            self.submission = parsed
            return {"recorded": True, "delivery_enabled": False}
        if (name == "request_synthetic_owner_approval" and not self.treatment
                and self.owner_reviewer is not None and self.phase == "onboarding"):
            return await self.semantic_owner_review(None)
        if name == "request_synthetic_owner_approval" and self.treatment and self.phase == "onboarding":
            card_id = arguments["card_id"]
            card = await self.product("get_insight_card", {"card_id": card_id})
            fingerprint = card_fingerprint(card)
            accepted = (self.reviewed.get(card_id) == fingerprint
                        and self.simulated.get(card_id) == fingerprint)
            owner_review = None
            if accepted and self.owner_reviewer is not None:
                owner_review = await self.semantic_owner_review(card)
                accepted = owner_review.get("approved") is True
            decision = {"card_id": card_id, "approved": accepted, "card_digest": fingerprint,
                        "synthetic": True, "policy_correctness_validated": False,
                        "reason": "Inspected stored card and preview; no hidden labels consulted."
                        if accepted else "Current card inspection and/or preview is missing.",
                        "next_tools": (["approve_insight_card", "save_notes", "finish_setup"] if accepted
                                       else ["get_insight_card", "simulate_insight_card", "preview_investigation_report",
                                             "request_synthetic_owner_approval"])}
            if owner_review is not None:
                decision.update(owner_review=owner_review, reason="Independent simulated owner reviewed original instructions, draft and notes; not actual human approval.")
            self.adapter.audit.emit("owner.approval", **decision)
            if accepted:
                self.owner_approvals[card_id] = self.approval_fingerprint(card)
            return decision
        if name not in self.allowed_product or not self.treatment:
            raise ValueError("tool not available in this arm/phase")
        card_id = arguments.get("card_id")
        before = None
        if name in {"simulate_insight_card", "preview_investigation_report"}:
            before = card_fingerprint(await self.product("get_insight_card", {"card_id": card_id}))
        if name == "approve_insight_card":
            card = await self.product("get_insight_card", {"card_id": card_id})
            fingerprint = self.approval_fingerprint(card)
            if self.owner_approvals.get(card_id) != fingerprint:
                raise ValueError("Synthetic owner requires get_insight_card inspection and successful "
                                 "simulate_insight_card or preview_investigation_report then request_synthetic_owner_approval "
                                 "for the current card before approval")
        result = await self.product(name, arguments)
        if name == "get_insight_card":
            self.reviewed[card_id] = card_fingerprint(result)
        if name in {"simulate_insight_card", "preview_investigation_report"} and result.get("status") == "preview":
            # A safe abstention is a valid preview; the independent scorer assesses
            # correctness later. Never approve based on hidden expected outcomes.
            after = card_fingerprint(await self.product("get_insight_card", {"card_id": card_id}))
            if before == after:
                self.simulated[card_id] = before
        return result


async def luna_episode(session: ToolSession, *, key: str, effort: str, budget: RequestBudget,
                       audit: Audit, max_turns: int, max_tool_calls: int,
                       max_output_tokens: int, bundle: dict | None = None,
                       transport=None) -> dict:
    instructions = COMMON_SYSTEM
    if session.treatment:
        instructions += (" SignalWeave is available. For setup: onboard or draft a card from "
                         "the brief and owner answers; inspect it with get_insight_card, dry-run "
                         "simulate_insight_card or preview_investigation_report, resolve blockers, request_synthetic_owner_approval, "
                         "then approve_insight_card. "
                         "Approval models a synthetic owner's procedural review only. Save notes "
                         "and finish_setup with the card ID. No actual human has validated it.")
        instructions += "\nProduction MCP initialization instructions:\n" + (session.server.instructions or "")
    prompt = {"phase": session.phase, "period": session.adapter.period_context,
              "business": session.public, "saved_notes": session.notes,
              "signalweave_evaluation": bundle}
    messages = [{"role": "user", "content": canonical(prompt)}]
    specs = await session.specs()
    allowed = {spec["name"] for spec in specs}
    calls = 0
    started = time.perf_counter()
    error = None
    async with httpx.AsyncClient(timeout=120, transport=transport) as client:
        for _ in range(max_turns):
            try:
                budget.claim()
            except BudgetExceeded:
                error = "global_api_request_budget_exhausted"
                break
            request_id = budget.used
            request = {"model": MODEL, "instructions": instructions, "input": messages,
                       "reasoning": {"effort": effort}, "tools": specs,
                       "max_output_tokens": max_output_tokens, "store": False}
            audit.emit("api.request", provider="openai", request_id=request_id, request=request)
            begin = time.perf_counter()
            try:
                response = await client.post("https://api.openai.com/v1/responses", json=request,
                                             headers={"Authorization": f"Bearer {key}"})
                response.raise_for_status()
                payload = response.json()
                audit.emit("api.response", provider="openai", request_id=request_id,
                           response=payload, usage=payload.get("usage"),
                           seconds=time.perf_counter() - begin)
            except Exception as exc:
                error = type(exc).__name__
                audit.emit("api.error", provider="openai", request_id=request_id,
                           error_type=error, seconds=time.perf_counter() - begin, usage_known=False)
                break
            output = payload.get("output", [])
            messages.extend(output)  # Retain reasoning items as required by Responses API.
            tool_calls = [item for item in output if item.get("type") == "function_call"]
            if not tool_calls:
                error = "no_structured_submission"
                break
            for call in tool_calls:
                calls += 1
                if calls > max_tool_calls:
                    error = "tool_call_budget_exhausted"
                    break
                begin = time.perf_counter()
                arguments = None
                try:
                    if call["name"] not in allowed:
                        raise ValueError("unknown tool")
                    arguments = json.loads(call["arguments"])
                    result = await session.call(call["name"], arguments)
                except BudgetExceeded:
                    error = "global_api_request_budget_exhausted"
                    break
                except Exception as exc:
                    # No provider exception body (may contain credentials) in public artifacts.
                    result = {"error": type(exc).__name__, "message": audit.redact(str(exc)[:2000])}
                audit.emit("tool.result", name=call["name"], arguments=arguments, result=result,
                           seconds=time.perf_counter() - begin)
                messages.append({"type": "function_call_output", "call_id": call["call_id"],
                                 "output": canonical(result)})
                if session.submission is not None or (
                    session.phase == "onboarding" and session.setup_complete
                ):
                    return {"status": "complete", "tool_calls": calls,
                            "seconds": time.perf_counter() - started}
            if error:
                break
    return {"status": "failed", "error": error or "turn_budget_exhausted",
            "tool_calls": calls, "seconds": time.perf_counter() - started}


def usage_summary(events: list[dict]) -> dict:
    totals = {provider: {"attempts": 0, "failed_attempts": 0, "input_tokens": 0,
                        "cached_input_tokens": 0, "output_tokens": 0,
                        "unknown_usage_attempts": 0, "estimated_known_usage_usd": 0.0}
              for provider in ("openai", "jev")}
    responded: set[tuple[str, int]] = set()
    for event in events:
        provider = event.get("provider")
        if provider not in totals:
            continue
        row = totals[provider]
        if event["kind"] == "api.request":
            row["attempts"] += 1
        elif event["kind"] == "api.error":
            row["failed_attempts"] += 1
        elif event["kind"] == "api.response":
            usage = event.get("usage")
            if isinstance(usage, dict) and all(
                type(usage.get(key)) is int and usage[key] >= 0
                for key in ("input_tokens", "output_tokens")
            ):
                responded.add((provider, event["request_id"]))
                row["input_tokens"] += usage["input_tokens"] or 0
                row["output_tokens"] += usage["output_tokens"] or 0
                row["cached_input_tokens"] += (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    prices = PRICES["per_million_tokens"]
    for provider, row in totals.items():
        row["unknown_usage_attempts"] = sum(
            event["kind"] == "api.request" and event.get("provider") == provider
            and (provider, event["request_id"]) not in responded for event in events)
        if provider == "openai":
            cost = ((row["input_tokens"] - row["cached_input_tokens"]) * prices["luna_input"]
                    + row["cached_input_tokens"] * prices["luna_cached_input"]
                    + row["output_tokens"] * prices["luna_output"])
        else:
            cost = row["input_tokens"] * prices["jev_input"]
        row["estimated_known_usage_usd"] = cost / 1_000_000
    return totals


def credentials(args) -> tuple[str, str]:
    codex = getattr(args, "agent_transport", "api") == "codex"
    values = dotenv_values(args.openai_env) if args.openai_env else {}
    openai_key = os.environ.get("OPENAI_API_KEY") or values.get("OPENAI_API_KEY")
    jev_key = os.environ.get("TYPESAFE_API_KEY")
    key_file = args.jev_key_file or os.environ.get("TYPESAFE_API_KEY_FILE")
    if not jev_key and key_file:
        jev_key = Path(key_file).read_text(encoding="utf-8").strip()
    if codex:
        openai_key = ""  # Supported CLI owns saved login; never read its OAuth credentials.
    if (not codex and not openai_key) or not jev_key:
        required = [("TYPESAFE_API_KEY or --jev-key-file", jev_key)]
        if not codex:
            required.insert(0, ("OPENAI_API_KEY", openai_key))
        missing = [name for name, value in required if not value]
        raise ValueError("Missing credential: " + ", ".join(missing) + "; no live run attempted")
    return str(openai_key), str(jev_key)


def write_exclusive(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def source_fingerprint() -> dict:
    root = Path(__file__).resolve().parents[1]
    paths = ("evaluations/bootstrap_agent_trial.py", "evaluations/bootstrap_scenarios.py",
             "evaluations/codex_trial_transport.py", "evaluations/bootstrap_owner_review.py",
             "docs/bootstrap-benchmark-protocol.md", "docs/bootstrap-benchmark-v3.md",
             "docs/bootstrap-owner-reviewed-v4.md", "uv.lock",
             "src/signalweave/engine.py", "src/signalweave/models.py", "src/signalweave/onboarding.py",
             "src/signalweave/diagnostics.py", "src/signalweave/mcp_server.py",
             "src/signalweave/getting_started.py", "src/signalweave/evaluation.py",
             "src/signalweave/numeric_conditions.py", "src/signalweave/reporting.py",
             "src/signalweave/typesafe_adapter.py")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, check=True, timeout=5).stdout.strip()
    return {"git_revision": revision, "sha256": hashes,
            "note": "Content hashes include uncommitted working files; revision alone is insufficient."}


def aggregate(rows: list[dict]) -> dict:
    output = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        cold = [row for row in arm_rows if row["phase"] == "onboarding"]
        warm = [row for row in arm_rows if row["phase"] == "monitoring"]
        def cost(items):
            return sum(sum(p["estimated_known_usage_usd"] for p in r["usage"].values()) for r in items)
        unknown = sum(sum(p["unknown_usage_attempts"] for p in row["usage"].values()) for row in arm_rows)
        output[arm] = {
            "onboarding_attempts": len(cold), "onboarding_complete": sum(r["status"] == "complete" for r in cold),
            "monitoring_denominator": len(warm),
            "complete_monitoring_runs": sum(r["status"] == "complete" for r in warm),
            "exact_count": sum(r.get("score", {}).get("exact", False) for r in warm),
            "outcome_correct_count": sum(r.get("score", {}).get("outcome_correct", False) for r in warm),
            "cold_seconds": sum(r["seconds"] for r in cold),
            "warm_seconds": sum(r["seconds"] for r in warm),
            "source_reads": sum(r.get("source_reads", 0) for r in arm_rows),
            "tool_calls": sum(r.get("tool_calls", 0) for r in arm_rows),
            "luna_api_attempts": sum(r["usage"]["openai"]["attempts"] for r in arm_rows),
            "jev_api_attempts": sum(r["usage"]["jev"]["attempts"] for r in arm_rows),
            "warm_completed_median_seconds": statistics.median([r["seconds"] for r in warm
                if r["status"] == "complete"]) if any(r["status"] == "complete" for r in warm) else None,
            "cold_known_usage_usd": cost(cold), "warm_known_usage_usd": cost(warm),
            "observed_cold_plus_warm_known_usage_usd": cost(arm_rows),
            "setup_amortized_known_usage_usd_per_scheduled_run": cost(arm_rows) / len(warm) if warm else None,
            "unknown_usage_attempts": unknown,
            "cost_complete": unknown == 0,
            "valid_monitoring_submissions": sum(r.get("score", {}).get("valid_submission", False) for r in warm),
            "safety_unassessed_runs": sum(not r.get("score", {}).get("valid_submission", False) for r in warm),
            "runtime_failures": sum(r["status"] != "complete" for r in arm_rows),
        }
        for metric in ("recipients_correct", "wrong_recipient", "false_alert", "missed_event",
                       "unsafe_suppression", "provenance_complete"):
            output[arm][metric + "_count"] = sum(r.get("score", {}).get(metric, False) for r in warm)
        output[arm]["all_structured_cases_pass"] = bool(cold and warm and all(
            r["status"] == "complete" for r in arm_rows) and all(
            r.get("score", {}).get("exact", False) for r in warm))
        system_rows = [r["raw_system_decision"] for r in warm if r.get("raw_system_decision")]
        output[arm]["raw_system_decision_runs"] = len(system_rows)
        if any("owner_reviews" in row for row in arm_rows):
            output[arm]["owner_review_attempts"] = sum(len(row.get("owner_reviews", [])) for row in arm_rows)
            output[arm]["owner_review_tool_calls"] = sum(row.get("owner_review_tool_calls", 0) for row in arm_rows)
        for metric in ("outcome_correct", "recipients_correct", "agent_changed_outcome"):
            output[arm]["raw_system_" + metric + "_count"] = sum(r[metric] for r in system_rows)
    return output


def select_scenarios(scenarios: list[dict], scenario_ids: list[str] | None, limit: int) -> list[dict]:
    """Explicit regression subsets, preserving fixture order and every selected period."""
    if limit < 1:
        raise ValueError("limit must be positive")
    if scenario_ids is None:
        return scenarios[:limit]
    if not scenario_ids or len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("scenario IDs must be nonempty and unique")
    if len(scenario_ids) > limit:
        raise ValueError("explicit scenario selection exceeds limit; do not silently drop a company")
    unknown = set(scenario_ids) - {scenario["scenario_id"] for scenario in scenarios}
    if unknown:
        raise ValueError("Unknown scenario IDs: " + ", ".join(sorted(unknown)))
    return [scenario for scenario in scenarios if scenario["scenario_id"] in scenario_ids]


async def run_trial(args, *, scenarios_override: list[dict] | None = None) -> dict:
    owner_review_mode = getattr(args, "owner_review", "procedural")
    if owner_review_mode == "independent" and getattr(args, "agent_transport", "api") != "codex":
        raise ValueError("Independent owner review currently requires the Codex research transport")
    openai_key, jev_key = credentials(args)  # Fail before creating output or calling a provider.
    fixture_source = scenarios_override if scenarios_override is not None else build_scenarios(seed=args.seed, split=args.split)
    scenarios = select_scenarios(fixture_source,
                                 getattr(args, "scenario_id", None), args.limit)
    if not scenarios:
        raise ValueError("no selected scenarios")
    args.output.mkdir(parents=True, exist_ok=False)
    os.chmod(args.output, 0o700)
    audit = Audit(args.output / "trace.jsonl", (openai_key, jev_key))
    budget = RequestBudget(args.max_api_requests)
    clock = datetime.now(timezone.utc)
    config = {"model": MODEL, "effort": args.effort, "seed": args.seed, "split": args.split,
              "fixtures": "explicit_versioned_scenarios" if scenarios_override is not None else "builtin",
              "dataset_digest": dataset_digest(scenarios), "selected_companies": len(scenarios),
              "selected_scenario_ids": [scenario["scenario_id"] for scenario in scenarios],
              "public_context_digest": digest([public_scenario(scenario) for scenario in scenarios]),
              "max_api_requests": args.max_api_requests, "max_turns": args.max_turns,
              "max_tool_calls": args.max_tool_calls, "max_output_tokens": args.max_output_tokens,
              "prices": PRICES, "clock_rebased_to": clock.isoformat(),
              "source_fingerprint": source_fingerprint(),
              "live": True, "real_external_notifications": False,
              "limits": ["Synthetic sources with normalized adapter contracts, not real BI connectors.",
                         "Human approval is procedural and simulated, not actual human validation.",
                         "No autonomous causal inference or enterprise reliability claim.",
                         "Baseline has notes and calculators but not persistent code generation.",
                         "Comparator: notes-persistent, LLM-per-run baseline, not all agent strategies.",
                         "Scorer checks structured fields, not narrative entailment; prose needs independent review.",
                         "Every warm run wakes Luna in both arms; no claimed wakeup savings."]}
    episode_runner = luna_episode
    owner_reviewer = None
    if owner_review_mode == "independent":
        from evaluations.bootstrap_owner_review import review_owner_artifact

        async def owner_reviewer(**kwargs):
            return await review_owner_artifact(**kwargs, audit=audit, budget=budget)

        config.update(protocol="bootstrap-owner-reviewed-v4", owner_review="independent_synthetic", owner_review_model=MODEL,
                      owner_review_effort="high", owner_review_attempts_per_arm_company=3,
                      owner_review_timeout_seconds=90)
        config["limits"][1] = ("Approval uses an independent simulated owner model, not actual human validation. "
                              "Both arms use the same reviewer and capped correction opportunities.")
    if getattr(args, "agent_transport", "api") == "codex":
        from evaluations.codex_trial_transport import codex_command, codex_episode
        episode_runner = codex_episode
        config.update(agent_transport="codex_cli", max_turns=None, max_output_tokens=None,
                      episode_timeout_seconds=360, api_request_budget_scope="Jev only",
                      codex_version=subprocess.run(["codex", "--version"], capture_output=True,
                                                   text=True, check=True).stdout.strip())
        config["codex_command_template"] = codex_command(
            "<empty-temporary-directory>", "<exclusive-loopback-mcp>", model=MODEL, effort=args.effort)
        config["limits"] += [
            "Codex uses saved ChatGPT login; reported OpenAI attempts mean agent invocations, not API requests.",
            "Codex wall time includes CLI/MCP startup and cleanup; the 360-second active-response timeout excludes them. Wall overrun is reported.",
            "Codex token prices are illustrative API-equivalent estimates, NOT subscription charges; cost advantage gate cannot be established.",
            "Codex internal request/retry count and per-response token cap are not observable or enforced by this harness."]
    write_exclusive(args.output / "config.json", config)
    rows = []
    rng = random.Random(args.seed)
    for scenario in scenarios:
        public = public_scenario(scenario)
        sessions = {}
        order = list(ARMS)
        rng.shuffle(order)
        for arm in order:
            folder = args.output / public["scenario_id"] / arm
            folder.mkdir(parents=True)
            adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
            registry = SourceRegistry([adapter])
            judger = MeasuredJev(jev_key, budget, audit)
            runtime = Runtime(card_store=JsonInsightCardStore(folder / "cards.json"), sources=registry,
                              engine=InsightEngine(judger, registry, clock=lambda a=adapter: a.clock),
                              metric_query_store=JsonMetricQueryCardStore(folder / "metric-cards.json"),
                              principal=PrincipalContext(principal_id="synthetic-owner",
                                                         tenant_id=public["scenario_id"]))
            sessions[arm] = ToolSession(public, adapter, create_mcp(runtime), arm == ARMS[1],
                                        owner_reviewer=owner_reviewer)
        periods = [("onboarding", public["onboarding"])] + [("monitoring", p) for p in public["periods"]]
        for phase, period in periods:
            # Alternate pair order by period to reduce provider/cache ordering bias.
            order.reverse()
            for arm in order:
                session = sessions[arm]
                session.phase, session.submission = phase, None
                # Fixed scenario clock preserves original chronological spacing and ages.
                period_clock = clock + (datetime.fromisoformat(period["as_of"])
                                        - datetime.fromisoformat(public["onboarding"]["as_of"]))
                session.adapter.set_period(period, period_clock)
                audit.episode = f"{public['scenario_id']}/{arm}/{period['period_id']}"
                offset = len(audit.events)
                review_offset = len(session.owner_review_records)
                started = time.perf_counter()
                system_output = None
                row = {"scenario_id": public["scenario_id"], "arm": arm, "phase": phase,
                       "period_id": period["period_id"], "status": "failed", "tool_calls": 0,
                       "system_seconds": 0.0, "agent_seconds": 0.0}
                try:
                    if budget.used >= budget.limit:
                        raise BudgetExceeded("global_api_request_budget_exhausted")
                    if phase == "monitoring" and not session.setup_complete:
                        raise RuntimeError("onboarding_incomplete")
                    if phase == "monitoring":
                        await session.assert_current_owner_review()
                    if phase == "monitoring" and session.treatment:
                        system_started = time.perf_counter()
                        system_output = await session.product("evaluate_insight_card", {
                            "card_id": session.card_id, "idempotency_key": audit.episode})
                        row["system_seconds"] = time.perf_counter() - system_started
                        audit.emit("system.evaluation", response=system_output)
                    episode = await episode_runner(session, key=openai_key, effort=args.effort,
                                                 budget=budget, audit=audit, max_turns=args.max_turns,
                                                 max_tool_calls=args.max_tool_calls,
                                                 max_output_tokens=args.max_output_tokens,
                                                 bundle=system_output)
                    row.update(episode)
                    row["agent_seconds"] = episode["seconds"]
                except Exception as error:
                    row["error"] = type(error).__name__
                    row["tool_calls"] = sum(e["kind"] == "tool.result" and e.get("actor_role") != "owner_reviewer"
                                            for e in audit.events[offset:])
                    audit.emit("episode.error", error_type=type(error).__name__)
                row.update(seconds=time.perf_counter() - started, usage=usage_summary(audit.events[offset:]),
                           submission=session.submission, notes=session.notes, card_id=session.card_id,
                           system_output=system_output, inspected_refs=sorted(session.adapter.inspected),
                           source_reads=session.adapter.inspections, asked_owner_topics=sorted(session.owner_topics))
                if owner_reviewer is not None:
                    row["owner_reviews"] = session.owner_review_records[review_offset:]
                    row["owner_review_tool_calls"] = sum(
                        e["kind"] == "tool.result" and e.get("actor_role") == "owner_reviewer"
                        for e in audit.events[offset:])
                    row["author_tool_calls"] = row["tool_calls"]
                    row["tool_calls"] += row["owner_review_tool_calls"]
                # Scoring happens below, after ALL model calls; no oracle enters live traces.
                rows.append(row)
                write_exclusive(args.output / f"episode-{len(rows):03d}.json", row)
                print(canonical({key: row[key] for key in ("arm", "phase", "status", "seconds")}), flush=True)
    by_id = {scenario["scenario_id"]: scenario for scenario in scenarios}
    for row in rows:
        if row["phase"] == "monitoring":
            try:
                row["score"] = score_submission(by_id[row["scenario_id"]], row["period_id"],
                                                row["submission"] or {}, inspected_refs=row["inspected_refs"],
                                                asked_owner_topics=row["asked_owner_topics"])
            except Exception as error:
                row["score"] = {"exact": False, "valid_submission": False,
                                "safety_unassessed": True, "narrative_review_required": True,
                                "errors": ["scoring_error:" + type(error).__name__]}
            if row["status"] != "complete":
                row["score"]["exact"] = False
            system = (row.get("system_output") or {}).get("result")
            if system:
                expected = by_id[row["scenario_id"]]["private"]["periods"][row["period_id"]]
                destination_keys = {d["destination"]: d["key"] for d in
                                    by_id[row["scenario_id"]]["public"]["destinations"]}
                destinations = sorted({method["destination"] for method in system.get("delivery_methods", [])})
                routes = sorted({destination_keys.get(destination, destination) for destination in destinations})
                row["raw_system_decision"] = {
                    "outcome": system.get("outcome"), "recipients": routes, "destinations": destinations,
                    "outcome_correct": system.get("outcome") == expected["outcome"],
                    "recipients_correct": set(routes) == set(expected["recipients"]),
                    "agent_changed_outcome": system.get("outcome") != (row["submission"] or {}).get("outcome"),
                    "scope": "raw system routing only; not numerical or narrative correctness"}
    budget_censored = budget.exhausted or any(
        row.get("error") in {"BudgetExceeded", "global_api_request_budget_exhausted"}
        for row in rows)
    report = {"config": config, "api_attempts": budget.used, "rows": rows,
              "budget_censored": budget_censored, "comparative_eligible": not budget_censored,
              "comparative_note": "A global budget can starve later arms. Budget-censored reports "
                                  "retain all denominators but cannot support comparative claims.",
              "summary": aggregate(rows), "usage": usage_summary(audit.events),
              "status": "complete" if all(row["status"] == "complete" for row in rows) else "partial_or_failed"}
    report["resolved_jev_models"] = sorted({e["response"]["model"] for e in audit.events
        if e["kind"] == "api.response" and e.get("provider") == "jev"
        and isinstance(e.get("response"), dict) and e["response"].get("model")})
    report["live_jev_observed"] = bool(report["resolved_jev_models"])
    report["comparative_eligible"] &= len(report["resolved_jev_models"]) <= 1
    if config.get("agent_transport") == "codex_cli":
        report["measured_dollar_cost_comparison_available"] = False
        report["jev_api_attempts"] = budget.used
        report["comparative_eligible"] &= not any(row.get("foreign_tools") for row in rows)
        for summary in report["summary"].values():
            summary["codex_invocations"] = summary.pop("luna_api_attempts")
            summary["usage_complete"] = summary.pop("cost_complete")
            summary["cost_basis"] = "illustrative_api_equivalent_not_measured_subscription_cost"
    write_exclusive(args.output / "report.json", report)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--owner-review", choices=["procedural", "independent"], default="procedural")
    result.add_argument("--preflight", action="store_true", help="Offline configuration/credential check; no paid API calls")
    result.add_argument("--openai-env", type=Path, help="Explicit dotenv path; never auto-search user files")
    result.add_argument("--agent-transport", choices=["api", "codex"], default="api",
                        help="codex reuses saved CLI login; no OpenAI API key required")
    result.add_argument("--jev-key-file", type=Path)
    result.add_argument("--split", choices=["dev", "holdout"], default="dev")
    result.add_argument("--limit", type=int, default=6, help="Maximum companies, not periods")
    result.add_argument("--scenario-id", action="append", help="Explicit development subset; repeat per company. No periods are omitted.")
    result.add_argument("--seed", type=int, default=DEFAULT_SEED)
    result.add_argument("--max-api-requests", type=int, default=120, help="Global Luna + Jev attempt ceiling, failures included")
    result.add_argument("--max-turns", type=int, default=12)
    result.add_argument("--max-tool-calls", type=int, default=60)
    result.add_argument("--max-output-tokens", type=int, default=2500)
    result.add_argument("--effort", choices=["none", "low", "medium", "high"], default="low")
    result.add_argument("--output", type=Path, default=Path("artifacts/bootstrap-live"))
    return result


def main() -> None:
    args = parser().parse_args()
    os.umask(0o077)
    try:
        if args.owner_review == "independent" and args.agent_transport != "codex":
            raise ValueError("Independent owner review currently requires the Codex research transport")
        if min(args.limit, args.max_api_requests, args.max_turns, args.max_tool_calls,
               args.max_output_tokens) < 1:
            raise ValueError("limits must be positive")
        credentials(args)
        select_scenarios(build_scenarios(seed=args.seed, split=args.split), args.scenario_id, args.limit)
        if args.output.exists():
            raise ValueError("Output already exists; choose a new directory. No overwrite or silent resume.")
        if args.preflight:
            print(canonical({"status": "configuration_ready", "model": MODEL, "live_model_verified": False,
                             "credentials_present": True, "requests_made": 0,
                             "note": "Credential presence is not provider authentication or model availability."}))
            return
        report = asyncio.run(run_trial(args))
        raise SystemExit(0 if report["status"] == "complete" else 1)
    except (ValueError, OSError) as error:
        # Paths may be reported, but keys and dotenv values never are.
        print(canonical({"status": "blocked", "error": str(error)}))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()

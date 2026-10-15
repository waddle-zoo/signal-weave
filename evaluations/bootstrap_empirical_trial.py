"""Bounded empirical bootstrap worker.

The checked-in fixture worker owns all companies, sources, clocks, cards, and
private labels.  This module owns only projection, authoring, execution, audit,
and replay.  Without ``--live`` it makes no Codex or Jev calls.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from evaluations import codex_trial_transport
from evaluations.bootstrap_agent_trial import (
    Audit,
    RequestBudget,
    canonical,
    json_value,
)
from evaluations.bootstrap_empirical_cases import build_companies as fixture_build_companies
from evaluations.onboarding_acceptance_trial import source_freeze
from examples.investigation_agent.onboarding import DraftIntent, draft_arguments
from signalweave.engine import InsightEngine
from signalweave.evaluation import (
    CardEvaluationCase,
    CardEvaluationThresholds,
    CardWorkflowEvaluator,
    card_acceptance_digest,
)
from signalweave.mcp_server import CARD_AUTHORING_GUIDANCE
from signalweave.models import InsightCard, InsightCardStatus, Outcome, ResourceSnapshot, SourceRef
from signalweave.typesafe_adapter import JevJudger, load_api_key

MODEL = "gpt-5.6-luna"
EFFORT = "low"
MAX_JEV_ATTEMPTS = 72
JEV_TIMEOUT_SECONDS = 30
CODEX_EPISODE_TIMEOUT_SECONDS = 180
MAX_CANDIDATE_EVALUATIONS = 2
MIN_CONFIDENCE_FLOOR = 0.70
SETUP_CASE_COUNT = 3
HOLDOUT_CASE_COUNT = 4
SCHEMA_VERSION = 2
FIXED_SNAPSHOT_PROFILE = {
    "retrieval_mode": "fixed",
    "investigation_mode": "none",
    "action_confidence_threshold": 0.70,
    "max_source_age_hours": 24.0,
}
SCOPE = (
    "bounded card authoring and native Jev holdout comparison; numeric claim scoring is out of scope"
)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class PublicSubmission(BaseModel):
    """The complete raw-Luna output contract; no numeric claims are scored."""

    model_config = ConfigDict(extra="forbid", strict=True)

    outcome: Outcome
    recipients: list[StrictStr] = Field(default_factory=list, max_length=20)
    evidence_refs: list[StrictStr] = Field(default_factory=list, max_length=50)
    explanation: StrictStr = Field(min_length=1, max_length=8_000)


def build_companies(seed: int = 20261002) -> list[dict[str, Any]]:
    """The one fixture API.  No runner-side fallback scenario is permitted."""

    return fixture_build_companies(seed=seed)


def _case_public(case: dict[str, Any], *, labels: bool) -> dict[str, Any]:
    result = {
        key: copy.deepcopy(case[key])
        for key in ("id", "resources", "context", "dataset")
        if key in case
    }
    if labels:
        for key in (
            "expected_outcome",
            "allowed_outcomes",
            "expected_delivery_method_keys",
            "expected_delivery_destinations",
            "required_evidence_source_keys",
            "expected_retrieval_refs",
        ):
            if key in case:
                result[key] = copy.deepcopy(case[key])
    return result


def public_company(company: dict[str, Any]) -> dict[str, Any]:
    """Public author/setup payload; expert card and all holdout labels stay parent-side."""

    return {
        "id": company["id"],
        "brief": company["brief"],
        "owner_policy": company["owner_policy"],
        "as_of": company["as_of"],
        "execution_profile": copy.deepcopy(FIXED_SNAPSHOT_PROFILE),
        "destinations": copy.deepcopy(company["destinations"]),
        "sources": copy.deepcopy(company["sources"]),
        "setup_examples": [_case_public(case, labels=True) for case in company["setup_cases"]],
    }


def public_card_payload(card: InsightCard) -> dict[str, Any]:
    """Accepted authored policy for raw Luna, retaining routes/source declarations."""

    payload = card.model_dump(mode="json")
    for key in (
        "onboarding_review",
        "onboarding_review_history",
        "onboarding_corrections",
        "status",
        "approved_by",
        "approved_at",
        "principal_id",
        "principal_tenant",
    ):
        payload.pop(key, None)
    return payload


def canonical_evidence_refs(resources: list[dict[str, Any]], citations: list[str]) -> list[str]:
    """Resolve only exact identifiers actually present in this case's evidence.

    A source key or observed fact provenance is not an invented citation just
    because the caller did not spell it as adapter|resource. Never guess a
    prefix, accept a different period's fact, or resolve an ambiguous alias.
    """
    aliases: dict[str, set[str]] = {}
    for resource in resources:
        ref = f"{resource['adapter']}|{resource['resource']}"
        names = [ref, resource["source_key"]]
        for fact in [*resource.get("evidence", []), *resource.get("observations", [])]:
            names.extend(fact.get("provenance", []))
        for name in names:
            if isinstance(name, str):
                aliases.setdefault(name, set()).add(ref)
    resolved = []
    for citation in citations:
        matches = aliases.get(citation, set())
        if len(matches) != 1:
            raise ValueError("unknown_or_ambiguous_current_evidence_ref")
        ref = next(iter(matches))
        if ref not in resolved:
            resolved.append(ref)
    return resolved


def acceptance_outcomes(company: dict[str, Any]) -> list[Outcome]:
    """Use only the three labels declared by this company's setup examples."""

    values = {Outcome(case["expected_outcome"]) for case in company["setup_cases"]}
    if len(values) != SETUP_CASE_COUNT:
        raise ValueError("setup cases must cover exactly three declared outcomes")
    return sorted(values, key=lambda item: item.value)


def _candidate(raw: dict[str, Any], company: dict[str, Any]) -> InsightCard:
    """Validate JSON first, then enforce exact company source and route allowlists."""

    try:
        card = InsightCard.model_validate_json(canonical(raw)).model_copy(deep=True)
    except (TypeError, ValueError, ValidationError) as error:
        raise ValueError(f"invalid_candidate_schema: {error}") from error
    allowed_sources = {item["key"]: SourceRef.model_validate(item) for item in company["sources"]}
    actual_sources = {item.key: item for item in card.sources}
    required_sources = {
        key for key, source in allowed_sources.items() if source.required
    }
    missing = required_sources - set(actual_sources)
    unknown = set(actual_sources) - set(allowed_sources)
    if missing:
        raise ValueError("candidate omitted required source keys: " + ", ".join(sorted(missing)))
    if unknown:
        raise ValueError("candidate used unapproved source keys: " + ", ".join(sorted(unknown)))
    for key, actual in actual_sources.items():
        if actual.model_dump(mode="json") != allowed_sources[key].model_dump(mode="json"):
            raise ValueError(f"candidate changed source declaration: {key}")
    destinations = {item["key"]: item for item in company["destinations"]}
    for method in card.delivery_methods:
        expected = destinations.get(method.key)
        if expected is None:
            matches = [
                item for item in company["destinations"]
                if method.label == item["label"] and method.destination == item["destination"]
            ]
            if len(matches) == 1:
                expected = matches[0]
        if expected is None or method.label != expected["label"] or method.destination != expected["destination"]:
            raise ValueError(f"candidate changed destination declaration: {method.key}")
    if card.action_confidence_threshold < MIN_CONFIDENCE_FLOOR:
        raise ValueError(f"candidate confidence floor must be at least {MIN_CONFIDENCE_FLOOR:.2f}")
    for field, expected in FIXED_SNAPSHOT_PROFILE.items():
        if getattr(card, field) != expected:
            raise ValueError(f"operator execution profile requires {field}={expected!r}; author business policy, not runtime settings")
    if card.max_source_age_hours is None or card.max_source_age_hours > 24:
        raise ValueError("candidate max_source_age_hours must be finite and no greater than 24")
    return card.model_copy(
        update={
            "compiled_plan": None,
            "status": InsightCardStatus.DRAFT,
            "approved_by": None,
            "approved_at": None,
            "onboarding_review": None,
            "onboarding_review_history": [],
            "onboarding_corrections": [],
        }
    )


class HistoricalClockEngine(InsightEngine):
    """Use each case's captured_at as the replay clock, never wall clock."""

    async def evaluate(self, card, resources=None, context_override=None, principal=None):
        if resources:
            captures = [
                resource.captured_at
                for resource in resources
                if isinstance(resource, ResourceSnapshot)
            ]
            if captures:
                replay_clock = max(captures)
                self.clock = lambda: replay_clock
        return await super().evaluate(
            card, resources=resources, context_override=context_override, principal=principal
        )


class RecordingHistoricalClockEngine(HistoricalClockEngine):
    """Retain native run evidence separately from the compact evaluator report."""

    def __init__(self, judger: Any):
        super().__init__(judger)
        self.raw_runs: list[Any] = []
        self.case_ids: list[str] = []

    async def evaluate(self, *args, **kwargs):
        case_id = self.case_ids.pop(0) if self.case_ids else "unknown-case"
        try:
            run = await super().evaluate(*args, **kwargs)
        except Exception as error:
            self.raw_runs.append({"case_id": case_id, "error": type(error).__name__})
            raise
        self.raw_runs.append({"case_id": case_id, "run": run})
        return run


class TrialJev(JevJudger):
    """No retries, 30-second Jev calls, shared attempt budget, raw request audit."""

    def __init__(self, key: str, budget: RequestBudget, audit: Audit):
        super().__init__(api_key=key, timeout=JEV_TIMEOUT_SECONDS, max_retries=0)
        self.budget = budget
        self.audit = audit

    async def _system_one_with_retry(self, *, state, questions, stage):
        self.budget.claim()
        request_id = self.budget.used
        started = time.perf_counter()
        self.audit.emit(
            "api.request",
            provider="jev",
            request_id=request_id,
            model=self.name,
            stage=stage,
            timeout_seconds=JEV_TIMEOUT_SECONDS,
            state=state,
            questions=self._question_budget_payload(questions),
        )
        try:
            response = await super()._system_one_with_retry(
                state=state, questions=questions, stage=stage
            )
        except Exception as error:
            self.audit.emit(
                "api.error",
                provider="jev",
                request_id=request_id,
                error_type=type(error).__name__,
                usage_known=False,
                seconds=time.perf_counter() - started,
            )
            raise
        self.audit.emit(
            "api.response",
            provider="jev",
            request_id=request_id,
            response=json_value(response),
            usage=json_value(getattr(response, "usage", None)),
            seconds=time.perf_counter() - started,
        )
        return response


def _case_objects(company: dict[str, Any], card: InsightCard, split: str) -> list[CardEvaluationCase]:
    raw_cases = company["setup_cases"] if split == "validation" else company["holdout_cases"]
    return [CardEvaluationCase(card=card, **_case_public(case, labels=True)) for case in raw_cases]


def _strict_acceptance(report: Any, company: dict[str, Any]) -> bool:
    return bool(
        report.acceptance_passed is True
        and report.status == "approved"
        and report.case_count == SETUP_CASE_COUNT
        and report.error_count == 0
        and report.outcome_accuracy == 1.0
        and report.evidence_recall == 1.0
        and report.retrieval_recall == 1.0
        and report.retrieval_precision == 1.0
        and report.unsafe_action_rate == 0.0
        and not report.preflight_blockers
        and set(report.acceptance_outcomes or []) == set(acceptance_outcomes(company))
    )


def _strict_acceptance_for_card(report: Any, company: dict[str, Any], card: InsightCard) -> bool:
    return _strict_acceptance(report, company) and report.card_execution_digests.get(card.id) == card_acceptance_digest(card)


async def evaluate_candidate(card: InsightCard, company: dict[str, Any], judger: Any) -> Any:
    """Compile against all sources from the first setup case, then strict-replay setup."""

    resources = [ResourceSnapshot.model_validate(item) for item in company["setup_cases"][0]["resources"]]
    engine = HistoricalClockEngine(judger)
    plan = await engine.compile(card, resources=resources)
    card.compiled_plan = plan
    return await CardWorkflowEvaluator(engine, max_concurrency=1).evaluate(
        _case_objects(company, card, "validation"),
        thresholds=CardEvaluationThresholds(min_cases=SETUP_CASE_COUNT),
        acceptance_outcomes=acceptance_outcomes(company),
    )


def _diagnostics(report: Any | None) -> dict[str, Any]:
    if report is None:
        return {"status": "not_evaluated", "cases": []}
    return {
        "status": report.status,
        "preflight_blockers": report.preflight_blockers,
        "cases": [
            {
                "case_id": item.case_id,
                "failure_reasons": item.failure_reasons,
                "evidence_plan": item.evidence_plan.model_dump(mode="json") if item.evidence_plan else None,
                "workflow": item.workflow.model_dump(mode="json") if item.workflow else None,
                "watch_results": [watch.model_dump(mode="json") for watch in item.watch_results],
                "question_results": [question.model_dump(mode="json") for question in item.question_results],
            }
            for item in report.cases
        ],
    }


def _full_payload(value: Any | None) -> Any | None:
    """Keep the complete typed artifact in the audit/result, not a projection."""

    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _full_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_full_payload(item) for item in value]
    if hasattr(value, "__dict__"):
        return {str(key): _full_payload(item) for key, item in vars(value).items()}
    return json_value(value)


def _run_payload(run: Any) -> dict[str, Any]:
    """Serialize the dataclass InsightRun without assuming a Pydantic API."""

    return {
        "card": _full_payload(run.card),
        "resources": [_full_payload(resource) for resource in run.resources],
        "plan": _full_payload(run.plan),
        "result": _full_payload(run.result),
    }


def has_paid_audit_requests(audit: Audit | None) -> bool:
    """Count actual audited provider invocations, including failed Codex calls."""

    return bool(
        audit
        and any(
            event.get("kind") == "api.request"
            and event.get("provider") in {"openai", "jev"}
            for event in audit.events
        )
    )


def _propose_parameters() -> dict[str, Any]:
    return DraftIntent.model_json_schema()


@dataclass
class AuthorSession:
    company: dict[str, Any]
    judger: Any
    audit: Audit
    candidate: InsightCard | None = None
    accepted_card: InsightCard | None = None
    report: Any | None = None
    candidate_evaluations: int = 0
    setup_complete: bool = False
    notes: str = ""
    submission: dict[str, Any] | None = None
    tested_candidate_digest: str | None = None
    last_proposed_digest: str | None = None
    phase: str = "onboarding"
    treatment: bool = True
    audit_role: str = "author"

    def __post_init__(self) -> None:
        self.public = public_company(self.company)
        self.adapter = SimpleNamespace(period_context={"as_of": self.company["as_of"]})
        self.server = SimpleNamespace(instructions=PRODUCTION_MCP_INSTRUCTIONS)

    async def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "propose_card",
                "description": "Propose flat business intent using exact keys from the approved source shortlist and destination directory; the bridge builds the draft card.",
                "strict": True,
                "parameters": _propose_parameters(),
            },
            {
                "type": "function",
                "name": "test_card",
                "description": "Compile the candidate and run strict acceptance on all three setup examples.",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "type": "function",
                "name": "inspect_diagnostics",
                "description": "Inspect evidence-plan, workflow, watch, question, and failure diagnostics.",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "type": "function",
                "name": "finish_setup",
                "description": "Freeze a strictly accepted card and save reusable policy notes.",
                "strict": True,
                "parameters": {"type": "object", "properties": {"notes": {"type": "string", "maxLength": 8000}}, "required": ["notes"], "additionalProperties": False},
            },
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "propose_card":
            if self.setup_complete:
                raise ValueError("accepted_card_is_frozen")
            # A new proposal invalidates any previous acceptance immediately;
            # this prevents a malformed/rejected repair from reusing a stale
            # accepted card at finish time.
            self.candidate = None
            self.report = None
            self.accepted_card = None
            try:
                try:
                    draft = draft_arguments(
                        arguments,
                        self.company["sources"],
                        self.company["destinations"],
                    )
                except (KeyError, TypeError, ValueError, ValidationError) as error:
                    raise ValueError(f"invalid_candidate_schema: {error}") from error
                candidate = _candidate(
                    {
                        "id": f"author-{self.company['id']}",
                        **FIXED_SNAPSHOT_PROFILE,
                        **draft,
                    },
                    self.company,
                )
            except (KeyError, TypeError, ValueError, ValidationError) as error:
                raise ValueError(str(error)) from error
            candidate_digest = digest(candidate.execution_payload())
            if candidate_digest == self.last_proposed_digest or candidate_digest == self.tested_candidate_digest:
                raise ValueError("unchanged_candidate_would_repeat_evaluation")
            self.candidate = candidate
            self.last_proposed_digest = candidate_digest
            return {"recorded": True, "candidate_evaluations_remaining": MAX_CANDIDATE_EVALUATIONS - self.candidate_evaluations}

        if name == "test_card":
            if self.candidate is None:
                raise ValueError("propose_card_first")
            if self.candidate_evaluations >= MAX_CANDIDATE_EVALUATIONS:
                raise ValueError("candidate_evaluation_budget_exhausted")
            candidate_digest = digest(self.candidate.execution_payload())
            if self.tested_candidate_digest == candidate_digest:
                raise ValueError("unchanged_candidate_would_repeat_evaluation")
            self.candidate_evaluations += 1  # reserve before any paid compile
            self.tested_candidate_digest = candidate_digest
            self.report = None
            self.accepted_card = None
            evaluation_error: Exception | None = None
            try:
                self.report = await evaluate_candidate(self.candidate, self.company, self.judger)
            except Exception as error:
                evaluation_error = error
                self.audit.emit("candidate.error", candidate_evaluation=self.candidate_evaluations, error_type=type(error).__name__)
            accepted = bool(
                evaluation_error is None
                and self.report is not None
                and _strict_acceptance(self.report, self.company)
            )
            if accepted:
                self.accepted_card = self.candidate.model_copy(deep=True)
            candidate_payload = _full_payload(self.candidate)
            report_payload = _full_payload(self.report)
            self.audit.emit(
                "candidate.evaluated",
                candidate_evaluation=self.candidate_evaluations,
                candidate=candidate_payload,
                candidate_digest=card_acceptance_digest(self.candidate),
                acceptance_report=report_payload,
                accepted=accepted,
                error_type=type(evaluation_error).__name__ if evaluation_error else None,
            )
            return {
                "accepted": accepted,
                "candidate_evaluation": self.candidate_evaluations,
                "candidate": candidate_payload,
                "acceptance_report": report_payload,
                "diagnostics": _diagnostics(self.report),
                **({"error": type(evaluation_error).__name__} if evaluation_error else {}),
            }

        if name == "inspect_diagnostics":
            return {"candidate_evaluations": self.candidate_evaluations, "diagnostics": _diagnostics(self.report)}

        if name == "finish_setup":
            if (
                self.accepted_card is None
                or self.candidate is None
                or self.report is None
                or digest(self.accepted_card.execution_payload()) != digest(self.candidate.execution_payload())
                or not _strict_acceptance_for_card(self.report, self.company, self.accepted_card)
            ):
                raise ValueError("strict_setup_acceptance_required")
            notes = arguments["notes"]
            if type(notes) is not str or len(notes) > 8_000:
                raise ValueError("notes_must_be_bounded_text")
            self.notes = notes
            self.setup_complete = True
            return {"recorded": True, "frozen": True}

        raise ValueError("tool_not_available")


@dataclass
class RawLunaSession:
    company: dict[str, Any]
    case: dict[str, Any]
    accepted_card: dict[str, Any] | None
    notes: str
    submission: dict[str, Any] | None = None
    phase: str = "monitoring"
    treatment: bool = False
    setup_complete: bool = True
    audit_role: str = "baseline"

    def __post_init__(self) -> None:
        self.public = public_company(self.company)
        self.public["current_holdout"] = _case_public(self.case, labels=False)
        if self.accepted_card is not None:
            self.public["accepted_authored_card"] = copy.deepcopy(self.accepted_card)
        self.adapter = SimpleNamespace(period_context={"as_of": self.company["as_of"]})
        self.server = SimpleNamespace(instructions="")

    async def specs(self) -> list[dict[str, Any]]:
        return [{
            "type": "function",
            "name": "submit_analysis",
            "description": "Submit one label-free result with approved recipient keys and inspected source refs.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "outcome": {"type": "string", "enum": [item.value for item in Outcome]},
                    "recipients": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                    "explanation": {"type": "string", "minLength": 1, "maxLength": 8000},
                },
                "required": ["outcome", "recipients", "evidence_refs", "explanation"],
                "additionalProperties": False,
            },
        }]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "submit_analysis" or self.submission is not None:
            raise ValueError("only_one_submission_is_allowed")
        # JSON serialization is intentional: enum strings are parsed by the
        # strict Pydantic JSON contract, not silently coerced from Python input.
        submission = PublicSubmission.model_validate_json(canonical(arguments)).model_dump(mode="json")
        allowed = {item["key"] for item in self.company["destinations"]}
        if any(item not in allowed for item in submission["recipients"]):
            raise ValueError("unapproved_recipient_key")
        try:
            submission["evidence_refs"] = canonical_evidence_refs(
                self.case["resources"], submission["evidence_refs"],
            )
        except ValueError:
            raise ValueError("uninspected_evidence_ref") from None
        self.submission = submission
        return {"recorded": True, "delivery_enabled": False}


def _episode_complete(episode: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(episode, dict)
        and episode.get("status") == "complete"
        and episode.get("error") in (None, "")
        and type(episode.get("exit_code")) is int
        and episode["exit_code"] == 0
        and not episode.get("foreign_tools")
    )


PRODUCTION_MCP_INSTRUCTIONS = (
    "Production SignalWeave authoring semantics: preserve owner policy in decision_guidance, exact "
    "source contracts and delivery_methods, inspect the effective evidence plan, and use the card "
    "workflow evaluator with owner-declared acceptance outcomes before approval. This trial's library "
    "equivalent is evidence of the evaluator contract, not proof that production MCP was called."
)


AUTHOR_INSTRUCTIONS = (
    "You are the card author in a synthetic read-only trial. Use only the supplied owner policy, "
    "the caller's bounded approved source shortlist (not the entire enterprise catalog), exact "
    "destination directory, and three labeled setup examples. Every approved source with required=true "
    "is forced into the draft; optional required=false sources may be omitted. Do not ask "
    "for or infer holdout labels. Use propose_card, test_card, inspect_diagnostics, and finish_setup. "
    "propose_card accepts one flat DraftIntent: title, what_to_watch, why_watch, decision_guidance, "
    "source_keys, routes, and optional watch_for, questions, evidence_requirements, and "
    "follow_up_guidance. source_keys and routes are exact approved directory selectors; a route's "
    "destination_key selects a directory entry, and method_key is optional for an explicit distinct "
    "delivery key. Do not send a persisted InsightCard, id, compiled plan, approval, profile, "
    "confidence, retrieval, or investigation fields. "
    "You may test at most two distinct candidates; an unchanged retry is forbidden. Inspect the full "
    "diagnostics before repairing. Finish only after strict setup acceptance passes. No external delivery.\n\n"
    + PRODUCTION_MCP_INSTRUCTIONS
    + " The operator supplies a fixed-snapshot execution_profile: no live source registry or "
    "follow-up retrieval is available in this trial. Keep that profile unchanged. It uses the "
    "normal 0.70 support floor, not a claim of 70% accuracy. Do not invent a 1.0 requirement. "
    "Copy approved source declarations exactly; do not reconstruct or rename their parameters. "
    "Represent every outcome-to-recipient rule in the full owner policy, including branches "
    "not illustrated by setup examples. An example set is not the entire policy."
    + CARD_AUTHORING_GUIDANCE
    + " In this research bridge, propose_card is the drafting tool and test_card performs "
    "compilation and workflow replay. Only the four advertised bridge tools are available; "
    "do not call production tool names. Supply minimal new-card fields, not plan, approval "
    "or review-history objects."
)


async def author_company(company: dict[str, Any], *, judger: Any, budget: RequestBudget, audit: Audit) -> dict[str, Any]:
    session = AuthorSession(company, judger, audit)
    try:
        episode = await codex_trial_transport.codex_episode(
            session,
            key="",
            effort=EFFORT,
            budget=budget,
            audit=audit,
            max_turns=4,
            max_tool_calls=16,
            max_output_tokens=4_000,
            timeout_seconds=CODEX_EPISODE_TIMEOUT_SECONDS,
            instructions_override=AUTHOR_INSTRUCTIONS,
            prompt_override={"phase": "onboarding", "business": session.public, "saved_notes": ""},
        )
    except Exception as error:
        episode = {"status": "failed", "error": type(error).__name__, "exit_code": None, "foreign_tools": []}
    complete = _episode_complete(episode) and session.setup_complete and session.accepted_card is not None
    return {
        "status": "accepted" if complete else "failed",
        "episode": episode,
        "candidate_evaluations": session.candidate_evaluations,
        "accepted_card": session.accepted_card.model_dump(mode="json") if complete else None,
        "notes": session.notes if complete else "",
        "last_candidate": _full_payload(session.candidate),
        "acceptance_report": _full_payload(session.report),
        "diagnostics": _diagnostics(session.report),
    }


async def run_native_holdout(company: dict[str, Any], card: InsightCard, judger: Any, *, audit: Audit | None = None, arm: str = "native", raw_output: list[dict[str, Any]] | None = None) -> Any:
    engine = RecordingHistoricalClockEngine(judger)
    cases = _case_objects(company, card, "holdout")
    engine.case_ids = [case.id for case in cases]
    report = await CardWorkflowEvaluator(engine, max_concurrency=1).evaluate(
        cases,
        thresholds=CardEvaluationThresholds(min_cases=HOLDOUT_CASE_COUNT, require_dataset_provenance=True, required_splits=["holdout"]),
    )
    if raw_output is not None:
        for index, case in enumerate(cases):
            recorded = engine.raw_runs[index] if index < len(engine.raw_runs) else {"case_id": case.id, "error": "not_executed"}
            raw = {"case_id": case.id}
            if "run" in recorded:
                raw["run"] = _run_payload(recorded["run"])
            else:
                raw["error"] = recorded.get("error", "not_executed")
            raw_output.append(raw)
            if audit is not None:
                audit.emit("native.result", arm=arm, **raw)
    return report


async def run_raw_holdout(company: dict[str, Any], case: dict[str, Any], *, accepted_card: dict[str, Any] | None, notes: str, budget: RequestBudget, audit: Audit) -> dict[str, Any]:
    session = RawLunaSession(company, case, accepted_card, notes)
    episode = await codex_trial_transport.codex_episode(
        session,
        key="",
        effort=EFFORT,
        budget=budget,
        audit=audit,
        max_turns=1,
        max_tool_calls=1,
        max_output_tokens=1_200,
        timeout_seconds=CODEX_EPISODE_TIMEOUT_SECONDS,
        instructions_override=(
            "You are raw Luna. Use only owner policy, setup examples, accepted authored policy if supplied, "
            "and current evidence. Never use holdout labels. Call submit_analysis exactly once with only "
            "outcome, recipients, evidence_refs, and explanation. No numeric_claims and no external delivery."
        ),
        prompt_override={"phase": "monitoring", "business": session.public, "saved_notes": notes},
    )
    return {"case_id": case["id"], "episode": episode, "submission": session.submission, "complete": _episode_complete(episode) and session.submission is not None}


def score_raw_submission(company: dict[str, Any], case: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    submission = row.get("submission")
    if row.get("complete") is not True or not isinstance(submission, dict):
        return {"case_id": case["id"], "exact": False, "status": "missing"}
    refs = {f"{item['adapter']}|{item['resource']}" for item in company["sources"]}
    submitted_refs = set(submission.get("evidence_refs", []))
    required = {
        f"{item['adapter']}|{item['resource']}"
        for item in company["sources"]
        if item["key"] in case["required_evidence_source_keys"]
    }
    citations = submitted_refs <= refs and required <= submitted_refs
    outcome = submission.get("outcome") == case["expected_outcome"]
    recipients = set(submission.get("recipients", [])) == set(case["expected_delivery_method_keys"])
    return {"case_id": case["id"], "exact": outcome and recipients and citations, "outcome_exact": outcome, "recipients_exact": recipients, "citation_valid": citations}


def recompute_report(companies: list[dict[str, Any]], report: dict[str, Any]) -> dict[str, Any]:
    if report.get("authoring_regression"):
        return {"status": "not_run", "reason": "no new baseline episodes in the authoring regression"}
    result = {}
    for company in companies:
        rows = report.get("execution_comparison", {}).get(company["id"], {}).get("raw_luna", [])
        by_id = {row.get("case_id"): row for row in rows if isinstance(row, dict)}
        cases = [score_raw_submission(company, case, by_id.get(case["id"], {})) for case in company["holdout_cases"]]
        result[company["id"]] = {"case_count": len(cases), "exact_count": sum(item["exact"] for item in cases), "cases": cases}
    return {"numeric_claim_scoring": "out_of_scope", "companies": result}


def _freeze_digest(frozen: dict[str, Any]) -> str:
    return digest(frozen)


def _assert_live_freeze(companies: list[dict[str, Any]], fixture_hash: str, code_freeze: dict[str, Any]) -> None:
    if digest(companies) != fixture_hash:
        raise RuntimeError("fixture_data_freeze_changed")
    if _freeze_digest(source_freeze()) != _freeze_digest(code_freeze):
        raise RuntimeError("code_prompt_dependency_freeze_changed")


async def run_trial(output: Path, *, seed: int = 20261002, live: bool = False, jev_key_file: str | Path | None = None, authoring_regression: bool = False) -> dict[str, Any]:
    companies = build_companies(seed)
    output.mkdir(parents=False, exist_ok=False)
    frozen_code = source_freeze()
    attempt_limit = 40 if authoring_regression else MAX_JEV_ATTEMPTS
    scope = "development authoring regression on previously observed cases; no new baseline or expert control" if authoring_regression else SCOPE
    fixture_hash = digest(companies)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scope": scope,
        "authoring_regression": authoring_regression,
        "execution_profile": FIXED_SNAPSHOT_PROFILE,
        "model": MODEL,
        "effort": EFFORT,
        "max_jev_attempts": attempt_limit,
        "jev_retries": 0,
        "jev_timeout_seconds": JEV_TIMEOUT_SECONDS,
        "codex_episode_timeout_seconds": CODEX_EPISODE_TIMEOUT_SECONDS,
        "max_candidate_evaluations": MAX_CANDIDATE_EVALUATIONS,
        "code_prompt_dependency_freeze": frozen_code,
        "fixture_digest": fixture_hash,
        "companies": companies,
        "external_delivery": False,
        "openai_api_key_used": False,
        "numeric_claim_scoring": "out_of_scope",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    report: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "scope": scope, "authoring_regression": authoring_regression, "status": "not_run" if not live else "running", "paid_calls_made": False, "fixture_digest_before": fixture_hash, "bootstrap_quality": {}, "execution_comparison": {}, "failures": []}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if not live:
        return report
    if not jev_key_file:
        raise ValueError("--jev-key-file is required for --live")
    key = load_api_key(str(jev_key_file))
    if not key:
        raise ValueError("empty TypeSafe key; no live run attempted")
    budget = RequestBudget(attempt_limit)
    events = output / "events.jsonl"
    audit: Audit | None = Audit(events, secrets=(key,), episode="bootstrap-empirical")
    treatment_jev = TrialJev(key, budget, audit)
    expert_jev = TrialJev(key, budget, audit)
    try:
        for company in companies:
            _assert_live_freeze(companies, fixture_hash, frozen_code)
            audit.episode = f"{company['id']}:author"
            try:
                author = await author_company(company, judger=treatment_jev, budget=budget, audit=audit)
            except Exception as error:
                author = {"status": "failed", "error": type(error).__name__}
                report["failures"].append({"company": company["id"], "stage": "author", "error": type(error).__name__})
            _assert_live_freeze(companies, fixture_hash, frozen_code)
            report["bootstrap_quality"][company["id"]] = author
            authored = InsightCard.model_validate(author["accepted_card"]) if author.get("accepted_card") else None
            expert = InsightCard.model_validate(company["expert_card"])
            expert_raw: list[dict[str, Any]] = []
            audit.episode = f"{company['id']}:expert_native"
            expert_report = None if authoring_regression else await run_native_holdout(company, expert, expert_jev, audit=audit, arm="expert", raw_output=expert_raw)
            treatment_raw: list[dict[str, Any]] = []
            audit.episode = f"{company['id']}:treatment_native"
            treatment_report = await run_native_holdout(company, authored, treatment_jev, audit=audit, arm="treatment", raw_output=treatment_raw) if authored else None
            _assert_live_freeze(companies, fixture_hash, frozen_code)
            baseline = []
            for case in ([] if authoring_regression else company["holdout_cases"]):
                audit.episode = f"{company['id']}:baseline:{case['id']}"
                try:
                    baseline.append(await run_raw_holdout(company, case, accepted_card=public_card_payload(authored) if authored else None, notes=author.get("notes", ""), budget=budget, audit=audit))
                except Exception as error:
                    baseline.append({"case_id": case["id"], "complete": False, "error": type(error).__name__})
                    report["failures"].append({"company": company["id"], "stage": "baseline", "case": case["id"], "error": type(error).__name__})
                _assert_live_freeze(companies, fixture_hash, frozen_code)
            report["execution_comparison"][company["id"]] = {
                "paired_with_authored_card": authored is not None and not authoring_regression,
                "author_failed": authored is None,
                "expert_native_jev": expert_report.model_dump(mode="json") if expert_report else None,
                "treatment_native_jev": treatment_report.model_dump(mode="json") if treatment_report else None,
                "expert_native_raw": expert_raw,
                "treatment_native_raw": treatment_raw,
                "raw_luna": baseline,
            }
            report["recomputed_score"] = recompute_report(companies, report)
            (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        report["status"] = "partial_or_failed" if budget.exhausted else "complete"
    except BaseException as error:
        report["status"] = "interrupted" if not isinstance(error, Exception) else "failed"
        report["failures"].append({"stage": "runner", "error": type(error).__name__, "message": str(error)[:2000]})
        if not isinstance(error, Exception):
            raise
    finally:
        try:
            _assert_live_freeze(companies, fixture_hash, frozen_code)
            report["freeze_verified"] = True
        except Exception as error:
            report["freeze_verified"] = False
            report["status"] = "failed"
            report["failures"].append({"stage": "freeze_final", "error": type(error).__name__})
        report["fixture_digest_after"] = digest(companies)
        report["code_prompt_dependency_freeze_after"] = _freeze_digest(source_freeze())
        report["paid_calls_made"] = has_paid_audit_requests(audit)
        report["jev_attempts"] = budget.used
        report["budget_exhausted"] = budget.exhausted
        report["recomputed_score"] = recompute_report(companies, report)
        (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--seed", type=int, default=20261002)
    result.add_argument("--live", action="store_true")
    result.add_argument("--jev-key-file", type=Path)
    result.add_argument("--authoring-regression", action="store_true", help="Previously observed cases; at most three authors and 40 Jev attempts, no baseline/control reruns")
    return result


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.live and args.jev_key_file is None:
        parser().error("--jev-key-file is required with --live")
    report = asyncio.run(run_trial(args.output, seed=args.seed, live=args.live, jev_key_file=args.jev_key_file, authoring_regression=args.authoring_regression))
    raise SystemExit(0 if report["status"] in {"not_run", "complete"} else 1)


if __name__ == "__main__":
    main()

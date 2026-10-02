"""Bounded prospective recurring-runtime comparison.

This is an evaluation harness, not product runtime code.  It keeps the private
case labels in the parent process, authors one card per company, freezes all
cards before opening either recurring arm, and writes enough paired telemetry
to audit source reads, numeric checks, routing, prose and replay.  Without
``--live`` it performs only protocol validation and manifest generation.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.bootstrap_empirical_trial import TrialJev
from evaluations.business_outcome_trial import (
    INSTRUCTIONS as BUSINESS_INSTRUCTIONS,
)
from evaluations.business_outcome_trial import (
    BusinessSession,
)
from evaluations.business_outcome_trial import (
    review_packet as business_review_packet,
)
from evaluations.business_outcome_trial import (
    summarize as business_summarize,
)
from evaluations.codex_trial_transport import codex_episode
from evaluations.first_report_trial import (
    PeriodAdapter,
    Session,
    operator_principal,
)
from evaluations.first_report_trial import (
    dispatch as first_report_dispatch,
)
from evaluations.first_report_trial import (
    score as first_report_score,
)
from evaluations.onboarding_acceptance_trial import source_freeze
from signalweave.diagnostics import AnalysisReport
from signalweave.engine import InsightEngine
from signalweave.mcp_server import CARD_AUTHORING_GUIDANCE, create_mcp
from signalweave.models import InsightCard, InsightCardStatus, SourceRef
from signalweave.numeric_conditions import evaluate_numeric_conditions
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteDecisionReceiptStore, SQLiteInsightCardStore

MODEL = "gpt-5.6-luna"
MAX_JEV_ATTEMPTS = 36
MAX_LUNA_AUTHOR_EPISODES = 3
MAX_LUNA_REPORT_EPISODES = 6
MAX_LUNA_EPISODES = MAX_LUNA_AUTHOR_EPISODES + MAX_LUNA_REPORT_EPISODES
EPISODE_TIMEOUT_SECONDS = 240
MAX_DRAFTS = 2
SETUP_PERIODS = 2
HOLDOUT_PERIODS = 4


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _compare_numeric(value: float, comparator: str, threshold: float) -> bool:
    return {
        "<": value < threshold,
        "<=": value <= threshold,
        "==": value == threshold,
        ">=": value >= threshold,
        ">": value > threshold,
        "!=": value != threshold,
    }[comparator]


def audit_numeric_policy(card: InsightCard, company: dict[str, Any]) -> dict[str, Any]:
    """Independent parent-side audit of authored checks against owner policy.

    This intentionally uses the private oracle's declared materiality and
    measurements, not ``evaluate_numeric_conditions`` or production reports.
    It validates binding/unit/threshold/selector coverage before synthetic
    owner approval; labels never enter an agent prompt or MCP result.
    """
    setup, _ = _period_groups(company)
    expected = {_condition_identity(item) for item in setup[0]["oracle"]["numeric_policy"]}
    if not card.numeric_conditions:
        return {"passed": False, "errors": ["missing_numeric_conditions"]}
    actual = [_condition_identity(item.model_dump()) for item in card.numeric_conditions]
    errors = []
    if len(actual) != len(set(actual)):
        errors.append("duplicate_numeric_condition")
    if set(actual) != expected:
        errors.append("numeric_policy_coverage")
    return {"passed": not errors, "errors": sorted(set(errors))}


def _condition_identity(item: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(item.get(field) for field in (
        "source_key", "comparison_key", "unit", "measurement", "segment",
        "absolute", "comparator", "threshold",
    ))


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _independent_numeric_score(results: list[dict[str, Any]] | None, oracle: dict[str, Any]) -> dict[str, Any]:
    """Score check results from private measurements without the production helper."""
    errors: list[str] = []
    if not results:
        return {"passed": False, "numeric_passed": False, "errors": ["numeric_condition_missing"]}
    expected = {_condition_identity(item) for item in oracle["numeric_policy"]}
    actual = [_condition_identity({**item, "unit": item.get("expected_unit")}) for item in results]
    if set(actual) != expected or len(actual) != len(expected):
        errors.append("numeric_policy_coverage")
    complete = oracle.get("status") == "complete"
    for result in results:
        if _condition_identity({**result, "unit": result.get("expected_unit")}) not in expected:
            errors.append("numeric_binding")
            continue
        if not complete:
            if result.get("status") != "unknown" or result.get("value") is not None:
                errors.append("numeric_incomplete_not_unknown")
            continue
        if result.get("unit") != result.get("expected_unit"):
            errors.append("numeric_unit")
        measurement = result.get("measurement")
        value: float | None
        if measurement == "contribution":
            contributions = oracle.get("measurements", {}).get("contributions", [])
            segment = result.get("segment")
            if segment is None:
                matches = [item for item in contributions if _compare_numeric(
                    abs(item["contribution"]) if result.get("absolute") else item["contribution"],
                    result["comparator"], result["threshold"],
                )]
                expected_status = "true" if matches else "false"
                witness = [item for item in matches if item["segment"] == result.get("matched_segment")]
                value = witness[0]["contribution"] if len(witness) == 1 else None
                if matches and len(witness) != 1:
                    errors.append("numeric_witness")
                if not matches and result.get("matched_segment") is not None:
                    errors.append("numeric_false_witness")
            else:
                selected = [item for item in contributions if item.get("segment") == segment]
                if len(selected) != 1:
                    errors.append("numeric_segment_binding")
                    continue
                value = selected[0].get("contribution")
                if result.get("matched_segment") != segment:
                    errors.append("numeric_witness")
                expected_status = "true" if _finite_number(value) and _compare_numeric(
                    abs(value) if result.get("absolute") else value, result.get("comparator"), result.get("threshold")
                ) else "false"
        else:
            value = oracle.get("measurements", {}).get(measurement)
            expected_status = "true" if _finite_number(value) and _compare_numeric(
                abs(value) if result.get("absolute") else value, result.get("comparator"), result.get("threshold")
            ) else "false"
        if result.get("status") != expected_status:
            errors.append("numeric_status")
        observed = result.get("value")
        if (value is None and observed is not None) or (value is not None and (
            not _finite_number(observed) or not math.isclose(observed, value, rel_tol=1e-10, abs_tol=1e-12)
        )):
            errors.append("numeric_value")
    return {"passed": not errors, "numeric_passed": not errors, "errors": sorted(set(errors))}


def _first_report_oracle(oracle: dict[str, Any]) -> dict[str, Any]:
    """Project recurring-case labels into the first-report scorer's contract."""
    projected = copy.deepcopy(oracle)
    for analysis in projected.get("analyses", []):
        contributions = analysis.get("contributions", [])
        if isinstance(contributions, list):
            analysis["contributions"] = {
                item["segment"]: item["contribution"] for item in contributions
            }
    return projected


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return value


def _period_groups(company: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use the case's explicit setup/holdout split; never infer by position."""
    if "setup_periods" in company or "holdout_periods" in company:
        setup = copy.deepcopy(company.get("setup_periods", []))
        holdout = copy.deepcopy(company.get("holdout_periods", []))
    else:
        periods = copy.deepcopy(company.get("periods", []))
        setup = [p for p in periods if p.get("split") == "setup"]
        holdout = [p for p in periods if p.get("split") == "holdout"]
        if not setup or not holdout:
            raise ValueError("Recurring cases must declare split='setup' and split='holdout'")
    if len(setup) != SETUP_PERIODS or len(holdout) != HOLDOUT_PERIODS:
        raise ValueError(f"{company.get('id', '<unknown>')} must have 2 setup and 4 holdout periods")
    ids = [item["id"] for item in [*setup, *holdout]]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{company.get('id', '<unknown>')} has duplicate period ids")
    return setup, holdout


def _public_company(company: dict[str, Any], *, recurring_only: bool = False) -> dict[str, Any]:
    """Remove labels before any value reaches the agent transport."""
    result = copy.deepcopy(company)
    setup, holdout = _period_groups(result)
    result["periods"] = holdout if recurring_only else [*setup, *holdout]
    result.pop("setup_periods", None)
    result.pop("holdout_periods", None)
    for period in result["periods"]:
        for key in ("oracle", "expected", "label", "labels", "private_oracle"):
            period.pop(key, None)
    for key in ("oracle", "expected", "private_oracle", "scoring_labels"):
        result.pop(key, None)
    return result


class CachedPeriodAdapter(PeriodAdapter):
    """Period-local snapshot cache shared by native evaluation and both arms."""

    def __init__(self, descriptors, audit, sources):
        super().__init__(descriptors, audit, sources)
        self.cache: dict[str, Any] = {}
        self.cache_hits = 0
        self.physical_reads = 0

    def set_period(self, period):
        super().set_period(period)
        self.cache = {}
        self.cache_hits = 0
        self.physical_reads = 0

    async def inspect(self, source):
        cache_key = canonical({"resource": source.resource, "parameters": source.parameters})
        if cache_key in self.cache:
            self.cache_hits += 1
            self.audit.emit("source.cache_hit", source=source.model_dump(mode="json"))
            snapshot = copy.deepcopy(self.cache[cache_key])
            snapshot.source_key = source.key
            for observation in snapshot.observations:
                observation.source_key = source.key
            for evidence in snapshot.evidence:
                evidence.source_key = source.key
            return snapshot
        snapshot = await super().inspect(source)
        self.physical_reads += 1
        self.cache[cache_key] = copy.deepcopy(snapshot)
        return snapshot


class SetupSession(Session):
    """Luna sees only the current setup period and advances explicitly."""

    def __init__(self, *, setup_periods, **kwargs):
        super().__init__(phase="onboarding", **kwargs)
        self.setup_periods = setup_periods
        self.setup_index = 0
        self.previewed_periods: set[str] = set()
        self.audit_role = "luna_author"

    async def specs(self):
        specs = await super().specs()
        specs.insert(1, {
            "name": "current_setup_period",
            "description": "Read only the current setup period; future setup and holdout data are unavailable.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        })
        specs.insert(2, {
            "name": "advance_setup",
            "description": "After previewing this setup period, advance to the second and final setup period.",
            "parameters": {"type": "object", "properties": {"period_id": {"type": "string"}}, "required": ["period_id"], "additionalProperties": False},
        })
        return specs

    async def call(self, name, args):
        period = self.setup_periods[self.setup_index]
        if name == "current_setup_period":
            return {"period_id": period["id"], "as_of": period["as_of"],
                    "setup_index": self.setup_index, "remaining_setup_periods": len(self.setup_periods) - self.setup_index}
        if name == "advance_setup":
            if args["period_id"] != period["id"]:
                raise ValueError("advance_setup must name the current setup period")
            if period["id"] not in self.previewed_periods:
                raise ValueError("Preview the current setup period before advancing")
            if self.setup_index + 1 >= len(self.setup_periods):
                raise ValueError("All setup periods are complete")
            self.setup_index += 1
            self.adapter.set_period(self.setup_periods[self.setup_index])
            self.inspected_analyses.clear()
            self.inspected_period = self.adapter.clock
            return await self.call("current_setup_period", {})
        if name == "preview_investigation_report":
            result = await super().call(name, args)
            self.previewed_periods.add(period["id"])
            return result
        if name == "draft_from_intent":
            if self.setup_index != 0:
                # A repaired second draft starts a fresh setup pass.  The
                # previous draft's previews are not evidence for the new card.
                self.setup_index = 0
                self.adapter.set_period(self.setup_periods[0])
                self.inspected_analyses.clear()
                self.inspected_period = self.adapter.clock
                self.previewed_periods.clear()
            result = await super().call(name, args)
            self.previewed_periods.clear()
            return result
        if name == "finish_setup":
            if set(p["id"] for p in self.setup_periods) != self.previewed_periods:
                raise ValueError("Preview the current card in both setup periods before freezing")
            return await super().call(name, args)
        return await super().call(name, args)


class RecurringSession(BusinessSession):
    """BusinessSession with identical deterministic numeric checks in both arms."""

    def __init__(self, *, card: InsightCard, **kwargs):
        super().__init__(**kwargs)
        self.card = card
        self.numeric_results: list[dict[str, Any]] = []
        self.analysis_digest: str | None = None
        self.unhealthy_source_keys: set[str] = set()
        self.numeric_origin = "code_helper"
        self.catalog_digest = digest({"descriptors": _dump(self.adapter.descriptors), "sources": self.company["sources"], "destinations": self.company["destinations"]})

    async def specs(self):
        specs = await super().specs()
        specs.append({
            "name": "evaluate_numeric_conditions",
            "description": "Optionally re-read the approved card's bound numeric checks. inspect_source already returns these checks; this never selects an action.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        })
        return specs

    def _record_numeric(self, analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Match engine.py: source errors are excluded before the helper.  A
        # broken source must become unknown/blocked, never a passing check.
        healthy = [item for item in analyses
                   if item.get("source_key") not in self.unhealthy_source_keys
                   and not item.get("error")
                   and item.get("contract", {}).get("source_status", "healthy") == "healthy"]
        reports = [AnalysisReport.model_validate(item) for item in healthy]
        results = [item.model_dump(mode="json") for item in evaluate_numeric_conditions(self.card, reports)]
        self.numeric_results = results
        self.analysis_digest = digest(analyses)
        self.numeric_origin = "code_helper"
        return results

    async def call(self, name, args):
        if name == "inspect_source":
            response = await super().call(name, args)
            resource = response.get("resource", {})
            if resource.get("error") or resource.get("contract", {}).get("source_status", "healthy") != "healthy":
                self.unhealthy_source_keys.add(args["source_key"])
                self.numeric_results = [item.model_dump(mode="json") for item in evaluate_numeric_conditions(self.card, [])]
                self.analysis_digest = digest([])
                self.numeric_origin = "code_helper"
            else:
                self.unhealthy_source_keys.discard(args["source_key"])
                self._record_numeric(list(self.inspected_analyses.values()))
            response["numeric_conditions"] = copy.deepcopy(self.numeric_results)
            response["analysis_input_digest"] = self.analysis_digest
            return response
        if name == "evaluate_numeric_conditions":
            return {"results": copy.deepcopy(self.numeric_results), "analysis_input_digest": self.analysis_digest}
        if name == "evaluate_workflow":
            # Native evaluation already computes full validated reports. Do
            # not force a redundant preflight fetch in the treatment arm.
            response = await super().call(name, args)
            if self.native is not None:
                full_analyses = self.native.get("result", {}).get("analyses", [])
                self.inspected_analyses = {
                    (item["source_key"], item["comparison_key"]): copy.deepcopy(item)
                    for item in full_analyses
                }
                self.inspected_period = self.adapter.clock
                # Preserve unknown checks even when no analysis is available.
                # Production report checks, not a scorer projection, are final.
                self.analysis_digest = digest(full_analyses)
                self.numeric_results = copy.deepcopy(
                    self.native.get("report", {}).get("numeric_conditions", [])
                )
                self.numeric_origin = "production_report"
                response["numeric_conditions"] = copy.deepcopy(self.numeric_results)
            return response
        if name == "submit_report":
            numeric = copy.deepcopy(self.numeric_results)
            analysis_digest = self.analysis_digest
            cache_hits = self.adapter.cache_hits
            response = await super().call(name, args)
            if self.runs:
                self.runs[-1]["numeric_conditions"] = numeric
                self.runs[-1]["analysis_input_digest"] = analysis_digest
                self.runs[-1]["numeric_origin"] = getattr(self, "numeric_origin", "code_helper")
                self.runs[-1]["cache_hits"] = cache_hits
                self.runs[-1]["physical_reads"] = self.runs[-1]["source_reads"]
            # BusinessSession advances and resets the adapter/analysis state;
            # these per-period projections must reset with it too.
            self.numeric_results = []
            self.analysis_digest = None
            self.unhealthy_source_keys.clear()
            self.numeric_origin = "code_helper"
            return response
        return await super().call(name, args)


def score(submission, oracle, numeric_conditions=None, *, numeric_required=True):
    """Strict outcome/analysis score plus optional independent numeric labels."""
    result = first_report_score(submission, _first_report_oracle(oracle))
    numeric = (_independent_numeric_score(numeric_conditions, oracle) if numeric_required else
               {"passed": True, "numeric_passed": None, "errors": []})
    errors = sorted(set([*result.get("errors", []), *numeric["errors"]]))
    result["errors"] = errors
    result["passed"] = not errors
    result["numeric_passed"] = numeric["numeric_passed"]
    return result


def _fallback_card(company: dict[str, Any]) -> InsightCard | None:
    for key in ("owner_context_card", "fallback_card"):
        value = company.get(key)
        if value:
            return InsightCard.model_validate(value)
    return None


def _brief_metadata_card(company: dict[str, Any]) -> InsightCard:
    """Baseline-only context container after onboarding failure.

    This is not an approved SignalWeave card: it copies only the owner's
    brief/policy, exact source directory and no numeric checks or routes.
    """
    return InsightCard(
        id=f"baseline-context-{company['id']}",
        title=company.get("company", company["id"]) + " owner review",
        what_to_watch=company["brief"],
        why_watch="Use the supplied owner policy for a direct baseline review.",
        decision_guidance=company["owner_policy"],
        sources=[SourceRef.model_validate(item) for item in company["sources"]],
        delivery_methods=[],
    )


def _assert_approved_runtime_card(card: InsightCard) -> None:
    """Fail closed unless a recurring treatment card carries its stored plan."""
    if card.status != InsightCardStatus.APPROVED:
        raise ValueError("recurring treatment card is not approved")
    plan = card.compiled_plan
    if plan is None:
        raise ValueError("recurring treatment card has no stored compiled plan")
    if plan.card_id != card.id:
        raise ValueError("stored compiled plan card_id does not match treatment card")
    if plan.card_version != card.version:
        raise ValueError("stored compiled plan card_version does not match treatment card")
    source_keys = [source.key for source in card.sources]
    if not set(plan.selected_source_keys).issubset(set(source_keys)):
        raise ValueError("stored compiled plan selects a source outside the treatment card")


def _approved_card_from_store(runtime: Runtime, approval: dict[str, Any], card_id: str) -> InsightCard:
    """Restore the full approved card while rejecting an unexpected MCP payload."""
    response_card = approval.get("card")
    if not isinstance(response_card, dict):
        raise ValueError("approval response did not contain a card payload")
    sanitized_fields = {
        "compiled_plan", "onboarding_review", "onboarding_review_history", "onboarding_corrections",
    }
    if sanitized_fields & response_card.keys():
        raise ValueError("approval response card was not sanitized")

    stored = runtime.card_store.get_card(card_id)
    _assert_approved_runtime_card(stored)
    stored_source_keys = [source.key for source in stored.sources]
    response_source_keys = [source.get("key") for source in response_card.get("sources", [])]
    if (
        response_card.get("id") != stored.id
        or response_card.get("version") != stored.version
        or response_card.get("status") != stored.status.value
        or response_source_keys != stored_source_keys
    ):
        raise ValueError("approval response identity disagrees with the stored approved card")
    return stored


def _select_arm_card(setup_result: dict[str, Any], company: dict[str, Any], *, treatment: bool) -> tuple[InsightCard | None, str]:
    """Keep treatment approval-gated without zeroing an independent baseline."""
    approved = InsightCard.model_validate(setup_result["card"]) if setup_result.get("card") else None
    if treatment:
        return approved, "authored_approved" if approved else "unauthored"
    fallback = _fallback_card(company)
    draft = InsightCard.model_validate(setup_result["draft_card"]) if setup_result.get("draft_card") else None
    if approved:
        return approved, "authored_approved"
    if fallback:
        return fallback, "owner_context_fallback"
    if draft:
        return draft, "returned_draft_unapproved"
    return _brief_metadata_card(company), "brief_metadata_only"


def _usage(audit: Audit) -> dict[str, Any]:
    output: dict[str, Any] = {"setup": {}, "recurring": {}}
    unknown: list[dict[str, Any]] = []
    requests: dict[tuple[str, str], int] = {}
    for event in audit.events:
        episode = event.get("episode", "")
        phase = "setup" if episode.endswith(":setup") else "recurring"
        provider = event.get("provider")
        if event.get("kind") == "api.request" and provider in {"openai", "jev"}:
            requests[(episode, provider)] = requests.get((episode, provider), 0) + 1
        if event.get("kind") == "api.error" and provider in {"openai", "jev"}:
            unknown.append({"episode": episode, "provider": provider, "reason": "api_error_usage_unknown"})
        if event.get("kind") == "api.response" and provider in {"openai", "jev"}:
            usage = event.get("usage")
            if not isinstance(usage, dict):
                unknown.append({"episode": episode, "provider": provider, "reason": "missing_usage"})
                continue
            target = output[phase].setdefault(episode, {}).setdefault(provider, {
                "attempts": 0, "input_tokens": 0, "output_tokens": 0,
                "cached_input_tokens": 0, "cached_input_tokens_provided": False,
            })
            target["attempts"] += 1
            for field in ("input_tokens", "output_tokens"):
                value = usage.get(field)
                if value is None or not isinstance(value, int) or value < 0:
                    unknown.append({"episode": episode, "provider": provider, "reason": f"unknown_{field}"})
                else:
                    target[field] += value
            cached = usage.get("cached_input_tokens")
            if cached is not None:
                if not isinstance(cached, int) or cached < 0:
                    unknown.append({"episode": episode, "provider": provider, "reason": "invalid_cached_input_tokens"})
                else:
                    target["cached_input_tokens"] += cached
                    target["cached_input_tokens_provided"] = True
    for (episode, provider), count in requests.items():
        response_count = sum(
            event.get("kind") == "api.response" and event.get("episode") == episode and event.get("provider") == provider
            for event in audit.events
        )
        if response_count < count:
            unknown.append({"episode": episode, "provider": provider, "reason": "request_without_usage_response"})
    return {"by_episode": output, "unknown_usage": unknown, "cost_status": "unknown" if unknown else "complete"}


def _paired(rows: list[dict[str, Any]], companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {(row["company"], row["arm"], run["period"]): run for row in rows for run in row.get("runs", [])}
    result = []
    for company in companies:
        _, holdout = _period_groups(company)
        for period in holdout:
            identity = (company["id"], period["id"])
            baseline = indexed.get((identity[0], "baseline", identity[1]))
            treatment = indexed.get((identity[0], "signalweave", identity[1]))
            result.append({"company": identity[0], "period": identity[1],
                           "baseline": (baseline or {}).get("score"),
                           "signalweave": (treatment or {}).get("score"),
                           "numeric_provenance": {"baseline": (baseline or {}).get("numeric_conditions", []),
                                                   "signalweave": (treatment or {}).get("numeric_conditions", [])},
                           "route_score": {"baseline": (baseline or {}).get("score", {}).get("errors", []),
                                           "signalweave": (treatment or {}).get("score", {}).get("errors", [])},
                           "same_catalog": bool(baseline and treatment and baseline.get("catalog_digest") == treatment.get("catalog_digest")),
                           "same_analysis": bool(baseline and treatment and baseline.get("analysis_input_digest") == treatment.get("analysis_input_digest"))})
    return result


def masked_review_packet(rows: list[dict[str, Any]], companies: list[dict[str, Any]]):
    packet, key = business_review_packet(rows, companies)
    for case in packet["cases"]:
        case.pop("expected", None)
        case.pop("oracle", None)
    packet["scope"] = "Arm-masked internal prose review; private labels are retained only by the scorer."
    return packet, key


def summarize(rows, companies):
    """Preserve the common business metrics but use numeric-aware strict grades."""
    normalized = copy.deepcopy(companies)
    for company in normalized:
        for period in company["periods"]:
            period["oracle"] = _first_report_oracle(period["oracle"])
    result = business_summarize(rows, normalized)
    intended = {(company["id"], period["id"]) for company in companies for period in company["periods"]}
    for arm in ("baseline", "signalweave"):
        indexed = {(row["company"], run["period"]): run
                   for row in rows if row["arm"] == arm for run in row.get("runs", [])}
        result[arm]["strict_passed"] = sum(
            indexed.get(identity, {}).get("score", {}).get("passed") is True
            for identity in intended
        )
        result[arm]["review_required_proxy"] = len(intended) - result[arm]["strict_passed"]
    return result


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _manifest(companies: list[dict[str, Any]], *, live: bool) -> dict[str, Any]:
    public = [_public_company(c) for c in companies]
    return {
        "scope": "prospective full-runtime recurring comparison; not certification",
        "protocol_version": 1,
        "live": live,
        "hypotheses": {
            "primary": "full-runtime recurring correctness and report quality under the same approved policy and evidence",
            "benefit": "measured recurring runtime/resource benefit is an outcome, not a requirement for correctness",
            "interpretation": "No benefit claim is made if the structured or independent prose gate fails.",
        },
        "acceptance": {
            "correctness": "All intended outcomes, routes, numeric/provenance checks and exact replays; no unsupported delivered numeric or causal claims.",
            "comparative_benefit": "No correctness loss AND either >=20% lower whole-report recurring latency OR >=3 masked quality wins with zero losses.",
            "limits": "A single small synthetic trial does not establish universal accuracy, customer adoption, dollar savings or human labor savings.",
        },
        "case_hash": digest(public),
        "freeze": source_freeze(),
        "companies": public,
        "private_oracles": "parent-side scorer only; never in agent prompts, MCP tool results, or review-input",
        "setup": {"periods_per_company": SETUP_PERIODS, "draft_cap": MAX_DRAFTS, "preview_each_period": True,
                  "finish_then_synthetic_owner_review_approve": True, "approval_is_certification": False},
        "recurring": {"holdout_periods_per_company": HOLDOUT_PERIODS,
                      "arms": ["baseline", "signalweave"], "same_card_catalog_analyses": True,
                      "period_local_snapshot_cache": True, "freshness_reset_each_period": True,
                      "final_written_report_including_quiet": True, "serial_counterbalance": True},
        "budgets": {"jev_attempts": MAX_JEV_ATTEMPTS, "luna_author_episodes": MAX_LUNA_AUTHOR_EPISODES,
                    "luna_report_episodes": MAX_LUNA_REPORT_EPISODES, "luna_total_episodes": MAX_LUNA_EPISODES,
                    "retries": 0, "episode_timeout_seconds": EPISODE_TIMEOUT_SECONDS},
        "audit": {"setup_vs_recurring_usage": True, "physical_reads_vs_cache_hits": True,
                   "paired_outcomes": True, "numeric_provenance": True, "route_score": True,
                   "masked_review_packet": True, "exact_replay_required": True,
                   "unknown_token_cost_is_failure": True, "retain_budget_close_failures": True},
    }


def _evaluation_companies(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize private labels for the existing business summary/reviewer."""
    result = []
    for company in companies:
        _, holdout = _period_groups(company)
        item = copy.deepcopy(company)
        item["periods"] = holdout
        item.pop("setup_periods", None)
        item.pop("holdout_periods", None)
        result.append(item)
    return result


async def _author_company(company, audit, judger, output):
    # Cases provide this view so no future period is even resident in the
    # author Session, not merely omitted from a prompt.
    from evaluations.recurring_runtime_cases import onboarding_company
    public = onboarding_company(company)
    setup = public["periods"]
    adapter = CachedPeriodAdapter(public["descriptors"], audit, public["sources"])
    adapter.set_period(setup[0])
    registry = SourceRegistry([adapter])
    database = output / f"{company['id']}-setup.db"
    runtime = Runtime(card_store=SQLiteInsightCardStore(database), sources=registry,
                      engine=InsightEngine(judger, registry, clock=lambda a=adapter: a.clock),
                      decision_receipts=SQLiteDecisionReceiptStore(database),
                      principal=operator_principal(public))
    session = SetupSession(company=public, setup_periods=setup, adapter=adapter,
                           server=create_mcp(runtime), audit=audit)
    instructions = (
        "You are authoring one recurring analytical card for a synthetic company. "
        "Read catalog and current_setup_period, inspect the relevant sources, ask no invented questions, "
        "use the supplied business brief and policy, and make at most two native drafts. "
        "Preview the current card in both setup periods, use advance_setup between them, then call "
        "finish_setup. This freezes a draft for explicit synthetic-owner production review and approval; "
        "it is not certification. Do not ask for or infer future holdout data. " + CARD_AUTHORING_GUIDANCE
    )
    episode = await codex_episode(
        session, key=None, effort="low", budget=RequestBudget(0), audit=audit,
        max_turns=40, max_tool_calls=38, max_output_tokens=7000,
        timeout_seconds=EPISODE_TIMEOUT_SECONDS, instructions_override=instructions,
        prompt_override={"brief": public.get("brief", ""), "owner_policy": public.get("owner_policy", ""),
                         "company": {"id": public["id"], "brief": public.get("brief", ""),
                                    "owner_policy": public.get("owner_policy", ""),
                                    "sources": public["sources"], "destinations": public["destinations"]},
                         "prompt_policy": "No private oracle or future holdout label is available."})
    card = None
    draft_card = None
    approval = {"status": "not_attempted"}
    numeric_audit = {"passed": False, "errors": ["no_draft"]}
    if session.card_id:
        draft_card = runtime.card_store.get_card(session.card_id)
        numeric_audit = audit_numeric_policy(draft_card, company)
    if session.setup_complete and session.card_id:
        if not numeric_audit["passed"]:
            approval = {"status": "failed", "error": "numeric_policy_audit_failed", "details": numeric_audit}
        else:
            try:
                review = await first_report_dispatch(session.server, "review_insight_card", {"card_id": session.card_id})
                review_data = review.get("review", {})
                approval_args = {"card_id": session.card_id, "actor": "synthetic-owner",
                                 "source_selection_fingerprint": review_data.get("source_selection_fingerprint"),
                                 "source_selection_reason": "Synthetic owner reviewed the selected definitions and sources for this recurring card."}
                approval = await first_report_dispatch(session.server, "approve_insight_card", approval_args)
                if approval.get("status") in {"approved", "replayed"}:
                    # The MCP approval response is deliberately compact and omits
                    # compiled_plan.  Rehydrate from the durable store so each arm
                    # receives the approved execution plan rather than recompiling
                    # on every fresh period snapshot.
                    card = _approved_card_from_store(runtime, approval, session.card_id)
            except Exception as error:  # retain the authored attempt; approval is a separate gate
                approval = {"status": "failed", "error": type(error).__name__}
    return {"company": company["id"], "episode": episode, "setup_complete": session.setup_complete,
            "drafts": session.drafts, "card": card.model_dump(mode="json") if card else None,
            "draft_card": draft_card.model_dump(mode="json") if draft_card else None,
            "approval": approval, "numeric_policy_audit": numeric_audit,
            "previewed_periods": sorted(session.previewed_periods)}


async def run_trial(output: Path, *, live: bool = False, key_file: str | None = None,
                    company_limit: int = 3, case_set: str = "initial"):
    if case_set == "initial":
        from evaluations.recurring_runtime_cases import cases
    elif case_set == "transfer":
        from evaluations.recurring_runtime_transfer_cases import cases
    else:
        raise ValueError("Unknown frozen case set")

    all_companies = cases()
    if len(all_companies) != 3:
        raise ValueError("Recurring runtime requires exactly three companies")
    companies = all_companies[:company_limit]
    manifest = _manifest(companies, live=live)
    manifest["case_set"] = case_set
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "manifest.json", manifest)
    if not live:
        return {"status": "dry_run", "paid_calls": 0, "manifest": manifest}

    # This is the only path that can create live clients; callers must opt in.
    from signalweave.typesafe_adapter import load_api_key
    key = load_api_key(key_file)
    audit = Audit(path=output / "events.jsonl", secrets=(key,))
    jev_budget = RequestBudget(MAX_JEV_ATTEMPTS)
    judger = TrialJev(key, jev_budget, audit)
    luna_episodes = 0
    setup_results = []
    for company in companies:
        audit.episode = company["id"] + ":setup"
        luna_episodes += 1
        try:
            setup_results.append(await _author_company(company, audit, judger, output))
        except Exception as error:
            # Preserve a bounded failure row and continue to the other
            # companies; an unexpected author error must not erase the study.
            setup_results.append({"company": company["id"],
                                  "episode": {"status": "failed", "error": type(error).__name__, "seconds": 0, "tool_calls": 0, "foreign_tools": []},
                                  "setup_complete": False, "drafts": 0, "card": None, "draft_card": None,
                                  "approval": {"status": "failed", "error": type(error).__name__},
                                  "previewed_periods": []})
        _write_json(output / "progress.json", {"setup": setup_results, "results": []})
    # No recurring session starts before all three author/approval attempts finish.
    _write_json(output / "frozen-cards.json", {item["company"]: item for item in setup_results})

    rows = []
    for index, company in enumerate(companies):
        _, holdout = _period_groups(company)
        setup_result = next(item for item in setup_results if item["company"] == company["id"])
        order = (False, True) if index % 2 == 0 else (True, False)
        for treatment in order:
            arm = "signalweave" if treatment else "baseline"
            audit.episode = f"{company['id']}:{arm}"
            public = _public_company(company, recurring_only=True)
            card, card_source = _select_arm_card(setup_result, company, treatment=treatment)
            if card is None:
                rows.append({"company": company["id"], "arm": arm,
                             "episode": {"status": "failed", "error": "no_card_for_arm", "seconds": 0, "tool_calls": 0, "foreign_tools": []},
                             "runs": [], "card_source": card_source,
                             "intended_holdouts": [p["id"] for p in holdout]})
                _write_json(output / "progress.json", {"setup": setup_results, "results": rows})
                continue
            if treatment:
                try:
                    _assert_approved_runtime_card(card)
                except Exception as error:  # retain a fail-closed pre-arm failure
                    rows.append({"company": company["id"], "arm": arm,
                                 "episode": {"status": "failed", "error": f"treatment_card_invariant:{type(error).__name__}",
                                              "seconds": 0, "tool_calls": 0, "foreign_tools": []},
                                 "runs": [], "card_source": card_source,
                                 "intended_holdouts": [p["id"] for p in holdout]})
                    _write_json(output / "progress.json", {"setup": setup_results, "results": rows})
                    continue
            luna_episodes += 1
            session = None
            try:
                adapter = CachedPeriodAdapter(public["descriptors"], audit, public["sources"])
                adapter.set_period(holdout[0])
                registry = SourceRegistry([adapter])
                database = output / f"{company['id']}-{arm}.db"
                store = SQLiteInsightCardStore(database)
                store.save_card(card)
                runtime = Runtime(card_store=store, sources=registry,
                                  engine=InsightEngine(judger, registry, clock=lambda a=adapter: a.clock),
                                  decision_receipts=SQLiteDecisionReceiptStore(database),
                                  principal=operator_principal(public))
                session = RecurringSession(company=public, adapter=adapter, server=create_mcp(runtime),
                                           audit=audit, treatment=treatment, card_id=card.id, card=card)
                extra = ("Use evaluate_workflow once per period before composing the final written report. "
                         "Retain its authoritative outcome, recipients and analyses. inspect_source returns "
                         "the deterministic numeric-condition results when needed. " if treatment else
                         "Use inspect_source with the saved policy; its result includes the deterministic "
                         "numeric-condition checks. The optional helper is not required. ")
                episode = await codex_episode(
                    session, key=None, effort="low", budget=RequestBudget(0), audit=audit,
                    max_turns=35, max_tool_calls=34, max_output_tokens=7000,
                    timeout_seconds=EPISODE_TIMEOUT_SECONDS,
                    instructions_override=BUSINESS_INSTRUCTIONS + " " + extra,
                    prompt_override={"brief": public.get("brief", ""), "owner_policy": public.get("owner_policy", ""),
                                     "saved_card": card.execution_payload(),
                                     "period_count": HOLDOUT_PERIODS,
                                     "private_oracle_policy": "No oracle, expected route, or expected numeric label is available."})
                for run in session.runs:
                    period = next(p for p in holdout if p["id"] == run["period"])
                    run["score"] = score(
                        run.get("submission"), period["oracle"], run.get("numeric_conditions"),
                        numeric_required=bool(card.numeric_conditions),
                    )
                    run["catalog_digest"] = session.catalog_digest
                    run["card_id"] = card.id
                    run["card_digest"] = digest(card.execution_payload())
                rows.append({"company": company["id"], "arm": arm, "episode": episode, "runs": session.runs,
                             "simulated_deliveries": session.deliveries, "card_source": card_source})
            except Exception as error:
                partial_runs = session.runs if session is not None else []
                for run in partial_runs:
                    period = next((p for p in holdout if p["id"] == run["period"]), None)
                    if period is not None:
                        run["score"] = score(
                            run.get("submission"), period["oracle"], run.get("numeric_conditions"),
                            numeric_required=bool(card.numeric_conditions),
                        )
                rows.append({"company": company["id"], "arm": arm,
                             "episode": {"status": "failed", "error": type(error).__name__, "seconds": 0,
                                          "tool_calls": 0, "foreign_tools": []},
                             "runs": partial_runs,
                             "simulated_deliveries": session.deliveries if session is not None else [],
                             "card_source": card_source,
                             "intended_holdouts": [p["id"] for p in holdout]})
            _write_json(output / "progress.json", {"setup": setup_results, "results": rows})

    if luna_episodes > MAX_LUNA_EPISODES:
        raise RuntimeError("Luna episode budget exceeded")
    private_companies = _evaluation_companies(companies)
    summary = summarize(rows, private_companies)
    # Pairing needs only the period split; retain the original six-period
    # case shape here.  The summary/reviewer receive the holdout-normalized
    # private view below.
    paired = _paired(rows, companies)
    usage = _usage(audit)
    no_foreign_tools = all(not item.get("episode", {}).get("foreign_tools", []) for item in [*setup_results, *rows])
    all_scores = all(
        summary[arm]["strict_passed"] == summary[arm]["intended_periods"]
        and summary[arm]["failed_episodes"] == 0
        for arm in ("baseline", "signalweave")
    )
    all_approved = len(companies) == 3 and all(
        item.get("setup_complete") and item.get("approval", {}).get("status") in {"approved", "replayed"}
        for item in setup_results
    )
    all_replays = all(
        run.get("replay_exact_no_calls") is True
        for row in rows if row["arm"] == "signalweave" for run in row.get("runs", [])
    ) and all(row.get("runs") for row in rows if row["arm"] == "signalweave")
    paired_context = all(item["same_catalog"] and item["same_analysis"] for item in paired)
    protocol_checks = {
        "all_intended_holdout_scores": all_scores,
        "all_three_cards_approved": all_approved,
        "no_foreign_tools": no_foreign_tools,
        "exact_replay_all_treatment_periods": all_replays,
        "paired_catalog_and_analysis": paired_context,
        "jev_within_cap": jev_budget.used <= MAX_JEV_ATTEMPTS,
        "luna_within_cap": luna_episodes <= MAX_LUNA_EPISODES,
        "usage_complete": not usage["unknown_usage"],
    }
    structured_gate = all(protocol_checks.values())
    report = {"results": rows, "setup": setup_results,
              "summary": summary, "paired_outcomes": paired,
              "usage": usage, "protocol_checks": protocol_checks,
              "jev_attempts": jev_budget.used, "luna_episodes": luna_episodes,
              "all_attempts_retained": True, "exact_replay_required": True,
              "structured_gate_passed": structured_gate,
              "overall_status": "pending_prose_review" if structured_gate else "failed_structured_gate"}
    _write_json(output / "report.json", report)
    packet, review_key = masked_review_packet(rows, private_companies)
    _write_json(output / "review-input.json", packet)
    _write_json(output / "review-key.json", review_key)
    scoring_labels = {}
    for company in private_companies:
        scoring_labels[company["id"]] = {
            period["id"]: period["oracle"] for period in company["periods"]
        }
    _write_json(output / "scoring-labels.json", scoring_labels)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--jev-key-file")
    parser.add_argument("--company-limit", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--case-set", choices=("initial", "transfer"), default="initial")
    args = parser.parse_args()
    result = asyncio.run(run_trial(args.output, live=args.live, key_file=args.jev_key_file,
                                   company_limit=args.company_limit, case_set=args.case_set))
    print(json.dumps({"output": str(args.output), "status": result.get("status"), "jev_attempts": result.get("jev_attempts", 0)}))


if __name__ == "__main__":
    main()

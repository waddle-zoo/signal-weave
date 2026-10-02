"""Opt-in, bounded first-report experiment; fixtures and labels never enter src.

The optional Codex agent authors context once. Paired recurring arms then receive
the same authored policy, catalog, measurements and deterministic analysis tool.
This measures runtime after shared onboarding, not independent onboarding superiority.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.bootstrap_empirical_trial import TrialJev
from evaluations.codex_trial_transport import codex_episode
from evaluations.onboarding_acceptance_trial import source_freeze
from examples.investigation_agent.onboarding import DraftIntent, draft_arguments
from signalweave.diagnostics import analyze_comparison
from signalweave.engine import InsightEngine
from signalweave.mcp_server import CARD_AUTHORING_GUIDANCE, create_mcp
from signalweave.models import (
    InsightCard,
    Outcome,
    PrincipalContext,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteDecisionReceiptStore, SQLiteInsightCardStore
from signalweave.typesafe_adapter import load_api_key


class AnalysisRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: str
    comparison_key: str


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["complete", "partial", "blocked"]
    outcome: Outcome
    recipients: list[str]
    analysis_refs: list[AnalysisRef] = Field(default_factory=list)
    narrative: str


async def dispatch(server, name, arguments):
    response = await server.call_tool(name, arguments)
    return response[1] if isinstance(response, tuple) else json.loads(
        next(item.text for item in response if getattr(item, "type", None) == "text")
    )


class PeriodAdapter:
    name = "company_mcp"

    def __init__(self, descriptors, audit, sources):
        self.descriptors = [ResourceDescriptor.model_validate(item) for item in descriptors]
        self.allowed_parameters = {item["resource"]: item.get("parameters", {}) for item in sources}
        self.audit = audit
        self.snapshots = {}
        self.inspections = 0

    def set_period(self, period):
        self.clock = datetime.fromisoformat(period["as_of"])
        self.snapshots = {item["resource"]: copy.deepcopy(item) for item in period["resources"]}
        self.inspections = 0

    async def list_resources(self):
        return [item.model_copy(deep=True) for item in self.descriptors]

    async def inspect(self, source):
        if (source.adapter != self.name or source.resource not in self.snapshots
                or source.parameters != self.allowed_parameters.get(source.resource)):
            raise ValueError("Source is not available in this period")
        self.inspections += 1
        snapshot = ResourceSnapshot.model_validate(self.snapshots[source.resource])
        snapshot.source_key = source.key
        for observation in snapshot.observations:
            observation.source_key = source.key
        for evidence in snapshot.evidence:
            evidence.source_key = source.key
        self.audit.emit("source.read", source=source.model_dump(mode="json"))
        return snapshot


def operator_principal(company):
    """Test operator identity matches the catalog's declared deployment tenant."""
    tenants = {d["contract"]["tenant_id"] for d in company["descriptors"]}
    if len(tenants) != 1:
        raise ValueError("Trial requires one explicitly configured deployment tenant")
    return PrincipalContext(principal_id=company["id"] + "-owner", tenant_id=next(iter(tenants)))


def tool(name, description, properties=None, required=None, schema=None):
    return {"name": name, "description": description, "parameters": schema or {
        "type": "object", "properties": properties or {}, "required": required or [],
        "additionalProperties": False,
    }}


class Session:
    def __init__(self, *, company, adapter, server, phase, audit):
        self.company, self.adapter, self.server = company, adapter, server
        self.phase, self.audit = phase, audit
        self.submission = None
        self.setup_complete = False
        self.card_id = None
        self.preview = None
        self.preview_card = None
        self.drafts = 0
        self.notes = ""
        self.inspected_analyses = {}
        self.inspected_period = adapter.clock
        self.directory = {source["key"]: source for source in company["sources"]}

    async def specs(self):
        specs = [
            tool("catalog", "Read approved source definitions and exact source selectors."),
            tool("inspect_source", "Read current source and validated deterministic comparisons. Same tool in both arms.",
                 {"source_key": {"type": "string"}}, ["source_key"]),
        ]
        if self.phase == "onboarding":
            specs += [
                tool("draft_from_intent", "Persist a native draft from business intent. At most two drafts. Technical defaults are fixed by the operator.", schema=DraftIntent.model_json_schema()),
                tool("preview_investigation_report", "Execute real sources and Jev through production MCP; returns first report without approval or delivery.",
                     {"card_id": {"type": "string"}}, ["card_id"]),
                tool("finish_setup", "Freeze the previewed draft and reusable notes. This is NOT human authorization or workflow certification.",
                     {"card_id": {"type": "string"}, "notes": {"type": "string"}}, ["card_id", "notes"]),
            ]
        else:
            specs.append(tool("submit_report", "Submit the final report. Select analysis_refs from current inspect_source results; code attaches their exact calculations. No copying tables or invented causal mechanism.", schema=Submission.model_json_schema()))
        return specs

    async def call(self, name, args):
        if name == "catalog":
            return {"descriptors": [d.model_dump(mode="json") for d in self.adapter.descriptors],
                    "sources": list(self.directory.values()), "destinations": self.company["destinations"]}
        if name == "inspect_source":
            if self.inspected_period != self.adapter.clock:
                self.inspected_analyses.clear()
                self.inspected_period = self.adapter.clock
            source = SourceRef.model_validate(self.directory[args["source_key"]])
            snapshot = await self.adapter.inspect(source)
            analyses = [analyze_comparison(source.key, item).model_dump(mode="json")
                        for item in snapshot.analytical_comparisons]
            identities = [(a["source_key"], a["comparison_key"]) for a in analyses]
            if len(set(identities)) != len(identities):
                raise ValueError("Ambiguous analysis references in source")
            for analysis in analyses:
                identity = (analysis["source_key"], analysis["comparison_key"])
                self.inspected_analyses[identity] = copy.deepcopy(analysis)
            return {"resource": snapshot.model_dump(mode="json"), "analyses": analyses}
        if name == "draft_from_intent":
            if self.drafts >= 2:
                raise ValueError("draft budget exhausted")
            self.drafts += 1
            intent = DraftIntent.model_validate(args)
            # Directory selection remains the agent's job; no expected source is injected.
            selected = [self.directory[key] for key in intent.source_keys]
            native_args = draft_arguments(intent, selected, self.company["destinations"])
            response = await dispatch(self.server, "draft_insight_card", native_args)
            self.card_id = response["card"]["id"]
            return response
        if name == "preview_investigation_report":
            if args["card_id"] != self.card_id:
                raise ValueError("Preview the current draft")
            self.preview = await dispatch(self.server, name, args)
            self.preview_card = self.card_id
            return self.preview
        if name == "finish_setup":
            if args["card_id"] != self.card_id or self.preview_card != self.card_id:
                raise ValueError("Preview the current draft before freezing")
            self.notes = args["notes"]
            self.setup_complete = True
            return {"frozen": True, "approval_required": True}
        if name == "submit_report":
            if self.inspected_period != self.adapter.clock:
                raise ValueError("Inspect current-period analyses before submitting")
            submission = Submission.model_validate(args).model_dump(mode="json")
            refs = submission.pop("analysis_refs")
            identities = [(ref["source_key"], ref["comparison_key"]) for ref in refs]
            if len(set(identities)) != len(identities):
                raise ValueError("Duplicate analysis reference")
            if any(identity not in self.inspected_analyses for identity in identities):
                raise ValueError("Inspect every referenced analysis in this episode")
            submission["analyses"] = [copy.deepcopy(self.inspected_analyses[key]) for key in identities]
            self.submission = submission
            return {"submitted": True}
        raise ValueError("Unknown tool")


def score(submission, oracle):
    try:
        return _score(submission, oracle)
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"passed": False, "errors": ["malformed_analysis"]}


def _score(submission, oracle):
    """Independent oracle projection. Does not invoke production diagnostics or Jev."""
    if submission is None:
        return {"passed": False, "errors": ["missing_report"]}
    errors = []
    for field in ("status", "outcome"):
        if submission[field] != oracle[field]:
            errors.append(field)
    if set(submission["recipients"]) != set(oracle["recipients"]):
        errors.append("recipients")
    valid = [a for a in submission["analyses"] if a.get("status") == "complete"]
    expected = oracle["analyses"]
    if len(valid) != len(expected):
        errors.append("analysis_coverage")
    identities = [(a.get("source_key"), a.get("comparison_key")) for a in valid]
    if len(identities) != len(set(identities)):
        errors.append("duplicate_analysis")
    for truth in expected:
        actual = next((a for a in valid if a.get("source_key") == truth["source_key"]
                       and a.get("comparison_key") == truth["comparison_key"]), None)
        if actual is None:
            errors.append("missing_analysis")
            continue
        for field in ("metric", "unit", "dimension"):
            if actual.get(field) != truth[field]:
                errors.append(field)
        comparison = actual.get("comparison", {})
        for field in ("definition", "population", "baseline_start", "baseline_end", "current_start", "current_end"):
            got, want = comparison.get(field), truth[field]
            if field.endswith(("_start", "_end")):
                try:
                    got, want = datetime.fromisoformat(got), datetime.fromisoformat(want)
                except (TypeError, ValueError):
                    pass
            if got != want:
                errors.append(field)
        for field in ("baseline", "current", "delta", "within_effect", "mix_effect"):
            want, got = truth.get(field), actual.get(field)
            if want is None:
                if got is not None:
                    errors.append(field)
            elif (isinstance(got, bool) or not isinstance(got, (int, float))
                  or not math.isfinite(got) or not math.isclose(got, want, rel_tol=1e-10, abs_tol=1e-12)):
                errors.append(field)
        contributions = {row["segment"]: row["contribution"] for row in actual.get("contributions", [])}
        if len(contributions) != len(actual.get("contributions", [])) or set(contributions) != set(truth["contributions"]):
            errors.append("contribution_coverage")
        for segment, value in truth["contributions"].items():
            got = contributions.get(segment)
            if (isinstance(got, bool) or not isinstance(got, (int, float)) or not math.isfinite(got)
                    or not math.isclose(got, value, rel_tol=1e-10, abs_tol=1e-12)):
                errors.append("contribution_value")
        if not actual.get("query_refs") or set(actual["query_refs"]) != set(truth["query_refs"]):
            errors.append("provenance")
    return {"passed": not errors, "errors": sorted(set(errors)),
            "narrative_review": "requires_independent_review"}


def native_submission(native, destinations):
    """Grade the emitted report's claims, not a hidden engine intermediate."""
    report = native["report"]
    provenance = {(p["source_key"], p["comparison_key"]): p for p in report["provenance"]}
    analyses = []
    for claim in report["numeric_claims"]:
        source = provenance[(claim["source_key"], claim["comparison_key"])]
        analyses.append({**claim, "status": "complete", "query_refs": source["query_refs"],
                         "comparison": {"definition": source["definition"], "population": source["population"],
                                        "baseline_start": source["baseline_period"]["start"],
                                        "baseline_end": source["baseline_period"]["end"],
                                        "current_start": source["current_period"]["start"],
                                        "current_end": source["current_period"]["end"]}})
    destination_keys = {d["destination"]: d["key"] for d in destinations}
    return {"status": report["status"], "outcome": native["result"]["outcome"],
            "recipients": [destination_keys.get(r["destination"], "unknown_destination")
                           for r in native["result"]["delivery_methods"]],
            "analyses": analyses, "narrative": native["report_markdown"]}


async def run_trial(output: Path, *, live=False, key_file=None, company_limit=4, resume_from=None):
    from evaluations.first_report_cases import cases

    output.mkdir(parents=True, exist_ok=False)
    companies = cases()[:company_limit]
    previous = json.loads((resume_from / "report.json").read_text()) if resume_from else None
    prior_attempts = previous.get("cumulative_jev_attempts", previous["jev_attempts"]) if previous else 0
    prior_rows = {row["company"]: row for row in previous["results"]} if previous else {}
    prior_manifest = json.loads((resume_from / "manifest.json").read_text()) if previous else None
    prior_companies = {c["id"]: c for c in prior_manifest["companies"]} if prior_manifest else {}
    prior_luna = previous.get("cumulative_luna_episodes", 0) if previous else 0
    if previous and not prior_luna:
        prior_luna = sum(json.loads(line).get("kind") == "api.request"
                         and json.loads(line).get("provider") == "openai"
                         for line in (resume_from / "events.jsonl").read_text().splitlines())
    remaining = 48 - prior_attempts
    if remaining <= 0:
        raise ValueError("Combined 48-attempt budget exhausted")
    manifest = {"scope": "synthetic first-report feasibility, not enterprise certification",
                "protocol_version": 2 if resume_from else 1,
                "policy_versions": {c["id"]: "clarified-v2" if c["id"] in prior_companies
                                    and c["owner_policy"] != prior_companies[c["id"]]["owner_policy"]
                                    else "original-v1" for c in companies},
                "oracle_versions": {c["id"]: "v2-context-supported" if c["id"] in prior_companies
                                    and c != prior_companies[c["id"]] else "original-v1" for c in companies},
                "freeze": source_freeze(), "companies": companies, "live": live,
                "max_jev_attempts": remaining, "combined_jev_ceiling": 48,
                "prior_jev_attempts": prior_attempts, "max_drafts_per_company": 2,
                "prior_luna_episodes": prior_luna, "combined_luna_episode_ceiling": 16,
                "resume_from": str(resume_from) if resume_from else None,
                "previous_report_sha256": hashlib.sha256((resume_from / "report.json").read_bytes()).hexdigest() if resume_from else None,
                "period_scope": "unseen_periods_only" if resume_from else "setup_and_unseen_periods",
                "baseline": "same authored card and notes, same deterministic comparison tool"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not live:
        return {"status": "dry_run", "companies": len(companies), "paid_calls": 0}
    key = load_api_key(key_file)
    audit = Audit(path=output / "events.jsonl", secrets=(key,))
    budget = RequestBudget(remaining)
    judger = TrialJev(key, budget, audit)

    async def bounded_episode(session, **kwargs):
        used = prior_luna + sum(e["kind"] == "api.request" and e.get("provider") == "openai"
                                for e in audit.events)
        if used >= 16:
            return {"status": "failed", "error": "combined_luna_episode_budget_exhausted"}
        return await codex_episode(session, **kwargs)

    results = []
    for company in companies:
        audit.episode = company["id"] + ":onboarding"
        adapter = PeriodAdapter(company["descriptors"], audit, company["sources"])
        adapter.set_period(company["periods"][0])
        registry = SourceRegistry([adapter])
        database = output / (company["id"] + ".db")
        runtime = Runtime(card_store=SQLiteInsightCardStore(database), sources=registry,
                          engine=InsightEngine(judger, registry, clock=lambda source=adapter: source.clock),
                          decision_receipts=SQLiteDecisionReceiptStore(database),
                          principal=operator_principal(company))
        server = create_mcp(runtime)
        author = Session(company=company, adapter=adapter, server=server, phase="onboarding", audit=audit)
        instructions = ("You are onboarding a recurring analytical review. Read catalog and inspect relevant sources, "
                        "derive the reusable policy from the brief, draft a minimal card, and preview a useful first "
                        "report. Ask no invented owner questions: only supplied policy is available. Do not invent "
                        "definitions or causal explanations. A report may expose missing context. Freeze with "
                        "finish_setup only after preview. Use only supplied MCP tools; stop after finish_setup. "
                        "The operator requires fixed retrieval, no follow-up engine, normal .70 confidence, "
                        "24-hour freshness. Destinations must exactly match catalog entries. " + CARD_AUTHORING_GUIDANCE)
        previous_row = prior_rows.get(company["id"], {})
        reusable = (previous_row.get("preview_score", {}).get("passed") is True
                    and previous_row.get("card") and prior_companies.get(company["id"]) == company)
        if reusable:
            # Trusted deployment identity was missing in v1. Business policy and
            # source declarations remain byte-for-byte unchanged; no reauthoring.
            card = InsightCard.model_validate(previous_row["card"]).model_copy(update={
                "principal_id": runtime.principal.principal_id,
                "principal_tenant": runtime.principal.tenant_id,
            })
            runtime.card_store.save_card(card)
            author.card_id, author.preview, author.notes = card.id, previous_row["preview"], previous_row["notes"]
            author.setup_complete = True
            episode = {"status": "complete", "transport": "retained_authoring",
                       "original_episode": previous_row["author"], "new_luna_calls": 0}
            audit.emit("authoring.reused", original_card=previous_row["card"],
                       identity_bound_card=card.model_dump(mode="json"))
        else:
            episode = await bounded_episode(author, key=None, effort="low", budget=budget, audit=audit,
                                          max_turns=12, max_tool_calls=16, max_output_tokens=5000,
                                          timeout_seconds=180, instructions_override=instructions,
                                          prompt_override={"brief": company["brief"], "owner_policy": company["owner_policy"],
                                                           "as_of": company["periods"][0]["as_of"]})
        row = {"company": company["id"], "author": episode, "drafts": author.drafts,
               "notes": author.notes, "preview": author.preview, "runs": []}
        results.append(row)
        if not author.setup_complete or episode["status"] != "complete":
            row["error"] = "onboarding_failed"
            continue
        row["preview_score"] = score(native_submission(author.preview, company["destinations"]), company["periods"][0]["oracle"])
        if author.preview["report"]["status"] != "complete" or not row["preview_score"]["passed"]:
            row["error"] = "first_report_incomplete"
            continue
        card = runtime.card_store.get_card(author.card_id)
        row["card"] = card.model_dump(mode="json")
        # Synthetic owner authorization is explicitly recorded, never claimed as a human study.
        try:
            review = await dispatch(server, "review_insight_card", {"card_id": card.id})
            row["approval"] = await dispatch(server, "approve_insight_card", {
                "card_id": card.id, "actor": "synthetic-owner",
                "source_selection_fingerprint": review["review"]["source_selection_fingerprint"],
                "source_selection_reason": "Synthetic owner accepts only the agent-selected definitions from the supplied brief. This is authorization, not correctness certification.",
            })
        except Exception as error:
            row["approval_error"] = str(error)
            continue
        for period in company["periods"]:
            if resume_from and period["split"] != "holdout":
                continue
            adapter.set_period(period)
            audit.episode = company["id"] + ":jev:" + period["id"]
            started = time.perf_counter()
            entry = {"period": period["id"], "split": period["split"]}
            row["runs"].append(entry)
            try:
                native = await dispatch(server, "evaluate_insight_card", {
                    "card_id": card.id, "idempotency_key": period["id"],
                })
                entry["native_seconds"] = time.perf_counter() - started
                entry["native"] = native
                entry["native_score"] = score(native_submission(native, company["destinations"]), period["oracle"])
                calls = budget.used
                replay = await dispatch(server, "evaluate_insight_card", {
                    "card_id": card.id, "idempotency_key": period["id"],
                })
                entry["replay_exact"] = replay["report"] == native["report"] and budget.used == calls
            except Exception as error:
                entry["native_error"] = str(error)
            # Baseline gets the same reusable card and setup notes, but no Jev result.
            adapter.set_period(period)
            audit.episode = company["id"] + ":luna:" + period["id"]
            baseline = Session(company=company, adapter=adapter, server=server, phase="monitoring", audit=audit)
            entry["baseline_episode"] = await bounded_episode(
                baseline, key=None, effort="low", budget=RequestBudget(0), audit=audit,
                max_turns=12, max_tool_calls=10, max_output_tokens=5000, timeout_seconds=120,
                instructions_override=("Produce the recurring analytical report using only the provided MCP tools. "
                                       "Read catalog as needed and inspect current sources. inspect_source supplies "
                                       "validated deterministic analyses; select their source_key/comparison_key in analysis_refs, "
                                       "and code attaches the exact calculations without copying the tables. "
                                       "Apply the English owner policy, including the right audience. recipients are the "
                                       "exact approved destination keys, not URLs or card method aliases. status is complete, "
                                       "partial or blocked; missing required comparisons means blocked, not quiet. "
                                       "A required source marked ambiguous, stale, unknown or failed also makes the "
                                       "report blocked; valid arithmetic may still be shown with that qualification. "
                                       "Never substitute previous-period facts. Explain accounting contributors, not invented "
                                       "causes. Submit the report with submit_report and stop. No external delivery."),
                prompt_override={"brief": company["brief"], "owner_policy": company["owner_policy"],
                                 "saved_card": row["card"], "saved_notes": author.notes,
                                 "as_of": period["as_of"]},
            )
            entry["baseline"] = baseline.submission
            entry["baseline_score"] = score(baseline.submission, period["oracle"])
            (output / "progress.json").write_text(json.dumps(results, indent=2) + "\n")
    runs = [run for company in results for run in company["runs"]]
    usage = {}
    for event in audit.events:
        if event["kind"] == "api.response" and isinstance(event.get("usage"), dict):
            target = usage.setdefault(event["provider"], {"input_tokens": 0, "output_tokens": 0})
            for field in target:
                target[field] += event["usage"].get(field, 0) or 0
    report = {"results": results, "jev_attempts": budget.used,
              "cumulative_jev_attempts": prior_attempts + budget.used,
              "cumulative_luna_episodes": prior_luna + sum(e["kind"] == "api.request" and e.get("provider") == "openai" for e in audit.events),
              "summary": {"intended_companies": len(companies),
                          "approved_companies": sum("approval" in row for row in results),
                          "intended_periods": sum(len(c["periods"]) for c in companies),
                          "paired_periods": len(runs),
                          "native_passed": sum(r.get("native_score", {}).get("passed", False) for r in runs),
                          "baseline_passed": sum(r.get("baseline_score", {}).get("passed", False) for r in runs),
                          "fresh_periods": sum(r["split"] == "holdout" for r in runs),
                          "native_fresh_passed": sum(r["split"] == "holdout" and r.get("native_score", {}).get("passed", False) for r in runs),
                          "baseline_fresh_passed": sum(r["split"] == "holdout" and r.get("baseline_score", {}).get("passed", False) for r in runs),
                          "usage": usage, "narrative_quality": "not_automatically_scored"},
              "scope": manifest["scope"], "all_attempts_retained": True}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--jev-key-file")
    parser.add_argument("--company-limit", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--resume-from", type=Path, help="Retain passing authored cards; share the original 48-attempt ceiling; run only unseen periods")
    args = parser.parse_args()
    result = asyncio.run(run_trial(args.output, live=args.live, key_file=args.jev_key_file,
                                  company_limit=args.company_limit, resume_from=args.resume_from))
    print(json.dumps({"output": str(args.output), "status": result.get("status", "recorded"),
                      "jev_attempts": result.get("jev_attempts", 0)}))


if __name__ == "__main__":
    main()

"""Small equal-information live-agent canary, NOT an enterprise/value benchmark.

The control keeps the same searchable full notes and source snapshots. Treatment
adds the production context read tools; neither arm evaluates cards or calls Jev.
Owner context is precurated, so this cannot prove onboarding or autonomous reuse.
Private expected labels remain in the scorer, never tool responses or prompts.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from evaluations.bootstrap_agent_trial import Audit
from evaluations.codex_trial_transport import codex_episode
from signalweave.knowledge import KnowledgeService
from signalweave.knowledge_mcp import register_knowledge_tools
from signalweave.knowledge_models import KnowledgeContent, KnowledgeEntry
from signalweave.knowledge_store import SQLiteKnowledgeStore
from signalweave.models import PrincipalContext, ResourceContract, ResourceDescriptor, SourceRef
from signalweave.sources import SourceRegistry

SUBMISSION = {
    "type": "object", "additionalProperties": False,
    "required": ["outcome", "alert_recipients", "report_audience", "findings", "uncertainties", "message"],
    "properties": {
        "outcome": {"type": "string", "enum": ["ignore", "investigate", "notify"]},
        "alert_recipients": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
        "report_audience": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
        "findings": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "additionalProperties": False, "required": ["claim", "evidence_refs"],
            "properties": {"claim": {"type": "string", "maxLength": 500},
                           "evidence_refs": {"type": "array", "maxItems": 10, "items": {"type": "string"}}},
        }},
        "uncertainties": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 500}},
        "message": {"type": "string", "minLength": 1, "maxLength": 1800},
    },
}


def public_case(case: dict) -> dict:
    return copy.deepcopy({key: case[key] for key in ("id", "tenant", "task", "policy", "sources", "notes")})


class PublicAssets:
    name = "company"

    def __init__(self, sources: list[dict], tenant: str):
        self.sources, self.tenant = sources, tenant
        self.authorization_calls = 0

    async def authorize(self, source, *, authorized_tenants=None):
        self.authorization_calls += 1
        ref = f"{source.adapter}|{source.resource}"
        item = next((item for item in self.sources if item["ref"] == ref), None)
        if item is None or self.tenant not in (authorized_tenants or []):
            return None
        return ResourceDescriptor(adapter=source.adapter, resource=source.resource,
                                  kind="fixture-snapshot", title=item["title"],
                                  contract=ResourceContract(tenant_id=self.tenant))


def fixture_refs(refs: list[str]) -> list[SourceRef]:
    return [SourceRef(key=f"source-{index}", adapter=ref.split("|", 1)[0],
                      resource=ref.split("|", 1)[1], label=ref)
            for index, ref in enumerate(refs)]


class ContextEpisode:
    phase = "monitoring"
    setup_complete = False

    def __init__(self, case: dict, path: Path, treatment: bool, clock: datetime):
        self.public = public_case(case)  # deliberately no expected labels
        self.treatment = treatment
        self.submission = None
        self.source_reads = 0
        self.identity = PrincipalContext(principal_id="fixture-owner", tenant_id=case["tenant"])
        adapters = []
        for name in sorted({source["ref"].split("|", 1)[0] for source in case["sources"]}):
            adapter = PublicAssets(case["sources"], case["tenant"])
            adapter.name = name
            adapters.append(adapter)
        self.adapters = adapters
        service = KnowledgeService(SQLiteKnowledgeStore(path), SourceRegistry(adapters))
        self.notes = []
        for note in case["notes"]:
            review_after = clock + timedelta(days=14 if note["review_after"] == "future" else -14)
            valid_from = None if note.get("valid_from") is None else clock + timedelta(
                days=3 if note["valid_from"] == "future" else -30,
            )
            value = KnowledgeContent(
                domain=note["domain"], title=note["title"], body=note["body"], kind=note["kind"],
                sources=fixture_refs(note["source_refs"]), provenance=note["provenance"],
                review_after=review_after, valid_from=valid_from,
            )
            record = KnowledgeEntry(id=note["id"], revision=1, tenant_id=case["tenant"],
                                    content=value, status=note["status"], actor=self.identity.principal_id)
            service.store.append(record, expected_revision=0)
            self.notes.append(record.model_dump(mode="json"))
        self.server = FastMCP("context-pilot-component")
        register_knowledge_tools(self.server, service, lambda _ctx: self.identity)

    async def specs(self) -> list[dict]:
        specs = [
            {"name": "search_company_notes", "description": "Search the same full owner notes available to every arm. Literal words; empty query browses all. Notes include status, review date and provenance; preserve caveats.",
             "parameters": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 2000}}, "required": ["query"], "additionalProperties": False}},
            {"name": "read_company_note", "description": "Read a full company note by exact ID, including its review/validity metadata.",
             "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"], "additionalProperties": False}},
            {"name": "read_source_snapshot", "description": "Read one authorized cached source snapshot by exact adapter|resource reference. Same fixture data and tool in every arm.",
             "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"], "additionalProperties": False}},
            {"name": "submit_analysis", "description": "Submit the final analysis and a concise proposed human message. This never sends a notification. Stop after submitting.", "parameters": SUBMISSION},
        ]
        if self.treatment:
            specs.extend({"name": tool.name, "description": tool.description, "parameters": tool.inputSchema}
                         for tool in await self.server.list_tools()
                         if tool.name in {"retrieve_domain_context", "get_context_history"})
        return specs

    async def call(self, name: str, arguments: dict) -> dict:
        if name == "submit_analysis":
            self.submission = copy.deepcopy(arguments)
            return {"accepted": True, "delivery_enabled": False}
        if name == "search_company_notes":
            words = re.findall(r"[^\W_]+", arguments["query"].lower())
            return {"notes": [copy.deepcopy(note) for note in self.notes
                              if all(word in (note["content"]["title"] + " " + note["content"]["body"] + " " + note["content"]["domain"]).lower() for word in words)]}
        if name == "read_company_note":
            return copy.deepcopy(next(note for note in self.notes if note["id"] == arguments["id"]))
        if name == "read_source_snapshot":
            self.source_reads += 1
            return copy.deepcopy(next(source for source in self.public["sources"] if source["ref"] == arguments["ref"]))
        result = await self.server.call_tool(name, arguments)
        return result[1] if isinstance(result, tuple) else json.loads(result[0].text)


async def run(args) -> dict:
    payload = json.loads(Path(args.cases).read_text())
    cases = payload["cases"][:args.limit]
    if not 1 <= len(cases) <= 3:
        raise ValueError("this canary permits only one to three independent cases")
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("use a new output directory; never replace an earlier pilot")
    output.mkdir(parents=True)
    audit = Audit(path=output / "trace.jsonl")
    clock = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "scope": "Small precurated-context canary with live Codex agents and fixture source tools; not onboarding, Jev, real warehouse, statistical superiority, or customer evidence",
        "protocol_version": 2,
        "model": args.model, "effort": args.effort,
        "codex_executable": args.codex_executable,
        "case_digest": hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(),
        "episodes": [], "raw_company_tools_retained_in_both_arms": True,
        "max_agent_invocations": 2 * len(cases), "max_tool_calls_per_invocation": 10,
        "input_token_stop_before_next_episode": 100000,
    }
    with tempfile.TemporaryDirectory(prefix="signalweave-context-canary-") as temporary:
        for index, case in enumerate(cases):
            # Counterbalance order; never select the favorable result after seeing outputs.
            for arm in (["ordinary_notes", "signalweave_context"] if index % 2 == 0 else ["signalweave_context", "ordinary_notes"]):
                tokens = sum(event.get("usage", {}).get("input_tokens", 0)
                             for event in audit.events if event["kind"] == "api.response")
                if tokens >= 100000:
                    report["stopped_for_budget"] = True
                    break
                session = ContextEpisode(case, Path(temporary) / f"{case['id']}-{arm}.db", arm == "signalweave_context", clock)
                audit.episode = f"{case['id']}:{arm}"
                instructions = (
                    "You are an analytics agent preparing a concise, evidence-backed business update. "
                    "Use only the trial MCP tools; no shell, filesystem, web, or other connections. "
                    "Both the source snapshots and full company notes are available. Search notes with "
                    "short literal terms or browse using an empty query. Preserve review dates, validity, "
                    "definitions and hypotheses; a note is not a current measurement. Follow the owner's "
                    "policy, distinguish supported facts from causal guesses, cite exact note/source IDs, "
                    "and use the directory in the policy for recipients. alert_recipients contains only "
                    "policy-triggered escalation recipients (empty when outcome=ignore). report_audience "
                    "is the audience requested for the routine report and may be present when no alert "
                    "is warranted. Neither field authorizes sending. You can report supported facts "
                    "even if some context remains ambiguous. Do not send or schedule anything. "
                    "When ready call submit_analysis once with a short human-readable message and stop. "
                    "SignalWeave context read tools, when present, are optional; raw company tools remain available."
                )
                result = await codex_episode(
                    session, key=None, effort=args.effort, budget=None, audit=audit,
                    max_turns=10, max_tool_calls=10, max_output_tokens=2000,
                    timeout_seconds=180, model=args.model, codex_executable=args.codex_executable,
                    instructions_override=instructions,
                    prompt_override={"as_of": clock.isoformat(), "task": case["task"], "policy": case["policy"],
                                     "source_directory": [{"ref": source["ref"], "title": source["title"]} for source in case["sources"]]},
                )
                submission = session.submission or {}
                expected = case["expected"]
                report["episodes"].append({
                    "case_id": case["id"], "arm": arm, "agent": result,
                    "submission": submission, "source_reads": session.source_reads,
                    "source_authorization_checks": sum(adapter.authorization_calls for adapter in session.adapters),
                    "expected": expected,
                    "outcome_matches": submission.get("outcome") == expected["outcome"],
                    "alert_recipients_match": set(submission.get("alert_recipients", [])) == set(expected["recipients"]),
                    "message_review": "pending independent content review; label matches alone are not success",
                })
                (output / "report.json").write_text(json.dumps(report, indent=2))
                print(json.dumps({"case": case["id"], "arm": arm, "status": result["status"],
                                  "outcome_matches": report["episodes"][-1]["outcome_matches"]}), flush=True)
                if result["status"] != "complete":
                    report["stopped_for_transport_or_tool_failure"] = True
                    break
            if report.get("stopped_for_budget") or report.get("stopped_for_transport_or_tool_failure"):
                break
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="evaluations/data/domain-context-pilot.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh"], default="medium")
    parser.add_argument("--codex-executable", required=True)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

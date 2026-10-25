"""Opt-in native Decisions/semantic-export journey; never imported by the product.

The ordinary-context arm retains every company tool and the same reviewed brief.
Synthetic SQL exports are not live semantic-vendor integration or human evidence.
Each invocation and failed attempt is retained in a new exclusive directory.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit
from evaluations.codex_trial_transport import codex_episode
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _manifest,
    _source_server,
    _SourceSession,
)
from evaluations.native_runtime_identity import inventory_native_runtime, verify_native_runtime
from scripts.binary_provenance import verify_binary
from signalweave.models import SourceRef

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "evaluations/protocols/decisions-semantic-2026-10-25.json"
PROMPTS = [
    "Finance monthly review: what happened to September revenue versus August?",
    "Give the CFO a concise September versus August revenue update on our agreed Finance basis.",
    "How did revenue move last complete month against the preceding month? Use our Finance definition.",
    "Prepare the leadership revenue brief for September compared with August, using the reviewed metric.",
    "Is our September revenue change meaningful under the saved Finance policy? Explain with evidence.",
    "I lead operations. Explain the latest complete-month revenue change using the same Finance basis.",
    "For the executive review, compare August and September revenue on our reviewed reporting basis.",
    "Tell the finance lead whether September's revenue movement deserves attention and why.",
    "Summarize September revenue, the prior month's amount, and the business implication under our agreed rule.",
    "What should leadership know about September versus August revenue? Keep the definition and scope explicit.",
]


def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")
    path.chmod(0o600)


def spec(name, description, properties, required):
    return {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required,
        "additionalProperties": False,
    }}


def reader_instructions(treatment):
    instructions = (
        "You are the company's analytics agent. Use only the exposed MCP tools, not shell/web/other connections. "
        "Retain company BI tools. Answer using the requested source-owned metric, current source values and applicable reviewed policy. "
        "Read the Finance notes for the reviewed brief and definition. Explain measurement periods, reporting unit and material scope; contribution is not causation. "
        "The same reviewed card/context is available in ordinary notes when SignalWeave is absent. "
        "With SignalWeave, evaluate the existing approved card once with the supplied NEW run_key when its business scope matches the question. "
        "For a distinct metric or question, do not force an unrelated card; use the company source tools. "
        "Retrieve needed shared definition/evidence, not the entire history. Never mutate cards or definitions during a reader run. "
        "You own the explanation; a policy label is not the analysis. If judgment is deferred, use available evidence without inventing an outcome. "
        "Return a concise human brief, at most 140 words. Do not claim anything was sent or scheduled. "
        "Complete with submit_report: source-owned metric identity/revision, amounts in full currency units (not thousands), "
        "YYYY-MM periods and inspectable source refs. Recipients are empty when no alert is warranted; otherwise use the exact owner-defined destination."
    )
    if treatment:
        instructions = (ROOT / "skills/signalweave/SKILL.md").read_text() + "\n" + instructions
    return instructions


@asynccontextmanager
async def native(binary, company, key_file, root, audit, runtime):
    """Actual native setup and normal-profile MCP; no preseeded cards or approvals."""
    build = verify_binary(binary)
    verify_native_runtime(binary, build, runtime)
    home = root / "person/.signalweave"
    home.parent.mkdir(parents=True, mode=0o700)
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    async with _source_server(_SourceSession(company, audit, company.tenant_id)) as url:
        public = {"scenario_id": company.tenant_id, "catalog": company.descriptors()}
        manifest = _manifest(public, url)
        for connection in manifest["connections"]:
            connection["context_namespace"] = "synthetic-semantic/" + company.tenant_id
        manifest_path = root / "sources.json"
        save(manifest_path, manifest)
        for args in [
            ["setup", "--non-interactive", "--home", str(home),
             "--decision-provider", "openai-decisions", "--openai-key-file", str(key_file),
             "--source", "mcp", "--manifest", str(manifest_path),
             "--tenant", company.tenant_id, "--principal", "finance-owner",
             "--profile", "agent", "--agent", "codex", "--no-register-agent"],
            ["context", "enable", "--home", str(home)],
            ["health", "--live", "--json", "--home", str(home)],
        ]:
            process = await asyncio.create_subprocess_exec(
                str(binary), *args, cwd=root, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), 90)
            audit.emit("native.command", command=args[:2], returncode=process.returncode,
                       stdout=stdout.decode(), stderr=stderr.decode())
            if process.returncode:
                raise RuntimeError("Native setup/context/health failed; retained redacted audit")
        params = StdioServerParameters(command=str(binary), args=["serve", "--home", str(home)],
                                       cwd=str(root), env=env)
        with (root / "native-stderr.txt").open("w") as errors:
            async with stdio_client(params, errlog=errors) as streams, ClientSession(*streams) as session:
                initialized = await _initialize_mcp_session(session)
                yield InstalledServer(session, initialized.instructions, audit)


class Episode:
    phase = "monitoring"
    setup_complete = True

    def __init__(self, company, native_server, *, onboarding=False, notes=None):
        self.company, self.native = company, native_server
        self.onboarding, self.notes = onboarding, notes
        self.treatment = native_server is not None
        self.submission = None
        self.calls = []

    async def specs(self):
        tools = [
            spec("search_company_assets", "Browse/search the company's semantic metric exports. Names alone do not establish meaning.",
                 {"query": {"type": "string"}}, ["query"]),
            spec("read_company_asset", "Read a source-owned SQL metric export and its exact definition and measurement periods.",
                 {"resource": {"type": "string"}}, ["resource"]),
            spec("read_finance_notes", "Read source-owned metric definitions, the Finance owner's policy and reviewed briefs, if present.", {}, []),
        ]
        if self.native:
            tools += [{"name": tool.name, "description": tool.description, "parameters": tool.inputSchema}
                      for tool in await self.native.list_tools()]
        if self.onboarding:
            tools += [spec("finish_onboarding", "Finish only after saving, reviewing and approving the agreed card and shared definition. Never send or schedule.",
                           {"card_id": {"type": "string"}, "context_id": {"type": "string"},
                            "handoff": {"type": "string"}}, ["card_id", "context_id", "handoff"])]
        else:
            tools += [spec("submit_report", "Return the business brief and its inspectable facts; does not send a message.", {
                "metric_id": {"type": "string"}, "definition_revision": {"type": "string"},
                "current": {"type": ["number", "null"]}, "previous": {"type": ["number", "null"]},
                "unit": {"type": "string"}, "current_period": {"type": "string"},
                "previous_period": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}},
                "outcome": {"type": "string", "enum": ["ignore", "investigate", "insufficient_data", "notify", "deferred", "not_applicable"]},
                "recipients": {"type": "array", "items": {"type": "string"}},
                "message": {"type": "string"}, "uncertainties": {"type": "array", "items": {"type": "string"}},
            }, ["metric_id", "definition_revision", "current", "previous", "unit", "current_period",
                "previous_period", "source_refs", "outcome", "recipients", "message", "uncertainties"])]
        return tools

    async def call(self, name, arguments):
        self.calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
        if name == "search_company_assets":
            terms = arguments["query"].lower().split()
            return {"resources": [item for item in self.company.descriptors()
                                  if all(term in json.dumps(item).lower() for term in terms)]}
        if name == "read_company_asset":
            snapshot = await self.company.inspect(SourceRef(
                key=arguments["resource"], adapter=self.company.name,
                resource=arguments["resource"], label=arguments["resource"]))
            return snapshot.model_dump(mode="json")
        if name == "read_finance_notes":
            return {"source_notes": self.company.notes(), "owner_policy": self.company.business_policy,
                    "destinations": [{"key": "finance", "label": "Finance", "destination": "agent://finance"}],
                    "reviewed_brief": self.notes}
        if name == "finish_onboarding" and self.onboarding:
            _, card = await self.native.call_tool("get_insight_card", {
                "card_id": arguments["card_id"], "response_mode": "full"})
            _, context = await self.native.call_tool("retrieve_domain_context", {
                "entry_ids": [arguments["context_id"]]})
            if card["status"] != "approved" or not context["entries"]:
                raise ValueError("Onboarding is not complete")
            self.submission = {**arguments, "card": card, "context": context}
            return {"accepted": True, "sent": False, "scheduled": False}
        if name == "submit_report" and not self.onboarding:
            self.submission = copy.deepcopy(arguments)
            return {"accepted": True, "sent": False}
        if not self.native:
            raise ValueError("Unknown company tool")
        _, result = await self.native.call_tool(name, arguments)
        return result


async def actor(episode, audit, codex, instructions, task, *, onboarding=False):
    return await codex_episode(
        episode, key=None, effort="xhigh", budget=None, audit=audit,
        max_turns=45 if onboarding else 14, max_tool_calls=45 if onboarding else 14,
        max_output_tokens=6000 if onboarding else 2200,
        timeout_seconds=420 if onboarding else 240,
        model="gpt-6-luna", codex_executable=codex,
        allow_trial_resource_discovery=True, strict_single_turn_usage=True,
        instructions_override=instructions, prompt_override=task,
    )


def grade(submission, company, *, resource=None):
    """Independent amount oracle, never passed into an agent tool or prompt."""
    expected = company.expected(resource) if resource else company.expected()
    alternate = resource is not None and resource != company.canonical_resource
    checks = {
        "submitted": bool(submission),
        "metric": submission.get("metric_id") == (expected["metric_id"] if alternate else company.metric_id),
        "unit": submission.get("unit") == company.unit,
        "canonical_source": f"{company.name}|{resource or company.canonical_resource}" in submission.get("source_refs", []),
        "current_period": submission.get("current_period") == company.current_period,
        "previous_period": submission.get("previous_period") == company.previous_period,
        "definition_revision": submission.get("definition_revision") == ("r2" if alternate else "r3"),
        "outcome": submission.get("outcome") == ("not_applicable" if alternate else "notify" if expected["change_pct"] < -10 else "ignore"),
        "recipients": submission.get("recipients") == (["agent://finance"] if not alternate and expected["change_pct"] < -10 else []),
    }
    for field in ("current", "previous"):
        value = submission.get(field)
        checks[field] = type(value) in (float, int) and abs(value - float(expected[field])) <= 0.005
    return checks


async def run(args):
    from evaluations.semantic_company import SemanticCompany

    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    identity = verify_binary(args.binary)
    runtime = inventory_native_runtime(args.binary, identity)
    protocol = json.loads(PROTOCOL.read_text())
    save(root / "protocol.json", {**protocol, "build": identity, "runtime": runtime,
                                 "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
                                 "source_hashes": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                                   for path in [Path(__file__), ROOT / "evaluations/semantic_company.py",
                                                                ROOT / "evaluations/codex_trial_transport.py",
                                                                ROOT / "evaluations/installed_trial_transport.py"]},
                                 "requested_readers": args.readers, "requested_companies": args.companies})
    secret = args.key_file.read_text().strip()
    if not secret:
        raise ValueError("Empty private OpenAI credential")
    result = {"scope": protocol["question"], "companies": [], "complete": False,
              "provider_usage_instrumented": False, "delivery_enabled": False}
    try:
        for company_name in args.companies:
            directory = root / company_name
            directory.mkdir(mode=0o700)
            audit = Audit(path=directory / "setup-trace.jsonl", secrets=(secret,))
            company = SemanticCompany(directory, company_name, seed=protocol["seed"])
            company.set_condition("decline")
            company_result = {"company": company_name, "readers": []}
            result["companies"].append(company_result)
            async with native(args.binary, company, args.key_file, directory, audit, runtime) as installed:
                episode = Episode(company, installed, onboarding=True)
                instructions = (
                    (ROOT / "skills/signalweave/SKILL.md").read_text()
                    + "\nThis is an isolated synthetic company, not production. Use only the exposed MCP tools; no shell, web or unrelated connections. "
                    "The fictional Finance owner delegates technical source validation and approval to you within the source-owned policy. "
                    "Discover and inspect the semantic definitions before choosing. Give a useful first analysis, then save one shared reviewed "
                    "Finance revenue definition and a reviewed approved card for this retrospective monthly comparison. Pin that exact reviewed "
                    "definition as required for policy action. This historical review may set max_source_age_hours=null; retain actual periods. "
                    "Do not add invented metric contracts, thresholds, sources or causal claims. Delivery routes are metadata, not permission to send. "
                    "Read the owner policy from company notes. No live sending or scheduling. Call finish_onboarding when complete."
                )
                started = time.monotonic()
                onboarding = await actor(episode, audit, args.codex, instructions,
                                         {"task": "Set up Finance's revenue comparison for September against August. Use the company's authoritative semantic metric and owner policy."},
                                         onboarding=True)
                company_result["onboarding"] = {"agent": onboarding, "submission": episode.submission,
                                                 "seconds": time.monotonic() - started, "calls": episode.calls}
                save(root / "report.json", result)
                if not episode.submission or onboarding["status"] != "complete":
                    result["stopped"] = "Onboarding incomplete; preserve this attempt before repair"
                    return result
                shared = episode.submission
                card = shared["card"]
                context_entries = shared["context"]["entries"]
                company_result["onboarding_checks"] = {
                    "approved": card["status"] == "approved",
                    "canonical_source": any(source["adapter"] == company.name and source["resource"] == company.canonical_resource
                                            for source in card["sources"]),
                    "required_reviewed_context": any(pin["required_for_action"] and any(
                        entry["id"] == pin["entry_id"] and entry["revision"] == pin["revision"]
                        and entry["status"] == "reviewed" for entry in context_entries)
                        for pin in card.get("context_bindings", [])),
                }
                if not all(company_result["onboarding_checks"].values()):
                    result["stopped"] = "Onboarding did not preserve the agreed semantic source and reviewed meaning"
                    return result
                for index, prompt in enumerate(PROMPTS[:args.readers]):
                    for arm in (["ordinary_context", "signalweave"] if index % 2 == 0
                                else ["signalweave", "ordinary_context"]):
                        reader_audit = Audit(path=directory / f"reader-{index:02d}-{arm}.jsonl", secrets=(secret,))
                        reader = Episode(company, installed if arm == "signalweave" else None, notes=shared)
                        task = {"question": prompt, "as_of": "2026-10-25",
                                "run_key": f"semantic-v1:{company_name}:{index}:{arm}"}
                        common = reader_instructions(arm == "signalweave")
                        started = time.monotonic()
                        response = await actor(reader, reader_audit, args.codex, common, task)
                        record = {"index": index, "arm": arm, "prompt": prompt, "agent": response,
                                  "submission": reader.submission, "calls": reader.calls,
                                  "seconds": time.monotonic() - started,
                                  "checks": grade(reader.submission or {}, company),
                                  "human_review": "pending independent review; structured checks are not report quality"}
                        company_result["readers"].append(record)
                        save(root / "report.json", result)
                        print(json.dumps({"company": company_name, "reader": index, "arm": arm,
                                          "status": response["status"], "checks": record["checks"]}), flush=True)
                        if not reader.submission or response["status"] != "complete":
                            result["stopped"] = "Reader did not submit; retain failure before further paid episodes"
                            return result
                        if not all(record["checks"].values()):
                            result["stopped"] = "Reader failed the preregistered semantic/amount/action gate; preserve before repair"
                            return result
                company_result["semantic_contrasts"] = []
                if args.sensitivity:
                    for contrast in ("explicit_gross", "conflicting_definition"):
                        company.set_condition("decline" if contrast == "explicit_gross" else "definition_conflict")
                        prompt = (
                            "This is a different question: report gross billings BEFORE refunds, credits, tax and eligibility exclusions for September against August, not Finance net revenue. "
                            "Do not apply the saved net-revenue card's alert policy to this separate metric. Mark policy not_applicable and notify nobody."
                            if contrast == "explicit_gross" else
                            "Review the currently competing revenue definitions. Can we responsibly give leadership one definitive revenue figure and alert under the saved card? "
                            "Explain the conflict and what clarification is needed; do not reconcile incompatible definitions by guessing."
                        )
                        for arm in ("ordinary_context", "signalweave"):
                            reader = Episode(company, installed if arm == "signalweave" else None, notes=shared)
                            contrast_audit = Audit(path=directory / f"contrast-{contrast}-{arm}.jsonl", secrets=(secret,))
                            response = await actor(reader, contrast_audit, args.codex, reader_instructions(arm == "signalweave"), {
                                "question": prompt, "as_of": "2026-10-25",
                                "run_key": f"semantic-sensitivity:{company_name}:{contrast}:{arm}",
                            })
                            submission = reader.submission or {}
                            checks = grade(submission, company, resource="metric:gross-revenue") if contrast == "explicit_gross" else {
                                "submitted": bool(submission),
                                "unresolved": submission.get("outcome") in {"deferred", "investigate", "insufficient_data"},
                                "no_alert": submission.get("recipients") == [],
                                "uncertainty_explicit": bool(submission.get("uncertainties")),
                            }
                            company_result["semantic_contrasts"].append({
                                "contrast": contrast, "arm": arm, "agent": response,
                                "submission": reader.submission, "checks": checks, "calls": reader.calls,
                                "human_review": "pending independent review",
                            })
                            save(root / "report.json", result)
                            if response["status"] != "complete" or not all(checks.values()):
                                result["stopped"] = "Semantic sensitivity gate failed; preserve before repair"
                                return result
                company_result["policy_contrasts"] = []
                for condition in ("quiet", "decline", "gap", "definition_conflict"):
                    company.set_condition(condition)
                    for repeat in range(2):
                        _, packet = await installed.call_tool("evaluate_insight_card", {
                            "card_id": card["id"],
                            "idempotency_key": f"semantic-contrast:{company_name}:{condition}:{repeat}",
                            "response_mode": "full",
                        })
                        company_result["policy_contrasts"].append({
                            "condition": condition, "repeat": repeat, "packet": packet,
                            "independent_source_values": company.expected(),
                        })
                        save(root / "report.json", result)
        result["complete"] = True
        return result
    except Exception as error:
        result["failure"] = {"type": type(error).__name__, "message": str(error).replace(secret, "[REDACTED]")[:1500]}
        raise
    finally:
        save(root / "report.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Explicitly permit paid Decisions and Codex invocations")
    parser.add_argument("--sensitivity", action="store_true", help="Also test a distinct metric and conflicting definitions")
    parser.add_argument("--readers", type=int, choices=range(1, 11), default=2)
    parser.add_argument("--companies", nargs="+", choices=["retail", "saas", "marketplace"], default=["retail"])
    args = parser.parse_args()
    if not args.live:
        parser.error("This trial makes paid provider requests; explicitly pass --live")
    args.binary, args.key_file = args.binary.resolve(), args.key_file.resolve()
    os.umask(0o077)
    report = asyncio.run(run(args))
    print(json.dumps({"complete": report["complete"], "stopped": report.get("stopped")}))
    if not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

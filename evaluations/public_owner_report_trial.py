"""Fresh agent-authored setup → independent policy review → current report.

Public synthetic retail data over the native company-MCP bridge. No archived
cards, imported approvals, supplied judgments, delivery or schedule. This small
development pair is not a human usability panel or enterprise benchmark.
"""

import argparse
import asyncio
import copy
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator, validate

from evaluations.agent_workflow_cohort import _bridge_identity
from evaluations.bootstrap_agent_trial import (
    Audit,
    PublicSourceAdapter,
    RequestBudget,
    calculate,
    function,
)
from evaluations.bootstrap_owner_review import review_owner_artifact
from evaluations.bootstrap_scenarios import build_scenarios, public_episode
from evaluations.codex_trial_transport import codex_episode
from evaluations.domain_context_onboarding_trial import (
    Episode,
    approval_digest,
    failure_detail,
    native_context,
    pinned_codex,
    public_brief,
    usage_totals,
)
from evaluations.human_report_episode import HumanReportEpisode
from evaluations.reviewed_setup_report_trial import (
    before_invocation,
    calendar_measurement_rebase,
    record_tool_inventory,
    summarize_usage,
)
from scripts.binary_provenance import verify_binary
from signalweave.models import SourceRef

PROTOCOL = "public-owner-report-v1"
HANDOFF_PROTOCOL = "public-owner-report-handoff-v2"
HANDOFF_MANIFEST = Path(__file__).with_name("data") / "public-owner-handoff-v1-manifest.json"
LIMITS = {"agent_invocations": 6, "jev_attempts": 1,
          "between_invocation_input_stop": 1_200_000, "between_invocation_uncached_stop": 220_000}
AUTHOR = (
    "Help the owner onboard this recurring BI question. Discover and inspect relevant sources, "
    "use the glossary and ask focused owner questions for consequential missing context. "
    "Give a useful current readout; save reusable definitions, exact scope, policy, quiet and "
    "missing-data behavior. These onboarding snapshots are historical examples: use their own "
    "measurement intervals and do not describe them as today's business conditions. Preserve "
    "the reusable method, not those measurements. Show the saved artifact through request_owner_approval for synthetic "
    "owner consent. Treatment has card tools; baseline has durable notes, not cards. "
    "Use only the supplied tools. No evaluation, schedule or sending during setup. "
    "Finish with finish_setup and stop. Never invent policy or claim unresolved setup is complete. "
)
REPORT = (
    "You are a fresh analytics reporting agent reusing your own arm's reviewed setup. "
    "Fetch this run's current evidence; old onboarding measurements are not current truth. "
    "Write the concise business message: supported changes, significance under the agreed rule, "
    "useful breakdown, limitations, proposed policy-triggered recipients and next step. "
    "Cite underlying source refs beside measurements; receipts support workflow facts only. "
    "Accounting contributions are not causes. Use calculate if needed. No owner questions, "
    "policy edits, scheduling or sending. Finish with record_report and stop. "
    "Use only the supplied tools. Capture time is not the measurement cutoff; use source intervals. "
)


class AuthorEpisode(Episode):
    async def specs(self):
        return [*await super().specs(), function("calculate", "Bounded arithmetic, available in both arms.",
                {"expression": {"type": "string", "maxLength": 1000}}, ("expression",))]

    async def call(self, name, args):
        if name == "calculate":
            return {"value": calculate(args["expression"])}
        return await super().call(name, args)


def scenario():
    value = _bridge_identity(build_scenarios(seed=20261001, connector_profile=True)[0])
    value["public"]["brief"] += " Remember the agreed definition for future sales investigations."
    value["public"]["owner_topics"].append("context_review")
    value["public"]["owner_answers"]["context_review"] = (
        "Definitions may be shared within this synthetic tenant; review in 30 days. Show the saved draft before requesting approval. Hypotheses stay advisory."
    )
    return value


def pin_tools(specs):
    result = {}
    for spec in specs:
        Draft202012Validator.check_schema(spec["parameters"])
        if spec["name"] in result:
            raise ValueError("Duplicate advertised tool")
        result[spec["name"]] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    return result


def load_baseline_handoff(report_path, trace_path, scenario_hash, identity, codex):
    """Charge one complete author handoff, never import a card or grant approval."""
    report_bytes, trace_bytes = Path(report_path).read_bytes(), Path(trace_path).read_bytes()
    manifest_bytes = HANDOFF_MANIFEST.read_bytes()
    expected = json.loads(manifest_bytes)
    if (hashlib.sha256(report_bytes).hexdigest() != expected["report_sha256"]
            or hashlib.sha256(trace_bytes).hexdigest() != expected["trace_sha256"]):
        raise ValueError("Prior handoff differs from the preregistered immutable artifacts")
    prior = json.loads(report_bytes)
    public_input = Path(report_path).parent / "public-onboarding-input.json"
    if (prior["runner_sha256"] != expected["runner_sha256"]
            or hashlib.sha256(public_input.read_bytes()).hexdigest() != expected["public_input_sha256"]
            or json.loads(public_input.read_text()) != public_episode(scenario())):
        raise ValueError("Prior runner or public fixture does not match the frozen handoff")
    events = [json.loads(line) for line in trace_bytes.splitlines()]
    entries = prior.get("episodes", [])
    if (prior.get("protocol") != PROTOCOL or prior.get("scenario_sha256") != scenario_hash
            or prior.get("preflight_only") is not False or prior.get("usage_known") is not True
            or prior.get("agent_invocations_started") != 1 or prior.get("provider_attempts") != 0
            or prior["build"]["binary_sha256"] != identity["binary_sha256"]
            or prior["codex"]["sha256"] != codex["sha256"] or len(entries) != 1):
        raise ValueError("Expected the unchanged one-author public handoff with current binaries")
    entry = entries[0]
    if (entry.get("arm") != "baseline" or entry.get("stage") != "author"
            or entry.get("agent", {}).get("status") != "complete" or not entry.get("notes", "").strip()
            or entry.get("setup", {}).get("card_ids") != []
            or not any(request.get("kind") == "notes" and request.get("id") == "working"
                       and request.get("saved_artifact") == {"notes": entry["notes"]}
                       for request in entry.get("owner_requests", []))):
        raise ValueError("A completed, owner-shown notes handoff is required; no card imports")
    summary = summarize_usage(SimpleNamespace(events=events), {k: 0 for k in usage_totals([])})
    if (not summary["usage_known"] or summary["agent_invocations_started"] != 1
            or summary["usage"] != prior["usage"]
            or any(e.get("provider") == "jev" for e in events)):
        raise ValueError("Prior author usage must be known and charged without provider attempts")
    return copy.deepcopy(entry), events, {
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "trace_sha256": hashlib.sha256(trace_bytes).hexdigest(), "usage": prior["usage"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "classification": "Completed baseline author awaiting semantic review; original v1 remains terminal. No author retry or imported approval.",
    }


async def run(args):
    binary = Path(args.binary).resolve()
    identity, codex = verify_binary(binary), await pinned_codex(args.codex_executable)
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    key = Path(args.key_file).resolve() if args.run else output / "synthetic-startup-key"
    if not args.run:
        key.write_text("synthetic-public-owner-preflight-no-inference")
        key.chmod(0o600)
    audit = Audit(path=output / "trace.jsonl", secrets=(key.read_text().strip(),))
    budget = RequestBudget(limit=LIMITS["jev_attempts"] if args.run else 0)
    fixture = scenario()
    public = public_episode(fixture)
    (output / "public-onboarding-input.json").write_text(json.dumps(public, indent=2) + "\n")
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    clock = datetime.now(timezone.utc)
    offset, _ = calendar_measurement_rebase(fixture["public"]["periods"], clock)
    report = {"protocol": PROTOCOL, "preflight_only": not args.run, "build": identity,
              "codex": codex, "limits": LIMITS, "episodes": [], "period_index": 2,
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scenario_sha256": hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest(),
              "scope": "One known synthetic retail development case; historical onboarding examples followed by a later current-period report. Scripted owner facts, normalized company-MCP exports, isolated non-interactive native setup. No real human/vendor/enterprise claim. Both arms retain company tools and own notes; arbitrary scripts disabled. Whole-package comparison, not isolated Jev/context ablation. No schedule or delivery.",
              "read_clock": clock.isoformat(), "measurement_offset_seconds": offset.total_seconds()}
    zero = {"input_tokens": 0, "cached_input_tokens": 0, "uncached_input_tokens": 0, "output_tokens": 0, "responses": 0}
    prior_entry, prior_events = None, []
    handoff_report = getattr(args, "baseline_handoff_report", None)
    if handoff_report:
        prior_entry, prior_events, charge = load_baseline_handoff(handoff_report, args.baseline_handoff_trace,
            report["scenario_sha256"], identity, codex)
        report.update(protocol=HANDOFF_PROTOCOL, charged_prior_author=charge)

    def combined_audit():
        return SimpleNamespace(events=[*prior_events, *audit.events])

    def save():
        report.update(summarize_usage(combined_audit(), zero))
        report["new_agent_invocations_started"] = sum(e["kind"] == "api.request" and e.get("provider") == "openai" for e in audit.events)
        report["new_usage"] = usage_totals(audit.events)
        report.pop("usage_including_accepted_onboarding", None)
        report["provider_attempts"] = budget.used
        usage = [e.get("usage") for e in audit.events if e["kind"] == "api.response" and e.get("provider") == "jev"]
        report["provider_usage"] = usage
        report["provider_usage_known"] = (len(usage) == budget.used and not budget.exhausted
            and not any(e["kind"] in {"api.error", "api.rejected"} and e.get("provider") == "jev" for e in audit.events)
            and all(isinstance(u, dict) and all(type(u.get(k)) is int and u[k] >= 0 for k in ("input_tokens", "output_tokens")) for u in usage))
        (output / "report.json").write_text(json.dumps(audit.redact(report), indent=2) + "\n")

    def check():
        before_invocation(combined_audit(), LIMITS, codex["path"], codex["sha256"])
        if hashlib.sha256(binary.read_bytes()).hexdigest() != identity["binary_sha256"]:
            raise RuntimeError("Native executable changed; stop without retry")
        if (hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != report["runner_sha256"]
                or hashlib.sha256(canonical.read_bytes()).hexdigest() != report["installed_skill_sha256"]):
            raise RuntimeError("Frozen runner or skill changed; stop without retry")
        if handoff_report and hashlib.sha256(HANDOFF_MANIFEST.read_bytes()).hexdigest() != report["charged_prior_author"]["manifest_sha256"]:
            raise RuntimeError("Frozen handoff manifest changed; stop without retry")

    try:
        with tempfile.TemporaryDirectory(prefix="fresh-public-owner-", dir=output) as private:
            root = Path(private)
            async with native_context(binary, key, public, adapter, audit, root, request_budget=budget) as (native, skill):
                report["installed_skill_sha256"] = hashlib.sha256(skill.encode()).hexdigest()
                canonical = Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md"
                if hashlib.sha256(canonical.read_bytes()).hexdigest() != report["installed_skill_sha256"]:
                    raise RuntimeError("Installed native skill differs from the current canonical skill")
                _, initial_cards = await native.call_tool("list_insight_cards", {})
                if initial_cards["count"] != 0 or initial_cards["cards"]:
                    raise RuntimeError("This cohort requires a blank native home")
                report["initial_native_card_count"] = 0
                setups = []
                for treatment in (False, True):
                    arm = "signalweave" if treatment else "baseline"
                    audit.episode = arm + ":setup"
                    adapter.set_period(public["period"], clock, measurement_offset=offset)
                    session = AuthorEpisode(public, adapter, native if treatment else None)
                    specs = await session.specs()
                    report.setdefault("author_tool_inventories", {})[arm] = pin_tools(specs)
                    if treatment:
                        baseline = report["author_tool_inventories"]["baseline"]
                        if any(report["author_tool_inventories"][arm].get(name) != digest
                               for name, digest in baseline.items() if name not in {"finish_setup", "request_owner_approval"}):
                            raise RuntimeError("Shared author tools differ between arms")
                    finish = next(t["parameters"] for t in specs if t["name"] == "finish_setup")
                    validate({"card_ids": ["probe"] if treatment else [], "message": "Schema probe", "unresolved": []}, finish)
                    if not args.run:
                        asset = (await session.call("list_company_assets", {}))["assets"][0]
                        await session.call("read_company_asset", {"ref": asset["adapter"] + "|" + asset["resource"]})
                        if treatment:
                            _, snapshot = await native.call_tool("inspect_resource", {
                                "adapter": asset["adapter"], "resource": asset["resource"],
                            })
                            expected = (await adapter.inspect(SourceRef(key=snapshot["source_key"],
                                adapter=asset["adapter"], resource=asset["resource"], label=asset["title"]))).model_dump(mode="json")
                            if (snapshot["contract"]["tenant_id"] != public["scenario_id"]
                                    or any(snapshot[field] != expected[field] for field in ("observations", "evidence", "analytical_comparisons"))):
                                raise RuntimeError("Native bridge altered current analytical facts or tenant")
                            report["preflight_bridge_fidelity_verified"] = True
                        report_specs = await HumanReportEpisode(public, adapter, native if treatment else None).specs()
                        pin_tools(report_specs)
                        record_tool_inventory(report, arm, report_specs)
                        continue
                    start = len(audit.events)
                    if prior_entry is not None and not treatment:
                        entry = copy.deepcopy(prior_entry)
                        entry["restored_author_handoff"] = True
                        session.notes, session.setup = entry["notes"], entry["setup"]
                        session.owner_requests = copy.deepcopy(entry["owner_requests"])
                        result = entry["agent"]
                    else:
                        check()
                        result = await codex_episode(session, key=None, budget=None, audit=audit,
                            model="gpt-6-luna", effort="medium", max_turns=24, max_tool_calls=24,
                            max_output_tokens=3000, timeout_seconds=240, codex_executable=codex["path"], accounting_drain=True,
                            instructions_override=AUTHOR + ("\n" + native.instructions + "\n" + skill if treatment else ""), prompt_override=public_brief(public))
                        entry = {"arm": arm, "stage": "author", "agent": result, "setup": session.setup,
                                 "notes": session.notes, "owner_requests": session.owner_requests, "native_calls": session.native_calls}
                    report["episodes"].append(entry)
                    save()
                    if (not report["usage_known"] or result["status"] != "complete" or not session.setup
                            or (not handoff_report and session.setup["unresolved"])):
                        raise RuntimeError("Author setup incomplete or unknown usage; no retry")
                    card = None
                    if treatment:
                        _, card = await native.call_tool("get_insight_card", {"card_id": session.setup["card_ids"][0], "response_mode": "full"})
                        entry["card"] = card
                    review_events = prior_events if entry.get("restored_author_handoff") else audit.events[start:]
                    source_context = {"catalog": public["catalog"], "inspected_sources": [
                        {**e["snapshot"], "ref": e["ref"]} for e in review_events if e["kind"] == "source.read"]}
                    review_notes = session.notes
                    if handoff_report:
                        review_notes += "\n\nAuthor's pending items (quoted, not proof of missing business context):\n" + json.dumps(session.setup["unresolved"])
                    check()
                    audit.episode = arm + ":policy-review"
                    entry["independent_review"] = await review_owner_artifact(public=fixture["public"],
                        owner_answers=public["owner_answers"], artifact={"notes": review_notes, **({"card": card} if card else {})},
                        source_context=source_context, audit=audit, budget=None, model="gpt-6-luna", effort="medium", codex_executable=codex["path"])
                    save()
                    if not report["usage_known"] or not entry["independent_review"]["approved"]:
                        raise RuntimeError("Independent policy review rejected setup or usage unknown; no retry")
                    if treatment and (card["status"] != "approved"
                            or session.approvals.get(("card", card["id"])) != approval_digest("card", card)):
                        raise RuntimeError("Treatment still needs owner-confirmed card approval; semantic review does not grant it")
                    setups.append((session, card))
                if args.run:
                    period = fixture["public"]["periods"][2]
                    for treatment, (setup, card) in zip((False, True), setups, strict=True):
                        arm = "signalweave" if treatment else "baseline"
                        audit.episode = arm + ":report"
                        adapter.set_period(period, clock, measurement_offset=offset)
                        run_key = report["protocol"] + ":" + period["period_id"]
                        session = HumanReportEpisode(public, adapter, native if treatment else None,
                            notes=setup.notes, approved_card_id=card["id"] if card else None,
                            approved_card_version=card["version"] if card else None, run_key=run_key)
                        report_specs = await session.specs()
                        pin_tools(report_specs)
                        record_tool_inventory(report, arm, report_specs)
                        check()
                        result = await codex_episode(session, key=None, budget=None, audit=audit,
                            model="gpt-6-luna", effort="medium", max_turns=12, max_tool_calls=12,
                            max_output_tokens=3000, timeout_seconds=180, codex_executable=codex["path"], accounting_drain=True,
                            instructions_override=REPORT + (("Evaluate the approved card once with the supplied run key.\n" + skill) if treatment else ""),
                            prompt_override={"business": public_brief(public), "saved_setup": setup.setup,
                                "saved_notes": setup.notes, "period": adapter.period_context,
                                "completed_policy_review": report["episodes"][0 if not treatment else 1]["independent_review"],
                                "card_id": card["id"] if card else None, "idempotency_key": run_key})
                        report["episodes"].append({"arm": arm, "stage": "report", "agent": result,
                            "submission": session.submission, "source_reads": adapter.inspections,
                            "native_calls": session.native_calls, "approved_card_execution_verified": session.evaluation_verified if treatment else None})
                        save()
                        if (not report["usage_known"] or not report["provider_usage_known"] or result["status"] != "complete"
                                or session.submission is None):
                            raise RuntimeError("Report incomplete or usage unknown; no retry")
                        if treatment and not session.evaluation_verified:
                            raise RuntimeError("Live-policy integration gate not achieved; inspect the recorded report separately for usefulness")
                if not args.run and (budget.used or budget.exhausted):
                    raise RuntimeError("Preflight attempted provider inference")
                if args.run and budget.used != LIMITS["jev_attempts"]:
                    raise RuntimeError("Live Jev integration was not exercised; reports remain recorded separately")
                report["completed"] = True
    except Exception as error:  # noqa: BLE001 - preserve partial paid attempts
        report["failure"] = failure_detail(error)
    finally:
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("binary", "codex-executable", "output"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--key-file")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--baseline-handoff-report")
    parser.add_argument("--baseline-handoff-trace")
    args = parser.parse_args()
    if args.run and not args.key_file:
        parser.error("--run requires --key-file; preflight uses its own dummy key")
    if bool(args.baseline_handoff_report) != bool(args.baseline_handoff_trace):
        parser.error("Both baseline handoff report and trace are required together")
    result = asyncio.run(run(args))
    print(json.dumps({k: result.get(k) for k in ("completed", "failure", "agent_invocations_started", "provider_attempts", "usage")}))
    if not result.get("completed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Report-only development follow-up, not a resumed onboarding or durability test.

Restore one immutable, synthetically accepted setup into fresh native state.
Both arms receive the same accepted policy, owner facts and source access. The
card service adds typed execution, not privileged business information. All
onboarding costs remain reported. No messages, schedules, retries or repairs.
This compares the installed skill/native-analysis-tool package, not an isolated
card-evaluation ablation; only the common company-tool surface is identical.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter, RequestBudget
from evaluations.bootstrap_scenarios import public_episode, score_submission
from evaluations.codex_trial_transport import codex_episode
from evaluations.domain_context_onboarding_trial import (
    RecurringEpisode,
    clarified_development_scenario,
    failure_detail,
    native_context,
    pinned_codex,
    public_brief,
    usage_totals,
)
from evaluations.reviewed_setup import load_reviewed_setup, restore_reviewed_card
from scripts.binary_provenance import verify_binary
from signalweave.models import SourceRef

PROTOCOL = "reviewed-setup-reports-v1"
LIMITS = {"agent_invocations": 6, "jev_attempts": 3, "tools_per_report": 12,
          "seconds_per_report": 180, "between_invocation_input_stop": 600_000,
          "between_invocation_uncached_stop": 150_000}
INSTRUCTIONS = (
    "You are a fresh analytics reporting agent using an already accepted development setup. "
    "Use only the supplied trial-server tools; do not enumerate other MCP tools or resources. "
    "Fetch this period's evidence; previous measurements in notes are not current truth. "
    "Use the supplied accepted policy, definitions and owner facts. "
    "Write a concise useful report: supported changes, significance under the owner's policy, "
    "limitations, proposed recipients and next step. Cite exact source references beside claims. "
    "Distinguish observation, accounting decomposition, association and hypothesis; do not infer causation. "
    "Do not invent missing measurements or policy, edit setup, ask the owner, schedule or send. "
    "Use calculate for arithmetic if needed, then submit_analysis to record your draft only. "
    "Use only keys in numeric_vocabulary for numeric_claims; values and units must follow evidence."
)


def cohort_settings(cohort):
    if cohort == "paired":
        return PROTOCOL, dict(LIMITS), (False, True)
    if cohort == "interpretation-repair-v1":
        return "handoff-interpretation-v1", {
            **LIMITS, "agent_invocations": 3, "between_invocation_input_stop": 300_000,
            "between_invocation_uncached_stop": 90_000,
        }, (True,)
    raise ValueError("unknown report cohort")


def common_context(public, card):
    """Equal information, including the treatment card's policy, for the control."""
    return {"accepted_policy": card.execution_payload(), "owner_answers": public["owner_answers"],
            "glossary": public["glossary"]}


def summarize_usage(audit, onboarding):
    known = usage_totals(audit.events)
    started = sum(e.get("kind") == "api.request" and e.get("provider") == "openai" for e in audit.events)
    complete = (known["responses"] == started and not any(
        e.get("kind") == "api.error" and e.get("provider") == "openai" for e in audit.events
    ))
    return {"agent_invocations_started": started, "usage_known": complete,
            "usage": known if complete else {"status": "unknown"},
            "known_partial_usage": None if complete else known,
            "usage_including_accepted_onboarding": {
                key: value + onboarding[key] for key, value in known.items()
            } if complete else {"status": "unknown"}}


def score_report(scenario, period_id, submission, inspected):
    """Keep the original lookup score; a reporting agent is given owner context."""
    score = score_submission(scenario, period_id, submission,
                             inspected_refs=inspected, asked_owner_topics=[])
    score["owner_question_topic_coverage_complete"] = score.pop("owner_policy_complete")
    score["exact_including_owner_lookup"] = score.pop("exact")
    score["owner_context_supplied"] = True
    score["report_errors"] = [error for error in score["errors"] if error != "missing_owner_policy_lookup"]
    score["report_exact"] = bool(
        score["valid_submission"] and score["outcome_correct"] and score["recipients_correct"]
        and score["provenance_complete"] and score["evidence_recall"] == 1
        and score["numeric_recall"] == 1 and not score["unsupported_numeric_facts"]
        and not score["unsupported_claim_types"] and not score["report_errors"]
    )
    return score


def before_invocation(audit, limits, executable, expected_binary_hash):
    if hashlib.sha256(Path(executable).read_bytes()).hexdigest() != expected_binary_hash:
        raise RuntimeError("pinned executable changed")
    summary = summarize_usage(audit, {key: 0 for key in usage_totals([])})
    if not summary["usage_known"]:
        raise RuntimeError("unknown agent usage; stop without retry")
    usage = summary["usage"]
    if (summary["agent_invocations_started"] >= limits["agent_invocations"]
            or usage["input_tokens"] >= limits["between_invocation_input_stop"]
            or usage["uncached_input_tokens"] >= limits["between_invocation_uncached_stop"]):
        raise RuntimeError("preregistered between-invocation stop reached")


async def run(args):
    protocol, limits, arms = cohort_settings(getattr(args, "cohort", "paired"))
    accepted, card = load_reviewed_setup(Path(args.accepted_report), Path(args.accepted_trace))
    scenario = clarified_development_scenario()
    scenario_hash = hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest()
    if accepted["scenario_sha256"] != scenario_hash or card.principal_tenant != scenario["scenario_id"]:
        raise ValueError("accepted setup and unchanged development scenario do not match")
    public = public_episode(scenario)
    binary = Path(args.binary).resolve()
    identity = verify_binary(binary)
    codex = await pinned_codex(args.codex_executable)
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    audit = Audit(path=output / "trace.jsonl", secrets=(Path(args.key_file).read_text().strip(),))
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    budget = RequestBudget(limit=limits["jev_attempts"] if args.run else 0)
    report = {"protocol": protocol, "limits": limits, "build": identity, "codex": codex,
              "arms": ["signalweave" if treatment else "baseline" for treatment in arms],
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scenario_sha256": scenario_hash, "preflight_only": not args.run, "episodes": [],
              "accepted_onboarding_usage": accepted["usage"],
              "accepted_report_sha256": hashlib.sha256(Path(args.accepted_report).read_bytes()).hexdigest(),
              "restoration": "Exact accepted card in fresh SQLite fixture, not surviving native state or a new public approval.",
              "limitations": ["One development company, three supplied periods; not a holdout or customer trial.",
                              "Accepted policy/owner context, generic source MCP and bounded arithmetic are supplied; arbitrary scripts disabled.",
                              "Report-only role exposes only its dispatchable read/evaluation tools, not the whole production authoring profile.",
                              "No delivery, scheduling, context pins, restored context graph or cross-card reuse.",
                              "All older stopped cohorts and unknown costs remain separate; this is not project-total accounting."]}
    if arms == (True,):
        report["limitations"].append(
            "Treatment-only interpretation repair on known development periods; no fresh baseline or superiority estimate."
        )
    else:
        report["limitations"].append(
            "Whole SignalWeave skill/native analysis tools versus the control with equal business information; not isolated card evaluation."
        )

    def save():
        report.update(summarize_usage(audit, accepted["usage"]))
        report["provider_attempts"] = budget.used
        report["provider_usage"] = [event.get("usage") for event in audit.events
                                    if event.get("kind") == "api.response" and event.get("provider") == "jev"]
        report["provider_usage_known"] = (
            len(report["provider_usage"]) == budget.used
            and not any(event.get("kind") in {"api.error", "api.rejected"}
                        and event.get("provider") == "jev" for event in audit.events)
            and all(isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0
                    for key in ("input_tokens", "output_tokens")) for usage in report["provider_usage"])
        )
        (output / "report.json").write_text(json.dumps(audit.redact(report), indent=2) + "\n")

    try:
        with tempfile.TemporaryDirectory(prefix="accepted-setup-report-", dir=output) as temporary:
            root = Path(temporary)
            async with native_context(binary, Path(args.key_file).resolve(), public, adapter, audit,
                                      root, request_budget=budget) as (native, skill):
                restore_reviewed_card(root / "native-home" / "state" / "signalweave.db", card)
                _, restored = await native.call_tool("get_insight_card", {
                    "card_id": card.id, "response_mode": "full", "include_history": True,
                })
                if restored != card.model_dump(mode="json"):
                    raise RuntimeError("native restored snapshot differs; do not repair")
                report["restored_card_verified"] = {"id": card.id, "version": card.version,
                                                     "approved": card.status.value == "approved"}
                audit.emit("fixture.restored", card_id=card.id, card_version=card.version,
                           public_approval_exercised=False, original_native_state_survived=False)
                context = common_context(public, card)
                notes = json.dumps(context, sort_keys=True)
                clock = datetime.now(timezone.utc)
                for period in scenario["public"]["periods"]:
                    for treatment in arms:
                        adapter.set_period(period, clock)
                        adapter.inspections = 0
                        adapter.inspected.clear()
                        arm = "signalweave" if treatment else "baseline"
                        audit.episode = f"{arm}:{period['period_id']}"
                        key = protocol + ":" + period["period_id"]
                        session = RecurringEpisode(public, adapter, native if treatment else None,
                                                   notes=notes, approved_card_id=card.id if treatment else None,
                                                   approved_card_version=card.version if treatment else None, run_key=key)
                        specs = await session.specs()
                        if any(item["name"] not in session.ANALYSIS_TOOLS | {"calculate", "submit_analysis"}
                               for item in specs):
                            raise RuntimeError("report tools do not match dispatch scope")
                        if not args.run:
                            source = card.sources[0]
                            _, snapshot = await native.call_tool("inspect_resource", {
                                "adapter": source.adapter, "resource": source.resource,
                            })
                            expected = await adapter.inspect(SourceRef(
                                key=snapshot["source_key"], adapter=source.adapter,
                                resource=source.resource, label=source.label,
                            ))
                            fields = ("observations", "evidence", "analytical_comparisons")
                            if any(snapshot[field] != expected.model_dump(mode="json")[field] for field in fields):
                                raise RuntimeError("source roundtrip changed analytical facts")
                            continue
                        before_invocation(audit, limits, codex["path"], codex["sha256"])
                        if hashlib.sha256(binary.read_bytes()).hexdigest() != identity["binary_sha256"]:
                            raise RuntimeError("native binary changed")
                        instructions = INSTRUCTIONS
                        if treatment:
                            instructions += (
                                " Evaluate the exact approved card once using supplied card_id and idempotency_key. "
                                "Use compact mode for normal work, full only for a necessary audit. The decision is "
                                "evidence for your report, not a causal explanation or permission to invent data.\n" + skill
                            )
                        result = await codex_episode(
                            session, key=None, effort="medium", budget=None, audit=audit,
                            max_turns=12, max_tool_calls=limits["tools_per_report"], max_output_tokens=3000,
                            timeout_seconds=limits["seconds_per_report"], model="gpt-6-luna",
                            codex_executable=codex["path"], accounting_drain=True,
                            instructions_override=instructions,
                            prompt_override={"business": public_brief(public), "accepted_context": context,
                                             "period": adapter.period_context,
                                             "card_id": card.id if treatment else None,
                                             "idempotency_key": key if treatment else None,
                                             "numeric_vocabulary": public["numeric_vocabulary"]},
                        )
                        entry = {"arm": arm, "period_id": period["period_id"], "agent": result,
                                 "submission": session.submission, "source_reads": adapter.inspections,
                                 "native_calls": session.native_calls,
                                 "approved_card_execution_verified": session.evaluation_verified if treatment else None}
                        if session.submission:
                            entry["structured_score"] = score_report(
                                scenario, period["period_id"], session.submission, adapter.inspected,
                            )
                        report["episodes"].append(entry)
                        save()
                        if not report["usage_known"] or not report["provider_usage_known"]:
                            raise RuntimeError("unknown agent/provider usage; no retry")
                        if result["status"] != "complete" or (treatment and not session.evaluation_verified):
                            raise RuntimeError("report or approved-card execution incomplete; no retry")
                save()
                if not report["provider_usage_known"] or (not args.run and budget.used):
                    raise RuntimeError("preflight/provider accounting boundary failed")
                report["completed"] = True
    except Exception as error:  # noqa: BLE001 - retain partial/failed evidence
        report["failure"] = failure_detail(error)
    finally:
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "key-file", "codex-executable", "accepted-report", "accepted-trace", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--cohort", choices=["paired", "interpretation-repair-v1"], default="paired",
                        help="Paired study or separately preregistered treatment-only repair; never resumes a closed run")
    parser.add_argument("--run", action="store_true", help="Explicitly authorize the one bounded live report cohort")
    report = asyncio.run(run(parser.parse_args()))
    print(json.dumps({"completed": report.get("completed", False), "failure": report.get("failure"),
                      "episodes": len(report["episodes"]), "provider_attempts": report["provider_attempts"]}))


if __name__ == "__main__":
    main()

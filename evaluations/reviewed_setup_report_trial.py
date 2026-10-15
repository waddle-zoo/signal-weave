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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import validate

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
from evaluations.human_report_episode import HumanReportEpisode
from evaluations.reviewed_setup import load_reviewed_setup, restore_reviewed_card
from scripts.binary_provenance import verify_binary
from signalweave.models import SourceRef

PROTOCOL = "reviewed-setup-reports-v1"
CALENDAR_PAIRED = "calendar-paired-v1"
GROUNDED_REPORTS = "grounded-reports-v2"
HUMAN_READOUT = "human-readout-v1"
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
HUMAN_INSTRUCTIONS = (
    "You are a fresh analytics reporting agent using an already accepted development setup. "
    "Use only the supplied trial-server tools and current source evidence; old measurements are not current truth. "
    "Prepare the concise message a business reader should receive: what matters, why under the owner's policy, "
    "material known values, limits, intended policy-triggered routes and useful next step. "
    "Cite actual source references beside measurements; workflow receipts support workflow facts only. "
    "Distinguish accounting, association and hypothesis from causation; do not invent significance or missingness. "
    "Do not edit setup, ask the owner, schedule or send. Use calculate if needed. "
    "Finish with record_report using only outcome, recipients and summary. Ignore has no triggered routes; "
    "a routine report audience may be named in the message. No numeric-claim registry is required. Stop after success."
)


def cohort_settings(cohort):
    if cohort == "paired":
        return PROTOCOL, dict(LIMITS), (False, True)
    if cohort == CALENDAR_PAIRED:
        return CALENDAR_PAIRED, dict(LIMITS), (False, True)
    if cohort == GROUNDED_REPORTS:
        return GROUNDED_REPORTS, dict(LIMITS), (False, True)
    if cohort == HUMAN_READOUT:
        return HUMAN_READOUT, dict(LIMITS), (False, True)
    if cohort == "interpretation-repair-v1":
        return "handoff-interpretation-v1", {
            **LIMITS, "agent_invocations": 3, "between_invocation_input_stop": 300_000,
            "between_invocation_uncached_stop": 90_000,
        }, (True,)
    raise ValueError("unknown report cohort")


def _utc_datetime(value, field):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO datetime") from exc
    else:
        raise ValueError(f"{field} must be an aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def calendar_measurement_rebase(periods, clock):
    """Map weekly fixture cutoffs to current UTC Monday while preserving spacing."""
    capture_at = _utc_datetime(clock, "clock")
    if not periods:
        raise ValueError("calendar-paired-v1 requires monitoring periods")
    cutoffs = [_utc_datetime(period["as_of"], f"periods[{index}].as_of")
               for index, period in enumerate(periods)]
    if any(cutoff.weekday() != 0 or cutoff.time() != datetime.min.time() for cutoff in cutoffs):
        raise ValueError("calendar-paired-v1 requires Monday 00:00 UTC fixture cutoffs")
    latest_original = max(cutoffs)
    if any((latest_original - cutoff).total_seconds() % (7 * 24 * 60 * 60) for cutoff in cutoffs):
        raise ValueError("calendar-paired-v1 fixture cutoffs must be whole weeks apart")
    latest_monday = capture_at.replace(hour=0, minute=0, second=0, microsecond=0)
    latest_monday -= timedelta(days=latest_monday.weekday())
    return latest_monday - latest_original, latest_monday


def common_context(public, card):
    """Equal information, including the treatment card's policy, for the control."""
    return {"accepted_policy": card.execution_payload(), "owner_answers": public["owner_answers"],
            "glossary": public["glossary"]}


def record_tool_inventory(report, arm, specs):
    """Pin actual advertised contracts, including the treatment-only surface."""
    inventory = {item["name"]: hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                 for item in specs}
    if len(inventory) != len(specs):
        raise ValueError("duplicate advertised tool name")
    inventories = report.setdefault("report_tool_inventories", {})
    if arm in inventories and inventories[arm] != inventory:
        raise ValueError("advertised report tools changed between periods")
    inventories[arm] = inventory
    if {"baseline", "signalweave"} <= inventories.keys():
        baseline, treatment = inventories["baseline"], inventories["signalweave"]
        if any(treatment.get(name) != digest for name, digest in baseline.items()):
            raise ValueError("common company/report tools differ between arms")
        report["treatment_additional_tools"] = sorted(set(treatment) - set(baseline))


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
    cohort = getattr(args, "cohort", "paired")
    protocol, limits, arms = cohort_settings(cohort)
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
    if cohort == HUMAN_READOUT:
        report["planned_episode_count"] = len(arms) * len(scenario["public"]["periods"])
        report["report_review_required"] = True
        report["report_sink"] = "record_report"
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
                measurement_offset = None
                if cohort in {CALENDAR_PAIRED, GROUNDED_REPORTS, HUMAN_READOUT}:
                    measurement_offset, latest_cutoff = calendar_measurement_rebase(
                        scenario["public"]["periods"], clock,
                    )
                    report["cohort_clock_semantics"] = {
                        "measurement_rebase": "one shared whole-week UTC offset",
                        "latest_measurement_cutoff": latest_cutoff.isoformat(),
                        "measurement_offset_seconds": int(measurement_offset.total_seconds()),
                        "query_capture_at": clock.isoformat(),
                        "source_capture_age": "preserved relative to each fixture period as_of",
                        "source_data": "synthetic fixture; not warehouse freshness evidence",
                    }
                for period in scenario["public"]["periods"]:
                    for treatment in arms:
                        if cohort in {CALENDAR_PAIRED, GROUNDED_REPORTS, HUMAN_READOUT}:
                            adapter.set_period(period, clock, measurement_offset=measurement_offset)
                        else:
                            adapter.set_period(period, clock)
                        adapter.inspections = 0
                        adapter.inspected.clear()
                        arm = "signalweave" if treatment else "baseline"
                        audit.episode = f"{arm}:{period['period_id']}"
                        key = protocol + ":" + period["period_id"]
                        episode_class = HumanReportEpisode if cohort == HUMAN_READOUT else RecurringEpisode
                        session = episode_class(public, adapter, native if treatment else None,
                                                   notes=notes, approved_card_id=card.id if treatment else None,
                                                   approved_card_version=card.version if treatment else None, run_key=key,
                                                   reporting_contract=cohort == GROUNDED_REPORTS)
                        specs = await session.specs()
                        sink_name = "record_report" if cohort == HUMAN_READOUT else "submit_analysis"
                        if any(item["name"] not in session.ANALYSIS_TOOLS | {"calculate", sink_name}
                               for item in specs):
                            raise RuntimeError("report tools do not match dispatch scope")
                        if cohort == HUMAN_READOUT:
                            record_tool_inventory(report, arm, specs)
                        if cohort in {GROUNDED_REPORTS, HUMAN_READOUT}:
                            schema = json.loads(json.dumps(next(
                                item["parameters"] for item in specs if item["name"] == sink_name
                            )))
                            probe = {"outcome": "investigate", "recipients": [],
                                     "summary": "Offline schema probe, not a business result."}
                            if cohort == GROUNDED_REPORTS:
                                definitions = public["submission_contract"]["numeric_definitions"]
                                probe.update({
                                      "evidence_refs": ["schema-probe|source"],
                                      "numeric_claims": [
                                          {"fact": fact, "value": 0, "unit": definition["unit"],
                                           "evidence_refs": ["schema-probe|source"]}
                                          for fact, definition in definitions.items()
                                      ]})
                            validate(probe, schema)
                            digest = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
                            previous = report.setdefault("report_contract_schema_sha256", digest)
                            if previous != digest:
                                raise RuntimeError("shared report schema changed across arms or periods")
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
                        instructions = HUMAN_INSTRUCTIONS if cohort == HUMAN_READOUT else INSTRUCTIONS
                        if cohort in {CALENDAR_PAIRED, GROUNDED_REPORTS, HUMAN_READOUT}:
                            instructions += (
                                " In the supplied period, as_of is the measurement cutoff, while captured_at "
                                "is the separate simulated source-read clock. Use the source's actual interval "
                                "bounds and coverage, not capture time, to interpret a reporting week."
                            )
                        if cohort == GROUNDED_REPORTS:
                            instructions += (
                                " Structured recipients mean policy-triggered alert/review routes, not routine "
                                "report audience; ignore has no such recipients. Structured evidence_refs cite "
                                "underlying source data only. Cite an actual workflow receipt in summary prose "
                                "for workflow facts, never as measurement evidence. The supplied numeric definitions "
                                "bind each fact to a unit and meaning. Report other supported counts or quantities "
                                "in source-cited prose rather than relabeling them as registered rate facts."
                            )
                        if treatment:
                            instructions += (
                                " Evaluate the exact approved card once using supplied card_id and idempotency_key. "
                                "Use compact mode for normal work, full only for a necessary audit. The decision is "
                                "evidence for your report, not a causal explanation or permission to invent data.\n" + skill
                            )
                        prompt = {"business": public_brief(public), "accepted_context": context,
                                  "period": adapter.period_context,
                                  "card_id": card.id if treatment else None,
                                  "idempotency_key": key if treatment else None,
                                  "numeric_vocabulary": public["numeric_vocabulary"]}
                        if cohort == GROUNDED_REPORTS:
                            prompt["submission_contract"] = public["submission_contract"]
                        if cohort == HUMAN_READOUT:
                            prompt.pop("numeric_vocabulary")
                            prompt["measurement_definitions"] = public["submission_contract"]["numeric_definitions"]
                        result = await codex_episode(
                            session, key=None, effort="medium", budget=None, audit=audit,
                            max_turns=12, max_tool_calls=limits["tools_per_report"], max_output_tokens=3000,
                            timeout_seconds=limits["seconds_per_report"], model="gpt-6-luna",
                            codex_executable=codex["path"], accounting_drain=True,
                            instructions_override=instructions,
                            prompt_override=prompt,
                        )
                        entry = {"arm": arm, "period_id": period["period_id"], "agent": result,
                                 "submission": session.submission, "source_reads": adapter.inspections,
                                 "native_calls": session.native_calls,
                                 "approved_card_execution_verified": session.evaluation_verified if treatment else None}
                        if session.submission:
                            if cohort == HUMAN_READOUT:
                                label = scenario["private"]["periods"][period["period_id"]]
                                entry["routing_diagnostics"] = {
                                    "outcome_correct": session.submission["outcome"] == label["outcome"],
                                    "recipients_correct": set(session.submission["recipients"]) == set(label["recipients"]),
                                    "scope": "Policy fields only; factual/provenance/narrative review still required.",
                                }
                            else:
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
    parser.add_argument("--cohort", choices=["paired", "interpretation-repair-v1", CALENDAR_PAIRED, GROUNDED_REPORTS, HUMAN_READOUT], default="paired",
                        help="Paired study, treatment-only repair, or calendar-aligned paired report cohort")
    parser.add_argument("--run", action="store_true", help="Explicitly authorize the one bounded live report cohort")
    report = asyncio.run(run(parser.parse_args()))
    print(json.dumps({"completed": report.get("completed", False), "failure": report.get("failure"),
                      "episodes": len(report["episodes"]), "provider_attempts": report["provider_attempts"]}))


if __name__ == "__main__":
    main()

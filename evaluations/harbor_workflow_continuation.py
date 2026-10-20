"""Expert-assisted recurrence after a CLOSED onboarding pair; never rescore it.

Reuses actual author notes and policy, current native MCP and the shared source
bridge. No human-install, unassisted-onboarding or population-level lift claim.
Preparation and expert review precede two opt-in, single-attempt analysts.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from evaluations import harbor_workflow_journey as journey
from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.codex_trial_transport import codex_episode
from evaluations.harbor_history_preflight import _errors
from evaluations.harbor_workflow_actor import HarborWorkflowActor
from evaluations.harbor_workflow_preflight import _activate, _sha
from evaluations.raw_superset_onboarding import usage_snapshot

PROTOCOL = "harbor-expert-assisted-continuation-v1"
LIMITS = {"total_analysts_including_parent": 4, "jev_requests": 6,
          "between_actor_input_stop_including_parent": 2_500_000,
          "between_actor_uncached_stop_including_parent": 300_000,
          "tools_per_actor": 60, "response_seconds": 420}
CLARIFICATION = (
    "Expert clarification for BOTH arms: existing company query_readonly/export_query tools remain "
    "authorized for ticket detail; native card scope limits automatic native reads, not your companion "
    "tools. An export alias is a transient result, not a registered saved catalog resource; retain and "
    "rerun its SQL. Missing prior handoff state means newness is unknown, not that known qualifying "
    "records cannot be handed off. Resolution-only work may be a separate advisory but is not a newly "
    "approved recurring exception trigger. These are historical source cutoffs, not today's business."
)


def parents(root, metadata):
    result = {}
    for arm, expected in metadata["parent_reports"].items():
        path = Path(metadata["parent"]) / f"onboarding-{arm}.json"
        if _sha(path) != expected:
            raise ValueError("Closed parent report changed")
        report = journey.read(path)
        if not report["process_complete"] or not report["usage"]["known"]:
            raise ValueError("Parent work incomplete or usage unknown")
        result[arm] = report
    return result


def admission(root, metadata):
    reports = list(parents(root, metadata).values())
    for arm in journey.ARMS:
        path = root / f"recurring-{arm}.json"
        if path.with_suffix(".claimed").exists() and not path.exists():
            raise ValueError("Claim without a terminal report; do not retry")
        if path.exists():
            reports.append(journey.read(path))
    if any(not r["process_complete"] or not r["usage"]["known"]
           or not r["provider_usage"]["known"] for r in reports):
        raise ValueError("Prior work incomplete or usage unknown; no next actor")
    inputs = sum(r["usage"]["usage"]["input_tokens"] for r in reports)
    uncached = sum(r["usage"]["usage"]["uncached_input_tokens"] for r in reports)
    used = sum(r["provider_attempts"] for r in reports)
    if (len(reports) >= LIMITS["total_analysts_including_parent"]
            or inputs >= LIMITS["between_actor_input_stop_including_parent"]
            or uncached >= LIMITS["between_actor_uncached_stop_including_parent"]
            or used > LIMITS["jev_requests"]):
        raise ValueError("Cumulative between-actor stop reached")
    return used


async def prepare(parent, root, binary, codex, key_file):
    parent, root = Path(parent).absolute(), Path(root).absolute()
    metadata = {"protocol": PROTOCOL, "parent": str(parent), "limits": LIMITS,
                "parent_reports": {arm: _sha(parent / f"onboarding-{arm}.json") for arm in journey.ARMS},
                "method_sha256": _sha(__file__), "common_clarification": CLARIFICATION,
                "assistance": "Operator re-imports actual draft with disclosed repairs; simulated expert reviews it. Human effort/review cost unmeasured. Original cohort remains closed."}
    original = parents(root, metadata)["signalweave"]["card"]
    await journey.prepare(binary, codex, key_file, root)
    old = journey.read(parent / "study.json")
    study = journey.read(root / "study.json")
    if [r["sha256"] for r in old["snapshots"]] != [r["sha256"] for r in study["snapshots"]]:
        raise ValueError("Continuation source differs from parent")
    # Fresh native store, not mutation or relabeling of the original draft.
    arguments = {key: original[key] for key in (
        "title", "what_to_watch", "why_watch", "watch_for", "questions", "numeric_conditions",
        "evidence_requirements", "decision_guidance", "follow_up_guidance", "delivery_methods",
        "action_confidence_threshold", "retrieval_mode", "investigation_mode")}
    arguments.update(selected_sources=[{"ref": f"{s['adapter']}|{s['resource']}", "key": s["key"]}
                                      for s in original["sources"]],
                     comparison_windows=[], max_source_age_hours=None, response_mode="full")
    old_requirement = ("A complete handoff must identify each ticket and the clock crossed; this selected aggregate "
                       "contains counts only, so a ticket-level detail source must be approved and included before "
                       "a repeated run can produce that list.")
    if old_requirement not in arguments["decision_guidance"]:
        raise ValueError("Actual parent policy differs; inspect before repairing")
    arguments["decision_guidance"] = arguments["decision_guidance"].replace(old_requirement,
        "A complete handoff must identify tickets and clocks using the agent's existing authorized company SQL. "
        "The selected aggregate supplies the trigger; companion detail registration is not a prerequisite.")
    arguments["follow_up_guidance"] = arguments["follow_up_guidance"].replace(
        "Ticket IDs require an approved detail source.", "Use existing authorized companion SQL for ticket IDs and clocks.")
    for method in arguments["delivery_methods"]:
        method["instructions"] = method["instructions"].replace(
            "after an approved detail source is added", "using the agent's existing authorized companion SQL")
    audit, budget = Audit(), RequestBudget(0)
    async with journey.sessions(study, root, "signalweave", audit, budget) as (_, native):
        draft = await journey._call(native, "onboard_insight_card", arguments)
        review = await journey._call(native, "review_insight_card", {
            "card_id": draft["card"]["id"], "response_mode": "full"})
        card = await journey._call(native, "get_insight_card", {
            "card_id": draft["card"]["id"], "response_mode": "full"})
    if budget.used or budget.exhausted:
        raise ValueError("Preparation must not perform inference")
    metadata.update(card=card, review=review, imported_arguments=arguments,
                    card_digest=journey.digest(card), preparation_provider_usage=journey.provider_usage(audit, 0))
    journey.write(root / "continuation.json", metadata)
    return {"prepared": True, "provider_requests": 0, "card_digest": metadata["card_digest"]}


async def run(root, arm, review_path):
    root = Path(root).absolute()
    metadata, study = journey.read(root / "continuation.json"), journey.read(root / "study.json")
    if metadata["protocol"] != PROTOCOL or metadata["method_sha256"] != _sha(__file__):
        raise ValueError("Continuation method changed")
    journey.verify_study(study)
    own = parents(root, metadata)[arm]
    review = journey.read(review_path)
    if (review.get("approved_for_shadow_recurrence") is not True
            or review.get("card_digest") != metadata["card_digest"]
            or review.get("parent_reports") != metadata["parent_reports"]
            or not review.get("reviewer") or review.get("reviewer_type") != "simulated_expert"
            or not review.get("source_selection_reason") or not review.get("assessments")):
        raise ValueError("Explicit review of current draft and both parent artifacts required")
    with journey.single_actor(root):
        used = admission(root, metadata)
        journey._private_file(root / f"recurring-{arm}.claimed", PROTOCOL)
        trace = root / f"recurring-{arm}.jsonl"
        journey._private_file(trace, "")
        audit = Audit(path=trace, episode=f"{PROTOCOL}:{arm}")
        audit.secrets = (Path(study["key_file"]).read_text().strip(),)
        budget = RequestBudget(LIMITS["jev_requests"] - used)
        report = {"protocol": PROTOCOL, "arm": arm, "process_complete": False, "errors": [],
                  "frontier_invocations": 0, "exercise_review": review, "business_assessment": "pending"}
        actor, native, started = None, None, time.perf_counter()
        try:
            active = root / arm / "active.sqlite3"
            current = _sha(active)
            if current != study["snapshots"][0]["sha256"]:
                raise ValueError("Start at ordinary observation")

            async def advance(index):
                nonlocal current
                current = _activate(Path(study["snapshots"][index]["path"]), active, current)
                audit.emit("caller.source_advanced", index=index, snapshot_sha256=current)

            async with journey.sessions(study, root, arm, audit, budget) as (source, native):
                card_id = metadata["card"]["id"] if native else None
                if native:
                    card = await journey._call(native, "get_insight_card", {"card_id": card_id, "response_mode": "full"})
                    if journey.digest(card) != metadata["card_digest"]:
                        raise ValueError("Reviewed card changed")
                    handoff = metadata["review"]["approval_handoff"]
                    report["approval"] = await journey._call(native, "approve_insight_card", {
                        **handoff["arguments_after_owner_confirmation"],
                        "source_selection_reason": review["source_selection_reason"]})
                actor = HarborWorkflowActor(source, audit, journey.owner_context(), native=native,
                    phase="recurring", notes=own["notes"], card_id=card_id, advance=advance,
                    observation_cutoffs=tuple(r["cutoff"] for r in study["snapshots"]))
                instructions = journey.COMMON + journey.REPEAT + "\n" + CLARIFICATION
                if native:
                    instructions += "\nInstalled SignalWeave skill:\n" + Path(study["skill_path"]).read_text()
                prompt = {"request": "Prepare the three requested internal shadow briefs from the then-current source.",
                    "source_cutoff": study["snapshots"][0]["cutoff"], "reusable_notes": own["notes"],
                    "owner_directory": journey.owner_context()["destinations"],
                    "expert_clarification": CLARIFICATION, "approved_card_id": card_id,
                    "review_status": "Delegated simulated expert approved unanswered-first-response policy for local shadow briefs only; no send or scheduling."}
                report["frontier_invocations"] = 1
                report["episode"] = await codex_episode(actor, key="", effort="xhigh", model="gpt-6-luna",
                    budget=budget, audit=audit, max_turns=1, max_tool_calls=60, max_output_tokens=1,
                    timeout_seconds=420, codex_executable=study["codex"]["path"],
                    instructions_override=instructions, prompt_override=prompt,
                    expected_registry_sha256=study["registry_sha256"], allow_trial_resource_discovery=True,
                    accounting_drain=True, report_remaining_budget=True, strict_single_turn_usage=True,
                    enforce_wall_response_timeout=True, finish_on_final_message=True)
                report["process_complete"] = report["episode"]["status"] == "complete" and len(actor.briefs) == 3
        except Exception as error:  # noqa: BLE001 - retain failed single attempts
            report["errors"] = _errors(error, audit)
        finally:
            if actor:
                report.update(briefs=actor.briefs, notes=actor.notes, queries=actor.queries, native_calls=actor.native_calls)
            report.update(total_stage_seconds=time.perf_counter() - started, provider_attempts=budget.used,
                          provider_usage=journey.provider_usage(audit, budget.used),
                          usage=usage_snapshot(audit.events, report["frontier_invocations"]))
            try:
                journey.verify_study(study)
                parents(root, metadata)
                report["inputs_unchanged"] = True
            except Exception as error:  # noqa: BLE001
                report["inputs_unchanged"] = False
                report["errors"].extend(_errors(error, audit))
            report["policy_path_exercised"] = bool(actor and native and journey.policy_path_exercised(
                actor.native_calls, actor.observation_cutoffs, actor.card_id, report["provider_usage"]))
            report["process_complete"] &= bool(report["usage"]["known"] and report["inputs_unchanged"]
                                                and not report["errors"] and not budget.exhausted)
            journey.write(root / f"recurring-{arm}.json", audit.redact(report))
        return {key: report[key] for key in ("process_complete", "provider_attempts", "policy_path_exercised", "errors")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "actor"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--codex")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--arm", choices=journey.ARMS)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = asyncio.run(prepare(args.parent, args.study, args.binary, args.codex, args.key_file))
    elif not args.execute:
        parser.error("Paid actor requires --execute")
    else:
        result = asyncio.run(run(args.study, args.arm, args.review_file))
    print(result)


if __name__ == "__main__":
    main()

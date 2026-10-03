"""Agent onboarding through the executable, followed by frozen-card MCP replay.

Research only. No reference card is installed and no private future label is
available to the author, the binary, or the source server. Historical owner
examples are explicit training inputs, never described as unseen holdouts.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluations.bootstrap_agent_trial import (
    COMMON_SYSTEM,
    Audit,
    PublicSourceAdapter,
    RequestBudget,
    ToolSession,
    card_fingerprint,
    digest,
    function,
    shift_timestamps,
    usage_summary,
    write_exclusive,
)
from evaluations.bootstrap_owner_review import review_owner_artifact
from evaluations.bootstrap_scenarios import public_scenario
from evaluations.codex_trial_transport import codex_episode
from evaluations.installed_first_report_trial import _file_hash, _git_sha

VERSION = "installed-workflow-v10"


def bind_examples(examples: list[dict], card: dict) -> list[dict]:
    """Identity projection only: never create measurements, policy or labels."""
    sources = {f"{s['adapter']}|{s['resource']}": s for s in card["sources"]}
    methods = {d["destination"]: d["key"] for d in card["delivery_methods"]}
    result = copy.deepcopy(examples)
    for case in result:
        resources = []
        for snapshot in case["resources"]:
            ref = f"{snapshot['adapter']}|{snapshot['resource']}"
            if ref not in sources:
                continue
            key = sources[ref]["key"]
            snapshot["source_key"] = key
            for collection in ("observations", "evidence"):
                for item in snapshot.get(collection, []):
                    item["source_key"] = key
            resources.append(snapshot)
        case["resources"] = resources
        expected = case["expected_delivery_destinations"]
        endpoints = list(expected.values()) if isinstance(expected, dict) else list(expected)
        if any(endpoint not in methods for endpoint in endpoints):
            raise ValueError("Card lacks an owner-required delivery destination; preserve all owner routes.")
        case["expected_delivery_destinations"] = {methods[endpoint]: endpoint for endpoint in endpoints}
        case["expected_delivery_method_keys"] = sorted(case["expected_delivery_destinations"])
        # Labels use canonical refs; the chosen card owns aliases.
        required = case.pop("required_evidence_refs", [])
        if any(ref not in sources for ref in required):
            raise ValueError("Card omits an owner-required evidence source; preserve recurring context.")
        case["required_evidence_source_keys"] = [sources[ref]["key"] for ref in required]
        if "expected_retrieval_refs" not in case:
            raise ValueError("Owner examples need explicit retrieval labels; never derive them from model selection.")
    return result


class InstalledSession(ToolSession):
    def __init__(self, *args, examples, **kwargs):
        super().__init__(*args, **kwargs)
        self.examples = copy.deepcopy(examples)
        self.acceptance_fingerprint = None
        self.acceptance_report_id = None
        self.offered_cases = None

    async def specs(self):
        specs = await super().specs()
        if self.phase == "onboarding":
            specs.append(function(
                "get_owner_examples",
                "Get the synthetic owner's labeled historical examples, bound to this card's source aliases. "
                "These are calibration examples, NOT future monitoring labels. Copy cases unchanged into "
                "evaluate_card_workflow with the returned acceptance_outcomes. Never relabel them.",
                {"card_id": {"type": "string"}}, ["card_id"]))
        return specs

    async def call(self, name, arguments):
        if name == "get_owner_examples" and self.phase == "onboarding":
            card = await self.product("get_insight_card", {"card_id": arguments["card_id"]})
            self.offered_cases = None
            selected = {f"{source['adapter']}|{source['resource']}" for source in card["sources"]}
            required = {ref for case in self.examples for ref in (
                case.get("required_evidence_refs", []) + case.get("expected_retrieval_refs", [])
            )}
            missing = sorted(required - selected)
            if missing:
                # This is the supplied owner's calibration context, not inferred
                # future truth. Do not make the author guess an opaque missing ID.
                return {
                    "status": "needs_source_review", "card_id": card["id"],
                    "missing_required_source_refs": missing,
                    "next_actions": [{"tool": "inspect_source", "arguments": {"ref": ref}} for ref in missing],
                    "message": "Owner-labeled history requires these sources. Inspect them, then revise the card faithfully and request examples again. No source was added and no approval was granted.",
                    "scope": "Supplied historical calibration requirements, not future labels or automatic source discovery.",
                }
            self.offered_cases = bind_examples(self.examples, card)
            return {"cases": self.offered_cases,
                    "acceptance_outcomes": sorted({x["expected_outcome"] for x in self.examples}),
                    "scope": "Synthetic owner-labeled history for calibration; no future cases."}
        if name == "evaluate_card_workflow":
            if self.offered_cases is None or arguments.get("cases") != self.offered_cases:
                raise ValueError("Use all unchanged owner examples from get_owner_examples; do not invent or relabel cases.")
            expected_outcomes = {x["expected_outcome"] for x in self.examples}
            if set(arguments.get("acceptance_outcomes") or []) != expected_outcomes:
                raise ValueError("Cover every owner-labeled disposition with acceptance_outcomes.")
            if arguments.get("thresholds") is not None:
                raise ValueError("Use the unmodified production acceptance thresholds.")
            card = await self.product("get_insight_card", {"card_id": arguments["card_id"]})
            if bind_examples(self.examples, card) != self.offered_cases:
                raise ValueError("Card source bindings changed; fetch current owner examples.")
            result = await super().call(name, arguments)
            if result.get("status") == "approved":
                current = await self.product("get_insight_card", {"card_id": arguments["card_id"]})
                self.acceptance_fingerprint = card_fingerprint(current)
                self.acceptance_report_id = result["certification_report_id"]
            return result
        if name in {"approve_insight_card", "finish_setup"}:
            card = await self.product("get_insight_card", {"card_id": arguments["card_id"]})
            if self.acceptance_fingerprint != card_fingerprint(card):
                raise ValueError("This trial requires passing the owner's historical examples for the current card first.")
            if name == "approve_insight_card" and arguments.get("workflow_report_id") != self.acceptance_report_id:
                raise ValueError("Pass the current accepted workflow_report_id when approving.")
        return await super().call(name, arguments)


def score_native(output: dict, card: dict, label: dict, destinations: list[dict]) -> dict:
    """Recompute from native result, not saved pass flags or the final LLM prose."""
    result = output.get("result") or {}
    methods = result.get("delivery_methods", [])
    directory = {d["destination"]: d["key"] for d in destinations}
    actual_destinations = [d.get("destination") for d in methods]
    actual = {directory.get(endpoint, f"UNAUTHORIZED:{endpoint}") for endpoint in actual_destinations}
    refs = {s["key"]: f"{s['adapter']}|{s['resource']}" for s in card["sources"]}
    present = {refs.get(item.get("source_key")) for item in
               [*result.get("evidence", []), *result.get("observations", [])]}
    required = set(label["required_evidence_refs"])
    outcome_correct = result.get("outcome") == label["outcome"]
    routes_correct = actual == set(label["recipients"])
    evidence_complete = required <= present and bool(result.get("evidence"))
    receipt, report, returned_card = (output.get(name) or {} for name in ("receipt", "report", "card"))
    identity_valid = bool(card.get("id")) and all(
        value == card["id"] for value in
        (result.get("card_id"), report.get("card_id"), receipt.get("card_id"), returned_card.get("id"))
    ) and receipt.get("card_version") == card.get("version")
    delivery_disabled = (receipt.get("delivery_enabled") is False
                         and receipt.get("delivery_mode") == "shadow"
                         and receipt.get("status") == "delivery_disabled")
    consistency = (report.get("outcome") == receipt.get("outcome") == result.get("outcome")
                   and result.get("report") == report
                   and sorted(receipt.get("delivery_method_keys", [])) == sorted(d.get("key", "") for d in methods))
    plan_unchanged = bool(card.get("compiled_plan")) and output.get("plan") == card["compiled_plan"]
    return {"exact": bool(outcome_correct and routes_correct and evidence_complete
                          and identity_valid and delivery_disabled and consistency and plan_unchanged),
            "identity_valid": identity_valid, "delivery_disabled": delivery_disabled,
            "consistency": consistency, "plan_unchanged": plan_unchanged,
            "outcome_correct": outcome_correct, "routes_correct": routes_correct,
            "evidence_complete": evidence_complete, "missing_evidence": sorted(required - present),
            "expected_outcome": label["outcome"], "actual_outcome": result.get("outcome"),
            "expected_recipients": label["recipients"], "actual_recipients": sorted(actual),
            "scope": "Native route and source-presence contract; not narrative or causal correctness."}


def onboarding_instructions(server) -> str:
    unavailable = (
        "No independent historical acceptance snapshots are supplied: "
        "record acceptance as unassessed, do not invent examples, and do not claim unattended "
        "delivery is ready. "
    )
    assert unavailable in COMMON_SYSTEM
    return COMMON_SYSTEM.replace(unavailable, "") + (
        " You are using the installed SignalWeave MCP, not an in-process imitation. "
        "Read get_signalweave_guide(task='monitor'). Ask the owner, inspect relevant sources, "
        "draft your own minimal card, inspect it with get_insight_card and preview it. "
        "The owner has supplied labeled historical examples: get_owner_examples(card_id) "
        "returns them. Copy these unchanged, including each historical as_of clock, "
        "to evaluate_card_workflow with acceptance_outcomes "
        "and max_concurrency=1. If the report fails, inspect the actual mismatch and clarify "
        "the card faithfully; never change labels, source measurements, or confidence floors. "
        "After passing, save reusable notes and request_synthetic_owner_approval. An independent "
        "owner model reviews the policy; correct its feedback if needed (three reviews max). "
        "Then approve_insight_card with the passing workflow_report_id and finish_setup. "
        "Authorization and acceptance are distinct. All later runs remain delivery-disabled. "
        "Do not fetch future periods or use shell, filesystem or web tools. "
        "Do not attempt to create a scheduler or send a message. "
        "\nProduction MCP instructions:\n" + (server.instructions or ""))


async def run_trial(scenarios, *, binary, key_file, output, jev_budget=100, live=False,
                    stage_gate=6, fixture_seed=None):
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    protocol = {"version": VERSION, "code": _git_sha(), "binary_sha256": _file_hash(binary),
                "harness_sha256": {name: _file_hash(Path(__file__).with_name(name)) for name in
                                   ("installed_workflow_trial.py", "installed_trial_transport.py",
                                    "installed_northstar_cases.py", "installed_transfer_cases.py", "bootstrap_agent_trial.py",
                                    "bootstrap_owner_review.py", "codex_trial_transport.py")},
                "dataset_sha256": digest(scenarios), "fixture_seed": fixture_seed,
                "jev_attempt_limit": jev_budget,
                "stop_expansion_after_first_cases": stage_gate,
                "author_model": "gpt-5.6-luna", "owner_review_model": "gpt-5.6-luna",
                "companies": len(scenarios), "monitoring_cases": sum(len(s["public"]["periods"]) for s in scenarios),
                "expert_cards_seeded": False, "historical_examples_supplied": True,
                "live": live, "delivery_enabled": False,
                "limits": ["Known synthetic families, not new customer evidence.",
                           "Agent authors card; recurring runs below test native MCP outcomes without a report-writing LLM.",
                           "No measured comparative cost/latency advantage or real user usability claim.",
                           "Read-only synthetic MCP source; not a fresh Superset extraction or arbitrary MCP auto-normalization.",
                           "Metadata mappings and owner-labeled history are supplied, not auto-discovered from raw enterprise data."]}
    write_exclusive(output / "protocol.json", protocol)
    write_exclusive(output / "frozen-scenarios.json", scenarios)
    if not live:
        return {"status": "dry_run", **protocol}
    from evaluations.installed_trial_transport import installed_server

    secret = key_file.read_text().strip()
    if not secret:
        raise ValueError("Empty Jev key")
    audit = Audit(output / "trace.jsonl", (secret,))
    budget = RequestBudget(jev_budget)
    all_results = []
    for scenario in scenarios:
        public = public_scenario(scenario)
        adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
        adapter.set_period(public["onboarding"], datetime.now(timezone.utc))
        audit.episode = public["scenario_id"] + "/onboarding"
        company_result = {"scenario_id": public["scenario_id"], "onboarding_complete": False, "periods": []}
        all_results.append(company_result)

        async def reviewer(**kwargs):
            return await review_owner_artifact(**kwargs, audit=audit, budget=budget)

        with tempfile.TemporaryDirectory(prefix="signalweave-installed-workflow-") as temporary:
            try:
                async with installed_server(binary=binary, key_file=key_file, public=public,
                                            adapter=adapter, audit=audit, budget=budget,
                                            work=Path(temporary).resolve()) as server:
                    # Compress simulated time into this live capture, preserving source
                    # ages. Business observations remain explicitly historical replays.
                    setup_delta = adapter.clock - datetime.fromisoformat(public["onboarding"]["as_of"])
                    examples = shift_timestamps(copy.deepcopy(scenario["owner_examples"]), setup_delta)
                    session = InstalledSession(public, adapter, server, True,
                                               examples=examples, owner_reviewer=reviewer)
                    started = time.perf_counter()
                    episode = await codex_episode(
                        session, key="", effort="low", budget=budget, audit=audit, max_turns=50,
                        max_tool_calls=60, max_output_tokens=6000, timeout_seconds=360,
                        instructions_override=onboarding_instructions(server),
                        prompt_override={"phase": "onboarding", "business": session.public,
                                         "period": adapter.period_context})
                    company_result.update(onboarding=episode, onboarding_seconds=time.perf_counter() - started,
                                          owner_reviews=session.owner_review_records,
                                          onboarding_complete=session.setup_complete, notes=session.notes)
                    if not session.setup_complete or episode.get("foreign_tools"):
                        raise ValueError("onboarding_incomplete_or_foreign_tools")
                    card = await session.product("get_insight_card", {"card_id": session.card_id})
                    company_result["card"] = card
                    frozen_card = card_fingerprint(card)
                    frozen_plan = digest(card.get("compiled_plan"))
                    company_result["card_fingerprint"] = frozen_card
                    company_result["compiled_plan_fingerprint"] = frozen_plan
                    company_result["calibration_report_id"] = session.acceptance_report_id
                    write_exclusive(output / f"{public['scenario_id']}-onboarding.json", company_result)
                    session.phase = "monitoring"
                    for period_index, period in enumerate(public["periods"]):
                        if period_index == stage_gate and not all(r["exact"] for r in company_result["periods"]):
                            raise ValueError("initial_stage_failed; remaining intended cases retained as not run")
                        adapter.set_period(period, datetime.now(timezone.utc))
                        audit.episode = f"{public['scenario_id']}/{period['period_id']}"
                        row = {"period_id": period["period_id"], "completed": False, "exact": False}
                        begin, offset = time.perf_counter(), len(audit.events)
                        try:
                            current = await session.product("get_insight_card", {"card_id": session.card_id})
                            if (card_fingerprint(current) != frozen_card
                                    or digest(current.get("compiled_plan")) != frozen_plan):
                                raise ValueError("frozen_card_changed")
                            result = await session.product("evaluate_insight_card", {
                                "card_id": session.card_id, "idempotency_key": audit.episode})
                            audit.emit("system.evaluation", response=result)
                            before = (budget.used, adapter.inspections)
                            replay = await session.product("evaluate_insight_card", {
                                "card_id": session.card_id, "idempotency_key": audit.episode})
                            # A receipt replay can change its replay marker, never the native result/report.
                            replay_ok = (before == (budget.used, adapter.inspections)
                                         and digest(result.get("result")) == digest(replay.get("result"))
                                         and digest(result.get("report")) == digest(replay.get("report")))
                            row.update(completed=True, result=result, replay_exact_no_calls=replay_ok)
                            row["score"] = score_native(result, card,
                                scenario["private"]["periods"][period["period_id"]], public["destinations"])
                            row["exact"] = row["score"]["exact"] and replay_ok
                        except Exception as error:
                            row["error_type"] = type(error).__name__
                            row["error"] = audit.redact(str(error)[:1000])
                            audit.emit("episode.error", error_type=type(error).__name__)
                        row.update(seconds=time.perf_counter() - begin, source_reads=adapter.inspections,
                                   usage=usage_summary(audit.events[offset:]))
                        company_result["periods"].append(row)
                        write_exclusive(output / f"{public['scenario_id']}-{period['period_id']}.json", audit.redact(row))
                        print(json.dumps({"company": public["company"], "period": period["period_id"],
                                          "exact": row["exact"], "error_type": row.get("error_type")}), flush=True)
            except Exception as error:
                company_result["error_type"] = type(error).__name__
                company_result["error"] = audit.redact(str(error)[:1000])
                audit.emit("company.error", error_type=type(error).__name__)
        present = {row["period_id"] for row in company_result["periods"]}
        company_result["periods"].extend({"period_id": p["period_id"], "completed": False, "exact": False,
                                           "error_type": "setup_or_runtime_incomplete"}
                                          for p in public["periods"] if p["period_id"] not in present)
        write_exclusive(output / f"{public['scenario_id']}-result.json", audit.redact(company_result))
    rows = [r for company in all_results for r in company["periods"]]
    report = {"protocol": protocol, "companies": all_results,
              "summary": {"onboarding_complete": sum(c["onboarding_complete"] for c in all_results),
                          "onboarding_total": len(scenarios), "correct": sum(r["exact"] for r in rows),
                          "completed": sum(r["completed"] for r in rows), "intended": protocol["monitoring_cases"]},
              "jev_attempts": budget.used, "budget_censored": budget.exhausted,
              "usage": usage_summary(audit.events),
              "passed": bool(rows) and all(r["exact"] for r in rows) and not budget.exhausted,
              "scope": "Installed synthetic onboarding and native execution; not enterprise completion."}
    write_exclusive(output / "report.json", audit.redact(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--seed-dir", type=Path)
    parser.add_argument("--seed", type=int, help="Transfer fixture seed; defaults to the recorded regression seed.")
    parser.add_argument("--suite", choices=["northstar", "transfer"], default="northstar")
    parser.add_argument("--company-index", action="append", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--jev-budget", type=int, default=100)
    args = parser.parse_args()
    if args.live and args.key_file is None:
        parser.error("--live requires --key-file")
    if not 1 <= args.jev_budget <= 250:
        parser.error("budget must be between 1 and 250")
    if args.suite == "northstar":
        if args.seed_dir is None or args.company_index is not None or args.seed is not None:
            parser.error("northstar requires --seed-dir and does not accept --company-index or --seed")
        from evaluations.installed_northstar_cases import build_northstar
        scenarios = [build_northstar(args.seed_dir, smoke=args.smoke)]
    else:
        if args.smoke or args.seed_dir is not None:
            parser.error("transfer uses --company-index for bounded probes, not --smoke/--seed-dir")
        from evaluations.installed_transfer_cases import DEFAULT_SEED, build_transfers
        args.seed = DEFAULT_SEED if args.seed is None else args.seed
        scenarios = build_transfers(args.seed)
        if args.company_index is not None:
            if len(set(args.company_index)) != len(args.company_index) or any(i not in range(len(scenarios)) for i in args.company_index):
                parser.error("Company indices must be unique and in range")
            scenarios = [s for i, s in enumerate(scenarios) if i in args.company_index]
    report = asyncio.run(run_trial(scenarios, binary=args.binary.resolve(), key_file=args.key_file,
                                   output=args.output, jev_budget=args.jev_budget, live=args.live,
                                   fixture_seed=args.seed))
    print(json.dumps({k: v for k, v in report.items() if k not in {"companies", "protocol"}}, indent=2))


if __name__ == "__main__":
    main()

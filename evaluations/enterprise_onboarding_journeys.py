"""Messy-catalog regression of actual agent onboarding, not new holdout evidence.

Extends the existing six business families without changing their private labels.
The agent must ask the simulated owner, inspect sources and author its own card.
No expert card is seeded. Live execution is explicit and uses the existing
audited Codex/live-Jev runner with a persistent-notes Luna baseline.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from evaluations.bootstrap_agent_trial import parser as agent_parser
from evaluations.bootstrap_agent_trial import run_trial
from evaluations.bootstrap_scenarios import build_scenarios, dataset_digest

VERSION = "enterprise-onboarding-journeys-v1"
EXECUTION_VERSION = "enterprise-onboarding-repair-v2"
SEED = 20261003
VARIANTS = (
    ("Archive", "Superseded weekly definition; retained for historical audit.", 60),
    ("Sandbox", "QA population with synthetic entities, not the live business population.", 0),
    ("Regional pilot", "Pilot-only regional population, not the complete company population.", 0),
    ("Planning", "Forecast assumptions, not observed actual results.", 0),
    ("Partner export", "Partner subset using a separate reporting cutoff and population.", 0),
)


def _replace(value, old: str, new: str):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, old, new) for key, item in value.items()}
    return value


def journeys(seed: int = SEED) -> list[dict]:
    scenarios = build_scenarios(seed=seed, split="holdout")
    rng = random.Random(f"{VERSION}:{seed}")
    for scenario in scenarios:
        public = scenario["public"]
        originals = copy.deepcopy(public["catalog"])
        periods = [public["onboarding"], *public["periods"]]
        # Public glossary declares previous complete weeks. This version makes
        # that capability explicit; the older frozen fixtures remain unchanged.
        for descriptor in public["catalog"]:
            descriptor["contract"]["available_comparison_windows"] = ["previous_period"]
        for period in periods:
            for snapshot in period["snapshots"].values():
                snapshot["contract"]["available_comparison_windows"] = ["previous_period"]
        for descriptor in originals:
            old_key = descriptor["resource"]
            old_ref = f"company_mcp|{old_key}"
            for label, scope, age_days in VARIANTS:
                key = f"resource-{rng.getrandbits(80):020x}"
                ref = f"company_mcp|{key}"
                alternative = _replace(copy.deepcopy(descriptor), old_key, key)
                alternative["title"] = f"{descriptor['title']} / {label}"
                alternative["description"] = f"{descriptor['description']} Scope: {scope}"
                alternative["metadata"]["scope_note"] = scope
                alternative["contract"]["available_comparison_windows"] = ["previous_period"]
                public["catalog"].append(alternative)
                for period in periods:
                    snapshot = _replace(copy.deepcopy(period["snapshots"][old_ref]), old_key, key)
                    snapshot["title"] = alternative["title"]
                    snapshot["description"] = alternative["description"]
                    snapshot["metadata"]["scope_note"] = scope
                    snapshot["source_captured_at"] = (
                        datetime.fromisoformat(snapshot["source_captured_at"].replace("Z", "+00:00"))
                        - timedelta(days=age_days)
                    ).isoformat()
                    for comparison in snapshot["analytical_comparisons"]:
                        comparison["population"] = scope
                    for evidence in snapshot["evidence"]:
                        evidence["statement"] = f"{scope} {evidence['statement']}"
                    period["snapshots"][ref] = snapshot
        rng.shuffle(public["catalog"])
    return scenarios


def protocol(scenarios: list[dict], *, jev_budget: int = 144) -> dict:
    periods = sum(len(s["public"]["periods"]) for s in scenarios)
    return {
        "version": VERSION, "seed": SEED, "dataset_sha256": dataset_digest(scenarios),
        "execution_version": EXECUTION_VERSION,
        "subset_probe": len(scenarios) != 6,
        "interventions": [
            "Stable source-selection confirmation and explicit authorized anchors.",
            "Typed selected-source and workflow-case inputs; optional single current capture.",
            "Separate owner action rules from unconditional evidence assessments in guide.",
            "Both owner reviewers receive bounded current public source contracts, not measurements or labels.",
            "Both report writers get identical inspected-citation validation and population caveats.",
        ],
        "companies": [{"name": s["public"]["company"], "family": s["private"]["family"],
                       "brief": s["public"]["brief"], "assets": len(s["public"]["catalog"]),
                       "monitoring_periods": len(s["public"]["periods"])} for s in scenarios],
        "primary_denominators": {"onboarding_per_arm": len(scenarios), "monitoring_per_arm": periods,
                                 "author_and_monitor_episodes": 2 * (len(scenarios) + periods)},
        "budget": {"jev_attempts": jev_budget, "sdk_retries": 0, "tool_calls_per_episode": 45,
                   "owner_review_attempts_per_arm_company": 3,
                   "max_codex_invocations_including_owner_reviews": 2 * (4 * len(scenarios) + periods)},
        "endpoints": ["setup completion", "owner questions and corrections", "guide usage",
                      "time to first preview", "native outcome and exact recipient",
                      "final outcome and exact recipient", "numeric and provenance correctness",
                      "unnecessary and missed alerts", "unsupported narrative claims",
                      "tool errors, reads, tokens and wall time"],
        "success_gate": "Six completed treatment onboardings; all 18 later native and final outcomes/recipients correct; required numeric/provenance checks pass; no unsupported material narrative claims. Missing work remains failure, not a quiet success.",
        "comparison_gate": "No correctness loss against the same Luna agent using the same source and owner tools; report setup and monitoring cost/time separately. No commercial savings or universal reliability claim from this regression.",
        "limits": ["Synthetic normalized MCP sources, not real provider accounts or installation.",
                   "Known business-family regression; new catalog distractors are not a new holdout.",
                   "Copied alternative data values test scope selection, not new statistical distributions.",
                   "Simulated owner answers and independent model review, not observed real-user usability.",
                   "One onboarding snapshot and three later periods per company, not months-long fleet scale.",
                   "No real scheduling, query billing, notifications, or causal ground truth.",
                   "The human still supplies business intent and policy; missing policy is not Jev's job.",
                   "No publication, runtime repair, label changes or retries during the frozen run."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jev-key-file", type=Path)
    parser.add_argument("--company-index", type=int, action="append",
                        help="Zero-based whole-company repair probe; never omit individual later periods.")
    parser.add_argument("--jev-budget", type=int, default=144)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new; never overwrite or resume")
    scenarios = journeys()
    if args.company_index is not None:
        if len(set(args.company_index)) != len(args.company_index) or any(i not in range(6) for i in args.company_index):
            parser.error("Company indices must be unique and in 0..5")
        scenarios = [s for i, s in enumerate(scenarios) if i in args.company_index]
    if not 1 <= args.jev_budget <= 144:
        parser.error("Jev budget must be in 1..144")
    frozen = protocol(scenarios, jev_budget=args.jev_budget)
    frozen["wrapper_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not args.live:
        args.output.mkdir(parents=True)
        (args.output / "protocol.json").write_text(json.dumps(frozen, indent=2) + "\n")
        print(json.dumps(frozen, indent=2))
        return
    if not args.jev_key_file:
        parser.error("--live requires --jev-key-file")
    # The runner owns creating its output and retaining each interrupted episode.
    # Freeze protocol separately BEFORE any model runs; neither contains secrets.
    sidecar = args.output.with_name(args.output.name + ".protocol.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    with sidecar.open("x") as stream:
        json.dump(frozen, stream, indent=2)
    options = agent_parser().parse_args([
        "--agent-transport", "codex", "--owner-review", "independent", "--split", "holdout",
        "--limit", str(len(scenarios)), "--seed", str(SEED), "--max-api-requests", str(args.jev_budget),
        "--max-tool-calls", "45", "--jev-key-file", str(args.jev_key_file),
        "--output", str(args.output),
    ])
    asyncio.run(run_trial(options, scenarios_override=scenarios))
    print(f"Retained results: {args.output}")


if __name__ == "__main__":
    main()

"""Prospective paired card workflows over six synthetic business families.

Uses the installed native MCP, simulated owner dialogue, live Jev, saved-login
Codex, and the distributed skill. This is not 108 independent companies or
live provider data: six companies have eighteen prospective weekly contexts.
Raw transcripts stay in ignored artifacts, not the public documentation tree.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evaluations.bootstrap_agent_trial import digest, shift_timestamps, write_exclusive
from evaluations.bootstrap_scenarios import build_scenarios
from evaluations.native_cadence_trial import run_trial

VERSION = "agent-workflow-cohort-v1"
DEFAULT_SEED = 20261013
CONTEXTS = ("ordinary_export", "reordered_export", "irrelevant_outage",
            "wide_catalog", "partial_quality_export", "definition_drift")


def _replace(value, mapping: dict[str, str]):
    if isinstance(value, str):
        for old, new in mapping.items():
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_replace(item, mapping) for item in value]
    if isinstance(value, dict):
        return {_replace(key, mapping): _replace(item, mapping) for key, item in value.items()}
    return value


def _identity(item: dict) -> tuple[str, str, str]:
    return item["title"], item["description"], item["kind"]


def _bridge_identity(scenario: dict) -> dict:
    """These are company-MCP exports, never pretend an adapter name is a live BI connection."""
    adapters = {item["adapter"] for item in scenario["public"]["catalog"]}
    transformed = _replace(scenario, {name + "|": "company_mcp|" for name in adapters})
    for descriptor in transformed["public"]["catalog"]:
        descriptor.setdefault("metadata", {})["simulated_artifact_origin"] = descriptor["adapter"]
        descriptor["adapter"] = "company_mcp"
    for period in [transformed["public"]["onboarding"], *transformed["public"]["periods"]]:
        for snapshot in period["snapshots"].values():
            snapshot["adapter"] = "company_mcp"
    return transformed


def build_cohort(seed: int = DEFAULT_SEED) -> list[dict]:
    """Preserve existing meaning/labels; independently generate scales and IDs per close."""
    bases = [_bridge_identity(item) for item in build_scenarios(
        seed, connector_profile=True, catalog_noise=20)]
    result = []
    for company_index, base in enumerate(bases):
        scenario = copy.deepcopy(base)
        for item in scenario["public"]["catalog"]:
            contract = item["contract"]
            contract["tenant_id"] = scenario["scenario_id"]
            if contract.get("roles") == ["primary"]:
                metric = contract["metric_names"][0]
                contract["comparison_contracts"] = [{
                    "key": metric, "metric": metric,
                    "definition": contract["scope"], "population": contract["population"],
                    "unit": scenario["public"]["glossary"]["unit"],
                    "comparison_window": "previous_period", "coverage": "complete", "comparable": True,
                    "detail": "Export includes the complete owner-defined weekly comparison population."}]
        target = {_identity(item): item for item in scenario["public"]["catalog"]}
        periods, labels = [], {}
        start = datetime(2025, 1, 6, tzinfo=timezone.utc)
        onboarding = scenario["public"]["onboarding"]
        old_clock = datetime.fromisoformat(onboarding["as_of"])
        scenario["public"]["onboarding"] = shift_timestamps(onboarding, start - old_clock)
        for ref, snapshot in scenario["public"]["onboarding"]["snapshots"].items():
            snapshot["contract"] = copy.deepcopy(next(item["contract"] for item in target.values()
                if ref == f"{item['adapter']}|{item['resource']}"))
        family = scenario["private"]["family"]
        for context_index, context in enumerate(CONTEXTS):
            generated = _bridge_identity(build_scenarios(seed + 1009 * (context_index + 1),
                                        connector_profile=True, catalog_noise=20)[company_index])
            assert generated["private"]["family"] == family
            mapping = {generated["scenario_id"]: scenario["scenario_id"]}
            for item in generated["public"]["catalog"]:
                other = target[_identity(item)]
                mapping[item["resource"]] = other["resource"]
            for old, new in zip(generated["public"]["destinations"],
                                scenario["public"]["destinations"], strict=True):
                mapping[old["key"]] = new["key"]
            for period in generated["public"]["periods"]:
                label = _replace(generated["private"]["periods"][period["period_id"]], mapping)
                shifted = _replace(period, mapping)
                as_of = start + timedelta(weeks=len(periods) + 1)
                shifted = shift_timestamps(shifted, as_of - datetime.fromisoformat(shifted["as_of"]))
                period_id = f"weekly-close-{len(periods) + 1:02d}"
                shifted["period_id"] = period_id
                for ref, snapshot in shifted["snapshots"].items():
                    snapshot.setdefault("metadata", {})["period_id"] = period_id
                    snapshot["metadata"]["fixture_context"] = context
                    descriptor = next(item for item in target.values()
                                      if ref == f"{item['adapter']}|{item['resource']}")
                    snapshot["contract"] = copy.deepcopy(descriptor["contract"])
                    # The source has the catalog's semantic definition, plus this run's quality.
                    # Analytical comparisons (including missing denominators) remain unchanged.
                    if context == "reordered_export":
                        for comparison in snapshot.get("analytical_comparisons", []):
                            comparison["segments"] = list(reversed(comparison.get("segments", [])))
                        snapshot["evidence"] = list(reversed(snapshot.get("evidence", [])))
                    if context == "irrelevant_outage" and not descriptor["contract"].get("roles"):
                        snapshot["error"] = "Synthetic read-only source unavailable for this close."
                        snapshot["evidence"] = []
                    if label["condition"] == "quality" and descriptor["contract"].get("roles") == ["primary"]:
                        for binding in snapshot["contract"].get("comparison_contracts", []):
                            binding.update(coverage="unknown", comparable=False,
                                detail="The source export explicitly cannot validate the owner's metric definition or full eligible population.")
                        if context == "partial_quality_export":
                            for comparison in snapshot.get("analytical_comparisons", []):
                                comparison.update(coverage="partial", comparable=False)
                            snapshot["metadata"]["export_coverage"] = "Incomplete business population; do not call a decline from this export."
                        if context == "definition_drift":
                            for binding in snapshot["contract"].get("comparison_contracts", []):
                                binding["definition"] = "Unreviewed eligibility revision; historical mapping unavailable."
                            for comparison in snapshot.get("analytical_comparisons", []):
                                comparison["comparable"] = False
                periods.append(shifted)
                labels[period_id] = {**label, "context": context, "family": family}
        scenario["public"]["periods"] = periods
        scenario["private"]["periods"] = labels
        scenario["cadence"] = "eighteen consecutive fictional weekly business closes"
        scenario["public"]["no_owner_during_monitoring"] = True
        scenario["public"]["brief"] += (
            " This is a fictional retrospective weekly-close review. Ask the owner for "
            "business definitions and routing during setup; later weekly runs are autonomous. "
            "Keep source scopes distinct, explain useful findings concisely, and retain evidence links."
        )
        result.append(scenario)
    return result


def summarize(reports: list[dict], intended_companies: int) -> dict:
    totals = Counter()
    for report in reports:
        for key, value in report.get("summary", {}).items():
            if type(value) is int:
                totals[key] += value
    completed = sum(report.get("status") == "completed" for report in reports)
    return {"intended_companies": intended_companies,
            "completed_companies": completed,
            "onboarded_companies": sum(bool(report.get("onboarding_complete")) for report in reports),
            **dict(totals),
            "budget_censored_companies": sum(bool(report.get("jev_budget_censored")) for report in reports),
            "native_decision_and_final_agent_scores_are_separate": True}


async def run(args) -> dict:
    scenarios = build_cohort(args.seed)
    if args.company_index is not None:
        if len(set(args.company_index)) != len(args.company_index) or any(
                index not in range(len(scenarios)) for index in args.company_index):
            raise ValueError("company indices must be unique and in range")
        scenarios = [scenario for index, scenario in enumerate(scenarios) if index in args.company_index]
    if args.pilot:
        # A development gate, never pooled with or substituted for the full cohort.
        for scenario in scenarios:
            scenario["public"]["periods"] = scenario["public"]["periods"][:3]
            ids = {period["period_id"] for period in scenario["public"]["periods"]}
            scenario["private"]["periods"] = {key: label for key, label in scenario["private"]["periods"].items() if key in ids}
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    skill = args.skill.read_text()
    protocol = {"version": VERSION, "seed": args.seed, "pilot": args.pilot,
                "companies": len(scenarios), "business_families": [s["private"]["family"] for s in scenarios],
                "paired_cases": sum(len(s["public"]["periods"]) for s in scenarios),
                "dataset_digest": digest(scenarios), "workflow_skill_digest": digest(skill),
                "concurrency": args.concurrency, "jev_cap_per_company": args.jev_budget,
                "source_transport": "real loopback HTTP company-MCP bridge carrying synthetic normalized exports, not hosted BI accounts",
                "company_statistical_unit": "six related business-family simulations; repeated periods are not independent companies",
                "comparison": "same reviewed card, notes, sources, Luna model/effort; treatment adds native SignalWeave and distributed skill",
                "stage_gate": "pilot retained separately; full cohort never stops after an incorrect outcome",
                "claim": "functional and comparative workflow evidence; no billed warehouse savings or real customer usability claim"}
    write_exclusive(args.output / "protocol.json", protocol)
    write_exclusive(args.output / "frozen-inputs.json", scenarios)
    if not args.live:
        return {"status": "dry_run", "protocol": protocol}
    if args.key_file is None:
        raise ValueError("live cohort requires an authorized Jev key file")
    semaphore = asyncio.Semaphore(args.concurrency)

    async def company(index, scenario):
        async with semaphore:
            return await run_trial(
                scenario, {"pilot_indices": [0, 1, 2, 3]}, binary=args.binary,
                key_file=args.key_file, output=args.output / f"company-{index:02d}",
                cases="all", jev_budget=args.jev_budget, live=True, workflow_skill=skill,
                transport="stdio" if index % 2 == 0 else "streamable-http")

    reports = await asyncio.gather(*(company(index, scenario) for index, scenario in enumerate(scenarios)))
    report = {"status": "completed" if all(r.get("status") == "completed" for r in reports) else "incomplete",
              "protocol": protocol, "summary": summarize(reports, len(scenarios)),
              "company_reports": [f"company-{index:02d}/report.json" for index in range(len(reports))]}
    write_exclusive(args.output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("dist/signalweave"))
    parser.add_argument("--skill", type=Path, default=Path("skills/signalweave/SKILL.md"))
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--company-index", type=int, action="append")
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 3], default=2)
    parser.add_argument("--jev-budget", type=int, default=80)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.jev_budget <= 100:
        parser.error("Jev cap must be between 1 and 100")
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()

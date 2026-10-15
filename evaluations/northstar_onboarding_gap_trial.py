"""Probe first-use Northstar onboarding when a business decision is unknown.

The scenario uses the installed binary and normal agent onboarding path. It
removes the owner's materiality answer, keeps the inspectable data and labeled
historical examples, and intentionally supplies no future periods: there is no
fair monitoring label until a human confirms the missing policy.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
from pathlib import Path

from evaluations.installed_northstar_cases import build_northstar
from evaluations.installed_workflow_trial import run_trial


def _replace_tenant(value, previous: str, current: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"tenant", "tenant_id"} and item == previous:
                value[key] = current
            else:
                _replace_tenant(item, previous, current)
    elif isinstance(value, list):
        for item in value:
            _replace_tenant(item, previous, current)


def build_missing_materiality_case(seed_dir: Path) -> dict:
    """Return one onboarding-only case with unresolved human policy intent."""

    scenario = copy.deepcopy(build_northstar(seed_dir, smoke=True))
    previous = scenario["scenario_id"]
    current = "northstar-outfitters-unclear-materiality"
    scenario["scenario_id"] = current
    scenario["public"]["brief"] += (
        " I have not decided what size of movement counts as material. Ask me if "
        "you need that to finish the monitoring setup; do not invent or infer a "
        "threshold from the chart title."
    )
    scenario["public"]["owner_answers"].pop("materiality", None)
    # An unresolved business policy has no honest future outcome labels. Keep
    # source examples for calibration, but do not score monitoring against the
    # policy the owner has not yet confirmed.
    scenario["public"]["periods"] = []
    scenario["private"]["periods"] = {}
    scenario["private"]["onboarding_expectation"] = {
        "state": "needs_human_clarification",
        "unknown_owner_topics": ["materiality"],
    }
    _replace_tenant(scenario["public"], previous, current)
    _replace_tenant(scenario["owner_examples"], previous, current)
    return scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--seed-dir", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jev-budget", type=int, default=12)
    args = parser.parse_args()
    scenario = build_missing_materiality_case(args.seed_dir)
    report = asyncio.run(run_trial(
        [scenario],
        binary=args.binary.resolve(),
        key_file=args.key_file,
        output=args.output,
        jev_budget=args.jev_budget,
        live=True,
        stage_gate=0,
    ))
    print({
        "scenario_id": scenario["scenario_id"],
        "onboarding_complete": report["companies"][0]["onboarding_complete"],
        "calibration_passed": report["companies"][0].get("calibration_report_passed"),
        "monitoring_cases": report["protocol"]["monitoring_cases"],
        "jev_attempts": report["jev_attempts"],
        "budget_censored": report["budget_censored"],
        "expected_human_clarification": report["summary"]["expected_human_clarification"],
    })


if __name__ == "__main__":
    main()

"""Export blinded public-evidence packets and compact results; never call a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime
from pathlib import Path

from evaluations.bootstrap_agent_trial import shift_timestamps, write_exclusive
from evaluations.bootstrap_scenarios import build_scenarios, dataset_digest, public_episode


def packets(report: dict) -> tuple[list[dict], dict, dict]:
    config = report["config"]
    fixtures = build_scenarios(seed=config["seed"], split=config["split"])
    fixtures = fixtures[:config.get("selected_companies", len(fixtures))]
    if config.get("dataset_digest") and dataset_digest(fixtures) != config["dataset_digest"]:
        raise ValueError("Fixture digest differs from measured run; do not reconstruct review evidence.")
    scenarios = {s["scenario_id"]: s for s in fixtures}
    rows = [r for r in report["rows"] if r["phase"] == "monitoring"]
    random.Random(81072).shuffle(rows)
    cases, mapping = [], {}
    for index, row in enumerate(rows):
        identifier = f"review-{index + 1:03d}"
        scenario = scenarios[row["scenario_id"]]
        public = public_episode(scenario, row["period_id"])
        if config.get("clock_rebased_to"):
            delta = (datetime.fromisoformat(config["clock_rebased_to"])
                     - datetime.fromisoformat(scenario["public"]["onboarding"]["as_of"]))
            public["period"] = shift_timestamps(public["period"], delta)
        cases.append({"case_id": identifier, "business": {
            key: public[key] for key in ("company", "brief", "glossary", "owner_answers",
                                        "destinations", "catalog", "period", "numeric_vocabulary",
                                        "submission_contract")},
            "analysis": row["submission"], "inspected_refs": row["inspected_refs"],
            "execution_complete": row["status"] == "complete"})
        mapping[identifier] = {key: row[key] for key in ("scenario_id", "period_id", "arm")}
    compact = {key: report[key] for key in ("config", "status", "summary", "usage",
                                            "budget_censored", "comparative_eligible")}
    compact["cases"] = [{key: row.get(key) for key in (
        "scenario_id", "period_id", "arm", "phase", "status", "error", "seconds",
        "agent_seconds", "system_seconds", "tool_calls", "source_reads", "usage",
        "score", "raw_system_decision", "submission", "foreign_tools")} for row in report["rows"]]
    compact["dollar_cost_scope"] = "Illustrative API-equivalent token estimates, not subscription charges."
    compact["resolved_jev_models"] = report.get("resolved_jev_models", [])
    compact["narrative_review_status"] = "Pending separate internal blind review; not external peer review."
    return cases, mapping, compact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    cases, mapping, compact = packets(json.loads(raw))
    args.output.mkdir(parents=True, exist_ok=False)
    compact["full_report_sha256"] = hashlib.sha256(raw).hexdigest()
    write_exclusive(args.output / "results.json", compact)
    write_exclusive(args.output / "blind-review.json", {"cases": cases})
    write_exclusive(args.output / "review-key.json", mapping)


if __name__ == "__main__":
    main()

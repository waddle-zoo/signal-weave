"""Opt-in live Jev test of semantic missingness, not an onboarding benchmark.

Three domains, four evidence states each. Labels never enter the engine state.
One judgment per case, no retries, no external delivery, exclusive output.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from time import perf_counter

from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.models import InsightCard, ResourceSnapshot
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]


def cases():
    domains = [
        ("commerce", "The settled refund batch is missing approval from its finance owner.",
         "The finance owner explicitly rejected approval for this settled refund batch.",
         "The finance owner approved this settled refund batch; signed approval is attached.",
         "The refund batch settled; its finance approval status is not included.",
         "Two equally authoritative current records conflict: the signed finance approval says approved; the approval register says no approval. Neither supersedes the other."),
        ("operations", "The current deployment violates the approved maintenance window.",
         "The current deployment began outside the explicitly approved maintenance window.",
         "The current deployment ran entirely inside the explicitly approved maintenance window.",
         "The current deployment started at 02:00 UTC. No approved maintenance window is supplied.",
         "Two current, equally authoritative schedules conflict: one explicitly permits this deployment time; the other explicitly prohibits it. No precedence is recorded."),
        ("customer-success", "A renewal account has no assigned account owner.",
         "The complete current renewal roster shows account A with no assigned account owner.",
         "The complete current renewal roster shows every account with an assigned account owner.",
         "Renewal dates and account names are provided, but account-owner assignments are omitted.",
         "Two current, equally authoritative renewal rosters disagree: one lists an owner for every account; one shows account A unassigned. Neither roster is designated canonical."),
    ]
    for domain, watch, positive, negative, missing, conflict in domains:
        for variant, statement, expected in (
            ("affirmative", positive, "present"), ("negative", negative, "absent"),
            ("missing", missing, "unknown"), ("conflicting", conflict, "unknown"),
        ):
            # The case/variant labels stay outside card and evidence semantics.
            card = InsightCard(
                id="operating-check", title="Operating review",
                what_to_watch=watch, why_watch="Route an evidenced exception to the operating owner.",
                watch_for=[watch],
                decision_guidance="Notify if evidence establishes the watch condition. Ignore if sufficient applicable evidence establishes it is absent. Return insufficient_data when evidence is missing or conflicting; never infer absence from omission.",
                sources=[{"key": "record", "adapter": "fixture", "resource": "record",
                          "label": "Current operating record"}],
                delivery_methods=[{"key": "owner", "outcome": "notify", "label": "Operating owner",
                                   "destination": "agent://operating-owner"},
                                  {"key": "data", "outcome": "insufficient_data", "label": "Data owner",
                                   "destination": "agent://data-owner"}],
            )
            card.compiled_plan = base_plan(card)
            snapshot = ResourceSnapshot(
                source_key="record", adapter="fixture", resource="record", title="Current operating record",
                evidence=[{"source_key": "record", "statement": statement,
                           "provenance": ["fixture:operating-record"]}],
            )
            yield f"{domain}-{variant}", card, snapshot, expected


class RecordedJudger(JevJudger):
    def __init__(self, api_key):
        super().__init__(api_key=api_key, max_retries=0)
        self.calls = []

    async def _system_one_with_retry(self, *, state, questions, stage):
        if len(self.calls) >= 12:
            raise RuntimeError("Twelve-attempt trial budget exhausted")
        record = {"stage": stage, "state": state,
                  "questions": self._question_budget_payload(questions)}
        self.calls.append(record)
        response = await super()._system_one_with_retry(state=state, questions=questions, stage=stage)
        record["resolved_model"] = getattr(response, "model", None)
        return response


async def trial(output, key_file):
    key = load_api_key(key_file)
    if not key:
        raise ValueError("A real configured Jev key is required")
    output.mkdir(parents=True, exist_ok=False)
    frozen_files = ["evaluations/watch_evidence_trial.py", "src/signalweave/typesafe_adapter.py",
                    "src/signalweave/models.py", "src/signalweave/engine.py", "src/signalweave/evaluation.py"]
    report = {"live_jev": True, "scope": "synthetic semantic evidence-state development regression",
              "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in frozen_files},
              "thresholds_unchanged": True, "external_delivery": False, "planned_cases": 12,
              "status": "running", "passed": False, "cases": []}
    judger = RecordedJudger(key)
    for name, card, snapshot, expected in cases():
        start = perf_counter()
        before = len(judger.calls)
        row = {"case": name, "expected_watch": expected,
               "expected_outcome": {"present": "notify", "absent": "ignore", "unknown": "insufficient_data"}[expected]}
        try:
            run = await InsightEngine(judger).evaluate(card, [snapshot])
            watch = run.result.watch_results[0]
            row["result"] = run.result.model_dump(mode="json")
            row["checks"] = {
                "watch_state": watch.status.value == expected,
                "policy_outcome": run.result.outcome.value == row["expected_outcome"],
                "distribution_retained": set(watch.probabilities) == {"present", "absent", "unknown"},
                "single_judgment": len(judger.calls) - before == 1,
                "no_unknown_completion": expected != "unknown" or "watch:1" in run.result.evidence_plan.missing_slot_keys,
                "exact_route": [m.key for m in run.result.delivery_methods] == (
                    ["owner"] if expected == "present" else ["data"] if expected == "unknown" else []),
            }
        except Exception as error:
            # Keep provider failure type, not exception text which may contain credentials.
            row["error_type"] = type(error).__name__
            row["checks"] = {"execution": False}
        row["seconds"] = perf_counter() - start
        row["requests"] = judger.calls[before:]
        report["cases"].append(row)
        report["attempts"] = len(judger.calls)
        report["successful_requests"] = judger.metrics.requests
        report["input_tokens"] = judger.metrics.input_tokens
        report["output_tokens"] = judger.metrics.output_tokens
        complete = len(report["cases"]) == report["planned_cases"]
        report["status"] = "complete" if complete else "running"
        report["passed"] = complete and all(all(r["checks"].values()) for r in report["cases"])
        (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"case": name, "checks": row["checks"]}), flush=True)
    return report["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(trial(args.output, args.key_file)) else 1)


if __name__ == "__main__":
    main()

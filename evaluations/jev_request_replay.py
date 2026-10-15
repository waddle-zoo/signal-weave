"""Opt-in, budgeted sensitivity probes of immutable recorded Jev requests.

This is a component diagnostic for controlled synthetic inputs, not a repair
certifier or an end-to-end benchmark. A trusted operator declares explicit
state edits; the runner loads no expected labels. Review the plan before use:
state edits can change meaning, even while questions and cards are retained.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import random
from pathlib import Path

from evaluations.bootstrap_agent_trial import (
    Audit,
    MeasuredJev,
    RequestBudget,
    canonical,
    json_value,
)
from signalweave.typesafe_adapter import load_api_key


def prepare(request: dict, variant: dict) -> tuple[dict, dict]:
    state = copy.deepcopy(request["state"])
    questions = copy.deepcopy(request["questions"])
    for edit in variant.get("edits", []):
        path = edit["path"]
        if not path or path[0] in {"card", "insight_card", "insight_plan"}:
            raise ValueError("Replay edits must not change authored policy or plan")
        parent = state
        for key in path[:-1]:
            parent = parent[key]
        key = path[-1]
        operation = edit["op"]
        if operation == "remove":
            del parent[key]
        elif operation == "replace":
            if parent[key] != edit["old"]:
                raise ValueError("Replay replacement precondition failed")
            parent[key] = copy.deepcopy(edit["value"])
        elif operation == "add":
            if not isinstance(parent, dict) or key in parent:
                raise ValueError("Replay add would overwrite existing state")
            parent[key] = copy.deepcopy(edit["value"])
        else:
            raise ValueError("Unsupported replay edit")
    if "question" in variant:
        questions = {variant["question"]: questions[variant["question"]]}
    return state, questions


def prepare_plan(trace: Path, plan: dict) -> list[dict]:
    requests = {}
    for line in trace.read_text().splitlines():
        event = json.loads(line)
        if event.get("kind") == "api.request" and event.get("provider") == "jev":
            request_id = event["request_id"]
            if request_id in requests:
                raise ValueError("Ambiguous request ID")
            requests[request_id] = event
    repeats = plan["repetitions"]
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("Repetitions must be 1..3")
    jobs = []
    for case in plan["cases"]:
        request = requests[case["request_id"]]
        names = [v["name"] for v in case["variants"]]
        if len(set(names)) != len(names) or "original" not in names:
            raise ValueError("Unique variants including original required")
        for variant in case["variants"]:
            if variant["name"] == "original" and set(variant) != {"name"}:
                raise ValueError("Original must be unchanged")
            state, questions = prepare(request, variant)
            for repeat in range(repeats):
                jobs.append({"request_id": request["request_id"],
                             "source_episode": request["episode"],
                             "variant": variant["name"], "repeat": repeat,
                             "model": request["model"], "state": state,
                             "questions": questions})
    if not jobs or len(jobs) > 60:
        raise ValueError("Replay must contain 1..60 predeclared attempts")
    random.Random(plan["seed"]).shuffle(jobs)
    return jobs


async def run(args) -> None:
    plan = json.loads(args.plan.read_text())
    jobs = prepare_plan(args.trace, plan)
    if not args.live:
        print(canonical({"planned_attempts": len(jobs), "live": False}))
        return
    if not args.synthetic_input:
        raise ValueError("Live replay is restricted to explicitly confirmed synthetic inputs")
    key = load_api_key(str(args.jev_key_file))
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    audit = Audit(args.output / "trace.jsonl", secrets=(key,))
    budget = RequestBudget(len(jobs))
    judger = MeasuredJev(key, budget, audit)
    config = {"plan": plan, "planned_attempts": len(jobs),
              "source_trace_sha256": hashlib.sha256(args.trace.read_bytes()).hexdigest(),
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "component sensitivity only; not onboarding or end-to-end acceptance"}
    (args.output / "config.json").write_text(canonical(audit.redact(config)) + "\n")
    rows = []
    for job in jobs:
        audit.episode = f"request-{job['request_id']}/{job['variant']}/{job['repeat']}"
        judger.name = job["model"]
        row = {k: v for k, v in job.items() if k not in {"state", "questions"}}
        try:
            response = await judger._system_one_with_retry(
                state=job["state"], questions=job["questions"], stage="recorded-replay")
            row.update(status="complete", response=json_value(response))
        except Exception as error:  # Retain failures without retrying/selecting winners.
            row.update(status="failed", error_type=type(error).__name__)
            status_code = getattr(error, "status_code", None)
            if type(status_code) is int and 100 <= status_code <= 599:
                row["http_status"] = status_code
            # Do not retain raw exception text/headers: they can contain credentials.
        rows.append(row)
        (args.output / "results.json").write_text(canonical(audit.redact({
            "planned_attempts": len(jobs), "attempts": budget.used,
            "complete": len(rows) == len(jobs), "rows": rows,
        })) + "\n")
        print(canonical(audit.redact({k: v for k, v in row.items() if k != "response"})), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--synthetic-input", action="store_true",
                        help="Confirm the source trace and mutation plan contain only synthetic data.")
    parser.add_argument("--jev-key-file", type=Path)
    args = parser.parse_args()
    if args.live and args.jev_key_file is None:
        parser.error("Live replay requires an explicit key file")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

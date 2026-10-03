"""Paired diagnostic of existing watch prose repeated in outcome guidance.

Not an onboarding success or holdout: uses a retained agent card and supplied
historical examples. Never changes measurements, labels or confidence floors.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
from pathlib import Path

from evaluations.bootstrap_agent_trial import (
    Audit,
    MeasuredJev,
    RequestBudget,
    digest,
    write_exclusive,
)
from signalweave.engine import InsightEngine
from signalweave.evaluation import CardEvaluationCase, CardWorkflowEvaluator
from signalweave.models import InsightCard


def prepare(trace: Path) -> tuple[dict, dict, list[dict]]:
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    evaluation = next(e for e in reversed(events)
                      if e.get("kind") == "tool.result" and e.get("name") == "evaluate_card_workflow"
                      and e.get("result", {}).get("cases"))
    card = next(e["result"] for e in reversed(events)
                if e.get("kind") == "tool.result" and e.get("name") == "get_insight_card"
                and e.get("result", {}).get("id") == evaluation["arguments"]["card_id"])
    cases = evaluation["arguments"]["cases"]
    if not card.get("watch_for") or not 1 <= len(cases) <= 20:
        raise ValueError("Needs existing watch prose and 1..20 retained historical cases")
    candidate = copy.deepcopy(card)
    candidate["decision_guidance"] += "\n" + "\n".join(card["watch_for"])
    candidate["version"] += 1
    candidate["compiled_plan"]["card_version"] = candidate["version"]
    return copy.deepcopy(card), candidate, copy.deepcopy(cases)


async def run(trace: Path, output: Path, key_file: Path | None) -> dict:
    original, candidate, cases = prepare(trace)
    output.mkdir(parents=True, exist_ok=False)
    inputs = {"original": original, "candidate": candidate, "cases": cases}
    protocol = {"version": "policy-placement-probe-v1", "live": key_file is not None,
                "input_digest": digest(inputs), "attempt_cap": len(cases) * 2,
                "scope": "In-process historical diagnostic, not binary onboarding or an unseen test",
                "mutation": "Repeat existing watch_for verbatim in decision_guidance; bump card/plan version only"}
    write_exclusive(output / "protocol.json", protocol)
    write_exclusive(output / "inputs.json", inputs)
    if key_file is None:
        return protocol
    key = key_file.read_text().strip()
    audit = Audit(output / "trace.jsonl", (key,))
    budget = RequestBudget(len(cases) * 2)
    judger = MeasuredJev(key, budget, audit)
    results = []
    for index, case in enumerate(cases):
        # Alternate pair order to avoid making every candidate the later call.
        arms = [("original", original), ("candidate", candidate)]
        for arm, card in (arms if index % 2 == 0 else reversed(arms)):
            parsed = CardEvaluationCase.model_validate({**case, "card": InsightCard.model_validate(card)})
            report = await CardWorkflowEvaluator(InsightEngine(judger)).evaluate(
                [parsed], acceptance_outcomes=[parsed.expected_outcome],
            )
            results.append({"arm": arm, "case_id": case["id"], "report": report.model_dump(mode="json")})
    result = {"protocol": protocol, "attempts": budget.used, "results": results}
    write_exclusive(output / "report.json", audit.redact(result))
    return {"attempts": budget.used, "cases": [
        {"arm": r["arm"], **{k: r["report"]["cases"][0][k] for k in
                              ("expected_outcome", "outcome", "confidence", "probabilities", "failure_reasons")}}
        for r in results
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live and args.key_file is None:
        parser.error("--live requires --key-file")
    print(json.dumps(asyncio.run(run(args.trace, args.output, args.key_file if args.live else None)), indent=2))


if __name__ == "__main__":
    main()

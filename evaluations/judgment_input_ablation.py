"""Replay retained Jev inputs with single-factor state ablations, not a product benchmark."""

import argparse
import asyncio
import copy
import gzip
import hashlib
import json
from pathlib import Path

from evaluations.bootstrap_agent_trial import Audit, RequestBudget, json_value
from evaluations.bootstrap_empirical_trial import TrialJev
from evaluations.business_outcome_probe import SELECTION
from evaluations.business_outcome_trial import write_json
from evaluations.onboarding_acceptance_trial import source_freeze
from signalweave.typesafe_adapter import load_api_key

ARMS = ("original", "deduplicated", "without_plan")


def variant(state, arm):
    """Each alternative differs from original in one factor, never drops evidence."""
    result = copy.deepcopy(state)
    if arm == "deduplicated":
        for duplicate, retained in (("card", "insight_card"),
                                    ("priority_observations", "observations")):
            if result[duplicate] != result[retained]:
                raise ValueError("A proposed duplicate differs; refusing lossy projection")
            del result[duplicate]
    elif arm == "without_plan":
        del result["insight_plan"]
    elif arm != "original":
        raise ValueError("Unknown ablation arm")
    return result


def retained_inputs(primary):
    manifest = json.loads((primary / "manifest.json").read_text())
    expected = json.loads((primary / "expected.json").read_text())
    with gzip.open(primary / "events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    rows = {}
    for company in manifest["companies"]:
        requests = [e for e in events if e["kind"] == "api.request"
                    and e.get("provider") == "jev"
                    and e["episode"] == company["id"] + ":signalweave"]
        if len(requests) != len(company["periods"]):
            raise ValueError("Cannot bind requests to chronological periods")
        for period, request in zip(company["periods"], requests, strict=True):
            refs = [ref for analysis in request["state"]["analyses"]
                    for ref in analysis["query_refs"]]
            if not refs or any(not ref.endswith(":" + period["id"]) for ref in refs):
                raise ValueError("Request query provenance does not match the intended period")
            if (request["model"], request["stage"], request["timeout_seconds"]) != ("jev-latest", "judgment", 30):
                raise ValueError("Original transport configuration differs from replay")
            rows[company["id"], period["id"]] = {
                "id": company["id"] + ":" + period["id"],
                "state": request["state"], "questions": request["questions"],
                "expected": expected[company["id"]][period["id"]],
                "original_request_id": request["request_id"],
                "original_transport": {key: request[key] for key in ("model", "stage", "timeout_seconds")},
            }
    return [rows[identity] for identity in SELECTION]


async def run(primary, output, *, live=False, key_file=None):
    rows = retained_inputs(primary)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "manifest.json", {
        "scope": __doc__, "freeze": source_freeze(), "arms": ARMS,
        "budget": 3 * len(rows), "rows": rows,
        "journal_sha256": hashlib.sha256((primary / "events.jsonl.gz").read_bytes()).hexdigest(),
        "limitations": ["Known cases, single repetition per cell, no final prose or baseline",
                        "Original questions unchanged; original model alias may have evolved",
                        "without_plan removes unique plan context, not just duplicates",
                        "Scores cover gated outcome only, not full engine evidence/recipient gates"],
    })
    if not live:
        return {"status": "dry_run", "attempts": 0}
    key = load_api_key(key_file)
    audit = Audit(path=output / "events.jsonl", secrets=(key,))
    budget = RequestBudget(3 * len(rows))
    judger = TrialJev(key, budget, audit)
    results = []
    for index, row in enumerate(rows):
        order = ARMS[index % 3:] + ARMS[:index % 3]
        for arm in order:
            audit.episode = row["id"] + ":" + arm
            result = {"id": row["id"], "arm": arm, "expected": row["expected"]["outcome"]}
            try:
                response = await judger._system_one_with_retry(
                    state=variant(row["state"], arm), questions=row["questions"], stage="ablation")
                answer = response.choices["outcome"]
                threshold = row["state"]["insight_card"]["action_confidence_threshold"]
                selected = str(answer.choice)
                support = answer.probabilities[selected]
                if not 0 <= support <= 1:
                    raise ValueError("Malformed selected support")
                routed = selected if support >= threshold else "investigate"
                result.update(response=json_value(response), outcome=routed,
                              selected=answer.choice, support=support,
                              passed=routed == result["expected"])
            except Exception as error:
                result.update(error=audit.redact(str(error)), passed=False)
            results.append(result)
            write_json(output / "progress.json", results)
    report = {"results": results, "attempts": budget.used,
              "summary": {arm: {"passed": sum(r["passed"] for r in results if r["arm"] == arm),
                                "intended": len(rows)} for arm in ARMS}}
    write_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--jev-key-file")
    args = parser.parse_args()
    result = asyncio.run(run(args.primary, args.output, live=args.live, key_file=args.jev_key_file))
    print(json.dumps({key: value for key, value in result.items() if key != "results"}))


if __name__ == "__main__":
    main()

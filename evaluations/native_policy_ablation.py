"""Bounded sensitivity test of retained Jev policy requests, not a product benchmark."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path

from evaluations.bootstrap_agent_trial import json_value, write_exclusive
from signalweave.typesafe_adapter import DEFAULT_MAX_JEV_INPUT_TOKENS, estimate_json_tokens

ARMS = ("policy_selection", "contract_facts", "policy_selection_contract_facts")
MAX_REQUESTS = 12


def load_cases(trial: Path) -> list[dict]:
    report = json.loads((trial / "report.json").read_text())
    if report["status"] != "completed" or len(report["periods"]) != 4:
        raise ValueError("A completed four-case pilot is required")
    events = [json.loads(line) for line in (trial / "trace.jsonl").read_text().splitlines()]
    responses = {event["request_id"]: event for event in events
                 if event.get("kind") == "api.response" and event.get("provider") == "jev"}
    cases = []
    for row in report["periods"]:
        requests = [event for event in events if event.get("kind") == "api.request"
                    and event.get("provider") == "jev"
                    and event.get("episode", "").endswith(f"/{row['period_id']}/treatment")]
        if len(requests) != 1 or requests[0]["request_id"] not in responses:
            raise ValueError("Exactly one retained request/response per case is required")
        request = requests[0]
        response = responses[request["request_id"]]["response"]
        cases.append({"period_id": row["period_id"], "state": request["state"],
                      "questions": request["questions"], "model": request["model"],
                      "baseline": response, "expected": row["treatment"]["score"]["expected_outcome"],
                      "threshold": request["state"]["card"]["action_confidence_threshold"]})
    return cases


def variant(case: dict, arm: str) -> tuple[dict, dict]:
    if arm not in ARMS:
        raise ValueError("Unknown arm")
    state, questions = copy.deepcopy(case["state"]), copy.deepcopy(case["questions"])
    if "contract_facts" in arm:
        for source in state.get("sources", []):
            metadata = source.pop("metadata", None)
            if metadata is not None:
                source["metadata_omitted_for_experiment"] = True
        # This tests whether the already-normalized records suffice in these
        # four cases. It is not an assertion that arbitrary metadata is useless.
    if arm.startswith("policy_selection"):
        outcome = questions["outcome"]
        outcome["instructions"] = (
            "Which outcome does the owner's card.decision_guidance select for the supplied "
            "measurement window? Apply explicit ordered rules in their stated order, using "
            "the normalized evidence and source definitions. This is a policy recommendation, "
            "not an external action. A retrospective review or delivery-disabled execution does "
            "not change which outcome the policy selects. Diagnostic watch items are not extra "
            "trigger conditions. Do not invent a threshold, prerequisite, or causal explanation."
        )
        outcome["criteria"] = {
            key: (f"The owner's applicable rule selects {key}. Follow the owner's thresholds, "
                  "exceptions, and fallback exactly; a configured route is not a trigger. "
                  "Select investigation for uncertainty only when the policy calls for it, "
                  "not as a replacement for an explicit quiet or notification rule.")
            for key in outcome["criteria"]
        }
    assert state["card"] == case["state"]["card"]
    assert state["observations"] == case["state"]["observations"]
    for key in case["state"]:
        if key != "sources":
            assert state[key] == case["state"][key]
    for actual, original in zip(state.get("sources", []), case["state"].get("sources", []), strict=True):
        assert {k: v for k, v in actual.items() if k != "metadata_omitted_for_experiment"} == {
            k: v for k, v in original.items() if k != "metadata"
        } if "contract_facts" in arm else actual == original
    assert {k: v for k, v in questions.items() if k != "outcome"} == {
        k: v for k, v in case["questions"].items() if k != "outcome"
    }
    return state, questions


def assessment(answer: dict, threshold: float, expected: str) -> dict:
    selected = answer["choice"]
    support = answer["probabilities"][selected]
    routed = selected if support >= threshold else "investigate"
    return {"selected": selected, "support": support, "routed": routed,
            "raw_correct": selected == expected, "routed_correct": routed == expected}


async def run(trial: Path, output: Path, *, live: bool, key_file: Path | None) -> dict:
    cases = load_cases(trial)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    prepared = []
    for index, case in enumerate(cases):
        for arm in ARMS[index % 3:] + ARMS[:index % 3]:
            state, questions = variant(case, arm)
            tokens = estimate_json_tokens({"state": state, "questions": questions})
            prepared.append((case, arm, state, questions, tokens))
    protocol = {
        "scope": __doc__, "arms": list(ARMS), "physical_request_cap": MAX_REQUESTS,
        "timeout_seconds": 30, "retries": 0, "input_token_guard": DEFAULT_MAX_JEV_INPUT_TOKENS,
        "trace_sha256": hashlib.sha256((trial / "trace.jsonl").read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "prepared": [{"period_id": case["period_id"], "arm": arm, "state": state,
                      "questions": questions, "estimated_tokens": tokens}
                     for case, arm, state, questions, tokens in prepared],
        "limitations": ["Four known synthetic cases, one call per cell; not holdout or enterprise evidence.",
                        "Metadata removal is an experimental projection, not a production-safe generalization.",
                        "Baseline is the saved response, not a fresh randomized control.",
                        "Only input/decision sensitivity is assessed; no agent, source latency, or delivery claim."],
    }
    write_exclusive(output / "protocol.json", protocol)
    results = [{"period_id": case["period_id"], "arm": "cached_baseline", "expected": case["expected"],
                **assessment(case["baseline"]["answers"]["outcome"], case["threshold"], case["expected"])}
               for case in cases]
    requests = 0
    if live:
        if key_file is None:
            raise ValueError("Live mode requires a key file")
        from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy
        key = key_file.read_text().strip()
        if not key:
            raise ValueError("Empty Jev key")
        async with AsyncTypeSafeClient(
            api_key=key, timeout=30, retry=RetryPolicy(max_retries=0),
            base_url="https://api.typesafe.ai",
        ) as client:
            for case, arm, state, questions, tokens in prepared:
                row = {"period_id": case["period_id"], "arm": arm, "expected": case["expected"]}
                if tokens > DEFAULT_MAX_JEV_INPUT_TOKENS:
                    row.update(status="local_preflight_not_run", estimated_tokens=tokens)
                else:
                    if requests >= MAX_REQUESTS:
                        raise RuntimeError("Physical request cap reached")
                    requests += 1
                    try:
                        response = json_value(await client.system_one(
                            state=state, questions=questions, model=case["model"]))
                        if response["model"] != case["baseline"]["model"]:
                            row.update(status="model_changed", response=response)
                        else:
                            row.update(status="completed", response=response,
                                       **assessment(response["answers"]["outcome"],
                                                    case["threshold"], case["expected"]))
                    except Exception as error:
                        row.update(status="provider_failed", error_type=type(error).__name__)
                results.append(row)
                (output / "progress.json").write_text(json.dumps(results, indent=2))
    report = {"status": "completed" if live else "dry_run", "physical_requests": requests,
              "results": results, "limitations": protocol["limitations"]}
    write_exclusive(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(run(args.trial, args.output, live=args.live, key_file=args.key_file))
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))


if __name__ == "__main__":
    main()

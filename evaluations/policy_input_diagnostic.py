"""Bounded, opt-in component diagnosis; never a workflow acceptance benchmark."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import random
import time
from pathlib import Path

import httpx

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.harbor_workflow_journey import read, write
from evaluations.harbor_workflow_preflight import _sha
from evaluations.installed_trial_transport import _private_dir, _private_file


def variant(payload, spec):
    result = copy.deepcopy(payload)
    fields = spec.get("remove_plan_slot_fields", [])
    if fields:
        for slot in result["state"]["insight_plan"]["evidence_slots"]:
            for field in fields:
                del slot[field]
    if spec.get("append_policy"):
        result["state"]["card"]["decision_guidance"] += " " + spec["append_policy"]
    return result


def encoded(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def prepare(protocol, output):
    protocol, output = Path(protocol).absolute(), Path(output).absolute()
    if output.exists():
        raise ValueError("New output directory required")
    spec = read(protocol)
    rows, inputs = [], {str(protocol): _sha(protocol), str(Path(__file__)): _sha(Path(__file__))}
    for source in spec["sources"]:
        path = Path(source["path"]).absolute()
        events = [json.loads(line) for line in path.read_text().splitlines()]
        requests = [event for event in events if event.get("kind") == "api.request" and event.get("provider") == "jev"]
        if len(requests) != 1:
            raise ValueError("Exactly one actual Jev request per recorded case required")
        inputs[str(path)] = _sha(path)
        payload = {key: requests[0][key] for key in ("model", "state", "questions")}
        for edit in spec["variants"]:
            body = variant(payload, edit)
            rows.append({"case": source["id"], "variant": edit["name"], "payload": body,
                         "expected_outcomes": source["expected_outcomes"],
                         "wire_sha256": hashlib.sha256(encoded(body)).hexdigest()})
    if len(rows) != spec["max_requests"]:
        raise ValueError("Request cap must match the complete prespecified design")
    random.Random(spec["seed"]).shuffle(rows)
    _private_dir(output)
    write(output/"prepared.json", {"scope": spec["scope"], "inputs": inputs, "rows": rows,
                                   "max_requests": spec["max_requests"], "resolved_model": spec["resolved_model"]})
    return {"prepared": len(rows), "provider_calls": 0}


async def run(output, key_file):
    output = Path(output).absolute()
    prepared = read(output/"prepared.json")
    for path, digest in prepared["inputs"].items():
        if _sha(Path(path)) != digest:
            raise ValueError("Frozen diagnostic input changed")
    _private_file(output/"run.claimed", _sha(output/"prepared.json"))
    key = Path(key_file).read_text().strip()
    audit = Audit(path=output/"attempts.jsonl", secrets=(key,))
    budget = RequestBudget(prepared["max_requests"])
    previous = prepared.get("previous_attempts", 0)
    results = list(prepared.get("inherited_results", []))
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30) as client:
        for row in prepared["rows"]:
            body = encoded(row["payload"])
            if hashlib.sha256(body).hexdigest() != row["wire_sha256"]:
                raise ValueError("Prepared payload changed")
            budget.claim()
            request_id = previous + budget.used
            audit.emit("api.request", request_id=request_id, case=row["case"], variant=row["variant"],
                       payload=row["payload"], wire_sha256=row["wire_sha256"])
            started = time.perf_counter()
            result = {"case": row["case"], "variant": row["variant"], "request_id": request_id,
                      "expected_outcomes": row["expected_outcomes"], "usage_known": False}
            try:
                response = await client.post("https://api.typesafe.ai/v1/systemone", content=body,
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
                response.raise_for_status()
                actual = response.json()
                usage = actual.get("usage", {})
                result.update(response=actual, usage_known=all(type(usage.get(k)) is int for k in ("input_tokens", "output_tokens")))
                if actual.get("model") != prepared["resolved_model"]:
                    raise ValueError("Resolved model changed; further calls not admitted")
            except Exception as error:  # noqa: BLE001 - retain failed attempt, never retry
                result["error"] = {"type": type(error).__name__, "message": audit.redact(str(error))}
            result["seconds"] = time.perf_counter()-started
            audit.emit("api.result", **result)
            results.append(result)
            write(output/f"result-{request_id:03d}.json", audit.redact(result))
            if result.get("error") or not result["usage_known"]:
                break
    summary = {"scope": prepared["scope"], "attempts": previous + budget.used, "rows": results}
    write(output/"results.json", audit.redact(summary))
    return {"attempts": summary["attempts"], "planned": previous + prepared["max_requests"], "errors": sum(bool(r.get("error")) for r in results)}


def prepare_remaining(original, output, original_runner):
    """Continue only unsubmitted payloads after a known local logging failure."""
    original, output, original_runner = (Path(p).absolute() for p in (original, output, original_runner))
    if output.exists():
        raise ValueError("New continuation directory required")
    old = read(original/"prepared.json")
    runner = str(Path(__file__))
    if _sha(original_runner) != old["inputs"][runner]:
        raise ValueError("Original method backup differs")
    for path, digest in old["inputs"].items():
        if path != runner and _sha(Path(path)) != digest:
            raise ValueError("Original diagnostic input changed")
    audit_path = original/"attempts.jsonl"
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    requests = [e for e in events if e["kind"] == "api.request"]
    results = [e for e in events if e["kind"] == "api.result"]
    if not 0 < len(requests) == len(results) < len(old["rows"]):
        raise ValueError("Cannot continue an unknown or complete attempt set")
    for index, (request, result) in enumerate(zip(requests, results, strict=True)):
        row = old["rows"][index]
        if (request["request_id"] != index+1 or result["request_id"] != index+1
                or request["payload"] != row["payload"] or request["wire_sha256"] != row["wire_sha256"]
                or any(result[k] != row[k] for k in ("case", "variant", "expected_outcomes"))
                or result.get("error") or result.get("usage_known") is not True
                or result.get("response", {}).get("model") != old["resolved_model"]):
            raise ValueError("Completed prefix does not bind the frozen planned requests")
    amended = {**old, "scope": old["scope"] + " Continuation after local exclusive-summary-write failure; prior paid calls are retained, not retried.",
               "previous_attempts": len(results), "inherited_results": results,
               "rows": old["rows"][len(results):], "max_requests": old["max_requests"]-len(results),
               "inputs": {**old["inputs"], runner: _sha(Path(runner)),
                          str(original_runner): _sha(original_runner),
                          str(original/"prepared.json"): _sha(original/"prepared.json"), str(audit_path): _sha(audit_path)}}
    _private_dir(output)
    write(output/"prepared.json", amended)
    return {"prior_attempts": len(results), "remaining": amended["max_requests"], "total_cap": old["max_requests"], "provider_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "prepare-remaining", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--original-runner", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare" and args.protocol:
        result = prepare(args.protocol, args.output)
    elif args.mode == "run" and args.key_file:
        result = asyncio.run(run(args.output, args.key_file))
    elif args.mode == "prepare-remaining" and args.original and args.original_runner:
        result = prepare_remaining(args.original, args.output, args.original_runner)
    else:
        parser.error("prepare needs --protocol; run needs --key-file")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

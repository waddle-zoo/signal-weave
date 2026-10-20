"""Offline preparation / explicitly admitted research replay; never certification."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import random
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
import httpx2
from typesafe_sdk import AsyncTypeSafeClient

from evaluations.installed_trial_transport import _private_dir, _private_file
from scripts.binary_provenance import source_fingerprint
from signalweave.engine import InsightEngine
from signalweave.models import InsightCard, ResourceSnapshot
from signalweave.typesafe_adapter import JevJudger

ROOT = Path(__file__).resolve().parents[1]
MODEL = "jev-1.13.0"
LIMITS = {"attempts": 16, "input_tokens": 120_000, "output_tokens": 4_000}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    _private_file(path, json.dumps(value, indent=2, allow_nan=False) + "\n")


class Captured(BaseException):
    """Stop before inference without manufacturing a model answer."""


async def evaluate(card, snapshot, clock, handler):
    judger = JevJudger(api_key="offline-transport", timeout=30, max_retries=0,
                       max_input_tokens=12_000, max_payload_bytes=4_000_000,
                       evidence_role_classification=False)
    judger.name = MODEL
    judger._client_type = lambda **kw: AsyncTypeSafeClient(transport=httpx2.MockTransport(handler), **kw)
    engine = InsightEngine(judger, clock=lambda: datetime.fromisoformat(clock))
    return await engine.evaluate(InsightCard.model_validate(card), [ResourceSnapshot.model_validate(snapshot)])


def synthetic(snapshot, original_rows, spec):
    """Alter date/channel rows, then derive every published quantitative fact."""
    rows = copy.deepcopy(original_rows)
    periods = sorted({r["period"] for r in rows})
    if len(rows) != 56 or len(periods) != 2 or not periods[0].startswith("current_"):
        raise ValueError("Fixture ambiguity: expected two seven-day, four-channel periods")
    dates = {p: sorted({r["order_date"] for r in rows if r["period"] == p}) for p in periods}
    unit = next((e["values"]["unit"] for e in snapshot["evidence"] if e.get("subject_id") == "all-digital-net-sales"), None)
    if not unit:
        raise ValueError("Fixture ambiguity: missing source unit")
    windows = {"current_window": f"{dates[periods[0]][0]} through {dates[periods[0]][-1]}",
               "prior_window": f"{dates[periods[1]][0]} through {dates[periods[1]][-1]}", "unit": unit}
    channels = ["Online", "Mobile", "Marketplace", "Store"]
    if any(len(dates[p]) != 7 or {(r["order_date"], r["channel"]) for r in rows if r["period"] == p}
           != {(d, c) for d in dates[p] for c in channels} for p in periods):
        raise ValueError("Fixture ambiguity: nonunique or incomplete seed date/channel grid")
    for r in rows:
        r["net_sales"] = str(Decimal("10000") if r["period"] == periods[1] else
                             Decimal("25000") if r["channel"] == "Store" else Decimal(spec["current_digital_daily"]))
    if spec.get("missing_current"):
        rows = [r for r in rows if (r["period"], r["order_date"]) != (periods[0], dates[periods[0]][0])]
    if spec.get("duplicate_prior"):
        for r in rows:
            if (r["period"], r["order_date"]) == (periods[1], dates[periods[1]][0]):
                r["order_date"] = dates[periods[1]][1]
    scopes = {"all_digital": channels[:3], "company": channels, **{c: [c] for c in channels}}
    totals, coverage = {}, {}
    for scope, members in scopes.items():
        totals[scope], coverage[scope] = [], []
        for p in periods:
            selected = [r for r in rows if r["period"] == p and r["channel"] in members]
            represented = {r["order_date"] for r in selected}
            totals[scope].append(sum((Decimal(r["net_sales"]) for r in selected), Decimal(0)))
            coverage[scope].append({"dates_present": len(represented), "missing_dates": sorted(set(dates[p])-represented),
                                    "channel_row_counts": {c: sum(r["channel"] == c for r in selected) for c in members}})
    complete = all(x["dates_present"] == 7 for x in coverage["all_digital"])
    def amounts(scope):
        current, prior = totals[scope]
        return {"current": str(current), "prior": str(prior), "delta": str(current-prior),
                "change_pct": str((current/prior-1)*100) if complete else None}
    fixture = copy.deepcopy(snapshot)
    fixture.update(description="Hypothetical date/channel-row control, not an observed warehouse result.",
                   source_url=None, source_captured_at=None, observations=[], analytical_comparisons=[], metadata={
                       "hypothetical": True, "parent_rows_sha256": digest(json.dumps(original_rows, sort_keys=True).encode()),
                       "lineage": "Synthetic amounts/dates derived from retained date/channel rows; no new source read."})
    facts = [
        ("observed-date-presence", "Distinct represented dates; row count is not date coverage.", {"days_expected_each": 7, "periods": periods, "scopes": coverage}),
        ("all-digital-net-sales", "Computed digital net sales for Online, Mobile, Marketplace.", {**amounts("all_digital"), "channels": channels[:3], "comparison_available": complete}),
        ("company-net-sales-bridge", "Computed company and Store bridge.", {**amounts("company"), "digital_delta": str(totals["all_digital"][0]-totals["all_digital"][1]), "store_delta": str(totals["Store"][0]-totals["Store"][1])}),
        ("channel-net-sales-movements", "Channel context; seasonal equivalence and causes are not established.", {c: amounts(c) for c in channels}),
    ]
    if spec.get("scope_conflict"):
        narrower = sum((Decimal(r["net_sales"]) for r in rows if r["period"] == periods[0] and r["channel"] in channels[:2]), Decimal(0))
        fixture["contract"].update(population="Online and Mobile only; Marketplace excluded", source_status="ambiguous")
        facts.append(("scope-reconciliation", "Declared source population excludes Marketplace; listed-channel sum conflicts with the published all-digital total.",
                      {"listed_channel_sum": str(narrower), "published_digital_total": str(totals["all_digital"][0])}))
    fixture["evidence"] = [{"source_key": fixture["source_key"], "subject_id": key, "statement": text,
                            "values": {**windows, **values}, "provenance": ["hypothetical:date-channel-row-transformation"]}
                           for key, text, values in facts]
    return fixture, rows


async def prepare(protocol, output):
    protocol, output = Path(protocol).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("New output directory required")
    spec, originals, paths = read(protocol), {}, [protocol, Path(__file__)]
    for day, files in spec["sources"].items():
        report_path, trace_path = [ROOT / files[k] for k in ("report", "trace")]
        paths.extend([report_path, trace_path])
        report = read(report_path)
        events = [json.loads(line) for line in trace_path.read_text().splitlines()]
        inspections = [c["result"] for c in report["native_calls"] if c["name"] == "inspect_resource"]
        if len(inspections) != 1:
            raise ValueError("Fixture ambiguity: expected one retained inspection")
        snapshot = copy.deepcopy(inspections[0])
        snapshot.pop("_caller_artifact", None)
        card = report["card_after"]
        if len(card["sources"]) != 1 or card["delivery_methods"] or card["action_confidence_threshold"] != .7:
            raise ValueError("Unexpected retained card settings")
        snapshot["source_key"] = card["sources"][0]["key"]
        for fact in snapshot["evidence"]:
            fact["source_key"] = snapshot["source_key"]
        queries = [json.loads(e["result"]["result"]) for e in events if e.get("kind") == "tool.result" and e.get("name") == "company_superset_sqllab_execute"]
        if len(queries) != 1:
            raise ValueError("Fixture ambiguity: expected one retained date/channel query")
        originals[day] = {"card": card, "inspection": inspections[0], "bound_snapshot": snapshot, "queries": queries}
    if originals["05"]["card"] != originals["12"]["card"]:
        raise ValueError("Fixture ambiguity: retained cards differ")
    records = []
    for case in spec["cases"]:
        source = originals[case["seed"]]
        snapshot, rows = (source["bound_snapshot"], None) if case["actual"] else synthetic(source["bound_snapshot"], source["queries"][0]["data"], case)
        for policy in ("original", "ordered"):
            card = copy.deepcopy(source["card"])
            if policy == "ordered":
                card["decision_guidance"] = spec["ordered_guidance"]
            record = {"case": case, "policy": policy, "card": card, "snapshot": snapshot, "derived_rows": rows}
            async def capture(request, record=record):
                record["wire"] = request.content.decode()
                record["wire_sha256"] = digest(request.content)
                raise Captured()
            try:
                await evaluate(card, snapshot, spec["clock"], capture)
            except Captured:
                pass
            if "wire" not in record:
                raise ValueError("Production engine did not emit exactly one judgment")
            records.append(record)
    random.Random(spec["seed"]).shuffle(records)
    if len(records) != LIMITS["attempts"]:
        raise ValueError("Exactly sixteen prepared requests required")
    _private_dir(output)
    save(output/"prepared.json", {"protocol": spec, "originals": originals, "records": records,
                                  "source_fingerprint": source_fingerprint(ROOT),
                                  "inputs": {str(p): digest(p.read_bytes()) for p in paths}, "limits": LIMITS})
    return {"prepared": len(records), "provider_calls": 0, "certification": False}


async def run(output, key_file):
    """Requires separate admission; one pass, no retry, actual usage stops between requests."""
    output = Path(output).resolve()
    prepared = read(output/"prepared.json")
    if source_fingerprint(ROOT) != prepared["source_fingerprint"]:
        raise ValueError("Production source fingerprint changed")
    for path, expected in prepared["inputs"].items():
        if digest(Path(path).read_bytes()) != expected:
            raise ValueError("Frozen input changed")
    records = prepared["records"]
    if len(records) != 16 or prepared["limits"] != LIMITS:
        raise ValueError("Frozen request limits changed")
    for r in records:
        if digest(r["wire"].encode()) != r["wire_sha256"]:
            raise ValueError("Frozen wire changed")
    _private_file(output/"run.claimed", digest((output/"prepared.json").read_bytes()))
    key, attempts, inputs, outputs, results = Path(key_file).read_text().strip(), 0, 0, 0, []
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
        for r in records:
            if inputs >= LIMITS["input_tokens"] or outputs >= LIMITS["output_tokens"]:
                break
            item = {"case": r["case"], "policy": r["policy"], "wire_sha256": r["wire_sha256"], "business_behavior": "requires independent review; raw label agreement is not efficacy"}
            async def forward(request, r=r, item=item):
                nonlocal attempts, inputs, outputs
                if request.content != r["wire"].encode() or attempts >= 16:
                    raise ValueError("Production wire differs or attempt cap exhausted")
                attempts += 1
                save(output/f"attempt-{attempts:03d}.json", {"case_id": r["case"]["id"], "policy": r["policy"], "wire_sha256": r["wire_sha256"]})
                response = await client.post("https://api.typesafe.ai/v1/systemone", content=request.content, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
                response.raise_for_status()
                item["raw_response"] = response.json()
                raw = item["raw_response"]
                usage = raw.get("usage", {})
                if any(type(usage.get(k)) is not int or usage[k] < 0 for k in ("input_tokens", "output_tokens")):
                    raise ValueError("Unknown usage")
                inputs += usage["input_tokens"]
                outputs += usage["output_tokens"]
                if raw.get("model") != MODEL:
                    raise ValueError("Changed resolved model")
                return httpx2.Response(200, json=item["raw_response"])
            try:
                evaluated = await evaluate(r["card"], r["snapshot"], prepared["protocol"]["clock"], forward)
                raw = item["raw_response"]
                item.update(raw_choice=raw["answers"]["outcome"], routed=evaluated.result.model_dump(mode="json"))
            except Exception as error:  # noqa: BLE001 - retain failures, never retry
                item["error"] = type(error).__name__  # Never persist credentials / transport exception bodies.
            results.append(item)
            save(output/f"result-{len(results):03d}.json", item)
            if "error" in item:
                break
    save(output/"results.json", {"attempts": attempts, "input_tokens": inputs, "output_tokens": outputs,
                                 "complete": len(results) == 16 and not any("error" in r for r in results), "certification": False, "results": results})
    return {"attempts": attempts, "completed": len(results), "certification": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=ROOT/"evaluations/protocols/northstar-policy-contrasts.json")
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    if args.mode == "run" and not args.key_file:
        parser.error("run requires --key-file and separate research admission")
    result = asyncio.run(prepare(args.protocol, args.output) if args.mode == "prepare" else run(args.output, args.key_file))
    print(json.dumps({"output": str(args.output.resolve()), **result}))


if __name__ == "__main__":
    main()

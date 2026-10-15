"""Small opt-in live-Jev integration trial; no heuristic or simulated model results.

One saved business brief; six synthetic scenarios. Actual
SQLite aggregations → actual stdio MCP → Jev → code-side analysis → local receipt.
This deliberately isolates execution after an operator has approved source meaning
and card policy. It is not an unassisted-onboarding or causal-inference benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from signalweave.engine import InsightEngine
from signalweave.local_run import run_card
from signalweave.mcp_source import build_mcp_sources
from signalweave.models import DeliveryMethod, InsightCard, InsightCardStatus, Outcome, SourceRef
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteDecisionReceiptStore, SQLiteInsightCardStore
from signalweave.typesafe_adapter import JevJudger, load_api_key

ROOT = Path(__file__).resolve().parents[1]


def cases():
    # period, segment, additive value, rate numerator, rate denominator
    yield "offsetting-segments", "additive", [
        ("baseline", "online", 60, None, None), ("baseline", "store", 40, None, None),
        ("current", "online", 30, None, None), ("current", "store", 50, None, None),
    ], "complete", -20, None, None
    yield "flat-total-hidden-movement", "additive", [
        ("baseline", "enterprise", 90, None, None), ("baseline", "self-serve", 10, None, None),
        ("current", "enterprise", 70, None, None), ("current", "self-serve", 30, None, None),
    ], "complete", 0, None, None
    yield "simpson-reversal", "rate", [
        ("baseline", "returning", None, 81, 90), ("baseline", "new", None, 1, 10),
        ("current", "returning", None, 10, 10), ("current", "new", None, 18, 90),
    ], "complete", -.54, .10, -.64
    yield "mix-only", "rate", [
        ("baseline", "high-intent", None, 72, 90), ("baseline", "low-intent", None, 2, 10),
        ("current", "high-intent", None, 8, 10), ("current", "low-intent", None, 18, 90),
    ], "complete", -.48, 0, -.48
    yield "unchanged", "additive", [
        ("baseline", "east", 60, None, None), ("baseline", "west", 40, None, None),
        ("current", "east", 60, None, None), ("current", "west", 40, None, None),
    ], "complete", 0, None, None
    yield "incomplete-population", "additive", [
        ("baseline", "known", 60, None, None), ("current", "known", 30, None, None),
    ], "partial", None, None, None


def seed(database, kind, rows, coverage):
    definition = {
        "key": "activity-breakdown", "metric": "activity", "definition": "Approved completed activity per eligible population",
        "population": "Production eligible accounts", "unit": "count" if kind == "additive" else "proportion",
        "dimension": "segment", "kind": kind, "baseline_start": "2026-08-01T00:00:00Z",
        "baseline_end": "2026-08-08T00:00:00Z", "current_start": "2026-08-08T00:00:00Z",
        "current_end": "2026-08-15T00:00:00Z", "comparison_window": "previous_period",
        "coverage": coverage, "disjoint_segments": True, "comparable": True,
        "query_refs": ["sqlite:measurements:group-by-period", "sqlite:measurements:group-by-period-segment"],
    }
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS definition(payload TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS measurements(period TEXT, segment TEXT, value REAL, numerator REAL, denominator REAL)")
        connection.execute("DELETE FROM definition")
        connection.execute("DELETE FROM measurements")
        connection.execute("INSERT INTO definition VALUES (?)", (json.dumps(definition),))
        connection.executemany("INSERT INTO measurements VALUES (?,?,?,?,?)", rows)


async def trial(output: Path, key_file: str):
    key = load_api_key(key_file)
    judger = JevJudger(api_key=key, max_retries=0)
    results = []
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="signalweave-local-trial-") as temporary:
        folder = Path(temporary)
        database = folder / "company.sqlite"
        manifest = {"version": 1, "connections": [{
            "name": "company_metrics", "tenant_id": "local", "read_only": True,
            "transport": {"type": "stdio", "command": [sys.executable, str(ROOT / "examples/local-investigation/company_mcp.py"), str(database)]},
            "resources": [{"descriptor": {"adapter": "company_metrics", "resource": "activity", "kind": "measurement",
                                         "title": "Approved activity breakdown", "contract": {"tenant_id": "local"}},
                           "source_key": "activity", "tool": "read_comparison"}],
        }]}
        path = folder / "sources.json"
        path.write_text(json.dumps(manifest))
        registry = SourceRegistry(build_mcp_sources(str(path)))
        card_store = SQLiteInsightCardStore(folder / "runtime.db")
        card_store.save_card(InsightCard(
            id="weekly-activity", title="Explain changes in activity", status=InsightCardStatus.APPROVED,
            what_to_watch="Completed activity and changes in the approved segment breakdown.",
            why_watch="Tell the owner when activity moves and which populations account for the change.",
            watch_for=["The aggregate activity or rate changed, or offsetting segment movements are present."],
            decision_guidance="Use code-computed analyses. Notify when a complete analysis shows any aggregate or segment movement. Ignore when every segment is unchanged. Return insufficient_data when a required analysis is incomplete. A mix effect is not evidence of declining within-segment performance. Accounting is not causation.",
            comparison_windows=["previous_period"],
            sources=[SourceRef(key="activity", adapter="company_metrics", resource="activity", label="Activity comparison", required_comparison_keys=["activity-breakdown"])],
            delivery_methods=[DeliveryMethod(key="analytics", outcome=Outcome.NOTIFY, label="Analytics owner", destination="agent://analytics")],
        ))
        runtime = Runtime(card_store=card_store, sources=registry, engine=InsightEngine(judger, registry),
                          decision_receipts=SQLiteDecisionReceiptStore(folder / "runtime.db"))
        for name, kind, rows, coverage, delta, within, mix in cases():
            seed(database, kind, rows, coverage)
            inspected = await registry.inspect(card_store.get_card("weekly-activity").sources[0])
            if inspected.error or not inspected.analytical_comparisons:
                raise RuntimeError("Example source preflight failed; no Jev call made for this case")
            start = perf_counter()
            response = await run_card("weekly-activity", name, output / "runs", runtime=runtime)
            seconds = perf_counter() - start
            result = response["result"]
            report = result["analyses"][0]
            expected_status = "complete" if coverage == "complete" else "insufficient_data"
            checks = {"analysis_status": report["status"] == expected_status,
                      "noncausal_contract": report["claim_type"] == "accounting_decomposition",
                      "delivery_disabled": response["receipt"]["delivery_enabled"] is False}
            for field, expected in (("delta", delta), ("within_effect", within), ("mix_effect", mix)):
                if expected is not None:
                    checks[field] = report[field] is not None and abs(report[field] - expected) < 1e-10
            expected_outcome = "insufficient_data" if coverage != "complete" else "ignore" if name == "unchanged" else "notify"
            checks["policy_outcome"] = result["outcome"] == expected_outcome
            if coverage != "complete":
                checks["unknown_not_absent"] = all(item["status"] == "unknown" for item in result["watch_results"])
                checks["blocked_evidence_plan"] = result["evidence_plan"]["status"] == "blocked"
            requests = judger.metrics.requests
            replay = await run_card("weekly-activity", name, output / "runs", runtime=runtime)
            checks["replay_no_jev"] = replay["replayed"] and judger.metrics.requests == requests
            results.append({"case": name, "expected_outcome": expected_outcome, "outcome": result["outcome"],
                            "seconds": seconds, "checks": checks, "analysis": report,
                            "telemetry": result.get("telemetry"), "artifacts": response["artifacts"]})
            (output / "trial.json").write_text(json.dumps({"live_jev": True, "cases": results,
                "requests": judger.metrics.requests, "passed": all(all(row["checks"].values()) for row in results)}, indent=2))
            print(json.dumps({"case": name, "outcome": result["outcome"], "checks": checks}), flush=True)
    return all(all(row["checks"].values()) for row in results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/local-investigation-live")
    args = parser.parse_args()
    os.umask(0o077)
    raise SystemExit(0 if asyncio.run(trial(args.output.resolve(), args.key_file)) else 1)


if __name__ == "__main__":
    main()

"""Six-call development regression probe; never replaces the paired trial.

Two observed offsetting-change misses plus quiet, definition-conflict, stable-high
and missing-data controls. All inputs were seen in the original experiment: this
is a diagnostic patch test, not a new holdout or an end-to-end agent benchmark.
"""

import argparse
import asyncio
import json
from pathlib import Path

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.bootstrap_empirical_trial import TrialJev
from evaluations.business_outcome_trial import validated_retained_card, write_json
from evaluations.first_report_trial import (
    PeriodAdapter,
    dispatch,
    native_submission,
    operator_principal,
    score,
)
from evaluations.onboarding_acceptance_trial import source_freeze
from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteDecisionReceiptStore, SQLiteInsightCardStore
from signalweave.typesafe_adapter import load_api_key

SELECTION = (("northstar-cart", "p07"), ("redwood-fulfillment", "p08"),
             ("northstar-cart", "p06"), ("redwood-fulfillment", "p05"),
             ("harbor-help", "p07"), ("harbor-help", "p06"))


async def run_probe(primary, output, *, live=False, key_file=None):
    manifest = json.loads((primary / "manifest.json").read_text())
    expected = json.loads((primary / "expected.json").read_text())
    historical = json.loads((Path(manifest["onboarding"]["source"]) / "report.json").read_text())
    approved = {r["company"]: r for r in historical["results"]}
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "manifest.json", {
        "scope": __doc__, "selection": SELECTION, "freeze": source_freeze(),
        "max_jev_attempts": 6, "luna_episodes": 0, "primary": str(primary),
        "hypothesis": "Explicit signed-contribution semantics and policy-bound routed-outcome criteria help apply alternatives without changing thresholds or destinations.",
        "changed": "Judgment input semantics and routed outcome description only; no fixture, card, approval or threshold change.",
        "companies": manifest["companies"], "expected": expected,
    })
    if not live:
        return {"status": "dry_run", "paid_calls": 0}
    key = load_api_key(key_file)
    audit = Audit(path=output / "events.jsonl", secrets=(key,))
    budget = RequestBudget(6)
    judger = TrialJev(key, budget, audit)
    results = []
    for company_id, period_id in SELECTION:
        company = next(c for c in manifest["companies"] if c["id"] == company_id)
        period = next(p for p in company["periods"] if p["id"] == period_id)
        audit.episode = company_id + ":" + period_id
        card = validated_retained_card(approved[company_id])
        adapter = PeriodAdapter(company["descriptors"], audit, company["sources"])
        adapter.set_period(period)
        registry = SourceRegistry([adapter])
        database = output / (company_id + "-" + period_id + ".db")
        store = SQLiteInsightCardStore(database)
        store.save_card(card)
        runtime = Runtime(card_store=store, sources=registry,
                          engine=InsightEngine(judger, registry, clock=lambda a=adapter: a.clock),
                          decision_receipts=SQLiteDecisionReceiptStore(database),
                          principal=operator_principal(company))
        row = {"company": company_id, "period": period_id}
        try:
            native = await dispatch(create_mcp(runtime), "evaluate_insight_card", {
                "card_id": card.id, "idempotency_key": period_id})
            row.update(native=native, score=score(native_submission(native, company["destinations"]), expected[company_id][period_id]))
        except Exception as error:
            row.update(error=audit.redact(str(error)), score={"passed": False, "errors": [type(error).__name__]})
        results.append(row)
        write_json(output / "progress.json", results)
    report = {"results": results, "jev_attempts": budget.used, "luna_episodes": 0,
              "passed": sum(r["score"]["passed"] for r in results), "intended": len(SELECTION),
              "scope": "seen-input development regression, no final writer or baseline rerun",
              "primary_scores_replaced": False}
    write_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--jev-key-file")
    args = parser.parse_args()
    result = asyncio.run(run_probe(args.primary, args.output, live=args.live, key_file=args.jev_key_file))
    print(json.dumps({k: v for k, v in result.items() if k != "results"}))


if __name__ == "__main__":
    main()

"""Complete only absent reports after the retained trial's plan-transfer bug.

This is a post hoc execution repair, never a new prospective win. Parent files
are read-only. No completed report, authored policy or production source changes.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

from evaluations import recurring_runtime_trial as trial
from evaluations.recurring_runtime_transfer_cases import cases
from signalweave.models import InsightCard

MAX_JEV = 5
MAX_LUNA = 2
ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_payload(database, table, column, identity):
    # Table/column are only local constants, never agent-selected SQL.
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute(f"SELECT payload FROM {table} WHERE {column} = ?", (identity,)).fetchone()
    return json.loads(row[0]) if row else None


def validate_card(card, public_card):
    trial._assert_approved_runtime_card(card)
    if card.execution_payload() != InsightCard.model_validate(public_card).execution_payload():
        raise ValueError("Stored execution payload differs from frozen owner-approved policy")


def prepare(parent):
    manifest = json.loads((parent / "manifest.json").read_text())
    report = json.loads((parent / "report.json").read_text())
    frozen = json.loads((parent / "frozen-cards.json").read_text())
    companies = cases()
    if (manifest.get("protocol_version") != 1 or report.get("overall_status") != "failed_structured_gate"
            or manifest.get("budgets", {}).get("jev_attempts") != 36
            or manifest.get("budgets", {}).get("luna_total_episodes") != 9
            or manifest.get("budgets", {}).get("retries") != 0):
        raise ValueError("Parent is not the frozen failed bounded protocol")
    if manifest.get("case_set") != "transfer" or manifest["case_hash"] != trial.digest([
        trial._public_company(company) for company in companies
    ]):
        raise ValueError("Original source snapshots or transfer protocol differ")
    current = trial.source_freeze()
    old_source = {name: value for name, value in manifest["freeze"]["source_sha256"].items() if name.startswith("src/")}
    new_source = {name: value for name, value in current["source_sha256"].items() if name.startswith("src/")}
    if old_source != new_source:
        raise ValueError("Production source changed since the original run")
    if current["dependencies"] != manifest["freeze"]["dependencies"]:
        raise ValueError("Runtime dependencies changed")
    pending, cards, missing_receipts = {}, {}, {}
    for company in companies:
        cid = company["id"]
        public = frozen[cid].get("card")
        if not public or frozen[cid]["approval"]["status"] != "approved":
            raise ValueError("Completion cannot author or approve a card")
        card = InsightCard.model_validate(read_payload(parent / f"{cid}-setup.db", "insight_cards", "id", public["id"]))
        validate_card(card, public)
        cards[cid] = card
        rows = [row for row in report["results"] if row["company"] == cid and row["arm"] == "signalweave"]
        if len(rows) != 1:
            raise ValueError("Ambiguous original treatment row")
        finished = [run["period"] for run in rows[0]["runs"]]
        if len(finished) != len(set(finished)):
            raise ValueError("Duplicate original result")
        _, holdout = trial._period_groups(company)
        if not set(finished) <= {period["id"] for period in holdout}:
            raise ValueError("Original result names a non-holdout period")
        for run in rows[0]["runs"]:
            submission = run.get("submission")
            if not isinstance(submission, dict) or not {"status", "outcome", "recipients", "analyses", "narrative"} <= submission.keys():
                raise ValueError("Original row has an ambiguous submission")
            receipt = read_payload(parent / f"{cid}-signalweave.db", "decision_receipts", "idempotency_key", f"business-outcomes:{run['period']}")
            if receipt is None or receipt.get("status") != "delivery_disabled" or not receipt.get("result"):
                raise ValueError("Original submitted report lacks a completed durable receipt")
        absent = [period["id"] for period in holdout if period["id"] not in finished]
        if not absent:
            continue
        pending[cid] = absent
        missing_receipts[cid] = {}
        for period_id in absent:
            receipt = read_payload(parent / f"{cid}-signalweave.db", "decision_receipts", "idempotency_key", f"business-outcomes:{period_id}")
            if receipt is not None and not (
                receipt["status"] == "failed" and receipt.get("outcome") == "insufficient_data"
                and receipt.get("delivery_enabled") is False and receipt.get("delivery_method_keys") == []
                and receipt.get("result") == {
                    "error": "BudgetExceeded: global_api_request_budget_exhausted"
                }
            ):
                raise ValueError("Missing report has a completed or ambiguous durable receipt")
            missing_receipts[cid][period_id] = receipt
    if not pending or len(pending) > MAX_LUNA or sum(map(len, pending.values())) > MAX_JEV:
        raise ValueError("Completion exceeds the frozen missing-report allocation")
    return companies, report, frozen, cards, pending, missing_receipts, current


class GuardedSession(trial.RecurringSession):
    def __init__(self, *, frozen_public_card, card_store, **kwargs):
        super().__init__(**kwargs)
        self.frozen_public_card = copy.deepcopy(frozen_public_card)
        self.card_store = card_store
        self.frozen_full_digest = trial.digest(self.card.model_dump(mode="json"))

    async def call(self, name, args):
        if name == "evaluate_workflow":
            validate_card(self.card, self.frozen_public_card)
            stored = self.card_store.get_card(self.card.id)
            validate_card(stored, self.frozen_public_card)
            if trial.digest(stored.model_dump(mode="json")) != self.frozen_full_digest:
                raise ValueError("Approved stored card or plan changed during completion")
        return await super().call(name, args)


async def run_completion(parent: Path, output: Path, *, live=False, key_file=None):
    companies, original, frozen, cards, pending, receipts, freeze = prepare(parent)
    hashes = {name: sha(parent / name) for name in ("manifest.json", "report.json", "frozen-cards.json", "events.jsonl")}
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "scope": "post hoc missing-report completion; not a prospective pass or latency comparison",
        "live": live, "freeze": freeze, "parent_hashes": hashes, "pending": pending,
        "prior_failed_receipts": receipts, "cards": {cid: card.model_dump(mode="json") for cid, card in cards.items()},
        "approved_card_digests": {cid: trial.digest(card.model_dump(mode="json")) for cid, card in cards.items()},
        "budgets": {"jev": MAX_JEV, "luna": MAX_LUNA, "retries": 0, "authoring": 0},
        "original_status": original["overall_status"], "preserve_original_failed_gate": True,
        "resumable": False, "storage_read_mode": "read-only SQLite",
    }
    trial._write_json(output / "manifest.json", manifest)
    if not live:
        return {"status": "dry_run", "paid_calls": 0, "pending": pending}
    from signalweave.typesafe_adapter import load_api_key
    key = load_api_key(key_file)
    audit = trial.Audit(path=output / "events.jsonl", secrets=(key,))
    budget = trial.RequestBudget(MAX_JEV)
    judger = trial.TrialJev(key, budget, audit)
    completion = []
    for company in companies:
        cid = company["id"]
        if cid not in pending:
            continue
        card = cards[cid]
        public = trial._public_company(company, recurring_only=True)
        public["periods"] = [period for period in public["periods"] if period["id"] in pending[cid]]
        audit.episode = cid + ":completion"
        adapter = trial.CachedPeriodAdapter(public["descriptors"], audit, public["sources"])
        adapter.set_period(public["periods"][0])
        sources = trial.SourceRegistry([adapter])
        db = output / f"{cid}.db"
        store = trial.SQLiteInsightCardStore(db)
        store.save_card(card)
        runtime = trial.Runtime(card_store=store, sources=sources,
                                engine=trial.InsightEngine(judger, sources, clock=lambda a=adapter: a.clock),
                                decision_receipts=trial.SQLiteDecisionReceiptStore(db), principal=trial.operator_principal(public))
        session = GuardedSession(company=public, adapter=adapter, server=trial.create_mcp(runtime), audit=audit,
                                 treatment=True, card_id=card.id, card=card, frozen_public_card=frozen[cid]["card"],
                                 card_store=store)
        previous = next(row for row in original["results"] if row["company"] == cid and row["arm"] == "signalweave")
        try:
            episode = await trial.codex_episode(
                session, key=None, effort="low", budget=trial.RequestBudget(0), audit=audit,
                max_turns=35, max_tool_calls=34, max_output_tokens=7000, timeout_seconds=240,
                instructions_override=trial.BUSINESS_INSTRUCTIONS + (
                    " Use evaluate_workflow once per period before composing the final written report. "
                    "Retain its authoritative outcome, recipients and analyses. "
                    "This is a completion-only execution; do not repeat prior reports or edit the approved card."
                ),
                prompt_override={"brief": public["brief"], "owner_policy": public["owner_policy"],
                                 "saved_card": card.execution_payload(), "period_count": len(public["periods"]),
                                 "past_reports": [run["submission"] for run in previous["runs"]]},
            )
        except Exception as error:
            episode = {"status": "failed", "error": type(error).__name__, "seconds": 0, "tool_calls": 0}
        for run in session.runs:
            period = next(period for period in company["periods"] if period["id"] == run["period"])
            run["score"] = trial.score(run["submission"], period["oracle"], run["numeric_conditions"])
            run.update(catalog_digest=session.catalog_digest, card_digest=trial.digest(card.execution_payload()),
                       completion_only=True)
        completion.append({"company": cid, "arm": "signalweave", "episode": episode, "runs": session.runs})
        trial._write_json(output / "progress.json", {"completion": completion, "jev_attempts": budget.used})
    combined = copy.deepcopy(original["results"])
    for row in completion:
        prior = next(item for item in combined if item["company"] == row["company"] and item["arm"] == "signalweave")
        if {run["period"] for run in row["runs"]} & {run["period"] for run in prior["runs"]}:
            raise ValueError("Completion attempted to replace an existing report")
        prior["runs"].extend(row["runs"])
        prior["completion_episode"] = row["episode"]  # never overwrite the original failed episode
    private = trial._evaluation_companies(companies)
    packet, key_map = trial.masked_review_packet(combined, private)
    packet["scope"] = "Combined artifact review of original reports plus targeted post hoc completions, not a fresh prospective trial."
    trial._write_json(output / "review-input.json", packet)
    trial._write_json(output / "review-key.json", key_map)
    completion_exact = all(
        len(row["runs"]) == len(pending[row["company"]])
        and {run["period"] for run in row["runs"]} == set(pending[row["company"]])
        and row["episode"].get("status") == "complete"
        for row in completion
    ) and len(completion) == len(pending)
    report = {
        "status": "completion_only", "parent_hashes": hashes, "completion": completion,
        "completion_complete": completion_exact,
        "completion_correct": completion_exact and all(run["score"]["passed"] for row in completion for run in row["runs"]),
        "coverage_origin": {
            "original_treatment_reports": sum(len(row["runs"]) for row in original["results"] if row["arm"] == "signalweave"),
            "post_hoc_reports": sum(len(row["runs"]) for row in completion),
            "pending_allocation": pending,
        },
        "combined_results": combined, "combined_coverage": trial.summarize(combined, private),
        "paired": trial._paired(combined, companies), "usage": trial._usage(audit),
        "jev_attempts": budget.used, "luna_episodes": len(completion),
        "original_failed_gate_preserved": True, "prospective_pass": False, "latency_comparable": False,
    }
    if any(sha(parent / name) != value for name, value in hashes.items()):
        raise ValueError("Original artifacts changed during completion")
    checked_cards = prepare(parent)[3]  # recheck runtime, fixtures and original receipt state
    if {cid: trial.digest(card.model_dump(mode="json")) for cid, card in checked_cards.items()} != manifest["approved_card_digests"]:
        raise ValueError("Original approved cards changed during completion")
    trial._write_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--jev-key-file")
    args = parser.parse_args()
    result = asyncio.run(run_completion(args.parent, args.output, live=args.live, key_file=args.jev_key_file))
    print(json.dumps({"status": result["status"], "jev_attempts": result.get("jev_attempts", 0)}))


if __name__ == "__main__":
    main()

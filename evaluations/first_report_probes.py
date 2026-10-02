"""Offline-preparable counterexample probes for the frozen first-report trial.

This module is intentionally separate from the original twelve-period trial.
It prepares two development probes, archives their public inputs and private
expected labels before any optional calls, and can later run at most one Jev
request plus one Luna episode per probe.  Probe results never replace the
frozen v2 denominator or primary scores.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.bootstrap_empirical_trial import TrialJev
from evaluations.codex_trial_transport import codex_episode
from evaluations.first_report_cases import _COMPANIES, _build_run, _public_company
from evaluations.first_report_trial import (
    PeriodAdapter,
    Session,
    dispatch,
    native_submission,
    operator_principal,
    score,
)
from evaluations.onboarding_acceptance_trial import source_freeze
from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.models import InsightCard, InsightCardStatus
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteDecisionReceiptStore, SQLiteInsightCardStore
from signalweave.typesafe_adapter import load_api_key

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APPROVED_RUN = ROOT / "docs" / "evidence" / "first-report-live-02"
FROZEN_V2_REVISION = "cee8d0df8f2398ec5ee7793a703edd8ac5f550e6"
JEV_REMAINING = 2
LUNA_REMAINING = 2
JEV_CEILING = 48
LUNA_CEILING = 16
PRIOR_JEV = 46
PRIOR_LUNA = 13
PROBE_COMPANIES = ("harbor-help", "northstar-cart")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _probe_periods() -> dict[str, dict[str, Any]]:
    """Return only new p04 rows; no original period is copied into a probe."""
    return {
        "harbor-help": {
            "id": "p04",
            "role": "probe",
            "coverage": "complete",
            "semantic_status": "aligned",
            # 26 / 200 = 13% in both periods. No between-period change.
            "primary": [("enterprise", 10, 80, 10, 80), ("self_serve", 16, 120, 16, 120)],
            "alternate": [("enterprise", 8, 80, 8, 80), ("self_serve", 18, 120, 18, 120)],
        },
        "northstar-cart": {
            "id": "p04",
            "role": "probe",
            "coverage": "complete",
            "semantic_status": "aligned",
            # A high stable total, but total and every channel change are zero.
            "primary": {"web": [600, 600], "marketplace": [250, 250], "store": [150, 150]},
            "alternate": {"web": [650, 650], "marketplace": [280, 280], "store": [170, 170]},
        },
    }


def build_probe_cases() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build public p04 company dictionaries and a parent-only expected map."""
    periods = _probe_periods()
    companies: list[dict[str, Any]] = []
    expected: dict[str, dict[str, Any]] = {}
    for company_id in PROBE_COMPANIES:
        spec = next(item for item in _COMPANIES if item["id"] == company_id)
        run = _build_run(spec, periods[company_id], 3)
        company = _public_company(spec, [run])
        company["periods"][0]["split"] = "probe"
        expected[company_id] = copy.deepcopy(company["periods"][0]["oracle"])
        expected[company_id]["period"] = "p04"
        expected[company_id]["oracle_version"] = "corrected-fixture-builder"
        companies.append(company)
    return companies, expected


def _public_inputs(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inputs = copy.deepcopy(companies)
    for company in inputs:
        for period in company["periods"]:
            period.pop("oracle", None)
    return inputs


def _load_approved_context(approved_run: Path) -> dict[str, Any]:
    manifest = json.loads((approved_run / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((approved_run / "report.json").read_text(encoding="utf-8"))
    if manifest.get("freeze", {}).get("git_revision") != FROZEN_V2_REVISION:
        raise ValueError("approved run is not the frozen v2 revision")
    if manifest.get("freeze", {}).get("git_status"):
        raise ValueError("approved run source freeze is dirty")
    if report.get("cumulative_jev_attempts") != PRIOR_JEV:
        raise ValueError("approved run does not have the expected Jev accounting")
    if report.get("cumulative_luna_episodes") != PRIOR_LUNA:
        raise ValueError("approved run does not have the expected Luna accounting")
    rows = {row["company"]: row for row in report["results"]}
    return {"manifest": manifest, "report": report, "rows": rows}


def _check_card_policy_clarification(company_id: str, row: dict[str, Any]) -> dict[str, Any]:
    card = row.get("card") or {}
    text = " ".join([
        str(card.get("decision_guidance", "")),
        " ".join(str(item) for item in card.get("watch_for", [])),
        str(row.get("notes", "")),
    ]).lower()
    if company_id == "harbor-help":
        present = "current" in text and "12%" in text and "change" in text and "4 percentage" in text
    else:
        present = "total change" in text and "previous period" in text
    return {
        "status": "present" if present else "surface_to_operator",
        "present": present,
        "checked_fields": ["decision_guidance", "watch_for", "notes"],
        "message": ("Approved card explicitly describes the between-period total change."
                    if present else
                    "Approved card does not explicitly clarify the between-period total change; surface this before calls."),
    }


def _backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def _approved_card_payload(row: dict[str, Any]) -> InsightCard:
    draft = InsightCard.model_validate(row["card"])
    approval_card = (row.get("approval") or {}).get("card") or {}
    approved_id = approval_card.get("id", draft.id)
    if approved_id != draft.id:
        raise ValueError("retained approval card id does not match the retained compiled card")
    if draft.compiled_plan is None:
        raise ValueError("retained card has no compiled plan")
    approved_at = approval_card.get("approved_at")
    if isinstance(approved_at, str):
        approved_at = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    return draft.model_copy(update={
        "status": InsightCardStatus.APPROVED,
        "approved_by": approval_card.get("approved_by", f"{row['company']}-owner"),
        "approved_at": approved_at,
        "principal_id": approval_card.get("principal_id", f"{row['company']}-owner"),
        "principal_tenant": approval_card.get("principal_tenant", "synthetic-first-report"),
    })


def _reconstruct_sqlite_card(destination: Path, row: dict[str, Any]) -> InsightCard:
    card = _approved_card_payload(row)
    store = SQLiteInsightCardStore(destination)
    store.save_card(card)
    return card


def prepare_probe_bundle(output: Path, approved_run: Path = DEFAULT_APPROVED_RUN) -> dict[str, Any]:
    """Archive all probe inputs, labels, DB backups and hashes before calls."""
    if output.exists():
        raise FileExistsError(output)
    context = _load_approved_context(approved_run)
    companies, expected = build_probe_cases()
    for company_id in PROBE_COMPANIES:
        if company_id not in context["rows"]:
            raise ValueError(f"approved run is missing {company_id}")
    card_clarifications = {
        company_id: _check_card_policy_clarification(company_id, context["rows"][company_id])
        for company_id in PROBE_COMPANIES
    }
    missing_clarification = [
        item["message"] for item in card_clarifications.values() if item["status"] != "present"
    ]
    if missing_clarification:
        raise ValueError(" ".join(missing_clarification))

    output.mkdir(parents=True)
    cards_dir = output / "approved_cards"
    cards_dir.mkdir()
    card_provenance = {}
    for company_id in PROBE_COMPANIES:
        source = approved_run / f"{company_id}.db"
        destination = cards_dir / source.name
        row = context["rows"][company_id]
        approved_card_id = ((row.get("approval") or {}).get("card") or row["card"])["id"]
        if source.exists():
            _backup_sqlite(source, destination)
            provenance_kind = "sqlite_backup"
            source_digest = _file_digest(source)
        else:
            _reconstruct_sqlite_card(destination, row)
            provenance_kind = "retained_report_reconstruction"
            source_digest = _file_digest(approved_run / "report.json")
        archived_card = SQLiteInsightCardStore(destination).get_card(approved_card_id)
        expected_card = _approved_card_payload(row)
        if (archived_card.status != InsightCardStatus.APPROVED
                or archived_card.execution_payload() != expected_card.execution_payload()):
            raise ValueError("Approved card execution contract differs from retained evidence")
        # Freeze a self-contained DB, not a base file whose committed pages still
        # live in a WAL that could be checkpointed after the manifest is hashed.
        with closing(sqlite3.connect(destination)) as connection:
            if connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                raise ValueError("Could not checkpoint the approved-card archive")
        card_provenance[company_id] = {
            "source": str(source),
            "source_sha256": source_digest,
            "provenance_kind": provenance_kind,
            "backup": str(destination),
            "backup_sha256": _file_digest(destination),
            "card_id": approved_card_id,
            "card_digest": _digest(archived_card.model_dump(mode="json")),
            "notes_digest": _digest(row.get("notes", "")),
        }

    inputs = {
        "scope": "development counterexample probes; not an enterprise holdout",
        "companies": _public_inputs(companies),
        "approved_card_refs": card_provenance,
        "same_card_and_notes": True,
        "no_approval_calls": True,
        "baseline_contract": "compact analysis_refs plus typed Outcome; no Jev result or expected labels",
    }
    labels = {
        "scope": "parent-only expected labels; excluded from agent inputs",
        "expected": expected,
        "policy_basis": {
            "harbor-help": "complete weighted current rate >= 12% OR between-period absolute delta >= 4pp; route support-operations",
            "northstar-cart": "complete total change versus the immediately previous period >= $100 OR channel contribution to that change >= $80; zero-change high levels ignore",
        },
    }
    manifest = {
        "protocol": "first-report-counterexample-probes-v1",
        "scope": "development counterexamples only; original scores and denominator unchanged",
        "frozen_v2_revision": FROZEN_V2_REVISION,
        "source_freeze": source_freeze(),
        "approved_run": str(approved_run),
        "approved_report_sha256": _file_digest(approved_run / "report.json"),
        "probe_ids": ["harbor-help:p04", "northstar-cart:p04"],
        "budget": {
            "jev_calls_max": JEV_REMAINING,
            "luna_episodes_max": LUNA_REMAINING,
            "prior_jev": PRIOR_JEV,
            "prior_luna": PRIOR_LUNA,
            "jev_ceiling": JEV_CEILING,
            "luna_ceiling": LUNA_CEILING,
            "retries": 0,
        },
        "card_policy_clarification": card_clarifications,
        "artifacts_written_before_calls": ["manifest.json", "inputs.json", "expected.json", "approved_cards/*.db"],
        "labels_exposed_to_agent": False,
    }
    _json_write(output / "inputs.json", inputs)
    _json_write(output / "expected.json", labels)
    _json_write(output / "manifest.json", manifest)
    return {"manifest": manifest, "inputs": inputs, "expected": labels, "card_provenance": card_provenance}


def _baseline_instructions() -> str:
    return (
        "Produce the report using only the provided MCP tools. Read catalog as needed and inspect the current p04 source. "
        "Use compact analysis_refs from inspect_source; code attaches exact calculations. Do not copy tables or invent causes. "
        "Apply the owner policy and exact approved recipient keys. Use typed Outcome values only: notify, ignore, investigate, "
        "or insufficient_data. Submit the compact report and stop. No external delivery."
    )


async def run_probes(
    output: Path,
    *,
    approved_run: Path = DEFAULT_APPROVED_RUN,
    live: bool = False,
    key_file: str | None = None,
) -> dict[str, Any]:
    """Prepare probes, or optionally execute exactly one paired call per probe."""
    bundle = prepare_probe_bundle(output, approved_run)
    if not live:
        return {"status": "ready_for_review", "paid_calls": 0, "manifest": bundle["manifest"]}

    key = load_api_key(key_file)
    audit = Audit(path=output / "events.jsonl", secrets=(key,))
    budget = RequestBudget(JEV_REMAINING)
    judger = TrialJev(key, budget, audit)
    results = []
    try:
        companies, _ = build_probe_cases()
        expected = bundle["expected"]["expected"]
        for company in companies:
            company_id = company["id"]
            adapter = PeriodAdapter(company["descriptors"], audit, company["sources"])
            period = company["periods"][0]
            adapter.set_period(period)
            database = output / f"{company_id}-runtime.db"
            _backup_sqlite(output / "approved_cards" / f"{company_id}.db", database)
            card_store = SQLiteInsightCardStore(database)
            card_id = bundle["card_provenance"][company_id]["card_id"]
            card = card_store.get_card(card_id)
            if card.status != InsightCardStatus.APPROVED:
                raise ValueError(f"{company_id} retained approved card is not approved")
            registry = SourceRegistry([adapter])
            runtime = Runtime(
                card_store=card_store,
                sources=registry,
                engine=InsightEngine(judger, registry, clock=lambda source=adapter: source.clock),
                decision_receipts=SQLiteDecisionReceiptStore(database),
                principal=operator_principal(company),
            )
            server = create_mcp(runtime)
            audit.episode = f"{company_id}:probe:jev"
            started = time.perf_counter()
            native = await dispatch(server, "evaluate_insight_card", {
                "card_id": card.id, "idempotency_key": f"probe:p04:{company_id}:native",
            })
            native_seconds = time.perf_counter() - started
            native_score = score(native_submission(native, company["destinations"]), expected[company_id])
            calls = budget.used
            replay = await dispatch(server, "evaluate_insight_card", {
                "card_id": card.id, "idempotency_key": f"probe:p04:{company_id}:native",
            })
            replay_exact = replay["report"] == native["report"] and budget.used == calls

            baseline = Session(company=company, adapter=adapter, server=server, phase="monitoring", audit=audit)
            audit.episode = f"{company_id}:probe:luna"
            baseline_started = time.perf_counter()
            baseline_episode = await codex_episode(
                baseline, key=None, effort="low", budget=RequestBudget(0), audit=audit,
                max_turns=10, max_tool_calls=8, max_output_tokens=2500, timeout_seconds=120,
                instructions_override=_baseline_instructions(),
                prompt_override={
                    "brief": company["brief"], "owner_policy": company["owner_policy"],
                    "saved_card": card.model_dump(mode="json"),
                    "saved_notes": context_notes(approved_run, company_id), "as_of": period["as_of"],
                },
            )
            baseline_seconds = time.perf_counter() - baseline_started
            baseline_score = score(baseline.submission, expected[company_id])
            results.append({
                "company": company_id, "period": "p04",
                "native": native, "native_score": native_score, "native_seconds": native_seconds,
                "replay_exact": replay_exact,
                "baseline_episode": baseline_episode, "baseline": baseline.submission,
                "baseline_score": baseline_score, "baseline_seconds": baseline_seconds,
            })
        usage = {}
        for event in audit.events:
            if event.get("kind") == "api.response" and isinstance(event.get("usage"), dict):
                provider = event.get("provider", "unknown")
                target = usage.setdefault(provider, {"input_tokens": 0, "output_tokens": 0})
                for field in target:
                    target[field] += event["usage"].get(field, 0) or 0
        report = {
            "kind": "first-report-counterexample-probe-report",
            "manifest_sha256": _file_digest(output / "manifest.json"),
            "results": results,
            "jev_calls": budget.used,
            "luna_episodes": sum(event.get("kind") == "api.request" and event.get("provider") == "openai" for event in audit.events),
            "usage": usage,
            "primary_scores_replaced": False,
        }
        _json_write(output / "report.json", report)
        return report
    except Exception as error:
        _json_write(output / "failure.json", audit.redact({
            "error": str(error), "completed_results": results, "jev_calls": budget.used,
            "primary_scores_replaced": False,
        }))
        raise


def context_notes(approved_run: Path, company_id: str) -> str:
    report = json.loads((approved_run / "report.json").read_text(encoding="utf-8"))
    row = next(item for item in report["results"] if item["company"] == company_id)
    return row.get("notes", "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approved-run", type=Path, default=DEFAULT_APPROVED_RUN)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--jev-key-file")
    args = parser.parse_args()
    result = asyncio.run(run_probes(args.output, approved_run=args.approved_run,
                                    live=args.live, key_file=args.jev_key_file))
    print(json.dumps({"status": result["status"] if "status" in result else "complete",
                      "paid_calls": result.get("paid_calls", result.get("jev_calls", 0))}))


if __name__ == "__main__":
    main()

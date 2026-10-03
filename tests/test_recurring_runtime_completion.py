"""Offline recovery tests; synthetic omissions are created only in temp fixtures."""
import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from evaluations import recurring_runtime_completion as completion
from evaluations import recurring_runtime_trial as trial
from tests.test_recurring_runtime_smoke import _AlwaysNotifyJev, _fake_episode


@pytest.fixture
async def parent_run(tmp_path, monkeypatch):
    async def episode(session, **kwargs):
        return await _fake_episode(session, receipt_ids=[], **kwargs)
    monkeypatch.setattr(trial, "TrialJev", _AlwaysNotifyJev)
    monkeypatch.setattr(trial, "codex_episode", episode)
    monkeypatch.setattr("signalweave.typesafe_adapter.load_api_key", lambda _: "offline-key")
    parent = tmp_path / "parent"
    report = await trial.run_trial(parent, live=True, case_set="transfer")
    for row in report["results"]:
        if row["arm"] != "signalweave" or row["company"] == "canyon-freight":
            continue
        removed = row["runs"][3:] if row["company"] == "helio-support" else row["runs"][:]
        row["runs"] = row["runs"][:3] if row["company"] == "helio-support" else []
        row["episode"]["status"] = "failed"
        with sqlite3.connect(parent / f"{row['company']}-signalweave.db") as db:
            for run in removed:
                key = f"business-outcomes:{run['period']}"
                payload = json.loads(db.execute("SELECT payload FROM decision_receipts WHERE idempotency_key=?", (key,)).fetchone()[0])
                payload.update(status="failed", outcome="insufficient_data", delivery_enabled=False, delivery_method_keys=[],
                               result={"error": "BudgetExceeded: global_api_request_budget_exhausted"})
                db.execute("UPDATE decision_receipts SET payload=? WHERE idempotency_key=?", (json.dumps(payload), key))
    trial._write_json(parent / "report.json", report)
    return parent


async def test_dry_completion_selects_only_missing_and_makes_no_calls(parent_run, tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Dry run invoked a model")
    monkeypatch.setattr(trial, "codex_episode", forbidden)
    result = await completion.run_completion(parent_run, tmp_path / "dry")
    assert result["pending"] == {"helio-support": ["p06"], "lattice-energy": ["p03", "p04", "p05", "p06"]}
    assert result["paid_calls"] == 0


async def test_completion_rejects_policy_plan_source_and_completed_receipt_drift(parent_run, monkeypatch):
    _, _, frozen, cards, _, _, freeze = completion.prepare(parent_run)
    card = cards["helio-support"]
    changed = card.model_copy(update={"decision_guidance": "ignore everything"})
    with pytest.raises(ValueError, match="payload"):
        completion.validate_card(changed, frozen["helio-support"]["card"])
    with pytest.raises(ValueError, match="plan"):
        completion.validate_card(card.model_copy(update={"compiled_plan": None}), frozen["helio-support"]["card"])
    drift = copy.deepcopy(freeze)
    drift["source_sha256"]["src/new.py"] = "changed"
    with monkeypatch.context() as patch:
        patch.setattr(trial, "source_freeze", lambda: drift)
        with pytest.raises(ValueError, match="source changed"):
            completion.prepare(parent_run)
    with sqlite3.connect(parent_run / "helio-support-signalweave.db") as db:
        payload = json.loads(db.execute("SELECT payload FROM decision_receipts WHERE idempotency_key='business-outcomes:p06'").fetchone()[0])
        payload["status"] = "delivery_disabled"
        db.execute("UPDATE decision_receipts SET payload=? WHERE idempotency_key='business-outcomes:p06'", (json.dumps(payload),))
    with pytest.raises(ValueError, match="ambiguous durable receipt"):
        completion.prepare(parent_run)


async def test_runtime_guard_rechecks_actual_stored_plan_before_each_call(parent_run):
    companies, _, frozen, cards, _, _, _ = completion.prepare(parent_run)
    company = companies[0]
    card = cards[company["id"]]
    changed = card.model_copy(update={"compiled_plan": card.compiled_plan.model_copy(update={"card_scope": "tampered"})})
    public = trial._public_company(company, recurring_only=True)
    audit = trial.Audit()
    adapter = trial.CachedPeriodAdapter(public["descriptors"], audit, public["sources"])
    adapter.set_period(public["periods"][0])
    session = completion.GuardedSession(
        company=public, adapter=adapter, server=None, audit=audit, treatment=True,
        card_id=card.id, card=card, frozen_public_card=frozen[company["id"]]["card"],
        card_store=SimpleNamespace(get_card=lambda _: changed),
    )
    with pytest.raises(ValueError, match="plan changed"):
        await session.call("evaluate_workflow", {})


async def test_partial_completion_cannot_claim_complete(parent_run, tmp_path, monkeypatch):
    async def fails(*args, **kwargs):
        raise RuntimeError("offline failure")
    monkeypatch.setattr(trial, "codex_episode", fails)
    result = await completion.run_completion(parent_run, tmp_path / "partial", live=True)
    assert result["completion_complete"] is False
    assert result["completion_correct"] is False
    assert result["coverage_origin"]["post_hoc_reports"] == 0
    assert result["combined_coverage"]["signalweave"]["submitted"] == 7


async def test_real_completion_runtime_retains_original_reports_and_gates(parent_run, tmp_path, monkeypatch):
    calls = []
    async def episode(session, **kwargs):
        calls.append(session.company["id"])
        for period in session.company["periods"]:
            response = await session.call("evaluate_workflow", {})
            writer = response["writer_input"]
            await session.call("submit_report", {
                "period_id": period["id"], "status": writer["report"]["status"],
                "outcome": writer["report"]["outcome"], "recipients": writer["configured_recipient_keys"],
                "analysis_refs": writer["known_analysis_refs"], "narrative": "Offline continuation, not semantic proof.",
            })
        return {"status": "complete", "error": None, "tool_calls": 8, "seconds": 1, "foreign_tools": []}
    monkeypatch.setattr(trial, "codex_episode", episode)
    original = (parent_run / "report.json").read_bytes()
    output = tmp_path / "completion"
    result = await completion.run_completion(parent_run, output, live=True)
    assert calls == ["helio-support", "lattice-energy"]
    assert result["jev_attempts"] == 5 and result["luna_episodes"] == 2
    assert result["prospective_pass"] is result["latency_comparable"] is False
    assert result["original_failed_gate_preserved"]
    assert result["combined_coverage"]["signalweave"]["submitted"] == 12
    assert result["combined_coverage"]["signalweave"]["failed_episodes"] == 2
    assert (parent_run / "report.json").read_bytes() == original
    assert all(run["replay_exact_no_calls"] for row in result["completion"] for run in row["runs"])
    packet = json.loads((output / "review-input.json").read_text())
    assert len(packet["cases"]) == 12 and '"oracle"' not in json.dumps(packet)

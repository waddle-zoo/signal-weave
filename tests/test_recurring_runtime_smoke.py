"""Full offline smoke for the recurring runtime trial.

This deliberately drives the real Runtime/MCP setup, review, approval,
evaluation, and receipt paths.  Only the provider boundary (TrialJev), the
Codex episode transport, and API-key loading are replaced.  The semantic
double always chooses ``notify``; this test is protocol/artifact coverage, not
an oracle-perfect scoring proof.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from evaluations import recurring_runtime_trial as trial
from evaluations.first_report_trial import dispatch
from signalweave.models import InsightResult, Outcome, WatchResult, WatchStatus


def _author_intent(company: dict, catalog: dict) -> dict:
    """Build a deterministic valid draft request without entering the agent view."""

    from evaluations.recurring_runtime_cases import cases
    from evaluations.recurring_runtime_transfer_cases import cases as transfer_cases

    private_company = next(item for item in [*cases(), *transfer_cases()] if item["id"] == company["id"])
    conditions = [
        {**condition, "text": "Owner numeric policy"}
        for condition in private_company["periods"][0]["oracle"]["numeric_policy"]
    ]
    destinations = catalog["destinations"]
    return {
        "title": f"{company['id']} recurring policy",
        "what_to_watch": company["brief"],
        "why_watch": company["owner_policy"],
        "decision_guidance": company["owner_policy"],
        "source_keys": [source["key"] for source in catalog["sources"]],
        "routes": [
            {"destination_key": destination["key"], "outcome": "notify"}
            for destination in destinations
        ],
        "numeric_conditions": conditions,
        "watch_for": ["The configured owner policy trigger is present or absent."],
        "questions": [],
        "evidence_requirements": {},
        "follow_up_guidance": "State uncertainty and do not infer causation.",
    }


class _AlwaysNotifyJev:
    name = "offline-always-notify-jev"

    def __init__(self, key, budget, audit):
        self.key = key
        self.budget = budget
        self.audit = audit

    async def compile_plan(self, state, card):
        del state
        return {
            "capabilities": ["percent_change", "baseline_comparison", "freshness_check"],
            "baseline": card.comparison_windows[0],
            "source_keys": [source.key for source in card.sources],
        }

    async def rank_resources(self, goal, candidates):
        del goal
        return {f"{candidate.adapter}|{candidate.resource}": 1.0 for candidate in candidates}

    async def classify_resource_roles(self, goal, candidates):
        del goal
        return {
            f"{candidate.adapter}|{candidate.resource}": {
                "role": "primary",
                "probability": 0.99,
            }
            for candidate in candidates
        }

    async def judge(self, state, card, plan, observations):
        del plan
        request_id = self.budget.used + 1
        self.budget.claim()
        self.audit.emit(
            "api.request",
            provider="jev",
            request_id=request_id,
            model=self.name,
            stage="offline-smoke",
        )
        result = InsightResult(
            card_id=card.id,
            outcome=Outcome.NOTIFY,
            delivery_methods=list(card.delivery_methods),
            summary="Offline smoke semantic double always selects notify.",
            rationale="This is intentionally not an oracle-perfect semantic result.",
            confidence=0.99,
            probabilities={Outcome.NOTIFY.value: 0.99},
            watch_results=[WatchResult(
                key="watch_0",
                watch_for="The configured owner policy trigger is present or absent.",
                status=WatchStatus.PRESENT,
                probability=0.99,
            )],
            evidence=state["evidence"],
            observations=observations,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )
        self.audit.emit(
            "api.response",
            provider="jev",
            request_id=request_id,
            response={"choice": Outcome.NOTIFY.value},
            usage={"input_tokens": 1, "output_tokens": 1},
        )
        return result


async def _fake_episode(session, *, receipt_ids: list[str], **kwargs):
    """Exercise the real session/MCP boundary while replacing only Codex."""

    del kwargs
    calls = 0

    async def call(name, arguments):
        nonlocal calls
        calls += 1
        return await session.call(name, arguments)

    if isinstance(session, trial.SetupSession):
        catalog = await call("catalog", {})
        await call("current_setup_period", {})
        intent = _author_intent(session.company, catalog)
        draft = await call("draft_from_intent", intent)
        card_id = draft["card"]["id"]

        for index in range(trial.SETUP_PERIODS):
            await call("current_setup_period", {})
            for source in catalog["sources"]:
                await call("inspect_source", {"source_key": source["key"]})
            await call("preview_investigation_report", {"card_id": card_id})
            if index == 0:
                await call("advance_setup", {"period_id": session.setup_periods[0]["id"]})
        await call("finish_setup", {
            "card_id": card_id,
            "notes": "Offline smoke setup completed; synthetic owner review follows.",
        })
    else:
        catalog = await call("catalog", {})
        source_keys = [source["key"] for source in catalog["sources"]]
        destination_keys = [destination["key"] for destination in catalog["destinations"]]

        for _ in range(trial.HOLDOUT_PERIODS):
            period = await call("current_period", {})
            for source_key in source_keys:
                await call("inspect_source", {"source_key": source_key})

            if session.treatment:
                workflow = await call("evaluate_workflow", {})
                writer_input = workflow["writer_input"]
                receipt = await dispatch(
                    session.server,
                    "get_decision_receipt",
                    {"idempotency_key": f"business-outcomes:{period['period_id']}"},
                )
                assert receipt["status"] == "found"
                receipt_ids.append(receipt["receipt"]["receipt_id"])
                report = writer_input["report"]
                status = report["status"]
                outcome = report["outcome"]
                recipients = writer_input["configured_recipient_keys"]
                analysis_refs = writer_input["known_analysis_refs"]
            else:
                status = "complete"
                outcome = Outcome.NOTIFY.value
                recipients = destination_keys
                analysis_refs = [
                    {"source_key": source_key, "comparison_key": comparison_key}
                    for source_key, comparison_key in session.inspected_analyses
                ]

            await call("submit_report", {
                "period_id": period["period_id"],
                "status": status,
                "outcome": outcome,
                "recipients": recipients,
                "analysis_refs": analysis_refs,
                "narrative": "Offline smoke report: always-notify semantic double; no external delivery.",
            })

    return {
        "status": "complete",
        "error": None,
        "exit_code": 0,
        "seconds": 0.001,
        "foreign_tools": [],
        "tool_calls": calls,
        "offline_semantic_double": "always_notify",
    }


@pytest.mark.parametrize("case_set", ["initial", "transfer"])
def test_full_offline_run_trial_smoke_exercises_real_runtime_artifacts(tmp_path, monkeypatch, case_set):
    receipt_ids: list[str] = []

    async def fake_episode(session, **kwargs):
        return await _fake_episode(session, receipt_ids=receipt_ids, **kwargs)

    monkeypatch.setattr(trial, "TrialJev", _AlwaysNotifyJev)
    monkeypatch.setattr(trial, "codex_episode", fake_episode)
    monkeypatch.setattr("signalweave.typesafe_adapter.load_api_key", lambda _: "offline-smoke-key")

    output = tmp_path / "recurring-runtime-full-offline-smoke"
    report = asyncio.run(trial.run_trial(output, live=True, case_set=case_set))

    expected_artifacts = {
        "manifest.json",
        "progress.json",
        "frozen-cards.json",
        "events.jsonl",
        "report.json",
        "review-input.json",
        "review-key.json",
        "scoring-labels.json",
    }
    assert expected_artifacts <= {path.name for path in output.iterdir()}
    assert report["overall_status"] == "failed_structured_gate"
    assert report["structured_gate_passed"] is False
    assert report["all_attempts_retained"] is True
    assert report["luna_episodes"] == trial.MAX_LUNA_EPISODES == 9
    assert report["jev_attempts"] <= trial.MAX_JEV_ATTEMPTS == 36
    assert len(receipt_ids) == 12
    assert len(set(receipt_ids)) == 12

    assert len(report["setup"]) == 3
    assert all(item["setup_complete"] for item in report["setup"])
    assert all(item["approval"]["status"] in {"approved", "replayed"} for item in report["setup"])
    assert all(item["card"]["status"] == "approved" for item in report["setup"])
    assert all(len(item["previewed_periods"]) == trial.SETUP_PERIODS for item in report["setup"])

    assert len(report["results"]) == 6
    progress = json.loads((output / "progress.json").read_text(encoding="utf-8"))
    assert len(progress["setup"]) == 3
    assert len(progress["results"]) == 6
    assert all(item["episode"]["status"] == "complete" for item in progress["setup"])
    assert all(item["episode"]["status"] == "complete" for item in progress["results"])
    assert all(len(row["runs"]) == trial.HOLDOUT_PERIODS for row in report["results"])
    assert report["summary"]["baseline"]["submitted"] == 12
    assert report["summary"]["signalweave"]["submitted"] == 12
    assert len(report["paired_outcomes"]) == 12
    assert all(item["same_catalog"] for item in report["paired_outcomes"])
    assert all(item["same_analysis"] for item in report["paired_outcomes"])
    assert all(
        run["replay_exact_no_calls"]
        for row in report["results"]
        if row["arm"] == "signalweave"
        for run in row["runs"]
    )

    checks = report["protocol_checks"]
    assert checks["all_three_cards_approved"]
    assert checks["no_foreign_tools"]
    assert checks["exact_replay_all_treatment_periods"]
    assert checks["paired_catalog_and_analysis"]
    assert checks["usage_complete"]
    assert not checks["all_intended_holdout_scores"]

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    review_input = json.loads((output / "review-input.json").read_text(encoding="utf-8"))
    assert all("oracle" not in json.dumps(company) for company in manifest["companies"])
    assert all("oracle" not in json.dumps(case) for case in review_input["cases"])
    assert all(
        run["native"]["receipt"]["status"] == "delivery_disabled"
        for row in report["results"]
        if row["arm"] == "signalweave"
        for run in row["runs"]
    )

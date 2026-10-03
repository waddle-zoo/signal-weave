"""Offline contract tests for the prospective recurring runtime harness."""

import asyncio
import copy
import json
import sys
import types

import pytest

from evaluations.bootstrap_agent_trial import Audit
from evaluations.first_report_cases import cases as first_cases
from evaluations.recurring_runtime_trial import (
    CachedPeriodAdapter,
    RecurringSession,
    SetupSession,
    _brief_metadata_card,
    _independent_numeric_score,
    _paired,
    _paired_context_matches,
    _period_groups,
    _public_company,
    _select_arm_card,
    audit_numeric_policy,
    run_trial,
    score,
    summarize,
)
from signalweave.diagnostics import analyze_comparison
from signalweave.models import InsightCard, ResourceSnapshot
from signalweave.numeric_conditions import evaluate_numeric_conditions


def policy_card(company):
    conditions = [{**item, "text": "Owner numeric policy"}
                  for item in company["periods"][0]["oracle"]["numeric_policy"]]
    sources = copy.deepcopy(company["sources"])
    for source in sources:
        source["required_comparison_keys"] = sorted({item["comparison_key"] for item in conditions
                                                    if item["source_key"] == source["key"]})
    return InsightCard(id="policy-audit", title="Policy audit", what_to_watch="Owner policy",
                       why_watch="Owner review", sources=sources, numeric_conditions=conditions)


def test_policy_audit_preserves_exact_segments_and_never_uses_holdouts():
    from evaluations.recurring_runtime_cases import cases

    company = cases()[2]
    card = policy_card(company)
    for period in company["periods"][2:]:
        period["oracle"] = {}
    assert audit_numeric_policy(card, company)["passed"]
    condition = next(item for item in card.numeric_conditions if item.segment == "churn")
    condition.segment = None
    assert not audit_numeric_policy(card, company)["passed"]


@pytest.mark.parametrize("company_index", range(3))
@pytest.mark.parametrize("case_set", ["initial", "transfer"])
def test_independent_numeric_labels_cover_all_periods(company_index, case_set):
    from evaluations.recurring_runtime_cases import cases as initial
    from evaluations.recurring_runtime_transfer_cases import cases as transfer

    company = (initial if case_set == "initial" else transfer)()[company_index]
    card = policy_card(company)
    assert audit_numeric_policy(card, company)["passed"]
    for period in company["periods"]:
        analyses = [analyze_comparison(snapshot.source_key, comparison)
                    for value in period["resources"]
                    for snapshot in [ResourceSnapshot.model_validate(value)]
                    for comparison in snapshot.analytical_comparisons]
        checks = [item.model_dump(mode="json") for item in evaluate_numeric_conditions(card, analyses)]
        assert _independent_numeric_score(checks, period["oracle"])["passed"], period["id"]
        changed = copy.deepcopy(checks)
        changed[0]["value"] = 99999
        assert not _independent_numeric_score(changed, period["oracle"])["passed"]
        assert not _independent_numeric_score(checks[:-1], period["oracle"])["passed"]


def test_period_local_cache_tracks_physical_reads_and_resets():
    company = first_cases()[0]
    audit = Audit()
    adapter = CachedPeriodAdapter(company["descriptors"], audit, company["sources"])
    adapter.set_period(company["periods"][0])
    source = company["sources"][0]

    async def exercise():
        first = await adapter.inspect(__import__("signalweave.models", fromlist=["SourceRef"]).SourceRef.model_validate(source))
        second = await adapter.inspect(__import__("signalweave.models", fromlist=["SourceRef"]).SourceRef.model_validate(source))
        return first, second

    first, second = asyncio.run(exercise())
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert adapter.physical_reads == adapter.inspections == 1
    assert adapter.cache_hits == 1
    assert sum(event["kind"] == "source.read" for event in audit.events) == 1
    assert sum(event["kind"] == "source.cache_hit" for event in audit.events) == 1

    adapter.set_period(company["periods"][1])
    assert adapter.physical_reads == adapter.cache_hits == 0


def test_setup_session_exposes_only_explicit_setup_advance():
    company = first_cases()[0]
    setup = copy.deepcopy(company["periods"][:2])
    for period in setup:
        period["split"] = "setup"
        period.pop("oracle", None)
    public = copy.deepcopy(company)
    public["periods"] = setup
    audit = Audit()
    adapter = CachedPeriodAdapter(public["descriptors"], audit, public["sources"])
    adapter.set_period(setup[0])
    session = SetupSession(company=public, setup_periods=setup, adapter=adapter, server=None, audit=audit)
    names = {spec["name"] for spec in asyncio.run(session.specs())}
    assert {"current_setup_period", "advance_setup", "draft_from_intent", "preview_investigation_report", "finish_setup"} <= names
    assert "submit_report" not in names
    assert asyncio.run(session.call("current_setup_period", {}))["period_id"] == setup[0]["id"]
    assert "oracle" not in json.dumps(awaitable_catalog(session))


def awaitable_catalog(session):
    return asyncio.run(session.call("catalog", {}))


def test_public_projection_removes_labels_but_keeps_all_holdout_ids():
    company = next(item for item in __import__("evaluations.recurring_runtime_cases", fromlist=["cases"]).cases() if item["id"] == "juniper-bookings")
    setup, holdout = _period_groups(company)
    public = _public_company(company, recurring_only=True)
    assert [item["id"] for item in public["periods"]] == [item["id"] for item in holdout]
    assert "oracle" not in json.dumps(public)
    assert all(item["id"] not in json.dumps(public) for item in setup)


def test_numeric_score_never_calls_unlabeled_fixture_path_a_pass():
    company = __import__("evaluations.recurring_runtime_cases", fromlist=["cases"]).cases()[0]
    oracle = company["periods"][2]["oracle"]
    submission = {"status": "complete", "outcome": oracle["outcome"],
                  "recipients": oracle["recipients"], "analyses": [], "narrative": "Observed."}
    result = score(submission, oracle, [])
    assert result["numeric_passed"] is False
    assert "numeric_condition_missing" in result["errors"]


@pytest.mark.parametrize("segment", [None, "down"])
def test_absolute_contribution_scores_normalized_value(segment):
    oracle = {
        "status": "complete",
        "numeric_policy": [{
            "source_key": "source",
            "comparison_key": "movement",
            "unit": "units",
            "measurement": "contribution",
            "segment": segment,
            "absolute": True,
            "comparator": ">=",
            "threshold": 5,
        }],
        "measurements": {"contributions": [{"segment": "down", "contribution": -7}]},
    }
    results = [{
        "condition_text": "Magnitude is at least five units",
        "source_key": "source",
        "comparison_key": "movement",
        "unit": "units",
        "expected_unit": "units",
        "measurement": "contribution",
        "segment": segment,
        "matched_segment": "down",
        "absolute": True,
        "comparator": ">=",
        "threshold": 5,
        "status": "true",
        "value": 7,
    }]
    assert _independent_numeric_score(results, oracle)["passed"]


def test_paired_context_requires_same_card_digest():
    from evaluations.recurring_runtime_transfer_cases import cases

    company = cases()[0]
    _, holdout = _period_groups(company)

    def row(arm, card_digest, catalog_digest="catalog", analysis_digest="analysis"):
        return {
            "company": company["id"],
            "arm": arm,
            "runs": [{
                "period": period["id"],
                "card_digest": card_digest,
                "catalog_digest": catalog_digest,
                "analysis_input_digest": analysis_digest,
            } for period in holdout],
        }

    paired = _paired([row("baseline", "same"), row("signalweave", "same")], [company])
    assert all(item["same_card"] for item in paired)
    assert _paired_context_matches(paired)

    mismatched = _paired([row("baseline", "baseline-card"), row("signalweave", "treatment-card")], [company])
    assert not any(item["same_card"] for item in mismatched)
    assert not _paired_context_matches(mismatched)

    for field, paired_field in (
        ("card_digest", "same_card"),
        ("catalog_digest", "same_catalog"),
        ("analysis_digest", "same_analysis"),
    ):
        for missing in (None, "", "   "):
            values = {"card_digest": "same", "catalog_digest": "catalog", "analysis_digest": "analysis"}
            values[field] = missing
            incomplete = _paired(
                [row("baseline", **values), row("signalweave", **values)],
                [company],
            )
            assert not any(item[paired_field] for item in incomplete)
            assert not _paired_context_matches(incomplete)

    assert not _paired_context_matches([])


def test_summary_cannot_drop_numeric_failure_from_strict_gate():
    company = {"id": "c", "periods": [{"id": "p", "oracle": {
        "status": "complete", "outcome": "ignore", "recipients": [], "analyses": [],
    }}]}
    submission = {"status": "complete", "outcome": "ignore", "recipients": [], "analyses": []}
    rows = [{"company": "c", "arm": arm,
             "episode": {"status": "complete", "seconds": 1, "tool_calls": 1},
             "runs": [{"period": "p", "submission": submission, "source_reads": 1,
                       "score": {"passed": arm == "baseline", "numeric_passed": arm == "baseline"}}]}
            for arm in ("baseline", "signalweave")]
    result = summarize(rows, [company])
    assert result["baseline"]["strict_passed"] == 1
    assert result["signalweave"]["strict_passed"] == 0
    assert result["signalweave"]["review_required_proxy"] == 1


def test_numeric_policy_audit_requires_authored_checks_and_baseline_fallback_is_unapproved():
    company = __import__("evaluations.recurring_runtime_cases", fromlist=["cases"]).cases()[0]
    fallback = _brief_metadata_card(company)
    assert fallback.numeric_conditions == []
    assert fallback.delivery_methods == []
    assert audit_numeric_policy(fallback, company)["passed"] is False


def test_missing_author_card_keeps_baseline_context_and_fails_treatment_gate():
    company = __import__("evaluations.recurring_runtime_cases", fromlist=["cases"]).cases()[0]
    setup_result = {"card": None, "draft_card": None}
    baseline, baseline_source = _select_arm_card(setup_result, company, treatment=False)
    treatment, treatment_source = _select_arm_card(setup_result, company, treatment=True)
    assert baseline_source == "brief_metadata_only"
    assert baseline is not None
    assert [item.key for item in baseline.sources] == [item["key"] for item in company["sources"]]
    assert not baseline.numeric_conditions and not baseline.delivery_methods
    assert treatment is None and treatment_source == "unauthored"


def test_dry_run_freezes_protocol_without_live_calls_or_private_labels(tmp_path, monkeypatch):
    source = first_cases()[0]
    company = copy.deepcopy(source)
    company["id"] = "dry-company"
    periods = []
    for index in range(6):
        period = copy.deepcopy(source["periods"][index % 3])
        period["id"] = f"p{index + 1:02d}"
        period["split"] = "setup" if index < 2 else "holdout"
        periods.append(period)
    company["periods"] = periods
    companies = [copy.deepcopy(company) for _ in range(3)]
    for index, item in enumerate(companies):
        item["id"] = f"dry-company-{index}"
    module = types.ModuleType("evaluations.recurring_runtime_cases")
    module.cases = lambda: copy.deepcopy(companies)
    monkeypatch.setitem(sys.modules, "evaluations.recurring_runtime_cases", module)

    result = asyncio.run(run_trial(tmp_path / "dry", live=False))
    manifest = json.loads((tmp_path / "dry" / "manifest.json").read_text())
    assert result["status"] == "dry_run"
    assert result["paid_calls"] == 0
    assert manifest["budgets"]["jev_attempts"] == 36
    assert manifest["budgets"]["luna_total_episodes"] == 9
    assert "oracle" not in json.dumps(manifest["companies"])
    assert not (tmp_path / "dry" / "events.jsonl").exists()


def test_recurring_specs_include_numeric_helper_in_both_arms():
    # The public contract is checked without opening a runtime or making a Jev call.
    company = copy.deepcopy(first_cases()[0])
    company["periods"] = []
    for index in range(6):
        period = copy.deepcopy(first_cases()[0]["periods"][index % 3])
        period["id"] = f"p{index + 1:02d}"
        period["split"] = "setup" if index < 2 else "holdout"
        company["periods"].append(period)
    public = _public_company(company, recurring_only=True)
    audit = Audit()
    adapter = CachedPeriodAdapter(public["descriptors"], audit, public["sources"])
    adapter.set_period(public["periods"][0])
    card = InsightCard.model_validate({
        "id": "test-card", "title": "Test", "what_to_watch": "Test", "why_watch": "Test",
        "sources": public["sources"], "delivery_methods": [],
    })
    names = asyncio.run(RecurringSession(company=public, adapter=adapter, server=None, audit=audit,
                                         treatment=False, card_id=card.id, card=card).specs())
    treatment_names = asyncio.run(RecurringSession(company=public, adapter=adapter, server=None, audit=audit,
                                                    treatment=True, card_id=card.id, card=card).specs())
    assert "evaluate_numeric_conditions" in {item["name"] for item in names}
    assert "evaluate_numeric_conditions" in {item["name"] for item in treatment_names}
    assert "evaluate_workflow" not in {item["name"] for item in names}
    assert "evaluate_workflow" in {item["name"] for item in treatment_names}


def test_treatment_replay_uses_full_native_analyses_without_prefetch(monkeypatch):
    from evaluations.recurring_runtime_cases import cases

    source_company = cases()[0]
    public = _public_company(source_company, recurring_only=True)
    period = public["periods"][0]
    source = public["sources"][0]
    snapshot = ResourceSnapshot.model_validate(
        next(item for item in period["resources"] if item["source_key"] == source["key"])
    )
    analysis = analyze_comparison(source["key"], snapshot.analytical_comparisons[0]).model_dump(mode="json")
    card = InsightCard.model_validate({
        "id": "runtime-replay-card", "title": "Runtime replay", "what_to_watch": "The approved metric",
        "why_watch": "Keep the owner informed", "sources": [source], "delivery_methods": [],
    })
    audit = Audit()
    adapter = CachedPeriodAdapter(public["descriptors"], audit, public["sources"])
    adapter.set_period(period)
    session = RecurringSession(company=public, adapter=adapter, server=None, audit=audit,
                               treatment=True, card_id=card.id, card=card)
    native = {
        "report": {"status": "complete", "numeric_claims": [], "provenance": []},
        "report_markdown": "No action is required.",
        "result": {"outcome": "ignore", "delivery_methods": [], "analyses": [analysis]},
    }
    calls = []

    async def dispatch(*args):
        calls.append(args)
        return copy.deepcopy(native)

    async def briefing(*args, **kwargs):
        return {"writer_status": "accepted"}

    monkeypatch.setattr("evaluations.business_outcome_trial.dispatch", dispatch)
    monkeypatch.setattr("evaluations.business_outcome_trial.build_briefing_writer_input", lambda *args: {})
    monkeypatch.setattr("evaluations.business_outcome_trial.create_briefing", briefing)

    async def exercise():
        result = await session.call("evaluate_workflow", {})
        await session.call("submit_report", {
            "period_id": period["id"], "status": "complete", "outcome": "ignore",
            "recipients": [], "analysis_refs": [], "narrative": "No action is required.",
        })
        return result

    response = asyncio.run(exercise())
    assert len(calls) == 2  # evaluation plus exact idempotent replay
    assert adapter.physical_reads == adapter.cache_hits == 0
    assert session.runs[0]["replay_exact_no_calls"] is True
    assert session.runs[0]["numeric_conditions"] == []
    assert session.runs[0]["analysis_input_digest"]
    assert response["numeric_conditions"] == []

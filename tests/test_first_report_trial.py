"""Grader and public tool-boundary checks run offline, before spending credits."""

import copy

import pytest

from evaluations.first_report_trial import score


def pair():
    expected = {"source_key": "s", "comparison_key": "c", "metric": "units",
                "unit": "count", "dimension": "group", "definition": "closed units",
                "population": "eligible units", "baseline_start": "2026-09-01T00:00:00+00:00",
                "baseline_end": "2026-09-02T00:00:00+00:00",
                "current_start": "2026-09-02T00:00:00+00:00",
                "current_end": "2026-09-03T00:00:00+00:00", "baseline": 100,
                "current": 80, "delta": -20, "within_effect": None, "mix_effect": None,
                "contributions": {"one": -20}, "query_refs": ["q"]}
    actual = {**expected, "status": "complete", "comparison": copy.deepcopy(expected),
              "contributions": [{"segment": "one", "contribution": -20}]}
    return ({"status": "complete", "outcome": "notify", "recipients": ["owner"],
             "analyses": [actual], "narrative": "An accounting change, not a causal claim."},
            {"status": "complete", "outcome": "notify", "recipients": ["owner"],
             "analyses": [expected]})


def test_good_quantitative_report_passes_but_narrative_still_needs_review():
    report, oracle = pair()
    report["analyses"][0]["comparison"]["baseline_start"] = "2026-09-01T00:00:00Z"
    assert score(report, oracle) == {"passed": True, "errors": [],
                                     "narrative_review": "requires_independent_review"}


@pytest.mark.parametrize("field,value", [("delta", -200), ("current", True),
                                         ("metric", "different"), ("source_key", "wrong")])
def test_numeric_and_source_corruption_fails(field, value):
    report, oracle = pair()
    report["analyses"][0][field] = value
    assert not score(report, oracle)["passed"]


def test_missing_extra_duplicate_and_wrong_population_fail():
    for mutation in ("missing", "extra", "duplicate", "population", "provenance"):
        report, oracle = pair()
        if mutation == "missing":
            report["analyses"] = []
        elif mutation in {"extra", "duplicate"}:
            report["analyses"] += copy.deepcopy(report["analyses"])
        elif mutation == "population":
            report["analyses"][0]["comparison"]["population"] = "wrong"
        else:
            report["analyses"][0]["query_refs"] = ["old-period"]
        assert not score(report, oracle)["passed"]


def test_abstaining_everything_is_not_success():
    report, oracle = pair()
    report.update(status="blocked", outcome="insufficient_data", recipients=[], analyses=[])
    assert not score(report, oracle)["passed"]


async def test_agent_tool_projections_never_include_oracle_or_future_periods():
    import json

    from evaluations.bootstrap_agent_trial import Audit
    from evaluations.first_report_cases import cases
    from evaluations.first_report_trial import PeriodAdapter, Session

    company = cases()[0]
    audit = Audit()
    adapter = PeriodAdapter(company["descriptors"], audit, company["sources"])
    adapter.set_period(company["periods"][0])
    session = Session(company=company, adapter=adapter, server=None, phase="monitoring", audit=audit)
    catalog = await session.call("catalog", {})
    serialized = json.dumps(catalog)
    assert "oracle" not in serialized and "expected_outcome" not in serialized
    for source in company["sources"]:
        inspected = await session.call("inspect_source", {"source_key": source["key"]})
        text = json.dumps(inspected)
        assert "oracle" not in text and "expected_outcome" not in text
        assert "p02" not in text and "p03" not in text
        assert "distractor" not in text
    assert session.submission is None


async def test_fixture_adapter_rejects_unapproved_parameter_changes():
    from evaluations.bootstrap_agent_trial import Audit
    from evaluations.first_report_cases import cases
    from evaluations.first_report_trial import PeriodAdapter
    from signalweave.models import SourceRef

    company = cases()[0]
    adapter = PeriodAdapter(company["descriptors"], Audit(), company["sources"])
    adapter.set_period(company["periods"][0])
    source = SourceRef.model_validate(company["sources"][0])
    source.parameters["unreviewed"] = "anything"
    with pytest.raises(ValueError, match="not available"):
        await adapter.inspect(source)


async def test_configured_principal_completes_real_mcp_approval_offline(tmp_path):
    from evaluations.bootstrap_agent_trial import Audit
    from evaluations.first_report_cases import cases
    from evaluations.first_report_trial import PeriodAdapter, dispatch, operator_principal
    from signalweave.engine import InsightEngine
    from signalweave.mcp_server import create_mcp
    from signalweave.runtime import Runtime
    from signalweave.sources import SourceRegistry
    from signalweave.store import SQLiteInsightCardStore
    from tests.test_local_investigation import InspectingJudger

    class ApprovalDouble(InspectingJudger):
        async def rank_resources(self, goal, resources):
            return {f"{r.adapter}|{r.resource}": .2 for r in resources}

        async def judge(self, *args):
            from signalweave.models import WatchResult, WatchStatus

            result = await super().judge(*args)
            result.watch_results = [WatchResult(key="watch_0", watch_for="Material change",
                                                status=WatchStatus.PRESENT, probability=.99)]
            return result

    company = cases()[0]
    adapter = PeriodAdapter(company["descriptors"], Audit(), company["sources"])
    adapter.set_period(company["periods"][0])
    registry = SourceRegistry([adapter])
    runtime = Runtime(card_store=SQLiteInsightCardStore(tmp_path / "cards.db"), sources=registry,
                      engine=InsightEngine(ApprovalDouble(), registry, clock=lambda: adapter.clock),
                      principal=operator_principal(company))
    server = create_mcp(runtime)
    draft = await dispatch(server, "draft_insight_card", {
        "title": "Identity regression", "what_to_watch": company["brief"],
        "why_watch": "Daily review", "decision_guidance": company["owner_policy"],
        "watch_for": ["Material change"],
        "sources": [company["sources"][0]],
        "delivery_methods": [{"key": "owner", "outcome": "notify", "label": "Owner",
                              "destination": company["destinations"][0]["destination"]}],
    })
    card_id = draft["card"]["id"]
    assert draft["card"]["principal_tenant"] == runtime.principal.tenant_id
    preview = await dispatch(server, "preview_investigation_report", {"card_id": card_id})
    assert preview["report"]["status"] == "complete"
    approved = await dispatch(server, "approve_insight_card", {"card_id": card_id})
    assert approved["status"] == "approved"
    assert approved["card"]["approved_by"] == runtime.principal.principal_id


def test_operator_principal_rejects_mixed_tenants():
    from evaluations.first_report_cases import cases
    from evaluations.first_report_trial import operator_principal

    company = cases()[0]
    company["descriptors"][1]["contract"]["tenant_id"] = "different"
    with pytest.raises(ValueError, match="one explicitly"):
        operator_principal(company)


async def test_compact_baseline_only_resolves_current_inspected_analyses():
    from evaluations.bootstrap_agent_trial import Audit
    from evaluations.first_report_cases import cases
    from evaluations.first_report_trial import PeriodAdapter, Session

    company = cases()[0]
    adapter = PeriodAdapter(company["descriptors"], Audit(), company["sources"])
    adapter.set_period(company["periods"][0])
    session = Session(company=company, adapter=adapter, server=None, phase="monitoring", audit=Audit())
    source = company["sources"][0]["key"]
    inspected = await session.call("inspect_source", {"source_key": source})
    analysis = inspected["analyses"][0]
    ref = {"source_key": source, "comparison_key": analysis["comparison_key"]}
    payload = {"status": "complete", "outcome": "notify", "recipients": [],
               "analysis_refs": [ref], "narrative": "Observed change, not a causal claim."}
    await session.call("submit_report", payload)
    assert session.submission["analyses"] == [analysis]
    inspected["analyses"][0]["current"] = -123456
    assert session.submission["analyses"][0]["current"] != -123456
    with pytest.raises(ValueError, match="Duplicate"):
        await session.call("submit_report", {**payload, "analysis_refs": [ref, ref]})
    new_session = Session(company=company, adapter=adapter, server=None, phase="monitoring", audit=Audit())
    with pytest.raises(ValueError, match="Inspect every"):
        await new_session.call("submit_report", payload)
    adapter.set_period(company["periods"][1])
    with pytest.raises(ValueError, match="current-period"):
        await session.call("submit_report", payload)
    await session.call("inspect_source", {"source_key": source})
    await session.call("submit_report", payload)
    assert session.submission["analyses"][0]["current"] != analysis["current"]


def test_baseline_schema_provides_exact_outcomes_and_no_table_copying():
    from pydantic import ValidationError

    from evaluations.first_report_trial import Submission

    payload = {"status": "complete", "outcome": "ignore", "recipients": [],
               "analysis_refs": [], "narrative": "No material change."}
    assert Submission.model_validate(payload).outcome.value == "ignore"
    with pytest.raises(ValidationError):
        Submission.model_validate({**payload, "outcome": "no_action"})
    with pytest.raises(ValidationError):
        Submission.model_validate({**payload, "analyses": []})

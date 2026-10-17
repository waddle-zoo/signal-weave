from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError, validate

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import build_scenarios, public_episode
from evaluations.domain_context_onboarding_trial import RecurringEpisode
from evaluations.human_report_episode import HumanReportEpisode


@pytest.fixture
def scenario():
    return build_scenarios(seed=20261001, split="dev", connector_profile=True)[0]


class _Native:
    def __init__(self, result=None):
        self.result = result or {}
        self.calls = []
        self.tools = [SimpleNamespace(name=name, description="", inputSchema={}) for name in (
            "evaluate_insight_card", "get_signalweave_guide", "search_catalog", "inspect_resource",
            "get_insight_card", "retrieve_domain_context", "get_decision_receipt",
            "draft_insight_card", "revise_insight_card", "approve_insight_card",
        )]

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        return None, self.result


def _episode(scenario, native=None, **kwargs):
    period = scenario["public"]["periods"][0]
    public = public_episode(scenario, period["period_id"])
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    adapter.set_period(public["period"], datetime.fromisoformat(public["period"]["as_of"]))
    return HumanReportEpisode(public, adapter, native, **kwargs)


async def _tools(episode):
    return {item["name"]: item for item in await episode.specs()}


def _report(episode):
    source = episode.public["catalog"][0]
    return {
        "outcome": "notify",
        "recipients": [episode.public["destinations"][0]["key"]],
        "summary": f"Net sales fell 12%; source: {source['adapter']}|{source['resource']}.",
    }


async def test_both_arms_share_report_read_and_calculator_contracts_without_authoring(scenario):
    baseline, treatment = _episode(scenario), _episode(scenario, _Native())
    base_tools, treatment_tools = await _tools(baseline), await _tools(treatment)

    assert base_tools["record_report"]["parameters"] == treatment_tools["record_report"]["parameters"]
    for name in ("list_company_assets", "read_company_asset", "read_company_glossary",
                 "read_working_notes", "calculate"):
        assert base_tools[name] == treatment_tools[name]
    assert "evaluate_insight_card" in treatment_tools
    assert set(treatment_tools) - set(base_tools) == {
        "evaluate_insight_card", "get_signalweave_guide", "search_catalog", "inspect_resource",
        "get_insight_card", "retrieve_domain_context", "get_decision_receipt",
    }
    assert not ({"ask_owner", "save_working_notes", "finish_setup", "draft_insight_card",
                 "revise_insight_card", "approve_insight_card"} & treatment_tools.keys())


async def test_serialized_schema_accepts_prose_without_numeric_registry_and_copies_exactly(scenario):
    episode = _episode(scenario)
    episode.public.pop("numeric_vocabulary")
    episode.public.pop("submission_contract")
    tool = (await _tools(episode))["record_report"]
    schema = json.loads(json.dumps(tool["parameters"]))
    props = schema["properties"]
    assert set(props) == {"outcome", "recipients", "summary"}
    assert schema["required"] == ["outcome", "recipients", "summary"]
    assert props["outcome"]["enum"] == ["ignore", "notify", "investigate", "insufficient_data"]
    private_conditions = {item["condition"] for item in scenario["private"]["periods"].values()}
    assert not private_conditions.intersection(props["outcome"]["enum"])
    assert props["recipients"]["items"]["enum"] == [
        item["key"] for item in episode.public["destinations"]
    ]
    assert props["summary"]["maxLength"] == 12000
    assert "numeric_claims" not in props and "numeric_definitions" not in json.dumps(schema)

    source = episode.public["catalog"][0]
    report = _report(episode)
    report["summary"] = (
        f"  Revenue fell 12%. Inline citation: {source['adapter']}|{source['resource']}.\n"
    )
    original = deepcopy(report)
    validate(report, schema)
    assert await episode.call("record_report", report) == {"recorded": True, "delivery_enabled": False}
    assert report == original and episode.submission == original
    report["summary"] = "caller changed this"
    report["recipients"].clear()
    assert episode.submission == original


async def test_ignore_route_rule_is_enforced_on_call_not_in_schema(scenario):
    episode = _episode(scenario)
    schema = (await _tools(episode))["record_report"]["parameters"]
    quiet = {"outcome": "ignore", "recipients": [], "summary": "Routine report for the team."}
    validate(quiet, schema)
    assert (await episode.call("record_report", quiet))["recorded"]

    routed = {**quiet, "recipients": [episode.public["destinations"][0]["key"]]}
    validate(routed, schema)
    with pytest.raises(ValueError, match="ignore has no"):
        await _episode(scenario).call("record_report", routed)


async def test_first_successful_report_cannot_be_overwritten(scenario):
    episode = _episode(scenario)
    first = _report(episode)
    await episode.call("record_report", first)
    with pytest.raises(ValueError, match="already recorded"):
        await episode.call("record_report", {**first, "summary": "replacement"})
    assert episode.submission == first


@pytest.mark.parametrize(("change", "error"), [
    ("extra", ValidationError), ("outcome", ValidationError), ("route", ValidationError),
    ("long", ValidationError),
    ("duplicate", ValueError), ("blank", ValueError),
])
async def test_record_report_rejects_invalid_payloads(scenario, change, error):
    episode = _episode(scenario)
    report = _report(episode)
    if change == "extra":
        report["numeric_claims"] = []
    elif change == "outcome":
        report["outcome"] = "surprise"
    elif change == "route":
        report["recipients"] = ["unapproved-route"]
    elif change == "long":
        report["summary"] = "x" * 12001
    elif change == "duplicate":
        report["recipients"] *= 2
    else:
        report["summary"] = " \n\t "
    with pytest.raises(error):
        await episode.call("record_report", report)


async def test_legacy_submit_analysis_is_rejected_and_default_recurring_contract_remains(scenario):
    episode = _episode(scenario)
    with pytest.raises(ValueError, match="Use record_report"):
        await episode.call("submit_analysis", {})

    public = public_episode(scenario, scenario["public"]["periods"][0]["period_id"])
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], Audit())
    legacy = RecurringEpisode(public, adapter)
    tools = await _tools(legacy)
    assert "submit_analysis" in tools and "record_report" not in tools
    assert set(legacy.submission_schema()["properties"]) == {
        "outcome", "recipients", "evidence_refs", "numeric_claims", "claims", "summary",
    }


async def test_native_evaluation_still_requires_exact_reviewed_card_and_run_key(scenario):
    result = {"receipt": {"card_id": "reviewed", "idempotency_key": "run-7",
                          "status": "delivery_disabled", "card_version": 3},
              "result": {"card_id": "reviewed"}}
    native = _Native(result)
    episode = _episode(scenario, native, approved_card_id="reviewed",
                       approved_card_version=3, run_key="run-7")
    with pytest.raises(ValueError, match="exact reviewed card"):
        await episode.call("evaluate_insight_card", {"card_id": "other", "idempotency_key": "run-7"})
    with pytest.raises(ValueError, match="exact reviewed card"):
        await episode.call("evaluate_insight_card", {"card_id": "reviewed", "idempotency_key": "other"})
    assert native.calls == []
    await episode.call("evaluate_insight_card", {"card_id": "reviewed", "idempotency_key": "run-7"})
    assert episode.evaluation_verified
    assert len(native.calls) == 1

from collections import Counter

import pytest

from evaluations.agent_workflow_cohort import build_cohort, summarize
from evaluations.bootstrap_scenarios import agent_context, public_episode, public_scenario
from evaluations.native_cadence_trial import select_periods
from signalweave.models import ResourceDescriptor, ResourceSnapshot


@pytest.fixture(scope="module")
def cohort():
    return build_cohort()


def test_cohort_has_six_business_families_and_108_prospective_weekly_contexts(cohort):
    assert len(cohort) == 6
    assert len({s["private"]["family"] for s in cohort}) == 6
    assert sum(len(s["public"]["periods"]) for s in cohort) == 108
    for scenario in cohort:
        periods = select_periods(scenario, {"pilot_indices": [0, 1, 2, 3]}, cases="all")
        assert len(periods) == 18
        assert Counter(row["label"]["condition"] for row in periods) == {
            "quiet": 6, "event": 6, "quality": 6}
        assert len(scenario["public"]["catalog"]) == 84


def test_fixture_never_misrepresents_normalized_mcp_as_a_real_provider(cohort):
    for scenario in cohort:
        assert {item["adapter"] for item in scenario["public"]["catalog"]} == {"company_mcp"}
        for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
            assert all(ref.startswith("company_mcp|") for ref in period["snapshots"])
            for snapshot in period["snapshots"].values():
                assert snapshot["adapter"] == "company_mcp"


def test_fixture_models_and_scope_are_valid_and_private_labels_do_not_enter_prompts(cohort):
    for scenario in cohort:
        public = public_scenario(scenario)
        context = agent_context(public_episode(scenario))
        assert not {"private", "periods", "onboarding", "owner_answers"} & context.keys()
        catalog = {f"{item['adapter']}|{item['resource']}": ResourceDescriptor.model_validate(item)
                   for item in public["catalog"]}
        for period in [public["onboarding"], *public["periods"]]:
            assert set(period["snapshots"]) == set(catalog)
            for ref, value in period["snapshots"].items():
                snapshot = ResourceSnapshot.model_validate(value)
                assert snapshot.contract.tenant_id == scenario["scenario_id"]
                assert catalog[ref].contract.tenant_id == scenario["scenario_id"]
                assert "expected_outcome" not in snapshot.metadata


def test_run_quality_changes_without_changing_the_reviewed_catalog_meaning(cohort):
    for scenario in cohort:
        public = scenario["public"]
        primary = next(item for item in public["catalog"] if item["contract"].get("roles") == ["primary"])
        ref = f"{primary['adapter']}|{primary['resource']}"
        assert primary["contract"]["comparison_contracts"][0]["comparable"] is True
        for period in public["periods"]:
            label = scenario["private"]["periods"][period["period_id"]]
            binding = period["snapshots"][ref]["contract"]["comparison_contracts"][0]
            assert binding["comparable"] is (label["condition"] != "quality")
            if label["condition"] == "quality" and label["context"] == "definition_drift":
                assert binding["definition"] != primary["contract"]["comparison_contracts"][0]["definition"]
        assert primary["contract"]["comparison_contracts"][0]["coverage"] == "complete"


def test_missing_work_is_not_counted_as_observed_success():
    summary = summarize([{"status": "onboarding_incomplete", "onboarding_complete": False,
                          "summary": {"intended_cases": 18, "paired_cases": 0,
                                      "treatment_outcome_correct": 0}}], 6)
    assert summary["intended_companies"] == 6
    assert summary["completed_companies"] == summary["onboarded_companies"] == 0
    assert summary["intended_cases"] == 18
    assert summary["paired_cases"] == 0

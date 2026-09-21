import json
from pathlib import Path

import pytest

from evaluations.onboarding_contract_trial import run_scenario, run_trial

CASES = Path(__file__).parents[1] / "evaluations" / "data" / "onboarding-scenarios.json"


@pytest.mark.asyncio
async def test_generalized_onboarding_matrix_runs_without_source_specific_core_branches():
    results = await run_trial(CASES)

    assert len(results) == 11
    assert {result.domain for result in results} == {
        "saas",
        "retail",
        "fintech",
        "marketplace",
        "logistics",
        "healthcare",
        "manufacturing",
        "multi-domain",
    }
    assert all(result.candidate_count >= 0 for result in results)


@pytest.mark.asyncio
async def test_tenant_decoy_is_filtered_before_jev_sees_candidates():
    scenarios = json.loads(CASES.read_text())
    scenario = next(item for item in scenarios if item["scenario_id"] == "tenant-decoy")

    result = await run_scenario(scenario)

    assert result.tenant_leaks == []
    assert result.relevant_recall == 1.0
    assert result.passed is True


@pytest.mark.asyncio
async def test_large_catalog_uses_server_search_and_exposes_incompleteness():
    scenarios = json.loads(CASES.read_text())
    scenario = next(item for item in scenarios if item["scenario_id"] == "large-bounded-catalog")

    result = await run_scenario(scenario)

    assert result.candidate_count == 100_000
    assert result.truncated is True
    # This is an intentionally visible red case: the current review contract
    # can still approve a selected anchor despite an incomplete catalog.
    assert result.review_status == "ready_for_approval"
    assert "human-review gate differs" in result.failures

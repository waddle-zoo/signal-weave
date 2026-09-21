import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest

from evaluations.onboarding_contract_trial import run_scenario, run_trial
from evaluations.onboarding_readiness import assess_readiness
from signalweave.models import (
    InsightCard,
    InsightCardOnboardingReview,
    ResourceContract,
    ResourceDiscovery,
    ResourceMatch,
    SourceRef,
)

CASES = Path(__file__).parents[1] / "evaluations" / "data" / "onboarding-scenarios.json"


@pytest.mark.asyncio
async def test_generalized_onboarding_matrix_runs_without_source_specific_core_branches():
    results = await run_trial(CASES)
    scenario_ids = {result.scenario_id for result in results}

    assert len(results) == 24
    assert {
        "saas",
        "retail",
        "fintech",
        "marketplace",
        "logistics",
        "healthcare",
        "manufacturing",
        "multi-domain",
        "data-platform",
    } <= {result.domain for result in results}
    assert {
        "seedless-executive-pulse",
        "airflow-only-freshness",
        "permission-revoked-after-card-draft",
        "fiscal-calendar-definition-conflict",
        "paginated-catalog-resume",
    } <= scenario_ids
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


@pytest.mark.asyncio
async def test_readiness_pattern_catches_expected_human_and_enterprise_blockers():
    results = await run_trial(CASES)

    assert all(result.readiness_passed for result in results)
    assert any("definition-conflict" in result.readiness_codes for result in results)
    assert any("source-health-review" in result.readiness_codes for result in results)
    assert any("catalog-incomplete" in result.readiness_codes for result in results)
    assert any(result.readiness_status == "blocked" for result in results)


def test_missing_principal_is_a_hard_readiness_block():
    card = InsightCard(
        id="card-missing-principal",
        title="Missing principal",
        what_to_watch="Revenue movement",
        why_watch="Decide whether to notify Finance.",
    )
    discovery = ResourceDiscovery(
        goal="Revenue movement",
        matches=[],
        candidate_count=0,
        candidate_limit=10,
        no_match=True,
        evaluator="test-jev",
    )
    review = InsightCardOnboardingReview(
        card_id=card.id,
        status="needs_human_input",
    )

    readiness = assess_readiness(
        card,
        discovery,
        review,
        principal_tenant=None,
    )

    assert readiness.status.value == "blocked"
    assert "principal-required" in readiness.blocker_codes
    assert "anchor-required" in readiness.blocker_codes


def test_readiness_defense_in_depth_blocks_a_post_discovery_permission_drift():
    card = InsightCard(
        id="card-permission-drift",
        title="Permission drift",
        what_to_watch="Revenue movement",
        why_watch="Decide whether to notify Finance.",
        sources=[
            SourceRef(
                key="revenue",
                adapter="looker",
                resource="dashboard:revenue",
                label="Revenue",
            )
        ],
    )
    discovery = ResourceDiscovery(
        goal="Revenue movement",
        matches=[
            ResourceMatch(
                ref="looker|dashboard:revenue",
                adapter="looker",
                resource="dashboard:revenue",
                kind="dashboard",
                title="Revenue",
                recommended=True,
                relevance=0.95,
                contract=ResourceContract(
                    tenant_id="northstar",
                    authorized=False,
                ),
            )
        ],
        candidate_count=1,
        candidate_limit=10,
        evaluator="test-jev",
    )
    review = InsightCardOnboardingReview(
        card_id=card.id,
        status="ready_for_approval",
    )

    readiness = assess_readiness(
        card,
        discovery,
        review,
        principal_tenant="northstar",
    )

    assert readiness.status.value == "blocked"
    assert "unauthorized-candidate" in readiness.blocker_codes


@pytest.mark.asyncio
async def test_stale_and_truncated_cases_remain_red_in_the_current_review_contract():
    scenarios = json.loads(CASES.read_text())
    stale = deepcopy(
        next(item for item in scenarios if item["scenario_id"] == "stale-source-review")
    )
    large = deepcopy(
        next(item for item in scenarios if item["scenario_id"] == "large-bounded-catalog")
    )

    stale_result, large_result = await asyncio.gather(run_scenario(stale), run_scenario(large))

    assert stale_result.readiness_status == "needs_human_review"
    assert "source-health-review" in stale_result.readiness_codes
    assert stale_result.passed is False
    assert large_result.readiness_status == "needs_human_review"
    assert "catalog-incomplete" in large_result.readiness_codes
    assert large_result.passed is False

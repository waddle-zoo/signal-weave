import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations.onboarding_adversarial_review import audit_matrix
from evaluations.onboarding_contract_trial import (
    ScenarioAdapter,
    ScenarioJev,
    _descriptor,
    run_scenario,
    run_trial,
)
from evaluations.onboarding_readiness import assess_readiness
from signalweave.models import (
    InsightCard,
    InsightCardOnboardingReview,
    OnboardingDiscoveryReceipt,
    PrincipalContext,
    ResourceContract,
    ResourceDescriptor,
    ResourceDiscovery,
    ResourceMatch,
    SourceRef,
)
from signalweave.onboarding import InsightAuthoringService
from signalweave.sources import SourceRegistry

CASES = Path(__file__).parents[1] / "evaluations" / "data" / "onboarding-scenarios.json"


@pytest.mark.asyncio
async def test_generalized_onboarding_matrix_runs_without_source_specific_core_branches():
    results = await run_trial(CASES)
    scenario_ids = {result.scenario_id for result in results}

    assert len(results) == 30
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
        "media",
    } <= {result.domain for result in results}
    assert len({scenario["principal"]["tenant_id"] for scenario in json.loads(CASES.read_text())}) == 7
    assert sum(result.role_labels_checked for result in results) == 39
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
async def test_request_principal_scopes_shared_catalog_search_and_inspection():
    scenarios = json.loads(CASES.read_text())
    scenario = next(item for item in scenarios if item["scenario_id"] == "tenant-decoy")
    resources = [_descriptor(raw) for raw in scenario["resources"]]
    resources.append(
        ResourceDescriptor(
            adapter="looker",
            resource="dashboard:other-only",
            kind="dashboard",
            title="Other-only dashboard",
            contract=ResourceContract(tenant_id="otherco", domain="growth"),
        )
    )
    adapters = [
        ScenarioAdapter(
            adapter,
            [resource for resource in resources if resource.adapter == adapter],
            server_search=False,
            total_count=len(resources),
            has_more=False,
        )
        for adapter in sorted({resource.adapter for resource in resources})
    ]
    registry = SourceRegistry(adapters)
    service = InsightAuthoringService(
        registry=registry,
        engine=SimpleNamespace(judger=ScenarioJev(scenario["jev_scores"])),
    )

    for tenant_id in ("northstar", "otherco"):
        discovery = await service.discover(
            scenario["goal"],
            principal=PrincipalContext(
                principal_id=f"{tenant_id}-reviewer", tenant_id=tenant_id
            ),
        )
        assert discovery.matches
        assert {match.contract.tenant_id for match in discovery.matches} == {tenant_id}

    other_source = SourceRef(
        key="other-conversion",
        adapter="looker",
        resource="dashboard:other-only",
        label="Other-only dashboard",
    )
    blocked = await registry.inspect(other_source, authorized_tenants=["northstar"])
    assert blocked.error and "authorized adapter catalog" in blocked.error
    visible = await registry.inspect(other_source, authorized_tenants=["otherco"])
    assert visible.error is None


@pytest.mark.asyncio
async def test_large_catalog_uses_server_search_and_exposes_incompleteness():
    scenarios = json.loads(CASES.read_text())
    scenario = next(item for item in scenarios if item["scenario_id"] == "large-bounded-catalog")

    result = await run_scenario(scenario)

    # The fixture adapter does not accept an authorized_tenants keyword, so
    # the registry redacts its provider-wide count rather than exposing other
    # tenants' catalog size. The pagination flag keeps the incomplete scope
    # visible for human review.
    assert result.candidate_count == 1
    assert result.truncated is True
    assert any("catalog count was redacted" in warning for warning in result.warnings)
    assert result.review_status == "needs_human_input"
    assert result.passed is True
    assert result.readiness_status == "needs_human_review"


@pytest.mark.asyncio
async def test_readiness_pattern_catches_expected_human_and_enterprise_blockers():
    results = await run_trial(CASES)

    assert all(result.readiness_passed for result in results)
    assert all(result.safe for result in results)
    assert all(not result.role_mismatches for result in results)
    assert any("definition-conflict" in result.readiness_codes for result in results)
    assert any("source-health-review" in result.readiness_codes for result in results)
    assert any("catalog-incomplete" in result.readiness_codes for result in results)
    assert any(result.readiness_status == "blocked" for result in results)


@pytest.mark.asyncio
async def test_independent_adversarial_review_passes_scope_and_generalization_gates():
    scenarios = json.loads(CASES.read_text())
    report = audit_matrix(scenarios, await run_trial(CASES), evaluator="fixture-jev")

    assert report.passed is True
    assert not any(
        finding.reviewer in {"scope", "generalization"} and finding.severity == "error"
        for finding in report.findings
    )
    assert any(
        finding.reviewer == "correctness" and finding.severity == "warning"
        for finding in report.findings
    )


@pytest.mark.asyncio
async def test_adversarial_reviewer_catches_silent_approval_scope_and_recall_mutations():
    scenarios = json.loads(CASES.read_text())
    results = await run_trial(CASES)
    by_id = {result.scenario_id: result for result in results}

    silent_approval = replace(
        by_id["no-match-abstention"], readiness_status="ready_for_approval"
    )
    scope_leak = replace(by_id["tenant-decoy"], tenant_leaks=["looker|dashboard:conversion"])
    recall_drop = replace(by_id["saas-single-bi-anchor"], relevant_recall=0.5)

    for mutated in (silent_approval, scope_leak, recall_drop):
        mutated_results = [
            mutated if result.scenario_id == mutated.scenario_id else result
            for result in results
        ]
        report = audit_matrix(scenarios, mutated_results, evaluator="mutation-test")
        assert report.passed is False
        assert any(
            finding.reviewer in {"correctness", "scope"}
            and finding.severity == "error"
            and finding.scenario_id == mutated.scenario_id
            for finding in report.findings
        )


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
        discovery_receipt=OnboardingDiscoveryReceipt(
            catalog_provider="test",
            catalog_strategy="fixture",
            candidate_count=0,
            candidate_limit=10,
            evaluator="test-jev",
        ),
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
    assert "intent-detail-required" in readiness.blocker_codes


def test_production_onboarding_review_blocks_missing_principal_boundary():
    card = InsightCard(
        id="card-production-principal",
        title="Principal boundary",
        what_to_watch="Revenue movement",
        why_watch="Decide whether Finance should act.",
        watch_for=["Revenue is materially down."],
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
                contract=ResourceContract(tenant_id="northstar"),
            )
        ],
        candidate_count=1,
        candidate_limit=10,
        evaluator="test-jev",
    )

    review = InsightAuthoringService.build_onboarding_review(card, discovery)

    assert review.readiness_status == "blocked"
    assert review.principal_id is None
    assert review.authorization_evidence == "not-provided"
    assert any(blocker.code.value == "principal-required" for blocker in review.blockers)


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
        discovery_receipt=OnboardingDiscoveryReceipt(
            catalog_provider="test",
            catalog_strategy="fixture",
            candidate_count=1,
            candidate_limit=10,
            evaluator="test-jev",
        ),
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
async def test_stale_and_truncated_cases_are_blocked_by_the_hardened_review_contract():
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
    assert stale_result.review_status == "needs_human_input"
    assert stale_result.passed is True
    assert large_result.readiness_status == "needs_human_review"
    assert "catalog-incomplete" in large_result.readiness_codes
    assert large_result.review_status == "needs_human_input"
    assert large_result.passed is True

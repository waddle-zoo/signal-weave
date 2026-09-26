from __future__ import annotations

import json
from collections import Counter

import pytest

from evaluations.northstar_scale_adversarial_review import review
from evaluations.northstar_scale_trial import (
    _build_bundle_cases,
    _build_cases,
    _descriptors_and_records,
    _load_reused_workflow_evidence,
    build_scale_fixtures,
)
from signalweave.retrieval import build_candidate_pool
from signalweave.sources import SourceRegistry


def test_northstar_scale_is_config_derived_and_covers_realistic_population():
    config, fixtures, roster = build_scale_fixtures()

    assert len(config["domains"]) == 12
    assert len(config["personas"]) == 24
    assert len(roster) == 40
    assert {fixture["stats"]["tasks"] for fixture in fixtures.values()} == {168}

    workflow_cases, retrieval_cases, cards = _build_cases(
        config, fixtures, tenant_id="northstar-outfitters"
    )
    bundle_cases = _build_bundle_cases(config, fixtures, tenant_id="northstar-outfitters")
    assert len(workflow_cases) == 168
    assert len(retrieval_cases) == 169
    assert len(cards) == 168
    assert len(bundle_cases) == 168
    assert {case.dataset.split for case in workflow_cases} == {
        "train",
        "validation",
        "holdout",
        "adversarial",
    }
    assert {
        case.tags[-1]
        for case in workflow_cases
    } == {
        "corroborated_notify",
        "explained_ignore",
        "contradictory_investigate",
        "stale_escalation",
        "definition_mismatch",
        "missing_baseline",
        "source_failure",
    }
    assert all(card.decision_guidance for card in cards.values())
    assert all(card.principal_tenant == "northstar-outfitters" for card in cards.values())
    assert all(len(case.expected_resource_refs) == 1 for case in retrieval_cases[:-1])
    assert all(case.required_resource_groups for case in retrieval_cases[:-1])
    assert all(case.context and case.context.trust == "trusted" for case in bundle_cases)
    assert all(
        case.card.sources[0].resource.startswith("dashboard:northstar-scale-anchor-")
        for case in bundle_cases
    )
    assert all(len(case.expected_related_groups) == 1 for case in bundle_cases)


def test_northstar_scale_native_catalog_is_virtual_and_bounded():
    _config, fixtures, _roster = build_scale_fixtures()
    adapters, _records, stats = _descriptors_and_records(
        fixtures,
        decoys_per_adapter=4,
        virtual_catalog_size=100_000,
        tenant_id="northstar-outfitters",
    )

    assert stats["virtual_catalog_size_per_adapter"] == 100_000
    assert stats["materialized_descriptors"] > len(adapters)
    assert all(adapter.list_calls == 0 for adapter in adapters)
    assert all(adapter.total_count == 100_000 for adapter in adapters)
    context_descriptors = [
        descriptor
        for adapter in adapters
        for descriptor in adapter._descriptors
        if descriptor.metadata.get("context_source")
    ]
    assert context_descriptors
    assert all(descriptor.metadata.get("related_refs") for descriptor in context_descriptors)


@pytest.mark.asyncio
async def test_northstar_scale_overfetch_preserves_cross_adapter_context_before_jev(tmp_path):
    config, fixtures, _roster = build_scale_fixtures(output_dir=tmp_path)
    adapters, _records, _stats = _descriptors_and_records(
        fixtures,
        decoys_per_adapter=4,
        virtual_catalog_size=100_000,
        tenant_id="northstar-outfitters",
    )
    _workflow_cases, retrieval_cases, _cards = _build_cases(
        config, fixtures, tenant_id="northstar-outfitters"
    )
    case = retrieval_cases[0]
    page = await SourceRegistry(adapters).search_resources(
        case.goal,
        limit=46,
        authorized_tenants=["northstar-outfitters"],
    )
    pool = build_candidate_pool(case.goal, page.resources, limit=40)
    refs = {f"{resource.adapter}|{resource.resource}" for resource in pool.resources}

    assert len(pool.resources) == 40
    assert set(case.expected_resource_refs) <= refs
    assert any(set(group) & refs for group in case.required_resource_groups)


def test_northstar_scale_adversarial_gate_rejects_unsafe_report():
    report = {
        "evaluator": "jev-latest",
        "jev_only_product_path": True,
        "scale": {
            "role_agents": 40,
            "workflow_case_count": 168,
            "retrieval_case_count": 168,
            "bundle_case_count": 168,
            "variant_counts": {
                "corroborated_notify": 24,
                "explained_ignore": 24,
                "contradictory_investigate": 24,
                "stale_escalation": 24,
                "definition_mismatch": 24,
                "missing_baseline": 24,
                "source_failure": 24,
            },
            "catalog": {"virtual_catalog_size_per_adapter": 100_000},
        },
        "bootstrap": {
            "report": {
                "status": "ready",
                "adapters": [{"status": "ready"}],
            }
        },
        "retrieval": {
            "status": "approved",
            "candidate_recall": 1.0,
            "recommended_precision": 0.95,
            "recommended_recall": 0.95,
            "required_group_recall": 1.0,
            "unauthorized_ref_count": 0,
        },
        "bundle_retrieval": {
            "status": "approved",
            "candidate_group_recall": 1.0,
            "selected_group_recall": 1.0,
            "selected_precision": 0.95,
            "error_rate": 0.0,
            "unauthorized_ref_count": 0,
        },
        "workflow": {
            "status": "approved",
            "outcome_accuracy": 0.95,
            "evidence_recall": 1.0,
            "retrieval_recall": 1.0,
            "unsafe_action_rate": 0.0,
            "error_rate": 0.0,
        },
        "adversarial_review_inputs": {
            "dataset_splits": ["train", "validation", "holdout", "adversarial"],
            "labels_sent_to_jev": False,
            "leaked_label_keys": [],
            "native_catalog_full_scan_calls": 0,
            "candidate_pool_bound": 40,
        },
    }

    assert review(report)["passed"] is True
    report["bundle_retrieval"]["selected_group_recall"] = 0.5
    group_failed = review(report)
    assert group_failed["passed"] is False
    assert "Jev bundle selection missed a required related-source group" in group_failed[
        "failures"
    ]
    report["bundle_retrieval"]["selected_group_recall"] = 1.0
    report["workflow"]["unsafe_action_rate"] = 0.01
    failed = review(report)
    assert failed["passed"] is False
    assert "workflow emitted at least one unsafe automatic action" in failed["failures"]


def test_northstar_scale_reused_workflow_requires_matching_fixture_identity(tmp_path):
    config, fixtures, roster = build_scale_fixtures(output_dir=tmp_path)
    workflow_cases, _retrieval_cases, cards = _build_cases(
        config, fixtures, tenant_id="northstar-outfitters"
    )
    source_adapters = {source.adapter for case in workflow_cases for source in case.card.sources}
    workflow = {
        "status": "approved",
        "case_count": len(workflow_cases),
        "error_rate": 0.0,
        "dataset_ids": sorted(case.dataset.dataset_id for case in workflow_cases),
        "card_ids": sorted(cards),
        "splits": ["adversarial", "holdout", "train", "validation"],
        "jev_requests": 336,
    }
    payload = {
        "evaluator": "jev-latest",
        "jev_only_product_path": True,
        "scale": {
            "company": config["company"],
            "domains": len(config["domains"]),
            "owner_personas": len(config["personas"]),
            "role_agents": len(roster),
            "workflow_case_count": len(workflow_cases),
            "variant_counts": {},
            "expected_outcome_counts": {},
            "source_adapters": sorted(source_adapters),
        },
        "workflow": workflow,
    }
    # Use the real distributions rather than relying on the minimal payload's
    # placeholder, keeping the identity check itself under test.
    payload["scale"]["variant_counts"] = dict(Counter(case.tags[-1] for case in workflow_cases))
    payload["scale"]["expected_outcome_counts"] = dict(
        Counter(case.expected_outcome.value for case in workflow_cases)
    )
    report_path = tmp_path / "workflow.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = _load_reused_workflow_evidence(
        report_path,
        workflow_cases=workflow_cases,
        cards=cards,
        config=config,
        roster=roster,
        source_adapters=source_adapters,
    )
    assert loaded["workflow"]["status"] == "approved"

    payload["workflow"]["dataset_ids"][0] = "wrong-dataset"
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset IDs"):
        _load_reused_workflow_evidence(
            report_path,
            workflow_cases=workflow_cases,
            cards=cards,
            config=config,
            roster=roster,
            source_adapters=source_adapters,
        )

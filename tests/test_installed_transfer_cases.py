import copy
import json
from datetime import datetime

import pytest

from evaluations.enterprise_onboarding_journeys import journeys
from evaluations.installed_transfer_cases import _target_resource_map, build_transfers
from evaluations.installed_workflow_trial import bind_examples
from signalweave.models import ResourceDescriptor, ResourceSnapshot


def _dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_transfer_fixture_has_six_valid_scenarios_and_target_future_shape():
    scenarios = build_transfers()
    assert len(scenarios) == 6
    assert len({scenario["scenario_id"] for scenario in scenarios}) == 6
    for scenario in scenarios:
        public = scenario["public"]
        assert len(public["catalog"]) == 24
        assert len(public["periods"]) == 3
        assert len(scenario["owner_examples"]) == 3
        for descriptor_payload in public["catalog"]:
            descriptor = ResourceDescriptor.model_validate(descriptor_payload)
            assert descriptor.adapter == "company_mcp"
        for period in [public["onboarding"], *public["periods"]]:
            refs = set(period["snapshots"])
            assert len(refs) == 24
            for ref, payload in period["snapshots"].items():
                snapshot = ResourceSnapshot.model_validate(payload)
                assert ref == f"{snapshot.adapter}|{snapshot.resource}"
                assert snapshot.source_key == snapshot.resource
                assert snapshot.contract.tenant_id == scenario["scenario_id"]
                assert snapshot.metadata["reporting_cutoff"] == period["as_of"]


def test_transfer_examples_are_disjoint_from_future_labels_and_before_onboarding():
    for scenario, target in zip(build_transfers(), journeys(20261004), strict=True):
        public = scenario["public"]
        assert scenario["private"] == target["private"]
        future_ids = {period["period_id"] for period in public["periods"]}
        example_ids = {example["id"] for example in scenario["owner_examples"]}
        assert future_ids.isdisjoint(example_ids)
        assert all("expected_outcome" not in json.dumps(period) for period in public["periods"])
        onboarding = _dt(public["onboarding"]["as_of"])
        for example in scenario["owner_examples"]:
            assert all(resource["metadata"]["reporting_cutoff"] == example["as_of"]
                       for resource in example["resources"])
            for resource in example["resources"]:
                for timestamp in ("captured_at", "source_captured_at"):
                    if resource.get(timestamp):
                        assert _dt(resource[timestamp]) <= _dt(example["as_of"])
            assert all(_dt(resource["metadata"]["reporting_cutoff"]) < onboarding
                       for resource in example["resources"])
            assert example["required_evidence_refs"]
            assert set(example["expected_retrieval_refs"]) == set(example["required_evidence_refs"])
            assert len(example["resources"]) == 2
            assert set(example["expected_retrieval_refs"]) <= {
                f"{resource['adapter']}|{resource['resource']}"
                for resource in example["resources"]
            }


def test_transfer_keeps_target_policy_and_maps_refs_and_destinations():
    expected = journeys(20261004)
    for scenario, original in zip(build_transfers(), expected, strict=True):
        target_policy = scenario["public"]["owner_answers"]
        target_destinations = {item["key"]: item["destination"] for item in scenario["public"]["destinations"]}
        target_refs = {f"{item['adapter']}|{item['resource']}" for item in scenario["public"]["catalog"]}
        assert target_policy == original["public"]["owner_answers"]
        for example in scenario["owner_examples"]:
            assert set(example["expected_delivery_destinations"]) <= set(target_destinations)
            assert set(example["expected_delivery_destinations"].values()) <= set(target_destinations.values())
            assert set(example["required_evidence_refs"]) <= target_refs
            assert set(example["expected_retrieval_refs"]) <= target_refs
            assert set(example["required_evidence_refs"]) <= set(example["expected_retrieval_refs"])
            assert {f"{item['adapter']}|{item['resource']}" for item in example["resources"]} >= set(
                example["expected_retrieval_refs"]
            )


def test_transfer_adds_finance_reporting_cutoff_to_calibration_and_future_snapshots():
    for scenario in build_transfers():
        periods = [scenario["public"]["onboarding"], *scenario["public"]["periods"]]
        for example in scenario["owner_examples"]:
            periods.append({"as_of": example["resources"][0]["metadata"]["reporting_cutoff"],
                            "snapshots": {resource["resource"]: resource for resource in example["resources"]}})
        for period in periods:
            for snapshot in period["snapshots"].values():
                assert snapshot["metadata"]["reporting_cutoff"] == period["as_of"]


@pytest.mark.parametrize("seed", [20261004, 20261005, 20262013])
def test_resource_mapping_preserves_complete_semantic_identity_across_families(seed):
    target_scenarios = journeys(seed)
    calibration_scenarios = journeys(seed + 1009)
    assert len(target_scenarios) == len(calibration_scenarios) == 6
    for target, calibration in zip(target_scenarios, calibration_scenarios, strict=True):
        mapping = _target_resource_map(target, calibration)
        target_by_resource = {
            item["resource"]: item for item in target["public"]["catalog"]
        }
        calibration_by_resource = {
            item["resource"]: item for item in calibration["public"]["catalog"]
        }
        target_snapshots = target["public"]["onboarding"]["snapshots"]
        calibration_snapshots = calibration["public"]["onboarding"]["snapshots"]
        assert set(mapping) == set(calibration_by_resource)
        assert set(mapping.values()) == set(target_by_resource)
        for calibration_resource, target_resource in mapping.items():
            source = calibration_by_resource[calibration_resource]
            expected = target_by_resource[target_resource]
            assert _semantic_fields(source) == _semantic_fields(expected)
            source_snapshot = calibration_snapshots[f"company_mcp|{calibration_resource}"]
            expected_snapshot = target_snapshots[f"company_mcp|{target_resource}"]
            assert source_snapshot["title"] == expected_snapshot["title"]
            assert source_snapshot["description"] == expected_snapshot["description"]
            assert _semantic_fields({**source_snapshot, "kind": source["kind"]}) == (
                _semantic_fields({**expected_snapshot, "kind": expected["kind"]})
            )
            for source_comparison, expected_comparison in zip(
                source_snapshot.get("analytical_comparisons", []),
                expected_snapshot.get("analytical_comparisons", []),
                strict=True,
            ):
                for field in (
                    "key",
                    "kind",
                    "metric",
                    "unit",
                    "dimension",
                    "definition",
                    "population",
                    "coverage",
                    "comparable",
                ):
                    assert source_comparison.get(field) == expected_comparison.get(field)


def _semantic_fields(item):
    contract = item["contract"]
    return (
        item["title"],
        item["kind"],
        item["description"],
        contract["scope"],
        contract["population"],
        tuple(contract["metric_names"]),
        tuple(contract["metric_definitions"]),
        tuple(contract["available_comparison_windows"]),
    )


def test_resource_mapping_is_invariant_to_catalog_order():
    target, calibration = journeys(20261004)[5], journeys(20261004 + 1009)[5]
    expected = _target_resource_map(target, calibration)
    reordered_target = copy.deepcopy(target)
    reordered_calibration = copy.deepcopy(calibration)
    reordered_target["public"]["catalog"].reverse()
    reordered_calibration["public"]["catalog"] = (
        reordered_calibration["public"]["catalog"][7:]
        + reordered_calibration["public"]["catalog"][:7]
    )
    assert _target_resource_map(reordered_target, reordered_calibration) == expected


def test_resource_mapping_rejects_ambiguous_duplicate_semantic_identity():
    target, calibration = journeys(20261004)[0], journeys(20261004 + 1009)[0]
    duplicate = copy.deepcopy(target["public"]["catalog"][0])
    duplicate["resource"] = "resource-ambiguous-duplicate"
    target["public"]["catalog"].append(duplicate)
    with pytest.raises(ValueError, match="ambiguous target semantic identity"):
        _target_resource_map(target, calibration)


@pytest.mark.parametrize("field,value", [
    ("population", "different eligible population"),
    ("metric_definitions", ["different metric meaning"]),
    ("available_comparison_windows", ["year_over_year"]),
])
def test_resource_mapping_rejects_contract_drift_despite_identical_title(field, value):
    target, calibration = journeys(20261004)[0], journeys(20261004 + 1009)[0]
    target["public"]["catalog"][0]["contract"][field] = value
    with pytest.raises(ValueError, match="catalog semantic identities differ"):
        _target_resource_map(target, calibration)


def test_optional_available_context_does_not_become_required_retrieval():
    scenario = build_transfers()[4]
    example = next(item for item in scenario["owner_examples"] if item["expected_outcome"] == "ignore")
    required_ref, = example["required_evidence_refs"]
    adapter, resource = required_ref.split("|", 1)
    card = {"sources": [{"key": "primary", "adapter": adapter, "resource": resource}],
            "delivery_methods": []}
    bound, = bind_examples([example], card)
    assert len(example["resources"]) == 2  # The optional context is still available.
    assert len(bound["resources"]) == 1
    assert bound["expected_retrieval_refs"] == [required_ref]
    assert bound["required_evidence_source_keys"] == ["primary"]
    with pytest.raises(ValueError, match="omits an owner-required evidence"):
        bind_examples([example], {"sources": [], "delivery_methods": []})

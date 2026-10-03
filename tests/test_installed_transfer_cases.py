import json
from datetime import datetime

from evaluations.enterprise_onboarding_journeys import journeys
from evaluations.installed_transfer_cases import build_transfers
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
            assert len(example["expected_retrieval_refs"]) == 2
            assert set(example["expected_retrieval_refs"]) == {
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
            assert {f"{item['adapter']}|{item['resource']}" for item in example["resources"]} == set(
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

import json
from datetime import datetime

from evaluations.installed_northstar_cases import build_northstar
from evaluations.northstar_growth_history_trial import (
    DEFAULT_SPEC,
    build_historical_cases,
    load_spec,
)
from signalweave.models import ResourceDescriptor, ResourceSnapshot
from tests.test_northstar_growth_history_trial import _write_seed_dir


def test_installed_fixture_separates_setup_labels_from_future_cases(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"))
    assert len(scenario["owner_examples"]) == 6
    assert len(scenario["public"]["periods"]) == 42
    assert len(scenario["private"]["periods"]) == 42
    assert {item["id"] for item in scenario["owner_examples"]}.isdisjoint(scenario["private"]["periods"])
    assert not {"card", "expert_card"} & scenario["public"].keys()


def test_installed_fixture_has_constant_policy_and_authorized_simulation_routes(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"))
    policy = scenario["public"]["owner_answers"]["materiality"]
    assert policy
    assert all(item["public"]["owner_answers"]["materiality"] == policy for item in [scenario])
    assert {item["destination"] for item in scenario["public"]["destinations"]} == {
        "slack://simulation-leadership", "slack://simulation-analytics", "slack://simulation-data-trust"
    }
    assert all(item["authorized"] and item["destination"].startswith("slack://simulation-")
               for item in scenario["public"]["destinations"])
    assert scenario["owner_examples"][3]["expected_delivery_destinations"] == {
        "leadership": "slack://simulation-leadership"
    }
    assert scenario["owner_examples"][5]["expected_delivery_destinations"] == {
        "data-trust": "slack://simulation-data-trust"
    }
    assert all("required_evidence_refs" in item for item in scenario["owner_examples"])


def test_installed_fixture_refs_validate_and_preserve_replayed_measurements(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"), smoke=True)
    public = scenario["public"]
    descriptors = [ResourceDescriptor.model_validate(item) for item in public["catalog"]]
    refs = {f"{item.adapter}|{item.resource}" for item in descriptors}
    assert len(descriptors) == 8
    assert all(item.contract.available_comparison_windows == ["previous_period"] for item in descriptors)
    assert len([item for item in descriptors if item.metadata.get("excluded")]) == 4
    for period in [public["onboarding"], *public["periods"]]:
        assert set(period["snapshots"]) == refs
        datetime.fromisoformat(period["as_of"].replace("Z", "+00:00"))
        for ref, payload in period["snapshots"].items():
            snapshot = ResourceSnapshot.model_validate(payload)
            assert ref == f"{snapshot.adapter}|{snapshot.resource}"
            assert snapshot.source_key == snapshot.resource
            assert snapshot.metadata["tenant"] == scenario["scenario_id"]
            assert snapshot.metadata["period_id"] == period["period_id"]
            assert snapshot.metadata["fresh_warehouse_read"] is False
            assert all(item.source_key == snapshot.resource for item in snapshot.observations)
            assert all(item.source_key == snapshot.resource for item in snapshot.evidence)
    failed = next(item for item in scenario["owner_examples"] if item["id"] == "week-01-day-06-source-unavailable")
    failed_sales = next(item for item in failed["resources"] if item["resource"] == next(
        descriptor["resource"] for descriptor in public["catalog"]
        if descriptor["title"] == "Northstar Executive Pulse"
    ))
    assert failed_sales["contract"]["source_status"] == "failed"
    assert failed_sales["error"] == "source unavailable during replay"


def test_smoke_is_the_next_week_known_family_not_a_novel_holdout(tmp_path):
    full = build_northstar(_write_seed_dir(tmp_path / "seed"))
    smoke = build_northstar(_write_seed_dir(tmp_path / "seed2"), smoke=True)
    assert len(smoke["public"]["periods"]) == 6
    assert {item["condition"] for item in smoke["private"]["periods"].values()} == {
        item["condition"] for item in full["private"]["periods"].values() if item["condition"] in {
            "day-01-no-change", "day-02-modest-movement", "day-03-isolated-channel",
            "day-04-corroborated-decline", "day-05-conflicting-sources", "day-06-source-unavailable",
        }
    }
    assert "novel" not in json.dumps(smoke).lower()


def test_private_outcomes_match_original_known_register(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"))
    original = build_historical_cases(load_spec(DEFAULT_SPEC))
    expected = {case.case_id: case.historical_outcome.value for case in original[6:]}
    assert {label["historical_case_id"]: label["outcome"]
            for label in scenario["private"]["periods"].values()} == expected
    assert [item["expected_outcome"] for item in scenario["owner_examples"]] == [
        case.historical_outcome.value for case in original[:6]
    ]


def test_future_source_metadata_does_not_disclose_scenario_family(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"))
    for period in scenario["public"]["periods"]:
        label = scenario["private"]["periods"][period["period_id"]]
        payload = json.dumps(period)
        assert label["historical_case_id"] not in payload
        assert label["condition"] not in payload
        assert period["period_id"].startswith("period-")

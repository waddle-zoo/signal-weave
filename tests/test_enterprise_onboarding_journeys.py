import copy
import json

from evaluations.bootstrap_scenarios import build_scenarios, dataset_digest, public_episode
from evaluations.enterprise_onboarding_journeys import SEED, journeys, protocol
from signalweave.models import ResourceDescriptor, ResourceSnapshot


def test_six_distinct_business_families_and_full_episode_denominator():
    scenarios = journeys()
    assert {s["private"]["family"] for s in scenarios} == {
        "retail", "saas", "support", "ops", "marketplace", "finance"}
    assert sum(len(s["public"]["catalog"]) for s in scenarios) == 144
    assert sum(len(s["public"]["periods"]) for s in scenarios) == 18
    assert protocol(scenarios)["primary_denominators"]["author_and_monitor_episodes"] == 48


def test_catalog_and_current_snapshots_remain_valid_and_identity_complete():
    for scenario in journeys():
        catalog = [ResourceDescriptor.model_validate(d) for d in scenario["public"]["catalog"]]
        refs = {f"{d.adapter}|{d.resource}" for d in catalog}
        assert len(refs) == len(catalog) == 24
        for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
            assert set(period["snapshots"]) == refs
            for ref, raw in period["snapshots"].items():
                snapshot = ResourceSnapshot.model_validate(raw)
                assert ref == f"{snapshot.adapter}|{snapshot.resource}"
                assert snapshot.contract.available_comparison_windows == ["previous_period"]


def test_overlay_preserves_old_labels_and_original_measurements():
    originals = build_scenarios(seed=SEED, split="holdout")
    for before, after in zip(originals, journeys(), strict=True):
        assert before["private"] == after["private"]
        assert before["public"]["owner_answers"] == after["public"]["owner_answers"]
        old_periods = [before["public"]["onboarding"], *before["public"]["periods"]]
        new_periods = [after["public"]["onboarding"], *after["public"]["periods"]]
        for old, new in zip(old_periods, new_periods, strict=True):
            for ref, snapshot in old["snapshots"].items():
                expected = copy.deepcopy(snapshot)
                expected["contract"]["available_comparison_windows"] = ["previous_period"]
                assert expected == new["snapshots"][ref]


def test_opening_view_does_not_include_labels_or_future_snapshots():
    for scenario in journeys():
        scenario["private"]["canary"] = "PRIVATE_LABEL_CANARY"
        episode = public_episode(scenario)
        encoded = json.dumps(episode)
        assert "PRIVATE_LABEL_CANARY" not in encoded
        for period in scenario["public"]["periods"]:
            assert period["period_id"] not in encoded
        assert "card" not in episode


def test_generation_and_protocol_are_reproducible():
    assert dataset_digest(journeys()) == dataset_digest(journeys())
    assert dataset_digest(journeys()) != dataset_digest(journeys(SEED + 1))
    assert protocol(journeys())["budget"]["jev_attempts"] == 144

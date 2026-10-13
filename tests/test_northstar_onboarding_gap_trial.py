from evaluations.northstar_onboarding_gap_trial import build_missing_materiality_case
from tests.test_northstar_growth_history_trial import _write_seed_dir


def test_missing_materiality_case_preserves_source_evidence_but_withholds_unearned_policy(tmp_path):
    scenario = build_missing_materiality_case(_write_seed_dir(tmp_path / "seed"))
    public = scenario["public"]

    assert scenario["scenario_id"] == "northstar-outfitters-unclear-materiality"
    assert "materiality" not in public["owner_answers"]
    assert "have not decided what size of movement counts as material" in public["brief"]
    assert len(scenario["owner_examples"]) == 6
    assert public["periods"] == []
    assert scenario["private"]["periods"] == {}
    assert scenario["private"]["onboarding_expectation"] == {
        "state": "needs_human_clarification",
        "unknown_owner_topics": ["materiality"],
    }
    assert public["onboarding"]["snapshots"]
    assert all(
        descriptor["contract"]["tenant_id"] == scenario["scenario_id"]
        for descriptor in public["catalog"]
    )
    assert all(
        snapshot["contract"]["tenant_id"] == scenario["scenario_id"]
        for snapshot in public["onboarding"]["snapshots"].values()
    )

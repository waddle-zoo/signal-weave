from pathlib import Path

from evaluations.enterprise_trial import load_config
from evaluations.northstar_corporation_trial import (
    DEFAULT_CORPORATION_CONFIG,
    _baseline_summary,
    build_agent_roster,
    build_corporation_fixture,
    load_corporation_config,
)


def test_northstar_corporation_roster_has_forty_distinct_expertise_roles():
    corporation = load_corporation_config(DEFAULT_CORPORATION_CONFIG)
    base = load_config(Path(DEFAULT_CORPORATION_CONFIG).parent / corporation["company"]["base_config"])
    roster = build_agent_roster(corporation, base)

    assert len(roster) == 40
    assert len({agent["id"] for agent in roster}) == 40
    assert {agent["group"] for agent in roster} == {
        "dashboard_curator",
        "domain_analyst",
        "enterprise_operations",
        "executives",
        "communications",
    }
    assert all(agent["expertise"] for agent in roster)


def test_northstar_corporation_fixture_covers_every_domain_and_four_workflows(tmp_path):
    corporation, fixture, roster = build_corporation_fixture(
        DEFAULT_CORPORATION_CONFIG,
        tmp_path / "fixture.json",
    )

    assert corporation["company"]["id"] == "northstar-outfitters"
    assert len(roster) == 40
    assert fixture["stats"]["tasks"] == 48
    assert {task["variant"] for task in fixture["tasks"]} == set(corporation["monitor_variants"])
    assert {
        task["brief"]["domain"] for task in fixture["tasks"]
    } == {domain["name"] for domain in load_config(Path(DEFAULT_CORPORATION_CONFIG).parent / "northstar-company.json")["domains"]}


def test_movement_only_baseline_exposes_false_alerts_and_missed_stale_escalations():
    rows = [
        {"baseline_action": "notify", "expected_outcome": "notify"},
        {"baseline_action": "notify", "expected_outcome": "ignore"},
        {"baseline_action": "notify", "expected_outcome": "investigate"},
        {"baseline_action": "ignore", "expected_outcome": "escalate"},
    ]

    summary = _baseline_summary(rows)

    assert summary["exact_outcomes"] == 1
    assert summary["false_positive_automatic_alerts"] == 2
    assert summary["missed_actionable_signals"] == 1

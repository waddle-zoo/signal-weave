from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime

import pytest

from evaluations import northstar_release_onboarding_trial as trial
from evaluations.bootstrap_agent_trial import canonical
from evaluations.bootstrap_scenarios import public_scenario
from signalweave.mcp_server import AGENT_PROFILE_TOOLS


@pytest.fixture(scope="module")
def scenario():
    return trial.build_trial_scenario()


def test_pilot_selects_diverse_existing_northstar_episodes(scenario):
    selected = trial.select_recurring_periods(scenario, cohort="pilot")
    variants = [scenario["private"]["periods"][p["period_id"]]["variant_id"]
                for p in selected]
    assert variants == [
        "ordinary-seasonal-softness",
        "day-03-isolated-channel",
        "day-04-corroborated-decline",
        "day-06-source-unavailable",
    ]
    assert len({p["period_id"] for p in selected}) == 4
    multistep = scenario["private"]["multistep"][selected[1]["period_id"]]
    assert multistep["expected_initial"] != multistep["expected_final"]
    assert multistep["diagnostic_facts"]


def test_all_fixture_timestamps_are_real_iso_dates(scenario):
    dated = [scenario["public"]["onboarding"], *scenario["public"]["periods"]]
    for period in dated:
        value = period["as_of"]
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None


def test_full_cohort_has_at_least_24_distinct_recurring_episodes(scenario):
    selected = trial.select_recurring_periods(scenario, cohort="full")
    assert len(selected) >= 24
    assert len({p["period_id"] for p in selected}) == len(selected)


def test_source_contracts_are_seed_grounded_without_fabricated_comparison_keys(scenario):
    audit = scenario["private"]["source_contract_fixture_audit"]
    assert audit["version"] == trial.SOURCE_CONTRACT_FIXTURE_VERSION
    assert audit["private_labels_used"] is False
    sales = next(item for item in audit["sources"]
                 if item["seed_file"] == "fct_sales_order_line.csv")
    assert sales["seed_columns"] == ["order_date", "channel", "net_sales"]
    assert sales["source_comparison_contract_keys"] == ["net-sales-change"]
    assert sales["required_comparison_keys"] == []
    assert sales["inspected_analytical_comparison_keys"] == []
    assert "settlement-status field" in sales["population"]
    assert "customer or order identifier" in sales["population"]
    assert "completed order lines" not in sales["population"]

    descriptor = next(item for item in scenario["public"]["catalog"]
                      if item["resource"] == sales["ref"].split("|", 1)[1])
    contract = descriptor["contract"]
    assert contract["population"] == sales["population"]
    assert contract["grain"] == sales["grain"]
    assert contract["required_comparison_keys"] == []
    assert [item["key"] for item in contract["comparison_contracts"]] == [
        "net-sales-change",
    ]
    for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
        snapshot = period["snapshots"][sales["ref"]]
        assert snapshot["contract"] == contract
        assert snapshot["analytical_comparisons"] == []


def test_report_first_probe_keeps_useful_facts_but_removes_only_missing_policies(scenario):
    changed, private = trial.build_report_first_scenario(scenario)
    assert "materiality" not in changed["public"]["owner_answers"]
    assert "routing" not in changed["public"]["owner_answers"]
    assert changed["public"]["owner_answers"]["metric_scope"]
    assert "Northstar local seed rows normalized through the existing shadow-trial helpers" not in changed["public"]["owner_answers"]["metric_scope"]
    assert "calendar month and sales channel" in changed["public"]["owner_answers"]["metric_scope"]
    assert len(changed["public"]["periods"]) == 1
    assert private["variant_id"] == "day-03-isolated-channel"
    assert changed["private"]["report_first_expected_unknown_topics"] == [
        "materiality", "routing",
    ]


def test_simulated_owner_followup_resolves_only_documented_gaps_without_touching_labels(scenario):
    changed = copy.deepcopy(scenario)
    old_labels = copy.deepcopy(changed["private"]["periods"])
    original_answers = copy.deepcopy(changed["public"]["owner_answers"])
    old_materiality = changed["public"]["owner_answers"]["materiality"]
    record = trial.apply_simulated_hil_followup(changed)
    assert record["mode"] == "simulated_human_followup"
    assert record["shared_with_both_arms"] is True
    actual_materiality = changed["public"]["owner_answers"]["materiality"]
    assert actual_materiality.startswith(old_materiality)
    assert "final investigate fallback is conditional" in actual_materiality
    assert "does not itself assign an outcome to every other material movement" in actual_materiality
    assert "owner explicitly adds these outcomes" in actual_materiality
    assert "increase of at least 10% goes to Analytics to investigate" in actual_materiality
    assert "decline from 10% up to but not including 15%" in actual_materiality
    assert "not an interpretation that the original fallback covers all such cases" in actual_materiality
    assert "no incident record or severity field" in actual_materiality
    assert "No approved incident definition or numeric severity threshold is available" in actual_materiality
    assert record["policy_order_preserved"] is True
    assert record["policy_semantics_expanded_by_explicit_hil_addendum"] is True
    assert record["new_numeric_thresholds"] == []
    assert len(record["addendum_outcome_rules"]) == 2
    assert changed["public"]["owner_answers"]["metric_scope"].startswith(
        "HIL clarification for this evaluation only: Northstar monthly sales"
    )
    assert "order_date, channel, and net_sales" in changed["public"]["owner_answers"]["metric_scope"]
    assert "do not establish unique customers or orders" in changed["public"]["owner_answers"]["metric_scope"]
    assert "completion or settlement status" in changed["public"]["owner_answers"]["metric_scope"]
    assert "settled net-sales amounts for completed order lines" not in changed["public"]["owner_answers"]["metric_scope"]
    assert "may corroborate or contextualize" in changed["public"]["owner_answers"]["metric_scope"]
    assert record["evidence_basis"]["checked_in_sales_columns"] == ["order_date", "channel", "net_sales"]
    assert record["evidence_basis"]["advertised_comparisons"][
        "company_mcp|" + next(
            item["resource"] for item in changed["public"]["catalog"]
            if item["title"] == "Northstar Executive Pulse"
        )
    ] == {
        "source_contract_keys": ["net-sales-change"],
        "required_keys": [],
        "inspected_analytical_keys": [],
    }
    assert changed["private"]["periods"] == old_labels
    assert changed["public"]["owner_answers"]["routing"] == original_answers["routing"]
    assert changed["public"]["owner_answers"]["data_gaps"] == original_answers["data_gaps"]
    assert old_materiality != actual_materiality


def test_report_first_score_rewards_useful_monthly_report_without_scoring_unknown_policy(scenario):
    public, _private = trial.build_report_first_scenario(scenario)
    period = public["public"]["periods"][0]
    facts = trial._northstar_numeric_facts(period["snapshots"])
    sales_ref = facts["net_sales_total_current"]["evidence_refs"][0]
    web_ref = facts["web_conversion_rate_change_pct"]["evidence_refs"][0]
    submission = {
        # Required transport schema only; policy outcome is deliberately not scored.
        "outcome": "investigate",
        "recipients": [],
        "evidence_refs": [sales_ref, web_ref],
        "numeric_claims": [
            {"fact": fact, "value": facts[fact]["value"],
             "unit": facts[fact]["unit"], "evidence_refs": facts[fact]["evidence_refs"]}
            for fact in ("net_sales_total_baseline", "net_sales_total_current",
                         "net_sales_total_change_pct", "online_net_sales_change_pct",
                         "web_conversion_rate_change_pct")
        ],
        "claims": [{
            "claim_type": "association",
            "evidence_refs": [sales_ref, web_ref],
            "statement": (
                "The online sales decline and higher web conversion co-occur in these "
                "snapshots; this does not establish a cause."
            ),
        }],
        "summary": (
            "Northstar monthly net sales fell from $400 to $340 (-15%) in this historical "
            "replay. The Executive Pulse shows the decline concentrated in Online (-35%), "
            "while web conversion rose 2%; that is a supported association, not proof of "
            "cause. Ask Growth Analytics to inspect checkout; alert materiality and owner "
            "remain unresolved."
        ),
    }
    scored = trial.score_report_first(
        submission, period=period, inspected_refs={sales_ref, web_ref},
        asked_topics={"materiality", "routing"},
        expected_unknown_topics={"materiality", "routing"},
    )
    assert scored["useful_report"] is True
    assert scored["numeric_accuracy"] is True
    assert scored["all_citations_inspected_and_in_period"] is True
    assert scored["scope_qualified"] is True
    assert scored["likely_driver_named"] is True
    assert scored["recipient_action_named"] is True
    assert scored["concise_10_to_80_words"] is True
    assert scored["owner_questions_only_for_missing_topics"] is True
    assert scored["outcome_not_scored_without_alert_policy"] is True
    assert "outcome_correct" not in scored


def test_report_first_score_rejects_uninspected_claims_and_new_alert_cutoffs(scenario):
    public, _private = trial.build_report_first_scenario(scenario)
    period = public["public"]["periods"][0]
    submission = {
        "outcome": "notify", "recipients": [], "evidence_refs": ["company_mcp|not-read"],
        "summary": (
            "Northstar monthly net sales changed in this historical replay. Alert at 12% "
            "and ask the owner to confirm the new threshold before routing the report."
        ),
    }
    scored = trial.score_report_first(
        submission, period=period, inspected_refs=set(), asked_topics=set(),
        expected_unknown_topics={"materiality", "routing"},
    )
    assert scored["useful_report"] is False
    assert scored["all_citations_inspected_and_in_period"] is False
    assert scored["no_threshold_invented"] is False
    assert scored["outcome_not_scored_without_alert_policy"] is True


def test_private_episode_labels_are_not_in_source_server_payload(scenario):
    public = public_scenario(scenario)
    serialized = canonical(public)
    private_labels = {
        str(value)
        for label in scenario["private"]["periods"].values()
        for value in (label.get("historical_case_id", ""), label.get("variant_id", ""))
        if value
    }
    assert private_labels
    assert not any(label in serialized for label in private_labels)


def test_default_agent_profile_is_exact_and_rejects_full_tools():
    trial.assert_agent_profile(set(AGENT_PROFILE_TOOLS))
    with pytest.raises(ValueError, match="exact default agent profile"):
        trial.assert_agent_profile(set(AGENT_PROFILE_TOOLS) | {"bootstrap_insight_card"})


def test_binary_gate_requires_both_parent_certified_fingerprints(monkeypatch, tmp_path):
    identity = {
        "source_sha256": trial.CERTIFIED_SOURCE_SHA256,
        "binary_sha256": trial.CERTIFIED_BINARY_SHA256,
        "version": "0.2.0rc2",
        "git_commit": "114614a",
        "dirty": True,
        "frozen": False,
    }
    monkeypatch.setattr(trial, "verify_binary", lambda _path: copy.deepcopy(identity))
    assert trial._verify_certified_binary(
        tmp_path / "candidate",
        certified_source_sha256=trial.CERTIFIED_SOURCE_SHA256,
        certified_binary_sha256=trial.CERTIFIED_BINARY_SHA256,
    ) == identity
    with pytest.raises(ValueError, match="source fingerprint"):
        trial._verify_certified_binary(
            tmp_path / "candidate", certified_source_sha256="a" * 64,
            certified_binary_sha256=trial.CERTIFIED_BINARY_SHA256,
        )
    wrong_version = {**identity, "version": "0.2.0rc1"}
    monkeypatch.setattr(trial, "verify_binary", lambda _path: wrong_version)
    with pytest.raises(ValueError, match="version"):
        trial._verify_certified_binary(
            tmp_path / "candidate", certified_source_sha256=trial.CERTIFIED_SOURCE_SHA256,
            certified_binary_sha256=trial.CERTIFIED_BINARY_SHA256,
        )


def test_parent_certificate_constants_match_current_candidate():
    assert trial.CERTIFIED_VERSION == "0.2.0rc2"
    assert trial.CERTIFIED_SOURCE_SHA256 == (
        "22498e8a38a937a29a4d06987ef297bd7a5e2fbe7f8a170d952c7f67a9c0f11c"
    )
    assert trial.CERTIFIED_BINARY_SHA256 == (
        "4dbc21d4bbf07a6979bc82f200aab2cc541c60c3f9f31e7b594a9eb87c2b1521"
    )


def test_run_pilot_delegates_all_model_roles_and_bounded_cases(
        monkeypatch, tmp_path, scenario):
    from evaluations import installed_workflow_trial

    identity = {
        "source_sha256": trial.CERTIFIED_SOURCE_SHA256,
        "binary_sha256": trial.CERTIFIED_BINARY_SHA256,
        "version": "0.2.0rc2",
        "git_commit": "114614a",
        "dirty": True,
        "frozen": False,
    }
    monkeypatch.setattr(trial, "verify_binary", lambda _path: copy.deepcopy(identity))
    monkeypatch.setattr(trial, "build_trial_scenario", lambda _seed: copy.deepcopy(scenario))
    captured = {}

    async def fake_run_trial(scenarios, **kwargs):
        captured["scenarios"] = scenarios
        captured["kwargs"] = kwargs
        return {"summary": {"completed": 4}, "protocol": {"binary_sha256": identity["binary_sha256"]}}

    monkeypatch.setattr(installed_workflow_trial, "run_trial", fake_run_trial)
    key_file = tmp_path / "private-key"
    key_file.write_text("test-only-not-a-credential", encoding="utf-8")
    report = asyncio.run(trial.run_pilot(
        binary=tmp_path / "binary", key_file=key_file,
        output=tmp_path / "pilot", episodes=4, simulate_hil_followup=True,
    ))
    preflight = json.loads((tmp_path / "pilot/release-preflight.json").read_text())
    assert preflight["parent_certificate"] == {
        "version": trial.CERTIFIED_VERSION,
        "source_sha256": trial.CERTIFIED_SOURCE_SHA256,
        "binary_sha256": trial.CERTIFIED_BINARY_SHA256,
    }
    assert preflight["certified_identity"] == identity

    kwargs = captured["kwargs"]
    assert kwargs["live"] is True
    assert kwargs["jev_budget"] == 40
    assert kwargs["stage_gate"] == 4
    assert kwargs["author_model"] == "gpt-6-luna"
    assert kwargs["author_effort"] == "xhigh"
    assert kwargs["recurring_agent_model"] == "gpt-6-luna"
    assert kwargs["recurring_agent_effort"] == "xhigh"
    assert kwargs["reviewer_model"] == "gpt-6-luna"
    assert kwargs["reviewer_effort"] == "xhigh"
    assert len(captured["scenarios"][0]["public"]["periods"]) == 4
    assert "HIL owner addendum for this evaluation only" in captured["scenarios"][0]["public"]["owner_answers"]["materiality"]
    assert report["summary"]["completed"] == 4

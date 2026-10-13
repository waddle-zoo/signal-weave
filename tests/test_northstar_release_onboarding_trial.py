from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime

import pytest

from evaluations import northstar_release_onboarding_trial as trial
from evaluations.bootstrap_agent_trial import canonical
from evaluations.bootstrap_scenarios import (
    agent_context,
    ask_owner,
    public_episode,
    public_scenario,
)
from evaluations.installed_workflow_trial import score_native
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
        snapshot_contract = copy.deepcopy(snapshot["contract"])
        source_status = snapshot_contract.pop("source_status")
        catalog_contract = copy.deepcopy(contract)
        catalog_contract.pop("source_status")
        assert snapshot_contract == catalog_contract
        assert source_status == ("failed" if snapshot.get("error") else contract["source_status"])
        assert snapshot["analytical_comparisons"] == []
        if snapshot.get("error"):
            assert snapshot["observations"] == []
            assert snapshot["evidence"] == []


def test_report_first_probe_keeps_useful_facts_but_removes_only_missing_policies(scenario):
    original_scope = scenario["public"]["owner_answers"]["metric_scope"]
    changed, private = trial.build_report_first_scenario(scenario)
    assert "materiality" not in changed["public"]["owner_answers"]
    assert "routing" not in changed["public"]["owner_answers"]
    assert changed["public"]["owner_answers"]["metric_scope"] == original_scope
    assert len(changed["public"]["periods"]) == 1
    assert private["variant_id"] == "day-03-isolated-channel"
    assert changed["private"]["report_first_expected_unknown_topics"] == [
        "materiality", "routing",
    ]


def test_simulated_owner_followup_answers_only_the_predeclared_unknown(scenario):
    changed = copy.deepcopy(scenario)
    old_private = copy.deepcopy(changed["private"])
    original_answers = copy.deepcopy(changed["public"]["owner_answers"])
    original_contracts = {
        ref: snapshot["contract"]
        for period in [changed["public"]["onboarding"], *changed["public"]["periods"]]
        for ref, snapshot in period["snapshots"].items()
    }
    record = trial.apply_simulated_hil_followup(changed)
    assert record["mode"] == "simulated_owner_followup_on_demand"
    assert record["shared_with_both_arms"] is True
    assert record["transport"] == "existing trial MCP facade"
    assert record["tool"] == "ask_owner"
    assert record["topic"] == "severe_incident_definition"
    assert record["response_status"] == "unknown"
    assert record["delivered_only_when_requested"] is True
    assert record["policy_changed"] is False
    assert record["source_contracts_changed"] is False
    assert record["outcome_labels_changed"] is False
    assert record["new_numeric_thresholds"] == []
    assert record["response"].startswith("Unknown.")
    assert "no approved definition or severity threshold" in record["response"]
    assert "support source reports backlog, not incident status or severity" in record["response"]
    assert "at least 10%" not in record["response"]
    assert changed["public"]["owner_answers"]["metric_scope"] == original_answers["metric_scope"]
    assert changed["public"]["owner_answers"]["materiality"] == original_answers["materiality"]
    assert changed["public"]["owner_answers"]["routing"] == original_answers["routing"]
    assert changed["public"]["owner_answers"]["data_gaps"] == original_answers["data_gaps"]
    assert "severe_incident_definition" in changed["public"]["owner_topics"]
    owner_reply = ask_owner(public_scenario(changed), "severe_incident_definition")
    assert owner_reply["known"] is True  # The owner response is known; the policy definition is not.
    assert owner_reply["answer"] == record["response"]
    assert changed["private"] == old_private
    assert {
        ref: snapshot["contract"]
        for period in [changed["public"]["onboarding"], *changed["public"]["periods"]]
        for ref, snapshot in period["snapshots"].items()
    } == original_contracts


def test_owner_policy_intervention_is_separate_and_preregistered(scenario):
    changed, registration = trial.build_policy_intervention_scenario()
    assert registration["protocol"] == trial.POLICY_INTERVENTION_PROTOCOL
    assert registration["cohort_label"] == (
        f"{trial.POLICY_INTERVENTION_PROTOCOL}: four-case row-backed fictional-company pilot; "
        "prior cohort invalid and excluded."
    )
    assert registration["legacy_oracle_used_for_selection_or_scoring"] is False
    assert registration["legacy_artifacts_preserved_as_invalid"] is True
    assert registration["selection_completed_before_future_values_exposed"] is True
    assert registration["synthetic_fixture_rows_generated"] is True
    assert "no real-business extract is claimed" in registration["sales_partition_rule"]
    assert len(changed["public"]["periods"]) == 4
    assert set(changed["private"]["periods"]) == set(trial.POLICY_INTERVENTION_CASES.values())
    assert registration["expected_outcomes_by_stratum"] == {
        "under_10_ignore": "ignore",
        "10_to_below_15_investigate": "investigate",
        "corroborated_15_plus_decline_notify": "notify",
        "primary_sales_source_unavailable": "insufficient_data",
    }
    assert all(item["sales_reconciliation"].get("status") != "checked"
               or item["sales_reconciliation"]["reconciled"]
               for item in registration["selected_strata"].values())
    unavailable = registration["selected_strata"]["primary_sales_source_unavailable"]
    assert unavailable["sales_reconciliation"] == {
        "status": "not_applicable", "reason": "Primary sales source unavailable."
    }


def test_sales_measurements_are_derived_from_reproducible_fictional_ledger_rows():
    changed, registration = trial.build_policy_intervention_scenario()
    scenario = changed
    ref = trial._intervention_source_ref(scenario, "superset|dashboard:1")
    for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
        snapshot = period["snapshots"][ref]
        assert "seed" not in json.dumps(snapshot).lower()
        assert "Superset dashboard" not in json.dumps(snapshot)
        if snapshot.get("error"):
            continue
        rows = snapshot["metadata"]["ledger_rows"]
        assert len({row["row_id"] for row in rows}) == len(rows)
        assert snapshot["metadata"]["ledger_sha256"] == trial.digest(rows)
        assert snapshot["source_url"].startswith("simulation-ledger://")
        assert "seed" not in json.dumps(snapshot).lower()
        assert "superset|dashboard" not in json.dumps(snapshot).lower()
        assert snapshot["contract"]["lineage"] == ["simulation-ledger://northstar/monthly-sales"]
        for comparison in snapshot["contract"]["comparison_contracts"]:
            assert "reporting_month" in comparison["definition"]
            assert "order_date" not in json.dumps(comparison)
            assert "local seed" not in json.dumps(comparison)
            assert comparison["query_refs"] == snapshot["contract"]["lineage"]
        for observation in snapshot["observations"]:
            selected = [row for row in rows if row["row_id"] in observation["attributes"]["ledger_row_ids"]]
            baseline = sum(row["net_sales"] for row in selected
                           if row["reporting_month"] == observation["attributes"]["baseline_period"])
            current = sum(row["net_sales"] for row in selected
                          if row["reporting_month"] == observation["dimensions"]["current_period"])
            assert baseline == observation["baseline"]
            assert current == observation["current"]
            assert "fixture_allocation" not in observation["attributes"]
    assert all(changed["private"]["periods"][item["period_id"]]["outcome"]
               == item["policy_outcome"]
               for item in registration["selected_strata"].values())
    assert registration["intervention"]["owner_answers"]["metric_scope"] == changed["public"]["owner_answers"]["metric_scope"]
    assert all(label["variant_id"].startswith("policy-intervention:")
               for label in changed["private"]["periods"].values())
    assert not any(item["title"] == "Northstar Checkout Incident Review"
                   for item in changed["public"]["catalog"])
    assert "No severe-incident exception applies" in changed["public"]["owner_answers"][
        "severe_incident_definition"]
    assert "Do not copy setup or approval questions" in changed["policy_intervention"][
        "recurring_questions_guidance"]
    assert changed["public"]["source_transport"]["kind"] == "simulated_bi_fixture"
    assert changed["public"]["source_transport"]["actual_superset"] is False
    for period in [changed["public"]["onboarding"], *changed["public"]["periods"]]:
        sales_ref = trial._intervention_source_ref(changed, "superset|dashboard:1")
        assert any(f"{item['adapter']}|{item['resource']}" == sales_ref
                   for item in changed["public"]["catalog"])
        snapshot = period["snapshots"][sales_ref]
        assert snapshot["analytical_comparisons"] == []
        assert snapshot["contract"]["required_comparison_keys"] == []
        if snapshot["contract"]["source_status"] == "healthy":
            assert trial.sales_partition_reconciliation(snapshot)["reconciled"] is True


def test_policy_intervention_mismatch_fails_closed_to_data_trust(scenario):
    changed, _registration = trial.build_policy_intervention_scenario()
    period = changed["public"]["periods"][0]
    sales_ref = trial._intervention_source_ref(changed, "superset|dashboard:1")
    sales = period["snapshots"][sales_ref]
    total = next(item for item in sales["observations"]
                 if item["subject_id"] == "revenue-total")
    total["current"] += 1

    classification = trial.classify_policy_intervention_period(changed, period)
    label = trial._policy_intervention_label(changed, period, classification)
    assert classification["stratum"] == "primary_sales_comparison_unreconciled"
    assert classification["outcome"] == label["outcome"] == "insufficient_data"
    assert label["recipients"] == ["data-trust"]
    assert label["required_numeric_facts"] == []


def test_native_agent_profile_score_uses_actual_evaluation_shape():
    card = {
        "id": "card-northstar-test", "version": 3, "status": "approved",
        "sources": [{"key": "sales", "adapter": "company_mcp", "resource": "sales-1"}],
    }
    destinations = [{"key": "leadership", "destination": "slack://simulation-leadership"}]
    label = {"outcome": "ignore", "recipients": [],
             "required_evidence_refs": ["company_mcp|sales-1"]}
    output = {
        "card": copy.deepcopy(card),
        "result": {
            "card_id": card["id"], "outcome": "ignore", "delivery_methods": [],
            "evidence": [{"source_key": "sales"}],
            "report": {"outcome": "ignore"},
        },
        "receipt": {
            "card_id": card["id"], "card_version": card["version"],
            "idempotency_key": "cohort/period-1", "outcome": "ignore",
            "delivery_method_keys": [], "delivery_enabled": False,
            "delivery_mode": "shadow", "status": "delivery_disabled",
        },
    }
    scored = score_native(
        output, card, label, destinations, expected_idempotency_key="cohort/period-1",
    )
    assert scored["exact"] is True
    assert scored["identity_valid"] is True
    assert scored["idempotency_valid"] is True
    assert scored["approved_card_digest_valid"] is True
    assert scored["outcome_correct"] is True
    assert scored["routes_correct"] is True
    assert "plan_unchanged" not in scored
    assert "legacy wrapper" not in scored["scope"]


def test_policy_owner_replies_only_from_predeclared_context(scenario):
    changed, _registration = trial.build_policy_intervention_scenario()
    episode = public_episode(changed)
    context = agent_context(episode)
    assert "owner_answers" not in context
    assert ask_owner(episode, "severe_incident_definition")["answer"] == changed[
        "public"]["owner_answers"]["severe_incident_definition"]
    unknown = ask_owner(episode, "unregistered_business_question")
    assert unknown["known"] is False
    assert unknown["answer"].startswith("Unknown.")


def test_policy_intervention_binary_gate_pins_current_source_and_build(monkeypatch, tmp_path):
    identity = {
        "source_sha256": trial.POLICY_INTERVENTION_SOURCE_SHA256,
        "binary_sha256": trial.POLICY_INTERVENTION_BINARY_SHA256,
        "version": "0.2.0rc2", "frozen": True, "dirty": True,
    }
    monkeypatch.setattr(trial, "source_fingerprint",
                        lambda _root: trial.POLICY_INTERVENTION_SOURCE_SHA256)
    monkeypatch.setattr(trial, "verify_binary", lambda _path: copy.deepcopy(identity))
    assert trial._verify_policy_intervention_binary(tmp_path / "dist") == identity
    monkeypatch.setattr(trial, "verify_binary", lambda _path: {**identity, "binary_sha256": "f" * 64})
    with pytest.raises(ValueError, match="[Nn]ative binary"):
        trial._verify_policy_intervention_binary(tmp_path / "dist")


def test_policy_intervention_runner_uses_live_paired_jev_budget_and_luna(
        monkeypatch, tmp_path):
    from evaluations import installed_workflow_trial

    frozen, registration = trial.build_policy_intervention_scenario()
    current_source = trial.source_fingerprint(trial.ROOT)
    identity = {"source_sha256": current_source,
                "binary_sha256": "a" * 64,
                "version": "0.2.0rc2", "frozen": True, "dirty": True}
    monkeypatch.setattr(trial, "POLICY_INTERVENTION_SOURCE_SHA256", current_source)
    monkeypatch.setattr(trial, "POLICY_INTERVENTION_BINARY_SHA256", identity["binary_sha256"])
    monkeypatch.setattr(trial, "verify_binary", lambda _path: copy.deepcopy(identity))
    monkeypatch.setattr(trial, "build_policy_intervention_scenario",
                        lambda _seed: (copy.deepcopy(frozen), copy.deepcopy(registration)))
    captured = {}

    async def fake_run_trial(scenarios, **kwargs):
        captured["scenario"] = scenarios[0]
        captured["kwargs"] = kwargs
        return {"status": "completed", "summary": {"onboarding_complete": 1,
                "completed": 4, "intended": 4}, "companies": [{}]}

    monkeypatch.setattr(installed_workflow_trial, "run_trial", fake_run_trial)
    key_file = tmp_path / "private-key"
    key_file.write_text("test-only-not-a-credential", encoding="utf-8")
    asyncio.run(trial.run_policy_intervention(
        binary=tmp_path / "dist", key_file=key_file, output=tmp_path / "intervention",
    ))
    kwargs = captured["kwargs"]
    assert kwargs["live"] is True and kwargs["stage_gate"] == 4
    assert kwargs["jev_budget"] == 20
    assert kwargs["author_model"] == kwargs["recurring_agent_model"] == "gpt-6-luna"
    assert kwargs["author_effort"] == kwargs["recurring_agent_effort"] == "xhigh"
    assert len(captured["scenario"]["public"]["periods"]) == 4
    preflight = json.loads((tmp_path / "intervention/release-preflight.json").read_text())
    assert preflight["protocol"] == trial.POLICY_INTERVENTION_PROTOCOL
    assert preflight["jev_budget"] == 20


def test_report_utility_excludes_censored_and_no_decision_pairs(monkeypatch):
    monkeypatch.setattr(trial, "score_final_report_utility", lambda *_args, **_kwargs: {
        "status": "valid", "valid": True, "score": 80,
    })
    rows = [{"period_id": str(index), "result": {"outcome": "ignore"},
             "baseline": {"completed": True}, "treatment": {"completed": True}}
            for index in range(3)]
    rows[0]["native_evaluation_error"] = "RuntimeError"
    rows[1]["baseline"]["completed"] = False
    report = {"companies": [{"periods": rows}]}
    scenario = {"public": {"periods": [{"period_id": str(index)} for index in range(3)]}}
    summary = trial.add_final_report_utility(report, scenario)
    assert summary["eligible_live_decision_pairs"] == 1
    assert summary["eligible_pair_utility_difference_mean"] == 0
    assert [row["final_report_utility"]["comparison_eligible"] for row in rows] == [False, False, True]


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


def test_final_report_utility_is_source_based_and_separates_invalid_reports(scenario):
    period = trial.select_recurring_periods(scenario, cohort="pilot")[1]
    facts = trial._northstar_numeric_facts(period["snapshots"])
    sales_ref = facts["net_sales_total_current"]["evidence_refs"][0]
    submission = {
        "outcome": "investigate", "recipients": ["analytics"],
        "evidence_refs": [sales_ref],
        "numeric_claims": [
            {"fact": fact, "value": facts[fact]["value"],
             "unit": facts[fact]["unit"], "evidence_refs": facts[fact]["evidence_refs"]}
            for fact in ("net_sales_total_baseline", "net_sales_total_current",
                         "net_sales_total_change_pct")
        ],
        "claims": [{"claim_type": "association", "evidence_refs": [sales_ref],
                    "statement": "Online sales and web conversion moved together; this is association, not cause."}],
        "summary": (
            "Northstar monthly net sales fell in this historical replay, with the online "
            "channel contributing to the movement. Ask Growth Analytics to investigate "
            "checkout; timing does not establish cause."
        ),
    }
    utility = trial.score_final_report_utility(
        submission, period=period, inspected_refs={sales_ref},
    )
    assert utility["status"] == "valid"
    assert utility["score"] == 100
    assert utility["evidence_fidelity"] is True
    assert utility["numeric_recall"] == 1
    assert trial.score_final_report_utility(
        {"outcome": "invented"}, period=period, inspected_refs={sales_ref},
    )["status"] == "invalid"
    assert trial.score_final_report_utility(
        None, period=period, inspected_refs={sales_ref},
    )["status"] == "missing"


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
        "9460d2e8e08a3e06de7309cf6c8d554b17043074d8fa9fe7fbdcee972c1298e2"
    )
    assert trial.CERTIFIED_BINARY_SHA256 == (
        "764323c36da96332bacc662807ad4c36ce03065619bcafd03289eed670ca4f83"
    )


def test_run_pilot_delegates_all_model_roles_and_bounded_cases(
        monkeypatch, tmp_path, scenario):
    from evaluations import installed_workflow_trial

    identity = {
        "source_sha256": trial.CERTIFIED_SOURCE_SHA256,
        "binary_sha256": trial.CERTIFIED_BINARY_SHA256,
        "version": "0.2.0rc2",
        "git_commit": "b8a0fc5b187ce0b49bff7842118f634a50daf5a6",
        "dirty": False,
        "frozen": True,
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
    assert captured["scenarios"][0]["public"]["owner_answers"]["severe_incident_definition"].startswith("Unknown.")
    assert kwargs["author_model"] == kwargs["recurring_agent_model"] == "gpt-6-luna"
    assert kwargs["author_effort"] == kwargs["recurring_agent_effort"] == "xhigh"
    assert report["summary"]["completed"] == 4

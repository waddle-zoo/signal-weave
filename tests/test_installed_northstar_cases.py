import json
from datetime import datetime
from pathlib import Path

from evaluations.bootstrap_scenarios import score_submission
from evaluations.installed_northstar_cases import (
    NORTHSTAR_POLICY_INTERVENTION,
    OWNER_FOLLOWUP_KNOWLEDGE,
    build_northstar,
    sales_partition_reconciliation,
)
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


def test_incident_followup_knowledge_is_independent_and_explicitly_unknown(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"))
    knowledge = scenario["owner_followup_knowledge"]["severe_incident_definition"]
    assert knowledge == OWNER_FOLLOWUP_KNOWLEDGE["severe_incident_definition"]
    assert knowledge["status"] == "unknown"
    assert knowledge["answer"].startswith("Unknown.")
    assert "severity threshold" in knowledge["answer"]
    assert "incident status or severity" in knowledge["answer"]
    assert "severe_incident_definition" not in scenario["public"]["owner_answers"]
    assert "severe_incident_definition" not in scenario["public"]["owner_topics"]
    assert "owner_followup_knowledge" not in scenario["private"]
    serialized_labels = json.dumps(scenario["private"])
    assert knowledge["answer"] not in serialized_labels


def test_policy_intervention_is_explicit_and_keeps_comparisons_english_only():
    answers = NORTHSTAR_POLICY_INTERVENTION["owner_answers"]
    assert "10%" in answers["materiality"] and "15%" in answers["materiality"]
    assert "at least two sales channels" in answers["materiality"]
    assert "Web Funnel conversion or Finance Daily revenue" in answers["materiality"]
    assert "All other material movements" in answers["materiality"]
    assert "no incident feed" in answers["severe_incident_definition"]
    assert "no row joins" in answers["source_scope"].lower()
    assert "Do not copy setup or approval questions" in NORTHSTAR_POLICY_INTERVENTION[
        "recurring_questions_guidance"]
    assert NORTHSTAR_POLICY_INTERVENTION["basis"].startswith(
        "Explicit simulation-coordinator-authored fictional owner policy,"
    )
    assert "user-supplied owner policy" not in NORTHSTAR_POLICY_INTERVENTION["basis"]
    assert "not derived from private outcome labels" in NORTHSTAR_POLICY_INTERVENTION["basis"]
    assert OWNER_FOLLOWUP_KNOWLEDGE["severe_incident_definition"]["status"] == "unknown"


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
            if snapshot.title == "Northstar Executive Pulse (Superset dashboard 1)":
                assert snapshot.metadata["source_transport"] == "simulated_bi_fixture"
                assert "not an actual Superset capture" in snapshot.metadata["source_capture"]
            assert all(item.source_key == snapshot.resource for item in snapshot.observations)
            assert all(item.source_key == snapshot.resource for item in snapshot.evidence)
    failed = next(item for item in scenario["owner_examples"] if item["id"] == "week-01-day-06-source-unavailable")
    failed_sales = next(item for item in failed["resources"] if item["resource"] == next(
        descriptor["resource"] for descriptor in public["catalog"]
        if descriptor["title"] == "Northstar Executive Pulse"
    ))
    assert failed_sales["contract"]["source_status"] == "failed"
    assert failed_sales["error"] == "source unavailable during replay"
    assert failed_sales["observations"] == []
    assert failed_sales["evidence"] == []


def test_simulated_sales_totals_reconcile_to_the_declared_channel_partition():
    partition_seed = Path(__file__).resolve().parents[1] / "evaluations" / "data" / "northstar-multistep-seed"
    scenario = build_northstar(partition_seed)
    sales_resource = next(item["resource"] for item in scenario["public"]["catalog"]
                          if item["title"] == "Northstar Executive Pulse")
    ref = f"company_mcp|{sales_resource}"
    for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
        snapshot = period["snapshots"][ref]
        if snapshot["contract"]["source_status"] == "healthy":
            check = sales_partition_reconciliation(snapshot)
            assert check["reconciled"] is True
            assert check["baseline_gap"] == 0
            assert check["current_gap"] == 0
        else:
            assert snapshot["error"] == "source unavailable during replay"
            assert snapshot["observations"] == []
            assert snapshot["evidence"] == []


def test_smoke_is_the_next_week_known_family_not_a_novel_holdout(tmp_path):
    full = build_northstar(_write_seed_dir(tmp_path / "seed"))
    smoke = build_northstar(_write_seed_dir(tmp_path / "seed2"), smoke=True)
    assert len(smoke["public"]["periods"]) == 6
    assert {item["condition"] for item in smoke["private"]["periods"].values()} == {
        item["condition"] for item in full["private"]["periods"].values() if item["variant_id"] in {
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


def test_installed_labels_score_actionable_abstentions_as_missed_work(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"), smoke=True)
    period_id, event = next(
        (period_id, label)
        for period_id, label in scenario["private"]["periods"].items()
        if label["outcome"] in {"notify", "investigate"}
    )
    assert event["condition"] == "event"
    missed_action = score_submission(
        scenario,
        period_id,
        {"outcome": "ignore", "recipients": [], "evidence_refs": [],
         "numeric_claims": [], "claims": []},
        inspected_refs=set(scenario["public"]["periods"][0]["snapshots"]),
        asked_owner_topics=event["required_owner_topics"],
    )
    assert missed_action["missed_event"] is True
    assert missed_action["exact"] is False


def test_installed_private_label_matches_generic_final_agent_scorer(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"), smoke=True)
    for label in scenario["private"]["periods"].values():
        assert label["condition"] in {"event", "data_gap", "quiet"}
        assert label["variant_id"]
        assert label["required_owner_topics"] == [
            "metric_scope", "materiality", "routing", "data_gaps"
        ]
        if label["outcome"] == "insufficient_data":
            assert "net_sales_total_delta" not in label["numeric_facts"]
        else:
            assert "net_sales_total_delta" in label["numeric_facts"]
        assert label["required_numeric_facts"] == (
            ["net_sales_total_baseline", "net_sales_total_current",
             "net_sales_total_change_pct"]
            if label["outcome"] in {"notify", "investigate"}
            and label["condition"] == "event"
            else []
        )


def test_northstar_numeric_contract_scores_source_supported_report_values(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"), smoke=True)
    period_id, label = next(
        (period_id, item)
        for period_id, item in scenario["private"]["periods"].items()
        if item["outcome"] == "notify"
    )
    claims = [
        {"fact": fact_id, "value": label["numeric_facts"][fact_id]["value"],
         "unit": label["numeric_facts"][fact_id]["unit"],
         "evidence_refs": label["numeric_facts"][fact_id]["evidence_refs"]}
        for fact_id in label["required_numeric_facts"]
    ]
    citations = sorted(set(label["required_evidence_refs"]) |
                       {ref for claim in claims for ref in claim["evidence_refs"]})
    result = score_submission(
        scenario,
        period_id,
        {"outcome": label["outcome"], "recipients": label["recipients"],
         "evidence_refs": citations, "numeric_claims": claims, "claims": []},
        inspected_refs=set(scenario["public"]["periods"][0]["snapshots"]),
        asked_owner_topics=label["required_owner_topics"],
    )
    assert result["valid_submission"] is True
    assert result["numeric_precision"] == 1
    assert result["numeric_recall"] == 1
    assert result["evidence_recall"] == 1
    assert result["exact"] is True


def test_future_source_metadata_does_not_disclose_scenario_family(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"))
    for period in scenario["public"]["periods"]:
        label = scenario["private"]["periods"][period["period_id"]]
        payload = json.dumps(period)
        assert label["historical_case_id"] not in payload
        assert label["condition"] not in payload
        assert period["period_id"].startswith("period-")

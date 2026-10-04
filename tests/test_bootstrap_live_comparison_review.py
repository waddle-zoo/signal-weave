import json

from evaluations.bootstrap_agent_trial import source_fingerprint
from evaluations.bootstrap_live_comparison_review import review_report
from evaluations.bootstrap_scenarios import build_scenarios, dataset_digest, score_submission


def _gold_submission(scenario, period_id):
    label = scenario["private"]["periods"][period_id]
    numeric_claims = [
        {"fact": fact, "value": value["value"], "unit": value["unit"],
         "evidence_refs": value["evidence_refs"]}
        for fact, value in label["numeric_facts"].items()
    ]
    claims = [{"claim_type": claim_type, "evidence_refs": label["required_evidence_refs"],
               "statement": "Mechanical review fixture."}
              for claim_type in label["required_claim_types"]]
    return {
        "outcome": label["outcome"], "recipients": label["recipients"],
        "evidence_refs": label["required_evidence_refs"], "numeric_claims": numeric_claims,
        "claims": claims, "summary": "Mechanical review fixture.",
    }


def test_review_recomputes_scores_and_requires_same_card(tmp_path):
    scenarios = build_scenarios(seed=20261001, split="holdout", connector_profile=True, catalog_noise=2)
    scenario = scenarios[0]
    rows = []
    periods = scenario["public"]["periods"]
    skip_period_id = next(
        period["period_id"] for period in periods
        if scenario["private"]["periods"][period["period_id"]]["outcome"] == "ignore"
    )
    for arm in ("luna_bi", "luna_signalweave_jev"):
        for period in periods:
            submission = _gold_submission(scenario, period["period_id"])
            score = score_submission(
                scenario, period["period_id"], submission,
                inspected_refs=period["private_refs"],
                asked_owner_topics=scenario["public"]["owner_topics"],
            ) if "private_refs" in period else score_submission(
                scenario, period["period_id"], submission,
                inspected_refs=[item["adapter"] + "|" + item["resource"] for item in scenario["public"]["catalog"]],
                asked_owner_topics=scenario["public"]["owner_topics"],
            )
            rows.append({
                "scenario_id": scenario["scenario_id"], "arm": arm, "phase": "monitoring",
                "period_id": period["period_id"], "status": "complete", "score": score,
                "submission": submission,
                "inspected_refs": [item["adapter"] + "|" + item["resource"] for item in scenario["public"]["catalog"]],
                "asked_owner_topics": scenario["public"]["owner_topics"],
                "shared_card_digest": "same-card", "card_id": "card-approved",
                "foreign_tools": [], "usage": {"jev": {"unknown_usage_attempts": 0},
                                                  "openai": {"unknown_usage_attempts": 0}},
                    "agent_wakeup_skipped": arm == "luna_signalweave_jev" and period["period_id"] == skip_period_id,
                    "agent_seconds": 0.0 if arm == "luna_signalweave_jev" and period["period_id"] == skip_period_id else (2.0 if arm == "luna_bi" else 1.0),
                    "tool_calls": 0 if arm == "luna_signalweave_jev" and period["period_id"] == skip_period_id else 1,
                "source_reads": 1,
                "raw_system_decision": ({"outcome": scenario["private"]["periods"][period["period_id"]]["outcome"],
                                          "recipients": scenario["private"]["periods"][period["period_id"]]["recipients"],
                                          "agent_changed_outcome": False} if arm == "luna_signalweave_jev" else None),
            })
    config = {
        "seed": 20261001, "split": "holdout", "connector_profile": True, "catalog_noise": 2,
        "selected_scenario_ids": [scenario["scenario_id"]], "selected_companies": 1,
        "dataset_digest": dataset_digest([scenario]), "push_gated": True,
        "source_fingerprint": source_fingerprint(),
    }
    report_path = tmp_path / "report.json"
    cards_path = tmp_path / scenario["scenario_id"] / "luna_signalweave_jev" / "cards.json"
    cards_path.parent.mkdir(parents=True)
    cards_path.write_text(json.dumps({"card-approved": {"status": "approved"}}))
    report_path.write_text(json.dumps({
        "config": config, "status": "complete", "comparative_eligible": True,
        "live_jev_observed": True, "budget_censored": False, "rows": rows,
    }))

    result = review_report(report_path)
    assert result["integrity_pass"]
    assert result["strong_superiority_claim_allowed"] is False
    assert result["gates"]["scores_recompute"]
    assert result["gates"]["same_card_monitoring"]
    assert result["gates"]["push_gate_contract"]
    assert result["value_signal"]["treatment_agent_wakeups"] < result["value_signal"]["baseline_agent_wakeups"]
    assert result["value_signal"]["treatment_active_warm_agent_seconds"] == 2.0
    assert result["value_signal"]["baseline_active_warm_agent_seconds"] == 6.0
    assert result["value_signal"]["treatment_active_warm_agent_seconds_per_wakeup"] == 1.0
    assert result["value_signal"]["baseline_active_warm_agent_seconds_per_wakeup"] == 2.0
    assert result["value_signal"]["active_warm_agent_seconds_per_wakeup_reduction_pct"] == 50.0
    assert result["value_signal"]["treatment_quality"]["evidence_recall_mean"] == 1.0
    assert result["value_signal"]["treatment_onboarding"]["runs"] == 0
    assert result["value_signal"]["baseline_onboarding"]["runs"] == 0
    assert result["value_signal"]["lifecycle_amortization"]["break_even_monitoring_runs"] == 0


def test_review_rejects_changed_score(tmp_path):
    scenarios = build_scenarios(seed=20261001, split="holdout")
    scenario = scenarios[0]
    period = scenario["public"]["periods"][0]
    submission = _gold_submission(scenario, period["period_id"])
    rows = []
    for arm in ("luna_bi", "luna_signalweave_jev"):
        score = score_submission(
            scenario, period["period_id"], submission,
            inspected_refs=[item["adapter"] + "|" + item["resource"] for item in scenario["public"]["catalog"]],
            asked_owner_topics=scenario["public"]["owner_topics"],
        )
        if arm == "luna_signalweave_jev":
            score["exact"] = False
        rows.append({"scenario_id": scenario["scenario_id"], "arm": arm, "phase": "monitoring",
                     "period_id": period["period_id"], "score": score, "submission": submission,
                     "inspected_refs": [item["adapter"] + "|" + item["resource"] for item in scenario["public"]["catalog"]],
                     "asked_owner_topics": scenario["public"]["owner_topics"], "shared_card_digest": "x",
                     "card_id": "card-approved", "foreign_tools": [], "usage": {"jev": {}, "openai": {}},
                     "agent_wakeup_skipped": False, "raw_system_decision": {"outcome": "ignore", "recipients": [], "agent_changed_outcome": False}})
    config = {"seed": 20261001, "split": "holdout", "selected_scenario_ids": [scenario["scenario_id"]],
              "selected_companies": 1, "dataset_digest": dataset_digest([scenario]),
              "source_fingerprint": source_fingerprint()}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"config": config, "status": "complete", "comparative_eligible": True,
                                       "live_jev_observed": True, "budget_censored": False, "rows": rows}))
    result = review_report(report_path)
    assert not result["integrity_pass"]
    assert result["gates"]["scores_recompute"] is False


def test_review_rejects_a_historical_source_fingerprint_by_default(tmp_path):
    scenarios = build_scenarios(seed=20261001, split="holdout")
    scenario = scenarios[0]
    period = scenario["public"]["periods"][0]
    submission = _gold_submission(scenario, period["period_id"])
    inspected_refs = [
        item["adapter"] + "|" + item["resource"]
        for item in scenario["public"]["catalog"]
    ]
    score = score_submission(
        scenario, period["period_id"], submission,
        inspected_refs=inspected_refs,
        asked_owner_topics=scenario["public"]["owner_topics"],
    )
    rows = []
    for arm in ("luna_bi", "luna_signalweave_jev"):
        rows.append({
            "scenario_id": scenario["scenario_id"], "arm": arm, "phase": "monitoring",
            "period_id": period["period_id"], "status": "complete", "score": score,
            "submission": submission, "inspected_refs": inspected_refs,
            "asked_owner_topics": scenario["public"]["owner_topics"],
            "shared_card_digest": "same-card", "card_id": "card-approved",
            "foreign_tools": [], "usage": {"jev": {"unknown_usage_attempts": 0},
                                              "openai": {"unknown_usage_attempts": 0}},
            "agent_wakeup_skipped": False, "agent_seconds": 1.0, "tool_calls": 1,
            "source_reads": 1,
            "raw_system_decision": ({
                "outcome": scenario["private"]["periods"][period["period_id"]]["outcome"],
                "recipients": scenario["private"]["periods"][period["period_id"]]["recipients"],
                "agent_changed_outcome": False,
            } if arm == "luna_signalweave_jev" else None),
        })
    config = {
        "seed": 20261001, "split": "holdout", "selected_scenario_ids": [scenario["scenario_id"]],
        "selected_companies": 1, "dataset_digest": dataset_digest([scenario]),
        "source_fingerprint": {"git_revision": "old", "sha256": {"fixture": "old"}},
    }
    report_path = tmp_path / "report.json"
    cards_path = tmp_path / scenario["scenario_id"] / "luna_signalweave_jev" / "cards.json"
    cards_path.parent.mkdir(parents=True)
    cards_path.write_text(json.dumps({"card-approved": {"status": "approved"}}))
    report_path.write_text(json.dumps({
        "config": config, "status": "complete", "comparative_eligible": True,
        "live_jev_observed": True, "budget_censored": False, "rows": rows,
    }))

    result = review_report(report_path)
    assert result["integrity_pass"] is False
    assert result["gates"]["source_fingerprint_present"] is True
    assert result["gates"]["source_fingerprint_matches_current"] is False
    historical = review_report(report_path, require_current_source=False)
    assert historical["integrity_pass"] is True
    assert historical["source_review"]["historical_only"] is True

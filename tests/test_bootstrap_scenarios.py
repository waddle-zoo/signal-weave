import copy
import json
from fractions import Fraction

import pytest

from evaluations.bootstrap_scenarios import (
    OWNER_TOPICS,
    _rate_facts,
    agent_context,
    ask_owner,
    build_scenarios,
    dataset_digest,
    public_episode,
    public_scenario,
    score_submission,
)
from signalweave.models import ResourceDescriptor, ResourceSnapshot


def select(family="retail", condition="event"):
    scenario = next(s for s in build_scenarios() if s["private"]["family"] == family)
    period_id, label = next((key, value) for key, value in scenario["private"]["periods"].items()
                            if value["condition"] == condition)
    return scenario, period_id, label


def perfect(label):
    # Used only to test the scorer. Never an agent input or benchmark submission.
    return {"outcome": label["outcome"], "recipients": label["recipients"].copy(),
            "evidence_refs": label["required_evidence_refs"].copy(),
            "numeric_claims": [{"fact": key, "value": value["value"], "unit": value["unit"],
                                "evidence_refs": value["evidence_refs"]}
                               for key, value in label["numeric_facts"].items()],
            "claims": [{"claim_type": kind, "evidence_refs": label["required_evidence_refs"]}
                       for kind in label["required_claim_types"]]}


def score(scenario, period_id, label, submission, **kwargs):
    return score_submission(scenario, period_id, submission,
                            inspected_refs=kwargs.get("inspected_refs", label["required_evidence_refs"]),
                            asked_owner_topics=kwargs.get("asked_owner_topics", list(OWNER_TOPICS)))


def test_counts_split_and_real_contracts():
    holdout, dev = build_scenarios(), build_scenarios(split="dev")
    assert len(holdout) == 6 and len(dev) == 2
    assert sum(len(s["public"]["periods"]) for s in holdout) == 18
    assert {s["private"]["family"] for s in holdout}.isdisjoint(s["private"]["family"] for s in dev)
    assert {s["public"]["company"] for s in holdout}.isdisjoint(s["public"]["company"] for s in dev)
    for scenario in holdout + dev:
        pub = public_scenario(scenario)
        assert len(pub["brief"]) < 240
        assert "card" not in pub
        assert {label["condition"] for label in scenario["private"]["periods"].values()} == {"quiet", "event", "quality"}
        descriptors = [ResourceDescriptor.model_validate(d) for d in pub["catalog"]]
        refs = {f"{d.adapter}|{d.resource}" for d in descriptors}
        assert len(refs) == 4
        assert pub["onboarding"]["period_id"] not in scenario["private"]["periods"]
        for period in [pub["onboarding"], *pub["periods"]]:
            assert set(period["snapshots"]) == refs
            for ref, value in period["snapshots"].items():
                snapshot = ResourceSnapshot.model_validate(value)
                assert ref == f"{snapshot.adapter}|{snapshot.resource}"
                assert snapshot.metadata["period_id"] == period["period_id"]
                assert snapshot.metadata["tenant"] == scenario["scenario_id"]


def test_public_allowlist_cannot_leak_private_fields_or_alias_private_state():
    scenario = build_scenarios()[0]
    scenario["private"]["secret_sentinel"] = "HIDDEN_SCORER_CANARY"
    scenario["unexpected_top_level"] = "HIDDEN_SCORER_CANARY"
    public = public_scenario(scenario)
    dumped = json.dumps(public)
    for key in ("HIDDEN_SCORER_CANARY", "required_numeric_facts", "required_evidence_refs",
                "required_claim_types", "numeric_facts", '"condition"', '"private"'):
        assert key not in dumped
    public["owner_answers"]["materiality"] = "overwrite"
    assert scenario["public"]["owner_answers"]["materiality"] != "overwrite"


def test_owner_is_policy_lookup_not_oracle():
    public = public_scenario(build_scenarios()[0])
    assert ask_owner(public, "materiality")["known"]
    assert "10%" in ask_owner(public, "materiality")["answer"]
    assert not ask_owner(public, "which outcome is right in the next period?")["known"]
    assert not ask_owner(public, "expected_outcome")["known"]
    assert "missing measurements" in ask_owner(public, "compute net sales for me")["answer"]


def test_episode_projection_is_independent_of_labels_and_future_measurements():
    scenario = build_scenarios()[0]
    original = public_episode(scenario)
    scenario["private"] = {"poison": "never read labels from a tool server"}
    for period in scenario["public"]["periods"]:
        period["snapshots"] = {"FUTURE_CANARY": "unavailable before this period"}
    assert public_episode(scenario) == original
    assert "FUTURE_CANARY" not in json.dumps(public_episode(scenario))
    opening = agent_context(original)
    assert not {"snapshots", "catalog", "owner_answers", "periods", "onboarding"} & opening.keys()
    assert opening["period_id"] == original["period"]["period_id"]


def test_current_episode_projection_contains_only_selected_period():
    scenario = build_scenarios()[0]
    selected = scenario["public"]["periods"][1]
    episode = public_episode(scenario, selected["period_id"])
    assert episode["period"] == selected
    assert "periods" not in episode and "onboarding" not in episode
    for other in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
        if other["period_id"] != selected["period_id"]:
            assert other["period_id"] not in json.dumps(episode)


def test_public_vocabulary_is_not_computed_from_future_oracle_facts(monkeypatch):
    import evaluations.bootstrap_scenarios as fixtures

    expected = [public_episode(s)["numeric_vocabulary"] for s in build_scenarios()]
    original = fixtures._payload

    def poisoned_labels(*args, **kwargs):
        payloads, _, _ = original(*args, **kwargs)
        return payloads, {"HIDDEN_FUTURE_FACT": {"value": 999}}, ["HIDDEN_FUTURE_FACT"]

    monkeypatch.setattr(fixtures, "_payload", poisoned_labels)
    actual = [public_episode(s)["numeric_vocabulary"] for s in build_scenarios()]
    assert actual == expected


def test_seed_reproducibility_opaque_identifiers_and_order():
    first, second = build_scenarios(seed=1), build_scenarios(seed=2)
    assert dataset_digest(first) == dataset_digest(build_scenarios(seed=1))
    assert dataset_digest(first) != dataset_digest(second)
    assert {s["scenario_id"] for s in first}.isdisjoint(s["scenario_id"] for s in second)
    orderings = set()
    for seed in range(12):
        for scenario in build_scenarios(seed):
            orderings.add(tuple(label["condition"] for label in scenario["private"]["periods"].values()))
            for entry in scenario["public"]["catalog"]:
                assert entry["resource"].startswith("resource-")
                assert len(entry["resource"]) == len("resource-") + 20
    assert len(orderings) == 6


def test_fixture_generation_rejects_unknown_split():
    with pytest.raises(ValueError):
        build_scenarios(split="training")


def test_all_correct_structured_answers_can_pass_scorer():
    for scenario in build_scenarios() + build_scenarios(split="dev"):
        for period_id, label in scenario["private"]["periods"].items():
            result = score(scenario, period_id, label, perfect(label))
            assert result["exact"], result
            assert not result["unsafe_route"]
            assert result["numeric_recall"] == 1


def test_retail_oracle_from_raw_gross_and_refund_rows_not_runtime_solver():
    for seed in range(10):
        scenario = build_scenarios(seed)[0]
        for period in scenario["public"]["periods"]:
            label = scenario["private"]["periods"][period["period_id"]]
            if label["condition"] == "quality":
                assert not label["numeric_facts"]
                continue
            ref = label["required_evidence_refs"][0]
            rows = period["snapshots"][ref]["evidence"][0]["values"]["rows"]
            baseline = sum(r["baseline_gross"] - r["baseline_refunds"] for r in rows)
            current = sum(r["current_gross"] - r["current_refunds"] for r in rows)
            assert label["numeric_facts"]["net_sales.delta"]["value"] == current - baseline
            assert label["outcome"] == ("notify" if current <= baseline * .9 else "ignore")


def test_rate_oracle_separate_within_and_mix_not_merely_sum():
    facts = _rate_facts([("a", 10, 100, 80, 200), ("b", 90, 100, 80, 100)])
    assert facts["within_effect"] == float(Fraction(2, 15))
    assert facts["mix_effect"] == float(Fraction(-1, 10))
    assert facts["delta"] == float(Fraction(1, 30))
    scenario, _, label = select("saas", "quiet")
    assert label["numeric_facts"]["retention.delta"]["value"] == -.175
    assert label["numeric_facts"]["retention.within_effect"]["value"] == 0
    assert label["outcome"] == "ignore"
    assert "mix" in scenario["public"]["brief"]


def test_support_denominator_and_marketplace_overlap_are_real_missingness():
    scenario, pid, label = select("support", "quality")
    period = next(p for p in scenario["public"]["periods"] if p["period_id"] == pid)
    snapshot = period["snapshots"][label["required_evidence_refs"][0]]
    assert snapshot["analytical_comparisons"][0]["current_total"]["denominator"] is None
    scenario, pid, label = select("marketplace", "quality")
    period = next(p for p in scenario["public"]["periods"] if p["period_id"] == pid)
    union = period["snapshots"][label["required_evidence_refs"][0]]["evidence"][0]["values"]
    tags = period["snapshots"][label["required_evidence_refs"][1]]["evidence"][0]["values"]
    assert union["current_distinct_buyers"] is None
    assert tags["disjoint"] is False
    assert not label["numeric_facts"]


def test_late_finance_feed_is_not_treated_as_cash_loss():
    scenario, pid, label = select("finance", "quality")
    period = next(p for p in scenario["public"]["periods"] if p["period_id"] == pid)
    snapshot = period["snapshots"][label["required_evidence_refs"][0]]
    assert snapshot["source_captured_at"] < snapshot["captured_at"]
    assert label["outcome"] == "insufficient_data"


@pytest.mark.parametrize("mutation,field", [
    (lambda s: s.update(outcome="ignore"), "outcome_correct"),
    (lambda s: s.update(recipients=[]), "recipients_correct"),
    (lambda s: s.update(evidence_refs=[]), "provenance_complete"),
    (lambda s: s.update(numeric_claims=[]), "numeric_recall"),
    (lambda s: s["numeric_claims"][0].update(value=999999), "numeric_precision"),
    (lambda s: s["numeric_claims"][0].update(unit="EUR"), "numeric_precision"),
    (lambda s: s["numeric_claims"][0].update(fact="made_up"), "numeric_precision"),
])
def test_wrong_or_missing_answers_never_earn_exact(mutation, field):
    scenario, pid, label = select()
    submission = perfect(label)
    mutation(submission)
    result = score(scenario, pid, label, submission)
    assert not result["exact"]
    assert result[field] != 1


@pytest.mark.parametrize("value", [True, "700", float("nan"), float("inf"), float("-inf")])
def test_numeric_schema_and_finite_values_fail_closed(value):
    scenario, pid, label = select()
    submission = perfect(label)
    submission["numeric_claims"][0]["value"] = value
    assert not score(scenario, pid, label, submission)["exact"]


def test_correct_numbers_without_actual_inspection_do_not_pass():
    scenario, pid, label = select()
    result = score(scenario, pid, label, perfect(label), inspected_refs=[])
    assert not result["exact"] and result["evidence_recall"] == 0
    assert result["numeric_precision"] == 0


def test_hallucinated_or_other_company_evidence_cannot_pass():
    scenario, pid, label = select()
    submission = perfect(label)
    alien = build_scenarios()[1]["private"]["periods"]
    alien_ref = next(iter(alien.values()))["required_evidence_refs"][0]
    submission["evidence_refs"].append(alien_ref)
    result = score(scenario, pid, label, submission,
                   inspected_refs=[*label["required_evidence_refs"], alien_ref])
    assert not result["exact"] and not result["provenance_complete"]


def test_duplicate_numeric_claim_cannot_inflate_recall_or_hide_contradiction():
    scenario, pid, label = select()
    submission = perfect(label)
    submission["numeric_claims"].append(copy.deepcopy(submission["numeric_claims"][0]))
    result = score(scenario, pid, label, submission)
    assert not result["exact"]
    assert result["numeric_precision"] < 1


def test_causal_claims_are_rejected_even_with_right_outcome_and_numbers():
    scenario, pid, label = select("ops")
    submission = perfect(label)
    submission["claims"].append({"claim_type": "causal", "evidence_refs": label["required_evidence_refs"],
                                 "statement": "The deployment caused the slowdown."})
    result = score(scenario, pid, label, submission)
    assert result["unsupported_claim_types"] == ["causal"] and not result["exact"]


def test_structured_scorer_does_not_claim_to_certify_free_text():
    scenario, pid, label = select("ops")
    submission = perfect(label)
    submission["claims"][0]["statement"] = "Deployment definitively caused this. Roll back immediately."
    result = score(scenario, pid, label, submission)
    # This must go to separate blind narrative review. No regex/LLM is smuggled
    # into the independent numeric scorer, and exact is never narrative accuracy.
    assert result["exact"]
    assert result["scoring_scope"] == "structured_fields_only"
    assert result["narrative_review_required"]


def test_ops_needs_association_explanation_not_just_route():
    scenario, pid, label = select("ops")
    submission = perfect(label)
    submission["claims"] = []
    result = score(scenario, pid, label, submission)
    assert result["errors"] == ["missing_explanation_claim_type"]


def test_recipients_are_exact_not_whichever_team_was_available():
    scenario, pid, label = select()
    submission = perfect(label)
    submission["recipients"].append("random-slack-team")
    result = score(scenario, pid, label, submission)
    assert result["wrong_recipient"] and result["unsafe_route"] and not result["exact"]


def test_safety_metrics_distinguish_noise_misses_and_missingness():
    for condition, actual, metric in [("quiet", "notify", "false_alert"),
                                       ("event", "ignore", "missed_event"),
                                       ("quality", "ignore", "unsafe_suppression")]:
        scenario, pid, label = select(condition=condition)
        submission = perfect(label)
        submission["outcome"] = actual
        result = score(scenario, pid, label, submission)
        assert result[metric] and not result["exact"]


def test_public_glossary_and_destinations_do_not_require_redundant_questions():
    for scenario in build_scenarios() + build_scenarios(split="dev"):
        opening = agent_context(public_episode(scenario))
        assert opening["destinations"] == scenario["public"]["destinations"]
        assert {d["label"] for d in opening["destinations"]} == {"Business owner", "Data operations"}
        for pid, label in scenario["private"]["periods"].items():
            assert label["required_owner_topics"] == ["materiality"]
            assert score(scenario, pid, label, perfect(label), asked_owner_topics=["materiality"])["exact"]
            result = score(scenario, pid, label, perfect(label), asked_owner_topics=["routing"])
            assert not result["owner_policy_complete"] and not result["exact"]


@pytest.mark.parametrize("submission", [{}, None, {"outcome": "delete_database"},
                                         {"outcome": "notify", "recipients": "team"}])
def test_invalid_submission_is_a_scored_failure_not_a_runner_crash(submission):
    scenario, pid, label = select()
    result = score(scenario, pid, label, submission)
    assert not result["valid_submission"] and not result["exact"]


def test_wrong_period_is_a_harness_error_not_silently_scored():
    scenario, _, label = select()
    with pytest.raises(KeyError):
        score(scenario, "unknown-period", label, perfect(label))

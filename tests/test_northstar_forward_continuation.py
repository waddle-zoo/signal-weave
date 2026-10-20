"""Research admission controls; these are not business outcome cases."""
import json

import pytest

from evaluations import northstar_forward_continuation as trial


def record(**updates):
    value = {"process_complete": True, "protocol_ok": True,
             "usage": {"known": True, "usage": {"input_tokens": 1, "uncached_input_tokens": 1}}}
    value.update(updates)
    return value


def test_completed_pair_is_bounded_and_distinct_from_old_cohort():
    assert trial.CUTOFF == "2026-09-18"
    assert trial.ORDER == ("signalweave", "baseline")
    assert trial.LIMITS["actors"] == 2 and trial.LIMITS["jev_requests"] == 1
    assert trial.PROTOCOL != trial.rolling.PROTOCOL


def test_same_business_request_without_hidden_policy_or_answer():
    b_instructions, baseline = trial.task("baseline", "saved-card")
    t_instructions, treatment = trial.task("signalweave", "saved-card")
    assert {k: treatment[k] for k in baseline} == baseline
    assert t_instructions.startswith(b_instructions)
    assert "SignalWeave" not in b_instructions and "publication" not in b_instructions
    assert treatment["card_id"] == "saved-card"
    assert trial.PROTOCOL in treatment["idempotency_key"]
    assert "ordered_guidance" not in t_instructions and "0.79" not in t_instructions


def test_order_claim_and_completion_stop_before_another_actor(tmp_path):
    assert trial.prior_results(tmp_path, "signalweave") == []
    with pytest.raises(ValueError, match="Order"):
        trial.prior_results(tmp_path, "baseline")
    (tmp_path/"signalweave.claimed").write_text("one attempt")
    with pytest.raises(ValueError, match="Unreported"):
        trial.prior_results(tmp_path, "signalweave")
    (tmp_path/"signalweave.json").write_text(json.dumps(record()))
    assert len(trial.prior_results(tmp_path, "baseline")) == 1
    with pytest.raises(ValueError, match="Order"):
        trial.prior_results(tmp_path, "signalweave")
    (tmp_path/"baseline.json").write_text(json.dumps(record()))
    with pytest.raises(ValueError, match="Order"):
        trial.prior_results(tmp_path, "baseline")


@pytest.mark.parametrize("report", [record(process_complete=False), record(protocol_ok=False),
    record(usage={"known": False}),
    record(usage={"known": True, "usage": {"input_tokens": 3_000_000, "uncached_input_tokens": 1}}),
    record(usage={"known": True, "usage": {"input_tokens": 1, "uncached_input_tokens": 250_000}})])
def test_failure_or_known_usage_ceiling_is_not_a_budget_reset(tmp_path, report):
    (tmp_path/"signalweave.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="admission stopped"):
        trial.prior_results(tmp_path, "baseline")

"""A forward company journey retains failures and their real usage, not a rescore."""
from __future__ import annotations

import copy

import pytest

from evaluations import northstar_enterprise_journey as journey


@pytest.fixture
def prior_pair(tmp_path):
    study = {
        "protocol": journey.PROTOCOL, "reporting_period_ends": list(journey.PERIOD_ENDS),
        "warehouse": {"sha": "same-source"}, "source_revision": "source-revision",
        "source_environment": {"python": "same"}, "binary": {"sha": "same-native"},
    }
    journey.save(tmp_path / "study.json", study)
    for arm in journey.ORDER:
        journey.save(tmp_path / f"{arm}.json", {
            "protocol": journey.PROTOCOL, "arm": arm, "process_complete": arm == "baseline",
            "inputs_unchanged": True, "seconds": 300, "provider_requests": 0,
            "usage": {"known": True, "usage": {"input_tokens": 1000, "uncached_input_tokens": 200}},
        })
    return tmp_path


def test_forward_ledger_keeps_both_terminal_identities_and_costs(prior_pair):
    ledger = journey._prior_attempts(prior_pair)
    assert set(ledger["terminal_sha256"]) == set(journey.ORDER)
    assert ledger["usage"]["signalweave"]["usage"]["input_tokens"] == 1000
    assert ledger["provider_requests"] == {"baseline": 0, "signalweave": 0}
    assert "not a replacement or rescore" in ledger["limitation"]
    assert ledger["source_identity"]["warehouse"] == {"sha": "same-source"}
    original = copy.deepcopy(ledger)
    record = journey.setup.shared.read(prior_pair / "signalweave.json")
    record["seconds"] = 301
    journey.save(prior_pair / "signalweave.json", record)
    assert journey._prior_attempts(prior_pair) != original


@pytest.mark.parametrize("field,value,match", [
    ("usage", {"known": False}, "usage is unknown"),
    ("inputs_unchanged", False, "changed frozen source"),
    ("arm", "baseline", "expected arm"),
])
def test_forward_ledger_rejects_unknown_cost_changed_inputs_or_mislabeled_record(prior_pair, field, value, match):
    record = journey.setup.shared.read(prior_pair / "signalweave.json")
    record[field] = value
    journey.save(prior_pair / "signalweave.json", record)
    with pytest.raises(ValueError, match=match):
        journey._prior_attempts(prior_pair)


def test_forward_ledger_rejects_different_periods(prior_pair):
    study = journey.setup.shared.read(prior_pair / "study.json")
    study["reporting_period_ends"] = [journey.PERIOD_ENDS[0]]
    journey.save(prior_pair / "study.json", study)
    with pytest.raises(ValueError, match="same company's"):
        journey._prior_attempts(prior_pair)


async def test_forward_options_fail_before_any_install(tmp_path, monkeypatch):
    monkeypatch.setattr(journey, "_require_source_docker_context", lambda: None)
    for treatment_only, prior_study in ((True, None), (False, tmp_path)):
        with pytest.raises(ValueError, match="together"):
            await journey.prepare(tmp_path, tmp_path, tmp_path, tmp_path, tmp_path, tmp_path,
                                  treatment_only=treatment_only, prior_study=prior_study)


def test_forward_order_admits_one_fresh_treatment_but_no_baseline_or_retry(tmp_path):
    study = {"order": ["signalweave"]}
    journey._check_actor_order(study, tmp_path, "signalweave")
    with pytest.raises(ValueError, match="Unknown arm"):
        journey._check_actor_order(study, tmp_path, "baseline")
    (tmp_path / "signalweave.claimed").write_text("one attempt")
    with pytest.raises(ValueError, match="unreported"):
        journey._check_actor_order(study, tmp_path, "signalweave")
    journey.save(tmp_path / "signalweave.json", {"process_complete": False})
    with pytest.raises(ValueError, match="One attempt"):
        journey._check_actor_order(study, tmp_path, "signalweave")


def test_normal_pair_still_requires_accounted_baseline_first(tmp_path):
    study = {"order": list(journey.ORDER)}
    with pytest.raises(ValueError, match="One attempt"):
        journey._check_actor_order(study, tmp_path, "signalweave")
    journey._check_actor_order(study, tmp_path, "baseline")
    baseline = {"usage": {"known": False}, "inputs_unchanged": True}
    journey.save(tmp_path / "baseline.json", baseline)
    with pytest.raises(ValueError, match="usage is unknown"):
        journey._check_actor_order(study, tmp_path, "signalweave")
    baseline["usage"] = {"known": True, "usage": {"input_tokens": 100, "uncached_input_tokens": 50}}
    journey.save(tmp_path / "baseline.json", baseline)
    journey._check_actor_order(study, tmp_path, "signalweave")

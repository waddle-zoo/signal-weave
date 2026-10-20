"""Prospective method controls, not enterprise accuracy or workflow proof."""
from evaluations import northstar_rolling_analysis as trial


def test_prespecified_order_and_whole_trajectory_budget():
    assert trial.CUTOFFS == ("2026-09-05", "2026-09-12", "2026-09-19")
    assert trial.ORDER == tuple(f"{d}-{a}" for d in trial.CUTOFFS for a in ("baseline", "signalweave"))
    assert len(trial.ORDER) == trial.LIMITS["actors"] == 6
    assert trial.LIMITS["jev_requests"] == 3


def test_same_owner_question_with_no_unavailable_product_work_for_baseline():
    baseline, b = trial.task("baseline", trial.CUTOFFS[0], "actual-card")
    treatment, t = trial.task("signalweave", trial.CUTOFFS[0], "actual-card")
    assert {k: t[k] for k in b} == b
    assert "SignalWeave" not in baseline and "publication" not in baseline
    assert "first checkpoint" in treatment and "review and approve only if" in treatment
    assert t["card_id"] == "actual-card"
    assert trial.CUTOFFS[0] in t["idempotency_key"]


def test_delegation_is_simulated_expert_authority_not_invented_human_review():
    assert "delegated BI/data expert" in trial.OWNER
    assert "not a claim that any human" in trial.OWNER
    assert "D-6 through D with D-370 through D-364" in trial.OWNER
    assert "currently retained warehouse" in trial.OWNER
    assert "10%" in trial.OWNER and "No sending or scheduling" in trial.OWNER
    assert "271,329" not in trial.OWNER and "7.21%" not in trial.OWNER

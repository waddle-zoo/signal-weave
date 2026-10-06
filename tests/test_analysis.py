from signalweave.analysis import evidence_statements
from signalweave.models import Observation


def observation(**overrides):
    return Observation(
        source_key="metrics",
        subject_id="orders",
        subject_label="Orders",
        metric="orders",
        **overrides,
    )


def test_current_value_without_baseline_is_not_misreported_as_missing():
    statement = evidence_statements([
        observation(current=100, baseline=None, change_pct=None),
    ])[0]
    assert statement == "Orders is currently 100. No comparable baseline is available."


def test_equal_current_and_baseline_is_not_described_as_a_decline():
    statement = evidence_statements([
        observation(current=100, baseline=100, change_pct=0),
    ])[0]
    assert statement == "Orders is unchanged versus baseline (0.0%)."


def test_zero_baseline_preserves_values_and_says_relative_change_is_unavailable():
    statement = evidence_statements([
        observation(current=20, baseline=0, change_pct=None, unit="users"),
    ])[0]
    assert statement == (
        "Orders is currently 20 users. The baseline is 0 users, but relative change is unavailable."
    )


def test_missing_current_value_is_described_as_missing_without_claiming_a_change():
    statement = evidence_statements([
        observation(current=None, baseline=100, change_pct=None),
    ])[0]
    assert statement == "No current value is available for Orders."

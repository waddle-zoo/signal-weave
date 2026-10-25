"""Scalar semantic exports must not require an invented decomposition."""

import pytest

from signalweave.models import (
    Observation,
    ResourceContract,
    ResourceSnapshot,
    SourceComparisonContract,
)
from signalweave.reporting import build_investigation_report
from tests.test_reporting import card, comparison, result


def scalar_snapshot():
    return ResourceSnapshot(
        source_key="sales", adapter="test", resource="query:sales", title="Monthly activity",
        observations=[Observation(source_key="sales", metric="volume", unit="count", current=80, baseline=100)],
        contract=ResourceContract(comparison_contracts=[SourceComparisonContract(
            key="volume-by-channel", metric="volume", definition="Completed activity",
            population="Eligible population", unit="count", comparison_window="previous_period",
            coverage="complete", comparable=True, query_refs=["semantic:activity:r3"],
        )]),
    )


def test_complete_scalar_contract_preserves_policy_without_fabricated_numeric_analysis():
    report = build_investigation_report(card(), result(), [scalar_snapshot()])
    assert report.status == "partial"  # source measurements, not engine decomposition
    assert not report.blockers
    assert report.outcome == "notify"
    assert not report.numeric_claims and not report.provenance
    assert any(item.required and item.status == "satisfied" and "scalar" in item.detail.lower()
               for item in report.coverage)


@pytest.mark.parametrize("fault", [
    "partial", "unknown-coverage", "not-comparable", "wrong-window", "duplicate", "wrong-key",
    "wrong-identity", "unauthorized", "source-error", "unhealthy", "duplicate-snapshot", "empty",
])
def test_invalid_scalar_contract_cannot_clear_required_report_coverage(fault):
    snapshot = scalar_snapshot()
    contract = snapshot.contract.comparison_contracts[0]
    if fault == "partial":
        contract.coverage = "partial"
    elif fault == "unknown-coverage":
        contract.coverage = "unknown"
    elif fault == "not-comparable":
        contract.comparable = False
    elif fault == "wrong-window":
        contract.comparison_window = "previous_year"
    elif fault == "duplicate":
        snapshot.contract.comparison_contracts.append(contract.model_copy(deep=True))
    elif fault == "wrong-key":
        contract.key = "different-measure"
    elif fault == "wrong-identity":
        snapshot.resource = "query:another-population"
    elif fault == "unauthorized":
        snapshot.contract.authorized = False
    elif fault == "source-error":
        snapshot.error = "Query incomplete"
    elif fault == "unhealthy":
        snapshot.contract.source_status = "stale"
    elif fault == "empty":
        snapshot.observations = []
    resources = [snapshot, snapshot.model_copy(deep=True)] if fault == "duplicate-snapshot" else [snapshot]
    report = build_investigation_report(card(), result(), resources)
    assert report.status == "blocked"
    assert report.blockers


def test_scalar_contract_cannot_substitute_for_a_returned_decomposition():
    snapshot = scalar_snapshot()
    snapshot.analytical_comparisons = [comparison()]
    report = build_investigation_report(card(), result(), [snapshot])
    assert report.status == "blocked"
    assert any(item.code == "required_analysis_missing" for item in report.blockers)


def test_scalar_contract_cannot_rescue_an_invalid_returned_analysis():
    from tests.test_reporting import complete_analysis

    snapshot = scalar_snapshot()
    snapshot.analytical_comparisons = [comparison()]
    invalid = complete_analysis().model_copy(update={"current": 999999})
    report = build_investigation_report(card(), result(invalid), [snapshot])
    assert report.status == "blocked"
    assert report.blockers and not report.numeric_claims


def test_scalar_contract_does_not_satisfy_an_explicit_decomposition_numeric_condition():
    from signalweave.numeric_conditions import NumericCondition

    configured = card()
    configured.numeric_conditions = [NumericCondition(
        text="Contribution from each channel", source_key="sales", comparison_key="volume-by-channel",
        measurement="contribution", unit="count", comparator="<=", threshold=-10,
    )]
    report = build_investigation_report(configured, result(), [scalar_snapshot()])
    assert report.status == "blocked"
    assert any(issue.code == "required_numeric_condition_unavailable" for issue in report.blockers)


@pytest.mark.asyncio
@pytest.mark.parametrize("response_mode", ["compact", "full"])
@pytest.mark.parametrize("over_age", [False, True])
async def test_normal_mcp_scalar_onboarding_returns_a_usable_report(tmp_path, response_mode, over_age):
    from signalweave.mcp_server import create_mcp
    from tests.test_onboarding import OnboardingJevDouble, make_server
    from tests.test_selected_scalar_comparison_binding import ScalarSource, onboard

    source = ScalarSource()
    original_inspect = source.inspect

    async def inspect(request):
        from datetime import datetime, timedelta, timezone

        snapshot = await original_inspect(request)
        if over_age:
            snapshot.source_captured_at = datetime.now(timezone.utc) - timedelta(days=7)
        return snapshot

    source.inspect = inspect
    server = create_mcp(make_server(tmp_path, catalog=source, judger=OnboardingJevDouble())._test_runtime,
                        profile="agent")
    created = await onboard(server, {"ref": "measurements|accounts", "key": "accounts",
                                     "required_comparison_keys": ["accounts-change"]})
    card_id = created["card"]["id"]
    await server.call_tool("review_insight_card", {"card_id": card_id})
    await server.call_tool("approve_insight_card", {
        "card_id": card_id, "use_current_source_selection_review": True,
        "source_selection_reason": "Synthetic owner confirms the scalar comparison and policy.",
        "source_scope_confirmations": {"measurements|accounts": "Reviewed account population"},
    })
    _, packet = await server.call_tool("evaluate_insight_card", {
        "card_id": card_id, "idempotency_key": "scalar-report:" + response_mode,
        "response_mode": response_mode,
    })
    assert packet["result"]["outcome"] == ("insufficient_data" if over_age else "notify")
    assert packet["result"]["report"]["status"] == ("blocked" if over_age else "partial")
    assert bool(packet["result"]["report"]["blockers"]) is over_age
    assert packet["receipt"]["delivery_enabled"] is False

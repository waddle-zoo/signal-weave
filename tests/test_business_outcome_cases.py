import copy
import json
from datetime import timedelta
from fractions import Fraction

from evaluations.business_outcome_cases import _fresh_periods, cases
from evaluations.first_report_cases import cases as first_report_cases
from signalweave.models import ResourceDescriptor, ResourceSnapshot, SourceRef


def _periods():
    return [(company, period) for company in cases() for period in company["periods"]]


def _analysis(period):
    return period["oracle"]["analyses"][0] if period["oracle"]["analyses"] else None


def _selected_snapshot(period):
    source_key = _analysis(period)["source_key"]
    return next(resource for resource in period["resources"] if resource["source_key"] == source_key)


def test_shape_is_three_companies_and_twelve_fresh_pairs():
    companies = cases()
    assert {company["id"] for company in companies} == {"northstar-cart", "harbor-help", "redwood-fulfillment"}
    assert len(_periods()) == 12
    assert {period["id"] for _, period in _periods()} == {"p05", "p06", "p07", "p08"}
    assert {period["split"] for _, period in _periods()} == {"holdout"}
    assert all(period["role"] == "fresh" for periods in _fresh_periods().values() for period in periods)
    assert all(len(period["resources"]) == 2 for _, period in _periods())


def test_fresh_clock_starts_after_existing_periods():
    original = {company["id"]: company for company in first_report_cases()}
    for company in cases():
        old_p03 = ResourceSnapshot.model_validate(original[company["id"]]["periods"][-1]["resources"][0]).analytical_comparisons[0]
        new_p05 = ResourceSnapshot.model_validate(company["periods"][0]["resources"][0]).analytical_comparisons[0]
        assert new_p05.baseline_start > old_p03.current_end


def test_public_company_reuses_approved_directory_policy_and_destinations():
    approved = {company["id"]: company for company in first_report_cases()}
    for company in cases():
        original = approved[company["id"]]
        assert company["descriptors"] == original["descriptors"]
        assert company["sources"] == original["sources"]
        assert company["owner_policy"] == original["owner_policy"]
        assert company["destinations"] == original["destinations"]


def test_contracts_and_snapshots_are_real_and_as_of_aligned():
    for company in cases():
        refs = set()
        for payload in company["descriptors"]:
            descriptor = ResourceDescriptor.model_validate(payload)
            refs.add(f"{descriptor.adapter}|{descriptor.resource}")
            assert descriptor.contract.available_comparison_windows == ["previous_period"]
            assert descriptor.contract.required_comparison_keys
        for payload in company["sources"]:
            source = SourceRef.model_validate(payload)
            assert source.required is True
            assert source.required_comparison_keys
        for period in company["periods"]:
            assert {f"{item['adapter']}|{item['resource']}" for item in period["resources"]} == refs
            for payload in period["resources"]:
                snapshot = ResourceSnapshot.model_validate(payload)
                assert snapshot.captured_at - snapshot.source_captured_at == timedelta(hours=1)
                assert snapshot.contract.tenant_id == "synthetic-first-report"
                assert snapshot.metadata["period_id"] == period["id"]
                assert snapshot.metadata["as_of"] == period["as_of"]
                assert snapshot.analytical_comparisons[0].key in snapshot.contract.required_comparison_keys


def test_snapshots_do_not_expose_outcomes_or_source_answer_labels():
    for _, period in _periods():
        for resource in period["resources"]:
            encoded = json.dumps(resource)
            for forbidden in ("outcome", "recipient", "correct", "selected", "primary", "distractor"):
                assert forbidden not in encoded


def test_independent_oracle_matches_snapshot_math():
    for _, period in _periods():
        if period["oracle"]["status"] == "blocked" and not period["oracle"]["analyses"]:
            assert period["oracle"]["outcome"] == "insufficient_data"
            continue
        analysis = _analysis(period)
        comparison = ResourceSnapshot.model_validate(_selected_snapshot(period)).analytical_comparisons[0]
        assert analysis["comparison_key"] == comparison.key
        assert analysis["query_refs"] == comparison.query_refs
        if comparison.kind == "additive":
            assert analysis["baseline"] == comparison.baseline_total.value
            assert analysis["current"] == comparison.current_total.value
            assert analysis["delta"] == comparison.current_total.value - comparison.baseline_total.value
            assert analysis["contributions"] == {
                item.segment: item.current.value - item.baseline.value
                for item in comparison.segments
            }
        else:
            baseline = Fraction(int(comparison.baseline_total.numerator), int(comparison.baseline_total.denominator))
            current = Fraction(int(comparison.current_total.numerator), int(comparison.current_total.denominator))
            assert analysis["baseline"] == float(baseline)
            assert analysis["current"] == float(current)
            assert analysis["delta"] == float(current - baseline)


def test_outcomes_cover_actionable_quiet_stable_mix_missing_and_conflict():
    expected = {
        "northstar-cart": {"p05": "notify", "p06": "ignore", "p07": "notify", "p08": "insufficient_data"},
        "harbor-help": {"p05": "ignore", "p06": "insufficient_data", "p07": "notify", "p08": "notify"},
        "redwood-fulfillment": {"p05": "investigate", "p06": "notify", "p07": "ignore", "p08": "notify"},
    }
    for company, period in _periods():
        assert period["oracle"]["outcome"] == expected[company["id"]][period["id"]]
    harbor = next(company for company in cases() if company["id"] == "harbor-help")
    stable = next(period for period in harbor["periods"] if period["id"] == "p07")
    mixed = next(period for period in harbor["periods"] if period["id"] == "p08")
    assert (_analysis(stable)["baseline"], _analysis(stable)["current"], _analysis(stable)["delta"]) == (0.14, 0.14, 0.0)
    assert _analysis(mixed)["within_effect"] != _analysis(mixed)["mix_effect"]
    conflict = next(period for _, period in _periods() if period["oracle"]["semantic_status"] == "definition-conflict")
    assert conflict["oracle"]["status"] == "blocked"
    assert len(conflict["oracle"]["analyses"]) == 1


def test_policy_routes_are_strict_for_missing_and_definition_conflict():
    expected = {
        ("northstar-cart", "p05"): ["commerce-owner"],
        ("northstar-cart", "p06"): [],
        ("northstar-cart", "p07"): ["commerce-owner"],
        ("northstar-cart", "p08"): ["data-operations"],
        ("harbor-help", "p05"): [],
        ("harbor-help", "p06"): ["support-data-steward"],
        ("harbor-help", "p07"): ["support-operations"],
        ("harbor-help", "p08"): ["support-operations"],
        ("redwood-fulfillment", "p05"): ["fulfillment-data"],
        ("redwood-fulfillment", "p06"): ["fulfillment-owner"],
        ("redwood-fulfillment", "p07"): [],
        ("redwood-fulfillment", "p08"): ["fulfillment-owner"],
    }
    for company, period in _periods():
        assert period["oracle"]["recipients"] == expected[(company["id"], period["id"])]


def test_fresh_period_values_are_not_aliased_and_do_not_include_orbit():
    fresh = _fresh_periods()
    assert set(fresh) == {"northstar-cart", "harbor-help", "redwood-fulfillment"}
    assert all(period["id"] in {"p05", "p06", "p07", "p08"} for periods in fresh.values() for period in periods)
    first = cases()
    original = copy.deepcopy(first)
    first[0]["periods"][0]["resources"].clear()
    assert cases() == original

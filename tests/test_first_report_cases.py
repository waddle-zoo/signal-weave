import copy
import json
from datetime import timedelta
from fractions import Fraction

from evaluations.first_report_cases import cases
from signalweave.models import ResourceDescriptor, ResourceSnapshot, SourceRef


def _periods():
    return [(company, period) for company in cases() for period in company["periods"]]


def _primary(period):
    source_key = period["oracle"]["analyses"][0]["source_key"]
    return next(
        ResourceSnapshot.model_validate(resource)
        for resource in period["resources"]
        if resource["source_key"] == source_key
    )


def test_shape_is_four_companies_and_twelve_runs():
    companies = cases()
    assert len(companies) == 4
    assert {company["id"] for company in companies} == {
        "northstar-cart", "harbor-help", "redwood-fulfillment", "orbit-subscriptions",
    }
    assert all(set(company) == {
        "id", "company", "brief", "owner_policy", "descriptors", "sources", "destinations", "periods",
    } for company in companies)
    assert all(len(company["periods"]) == 3 for company in companies)
    assert len(_periods()) == 12
    assert {period["split"] for _, period in _periods()} == {"setup", "holdout"}


def test_directory_sources_and_snapshots_are_real_contracts():
    for company in cases():
        assert len(company["descriptors"]) == 2
        assert len(company["sources"]) == 2
        descriptor_refs = set()
        for payload in company["descriptors"]:
            descriptor = ResourceDescriptor.model_validate(payload)
            descriptor_refs.add(f"{descriptor.adapter}|{descriptor.resource}")
            assert descriptor.adapter == "company_mcp"
            assert descriptor.contract.available_comparison_windows == ["previous_period"]
            assert descriptor.contract.required_comparison_keys
            assert descriptor.metadata["business_role"] in {"reporting", "operations"}
        assert all(SourceRef.model_validate(source).required_comparison_keys for source in company["sources"])
        assert {f"{source['adapter']}|{source['resource']}" for source in company["sources"]} == descriptor_refs

        for period in company["periods"]:
            assert set(period) == {"id", "split", "as_of", "resources", "oracle"}
            assert len(period["resources"]) == 2
            assert {f"{resource['adapter']}|{resource['resource']}" for resource in period["resources"]} == descriptor_refs
            for payload in period["resources"]:
                snapshot = ResourceSnapshot.model_validate(payload)
                assert snapshot.captured_at == snapshot.source_captured_at + timedelta(hours=1)
                assert snapshot.metadata["period_id"] == period["id"]
                assert snapshot.metadata["as_of"] == period["as_of"]
                assert snapshot.metadata["replay_clock"] == snapshot.captured_at.isoformat()
                assert snapshot.contract.available_comparison_windows == ["previous_period"]
                assert len(snapshot.analytical_comparisons) == 1
                comparison = snapshot.analytical_comparisons[0]
                assert comparison.comparison_window == "previous_period"
                assert comparison.key in snapshot.contract.required_comparison_keys


def test_each_company_has_two_real_business_sources_with_different_definitions():
    for company in cases():
        assert {descriptor["metadata"]["business_role"] for descriptor in company["descriptors"]} == {"reporting", "operations"}
        metrics = [descriptor["contract"]["metric_names"][0] for descriptor in company["descriptors"]]
        populations = [descriptor["contract"]["population"] for descriptor in company["descriptors"]]
        assert len(set(metrics)) == 2
        assert len(set(populations)) == 2
        dumped = json.dumps(company["descriptors"] + company["periods"])
        for forbidden in ("primary", "distractor", "owner_requested", "semantic_disagreement", "source_role"):
            assert forbidden not in dumped


def test_oracle_analysis_matches_primary_comparison_totals_and_contributions():
    for _, period in _periods():
        if not period["oracle"]["analyses"]:
            assert period["oracle"]["status"] == "blocked"
            continue
        comparison = _primary(period).analytical_comparisons[0]
        analysis = period["oracle"]["analyses"][0]
        assert analysis["source_key"] == _primary(period).source_key
        assert analysis["comparison_key"] == comparison.key
        assert analysis["metric"] == comparison.metric
        assert analysis["unit"] == comparison.unit
        assert analysis["dimension"] == comparison.dimension
        assert analysis["definition"] == comparison.definition
        assert analysis["population"] == comparison.population
        assert analysis["query_refs"] == comparison.query_refs
        if comparison.kind == "additive":
            assert analysis["baseline"] == comparison.baseline_total.value
            assert analysis["current"] == comparison.current_total.value
            if period["oracle"]["status"] == "complete":
                assert analysis["delta"] == comparison.current_total.value - comparison.baseline_total.value
                expected = {
                    row.segment: row.current.value - row.baseline.value
                    for row in comparison.segments
                }
                assert analysis["contributions"] == expected
        else:
            baseline = Fraction(int(comparison.baseline_total.numerator), int(comparison.baseline_total.denominator))
            current = Fraction(int(comparison.current_total.numerator), int(comparison.current_total.denominator))
            assert analysis["baseline"] == float(baseline)
            assert analysis["current"] == float(current)
            if period["oracle"]["status"] == "complete":
                assert analysis["delta"] == float(current - baseline)


def test_rate_oracle_is_weighted_and_keeps_mix_and_within_effects_separate():
    company = next(company for company in cases() if company["id"] == "harbor-help")
    period = next(period for period in company["periods"] if period["id"] == "p02")
    comparison = _primary(period).analytical_comparisons[0]
    analysis = period["oracle"]["analyses"][0]
    d0, d1 = int(comparison.baseline_total.denominator), int(comparison.current_total.denominator)
    within = Fraction()
    mix = Fraction()
    for row in comparison.segments:
        r0 = Fraction(int(row.baseline.numerator), int(row.baseline.denominator))
        r1 = Fraction(int(row.current.numerator), int(row.current.denominator))
        w0 = Fraction(int(row.baseline.denominator), d0)
        w1 = Fraction(int(row.current.denominator), d1)
        within += (w0 + w1) * (r1 - r0) / 2
        mix += (r0 + r1) * (w1 - w0) / 2
    assert analysis["within_effect"] == float(within)
    assert analysis["mix_effect"] == float(mix)
    assert analysis["within_effect"] != analysis["mix_effect"]


def test_distribution_contains_quiet_partial_definition_conflict_and_routes():
    periods = [period for _, period in _periods()]
    assert any(period["oracle"]["outcome"] == "ignore" for period in periods)
    assert any(period["oracle"]["status"] == "blocked" and not period["oracle"]["analyses"] for period in periods)
    assert any(period["oracle"]["semantic_status"] == "definition-conflict" for period in periods)
    partial = next(period for period in periods if period["oracle"]["status"] == "blocked" and not period["oracle"]["analyses"])
    assert partial["oracle"]["status"] == "blocked"  # report status; outcome remains the engine's insufficient-data route
    assert partial["oracle"]["outcome"] == "insufficient_data"
    assert partial["oracle"]["recipients"] == []
    conflict = next(period for period in periods if period["oracle"]["semantic_status"] == "definition-conflict")
    assert conflict["oracle"]["status"] == "blocked"
    assert len(conflict["oracle"]["analyses"]) == 1
    assert conflict["oracle"]["outcome"] == "investigate"
    assert conflict["oracle"]["recipients"] == ["fulfillment-data"]


def test_fixture_is_json_serializable_reproducible_and_does_not_alias():
    first = cases()
    second = cases()
    assert first == second
    json.dumps(first)
    original = copy.deepcopy(first)
    first[0]["periods"][0]["oracle"]["outcome"] = "poisoned"
    first[0]["periods"][0]["resources"].clear()
    assert cases() == original

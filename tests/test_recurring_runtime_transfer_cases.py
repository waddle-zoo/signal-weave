"""Independent arithmetic and boundary checks for transfer fixtures."""

import ast
import copy
import json
from fractions import Fraction
from pathlib import Path

from evaluations.recurring_runtime_transfer_cases import cases, onboarding_company, public_company
from signalweave.models import ResourceDescriptor, ResourceSnapshot, SourceRef


def _primary(company, period):
    key = next(source["key"] for source in company["sources"] if source["parameters"]["business_role"] == "reporting")
    return ResourceSnapshot.model_validate(next(resource for resource in period["resources"] if resource["source_key"] == key))


def _independent_additive(snapshot):
    comparison = snapshot.analytical_comparisons[0]
    baseline = {row.segment: row.baseline.value for row in comparison.segments if row.baseline.value is not None}
    current = {row.segment: row.current.value for row in comparison.segments if row.current.value is not None}
    complete = comparison.coverage == "complete" and comparison.comparable and set(baseline) == set(current)
    return {
        "baseline": sum(baseline.values()) if baseline else None,
        "current": sum(current.values()) if complete and current else None,
        "delta": (sum(current.values()) - sum(baseline.values())) if complete else None,
        "contributions": {
            segment: current[segment] - baseline[segment]
            for segment in sorted(set(baseline) & set(current))
        } if complete else {},
    }


def _independent_rate(snapshot):
    comparison = snapshot.analytical_comparisons[0]
    baseline = {
        row.segment: (int(row.baseline.numerator), int(row.baseline.denominator))
        for row in comparison.segments
        if row.baseline.numerator is not None and row.baseline.denominator is not None
    }
    current = {
        row.segment: (int(row.current.numerator), int(row.current.denominator))
        for row in comparison.segments
        if row.current.numerator is not None and row.current.denominator is not None
    }
    complete = comparison.coverage == "complete" and comparison.comparable and set(baseline) == set(current)
    if not complete:
        return {"baseline": None, "current": None, "delta": None, "contributions": {}}
    base_total = (sum(value[0] for value in baseline.values()), sum(value[1] for value in baseline.values()))
    current_total = (sum(value[0] for value in current.values()), sum(value[1] for value in current.values()))
    baseline_rate = Fraction(*base_total)
    current_rate = Fraction(*current_total)
    contributions = {}
    for segment in sorted(baseline):
        r0, r1 = Fraction(*baseline[segment]), Fraction(*current[segment])
        w0 = Fraction(baseline[segment][1], base_total[1])
        w1 = Fraction(current[segment][1], current_total[1])
        contributions[segment] = float((w0 + w1) * (r1 - r0) / 2 + (r0 + r1) * (w1 - w0) / 2)
    return {
        "baseline": float(baseline_rate),
        "current": float(current_rate),
        "delta": float(current_rate - baseline_rate),
        "contributions": contributions,
    }


def test_transfer_cases_are_new_plain_english_companies_with_two_setup_and_four_holdout_periods():
    companies = cases()
    assert {company["id"] for company in companies} == {"canyon-freight", "helio-support", "lattice-energy"}
    assert len({company["company"] for company in companies}) == 3
    assert len({company["owner_policy"] for company in companies}) == 3
    for company in companies:
        assert len(company["periods"]) == 6
        assert [period["split"] for period in company["periods"]] == ["setup", "setup", "holdout", "holdout", "holdout", "holdout"]
        assert len({period["id"] for period in company["periods"]}) == 6
        assert "numeric_conditions" not in json.dumps(company["owner_policy"]).lower()
        assert "rule" not in json.dumps(company["owner_policy"]).lower()
        assert "plan" not in json.dumps(company["owner_policy"]).lower()


def test_transfer_sources_and_snapshots_are_valid_and_pairs_are_disjoint():
    for company in cases():
        descriptor_refs = set()
        for payload in company["descriptors"]:
            descriptor = ResourceDescriptor.model_validate(payload)
            descriptor_refs.add(f"{descriptor.adapter}|{descriptor.resource}")
            assert descriptor.contract.available_comparison_windows == ["previous_period"]
            assert descriptor.metadata["comparability_contract"]["segment_partition"]
        assert {f"{source['adapter']}|{source['resource']}" for source in company["sources"]} == descriptor_refs
        for source in company["sources"]:
            SourceRef.model_validate(source)
        previous_end = None
        for period in company["periods"]:
            snapshot = _primary(company, period)
            comparison = snapshot.analytical_comparisons[0]
            assert comparison.comparison_window == "previous_period"
            assert comparison.disjoint_segments is True
            assert comparison.query_refs
            if previous_end is not None:
                assert comparison.baseline_start >= previous_end
            previous_end = comparison.current_end


def test_independent_arithmetic_matches_private_oracles_and_expected_holdouts():
    expected = {
        "canyon-freight": ["notify", "ignore", "insufficient_data", "notify"],
        "helio-support": ["notify", "notify", "ignore", "insufficient_data"],
        "lattice-energy": ["notify", "ignore", "ignore", "investigate"],
    }
    for company in cases():
        for period in company["periods"]:
            oracle = period["oracle"]
            snapshot = _primary(company, period)
            recomputed = _independent_rate(snapshot) if company["id"] == "helio-support" else _independent_additive(snapshot)
            measurements = oracle["measurements"]
            assert measurements["baseline"] == recomputed["baseline"]
            assert measurements["current"] == recomputed["current"]
            assert measurements["delta"] == recomputed["delta"]
            assert {item["segment"]: item["contribution"] for item in measurements["contributions"]} == recomputed["contributions"]
        assert [period["oracle"]["outcome"] for period in company["periods"][2:]] == expected[company["id"]]


def test_setup_examples_include_quiet_then_actionable_outcomes():
    companies = {company["id"]: company for company in cases()}
    assert companies["canyon-freight"]["periods"][0]["oracle"]["measurements"]["delta"] == -37
    assert [period["oracle"]["outcome"] for period in companies["canyon-freight"]["periods"][:2]] == ["ignore", "notify"]
    assert [period["oracle"]["outcome"] for period in companies["helio-support"]["periods"][:2]] == ["ignore", "notify"]
    assert [period["oracle"]["outcome"] for period in companies["lattice-energy"]["periods"][:2]] == ["ignore", "notify"]


def test_transfer_cases_cover_directional_quiet_segment_exception_and_unknown_paths():
    companies = {company["id"]: company for company in cases()}
    canyon = companies["canyon-freight"]
    p03 = canyon["periods"][2]["oracle"]
    p04 = canyon["periods"][3]["oracle"]
    assert p03["measurements"]["delta"] == 13
    assert next(item for item in p03["measurements"]["contributions"] if item["segment"] == "air")["contribution"] == 12
    assert p04["measurements"]["delta"] == -17
    assert next(item for item in p04["measurements"]["contributions"] if item["segment"] == "air")["contribution"] == -20
    assert p04["outcome"] == "ignore"

    helio = companies["helio-support"]
    assert helio["periods"][2]["oracle"]["measurements"]["current"] >= 0.09
    assert helio["periods"][3]["oracle"]["measurements"]["current"] < 0.09
    assert helio["periods"][3]["oracle"]["measurements"]["delta"] >= 0.025
    assert helio["periods"][5]["oracle"]["outcome"] == "insufficient_data"

    lattice = companies["lattice-energy"]
    for condition in lattice["periods"][0]["oracle"]["numeric_policy"]:
        assert condition["absolute"] is False
    segments = {condition["segment"] for condition in lattice["periods"][0]["oracle"]["numeric_policy"] if condition["measurement"] == "contribution"}
    assert segments == {"contraction", "churn"}
    assert lattice["periods"][4]["oracle"]["context_status"] == "approved"
    assert lattice["periods"][4]["oracle"]["outcome"] == "ignore"
    assert lattice["periods"][5]["oracle"]["context_status"] == "unresolved"
    assert lattice["periods"][5]["oracle"]["outcome"] == "investigate"
    p04 = lattice["periods"][3]["oracle"]
    assert p04["measurements"]["delta"] == 5
    contributions = {item["segment"]: item["contribution"] for item in p04["measurements"]["contributions"]}
    assert contributions["expansion"] == -60
    assert contributions["new_contract"] == 75
    assert contributions["contraction"] == -5
    assert contributions["churn"] == -5
    assert p04["outcome"] == "ignore"
    context = next(resource for resource in lattice["periods"][5]["resources"] if resource["source_key"].endswith("-context"))
    assert context["contract"]["source_status"] == "healthy"
    assert "available and healthy" in context["evidence"][0]["statement"]
    assert context["evidence"][0]["values"]["exception_status"] == "unresolved"


def test_views_hide_future_oracle_labels_and_preserve_setup_only_boundary():
    for company in cases():
        onboarding = onboarding_company(company)
        public = public_company(company)
        assert len(onboarding["periods"]) == 2
        assert all("oracle" not in period for period in onboarding["periods"])
        assert {period["id"] for period in onboarding["periods"]} == {"p01", "p02"}
        assert all("oracle" not in period for period in public["periods"])
        assert len(public["periods"]) == 6
        assert "holdout" not in json.dumps(onboarding).lower()


def test_cases_are_reproducible_and_fixture_has_no_live_runtime_dependencies():
    first = cases()
    second = cases()
    assert first == second
    json.dumps(first, allow_nan=False)
    original = copy.deepcopy(first)
    first[0]["periods"][0]["resources"].clear()
    first[0]["periods"][2]["oracle"]["outcome"] = "poisoned"
    assert cases() == original

    source_path = Path(__file__).parents[1].joinpath("evaluations", "recurring_runtime_transfer_cases.py")
    tree = ast.parse(source_path.read_text())
    source = source_path.read_text()
    assert "load_api_key" not in source
    assert "AsyncTypeSafeClient" not in source
    assert "http://" not in source
    assert not any(isinstance(node, ast.Call) and getattr(node.func, "attr", "") in {"run_trial", "evaluate_insight_card"} for node in ast.walk(tree))

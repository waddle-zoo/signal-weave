"""Offline integrity tests for the prospective recurring-runtime fixtures."""

import ast
import copy
import json
from collections import Counter
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

from evaluations.recurring_runtime_cases import cases, onboarding_company, public_company
from signalweave.models import ResourceDescriptor, ResourceSnapshot, SourceRef


def _all_periods(company):
    return company["periods"]


def _primary(company, period):
    primary_key = next(item["key"] for item in company["sources"] if item["parameters"]["business_role"] == "reporting")
    return ResourceSnapshot.model_validate(next(resource for resource in period["resources"] if resource["source_key"] == primary_key))


def _recompute_additive(snapshot):
    comparison = snapshot.analytical_comparisons[0]
    baseline = {row.segment: row.baseline.value for row in comparison.segments if row.baseline.value is not None}
    current = {row.segment: row.current.value for row in comparison.segments if row.current.value is not None}
    complete = comparison.coverage == "complete" and comparison.comparable and set(baseline) == set(current)
    baseline_total = sum(baseline.values()) if baseline else None
    current_total = sum(current.values()) if current else None
    return {
        "baseline": baseline_total,
        "current": current_total if complete else None,
        "delta": current_total - baseline_total if complete and baseline_total is not None and current_total is not None else None,
        "contributions": {
            segment: current[segment] - baseline[segment]
            for segment in sorted(set(baseline) & set(current))
        } if complete else {},
    }


def _recompute_rate(snapshot):
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
    base_total = (sum(value[0] for value in baseline.values()), sum(value[1] for value in baseline.values()))
    current_total = (sum(value[0] for value in current.values()), sum(value[1] for value in current.values()))
    baseline_rate = Fraction(*base_total) if complete else None
    current_rate = Fraction(*current_total) if complete else None
    contributions = {}
    if complete and baseline_rate is not None and current_rate is not None:
        for segment in sorted(baseline):
            r0 = Fraction(*baseline[segment])
            r1 = Fraction(*current[segment])
            w0 = Fraction(baseline[segment][1], base_total[1])
            w1 = Fraction(current[segment][1], current_total[1])
            within = (w0 + w1) * (r1 - r0) / 2
            mix = (r0 + r1) * (w1 - w0) / 2
            contributions[segment] = float(within + mix)
    return {
        "baseline": float(baseline_rate) if baseline_rate is not None else None,
        "current": float(current_rate) if current_rate is not None else None,
        "delta": float(current_rate - baseline_rate) if baseline_rate is not None and current_rate is not None else None,
        "contributions": contributions,
    }


def test_fixture_has_three_new_companies_and_two_setup_four_holdout_periods():
    companies = cases()
    assert len(companies) == 3
    assert {company["id"] for company in companies} == {
        "juniper-bookings", "mosaic-payments", "saffron-cloud",
    }
    assert not {company["company"] for company in companies} & {
        "Northstar Cart", "Harbor Help", "Redwood Fulfillment",
    }
    for company in companies:
        assert len(company["periods"]) == 6
        assert [period["split"] for period in company["periods"]] == [
            "setup", "setup", "holdout", "holdout", "holdout", "holdout",
        ]
        assert len({period["id"] for period in company["periods"]}) == 6


def test_directory_contracts_and_snapshots_are_explicitly_comparable():
    for company in cases():
        descriptor_refs = set()
        for payload in company["descriptors"]:
            descriptor = ResourceDescriptor.model_validate(payload)
            descriptor_refs.add(f"{descriptor.adapter}|{descriptor.resource}")
            assert descriptor.contract.tenant_id == "synthetic-recurring-runtime"
            assert descriptor.contract.available_comparison_windows == ["previous_period"]
            assert descriptor.metadata["period_contract"]
            assert descriptor.metadata["comparability_contract"]["population_identity"]
        assert {f"{source['adapter']}|{source['resource']}" for source in company["sources"]} == descriptor_refs
        for source in company["sources"]:
            SourceRef.model_validate(source)
        for period in company["periods"]:
            refs = {f"{resource['adapter']}|{resource['resource']}" for resource in period["resources"]}
            assert refs == descriptor_refs
            for payload in period["resources"]:
                snapshot = ResourceSnapshot.model_validate(payload)
                assert snapshot.captured_at == snapshot.source_captured_at + timedelta(hours=1)
                assert snapshot.metadata["period_id"] == period["id"]
                assert snapshot.metadata["comparability"]["adjacent_periods"] is True
                if snapshot.analytical_comparisons:
                    flags = snapshot.metadata["comparability"]["flags"]
                    assert flags["same_definition"] is True
                    assert flags["adjacent_periods"] is True
                    assert flags["same_population"] is (period["oracle"]["status"] == "complete")
                    assert flags["complete_segment_partition"] is (period["oracle"]["status"] == "complete")
                    assert flags["totals_reconciled"] is (period["oracle"]["status"] == "complete")
                    comparison = snapshot.analytical_comparisons[0]
                    assert comparison.comparison_window == "previous_period"
                    assert comparison.disjoint_segments is True
                    assert comparison.comparable is (comparison.coverage == "complete")
                    assert comparison.query_refs
                    assert comparison.key in snapshot.contract.required_comparison_keys


def test_policy_is_plain_english_and_does_not_smuggle_a_plan_schema():
    for company in cases():
        assert company["owner_policy"].strip()
        assert "selector" not in company["owner_policy"]
        assert "operator" not in company["owner_policy"]
        assert "magnitude" not in company["owner_policy"]
        assert "numeric_conditions" not in company
        assert "plan" not in company
        assert "compiled_plan" not in company
        assert "checks" not in company
        assert set(company["review_guidance"]) == {"expected_prose_claims", "noncausal_limitations"}
        assert company["review_guidance"]["expected_prose_claims"]
        assert company["review_guidance"]["noncausal_limitations"]
        assert any("cause" in item.lower() or "causal" in item.lower() for item in company["review_guidance"]["noncausal_limitations"])


def test_oracles_recompute_from_returned_comparisons_and_cover_all_outcomes():
    outcome_counts = Counter()
    expected_holdout = {
        "juniper-bookings": ["notify", "notify", "ignore", "insufficient_data"],
        "mosaic-payments": ["notify", "notify", "ignore", "insufficient_data"],
        "saffron-cloud": ["notify", "ignore", "ignore", "investigate"],
    }
    for company in cases():
        holdouts = company["periods"][2:]
        assert [period["oracle"]["outcome"] for period in holdouts] == expected_holdout[company["id"]]
        for period in company["periods"]:
            oracle = period["oracle"]
            outcome_counts[oracle["outcome"]] += 1
            primary = _primary(company, period)
            recomputed = _recompute_rate(primary) if company["id"] == "mosaic-payments" else _recompute_additive(primary)
            measurements = oracle["measurements"]
            assert measurements["baseline"] == recomputed["baseline"]
            assert measurements["current"] == recomputed["current"]
            assert measurements["delta"] == recomputed["delta"]
            assert {
                item["segment"]: item["contribution"] for item in measurements["contributions"]
            } == recomputed["contributions"]
    assert outcome_counts == Counter({"notify": 8, "ignore": 7, "insufficient_data": 2, "investigate": 1})


def test_threshold_cases_are_substantive_not_boundary_only():
    companies = {company["id"]: company for company in cases()}
    juniper = companies["juniper-bookings"]
    p03 = juniper["periods"][2]["oracle"]
    assert p03["measurements"]["delta"] == 10
    assert max(p03["measurements"]["contributions"], key=lambda item: item["contribution"])["contribution"] == 28
    mosaic = companies["mosaic-payments"]
    p03 = mosaic["periods"][2]["oracle"]
    p04 = mosaic["periods"][3]["oracle"]
    assert p03["measurements"]["current"] > 0.048
    assert p03["measurements"]["delta"] < 0.012
    assert p04["measurements"]["current"] < 0.048
    assert p04["measurements"]["delta"] > 0.012
    saffron = companies["saffron-cloud"]
    quiet = saffron["periods"][3]["oracle"]
    assert quiet["outcome"] == "ignore"
    assert quiet["measurements"]["delta"] == -15
    assert next(item for item in quiet["measurements"]["contributions"]
                if item["segment"] == "expansion")["contribution"] == -70
    assert saffron["periods"][4]["oracle"]["context_status"] == "approved"
    assert saffron["periods"][4]["oracle"]["outcome"] == "ignore"
    assert saffron["periods"][5]["oracle"]["context_status"] == "unavailable"
    assert saffron["periods"][5]["oracle"]["outcome"] == "investigate"


def test_signed_movement_preserves_negative_values_and_qualitative_context():
    company = next(item for item in cases() if item["id"] == "saffron-cloud")
    p03 = company["periods"][2]
    comparison = _primary(company, p03).analytical_comparisons[0]
    values = {row.segment: (row.baseline.value, row.current.value) for row in comparison.segments}
    assert values["churn"] == (-35, -100)
    assert p03["oracle"]["outcome"] == "notify"
    assert p03["oracle"]["recipients"] == ["revenue-operations"]
    context = next(resource for resource in p03["resources"] if resource["resource"] == "record:pricing-freeze-register")
    assert context["evidence"][0]["values"]["exception_status"] == "none"
    exception = company["periods"][4]
    assert exception["oracle"]["outcome"] == "ignore"
    exception_context = next(resource for resource in exception["resources"] if resource["resource"] == "record:pricing-freeze-register")
    assert exception_context["evidence"][0]["values"]["exception_status"] == "approved"


def test_onboarding_view_has_only_setup_data_and_no_private_labels_or_future_ids():
    for company in cases():
        view = onboarding_company(company)
        assert len(view["periods"]) == 2
        assert all("oracle" not in period for period in view["periods"])
        assert {period["id"] for period in view["periods"]} == {"p01", "p02"}
        serialized = json.dumps(view, sort_keys=True).lower()
        assert "holdout" not in serialized
        assert "expected_outcome" not in serialized
        assert all(f'"p0{index}"' not in serialized for index in (3, 4, 5, 6))
        full_public = public_company(company)
        assert all("oracle" not in period for period in full_public["periods"])
        assert len(full_public["periods"]) == 6


def test_public_source_payload_does_not_leak_private_oracle_labels():
    for company in cases():
        public = public_company(company)
        payload = json.dumps(public, sort_keys=True).lower()
        for private_label in ("expected_outcome", "materiality", "context_status", "holdout", "oracle"):
            assert private_label not in payload


def test_cases_are_reproducible_independent_copies_and_json_ready():
    first = cases()
    second = cases()
    assert first == second
    json.dumps(first, allow_nan=False)
    original = copy.deepcopy(first)
    first[0]["periods"][0]["resources"].clear()
    first[0]["periods"][2]["oracle"]["outcome"] = "poisoned"
    assert cases() == original


def test_fixture_module_is_static_and_makes_no_live_runtime_calls():
    source_path = Path(__file__).parents[1].joinpath("evaluations", "recurring_runtime_cases.py")
    source = source_path.read_text()
    tree = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    imported_modules = {node.module for node in imports if isinstance(node, ast.ImportFrom)}
    assert imported_modules <= {"__future__", "datetime", "fractions", "typing", "signalweave.models"}
    assert {name.name for node in imports if isinstance(node, ast.Import) for name in node.names} <= {"copy"}
    assert "load_api_key" not in source
    assert "AsyncTypeSafeClient" not in source
    assert "http://" not in source
    assert "evaluate_insight_card" not in source


def test_timestamps_are_ordered_and_current_gap_is_explicit():
    for company in cases():
        periods = company["periods"]
        for earlier, later in zip(periods, periods[1:], strict=False):
            assert datetime.fromisoformat(earlier["as_of"]) < datetime.fromisoformat(later["as_of"])
            assert (_primary(company, earlier).analytical_comparisons[0].current_end
                    <= _primary(company, later).analytical_comparisons[0].baseline_start)
        blocked = [period for period in periods if period["oracle"]["outcome"] == "insufficient_data"]
        for period in blocked:
            primary = _primary(company, period)
            comparison = primary.analytical_comparisons[0]
            assert comparison.coverage == "partial"
            assert comparison.comparable is False
            assert primary.metadata["comparability"]["segment_partition_complete"] is False

"""Offline contract tests for the fresh policy-composition holdout."""

import ast
import json
from collections import Counter
from pathlib import Path

from evaluations.policy_composition_cases import LABEL_SOURCE, cases

EXPECTED_OUTCOMES = {
    "cobalt-orders-flat-total": "notify",
    "cobalt-orders-quiet": "ignore",
    "cobalt-orders-exception": "ignore",
    "cobalt-orders-missing-context": "insufficient_data",
    "maple-delivery-both-triggers": "notify",
    "maple-delivery-one-sided": "ignore",
    "maple-delivery-exception-conflict": "investigate",
    "maple-delivery-missing-rate": "insufficient_data",
    "quartz-release-high-priority": "notify",
    "quartz-release-routine": "ignore",
    "quartz-release-missing-priority": "insufficient_data",
    "quartz-release-conflicting-priority": "insufficient_data",
}


def test_holdout_has_three_novel_companies_and_twelve_cases():
    fixture = cases()
    assert len(fixture) == 12
    assert Counter(case["company"] for case in fixture) == {
        "cobalt-market": 4,
        "maple-mobility": 4,
        "quartz-care": 4,
    }
    assert len({case["id"] for case in fixture}) == 12


def test_schema_is_small_json_ready_and_policy_is_plain_english():
    fixture = cases()
    json.loads(json.dumps(fixture, allow_nan=False))
    for case in fixture:
        assert set(case) == {
            "id", "company", "policy", "field_catalog", "measurements", "facts",
            "expected", "metadata",
        }
        assert set(case["policy"]) == {"text", "destinations"}
        assert case["policy"]["text"].strip()
        assert set(case["policy"]["destinations"]) == {
            "notify", "investigate", "insufficient_data",
        }
        assert case["facts"] and all(set(fact) == {"id", "statement"} for fact in case["facts"])
        assert all(fact["statement"].strip() for fact in case["facts"])
        assert set(case["measurements"]) == set(case["field_catalog"])
        assert all(set(field) == {"type", "description"} for field in case["field_catalog"].values())
        assert all(field["description"].strip() for field in case["field_catalog"].values())
        assert set(case["expected"]) == {"outcome", "recipients", "reason"}
        assert case["expected"]["reason"].strip()
        assert case["metadata"]["label_source"] == LABEL_SOURCE
        assert "LLM-onboarded" in case["metadata"]["label_source"]


def test_expected_labels_are_explicit_and_cover_routes_without_deriving_them():
    fixture = cases()
    assert {case["id"] for case in fixture} == set(EXPECTED_OUTCOMES)
    for case in fixture:
        expected = case["expected"]
        assert expected["outcome"] == EXPECTED_OUTCOMES[case["id"]]
        if expected["outcome"] == "ignore":
            assert expected["recipients"] == []
        else:
            assert expected["recipients"] == [case["policy"]["destinations"][expected["outcome"]]]
    assert Counter(EXPECTED_OUTCOMES.values()) == {
        "notify": 3,
        "ignore": 4,
        "investigate": 1,
        "insufficient_data": 4,
    }


def test_each_company_has_one_policy_for_compile_once_onboarding():
    policies_by_company = {}
    for case in cases():
        policies_by_company.setdefault(case["company"], case["policy"])
        assert case["policy"] == policies_by_company[case["company"]]
    assert set(policies_by_company) == {"cobalt-market", "maple-mobility", "quartz-care"}


def test_measurements_are_frozen_flat_scalars_with_absence_explicitly_null():
    by_id = {case["id"]: case for case in cases()}
    assert by_id["cobalt-orders-flat-total"]["measurements"] == {
        "total_decline_pct": 0.0,
        "max_region_decline_pct": 20.0,
    }
    assert by_id["cobalt-orders-missing-context"]["measurements"] == {
        "total_decline_pct": 16.0,
        "max_region_decline_pct": None,
    }
    assert by_id["maple-delivery-both-triggers"]["measurements"] == {
        "on_time_pct": 90,
        "cancellation_delta_pp": 3,
    }
    assert by_id["maple-delivery-missing-rate"]["measurements"] == {
        "on_time_pct": 89,
        "cancellation_delta_pp": None,
    }


def test_adversarial_dimensions_are_represented_without_expert_decision_trees():
    tags = {tag for case in cases() for tag in case["metadata"]["tags"]}
    assert {
        "or_vs_and", "exception_override", "missing_context", "flat_total",
        "opposing_movements", "directional_change", "directional_increase", "qualitative_semantics",
        "conflicting_evidence", "quiet",
    } <= tags
    for case in cases():
        assert "narrow_checks" not in case
        assert "boolean_plan" not in case
        assert "decision_tree" not in case


def test_cases_are_returned_as_independent_copies():
    first = cases()
    first[0]["facts"].clear()
    first[0]["policy"]["destinations"]["notify"] = "mutated"
    second = cases()
    assert second[0]["facts"]
    assert second[0]["policy"]["destinations"]["notify"] == "primary-owner"


def test_fixture_module_is_static_and_does_not_load_keys_or_call_networks():
    source = Path(__file__).parents[1].joinpath("evaluations", "policy_composition_cases.py").read_text()
    tree = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert {node.module for node in imports if isinstance(node, ast.ImportFrom)} <= {"__future__", "copy", "typing"}
    assert not {name for node in imports if isinstance(node, ast.Import) for name in node.names}
    assert "load_api_key" not in source
    assert "AsyncTypeSafeClient" not in source
    assert "requests" not in source
    assert "http://" not in source

"""Offline contract checks for the independent policy-composition transfer set."""

import ast
import json
from collections import Counter
from pathlib import Path

from evaluations.policy_composition_transfer import (
    EXCLUDED_AMBIGUITIES,
    LABEL_SOURCE,
    cases,
)

EXPECTED = {
    "cobalt-transfer-opposed-nonzero-total": "notify",
    "cobalt-transfer-exact-ten-fifteen": "notify",
    "cobalt-transfer-approved-freeze": "ignore",
    "cobalt-transfer-missing-regions": "insufficient_data",
    "maple-transfer-both-triggers": "notify",
    "maple-transfer-one-trigger": "ignore",
    "maple-transfer-strict-boundary": "ignore",
    "maple-transfer-missing-cancellation": "insufficient_data",
    "quartz-transfer-high-priority": "notify",
    "quartz-transfer-routine-release": "ignore",
    "quartz-transfer-signed-override": "ignore",
    "quartz-transfer-priority-conflict": "insufficient_data",
}


def test_transfer_has_three_companies_and_twelve_fresh_cases():
    fixture = cases()
    assert len(fixture) == 12
    assert Counter(case["company"] for case in fixture) == {
        "cobalt-market": 4,
        "maple-mobility": 4,
        "quartz-care": 4,
    }
    assert len({case["id"] for case in fixture}) == 12


def test_schema_routes_and_labels_are_explicit():
    fixture = cases()
    assert {case["id"] for case in fixture} == set(EXPECTED)
    assert Counter(EXPECTED.values()) == {
        "notify": 4,
        "ignore": 5,
        "insufficient_data": 3,
    }
    for case in fixture:
        assert set(case) == {
            "id", "company", "policy", "field_catalog", "measurements",
            "facts", "expected", "metadata",
        }
        assert case["expected"]["outcome"] == EXPECTED[case["id"]]
        assert case["expected"]["reason"].strip()
        assert case["metadata"]["label_source"] == LABEL_SOURCE
        assert set(case["policy"]["destinations"]) == {
            "notify", "investigate", "insufficient_data",
        }
        outcome = case["expected"]["outcome"]
        expected_recipients = [] if outcome == "ignore" else [case["policy"]["destinations"][outcome]]
        assert case["expected"]["recipients"] == expected_recipients
        assert set(case["measurements"]) == set(case["field_catalog"])
        assert all(set(field) == {"type", "description"}
                   for field in case["field_catalog"].values())
        assert all(set(fact) == {"id", "statement"} for fact in case["facts"])


def test_transfer_arithmetic_and_required_edge_cases_are_frozen():
    by_id = {case["id"]: case for case in cases()}
    assert by_id["cobalt-transfer-opposed-nonzero-total"]["measurements"] == {
        "total_decline_pct": -2.0,
        "max_region_decline_pct": 21.43,
    }
    assert by_id["cobalt-transfer-exact-ten-fifteen"]["measurements"] == {
        "total_decline_pct": 10.0,
        "max_region_decline_pct": 15.0,
    }
    assert by_id["cobalt-transfer-missing-regions"]["measurements"]["max_region_decline_pct"] is None
    assert by_id["maple-transfer-strict-boundary"]["measurements"] == {
        "on_time_pct": 92.0,
        "cancellation_delta_pp": 2.0,
    }
    assert by_id["maple-transfer-missing-cancellation"]["measurements"]["cancellation_delta_pp"] is None


def test_ambiguities_are_explicitly_excluded_and_reasons_are_noncausal():
    assert EXCLUDED_AMBIGUITIES
    assert all("caus" not in case["expected"]["reason"].lower() for case in cases())
    assert any("signed_reconciliation_override" in case["metadata"]["tags"] for case in cases())
    assert any("priority_conflict" in case["metadata"]["tags"] for case in cases())


def test_cases_are_independent_copies_and_json_ready():
    first = cases()
    first[0]["facts"].clear()
    first[0]["policy"]["destinations"]["notify"] = "mutated"
    second = cases()
    assert second[0]["facts"]
    assert second[0]["policy"]["destinations"]["notify"] == "primary-owner"
    json.dumps(second, allow_nan=False)


def test_fixture_is_data_only_and_does_not_import_trial_or_network_code():
    source = Path(__file__).parents[1].joinpath(
        "evaluations", "policy_composition_transfer.py"
    ).read_text()
    tree = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert {node.module for node in imports if isinstance(node, ast.ImportFrom)} <= {
        "__future__", "copy", "typing",
    }
    assert not {name for node in imports if isinstance(node, ast.Import) for name in node.names}
    for forbidden in ("policy_composition_trial", "AsyncTypeSafeClient", "load_api_key", "http://"):
        assert forbidden not in source

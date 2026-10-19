"""Source rows are useful facts even when no Observation mapping exists."""
import copy
import json

from signalweave.mcp_server import (
    AGENT_HANDOFF_BYTES,
    _compact_evaluation_response,
    _receipt_result_page,
)


def response(rows):
    return {
        "receipt": {"receipt_id": "rows-receipt"},
        "result": {
            "outcome": "investigate", "observations": [], "evidence": rows,
            "warnings": ["The denominator definition is owner-reviewed, not independently certified."],
            "source_contracts": [{"source_key": "query", "population": "The selected cohort."}],
            "source_by_key": {"query": {"raw_connector_metadata": "x" * AGENT_HANDOFF_BYTES}},
        },
    }


def row(index):
    return {
        "source_key": "query", "subject_id": f"row-{index}", "origin": "source",
        "statement": "A source-provided result row, not an inferred metric definition.",
        "values": {"segment": f"slice-{index}", "eligible": index, "ratio": 0.125,
                   "precise_decimal": "0.123456789123456789", "unknown": None, "flag": False},
        "provenance": ["query-adapter|saved-query:reviewed"],
    }


def test_source_rows_fit_without_observations_and_keep_exact_values_and_provenance():
    original = response([row(index) for index in range(23)])
    before = copy.deepcopy(original)
    compact = _compact_evaluation_response(original)
    assert compact["result"]["evidence"] == original["result"]["evidence"]
    assert compact["evidence_access"]["evidence_coverage"] == {
        "result_path": ["evidence"], "total": 23, "included": 23,
        "coverage": "complete_section", "next_offset": None,
    }
    assert compact["result"]["warnings"] == original["result"]["warnings"]
    assert compact["result"]["source_contracts"] == original["result"]["source_contracts"]
    assert compact["result"]["evidence"][0]["values"]["flag"] is False
    assert compact["result"]["evidence"][0]["values"]["unknown"] is None
    assert json.dumps(original, sort_keys=True) == json.dumps(before, sort_keys=True)
    assert len(json.dumps(compact, ensure_ascii=False).encode()) <= AGENT_HANDOFF_BYTES


def test_bounded_prefix_reconstructs_all_remaining_rows_from_receipt_without_inference():
    original = response([row(index) for index in range(200)])
    compact = _compact_evaluation_response(original)
    coverage = compact["evidence_access"]["evidence_coverage"]
    shown = compact["result"]["evidence"]
    assert 0 < len(shown) <= 25
    assert coverage["coverage"] == "partial_section"
    assert coverage["total"] == 200 and coverage["next_offset"] == len(shown)
    recovered = list(shown)
    offset = coverage["next_offset"]
    while offset is not None:
        page = _receipt_result_page(original["result"], coverage["result_path"], offset, 25)
        recovered.extend(page["items"])
        offset = page["next_offset"]
    assert json.dumps(recovered, sort_keys=True) == json.dumps(original["result"]["evidence"], sort_keys=True)
    assert len(json.dumps(compact, ensure_ascii=False).encode()) <= AGENT_HANDOFF_BYTES


def test_oversized_first_evidence_is_explicitly_omitted_not_truncated_or_reported_empty():
    first = row(0)
    first["values"]["large_detail"] = "漢" * AGENT_HANDOFF_BYTES
    original = response([first])
    compact = _compact_evaluation_response(original)
    assert compact["result"]["evidence"] == []
    assert compact["evidence_access"]["evidence_coverage"] == {
        "result_path": ["evidence"], "total": 1, "included": 0,
        "coverage": "partial_section", "next_offset": 0,
    }
    page = _receipt_result_page(original["result"], ["evidence", "0", "values"], 0, 5)
    assert {item["key"]: item["value"] for item in page["items"]}["eligible"] == 0
    assert original["result"]["evidence"][0]["values"]["large_detail"] == "漢" * AGENT_HANDOFF_BYTES
    assert len(json.dumps(compact, ensure_ascii=False).encode()) <= AGENT_HANDOFF_BYTES


def test_mixed_facts_do_not_spend_the_entire_handoff_on_observations():
    original = response([row(index) for index in range(23)])
    original["result"]["evidence"][0]["statement"] += " Source-linked explanation." * 80
    original["result"]["observations"] = [
        {"source_key": "dashboard", "subject_id": str(index), "metric": "an_observed_value",
         "current": index, "attributes": {"context": "x" * 700}}
        for index in range(75)
    ]
    before = copy.deepcopy(original)
    compact = _compact_evaluation_response(original)
    assert compact["result"]["observations"]
    assert compact["result"]["evidence"]
    for section, coverage_key in (("observations", "observation_coverage"), ("evidence", "evidence_coverage")):
        coverage = compact["evidence_access"][coverage_key]
        assert coverage["included"] == len(compact["result"][section])
        assert coverage["result_path"] == [section]
    assert original == before
    assert len(json.dumps(compact, ensure_ascii=False).encode()) <= AGENT_HANDOFF_BYTES

"""Compact evaluation handoffs retain normalized facts and page full receipts."""

import copy
import json

from signalweave.mcp_server import (
    AGENT_HANDOFF_BYTES,
    _compact_evaluation_response,
    _receipt_result_page,
)


def observation(index: int, *, verbose: bool = True) -> dict:
    attributes = {
        "source_status": "stale" if index == 4 else "healthy",
        "quality_status": "partial" if index == 4 else "verified",
        "metric_semantics": "conversion_rate",
    }
    if verbose:
        attributes["connector_provenance"] = {
            "raw_chart_payload": "private connector detail " * 500,
        }
    return {
        "source_key": f"source-{index % 3}",
        "subject_id": f"subject-{index}",
        "subject_label": f"Checkout conversion {index}",
        "subject_type": "metric",
        "metric": "checkout_conversion",
        "unit": "percent",
        "current": 0.084,
        "baseline": 0.091,
        "previous": 0.089,
        "change_pct": -7.692,
        "comparison_baselines": {
            "previous_period": 0.091,
            "trailing_4_period_average": 0.09,
        },
        "dimensions": {"region": "west", "device": "mobile"},
        "freshness": "current",
        "source_url": f"https://example.invalid/chart/{index}",
        "attributes": attributes,
    }


def evidence_plan() -> dict:
    return {
        "objective": "Assess the approved source scope.",
        "slots": [{
            "key": "quality:1",
            "role": "quality",
            "source_keys": ["source-1"],
            "required": True,
            "status": "unavailable",
            "evidence_source_keys": [],
        }],
        "status": "blocked",
        "missing_slot_keys": ["quality:1"],
        "conflicting_slot_keys": [],
        "warnings": ["The required source scope is unavailable."],
    }


def test_nine_observation_facts_fit_inline_with_explicit_attribute_omissions():
    observations = [observation(index) for index in range(9)]
    plan = evidence_plan()
    result = {
        "card_id": "card-1",
        "outcome": "investigate",
        "summary": "Review the available observations.",
        "rationale": "One required scope is unavailable.",
        "warnings": ["Do not treat the unavailable scope as empty."],
        "evidence_plan": plan,
        "source_keys": ["source-0", "source-1", "source-2"],
        "observations": observations,
    }
    before = copy.deepcopy(result)
    response = {"result": result, "receipt": {"receipt_id": "receipt-1"}}

    compact = _compact_evaluation_response(response)

    assert len(json.dumps(compact, ensure_ascii=False).encode()) < AGENT_HANDOFF_BYTES
    inline = compact["result"]["observations"]
    assert len(inline) == 9
    assert compact["result"]["outcome"] == result["outcome"]
    assert compact["result"]["warnings"] == result["warnings"]
    assert compact["result"]["evidence_plan"] == plan
    for index, (actual, original) in enumerate(zip(inline, observations, strict=True)):
        for field in (
            "source_key", "subject_id", "subject_label", "subject_type", "metric", "unit",
            "current", "baseline", "previous", "change_pct", "dimensions",
            "comparison_baselines", "freshness", "source_url",
        ):
            assert actual[field] == original[field]
        assert actual["attributes"] == {
            key: original["attributes"][key]
            for key in ("source_status", "quality_status", "metric_semantics")
        }
        assert actual["attributes_omitted"] == {
            "count": 1,
            "keys": ["connector_provenance"],
            "keys_complete": True,
            "receipt_path": ["observations", str(index), "attributes"],
        }
    assert result == before
    full_attributes = _receipt_result_page(
        result, ["observations", "4", "attributes"], offset=0, limit=25
    )
    assert {entry["key"]: entry["value"] for entry in full_attributes["items"]} == observations[4]["attributes"]


def test_large_handoff_includes_bounded_observation_prefix_and_receipt_offset():
    observations = [observation(index, verbose=False) for index in range(400)]
    result = {
        "outcome": "investigate",
        "summary": "Review the available observations.",
        "warnings": ["The full evidence set remains required for interpretation."],
        "evidence_plan": evidence_plan(),
        "observations": observations,
        "evidence": [
            {"source_key": "source-0", "statement": f"Supporting fact {index}: " + "x" * 240}
            for index in range(400)
        ],
    }
    before = copy.deepcopy(result)

    compact = _compact_evaluation_response({
        "result": result,
        "receipt": {"receipt_id": "receipt-large"},
    })

    assert len(json.dumps(compact, ensure_ascii=False).encode()) <= AGENT_HANDOFF_BYTES
    coverage = compact["evidence_access"]["observation_coverage"]
    inline = compact["result"]["observations"]
    assert 0 < len(inline) < len(observations)
    assert len(inline) <= 100
    assert coverage == {
        "result_path": ["observations"],
        "total": 400,
        "included": len(inline),
        "coverage": "partial_section",
        "next_offset": len(inline),
    }
    section = next(
        item for item in compact["evidence_access"]["available_sections"]
        if item["path"] == ["observations"]
    )
    assert section["count"] == len(observations)
    assert compact["result"]["warnings"] == result["warnings"]
    assert compact["result"]["evidence_plan"] == result["evidence_plan"]
    assert result == before

    page = _receipt_result_page(
        result, coverage["result_path"], offset=coverage["next_offset"], limit=25
    )
    assert page["items"][0] == observations[len(inline)]
    assert page["coverage"] == "partial_section"


def test_unfittable_first_observation_is_reported_as_partial_not_empty():
    first = observation(0, verbose=False)
    first["dimensions"] = {"oversized_dimension": "x" * (AGENT_HANDOFF_BYTES * 2)}
    result = {"outcome": "investigate", "observations": [first]}

    compact = _compact_evaluation_response({
        "result": result,
        "receipt": {"receipt_id": "receipt-oversized"},
    })

    coverage = compact["evidence_access"]["observation_coverage"]
    assert compact["result"]["observations"] == []
    assert coverage == {
        "result_path": ["observations"],
        "total": 1,
        "included": 0,
        "coverage": "partial_section",
        "next_offset": 0,
    }
    page = _receipt_result_page(result, ["observations"], offset=0, limit=25)
    assert page["oversized_item"]["path"] == ["observations", "0"]
    assert page["section_complete"] is False

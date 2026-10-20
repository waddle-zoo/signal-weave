"""Deferred judgments retain measured facts without inventing policy conclusions."""

import json
from copy import deepcopy

import pytest

from signalweave.diagnostics import analyze_comparison
from signalweave.getting_started import EVIDENCE_INTERPRETATION
from signalweave.mcp_server import (
    AGENT_HANDOFF_BYTES,
    _compact_evaluation_response,
    _receipt_result_page,
    create_mcp,
)
from tests.test_diagnostics import comparison, rate_comparison
from tests.test_onboarding import make_server, tool


def deferred_response(observations):
    source_key = "ledger-source"
    result = {
        "card_id": "card-generic-facts",
        "outcome": None,
        "judgment": {"status": "deferred", "reason": "payload_limit"},
        "summary": "Some measurements are available; analysis is incomplete.",
        "rationale": "The policy judgment payload exceeded its configured limit.",
        "confidence": None,
        "probabilities": {},
        "watch_results": [{
            "key": "watch:1",
            "status": "unknown",
            "probability": 0.01,
            "probabilities": {"present": 0.01, "absent": 0.01, "unknown": 0.98},
        }],
        "question_results": [{
            "key": "question:1",
            "status": "unknown",
            "probability": 0.02,
        }],
        "source_contracts": [{
            "source_key": source_key,
            "coverage": "partial",
            "comparable": False,
            "action_status": "blocked",
        }],
        "judgment_state": {"observations": observations, "evidence": []},
        "source_by_key": {
            source_key: {
                "adapter": "warehouse",
                "resource": "table:settlements",
                "metadata": {"definition": "settled transaction total", "revision": 3},
                "contract": {"coverage": "partial", "comparable": False},
                "analytical_comparisons": [{
                    "key": "settlements:previous-window",
                    "coverage": "partial",
                    "comparable": False,
                }],
                "observations": observations,
                "evidence": [],
            }
        },
        # Force the real bounded handoff and receipt-backed paging path.
        "oversized_audit_detail": "x" * (AGENT_HANDOFF_BYTES + 2_048),
    }
    return {
        "receipt": {"receipt_id": "receipt-generic-facts"},
        "result": result,
        "policy_action_available": False,
    }


def fact_values(facts, row):
    return dict(zip(facts["fields"], row["values"], strict=True))


@pytest.mark.parametrize("kind,missing_current", [("additive", False), ("rate", False), ("rate", True)])
def test_ordinary_policy_packet_keeps_typed_measurements_separate_from_unknown_watch(kind, missing_current):
    data = comparison() if kind == "additive" else rate_comparison()
    if missing_current:
        data.current_total.denominator = None
    analysis = analyze_comparison("primary", data).model_dump(mode="json")
    response = {
        "receipt": {"receipt_id": "receipt-policy-with-measurements"},
        "result": {"card_id": "generic-policy", "outcome": "insufficient_data" if missing_current else "ignore",
                   "confidence": .9, "probabilities": {"insufficient_data" if missing_current else "ignore": .9},
                   "watch_results": [{"key": "optional", "watch_for": "Context for the business question",
                                      "status": "unknown", "probability": .5}],
                   "analyses": [analysis], "observations": []},
    }
    original = deepcopy(response)
    compact = _compact_evaluation_response(response)
    assert compact["result"] == original["result"]
    assert compact["evidence_interpretation"] == EVIDENCE_INTERPRETATION
    assert response == original
    assert compact["result"]["analyses"][0]["comparison"]["baseline_total"] == data.baseline_total.model_dump(mode="json")
    if missing_current:
        assert analysis["status"] == "insufficient_data"
        assert analysis["baseline"] is None  # The comparison failed, but source totals remain known.
        assert analysis["comparison"]["baseline_total"]["denominator"] == 100
        assert analysis["comparison"]["current_total"]["denominator"] is None


def test_unknown_watch_and_question_do_not_hide_measured_current_values():
    observations = [
        {
            "source_key": "ledger-source",
            "subject_id": "license-count",
            "metric": "active_licenses",
            "unit": "seats",
            "aggregation": "scalar",
            "current": 0,
            "baseline": 4,
        },
        {
            "source_key": "ledger-source",
            "subject_id": "adjustment-total",
            "metric": "net_adjustments",
            "unit": "CAD",
            "aggregation": "additive",
            "current": -12.5,
            "baseline": 2.0,
        },
        {
            "source_key": "ledger-source",
            "subject_id": "approval-rate",
            "metric": "approval_fraction",
            "unit": "ratio",
            "aggregation": "rate",
            "current": 0.72,
            "baseline": 0.64,
        },
    ]
    response = deferred_response(observations)
    original = deepcopy(response)

    compact = _compact_evaluation_response(response)

    assert len(json.dumps(compact, ensure_ascii=False).encode("utf-8")) <= AGENT_HANDOFF_BYTES
    assert compact["evidence_interpretation"] == EVIDENCE_INTERPRETATION
    facts = compact["result"]["observation_facts"]
    assert facts["rows_complete"] is True
    assert [fact_values(facts, row)["current"] for row in facts["rows"]] == [0, -12.5, 0.72]
    assert [fact_values(facts, row)["baseline"] for row in facts["rows"]] == [4, 2.0, 0.64]

    for field in ("watch_results", "question_results"):
        assert {"path": [field], "count": 1} in compact["evidence_access"]["available_sections"]
        page = _receipt_result_page(response["result"], [field], offset=0, limit=10)
        assert page["items"][0]["status"] == "unknown"
    assert compact["result"]["outcome"] is None
    assert compact["policy_action_available"] is False
    assert response == original


def test_known_baseline_survives_missing_current_and_insufficient_analysis():
    observations = [
        {
            "source_key": "ledger-source",
            "subject_id": "settlement-total",
            "metric": "settled_transactions",
            "unit": "transactions",
            "aggregation": "sum",
            "current": None,
            "baseline": 0,
            "analysis_status": "insufficient_data",
        },
        {
            "source_key": "ledger-source",
            "subject_id": "average-hold-time",
            "metric": "average_hold_time",
            "unit": "seconds",
            "aggregation": "rate",
            "baseline": 18.5,
            "analysis_status": "insufficient_data",
        },
    ]
    response = deferred_response(observations)
    original = deepcopy(response)

    compact = _compact_evaluation_response(response)

    facts = compact["result"]["observation_facts"]
    explicit_null, absent_current = facts["rows"]
    explicit_values = fact_values(facts, explicit_null)
    absent_values = fact_values(facts, absent_current)
    assert explicit_values["baseline"] == 0
    assert explicit_values["current"] is None
    assert "current" not in explicit_null.get("missing_fields", [])
    assert absent_values["baseline"] == 18.5
    assert absent_values["current"] is None
    assert "current" in absent_current["missing_fields"]

    assert compact["result"]["outcome"] is None
    assert compact["policy_action_available"] is False
    assert compact["evidence_access"]["complete"] is False
    assert compact["evidence_access"]["observation_facts"]["source_coverage_asserted"] is False
    assert compact["result"]["source_contracts"] == original["result"]["source_contracts"]
    assert compact["evidence_access"]["source_contract_coverage"]["coverage"] == "complete_section"
    assert response == original
    assert compact["result"]["probabilities"] == original["result"]["probabilities"]


def test_bounded_handoff_keeps_hint_and_pages_original_observation_and_source_paths():
    observations = [
        {
            "source_key": "ledger-source",
            "subject_id": f"settlement-{index:03d}",
            "metric": "settled_transactions",
            "unit": "transactions",
            "current": index,
            "baseline": index + 1,
            "dimensions": {"region": f"region-{index % 4}"},
            "attributes": {"batch": f"batch-{index:03d}"},
        }
        for index in range(117)
    ]
    response = deferred_response(observations)

    compact = _compact_evaluation_response(response)

    assert len(json.dumps(compact, ensure_ascii=False).encode("utf-8")) <= AGENT_HANDOFF_BYTES
    assert compact["evidence_interpretation"] == EVIDENCE_INTERPRETATION
    access = compact["evidence_access"]
    assert access["complete"] is False
    assert access["observation_coverage"] == {
        "result_path": ["judgment_state", "observations"],
        "total": len(observations),
        "included": 0,
        "coverage": "partial_section",
        "next_offset": 0,
    }
    assert "observation_facts" in access["instruction"]
    assert "page" in access["instruction"]
    assert "no source or model calls" in access["instruction"]
    assert access["source_directory"] == [{
        "source_key": "ledger-source",
        "snapshot_path": ["source_by_key", "ledger-source"],
        "source_id": "warehouse|table:settlements",
        "metadata_path": ["source_by_key", "ledger-source", "metadata"],
        "contract_path": ["source_by_key", "ledger-source", "contract"],
        "analytical_comparisons_path": [
            "source_by_key", "ledger-source", "analytical_comparisons",
        ],
        "observations_path": ["source_by_key", "ledger-source", "observations"],
        "evidence_path": ["source_by_key", "ledger-source", "evidence"],
    }]
    assert compact["result"]["observation_facts"]["rows"][0]["full_ref"] == [
        "judgment_state", "observations", "0",
    ]

    recovered = []
    offset = 0
    while True:
        page = _receipt_result_page(
            response["result"], access["observation_facts"]["result_path"],
            offset=offset, limit=25,
        )
        recovered.extend(page["items"])
        if not page["has_more"]:
            break
        offset = page["next_offset"]
    assert recovered == observations

    metadata_path = access["source_directory"][0]["metadata_path"]
    metadata_page = _receipt_result_page(response["result"], metadata_path, offset=0, limit=10)
    assert {item["key"]: item["value"] for item in metadata_page["items"]} == {
        "definition": "settled transaction total",
        "revision": 3,
    }


@pytest.mark.parametrize(
    ("profile", "task"),
    [("agent", "monitor"), ("full", "report")],
)
def test_guide_api_and_constructor_instructions_expose_the_interpretation_hint(
    tmp_path, monkeypatch, profile, task,
):
    class NoInference:
        name = "offline-guide-test"

        def __getattr__(self, name):
            raise AssertionError(f"guide unexpectedly requested inference: {name}")

    base = make_server(tmp_path, judger=NoInference())
    runtime = base._test_runtime

    def forbidden_source_call(*args, **kwargs):
        raise AssertionError("guide unexpectedly accessed source data")

    for method in ("list_resources", "inspect", "resolve"):
        monkeypatch.setattr(runtime.sources, method, forbidden_source_call)

    server = base if profile == "full" else create_mcp(runtime, profile=profile)
    guide = tool(server, "get_signalweave_guide")(task=task)

    assert guide["evidence_interpretation"] == EVIDENCE_INTERPRETATION
    assert EVIDENCE_INTERPRETATION in server.instructions

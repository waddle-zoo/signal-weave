"""Serialization fixtures, not coherent business readouts or accuracy trials."""

from copy import deepcopy

import pytest

from evaluations.evidence_first_handoff import evidence_first_handoff
from signalweave.mcp_server import _receipt_result_page
from signalweave.models import Evidence
from signalweave.reporting import InvestigationReport


def slot(role, index=1, *, required=False, question=None):
    return {"key": f"{role}:{index}", "role": role, "required": required, "question": question or f"Question for {role} {index}"}

def judgment(reference, status="unknown"):
    return {"reference": reference, "status": status, "probabilities": {status: 1.0}, "interpretation": "A typed semantic assessment, not a measured fact."}

def handoff(*, slots=None, optional_values=None, evidence=None, report_evidence=None):
    question = "Which approved category explains the measured change?"
    evidence = evidence if evidence is not None else [{"source_key": "source-a", "statement": "A measured source fact.", "values": {"count": 0}}]
    evidence = [Evidence.model_validate(item).model_dump(mode="json") for item in evidence]
    report_evidence = evidence if report_evidence is None else [Evidence.model_validate(item).model_dump(mode="json") for item in report_evidence]
    report = InvestigationReport.model_validate(dict(
        card_id="card-a", title="Offline evidence review", status="partial", outcome="investigate",
        purpose="Review the approved source evidence.", intended_audience="Owner", evidence=deepcopy(report_evidence),
        numeric_claims=[dict(source_key="source-a", comparison_key="approval", metric="approval_fraction", dimension="all", unit="ratio",
            method="symmetric_rate_decomposition_v1", claim_type="accounting_decomposition", baseline=0.5, current=0.4, delta=-0.1, residual=0,
            provenance_key='["source-a","approval"]')],
        provenance=[dict(source_key="source-a", comparison_key="approval", query_refs=["offline-query"], definition="A measured approval fraction.",
            population="fixture population", metric="approval_fraction", dimension="all", unit="ratio",
            baseline_period=dict(start="2026-10-01T00:00:00Z", end="2026-10-08T00:00:00Z"), current_period=dict(start="2026-10-08T00:00:00Z", end="2026-10-15T00:00:00Z"),
            coverage="complete", comparable=True, input_digest="offline-digest")],
        coverage=[dict(key="watch:1", kind="watch", required=False, status="unresolved"), dict(key="question:1", kind="question", required=False, status="unresolved")],
        judgments=[judgment(k, s) for k, s in (("outcome", "investigate"), ("watch_0", "unknown"), ("watch_1", "unknown"), ("question:1", "unknown"), ("unmapped-reference", "unknown"))],
        unresolved_questions=[question, "A separate unresolved note with similar wording."], blockers=[dict(code="source_limit", message="The source boundary remains limited.")],
        warnings=["Keep the populations separate."], limitations=["No causal conclusion is established."],
        source_boundaries=[dict(source_key="source-a", adapter="offline", resource="fixture:source-a", scope="approved subset", population="fixture population",
            grain="day", scope_status="declared", population_status="declared", grain_status="declared", source_status="healthy")],
        numeric_conditions=[dict(condition_text="Approval fraction below threshold", source_key="source-a", comparison_key="approval", measurement="current",
            comparator="<", threshold=0.5, status="true", value=0.4, expected_unit="ratio")],
        intended_routes_not_delivered=[dict(key="owner", outcome="investigate", label="Owner", destination="offline://owner", reason="Review the result.")],
        evaluated_at="2026-10-15T12:00:00Z", evaluator="offline-fixture",
    )).model_dump(mode="json")
    return {
        "receipt": {"receipt_id": "receipt-a", "card_id": "card-a"},
        "result": {
            "card_id": "card-a",
            "outcome": "investigate",
            "summary": "Source measurements require review.",
            "evidence": deepcopy(evidence),
            "analyses": [{"kind": "rate", "current": 0.4, "baseline": None}],
            "observations": [{"aggregation": "additive", "current": 0, "baseline": None}, {"aggregation": "rate", "numerator": 4, "denominator": None, "current": 0.4},
                {"aggregation": "scalar", "current": None, "baseline": 0}],
            "card": {"id": "card-a", "policy": "reviewed"},
            "policy": {"action_available": False},
            "routes": [{"key": "owner", "outcome": "investigate"}],
            "evidence_plan": {"slots": slots if slots is not None else [slot("watch"), slot("question", question=question)]},
            "report": report,
        },
        "optional_policy_diagnostics": {"values": optional_values if optional_values is not None else {
            "watch_results": [{"key": "watch_0", "status": "unknown"}], "question_results": [{"key": "question:1", "status": "unknown"}],}},
    }


def paths(audit):
    return {tuple(section["result_path"]) for section in audit["receipt_sections"]}


def test_moves_report_to_audit_preserves_measurements_and_pages_exact_original_paths():
    original = handoff()
    original["result"]["judgment"] = None
    before = deepcopy(original)
    original_result = original["result"]

    compact = evidence_first_handoff(original)

    assert compact is not original and compact["result"] is not original_result
    assert original == before
    assert "report" not in compact["result"]
    audit = compact["report_audit"]
    assert set(audit) == {"scope", "summary", "receipt_sections", "instruction"}
    assert audit["scope"] and audit["instruction"]
    report = audit["summary"]
    expected_report = deepcopy(before["result"]["report"])
    expected_report.pop("evidence")
    expected_report["judgments"] = [item for item in expected_report["judgments"] if item["reference"] not in {"watch_0", "question:1"}]
    expected_report["unresolved_questions"] = ["A separate unresolved note with similar wording."]
    assert report == expected_report
    expected_paths = {("report", "evidence"), ("report", "judgments"), ("report", "unresolved_questions"),
                      ("watch_results",), ("question_results",)}
    assert paths(audit) == expected_paths
    receipt_result = deepcopy(before["result"])
    receipt_result.update(before["optional_policy_diagnostics"]["values"])
    paged = {}
    for path in expected_paths:
        paged[path] = _receipt_result_page(receipt_result, list(path), offset=0, limit=25)["items"]
        assert paged[path]
    assert paged[("report", "evidence")] == before["result"]["report"]["evidence"]
    assert paged[("watch_results",)] == before["optional_policy_diagnostics"]["values"]["watch_results"]
    assert paged[("question_results",)] == before["optional_policy_diagnostics"]["values"]["question_results"]
    assert set(compact["result"]) == set(before["result"]) - {"report"}
    assert all(compact["result"][field] == before["result"][field] for field in
               ("judgment", "outcome", "summary", "evidence", "analyses", "observations", "card", "policy", "routes", "evidence_plan"))
    assert compact["receipt"] == before["receipt"]
    assert compact["optional_policy_diagnostics"] == {
        "values": {}, "omitted_optional_results": ["question_results", "watch_results"]
    }
    compact["result"]["observations"][0]["current"] = 100
    assert original["result"]["observations"][0]["current"] == 0


def test_evidence_deduplication_uses_type_sensitive_json_identity_and_preserves_unique_facts():
    primary = {"source_key": "source-a", "statement": "Typed count.", "values": {"count": 1}}
    unique = {"source_key": "source-a", "statement": "Additional fact.", "values": {"count": 2}}
    ordered = {"source_key": "source-a", "statement": "Ordered fields.", "values": {"first": 1, "second": 2}}
    cases = [([primary, unique], False), ([{**primary, "values": {"count": True}}], False),
             ([{**primary, "values": {"count": 1.0}}], False),
             ([{**ordered, "values": {"second": 2, "first": 1}}], True)]
    for report_facts, duplicate in cases:
        compact = evidence_first_handoff(handoff(evidence=[primary] if not duplicate else [ordered], report_evidence=report_facts))
        report = compact["report_audit"]["summary"]
        if duplicate:
            assert "evidence" not in report and ("report", "evidence") in paths(compact["report_audit"])
        else:
            assert report["evidence"] == [Evidence.model_validate(item).model_dump(mode="json") for item in report_facts]
            assert type(report["evidence"][0]["values"].get("count")) is type(report_facts[0]["values"].get("count"))
            assert ("report", "evidence") not in paths(compact["report_audit"])
    assert type(cases[1][0][0]["values"]["count"]) is bool
    assert type(cases[2][0][0]["values"]["count"]) is float


@pytest.mark.parametrize("case", ["unknown", "required", "mixed", "bad_alias", "ambiguous_text"])
def test_unproved_optional_semantics_and_unmapped_records_stay_inline(case):
    question = "Which approved category explains the measured change?"
    if case == "unknown":
        original = handoff(optional_values={"watch_results": [{"key": "invented", "status": "unknown"}], "question_results": [{"key": "question:1", "status": "unknown"}]})
    elif case == "required":
        original = handoff(slots=[slot("watch", required=True), slot("question", question=question)], optional_values={"watch_results": [{"key": "watch_0"}], "question_results": [{"key": "question:1"}]})
    elif case == "mixed":
        original = handoff(slots=[slot("watch"), slot("watch", 2, required=True)], optional_values={"watch_results": [{"key": "watch_0"}, {"key": "watch_1"}], "question_results": [{"key": "question:1"}]})
    elif case == "bad_alias":
        original = handoff(optional_values={"watch_results": [{"key": "watch_1"}], "question_results": [{"key": "question:1"}]})
    else:
        original = handoff(slots=[slot("watch"), slot("question", question=question), slot("question", 2, question=question)],
                           optional_values={"watch_results": [{"key": "watch_0"}], "question_results": [{"key": "question:1"}, {"key": "question_1"}]})
    before = deepcopy(original)

    compact = evidence_first_handoff(original)
    assert original == before
    audit = compact["report_audit"]
    expected_refs = ["outcome", "watch_0", "watch_1", "unmapped-reference"]
    if case == "mixed":
        # This fixture has no question slot, so its question result is unmapped.
        expected_refs.insert(-1, "question:1")
    if case == "ambiguous_text":
        expected_refs.remove("watch_0")
    assert [item["reference"] for item in audit["summary"]["judgments"]] == expected_refs
    unresolved = audit["summary"]["unresolved_questions"]
    values = compact["optional_policy_diagnostics"]["values"]
    if case == "ambiguous_text":
        assert unresolved == before["result"]["report"]["unresolved_questions"]
        removed = ["question_results", "watch_results"]
    elif case == "mixed":
        assert unresolved == before["result"]["report"]["unresolved_questions"]
        removed = []
    else:
        assert unresolved == ["A separate unresolved note with similar wording."]
        removed = ["question_results"]
    expected_values = deepcopy(before["optional_policy_diagnostics"]["values"])
    for field in removed:
        expected_values.pop(field)
    assert values == expected_values
    assert compact["optional_policy_diagnostics"].get("omitted_optional_results", []) == removed


@pytest.mark.parametrize("fallback", ["no_receipt", "wrong_receipt_card", "paged", "deferred", "bad_plan", "bad_judgment"])
def test_receipt_or_shape_gates_return_an_unchanged_copy(fallback):
    original = handoff()
    changes = {
        "no_receipt": lambda: original.pop("receipt"),
        "wrong_receipt_card": lambda: original["receipt"].update(card_id="other-card"),
        "paged": lambda: original.update(evidence_access={"complete": False}),
        "deferred": lambda: original["result"].update(judgment={"status": "deferred"}),
        "bad_judgment": lambda: original["result"].update(judgment="malformed"),
        "bad_plan": lambda: original["result"]["evidence_plan"].update(slots="malformed"),
    }
    changes[fallback]()
    before = deepcopy(original)

    compact = evidence_first_handoff(original)
    assert compact == before
    assert compact is not original


def test_report_with_unrecognized_extra_field_is_conservatively_unchanged():
    original = handoff()
    original["result"]["report"]["future_audit_field"] = {"preserve": ["unknown", "as authored"]}
    before = deepcopy(original)

    compact = evidence_first_handoff(original)
    assert compact == before
    assert "report_audit" not in compact


@pytest.mark.parametrize("field", ["watch_results", "question_results"])
def test_diagnostic_group_also_present_in_primary_result_keeps_whole_projection(field):
    original = handoff()
    original["result"][field] = [{"key": "conflicting-primary-copy", "status": "unknown"}]
    before = deepcopy(original)

    compact = evidence_first_handoff(original)

    assert compact == before

"""Optional criterion judgments are labeled without changing policy or receipts."""

import copy
from datetime import datetime, timezone

import pytest

from signalweave.diagnostics import AnalyticalComparison, analyze_comparison
from signalweave.mcp_server import (
    AGENT_HANDOFF_BYTES,
    _compact_evaluation_response,
    _json_bytes,
    _receipt_result_page,
    _separate_optional_judgments,
)
from signalweave.models import (
    Evidence,
    EvidencePlan,
    EvidenceSlot,
    InsightResult,
    Outcome,
    QuestionResult,
    QuestionStatus,
    WatchResult,
    WatchStatus,
    WorkflowHandoff,
)
from signalweave.reporting import InvestigationReport, ReportIssue


def slot(role: str, index: int = 1, *, required: bool = False) -> dict:
    return EvidenceSlot(
        key=f"{role}:{index}",
        role=role,
        question="An offline fixture criterion.",
        required=required,
    ).model_dump(mode="json")


def typed_judgment(role: str, key: str, status: str) -> dict:
    if role == "watch":
        watch_status = WatchStatus(status)
        probabilities = {
            WatchStatus.PRESENT: {
                WatchStatus.PRESENT: 0.90,
                WatchStatus.ABSENT: 0.05,
                WatchStatus.UNKNOWN: 0.05,
            },
            WatchStatus.ABSENT: {
                WatchStatus.PRESENT: 0.05,
                WatchStatus.ABSENT: 0.90,
                WatchStatus.UNKNOWN: 0.05,
            },
            WatchStatus.UNKNOWN: {
                WatchStatus.PRESENT: 0.25,
                WatchStatus.ABSENT: 0.25,
                WatchStatus.UNKNOWN: 0.50,
            },
        }
        distribution = probabilities[watch_status]
        value = WatchResult(
            key=key,
            watch_for="An offline fixture condition.",
            status=watch_status,
            probability=distribution[WatchStatus.PRESENT],
            probabilities=distribution,
        )
    else:
        question_status = QuestionStatus(status)
        probability = {
            QuestionStatus.SUPPORTED: 0.90,
            QuestionStatus.NOT_SUPPORTED: 0.10,
            QuestionStatus.UNKNOWN: 0.50,
        }[question_status]
        value = QuestionResult(
            key=key,
            question="What does the offline fixture establish?",
            status=question_status,
            probability=probability,
        )
    return value.model_dump(mode="json")


def typed_result(
    *,
    watch_results: list[dict] | None = None,
    question_results: list[dict] | None = None,
    evidence_slots: list[dict] | None = None,
    **fields,
) -> dict:
    slots = [EvidenceSlot.model_validate(item) for item in evidence_slots or []]
    evidence_plan = EvidencePlan(
        objective="Resolve the offline fixture evidence plan.",
        slots=slots,
        status="blocked" if any(item.required for item in slots) else "incomplete",
        missing_slot_keys=[item.key for item in slots if item.required],
    )
    payload = {
        "card_id": "offline-fixture-card",
        "outcome": Outcome.INVESTIGATE,
        "summary": "An offline typed result fixture.",
        "rationale": "Preserve this value during compact presentation.",
        "evaluator": "offline-fixture",
        "watch_results": watch_results or [],
        "question_results": question_results or [],
        "evidence_plan": evidence_plan,
    }
    payload.update(fields)
    return InsightResult.model_validate(payload).model_dump(mode="json")


def compact_response(result: dict) -> dict:
    return _compact_evaluation_response(
        {
            "receipt": {"receipt_id": "receipt-fixture"},
            "result": result,
        }
    )


@pytest.mark.parametrize(
    ("role", "field", "status"),
    [
        ("watch", "watch_results", WatchStatus.PRESENT.value),
        ("watch", "watch_results", WatchStatus.ABSENT.value),
        ("watch", "watch_results", WatchStatus.UNKNOWN.value),
        ("question", "question_results", QuestionStatus.SUPPORTED.value),
        ("question", "question_results", QuestionStatus.NOT_SUPPORTED.value),
        ("question", "question_results", QuestionStatus.UNKNOWN.value),
    ],
)
@pytest.mark.parametrize(
    "alias_format",
    [
        pytest.param("{role}_0", id="role-index-zero"),
        pytest.param("{role}:1", id="canonical-key"),
        pytest.param("0", id="literal-zero"),
    ],
)
def test_typed_optional_results_move_for_each_role_alias_and_status(
    role, field, status, alias_format
):
    alias = alias_format.format(role=role)
    value = typed_judgment(role, alias, status)
    original = typed_result(
        watch_results=[value] if role == "watch" else [],
        question_results=[value] if role == "question" else [],
        evidence_slots=[slot(role)],
    )

    compact = compact_response(copy.deepcopy(original))

    assert compact["optional_policy_diagnostics"]["values"] == {field: [value]}
    assert field not in compact["result"]
    restored = {
        **compact["result"],
        **compact["optional_policy_diagnostics"]["values"],
    }
    assert restored == original
    assert _json_bytes(compact) <= AGENT_HANDOFF_BYTES


def test_mixed_required_and_optional_group_stays_whole_while_other_group_moves():
    for mixed_role in ("watch", "question"):
        other_role = "question" if mixed_role == "watch" else "watch"
        mixed_field = f"{mixed_role}_results"
        other_field = f"{other_role}_results"
        mixed_statuses = (
            [WatchStatus.PRESENT.value, WatchStatus.ABSENT.value]
            if mixed_role == "watch"
            else [QuestionStatus.SUPPORTED.value, QuestionStatus.NOT_SUPPORTED.value]
        )
        mixed_values = [
            typed_judgment(mixed_role, f"{mixed_role}_{index}", status)
            for index, status in enumerate(mixed_statuses)
        ]
        other_values = [typed_judgment(other_role, f"{other_role}_0", "unknown")]
        original = typed_result(
            watch_results=mixed_values if mixed_role == "watch" else other_values,
            question_results=mixed_values if mixed_role == "question" else other_values,
            evidence_slots=[
                slot(mixed_role, 1, required=False),
                slot(mixed_role, 2, required=True),
                slot(other_role, 1, required=False),
            ],
        )

        compact = compact_response(copy.deepcopy(original))

        assert compact["result"][mixed_field] == mixed_values
        assert compact["optional_policy_diagnostics"]["values"] == {other_field: other_values}


def test_typed_result_and_report_fields_and_receipt_pages_are_unchanged():
    evaluated_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    slots = [
        slot("watch", required=False),
        slot("question", required=False),
        slot("primary", required=True),
        slot("quality", required=True),
    ]
    evidence_plan = EvidencePlan(
        objective="Resolve the offline fixture evidence plan.",
        slots=[EvidenceSlot.model_validate(item) for item in slots],
        status="blocked",
        missing_slot_keys=["primary:1", "quality:1"],
    )
    comparison = AnalyticalComparison(
        key="fixture-comparison",
        metric="fixture-measure",
        definition="A synthetic measure used only to validate the report shape.",
        population="The offline fixture population.",
        unit="count",
        dimension="category",
        kind="additive",
        baseline_start=datetime(2026, 9, 1, tzinfo=timezone.utc),
        baseline_end=datetime(2026, 9, 8, tzinfo=timezone.utc),
        current_start=datetime(2026, 9, 8, tzinfo=timezone.utc),
        current_end=datetime(2026, 9, 15, tzinfo=timezone.utc),
        coverage="complete",
        disjoint_segments=True,
        comparable=True,
        query_refs=["fixture-query"],
        baseline_total={"value": 10},
        current_total={"value": 12},
        segments=[{"segment": "all", "baseline": {"value": 10}, "current": {"value": 12}}],
    )
    analysis = analyze_comparison("source-a", comparison)
    workflow = WorkflowHandoff(
        status="blocked",
        step_key="offline-fixture-step",
        action="retrieve_evidence",
        objective="Resolve the required offline fixture slots.",
        instructions="Inspect the authorized fixture evidence.",
        required_source_keys=["source-a"],
        evidence_plan=evidence_plan,
    )
    report = InvestigationReport(
        card_id="offline-fixture-card",
        title="Offline fixture report",
        outcome=Outcome.INVESTIGATE.value,
        purpose="Preserve a validated report payload.",
        intended_audience="Test caller",
        status="blocked",
        blockers=[
            ReportIssue(
                code="required_evidence_unresolved",
                message="A required fixture slot remains unresolved.",
                reference="quality:1",
            )
        ],
        warnings=["The report retains its unresolved fixture warning."],
        evaluated_at=evaluated_at,
        evaluator="offline-fixture",
    )
    watch_values = [typed_judgment("watch", "watch_0", WatchStatus.UNKNOWN.value)]
    question_values = [typed_judgment("question", "question:1", QuestionStatus.UNKNOWN.value)]
    original = typed_result(
        watch_results=watch_values,
        question_results=question_values,
        evidence_slots=slots,
        evidence_plan=evidence_plan,
        outcome=Outcome.INVESTIGATE,
        probabilities={"ignore": 0.1, "investigate": 0.8, "notify": 0.1},
        analyses=[analysis],
        workflow=workflow,
        evaluated_at=evaluated_at,
    )
    original["report"] = report.model_dump(mode="json")
    response = {"receipt": {"receipt_id": "receipt-fixture"}, "result": original}
    before = copy.deepcopy(response)
    watch_page_before = _receipt_result_page(original, ["watch_results"], 0, 10)
    question_page_before = _receipt_result_page(original, ["question_results"], 0, 10)

    compact = compact_response(response["result"])

    expected_inline = {
        key: value
        for key, value in original.items()
        if key not in {"watch_results", "question_results"}
    }
    restored_inline = copy.deepcopy(compact["result"])
    for parent, field in (("report", "evidence"), ("workflow", "evidence_plan")):
        assert restored_inline[parent].pop(f"{field}_ref") == {"result_path": [field]}
        restored_inline[parent][field] = copy.deepcopy(restored_inline[field])
    assert restored_inline == expected_inline
    assert compact["optional_policy_diagnostics"]["values"] == {
        "watch_results": watch_values,
        "question_results": question_values,
    }
    assert compact["result"]["outcome"] == original["outcome"]
    assert compact["result"]["probabilities"] == original["probabilities"]
    assert compact["result"]["analyses"] == original["analyses"]
    assert restored_inline["workflow"] == original["workflow"]
    assert compact["result"]["evidence_plan"] == original["evidence_plan"]
    assert compact["result"]["report"]["blockers"] == original["report"]["blockers"]
    assert compact["result"]["report"]["warnings"] == original["report"]["warnings"]
    restored = {
        **restored_inline,
        **compact["optional_policy_diagnostics"]["values"],
    }
    assert restored == original
    assert response == before
    assert _receipt_result_page(original, ["watch_results"], 0, 10) == watch_page_before
    assert _receipt_result_page(original, ["question_results"], 0, 10) == question_page_before


def test_legacy_malformed_and_unmapped_groups_remain_inline():
    """Malformed raw payloads here are intentional negative-coverage fixtures."""
    value = typed_judgment("watch", "watch_0", WatchStatus.UNKNOWN.value)
    valid_plan = EvidencePlan(
        objective="Resolve the offline fixture evidence plan.",
        slots=[EvidenceSlot.model_validate(slot("watch"))],
    ).model_dump(mode="json")
    unknown_key = typed_judgment("watch", "unmapped-criterion", WatchStatus.UNKNOWN.value)
    cases = [
        {"watch_results": [value]},
        {"evidence_plan": None, "watch_results": [value]},
        {"evidence_plan": {"slots": "invalid"}, "watch_results": [value]},
        {"evidence_plan": valid_plan, "watch_results": ["invalid"]},
        typed_result(
            watch_results=[unknown_key],
            evidence_slots=[slot("watch")],
        ),
    ]

    for result in cases:
        compact = compact_response(copy.deepcopy(result))
        assert "optional_policy_diagnostics" not in compact
        assert compact["result"] == result


def test_missing_or_nonoptional_requirement_does_not_move_the_group():
    value = typed_judgment("watch", "watch_0", WatchStatus.UNKNOWN.value)
    for requirement in ("missing", None, True):
        criterion = slot("watch")
        if requirement == "missing":
            criterion.pop("required")
        else:
            criterion["required"] = requirement
        result = {"evidence_plan": {"slots": [criterion]}, "watch_results": [value]}

        compact = compact_response(copy.deepcopy(result))

        assert "optional_policy_diagnostics" not in compact
        assert compact["result"] == result


def test_reordered_results_and_duplicate_slot_keys_remain_inline():
    values = [
        typed_judgment("watch", "watch_1", WatchStatus.UNKNOWN.value),
        typed_judgment("watch", "watch_0", WatchStatus.UNKNOWN.value),
    ]
    cases = [
        typed_result(
            watch_results=values,
            evidence_slots=[slot("watch", 1), slot("watch", 2)],
        ),
        typed_result(
            watch_results=values,
            evidence_slots=[slot("watch", 1), slot("watch", 1)],
        ),
    ]

    for result in cases:
        compact = compact_response(copy.deepcopy(result))
        assert "optional_policy_diagnostics" not in compact
        assert compact["result"] == result


def test_near_limit_presentation_falls_back_without_changing_typed_result():
    value = typed_judgment("watch", "watch_0", WatchStatus.UNKNOWN.value)
    result = typed_result(
        watch_results=[value],
        evidence_slots=[slot("watch")],
        rationale="",
    )
    compact = {"receipt": {"receipt_id": "receipt-fixture"}, "result": result}
    result["rationale"] = "x" * (AGENT_HANDOFF_BYTES - _json_bytes(compact) - 1)
    InsightResult.model_validate(result)
    before = copy.deepcopy(compact)
    assert _json_bytes(compact) == AGENT_HANDOFF_BYTES - 1

    returned = _separate_optional_judgments(compact)

    assert returned is compact
    assert returned == before
    assert "optional_policy_diagnostics" not in returned


def test_oversized_typed_handoff_keeps_receipt_paging_path_lossless():
    value = typed_judgment("watch", "watch_0", WatchStatus.UNKNOWN.value)
    evidence = [
        Evidence(subject_id=str(index), statement="x" * 300).model_dump(mode="json")
        for index in range(400)
    ]
    result = typed_result(
        watch_results=[value],
        evidence_slots=[slot("watch")],
        outcome=Outcome.INVESTIGATE,
        evidence=evidence,
    )
    response = {"receipt": {"receipt_id": "receipt-large"}, "result": result}
    before = copy.deepcopy(response)

    compact = _compact_evaluation_response(response)

    assert _json_bytes(compact) <= AGENT_HANDOFF_BYTES
    assert "optional_policy_diagnostics" not in compact
    assert compact["evidence_access"]["complete"] is False
    sections = {
        tuple(section["path"]): section["count"]
        for section in compact["evidence_access"]["available_sections"]
    }
    assert sections[("watch_results",)] == len(result["watch_results"])
    assert sections[("evidence",)] == len(evidence)
    assert response == before

    recovered = []
    offset = 0
    while True:
        page = _receipt_result_page(result, ["evidence"], offset, 100)
        recovered.extend(page["items"])
        if not page["has_more"]:
            break
        offset = page["next_offset"]
    assert recovered == evidence
    watch_page = _receipt_result_page(result, ["watch_results"], 0, 10)
    assert watch_page["items"] == result["watch_results"]

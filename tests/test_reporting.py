from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from signalweave.diagnostics import AnalyticalComparison, analyze_comparison
from signalweave.models import InsightCard, InsightResult, ResourceSnapshot
from signalweave.reporting import (
    build_investigation_report,
    render_investigation_report,
)


def comparison(**updates) -> AnalyticalComparison:
    payload = {
        "key": "volume-by-channel",
        "metric": "volume",
        "definition": "Completed activity in the approved population",
        "population": "Eligible population",
        "unit": "count",
        "dimension": "channel",
        "kind": "additive",
        "baseline_start": "2026-08-01T00:00:00Z",
        "baseline_end": "2026-08-08T00:00:00Z",
        "current_start": "2026-08-08T00:00:00Z",
        "current_end": "2026-08-15T00:00:00Z",
        "comparison_window": "previous_period",
        "coverage": "complete",
        "disjoint_segments": True,
        "comparable": True,
        "query_refs": ["query:volume-total", "query:volume-segments"],
        "baseline_total": {"value": 100},
        "current_total": {"value": 80},
        "segments": [
            {"segment": "online", "baseline": {"value": 60}, "current": {"value": 30}},
            {"segment": "store", "baseline": {"value": 40}, "current": {"value": 50}},
        ],
    }
    payload.update(updates)
    return AnalyticalComparison.model_validate(payload)


def card(*, optional_source: bool = False, question: bool = False) -> InsightCard:
    return InsightCard(
        id="sales-card",
        title="Sales <pulse> | weekly",
        what_to_watch="Approved volume movement",
        why_watch="Bound the measured change for review",
        questions=["Which approved question remains unresolved?"] if question else [],
        evidence_requirements={"question:1": False} if question else {},
        sources=[
            {
                "key": "sales",
                "adapter": "test",
                "resource": "query:sales",
                "label": "Sales query",
                "required": not optional_source,
                "required_comparison_keys": ["volume-by-channel"],
            }
        ],
        delivery_methods=[
            {
                "key": "owner",
                "outcome": "notify",
                "label": "Owner",
                "destination": "slack://owner|weekly",
            }
        ],
    )


def result(*analyses, **updates) -> InsightResult:
    payload = {
        "card_id": "sales-card",
        "outcome": "notify",
        "summary": "Jev says this is notable.",
        "rationale": "Jev says the owner should review it.",
        "source_keys": ["sales"],
        "analyses": list(analyses),
        "evidence_plan": {
            "objective": "Bounded source evidence",
            "slots": [],
            "status": "complete",
        },
        "delivery_methods": [
            {
                "key": "owner",
                "outcome": "notify",
                "label": "Owner",
                "destination": "slack://owner|weekly",
            }
        ],
        "evaluator": "jev-test-double",
    }
    payload.update(updates)
    return InsightResult.model_validate(payload)


def healthy_resources(*, source_status: str = "healthy", error: str | None = None):
    return [ResourceSnapshot(
        source_key="sales",
        adapter="test",
        resource="query:sales",
        title="Sales query",
        error=error,
        contract={"source_status": source_status},
    )]


def complete_analysis(*, required: bool = True):
    return analyze_comparison("sales", comparison()).model_copy(update={"required": required})


def test_complete_report_contains_only_recomputed_numeric_facts_and_provenance():
    report = build_investigation_report(
        card(), result(complete_analysis()), resources=healthy_resources()
    )

    assert report.status == "complete"
    assert len(report.numeric_claims) == 1
    claim = report.numeric_claims[0]
    assert (claim.baseline, claim.current, claim.delta) == (100, 80, -20)
    assert claim.provenance_key == '["sales","volume-by-channel"]'
    assert report.provenance[0].query_refs == ["query:volume-total", "query:volume-segments"]
    assert report.provenance[0].definition.startswith("Completed activity")
    assert report.model_dump()["status"] == "complete"
    assert "caus" in " ".join(report.limitations).lower()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda analysis: analysis.model_copy(update={"delta": float("nan")}),
        lambda analysis: analysis.model_copy(update={"current": float("inf")}),
        lambda analysis: analysis.model_copy(update={"baseline": None}),
    ],
)
def test_invalid_or_invented_numeric_fields_block_and_are_not_claimed(mutation):
    analysis = mutation(complete_analysis())
    report = build_investigation_report(card(), result(analysis), resources=healthy_resources())

    assert report.status == "blocked"
    assert report.numeric_claims == []
    assert any(item.code == "invalid_analysis" for item in report.blockers)


def test_duplicate_analysis_identity_blocks_instead_of_deduplicating():
    analysis = complete_analysis()
    report = build_investigation_report(card(), result(analysis, deepcopy(analysis)))

    assert report.status == "blocked"
    assert report.numeric_claims == []
    assert any(item.code == "duplicate_analysis" for item in report.blockers)


def test_duplicate_segments_are_recomputed_as_insufficient_data():
    duplicate = comparison().model_copy(
        update={
            "segments": [
                comparison().segments[0],
                comparison().segments[0],
            ]
        }
    )
    analysis = analyze_comparison("sales", duplicate)
    report = build_investigation_report(card(), result(analysis))

    assert report.status == "blocked"
    assert report.numeric_claims == []
    assert any(item.code == "required_analysis_insufficient_data" for item in report.blockers)


def test_missing_required_source_and_insufficient_data_block():
    report = build_investigation_report(card(), result(source_keys=[], analyses=[]))

    assert report.status == "blocked"
    assert any(item.code == "required_source_missing" for item in report.blockers)
    assert not any(item.code == "required_analysis_insufficient_data" for item in report.blockers)


def test_failed_required_source_is_not_overridden_by_summary_or_confidence():
    report = build_investigation_report(
        card(),
        result(
            summary="Everything is healthy and complete.",
            rationale="Confidence proves the source is usable.",
            confidence=0.99,
            evidence_plan={
                "objective": "Required source evidence",
                "slots": [{
                    "key": "primary",
                    "role": "primary",
                    "question": "Fetch the approved comparison",
                    "source_keys": ["sales"],
                    "required": True,
                    "status": "unavailable",
                }],
                "status": "blocked",
            },
        ),
    )

    assert report.status == "blocked"
    assert report.numeric_claims == []
    assert any(item.code == "required_source_failed" for item in report.blockers)


def test_optional_missing_work_is_partial_not_complete():
    optional = card(optional_source=True)
    no_analysis = result(analyses=[], source_keys=[])
    report = build_investigation_report(optional, no_analysis)

    assert report.status == "partial"
    assert report.numeric_claims == []
    assert not report.blockers
    assert any("optional" in warning.lower() for warning in report.warnings)


@pytest.mark.parametrize("source_status", ["failed", "stale", "ambiguous"])
def test_required_unhealthy_source_cannot_be_complete_even_with_valid_arithmetic(source_status):
    report = build_investigation_report(
        card(),
        result(complete_analysis()),
        resources=healthy_resources(source_status=source_status),
    )

    assert report.status == "blocked"
    assert report.numeric_claims
    assert any(item.code == "required_source_failed" for item in report.blockers)


def test_optional_source_health_failure_is_partial():
    report = build_investigation_report(
        card(optional_source=True),
        result(complete_analysis()),
        resources=healthy_resources(source_status="failed", error="adapter failed"),
    )

    assert report.status == "partial"
    assert report.blockers == []
    assert any("optional source" in item.lower() for item in report.warnings)


def test_missing_resources_warns_that_source_health_is_unassessed():
    report = build_investigation_report(card(), result(complete_analysis()))

    assert report.status == "partial"
    assert any("unassessed" in item.lower() for item in report.warnings)


def test_required_evidence_slot_blocks_optional_slot_only_warns():
    required_card = card()
    required_result = result(
        complete_analysis(),
        evidence_plan={
            "objective": "Answer the bounded question",
            "slots": [{
                "key": "question:1",
                "role": "question",
                "question": "Required answer",
                "required": True,
                "status": "pending",
            }],
            "status": "incomplete",
        },
    )
    required_card.questions = ["Required answer"]
    required_card.evidence_requirements = {"question:1": True}
    blocked = build_investigation_report(required_card, required_result)
    assert blocked.status == "blocked"
    assert any(item.code == "required_evidence_missing" for item in blocked.blockers)

    optional_result = result(
        complete_analysis(),
        evidence_plan={
            "objective": "Answer the optional question",
            "slots": [{
                "key": "question:1",
                "role": "question",
                "question": "Optional answer",
                "required": False,
                "status": "pending",
            }],
            "status": "incomplete",
        },
    )
    optional_card = card(question=True)
    optional = build_investigation_report(optional_card, optional_result)
    assert optional.status == "partial"
    assert optional.blockers == []


def test_markdown_escapes_untrusted_text_and_states_limits():
    report = build_investigation_report(
        card(), result(complete_analysis()), resources=healthy_resources()
    )
    markdown = render_investigation_report(report)

    assert "&lt;pulse&gt;" in markdown
    assert "\\|" in markdown
    assert "not establish causality" in markdown
    assert "Jev says" not in markdown
    assert "<pulse>" not in markdown


def test_markdown_escapes_link_and_emphasis_metacharacters():
    hostile = card().model_copy(update={"title": "[click](https://bad) *bold*! _italics_"})
    markdown = render_investigation_report(
        build_investigation_report(hostile, result(complete_analysis()), healthy_resources())
    )
    assert r"\[click\]\(https://bad\) \*bold\*\! \_italics\_" in markdown


def test_report_models_reject_extra_fields():
    report = build_investigation_report(card(), result(complete_analysis()))
    with pytest.raises(ValidationError):
        type(report).model_validate({**report.model_dump(), "not_allowed": "value"})


def test_colon_containing_analysis_identities_do_not_collide():
    first = analyze_comparison("source:one", comparison(key="comparison:shared"))
    second = analyze_comparison("source", comparison(key="one:comparison:shared"))
    payload = card().model_dump()
    payload["sources"] = [
        {**payload["sources"][0], "key": "source:one", "required_comparison_keys": ["comparison:shared"]},
        {**payload["sources"][0], "key": "source", "required_comparison_keys": ["one:comparison:shared"]},
    ]
    report = build_investigation_report(
        InsightCard.model_validate(payload),
        result(first, second, source_keys=["source:one", "source"]),
        resources=[
            ResourceSnapshot(source_key="source:one", adapter="test", resource="one", title="one"),
            ResourceSnapshot(source_key="source", adapter="test", resource="two", title="two"),
        ],
    )
    assert report.status == "complete"
    assert len(report.numeric_claims) == 2


def test_selected_routes_are_not_sent_but_do_not_downgrade_good_report():
    report = build_investigation_report(
        card(), result(complete_analysis()), resources=healthy_resources()
    )
    assert report.status == "complete"
    assert report.intended_routes_not_delivered[0].reason == "Caller owns delivery; not sent."


def test_changed_endpoint_and_foreign_route_are_blockers_not_new_routes():
    changed = result(
        complete_analysis(),
        delivery_methods=[{
            "key": "owner",
            "outcome": "notify",
            "label": "Owner",
            "destination": "slack://foreign-endpoint",
        }],
    )
    report = build_investigation_report(card(), changed, healthy_resources())
    assert report.status == "blocked"
    assert report.intended_routes_not_delivered == []
    assert any(item.code == "route_endpoint_mismatch" for item in report.blockers)

    foreign = result(
        complete_analysis(),
        card_id="other-card",
        delivery_methods=[{
            "key": "foreign",
            "outcome": "notify",
            "label": "Foreign",
            "destination": "slack://foreign",
        }],
    )
    report = build_investigation_report(card(), foreign, healthy_resources())
    assert report.status == "blocked"
    assert any(item.code == "result_card_mismatch" for item in report.blockers)
    assert any(item.code == "unauthorized_route" for item in report.blockers)


def test_known_negative_question_is_resolved_not_missing():
    report = build_investigation_report(
        card(question=True),
        result(
            complete_analysis(),
            question_results=[{
                "key": "question_0",
                "question": "Which approved question remains unresolved?",
                "status": "not_supported",
                "probability": 0.9,
            }],
        ),
        resources=healthy_resources(),
    )
    assert report.status == "complete"
    assert report.unresolved_questions == []


@pytest.mark.parametrize("slot_status", ["unavailable", "conflicting"])
def test_positive_answer_cannot_override_unfulfilled_required_slot(slot_status):
    required = card(question=True)
    required.evidence_requirements = {}
    evaluation = result(complete_analysis(), question_results=[{
        "key": "question_0", "question": required.questions[0],
        "status": "supported", "probability": .99,
    }], evidence_plan={"objective": "Evidence", "status": "incomplete", "slots": [{
        "key": "question:1", "role": "question", "question": required.questions[0],
        "required": True, "status": slot_status,
    }]})
    report = build_investigation_report(required, evaluation, healthy_resources())
    assert report.status == "blocked"
    assert any(c.kind == "evidence_slot" and c.status != "satisfied" for c in report.coverage)


def test_optional_only_failure_is_partial_under_engine_plan_contract():
    # InsightEngine._build_evidence_plan marks a plan blocked only for required
    # unavailable slots. Optional failures leave it complete with missing slots.
    evaluation = result(complete_analysis(), evidence_plan={
        "objective": "Evidence", "status": "complete", "slots": [{
            "key": "optional-context", "role": "diagnostic", "question": "Extra context",
            "required": False, "status": "unavailable",
        }],
    })
    report = build_investigation_report(card(), evaluation, healthy_resources())
    assert report.status == "partial"
    assert not report.blockers


def test_explicit_engine_block_is_not_silently_waived():
    evaluation = result(complete_analysis(), evidence_plan={
        "objective": "Evidence", "status": "blocked", "slots": [],
    })
    assert build_investigation_report(card(), evaluation, healthy_resources()).status == "blocked"


def test_decision_purpose_and_handoff_are_exposed_without_using_summary_as_fact():
    report = build_investigation_report(
        card(),
        result(
            complete_analysis(),
            summary="Invented narrative must not appear.",
            workflow={
                "status": "ready",
                "step_key": "review",
                "action": "request_review",
                "objective": "Review the bounded result",
                "instructions": "Check the approved source before delivery.",
            },
        ),
        resources=healthy_resources(),
    )
    markdown = render_investigation_report(report)
    assert report.outcome == "notify"
    assert report.purpose == card().why_watch
    assert report.next_step == "Check the approved source before delivery."
    assert "Invented narrative" not in markdown
    assert "Suggested next step" in markdown

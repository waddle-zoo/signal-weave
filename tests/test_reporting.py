from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from signalweave.diagnostics import AnalyticalComparison, SegmentContribution, analyze_comparison
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    InsightResult,
    InvestigationMode,
    ResourceSnapshot,
)
from signalweave.numeric_conditions import NumericCondition
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


def test_rendered_numeric_checks_expose_executable_binding_not_only_authored_label():
    policy = card()
    policy.numeric_conditions = [NumericCondition(
        text="Owner-written label that must not hide the chosen measurement",
        source_key="sales", comparison_key="volume-by-channel", measurement="contribution",
        unit="count", threshold=-10, comparator="<=",
    )]
    report = build_investigation_report(policy, result(complete_analysis()))
    rendered = render_investigation_report(report)
    assert "Binding: contribution for any segment" in rendered
    assert "-10.0 count" in rendered
    assert "sales / volume-by-channel" in rendered


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
        analytical_comparisons=[comparison()],
        error=error,
        contract={"source_status": source_status},
    )]


def complete_analysis(*, required: bool = True):
    return analyze_comparison("sales", comparison()).model_copy(update={"required": required})


def test_semantic_uncertainty_is_not_reported_as_observed_source_failure():
    from examples.investigation_agent.briefing import build_briefing_writer_input

    configured = card().model_copy(update={"watch_for": ["An exception applies."]})
    evaluated = result(complete_analysis(), outcome="investigate", delivery_methods=[],
                       confidence=.95, probabilities={"investigate": .95, "notify": .05},
                       watch_results=[{"key": "watch_0", "watch_for": "An exception applies.",
                                       "status": "unknown", "probability": .03,
                                       "probabilities": {"present": .03, "absent": .62, "unknown": .35}}],
                       evidence_plan={"objective": "Review policy", "status": "incomplete", "slots": [{
                           "key": "watch:1", "role": "watch", "question": "An exception applies.",
                           "required": True, "status": "pending", "source_keys": ["sales"],
                           "completion_criteria": "Establish whether an exception applies."}]})
    report = build_investigation_report(configured, evaluated, resources=healthy_resources())
    assert report.status == "blocked"  # Keep the reviewed requirement; do not waive it.
    assert next(c for c in report.coverage if c.kind == "source").status == "satisfied"
    watch = next(j for j in report.judgments if j.reference == "watch_0")
    assert watch.status == "unknown" and watch.support == .62
    assert watch.probabilities["absent"] == .62
    assert "does not establish" in watch.interpretation
    assert any("semantic assessment is unresolved" in b.message for b in report.blockers)
    projected = build_briefing_writer_input(report, render_investigation_report(report), [])
    assert projected["report"]["judgments"][1]["support"] == .62
    semantic = [item for item in projected["report"]["coverage"] if item["kind"] in {"watch", "evidence_slot"}]
    assert semantic and all(item["status"] == "unresolved" for item in semantic)
    assert "do not call a document" in projected["instructions"]


def test_actual_missing_sources_remain_explicit_when_judgments_are_available():
    report = build_investigation_report(card(), result(analyses=[]), resources=[])
    assert report.status == "blocked"
    assert any(b.code == "required_source_missing" for b in report.blockers)
    assert report.judgments[0].reference == "outcome"


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


def test_report_keeps_source_facts_needed_for_a_bounded_investigation():
    evidence = Evidence(
        source_key="sales",
        subject_id="deployment-42",
        subject_label="Release calendar",
        statement="Release completed 12 minutes before the measured change.",
        values={"lead_minutes": 12},
        provenance=["query:release-calendar"],
    )
    report = build_investigation_report(
        card(), result(complete_analysis(), evidence=[evidence]), healthy_resources()
    )

    assert report.status == "complete"
    assert report.evidence == [evidence]
    assert "Release completed 12 minutes" in render_investigation_report(report)


def test_report_rejects_foreign_evidence_instead_of_forwarding_it():
    foreign = Evidence(
        source_key="unapproved-source",
        statement="A foreign fact.",
        provenance=["query:foreign"],
    )
    report = build_investigation_report(
        card(), result(complete_analysis(), evidence=[foreign]), healthy_resources()
    )

    assert report.status == "blocked"
    assert any(item.code == "foreign_evidence" for item in report.blockers)


@pytest.mark.parametrize("blank", ["", " \t\n"])
def test_undeclared_source_bounds_do_not_downgrade_complete_comparisons(blank):
    resources = healthy_resources()
    for field in ("scope", "population", "grain"):
        setattr(resources[0].contract, field, blank)
    resources[0].description = "Complete company-wide population."
    resources[0].metadata = {"population": "All customers", "scope": "Global"}
    configured, evaluated = card(), result(complete_analysis())
    before = deepcopy((configured, evaluated, resources))
    report = build_investigation_report(configured, evaluated, resources)

    assert report.status == "complete"
    assert report.outcome == evaluated.outcome.value
    assert report.blockers == report.warnings == []
    assert next(c for c in report.coverage if c.kind == "source").status == "satisfied"
    assert (report.numeric_claims[0].baseline, report.numeric_claims[0].current,
            report.numeric_claims[0].delta) == (100, 80, -20)
    assert report.provenance[0].population == "Eligible population"
    assert report.provenance[0].coverage == "complete"
    boundary = report.source_boundaries[0]
    assert boundary.source_status == "healthy"
    for field in ("scope", "population", "grain"):
        assert getattr(boundary, field) is None
        assert getattr(boundary, field + "_status") == "undeclared"
    assert (configured, evaluated, resources) == before
    assert type(report).model_validate_json(report.model_dump_json()) == report
    markdown = render_investigation_report(report)
    assert "population: undeclared" in markdown
    assert "do not establish population completeness" in markdown
    assert "Measurements are provisional" not in markdown


def test_source_bounds_preserve_literal_text_and_remain_separate_from_comparisons():
    resources = healthy_resources()
    resources[0].contract.scope = " Pilot <west> | [only] "
    resources[0].contract.population = " Pilot accounts "
    resources[0].contract.grain = "daily"
    report = build_investigation_report(card(), result(complete_analysis()), resources)

    boundary = report.source_boundaries[0]
    assert boundary.model_dump() == {
        "source_key": "sales", "adapter": "test", "resource": "query:sales",
        "scope": " Pilot <west> | [only] ", "population": " Pilot accounts ",
        "grain": "daily", "scope_status": "declared", "population_status": "declared",
        "grain_status": "declared", "source_status": "healthy",
    }
    assert report.status == "complete"
    assert report.provenance[0].population == "Eligible population"
    markdown = render_investigation_report(report)
    assert "Pilot &lt;west&gt; \\| \\[only\\]" in markdown
    assert "population: declared —  Pilot accounts " in markdown
    assert "Comparison coverage applies only to its stated population" in markdown


def test_source_boundaries_do_not_require_structured_annotations_for_raw_evidence():
    configured = card()
    configured.sources[0].required_comparison_keys = []
    snapshot = healthy_resources()[0]
    snapshot.analytical_comparisons = []
    snapshot.evidence = [Evidence(
        source_key="sales", statement="Scoped export", values={"count": 0},
    )]
    report = build_investigation_report(configured, result(), [snapshot])
    assert report.status == "partial"  # Existing absence of validated quantitative analysis.
    assert not report.blockers
    assert not report.warnings
    assert report.source_boundaries[0].population_status == "undeclared"


@pytest.mark.parametrize("resources", [None, []])
def test_source_bounds_without_snapshots_are_not_returned(resources):
    report = build_investigation_report(card(), result(complete_analysis()), resources)
    boundary = report.source_boundaries[0]
    assert boundary.source_status is None
    for field in ("scope", "population", "grain"):
        assert getattr(boundary, field) is None
        assert getattr(boundary, field + "_status") == "not_returned"
    if resources is None:
        assert report.status == "partial"
        assert report.numeric_claims
    else:
        assert report.status == "blocked"
        assert any(b.code == "required_source_missing" for b in report.blockers)
        assert not report.numeric_claims


@pytest.mark.parametrize("source_status", ["failed", "stale", "ambiguous", "unknown"])
def test_declared_source_bounds_do_not_override_source_health_blocks(source_status):
    resources = healthy_resources(source_status=source_status)
    resources[0].contract.population = "Eligible population"
    report = build_investigation_report(card(), result(complete_analysis()), resources)
    assert report.status == "blocked"
    assert any(b.code == "required_source_failed" for b in report.blockers)
    assert report.source_boundaries[0].source_status == source_status
    assert report.source_boundaries[0].population_status == "declared"
    assert report.source_boundaries[0].scope_status == "undeclared"
    assert report.numeric_claims[0].delta == -20
    assert "Measurements are provisional" in render_investigation_report(report)


@pytest.mark.parametrize("invalid", ["identity", "duplicate", "foreign"])
def test_source_bounds_require_unique_authorized_snapshot_identity(invalid):
    resource = healthy_resources()[0]
    resource.contract.population = "Do not attribute this population to another source"
    if invalid == "identity":
        resource.resource = "query:other"
    elif invalid == "foreign":
        resource.source_key = "other"
    resources = [resource, deepcopy(resource)] if invalid == "duplicate" else [resource]
    report = build_investigation_report(card(), result(complete_analysis()), resources)
    assert report.status == "blocked"
    assert not report.numeric_claims
    assert len(report.source_boundaries) == 1
    boundary = report.source_boundaries[0]
    assert boundary.source_key == "sales" and boundary.resource == "query:sales"
    assert boundary.population is None
    assert boundary.population_status == "not_returned"


def test_legacy_report_without_source_boundaries_still_validates():
    report = build_investigation_report(card(), result(complete_analysis()), healthy_resources())
    payload = report.model_dump(mode="json")
    del payload["source_boundaries"]
    restored = type(report).model_validate(payload)
    assert restored.source_boundaries == []
    assert restored.numeric_claims == report.numeric_claims
    assert restored.status == "complete"


@pytest.mark.parametrize("source_status", ["healthy", "failed"])
def test_revoked_source_annotations_do_not_reach_report_or_writer(source_status):
    from examples.investigation_agent.briefing import build_briefing_writer_input

    resources = healthy_resources(source_status=source_status)
    resources[0].contract.authorized = False
    for field in ("scope", "population", "grain"):
        setattr(resources[0].contract, field, "REVOKED_ANNOTATION_CANARY")
    report = build_investigation_report(card(), result(complete_analysis()), resources)
    assert report.status == "blocked"
    assert any(b.code == "required_source_failed" for b in report.blockers)
    assert report.source_boundaries[0].population_status == "not_returned"
    assert report.source_boundaries[0].source_status is None
    assert report.numeric_claims == []
    assert report.provenance == []
    markdown = render_investigation_report(report)
    writer = build_briefing_writer_input(report, markdown, [])
    assert "REVOKED_ANNOTATION_CANARY" not in report.model_dump_json()
    assert "REVOKED_ANNOTATION_CANARY" not in markdown
    assert "REVOKED_ANNOTATION_CANARY" not in str(writer)


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


def test_analysis_must_match_the_returned_snapshot_comparison():
    actual = comparison(
        current_total={"value": 90},
        segments=[
            {"segment": "online", "baseline": {"value": 60}, "current": {"value": 40}},
            {"segment": "store", "baseline": {"value": 40}, "current": {"value": 50}},
        ],
    )
    resources = [ResourceSnapshot(
        source_key="sales",
        adapter="test",
        resource="query:sales",
        title="Sales query",
        analytical_comparisons=[actual],
    )]
    report = build_investigation_report(card(), result(complete_analysis()), resources)

    assert report.status == "blocked"
    assert report.numeric_claims == []
    assert any(item.code == "analysis_snapshot_comparison_mismatch" for item in report.blockers)


def test_fixed_card_rejects_unselected_foreign_resource_snapshot():
    foreign = ResourceSnapshot(
        source_key="rogue",
        adapter="test",
        resource="query:rogue",
        title="Rogue query",
        analytical_comparisons=[comparison()],
    )
    report = build_investigation_report(
        card(), result(complete_analysis()), [*healthy_resources(), foreign]
    )

    assert report.status == "blocked"
    assert any(item.code == "foreign_resource" for item in report.blockers)


def test_foreign_analysis_is_blocked_even_without_source_snapshots():
    foreign = analyze_comparison("rogue", comparison())
    report = build_investigation_report(card(), result(foreign))

    assert report.status == "blocked"
    assert report.numeric_claims == []
    assert any(item.code == "analysis_source_not_approved" for item in report.blockers)


def test_analysis_requiredness_ignores_mutated_analysis_required_flag():
    report = build_investigation_report(
        card(), result(complete_analysis(required=False)), healthy_resources()
    )

    assert report.status == "complete"
    analysis_coverage = next(item for item in report.coverage if item.kind == "analysis")
    assert analysis_coverage.required is True


def test_missing_card_declared_comparison_still_blocks():
    missing = ResourceSnapshot(
        source_key="sales",
        adapter="test",
        resource="query:sales",
        title="Sales query",
    )
    report = build_investigation_report(card(), result(analyses=[]), [missing])

    assert report.status == "blocked"
    assert any(item.code == "required_analysis_missing" for item in report.blockers)


def test_optional_comparison_within_required_source_is_partial_not_blocked():
    optional_source = card().sources[0].model_copy(update={"required_comparison_keys": []})
    required_card = card().model_copy(update={"sources": [optional_source]})
    optional_comparison = comparison(required=False, coverage="partial")
    optional_analysis = analyze_comparison("sales", optional_comparison)
    resources = [ResourceSnapshot(
        source_key="sales",
        adapter="test",
        resource="query:sales",
        title="Sales query",
        analytical_comparisons=[optional_comparison],
    )]
    report = build_investigation_report(
        required_card, result(optional_analysis), resources
    )

    assert report.status == "partial"
    assert not any(item.code == "required_analysis_insufficient_data" for item in report.blockers)


def test_bounded_investigation_selected_source_is_authorized_and_bound():
    investigated = card().model_copy(update={"investigation_mode": InvestigationMode.BOUNDED})
    selected_source = {
        "key": "diagnostic",
        "adapter": "test",
        "resource": "query:diagnostic",
        "label": "Diagnostic query",
        "required": False,
    }
    selected_comparison = comparison(key="diagnostic-comparison")
    extra_analysis = analyze_comparison("diagnostic", selected_comparison)
    trace = {
        "mode": "bounded",
        "attempted": True,
        "candidate_count": 1,
        "candidate_limit": 1,
        "selected": [{
            "source": selected_source,
            "score": 0.9,
            "confidence": 0.9,
            "selection_reason": "Approved bounded diagnostic selection.",
            "retrieval_status": "succeeded",
        }],
        "evaluator": "test",
    }
    report = build_investigation_report(
        investigated,
        result(
            complete_analysis(),
            source_keys=["sales", "diagnostic"],
            analyses=[complete_analysis(), extra_analysis],
            investigation=trace,
        ),
        [
            *healthy_resources(),
            ResourceSnapshot(
                source_key="diagnostic",
                adapter="test",
                resource="query:diagnostic",
                title="Diagnostic query",
                analytical_comparisons=[selected_comparison],
            ),
        ],
    )

    assert report.status == "complete"
    assert {claim.source_key for claim in report.numeric_claims} == {"sales", "diagnostic"}
    assert {item.source_key for item in report.source_boundaries} == {"sales", "diagnostic"}


def test_notify_route_without_configuration_and_duplicate_selection_block():
    no_route_card = card().model_copy(update={"delivery_methods": []})
    no_route = build_investigation_report(
        no_route_card,
        result(complete_analysis(), delivery_methods=[]),
        healthy_resources(),
    )
    assert no_route.status == "blocked"
    assert any(item.code == "route_not_configured" for item in no_route.blockers)

    duplicate = result(
        complete_analysis(),
        delivery_methods=[
            {"key": "owner", "outcome": "notify", "label": "Owner", "destination": "slack://owner|weekly"},
            {"key": "owner", "outcome": "notify", "label": "Owner", "destination": "slack://owner|weekly"},
        ],
    )
    duplicate_report = build_investigation_report(card(), duplicate, healthy_resources())
    assert duplicate_report.status == "blocked"
    assert any(item.code == "duplicate_route_selection" for item in duplicate_report.blockers)


def test_route_must_match_result_outcome_and_appendix_preserves_delivery_contract():
    mismatched = result(
        complete_analysis(),
        outcome="notify",
        delivery_methods=[{
            "key": "owner",
            "outcome": "investigate",
            "label": "Owner",
            "destination": "slack://owner|weekly",
        }],
    )
    report = build_investigation_report(card(), mismatched, healthy_resources())
    assert report.status == "blocked"
    assert any(item.code == "route_outcome_mismatch" for item in report.blockers)

    good_markdown = render_investigation_report(
        build_investigation_report(card(), result(complete_analysis()), healthy_resources())
    )
    assert "owner" in good_markdown
    assert "slack://owner" in good_markdown
    assert "Caller owns delivery; not sent." in good_markdown


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
    assert any(item.code == "required_semantic_assessment_unresolved" for item in blocked.blockers)

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


def test_semantic_coverage_retains_jev_judgment_and_probability():
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
    item = next(item for item in report.coverage if item.kind == "question")
    assert item.judgment == "not_supported"
    assert item.probability == 0.9


def test_reader_labels_semantic_probability_by_what_it_measures():
    watched = card(question=True).model_copy(
        update={
            "watch_for": ["Movement is present"],
            "evidence_requirements": {"question:1": False, "watch:1": False},
        }
    )
    report = build_investigation_report(
        watched,
        result(
            complete_analysis(),
            watch_results=[{
                "key": "watch_0",
                "watch_for": "Movement is present",
                "status": "absent",
                "probability": 0.03,
            }],
            question_results=[{
                "key": "question_0",
                "question": "Which approved question remains unresolved?",
                "status": "not_supported",
                "probability": 0.03,
            }],
        ),
        resources=healthy_resources(),
    )

    markdown = render_investigation_report(report)
    assert "P(present) 0.03" in markdown
    assert "P(supported) 0.03" in markdown
    assert "; probability 0.03" not in markdown


def test_reader_markdown_surfaces_goal_policy_checks_gaps_and_audit_once():
    report = build_investigation_report(
        card(question=True),
        result(
            complete_analysis(),
            question_results=[{
                "key": "question_0",
                "question": "Which approved question remains unresolved?",
                "status": "unknown",
                "probability": 0.5,
            }],
        ),
        resources=healthy_resources(source_status="ambiguous"),
    )
    markdown = render_investigation_report(report)
    assert "- Goal:" in markdown
    assert "- Decision:" in markdown
    assert "- Intended route audience: Owner \\(slack://owner\\|weekly\\)" in markdown
    assert "### Policy checks (Jev judgments)" in markdown
    assert markdown.index("<details>") < markdown.index("### Policy checks")
    assert "Measurements are provisional" in markdown
    assert "No complete business conclusion" in markdown
    assert "Source sales is failed: Source contract status is ambiguous." in markdown
    assert "<details>" in markdown and "### Provenance" in markdown
    assert "\n## Coverage" not in markdown


def test_front_matter_is_compact_and_route_audience_has_quiet_fallback():
    report = build_investigation_report(
        card(),
        result(complete_analysis(), outcome="ignore", delivery_methods=[]),
        resources=healthy_resources(),
    )
    markdown = render_investigation_report(report)
    front_matter = markdown.split("<details>", 1)[0]
    assert len(front_matter) < 1200
    assert "Intended route audience: No notification intended \\(quiet outcome\\)." in markdown
    assert "## Policy checks" not in front_matter


def test_renderer_sorts_top_contributions_by_absolute_change():
    report = build_investigation_report(
        card(), result(complete_analysis()), resources=healthy_resources()
    )
    claim = report.numeric_claims[0].model_copy(
        update={
            "contributions": [
                SegmentContribution(segment="small", baseline=1, current=2, contribution=1),
                SegmentContribution(
                    segment="large-negative", baseline=20, current=0, contribution=-20
                ),
                SegmentContribution(segment="medium", baseline=7, current=14, contribution=7),
                SegmentContribution(
                    segment="large-positive", baseline=12, current=24, contribution=12
                ),
            ]
        }
    )
    rendered = render_investigation_report(
        report.model_copy(update={"numeric_claims": [claim]})
    )

    assert rendered.index("large-negative: -20") < rendered.index("large-positive: 12")
    assert rendered.index("large-positive: 12") < rendered.index("medium: 7")
    assert "small: 1" not in rendered
    assert "plus 1 smaller" in rendered


def test_renderer_preserves_claim_order_across_metrics_and_marks_truncation():
    report = build_investigation_report(
        card(), result(complete_analysis()), resources=healthy_resources()
    )
    claims = [
        report.numeric_claims[0].model_copy(update={"metric": "first", "delta": 1}),
        report.numeric_claims[0].model_copy(update={"metric": "second", "delta": -100}),
        report.numeric_claims[0].model_copy(update={"metric": "third", "delta": 50}),
        report.numeric_claims[0].model_copy(update={"metric": "fourth", "delta": 25}),
    ]
    front_matter = render_investigation_report(
        report.model_copy(update={"numeric_claims": claims})
    ).split("<details>", 1)[0]

    assert "## Measured changes (first 3)" in front_matter
    assert front_matter.index("**first**") < front_matter.index("**second**")
    assert front_matter.index("**second**") < front_matter.index("**third**")
    assert "**fourth**" not in front_matter


def test_resource_identity_mismatch_blocks_at_approved_source_boundary():
    report = build_investigation_report(
        card(),
        result(complete_analysis()),
        resources=[ResourceSnapshot(
            source_key="sales",
            adapter="test",
            resource="query:other",
            title="Wrong resource",
        )],
    )
    assert report.status == "blocked"
    assert any(
        "identity does not match" in item.message for item in report.blockers
    )


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
            ResourceSnapshot(
                source_key="source:one",
                adapter="test",
                resource="query:sales",
                title="one",
                analytical_comparisons=[comparison(key="comparison:shared")],
            ),
            ResourceSnapshot(
                source_key="source",
                adapter="test",
                resource="query:sales",
                title="two",
                analytical_comparisons=[comparison(key="one:comparison:shared")],
            ),
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


def test_quiet_report_ignores_informational_quiet_route():
    quiet_card = card().model_copy(update={
        "delivery_methods": [
            *card().delivery_methods,
            DeliveryMethod(
                key="quiet-audit",
                outcome="ignore",
                label="Audit log",
                destination="audit://quiet",
            ),
        ]
    })
    report = build_investigation_report(
        quiet_card,
        result(complete_analysis(), outcome="ignore", delivery_methods=[]),
        resources=healthy_resources(),
    )

    assert report.status == "complete"
    assert report.intended_routes_not_delivered == []
    assert report.warnings == []


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


def test_required_not_supported_question_is_unresolved_even_with_a_result():
    required = card(question=True).model_copy(update={"evidence_requirements": {"question:1": True}})
    report = build_investigation_report(
        required,
        result(
            complete_analysis(),
            question_results=[{
                "key": "question_0",
                "question": "Which approved question remains unresolved?",
                "status": "not_supported",
                "probability": 0.9,
            }],
            evidence_plan={
                "objective": "Bounded source evidence",
                "status": "complete",
                "slots": [{
                    "key": "question:1",
                    "role": "question",
                    "question": required.questions[0],
                    "required": True,
                    "status": "fulfilled",
                }],
            },
        ),
        resources=healthy_resources(),
    )
    assert report.status == "blocked"
    assert report.unresolved_questions == required.questions
    assert any(item.code == "required_semantic_assessment_unresolved" for item in report.blockers)


def test_optional_not_supported_question_is_partial_not_resolved():
    report = build_investigation_report(
        card(question=True),
        result(
            complete_analysis(),
            question_results=[{
                "key": "question_0",
                "question": "Which approved question remains unresolved?",
                "status": "not_supported",
                "probability": 0.03,
            }],
        ),
        resources=healthy_resources(),
    )
    assert report.status == "partial"
    assert report.unresolved_questions == ["Which approved question remains unresolved?"]


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
    assert "## Next step" in markdown

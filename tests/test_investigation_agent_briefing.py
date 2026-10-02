from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from examples.investigation_agent.briefing import build_briefing_writer_input, create_briefing
from signalweave.reporting import (
    AnalysisProvenance,
    InvestigationReport,
    NumericClaim,
    PeriodProvenance,
)


def report(**overrides: Any) -> InvestigationReport:
    provenance = AnalysisProvenance(
        source_key="source-a", comparison_key="comparison-a", query_refs=["query-a"],
        definition="Order count", population="All orders", metric="orders", dimension="all",
        unit="count", baseline_period=PeriodProvenance(start=datetime(2026, 1, 1, tzinfo=timezone.utc), end=datetime(2026, 1, 2, tzinfo=timezone.utc)),
        current_period=PeriodProvenance(start=datetime(2026, 1, 2, tzinfo=timezone.utc), end=datetime(2026, 1, 3, tzinfo=timezone.utc)),
        coverage="complete", comparable=True, input_digest="digest-a",
    )
    claim = NumericClaim(
        source_key="source-a", comparison_key="comparison-a", metric="orders", dimension="all",
        unit="count", method="additive_contribution_v1", claim_type="accounting_decomposition",
        baseline=100, current=88, delta=-12, residual=0, provenance_key="source-a/comparison-a",
    )
    value: dict[str, Any] = {
        "card_id": "card-1", "title": "Signal review", "outcome": "notify",
        "purpose": "Support an operating decision.", "intended_audience": "Owner",
        "status": "complete", "numeric_claims": [claim], "provenance": [provenance],
        "evaluated_at": datetime(2026, 1, 3, tzinfo=timezone.utc), "evaluator": "test",
    }
    value.update(overrides)
    return InvestigationReport(**value)


@pytest.mark.asyncio
async def test_writer_input_is_compact_and_uses_recipient_keys() -> None:
    calls: list[dict[str, Any]] = []

    async def writer(writer_input):
        calls.append(writer_input)
        return {"narrative": "Orders declined in the comparison period.", "citations": [
            {"source_key": "source-a", "comparison_key": "comparison-a"}
        ]}

    result = await create_briefing(
        report(), "# Native report\n- Decision: notify", ["owner"], writer=writer
    )
    assert calls[0]["configured_recipient_keys"] == ["owner"]
    assert "report_markdown" not in calls[0]
    assert set(calls[0]["report"]) == {
        "card_id", "title", "outcome", "purpose", "intended_audience", "next_step",
        "status", "numeric_claims", "provenance", "limitations", "unresolved_questions",
        "intended_routes_not_delivered", "blockers", "warnings", "evaluator", "coverage", "judgments", "numeric_conditions",
    }
    assert calls[0]["known_analysis_refs"] == [
        {"source_key": "source-a", "comparison_key": "comparison-a"}
    ]
    assert result["narrative"] == "Orders declined in the comparison period."
    assert result["writer_status"] == "accepted"
    assert result["authoritative"]["report"] == report().model_dump(mode="json")
    assert result["authoritative"]["report_markdown"].startswith("# Native report")


@pytest.mark.asyncio
async def test_quiet_ignore_does_not_invoke_optional_writer() -> None:
    async def writer(_writer_input):
        pytest.fail("quiet ignore must not invoke the writer")

    result = await create_briefing(
        report(outcome="ignore", status="partial"), "native markdown", ["owner"], writer=writer
    )
    assert result["quiet"] is True
    assert result["writer_status"] == "quiet"
    assert result["outcome"] == "ignore"
    assert result["status"] == "partial"
    assert result["configured_recipient_keys"] == ["owner"]


@pytest.mark.asyncio
async def test_partial_and_blocked_warnings_remain_visible() -> None:
    native = report(status="blocked", numeric_claims=[], warnings=["context unavailable"])

    async def writer(_writer_input):
        return {"narrative": "Review is blocked pending more evidence.", "citations": []}

    result = await create_briefing(native, "blocked report", [], writer=writer)
    assert result["status"] == "blocked"
    assert result["warnings"] == ["context unavailable"]
    assert result["narrative"] == "Review is blocked pending more evidence."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("writer_result", "message"),
    [
        ({"narrative": "   ", "citations": []}, "writer narrative"),
        ({"narrative": "A number is reported.", "citations": []}, "numeric claims"),
        ({"narrative": "A number is reported.", "citations": [{"source_key": "invented", "comparison_key": "comparison-a"}]}, "unknown citation ref"),
        ({"narrative": "A number is reported.", "citations": [{"source_key": "source-a", "comparison_key": "invented"}]}, "unknown citation ref"),
    ],
)
async def test_writer_text_and_citations_are_validated(writer_result, message) -> None:
    async def writer(_writer_input):
        return writer_result

    with pytest.raises((TypeError, ValueError), match=message):
        await create_briefing(report(), "native markdown", [], writer=writer)


def test_writer_input_validates_actual_report_and_markdown() -> None:
    with pytest.raises(ValueError, match="report_markdown"):
        build_briefing_writer_input(report(), "  ", [])
    with pytest.raises(ValueError):
        build_briefing_writer_input({"outcome": "notify"}, "native markdown", [])

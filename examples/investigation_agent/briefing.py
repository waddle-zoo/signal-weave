"""Small caller-owned writer boundary for an authoritative investigation report.

This is not a prose truth verifier. Citations make numeric claims inspectable;
they do not prove them or justify unsupported causal claims. Independent review
remains necessary. Native report and Markdown are retained only in the returned
archived payload, never copied into the writer input wholesale.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from copy import deepcopy
from typing import Any, Protocol

from signalweave.reporting import InvestigationReport


class BriefingWriter(Protocol):
    """An async caller-owned writer; no model gateway is assumed here."""

    def __call__(self, writer_input: Mapping[str, Any]) -> Awaitable[Mapping[str, Any]]: ...


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def _validated_report(report: InvestigationReport | Mapping[str, Any]) -> InvestigationReport:
    if isinstance(report, InvestigationReport):
        return report
    if not isinstance(report, Mapping):
        raise TypeError("report must be an InvestigationReport or mapping")
    return InvestigationReport.model_validate(report)


def _recipient_keys(recipients: Sequence[str]) -> list[str]:
    keys: list[str] = []
    for recipient in recipients:
        if not isinstance(recipient, str) or not recipient.strip():
            raise ValueError("configured recipients must be nonempty directory keys")
        if recipient in keys:
            raise ValueError("configured recipient keys must be unique")
        keys.append(recipient)
    return keys


def _analysis_refs(report: InvestigationReport) -> set[tuple[str, str]]:
    pairs = {(claim.source_key, claim.comparison_key) for claim in report.numeric_claims}
    pairs.update((item.source_key, item.comparison_key) for item in report.provenance)
    return pairs


def _writer_report(report: InvestigationReport) -> dict[str, Any]:
    native = report.model_dump(mode="json")
    fields = (
        "card_id", "title", "outcome", "purpose", "intended_audience", "next_step",
        "status", "numeric_claims", "provenance", "limitations", "unresolved_questions",
        "intended_routes_not_delivered", "blockers", "warnings", "evaluator",
        "judgments", "numeric_conditions", "source_boundaries",
    )
    compact = {field: native[field] for field in fields if field != "intended_routes_not_delivered"}
    compact["intended_routes_not_delivered"] = [
        {key: item[key] for key in ("key", "outcome", "label", "reason")}
        for item in native["intended_routes_not_delivered"]
    ]
    compact["coverage"] = [
        {key: item[key] for key in ("key", "kind", "required", "status", "source_keys", "detail")}
        for item in native["coverage"]
    ]
    return compact


def build_briefing_writer_input(
    report: InvestigationReport | Mapping[str, Any],
    report_markdown: str,
    recipients: Sequence[str],
) -> dict[str, Any]:
    """Project concise writer input from a validated native report.

    ``report_markdown`` is required to prove that the caller has the native
    rendering, but is intentionally not sent because the compact projection
    already contains the relevant claims and gaps.
    """

    native = _validated_report(report)
    _text(report_markdown, "report_markdown")
    recipient_keys = _recipient_keys(recipients)
    known_pairs = _analysis_refs(native)
    return {
        "report": _writer_report(native),
        "configured_recipient_keys": recipient_keys,
        "known_analysis_refs": [
            {"source_key": source, "comparison_key": comparison}
            for source, comparison in sorted(known_pairs)
        ],
        "instructions": (
            "Write concise supported prose from the report projection. Preserve its "
            "outcome, status, configured recipient keys, numeric claims, and visible "
            "limitations or blockers. Do not invent destinations or make unsupported "
            "causal claims. Judgments are model assessments, not observed facts. Distinguish "
            "uncertain interpretation from known source failures: do not call a document "
            "missing or conflicting merely because a semantic assessment is unresolved. "
            "Do not claim the support probability measures a causal explanation's likelihood. "
            "Source boundaries copy literal contract annotations: undeclared annotations do not "
            "establish missing records, and healthy/satisfied sources do not establish population "
            "completeness. Keep each comparison's coverage within its stated population; do not "
            "extrapolate it to the whole source or company. "
            "Cite exact source_key/comparison_key references in the caller's output schema. "
            "Independent review remains necessary."
        ),
    }


def _writer_citations(report: InvestigationReport, value: Any) -> list[dict[str, str]]:
    if value is None:
        value = []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("writer citations must be a list")
    known = _analysis_refs(report)
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("each citation must contain source_key and comparison_key")
        source = _text(item.get("source_key"), "citation.source_key")
        comparison = _text(item.get("comparison_key"), "citation.comparison_key")
        ref = (source, comparison)
        if ref not in known:
            raise ValueError(f"unknown citation ref: {source}/{comparison}")
        if ref not in seen:
            seen.add(ref)
            result.append({"source_key": source, "comparison_key": comparison})
    if report.numeric_claims and not result:
        raise ValueError("numeric claims require citations")
    return result


async def create_briefing(
    report: InvestigationReport | Mapping[str, Any],
    report_markdown: str,
    recipients: Sequence[str],
    *,
    writer: BriefingWriter | None = None,
) -> dict[str, Any]:
    """Optionally write prose while retaining an exact authoritative archive."""

    native = _validated_report(report)
    markdown = _text(report_markdown, "report_markdown")
    recipient_keys = _recipient_keys(recipients)
    writer_input = build_briefing_writer_input(native, markdown, recipients)
    result: dict[str, Any] = {
        "narrative": None,
        "citations": [],
        "writer_status": "not_requested" if writer is None else "pending",
        "authoritative": {
            "report": deepcopy(native.model_dump(mode="json")),
            "report_markdown": markdown,
            "configured_recipient_keys": list(recipient_keys),
        },
        "outcome": native.outcome,
        "status": native.status,
        "configured_recipient_keys": recipient_keys,
        "warnings": list(native.warnings),
        "blockers": native.model_dump(mode="json")["blockers"],
        "quiet": native.outcome == "ignore",
    }
    if writer is None or result["quiet"]:
        result["writer_status"] = "quiet" if result["quiet"] else "not_requested"
        return result
    written = await writer(writer_input)
    if not isinstance(written, Mapping):
        raise TypeError("briefing writer must return a mapping")
    result["narrative"] = _text(written.get("narrative"), "writer narrative").strip()
    result["citations"] = _writer_citations(native, written.get("citations"))
    result["writer_status"] = "accepted"
    return result

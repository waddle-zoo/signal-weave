"""Prospective full-runtime recurring-review fixtures.

This module contains three new synthetic companies.  Each company has two
setup periods and four future holdout periods.  The holdout ``oracle`` is an
evaluation-only label: the authoring view below removes it and removes every
future period before an author can inspect the company.

The fixtures deliberately stop at plain-English owner policy, source
contracts, deterministic comparisons, and an independently computed oracle.
They do not define a policy plan or a ``numeric_conditions`` schema, and they
do not call Jev, Luna, a network, or a live source.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Any

from signalweave.models import ResourceContract, ResourceDescriptor, ResourceSnapshot, SourceRef

UTC = timezone.utc
WINDOW = "previous_period"
TENANT = "synthetic-recurring-runtime"

REVIEW_GUIDANCE = {
    "expected_prose_claims": [
        "State the selected metric's baseline, current value, and signed change when the comparison is complete.",
        "Use weighted rate totals for rate metrics; distinguish a current-level trigger from a between-period change.",
        "Preserve signs for signed movements and name material segment contributions without calling them causes.",
        "For a quiet period, say that the configured rule did not trigger; do not claim that the business is risk-free.",
        "For incomplete evidence, identify the missing comparability or context and route the stated owner action.",
    ],
    "noncausal_limitations": [
        "Accounting contributions describe the measured difference, not its causal mechanism.",
        "The fixture computes no statistical significance, forecast, counterfactual, or causal attribution.",
        "Do not estimate a total or substitute a nearby metric when the selected source is incomplete or non-comparable.",
    ],
}


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _period_dates(index: int, *, step_days: int) -> dict[str, datetime]:
    # Each fixture is an independently generated adjacent-period comparison.
    # Keep review pairs disjoint: do not publish contradictory values for the
    # same historical week/month across two snapshots.
    start = datetime(2027, 2, 1, tzinfo=UTC) + timedelta(days=index * step_days * 2)
    return {
        "baseline_start": start,
        "baseline_end": start + timedelta(days=step_days),
        "current_start": start + timedelta(days=step_days),
        "current_end": start + timedelta(days=step_days * 2),
    }


def _rows_additive(
    company_id: str,
    period_id: str,
    values: dict[str, tuple[int | None, int | None]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment, (baseline, current) in values.items():
        for period_name, amount in (("baseline", baseline), ("current", current)):
            if amount is None:
                continue
            rows.append({
                "record_id": f"{company_id}-{period_id}-{period_name}-{segment}",
                "period": period_name,
                "segment": segment,
                "value": amount,
            })
    return rows


def _rows_rate(
    company_id: str,
    period_id: str,
    values: dict[str, tuple[int | None, int | None, int | None, int | None]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment, (baseline_misses, baseline_total, current_misses, current_total) in values.items():
        for period_name, misses, total in (
            ("baseline", baseline_misses, baseline_total),
            ("current", current_misses, current_total),
        ):
            if misses is None or total is None:
                continue
            for index in range(total):
                rows.append({
                    "record_id": f"{company_id}-{period_id}-{period_name}-{segment}-{index}",
                    "period": period_name,
                    "segment": segment,
                    "eligible": True,
                    "missed": index < misses,
                })
    return rows


def _group_additive(rows: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {"baseline": {}, "current": {}}
    for row in rows:
        grouped[row["period"]][row["segment"]] = (
            grouped[row["period"]].get(row["segment"], 0) + row["value"]
        )
    return grouped["baseline"], grouped["current"]


def _group_rate(rows: list[dict[str, Any]]) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
    grouped: dict[str, dict[str, list[int]]] = {"baseline": {}, "current": {}}
    for row in rows:
        values = grouped[row["period"]].setdefault(row["segment"], [0, 0])
        values[0] += int(row["missed"])
        values[1] += int(row["eligible"])
    return (
        {key: tuple(value) for key, value in grouped["baseline"].items()},
        {key: tuple(value) for key, value in grouped["current"].items()},
    )


def _descriptor(
    *,
    source_key: str,
    resource: str,
    title: str,
    description: str,
    metric_names: list[str],
    comparison_keys: list[str],
    population: str,
    grain: str,
    business_role: str,
    required: bool = True,
    semantic_contract: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_key": source_key,
        "business_role": business_role,
        "required": required,
        "read_only": True,
        "period_contract": "closed UTC intervals compared with the immediately preceding closed interval",
        "comparability_contract": {
            "population_identity": population,
            "period_alignment": "adjacent closed intervals with the same calendar grain",
            "segment_partition": "declared disjoint segments; incomplete partitions are not comparable",
            "definition_version": "synthetic-contract-v1",
        },
    }
    if semantic_contract:
        metadata["semantic_contract"] = semantic_contract
    contract = ResourceContract(
        tenant_id=TENANT,
        domain=source_key,
        scope=population,
        metric_names=metric_names,
        available_comparison_windows=[WINDOW],
        required_comparison_keys=comparison_keys,
        population=population,
        grain=grain,
        freshness_sla_hours=48,
        roles=[business_role],
        source_status="healthy",
        authorized=True,
    )
    descriptor = ResourceDescriptor(
        adapter="company_mcp",
        resource=resource,
        kind="saved_query" if comparison_keys else "context_record",
        title=title,
        description=description,
        metadata=metadata,
        contract=contract,
    ).model_dump(mode="json")
    descriptor["source_key"] = source_key
    return descriptor


def _source_ref(descriptor: dict[str, Any]) -> dict[str, Any]:
    return SourceRef(
        key=descriptor["source_key"],
        adapter=descriptor["adapter"],
        resource=descriptor["resource"],
        label=descriptor["title"],
        parameters={
            "business_role": descriptor["metadata"]["business_role"],
            "available_comparison_windows": descriptor["contract"]["available_comparison_windows"],
        },
        required=descriptor["metadata"]["required"],
        required_comparison_keys=descriptor["contract"]["required_comparison_keys"],
    ).model_dump(mode="json")


def _comparison(
    *,
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
    dates: dict[str, datetime],
    coverage: str,
    query_ref: str,
) -> dict[str, Any]:
    segments = sorted(spec["segments"])
    if spec["kind"] == "additive":
        baseline, current = _group_additive(rows)
        baseline_total = sum(baseline.values()) if baseline else None
        current_total = sum(current.values()) if current else None
        if coverage != "complete":
            current_total = None
        segment_values = [
            {
                "segment": segment,
                "baseline": {"value": baseline[segment]} if segment in baseline else {"value": None},
                "current": {"value": current[segment]} if segment in current else {"value": None},
            }
            for segment in segments
        ]
        totals = {
            "baseline_total": {"value": baseline_total},
            "current_total": {"value": current_total},
        }
    else:
        baseline, current = _group_rate(rows)
        baseline_total = {
            "numerator": sum(value[0] for value in baseline.values()) if baseline else None,
            "denominator": sum(value[1] for value in baseline.values()) if baseline else None,
        }
        current_total = {
            "numerator": sum(value[0] for value in current.values()) if current else None,
            "denominator": sum(value[1] for value in current.values()) if current else None,
        }
        if coverage != "complete":
            current_total = {"numerator": None, "denominator": None}
        segment_values = [
            {
                "segment": segment,
                "baseline": (
                    {"numerator": baseline[segment][0], "denominator": baseline[segment][1]}
                    if segment in baseline else {"numerator": None, "denominator": None}
                ),
                "current": (
                    {"numerator": current[segment][0], "denominator": current[segment][1]}
                    if segment in current else {"numerator": None, "denominator": None}
                ),
            }
            for segment in segments
        ]
        totals = {"baseline_total": baseline_total, "current_total": current_total}
    return {
        "key": spec["comparison_key"],
        "metric": spec["metric"],
        "definition": spec["definition"],
        "population": spec["population"],
        "unit": spec["unit"],
        "dimension": spec["dimension"],
        "kind": spec["kind"],
        "baseline_start": _iso(dates["baseline_start"]),
        "baseline_end": _iso(dates["baseline_end"]),
        "current_start": _iso(dates["current_start"]),
        "current_end": _iso(dates["current_end"]),
        "comparison_window": WINDOW,
        "coverage": coverage,
        "disjoint_segments": True,
        "comparable": coverage == "complete",
        "query_refs": [query_ref],
        **totals,
        "segments": segment_values,
    }


def _snapshot(
    *,
    descriptor: dict[str, Any],
    company_id: str,
    period_id: str,
    as_of: datetime,
    comparison: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    coverage: str,
    comparability_note: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_key = descriptor["source_key"]
    captured_at = as_of
    metadata = {
        "company_id": company_id,
        "period_id": period_id,
        "as_of": _iso(as_of),
        "period_contract": descriptor["metadata"]["period_contract"],
        "replay_clock": _iso(captured_at),
        "comparability": {
            "status": "comparable" if coverage == "complete" else "not_comparable",
            "flags": {
                "same_population": coverage == "complete",
                "same_definition": True,
                "adjacent_periods": True,
                "complete_segment_partition": coverage == "complete",
                "totals_reconciled": coverage == "complete",
            },
            "population_match": coverage == "complete",
            "adjacent_periods": True,
            "segment_partition_complete": coverage == "complete",
            "note": comparability_note,
        },
    }
    evidence_values: dict[str, Any] = {"row_count": len(rows)}
    statement = "The source contract declares the population, period grain, and disjoint segment partition used by this result."
    if context is not None:
        metadata["semantic_context_contract"] = "The exception register states whether an owner-approved exception covers the exact closed period."
        evidence_values.update(context)
        statement = context["statement"]
    evidence = [{
        "source_key": source_key,
        "subject_id": f"{company_id}-{period_id}-{source_key}",
        "subject_label": descriptor["title"],
        "statement": statement,
        "values": evidence_values,
        "provenance": [f"source:{source_key}:{period_id}"],
    }]
    contract_payload = copy.deepcopy(descriptor["contract"])
    contract_payload["source_status"] = "healthy"
    snapshot = ResourceSnapshot(
        source_key=source_key,
        adapter=descriptor["adapter"],
        resource=descriptor["resource"],
        title=descriptor["title"],
        description=descriptor["description"],
        analytical_comparisons=[comparison] if comparison is not None else [],
        evidence=evidence,
        metadata=metadata,
        captured_at=captured_at,
        source_captured_at=captured_at - timedelta(hours=1),
        contract=ResourceContract(**contract_payload),
    )
    return snapshot.model_dump(mode="json")


def _rate(value: tuple[int, int] | None) -> Fraction | None:
    if value is None or value[1] <= 0:
        return None
    return Fraction(value[0], value[1])


def _analysis(
    *,
    spec: dict[str, Any],
    comparison: dict[str, Any],
    oracle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_key": spec["primary_key"],
        "comparison_key": comparison["key"],
        "metric": comparison["metric"],
        "unit": comparison["unit"],
        "dimension": comparison["dimension"],
        "definition": comparison["definition"],
        "population": comparison["population"],
        "baseline_start": comparison["baseline_start"],
        "baseline_end": comparison["baseline_end"],
        "current_start": comparison["current_start"],
        "current_end": comparison["current_end"],
        "baseline": oracle["baseline"],
        "current": oracle["current"],
        "delta": oracle["delta"],
        "within_effect": oracle["within_effect"],
        "mix_effect": oracle["mix_effect"],
        "contributions": oracle["contributions"],
        "query_refs": list(comparison["query_refs"]),
    }


def _oracle(*, spec: dict[str, Any], rows: list[dict[str, Any]], coverage: str, context_status: str) -> dict[str, Any]:
    signed = spec.get("signed", False)
    if spec["kind"] == "additive":
        baseline, current = _group_additive(rows)
        baseline_total = sum(baseline.values()) if baseline else None
        current_total = sum(current.values()) if current else None
        complete = coverage == "complete" and all(segment in baseline and segment in current for segment in spec["segments"])
        delta = current_total - baseline_total if complete and baseline_total is not None and current_total is not None else None
        contributions = [
            {
                "segment": segment,
                "baseline": baseline[segment],
                "current": current[segment],
                "contribution": current[segment] - baseline[segment],
            }
            for segment in sorted(spec["segments"])
            if segment in baseline and segment in current
        ]
        quantitative = {
            "baseline": baseline_total,
            "current": current_total if complete else None,
            "delta": delta,
            "within_effect": None,
            "mix_effect": None,
            "contributions": contributions if complete else [],
        }
        if signed:
            numeric_trigger = complete and (
                (delta is not None and delta <= spec["delta_threshold"])
                or any(item["contribution"] <= spec["contribution_threshold"]
                       for item in contributions if item["segment"] in {"contraction", "churn"})
            )
        else:
            numeric_trigger = complete and (
                (delta is not None and delta >= spec["delta_threshold"])
                or any(item["contribution"] >= spec["contribution_threshold"] for item in contributions)
            )
    else:
        baseline, current = _group_rate(rows)
        baseline_total = {
            "numerator": sum(value[0] for value in baseline.values()) if baseline else None,
            "denominator": sum(value[1] for value in baseline.values()) if baseline else None,
        }
        current_total = {
            "numerator": sum(value[0] for value in current.values()) if current else None,
            "denominator": sum(value[1] for value in current.values()) if current else None,
        }
        complete = coverage == "complete" and all(segment in baseline and segment in current for segment in spec["segments"])
        baseline_rate = (
            Fraction(baseline_total["numerator"], baseline_total["denominator"])
            if complete and baseline_total["numerator"] is not None and baseline_total["denominator"] else None
        )
        current_rate = (
            Fraction(current_total["numerator"], current_total["denominator"])
            if complete and current_total["numerator"] is not None and current_total["denominator"] else None
        )
        contributions: list[dict[str, Any]] = []
        within = Fraction()
        mix = Fraction()
        if complete and baseline_rate is not None and current_rate is not None:
            for segment in sorted(spec["segments"]):
                r0, r1 = _rate(baseline[segment]), _rate(current[segment])
                w0 = Fraction(baseline[segment][1], baseline_total["denominator"])
                w1 = Fraction(current[segment][1], current_total["denominator"])
                within_part = (w0 + w1) * (r1 - r0) / 2
                mix_part = (r0 + r1) * (w1 - w0) / 2
                within += within_part
                mix += mix_part
                contributions.append({
                    "segment": segment,
                    "baseline": float(r0),
                    "current": float(r1),
                    "contribution": float(within_part + mix_part),
                    "within_effect": float(within_part),
                    "mix_effect": float(mix_part),
                })
        delta = current_rate - baseline_rate if current_rate is not None and baseline_rate is not None else None
        quantitative = {
            "baseline": float(baseline_rate) if baseline_rate is not None else None,
            "current": float(current_rate) if current_rate is not None else None,
            "delta": float(delta) if delta is not None else None,
            "within_effect": float(within) if complete else None,
            "mix_effect": float(mix) if complete else None,
            "contributions": contributions if complete else [],
        }
        numeric_trigger = complete and (
            (quantitative["current"] is not None and quantitative["current"] >= spec["current_threshold"])
            or (quantitative["delta"] is not None and quantitative["delta"] >= spec["delta_threshold"])
        )

    if not complete:
        outcome = "insufficient_data"
        route_keys = [spec["insufficient_key"]]
    elif signed and numeric_trigger and context_status == "unavailable":
        outcome = "investigate"
        route_keys = [spec["investigate_key"]]
    elif signed and numeric_trigger and context_status == "approved":
        outcome = "ignore"
        route_keys = []
    elif numeric_trigger:
        outcome = "notify"
        route_keys = [spec["notify_key"]]
    else:
        outcome = "ignore"
        route_keys = []
    return {
        **quantitative,
        "status": "complete" if complete else "blocked",
        "outcome": outcome,
        "recipients": route_keys,
        "context_status": context_status,
        "materiality": {
            key: spec[key]
            for key in ("delta_threshold", "contribution_threshold", "current_threshold")
            if key in spec
        },
    }


def _build_period(spec: dict[str, Any], period: dict[str, Any], index: int) -> dict[str, Any]:
    dates = _period_dates(index, step_days=spec["step_days"])
    as_of = dates["current_end"] + timedelta(hours=2)
    primary_rows = spec["rows"](spec["company_id"], period["id"], period["values"])
    comparison = _comparison(
        spec=spec,
        rows=primary_rows,
        dates=dates,
        coverage=period["coverage"],
        query_ref=f"query:{spec['company_id']}:reporting:{period['id']}",
    )
    context_status = period.get("context_status", "not_applicable")
    snapshots = {
        f"company_mcp|{spec['primary_resource']}": _snapshot(
            descriptor=spec["primary_descriptor"],
            company_id=spec["company_id"],
            period_id=period["id"],
            as_of=as_of,
            comparison=comparison,
            rows=primary_rows,
            coverage=period["coverage"],
            comparability_note=period["comparability_note"],
        )
    }
    if spec.get("context_descriptor"):
        context_text = {
            "approved": "The owner-approved exception register says the exception covers this exact closed period.",
            "none": "The exception register says no owner-approved exception covers this exact closed period.",
            "unavailable": "The exception register has not published a status for this exact closed period.",
        }[context_status]
        snapshots[f"company_mcp|{spec['context_resource']}"] = _snapshot(
            descriptor=spec["context_descriptor"],
            company_id=spec["company_id"],
            period_id=period["id"],
            as_of=as_of,
            comparison=None,
            rows=[],
            coverage="complete",
            comparability_note="This context source is qualitative and is not an analytical comparison.",
            context={"exception_status": context_status, "statement": context_text},
        )
    oracle = _oracle(spec=spec, rows=primary_rows, coverage=period["coverage"], context_status=context_status)
    analyses = []
    if oracle["status"] == "complete":
        analyses = [_analysis(spec=spec, comparison=comparison, oracle=oracle)]
    numeric_policy = []
    for measurement in ("current", "delta", "contribution"):
        if f"{measurement}_threshold" not in spec:
            continue
        threshold = spec[f"{measurement}_threshold"]
        segments = ["contraction", "churn"] if spec.get("signed") and measurement == "contribution" else [None]
        for segment in segments:
            numeric_policy.append({
                "source_key": spec["primary_key"], "comparison_key": comparison["key"],
                "unit": spec["unit"], "measurement": measurement, "segment": segment,
                "absolute": False, "comparator": "<=" if spec.get("signed") else ">=",
                "threshold": threshold,
            })
    return {
        "id": period["id"],
        "split": period["split"],
        "as_of": _iso(as_of),
        "resources": list(snapshots.values()),
        "oracle": {
            "numeric_policy": numeric_policy,
            "status": oracle["status"],
            "outcome": oracle["outcome"],
            "recipients": oracle["recipients"],
            "analyses": analyses,
            "semantic_status": context_status,
            "context_status": context_status,
            "measurements": {
                "baseline": oracle["baseline"],
                "current": oracle["current"],
                "delta": oracle["delta"],
                "contributions": oracle["contributions"],
                "within_effect": oracle["within_effect"],
                "mix_effect": oracle["mix_effect"],
            },
            "materiality": oracle["materiality"],
        },
    }


def _additive_rows(company_id: str, period_id: str, values: dict[str, tuple[int | None, int | None]]) -> list[dict[str, Any]]:
    return _rows_additive(company_id, period_id, values)


def _rate_rows(company_id: str, period_id: str, values: dict[str, tuple[int | None, int | None, int | None, int | None]]) -> list[dict[str, Any]]:
    return _rows_rate(company_id, period_id, values)


def _company_specs() -> list[dict[str, Any]]:
    """Return source/policy specs; expected labels are created only by ``_build_period``."""
    return [
        {
            "company_id": "juniper-bookings",
            "company": "Juniper Bookings",
            "brief": "Monitor canceled paid reservations across booking channels.",
            "owner_policy": (
                "Use canceled paid reservations in the closed weekly interval, after duplicate removal and excluding test reservations. "
                "Compare the same channel population in adjacent closed weeks. Treat the comparison as valid only when the source "
                "explicitly flags the same population, the same definition, adjacent periods, a complete channel partition, and "
                "reconciled totals. Notify Booking Operations when the total cancellation count is at least 24 higher than baseline "
                "or when any channel's cancellation count is at least 18 higher than its baseline. In both cases, compare current "
                "minus baseline; a negative contribution is not an increase. If coverage is partial or the source does not provide "
                "all of those positive comparability flags, route insufficient_data to Data Quality. For complete movements that meet "
                "neither threshold, ignore. State contributions as an accounting decomposition, not causes."
            ),
            "comparison_key": "paid-cancellations",
            "metric": "canceled_paid_reservations",
            "definition": "Paid reservations canceled in the closed interval after duplicate removal and test-reservation exclusion.",
            "population": "paid reservations with a cancellation timestamp, excluding test reservations",
            "dimension": "booking_channel",
            "unit": "reservations",
            "kind": "additive",
            "grain": "weekly booking interval",
            "segments": ["direct", "mobile", "partner"],
            "step_days": 7,
            "delta_threshold": 24,
            "contribution_threshold": 18,
            "notify_key": "booking-operations",
            "insufficient_key": "booking-data-quality",
            "primary_resource": "paid-cancellations",
            "policy_destinations": [
                {"key": "booking-operations", "label": "Booking Operations", "destination": "agent://booking-operations"},
                {"key": "booking-data-quality", "label": "Booking Data Quality", "destination": "agent://booking-data-quality"},
            ],
            "rows": _additive_rows,
            "periods": [
                {"id": "p01", "split": "setup", "coverage": "complete", "comparability_note": "All three channels are present under the same paid-reservation definition.", "values": {"direct": (120, 126), "mobile": (180, 205), "partner": (60, 58)}},
                {"id": "p02", "split": "setup", "coverage": "complete", "comparability_note": "All three channels are present under the same paid-reservation definition.", "values": {"direct": (126, 127), "mobile": (205, 202), "partner": (58, 58)}},
                {"id": "p03", "split": "holdout", "coverage": "complete", "comparability_note": "All three channels are present and the channel partition reconciles to the selected population.", "values": {"direct": (160, 135), "mobile": (210, 238), "partner": (70, 77)}},
                {"id": "p04", "split": "holdout", "coverage": "complete", "comparability_note": "All three channels are present and the channel partition reconciles to the selected population.", "values": {"direct": (240, 250), "mobile": (150, 160), "partner": (80, 85)}},
                {"id": "p05", "split": "holdout", "coverage": "complete", "comparability_note": "All three channels are present and the channel partition reconciles to the selected population.", "values": {"direct": (260, 266), "mobile": (170, 165), "partner": (90, 90)}},
                {"id": "p06", "split": "holdout", "coverage": "partial", "comparability_note": "The current partner channel is absent; the visible current total is not a comparable all-channel total.", "values": {"direct": (250, 268), "mobile": (160, 174), "partner": (90, None)}},
            ],
        },
        {
            "company_id": "mosaic-payments",
            "company": "Mosaic Payments",
            "brief": "Monitor weighted payment-authorization failure rate across payment rails.",
            "owner_policy": (
                "Use eligible payment authorization attempts and weight the failure rate by attempt count across card, bank-transfer, "
                "and wallet rails; do not average the rail percentages. Notify Payments Operations when the weighted current failure "
                "rate is at least 4.8% OR when the weighted failure-rate change from baseline is at least 1.2 percentage points. "
                "Compare current minus baseline for the change. Treat the comparison as valid only when the source explicitly flags "
                "the same population, the same definition, adjacent periods, a complete rail partition, and reconciled totals. If any "
                "eligible rail is missing or the source does not provide all of those positive comparability flags, route "
                "insufficient_data to Payments Data. If the comparison is complete and neither threshold is met, ignore. Report "
                "rate and mix effects as descriptive accounting terms, not causes."
            ),
            "comparison_key": "authorization-failure-rate",
            "metric": "payment_authorization_failure_rate",
            "definition": "Failed eligible payment authorization attempts divided by all eligible authorization attempts.",
            "population": "eligible payment authorization attempts with a rail and outcome",
            "dimension": "payment_rail",
            "unit": "ratio",
            "kind": "rate",
            "grain": "weekly authorization interval",
            "segments": ["bank_transfer", "card", "wallet"],
            "step_days": 7,
            "current_threshold": 0.048,
            "delta_threshold": 0.012,
            "notify_key": "payments-operations",
            "insufficient_key": "payments-data",
            "primary_resource": "authorization-failure-rate",
            "policy_destinations": [
                {"key": "payments-operations", "label": "Payments Operations", "destination": "agent://payments-operations"},
                {"key": "payments-data", "label": "Payments Data", "destination": "agent://payments-data"},
            ],
            "rows": _rate_rows,
            "periods": [
                {"id": "p01", "split": "setup", "coverage": "complete", "comparability_note": "All three rails have eligible attempts in both adjacent weeks.", "values": {"card": (12, 300, 15, 300), "bank_transfer": (9, 300, 12, 300), "wallet": (4, 200, 5, 200)}},
                {"id": "p02", "split": "setup", "coverage": "complete", "comparability_note": "All three rails have eligible attempts in both adjacent weeks.", "values": {"card": (15, 300, 20, 300), "bank_transfer": (10, 300, 12, 300), "wallet": (4, 200, 7, 200)}},
                {"id": "p03", "split": "holdout", "coverage": "complete", "comparability_note": "All three rails have eligible attempts and the weighted denominator is the sum of their eligible attempts.", "values": {"card": (15, 300, 20, 400), "bank_transfer": (12, 300, 15, 300), "wallet": (8, 200, 10, 200)}},
                {"id": "p04", "split": "holdout", "coverage": "complete", "comparability_note": "All three rails have eligible attempts and the weighted denominator is the sum of their eligible attempts.", "values": {"card": (8, 300, 14, 360), "bank_transfer": (8, 300, 13, 300), "wallet": (4, 200, 10, 240)}},
                {"id": "p05", "split": "holdout", "coverage": "complete", "comparability_note": "All three rails have eligible attempts and the weighted denominator is the sum of their eligible attempts.", "values": {"card": (12, 300, 13, 320), "bank_transfer": (10, 300, 10, 300), "wallet": (8, 200, 8, 200)}},
                {"id": "p06", "split": "holdout", "coverage": "partial", "comparability_note": "Current wallet attempts are absent; the visible current denominator cannot represent all three rails.", "values": {"card": (14, 320, 15, 330), "bank_transfer": (10, 300, 12, 300), "wallet": (6, 200, None, None)}},
            ],
        },
        {
            "company_id": "saffron-cloud",
            "company": "Saffron Cloud",
            "brief": "Monitor signed monthly recurring-revenue movements from subscription changes.",
            "owner_policy": (
                "Use signed monthly recurring-revenue movements from effective subscription-change records for the same billed accounts. "
                "Expansion and new-logo are positive; contraction and churn are negative. Notify Revenue Operations when net signed "
                "movement falls by $90 or more from baseline or when any contraction or churn segment is at least $60 lower than its "
                "baseline. Compare current minus baseline and preserve the signs: do not convert signed movement to absolute volume "
                "or use booked pipeline. Treat the comparison as valid only when the source explicitly flags the same population, the "
                "same definition, adjacent periods, a complete movement partition, and reconciled totals. An approved pricing-freeze "
                "context for the exact closed month overrides both numeric triggers and means ignore. If that context is unavailable "
                "while a numeric trigger is present, investigate and route to Revenue Data Review. If the movement export is partial "
                "or the source does not provide all of those positive comparability flags, route insufficient_data to Revenue Data "
                "Review. If the comparison is complete, no exception applies, and neither threshold is met, ignore. Contributions "
                "explain measured movement, not causes."
            ),
            "comparison_key": "signed-mrr-movement",
            "metric": "signed_mrr_movement",
            "definition": "Signed monthly recurring-revenue movement recorded for effective subscription changes; contraction and churn are negative.",
            "population": "billed subscription accounts with an effective subscription-change record",
            "dimension": "movement_type",
            "unit": "USD",
            # The runtime supports additive comparisons; signed movement is
            # represented by negative additive values, not a new analytical kind.
            "kind": "additive",
            "signed": True,
            "segments": ["contraction", "churn", "expansion", "new_logo"],
            "grain": "monthly subscription interval",
            "step_days": 28,
            "delta_threshold": -90,
            "contribution_threshold": -60,
            "notify_key": "revenue-operations",
            "investigate_key": "revenue-data-review",
            "insufficient_key": "revenue-data-review",
            "primary_resource": "signed-mrr-movement",
            "context_resource": "pricing-freeze-register",
            "policy_destinations": [
                {"key": "revenue-operations", "label": "Revenue Operations", "destination": "agent://revenue-operations"},
                {"key": "revenue-data-review", "label": "Revenue Data Review", "destination": "agent://revenue-data-review"},
            ],
            "rows": _additive_rows,
            "periods": [
                {"id": "p01", "split": "setup", "coverage": "complete", "context_status": "none", "comparability_note": "All movement types are present for the same billed-account population.", "values": {"contraction": (-60, -70), "churn": (-30, -35), "expansion": (120, 130), "new_logo": (50, 45)}},
                {"id": "p02", "split": "setup", "coverage": "complete", "context_status": "none", "comparability_note": "All movement types are present for the same billed-account population.", "values": {"contraction": (-70, -110), "churn": (-40, -80), "expansion": (150, 100), "new_logo": (60, 40)}},
                {"id": "p03", "split": "holdout", "coverage": "complete", "context_status": "none", "comparability_note": "All movement types are present and the signed partition reconciles to the selected population.", "values": {"contraction": (-80, -85), "churn": (-35, -100), "expansion": (140, 150), "new_logo": (50, 45)}},
                {"id": "p04", "split": "holdout", "coverage": "complete", "context_status": "none", "comparability_note": "All movement types are present and the signed partition reconciles to the selected population.", "values": {"contraction": (-75, -80), "churn": (-50, -60), "expansion": (130, 60), "new_logo": (45, 115)}},
                {"id": "p05", "split": "holdout", "coverage": "complete", "context_status": "approved", "comparability_note": "All movement types are present and the signed partition reconciles to the selected population.", "values": {"contraction": (-80, -120), "churn": (-40, -100), "expansion": (160, 90), "new_logo": (50, 35)}},
                {"id": "p06", "split": "holdout", "coverage": "complete", "context_status": "unavailable", "comparability_note": "All movement types are present, but the owner context source has no status for this exact month.", "values": {"contraction": (-85, -125), "churn": (-35, -85), "expansion": (150, 100), "new_logo": (45, 30)}},
            ],
        },
    ]


def _build_company(spec: dict[str, Any]) -> dict[str, Any]:
    primary = _descriptor(
        source_key=f"{spec['company_id']}-reporting",
        resource=f"report:{spec['primary_resource']}",
        title={
            "juniper-bookings": "Paid cancellations by booking channel",
            "mosaic-payments": "Weighted authorization failure rate by payment rail",
            "saffron-cloud": "Signed MRR movement by movement type",
        }[spec["company_id"]],
        description=spec["definition"],
        metric_names=[spec["metric"]],
        comparison_keys=[spec["comparison_key"]],
        population=spec["population"],
        grain=spec["grain"],
        business_role="reporting",
    )
    spec = copy.deepcopy(spec)
    spec["primary_descriptor"] = primary
    spec["primary_key"] = primary["source_key"]
    descriptors = [primary]
    if spec.get("context_resource"):
        context = _descriptor(
            source_key=f"{spec['company_id']}-context",
            resource=f"record:{spec['context_resource']}",
            title="Pricing-freeze exception register",
            description="Owner context stating whether an approved pricing-freeze exception covers the exact closed month.",
            metric_names=["pricing_freeze_exception"],
            comparison_keys=[],
            population="owner-approved pricing-freeze records keyed to a closed month",
            grain="monthly exception record",
            business_role="owner_context",
            semantic_contract="Status is one of approved, none, or unavailable; this source is qualitative and has no analytical comparison.",
        )
        spec["context_descriptor"] = context
        descriptors.append(context)
    periods = [_build_period(spec, period, index) for index, period in enumerate(spec["periods"])]
    return {
        "id": spec["company_id"],
        "company": spec["company"],
        "brief": spec["brief"],
        "owner_policy": spec["owner_policy"],
        "descriptors": descriptors,
        "sources": [_source_ref(descriptor) for descriptor in descriptors],
        "destinations": spec["policy_destinations"],
        "review_guidance": copy.deepcopy(REVIEW_GUIDANCE),
        "periods": periods,
    }


def cases() -> list[dict[str, Any]]:
    """Return fresh copies of the three companies and their private oracles."""
    return [_build_company(spec) for spec in _company_specs()]


def public_company(company: dict[str, Any]) -> dict[str, Any]:
    """Remove evaluation labels while retaining all setup and future data."""
    result = copy.deepcopy(company)
    for period in result["periods"]:
        period.pop("oracle", None)
        period.pop("split", None)
    return result


def onboarding_company(company: dict[str, Any]) -> dict[str, Any]:
    """Return the only company view an onboarding author may inspect."""
    result = copy.deepcopy(company)
    result["periods"] = []
    for period in company["periods"]:
        if period["split"] != "setup":
            continue
        result["periods"].append({
            key: copy.deepcopy(value)
            for key, value in period.items()
            if key not in {"oracle", "split"}
        })
    return result


__all__ = ["REVIEW_GUIDANCE", "cases", "onboarding_company", "public_company"]

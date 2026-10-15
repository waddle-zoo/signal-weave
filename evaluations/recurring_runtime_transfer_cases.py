"""Prospective transfer fixtures for the recurring-runtime review.

These cases are independent synthetic companies with plain-English policies,
source contracts, six sparse comparison periods, and private evaluation
labels.  They contain no plan, rule language, or runtime calls.
"""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

from evaluations.recurring_runtime_cases import (
    REVIEW_GUIDANCE,
    _analysis,
    _comparison,
    _descriptor,
    _iso,
    _oracle,
    _period_dates,
    _rows_additive,
    _rows_rate,
    _snapshot,
    _source_ref,
)


def _build_period(spec: dict[str, Any], period: dict[str, Any], index: int) -> dict[str, Any]:
    dates = _period_dates(index, step_days=spec["step_days"])
    as_of = dates["current_end"] + timedelta(hours=2)
    rows = spec["rows"](spec["company_id"], period["id"], period["values"])
    comparison = _comparison(
        spec=spec,
        rows=rows,
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
            rows=rows,
            coverage=period["coverage"],
            comparability_note=period["comparability_note"],
        )
    }
    if spec.get("context_descriptor"):
        statement = {
            "approved": "The exception register says an owner-approved exception covers this exact closed period.",
            "none": "The exception register says no owner-approved exception covers this exact closed period.",
            "unavailable": "The exception register is available and healthy but does not state whether an exception covers this exact closed period.",
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
            context={
                "exception_status": "unresolved" if context_status == "unavailable" else context_status,
                "statement": statement,
            },
        )

    oracle = _oracle(
        spec=spec,
        rows=rows,
        coverage=period["coverage"],
        context_status=context_status,
    )
    analyses = []
    if oracle["status"] == "complete":
        analyses = [_analysis(spec=spec, comparison=comparison, oracle=oracle)]

    numeric_policy = []
    for measurement in ("current", "delta", "contribution"):
        if f"{measurement}_threshold" not in spec:
            continue
        threshold = spec[f"{measurement}_threshold"]
        segments = (
            ["contraction", "churn"]
            if spec.get("signed") and measurement == "contribution"
            else [None]
        )
        for segment in segments:
            numeric_policy.append({
                "source_key": spec["primary_key"],
                "comparison_key": comparison["key"],
                "unit": spec["unit"],
                "measurement": measurement,
                "segment": segment,
                "absolute": False,
                "comparator": "<=" if spec.get("signed") else ">=",
                "threshold": threshold,
            })

    displayed_context_status = "unresolved" if context_status == "unavailable" else context_status
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
            "semantic_status": displayed_context_status,
            "context_status": displayed_context_status,
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


def _build_company(spec: dict[str, Any]) -> dict[str, Any]:
    spec = copy.deepcopy(spec)
    primary = _descriptor(
        source_key=f"{spec['company_id']}-reporting",
        resource=f"report:{spec['primary_resource']}",
        title=spec["title"],
        description=spec["definition"],
        metric_names=[spec["metric"]],
        comparison_keys=[spec["comparison_key"]],
        population=spec["population"],
        grain=spec["grain"],
        business_role="reporting",
    )
    spec["primary_descriptor"] = primary
    spec["primary_key"] = primary["source_key"]
    descriptors = [primary]
    if spec.get("context_resource"):
        context = _descriptor(
            source_key=f"{spec['company_id']}-context",
            resource=f"record:{spec['context_resource']}",
            title=spec["context_title"],
            description="Owner context stating whether an approved exception covers the exact closed period.",
            metric_names=["owner_exception"],
            comparison_keys=[],
            population="owner-approved exceptions keyed to a closed period",
            grain=spec["grain"],
            business_role="owner_context",
            semantic_contract="Status is approved, none, or unresolved; this source has no analytical comparison.",
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


def _specs() -> list[dict[str, Any]]:
    return [
        {
            "company_id": "canyon-freight",
            "company": "Canyon Freight",
            "title": "Late deliveries by service lane",
            "brief": "Monitor late delivery counts across service lanes.",
            "owner_policy": (
                "Use late deliveries in adjacent closed weeks for the same shipment population after duplicate removal. "
                "Notify Fleet Operations when the total is at least 17 higher than baseline or when any service lane is at least "
                "11 higher than its baseline. Compare current minus baseline; a negative lane contribution is not an increase. "
                "Use the result only when the source confirms the same population, definition, adjacent periods, complete lane "
                "partition, and reconciled totals. Route incomplete comparisons as insufficient_data to Logistics Data. If neither threshold is met, "
                "ignore. Describe lane contributions as accounting decomposition, not causes."
            ),
            "comparison_key": "late-deliveries",
            "metric": "late_delivery_count",
            "definition": "Shipments delivered late in the closed interval after duplicate removal.",
            "population": "non-duplicate shipments with a delivery timestamp",
            "dimension": "service_lane",
            "unit": "deliveries",
            "kind": "additive",
            "grain": "weekly delivery interval",
            "segments": ["air", "ground", "ocean"],
            "step_days": 7,
            "delta_threshold": 17,
            "contribution_threshold": 11,
            "notify_key": "fleet-operations",
            "insufficient_key": "logistics-data",
            "primary_resource": "late-deliveries",
            "policy_destinations": [
                {"key": "fleet-operations", "label": "Fleet Operations", "destination": "agent://fleet-operations"},
                {"key": "logistics-data", "label": "Logistics Data", "destination": "agent://logistics-data"},
            ],
            "rows": _rows_additive,
            "periods": [
                {"id": "p01", "split": "setup", "coverage": "complete", "comparability_note": "All lanes are present under the same shipment definition.", "values": {"air": (80, 50), "ground": (140, 135), "ocean": (50, 48)}},
                {"id": "p02", "split": "setup", "coverage": "complete", "comparability_note": "All lanes are present under the same shipment definition.", "values": {"air": (84, 99), "ground": (145, 150), "ocean": (48, 50)}},
                {"id": "p03", "split": "holdout", "coverage": "complete", "comparability_note": "All lanes are present and the partition reconciles to the selected population.", "values": {"air": (100, 112), "ground": (80, 82), "ocean": (40, 39)}},
                {"id": "p04", "split": "holdout", "coverage": "complete", "comparability_note": "All lanes are present and the partition reconciles to the selected population.", "values": {"air": (150, 130), "ground": (90, 88), "ocean": (60, 65)}},
                {"id": "p05", "split": "holdout", "coverage": "partial", "comparability_note": "The current ocean lane is absent; the visible total is not comparable.", "values": {"air": (120, 126), "ground": (90, 95), "ocean": (60, None)}},
                {"id": "p06", "split": "holdout", "coverage": "complete", "comparability_note": "All lanes are present and the partition reconciles to the selected population.", "values": {"air": (120, 125), "ground": (140, 150), "ocean": (80, 92)}},
            ],
        },
        {
            "company_id": "helio-support",
            "company": "Helio Support",
            "title": "Weighted recontact quality rate by support channel",
            "brief": "Monitor weighted customer recontact quality across support channels.",
            "owner_policy": (
                "Use the weighted recontact rate across eligible support conversations, using conversation counts rather than an "
                "average of channel percentages. Notify Support Quality when the weighted current rate is at least 9% or when "
                "current minus baseline is at least 2.5 percentage points. Use adjacent closed weeks and require the source to "
                "confirm the same population, definition, complete channel partition, and reconciled totals. Route incomplete "
                "comparisons as insufficient_data to Support Data. If neither threshold is met, ignore. Describe channel accounting effects without "
                "claiming causes."
            ),
            "comparison_key": "recontact-quality-rate",
            "metric": "customer_recontact_rate",
            "definition": "Eligible support conversations followed by a customer recontact within the quality window, divided by eligible conversations.",
            "population": "eligible support conversations with a channel and quality outcome",
            "dimension": "support_channel",
            "unit": "ratio",
            "kind": "rate",
            "grain": "weekly support interval",
            "segments": ["chat", "email", "voice"],
            "step_days": 7,
            "current_threshold": 0.09,
            "delta_threshold": 0.025,
            "notify_key": "support-quality",
            "insufficient_key": "support-data",
            "primary_resource": "recontact-quality-rate",
            "policy_destinations": [
                {"key": "support-quality", "label": "Support Quality", "destination": "agent://support-quality"},
                {"key": "support-data", "label": "Support Data", "destination": "agent://support-data"},
            ],
            "rows": _rows_rate,
            "periods": [
                {"id": "p01", "split": "setup", "coverage": "complete", "comparability_note": "All channels have eligible conversations in both adjacent weeks.", "values": {"chat": (12, 240, 16, 240), "email": (10, 240, 14, 240), "voice": (6, 120, 8, 120)}},
                {"id": "p02", "split": "setup", "coverage": "complete", "comparability_note": "All channels have eligible conversations in both adjacent weeks.", "values": {"chat": (15, 240, 30, 240), "email": (12, 240, 20, 240), "voice": (7, 120, 12, 120)}},
                {"id": "p03", "split": "holdout", "coverage": "complete", "comparability_note": "All channels are present and the weighted denominator reconciles.", "values": {"chat": (30, 240, 42, 360), "email": (20, 240, 28, 240), "voice": (10, 120, 15, 120)}},
                {"id": "p04", "split": "holdout", "coverage": "complete", "comparability_note": "All channels are present and the weighted denominator reconciles.", "values": {"chat": (18, 360, 30, 360), "email": (16, 320, 24, 320), "voice": (6, 120, 10, 120)}},
                {"id": "p05", "split": "holdout", "coverage": "complete", "comparability_note": "All channels are present and the weighted denominator reconciles.", "values": {"chat": (18, 300, 24, 300), "email": (20, 400, 26, 400), "voice": (8, 300, 10, 300)}},
                {"id": "p06", "split": "holdout", "coverage": "partial", "comparability_note": "Current voice conversations are absent; the visible denominator is incomplete.", "values": {"chat": (20, 320, 25, 320), "email": (18, 300, 24, 300), "voice": (8, 120, None, None)}},
            ],
        },
        {
            "company_id": "lattice-energy",
            "company": "Lattice Energy",
            "title": "Signed monthly contract-value movement by change type",
            "brief": "Monitor signed contract-value movement across customer change types.",
            "owner_policy": (
                "Use signed monthly contract-value movement from effective account-change records for the same billed accounts. "
                "Expansion and new contracts are positive; contraction and churn are negative. Notify Commercial Operations when "
                "net movement is at least $75 lower than baseline or when the exact contraction or churn contribution is at least "
                "$45 lower than baseline. Preserve signs and compare current minus baseline. Require the source to confirm the same "
                "population, definition, adjacent periods, complete change-type partition, and reconciled totals. An approved "
                "service-credit exception for the exact closed month overrides a numeric trigger and means ignore. If that context "
                "is unresolved while a trigger is present in a complete analytical report, investigate with Commercial Data. A "
                "partial or otherwise incomplete analytical comparison is insufficient_data and also routes to Commercial Data. "
                "If the complete report has no trigger, or an approved exception covers the exact month, ignore. Contributions "
                "describe measured movement, not causes."
            ),
            "comparison_key": "signed-contract-movement",
            "metric": "signed_contract_value_movement",
            "definition": "Signed contract-value movement from effective account changes; contraction and churn are negative.",
            "population": "billed accounts with an effective contract-change record",
            "dimension": "change_type",
            "unit": "USD",
            "kind": "additive",
            "signed": True,
            "grain": "monthly contract interval",
            "segments": ["contraction", "churn", "expansion", "new_contract"],
            "step_days": 28,
            "delta_threshold": -75,
            "contribution_threshold": -45,
            "notify_key": "commercial-operations",
            "investigate_key": "commercial-data",
            "insufficient_key": "commercial-data",
            "primary_resource": "signed-contract-movement",
            "context_resource": "service-credit-register",
            "context_title": "Service-credit exception register",
            "policy_destinations": [
                {"key": "commercial-operations", "label": "Commercial Operations", "destination": "agent://commercial-operations"},
                {"key": "commercial-data", "label": "Commercial Data", "destination": "agent://commercial-data"},
            ],
            "rows": _rows_additive,
            "periods": [
                {"id": "p01", "split": "setup", "coverage": "complete", "context_status": "none", "comparability_note": "All change types are present for the same billed-account population.", "values": {"contraction": (-40, -45), "churn": (-20, -25), "expansion": (100, 110), "new_contract": (30, 35)}},
                {"id": "p02", "split": "setup", "coverage": "complete", "context_status": "none", "comparability_note": "All change types are present for the same billed-account population.", "values": {"contraction": (-50, -80), "churn": (-25, -45), "expansion": (120, 100), "new_contract": (40, 35)}},
                {"id": "p03", "split": "holdout", "coverage": "complete", "context_status": "none", "comparability_note": "All change types are present and the signed partition reconciles.", "values": {"contraction": (-20, -25), "churn": (-20, -70), "expansion": (100, 90), "new_contract": (30, 20)}},
                {"id": "p04", "split": "holdout", "coverage": "complete", "context_status": "none", "comparability_note": "All change types are present and the signed partition reconciles.", "values": {"contraction": (-40, -45), "churn": (-30, -35), "expansion": (100, 40), "new_contract": (20, 95)}},
                {"id": "p05", "split": "holdout", "coverage": "complete", "context_status": "approved", "comparability_note": "All change types are present and the signed partition reconciles.", "values": {"contraction": (-30, -90), "churn": (-25, -70), "expansion": (130, 80), "new_contract": (40, 20)}},
                {"id": "p06", "split": "holdout", "coverage": "complete", "context_status": "unavailable", "comparability_note": "All change types are present; the healthy exception register does not state whether an exception covers this exact month.", "values": {"contraction": (-35, -90), "churn": (-20, -25), "expansion": (100, 100), "new_contract": (30, 20)}},
            ],
        },
    ]


def cases() -> list[dict[str, Any]]:
    return [_build_company(spec) for spec in _specs()]


def public_company(company: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(company)
    for period in result["periods"]:
        period.pop("oracle", None)
        period.pop("split", None)
    return result


def onboarding_company(company: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(company)
    result["periods"] = [
        {
            key: copy.deepcopy(value)
            for key, value in period.items()
            if key not in {"oracle", "split"}
        }
        for period in company["periods"]
        if period["split"] == "setup"
    ]
    return result


__all__ = ["REVIEW_GUIDANCE", "cases", "onboarding_company", "public_company"]

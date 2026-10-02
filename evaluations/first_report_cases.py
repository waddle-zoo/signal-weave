"""Independent fixtures for the first-report onboarding trial.

``cases()`` returns four JSON-serializable companies with three closed period
comparisons each.  A company contains the public brief,
an adapter-owned directory, the snapshots returned for that period, and a
separate ``oracle``.  The oracle is evaluation-only; it is not part of the
source payload an author should inspect.

The primary comparisons are built from generated transaction or record rows.
The oracle recomputes totals, contributions, and the materiality route from
those rows with the standard library.  This module intentionally does not use
SignalWeave's production diagnostics solver or create an expert card.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Any

from signalweave.models import ResourceContract, ResourceDescriptor, ResourceSnapshot, SourceRef

UTC = timezone.utc
WINDOW = "previous_period"
AS_OF = datetime(2026, 10, 2, 12, tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _period_dates(index: int) -> dict[str, datetime]:
    start = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=index * 14)
    return {
        "baseline_start": start,
        "baseline_end": start + timedelta(days=7),
        "current_start": start + timedelta(days=7),
        "current_end": start + timedelta(days=14),
    }


def _rows_additive(company: str, period: str, values: dict[str, list[int]]) -> list[dict[str, Any]]:
    """Expand ``segment -> [baseline_total, current_total]`` into rows."""
    rows = []
    for segment, amounts in values.items():
        for period_name, amount in (("baseline", amounts[0]), ("current", amounts[1])):
            rows.append({
                "record_id": f"{company}-{period}-{period_name}-{segment}",
                "period": period_name,
                "segment": segment,
                "value": amount,
            })
    return rows


def _rows_rate(
    company: str,
    period: str,
    values: list[tuple[str, int, int, int | None, int | None]],
) -> list[dict[str, Any]]:
    """Expand ``(segment, baseline_misses, baseline_total, current_misses, current_total)``."""
    rows: list[dict[str, Any]] = []
    for segment, baseline_misses, baseline_total, current_misses, current_total in values:
        for period_name, misses, total in (
            ("baseline", baseline_misses, baseline_total),
            ("current", current_misses, current_total),
        ):
            if misses is None or total is None:
                continue
            for index in range(total):
                rows.append({
                    "record_id": f"{company}-{period}-{period_name}-{segment}-{index}",
                    "period": period_name,
                    "segment": segment,
                    "eligible": True,
                    "missed": index < misses,
                })
    return rows


def _group_additive(rows: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    grouped = {"baseline": {}, "current": {}}
    for row in rows:
        grouped[row["period"]][row["segment"]] = grouped[row["period"]].get(row["segment"], 0) + row["value"]
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


def _comparison(
    *,
    key: str,
    metric: str,
    definition: str,
    population: str,
    dimension: str,
    unit: str,
    kind: str,
    rows: list[dict[str, Any]],
    dates: dict[str, datetime],
    coverage: str,
    query_ref: str,
) -> dict[str, Any]:
    if kind == "additive":
        baseline, current = _group_additive(rows)
        segments = sorted(set(baseline) | set(current))
        baseline_total = sum(baseline.values()) if baseline else None
        current_total = sum(current.values()) if current else None
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
        segments = sorted(set(baseline) | set(current))
        baseline_total = {
            "numerator": sum(value[0] for value in baseline.values()) if baseline else None,
            "denominator": sum(value[1] for value in baseline.values()) if baseline else None,
        }
        current_total = {
            "numerator": sum(value[0] for value in current.values()) if current else None,
            "denominator": sum(value[1] for value in current.values()) if current else None,
        }
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
        "key": key,
        "metric": metric,
        "definition": definition,
        "population": population,
        "unit": unit,
        "dimension": dimension,
        "kind": kind,
        "baseline_start": _iso(dates["baseline_start"]),
        "baseline_end": _iso(dates["baseline_end"]),
        "current_start": _iso(dates["current_start"]),
        "current_end": _iso(dates["current_end"]),
        "comparison_window": WINDOW,
        "coverage": coverage,
        "disjoint_segments": True,
        "comparable": True,
        "query_refs": [query_ref],
        **totals,
        "segments": segment_values,
    }


def _descriptor(
    *,
    source_key: str,
    resource: str,
    title: str,
    description: str,
    comparison_key: str,
    metric: str,
    population: str,
    grain: str,
    business_role: str,
    required: bool,
) -> dict[str, Any]:
    contract = ResourceContract(
        tenant_id="synthetic-first-report",
        domain=source_key,
        scope=population,
        metric_names=[metric],
        available_comparison_windows=[WINDOW],
        required_comparison_keys=[comparison_key],
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
        kind="saved_query",
        title=title,
        description=description,
        metadata={
            "source_key": source_key,
            "business_role": business_role,
            "required": required,
            "available_comparison_windows": [WINDOW],
            "required_comparison_keys": [comparison_key],
            "read_only": True,
        },
        contract=contract,
    ).model_dump(mode="json")
    # Keep the adapter's stable key explicit for callers that do not use the
    # ResourceDescriptor model to index a bounded catalog.
    descriptor["source_key"] = source_key
    return descriptor


def _snapshot(
    *,
    source: dict[str, Any],
    company_id: str,
    period_id: str,
    as_of: datetime,
    comparison: dict[str, Any],
    rows: list[dict[str, Any]],
    semantic_status: str,
) -> dict[str, Any]:
    source_key = source["source_key"]
    captured_at = as_of
    source_captured_at = as_of - timedelta(hours=1)
    snapshot = ResourceSnapshot(
        source_key=source_key,
        adapter=source["adapter"],
        resource=source["resource"],
        title=source["title"],
        description=source["description"],
        analytical_comparisons=[comparison],
        evidence=[{
            "source_key": source_key,
            "subject_id": f"{company_id}-{period_id}-{source_key}",
            "subject_label": source["title"],
            "statement": "Bounded source result; interpret the comparison using the directory definition.",
            "values": {
                "row_count": len(rows),
            },
            "provenance": [f"source:{source_key}:{period_id}"],
        }],
        metadata={
            "company_id": company_id,
            "period_id": period_id,
            "as_of": _iso(as_of),
            "period_contract": "closed UTC intervals compared to the immediately previous interval",
            "replay_clock": _iso(captured_at),
        },
        captured_at=captured_at,
        source_captured_at=source_captured_at,
        contract=ResourceContract(
            tenant_id="synthetic-first-report",
            domain=source_key,
            scope=source["contract"]["scope"],
            metric_names=source["contract"]["metric_names"],
            available_comparison_windows=[WINDOW],
            required_comparison_keys=source["contract"]["required_comparison_keys"],
            population=source["contract"]["population"],
            grain=source["contract"]["grain"],
            freshness_sla_hours=48,
            roles=source["contract"]["roles"],
            source_status="ambiguous" if semantic_status == "definition-conflict" else "healthy",
            authorized=True,
        ),
    )
    return snapshot.model_dump(mode="json")


def _rate(value: tuple[int, int] | None) -> Fraction | None:
    if value is None or value[1] <= 0:
        return None
    return Fraction(value[0], value[1])


def _oracle(
    *,
    kind: str,
    rows: list[dict[str, Any]],
    coverage: str,
    semantic_status: str,
    materiality: dict[str, float],
    notify_route: str,
    investigate_route: str,
    destinations: list[dict[str, str]],
) -> dict[str, Any]:
    if kind == "additive":
        baseline, current = _group_additive(rows)
        baseline_total = sum(baseline.values()) if baseline else None
        current_total = sum(current.values()) if current else None
        delta = None if baseline_total is None or current_total is None else current_total - baseline_total
        contributions = [
            {
                "segment": segment,
                "baseline": baseline.get(segment),
                "current": current.get(segment),
                "contribution": current.get(segment, 0) - baseline.get(segment, 0),
            }
            for segment in sorted(set(baseline) | set(current))
            if segment in baseline and segment in current
        ]
        quantitative = {
            "baseline_total": {"value": baseline_total},
            "current_total": {"value": current_total},
            "baseline": baseline_total,
            "current": current_total,
            "delta": delta if coverage == "complete" else None,
            "contributions": contributions if coverage == "complete" else [],
            "within_effect": None,
            "mix_effect": None,
        }
        material = (
            delta is not None
            and abs(delta) >= materiality["aggregate_delta"]
        ) or any(
            abs(item["contribution"]) >= materiality["segment_contribution"]
            for item in contributions
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
        baseline_rate = (
            Fraction(baseline_total["numerator"], baseline_total["denominator"])
            if baseline_total["numerator"] is not None and baseline_total["denominator"] else None
        )
        current_rate = (
            Fraction(current_total["numerator"], current_total["denominator"])
            if current_total["numerator"] is not None and current_total["denominator"] else None
        )
        contributions = []
        within = Fraction()
        mix = Fraction()
        complete_segments = set(baseline) == set(current) and all(
            _rate(baseline[key]) is not None and _rate(current[key]) is not None for key in baseline
        )
        if complete_segments and baseline_rate is not None and current_rate is not None:
            for segment in sorted(baseline):
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
        quantitative = {
            "baseline_total": baseline_total,
            "current_total": current_total,
            "baseline": float(baseline_rate) if baseline_rate is not None else None,
            "current": float(current_rate) if current_rate is not None else None,
            "delta": float(current_rate - baseline_rate) if coverage == "complete" and baseline_rate is not None and current_rate is not None else None,
            "contributions": contributions if coverage == "complete" else [],
            "within_effect": float(within) if coverage == "complete" and complete_segments else None,
            "mix_effect": float(mix) if coverage == "complete" and complete_segments else None,
        }
        material = (
            quantitative["delta"] is not None
            and abs(quantitative["delta"]) >= materiality["aggregate_delta"]
        ) or any(
            abs(item["contribution"]) >= materiality["segment_contribution"]
            for item in contributions
        )

    status = "complete" if coverage == "complete" and semantic_status != "definition-conflict" else "blocked"
    if coverage != "complete":
        outcome = "insufficient_data"
        route_keys: list[str] = []
    elif semantic_status == "definition-conflict":
        outcome = "investigate"
        route_keys = [investigate_route]
    elif material:
        outcome = "notify"
        route_keys = [notify_route]
    else:
        outcome = "ignore"
        route_keys = []
    directory = {item["key"]: item["destination"] for item in destinations}
    return {
        **quantitative,
        "status": status,
        "semantic_status": semantic_status,
        "materiality": materiality,
        "expected_outcome": outcome,
        "expected_route_keys": route_keys,
        "expected_route_destinations": {key: directory[key] for key in route_keys},
    }


def _source_pair(company_id: str, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    reporting = _descriptor(
        source_key=f"{company_id}-reporting",
        resource=f"report:{spec['report_resource']}",
        title=spec["primary_title"],
        description=spec["primary_description"],
        comparison_key=spec["comparison_key"],
        metric=spec["metric"],
        population=spec["population"],
        grain=spec["grain"],
        business_role="reporting",
        required=True,
    )
    operations = _descriptor(
        source_key=f"{company_id}-operations",
        resource=f"report:{spec['operations_resource']}",
        title=spec["distractor_title"],
        description=spec["distractor_description"],
        comparison_key=f"{spec['distractor_metric']}-by-{spec['dimension']}",
        metric=spec["distractor_metric"],
        population=spec["distractor_population"],
        grain=spec["grain"],
        business_role="operations",
        required=True,
    )
    return reporting, operations


def _build_run(spec: dict[str, Any], period: dict[str, Any], index: int) -> dict[str, Any]:
    company_id = spec["id"]
    primary, distractor = _source_pair(company_id, spec)
    dates = _period_dates(index)
    as_of = dates["current_end"] + timedelta(hours=2)
    primary_rows = spec["rows"](period, company_id)
    distractor_rows = spec["distractor_rows"](period, company_id)
    primary_comparison = _comparison(
        key=spec["comparison_key"], metric=spec["metric"], definition=spec["definition"],
        population=spec["population"], dimension=spec["dimension"], unit=spec["unit"],
        kind=spec["kind"], rows=primary_rows, dates=dates, coverage=period["coverage"],
        query_ref=f"query:{company_id}:reporting:{period['id']}",
    )
    distractor_comparison = _comparison(
        key=f"{spec['distractor_metric']}-by-{spec['dimension']}", metric=spec["distractor_metric"],
        definition=spec["distractor_definition"], population=spec["distractor_population"],
        dimension=spec["dimension"], unit=spec["unit"], kind=spec["kind"],
        rows=distractor_rows, dates=dates, coverage="complete",
        query_ref=f"query:{company_id}:operations:{period['id']}",
    )
    snapshots = {
        f"{primary['adapter']}|{primary['resource']}": _snapshot(
            source=primary, company_id=company_id, period_id=period["id"], as_of=as_of,
            comparison=primary_comparison, rows=primary_rows, semantic_status=period["semantic_status"],
        ),
        f"{distractor['adapter']}|{distractor['resource']}": _snapshot(
            source=distractor, company_id=company_id, period_id=period["id"], as_of=as_of,
            comparison=distractor_comparison, rows=distractor_rows,
            semantic_status="distinct-metric",
        ),
    }
    notify_route, investigate_route = spec["destinations"][0]["key"], spec["destinations"][1]["key"]
    oracle = _oracle(
        kind=spec["kind"], rows=primary_rows, coverage=period["coverage"],
        semantic_status=period["semantic_status"], materiality=spec["materiality"],
        notify_route=notify_route, investigate_route=investigate_route,
        destinations=spec["destinations"],
    )
    if period["semantic_status"] == "definition-conflict":
        # This refers to the selected export itself, not a different nearby
        # metric. It is observable source context, not an expected action label.
        snapshots[f"{primary['adapter']}|{primary['resource']}"]["evidence"].append({
            "source_key": primary["source_key"],
            "subject_id": spec["comparison_key"],
            "subject_label": primary["title"],
            "statement": f"The catalog defines this export as: {spec['definition']} Current release notes define the same export as: {spec['conflicting_definition']} The data owner has not resolved which definition these rows implement.",
            "provenance": [f"release-notes:{company_id}:{period['id']}"],
        })
    return {
        "company": spec["name"],
        "company_id": company_id,
        "id": f"{company_id}/{period['id']}",
        "brief": spec["brief"],
        "policy": spec["policy"],
        "destinations": spec["destinations"],
        "directory": [primary, distractor],
        "period": {"id": period["id"], "role": period["role"], "as_of": _iso(as_of)},
        "snapshots": snapshots,
        "oracle": oracle,
        "_primary_source_key": primary["source_key"],
    }


def _public_analysis(run: dict[str, Any]) -> dict[str, Any]:
    """Normalize the primary comparison and independent oracle for the runner."""
    primary = next(
        snapshot for snapshot in run["snapshots"].values()
        if snapshot["source_key"] == run["_primary_source_key"]
    )
    comparison = ResourceSnapshot.model_validate(primary).analytical_comparisons[0]
    oracle = run["oracle"]
    return {
        "source_key": primary["source_key"],
        "comparison_key": comparison.key,
        "metric": comparison.metric,
        "unit": comparison.unit,
        "dimension": comparison.dimension,
        "definition": comparison.definition,
        "population": comparison.population,
        "baseline_start": comparison.baseline_start.isoformat(),
        "baseline_end": comparison.baseline_end.isoformat(),
        "current_start": comparison.current_start.isoformat(),
        "current_end": comparison.current_end.isoformat(),
        "baseline": oracle["baseline"],
        "current": oracle["current"],
        "delta": oracle["delta"],
        "within_effect": oracle["within_effect"],
        "mix_effect": oracle["mix_effect"],
        "contributions": {
            item["segment"]: item["contribution"] for item in oracle["contributions"]
        },
        "query_refs": list(comparison.query_refs),
    }


def _public_company(spec: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    descriptors = runs[0]["directory"]
    sources = []
    for descriptor in descriptors:
        sources.append(SourceRef(
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
        ).model_dump(mode="json"))
    periods = []
    for run in runs:
        raw_oracle = run["oracle"]
        analyses = (
            []
            if raw_oracle["status"] == "blocked" and raw_oracle["semantic_status"] != "definition-conflict"
            else [_public_analysis(run)]
        )
        periods.append({
            "id": run["period"]["id"],
            "split": "setup" if run["period"]["role"] == "setup" else "holdout",
            "as_of": run["period"]["as_of"],
            "resources": list(run["snapshots"].values()),
            "oracle": {
                "status": raw_oracle["status"],
                "outcome": raw_oracle["expected_outcome"],
                "recipients": list(raw_oracle["expected_route_keys"]),
                "analyses": analyses,
                "semantic_status": raw_oracle["semantic_status"],
            },
        })
    return {
        "id": spec["id"],
        "company": spec["name"],
        "brief": spec["brief"],
        "owner_policy": spec["policy"],
        "descriptors": descriptors,
        "sources": sources,
        "destinations": spec["destinations"],
        "periods": periods,
    }


def _ecommerce_rows(period: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return _rows_additive(company, period["id"], period["primary"])


def _ecommerce_distractor(period: dict[str, Any], company: str) -> list[dict[str, Any]]:
    values = {segment: [amount + 25 for amount in amounts] for segment, amounts in period["alternate"].items()}
    return _rows_additive(company, period["id"] + "-alt", values)


def _support_rows(period: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return _rows_rate(company, period["id"], period["primary"])


def _support_distractor(period: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return _rows_rate(company, period["id"] + "-alt", period["alternate"])


def _fulfillment_rows(period: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return _rows_additive(company, period["id"], period["primary"])


def _fulfillment_distractor(period: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return _rows_additive(company, period["id"] + "-alt", period["alternate"])


def _subscription_rows(period: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return _rows_additive(company, period["id"], period["primary"])


def _subscription_distractor(period: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return _rows_additive(company, period["id"] + "-alt", period["alternate"])


_COMPANIES: list[dict[str, Any]] = [
    {
        "id": "northstar-cart", "name": "Northstar Cart",
        "brief": "Monitor completed net sales across web, marketplace, and store channels.",
        "policy": "Use completed orders after refunds, excluding tax and shipping. Notify Commerce when the total changes by at least $100 or any channel contributes at least $80 in absolute terms. Ignore smaller complete movements. If the population or period coverage is incomplete, do not estimate the total; route the gap to Data Operations.",
        "comparison_key": "completed-net-sales", "metric": "net_sales", "definition": "Completed order value after refunds, excluding tax and shipping.",
        "population": "completed orders in the reporting channels", "dimension": "channel", "unit": "USD", "kind": "additive", "grain": "weekly channel interval",
        "report_resource": "completed-net-sales", "operations_resource": "booked-gross-sales",
        "primary_title": "Completed net sales by channel", "primary_description": "Completed-order net sales export.",
        "distractor_title": "Booked gross sales by channel", "distractor_metric": "gross_sales", "distractor_definition": "Booked order value before refunds, tax, and shipping.",
        "distractor_population": "booked orders including canceled and refunded orders", "distractor_description": "A plausible sales export with a different population and metric definition.",
        "distractor_disagreement": "semantic disagreement: gross booked value includes refunds, tax, shipping, and canceled orders; it is not completed net sales",
        "materiality": {"aggregate_delta": 100.0, "segment_contribution": 80.0},
        "destinations": [
            {"key": "commerce-owner", "label": "Commerce owner", "destination": "agent://commerce-owner"},
            {"key": "data-operations", "label": "Data Operations", "destination": "agent://data-operations"},
        ],
        "rows": _ecommerce_rows, "distractor_rows": _ecommerce_distractor,
        "periods": [
            {"id": "p01", "role": "setup", "coverage": "complete", "semantic_status": "aligned", "primary": {"web": [400, 560], "marketplace": [120, 110], "store": [80, 80]}, "alternate": {"web": [450, 500], "marketplace": [135, 145], "store": [90, 100]}},
            {"id": "p02", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"web": [480, 440], "marketplace": [120, 220], "store": [80, 80]}, "alternate": {"web": [520, 550], "marketplace": [140, 180], "store": [90, 100]}},
            {"id": "p03", "role": "edge", "coverage": "complete", "semantic_status": "aligned", "primary": {"web": [300, 320], "marketplace": [100, 100], "store": [100, 80]}, "alternate": {"web": [340, 360], "marketplace": [120, 125], "store": [110, 105]}},
        ],
    },
    {
        "id": "harbor-help", "name": "Harbor Help",
        "brief": "Monitor weighted resolution-SLA miss rate by support tier.",
        "policy": "Use eligible resolved tickets and weight the SLA miss rate by ticket count, not by averaging tier percentages. Notify Support Operations when the weighted current miss rate is at least 12% or its absolute change is at least 4 percentage points. If any eligible tier is missing, do not estimate a rate; route to the Data Steward. Keep rate and mix effects descriptive, not causal.",
        "comparison_key": "resolution-sla-rate", "metric": "sla_miss_rate", "definition": "Missed resolution-SLA tickets divided by eligible resolved tickets.",
        "population": "resolved priority tickets with an eligible resolution clock", "dimension": "support_tier", "unit": "ratio", "kind": "rate", "grain": "weekly support interval",
        "report_resource": "resolution-sla", "operations_resource": "first-response-sla",
        "primary_title": "Resolution SLA by support tier", "primary_description": "Weighted resolution-SLA measurement over eligible resolved tickets.",
        "distractor_title": "First-response SLA by support tier", "distractor_metric": "first_response_miss_rate", "distractor_definition": "Missed first-response SLA divided by tickets with a response clock.",
        "distractor_population": "tickets with a first-response clock", "distractor_description": "A support export with a similar label but a different service clock.",
        "distractor_disagreement": "semantic disagreement: first-response SLA is not resolution SLA and uses a different eligible population",
        "materiality": {"aggregate_delta": 0.04, "segment_contribution": 0.025},
        "destinations": [
            {"key": "support-operations", "label": "Support Operations", "destination": "agent://support-operations"},
            {"key": "support-data-steward", "label": "Support Data Steward", "destination": "agent://support-data-steward"},
        ],
        "rows": _support_rows, "distractor_rows": _support_distractor,
        "periods": [
            {"id": "p01", "role": "setup", "coverage": "complete", "semantic_status": "aligned", "primary": [("enterprise", 8, 80, 15, 75), ("self_serve", 12, 120, 18, 125)], "alternate": [("enterprise", 5, 80, 10, 75), ("self_serve", 20, 120, 25, 125)]},
            {"id": "p02", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": [("enterprise", 10, 100, 8, 80), ("self_serve", 10, 100, 20, 120)], "alternate": [("enterprise", 8, 100, 6, 80), ("self_serve", 14, 100, 28, 120)]},
            {"id": "p03", "role": "edge", "coverage": "partial", "semantic_status": "aligned", "primary": [("enterprise", 12, 120, 15, 100), ("self_serve", 10, 100, None, None)], "alternate": [("enterprise", 6, 120, 8, 100), ("self_serve", 15, 100, 17, 100)]},
        ],
    },
    {
        "id": "redwood-fulfillment", "name": "Redwood Fulfillment",
        "brief": "Monitor late completed shipments across fulfillment warehouses.",
        "policy": "Use completed shipments whose promised date fell in the closed interval. Notify Fulfillment when late shipments change by at least 15 or a warehouse contributes at least 15. Ignore smaller complete movements. Different metrics or populations in nearby reports are not, by themselves, a definition conflict. Use the selected export when its own contract is explicit, complete, and reconciled. Investigate when that selected export has incompatible definitions or its contract is ambiguous; route unresolved ambiguity to Fulfillment data review and do not issue a business alert.",
        "conflicting_definition": "Orders whose promises elapsed, including unshipped orders.",
        "comparison_key": "late-shipments", "metric": "late_shipments", "definition": "Completed shipments delivered after their promised date.",
        "population": "completed shipments with a promised delivery date", "dimension": "warehouse", "unit": "shipments", "kind": "additive", "grain": "weekly warehouse interval",
        "report_resource": "late-shipments", "operations_resource": "late-order-promises",
        "primary_title": "Late completed shipments by warehouse", "primary_description": "Shipment-level lateness export.",
        "distractor_title": "Late order promises by warehouse", "distractor_metric": "late_orders", "distractor_definition": "Orders whose promise elapsed, including orders not shipped.",
        "distractor_population": "all orders with an elapsed promise", "distractor_description": "An operations export that counts order promises rather than completed shipments.",
        "distractor_disagreement": "semantic disagreement: late order promises include unshipped and canceled orders; they are not late completed shipments",
        "materiality": {"aggregate_delta": 15.0, "segment_contribution": 15.0},
        "destinations": [
            {"key": "fulfillment-owner", "label": "Fulfillment owner", "destination": "agent://fulfillment-owner"},
            {"key": "fulfillment-data", "label": "Fulfillment data review", "destination": "agent://fulfillment-data"},
        ],
        "rows": _fulfillment_rows, "distractor_rows": _fulfillment_distractor,
        "periods": [
            {"id": "p01", "role": "setup", "coverage": "complete", "semantic_status": "aligned", "primary": {"north": [30, 45], "south": [20, 25]}, "alternate": {"north": [40, 50], "south": [25, 30]}},
            {"id": "p02", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"north": [40, 55], "south": [30, 30]}, "alternate": {"north": [50, 60], "south": [35, 40]}},
            {"id": "p03", "role": "edge", "coverage": "complete", "semantic_status": "definition-conflict", "primary": {"north": [30, 35], "south": [20, 23]}, "alternate": {"north": [55, 70], "south": [35, 48]}},
        ],
    },
    {
        "id": "orbit-subscriptions", "name": "Orbit Subscriptions",
        "brief": "Monitor additive expansion, contraction, new-logo, and churn MRR movements.",
        "policy": "Use signed monthly recurring-revenue movements from subscription change records. Notify Subscription Operations when net MRR changes by at least $50 or any expansion/contraction segment contributes at least $60. Ignore smaller complete movements. Report expansion and contraction as accounting contributions, not causes; do not substitute gross bookings for signed subscription movements.",
        "comparison_key": "signed-mrr-movement", "metric": "net_mrr_change", "definition": "Signed MRR movement recorded for subscription changes; contraction and churn are negative.",
        "population": "subscription change records with an effective date", "dimension": "movement_type", "unit": "USD", "kind": "additive", "grain": "weekly subscription interval",
        "report_resource": "signed-mrr-movements", "operations_resource": "gross-booked-arr",
        "primary_title": "Signed subscription MRR movements", "primary_description": "Expansion and contraction accounting from effective subscription-change records.",
        "distractor_title": "Gross booked ARR movements", "distractor_metric": "gross_booked_arr", "distractor_definition": "Unsigned booked ARR before contraction, churn, or effective-date validation.",
        "distractor_population": "booked subscription opportunities", "distractor_description": "A growth export with a different sign convention and booking population.",
        "distractor_disagreement": "semantic disagreement: gross booked ARR omits signed contraction and churn and is not effective-date MRR movement",
        "materiality": {"aggregate_delta": 50.0, "segment_contribution": 60.0},
        "destinations": [
            {"key": "subscription-operations", "label": "Subscription Operations", "destination": "agent://subscription-operations"},
            {"key": "subscription-data", "label": "Subscription data review", "destination": "agent://subscription-data"},
        ],
        "rows": _subscription_rows, "distractor_rows": _subscription_distractor,
        "periods": [
            {"id": "p01", "role": "setup", "coverage": "complete", "semantic_status": "aligned", "primary": {"expansion": [180, 270], "contraction": [-60, -80], "new_logo": [50, 60], "churn": [-30, -50]}, "alternate": {"expansion": [220, 290], "contraction": [70, 90], "new_logo": [65, 75], "churn": [0, 0]}},
            {"id": "p02", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"expansion": [200, 210], "contraction": [-80, -95], "new_logo": [40, 40], "churn": [-20, -15]}, "alternate": {"expansion": [240, 260], "contraction": [90, 100], "new_logo": [55, 65], "churn": [0, 0]}},
            {"id": "p03", "role": "edge", "coverage": "complete", "semantic_status": "aligned", "primary": {"expansion": [170, 240], "contraction": [-70, -110], "new_logo": [30, 30], "churn": [-20, -20]}, "alternate": {"expansion": [210, 270], "contraction": [75, 115], "new_logo": [45, 50], "churn": [0, 0]}},
        ],
    },
]


def cases() -> list[dict[str, Any]]:
    """Return four companies, each with setup, fresh, and edge periods."""
    result = []
    for spec in _COMPANIES:
        runs = [_build_run(spec, period, index) for index, period in enumerate(spec["periods"])]
        result.append(_public_company(spec, runs))
    return result

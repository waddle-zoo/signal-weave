"""Predeclared fictional monthly-close inputs for the Northstar cadence trial."""

from __future__ import annotations

import calendar
import copy
import hashlib
from datetime import date, datetime, timedelta, timezone

from evaluations.installed_northstar_cases import NORTHSTAR_POLICY_INTERVENTION
from signalweave.models import (
    Evidence,
    Observation,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
)

SCENARIO_ID = "northstar-outfitters-local"
PROTOCOL = "northstar-native-monthly-close-cadence-v1"
PILOT_INDICES = [0, 3, 6, 9]
MONTHS = tuple([f"2025-{m:02d}" for m in range(2, 13)] + ["2026-01"])
CHANNELS = ("online", "store", "mobile", "marketplace")
# pct, sales shape, Web change, Finance change, source fault, private family
CASES = (
    (-4, "all", 0, 0, None, "small_quiet"),
    (9.99, "all", 0, 0, None, "upper_quiet"),
    (10, "all", 0, 0, None, "positive_material"),
    (-10, "all", 0, 0, None, "negative_material"),
    (-14.99, "all", 0, 0, None, "below_decline_trigger"),
    (-15, "one", -1, 0, None, "single_channel"),
    (-15, "two", -1, 0, None, "corroborated_decline"),
    (-25, "all", 0, 0, None, "unconfirmed_decline"),
    (-25, "all", 0, -1, None, "finance_corroboration"),
    (0, "all", 0, 0, "unavailable", "unavailable"),
    (2, "all", 0, 0, "total_plus_10", "total_mismatch"),
    (-8, "all", 0, 0, "partial", "partial_month"),
)
FICTION = (
    "Generated fictional monthly balances for a functional policy test; not raw production rows."
)
SIMULATED_SCOPE = (
    "For this fictional trial, Executive Pulse's generated monthly channel ledger balances in USD "
    "are the metric of record. They are not actual order-line records and establish no unique orders, "
    "customers, settlement, or whole-company sales. Web Funnel, Finance Daily, and Support Operations "
    "are separate populations; never row-join them or claim a shared cohort."
)
DESTINATIONS = [
    {
        "key": "leadership",
        "label": "Leadership",
        "destination": "slack://simulation-leadership",
        "authorized": True,
    },
    {
        "key": "analytics",
        "label": "Analytics",
        "destination": "slack://simulation-analytics",
        "authorized": True,
    },
    {
        "key": "data-trust",
        "label": "Data trust",
        "destination": "slack://simulation-data-trust",
        "authorized": True,
    },
]
SOURCES = {
    "sales": (
        "superset|dashboard:1",
        "Northstar Executive Pulse",
        "dashboard",
        "commerce",
        ("net_sales",),
        ("primary", "dashboard"),
        36,
        "Generated fictional monthly channel balances.",
        "One balance per reporting month and sales channel.",
        SIMULATED_SCOPE,
        "simulation-ledger://northstar/monthly-sales",
    ),
    "web": (
        "northstar|fct_web_session",
        "Northstar Web Funnel",
        "saved_query",
        "commerce",
        ("conversion_rate", "sessions", "orders"),
        ("corroborates", "diagnostic"),
        36,
        "Generated fictional Web Funnel counts; no Sales linkage.",
        "Calendar month; sum sessions/orders, then orders divided by sessions.",
        "Separate generated Web population; no shared-cohort claim.",
        "simulation-ledger://northstar/web",
    ),
    "finance": (
        "northstar|fct_finance_daily",
        "Northstar Finance Daily",
        "saved_query",
        "finance",
        ("revenue",),
        ("corroborates", "quality"),
        72,
        "Generated fictional Finance revenue records, separate from Sales and Web.",
        "Calendar month; sum revenue.",
        "Separate generated Finance population; no joins.",
        "simulation-ledger://northstar/finance",
    ),
    "support": (
        "northstar|fct_support_ticket",
        "Northstar Support Operations",
        "saved_query",
        "support-operations",
        ("backlog",),
        ("diagnostic",),
        36,
        "Generated fictional backlog readings; no incident or severity records.",
        "Calendar month; average the available readings.",
        "Separate generated Support population; backlog is not an incident feed.",
        "simulation-ledger://northstar/support",
    ),
}
SUBJECTS = {
    "sales": [("revenue-total", "Net sales revenue", "net_sales", "currency")]
    + [(f"channel-{c}", f"Net sales — {c.title()}", "net_sales", "currency") for c in CHANNELS],
    "web": [
        ("conversion-rate", "Web conversion rate", "conversion_rate", "ratio"),
        ("web-sessions", "Web sessions", "sessions", "count"),
    ],
    "finance": [("finance-revenue", "Finance booked revenue", "revenue", "currency")],
    "support": [("support-backlog", "Support backlog", "backlog", "tickets")],
}


def _hash(value: str, n: int = 20) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:n]


def _ref(key):
    return "company_mcp|resource-" + _hash(SOURCES[key][0])


def _capture(key, month, rev="r1"):
    return "capture-" + _hash(f"{key}|{month}|{rev}", 16)


def _rid(key, month, slot, rev="r1"):
    return "row-" + _hash(f"{key}|{month}|{slot}|{rev}")


def _previous(month):
    d = date.fromisoformat(month + "-01")
    return date(d.year - (d.month == 1), d.month - 1 or 12, 1).strftime("%Y-%m")


def _record(key, month, slot, rev="r1", **fields):
    return {
        "record_id": _rid(key, month, slot, rev),
        "reporting_month": month,
        "population_id": key,
        "capture_id": _capture(key, month, rev),
        "revision_id": rev,
        "data_origin": "simulation_coordinator_authored",
        **fields,
    }


def _tables():
    months = ["2024-12", "2025-01", *MONTHS]
    sales = {months[0]: dict.fromkeys(CHANNELS, 2500.0)}
    sales["2025-01"] = {c: v * 1.04 for c, v in sales[months[0]].items()}
    web = {months[0]: [(5000, 500), (5000, 500)]}
    web["2025-01"] = web[months[0]].copy()
    finance = {months[0]: [25000.0, 25000.0]}
    finance["2025-01"] = finance[months[0]].copy()
    for month, (pct, shape, wp, fp, _, _) in zip(MONTHS, CASES, strict=True):
        base = sales[_previous(month)]
        if shape == "one":
            current = base.copy()
            current[CHANNELS[0]] *= 0.4
        elif shape == "two":
            factor = 1 - 0.15 * sum(base.values()) / sum(base[c] for c in CHANNELS[:2])
            current = {c: v * (factor if c in CHANNELS[:2] else 1) for c, v in base.items()}
        else:
            current = {c: v * (1 + pct / 100) for c, v in base.items()}
        sales[month] = current
        web[month] = [(s, round(o * (1 + wp / 100))) for s, o in web[_previous(month)]]
        finance[month] = [round(v * (1 + fp / 100), 2) for v in finance[_previous(month)]]
    result = {k: {} for k in SOURCES}
    for month in months:
        partial = month == "2026-01"
        days = 20 if partial else calendar.monthrange(*map(int, month.split("-")))[1]
        result["sales"][month] = [
            _record(
                "sales",
                month,
                c,
                channel=c,
                net_sales=v * (20 / 31 if partial else 1),
                currency="USD",
                coverage_days=days,
                period_days=calendar.monthrange(*map(int, month.split("-")))[1],
                covered_through=f"{month}-{days:02d}",
            )
            for c, v in sales[month].items()
        ]
        result["web"][month] = [
            _record("web", month, f"segment-{i}", segment=f"segment-{i}", sessions=s, orders=o)
            for i, (s, o) in enumerate(web[month], 1)
        ]
        result["finance"][month] = [
            _record("finance", month, f"bucket-{i}", revenue=v, currency="USD")
            for i, v in enumerate(finance[month], 1)
        ]
        result["support"][month] = [
            _record("support", month, f"reading-{i}", backlog_reading=v, unit="tickets")
            for i, v in enumerate((42.0, 58.0), 1)
        ]
    return result


def _value(key, rows, month, subject):
    selected = [r for r in rows if r["reporting_month"] == month]
    if subject.startswith("channel-"):
        selected = [r for r in selected if r["channel"] == subject[8:]]
    ids = [r["record_id"] for r in selected]
    if key == "sales":
        value = sum(r["net_sales"] for r in selected)
        extra = {}
    elif key == "web" and subject == "conversion-rate":
        sessions, orders = sum(r["sessions"] for r in selected), sum(r["orders"] for r in selected)
        value, extra = orders / sessions, {"sessions": sessions, "orders": orders}
    elif key == "web":
        value, extra = sum(r["sessions"] for r in selected), {}
    elif key == "finance":
        value, extra = sum(r["revenue"] for r in selected), {}
    else:
        value, extra = sum(r["backlog_reading"] for r in selected) / len(selected), {}
    return value, ids, extra


def _capture_times(month):
    d = date.fromisoformat(month + "-01")
    year, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    t = datetime(year, m, 5, 5, tzinfo=timezone.utc)
    return (t + timedelta(hours=1)).isoformat().replace("+00:00", "Z"), t.isoformat().replace(
        "+00:00", "Z"
    )


def _contract(key):
    s = SOURCES[key]
    comparisons = (
        [
            {
                "key": "net-sales-change",
                "metric": "net_sales",
                "definition": "Sum monthly recorded balances over the declared channels.",
                "population": s[7],
                "unit": "currency",
                "comparison_window": "previous_period",
                "coverage": "complete",
                "comparable": True,
                "detail": "Total and channels use the same complete generated ledger partition.",
                "query_refs": [s[10]],
            }
        ]
        if key == "sales"
        else []
    )
    return ResourceContract(
        tenant_id=SCENARIO_ID,
        domain=s[3],
        scope=s[9],
        metric_names=list(s[4]),
        comparison_contracts=comparisons,
        available_comparison_windows=["previous_period"],
        required_comparison_keys=[],
        population=s[7],
        grain=s[8],
        freshness_sla_hours=s[6],
        lineage=[s[10]],
        roles=list(s[5]),
        source_status="healthy",
        authorized=True,
    ).model_dump(mode="json")


def _descriptors():
    result = {}
    for key, s in SOURCES.items():
        resource = _ref(key).split("|", 1)[1]
        result[key] = ResourceDescriptor(
            adapter="company_mcp",
            resource=resource,
            kind=s[2],
            title=s[1],
            description=f"{s[1]} generated monthly-close snapshot for the fictional trial.",
            source_url=s[10],
            metadata={
                "tenant": SCENARIO_ID,
                "scope": s[9],
                "owner": "Northstar Growth Analytics",
                "read_only": True,
                "data_origin": "simulation_coordinator_authored",
            },
            contract=_contract(key),
        ).model_dump(mode="json")
    return list(result.values()), result


def _period(month, tables, descs, fault=None):
    period_id = "period-" + _hash(f"{PROTOCOL}|{month}", 16)
    base, as_of, captured = _previous(month), *_capture_times(month)
    snapshots = {}
    for key, s in SOURCES.items():
        failed = key == "sales" and fault == "unavailable"
        partial = key == "sales" and fault == "partial"
        rows = [] if failed else copy.deepcopy(tables[key][base] + tables[key][month])
        alt = []
        contract = copy.deepcopy(descs[key]["contract"])
        contract["source_status"] = "failed" if failed else "healthy"
        if partial:
            contract["comparison_contracts"][0].update(
                coverage="partial",
                comparable=False,
                detail="Generated January close has only 20 of 31 days; not a complete comparable month.",
            )
        if key == "sales" and fault == "total_plus_10":
            alt = copy.deepcopy(rows)
            for r in alt:
                r.update(
                    revision_id="aggregate-r0",
                    capture_id=_capture("sales-total", r["reporting_month"], "aggregate-r0"),
                    record_id=_rid(
                        "sales-total", r["reporting_month"], r["channel"], "aggregate-r0"
                    ),
                )
                if r["reporting_month"] == month and r["channel"] == CHANNELS[0]:
                    r["net_sales"] += 10
            contract["comparison_contracts"][0].update(
                detail="Same logical Sales population; total is from prior revision aggregate-r0 and channels from r1. These are separate captures, not one consistent snapshot.",
                query_refs=[s[10] + "/aggregate-total", s[10] + "/channel-ledger"],
            )
        history = (
            [
                {
                    "capture_id": _capture("sales-total", m, "aggregate-r0"),
                    "revision_id": "aggregate-r0",
                    "query": "controlling-total",
                    "logical_population_id": "sales",
                }
                for m in (base, month)
            ]
            + [
                {
                    "capture_id": _capture("sales", m),
                    "revision_id": "r1",
                    "query": "channel-ledger",
                    "logical_population_id": "sales",
                }
                for m in (base, month)
            ]
            if alt
            else [
                {
                    "capture_id": _capture(key, m),
                    "revision_id": "r1",
                    "query": "source-snapshot",
                    "logical_population_id": key,
                }
                for m in (base, month)
            ]
        )
        if failed:
            history = []
        capture = (
            "Simulated connector failure; no rows returned."
            if failed
            else f"Generated fictional {s[1]} records for {base} and {month}; no raw production extraction."
        )
        if partial:
            capture += " Current period is partial through 2026-01-20."
        if alt:
            capture = (
                f"Generated fictional close: total capture {_capture('sales-total', month, 'aggregate-r0')} "
                f"and channel capture {_capture('sales', month)} target the same logical population, "
                "but use different captures and row revisions."
            )
        metadata = {
            "tenant": SCENARIO_ID,
            "period_id": period_id,
            "source_scope": s[9],
            "source_capture": capture,
            "source_transport": "generated_fictional_monthly_close",
            "data_origin": "simulation_coordinator_authored",
            "fresh_warehouse_read": False,
            "measurement_window": [base, month],
            "measurement_as_of": as_of,
            "archived_measurement": True,
            "reporting_months": [base, month],
            "ledger_rows" if key == "sales" else "generated_records": rows,
            "aggregate_capture_rows": alt,
            "capture_history": history,
            "capture_ids": sorted({r["capture_id"] for r in [*rows, *alt]}),
        }
        observations, evidence = [], []
        if not failed:
            for subject, label, metric, unit in SUBJECTS[key]:
                used_rows = alt if alt and subject == "revenue-total" else rows
                before, ids0, extra0 = _value(key, used_rows, base, subject)
                current, ids1, extra1 = _value(key, used_rows, month, subject)
                ids = ids0 + ids1
                linked = [r for r in used_rows if r["record_id"] in ids]
                pct = round((current - before) / abs(before) * 100, 3) if before else 0
                url = (
                    s[10]
                    + (
                        "/aggregate-total/"
                        if alt and subject == "revenue-total"
                        else "/channel-ledger/"
                        if alt and subject.startswith("channel-")
                        else "/"
                    )
                    + period_id
                )
                captures, revisions = (
                    sorted({r["capture_id"] for r in linked}),
                    sorted({r["revision_id"] for r in linked}),
                )
                obs = Observation(
                    source_key=descs[key]["resource"],
                    subject_id=subject,
                    subject_label=label,
                    subject_type="channel" if subject.startswith("channel-") else "metric",
                    metric=metric,
                    unit=unit,
                    baseline=before,
                    current=current,
                    previous=before,
                    change_pct=pct,
                    dimensions={
                        "current_period": month,
                        "grain": "month",
                        **({"channel": subject[8:]} if subject.startswith("channel-") else {}),
                    },
                    freshness=f"Historical measurement window {base} through {month}; gateway query freshness is separate.",
                    source_url=url,
                    attributes={
                        "baseline_period": base,
                        "record_ids": ids,
                        "capture_ids": captures,
                        "revision_ids": revisions,
                        "data_origin": "simulation_coordinator_authored",
                        "currency": "USD" if unit == "currency" else None,
                        **{f"baseline_{k}": v for k, v in extra0.items()},
                        **{f"current_{k}": v for k, v in extra1.items()},
                    },
                )
                observations.append(obs)
                evidence.append(
                    Evidence(
                        source_key=descs[key]["resource"],
                        subject_id=subject,
                        subject_label=label,
                        statement=f"Generated fictional {label}: {base} {before} to {month} {current}; change {pct}% ({unit}).",
                        values={
                            "baseline": before,
                            "current": current,
                            "change_pct": pct,
                            "record_ids": ids,
                            "capture_ids": captures,
                            "revision_ids": revisions,
                            "data_origin": "simulation_coordinator_authored",
                        },
                        source_url=url,
                        origin="source",
                        provenance=ids,
                    )
                )
        source = descs[key]
        resource = source["resource"]
        snapshots[_ref(key)] = ResourceSnapshot(
            source_key=resource,
            adapter="company_mcp",
            resource=resource,
            title=source["title"],
            description=source["description"],
            observations=observations,
            evidence=evidence,
            metadata=metadata,
            error="simulated primary monthly-close source unavailable" if failed else None,
            source_url=s[10] + "/" + period_id,
            captured_at=as_of,
            source_captured_at=captured,
            contract=contract,
        ).model_dump(mode="json")
    return {"period_id": period_id, "as_of": as_of, "snapshots": snapshots}


def _audit_value(subject, rows, month):
    current = [r for r in rows if r["reporting_month"] == month]
    if subject == "conversion-rate":
        return sum(r["orders"] for r in current) / sum(r["sessions"] for r in current)
    if subject == "web-sessions":
        return sum(r["sessions"] for r in current)
    if subject == "finance-revenue":
        return sum(r["revenue"] for r in current)
    if subject == "support-backlog":
        return sum(r["backlog_reading"] for r in current) / len(current)
    return sum(r["net_sales"] for r in current)


def _linked_rows(snapshot, subject):
    obs = next((o for o in snapshot["observations"] if o["subject_id"] == subject), None)
    raw = [
        *snapshot["metadata"].get("ledger_rows", snapshot["metadata"].get("generated_records", [])),
        *snapshot["metadata"]["aggregate_capture_rows"],
    ]
    by_id = {r["record_id"]: r for r in raw}
    return [by_id[i] for i in obs["attributes"]["record_ids"] if i in by_id] if obs else []


def _raw_series(rows, metric):
    result = {}
    for month in sorted({r["reporting_month"] for r in rows}):
        current = [r for r in rows if r["reporting_month"] == month]
        if metric == "conversion":
            result[month] = sum(r["orders"] for r in current) / sum(r["sessions"] for r in current)
        elif metric == "backlog":
            result[month] = sum(r["backlog_reading"] for r in current) / len(current)
        else:
            result[month] = sum(r[metric] for r in current)
    return result


def _outcome(period, answers):
    policy = answers["materiality"].lower()
    if not all(x in policy for x in ("below 10%", "at least 15%", "at least two sales channels")):
        raise ValueError("Fixture policy differs from the frozen owner policy")
    snapshots = period["snapshots"]
    total_rows = _linked_rows(snapshots[_ref("sales")], "revenue-total")
    channel_rows = {c: _linked_rows(snapshots[_ref("sales")], f"channel-{c}") for c in CHANNELS}
    if not total_rows or any(not rows for rows in channel_rows.values()):
        return "insufficient_data"
    total = _raw_series(total_rows, "net_sales")
    channels = {c: _raw_series(rows, "net_sales") for c, rows in channel_rows.items()}
    if len(total) != 2 or any(series.keys() != total.keys() for series in channels.values()):
        return "insufficient_data"
    for rows in [*channel_rows.values(), total_rows]:
        if any(
            r.get("currency") != "USD" or r.get("coverage_days") != r.get("period_days")
            for r in rows
        ):
            return "insufficient_data"
    for month, amount in total.items():
        if abs(amount - sum(series[month] for series in channels.values())) > 1e-6:
            return "insufficient_data"
    baseline, current = total.values()
    change = round((current - baseline) / abs(baseline) * 100, 6) if baseline else None
    if change is None:
        return "insufficient_data"
    if abs(change) < 10:
        return "ignore"
    declines = sum(
        series[next(iter(total))] > series[next(reversed(total))] for series in channels.values()
    )
    web = _raw_series(_linked_rows(snapshots[_ref("web")], "conversion-rate"), "conversion")
    finance = _raw_series(_linked_rows(snapshots[_ref("finance")], "finance-revenue"), "revenue")
    if len(web) != 2 or len(finance) != 2:
        return "investigate"
    corroboration = (
        web[next(reversed(web))] < web[next(iter(web))]
        or finance[next(reversed(finance))] < finance[next(iter(finance))]
    )
    return "notify" if change <= -15 and declines >= 2 and corroboration else "investigate"


def _validate(scenario):
    public = scenario["public"]
    catalog = {f"{x['adapter']}|{x['resource']}": x for x in public["catalog"]}
    if len(public["periods"]) != 12 or set(catalog) != {_ref(k) for k in SOURCES}:
        raise ValueError("Bad cadence size/source registry")
    answers = scenario["policy_intervention"]["owner_answers"]
    if public["owner_answers"] != answers or answers["metric_scope"] != SIMULATED_SCOPE:
        raise ValueError("Owner policy/simulated scope diverges")
    for month, period in zip(
        ("2025-01", *MONTHS), [public["onboarding"], *public["periods"]], strict=True
    ):
        if period["as_of"] != _capture_times(month)[0]:
            raise ValueError("Period clock is not its monthly close")
        if set(period["snapshots"]) != set(catalog):
            raise ValueError("Snapshot/catalog identities differ")
        for ref, raw in period["snapshots"].items():
            key = next(k for k in SOURCES if _ref(k) == ref)
            snap = ResourceSnapshot.model_validate(raw)
            meta = snap.metadata
            if (
                snap.title != catalog[ref]["title"]
                or snap.contract.scope != catalog[ref]["contract"]["scope"]
            ):
                raise ValueError("Snapshot contract diverges from catalog")

            def stamp(value):
                return value.isoformat().replace("+00:00", "Z")

            if (
                stamp(snap.captured_at) != period["as_of"]
                or stamp(snap.source_captured_at) != _capture_times(month)[1]
            ):
                raise ValueError("Source timestamps diverge from close")
            if (
                meta["source_transport"] != "generated_fictional_monthly_close"
                or "seed" in str(raw).lower()
            ):
                raise ValueError("False source provenance")
            if not snap.source_url.startswith("simulation-ledger://") or any(
                o.source_url.startswith("http") for o in snap.observations
            ):
                raise ValueError("Fictional rows claim a live source")
            if meta["reporting_months"] != [_previous(month), month]:
                raise ValueError("Snapshot dates do not match the monthly window")
            source_rows = meta.get("ledger_rows", meta.get("generated_records", []))
            rows = [*source_rows, *meta["aggregate_capture_rows"]]
            by_id = {r["record_id"]: r for r in rows}
            if len(by_id) != len(rows) or any(
                r["data_origin"] != "simulation_coordinator_authored"
                or r["population_id"] != key
                or r["reporting_month"] not in meta["reporting_months"]
                for r in rows
            ):
                raise ValueError("Bad generated row identity/origin/population")
            if source_rows and any(
                sum(r["reporting_month"] == m for r in source_rows) != (4 if key == "sales" else 2)
                for m in meta["reporting_months"]
            ):
                raise ValueError("Source row grain/count differs from its monthly contract")
            if (
                key == "sales"
                and source_rows
                and any(
                    {r["channel"] for r in source_rows if r["reporting_month"] == m}
                    != set(CHANNELS)
                    for m in meta["reporting_months"]
                )
            ):
                raise ValueError("Sales source is missing a declared channel")
            if meta["aggregate_capture_rows"]:
                gaps = {
                    m: sum(
                        r["net_sales"]
                        for r in meta["aggregate_capture_rows"]
                        if r["reporting_month"] == m
                    )
                    - sum(r["net_sales"] for r in source_rows if r["reporting_month"] == m)
                    for m in meta["reporting_months"]
                }
                if (
                    abs(gaps[month] - 10) > 1e-6
                    or abs(gaps[_previous(month)]) > 1e-6
                    or {r["revision_id"] for r in meta["aggregate_capture_rows"]}
                    != {"aggregate-r0"}
                    or "not one consistent snapshot"
                    not in snap.contract.comparison_contracts[0].detail
                ):
                    raise ValueError("Mismatch provenance or raw-row arithmetic is not explicit")
            if key == "sales" and month == "2026-01" and source_rows:
                current = [r for r in source_rows if r["reporting_month"] == month]
                comp = snap.contract.comparison_contracts[0]
                if (
                    len(current) != 4
                    or any(
                        (r.get("coverage_days"), r.get("period_days")) != (20, 31) for r in current
                    )
                    or comp.coverage != "partial"
                    or comp.comparable
                ):
                    raise ValueError("Partial rows do not match the declared January window")
            if key in {"sales", "finance"} and any(r["currency"] != "USD" for r in rows):
                raise ValueError("Currency does not match the declared source unit")
            if sorted({r["capture_id"] for r in rows}) != meta["capture_ids"]:
                raise ValueError("Capture registry omits source rows")
            if len(snap.evidence) != len(snap.observations):
                raise ValueError("Every source observation needs matching evidence")
            for o in snap.observations:
                used = [by_id[x] for x in o.attributes["record_ids"]]
                if o.attributes["capture_ids"] != sorted(
                    {r["capture_id"] for r in used}
                ) or o.attributes["revision_ids"] != sorted({r["revision_id"] for r in used}):
                    raise ValueError("Observation lineage mismatch")
                months = sorted({r["reporting_month"] for r in used})
                if len(months) != 2:
                    raise ValueError("Observation does not cover its two source months")
                before, current = (_audit_value(o.subject_id, used, m) for m in months)
                pct = round((current - before) / abs(before) * 100, 3) if before else 0
                if (
                    abs(o.baseline - before) > 1e-6
                    or abs(o.current - current) > 1e-6
                    or o.change_pct != pct
                    or o.attributes["baseline_period"] != months[0]
                    or o.dimensions["current_period"] != months[1]
                ):
                    raise ValueError("Observation values do not reproduce from raw rows")
                e = next(x for x in snap.evidence if x.subject_id == o.subject_id)
                if e.provenance != o.attributes["record_ids"] or (
                    e.values["baseline"],
                    e.values["current"],
                    e.values["change_pct"],
                ) != (o.baseline, o.current, o.change_pct):
                    raise ValueError("Evidence facts/lineage diverge from raw observations")
                if (
                    e.values["capture_ids"] != o.attributes["capture_ids"]
                    or e.values["revision_ids"] != o.attributes["revision_ids"]
                ):
                    raise ValueError("Evidence capture lineage mismatch")
            if sorted({x["capture_id"] for x in meta["capture_history"]}) != meta["capture_ids"]:
                raise ValueError("Capture history does not match generated rows")
            if snap.error and (
                rows
                or snap.observations
                or snap.evidence
                or snap.contract.source_status != "failed"
            ):
                raise ValueError("Failed source has data")


def build_cadence_scenario():
    tables, catalog, descs = _tables(), *_descriptors()
    answers = copy.deepcopy(NORTHSTAR_POLICY_INTERVENTION["owner_answers"])
    answers["metric_scope"] = SIMULATED_SCOPE
    onboarding = _period("2025-01", tables, descs)
    periods, labels, schedule = [], {}, []
    recipients = {
        "ignore": [],
        "investigate": ["analytics"],
        "notify": ["leadership"],
        "insufficient_data": ["data-trust"],
    }
    notes = {
        "total_plus_10": "Prior-revision total is USD 10 above current channel-row sum.",
        "partial": "Only 20 of 31 current days are present; comparison is partial.",
        "unavailable": "Primary source returned no rows.",
    }
    for i, (month, case) in enumerate(zip(MONTHS, CASES, strict=True)):
        fault, family = case[4:]
        period = _period(month, tables, descs, fault)
        outcome = _outcome(period, answers)
        periods.append(period)
        labels[period["period_id"]] = {
            "outcome": outcome,
            "recipients": recipients[outcome],
            "category": family,
        }
        schedule.append(
            {
                "index": i,
                "period_id": period["period_id"],
                "case_family": family,
                "fault": notes.get(fault),
                "expected_outcome": outcome,
            }
        )
    replay_guidance = (
        "Apply the reviewed monthly policy retrospectively to each archived close. "
        "These fictional values are historical measurement inputs, not current company conditions; "
        "do not report a current business incident. Keep Sales, Web, Finance, and Support separate."
    )
    public = {
        "company": "Northstar Outfitters Co.",
        "brief": replay_guidance,
        "decision_guidance": replay_guidance,
        "glossary": {
            "comparison": "Previous complete calendar month; captures occur after close.",
            "net_sales": "Generated fictional monthly channel ledger balance in USD.",
        },
        "catalog": catalog,
        "owner_topics": list(answers),
        "owner_answers": copy.deepcopy(answers),
        "destinations": copy.deepcopy(DESTINATIONS),
        "numeric_vocabulary": [],
        "submission_contract": {
            "outcomes": list(recipients),
            "claim_types": ["observation", "accounting_decomposition", "association", "hypothesis"],
            "number_units": ["currency", "count", "percent", "ratio", "tickets"],
            "numeric_definitions": {},
        },
        "source_transport": {
            "kind": "generated_fictional_monthly_close",
            "actual_superset": False,
            "description": "Simulation-coordinator-authored fictional records; no live BI or raw warehouse extraction.",
        },
        "require_agent_data_signoff": True,
        "onboarding": onboarding,
        "periods": periods,
    }
    intervention = copy.deepcopy(NORTHSTAR_POLICY_INTERVENTION)
    intervention["owner_answers"] = copy.deepcopy(answers)
    scenario = {
        "scenario_id": SCENARIO_ID,
        "public": public,
        "private": {"periods": labels},
        "policy_intervention": intervention,
    }
    pilot = [schedule[i] for i in PILOT_INDICES]
    registration = {
        "protocol": PROTOCOL,
        "authored_functional_fixture": True,
        "independent_data_claim": False,
        "interpretation": "Fictional functional policy test, not independent data or an accuracy estimate.",
        "temporal_scope": "Archived monthly closes replayed through today's gateway; not a real-time scheduler trial.",
        "holdout_scope": "Remaining windows are the same fictional company and populations, not a new-company holdout.",
        "reporting_months": list(MONTHS),
        "pilot_indices": PILOT_INDICES.copy(),
        "pilot_period_ids": [x["period_id"] for x in pilot],
        "pilot_outcomes": [x["expected_outcome"] for x in pilot],
        "owner_answers": copy.deepcopy(answers),
        "case_schedule": schedule,
        "source_contracts_authored_for_generated_records": True,
        "source_populations_joined": False,
        "selection_or_scoring_used_legacy_private_oracle": False,
    }
    if (
        registration["owner_answers"] != public["owner_answers"]
        or intervention["owner_answers"] != public["owner_answers"]
    ):
        raise ValueError("Public, intervention, and registration owner policies differ")
    _validate(scenario)
    return scenario, registration

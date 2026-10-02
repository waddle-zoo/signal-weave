"""Small, offline fixtures for empirical automatic-card-authoring checks.

The returned dictionaries are intentionally ordinary JSON-shaped values.  Setup
labels stay outside source state, and the expert card is a separate conditional
control rather than input to an authoring arm.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from signalweave.compiler import base_plan
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    Observation,
    Outcome,
    ResourceContract,
    ResourceSnapshot,
    SourceRef,
)

DEFAULT_SEED = 20261002
AS_OF = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def _token(rng: random.Random, length: int = 12) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(rng.choice(alphabet) for _ in range(length))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _digest(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode()
    return hashlib.sha256(payload).hexdigest()


def _ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _numeric_values(
    baseline_numerator: int | None,
    baseline_denominator: int | None,
    current_numerator: int | None,
    current_denominator: int | None,
) -> dict[str, Any]:
    baseline_rate = _ratio(baseline_numerator, baseline_denominator)
    current_rate = _ratio(current_numerator, current_denominator)
    return {
        "baseline_numerator": baseline_numerator,
        "baseline_denominator": baseline_denominator,
        "current_numerator": current_numerator,
        "current_denominator": current_denominator,
        "baseline_rate": baseline_rate,
        "current_rate": current_rate,
        "delta": None if baseline_rate is None or current_rate is None else current_rate - baseline_rate,
        "change_pct": (
            None
            if baseline_rate in (None, 0) or current_rate is None
            else (current_rate - baseline_rate) / abs(baseline_rate) * 100
        ),
    }


def _source(
    *,
    key: str,
    adapter: str,
    resource: str,
    label: str,
    population: str,
    grain: str,
    required: bool = True,
    window: str = "previous_period",
) -> dict[str, Any]:
    return SourceRef(
        key=key,
        adapter=adapter,
        resource=resource,
        label=label,
        required=required,
        # The comparison window is a source contract, not an analytical
        # comparison key. No synthetic comparison report is needed here.
        required_comparison_keys=[],
        parameters={
            "approval": "owner-reviewed synthetic source",
            "population": population,
            "grain": grain,
            "period_contract": "closed interval ending before company as_of",
            "source_age_contract": "source captured one hour before replay clock; historical period is explicit",
        },
    ).model_dump(mode="json")


def _contract(
    *,
    tenant: str,
    domain: str,
    population: str,
    grain: str,
    metric_names: list[str],
    roles: list[str],
) -> ResourceContract:
    return ResourceContract(
        tenant_id=tenant,
        domain=domain,
        scope="synthetic company population; no cross-company rows",
        metric_names=metric_names,
        available_comparison_windows=["previous_period"],
        population=population,
        grain=grain,
        freshness_sla_hours=48,
        roles=roles,
        source_status="healthy",
        authorized=True,
    )


def _snapshot(
    *,
    source: dict[str, Any],
    company_id: str,
    as_of: datetime,
    period_id: str,
    period_start: datetime,
    period_end: datetime,
    population: str,
    grain: str,
    metric_names: list[str],
    roles: list[str],
    evidence: list[dict[str, Any]],
    observations: list[dict[str, Any]] | None = None,
    completeness: str = "complete",
    coverage: str = "declared",
    source_captured_offset_hours: int = 2,
) -> dict[str, Any]:
    captured_at = period_end + timedelta(hours=source_captured_offset_hours + 1)
    source_captured_at = period_end + timedelta(hours=source_captured_offset_hours)
    return ResourceSnapshot(
        source_key=source["key"],
        adapter=source["adapter"],
        resource=source["resource"],
        title=source["label"],
        description=(
            f"Bounded {grain} snapshot for {population}; completeness is {completeness} "
            f"and coverage is {coverage}."
        ),
        observations=[Observation.model_validate(item) for item in (observations or [])],
        evidence=[Evidence.model_validate(item) for item in evidence],
        metadata={
            "company_id": company_id,
            "period_id": period_id,
            "period_start": _iso(period_start),
            "period_end": _iso(period_end),
            "as_of": _iso(as_of),
            "completeness": completeness,
            "coverage": coverage,
            "population": population,
            "grain": grain,
            "period_contract": "closed interval ending before company as_of",
            "source_age_contract": "source captured one hour before replay clock",
            "replay_clock": _iso(captured_at),
        },
        captured_at=captured_at,
        source_captured_at=source_captured_at,
        contract=_contract(
            tenant=company_id,
            domain=company_id,
            population=population,
            grain=grain,
            metric_names=metric_names,
            roles=roles,
        ),
    ).model_dump(mode="json")


def _evidence(
    *,
    source_key: str,
    token: str,
    statement: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    return Evidence(
        source_key=source_key,
        subject_id=f"subject-{token}",
        subject_label="bounded source result",
        statement=statement,
        values=values,
        provenance=[f"source:{source_key}:fact-{token}"],
    ).model_dump(mode="json")


def _observation(
    *,
    source_key: str,
    token: str,
    metric: str,
    current: float | None,
    baseline: float | None,
    change_pct: float | None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return Observation(
        source_key=source_key,
        subject_id=f"subject-{token}",
        subject_label="bounded source result",
        metric=metric,
        current=current,
        baseline=baseline,
        change_pct=change_pct,
        attributes=attributes or {},
        provenance=[f"source:{source_key}:observation-{token}"],
    ).model_dump(mode="json")


def _period(index: int, *, holdout: bool) -> tuple[str, datetime, datetime]:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc) if holdout else datetime(
        2026, 8, 3, tzinfo=timezone.utc
    )
    period_index = index - 3 if holdout else index
    period_start = start + timedelta(days=7 * period_index)
    period_end = period_start + timedelta(days=6, hours=23, minutes=59)
    return f"period-{period_index + (4 if holdout else 1):02d}", period_start, period_end


def _dataset(
    *,
    company_id: str,
    split: str,
    dataset_id: str,
    first_start: datetime,
    last_end: datetime,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "split": split,
        "observed_from": _iso(first_start),
        "observed_to": _iso(last_end),
        "source_catalog_version": f"catalog-{company_id}",
        "context_version": f"policy-{company_id}",
        "digest": _digest(company_id, split, _iso(first_start), _iso(last_end)),
        "label_source": "owner-reviewed synthetic labels",
    }


def _case(
    *,
    case_id: str,
    resources: list[dict[str, Any]],
    outcome: Outcome,
    destinations: list[dict[str, str]],
    delivery_keys: list[str],
    required_keys: list[str],
    dataset: dict[str, Any],
) -> dict[str, Any]:
    by_key = {item["key"]: item["destination"] for item in destinations}
    route_destinations = {key: by_key[key] for key in delivery_keys}
    return {
        "id": case_id,
        "resources": resources,
        "expected_outcome": outcome.value,
        "expected_delivery_method_keys": delivery_keys,
        "expected_delivery_destinations": route_destinations,
        "required_evidence_source_keys": required_keys,
        "expected_retrieval_refs": [
            f"{resource['adapter']}|{resource['resource']}" for resource in resources
        ],
        "dataset": dataset,
    }


def _expert_card(
    *,
    card_id: str,
    brief: str,
    policy: str,
    sources: list[dict[str, Any]],
    destinations: list[dict[str, str]],
    outcome_by_destination: dict[str, Outcome],
    watch_for: list[str],
    questions: list[str],
) -> dict[str, Any]:
    card = InsightCard(
        id=card_id,
        title=brief,
        what_to_watch=brief,
        why_watch="Support a bounded owner decision from the declared source population.",
        watch_for=watch_for,
        questions=questions,
        decision_guidance=policy,
        sources=[SourceRef.model_validate(item) for item in sources],
        delivery_methods=[
            DeliveryMethod(
                key=destination["key"],
                outcome=outcome_by_destination[destination["key"]],
                label=destination["label"],
                destination=destination["destination"],
            )
            for destination in destinations
            if destination["key"] in outcome_by_destination
        ],
        comparison_windows=["previous_period"],
        owner="expert-control",
    )
    card.compiled_plan = base_plan(card)
    return card.model_dump(mode="json")


def _support_company(rng: random.Random) -> dict[str, Any]:
    company_id = f"company-{_token(rng)}"
    source_key = f"source-{_token(rng)}"
    policy_key = f"source-{_token(rng)}"
    source = _source(
        key=source_key,
        adapter="trino",
        resource=f"query:{_token(rng, 16)}",
        label="Support SLA measurements",
        population="resolved priority tickets with an eligible service clock",
        grain="weekly service interval",
    )
    policy_source = _source(
        key=policy_key,
        adapter="preset",
        resource=f"dataset:{_token(rng, 16)}",
        label="Support SLA definition",
        population="owner-approved SLA policy and eligible-ticket definition",
        grain="policy revision",
    )
    sources = [source, policy_source]
    destinations = [
        {"key": f"directory-{_token(rng)}", "label": "Support operations", "destination": "slack://support-operations"},
        {"key": f"directory-{_token(rng)}", "label": "Support data steward", "destination": "slack://support-data"},
    ]
    notify_key, investigate_key = destinations[0]["key"], destinations[1]["key"]
    policy = (
        "For the resolved-priority-ticket population, use the owner-approved eligible denominator and "
        "the closed weekly interval. If the current SLA miss rate is at least 0.10 and the denominator "
        "is present, notify Support operations. If it is below 0.10, ignore. If the denominator or its "
        "population contract is unavailable, investigate with the Support data steward rather than "
        "estimate a rate. The policy source defines eligibility; the measurement source "
        "supplies the period values."
    )

    def make_case(index: int, *, numerator: int | None, denominator: int | None, outcome: Outcome) -> dict[str, Any]:
        period_id, period_start, period_end = _period(index, holdout=index >= 3)
        token = _token(rng)
        values = _numeric_values(5, 100, numerator, denominator)
        measurement = _snapshot(
            source=source,
            company_id=company_id,
            as_of=AS_OF,
            period_id=period_id,
            period_start=period_start,
            period_end=period_end,
            population="resolved priority tickets with an eligible service clock",
            grain="weekly service interval",
            metric_names=["sla_miss_rate", "eligible_ticket_count"],
            roles=["primary"],
            completeness="partial" if denominator is None else "complete",
            coverage="unknown" if denominator is None else "declared",
            evidence=[_evidence(
                source_key=source_key,
                token=token,
                statement="The bounded SLA measurement contains baseline and current miss counts for the declared interval.",
                values=values,
            )],
            observations=[_observation(
                source_key=source_key,
                token=token,
                metric="sla_miss_rate",
                current=values["current_rate"],
                baseline=values["baseline_rate"],
                change_pct=values["change_pct"],
                attributes={
                    "current_eligible_denominator": values["current_denominator"],
                    "population": "resolved priority tickets with an eligible service clock",
                },
            )],
        )
        policy_snapshot = _snapshot(
            source=policy_source,
            company_id=company_id,
            as_of=AS_OF,
            period_id=period_id,
            period_start=period_start,
            period_end=period_end,
            population="owner-approved SLA policy and eligible-ticket definition",
            grain="policy revision",
            metric_names=["sla_threshold", "eligible_population"],
            roles=["definition"],
            evidence=[_evidence(
                source_key=policy_key,
                token=_token(rng),
                statement="The owner-approved policy defines the SLA threshold and eligible population.",
                values={"threshold": 0.10, "eligible_population": "resolved priority tickets with an eligible service clock"},
            )],
        )
        dataset = _dataset(
            company_id=company_id,
            split="holdout" if index >= 3 else "validation",
            dataset_id=f"dataset-{_token(rng)}",
            first_start=period_start,
            last_end=period_end,
        )
        return _case(
            case_id=f"case-{_token(rng)}",
            resources=[measurement, policy_snapshot],
            outcome=outcome,
            destinations=destinations,
            delivery_keys=[notify_key] if outcome is Outcome.NOTIFY else [investigate_key] if outcome is Outcome.INVESTIGATE else [],
            required_keys=[source_key, policy_key],
            dataset=dataset,
        )

    setup_cases = [
        make_case(0, numerator=14, denominator=100, outcome=Outcome.NOTIFY),
        make_case(1, numerator=4, denominator=100, outcome=Outcome.IGNORE),
        make_case(2, numerator=12, denominator=None, outcome=Outcome.INVESTIGATE),
    ]
    holdout_cases = [
        make_case(3, numerator=9, denominator=120, outcome=Outcome.IGNORE),
        make_case(4, numerator=18, denominator=140, outcome=Outcome.NOTIFY),
        make_case(5, numerator=2, denominator=80, outcome=Outcome.IGNORE),
        make_case(6, numerator=13, denominator=100, outcome=Outcome.NOTIFY),
    ]
    card = _expert_card(
        card_id=f"card-{_token(rng)}",
        brief="Support SLA threshold monitor",
        policy=policy,
        sources=sources,
        destinations=destinations,
        outcome_by_destination={notify_key: Outcome.NOTIFY, investigate_key: Outcome.INVESTIGATE},
        watch_for=["The current SLA miss rate crosses the owner threshold.", "The eligible denominator is declared."],
        questions=["Is the reported SLA rate scoped to the approved eligible-ticket population?"],
    )
    return {
        "id": company_id,
        "brief": "Support SLA threshold monitor over an eligible-ticket population.",
        "owner_policy": policy,
        "as_of": _iso(AS_OF),
        "destinations": destinations,
        "sources": sources,
        "setup_cases": setup_cases,
        "holdout_cases": holdout_cases,
        "expert_card": card,
    }


def _database_company(rng: random.Random) -> dict[str, Any]:
    company_id = f"company-{_token(rng)}"
    latency_key, inventory_key, cpu_key = (f"source-{_token(rng)}" for _ in range(3))
    latency = _source(
        key=latency_key, adapter="trino", resource=f"query:{_token(rng, 16)}",
        label="Database latency and lag", population="declared customer database clusters", grain="weekly interval",
    )
    inventory = _source(
        key=inventory_key, adapter="preset", resource=f"dataset:{_token(rng, 16)}",
        label="Database region inventory", population="customer database clusters and regions", grain="inventory revision",
    )
    cpu = _source(
        key=cpu_key, adapter="trino", resource=f"query:{_token(rng, 16)}",
        label="Database host CPU", population="database hosts in the declared cluster set", grain="weekly interval",
        required=False,
    )
    sources = [latency, inventory, cpu]
    destinations = [
        {"key": f"directory-{_token(rng)}", "label": "Database investigation", "destination": "slack://database-investigation"},
        {"key": f"directory-{_token(rng)}", "label": "Database notifications", "destination": "slack://database-notifications"},
    ]
    investigate_key = destinations[0]["key"]
    policy = (
        "Use only the declared customer-cluster population. If p95 latency is above 120 ms and lag "
        "is above 50 ms, and the inventory declares the affected regions, investigate through the "
        "Database investigation destination; this card never notifies from that correlation alone. "
        "If latency and lag remain within those limits and only host CPU is elevated, ignore. If region "
        "coverage is unknown, return insufficient data and do not substitute host CPU or an incident note "
        "for the missing population contract. The latency source owns measurements, inventory owns region "
        "coverage, and the CPU source is diagnostic only."
    )

    def make_case(
        index: int,
        *,
        current_latency: int,
        current_lag: int,
        regions: list[str] | None,
        cpu_percent: int,
        outcome: Outcome,
    ) -> dict[str, Any]:
        period_id, period_start, period_end = _period(index, holdout=index >= 3)
        token = _token(rng)
        latency_values = {
            "baseline_p95_ms": 100,
            "current_p95_ms": current_latency,
            "p95_delta_ms": current_latency - 100,
            "baseline_lag_ms": 12,
            "current_lag_ms": current_lag,
            "lag_delta_ms": current_lag - 12,
        }
        latency_snapshot = _snapshot(
            source=latency, company_id=company_id, as_of=AS_OF, period_id=period_id,
            period_start=period_start, period_end=period_end,
            population="declared customer database clusters", grain="weekly interval",
            metric_names=["p95_latency_ms", "replication_lag_ms"], roles=["primary"],
            evidence=[_evidence(source_key=latency_key, token=token,
                statement="The bounded database measurement reports latency and replication lag for the interval.",
                values=latency_values)],
            observations=[_observation(source_key=latency_key, token=token,
                metric="p95_latency_ms", current=current_latency, baseline=100,
                change_pct=(current_latency - 100) / 100 * 100,
                attributes={"population": "declared customer database clusters"}),
                _observation(source_key=latency_key, token=_token(rng),
                metric="replication_lag_ms", current=current_lag, baseline=12,
                change_pct=(current_lag - 12) / 12 * 100,
                attributes={"population": "declared customer database clusters"})],
        )
        inventory_snapshot = _snapshot(
            source=inventory, company_id=company_id, as_of=AS_OF, period_id=period_id,
            period_start=period_start, period_end=period_end,
            population="customer database clusters and regions", grain="inventory revision",
            metric_names=["affected_regions", "region_coverage"], roles=["quality"],
            completeness="partial" if regions is None else "complete",
            coverage="unknown" if regions is None else "declared",
            evidence=[_evidence(source_key=inventory_key, token=_token(rng),
                statement="The cluster inventory reports the region set and its coverage status.",
                values={"regions": regions, "coverage": "unknown" if regions is None else "declared",
                        "population_contract": "customer database clusters and regions"})],
        )
        cpu_snapshot = _snapshot(
            source=cpu, company_id=company_id, as_of=AS_OF, period_id=period_id,
            period_start=period_start, period_end=period_end,
            population="database hosts in the declared cluster set", grain="weekly interval",
            metric_names=["host_cpu_percent"], roles=["diagnostic"],
            evidence=[_evidence(source_key=cpu_key, token=_token(rng),
                statement="The host telemetry reports CPU utilization for the interval.",
                values={"cpu_percent": cpu_percent, "population": "database hosts in the declared cluster set"})],
        )
        dataset = _dataset(
            company_id=company_id, split="holdout" if index >= 3 else "validation",
            dataset_id=f"dataset-{_token(rng)}", first_start=period_start, last_end=period_end,
        )
        return _case(
            case_id=f"case-{_token(rng)}", resources=[latency_snapshot, inventory_snapshot, cpu_snapshot],
            outcome=outcome, destinations=destinations,
            delivery_keys=[investigate_key] if outcome is Outcome.INVESTIGATE else [],
            required_keys=[latency_key, inventory_key], dataset=dataset,
        )

    setup_cases = [
        make_case(0, current_latency=148, current_lag=83, regions=["r1", "r2", "r3"], cpu_percent=58, outcome=Outcome.INVESTIGATE),
        make_case(1, current_latency=104, current_lag=16, regions=["r1", "r2", "r3"], cpu_percent=61, outcome=Outcome.IGNORE),
        make_case(2, current_latency=143, current_lag=76, regions=None, cpu_percent=91, outcome=Outcome.INSUFFICIENT_DATA),
    ]
    holdout_cases = [
        make_case(3, current_latency=132, current_lag=64, regions=["r1", "r3"], cpu_percent=68, outcome=Outcome.INVESTIGATE),
        make_case(4, current_latency=103, current_lag=15, regions=["r1", "r2", "r3"], cpu_percent=96, outcome=Outcome.IGNORE),
        make_case(5, current_latency=129, current_lag=59, regions=None, cpu_percent=55, outcome=Outcome.INSUFFICIENT_DATA),
        make_case(6, current_latency=137, current_lag=62, regions=["r2", "r3"], cpu_percent=94, outcome=Outcome.INVESTIGATE),
    ]
    card = _expert_card(
        card_id=f"card-{_token(rng)}", brief="Database correlation monitor", policy=policy,
        sources=sources, destinations=destinations,
        outcome_by_destination={investigate_key: Outcome.INVESTIGATE},
        watch_for=["Latency and lag exceed their declared limits together.", "Region coverage is declared for the customer-cluster population."],
        questions=["Is the correlated measurement scoped to the declared database clusters?"],
    )
    return {
        "id": company_id,
        "brief": "Database latency, replication lag, and region-coverage monitor.",
        "owner_policy": policy,
        "as_of": _iso(AS_OF),
        "destinations": destinations,
        "sources": sources,
        "setup_cases": setup_cases,
        "holdout_cases": holdout_cases,
        "expert_card": card,
    }


def _finance_company(rng: random.Random) -> dict[str, Any]:
    company_id = f"company-{_token(rng)}"
    ledger_key, note_key = f"source-{_token(rng)}", f"source-{_token(rng)}"
    ledger = _source(
        key=ledger_key, adapter="trino", resource=f"query:{_token(rng, 16)}",
        label="Finance approval ledger", population="approval requests in the controlled finance queue", grain="approval record",
    )
    note = _source(
        key=note_key, adapter="preset", resource=f"dataset:{_token(rng, 16)}",
        label="Finance approval notes", population="owner and reviewer notes attached to approval requests", grain="approval record",
    )
    sources = [ledger, note]
    destinations = [
        {"key": f"directory-{_token(rng)}", "label": "Finance approvals", "destination": "slack://finance-approvals"},
        {"key": f"directory-{_token(rng)}", "label": "Finance review", "destination": "slack://finance-review"},
    ]
    notify_key, investigate_key = destinations[0]["key"], destinations[1]["key"]
    policy = (
        "This is a nonnumeric approval monitor for the controlled finance queue. Notify Finance approvals "
        "when the signed approval ledger has status approved; ignore a signed pending or rejected status. "
        "If the signed status is unavailable, return insufficient data and do not infer it from notes. "
        "If the signed status is exactly unresolved, investigate through Finance review. The "
        "signed ledger is authoritative when it conflicts with an attached note; retain both sources in the "
        "evidence record, but the note cannot overturn the signed status. Use Finance review only when the "
        "ledger is present but its status is unresolved. Source coverage is the controlled queue, and each "
        "record is evaluated within its closed approval interval."
    )

    def make_case(index: int, *, ledger_status: str | None, note_status: str, outcome: Outcome) -> dict[str, Any]:
        period_id, period_start, period_end = _period(index, holdout=index >= 3)
        ledger_snapshot = _snapshot(
            source=ledger, company_id=company_id, as_of=AS_OF, period_id=period_id,
            period_start=period_start, period_end=period_end,
            population="approval requests in the controlled finance queue", grain="approval record",
            metric_names=["approval_status"], roles=["primary"],
            completeness="partial" if ledger_status is None else "complete",
            coverage="unknown" if ledger_status is None else "declared",
            evidence=[_evidence(source_key=ledger_key, token=_token(rng),
                statement="The signed approval ledger contains the status recorded for the controlled request.",
                values={"signed_status": ledger_status, "authority": "signed approval ledger",
                        "population": "approval requests in the controlled finance queue"})],
        )
        note_snapshot = _snapshot(
            source=note, company_id=company_id, as_of=AS_OF, period_id=period_id,
            period_start=period_start, period_end=period_end,
            population="owner and reviewer notes attached to approval requests", grain="approval record",
            metric_names=["note_status"], roles=["corroborating"],
            evidence=[_evidence(source_key=note_key, token=_token(rng),
                statement="An attached approval note records the reviewer wording for the controlled request.",
                values={"note_status": note_status, "authority": "attached approval note",
                        "population": "owner and reviewer notes attached to approval requests"})],
        )
        dataset = _dataset(
            company_id=company_id, split="holdout" if index >= 3 else "validation",
            dataset_id=f"dataset-{_token(rng)}", first_start=period_start, last_end=period_end,
        )
        return _case(
            case_id=f"case-{_token(rng)}", resources=[ledger_snapshot, note_snapshot],
            outcome=outcome, destinations=destinations,
            delivery_keys=[notify_key] if outcome is Outcome.NOTIFY else [investigate_key] if outcome is Outcome.INVESTIGATE else [],
            required_keys=[ledger_key, note_key], dataset=dataset,
        )

    setup_cases = [
        make_case(0, ledger_status="approved", note_status="reviewed", outcome=Outcome.NOTIFY),
        make_case(1, ledger_status="pending", note_status="awaiting owner", outcome=Outcome.IGNORE),
        make_case(2, ledger_status=None, note_status="approved in note", outcome=Outcome.INSUFFICIENT_DATA),
    ]
    holdout_cases = [
        make_case(3, ledger_status="approved", note_status="confirmed", outcome=Outcome.NOTIFY),
        make_case(4, ledger_status="rejected", note_status="closed without approval", outcome=Outcome.IGNORE),
        make_case(5, ledger_status="unresolved", note_status="still under review", outcome=Outcome.INVESTIGATE),
        make_case(6, ledger_status="approved", note_status="rejected", outcome=Outcome.NOTIFY),
    ]
    card = _expert_card(
        card_id=f"card-{_token(rng)}", brief="Finance approval monitor", policy=policy,
        sources=sources, destinations=destinations,
        outcome_by_destination={notify_key: Outcome.NOTIFY, investigate_key: Outcome.INVESTIGATE},
        watch_for=["The signed approval status is resolved.", "An attached note is retained as corroborating context."],
        questions=["Does the signed ledger provide the authoritative approval status for this request?"],
    )
    return {
        "id": company_id,
        "brief": "Finance approval-state monitor with signed-record precedence.",
        "owner_policy": policy,
        "as_of": _iso(AS_OF),
        "destinations": destinations,
        "sources": sources,
        "setup_cases": setup_cases,
        "holdout_cases": holdout_cases,
        "expert_card": card,
    }


def build_companies(seed: int = DEFAULT_SEED) -> list[dict]:
    """Return three deterministic, disjoint synthetic authoring companies."""

    rng = random.Random(seed)
    return [_support_company(rng), _database_company(rng), _finance_company(rng)]

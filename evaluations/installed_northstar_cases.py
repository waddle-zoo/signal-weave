"""Offline fixture for the installed-binary Northstar MCP onboarding trial.

The fixture deliberately has no expert card.  A caller must draft the card from
the public company brief, catalog, glossary, owner answers, and the quiet
onboarding snapshot.  The first historical week is calibration-only; the
remaining seven weeks are replay inputs with private evaluator labels.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.northstar_growth_history_trial import (
    DEFAULT_SPEC,
    build_historical_cases,
    load_spec,
)
from evaluations.northstar_shadow_trial import _build_resources, _load_period_data
from signalweave.models import ResourceContract, ResourceDescriptor, ResourceSnapshot

_SOURCE_INFO = {
    "superset|dashboard:1": {
        "kind": "dashboard",
        "title": "Northstar Executive Pulse",
        "description": "Source-owned Northstar local dashboard snapshot for executive net-sales and channel observations.",
        "scope": "Northstar local seed scope as returned by the source; no additional population semantics are asserted.",
    },
    "northstar|fct_web_session": {
        "kind": "saved_query",
        "title": "Northstar Web Funnel",
        "description": "Web sessions and conversion-rate observations from the Northstar local seed replay.",
        "scope": "Northstar local seed scope as returned by the source; it is contextual evidence for the executive pulse.",
    },
    "northstar|fct_support_ticket": {
        "kind": "saved_query",
        "title": "Northstar Support Operations",
        "description": "Support backlog observations averaged across Northstar seed ticket rows.",
        "scope": "Northstar local seed scope as returned by the source; it is operational context.",
    },
    "northstar|fct_finance_daily": {
        "kind": "saved_query",
        "title": "Northstar Finance Daily",
        "description": "Finance booked-revenue observations summed from Northstar local seed rows.",
        "scope": "Northstar local seed scope as returned by the source; it is contextual evidence for the executive pulse.",
    },
}

_DISTRACTORS = (
    ("sandbox-dashboard", "Sandbox Executive Pulse", "Test-store dashboard; explicitly excluded from the Northstar tenant scope."),
    ("sandbox-funnel", "Sandbox Web Funnel", "Synthetic load-test funnel; explicitly excluded from the Northstar tenant scope."),
    ("sandbox-support", "Sandbox Support Queue", "Training queue activity; explicitly excluded from the customer-support scope."),
    ("sandbox-finance", "Sandbox Finance Daily", "Demo ledger values; explicitly excluded from the finance extract scope."),
)

_DESTINATIONS = [
    {"key": "leadership", "label": "Leadership", "destination": "slack://simulation-leadership", "authorized": True},
    {"key": "analytics", "label": "Analytics", "destination": "slack://simulation-analytics", "authorized": True},
    {"key": "data-trust", "label": "Data trust", "destination": "slack://simulation-data-trust", "authorized": True},
]

# Kept outside the private outcome register. This is the only predeclared
# response for the incident-policy clarification: the example policy names a
# severe incident but does not define one, and the support fixture is not an
# incident feed. The response records that absence instead of supplying a
# threshold or turning evaluator labels into owner knowledge.
OWNER_FOLLOWUP_KNOWLEDGE = {
    "severe_incident_definition": {
        "status": "unknown",
        "answer": (
            "Unknown. The Northstar materials provided for this evaluation mention "
            "a severe operational incident but contain no approved definition or "
            "severity threshold. The support source reports backlog, not incident "
            "status or severity, so it cannot establish whether the exception is "
            "present. Keep this exception unresolved and obtain an owner-approved "
            "definition and incident source before relying on it."
        ),
        "basis": [
            "The checked-in Northstar decision guidance mentions the exception but does not define it.",
            "The support source contains event_date and backlog fields, not incident or severity fields.",
        ],
    },
}

# A separate, explicitly authored simulation-policy intervention. It is not
# inferred from the historical oracle; its selected episodes are registered
# separately by northstar_release_onboarding_trial.py.
NORTHSTAR_POLICY_INTERVENTION = {
    "id": "northstar-sales-scope-policy-intervention-v1",
    "owner_answers": {
        "metric_scope": (
            "Northstar Executive Pulse source-reported monthly net sales from its sales-order-line "
            "population, grouped by the declared sales channels, is the metric of record. It does "
            "not establish company-wide sales, unique orders or customers, or completed/settled "
            "orders. Web Funnel, Finance Daily, and Support Operations are distinct populations "
            "that may be used only as source-level context; never row-join them or claim a shared cohort."
        ),
        "materiality": (
            "If the primary Executive Pulse source is unavailable or does not provide the needed "
            "sales comparison, or its total does not reconcile to the complete declared channel "
            "partition, return insufficient_data and route to data trust. Ignore absolute "
            "source-reported net-sales changes below 10%. No severe-incident exception is in force: "
            "the approved source scope has no incident feed. For a net-sales decline of at least "
            "15%, notify leadership only when at least two sales channels decline and either "
            "source-reported Web Funnel conversion or Finance Daily revenue also declines. All "
            "other material movements—including declines from 10% to below 15%, declines without "
            "that corroboration, and increases outside the under-10% ignore band—default to "
            "investigate, not silence."
        ),
        "routing": (
            "notify -> leadership; investigate -> analytics; insufficient_data -> data-trust; "
            "ignore -> none. Use only the authorized simulation destinations."
        ),
        "data_gaps": (
            "Support backlog is not incident status or severity. No incident feed is approved. "
            "Keep Web, Finance, Support, and Sales populations separate; do not join rows or claim "
            "a shared cohort. Do not invent missing source comparisons or numeric-condition keys; "
            "keep owner thresholds in plain-English decision guidance."
        ),
        "severe_incident_definition": (
            "No severe-incident exception applies in this intervention. The approved sources "
            "contain no incident feed; Support Operations reports backlog, not incident status "
            "or severity. Do not infer an incident from backlog."
        ),
        "source_scope": (
            "I explicitly approve the exact declared scope text for the sources selected in the "
            "current card review. As data expert, inspect those sources and pass their exact "
            "selected ref-to-scope map in source_scope_confirmations when approving. Keep Sales "
            "as the metric-of-record population and Web, Finance, and Support separate; no row joins."
        ),
    },
    "source_selection_reason": (
        "Owner-approved scope: Northstar Executive Pulse is the sales metric of record. Web "
        "Funnel, Finance Daily, and Support Operations remain distinct source populations used "
        "only as source-level context under the written policy; no row joins or shared-cohort claim "
        "are authorized. Confirm the exact declared scope for each selected ref."
    ),
    "recurring_questions_guidance": (
        "The owner has resolved the one-time setup clarifications above. Do not copy setup or "
        "approval questions into recurring card questions; leave recurring questions empty unless "
        "they express a distinct ongoing business question."
    ),
    "basis": (
        "Explicit simulation-coordinator-authored fictional owner policy, frozen before any selected future-period values are "
        "shown to either arm; not derived from private outcome labels."
    ),
}

_NUMERIC_PREFIX_BY_SUBJECT = {
    "revenue-total": "net_sales_total",
    "channel-online": "online_net_sales",
    "channel-store": "store_net_sales",
    "channel-mobile": "mobile_net_sales",
    "channel-marketplace": "marketplace_net_sales",
    "conversion-rate": "web_conversion_rate",
    "web-sessions": "web_sessions",
    "support-backlog": "support_backlog",
    "finance-revenue": "finance_booked_revenue",
}
_NUMERIC_FIELDS = ("baseline", "current", "delta", "change_pct")


def _northstar_numeric_facts(snapshots: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Expose a source-backed report vocabulary and independent score oracle.

    Calculations here define evaluation expectations only; the agent receives
    source observations and performs the analysis in its own workflow.
    """

    facts: dict[str, dict[str, Any]] = {}
    field_descriptions = {
        "baseline": "Source-reported baseline-period value.",
        "current": "Source-reported current-period value.",
        "delta": "Current-period value minus baseline-period value.",
        "change_pct": "Source-reported percent change from baseline to current.",
    }
    for snapshot in snapshots.values():
        source_ref = f"company_mcp|{snapshot['resource']}"
        for observation in snapshot.get("observations", []):
            prefix = _NUMERIC_PREFIX_BY_SUBJECT.get(str(observation.get("subject_id", "")))
            if not prefix:
                continue
            unit = str(observation.get("unit") or "")
            baseline, current = observation.get("baseline"), observation.get("current")
            values = {
                "baseline": baseline,
                "current": current,
                "delta": (current - baseline
                          if type(current) in {int, float} and type(baseline) in {int, float}
                          else None),
                "change_pct": observation.get("change_pct"),
            }
            for field in _NUMERIC_FIELDS:
                value = values[field]
                if type(value) not in {int, float}:
                    continue
                fact_id = f"{prefix}_{field}"
                facts[fact_id] = {
                    "value": value,
                    "unit": "percent" if field == "change_pct" else unit,
                    "absolute_tolerance": (0.01 if field == "change_pct" or unit != "ratio" else 1e-8),
                    "evidence_refs": [source_ref],
                    "definition": f"{field_descriptions[field]} {observation.get('subject_label', prefix)}.",
                }
    return facts


def _northstar_numeric_definitions(snapshots: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {
        fact_id: {"definition": fact["definition"], "unit": fact["unit"]}
        for fact_id, fact in _northstar_numeric_facts(snapshots).items()
    }


def _resource_id(source_ref: str) -> str:
    """Return a stable opaque id without carrying the original adapter/resource ref."""

    return "resource-" + hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:20]


def _iso(value: str) -> str:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _source_contract(snapshot: ResourceSnapshot, scenario_id: str) -> dict[str, Any]:
    contract = snapshot.contract.model_dump(mode="json")
    contract["tenant_id"] = scenario_id
    contract["available_comparison_windows"] = ["previous_period"]
    return contract


def _catalog(scenario_id: str, refs: dict[str, str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for original, info in _SOURCE_INFO.items():
        resource = refs[original]
        entries.append(ResourceDescriptor(
            adapter="company_mcp",
            resource=resource,
            kind=info["kind"],
            title=info["title"],
            description=info["description"],
            metadata={"tenant": scenario_id, "scope": info["scope"], "owner": "Northstar Growth Analytics", "read_only": True},
            contract=ResourceContract(
                tenant_id=scenario_id,
                authorized=True,
                available_comparison_windows=["previous_period"],
                source_status="healthy",
            ),
        ).model_dump(mode="json"))
    for suffix, title, description in _DISTRACTORS:
        resource = refs[suffix]
        entries.append(ResourceDescriptor(
            adapter="company_mcp", resource=resource, kind="saved_query", title=title,
            description=description,
            metadata={"tenant": scenario_id, "scope": "excluded sandbox scope", "excluded": True, "read_only": True},
            contract=ResourceContract(
                tenant_id=scenario_id, authorized=True,
                available_comparison_windows=["previous_period"], source_status="healthy",
            ),
        ).model_dump(mode="json"))
    return entries


def _rewrite_snapshot(snapshot: ResourceSnapshot, resource: str, scenario_id: str,
                      period_id: str, as_of: str, *, excluded: bool = False) -> dict[str, Any]:
    payload = snapshot.model_dump(mode="json")
    payload.update({
        "adapter": "company_mcp", "resource": resource, "source_key": resource,
        "captured_at": as_of, "source_captured_at": as_of,
        "contract": _source_contract(snapshot, scenario_id),
        "metadata": {
            **payload.get("metadata", {}),
            "tenant": scenario_id, "period_id": period_id, "as_of": as_of,
            "replayed_historical_data": True, "fresh_warehouse_read": False,
            "source_transport": "simulated_bi_fixture",
            "source_capture": (
                "Simulated BI transport over checked-in Northstar seed rows and synthetic replay "
                "adjustments; not an actual Superset capture or a fresh warehouse read."
            ),
            **({"excluded_scope": True} if excluded else {}),
        },
    })
    for observation in payload.get("observations", []):
        observation["source_key"] = resource
    for evidence in payload.get("evidence", []):
        evidence["source_key"] = resource
        evidence["provenance"] = [resource]
    return ResourceSnapshot.model_validate(payload).model_dump(mode="json")


def _reconcile_sales_channel_partition(snapshot: dict[str, Any]) -> None:
    """Generate channel values as an allocation of the fixed total replay value."""
    observations = snapshot.get("observations", [])
    total = next((item for item in observations if item.get("subject_id") == "revenue-total"), None)
    channels = [item for item in observations
                if str(item.get("subject_id", "")).startswith("channel-")]
    if total is None:
        raise ValueError("Northstar sales replay needs exactly one total observation")
    if not channels:
        # Some small legacy test seeds change channel membership between
        # months. Keep those observations untouched; reconciliation will fail
        # closed rather than inventing a partition for missing source rows.
        return

    baseline_sum = sum(float(item["baseline"]) for item in channels)
    total_baseline = float(total["baseline"])
    if abs(baseline_sum - total_baseline) > 1e-6:
        raise ValueError("Northstar local seed baseline does not reconcile to its channel rows")

    total_current = float(total["current"])
    raw_current_sum = sum(float(item["current"]) for item in channels)
    if raw_current_sum <= 0 or total_current < 0:
        raise ValueError("Northstar synthetic replay cannot allocate non-positive sales totals")

    # Keep the checked-in case's channel mix, but allocate it to the scenario's
    # fixed total so the declared partition is arithmetically coherent.
    scale = total_current / raw_current_sum
    allocated: list[float] = []
    for item in channels[:-1]:
        allocated.append(round(float(item["current"]) * scale, 6))
    allocated.append(round(total_current - sum(allocated), 6))
    for item, current in zip(channels, allocated, strict=True):
        baseline = float(item["baseline"])
        item["current"] = current
        item["change_pct"] = round((current - baseline) / abs(baseline) * 100, 3) if baseline else 0.0
        item.setdefault("attributes", {})["fixture_allocation"] = (
            "Synthetic channel allocation normalized to the fixed scenario total; not a source extract."
        )
    snapshot.setdefault("metadata", {})["source_transport"] = "simulated_bi_fixture"
    snapshot["metadata"]["sales_partition_generation"] = (
        "Channel current values allocated from their replay shares to exactly reconcile to the fixed total."
    )


def sales_partition_reconciliation(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Check the source-declared total/channel partition without policy thresholds."""
    observations = snapshot.get("observations", [])
    totals = [item for item in observations if item.get("subject_id") == "revenue-total"]
    channels = [item for item in observations
                if str(item.get("subject_id", "")).startswith("channel-")]
    errors: list[str] = []
    if len(totals) != 1:
        errors.append("expected exactly one total observation")
    if not channels:
        errors.append("missing declared channel observations")
    if len({item.get("subject_id") for item in channels}) != len(channels):
        errors.append("duplicate channel observation")
    if errors:
        return {"reconciled": False, "errors": errors}

    total = totals[0]
    numeric = [total.get("baseline"), total.get("current"),
               *(item.get("baseline") for item in channels),
               *(item.get("current") for item in channels)]
    if any(type(value) not in {int, float} for value in numeric):
        return {"reconciled": False, "errors": ["missing numeric total or channel value"]}

    baseline_sum = sum(float(item["baseline"]) for item in channels)
    current_sum = sum(float(item["current"]) for item in channels)
    baseline_gap = round(baseline_sum - float(total["baseline"]), 6)
    current_gap = round(current_sum - float(total["current"]), 6)
    if abs(baseline_gap) > 1e-6:
        errors.append("baseline total differs from channel sum")
    if abs(current_gap) > 1e-6:
        errors.append("current total differs from channel sum")
    periods = {
        (item.get("attributes", {}).get("baseline_period"),
         item.get("dimensions", {}).get("current_period"))
        for item in [total, *channels]
    }
    if len(periods) != 1:
        errors.append("total and channel rows use different comparison periods")
    return {
        "reconciled": not errors,
        "errors": errors,
        "total_baseline": float(total["baseline"]),
        "total_current": float(total["current"]),
        "channel_baseline_sum": baseline_sum,
        "channel_current_sum": current_sum,
        "baseline_gap": baseline_gap,
        "current_gap": current_gap,
    }


def _empty_distractor(resource: str, scenario_id: str, title: str, description: str,
                      period_id: str, as_of: str) -> dict[str, Any]:
    return ResourceSnapshot(
        source_key=resource, adapter="company_mcp", resource=resource, title=title,
        description=description, metadata={"tenant": scenario_id, "period_id": period_id, "as_of": as_of,
                                           "excluded_scope": True, "replayed_historical_data": True,
                                           "fresh_warehouse_read": False},
        contract=ResourceContract(tenant_id=scenario_id, authorized=True,
                                  available_comparison_windows=["previous_period"], source_status="healthy"),
        captured_at=as_of, source_captured_at=as_of,
    ).model_dump(mode="json")


def _period_snapshots(period_data: Any, case: Any, scenario_id: str,
                      refs: dict[str, str], period_id: str, as_of: str) -> dict[str, dict[str, Any]]:
    original = _build_resources(period_data, case.replay_case)
    snapshots = {
        f"company_mcp|{refs[item.source_key]}": _rewrite_snapshot(
            item, refs[item.source_key], scenario_id, period_id, as_of,
        )
        for item in original
    }
    for snapshot in snapshots.values():
        if snapshot.get("error"):
            snapshot["contract"]["source_status"] = "failed"
            snapshot["observations"] = []
            snapshot["evidence"] = []
            snapshot["analytical_comparisons"] = []
    sales_ref = f"company_mcp|{refs['superset|dashboard:1']}"
    if not snapshots[sales_ref].get("error"):
        _reconcile_sales_channel_partition(snapshots[sales_ref])
    for suffix, title, description in _DISTRACTORS:
        snapshots[f"company_mcp|{refs[suffix]}"] = _empty_distractor(
            refs[suffix], scenario_id, title, description, period_id, as_of,
        )
    return snapshots


def _private_label(case: Any, refs: dict[str, str],
                   snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    destination_by_outcome = {
        "notify": "leadership",
        "investigate": "analytics",
        "insufficient_data": "data-trust",
    }
    outcome = case.historical_outcome.value
    numeric_facts = _northstar_numeric_facts(snapshots)
    required_numeric_facts = (
        ["net_sales_total_baseline", "net_sales_total_current",
         "net_sales_total_change_pct"]
        if outcome in {"notify", "investigate"}
        and all(f"net_sales_total_{field}" in numeric_facts
                for field in _NUMERIC_FIELDS)
        else []
    )
    return {
        "historical_case_id": case.case_id,
        "outcome": outcome,
        "recipients": ([destination_by_outcome[case.historical_outcome.value]]
                       if case.historical_outcome.value in destination_by_outcome else []),
        "required_evidence_refs": [f"company_mcp|{refs[item]}" for item in case.required_explanation_sources],
        # The generic final-agent scorer uses this field to distinguish an
        # actionable event from a quiet period. Preserve the detailed Northstar
        # variant separately for evaluator analysis; an ignore on an
        # investigate/notify period is a missed workflow, not a safe abstention.
        "condition": ("event" if outcome in {"notify", "investigate"}
                      else "data_gap" if outcome == "insufficient_data" else "quiet"),
        "variant_id": case.variant_id,
        "required_owner_topics": ["metric_scope", "materiality", "routing", "data_gaps"],
        "numeric_facts": numeric_facts,
        "required_numeric_facts": required_numeric_facts,
        "required_claim_types": [],
        "allowed_claim_types": ["observation", "accounting_decomposition", "association", "hypothesis"],
    }


def build_northstar(seed_dir: Path, *, smoke: bool = False) -> dict[str, Any]:
    """Build the public/private installed-binary scenario from local seed rows."""

    spec = load_spec(DEFAULT_SPEC)
    cases = build_historical_cases(spec)
    if len(cases) != 48:
        raise ValueError(f"Northstar register must expand to 48 cases, got {len(cases)}")
    scenario_id = "northstar-outfitters-local"
    period_data = _load_period_data(seed_dir)
    refs = {source: _resource_id(source) for source in _SOURCE_INFO}
    refs.update({suffix: _resource_id(f"company_mcp|{suffix}") for suffix, _, _ in _DISTRACTORS})
    first_week = cases[:6]
    future_cases = cases[6:12] if smoke else cases[6:]
    policy = spec["card_policy"]["decision_guidance"]
    first_as_of = _iso(spec["periods"][0]["date"] + "T00:00:00+00:00")

    owner_examples = []
    for case in first_week:
        period_id = f"setup-{case.case_id}"
        resources = _period_snapshots(period_data, case, scenario_id, refs, period_id, first_as_of)
        label = _private_label(case, refs, resources)
        owner_examples.append({
            "id": case.case_id,
            "as_of": first_as_of,
            "expected_outcome": case.historical_outcome.value,
            "expected_delivery_destinations": {
                key: endpoint for key, endpoint in {
                    "leadership": "slack://simulation-leadership",
                    "analytics": "slack://simulation-analytics",
                    "data-trust": "slack://simulation-data-trust",
                }.items() if key in label["recipients"]
            },
            "required_evidence_refs": label["required_evidence_refs"],
            # Owner-labeled historical retrieval scope, not derived from a model's selection.
            "expected_retrieval_refs": [f"company_mcp|{refs[source]}" for source in _SOURCE_INFO],
            "resources": list(resources.values()),
        })

    onboarding_resources = _period_snapshots(period_data, first_week[0], scenario_id, refs, "onboarding-week-01", first_as_of)
    periods: list[dict[str, Any]] = []
    private_periods: dict[str, dict[str, Any]] = {}
    for case in future_cases:
        source_period = next(item for item in spec["periods"] if item["id"] == case.period_id)
        # The descriptive register ID contains the scenario family. It is
        # evaluator-only; do not leak that hint through source metadata.
        period_id = "period-" + hashlib.sha256(case.case_id.encode()).hexdigest()[:20]
        as_of = _iso(source_period["date"] + "T00:00:00+00:00")
        periods.append({"period_id": period_id, "as_of": as_of,
                        "snapshots": _period_snapshots(period_data, case, scenario_id, refs, period_id, as_of)})
        private_periods[period_id] = _private_label(
            case, refs, periods[-1]["snapshots"]
        )

    numeric_vocabulary = sorted(_northstar_numeric_facts(onboarding_resources))
    numeric_definitions = _northstar_numeric_definitions(onboarding_resources)

    public = {
        "company": "Northstar Outfitters Co.",
        "brief": spec["team"]["operating_question"],
        "glossary": {
            "net_sales": "Net sales, using the Northstar source's original metric label and meaning.",
            "comparison": "Previous complete reporting period; source periods are UTC and historical captures are replayed.",
        },
        "owner_topics": ["metric_scope", "materiality", "routing", "data_gaps"],
        "owner_answers": {"metric_scope": spec["team"]["source_basis"], "materiality": policy,
                          "routing": "notify -> leadership; investigate -> analytics; insufficient_data -> data-trust; ignore -> none. Use only the three authorized simulation Slack destinations.",
                          "data_gaps": "Do not infer missing evidence or causation; route source-quality failures to data trust."},
        "destinations": copy.deepcopy(_DESTINATIONS),
        "onboarding": {"period_id": "onboarding-week-01", "as_of": first_as_of, "snapshots": onboarding_resources},
        "periods": periods,
        "catalog": _catalog(scenario_id, refs),
        "numeric_vocabulary": numeric_vocabulary,
        "submission_contract": {"mode": "caller-agent-report", "outcomes": ["ignore", "notify", "investigate", "insufficient_data"],
                                 "claim_types": ["observation", "accounting_decomposition", "association", "hypothesis"],
                                 "number_units": sorted({item["unit"] for item in numeric_definitions.values()}),
                                 "numeric_definitions": numeric_definitions,
                                 "notes": "The caller-owned agent produces the final analysis. Identifiers are source-backed; for notify or investigate, report the primary net-sales baseline, current value, and source-reported percent change when available. Report a derived delta only when it reconciles with the source breakdown; otherwise explain the discrepancy."},
    }
    return {"scenario_id": scenario_id, "public": public,
            "private": {"family": "northstar-growth-history", "periods": private_periods},
            "owner_examples": owner_examples,
            "owner_followup_knowledge": copy.deepcopy(OWNER_FOLLOWUP_KNOWLEDGE)}

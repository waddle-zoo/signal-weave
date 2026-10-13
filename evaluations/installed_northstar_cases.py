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
            "source_capture": "Historical source capture replayed by the local binary fixture; not a fresh warehouse read.",
            **({"excluded_scope": True} if excluded else {}),
        },
    })
    for observation in payload.get("observations", []):
        observation["source_key"] = resource
    for evidence in payload.get("evidence", []):
        evidence["source_key"] = resource
        evidence["provenance"] = [resource]
    return ResourceSnapshot.model_validate(payload).model_dump(mode="json")


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
    return {"scenario_id": scenario_id, "public": public, "private": {"family": "northstar-growth-history", "periods": private_periods},
            "owner_examples": owner_examples}

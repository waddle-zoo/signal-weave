"""Prepare and run a default-profile Northstar installed-agent release trial.

This evaluation caller is fail-closed on a parent-certified native binary. Its
source service is a private loopback MCP backed by checked-in Northstar replay
fixtures, not a Superset extraction.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import hashlib
import inspect
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from evaluations.bootstrap_agent_trial import (
    Audit,
    RequestBudget,
    ToolSession,
    canonical,
    common_tools,
    digest,
    function,
)
from evaluations.bootstrap_scenarios import (
    _Submission,
    ask_owner,
    public_scenario,
)
from evaluations.codex_trial_transport import codex_episode
from evaluations.installed_northstar_cases import (
    NORTHSTAR_POLICY_INTERVENTION,
    OWNER_FOLLOWUP_KNOWLEDGE,
    _northstar_numeric_facts,
    _private_label,
    build_northstar,
    sales_partition_reconciliation,
)
from evaluations.northstar_growth_history_trial import (
    DEFAULT_SPEC as NORTHSTAR_HISTORY_SPEC,
)
from evaluations.northstar_growth_history_trial import (
    build_historical_cases,
)
from evaluations.northstar_growth_history_trial import (
    load_spec as load_northstar_history,
)
from evaluations.northstar_multistep_paired_trial import build_cases as build_multistep_cases
from evaluations.northstar_shadow_trial import ReplayCase, _build_resources, _load_period_data
from scripts.binary_provenance import source_fingerprint, verify_binary
from signalweave.mcp_server import AGENT_PROFILE_TOOLS
from signalweave.models import (
    Evidence,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = ROOT / "evaluations" / "data" / "northstar-multistep-seed"
DEFAULT_OUTPUT = ROOT / "artifacts" / "northstar-release-2026-10-13"
DEFAULT_INTERVENTION_OUTPUT = ROOT / "artifacts" / "northstar-owner-policy-reconciled-2026-10-13"
DEFAULT_KEY_FILE = Path("/Users/brandonsovran/Downloads/apikey_typesafe")
MODEL = "gpt-6-luna"
EFFORT = "xhigh"
PROFILE = "agent"
PROTOCOL_VERSION = "northstar-release-onboarding-v1"
POLICY_INTERVENTION_PROTOCOL = "northstar-owner-policy-ledger-v6"
POLICY_INTERVENTION_CASES = {
    "under_10_ignore": "period-41109ba382f9bde47760",
    "10_to_below_15_investigate": "period-c8cb712acffab956b59a",
    "corroborated_15_plus_decline_notify": "period-42733dd4648afe7bb944",
    "primary_sales_source_unavailable": "period-e82d47975f8ec9b4de0c",
}
POLICY_INTERVENTION_SOURCE_SHA256 = "722070fc3ca5997b1cd7beb9023e609827b270a8b5a00988ce6764978d58f74b"
POLICY_INTERVENTION_BINARY_SHA256 = "b5bb7388c7f143eb33e20285dcfd47e78e31f0570865eeb2b5f02011cb8b720c"
POLICY_INTERVENTION_JEV_BUDGET = 20
PILOT_SIZE = 4
FULL_BASE_SIZE = 24
CERTIFIED_BINARY_SHA256 = "764323c36da96332bacc662807ad4c36ce03065619bcafd03289eed670ca4f83"
CERTIFIED_SOURCE_SHA256 = "9460d2e8e08a3e06de7309cf6c8d554b17043074d8fa9fe7fbdcee972c1298e2"
CERTIFIED_VERSION = "0.2.0rc2"
SOURCE_CONTRACT_FIXTURE_VERSION = "northstar-seed-contract-v1"
SOURCE_ADAPTER = "company_mcp"
HOMONYM_TITLE = "Northstar Executive Pulse"
FORBIDDEN_FULL_TOOLS = frozenset({
    "bootstrap_insight_card", "simulate_insight_card", "preview_investigation_report",
    "evaluate_card_workflow",
})
AGENT_SOURCE_TOOLS = frozenset({"search_catalog", "inspect_resource"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    ).isoformat().replace("+00:00", "Z")


def _write_private(path: Path, value: Any) -> None:
    payload = (canonical(value) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _source_resource_by_original_ref(scenario: dict, original_ref: str) -> str:
    titles = {
        "superset|dashboard:1": "Northstar Executive Pulse",
        "northstar|fct_web_session": "Northstar Web Funnel",
        "northstar|fct_support_ticket": "Northstar Support Operations",
        "northstar|fct_finance_daily": "Northstar Finance Daily",
    }
    title = titles.get(original_ref)
    descriptor = next((item for item in scenario["public"]["catalog"]
                       if item.get("title") == title), None)
    if descriptor is None:
        raise ValueError(f"Required Northstar source is absent: {original_ref}")
    return str(descriptor["resource"])


def _seed_columns(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"Northstar seed table has no header: {path.name}")
        return list(reader.fieldnames)


def _ground_source_contracts(scenario: dict, seed_dir: Path) -> dict[str, Any]:
    """Expose seed-grounded source contracts without inventing analysis keys.

    The source snapshots already carry adapter-owned contracts, but the public
    catalog descriptors omit them. Copy those contracts into the manifest and
    replace claims the checked-in CSV columns cannot verify. The fixture keeps
    its actual source comparison contract separate from executable required
    keys and observed analytical comparisons.
    """
    specifications = {
        "superset|dashboard:1": {
            "seed_file": "fct_sales_order_line.csv",
            "required_columns": ["order_date", "channel", "net_sales"],
            "scope": "Northstar local sales-order-line seed only; no broader sales, customer, or order population is asserted.",
            "population": (
                "Rows with order_date, channel, and net_sales values in the local seed. "
                "The file has no customer or order identifier and no completion or "
                "settlement-status field."
            ),
            "grain": "Calendar month and sales channel; the monthly total sums net_sales across channels.",
        },
        "northstar|fct_web_session": {
            "seed_file": "fct_web_session.csv",
            "required_columns": ["event_date", "sessions", "orders", "revenue"],
            "scope": "Northstar local web-session seed only; separate from sales-order-line rows.",
            "population": (
                "Rows with event_date, sessions, orders, and revenue values in the local "
                "seed; individual session and customer identifiers are not present."
            ),
            "grain": "Calendar month; sessions and orders are summed, and conversion is total orders divided by total sessions.",
        },
        "northstar|fct_support_ticket": {
            "seed_file": "fct_support_ticket.csv",
            "required_columns": ["event_date", "backlog"],
            "scope": "Northstar local support-backlog seed only; it is not an incident feed.",
            "population": (
                "Rows with event_date and backlog values in the local seed; ticket IDs, "
                "ticket status, incident records, and severity fields are not present."
            ),
            "grain": "Calendar month; backlog is averaged across the available row values.",
        },
        "northstar|fct_finance_daily": {
            "seed_file": "fct_finance_daily.csv",
            "required_columns": ["event_date", "revenue"],
            "scope": "Northstar local finance seed only; separate from the sales and web populations.",
            "population": (
                "Rows with event_date and revenue values in the local seed; account and "
                "customer identifiers and a booked-status field are not present."
            ),
            "grain": "Calendar month; revenue values are summed.",
        },
    }
    tenant = scenario["scenario_id"]
    catalog_by_resource = {
        str(item["resource"]): item for item in scenario["public"]["catalog"]
    }
    periods = [scenario["public"]["onboarding"], *scenario["public"]["periods"]]
    audit_sources = []
    for original_ref, spec in specifications.items():
        resource = _source_resource_by_original_ref(scenario, original_ref)
        ref = f"{SOURCE_ADAPTER}|{resource}"
        descriptor = catalog_by_resource[resource]
        columns = _seed_columns(seed_dir / spec["seed_file"])
        if not set(spec["required_columns"]) <= set(columns):
            raise ValueError(f"Northstar source columns changed for {spec['seed_file']}")
        source_snapshot = scenario["public"]["onboarding"]["snapshots"].get(ref)
        if source_snapshot is None:
            raise ValueError(f"Northstar onboarding snapshot is missing: {ref}")
        contract = copy.deepcopy(source_snapshot["contract"])
        if contract.get("tenant_id") != tenant:
            raise ValueError(f"Northstar source contract tenant mismatch: {ref}")
        contract.update({
            "scope": spec["scope"],
            "population": spec["population"],
            "grain": spec["grain"],
        })
        if original_ref == "superset|dashboard:1":
            comparisons = contract.get("comparison_contracts", [])
            if len(comparisons) != 1 or comparisons[0].get("key") != "net-sales-change":
                raise ValueError("Northstar seed source comparison contract changed")
            comparisons[0].update({
                "definition": (
                    "Sum the net_sales values by calendar month across sales channels; "
                    "the local seed does not encode completion or settlement status."
                ),
                "population": spec["population"],
                "detail": (
                    "The monthly total and channel values are computed from the same "
                    "local seed rows. No order/customer identifier or completion/settlement "
                    "field is available in those rows."
                ),
            })
        if contract.get("required_comparison_keys", []) != []:
            raise ValueError("The Northstar seed must not invent required comparison keys")
        descriptor["contract"] = copy.deepcopy(contract)
        descriptor.setdefault("metadata", {})["scope"] = spec["scope"]
        for period in periods:
            snapshot = period["snapshots"].get(ref)
            if snapshot is None:
                continue
            period_source_status = snapshot.get("contract", {}).get("source_status")
            snapshot["contract"] = copy.deepcopy(contract)
            if period_source_status and period_source_status != "healthy":
                snapshot["contract"]["source_status"] = period_source_status
            snapshot.setdefault("metadata", {})["scope"] = spec["scope"]
        audit_sources.append({
            "ref": ref,
            "title": descriptor["title"],
            "seed_file": spec["seed_file"],
            "seed_columns": columns,
            "scope": spec["scope"],
            "population": spec["population"],
            "grain": spec["grain"],
            "available_comparison_windows": contract.get("available_comparison_windows", []),
            "source_comparison_contract_keys": [
                item["key"] for item in contract.get("comparison_contracts", [])
            ],
            "required_comparison_keys": contract.get("required_comparison_keys", []),
            "inspected_analytical_comparison_keys": [
                item["key"] for item in source_snapshot.get("analytical_comparisons", [])
            ],
        })
    audit = {
        "version": SOURCE_CONTRACT_FIXTURE_VERSION,
        "basis": "Checked-in Northstar seed columns and existing source-generated snapshot contracts; not evaluator outcome labels.",
        "source_classification": "Historical local replay over checked-in seed rows; not a live Superset extraction.",
        "sources": audit_sources,
        "numeric_conditions": (
            "Optional. No required_comparison_keys or inspected analytical_comparisons are fabricated. "
            "Keep owner thresholds in plain-English decision_guidance for Jev when no exact inspected "
            "analytical comparison key is available."
        ),
        "private_labels_used": False,
    }
    scenario["private"]["source_contract_fixture_audit"] = copy.deepcopy(audit)
    return audit


def _add_wrong_grain_homonym(scenario: dict) -> str:
    """Add an explicitly evaluation-only, empty same-title/wrong-grain asset."""
    tenant = scenario["scenario_id"]
    resource = "eval-homonym-" + hashlib.sha256(tenant.encode()).hexdigest()[:16]
    ref = f"{SOURCE_ADAPTER}|{resource}"
    description = (
        "Evaluation-only empty homonym stress asset. It is explicitly excluded, "
        "has daily grain, and is not the monthly sales source."
    )
    descriptor = ResourceDescriptor(
        adapter=SOURCE_ADAPTER,
        resource=resource,
        kind="saved_query",
        title=HOMONYM_TITLE,
        description=description,
        metadata={"tenant": tenant, "scope": "evaluation-only; excluded wrong-grain asset",
                  "grain": "day", "excluded": True, "evaluation_only": True,
                  "read_only": True},
        contract=ResourceContract(
            tenant_id=tenant, authorized=True,
            scope="evaluation-only excluded population",
            grain="daily transaction rows; not monthly net sales",
            source_status="healthy",
        ),
    ).model_dump(mode="json")
    scenario["public"]["catalog"].append(descriptor)
    for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
        as_of = _iso(period["as_of"])
        period["snapshots"][ref] = ResourceSnapshot(
            source_key=resource,
            adapter=SOURCE_ADAPTER,
            resource=resource,
            title=HOMONYM_TITLE,
            description=description,
            metadata={"tenant": tenant, "period_id": period["period_id"],
                      "as_of": as_of, "grain": "day", "excluded_scope": True,
                      "evaluation_only": True, "fresh_warehouse_read": False},
            contract=ResourceContract(
                tenant_id=tenant, authorized=True,
                scope="evaluation-only excluded population",
                grain="daily transaction rows; not monthly net sales",
                source_status="healthy",
            ),
            captured_at=as_of,
            source_captured_at=as_of,
        ).model_dump(mode="json")
    scenario["private"]["wrong_grain_homonym_ref"] = ref
    return ref


def _rewrite_showcase_snapshot(snapshot: ResourceSnapshot, *, resource: str,
                               tenant: str, period_id: str, as_of: str) -> dict:
    payload = snapshot.model_dump(mode="json")
    payload.update({
        "adapter": SOURCE_ADAPTER, "resource": resource, "source_key": resource,
        "captured_at": as_of, "source_captured_at": as_of,
        "metadata": {
            **payload.get("metadata", {}),
            "tenant": tenant, "period_id": period_id, "as_of": as_of,
            "replayed_historical_data": True, "fresh_warehouse_read": False,
            "source_capture": (
                "Checked-in Northstar showcase adjustment over local seed rows; "
                "synthetic replay, not a fresh warehouse read."
            ),
        },
    })
    contract = dict(payload.get("contract") or {})
    contract["tenant_id"] = tenant
    payload["contract"] = contract
    for observation in payload.get("observations", []):
        observation["source_key"] = resource
    for evidence in payload.get("evidence", []):
        evidence["source_key"] = resource
        evidence["provenance"] = [resource]
    return ResourceSnapshot.model_validate(payload).model_dump(mode="json")


def _add_showcase_seasonality(scenario: dict, seed_dir: Path) -> str:
    """Materialize the existing seasonal-softness fixture over the local rows."""
    showcase_path = ROOT / "examples" / "northstar-blog-showcase.json"
    showcase = json.loads(showcase_path.read_text(encoding="utf-8"))
    seasonal = next((item for item in showcase["scenarios"]
                     if "season" in str(item.get("id", "")).lower()), None)
    if seasonal is None:
        raise ValueError("The checked-in Northstar seasonal showcase case is missing")
    history = load_northstar_history(NORTHSTAR_HISTORY_SPEC)
    quiet = next(item for item in build_historical_cases(history)
                 if item.variant_id == "day-02-modest-movement")
    replay = ReplayCase(
        case_id=str(seasonal["id"]),
        description=str(seasonal.get("why_it_matters") or seasonal["id"]),
        expected=quiet.historical_outcome,
        adjustments={str(k): float(v) for k, v in seasonal["adjustments"].items()},
        failed_sources=tuple(seasonal.get("failed_sources", [])),
    )
    raw_snapshots = _build_resources(_load_period_data(seed_dir), replay)
    tenant = scenario["scenario_id"]
    base_period = scenario["public"]["periods"][-1]
    as_of = _iso(base_period["as_of"])
    period_id = "period-" + hashlib.sha256(
        f"{showcase['dataset_id']}:{seasonal['id']}".encode()
    ).hexdigest()[:20]
    period = copy.deepcopy(base_period)
    period["period_id"] = period_id
    period["as_of"] = as_of
    refs = {}
    for original in raw_snapshots:
        resource = _source_resource_by_original_ref(scenario, original.source_key)
        refs[original.source_key] = resource
        period["snapshots"][f"{SOURCE_ADAPTER}|{resource}"] = _rewrite_showcase_snapshot(
            original, resource=resource, tenant=tenant, period_id=period_id, as_of=as_of
        )
    label_case = SimpleNamespace(
        case_id=str(seasonal["id"]),
        variant_id=str(seasonal["id"]),
        historical_outcome=quiet.historical_outcome,
        required_explanation_sources=quiet.required_explanation_sources,
    )
    label = _private_label(label_case, refs, period["snapshots"])
    label["showcase_dataset_id"] = showcase["dataset_id"]
    scenario["public"]["periods"].append(period)
    scenario["private"]["periods"][period_id] = label
    scenario["private"].setdefault("fixture_lineage", {})[period_id] = {
        "dataset": showcase["dataset_id"],
        "case_id": seasonal["id"],
        "expected_outcome": seasonal["expected_outcome"],
        "label_visible_to_agent": False,
    }
    return period_id


def _add_multistep_diagnostic_source(scenario: dict) -> tuple[str, str, list[dict]]:
    source_case = next((item for item in build_multistep_cases()
                        if item["scenario"] == "isolated-online-drop-with-checkout-regression"), None)
    if source_case is None:
        raise ValueError("The checked-in Northstar multistep sales-drop case is missing")
    target = next((period for period in scenario["public"]["periods"]
                   if scenario["private"]["periods"][period["period_id"]]["variant_id"]
                   == "day-03-isolated-channel"), None)
    if target is None:
        raise ValueError("Northstar replay has no isolated-channel sales-drop episode")
    tenant = scenario["scenario_id"]
    resource = "eval-diagnostic-" + hashlib.sha256(
        source_case["scenario"].encode()
    ).hexdigest()[:16]
    ref = f"{SOURCE_ADAPTER}|{resource}"
    title = "Northstar Checkout Incident Review"
    description = (
        "Evaluation-only synthetic diagnostic source from the checked-in "
        "Northstar multistep fixture; separate from Superset."
    )
    descriptor = ResourceDescriptor(
        adapter=SOURCE_ADAPTER, resource=resource, kind="saved_query",
        title=title, description=description,
        metadata={"tenant": tenant, "scope": "Northstar payment incident replay",
                  "grain": "incident", "evaluation_only": True, "read_only": True},
        contract=ResourceContract(
            tenant_id=tenant, authorized=True,
            scope="Northstar payment incident replay",
            grain="incident-level facts; not a sales metric",
            source_status="healthy",
        ),
    ).model_dump(mode="json")
    scenario["public"]["catalog"].append(descriptor)
    facts = copy.deepcopy(source_case["diagnostic_facts"])
    for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
        period["snapshots"][ref] = ResourceSnapshot(
            source_key=resource, adapter=SOURCE_ADAPTER, resource=resource,
            title=title, description=description,
            metadata={"tenant": tenant, "period_id": period["period_id"],
                      "as_of": _iso(period["as_of"]), "evaluation_only": True,
                      "replayed_historical_data": True, "fresh_warehouse_read": False},
            contract=ResourceContract(
                tenant_id=tenant, authorized=True,
                scope="Northstar payment incident replay",
                grain="incident-level facts; not a sales metric",
                source_status="healthy",
            ),
            captured_at=_iso(period["as_of"]),
            source_captured_at=_iso(period["as_of"]),
        ).model_dump(mode="json")
    target["snapshots"][ref] = ResourceSnapshot(
        source_key=resource, adapter=SOURCE_ADAPTER, resource=resource,
        title=title, description=description,
        metadata={"tenant": tenant, "period_id": target["period_id"],
                  "as_of": _iso(target["as_of"]), "evaluation_only": True,
                  "replayed_historical_data": True, "fresh_warehouse_read": False},
        contract=ResourceContract(
            tenant_id=tenant, authorized=True,
            scope="Northstar payment incident replay",
            grain="incident-level facts; not a sales metric",
            source_status="healthy",
        ),
        evidence=[Evidence(
            source_key=resource, subject_id=str(item["fact_id"]),
            subject_label="Payment incident diagnostic fact",
            statement=str(item["statement"]), origin="source", provenance=[resource],
        ) for item in facts],
        captured_at=_iso(target["as_of"]),
        source_captured_at=_iso(target["as_of"]),
    ).model_dump(mode="json")
    label = scenario["private"]["periods"][target["period_id"]]
    label["outcome"] = source_case["label"]["expected_final"]
    label["recipients"] = ["leadership"] if label["outcome"] == "notify" else []
    label["required_evidence_refs"] = sorted(set(label["required_evidence_refs"] + [ref]))
    label["required_claim_types"] = []
    label["diagnostic_fact_ids"] = [str(item["fact_id"]) for item in facts]
    label["multistep_expected_initial"] = source_case["label"]["expected_initial"]
    label["multistep_expected_final"] = source_case["label"]["expected_final"]
    scenario["private"].setdefault("multistep", {})[target["period_id"]] = {
        "source_case": source_case["scenario"],
        "expected_initial": source_case["label"]["expected_initial"],
        "expected_final": source_case["label"]["expected_final"],
        "diagnostic_fact_ids": [str(item["fact_id"]) for item in facts],
        "diagnostic_source_ref": ref,
        "diagnostic_facts": facts,
    }
    return target["period_id"], ref, facts


def build_trial_scenario(seed_dir: Path = DEFAULT_SEED) -> dict:
    """Use existing Northstar fixtures plus clearly marked stress assets."""
    scenario = build_northstar(seed_dir)
    _add_wrong_grain_homonym(scenario)
    _add_showcase_seasonality(scenario, seed_dir)
    _add_multistep_diagnostic_source(scenario)
    _ground_source_contracts(scenario, seed_dir)
    scenario["public"]["require_agent_data_signoff"] = True
    return scenario


def _intervention_source_ref(scenario: dict, original_ref: str) -> str:
    resource = _source_resource_by_original_ref(scenario, original_ref)
    return f"{SOURCE_ADAPTER}|{resource}"


def _intervention_percent_facts(period: dict, source_ref: str) -> dict[str, dict[str, Any]]:
    snapshot = period["snapshots"].get(source_ref)
    return _northstar_numeric_facts({source_ref: snapshot}) if snapshot else {}


def classify_policy_intervention_period(scenario: dict, period: dict) -> dict[str, Any]:
    """Apply only the frozen owner policy to source-reported comparisons."""
    sales_ref = _intervention_source_ref(scenario, "superset|dashboard:1")
    sales_snapshot = period["snapshots"].get(sales_ref)
    if (not sales_snapshot or sales_snapshot.get("error")
            or sales_snapshot.get("contract", {}).get("source_status") != "healthy"):
        return {"stratum": "primary_sales_source_unavailable", "outcome": "insufficient_data",
                "source_reported_change_pct": None}
    reconciliation = sales_partition_reconciliation(sales_snapshot)
    if not reconciliation["reconciled"]:
        return {"stratum": "primary_sales_comparison_unreconciled", "outcome": "insufficient_data",
                "source_reported_change_pct": None, "reconciliation": reconciliation}
    sales_facts = _intervention_percent_facts(period, sales_ref)
    total_change = sales_facts.get("net_sales_total_change_pct", {}).get("value")
    if type(total_change) not in {int, float}:
        return {"stratum": "primary_sales_comparison_unavailable", "outcome": "insufficient_data",
                "source_reported_change_pct": None}
    if abs(total_change) < 10:
        return {"stratum": "under_10_ignore", "outcome": "ignore",
                "source_reported_change_pct": total_change}
    channels = (
        "online_net_sales_change_pct", "store_net_sales_change_pct",
        "mobile_net_sales_change_pct", "marketplace_net_sales_change_pct",
    )
    declining_channels = sum(
        type(value) in {int, float} and value < 0
        for value in (sales_facts.get(name, {}).get("value") for name in channels)
    )
    web_ref = _intervention_source_ref(scenario, "northstar|fct_web_session")
    finance_ref = _intervention_source_ref(scenario, "northstar|fct_finance_daily")
    web_pct = _intervention_percent_facts(period, web_ref).get("web_conversion_rate_change_pct", {}).get("value")
    finance_pct = _intervention_percent_facts(period, finance_ref).get("finance_booked_revenue_change_pct", {}).get("value")
    corroboration = any(type(value) in {int, float} and value < 0 for value in (web_pct, finance_pct))
    if total_change <= -15 and declining_channels >= 2 and corroboration:
        stratum, outcome = "corroborated_15_plus_decline_notify", "notify"
    elif total_change < 0 and 10 <= abs(total_change) < 15:
        stratum, outcome = "10_to_below_15_investigate", "investigate"
    else:
        stratum, outcome = "other_material_investigate", "investigate"
    return {"stratum": stratum, "outcome": outcome, "source_reported_change_pct": total_change}


def _policy_intervention_label(scenario: dict, period: dict,
                               classification: dict[str, Any]) -> dict[str, Any]:
    """Build private scoring facts and actions from the frozen policy and repaired inputs."""
    outcome = classification["outcome"]
    facts = _northstar_numeric_facts(period["snapshots"])
    sales_ref = _intervention_source_ref(scenario, "superset|dashboard:1")
    required_refs = [sales_ref]
    if outcome == "notify":
        web_ref = _intervention_source_ref(scenario, "northstar|fct_web_session")
        finance_ref = _intervention_source_ref(scenario, "northstar|fct_finance_daily")
        web_change = facts.get("web_conversion_rate_change_pct", {}).get("value")
        corroborator = web_ref if type(web_change) in {int, float} and web_change < 0 else finance_ref
        required_refs.append(corroborator)
    required_numeric = (
        ["net_sales_total_baseline", "net_sales_total_current", "net_sales_total_change_pct"]
        if classification["source_reported_change_pct"] is not None
        and all(name in facts for name in (
            "net_sales_total_baseline", "net_sales_total_current", "net_sales_total_change_pct",
        )) else []
    )
    recipients = {
        "ignore": [], "investigate": ["analytics"],
        "notify": ["leadership"], "insufficient_data": ["data-trust"],
    }[outcome]
    return {
        "historical_case_id": f"policy-intervention-{period['period_id']}",
        "outcome": outcome,
        "recipients": recipients,
        "required_evidence_refs": required_refs,
        "condition": ("event" if outcome in {"notify", "investigate"}
                      else "data_gap" if outcome == "insufficient_data" else "quiet"),
        "variant_id": f"policy-intervention:{classification['stratum']}",
        "required_owner_topics": ["metric_scope", "materiality", "routing", "data_gaps"],
        "numeric_facts": facts,
        "required_numeric_facts": required_numeric,
        "required_claim_types": [],
        "allowed_claim_types": ["observation", "accounting_decomposition", "association", "hypothesis"],
        "policy_intervention_stratum": classification["stratum"],
    }


def _install_simulation_sales_ledger(scenario: dict) -> None:
    """Materialize fictional ledger records, then derive all sales facts from them.

    Records have month/channel grain, not order or customer grain. The source
    is authoritative only inside this simulation; no real Superset extraction
    or actual business transaction is claimed.
    """
    ref = _intervention_source_ref(scenario, "superset|dashboard:1")
    scope = "The fictional company's generated monthly channel ledger; not a real company or Superset extract."
    descriptor = next(item for item in scenario["public"]["catalog"]
                      if f"{item['adapter']}|{item['resource']}" == ref)
    descriptor["contract"].update(scope=scope, population="Generated monthly channel ledger records.",
                                  grain="One recorded balance per reporting month and sales channel.")
    ledger_ref = "simulation-ledger://northstar/monthly-sales"
    descriptor["contract"]["lineage"] = [ledger_ref]
    for comparison in descriptor["contract"].get("comparison_contracts", []):
        comparison.update(
            definition="Sum recorded net_sales balances by reporting_month across the declared channels.",
            population="Generated monthly channel ledger records; not orders or customers.",
            detail="Totals and channels derive from the same complete fictional monthly ledger partition; no transaction, settlement or real-company coverage is asserted.",
            query_refs=[ledger_ref],
        )
    descriptor["description"] = "Authoritative monthly sales ledger for the fictional company in this trial."
    descriptor["metadata"]["scope"] = scope
    descriptor["source_url"] = "simulation-ledger://northstar/monthly-sales"
    for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]:
        snapshot = period["snapshots"].get(ref)
        if not snapshot:
            continue
        status = snapshot["contract"]["source_status"]
        snapshot["contract"].update(descriptor["contract"], source_status=status)
        snapshot["title"] = descriptor["title"]
        snapshot["description"] = descriptor["description"]
        snapshot["source_url"] = f"simulation-ledger://northstar/{period['period_id']}"
        snapshot["metadata"]["scope"] = scope
        snapshot["metadata"].update(
            source_capture="Generated ledger records are authoritative in this fictional company; not a real business extract.",
            source_transport="simulated_row_ledger",
        )
        if snapshot.get("error"):
            continue
        total = next(item for item in snapshot["observations"] if item["subject_id"] == "revenue-total")
        current_period = total["dimensions"]["current_period"]
        baseline_period = total["attributes"]["baseline_period"]
        channels = [item for item in snapshot["observations"] if item["subject_id"].startswith("channel-")]
        rows = [{"row_id": f"{period['period_id']}/{month}/{item['subject_id']}",
                 "reporting_month": month, "channel": item["dimensions"]["channel"],
                 "net_sales": item[field]}
                for item in channels for month, field in ((baseline_period, "baseline"), (current_period, "current"))]
        if len({row["row_id"] for row in rows}) != len(rows):
            raise ValueError("Simulation ledger contains duplicate record identities")
        source_url = f"simulation-ledger://northstar/{period['period_id']}"
        snapshot["contract"].update(descriptor["contract"])
        snapshot["source_url"] = source_url
        snapshot["metadata"].pop("sales_partition_generation", None)
        snapshot["metadata"].update(
            ledger_rows=rows, ledger_sha256=digest(rows),
            source_capture="Generated ledger records are authoritative in this fictional company; not a real business extract.",
            source_transport="simulated_row_ledger",
        )
        by_subject = {}
        for item in [total, *channels]:
            selected = rows if item is total else [row for row in rows if row["channel"] == item["dimensions"]["channel"]]
            item["baseline"] = sum(row["net_sales"] for row in selected if row["reporting_month"] == baseline_period)
            item["current"] = sum(row["net_sales"] for row in selected if row["reporting_month"] == current_period)
            item["previous"] = item["baseline"]
            item["change_pct"] = round((item["current"] - item["baseline"]) / abs(item["baseline"]) * 100, 3) if item["baseline"] else None
            item["source_url"] = source_url
            item["attributes"].pop("fixture_allocation", None)
            item["attributes"].update(data_origin="Authoritative fictional-company monthly ledger records.",
                                      ledger_row_ids=[row["row_id"] for row in selected])
            by_subject[item["subject_id"]] = item
        snapshot["evidence"] = [Evidence(
            source_key=snapshot["source_key"], subject_id=item["subject_id"],
            subject_label=item["subject_label"], source_url=source_url,
            statement=f"{item['subject_label']}: {baseline_period} {item['baseline']} to {current_period} {item['current']}; generated ledger-derived change {item['change_pct']}%.",
            values={"current": item["current"], "baseline": item["baseline"],
                    "previous": item["previous"], "change_pct": item["change_pct"],
                    "data_origin": item["attributes"]["data_origin"],
                    "ledger_row_ids": item["attributes"]["ledger_row_ids"]},
            origin="source", provenance=[row["row_id"] for row in rows],
        ).model_dump(mode="json") for item in by_subject.values()]
    scenario["public"]["owner_answers"]["metric_scope"] = scope


def build_policy_intervention_scenario(seed_dir: Path = DEFAULT_SEED) -> tuple[dict, dict[str, Any]]:
    """Freeze a separate, owner-policy-conditioned cohort before model exposure."""
    scenario = build_trial_scenario(seed_dir)
    _install_simulation_sales_ledger(scenario)
    public = scenario["public"]
    excluded = {f"{item['adapter']}|{item['resource']}" for item in public["catalog"]
                if item.get("title") == "Northstar Checkout Incident Review"}
    public["catalog"] = [
        item for item in public["catalog"]
        if item.get("title") != "Northstar Checkout Incident Review"
    ]
    for period in [public["onboarding"], *public["periods"]]:
        for ref in excluded:
            period["snapshots"].pop(ref, None)
    public["owner_answers"].update(copy.deepcopy(NORTHSTAR_POLICY_INTERVENTION["owner_answers"]))
    public["owner_answers"]["metric_scope"] = (
        "Executive Pulse's generated monthly channel ledger is the authoritative sales source "
        "in this fictional company. Total and per-channel balances are derived from the same "
        "recorded rows. It is not a real-company extract, and does not establish individual "
        "orders, customers, settlement, or company-wide coverage. Web, Finance and Support "
        "are separate simulated populations; no row joins or shared-cohort assertion."
    )
    public["owner_topics"] = list(dict.fromkeys([
        *public["owner_topics"], *NORTHSTAR_POLICY_INTERVENTION["owner_answers"],
    ]))
    public["source_transport"] = {
        "kind": "simulated_bi_fixture",
        "actual_superset": False,
        "description": (
            "Private local MCP replay of generated monthly sales ledger balances and "
            "synthetic Web, Finance and Support snapshots; no live Superset extraction."
        ),
    }
    public["brief"] += (
        " The owner has pre-answered one-time business-policy questions. Keep Sales, Web, "
        "Finance, and Support populations separate; no row joins. Owner policy and acting "
        "data-expert source sign-off are distinct: during approval pass source_scope_confirmations "
        "for exactly the selected refs, copying declared scope text from the current review. "
        f"{NORTHSTAR_POLICY_INTERVENTION['recurring_questions_guidance']} Preserve thresholds "
        "in English decision_guidance; do not invent comparison keys or numeric conditions. "
        f"{NORTHSTAR_POLICY_INTERVENTION['source_selection_reason']}"
    )
    scenario["policy_intervention"] = copy.deepcopy(NORTHSTAR_POLICY_INTERVENTION)
    scenario["policy_intervention"]["owner_answers"]["metric_scope"] = public["owner_answers"]["metric_scope"]
    periods = {period["period_id"]: period for period in scenario["public"]["periods"]}
    selected, strata = [], {}
    new_labels = {}
    for stratum, period_id in POLICY_INTERVENTION_CASES.items():
        period = periods.get(period_id)
        if period is None:
            raise ValueError(f"Preregistered policy-intervention episode is missing: {period_id}")
        expected = classify_policy_intervention_period(scenario, period)
        if expected["stratum"] != stratum:
            raise ValueError(f"Reconciled replay does not meet preregistered stratum {stratum}: {period_id}")
        label = _policy_intervention_label(scenario, period, expected)
        if label["outcome"] != expected["outcome"]:
            raise ValueError(f"Policy label derivation disagrees with frozen policy for {period_id}")
        selected.append(period)
        new_labels[period_id] = label
        sales_snapshot = period["snapshots"][_intervention_source_ref(
            scenario, "superset|dashboard:1",
        )]
        sales_reconciliation = (
            {"status": "not_applicable", "reason": "Primary sales source unavailable."}
            if sales_snapshot.get("error")
            or sales_snapshot.get("contract", {}).get("source_status") != "healthy"
            else {"status": "checked", **sales_partition_reconciliation(sales_snapshot)}
        )
        strata[stratum] = {
            "period_id": period_id,
            "policy_outcome": expected["outcome"],
            "source_reported_change_pct": expected["source_reported_change_pct"],
            "sales_reconciliation": sales_reconciliation,
        }
    if len(selected) != PILOT_SIZE or len({p["period_id"] for p in selected}) != PILOT_SIZE:
        raise ValueError("Policy intervention requires exactly four episodes")
    selected_ids = {item["period_id"] for item in selected}
    scenario["public"]["periods"] = copy.deepcopy(selected)
    scenario["private"]["periods"] = new_labels
    scenario["private"]["multistep"] = {key: value for key, value
        in scenario["private"].get("multistep", {}).items() if key in selected_ids}
    registration = {
        "protocol": POLICY_INTERVENTION_PROTOCOL,
        "cohort_label": (
            f"{POLICY_INTERVENTION_PROTOCOL}: four-case row-backed fictional-company pilot; "
            "prior cohort invalid and excluded."
        ),
        "intervention": copy.deepcopy(scenario["policy_intervention"]),
        "sales_partition_rule": (
            "For a healthy primary source, require exactly one total, a nonempty unique channel "
            "partition, numeric values, identical comparison periods, and baseline/current sums "
            "matching the total within 1e-6 arithmetic precision. Any mismatch is insufficient_data "
            "to data-trust. A failed primary source is not reconciled and must expose no observations. "
            "The generated monthly ledger rows are authoritative within the fictional company. "
            "Both totals and channels are computed from those records; no real-business extract is claimed."
        ),
        "case_selection": (
            "Fixed preregistered period IDs; repaired source facts were validated and the "
            "owner-policy outcome labels were recomputed before any model exposure."
        ),
        "selected_strata": strata,
        "expected_outcomes_by_stratum": {
            stratum: item["policy_outcome"] for stratum, item in strata.items()
        },
        "synthetic_fixture_rows_generated": True,
        "manufactured_business_truth_scope": (
            "No legacy outcome label was consulted. Owner policy and ledger source contracts "
            "are explicitly authored simulation inputs, not inferred real business knowledge. "
            "No cross-source population equivalence is claimed. Fixture numbers are synthetic, "
            "not asserted business facts."
        ),
        "selection_completed_before_future_values_exposed": True,
        "legacy_oracle_used_for_selection_or_scoring": False,
        "legacy_artifacts_preserved_as_invalid": True,
        "source_transport": copy.deepcopy(public["source_transport"]),
        "generalization_limit": (
            "Four synthetic, policy-derived cases test workflow behavior; they are not an "
            "independent business-accuracy estimate."
        ),
    }
    scenario["policy_intervention_registration"] = registration
    return scenario, registration


def apply_simulated_hil_followup(scenario: dict) -> dict:
    """Expose predeclared owner knowledge through the existing ask_owner tool.

    The response answers the actual incident-definition follow-up by saying it
    is unknown in the predeclared business materials. It does not alter policy,
    source contracts, outcome labels, or add a numeric threshold. The answer is
    available only through the shared trial MCP owner-lookup tool.
    """
    answers = scenario["public"]["owner_answers"]
    topic = "severe_incident_definition"
    knowledge = scenario.get("owner_followup_knowledge", {}).get(topic)
    if (not isinstance(knowledge, dict)
            or knowledge != OWNER_FOLLOWUP_KNOWLEDGE.get(topic)
            or knowledge.get("status") != "unknown"):
        raise ValueError("Northstar's independently predeclared incident answer is required")
    answer = knowledge.get("answer")
    if not isinstance(answer, str) or not answer.startswith("Unknown."):
        raise ValueError("The incident-definition follow-up must preserve unknown status")
    if not {"metric_scope", "materiality"} <= set(answers):
        raise ValueError("Northstar base owner answers are required before HIL follow-up")

    if topic in answers and answers[topic] != answer:
        raise ValueError("Conflicting Northstar owner follow-up answer is already present")
    answers[topic] = answer
    if topic not in scenario["public"]["owner_topics"]:
        scenario["public"]["owner_topics"].append(topic)
    return {
        "mode": "simulated_owner_followup_on_demand",
        "evaluation_only": True,
        "shared_with_both_arms": True,
        "transport": "existing trial MCP facade",
        "tool": "ask_owner",
        "topic": topic,
        "response_status": "unknown",
        "response": answer,
        "predeclared_knowledge_basis": copy.deepcopy(knowledge["basis"]),
        "delivered_only_when_requested": True,
        "policy_changed": False,
        "source_contracts_changed": False,
        "outcome_labels_changed": False,
        "new_numeric_thresholds": [],
    }


def select_recurring_periods(scenario: dict, *, cohort: str) -> list[dict]:
    """Select four diverse pilot episodes or a 24+ episode release cohort."""
    if cohort not in {"pilot", "full"}:
        raise ValueError("cohort must be pilot or full")
    periods = scenario["public"]["periods"]
    labels = scenario["private"]["periods"]
    if cohort == "pilot":
        desired = (
            "ordinary-seasonal-softness",
            "day-03-isolated-channel",
            "day-04-corroborated-decline",
            "day-06-source-unavailable",
        )
        selected = []
        for variant in desired:
            period = next((item for item in periods
                           if labels[item["period_id"]]["variant_id"] == variant), None)
            if period is None:
                raise ValueError(f"Pilot fixture is missing required case family: {variant}")
            selected.append(period)
        if len({item["period_id"] for item in selected}) != PILOT_SIZE:
            raise ValueError("Pilot episodes must be distinct")
        return selected
    base = [period for period in periods
            if labels[period["period_id"]]["variant_id"].startswith("day-")]
    dates = sorted({period["as_of"] for period in base})
    selected = [period for period in base if period["as_of"] in set(dates[:4])]
    if len(selected) != FULL_BASE_SIZE:
        raise ValueError(f"Balanced base cohort must contain {FULL_BASE_SIZE} episodes")
    seasonal = next(period for period in periods
                    if labels[period["period_id"]]["variant_id"] == "ordinary-seasonal-softness")
    selected.append(seasonal)
    if len({item["period_id"] for item in selected}) != len(selected):
        raise ValueError("Release cohort episodes must be distinct")
    return selected


def _public_only_scenario(scenario: dict, selected: list[dict]) -> dict:
    public = public_scenario(scenario)
    public["periods"] = copy.deepcopy(selected)
    return public


def _agent_visible_payload(session: ToolSession, *, period: dict | None = None) -> dict:
    payload = {"phase": session.phase, "business": session.public,
               "saved_notes": session.notes, "shared_card": session.shared_card}
    if period is not None:
        payload["period"] = session.adapter.period_context
    return payload


def assert_agent_profile(tool_names: set[str] | list[str]) -> None:
    names = set(tool_names)
    if names != set(AGENT_PROFILE_TOOLS):
        raise ValueError("Installed MCP is not the exact default agent profile")
    if names & FORBIDDEN_FULL_TOOLS:
        raise ValueError("Advanced/full-only tools appeared in the default agent profile")


def assert_transport_model_override(transport=codex_episode) -> None:
    parameters = inspect.signature(transport).parameters
    if "model" not in parameters or "effort" not in parameters:
        raise ValueError("Codex trial transport must accept explicit model and effort overrides")


def _verify_certified_binary(binary: Path, *, certified_source_sha256: str,
                             certified_binary_sha256: str) -> dict:
    for name, value in (("source", certified_source_sha256),
                        ("binary", certified_binary_sha256)):
        if not re.fullmatch(r"[0-9a-f]{64}", value or ""):
            raise ValueError(f"A certified {name} SHA256 is required before live setup")
    result = verify_binary(binary)
    if result["source_sha256"] != certified_source_sha256:
        raise ValueError("Verified source fingerprint does not match parent certification")
    if result["binary_sha256"] != certified_binary_sha256:
        raise ValueError("Verified binary SHA256 does not match parent certification")
    if result["version"] != CERTIFIED_VERSION:
        raise ValueError("Verified binary version does not match parent certification")
    return result


def _assert_no_private_labels(payload: Any, private: dict) -> None:
    encoded = canonical(payload)
    labels = {
        str(value)
        for label in private.get("periods", {}).values()
        for value in (label.get("historical_case_id", ""), label.get("variant_id", ""))
        if value
    }
    if any(label in encoded for label in labels):
        raise ValueError("A private future case label entered a model-visible payload")


def _message_checks(submission: dict, label: dict, *, wrong_ref: str,
                    multistep: dict | None) -> dict:
    summary = str(submission.get("summary") or "").strip()
    words = re.findall(r"\b[\w%$.-]+\b", summary)
    normalized = summary.casefold()
    unknown_markers = ("unknown", "not known", "unavailable", "conflict", "lag",
                       "cannot confirm", "cannot reconcile", "needs review", "verify")
    unknowns_acknowledged = (
        label.get("condition") != "data_gap"
        or any(marker in normalized for marker in unknown_markers)
    )
    action = submission.get("outcome") in {"notify", "investigate"}
    next_step = any(marker in normalized for marker in (
        "next", "investigate", "review", "repair", "check", "confirm", "owner", "monitor",
    ))
    causal_language = any(marker in normalized for marker in (
        "caused by", "caused the", "due to", "resulted from", "because of",
    ))
    causal_supported = bool(multistep and multistep.get("expected_final") == "notify")
    return {
        "recipient_message": summary,
        "word_count": len(words),
        "concise_10_to_80_words": 10 <= len(words) <= 80,
        "action_has_next_step": (not action) or next_step,
        "source_scope_cited": bool(submission.get("evidence_refs")),
        "unknowns_or_conflicts_acknowledged": unknowns_acknowledged,
        "wrong_grain_source_cited": wrong_ref in set(submission.get("evidence_refs", [])),
        "causal_language_present": causal_language,
        "causal_language_has_multistep_support": (not causal_language) or causal_supported,
        "message_is_proposed_only": True,
        "delivery_enabled": False,
    }


def _replace_tenant(value: Any, previous: str, current: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"tenant", "tenant_id"} and item == previous:
                value[key] = current
            else:
                _replace_tenant(item, previous, current)
    elif isinstance(value, list):
        for item in value:
            _replace_tenant(item, previous, current)


def build_report_first_scenario(scenario: dict) -> tuple[dict, dict]:
    """Create a one-period vague-owner probe with unresolved alert ownership.

    This keeps the checked-in Northstar observations and removes only
    materiality/routing. It is not a fresh warehouse read.
    """
    result = copy.deepcopy(scenario)
    if "simulated_hil_followup" not in result["private"]:
        apply_simulated_hil_followup(result)
    previous = result["scenario_id"]
    tenant = f"{previous}-report-first"
    result["scenario_id"] = tenant
    _replace_tenant(result["public"], previous, tenant)
    result["public"]["brief"] = (
        "Why did sales/customer health change? Give me a useful, scope-qualified "
        "current read first. Then ask only for missing materiality, alert owner, "
        "or routing context before setting up a recurring alert."
    )
    result["public"]["owner_answers"].pop("materiality", None)
    result["public"]["owner_answers"].pop("routing", None)
    period = next(
        (item for item in result["public"]["periods"]
         if result["private"]["periods"][item["period_id"]]["variant_id"]
         == "day-03-isolated-channel"),
        None,
    )
    if period is None:
        raise ValueError("Report-first Northstar source period is missing")
    result["public"]["periods"] = [copy.deepcopy(period)]
    result["public"]["report_first_probe"] = True
    private_label = copy.deepcopy(result["private"]["periods"][period["period_id"]])
    result["private"]["periods"] = {period["period_id"]: private_label}
    result["private"]["report_first_expected_unknown_topics"] = ["materiality", "routing"]
    return result, private_label


def score_report_first(submission: dict, *, period: dict, inspected_refs: set[str],
                       asked_topics: set[str], expected_unknown_topics: set[str]) -> dict:
    """Score useful current analysis without inventing an alert policy label."""
    try:
        parsed = _Submission.model_validate(submission).model_dump(mode="json")
    except Exception:
        return {"valid_submission": False, "useful_report": False,
                "errors": ["invalid_submission_schema"]}
    truth = _northstar_numeric_facts(period["snapshots"])
    refs = set(parsed["evidence_refs"])
    cited = refs | {ref for claim in parsed["numeric_claims"] for ref in claim["evidence_refs"]}
    cited |= {ref for claim in parsed["claims"] for ref in claim["evidence_refs"]}
    numeric_checks = []
    for claim in parsed["numeric_claims"]:
        expected = truth.get(claim["fact"])
        ok = bool(
            expected
            and claim["unit"] == expected["unit"]
            and type(claim["value"]) in {int, float}
            and abs(claim["value"] - expected["value"])
            <= expected["absolute_tolerance"]
            and set(claim["evidence_refs"]) >= set(expected["evidence_refs"])
        )
        numeric_checks.append({"fact": claim["fact"], "correct": ok})
    summary = parsed["summary"].strip()
    words = re.findall(r"\b[\w%$.-]+\b", summary)
    narrative = " ".join([summary, *(claim["statement"] for claim in parsed["claims"])])
    lowered = narrative.casefold()
    period_text = canonical(period)
    source_text = period_text.casefold()
    expected_data_refs = set(period["snapshots"])
    source_scope = bool(cited) and cited <= inspected_refs and cited <= expected_data_refs
    source_complete = bool(inspected_refs) and refs <= inspected_refs
    scope_qualified = (
        "northstar" in lowered
        and any(term in lowered for term in ("monthly", "calendar month", "month of "))
    )
    replay_caveat = any(term in lowered for term in ("historical", "replay", "not a fresh", "not live"))
    driver_terms = (
        "web", "online", "shop", "store", "conversion", "refund", "support", "finance", "channel",
    )
    driver_named = any(term in lowered and term in source_text for term in driver_terms)
    action_markers = (
        "ask", "confirm", "investigate", "analytics", "owner", "materiality",
        "threshold", "route", "review", "next",
    )
    recipient_action = any(term in lowered for term in action_markers)
    only_missing_context_asked = asked_topics <= expected_unknown_topics
    all_missing_context_asked = expected_unknown_topics <= asked_topics
    no_invented_threshold = not bool(re.search(
        r"\b(?:at least|threshold of|alert at)\s+\d+(?:\.\d+)?\s*%", lowered
    ))
    result = {
        "valid_submission": True,
        "numeric_claims": numeric_checks,
        "numeric_accuracy": bool(numeric_checks) and all(item["correct"] for item in numeric_checks),
        "all_citations_inspected_and_in_period": source_scope,
        "current_source_was_inspected": source_complete,
        "scope_qualified": scope_qualified,
        "historical_replay_caveat_present": replay_caveat,
        "likely_driver_named": driver_named,
        "recipient_action_named": recipient_action,
        "concise_10_to_80_words": 10 <= len(words) <= 80,
        "owner_questions_only_for_missing_topics": only_missing_context_asked,
        "all_missing_topics_asked": all_missing_context_asked,
        "no_threshold_invented": no_invented_threshold,
        "unresolved_topics": sorted(expected_unknown_topics - asked_topics),
        "outcome_not_scored_without_alert_policy": True,
        "delivery_enabled": False,
        "useful_report": bool(numeric_checks) and all(item["correct"] for item in numeric_checks)
        and source_scope and source_complete and scope_qualified and replay_caveat
        and driver_named and recipient_action and 10 <= len(words) <= 80
        and no_invented_threshold,
        "word_count": len(words),
        "recipient_message": summary,
        "source_evidence_period_digest": digest(period_text),
    }
    return result


def score_final_report_utility(submission: dict | None, *, period: dict,
                               inspected_refs: set[str]) -> dict[str, Any]:
    """Score source-grounded usefulness of the final recipient-facing report.

    This is a report-quality proxy, not a Jev or outcome-label score. Missing or
    invalid reports score zero and are distinguished in the returned status.
    """
    if submission is None:
        return {"status": "missing", "valid": False, "score": 0,
                "dimensions": {}, "narrative_review_required": True}
    try:
        parsed = _Submission.model_validate(submission).model_dump(mode="json")
    except Exception:
        return {"status": "invalid", "valid": False, "score": 0,
                "dimensions": {}, "narrative_review_required": True}

    period_refs = set(period["snapshots"])
    inspected = set(inspected_refs) & period_refs
    cited = set(parsed["evidence_refs"])
    cited |= {ref for item in parsed["numeric_claims"] for ref in item["evidence_refs"]}
    cited |= {ref for item in parsed["claims"] for ref in item["evidence_refs"]}
    evidence_fidelity = bool(cited) and cited <= inspected and cited <= period_refs

    source_facts = _northstar_numeric_facts(period["snapshots"])
    required_numeric = {
        f"net_sales_total_{field}"
        for field in ("baseline", "current", "change_pct")
        if f"net_sales_total_{field}" in source_facts
    }
    correct_numeric: set[str] = set()
    for claim in parsed["numeric_claims"]:
        fact = source_facts.get(claim["fact"])
        if (fact and claim["unit"] == fact["unit"]
                and type(claim["value"]) in {int, float}
                and abs(claim["value"] - fact["value"]) <= fact["absolute_tolerance"]
                and set(claim["evidence_refs"]) >= set(fact["evidence_refs"])):
            correct_numeric.add(claim["fact"])
    numeric_precision = (
        len(correct_numeric) / len(parsed["numeric_claims"])
        if parsed["numeric_claims"] else (1.0 if not required_numeric else 0.0)
    )
    numeric_recall = (
        len(correct_numeric & required_numeric) / len(required_numeric)
        if required_numeric else 1.0
    )

    narrative = " ".join([
        parsed["summary"], *(item["statement"] for item in parsed["claims"]),
    ]).casefold()
    source_text = canonical(period["snapshots"]).casefold()
    words = re.findall(r"\b[\w%$.-]+\b", parsed["summary"])
    scope_qualified = "northstar" in narrative and any(
        term in narrative for term in ("monthly", "calendar month")
    )
    replay_caveat = any(
        term in narrative for term in ("historical", "replay", "not live", "not a fresh")
    )
    driver_terms = (
        "online", "store", "mobile", "marketplace", "web", "conversion",
        "support", "finance", "channel", "checkout",
    )
    source_grounded_driver = any(
        term in narrative and term in source_text for term in driver_terms
    )
    action_terms = ("ask", "confirm", "investigate", "review", "route", "owner", "next step")
    concrete_next_step = any(term in narrative for term in action_terms)
    concise = 10 <= len(words) <= 80
    dimensions = {
        "evidence_fidelity": 25 if evidence_fidelity else 0,
        "numeric_fidelity": round(25 * (numeric_precision + numeric_recall) / 2, 2),
        "scope_qualification": 7.5 if scope_qualified else 0,
        "historical_replay_caveat": 7.5 if replay_caveat else 0,
        "source_grounded_driver": 10 if source_grounded_driver else 0,
        "concrete_next_step": 10 if concrete_next_step else 0,
        "conciseness": 5 if concise else 0,
    }
    rubric_max_points = 90
    return {
        "status": "valid",
        "valid": True,
        "score": round(100 * sum(dimensions.values()) / rubric_max_points, 2),
        "rubric_points": round(sum(dimensions.values()), 2),
        "rubric_max_points": rubric_max_points,
        "dimensions": dimensions,
        "evidence_fidelity": evidence_fidelity,
        "numeric_precision": numeric_precision,
        "numeric_recall": numeric_recall,
        "required_source_numeric_facts": sorted(required_numeric),
        "correct_source_numeric_facts": sorted(correct_numeric),
        "narrative_review_required": True,
        "rubric_limit": (
            "Rule-based final-report utility proxy; narrative entailment and real-user value "
            "were not independently human-reviewed. Outcome and routing correctness are "
            "reported separately as secondary diagnostics."
        ),
    }


def add_final_report_utility(report: dict[str, Any], scenario: dict) -> dict[str, Any]:
    """Attach paired final-report utility and separate invalid/missing counts."""
    periods = {item["period_id"]: item for item in scenario["public"]["periods"]}
    rows = report.get("companies", [{}])[0].get("periods", [])
    pair_scores: list[float] = []
    eligible_pair_scores: list[float] = []
    by_arm: dict[str, list[float]] = {"baseline": [], "treatment": []}
    counts = {
        arm: {"valid": 0, "invalid": 0, "missing": 0}
        for arm in ("baseline", "treatment")
    }
    for row in rows:
        period = periods.get(row.get("period_id"))
        if period is None:
            continue
        scored_arms = {}
        for arm in ("baseline", "treatment"):
            arm_result = row.get(arm) or {}
            utility = score_final_report_utility(
                arm_result.get("submission"), period=period,
                inspected_refs=set(arm_result.get("visible_refs", [])),
            )
            scored_arms[arm] = utility
            counts[arm][utility["status"]] += 1
            by_arm[arm].append(float(utility["score"]))
        row["final_report_utility"] = scored_arms
        pair_scores.append(
            float(scored_arms["treatment"]["score"])
            - float(scored_arms["baseline"]["score"])
        )
        # A treatment without a successful native decision is an agent fallback,
        # not evidence for Jev. Harness-censored baseline runs are not valid pairs.
        eligible = bool(
            row.get("result") and not row.get("native_evaluation_error")
            and all((row.get(arm) or {}).get("completed")
                    and scored_arms[arm]["valid"] for arm in ("baseline", "treatment"))
        )
        row["final_report_utility"]["comparison_eligible"] = eligible
        if eligible:
            eligible_pair_scores.append(pair_scores[-1])

    intended_per_arm = len(scenario["public"]["periods"])
    utility_summary = {
        "primary_endpoint": "final_human_report_utility_proxy",
        "scale": "0-100; invalid and missing reports score 0 and remain in the denominator",
        "intended_reports_per_arm": intended_per_arm,
        "baseline_mean": round(sum(by_arm["baseline"]) / max(1, intended_per_arm), 2),
        "treatment_mean": round(sum(by_arm["treatment"]) / max(1, intended_per_arm), 2),
        "paired_treatment_minus_baseline_mean": round(
            sum(pair_scores) / max(1, intended_per_arm), 2
        ),
        "report_counts": counts,
        "paired_rows_scored": len(pair_scores),
        "eligible_live_decision_pairs": len(eligible_pair_scores),
        "eligible_pair_utility_difference_mean": (
            round(sum(eligible_pair_scores) / len(eligible_pair_scores), 2)
            if eligible_pair_scores else None
        ),
        "comparison_limit": "Failure-inclusive means describe completion; only complete pairs with a successful native decision enter the live-decision comparison. This proxy is not a human preference score.",
        "narrative_review_required": True,
        "outcome_correctness_role": "secondary diagnostic; policy-label exactness is not the primary endpoint",
    }
    report.setdefault("summary", {})["final_report_utility"] = utility_summary
    report.setdefault("protocol", {})["primary_endpoint"] = utility_summary["primary_endpoint"]
    report["protocol"]["comparison"] = "paired_final_report_utility_with_secondary_outcome_diagnostics"
    return utility_summary


class ReleaseSession(ToolSession):
    """Default-profile agent bridge for report-first and paired episodes."""

    SHARED_SOURCE_TOOLS = frozenset({"search_catalog", "inspect_resource"})
    ONBOARDING_AGENT_TOOLS = frozenset({
        "get_signalweave_guide", "onboard_insight_card", "review_insight_card",
        "get_insight_card", "list_insight_cards", "approve_insight_card",
    })

    def __init__(self, *args, report_first: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.report_first = report_first
        self.report_only = False
        self.agent_inspected: set[str] = set()
        self.unknown_owner_topics: set[str] = set()
        self.owner_responses: list[dict] = []
        self.pending_policy_topics = {
            topic for topic in ("materiality", "routing")
            if topic not in self.owner["owner_answers"]
        } if report_first else set()
        self.setup_state = "not_started"
        self.onboarding_card: dict | None = None
        self.onboarding_review: dict | None = None
        self.reviewed_card_ids: set[str] = set()
        self.approved_card_ids: set[str] = set()

    async def specs(self) -> list[dict]:
        server_tools = await self.server.list_tools()
        names = {tool.name for tool in server_tools}
        assert_agent_profile(names)
        selected = []
        by_name = {tool.name: tool for tool in server_tools}
        for name in sorted(self.SHARED_SOURCE_TOOLS):
            tool = by_name.get(name)
            if tool is None:
                raise ValueError(f"Default agent profile lacks shared source tool {name}")
            selected.append({"type": "function", "name": tool.name,
                             "description": tool.description,
                             "parameters": tool.inputSchema, "strict": False})

        phase_tools = common_tools(
            {**self.public, "require_agent_data_signoff": True}, self.phase
        )
        shared_phase_names = {"ask_owner", "submit_analysis"}
        if self.phase == "onboarding":
            shared_phase_names |= {"save_notes", "sign_off_data_foundation"}
        selected.extend(spec for spec in phase_tools
                        if spec["name"] in shared_phase_names)
        if self.phase == "onboarding":
            selected.append(function(
                "finish_setup",
                "Close this isolated onboarding step. If materiality or routing remains unknown, "
                "record the policy as pending; do not claim approval or unattended delivery.",
                {"card_id": {"type": ["string", "null"]}},
            ))

        if (self.treatment and self.phase == "onboarding" and not self.report_only):
            for name in sorted(self.ONBOARDING_AGENT_TOOLS):
                tool = by_name.get(name)
                if tool is None:
                    raise ValueError(f"Default agent profile lacks onboarding tool {name}")
                selected.append({"type": "function", "name": tool.name,
                                 "description": tool.description,
                                 "parameters": tool.inputSchema, "strict": False})
        unique = {spec["name"]: spec for spec in selected}
        return list(unique.values())

    async def call(self, name: str, arguments: dict) -> Any:
        if name in self.SHARED_SOURCE_TOOLS:
            result = await self.product(name, arguments)
            if name == "inspect_resource":
                adapter = str(arguments["adapter"])
                resource = str(arguments["resource"])
                ref = f"{adapter}|{resource}"
                self.agent_inspected.add(ref)
            return result
        if name == "ask_owner":
            self.owner_topics.add(arguments["topic"])
            self.phase_owner_topics.add(arguments["topic"])
            result = ask_owner(self.owner, arguments["topic"])
            self.owner_responses.append(copy.deepcopy(result))
            if result.get("known") is False:
                self.unknown_owner_topics.add(str(arguments["topic"]))
            return result
        if name == "sign_off_data_foundation":
            return await super().call(name, arguments)
        if name == "save_notes":
            return await super().call(name, arguments)
        if name == "submit_analysis":
            return await super().call(name, arguments)
        if name == "finish_setup" and self.phase == "onboarding":
            if not self.notes or not self.adapter.inspected or not self.owner_topics:
                raise ValueError("Inspect sources, ask the owner, and save reusable notes first")
            if not self.data_signoff or self.data_signoff.get("status") != "ready":
                raise ValueError("Record data-expert signoff from inspected source refs first")
            if self.report_first and self.pending_policy_topics:
                if self.treatment:
                    card_id = self.onboarding_card.get("id") if self.onboarding_card else None
                    if not card_id or card_id not in self.reviewed_card_ids:
                        raise ValueError("Save and review the recurring-card draft before marking it pending")
                    if card_id in self.approved_card_ids:
                        raise ValueError("A card with unresolved owner policy must not be approved")
                elif not self.shared_card:
                    raise ValueError("The baseline must receive the same reviewed draft card")
                self.setup_state = "needs_human_clarification"
                self.setup_complete = True  # transport completion, not setup approval
                return {"trial_step_complete": True,
                        "state": "needs_human_clarification",
                        "unresolved_owner_topics": sorted(self.pending_policy_topics),
                        "automation_approved": False, "delivery_enabled": False}
            if self.treatment:
                card_id = arguments.get("card_id")
                if not card_id or card_id not in self.approved_card_ids:
                    raise ValueError("A reviewed, explicitly approved card is required")
                self.card_id = card_id
            else:
                card_id = self.shared_card.get("id") if self.shared_card else None
                if not card_id or arguments.get("card_id") not in {None, card_id}:
                    raise ValueError("Baseline must use the identical shared card snapshot")
                self.card_id = card_id
            self.setup_complete = True
            self.setup_state = "ready_for_shadow_only"
            return {"trial_step_complete": True, "state": self.setup_state,
                    "automation_approved": self.treatment,
                    "delivery_enabled": False, "card_id": self.card_id}

        if name == "onboard_insight_card" and self.treatment:
            result = await self.product(name, arguments)
            self.onboarding_card = copy.deepcopy(result.get("card"))
            return result
        if name == "review_insight_card" and self.treatment:
            result = await self.product(name, arguments)
            card = result.get("card") or {}
            card_id = str(arguments.get("card_id") or card.get("id") or "")
            if card_id:
                self.reviewed_card_ids.add(card_id)
                self.onboarding_card = copy.deepcopy(card or self.onboarding_card)
            self.onboarding_review = copy.deepcopy(result.get("review") or {})
            return result
        if name == "get_insight_card" and self.treatment:
            return await self.product(name, arguments)
        if name == "list_insight_cards" and self.treatment:
            return await self.product(name, arguments)
        if name == "get_signalweave_guide" and self.treatment:
            return await self.product(name, arguments)
        if name == "approve_insight_card" and self.treatment:
            card_id = str(arguments.get("card_id") or "")
            if self.report_first and self.pending_policy_topics:
                raise ValueError(
                    "Do not approve or enable automation while owner materiality/routing is unresolved; "
                    "the current agent report is still allowed."
                )
            if card_id not in self.reviewed_card_ids:
                raise ValueError("Review the current draft card before approval")
            if not self.data_signoff or self.data_signoff.get("status") != "ready":
                raise ValueError("Data-expert signoff is required before approval")
            result = await self.product(name, arguments)
            self.approved_card_ids.add(card_id)
            return result
        return await super().call(name, arguments)


def report_first_instructions(*, server_instructions: str, arm: str,
                              phase: str, pending_topics: set[str]) -> str:
    shared = (
        "You are Luna 6 xhigh in a read-only Northstar evaluation. Report useful "
        "current facts and likely drivers before deciding whether an alert can be "
        "automated. The source is a local synthetic MCP replay of checked-in data, "
        "not a fresh Superset extraction. Give a short 10-80 word recipient-ready "
        "message: facts, likely driver(s), scope/caveat, and next action. Cite every "
        "numeric fact with exact source refs. Do not state causal attribution without "
        "multi-step evidence. No notifications are sent. Ask only missing owner-policy "
        "topics; known source gaps must be named rather than treated as success."
    )
    if phase == "report":
        return shared + (
            " First inspect appropriate sources, then submit the useful current report. "
            "An unknown alert threshold or recipient must not prevent that report. "
            "Do not create or approve a recurring card in this report step."
        )
    if arm == "treatment":
        return shared + (
            " Continue first-use onboarding through the installed default 'agent' MCP "
            "profile only: read get_signalweave_guide, search and inspect exact source "
            "refs, ask the owner only for missing materiality/routing, record data-expert "
            "signoff from inspected refs, save concise reusable notes, create and review "
            "a recurring-card draft. If materiality or routing remains unknown, leave the "
            "card pending, do not approve it, and finish the trial step as "
            "needs_human_clarification."
        ) + "\nInstalled default-agent instructions:\n" + server_instructions
    return shared + (
        " This is the paired baseline with the same source tools, owner responses, and "
        "the identical reviewed card snapshot, but no SignalWeave tools. Inspect the card "
        "and sources, save concise reusable notes, sign off the data facts, and record the "
        "same unresolved owner-policy topics. Do not claim card approval or delivery readiness."
    )


def regular_onboarding_instructions(*, server_instructions: str, arm: str) -> str:
    shared = (
        "This is a read-only Northstar replay evaluation. Inspect sources before making "
        "a card or claiming a metric definition. Ask the owner for metric scope, "
        "materiality, routing/ownership, and known data gaps; use exactly the returned "
        "answers. As acting data expert, sign off only from inspected refs. Save short "
        "reusable policy notes, not stale numbers. Approval is shadow-only; no message is sent."
    )
    if arm == "treatment":
        return shared + (
            " Use only the installed default agent profile. First call "
            "get_signalweave_guide(task='start'), then use search_catalog and "
            "inspect_resource. Create the smallest faithful card with exact selected_sources, "
            "review it with review_insight_card, resolve only source/policy blockers, and "
            "approve only after the current review and data-expert signoff. Then finish_setup. "
            "Do not use advanced/full-only tools, invent an alert threshold, or claim a "
            "synthetic review is real human authorization.\nInstalled default-agent instructions:\n"
            + server_instructions
        )
    return shared + (
        " This is the paired baseline. The exact same reviewed card and source tools are "
        "provided, but there are no SignalWeave tools. Inspect the card and source facts, "
        "ask the same owner topics, write concise notes faithful to the card, record the "
        "data-expert signoff, then finish_setup with that card ID. Do not alter the card "
        "or claim unattended delivery readiness."
    )


def recurring_instructions(*, server_instructions: str, arm: str) -> str:
    shared = (
        "You are the final Northstar business analyst for a delivery-disabled shadow run. "
        "Write a short recipient-ready message (10-80 words): verified facts, likely "
        "drivers when supported, important scope or data gaps, and a concrete next action. "
        "Cite exact inspected source refs and preserve the identical shared card policy. "
        "Do not claim causation from timing alone, invent materiality, send alerts, or "
        "hide a known source outage. This is a checked-in local replay, not fresh Superset data."
    )
    if arm == "treatment":
        return shared + (
            " SignalWeave's current-period bundle is typed evidence and a useful triage input, "
            "not a substitute for your final business assessment. Reconcile it against its "
            "sources; inspect authorized context needed for the owner's why question. You "
            "own the final report and outcome.\nInstalled default-agent instructions:\n"
            + server_instructions
        )
    return shared + (
        " This paired baseline has the identical owner-reviewed card, notes, business context, "
        "destinations, source catalog, source tools, model, and effort, but no SignalWeave "
        "bundle or product tools. Inspect the same current evidence and make your own assessment."
    )


async def _paired_tool_signature(session: ReleaseSession) -> dict[str, str]:
    specs = await session.specs()
    return {spec["name"]: digest(spec["parameters"]) for spec in specs}


def _verify_stage(binary: Path, certified_source_sha256: str,
                  certified_binary_sha256: str, checks: list[dict], stage: str) -> dict:
    current = _verify_certified_binary(
        binary, certified_source_sha256=certified_source_sha256,
        certified_binary_sha256=certified_binary_sha256,
    )
    checks.append({"stage": stage, "identity": current})
    return current


async def _episode(session: ReleaseSession, *, budget: RequestBudget, audit: Audit,
                   instructions: str, prompt: dict, bundle: dict | None = None,
                   max_turns: int = 32, max_tool_calls: int = 50) -> dict:
    return await codex_episode(
        session, key="", model=MODEL, effort=EFFORT, budget=budget, audit=audit,
        max_turns=max_turns, max_tool_calls=max_tool_calls, max_output_tokens=6000,
        timeout_seconds=360, bundle=bundle, instructions_override=instructions,
        prompt_override=prompt,
    )


async def run_pilot(*, binary: Path, key_file: Path, output: Path,
                    seed_dir: Path = DEFAULT_SEED, episodes: int = PILOT_SIZE,
                    jev_budget: int = 40, simulate_hil_followup: bool = False) -> dict:
    """Run a bounded, certified Northstar pilot through the shared installed loop."""
    if not 2 <= episodes <= PILOT_SIZE:
        raise ValueError("Pilot is bounded to 2-4 paired recurring episodes")
    if not 1 <= jev_budget <= 40:
        raise ValueError("Pilot Jev request budget must be 1-40")
    binary = Path(binary).resolve()
    key_file = Path(key_file).resolve()
    output = Path(output).resolve()
    if not key_file.is_file():
        raise FileNotFoundError("Private Jev key file is unavailable")
    identity = _verify_certified_binary(
        binary, certified_source_sha256=CERTIFIED_SOURCE_SHA256,
        certified_binary_sha256=CERTIFIED_BINARY_SHA256,
    )

    scenario = build_trial_scenario(seed_dir)
    hil_record = apply_simulated_hil_followup(scenario) if simulate_hil_followup else None
    selected = select_recurring_periods(scenario, cohort="pilot")[:episodes]
    selected_ids = {period["period_id"] for period in selected}
    scenario["public"]["periods"] = copy.deepcopy(selected)
    scenario["private"]["periods"] = {
        period_id: label for period_id, label in scenario["private"]["periods"].items()
        if period_id in selected_ids
    }
    scenario["private"].setdefault("multistep", {
        key: value for key, value in scenario["private"].get("multistep", {}).items()
        if key in selected_ids
    })
    if "multistep" in scenario["private"]:
        scenario["private"]["multistep"] = {
            key: value for key, value in scenario["private"]["multistep"].items()
            if key in selected_ids
        }

    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    _write_private(output / "release-preflight.json", {
        "protocol": PROTOCOL_VERSION,
        "parent_certificate": {
            "version": CERTIFIED_VERSION,
            "source_sha256": CERTIFIED_SOURCE_SHA256,
            "binary_sha256": CERTIFIED_BINARY_SHA256,
        },
        "certified_identity": identity,
        "model": MODEL, "effort": EFFORT, "mcp_profile": PROFILE,
        "episodes": [{
            "period_id": period["period_id"],
            "variant_id_private": scenario["private"]["periods"][period["period_id"]]["variant_id"],
        } for period in selected],
        "source_classification": (
            "Checked-in Northstar historical data served over simulated BI transport "
            "through a local synthetic MCP; not an actual Superset connection or extraction."
        ),
        "source_contract_fixture": scenario["private"]["source_contract_fixture_audit"],
        "card_policy_representation": {
            "numeric_conditions": "Optional; no binding is authored or supplied by this fixture.",
            "plain_english_thresholds": "Remain in decision_guidance for Jev to evaluate.",
            "source_comparison_contracts": "Recorded separately from inspected analytical_comparisons and required_comparison_keys.",
        },
        "simulated_hil_followup": hil_record,
        "owner_followup_transport": {
            "facade": "existing trial MCP",
            "tool": "ask_owner",
            "response_source": "independently predeclared Northstar owner knowledge, separate from private outcome labels",
            "answer_is_returned_only_after_topic_is_requested": True,
            "unknown_definition_remains_unknown": True,
            "uses_codex_ui_input": False,
        },
        "paired_runtime_scope": (
            "Shared installed_workflow_trial loop: treatment onboarding authors the "
            "reviewed card; the baseline receives the same card/notes and source tools "
            "without SignalWeave tool access or evaluation bundle."
        ),
        "delivery_enabled": False,
    })

    from evaluations.installed_workflow_trial import run_trial

    try:
        report = await run_trial(
            [scenario], binary=binary, key_file=key_file, output=output / "shared-trial",
            jev_budget=jev_budget, live=True, stage_gate=episodes,
            fixture_seed=None, author_model=MODEL, author_effort=EFFORT,
            recurring_agent_model=MODEL, recurring_agent_effort=EFFORT,
            reviewer_model=MODEL, reviewer_effort=EFFORT,
        )
    except Exception as error:
        try:
            final_identity = _verify_certified_binary(
                binary, certified_source_sha256=CERTIFIED_SOURCE_SHA256,
                certified_binary_sha256=CERTIFIED_BINARY_SHA256,
            )
            postflight_error = None
        except Exception as provenance_error:
            final_identity = None
            postflight_error = type(provenance_error).__name__
        _write_private(output / "release-failure.json", {
            "failure_type": type(error).__name__,
            "details": "Sensitive exception text omitted; inspect the redacted shared trace.",
            "postflight_identity": final_identity,
            "postflight_error_type": postflight_error,
        })
        raise
    utility_summary = add_final_report_utility(report, scenario)
    trace_path = output / "shared-trial" / "trace.jsonl"
    owner_followup_calls = []
    if trace_path.is_file():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (event.get("kind") == "tool.result"
                    and event.get("name") == "ask_owner"
                    and (event.get("arguments") or {}).get("topic")
                    == "severe_incident_definition"):
                owner_followup_calls.append({
                    "topic": "severe_incident_definition",
                    "result": event.get("result"),
                    "actor_role": event.get("actor_role"),
                })
    owner_followup_summary = {
        "expected_topic": "severe_incident_definition",
        "requests_observed": len(owner_followup_calls),
        "responses": owner_followup_calls,
        "definition_status": "unknown",
    }
    report["summary"]["owner_followup"] = owner_followup_summary
    _write_private(output / "northstar-final-report-utility.json", {
        "primary_endpoint": utility_summary,
        "owner_followup": owner_followup_summary,
        "simulated_bi_transport": True,
        "actual_superset_extraction": False,
    })
    final_identity = _verify_certified_binary(
        binary, certified_source_sha256=CERTIFIED_SOURCE_SHA256,
        certified_binary_sha256=CERTIFIED_BINARY_SHA256,
    )
    _write_private(output / "release-postflight.json", {
        "parent_certificate": {
            "version": CERTIFIED_VERSION,
            "source_sha256": CERTIFIED_SOURCE_SHA256,
            "binary_sha256": CERTIFIED_BINARY_SHA256,
        },
        "certified_identity": final_identity,
        "same_as_preflight": final_identity == identity,
        "shared_report_summary": report.get("summary"),
    })
    if final_identity != identity:
        raise RuntimeError("Binary identity changed during pilot; report is uncertified")
    return report


def _verify_policy_intervention_binary(binary: Path) -> dict:
    current_source = source_fingerprint(ROOT)
    if current_source != POLICY_INTERVENTION_SOURCE_SHA256:
        raise ValueError("Frozen policy-intervention source fingerprint changed")
    identity = verify_binary(binary)
    if (identity["source_sha256"] != POLICY_INTERVENTION_SOURCE_SHA256
            or identity["binary_sha256"] != POLICY_INTERVENTION_BINARY_SHA256):
        raise ValueError("Native binary does not match the frozen policy-intervention build")
    return identity


async def run_policy_intervention(*, binary: Path = ROOT / "dist" / "signalweave",
                                  key_file: Path = DEFAULT_KEY_FILE,
                                  output: Path = DEFAULT_INTERVENTION_OUTPUT,
                                  seed_dir: Path = DEFAULT_SEED) -> dict:
    """Run the separate, preregistered policy cohort on the frozen native build."""
    binary, key_file, output = Path(binary).resolve(), Path(key_file).resolve(), Path(output).resolve()
    if not key_file.is_file():
        raise FileNotFoundError("Private Jev key file is unavailable")
    identity = _verify_policy_intervention_binary(binary)
    scenario, registration = build_policy_intervention_scenario(seed_dir)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    sales_ref = _intervention_source_ref(scenario, "superset|dashboard:1")
    ledgers = {period["period_id"]: period["snapshots"][sales_ref].get("metadata", {}).get("ledger_rows", [])
               for period in [scenario["public"]["onboarding"], *scenario["public"]["periods"]]}
    _write_private(output / "source-ledgers.json", ledgers)
    _write_private(output / "release-preflight.json", {
        "protocol": POLICY_INTERVENTION_PROTOCOL,
        "registration": registration, "binary_identity": identity,
        "models": [MODEL, EFFORT], "jev_budget": POLICY_INTERVENTION_JEV_BUDGET,
        "source_classification": "simulated BI transport over checked-in fixtures; not an actual Superset extraction",
        "primary_endpoint": "final_human_report_utility_proxy",
    })

    from evaluations.installed_workflow_trial import run_trial

    try:
        report = await run_trial(
            [scenario], binary=binary, key_file=key_file, output=output / "paired",
            jev_budget=POLICY_INTERVENTION_JEV_BUDGET, live=True, stage_gate=PILOT_SIZE,
            fixture_seed=None, author_model=MODEL, author_effort=EFFORT,
            recurring_agent_model=MODEL, recurring_agent_effort=EFFORT,
            reviewer_model=MODEL, reviewer_effort=EFFORT,
        )
    except Exception as error:
        try:
            postflight = _verify_policy_intervention_binary(binary)
        except Exception as provenance_error:
            postflight = {"error_type": type(provenance_error).__name__}
        _write_private(output / "release-failure.json", {"failure_type": type(error).__name__,
            "postflight": postflight, "details": "Inspect the redacted paired trace."})
        raise

    add_final_report_utility(report, scenario)
    postflight = _verify_policy_intervention_binary(binary)
    trace_path = output / "paired" / "trace.jsonl"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()] if trace_path.is_file() else []
    report["policy_intervention"] = {
        "protocol": POLICY_INTERVENTION_PROTOCOL,
        "cohort_label": registration["cohort_label"],
        "registration": registration, "binary_before": identity, "binary_after": postflight,
        "binary_identity_unchanged": identity == postflight,
        "source_fingerprint_after": source_fingerprint(ROOT),
        "source_scope_confirmations_at_approval": [
            event.get("arguments", {}).get("source_scope_confirmations") for event in events
            if event.get("kind") == "tool.result" and event.get("name") == "approve_insight_card"
        ],
        "owner_replies": [{"topic": event.get("arguments", {}).get("topic"),
                            "result": event.get("result")} for event in events
                           if event.get("kind") == "tool.result" and event.get("name") == "ask_owner"],
        "data_expert_signoffs": [event.get("result") for event in events
                                 if event.get("kind") == "tool.result"
                                 and event.get("name") == "sign_off_data_foundation"],
        "source_classification": "simulated BI transport; not an actual Superset extraction",
    }
    _write_private(output / "northstar-policy-intervention-report.json", report)
    if identity != postflight or report["policy_intervention"]["source_fingerprint_after"] != POLICY_INTERVENTION_SOURCE_SHA256:
        raise RuntimeError("Source or binary identity changed during policy-intervention trial")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--episodes", type=int, choices=(2, 3, 4), default=4)
    parser.add_argument("--jev-budget", type=int, choices=range(1, 41), default=40)
    parser.add_argument("--simulate-hil-followup", action="store_true",
                        help="Expose predeclared owner knowledge through the shared ask_owner MCP tool")
    args = parser.parse_args()
    report = asyncio.run(run_pilot(
        binary=args.binary, key_file=args.key_file, output=args.output,
        seed_dir=args.seed_dir, episodes=args.episodes, jev_budget=args.jev_budget,
        simulate_hil_followup=args.simulate_hil_followup,
    ))
    print(json.dumps({
        "status": "completed",
        "summary": report.get("summary"),
        "binary_sha256": report.get("protocol", {}).get("binary_sha256"),
        "output": str(args.output.resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()

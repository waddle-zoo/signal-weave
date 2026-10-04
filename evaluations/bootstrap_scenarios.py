"""Independent novice-onboarding fixtures and deterministic scorer; no runner.

Only ``public_scenario`` output belongs in an agent/adapter process. Private
labels are evaluation-owned and never required to serve catalog or source tools.
This module deliberately does not import the engine, Jev, or its numerical solver.
"""

from __future__ import annotations

import copy
import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, ValidationError

from signalweave.models import ResourceContract, ResourceDescriptor, ResourceSnapshot

SCHEMA_VERSION = 1
SCORER_VERSION = 3
DEFAULT_SEED = 20261001
CLAIM_TYPES = ("observation", "accounting_decomposition", "association", "hypothesis", "causal")
OWNER_TOPICS = ("metric_scope", "materiality", "routing", "data_gaps")

# The original v3 fixture intentionally uses one neutral adapter name so its
# historical digest remains immutable.  New connector-profile trials preserve
# the same business data and labels while exercising the multi-adapter runtime
# with realistic BI/warehouse/operations names.
CONNECTOR_PROFILES = {
    "retail": ("superset", "dbt", "airflow", "looker"),
    "subscription_boxes": ("superset", "dbt", "airflow", "looker"),
    "saas": ("looker", "airflow", "hex", "superset"),
    "support": ("superset", "notion", "looker", "airflow"),
    "ops": ("superset", "airflow", "pagerduty", "cloudwatch"),
    "logistics": ("tableau", "airflow", "carrier", "trino"),
    "marketplace": ("trino", "segment", "hex", "superset"),
    "finance": ("trino", "airflow", "looker", "dbt"),
}

# Optional catalog pressure for live onboarding trials. These are ordinary
# source scopes that appear in real BI/data catalogs, not evaluator labels.
# The default fixture does not include them so the measured v3 digest remains
# immutable; noisy trials opt in explicitly and expose the same alternatives
# to both the baseline and SignalWeave arms.
CATALOG_VARIANTS = (
    ("archive", "Historical archive retained for reconciliation."),
    ("sandbox", "Sandbox scope used for development and validation."),
    ("regional", "Regional pilot scope with a limited operating population."),
    ("forecast", "Planning projection used for forward-looking scenarios."),
    ("partner", "Partner scope with a separately governed population."),
)


def _numeric_vocabulary(spec: dict) -> list[str]:
    """Public measurement schema, defined independently of every period/label."""
    suffixes = {
        "retail": ("baseline", "current", "delta", "web_contribution"),
        "subscription_boxes": ("baseline", "current", "delta", "web_contribution"),
        "saas": ("baseline", "current", "delta", "within_effect", "mix_effect"),
        "support": ("baseline", "current", "delta", "within_effect", "mix_effect"),
        "logistics": ("baseline", "current", "delta", "within_effect", "mix_effect"),
        "ops": ("delta", "affected_regions", "rollout_lead_minutes"),
        "marketplace": ("baseline", "current", "delta"),
        "finance": ("baseline", "current", "delta"),
    }[spec["family"]]
    return sorted(f"{spec['metric']}.{name}" for name in suffixes)


def _numeric_definitions(spec: dict) -> dict[str, dict[str, str]]:
    """Static fact meanings, never period-specific availability or oracle values."""
    definitions = {
        "baseline": "Metric value in the baseline interval under the supplied metric definition.",
        "current": "Metric value in the current interval under the supplied metric definition.",
        "delta": "Signed current metric value minus baseline metric value, not percentage change.",
        "web_contribution": "Signed contribution of web to the total change: current net web "
                            "(current_gross - current_refunds) minus baseline net web "
                            "(baseline_gross - baseline_refunds); not current web proceeds.",
        "within_effect": "Symmetric within-segment rate change: sum over segments of "
                         "((baseline weight + current weight) / 2) * (current rate - baseline rate). "
                         "Weights are shares of eligible denominators; units are ratios, not percentages.",
        "mix_effect": "Symmetric population-mix effect: sum over segments of "
                      "((baseline rate + current rate) / 2) * (current weight - baseline weight). "
                      "Weights are shares of eligible denominators; units are ratios, not percentages.",
        "affected_regions": "Number of affected regions in the defined customer-cluster population.",
        "rollout_lead_minutes": "Latency-change timestamp minus rollout-start timestamp in minutes; "
                                "positive means rollout preceded the change, not proof of causation.",
    }
    if spec["family"] == "ops":
        definitions["delta"] = "Current query p95 latency minus baseline query p95 latency " \
                               "in milliseconds for the defined customer-cluster population."
    if spec["family"] == "finance":
        policy = (" Canonical collections require all expected bank partitions closed and the "
                  "bank watermark at the reporting cutoff. This export has no independent "
                  "historical closure attestation: a partial or stale export cannot validate "
                  "even its baseline. A printed amount alone does not establish a canonical total.")
        for name in ("baseline", "current", "delta"):
            definitions[name] += policy
    units = {"affected_regions": "regions", "rollout_lead_minutes": "minutes"}
    return {fact: {"definition": definitions[fact.rsplit(".", 1)[1]],
                   "unit": units.get(fact.rsplit(".", 1)[1], spec["unit"])}
            for fact in _numeric_vocabulary(spec)}


def _required_evidence_refs(spec: dict, payloads: list[dict], refs: list[str]) -> list[str]:
    """Require semantic dependencies, not every relevant or corroborating asset."""
    required = [refs[0]]
    # Bank closure is controlled outside the primary export. An observed
    # rollout association also needs the change calendar.
    # Other primary exports already define their population/timing or explicitly
    # disclose the gap; the separate document adds no indispensable fact.
    if spec["family"] == "finance" or (
        spec["family"] == "ops" and payloads[1].get("latency_change_at") is not None
    ):
        required.append(refs[1])
    return required


def _opaque(rng: random.Random, prefix: str) -> str:
    return f"{prefix}-{rng.getrandbits(80):020x}"


def _number(value: int | float | Fraction) -> float:
    return float(value)


def _perturb_numeric_values(value: Any, factor: float) -> Any:
    """Make a plausible alternative-scope export without metric-specific code."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(round(value * factor))
    if isinstance(value, float):
        return value * factor
    if isinstance(value, dict):
        return {key: _perturb_numeric_values(item, factor) for key, item in value.items()}
    if isinstance(value, list):
        return [_perturb_numeric_values(item, factor) for item in value]
    if isinstance(value, tuple):
        return tuple(_perturb_numeric_values(item, factor) for item in value)
    return value


def _rate_facts(rows: list[tuple[str, int, int, int, int]]) -> dict[str, float]:
    """Independent oracle: four standardized totals, not runtime contributions."""
    d0, d1 = sum(r[2] for r in rows), sum(r[4] for r in rows)
    r00 = sum((Fraction(n0, d0) for _, n0, _, _, _ in rows), Fraction())
    r11 = sum((Fraction(n1, d1) for _, _, _, n1, _ in rows), Fraction())
    # Hold weights from period zero / one while substituting the other rates.
    r10 = sum((Fraction(n1, den1) * Fraction(den0, d0)
               for _, _, den0, n1, den1 in rows), Fraction())
    r01 = sum((Fraction(n0, den0) * Fraction(den1, d1)
               for _, n0, den0, _, den1 in rows), Fraction())
    return {"baseline": float(r00), "current": float(r11), "delta": float(r11 - r00),
            "within_effect": float(((r10 - r00) + (r11 - r01)) / 2),
            "mix_effect": float(((r01 - r00) + (r11 - r10)) / 2)}


def _comparison(metric: str, rows: list[tuple[str, int, int, int, int]],
                as_of: datetime, query_ref: str, definition: str) -> dict:
    return {
        "key": metric, "metric": metric, "definition": definition,
        "population": "Eligible entities in the source glossary",
        "dimension": "cohort", "unit": "ratio", "kind": "rate",
        "baseline_start": (as_of - timedelta(days=14)).isoformat(),
        "baseline_end": (as_of - timedelta(days=7)).isoformat(),
        "current_start": (as_of - timedelta(days=7)).isoformat(),
        "current_end": as_of.isoformat(), "coverage": "complete",
        "disjoint_segments": True, "comparable": True, "query_refs": [query_ref],
        "baseline_total": {"numerator": sum(r[1] for r in rows),
                           "denominator": sum(r[2] for r in rows)},
        "current_total": {"numerator": sum(r[3] for r in rows),
                          "denominator": sum(r[4] for r in rows)},
        "segments": [{"segment": name, "baseline": {"numerator": n0, "denominator": d0},
                      "current": {"numerator": n1, "denominator": d1}}
                     for name, n0, d0, n1, d1 in rows],
    }


def _additive_comparison(
    metric: str,
    baseline: float | None,
    current: float | None,
    segments: list[tuple[str, float | None, float | None]],
    as_of: datetime,
    query_refs: list[str],
    definition: str,
    unit: str,
    *,
    comparable: bool = True,
    coverage: str = "complete",
) -> dict:
    """Build the normalized comparison a real connector would return.

    The raw export remains in the fixture as well.  This separate projection is
    important: SignalWeave consumes adapter-declared analytical comparisons,
    while a general-purpose agent may still inspect the underlying rows.
    """
    return {
        "key": metric,
        "metric": metric,
        "definition": definition,
        "population": "Eligible entities in the source glossary",
        "dimension": "total",
        "unit": unit,
        "kind": "additive",
        "baseline_start": (as_of - timedelta(days=14)).isoformat(),
        "baseline_end": (as_of - timedelta(days=7)).isoformat(),
        "current_start": (as_of - timedelta(days=7)).isoformat(),
        "current_end": as_of.isoformat(),
        "comparison_window": "previous_period",
        "coverage": coverage,
        "disjoint_segments": True,
        "comparable": comparable,
        "query_refs": query_refs,
        "baseline_total": {"value": baseline},
        "current_total": {"value": current},
        "segments": [
            {"segment": segment, "baseline": {"value": baseline_value},
             "current": {"value": current_value}}
            for segment, baseline_value, current_value in segments
        ],
    }


def _buyer_values(export: dict) -> dict[str, float]:
    """Read the union export, never reconstruct missing buyers from audience tags."""
    if (export.get("identity") != "customer_id" or export.get("aggregation") != "count_distinct"
            or export.get("coverage") not in {"all_completed_purchases", "missing_union_export"}):
        return {}
    values = {}
    for name in ("baseline", "current"):
        value = export.get(f"{name}_distinct_buyers")
        # missing_union_export describes the current union, not the supplied baseline.
        if name == "current" and export["coverage"] != "all_completed_purchases":
            continue
        if _is_finite_number(value) and value >= 0 and value == int(value):
            values[name] = value
    if {"baseline", "current"} <= values.keys():
        values["delta"] = values["current"] - values["baseline"]
    return values


def _finance_values(export: dict, control: dict, as_of: datetime) -> dict[str, float]:
    """No historical freshness exemption without a public closure attestation.

    The shared bank control is the only attestation in these fixtures. It must
    close every partition at the reporting cutoff, even for a baseline-only claim.
    Latent generating totals and the scenario's condition are not evidence.
    """
    expected, closed = control.get("expected_partitions"), control.get("closed_partitions")
    if type(expected) is not int or expected <= 0 or type(closed) is not int or closed != expected:
        return {}
    try:
        watermark = datetime.fromisoformat(control["watermark"])
    except (KeyError, TypeError, ValueError):
        return {}
    if watermark != as_of:
        return {}
    values = {name: export[f"{name}_settled_usd"] for name in ("baseline", "current")
              if _is_finite_number(export.get(f"{name}_settled_usd"))}
    if {"baseline", "current"} <= values.keys():
        values["delta"] = values["current"] - values["baseline"]
    return values


def _specs(split: str) -> list[dict]:
    common = [
        {"family": "retail", "company": "Juniper Trail Retail",
         "brief": "Keep an eye on what we actually keep from sales. If it takes a hit, tell our commerce lead what changed, not just that a chart moved.",
         "scope": "Sales means gross completed-order revenue minus refunds posted during the same reporting week, excluding tax and shipping. Do not use booked order value or subtract refunds twice.",
         "policy": "Notify the business destination for a net-sales decline of at least 10% against the prior complete week. Otherwise ignore. Missing definitions or incomplete postings require insufficient_data to the data destination, not a business alert.",
         "titles": ["Commerce weekly", "Returns operations", "Orders weekly", "Commerce weekly"],
         "descriptions": ["Completed transaction amounts by sales channel; refunds are positive deductions, amounts in USD.", "Refund posting metadata and accounting mapping; not an additional refund ledger.", "Order bookings including cancelled orders, tax and shipping; not recognized sales.", "Archived checkout experiment, test-store population only."],
         "metric": "net_sales", "unit": "USD"},
        {"family": "saas", "company": "Harbor Workspace",
         "brief": "Are customers sticking with us? Let customer success know when retention is really getting worse, rather than just because we signed up a different mix of customers.",
         "scope": "Retention is renewed accounts divided by accounts due for renewal in the week, grouped by the plan at renewal eligibility. Trial signups are excluded. Plan cohorts are mutually exclusive.",
         "policy": "Notify the business destination if the symmetric within-plan retention change is at most -0.05 in ratio units. A pure mix shift is ignore, even if the aggregate falls. An unknown eligibility definition requires insufficient_data to the data destination.",
         "titles": ["Account health", "Billing definitions", "Account health", "Acquisition"],
         "descriptions": ["Renewal counts and eligible accounts by paid plan, with controlling totals.", "Versioned renewal eligibility rules from Billing.", "Product logins divided by registered accounts, including trials.", "Campaign signups by source; not renewal cohorts."],
         "metric": "retention", "unit": "ratio"},
        {"family": "support", "company": "Kindred Helpdesk",
         "brief": "We are getting busier. Tell the support manager if we are letting customers down, not every time the ticket count goes up.",
         "scope": "SLA attainment is first responses within one business day divided by all eligible inbound customer tickets, including still-open tickets whose deadline elapsed. Bot and spam tickets are excluded.",
         "policy": "Notify the business destination when SLA attainment drops by at least 0.05 ratio units against the prior complete week. Volume alone is ignore. A missing eligible denominator requires insufficient_data to the data destination.",
         "titles": ["Queue service", "Support handbook", "Queue service", "Agent activity"],
         "descriptions": ["Response-within-SLA counts and eligible inbound denominators by queue.", "Queue inclusion rules, business calendar, and routing ownership.", "Closed-ticket response percentages; excludes overdue open tickets.", "Agent logins and automation messages, not customer outcomes."],
         "metric": "sla_attainment", "unit": "ratio"},
        {"family": "ops", "company": "Cinder Database Cloud",
         "brief": "Watch for customer-facing database slowdowns. Connect the related signals before paging someone. We do not want a page for one hot CPU.",
         "scope": "Customer impact needs query p95 latency and replication lag in the same cluster population, with regional breadth. Rollout times and incident notes are corroboration, not proof of cause.",
         "policy": "Investigate to the business destination when latency rises at least 20%, lag at least doubles, and at least two regions are affected. Isolated CPU spikes are ignore. Missing cluster coverage requires insufficient_data to the data destination. Never state a deployment caused an incident from timing alone.",
         "titles": ["Database service", "Change calendar", "Database service", "Capacity"],
         "descriptions": ["Customer-cluster latency, replication lag and region coverage.", "Deployment timestamps, cluster targets and rollback runbook link.", "Load-test latency and CPU from synthetic clusters only.", "Single-node CPU and disk utilization, not customer impact."],
         "metric": "latency", "unit": "ms"},
        {"family": "marketplace", "company": "Mosaic Exchange",
         "brief": "I want to know if the number of people buying is falling. Our growth team has lots of audience charts, but I do not want the same customer counted twice.",
         "scope": "Weekly buyers are distinct customer IDs with a completed purchase, across the entire marketplace. Audience tags overlap; only the union query is a population count.",
         "policy": "Notify the business destination for at least a 15% drop in distinct buyers. Otherwise ignore. If only overlapping audience counts are available, use insufficient_data to the data destination; do not add the tags.",
         "titles": ["Buyer activity", "Audience activity", "Buyer activity", "Seller activity"],
         "descriptions": ["Distinct completed-purchase buyer union, deduplicated by customer ID.", "Buyer audience tags; users may be in more than one audience.", "Purchase sessions by device, several sessions per customer possible.", "Listings and active sellers; different population from buyers."],
         "metric": "distinct_buyers", "unit": "people"},
        {"family": "finance", "company": "Lumen Freight Finance",
         "brief": "Keep me ahead of a cash shortfall. If collections dip, tell the controller, but do not panic everyone just because the bank feed is late.",
         "scope": "Collections are settled receipts in USD by bank posting week, not invoices or payment authorizations. All bank partitions must close before a comparison is actionable.",
         "policy": "Notify the business destination for at least a 10% decline in settled receipts versus the previous complete week. Otherwise ignore. A late partition requires insufficient_data to the data destination, never an assertion that cash disappeared.",
         "titles": ["Receipts weekly", "Bank ingest", "Receipts weekly", "Revenue plan"],
         "descriptions": ["Settled bank receipts by account, with independent control total.", "Bank partition close status, event watermark and expected reporting cutoff.", "Payment authorizations before settlement, including reversals.", "Forecast invoices, not settled cash receipts."],
         "metric": "collections", "unit": "USD"},
    ]
    if split == "holdout":
        return common
    # Distinct development business domains and metric language, not held-out companies.
    return [
        {**common[0], "family": "subscription_boxes", "company": "Cedar Meal Kits",
         "brief": "Watch what we earn from our delivered meal boxes after credits. Tell the operations lead if that gets materially worse.",
         "scope": "Box proceeds are fulfilled-box charges less customer credits posted in the same week, excluding delivery fees. The feeds call these gross and refunds.",
         "titles": ["Box proceeds", "Credit processing", "Box bookings", "Delivery plan"],
         "descriptions": ["Fulfilled-box charges and posted credits by purchase channel; amounts in USD.", "Customer credit posting metadata and accounting mapping, not extra credits.", "Box reservations including unfulfilled and cancelled boxes; not recognized proceeds.", "Forecast deliveries and test subscriptions, not fulfilled customer boxes."],
         "metric": "box_proceeds"},
        {**common[2], "family": "logistics", "company": "Pine Courier",
         "brief": "Let dispatch know when we stop meeting promised delivery windows. Extra parcel volume by itself is not bad news.",
         "scope": "SLA attainment is parcels delivered by the promised window divided by all parcels due, including overdue undelivered parcels. Cancelled parcels are excluded.",
         "titles": ["Delivery service", "Dispatch handbook", "Completed parcels", "Driver activity"],
         "descriptions": ["On-time parcel counts and all parcels due by service tier, with controlling totals.", "Promised delivery calendar, parcel eligibility and dispatch ownership.", "On-time percentages among completed parcels only; excludes overdue undelivered parcels.", "Driver logins and route starts, not completed customer deliveries."],
         "metric": "on_time_delivery"},
    ]


def _payload(spec: dict, condition: str, scale: int, as_of: datetime,
             refs: list[str], *, normalized_comparisons: bool = False) -> tuple[list[dict], dict, list[str]]:
    """Build source payloads; derive labels from generating quantities, not engine output."""
    family, metric = spec["family"], spec["metric"]
    broken, event = condition == "quality", condition == "event"
    payloads: list[dict] = [{}, {}, {}, {}]
    facts: dict[str, dict] = {}
    required: list[str] = []

    def fact(name: str, value: float, unit: str = spec["unit"], *, needed=False,
             evidence_refs: list[str] | None = None):
        key = f"{metric}.{name}"
        facts[key] = {"value": _number(value), "unit": unit,
                      "evidence_refs": evidence_refs or [refs[0]], "absolute_tolerance": 1e-6}
        if needed:
            required.append(key)

    if family in {"retail", "subscription_boxes"}:
        rows = [
            {"channel": "web", "baseline_gross": 800 * scale, "baseline_refunds": 100 * scale,
             "current_gross": (650 if event else 800) * scale,
             "current_refunds": (250 if event else 100) * scale},
            {"channel": "shop", "baseline_gross": 400 * scale, "baseline_refunds": 100 * scale,
             "current_gross": 400 * scale, "current_refunds": 100 * scale},
        ]
        payloads[0] = {"rows": rows, "fields": {"gross": "USD", "refunds": "USD"},
                       "refund_timing": "undocumented" if broken else "posting_week"}
        payloads[1] = {"posting_policy": "New refund feed has no versioned timing mapping." if broken
                       else "Posting week matches transaction feed; refunds already included in its rows."}
        if not broken:
            b = sum(r["baseline_gross"] - r["baseline_refunds"] for r in rows)
            c = sum(r["current_gross"] - r["current_refunds"] for r in rows)
            if normalized_comparisons:
                payloads[0]["comparison"] = _additive_comparison(
                metric,
                b,
                c,
                [
                    (
                        row["channel"],
                        row["baseline_gross"] - row["baseline_refunds"],
                        row["current_gross"] - row["current_refunds"],
                    )
                    for row in rows
                ],
                as_of,
                [refs[0]],
                spec["scope"],
                spec["unit"],
                )
            for name, value in (("baseline", b), ("current", c), ("delta", c - b)):
                fact(name, value, needed=name == "delta")
            fact("web_contribution", rows[0]["current_gross"] - rows[0]["current_refunds"]
                 - rows[0]["baseline_gross"] + rows[0]["baseline_refunds"], needed=event)
    elif family in {"saas", "support", "logistics"}:
        if family == "saas":
            rows = [("team", 90 * scale, 100 * scale, (40 if event else 45) * scale, 50 * scale),
                    ("self_serve", 20 * scale, 100 * scale, (15 if event else 30) * scale, 150 * scale)]
        else:
            rows = [("priority", 90 * scale, 100 * scale, (150 if event else 180) * scale, 200 * scale),
                    ("standard", 90 * scale, 100 * scale, (150 if event else 180) * scale, 200 * scale)]
        comp = _comparison(metric, rows, as_of, refs[0], spec["scope"])
        if broken:
            if family == "saas":
                comp["comparable"] = False
                payloads[1] = {"eligibility_version": None, "note": "Billing migrated plan eligibility; historical membership mapping is unavailable."}
            else:
                comp["segments"][0]["current"]["denominator"] = None
                comp["current_total"]["denominator"] = None
                payloads[1] = {"note": "Open overdue population export is missing. Owner cannot reconstruct it."}
                # Only the current denominator is missing. Preserve an optional
                # baseline fact from the visible export, not the complete latent rows.
                baseline = comp["baseline_total"]
                numerator, denominator = baseline.get("numerator"), baseline.get("denominator")
                if (_is_finite_number(numerator) and _is_finite_number(denominator)
                        and denominator > 0 and 0 <= numerator <= denominator):
                    fact("baseline", numerator / denominator)
        else:
            payloads[1] = {"definition_version": "v3", "eligible_population": spec["scope"]}
            for name, value in _rate_facts(rows).items():
                fact(name, value, needed=name in ({"delta", "within_effect", "mix_effect"}
                     if family == "saas" else {"delta"}))
        payloads[0] = {"comparison": comp}
    elif family == "ops":
        payloads[0] = {"baseline_p95_ms": 100, "current_p95_ms": 140 if event else 100,
                       "baseline_lag_ms": 10, "current_lag_ms": 80 if event else 10,
                       "affected_regions": None if broken else (3 if event else 0),
                       "cluster_population": None if broken else ["eu-1", "us-1", "ap-1"],
                       "single_node_cpu_percent": 95}
        payloads[1] = {"rollout_started_at": (as_of - timedelta(hours=2)).isoformat(),
                       "latency_change_at": (as_of - timedelta(hours=1, minutes=48)).isoformat() if event else None,
                       "target_population": ["eu-1", "us-1", "ap-1"],
                       "incident_note": "A prior rollout coincided with lag; no controlled causal test was performed.",
                       "runbook": "Check target clusters and customer reports before proposing rollback."}
        if not broken:
            if normalized_comparisons:
                payloads[0]["comparison"] = _additive_comparison(
                metric,
                payloads[0]["baseline_p95_ms"],
                payloads[0]["current_p95_ms"],
                [("all_customer_clusters", payloads[0]["baseline_p95_ms"], payloads[0]["current_p95_ms"])],
                as_of,
                [refs[0]],
                spec["scope"],
                spec["unit"],
                )
            fact("delta", 40 if event else 0, needed=True)
            fact("affected_regions", 3 if event else 0, "regions", needed=event)
            if event:
                fact("rollout_lead_minutes", 12, "minutes", needed=True, evidence_refs=[refs[1]])
    elif family == "marketplace":
        b, c = 200 * scale, (130 if event else 200) * scale
        payloads[0] = {"baseline_distinct_buyers": b, "current_distinct_buyers": None if broken else c,
                       "identity": "customer_id", "aggregation": "count_distinct",
                       "coverage": "missing_union_export" if broken else "all_completed_purchases"}
        payloads[1] = {"baseline_audience_counts": {"loyal": 150 * scale, "mobile": 150 * scale},
                       "current_audience_counts": {"loyal": c * 3 // 4, "mobile": c * 3 // 4},
                       "overlap": "known, intersection count not exported", "disjoint": False}
        for name, value in _buyer_values(payloads[0]).items():
            fact(name, value, needed=name == "delta")
        if not broken:
            values = _buyer_values(payloads[0])
            if normalized_comparisons:
                payloads[0]["comparison"] = _additive_comparison(
                metric,
                values.get("baseline"),
                values.get("current"),
                [("all_buyers", values.get("baseline"), values.get("current"))],
                as_of,
                [refs[0]],
                spec["scope"],
                spec["unit"],
                )
    else:
        b, c = 1000 * scale, (750 if event else 1000) * scale
        payloads[0] = {"baseline_settled_usd": b, "current_settled_usd": 400 * scale if broken else c,
                       "rows": [{"bank": "east", "current_usd": (150 if broken else c // scale // 2) * scale},
                                {"bank": "west", "current_usd": (250 if broken else c // scale // 2) * scale}]}
        payloads[1] = {"closed_partitions": 1 if broken else 2, "expected_partitions": 2,
                       "watermark": (as_of - timedelta(days=3) if broken else as_of).isoformat()}
        for name, value in _finance_values(payloads[0], payloads[1], as_of).items():
            fact(name, value, needed=name == "delta", evidence_refs=refs[:2])
        values = _finance_values(payloads[0], payloads[1], as_of)
        if values:
            if normalized_comparisons:
                payloads[0]["comparison"] = _additive_comparison(
                metric,
                values.get("baseline"),
                values.get("current"),
                [
                    (
                        row["bank"],
                        row.get("baseline_usd"),
                        row.get("current_usd"),
                    )
                    for row in payloads[0]["rows"]
                ] if all("baseline_usd" in row for row in payloads[0]["rows"]) else [
                    ("all_settled_receipts", values.get("baseline"), values.get("current"))
                ],
                as_of,
                refs[:2],
                spec["scope"],
                spec["unit"],
                )
    # Plausible, large movements in irrelevant populations on *every* period.
    payloads[2] = {"baseline": 900 * scale, "current": 450 * scale,
                   "population": spec["descriptions"][2], "coverage": "complete_for_this_population"}
    payloads[3] = {"baseline": 100 * scale, "current": 200 * scale,
                   "population": spec["descriptions"][3]}
    return payloads, facts, required


def build_scenarios(
    seed: int = DEFAULT_SEED,
    split: Literal["dev", "holdout"] = "holdout",
    *,
    connector_profile: bool = False,
    catalog_noise: int = 0,
) -> list[dict]:
    """Six held-out companies × three monitoring periods, or two dev companies.

    The separately supplied onboarding snapshot is not a held-out period. Each
    monitoring period is exposed to tools only when it becomes current; never
    put the full ``public`` object into a model prompt. ``catalog_noise`` adds
    the same number of scoped alternative resources per canonical resource;
    it is intentionally opt-in so the historical fixture stays byte-identical.
    """
    if split not in {"dev", "holdout"}:
        raise ValueError("split must be dev or holdout")
    if type(catalog_noise) is not int or not 0 <= catalog_noise <= 20:
        raise ValueError("catalog_noise must be an integer between 0 and 20")
    rng = random.Random(f"bootstrap-v{SCHEMA_VERSION}:{seed}:{split}")
    scenarios = []
    for spec in _specs(split):
        scenario_id = _opaque(rng, "company")
        keys = [_opaque(rng, "resource") for _ in range(4)]
        adapters = (
            CONNECTOR_PROFILES[spec["family"]]
            if connector_profile
            else ("company_mcp",) * len(keys)
        )
        refs = [f"{adapters[i]}|{key}" for i, key in enumerate(keys)]
        route, data_route = _opaque(rng, "team"), _opaque(rng, "team")
        destinations = [{"key": route, "label": "Business owner", "destination": f"slack://{route}"},
                        {"key": data_route, "label": "Data operations", "destination": f"slack://{data_route}"}]
        # Keep this measured v3 fixture immutable as production models evolve.
        # It did not declare window capabilities; a later trial must version
        # any enriched source contract instead of silently changing old inputs.
        catalog = []
        noise_specs = []
        noise_rng = random.Random(
            f"bootstrap-noise-v{SCHEMA_VERSION}:{seed}:{split}:{scenario_id}"
        )
        for i, key in enumerate(keys):
            metadata = {
                "tenant": scenario_id,
                "owner": destinations[i % 2]["label"],
                "inspection": "bounded current-period snapshot",
                "read_only": True,
            }
            if connector_profile and i == 0:
                # The profile catalog models a native lineage/knowledge-graph
                # edge: the primary analytical asset is related to the first
                # corroborating context asset. The edge is adapter metadata,
                # not a hidden expected outcome, and is intentionally absent
                # from the neutral legacy fixture.
                metadata["related_refs"] = [refs[1]]
            elif connector_profile and i == 1:
                metadata["related_refs"] = [refs[0]]
            descriptor = ResourceDescriptor(
                adapter=adapters[i], resource=key,
                kind=("saved_query", "document", "saved_query", "chart")[i],
                title=spec["titles"][i], description=spec["descriptions"][i],
                metadata=metadata,
            )
            if connector_profile and i == 0:
                # The profile trial models a connector that exposes a reviewed
                # recurring comparison contract. The historical neutral fixture
                # intentionally remains unchanged.
                descriptor.contract = ResourceContract(
                    tenant_id=scenario_id,
                    domain=spec["family"],
                    scope=spec["scope"],
                    metric_names=[spec["metric"]],
                    available_comparison_windows=["previous_period"],
                    required_comparison_keys=[spec["metric"]],
                    population="Eligible entities in the source glossary",
                    grain="week",
                    roles=["primary"],
                )
            catalog.append(descriptor.model_dump(
                mode="json",
                exclude={} if connector_profile else {"contract": {"available_comparison_windows"}},
            ))
            if catalog_noise:
                for variant_index in range(catalog_noise):
                    variant_name, variant_note = CATALOG_VARIANTS[
                        variant_index % len(CATALOG_VARIANTS)
                    ]
                    variant_suffix = (
                        variant_name if variant_index < len(CATALOG_VARIANTS)
                        else f"{variant_name}-{variant_index // len(CATALOG_VARIANTS) + 1}"
                    )
                    noise_key = _opaque(noise_rng, "resource")
                    noise_ref = f"{adapters[i]}|{noise_key}"
                    noise_descriptor = ResourceDescriptor(
                        adapter=adapters[i], resource=noise_key,
                        kind=descriptor.kind,
                        title=f"{spec['titles'][i]} — {variant_suffix}",
                        description=f"{spec['descriptions'][i]} {variant_note}",
                        metadata={
                            "tenant": scenario_id,
                            "owner": destinations[i % 2]["label"],
                            "inspection": "bounded current-period snapshot",
                            "read_only": True,
                            "scope": variant_suffix,
                        },
                        contract=ResourceContract(
                            tenant_id=scenario_id,
                            domain=spec["family"],
                            scope=f"{spec['scope']} ({variant_note})",
                            metric_names=[spec["metric"]],
                            roles=["reference"],
                        ),
                    )
                    catalog.append(noise_descriptor.model_dump(mode="json"))
                    noise_specs.append({
                        "canonical_index": i,
                        "adapter": adapters[i],
                        "resource": noise_key,
                        "ref": noise_ref,
                        "title": noise_descriptor.title,
                        "description": noise_descriptor.description,
                        "variant": variant_suffix,
                        "variant_index": variant_index,
                    })
        if catalog_noise:
            # Keep the canonical scenario RNG independent from optional catalog
            # pressure so explicit company IDs and private labels remain stable.
            catalog_rng = random.Random(
                f"bootstrap-catalog-order-v{SCHEMA_VERSION}:{seed}:{split}:{scenario_id}"
            )
            catalog_rng.shuffle(catalog)
            # Consume the same number of base-RNG draws as the canonical
            # four-resource shuffle; subsequent company IDs and periods must
            # not depend on whether this stress mode was enabled.
            rng.shuffle([None] * len(keys))
        else:
            rng.shuffle(catalog)
        scale = rng.randint(3, 37)
        base = datetime(2026, 10, 5, tzinfo=timezone.utc)

        def period(condition: str, as_of: datetime, *, spec=spec, scale=scale, refs=refs,
                   keys=keys, adapters=adapters, noise_specs=noise_specs,
                   scenario_id=scenario_id, route=route, data_route=data_route) -> tuple[dict, dict]:
            period_id = _opaque(rng, "period")
            payloads, facts, required = _payload(
                spec,
                condition,
                scale,
                as_of,
                refs,
                normalized_comparisons=connector_profile,
            )
            snapshots = {}
            for i, payload in enumerate(payloads):
                payload = copy.deepcopy(payload)
                comparison = payload.pop("comparison", None)
                snapshots[refs[i]] = ResourceSnapshot(
                    source_key=keys[i], adapter=adapters[i], resource=keys[i],
                    title=spec["titles"][i], description=spec["descriptions"][i],
                    captured_at=as_of, source_captured_at=(as_of - timedelta(days=3)
                        if condition == "quality" and spec["family"] == "finance" and i == 0 else as_of),
                    analytical_comparisons=[comparison] if comparison else [],
                    evidence=[{"source_key": keys[i], "subject_id": keys[i],
                               "statement": "Source export; interpret using catalog and owner definitions.",
                               "values": payload, "provenance": [refs[i]]}],
                    metadata={"tenant": scenario_id, "period_id": period_id},
                ).model_dump(mode="json", exclude={"contract": {"available_comparison_windows"}})
            for noise in noise_specs:
                source_ref = noise["ref"]
                values = copy.deepcopy(payloads[noise["canonical_index"]])
                # Alternative scopes expose data, but not the reviewed
                # comparison contract that makes the canonical source usable
                # for recurring decisions. This is intentionally generic.
                values.pop("comparison", None)
                factor = 0.45 + 0.17 * (noise["variant_index"] % len(CATALOG_VARIANTS))
                values = _perturb_numeric_values(values, factor)
                values["scope"] = noise["variant"]
                snapshots[source_ref] = ResourceSnapshot(
                    source_key=noise["resource"],
                    adapter=noise["adapter"],
                    resource=noise["resource"],
                    title=noise["title"],
                    description=noise["description"],
                    captured_at=as_of,
                    source_captured_at=as_of,
                    evidence=[{
                        "source_key": noise["resource"],
                        "subject_id": noise["resource"],
                        "statement": "Scoped source export; interpret using its catalog contract.",
                        "values": values,
                        "provenance": [source_ref],
                    }],
                    metadata={"tenant": scenario_id, "period_id": period_id,
                              "scope": noise["variant"]},
                ).model_dump(mode="json", exclude={"contract": {"available_comparison_windows"}})
            outcome = ("insufficient_data" if condition == "quality" else
                       "investigate" if condition == "event" and spec["family"] == "ops" else
                       "notify" if condition == "event" else "ignore")
            label = {"condition": condition, "outcome": outcome,
                     "recipients": [] if outcome == "ignore" else [data_route if condition == "quality" else route],
                     "required_evidence_refs": _required_evidence_refs(spec, payloads, refs),
                     "numeric_facts": facts,
                     "required_numeric_facts": required,
                     "allowed_claim_types": list(CLAIM_TYPES[:-1]),
                     "required_claim_types": ["association"] if spec["family"] == "ops" and condition == "event" else [],
                     "required_owner_topics": ["materiality"]}
            return {"period_id": period_id, "as_of": as_of.isoformat(), "snapshots": snapshots}, label

        onboarding, _ = period("quiet", base - timedelta(days=7))
        conditions = ["quiet", "event", "quality"]
        rng.shuffle(conditions)
        periods, labels = [], {}
        for index, condition in enumerate(conditions):
            public_period, label = period(condition, base + timedelta(days=index * 7))
            periods.append(public_period)
            labels[public_period["period_id"]] = label
        scenarios.append({
            "schema_version": SCHEMA_VERSION, "scorer_version": SCORER_VERSION,
            "scenario_id": scenario_id,
            "public": {"company": spec["company"], "brief": spec["brief"], "catalog": catalog,
                       "glossary": {spec["metric"]: spec["scope"], "unit": spec["unit"],
                                    "comparison": "Previous complete reporting week; source periods are UTC."},
                       "owner_topics": list(OWNER_TOPICS),
                       "owner_answers": {"metric_scope": spec["scope"], "materiality": spec["policy"],
                                         "routing": f"business destination: {route}; data destination: {data_route}. Only these routes are authorized; no destructive actions.",
                                         "data_gaps": "Ask for a corrected export or a versioned definition when needed. I cannot reconstruct missing rows, infer causation, or tell you a period's correct answer."},
                       "destinations": destinations, "onboarding": onboarding, "periods": periods,
                       "numeric_vocabulary": _numeric_vocabulary(spec),
                       "submission_contract": {"outcomes": ["ignore", "notify", "investigate", "insufficient_data"],
                                               "claim_types": list(CLAIM_TYPES),
                                               "number_units": [spec["unit"], "regions", "minutes"],
                                               "numeric_definitions": _numeric_definitions(spec)}},
            "private": {"family": spec["family"], "periods": labels},
        })
    return scenarios


def public_scenario(scenario: dict) -> dict:
    """Tool-server fixture export, NOT an agent prompt; contains future periods.

    Agent episodes must use ``public_episode`` and ``agent_context`` instead.
    Returned mutable data never aliases the original fixtures.
    """
    return copy.deepcopy({"scenario_id": scenario["scenario_id"], **scenario["public"]})


def public_episode(scenario: dict, period_id: str | None = None) -> dict:
    """Tool-server view limited to one episode; None means onboarding.

    Owner answers and current source payloads stay behind tools. This function
    does not even read the private labels or unselected snapshot payloads.
    """
    public = scenario["public"]
    current = public["onboarding"] if period_id is None else next(
        period for period in public["periods"] if period["period_id"] == period_id)
    return copy.deepcopy({"scenario_id": scenario["scenario_id"],
                          **{key: public[key] for key in (
                              "company", "brief", "catalog", "glossary", "owner_topics",
                              "owner_answers", "destinations", "numeric_vocabulary", "submission_contract")},
                          "period": current})


def agent_context(episode: dict) -> dict:
    """Opening prompt view; tools own source inspection and owner answers."""
    return copy.deepcopy({**{key: episode[key] for key in (
        "scenario_id", "company", "brief", "glossary", "owner_topics", "destinations",
        "numeric_vocabulary", "submission_contract")},
        "period_id": episode["period"]["period_id"], "as_of": episode["period"]["as_of"]})


def ask_owner(public: dict, topic: str) -> dict:
    """Policy lookup shared by both arms, not an outcome or missing-data oracle."""
    return {"topic": topic, "known": topic in public["owner_answers"],
            "answer": public["owner_answers"].get(topic, "Unknown. Please clarify which business policy you need; I cannot supply missing measurements.")}


class _NumericClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact: str
    value: StrictFloat | StrictInt
    unit: str
    evidence_refs: list[str] = Field(min_length=1, max_length=20)


class _Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_type: Literal["observation", "accounting_decomposition", "association", "hypothesis", "causal"]
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    statement: str = ""


class _Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["ignore", "notify", "investigate", "insufficient_data"]
    recipients: list[str] = Field(max_length=20)
    evidence_refs: list[str] = Field(max_length=100)
    numeric_claims: list[_NumericClaim] = Field(default_factory=list, max_length=100)
    claims: list[_Claim] = Field(default_factory=list, max_length=100)
    summary: str = ""


def _is_finite_number(value: Any) -> bool:
    """Check math-compatible numeric bounds independently of schema acceptance.

    StrictInt accepts arbitrary Python integers, but math functions convert them
    to floats and can overflow. Non-numbers and unrepresentable values fail closed.
    """
    if type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def score_submission(scenario: dict, period_id: str, submission: dict, *,
                     inspected_refs: list[str] | set[str],
                     asked_owner_topics: list[str] | set[str]) -> dict[str, Any]:
    """Score a final structured submission against private independent labels.

    ``inspected_refs`` must be runner-observed successful reads *in this period*,
    not a list supplied by the model. Cached reads qualify only for this snapshot.
    This checks typed causal claims, not arbitrary prose entailment.
    Invalid submissions leave compatibility safety flags unchanged and mark
    safety_unassessed; those flags must not be interpreted as a safe result.
    """
    label = scenario["private"]["periods"][period_id]
    period = next(p for p in scenario["public"]["periods"] if p["period_id"] == period_id)
    allowed = set(period["snapshots"])
    required = set(label["required_evidence_refs"])
    expected_routes = set(label["recipients"])
    report = {"scorer_version": SCORER_VERSION,
              "scenario_id": scenario["scenario_id"], "period_id": period_id,
              "valid_submission": False, "safety_unassessed": True,
              "exact": False, "outcome_correct": False,
              "recipients_correct": False, "wrong_recipient": False, "unsafe_route": False,
              "false_alert": False, "missed_event": False, "unsafe_suppression": False,
              "evidence_recall": 0.0, "provenance_complete": False,
              "numeric_precision": 0.0, "numeric_recall": 0.0,
              "unsupported_numeric_facts": [], "unsupported_claim_types": [],
              "numeric_diagnostics": [], "citation_diagnostics": [], "missing_numeric_facts": [],
              "owner_policy_complete": False, "errors": [],
              "scoring_scope": "structured_fields_only", "narrative_review_required": True}
    try:
        parsed = _Submission.model_validate(submission)
    except (ValidationError, OverflowError):
        report["errors"] = ["invalid_submission_schema"]
        return report
    report["valid_submission"] = True
    report["safety_unassessed"] = False
    recipients = set(parsed.recipients)
    evidence = set(parsed.evidence_refs)
    cited = evidence | {ref for n in parsed.numeric_claims for ref in n.evidence_refs}
    cited |= {ref for c in parsed.claims for ref in c.evidence_refs}
    inspected = set(inspected_refs) & allowed
    report["outcome_correct"] = parsed.outcome == label["outcome"]
    report["recipients_correct"] = recipients == expected_routes
    report["wrong_recipient"] = bool(recipients - expected_routes)
    report["unsafe_route"] = bool(recipients - expected_routes)
    report["false_alert"] = parsed.outcome in {"notify", "investigate"} and label["outcome"] in {"ignore", "insufficient_data"}
    report["missed_event"] = label["condition"] == "event" and parsed.outcome in {"ignore", "insufficient_data"}
    report["unsafe_suppression"] = parsed.outcome == "ignore" and label["outcome"] == "insufficient_data"
    report["evidence_recall"] = len(evidence & required & inspected) / len(required)
    report["provenance_complete"] = bool(evidence) and cited <= inspected and cited <= evidence
    report["owner_policy_complete"] = set(label["required_owner_topics"]) <= set(asked_owner_topics)

    def check_citations(location: str, refs: set[str], dependencies: set[str]) -> bool:
        failures = {"unknown_refs": sorted(refs - allowed),
                    "uninspected_refs": sorted((refs & allowed) - inspected),
                    "unlisted_refs": sorted(refs - evidence),
                    "missing_required_refs": sorted(dependencies - refs)}
        if any(failures.values()):
            report["citation_diagnostics"].append({"location": location, **failures})
            return False
        return True

    check_citations("evidence_refs", evidence, required)
    for index, claim in enumerate(parsed.claims):
        check_citations(f"claims[{index}].evidence_refs", set(claim.evidence_refs), set())
    vocabulary = set(scenario["public"]["numeric_vocabulary"])
    correct, seen, bad = set(), set(), []
    for index, claim in enumerate(parsed.numeric_claims):
        oracle = label["numeric_facts"].get(claim.fact)
        reasons = []
        if claim.fact not in vocabulary:
            reasons.append("unknown_identifier")
        elif oracle is None:
            reasons.append("unavailable_scope")
        finite = _is_finite_number(claim.value)
        if not finite:
            reasons.append("nonfinite_value")
        if oracle is not None:
            if claim.unit != oracle["unit"]:
                reasons.append("wrong_unit")
            if finite and not math.isclose(claim.value, oracle["value"], rel_tol=1e-9,
                                           abs_tol=oracle["absolute_tolerance"]):
                reasons.append("wrong_value")
        if not check_citations(f"numeric_claims[{index}].evidence_refs", set(claim.evidence_refs),
                               set(oracle["evidence_refs"]) if oracle else set()):
            reasons.append("invalid_citations")
        if claim.fact in seen:
            reasons.append("duplicate_fact")
        seen.add(claim.fact)
        if not reasons:
            correct.add(claim.fact)
        else:
            bad.append(claim.fact)
            report["numeric_diagnostics"].append({"claim_index": index, "fact": claim.fact,
                                                  "reasons": reasons})
    numerical_required = set(label["required_numeric_facts"])
    report["numeric_precision"] = len(correct) / len(parsed.numeric_claims) if parsed.numeric_claims else (1.0 if not numerical_required else 0.0)
    report["numeric_recall"] = len(correct & numerical_required) / len(numerical_required) if numerical_required else 1.0
    report["unsupported_numeric_facts"] = bad
    report["missing_numeric_facts"] = sorted(numerical_required - correct)
    claim_types = {c.claim_type for c in parsed.claims}
    report["unsupported_claim_types"] = sorted(claim_types - set(label["allowed_claim_types"]))
    if len(parsed.recipients) != len(recipients):
        report["errors"].append("duplicate_recipient")
    if not set(label["required_claim_types"]) <= claim_types:
        report["errors"].append("missing_explanation_claim_type")
    if not report["owner_policy_complete"]:
        report["errors"].append("missing_owner_policy_lookup")
    report["exact"] = bool(report["outcome_correct"] and report["recipients_correct"]
                           and report["provenance_complete"] and report["evidence_recall"] == 1
                           and report["numeric_recall"] == 1 and not bad
                           and not report["unsupported_claim_types"] and not report["errors"])
    return report


def dataset_digest(scenarios: list[dict]) -> str:
    """Freeze the full fixtures (including labels) before a measured run."""
    import json

    return hashlib.sha256(json.dumps(scenarios, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

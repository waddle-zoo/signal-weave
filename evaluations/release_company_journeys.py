"""Synthetic report-first onboarding journeys for a bounded release pilot.

The six onboarding stories and 24 later episodes are evaluation fixtures, not
production company data.  Agents receive only :func:`public_episode`; private
labels and owner-service answers are passed to the scorer/owner tool separately.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from signalweave.models import ResourceDescriptor, ResourceSnapshot

VERSION = "release-company-journeys-v1"
SEED = 20261012
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS = REPO_ROOT / "artifacts" / "release-company-journeys-2026-10-12"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "xhigh"
DEFAULT_PROFILE = "agent"
AGENT_TOOLS = (
    "get_signalweave_guide",
    "search_catalog",
    "inspect_resource",
    "onboard_insight_card",
    "review_insight_card",
    "approve_insight_card",
    "list_insight_cards",
    "get_insight_card",
    "evaluate_insight_card",
    "get_decision_receipt",
)
SOURCE_TOOLS = (
    "list_catalog", "search_catalog", "inspect_resource", "inspect_source",
    "analyze_source", "calculate", "ask_owner",
)
ARMS = ("luna_control", "luna_signalweave")
MAX_REPORT_CHARS = 1_200
CERTIFIED_BINARY_SHA256 = "6abe5f0e292a688a30c139f917e98cd6635bb4b6bb974597f23e3edfcda9d7b5"
CERTIFIED_SOURCE_SHA256 = "9460d2e8e08a3e06de7309cf6c8d554b17043074d8fa9fe7fbdcee972c1298e2"
CERTIFIED_VERSION = "0.2.0rc2"
ACTIVE_PARENT_CERTIFICATE: dict[str, str] | None = {
    "binary_sha256": CERTIFIED_BINARY_SHA256,
    "source_sha256": CERTIFIED_SOURCE_SHA256,
    "version": CERTIFIED_VERSION,
}

# All six briefs begin with a vague human question.  The current snapshot is
# useful enough for a scoped report, even if it is not sufficient to authorize
# unattended alerting.  Later episodes intentionally vary definition, window,
# source overlap, change magnitude, source errors and unresolved facts.
# These owner-persona responses and rules are authored independently from the
# episode labels. They become available only after a first report and an
# explicit ask_owner call; they authorize synthetic shadow recommendations,
# never external delivery or real customer approval.
_SYNTHETIC_OWNER_HIL: dict[str, dict[str, Any]] = {
    "journey-01": {
        "answers": {"materiality": {
            "known": True,
            "answer": "For a shadow review, flag net revenue retention declines of at least 5 percentage points over the previous complete seven days. Share a recommendation with Customer Success; do not page or send automatically.",
        }},
    },
    "journey-02": {
        "answers": {
            "materiality": {
                "known": True,
                "answer": "For a shadow review, flag weighted open pipeline declines of at least 20% when at least five late-stage opportunities slip in the same complete week.",
            },
            "routing": {
                "known": True,
                "answer": "Revenue Operations is the review owner. Keep the recommendation in the report; no on-call page or external delivery is authorized.",
            },
        },
    },
    "journey-04": {
        "answers": {"materiality": {
            "known": True,
            "answer": "For a shadow review, flag a decline of at least 5 percentage points in renewal rate after finalized refunds over the previous complete seven days. Do not notify automatically.",
        }},
    },
    "journey-06": {
        "answers": {
            "materiality": {
                "known": True,
                "answer": "For a shadow review, flag server-side p95 query latency rising at least 40% across at least three customer regions when replication lag exceeds five seconds.",
            },
            "routing": {
                "known": True,
                "answer": "Database Performance On-call reviews the recommendation. This is not permission to page or deliver automatically.",
            },
        },
    },
}

# Executable versions of the independently authored owner rules above and the
# already-known policies for journeys 03/05. The scorer derives warm outcomes
# from source facts and these rules, never from observation["decision"].
_OWNER_POLICY_RULES: dict[str, dict[str, Any]] = {
    "journey-01": {"kind": "decline_points", "threshold": 5},
    "journey-02": {"kind": "relative_decline_and_slips", "threshold_pct": 20,
                   "minimum_slips": 5},
    "journey-03": {"kind": "failed_held_share", "threshold_pct": 5},
    "journey-04": {"kind": "decline_points", "threshold": 5},
    "journey-05": {"kind": "decline_points_and_lanes", "threshold": 5,
                   "minimum_lanes": 3},
    "journey-06": {"kind": "latency_regions_lag", "threshold_pct": 40,
                   "minimum_regions": 3, "minimum_lag_seconds": 5},
}

_COMPANIES: tuple[dict[str, Any], ...] = (
    {
        "scenario_id": "journey-01",
        "company": "Arcwell Cloud",
        "family": "saas_customer_health",
        "brief": "I just connected our analytics. Why did customer health change? Give me the useful current picture first; we can decide later whether any part should page someone.",
        "metric": "net revenue retention",
        "unit": "percent",
        "population": "paid customer accounts active at the start of the comparison window",
        "window": "previous_7_days",
        "owner": "Customer Success",
        "owner_key": "customer-success",
        "destination": "team://customer-success",
        "sources": (
            {"slot": "health", "adapter": "superset", "resource": "chart:2101", "kind": "chart", "title": "Customer Health", "description": "Customer health trend; chart title is not a metric definition.", "scope": "current paid accounts"},
            {"slot": "renewals", "adapter": "stripe", "resource": "renewal-cohorts", "kind": "report", "title": "Renewal and expansion cohorts", "description": "Renewals, expansions and cancellations by account cohort.", "scope": "billing events"},
            {"slot": "archive", "adapter": "superset", "resource": "chart:2101-archive", "kind": "chart", "title": "Customer Health", "description": "Archived chart using a legacy 28-day cohort and a different population.", "scope": "legacy 28-day archive"},
        ),
        "onboarding": {"baseline": 104.0, "current": 101.5, "window": "Last 7 days", "context": (
            ("renewals", "Expansion revenue eased while paid-account renewals remained broadly steady.", {"expansion_usd": 91_000, "renewals": 482}),
            ("renewals", "The current export covers paid accounts; trial accounts are not in this cohort.", {"population": "paid_accounts"}),
        )},
        "episodes": (
            {"baseline": 101.5, "current": 101.8, "window": "Last 7 days", "context": (("renewals", "Renewal and expansion mix is close to the prior week.", {"renewals": 486, "expansion_usd": 92_400}),), "decision": "ignore", "required": ("health", "renewals"), "recipient": [], "clarification": (), "gap": None, "driver": "stable paid-account renewals"},
            {"baseline": 105.2, "current": 89.4, "window": "Last 7 days", "context": (("renewals", "Paid-account cancellations rose and expansion bookings fell in the current cohort.", {"cancellations": 41, "expansion_usd": 54_000}),), "decision": "notify", "required": ("health", "renewals"), "recipient": ["customer-success"], "clarification": (), "gap": None, "driver": "more cancellations and lower expansion"},
            {"baseline": 104.0, "current": 91.0, "window": "Last 7 days", "window_conflict": {"health": "rolling_7_days", "renewals": "calendar_month"}, "context": (("renewals", "The billing export is a calendar-month renewal cohort, not the rolling seven-day chart cohort.", {"billing_window": "calendar_month", "chart_window": "rolling_7_days"}),), "decision": "insufficient_data", "required": ("health", "renewals"), "recipient": [], "clarification": ("comparison_window",), "gap": "The source views use different renewal windows and cannot be reconciled from these snapshots.", "driver": "conflicting calendar-month and rolling-week windows"},
            {"baseline": 102.1, "current": 92.0, "window": "Last 7 days", "missing": {"slot": "renewals", "fields": ["eligible_account_id"]}, "snapshot_error": {"slot": "renewals", "type": "partial_account_cohort_export"}, "context": (("renewals", "The cohort export omits the account eligibility join for this refresh.", {"available_fields": ["renewal_amount", "refund_amount"], "unavailable_field": "eligible_account_id"}),), "decision": "insufficient_data", "required": ("health", "renewals"), "recipient": [], "clarification": ("eligible_account_cohort",), "gap": "Eligible-account linkage is missing; the displayed ratio is not validated as paid-customer retention.", "driver": "missing eligible-account linkage"},
        ),
        "owner_answers": {
            "metric_definition": {"known": True, "answer": "Use net revenue retention for paid accounts active at the start of the window; trials are excluded."},
            "time_window": {"known": True, "answer": "Use the previous complete seven-day period for recurring comparisons."},
            "materiality": {"known": False, "answer": "We have no approved automatic alert threshold. Report useful changes; ask Customer Success before enabling alerts."},
            "routing": {"known": True, "answer": "Customer Success owns follow-up. Do not page the team until a threshold is approved."},
        },
        "onboarding_label": {"required": ("health", "renewals"), "scope": "paid customer accounts", "window": "previous 7 days", "drivers": ("expansion", "renewal"), "alert_topics_missing": ("materiality",), "expected_recipient": "customer-success"},
    },
    {
        "scenario_id": "journey-02",
        "company": "FathomWorks",
        "family": "b2b_weighted_pipeline",
        "brief": "Why did sales change this week? Start with a useful read of the pipeline we have, then tell me only what you still need before recurring alerts.",
        "metric": "probability-weighted open pipeline",
        "unit": "USD",
        "population": "open opportunities with an active sales stage and a close date in the selected period",
        "window": "previous_7_days",
        "owner": "Revenue Operations",
        "owner_key": "revenue-operations",
        "destination": "team://revenue-operations",
        "sources": (
            {"slot": "pipeline", "adapter": "superset", "resource": "chart:3201", "kind": "chart", "title": "Weighted Pipeline", "description": "Pipeline chart with a saved probability transform; inspect the underlying stage inputs.", "scope": "open opportunities"},
            {"slot": "crm", "adapter": "salesforce", "resource": "opportunities", "kind": "report", "title": "Opportunity stage ledger", "description": "Open opportunity amount, stage, probability, owner and close-date fields.", "scope": "active CRM opportunities"},
            {"slot": "forecast", "adapter": "superset", "resource": "chart:3201-forecast", "kind": "chart", "title": "Weighted Pipeline", "description": "Planning forecast with a different probability table and future close dates.", "scope": "forecast scenario"},
        ),
        "onboarding": {"baseline": 12_400_000, "current": 11_650_000, "window": "Last 7 days", "context": (
            ("crm", "Gross open opportunity value increased, while weighted value fell as late-stage deals moved to earlier stages.", {"gross_open_usd": 18_900_000, "weighted_open_usd": 11_650_000, "stage_mix_shift": "late_to_early"}),
            ("crm", "The dashboard excludes closed-lost records and uses CRM stage probabilities.", {"population": "open_opportunities", "probability_version": "crm-current"}),
        )},
        "episodes": (
            {"baseline": 11_650_000, "current": 11_820_000, "window": "Last 7 days", "context": (("crm", "Stage and close-date mix is near the preceding week; no broad slippage is present.", {"late_stage_share": 0.42, "slipped_opportunities": 3}),), "decision": "ignore", "required": ("pipeline", "crm"), "recipient": [], "clarification": (), "gap": None, "driver": "little stage-mix movement"},
            {"baseline": 13_100_000, "current": 9_250_000, "window": "Last 7 days", "context": (("crm", "Several large late-stage opportunities slipped their close dates and moved into lower-probability stages.", {"slipped_opportunities": 14, "slipped_usd": 3_600_000}),), "decision": "notify", "required": ("pipeline", "crm"), "recipient": ["revenue-operations"], "clarification": (), "gap": None, "driver": "late-stage close-date slippage"},
            {"baseline": 12_400_000, "current": 10_100_000, "window": "Last 7 days", "window_conflict": {"pipeline": "rolling_7_days", "forecast": "next_quarter"}, "context": (("crm", "The CRM export uses current stage probabilities; the planning chart uses a forecast override and includes next-quarter deals.", {"crm_probability_version": "current", "forecast_probability_version": "planning-v3", "forecast_window": "next_quarter"}),), "decision": "insufficient_data", "required": ("pipeline", "crm", "forecast"), "recipient": [], "clarification": ("weighted_pipeline_definition", "comparison_window"), "gap": "The two weighted-pipeline charts apply different probability tables and close-date windows.", "driver": "probability table and close-date window differ"},
            {"baseline": 11_900_000, "current": 8_800_000, "window": "Last 7 days", "missing": {"slot": "crm", "fields": ["owner_id", "close_date"]}, "snapshot_error": {"slot": "crm", "type": "partial_opportunity_export"}, "context": (("crm", "The export is missing owner and close-date fields for a subset of open opportunities.", {"rows_missing_owner": 17, "rows_missing_close_date": 9}),), "decision": "insufficient_data", "required": ("pipeline", "crm"), "recipient": [], "clarification": ("crm_field_completeness",), "gap": "Missing close-date and owner fields prevent a reliable eligible-opportunity comparison.", "driver": "incomplete opportunity fields"},
        ),
        "owner_answers": {
            "metric_definition": {"known": True, "answer": "Weighted pipeline means open opportunity amount multiplied by the current CRM stage probability."},
            "time_window": {"known": True, "answer": "Use the prior complete seven-day period, based on the CRM close-date and stage snapshot."},
            "materiality": {"known": False, "answer": "We have no signed alert threshold yet; do not turn a report into an automatic notify."},
            "routing": {"known": False, "answer": "Revenue Operations owns the analysis, but the on-call recipient has not been approved."},
        },
        "onboarding_label": {"required": ("pipeline", "crm"), "scope": "open active CRM opportunities", "window": "previous 7 days", "drivers": ("gross_open_usd", "stage_mix_shift"), "alert_topics_missing": ("materiality", "routing"), "expected_recipient": "revenue-operations"},
    },
    {
        "scenario_id": "journey-03",
        "company": "OpenHarbor Market",
        "family": "marketplace_payouts",
        "brief": "Payouts look different from last week. What is actually changing for sellers, and what should our finance team do next?",
        "metric": "seller payouts settled",
        "unit": "USD",
        "population": "seller payout batches settled by the processor before the cutoff",
        "window": "previous_7_days",
        "owner": "Marketplace Finance",
        "owner_key": "marketplace-finance",
        "destination": "team://marketplace-finance",
        "sources": (
            {"slot": "payouts", "adapter": "superset", "resource": "chart:4301", "kind": "chart", "title": "Seller Payouts", "description": "Seller payout chart; distinguish initiated, settled and reversed amounts.", "scope": "processor payout batches"},
            {"slot": "ledger", "adapter": "stripe", "resource": "payout-ledger", "kind": "report", "title": "Processor payout ledger", "description": "Batch state, seller, settled amount, reversals and processor timestamps.", "scope": "processor ledger"},
            {"slot": "reconciliation", "adapter": "warehouse", "resource": "seller-settlement-reconciliation", "kind": "table", "title": "Seller payout reconciliation", "description": "Warehouse reconciliation with settlement cutoff and refund adjustments.", "scope": "finance close"},
        ),
        "onboarding": {"baseline": 8_420_000, "current": 8_980_000, "window": "Last 7 days", "context": (
            ("ledger", "Settled volume rose, but the initiated-to-settled gap also widened for a small group of sellers.", {"initiated_usd": 9_440_000, "settled_usd": 8_980_000, "pending_sellers": 126}),
            ("reconciliation", "Amounts are before the monthly reserve release and do not include the next-day refund adjustment.", {"cutoff": "processor_settlement_time", "refund_adjustment": "next_day"}),
        )},
        "episodes": (
            {"baseline": 8_980_000, "current": 9_020_000, "window": "Last 7 days", "context": (("ledger", "Settled and initiated batches remain close to the prior complete week.", {"failed_batches": 22, "settled_batches": 18_431}),), "decision": "ignore", "required": ("payouts", "ledger"), "recipient": [], "clarification": (), "gap": None, "driver": "settled batch totals are steady"},
            {"baseline": 9_020_000, "current": 7_480_000, "window": "Last 7 days", "context": (("ledger", "Failed and held batches rose across multiple seller groups; together they exceed the approved 5% share of all seller batches.", {"failed_batches": 684, "held_batches": 311, "seller_batches": 16_400, "initiated_usd": 9_610_000}), ("reconciliation", "The same-period seller-batch denominator is complete through the processor cutoff.", {"seller_batches": 16_400, "cutoff": "processor_settlement_time"})), "decision": "notify", "required": ("payouts", "ledger", "reconciliation"), "recipient": ["marketplace-finance"], "clarification": (), "gap": None, "driver": "more failed and held seller batches"},
            {"baseline": 8_420_000, "current": 7_910_000, "window": "Last 7 days", "definition_conflict": {"payouts": "initiated", "ledger": "settled"}, "context": (("reconciliation", "The chart counts initiated batches while the ledger total counts settled batches; both use a rolling seven-day window.", {"chart_state": "initiated", "ledger_state": "settled"}),), "decision": "insufficient_data", "required": ("payouts", "ledger"), "recipient": [], "clarification": ("payout_state_definition",), "gap": "Initiated and settled payout amounts are different states and cannot be treated as one comparable series.", "driver": "payout state differs between sources"},
            {"baseline": 8_900_000, "current": 7_100_000, "window": "Last 7 days", "missing": {"slot": "reconciliation", "fields": ["bank_cutoff_utc", "refund_partition_close"]}, "snapshot_error": {"slot": "reconciliation", "type": "partial_finance_reconciliation"}, "context": (("reconciliation", "The bank settlement cutoff is absent from this export; a partial refresh also omitted the refund-adjustment partition.", {"unavailable_fields": ["bank_cutoff_utc", "refund_partition_close"]}),), "decision": "insufficient_data", "required": ("payouts", "reconciliation"), "recipient": [], "clarification": ("bank_settlement_cutoff",), "gap": "The bank cutoff and refund-partition closure are missing, so the settled total is not validated.", "driver": "missing settlement cutoff and refund partition"},
        ),
        "owner_answers": {
            "metric_definition": {"known": True, "answer": "Count seller payout amounts only when the processor marks them settled; exclude initiated and reversed batches."},
            "time_window": {"known": True, "answer": "Use previous complete seven-day processor settlement time."},
            "materiality": {"known": True, "answer": "Escalate when failed plus held payout batches together exceed 5% of all seller batches in the same complete week; otherwise summarize."},
            "routing": {"known": True, "answer": "Marketplace Finance owns payout follow-up at team://marketplace-finance."},
        },
        "onboarding_label": {"required": ("payouts", "ledger", "reconciliation"), "scope": "processor-settled seller batches", "window": "previous 7 days", "drivers": ("initiated_usd", "pending_sellers"), "alert_topics_missing": (), "expected_recipient": "marketplace-finance"},
    },
    {
        "scenario_id": "journey-04",
        "company": "LumenBox",
        "family": "subscription_renewals_refunds",
        "brief": "Our renewal and refund numbers moved. Explain what happened in a way I can use, before we set up recurring alerts.",
        "metric": "subscription renewal rate net of finalized refunds",
        "unit": "percent",
        "population": "subscriptions eligible to renew during the comparison period; refunds counted when finalized",
        "window": "previous_7_days",
        "owner": "Subscription Operations",
        "owner_key": "subscription-operations",
        "destination": "team://subscription-operations",
        "sources": (
            {"slot": "renewals", "adapter": "superset", "resource": "chart:5401", "kind": "chart", "title": "Renewal Performance", "description": "Renewal cohort dashboard with refund overlays.", "scope": "renewal-eligible subscriptions"},
            {"slot": "billing", "adapter": "stripe", "resource": "subscription-events", "kind": "report", "title": "Subscription renewal and refund events", "description": "Renewal attempts, grace windows, cancellation and finalized refund events.", "scope": "billing events"},
            {"slot": "archive", "adapter": "superset", "resource": "chart:5401-archive", "kind": "chart", "title": "Renewal Performance", "description": "Prior dashboard includes grace-period retries and excludes refunds finalized after month end.", "scope": "legacy renewal definition"},
        ),
        "onboarding": {"baseline": 92.4, "current": 90.7, "window": "Last 7 days", "context": (
            ("billing", "Renewal attempts were nearly flat; finalized refunds increased mostly in annual plans.", {"renewal_attempts": 12_604, "finalized_refunds": 318, "annual_plan_refunds": 207}),
            ("billing", "Retries still inside the stated grace window are not final failures.", {"grace_days": 5, "pending_retries": 146}),
        )},
        "episodes": (
            {"baseline": 90.7, "current": 90.9, "window": "Last 7 days", "context": (("billing", "Finalized refunds and renewal attempts are close to the prior week.", {"finalized_refunds": 321, "renewal_attempts": 12_710}),), "decision": "ignore", "required": ("renewals", "billing"), "recipient": [], "clarification": (), "gap": None, "driver": "renewals and finalized refunds are steady"},
            {"baseline": 92.1, "current": 83.6, "window": "Last 7 days", "context": (("billing", "Finalized refunds rose sharply after a price-plan migration; pending grace retries remain separate.", {"finalized_refunds": 1_128, "migration_refunds": 704, "pending_retries": 208}),), "decision": "notify", "required": ("renewals", "billing"), "recipient": ["subscription-operations"], "clarification": (), "gap": None, "driver": "finalized refunds after plan migration"},
            {"baseline": 92.4, "current": 88.2, "window": "Last 7 days", "window_conflict": {"renewals": "calendar_month", "billing": "rolling_7_days"}, "definition_conflict": {"renewals": "grace_included", "billing": "grace_excluded"}, "context": (("billing", "The chart includes grace-period retries and uses calendar months; the event export excludes retries and uses rolling seven-day windows.", {"chart_window": "calendar_month", "event_window": "rolling_7_days", "chart_grace": "included", "events_grace": "excluded"}),), "decision": "insufficient_data", "required": ("renewals", "billing"), "recipient": [], "clarification": ("renewal_grace_definition", "comparison_window"), "gap": "The source views disagree on grace-period treatment and calendar window.", "driver": "grace-period and time-window definitions differ"},
            {"baseline": 91.8, "current": 84.1, "window": "Last 7 days", "missing": {"slot": "billing", "fields": ["refund_partition_close"]}, "snapshot_error": {"slot": "billing", "type": "refund_partition_not_closed"}, "context": (("billing", "A delayed processor partition containing finalized refunds has not closed.", {"partition": "refund_finalization", "status": "open", "missing_rows_estimate": 74}),), "decision": "insufficient_data", "required": ("renewals", "billing"), "recipient": [], "clarification": ("refund_partition_close",), "gap": "The finalized-refund partition is still open; the observed renewal rate is provisional.", "driver": "open refund-finalization partition"},
        ),
        "owner_answers": {
            "metric_definition": {"known": True, "answer": "A renewal succeeds when the eligible subscription is paid after retries; subtract only finalized refunds. The grace period is five days."},
            "time_window": {"known": True, "answer": "Use previous complete seven-day billing-event time."},
            "materiality": {"known": False, "answer": "No alert threshold has been approved. Summaries are useful now; do not enable unattended notifications."},
            "routing": {"known": True, "answer": "Subscription Operations owns investigation at team://subscription-operations."},
        },
        "onboarding_label": {"required": ("renewals", "billing"), "scope": "eligible subscriptions; finalized refunds only", "window": "previous 7 days", "drivers": ("finalized_refunds", "annual_plan_refunds"), "alert_topics_missing": ("materiality",), "expected_recipient": "subscription-operations"},
    },
    {
        "scenario_id": "journey-05",
        "company": "Redwood Freight",
        "family": "logistics_operations",
        "brief": "On-time performance looks worse. Tell me what the sources actually show, and what action is useful right now.",
        "metric": "on-time delivery rate",
        "unit": "percent",
        "population": "shipments delivered with a valid proof-of-delivery scan and a customer-promised timestamp",
        "window": "previous_7_days",
        "owner": "Network Operations",
        "owner_key": "network-operations",
        "destination": "team://network-operations",
        "sources": (
            {"slot": "sla", "adapter": "superset", "resource": "chart:6501", "kind": "chart", "title": "On-Time Delivery", "description": "Carrier performance snapshot grouped by operating lane.", "scope": "delivered shipments"},
            {"slot": "scans", "adapter": "carrier", "resource": "shipment-scans", "kind": "report", "title": "Shipment scan events", "description": "Pickup, arrival and proof-of-delivery events with carrier and lane IDs.", "scope": "carrier scan records"},
            {"slot": "promises", "adapter": "warehouse", "resource": "delivery-promises", "kind": "table", "title": "Customer delivery promises", "description": "Original promised timestamp and later customer ETA changes.", "scope": "customer-facing delivery commitments"},
        ),
        "onboarding": {"baseline": 96.1, "current": 92.8, "window": "Last 7 days", "context": (
            ("scans", "Most of the observed decline is concentrated in two regional lanes with late arrival scans.", {"affected_lanes": 2, "late_arrivals": 384}),
            ("promises", "The dashboard compares final delivery to the original promise; changed customer ETAs are shown separately.", {"promise_field": "original_promised_at", "eta_field": "customer_eta"}),
        )},
        "episodes": (
            {"baseline": 92.8, "current": 93.0, "window": "Last 7 days", "context": (("scans", "Lane-level delay mix is close to the previous week.", {"late_lanes": 2, "late_shipments": 371}),), "decision": "ignore", "required": ("sla", "scans", "promises"), "recipient": [], "clarification": (), "gap": None, "driver": "lane delays are near baseline"},
            {"baseline": 96.0, "current": 81.7, "window": "Last 7 days", "context": (("scans", "Late arrival and missed handoff scans increased across four high-volume lanes.", {"affected_lanes": 4, "late_shipments": 1_842, "missed_handoffs": 316}),), "decision": "notify", "required": ("sla", "scans", "promises"), "recipient": ["network-operations"], "clarification": (), "gap": None, "driver": "late arrivals and missed handoffs across four lanes"},
            {"baseline": 95.6, "current": 84.2, "window": "Last 7 days", "window_conflict": {"sla": "rolling_7_days", "scans": "calendar_week"}, "definition_conflict": {"sla": "customer_eta", "scans": "original_promised_at"}, "context": (("promises", "The chart uses customer ETA while the carrier export compares against the original promised timestamp; one view uses a rolling week and the other a calendar week.", {"chart_time": "rolling_7_days", "carrier_time": "calendar_week", "chart_deadline": "customer_eta", "carrier_deadline": "original_promised_at"}),), "decision": "insufficient_data", "required": ("sla", "scans", "promises"), "recipient": [], "clarification": ("on_time_definition", "comparison_window"), "gap": "The compared deadlines and calendar windows differ; the two reported rates are not directly comparable.", "driver": "deadline field and calendar window mismatch"},
            {"baseline": 94.8, "current": 82.3, "window": "Last 7 days", "missing": {"slot": "scans", "fields": ["proof_of_delivery_scan"]}, "snapshot_error": {"slot": "scans", "type": "partial_carrier_feed"}, "context": (("scans", "A carrier feed is missing proof-of-delivery scans for part of the active population.", {"missing_pod_scans": 528, "feed_status": "partial"}),), "decision": "insufficient_data", "required": ("sla", "scans"), "recipient": [], "clarification": ("proof_of_delivery_feed",), "gap": "Missing proof-of-delivery records leave the delivered-shipment denominator incomplete.", "driver": "partial carrier proof-of-delivery feed"},
        ),
        "owner_answers": {
            "metric_definition": {"known": True, "answer": "On time means final proof-of-delivery at or before the original customer promise. Exclude shipments without a valid proof-of-delivery scan from the denominator only when separately disclosed."},
            "time_window": {"known": True, "answer": "Use the previous complete seven-day delivery timestamp window."},
            "materiality": {"known": True, "answer": "Escalate a decline over 5 percentage points if it affects at least three operating lanes."},
            "routing": {"known": True, "answer": "Network Operations owns lane follow-up at team://network-operations."},
        },
        "onboarding_label": {"required": ("sla", "scans", "promises"), "scope": "shipments with valid proof-of-delivery and original customer promise", "window": "previous 7 days", "drivers": ("affected_lanes", "late_arrivals"), "alert_topics_missing": (), "expected_recipient": "network-operations"},
    },
    {
        "scenario_id": "journey-06",
        "company": "Cinderpeak Data",
        "family": "documentdb_performance",
        "brief": "Database performance changed. What is customer-impacting, what looks local, and who needs to act?",
        "metric": "DocumentDB p95 query latency",
        "unit": "milliseconds",
        "population": "production clusters serving customer traffic in the selected regions",
        "window": "previous_60_minutes",
        "owner": "Database Performance On-call",
        "owner_key": "database-performance-oncall",
        "destination": "team://database-performance-oncall",
        "sources": (
            {"slot": "latency", "adapter": "cloudwatch", "resource": "metric-group:docdb-performance", "kind": "metric_group", "title": "DocumentDB Customer Performance", "description": "Latency, replication lag, throttling and storage pressure across production clusters.", "scope": "customer-serving clusters"},
            {"slot": "deployments", "adapter": "deployments", "resource": "service:docdb", "kind": "change_log", "title": "DocumentDB deployment timeline", "description": "Deployment start and completion times by service and region.", "scope": "production deployments"},
            {"slot": "cpu", "adapter": "cloudwatch", "resource": "metric:docdb-cpu-one-cluster", "kind": "metric", "title": "DocumentDB CPU utilization", "description": "Single-cluster CPU utilization; an isolated CPU spike is not a customer-impact measure.", "scope": "one cluster"},
        ),
        "onboarding": {"baseline": 105.0, "current": 117.0, "window": "Previous 60 minutes", "context": (
            ("latency", "The p95 increase is visible across three customer regions; replication lag and throttling remain near their recent ranges.", {"regions": 3, "clusters": 8, "replication_lag_seconds": 2.7, "throttled_requests": 534}),
            ("deployments", "A regional index rollout completed shortly before the latency increase; timing alone does not establish cause.", {"deployment": "index-rollout", "lead_minutes": 18}),
        )},
        "episodes": (
            {"baseline": 117.0, "current": 119.0, "window": "Previous 60 minutes", "context": (("cpu", "CPU rose on one cluster; customer-facing p95 latency and lag stayed close to the preceding hour.", {"cluster_count": 1, "cpu_pct": 91, "regions_affected": 1}),), "decision": "ignore", "required": ("latency", "cpu"), "recipient": [], "clarification": (), "gap": None, "driver": "isolated CPU increase without broad customer impact"},
            {"baseline": 104.0, "current": 168.0, "window": "Previous 60 minutes", "context": (("latency", "Latency and replication lag increased across three regions and eight production clusters.", {"regions": 3, "clusters": 8, "replication_lag_seconds": 8.1, "throttled_requests": 1_462}), ("deployments", "A shared index rollout preceded the cross-region increase by 21 minutes.", {"deployment": "index-rollout", "lead_minutes": 21})), "decision": "notify", "required": ("latency", "deployments"), "recipient": ["database-performance-oncall"], "clarification": (), "gap": None, "driver": "correlated latency, lag and throttling after a rollout"},
            {"baseline": 106.0, "current": 143.0, "window": "Previous 60 minutes", "window_conflict": {"latency": "server_5m", "deployments": "client_1h"}, "definition_conflict": {"latency": "server_side", "deployments": "client_side"}, "context": (("latency", "One chart reports server-side p95 over five minutes; another reports client-side p95 over one hour.", {"server_window": "5m", "client_window": "1h", "measurement_point": "different"}),), "decision": "insufficient_data", "required": ("latency", "deployments"), "recipient": [], "clarification": ("latency_measurement_point", "comparison_window"), "gap": "Latency measurement point and aggregation windows differ, so the p95 values cannot be combined.", "driver": "client/server measurement and window mismatch"},
            {"baseline": 109.0, "current": 159.0, "window": "Previous 60 minutes", "missing": {"slot": "deployments", "fields": ["cluster_region_mapping"]}, "snapshot_error": {"slot": "deployments", "type": "incomplete_cluster_region_mapping"}, "context": (("deployments", "The telemetry snapshot lacks the cluster-to-region mapping for four clusters, so the apparent regional coverage cannot be verified.", {"unmapped_clusters": 4, "mapping_version": None}),), "decision": "insufficient_data", "required": ("latency", "deployments"), "recipient": [], "clarification": ("cluster_region_mapping",), "gap": "Cluster-to-region mapping is missing for part of the population; broad customer impact is unverified.", "driver": "incomplete cluster ownership and region mapping"},
        ),
        "owner_answers": {
            "metric_definition": {"known": True, "answer": "Use server-side p95 query latency for customer-serving production clusters; a single CPU spike is insufficient evidence."},
            "time_window": {"known": True, "answer": "Use the previous complete 60-minute window for recurring comparison."},
            "materiality": {"known": False, "answer": "The performance team has no approved automatic latency threshold. You may report correlated evidence but must not page unattended."},
            "routing": {"known": False, "answer": "The database performance on-call is the likely owner, but the current escalation destination needs confirmation."},
        },
        "onboarding_label": {"required": ("latency", "deployments"), "scope": "production customer-serving clusters across mapped regions", "window": "previous 60 minutes", "drivers": ("regions", "lead_minutes"), "alert_topics_missing": ("materiality", "routing"), "expected_recipient": "database-performance-oncall"},
    },
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _company_catalog(spec: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = []
    for source in spec["sources"]:
        contract: dict[str, Any] = {"tenant_id": spec["scenario_id"], "domain": spec["family"], "scope": source["scope"], "metric_names": [spec["metric"]]}
        # Native Superset chart exports intentionally expose no typed comparison
        # contract. The caller has to inspect the chart snapshot and qualify it.
        if source["adapter"] != "superset":
            contract["roles"] = ["primary" if source["slot"] in {"crm", "ledger", "billing", "scans", "deployments"} else "diagnostic"]
        descriptor = {
            "adapter": source["adapter"], "resource": source["resource"], "kind": source["kind"],
            "title": source["title"], "description": source["description"],
            "metadata": {"scope_note": source["scope"], "fixture_source": "synthetic", "source_slot": source["slot"]},
            "contract": contract,
        }
        catalog.append(ResourceDescriptor.model_validate(descriptor).model_dump(mode="json"))
    return catalog


def _snapshot(spec: dict[str, Any], source: dict[str, Any], observation: dict[str, Any], as_of: str) -> dict[str, Any]:
    ref = f"{source['adapter']}|{source['resource']}"
    facts = [fact for fact in observation["context"] if fact[0] == source["slot"]]
    role = source["slot"]
    baseline = observation["baseline"] if role in {"health", "pipeline", "payouts", "renewals", "sla", "latency"} else None
    current = observation["current"] if baseline is not None else None
    metric = spec["metric"] if baseline is not None else (facts[0][1] if facts else source["title"])
    unit = spec["unit"] if baseline is not None else "source fields"
    context_evidence = [
        {"source_key": source["resource"], "subject_id": f"{role}-fact-{index + 1}",
         "subject_label": source["title"], "statement": statement, "values": values,
         "origin": "source", "provenance": [ref]}
        for index, (_, statement, values) in enumerate(facts)
    ]
    observations = []
    if baseline is not None:
        delta = current - baseline
        change_pct = None if baseline == 0 else delta / abs(baseline) * 100
        observations.append({
            "source_key": source["resource"], "subject_id": "primary-comparison",
            "subject_label": source["title"], "metric": metric, "unit": unit,
            "baseline": baseline, "current": current, "change_pct": change_pct,
            "dimensions": {"period_label": observation["window"], "population": spec["population"]},
            "freshness": as_of,
        })
    native = source["adapter"] == "superset"
    metadata: dict[str, Any] = {"fixture_source": "synthetic", "source_slot": role}
    if native:
        metadata["transport_kind"] = "synthetic_superset_chart_snapshot"
        metadata["chart_snapshot"] = {
            "chart_id": source["resource"].split(":", 1)[1],
            "chart_title": source["title"], "time_range": observation["window"],
            "records": [{"metric": metric, "baseline": baseline, "current": current, "unit": unit}],
            "query_context": {"datasource": source["scope"], "time_column": "event_timestamp", "filters": []},
        }
    if observation.get("missing") and observation["missing"]["slot"] == role:
        metadata["unavailable_fields"] = observation["missing"]["fields"]
        metadata["source_response_status"] = "partial"
    if observation.get("window_conflict") and role in observation["window_conflict"]:
        metadata["declared_window"] = observation["window_conflict"][role]
    if observation.get("definition_conflict") and role in observation["definition_conflict"]:
        metadata["declared_definition"] = observation["definition_conflict"][role]
    if observation.get("snapshot_error") and observation["snapshot_error"]["slot"] == role:
        metadata["source_error_type"] = observation["snapshot_error"]["type"]
    descriptor = next(item for item in spec["sources"] if item["slot"] == role)
    contract = {
        "tenant_id": spec["scenario_id"], "domain": spec["family"],
        "scope": descriptor["scope"], "metric_names": [spec["metric"]],
    }
    if descriptor["adapter"] != "superset":
        contract["roles"] = ["primary" if role in {"crm", "ledger", "billing", "scans", "deployments"} else "diagnostic"]
    snapshot = {
        "source_key": source["resource"], "adapter": source["adapter"], "resource": source["resource"],
        "title": source["title"], "description": source["description"],
        "observations": observations, "analytical_comparisons": [], "evidence": context_evidence,
        "metadata": metadata, "source_url": None,
        "captured_at": as_of, "source_captured_at": as_of, "contract": contract,
    }
    return ResourceSnapshot.model_validate(snapshot).model_dump(mode="json")


def _period_snapshots(spec: dict[str, Any], observation: dict[str, Any], as_of: str) -> dict[str, dict[str, Any]]:
    snapshots = {}
    for source in spec["sources"]:
        snapshot = _snapshot(spec, source, observation, as_of)
        ref = f"{source['adapter']}|{source['resource']}"
        if observation.get("snapshot_error") and observation["snapshot_error"]["slot"] == source["slot"]:
            # The adapter error remains a visible per-source record; the runner
            # must preserve it and the episode slot rather than quietly skipping.
            snapshot["error"] = observation["snapshot_error"]["type"]
        snapshots[ref] = snapshot
    return snapshots


def _public_company(spec: dict[str, Any]) -> dict[str, Any]:
    catalog = _company_catalog(spec)
    onboarding_as_of = "2026-09-14T12:00:00+00:00"
    onboarding = {
        "period_id": "first-report", "as_of": onboarding_as_of,
        "snapshots": _period_snapshots(spec, spec["onboarding"], onboarding_as_of),
    }
    periods = []
    for index, observation in enumerate(spec["episodes"], start=1):
        as_of = (datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
                 + timedelta(days=index * 7)).isoformat()
        periods.append({
            "period_id": f"later-{index:02d}", "as_of": as_of,
            "snapshots": _period_snapshots(spec, observation, as_of),
        })
    return {
        "scenario_id": spec["scenario_id"], "company": spec["company"],
        "family": spec["family"], "brief": spec["brief"],
        "catalog": catalog,
        "glossary": [{"metric": spec["metric"], "unit": spec["unit"],
                      "description": "Owner definition is available only through a requested clarification."}],
        "owner_topics": ["metric_definition", "time_window", "materiality", "routing"],
        "destinations": [{"key": spec["owner_key"], "label": spec["owner"], "destination": spec["destination"]}],
        "numeric_vocabulary": ["primary.baseline", "primary.current", "primary.change_pct"],
        "submission_contract": {
            "type": "human_first_report", "summary_max_chars": 500,
            "max_report_chars": MAX_REPORT_CHARS,
            "required_fields": ["summary", "scope", "window", "evidence_refs", "drivers", "recipient_action", "caveats"],
        },
        "onboarding": onboarding, "periods": periods,
    }


def journeys() -> list[dict[str, Any]]:
    """Return six public/source fixtures plus separated scorer/owner sidecars."""
    scenarios = []
    for spec in _COMPANIES:
        public = _public_company(spec)
        hil_answers = copy.deepcopy(
            _SYNTHETIC_OWNER_HIL.get(spec["scenario_id"], {}).get("answers", {})
        )
        private = {
            "onboarding": dict(spec["onboarding_label"]),
            "owner_answers": json.loads(json.dumps(spec["owner_answers"])),
            "synthetic_owner_hil_answers": hil_answers,
            "synthetic_owner_hil": bool(hil_answers),
            "owner_policy_rule": copy.deepcopy(_OWNER_POLICY_RULES[spec["scenario_id"]]),
            "episodes": {},
        }
        for observation, period in zip(spec["episodes"], public["periods"], strict=True):
            signal_decision = observation["decision"]
            required_policy_topics = (
                ["materiality"] + (["routing"] if observation["recipient"] else [])
                if signal_decision == "notify" else []
            )
            initially_missing = [
                topic for topic in required_policy_topics
                if not private["owner_answers"].get(topic, {}).get("known", False)
            ]
            # No synthetic owner/HIL answers are supplied for unknown policies.
            staged_topics: set[str] = set()
            unresolved_topics = [topic for topic in initially_missing if topic not in staged_topics]
            recommendation_authorized = not unresolved_topics
            if unresolved_topics:
                policy_status = "unresolved"
            else:
                policy_status = "initial_owner_policy"
            private["episodes"][period["period_id"]] = {
                # Keep the observed signal separate from its policy disposition.
                # A notify signal is report-only until every required policy is
                # actually known; this fixture supplies no simulated signoff.
                "decision": "investigate" if signal_decision == "notify" and not recommendation_authorized
                else signal_decision,
                "signal_decision": signal_decision,
                "required_evidence_refs": [
                    f"{next(source['adapter'] for source in spec['sources'] if source['slot'] == slot)}|"
                    f"{next(source['resource'] for source in spec['sources'] if source['slot'] == slot)}"
                    for slot in observation["required"]
                ],
                "expected_recipients": list(observation["recipient"])
                if recommendation_authorized else [],
                "signal_recipients": list(observation["recipient"]),
                "alert_policy_topics": required_policy_topics,
                "alert_topics_missing_initially": initially_missing,
                "alert_topics_missing": unresolved_topics,
                "alert_policy_status": policy_status,
                "recommendation_authorized": recommendation_authorized,
                # No fixture label authorizes external automation or delivery.
                "automation_authorized": False,
                "outcome_semantics": "shadow_recommendation"
                if signal_decision == "notify" and recommendation_authorized
                else "report_only_requires_hil" if unresolved_topics else "report_only",
                "clarification_slots": list(dict.fromkeys(
                    (*observation["clarification"], *unresolved_topics)
                )),
                "known_data_gap": observation["gap"],
                "expected_driver": observation["driver"],
                "expected_scope": spec["population"],
                "expected_window": spec["window"].replace("_", " "),
                "window_conflicts": copy.deepcopy(observation.get("window_conflict", {})),
                "definition_conflicts": copy.deepcopy(observation.get("definition_conflict", {})),
                "expected_metric": {
                    "metric": spec["metric"], "baseline": observation["baseline"],
                    "current": observation["current"], "unit": spec["unit"],
                } if not observation["gap"] and not observation.get("window_conflict") else None,
                "source_error_slots": [observation["snapshot_error"]["slot"]]
                if observation.get("snapshot_error") else [],
            }
        scenarios.append({"scenario_id": spec["scenario_id"], "public": public, "private": private})
    return scenarios


def _episode_observation(scenario_id: str, period_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = next(item for item in _COMPANIES if item["scenario_id"] == scenario_id)
    index = int(period_id.rsplit("-", 1)[1]) - 1
    return spec, spec["episodes"][index]


def to_installed_trial_scenario(
    scenario: dict[str, Any], *, period_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Project a company journey onto the shared installed-runner contract.

    The shared runner and scorer receive labels only under ``private.periods``;
    public owner answers remain available only via its ask_owner tool. This is a
    fixture adapter, not another agent loop or transport.
    """
    original = scenario["public"]
    scenario_id = original["scenario_id"]
    spec = next(item for item in _COMPANIES if item["scenario_id"] == scenario_id)
    selected_ids = set(period_ids or [item["period_id"] for item in original["periods"]])
    periods = [copy.deepcopy(item) for item in original["periods"]
               if item["period_id"] in selected_ids]
    if len(periods) != len(selected_ids):
        raise ValueError(f"unknown period requested for {scenario_id}")

    owner_answers = {
        topic: answer["answer"]
        for topic, answer in scenario["private"]["owner_answers"].items()
        if answer.get("known") is True
    }
    public = {
        "company": original["company"],
        "brief": original["brief"],
        "catalog": copy.deepcopy(original["catalog"]),
        "glossary": {
            spec["metric"]: spec["population"],
            "unit": spec["unit"],
            "comparison": f"Previous complete {spec['window'].removeprefix('previous_').replace('_', ' ')}; source periods are UTC.",
        },
        "owner_topics": list(original["owner_topics"]),
        "owner_answers": owner_answers,
        "destinations": copy.deepcopy(original["destinations"]),
        "numeric_vocabulary": list(original["numeric_vocabulary"]),
        "submission_contract": {
            "outcomes": ["ignore", "notify", "investigate", "insufficient_data"],
            "claim_types": ["observation", "accounting_decomposition", "association", "hypothesis"],
            "number_units": [spec["unit"], "percent"],
            "numeric_definitions": {
                "primary.baseline": "Metric value in the baseline interval under the owner definition.",
                "primary.current": "Metric value in the current interval under the owner definition.",
                "primary.change_pct": "Relative change from baseline, expressed as a percent.",
            },
        },
        "onboarding": copy.deepcopy(original["onboarding"]),
        "periods": periods,
    }

    private_periods = {}
    primary_source = next(item for item in spec["sources"]
                          if item["slot"] in {"health", "pipeline", "payouts", "renewals", "sla", "latency"})
    primary_ref = f"{primary_source['adapter']}|{primary_source['resource']}"
    for period in periods:
        period_id = period["period_id"]
        label = scenario["private"]["episodes"][period_id]
        _, observation = _episode_observation(scenario_id, period_id)
        expected = label["expected_metric"]
        numeric_facts: dict[str, Any] = {}
        required_numeric_facts: list[str] = []
        if expected is not None:
            baseline = expected["baseline"]
            current = expected["current"]
            change_pct = (current - baseline) / abs(baseline) * 100
            for fact, value, unit in (
                ("primary.baseline", baseline, expected["unit"]),
                ("primary.current", current, expected["unit"]),
                ("primary.change_pct", change_pct, "percent"),
            ):
                numeric_facts[fact] = {
                    "value": value, "unit": unit,
                    "absolute_tolerance": max(abs(float(value)) * 1e-6, 1e-6),
                    "evidence_refs": [primary_ref],
                }
                required_numeric_facts.append(fact)
        private_periods[period_id] = {
            "condition": "quiet" if label["decision"] == "ignore" else (
                "event" if label["decision"] in {"notify", "investigate"} else "data_gap"
            ),
            "outcome": label["decision"],
            "recipients": list(label["expected_recipients"]),
            "required_evidence_refs": list(label["required_evidence_refs"]),
            "numeric_facts": numeric_facts,
            "required_numeric_facts": required_numeric_facts,
            "allowed_claim_types": ["observation", "accounting_decomposition", "association", "hypothesis"],
            "required_claim_types": [],
            "required_owner_topics": ["metric_definition", "time_window", "materiality", "routing"],
            "scenario_note_private": observation.get("gap"),
        }

    return {
            "schema_version": 1,
        "scorer_version": 3,
        "scenario_id": scenario_id,
        "public": public,
        "private": {
            "family": spec["family"],
            "onboarding_label": copy.deepcopy(scenario["private"]["onboarding"]),
            "periods": private_periods,
            "episodes": copy.deepcopy(scenario["private"]["episodes"]),
            "owner_answers": owner_answers,
        },
    }


def pilot_scenarios(pair_count: int = 4) -> list[dict[str, Any]]:
    """Select a bounded, diverse 2- or 4-pair smoke from the first two stories."""
    if pair_count not in {2, 4}:
        raise ValueError("pilot pair count must be 2 or 4")
    all_scenarios = {item["public"]["scenario_id"]: item for item in journeys()}
    selected = {
        "journey-03": ["later-02"] if pair_count == 2 else ["later-01", "later-02"],
        "journey-05": ["later-01"] if pair_count == 2 else ["later-01", "later-02"],
    }
    return [to_installed_trial_scenario(all_scenarios[scenario_id], period_ids=period_ids)
            for scenario_id, period_ids in selected.items()]


def public_episode(scenario: dict[str, Any], period_id: str | None = None) -> dict[str, Any]:
    """Return one agent-visible episode; never include labels or future snapshots."""
    public = scenario["public"]
    period = public["onboarding"] if period_id is None else next(
        item for item in public["periods"] if item["period_id"] == period_id
    )
    visible = {key: public[key] for key in (
        "scenario_id", "company", "family", "brief", "catalog", "glossary",
        "owner_topics", "destinations", "numeric_vocabulary", "submission_contract",
    )}
    visible["period"] = period
    return json.loads(json.dumps(visible))


def ask_owner(
    scenario: dict[str, Any], topic: str, *, after_first_report: bool = False,
) -> dict[str, Any]:
    """Return initial owner policy or a staged synthetic HIL answer."""
    answers = scenario["private"]["owner_answers"]
    answer = answers.get(topic)
    answer_source = "initial_owner_persona"
    if not (answer and answer.get("known")) and after_first_report:
        staged = scenario["private"].get("synthetic_owner_hil_answers", {}).get(topic)
        if staged and staged.get("known"):
            answer = staged
            answer_source = "synthetic_owner_persona_hil"
    known = bool(answer and answer.get("known"))
    return {
        "topic": topic, "known": known,
        "answer": answer["answer"] if known else "Unknown. Ask the business owner only for the missing policy; never infer it from source values.",
        "stage": "post_first_report_owner_clarification" if after_first_report
        else "initial_policy_lookup",
        "answer_source": answer_source if known else "unanswered",
    }


def paired_episode_plan(scenarios: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Freeze one later-episode slot per company/period for both equal-context arms."""
    scenarios = scenarios or journeys()
    pairs = []
    for scenario in scenarios:
        public = scenario["public"]
        for period in public["periods"]:
            episode = public_episode(scenario, period["period_id"])
            context_digest = _sha256(episode)
            pairs.append({
                "episode_id": f"{public['scenario_id']}/{period['period_id']}",
                "company": public["company"], "family": public["family"],
                "public_context_sha256": context_digest,
                "shared_card_required": True,
                "same_source_tools": list(SOURCE_TOOLS),
                "arms": {
                    "luna_control": {"model": MODEL, "reasoning_effort": REASONING_EFFORT,
                                     "signalweave_available": False, "card_copy": "same_signed_card"},
                    "luna_signalweave": {"model": MODEL, "reasoning_effort": REASONING_EFFORT,
                                         "signalweave_available": True, "card_copy": "same_signed_card"},
                },
                "private_label_key": f"{public['scenario_id']}:{period['period_id']}",
            })
    return pairs


def protocol(*, binary_preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "version": VERSION, "seed": SEED, "scenario_type": "synthetic_evaluation_only",
        "design": "6 human-first onboarding stories plus 24 paired later episodes (4 per company)",
        "company_families": [spec["family"] for spec in _COMPANIES],
        "denominators": {"onboarding_stories": 6, "later_episodes_per_arm": 24,
                         "paired_later_episodes": 24, "retained_slots_per_arm": 24},
        "human_first": {
            "opening_request": "why did this change?",
            "required_order": ["inspect current sources", "write short scope-qualified current report",
                                "ask only missing alert/materiality/ownership policy",
                                "record explicit owner signoff before any future alert policy",
                                "author recurring card",
                                "review", "independent expert signoff", "approve", "one shadow evaluation per later episode",
                                "write short final agent report"],
            "undefined_threshold": "May block unattended notify/alert authorization; must not block useful current reporting.",
            "report_contract": "Short facts, likely drivers with source refs, caveats/scope, and recipient action; <=1200 chars, not an evidence dump.",
        },
        "bounded_pilot": {
            "runner": "evaluations.installed_workflow_trial.run_trial",
            "status": "basic_shared_runner_pilot; report-before-automation is not measured in this first run",
            "companies": ["journey-03", "journey-05"],
            "paired_episode_choices": {
                "2": ["journey-03/later-02", "journey-05/later-01"],
                "4": ["journey-03/later-01", "journey-03/later-02",
                      "journey-05/later-01", "journey-05/later-02"],
            },
            "synthetic_owner_hil_answers_in_fixture": True,
            "live_pilot_uses_synthetic_owner_hil": False,
            "owner_policy_selection": "Journeys 01/02/04/06 have independently authored synthetic owner-persona answers available only after a useful first report and ask_owner; those responses are not real customer approval. The bounded pilot uses journeys 03/05 with known initial policies.",
            "maximum_jev_attempts": 40,
        },
        "profile": {"name": DEFAULT_PROFILE, "tool_count": 10, "tools": list(AGENT_TOOLS),
                    "advanced_full_is_separate_cohort": True,
                    "prohibited_for_default_claims": ["bootstrap_insight_card", "simulate_insight_card", "evaluate_card_workflow"]},
        "models": {"both_arms": MODEL, "reasoning_effort": REASONING_EFFORT},
        "paired_controls": {
            "same_source_tools": list(SOURCE_TOOLS), "same_owner_answers": True,
            "same_owner_lookup_tool": "ask_owner, shared in both arms",
            "same_frozen_expert_signed_card": True,
            "same_source_snapshots_and_read_budget": True,
            "only_treatment_difference": "SignalWeave guide/card review/approved-card Jev evaluation and its typed handoff; the final Luna report remains the primary utility endpoint.",
            "judge": "score the final report, source scope/citations, likely-driver qualification, missing-fact handling, concise recipient action and policy utility; native SignalWeave correctness is a secondary diagnostic.",
        },
        "failure_policy": "Every predeclared slot remains in the denominator. Setup, model, tool, source, scoring, timeout and budget failures are retained as failures/unknowns, never dropped or silently retried.",
        "private_data": "Scoring labels and simulated owner answer service remain outside agent prompts and source tools; owner answers are returned only for requested topics.",
        "source_realism": {
            "transport": "local synthetic source MCP; no live connector or HTTP request",
            "superset_shaped_chart_snapshots": ["journey-01", "journey-02", "journey-04", "journey-05"],
            "native_superset_integration_claimed": False,
            "perfect_comparison_contracts_assumed": False,
            "missing_facts_and_source_errors_retained": True,
        },
        "delivery": "All evaluations are shadow/delivery-disabled; no actual message or page is sent.",
        "binary_provenance": binary_preflight or {
            "status": "blocked_missing_parent_certificate"
            if ACTIVE_PARENT_CERTIFICATE is None else "pending_preflight",
            "certified_source_sha256": CERTIFIED_SOURCE_SHA256,
            "certified_binary_sha256": CERTIFIED_BINARY_SHA256,
            "certified_version": CERTIFIED_VERSION,
            "active_parent_certificate": ACTIVE_PARENT_CERTIFICATE,
            "verification": None,
            "required_before": ["live_setup", "report_certification"],
            "helper": "scripts.binary_provenance.verify_binary(Path(binary))",
        },
        "limits": [
            "Synthetic fixtures do not establish real customer performance or production reliability.",
            "Six authored stories are formative product coverage, not a statistical estimate.",
            "The shared runner uses a model reviewer, not a real HIL owner or human business approval; labels are not supplied to the author or either agent.",
            "Unresolved policy remains unknown; no owner threshold or recipient is fabricated and no notify label is assigned to those episodes.",
            "No alert is considered delivered; recipient action is scored as a report recommendation only.",
            "Narrative entailment requires independent human review in addition to deterministic rubric scoring.",
        ],
    }


def make_binary_preflight(
    binary: str | Path | None,
    certified_source_sha256: str | None,
    *,
    phase: str,
    certified_binary_sha256: str | None = None,
    certified_version: str | None = None,
) -> dict[str, Any]:
    """Verify the exact source/binary identity at each future live gate.

    This function is intentionally not called by offline fixture generation.
    A pilot runner must call it immediately before setup and again before
    certifying any report; the second call detects intervening source changes.
    """
    if phase not in {"live_setup", "shared_runner_gate", "report_certification"}:
        raise ValueError("phase must be live_setup, shared_runner_gate, or report_certification")
    if binary is None or not certified_source_sha256 or not certified_binary_sha256:
        return {"phase": phase, "status": "blocked_missing_parent_certificate", "verification": None}
    from scripts.binary_provenance import verify_binary

    identity = verify_binary(Path(binary))
    if (identity.get("source_sha256") != certified_source_sha256
            or identity.get("binary_sha256") != certified_binary_sha256
            or (certified_version is not None and identity.get("version") != certified_version)):
        raise ValueError("binary identity does not match the parent-certified fingerprint")
    return {"phase": phase, "status": "verified", "verification": identity}


def _write_private_json(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def verify_certified_binary(binary: str | Path, *, phase: str) -> dict[str, Any]:
    if ACTIVE_PARENT_CERTIFICATE is None:
        raise RuntimeError("live pilot is held until the next exact parent certificate is supplied")
    result = make_binary_preflight(
        binary, ACTIVE_PARENT_CERTIFICATE["source_sha256"], phase=phase,
        certified_binary_sha256=ACTIVE_PARENT_CERTIFICATE["binary_sha256"],
        certified_version=ACTIVE_PARENT_CERTIFICATE["version"],
    )
    if result["status"] != "verified":
        raise RuntimeError("parent-certified binary identity is required")
    return result["verification"]


async def run_live_pilot(
    *, binary: Path, key_file: Path, output: Path, pair_count: int = 4,
    jev_budget: int = 40,
) -> dict[str, Any]:
    """Run only 2 or 4 preselected pairs through the current shared runner."""
    if pair_count not in {2, 4}:
        raise ValueError("pilot is limited to 2 or 4 paired episodes")
    if not 1 <= jev_budget <= 40:
        raise ValueError("Jev attempt budget must be between 1 and 40")
    output = Path(output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    binary = Path(binary).resolve()
    key_file = Path(key_file).resolve()
    selected = pilot_scenarios(pair_count)
    selection = [
        {"scenario_id": scenario["scenario_id"],
         "period_ids": [period["period_id"] for period in scenario["public"]["periods"]]}
        for scenario in selected
    ]
    try:
        identity = verify_certified_binary(binary, phase="live_setup")
        preflight = {
            "status": "verified", "identity": identity,
            "profile": DEFAULT_PROFILE, "expected_tools": list(AGENT_TOOLS),
            "models": {"author": {"model": MODEL, "effort": REASONING_EFFORT},
                       "recurring_agent": {"model": MODEL, "effort": REASONING_EFFORT},
                       "reviewer": {"model": MODEL, "effort": REASONING_EFFORT}},
            "jev_attempt_limit": jev_budget, "planned_pairs": pair_count,
            "selected_slots": selection, "delivery_enabled": False,
            "private_labels_available_to_agent": False,
        }
        _write_private_json(output / "preflight.json", preflight)
        _write_private_json(output / "protocol.json", protocol(binary_preflight={
            "phase": "live_setup", "status": "verified", "verification": identity,
        }))

        from evaluations import installed_workflow_trial

        # Enforce the parent's exact binary identity at each of the shared
        # runner's own gates (preflight, before each setup, report certification).
        original_verify = installed_workflow_trial.verify_binary
        installed_workflow_trial.verify_binary = lambda path: verify_certified_binary(
            path, phase="shared_runner_gate"
        )
        previous_umask = os.umask(0o077)
        try:
            report = await installed_workflow_trial.run_trial(
                selected, binary=binary, key_file=key_file,
                output=output / "shared-trial", jev_budget=jev_budget,
                live=True, stage_gate=pair_count,
                author_model=MODEL, author_effort=REASONING_EFFORT,
                recurring_agent_model=MODEL, recurring_agent_effort=REASONING_EFFORT,
                reviewer_model=MODEL, reviewer_effort=REASONING_EFFORT,
            )
        finally:
            installed_workflow_trial.verify_binary = original_verify
            os.umask(previous_umask)
        final_identity = verify_certified_binary(binary, phase="report_certification")
        if final_identity != identity:
            raise RuntimeError("certified binary identity changed during the paired pilot")
        _write_private_json(output / "postflight.json", {
            "status": "verified", "identity": final_identity,
            "same_as_preflight": True,
            "shared_runner_summary": report.get("summary"),
        })
        return report
    except Exception as error:
        try:
            final_identity = verify_certified_binary(binary, phase="failure_postflight")
            postflight_error = None
        except Exception as verify_error:
            final_identity = None
            postflight_error = type(verify_error).__name__
        failure = {
            "status": "failed", "failure_type": type(error).__name__,
            "details": "Exception text omitted; inspect the private shared-trial trace when present.",
            "postflight_identity": final_identity,
            "postflight_error_type": postflight_error,
            "planned_pairs": pair_count,
            "selected_slots": selection,
        }
        if not (output / "failure.json").exists():
            _write_private_json(output / "failure.json", failure)
        raise


def _source_refs(public: dict[str, Any]) -> set[str]:
    return {f"{item['adapter']}|{item['resource']}" for item in public["catalog"]}


def _normalized_text(value: Any) -> str:
    text = str(value).casefold().replace("_", " ").replace("-", " ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _scope_matches(actual: Any, expected: str) -> bool:
    return _normalized_text(expected) in _normalized_text(actual)


def _expected_period_matches(actual: Any, expected: str) -> bool:
    text = _normalized_text(actual)
    expected_text = _normalized_text(expected)
    if "60 minute" in expected_text:
        return bool(re.search(
            r"\b(previous|prior|last)\s+(complete\s+)?(60\s+minutes?|hour)\b", text,
        ))
    if "7 day" in expected_text:
        return bool(re.search(
            r"\b(previous|prior|last)\s+(complete\s+)?(7\s+days?|week)\b", text,
        ))
    return expected_text in text


_CONFLICTING_WINDOW_ALIASES = {
    "rolling 7 days": ("rolling 7 days", "rolling 7 day", "rolling week"),
    "calendar month": ("calendar month",),
    "next quarter": ("next quarter",),
    "calendar week": ("calendar week",),
    "server 5m": ("server 5m", "server 5 minute", "server side 5 minute"),
    "client 1h": ("client 1h", "client 1 hour", "client side 1 hour"),
}


def _conflicting_windows_match(actual: Any, conflicts: dict[str, str]) -> bool:
    text = _normalized_text(actual)
    if not conflicts:
        return False
    for window in conflicts.values():
        normalized = _normalized_text(window)
        aliases = _CONFLICTING_WINDOW_ALIASES.get(normalized, (normalized,))
        if not any(alias in text for alias in aliases):
            return False
    return any(term in text for term in ("conflict", "differ", "mismatch", "versus", " vs "))


def _reported_scope_and_window_match(scope: Any, window: Any, label: dict[str, Any]) -> bool:
    if not _scope_matches(scope, label["expected_scope"]):
        return False
    conflicts = label.get("window_conflicts", {})
    if conflicts:
        return _conflicting_windows_match(window, conflicts)
    return _expected_period_matches(window, label["expected_window"])


def score_report(
    scenario: dict[str, Any],
    period_id: str,
    report: dict[str, Any] | None,
    *,
    inspected_refs: set[str] | list[str] = (),
    status: str = "complete",
) -> dict[str, Any]:
    """Rubric-score agent utility, including the narrative deliverable surface."""
    label = scenario["private"]["episodes"][period_id]
    public = scenario["public"]
    allowed = _source_refs(public)
    inspected = set(inspected_refs) & allowed
    result: dict[str, Any] = {
        "episode_id": f"{public['scenario_id']}/{period_id}", "completed": False,
        "score": 0, "denominator_included": True, "status": status,
        "dimensions": {"decision": 0, "ownership": 0, "evidence": 0, "numeric": 0,
                       "scope_window": 0, "clarity": 0, "recipient_action": 0, "conciseness": 0},
        "errors": [], "narrative_review_required": True,
    }
    if status != "complete" or not isinstance(report, dict):
        result["errors"].append("missing_or_failed_report")
        return result
    result["completed"] = True
    cited = set(ref for ref in report.get("evidence_refs", []) if isinstance(ref, str))
    required = set(label["required_evidence_refs"])
    if report.get("decision") == label["decision"]:
        result["dimensions"]["decision"] = 20
    if set(report.get("recipients", [])) == set(label["expected_recipients"]):
        result["dimensions"]["ownership"] = 10
    if required <= cited & inspected and cited <= inspected:
        result["dimensions"]["evidence"] = 20
    expected = label.get("expected_metric")
    metrics = report.get("metrics", [])
    numeric_ok = expected is None and not metrics
    if expected is not None:
        for item in metrics if isinstance(metrics, list) else []:
            if not isinstance(item, dict):
                continue
            numeric_ok = numeric_ok or (
                item.get("metric") == expected["metric"]
                and item.get("unit") == expected["unit"]
                and item.get("baseline") == expected["baseline"]
                and item.get("current") == expected["current"]
                and set(item.get("evidence_refs", [])) <= cited & inspected
            )
    if numeric_ok:
        result["dimensions"]["numeric"] = 15
    # Scope is the owner-defined population for the primary metric. Distinct
    # corroborating sources may have their own populations and are not required
    # to share a denominator unless the report claims a joined calculation.
    if _reported_scope_and_window_match(
        report.get("scope", ""), report.get("window", ""), label,
    ):
        result["dimensions"]["scope_window"] = 10
    clarification = set(report.get("clarification_slots", []))
    expected_clarification = set(label["clarification_slots"])
    if clarification == expected_clarification and (
        not label.get("known_data_gap") or bool(report.get("data_gaps"))
    ):
        result["dimensions"]["clarity"] = 5
    recipient_action = str(report.get("recipient_action", "")).strip()
    if recipient_action and len(recipient_action) <= 300:
        result["dimensions"]["recipient_action"] = 10
    summary = str(report.get("summary", "")).strip()
    report_chars = len(summary) + sum(len(str(item)) for item in report.get("drivers", [])) + len(recipient_action)
    if 60 <= len(summary) <= 500 and len(report.get("drivers", [])) <= 3 and report_chars <= MAX_REPORT_CHARS:
        result["dimensions"]["conciseness"] = 10
    result["score"] = sum(result["dimensions"].values())
    result["source_citation_recall"] = len(required & cited & inspected) / max(1, len(required))
    result["expected_decision"] = label["decision"]
    return result


def score_report_first(
    scenario: dict[str, Any],
    report: dict[str, Any] | None,
    *,
    inspected_refs: set[str] | list[str] = (),
    status: str = "complete",
) -> dict[str, Any]:
    """Score the user's first useful report separately from alert readiness."""
    label = scenario["private"]["onboarding"]
    public = scenario["public"]
    allowed = _source_refs(public)
    inspected = set(inspected_refs) & allowed
    result = {"scenario_id": public["scenario_id"], "completed": False, "score": 0,
              "status": status, "denominator_included": True,
              "dimensions": {"useful_report": 0, "evidence": 0, "scope": 0,
                             "drivers": 0, "action": 0, "no_false_alert": 0},
              "narrative_review_required": True}
    if status != "complete" or not isinstance(report, dict):
        result["error"] = "missing_or_failed_first_report"
        return result
    result["completed"] = True
    summary = str(report.get("summary", "")).strip()
    refs = set(ref for ref in report.get("evidence_refs", []) if isinstance(ref, str))
    required = {f"{next(s['adapter'] for s in _COMPANIES[i]['sources'] if s['slot'] == slot)}|"
                f"{next(s['resource'] for s in _COMPANIES[i]['sources'] if s['slot'] == slot)}"
                for i, spec in enumerate(_COMPANIES) if spec["scenario_id"] == public["scenario_id"]
                for slot in label["required"]}
    if 60 <= len(summary) <= 500 and len(report.get("drivers", [])) <= 3:
        result["dimensions"]["useful_report"] = 20
    if required <= refs & inspected:
        result["dimensions"]["evidence"] = 20
    expected_scope = label["scope"]
    expected_window = label["window"]
    if (_scope_matches(report.get("scope", ""), expected_scope)
            and _expected_period_matches(report.get("window", ""), expected_window)):
        result["dimensions"]["scope"] = 15
    if report.get("drivers") and len(report["drivers"]) <= 3:
        result["dimensions"]["drivers"] = 15
    if str(report.get("recipient_action", "")).strip():
        result["dimensions"]["action"] = 10
    if report.get("automated_alert") is False:
        result["dimensions"]["no_false_alert"] = 10
    result["score"] = sum(result["dimensions"].values())
    result["unresolved_policy_topics"] = list(label["alert_topics_missing"])
    result["expected_recipient_context"] = label["expected_recipient"]
    return result


def score_owner_clarification(
    scenario: dict[str, Any], *, asked_topics: set[str] | list[str],
    first_report_completed: bool,
) -> dict[str, Any]:
    """Score policy questions as a separate post-report step, never as report prose."""
    expected = set(scenario["private"]["onboarding"]["alert_topics_missing"])
    asked = set(asked_topics)
    return {
        "scenario_id": scenario["public"]["scenario_id"],
        "first_report_completed_before_questions": first_report_completed,
        "expected_missing_policy_topics": sorted(expected),
        "asked_topics": sorted(asked),
        "exact": bool(first_report_completed and asked == expected),
        "extra_topics": sorted(asked - expected),
        "unasked_topics": sorted(expected - asked),
    }


def score_paired_slots(
    scenarios: list[dict[str, Any]],
    responses: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Retain all 24 pairs; absent/failed arm outputs score zero, not dropped."""
    rows = []
    for scenario in scenarios:
        for period in scenario["public"]["periods"]:
            episode_id = f"{scenario['scenario_id']}/{period['period_id']}"
            row: dict[str, Any] = {"episode_id": episode_id, "arms": {}}
            for arm in ARMS:
                response = responses.get(arm, {}).get(episode_id)
                if response is None:
                    row["arms"][arm] = score_report(
                        scenario, period["period_id"], None, status="missing"
                    )
                else:
                    row["arms"][arm] = score_report(
                        scenario, period["period_id"], response.get("report"),
                        inspected_refs=response.get("inspected_refs", []),
                        status=response.get("status", "complete"),
                    )
            rows.append(row)
    failures = {arm: sum(not row["arms"][arm]["completed"] for row in rows) for arm in ARMS}
    means = {arm: (sum(row["arms"][arm]["score"] for row in rows) / len(rows) if rows else 0.0)
             for arm in ARMS}
    return {"intended_pairs": 24, "retained_pairs": len(rows), "failure_slots": failures,
            "mean_final_report_utility": means, "paired_rows": rows,
            "complete_denominator": len(rows) == 24}


def freeze_artifacts(output: Path = DEFAULT_ARTIFACTS) -> dict[str, Any]:
    """Write the deterministic public fixture, private labels and pair plan once."""
    if output.exists():
        raise FileExistsError(f"refusing to overwrite frozen artifact directory: {output}")
    output.mkdir(parents=True, mode=0o700)
    scenarios = journeys()
    public = [{"scenario_id": item["scenario_id"], **item["public"]} for item in scenarios]
    private = [{"scenario_id": item["scenario_id"], **item["private"]} for item in scenarios]
    payloads = {
        "public-source-fixtures.json": public,
        "private-scorer-labels.json": private,
        "paired-later-episode-plan.json": paired_episode_plan(scenarios),
        "protocol.json": protocol(),
    }
    for name, payload in payloads.items():
        path = output / name
        mode = 0o600 if name == "private-scorer-labels.json" else 0o644
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        path.chmod(mode)
    summary = {"output": str(output.resolve()), "files": sorted(payloads),
               "onboarding_stories": 6, "paired_later_episodes": 24,
               "public_fixture_sha256": _sha256(public)}
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true", help="write new, non-overwriting fixtures")
    mode.add_argument("--live-pilot", action="store_true",
                      help="run only 2 or 4 pairs through the certified shared installed runner")
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--pairs", type=int, choices=(2, 4), default=4)
    parser.add_argument("--jev-budget", type=int, default=40)
    args = parser.parse_args()
    try:
        if args.freeze:
            result = freeze_artifacts(args.output)
        else:
            if args.binary is None or args.key_file is None:
                parser.error("--live-pilot requires --binary and --key-file")
            output = args.output.resolve()
            if not output.is_relative_to(DEFAULT_ARTIFACTS.resolve()):
                parser.error("live pilot output must remain inside the dated artifacts directory")
            result = asyncio.run(run_live_pilot(
                binary=args.binary, key_file=args.key_file, output=output,
                pair_count=args.pairs, jev_budget=args.jev_budget,
            ))
    except (OSError, ValueError, ValidationError) as error:
        parser.error(str(error))
    except Exception as error:
        print(json.dumps({"status": "failed", "failure_type": type(error).__name__,
                          "output": str(args.output.resolve())}, indent=2))
        raise SystemExit(1) from error
    print(json.dumps(result.get("summary", result), indent=2))


if __name__ == "__main__":
    main()

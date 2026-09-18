"""Enterprise-readiness experiment primitives for SignalWeave.

This module is deliberately evaluation-only. It generates a reproducible synthetic
company, exposes the generated assets through the same source-adapter and MCP
contracts as production, and scores operator sessions against hidden labels. The
fixture is not a product policy and the research judger is not a Jev substitute;
use ``--evaluator jev`` for a live TypeSafe run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - fcntl is available on the supported Unix runners
    import fcntl
except ImportError:  # pragma: no cover - keeps the module importable on Windows
    fcntl = None

from signalweave.engine import InsightEngine
from signalweave.models import (
    DeliveryMethod,
    Evidence,
    InsightCard,
    InsightPlan,
    InsightResult,
    Observation,
    Outcome,
    QuestionResult,
    QuestionStatus,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
    WatchResult,
    WatchStatus,
)
from signalweave.runtime import Runtime
from signalweave.sources import SourceAdapter, SourceRegistry
from signalweave.store import JsonInsightCardStore
from signalweave.typesafe_adapter import InsightJudger, JevJudger, load_api_key

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "data" / "northstar-company.json"
ALLOWED_MCP_TOOLS = (
    "list_resources",
    "inspect_resource",
    "discover_insight_sources",
    "propose_insight_card",
    "draft_insight_card",
    "simulate_insight_card",
    "approve_insight_card",
    "list_insight_cards",
    "get_insight_card",
    "evaluate_insight_card",
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "item"


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", value.lower()) if len(term) > 2}


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _trace_digest(event: dict[str, Any]) -> str:
    payload = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


TRACE_ZERO_HASH = "0" * 64


def load_config(path: str | Path | dict[str, Any] = DEFAULT_CONFIG) -> dict[str, Any]:
    payload = path if isinstance(path, dict) else json.loads(Path(path).read_text())
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("enterprise config must be an object with schema_version=1")
    if "company" not in payload and "portfolio" not in payload:
        raise ValueError("enterprise config must define company or portfolio")
    return payload


class TraceSink:
    """Append-only, hash-chained JSONL trace sink shared by experiment actors."""

    def __init__(self, path: str | Path, *, experiment_id: str, run_id: str) -> None:
        self.path = Path(path)
        self.experiment_id = experiment_id
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event_type: str,
        *,
        actor: str,
        session_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                sequence = 0
                previous_hash = TRACE_ZERO_HASH
                for line in handle:
                    if not line.strip():
                        continue
                    previous = json.loads(line)
                    sequence = int(previous.get("sequence", sequence + 1))
                    previous_hash = str(previous.get("event_hash", _trace_digest(previous)))
                event = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "experiment_id": self.experiment_id,
                    "run_id": self.run_id,
                    "event_id": f"{self.run_id}:{sequence + 1:08d}",
                    "sequence": sequence + 1,
                    "previous_event_hash": previous_hash,
                    "session_id": session_id,
                    "actor": actor,
                    "event_type": event_type,
                    "payload": payload or {},
                }
                event["event_hash"] = _trace_digest(event)
                handle.seek(0, os.SEEK_END)
                handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return event


def audit_trace(path: str | Path) -> dict[str, Any]:
    """Verify trace integrity and the MCP workflow protocol without hidden labels."""
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    errors: list[str] = []
    previous_hash = TRACE_ZERO_HASH
    previous_sequence = 0
    by_session: dict[str, list[dict[str, Any]]] = {}
    for index, event in enumerate(events, start=1):
        if event.get("sequence") != index:
            errors.append(f"sequence gap at line {index}")
        if event.get("previous_event_hash") != previous_hash:
            errors.append(f"hash-chain break at line {index}")
        claimed = event.get("event_hash")
        unsigned = dict(event)
        unsigned.pop("event_hash", None)
        if claimed != _trace_digest(unsigned):
            errors.append(f"event hash mismatch at line {index}")
        previous_hash = str(claimed or "")
        previous_sequence = int(event.get("sequence", previous_sequence))
        by_session.setdefault(str(event.get("session_id", "")), []).append(event)

    protocol_failures: list[str] = []
    for session_id, session_events in by_session.items():
        completed_tools = [
            event["payload"].get("tool")
            for event in session_events
            if event.get("event_type") == "mcp.call.completed"
        ]
        if "evaluate_insight_card" in completed_tools:
            required = [
                ("draft_insight_card", "propose_insight_card"),
                ("simulate_insight_card",),
                ("approve_insight_card",),
                ("evaluate_insight_card",),
            ]
            positions = [
                min((completed_tools.index(tool) for tool in alternatives if tool in completed_tools), default=-1)
                for alternatives in required
            ]
            if positions != sorted(positions) or any(position < 0 for position in positions):
                protocol_failures.append(f"{session_id}: incomplete MCP card protocol")
        starts = {
            event["payload"].get("tool") for event in session_events if event.get("event_type") == "mcp.call.started"
        }
        terminal = {
            event["payload"].get("tool")
            for event in session_events
            if event.get("event_type") in {"mcp.call.completed", "mcp.call.failed"}
        }
        if starts != terminal:
            protocol_failures.append(f"{session_id}: MCP call without terminal event")

    return {
        "valid": not errors and not protocol_failures,
        "event_count": len(events),
        "session_count": len(by_session),
        "hash_chain_valid": not errors,
        "protocol_valid": not protocol_failures,
        "errors": errors,
        "protocol_failures": protocol_failures,
    }


@dataclass(frozen=True)
class TrialTask:
    id: str
    persona_id: str
    variant: str
    goal: str
    brief: dict[str, Any]
    expected_outcome: Outcome
    expected_delivery_methods: list[str]
    expected_source_resources: list[str]
    enterprise_objective: str
    false_action_cost: int


def _weighted_choice(rng: random.Random, values: list[dict[str, Any]], key: str) -> dict[str, Any]:
    total = sum(float(item[key]) for item in values)
    target = rng.random() * total
    running = 0.0
    for item in values:
        running += float(item[key])
        if target <= running:
            return item
    return values[-1]


def _make_observation(
    source_key: str,
    subject_id: str,
    subject_label: str,
    metric: str,
    *,
    current: float | None,
    baseline: float | None,
    change_pct: float | None,
    attributes: dict[str, Any] | None = None,
    dimensions: dict[str, Any] | None = None,
    freshness: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    return Observation(
        source_key=source_key,
        subject_id=subject_id,
        subject_label=subject_label,
        subject_type="metric",
        metric=metric,
        unit="normalized units",
        current=current,
        baseline=baseline,
        change_pct=change_pct,
        comparison_baselines={
            "previous_period": baseline if baseline is not None else 0.0,
            "trailing_4_period_average": baseline * 1.03 if baseline is not None else 0.0,
        },
        dimensions=dimensions or {"region": "global", "channel": "all"},
        freshness=freshness,
        source_url=source_url,
        attributes=attributes or {},
    ).model_dump(mode="json")


def _snapshot(
    *,
    source_key: str,
    adapter: str,
    resource: str,
    title: str,
    description: str,
    observations: list[dict[str, Any]],
    metadata: dict[str, Any],
    captured_at: datetime,
    error: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return ResourceSnapshot(
        source_key=source_key,
        adapter=adapter,
        resource=resource,
        title=title,
        description=description,
        observations=[Observation.model_validate(item) for item in observations],
        evidence=[Evidence.model_validate(item) for item in (evidence or [])],
        metadata=metadata,
        error=error,
        source_url=f"synthetic://signalweave/{adapter}/{resource}",
        captured_at=captured_at,
    ).model_dump(mode="json")


def _resource_record(
    *,
    adapter: str,
    resource: str,
    kind: str,
    title: str,
    description: str,
    snapshot: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "descriptor": ResourceDescriptor(
            adapter=adapter,
            resource=resource,
            kind=kind,
            title=title,
            description=description,
            source_url=snapshot.get("source_url"),
            metadata=metadata,
        ).model_dump(mode="json"),
        "snapshot": snapshot,
    }


def _domain_lookup(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(domain["id"]): domain for domain in config["domains"]}


def _variant_values(variant: str) -> tuple[float | None, float | None, float | None, str | None]:
    if variant == "corroborated_notify":
        return 82.0, 100.0, -18.0, None
    if variant == "explained_ignore":
        return 82.0, 100.0, -18.0, "expected seasonal movement"
    if variant == "contradictory_investigate":
        return 82.0, 100.0, -18.0, "ambiguous corroboration"
    if variant == "definition_mismatch":
        return 82.0, 100.0, -18.0, "ambiguous definition and grain"
    if variant == "stale_escalation":
        return 100.0, 100.0, 0.0, "stale: upstream refresh overdue"
    if variant == "missing_baseline":
        return 82.0, None, None, None
    if variant == "source_failure":
        return None, None, None, None
    raise ValueError(f"unknown trial variant: {variant}")


def _source_status(variant: str) -> str:
    if variant == "stale_escalation":
        return "stale"
    if variant == "missing_baseline":
        return "incomplete"
    if variant == "source_failure":
        return "unavailable"
    if variant == "contradictory_investigate":
        return "ambiguous"
    if variant == "definition_mismatch":
        return "ambiguous"
    return "fresh"


def _brief_for_variant(
    variant: str,
    persona: dict[str, Any],
    primary_metric: str,
    context_metric: str,
    domain_name: str,
) -> dict[str, Any]:
    if variant == "corroborated_notify":
        what = f"Monitor {primary_metric} and the related {context_metric} signal across {domain_name}."
        watch = [
            f"{primary_metric} moves materially away from its comparable baseline.",
            f"{context_metric} corroborates the movement with fresh evidence.",
            "The combined evidence is strong enough for the owning team to act.",
        ]
        questions = [f"Does the related {context_metric} signal support action on {primary_metric}?"]
    elif variant == "explained_ignore":
        what = f"Monitor {primary_metric} and determine whether its movement follows the expected operating cycle."
        watch = [
            f"{primary_metric} moves materially away from its comparable baseline.",
            f"{context_metric} moves in the same direction as expected context.",
            "The movement is explainable and should not create an operational notification.",
        ]
        questions = [f"Is the movement in {primary_metric} explained by the expected {context_metric} context?"]
    elif variant == "contradictory_investigate":
        what = f"Monitor {primary_metric} and check whether {context_metric} actually supports the same conclusion."
        watch = [
            f"{primary_metric} moves materially away from its comparable baseline.",
            f"{context_metric} does not provide reliable corroboration.",
            "The evidence is ambiguous and needs review before notification.",
        ]
        questions = [f"What evidence is missing before acting on the {primary_metric} movement?"]
    elif variant == "definition_mismatch":
        what = f"Monitor {primary_metric} with related {context_metric} context, but verify that both sources measure the same population and time grain."
        watch = [
            f"{primary_metric} moves materially away from its comparable baseline.",
            f"{context_metric} appears directionally related but uses a different definition, population, or grain.",
            "The evidence is not comparable enough for an automatic notification.",
        ]
        questions = [f"Are the {primary_metric} and {context_metric} definitions comparable enough to act?"]
    elif variant == "stale_escalation":
        what = f"Monitor the freshness and interpretability of {primary_metric} before using it for {persona['role_goal'].lower()}"
        watch = [
            f"The source feeding {primary_metric} is within its expected refresh window.",
            "A stale upstream refresh is surfaced before business movement is interpreted.",
        ]
        questions = [f"Can {primary_metric} be trusted while the upstream refresh is overdue?"]
    elif variant == "missing_baseline":
        what = f"Monitor whether {primary_metric} has enough comparable history to answer the business question."
        watch = [
            f"{primary_metric} has a current value and a comparable baseline.",
            "A missing baseline is treated as insufficient evidence rather than a normal movement.",
        ]
        questions = [f"Can the movement in {primary_metric} be compared safely right now?"]
    else:
        what = f"Monitor whether the source needed to interpret {primary_metric} is available and complete."
        watch = [
            f"The source feeding {primary_metric} returns observations instead of an error.",
            "A source failure is visible and does not become a business notification.",
        ]
        questions = [f"Can the card answer its business question when {primary_metric} data fails?"]
    return {
        "title": f"{persona['name']} — {domain_name} insight",
        "what_to_watch": what,
        "why_watch": persona["role_goal"],
        "watch_for": watch,
        "questions": questions,
        "comparison_windows": ["previous_period", "trailing_4_period_average"],
    }


def generate_fixture(
    config_path: str | Path = DEFAULT_CONFIG,
    output_path: str | Path | None = "artifacts/enterprise/northstar-fixture.json",
    *,
    seed: int | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    """Generate a large, reproducible enterprise catalog and hidden task labels."""
    config = load_config(config_path)
    if "portfolio" in config:
        return generate_portfolio_fixture(config_path, output_path, seed=seed)
    company = config["company"]
    company_slug = _slug(str(company["id"]))
    namespace_prefix = f"{namespace}-" if namespace else ""
    session_prefix = namespace or ""
    rng = random.Random(seed if seed is not None else int(company["seed"]))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    catalog = config["catalog"]
    domains = _domain_lookup(config)
    records: dict[tuple[str, str], dict[str, Any]] = {}
    dashboard_ids: list[str] = []

    def add_record(record: dict[str, Any]) -> None:
        descriptor = record["descriptor"]
        key = (str(descriptor["adapter"]), str(descriptor["resource"]))
        records[key] = record

    all_domains = list(config["domains"])
    for domain in all_domains:
        for dashboard_index in range(int(domain["dashboard_count"])):
            dashboard_id = f"{namespace_prefix}{domain['id']}-{dashboard_index + 1:03d}"
            dashboard_ids.append(dashboard_id)
            refresh = _weighted_choice(rng, catalog["refresh_profiles"], "weight")
            chart_count = rng.randint(*catalog["charts_per_dashboard"])
            charts: list[dict[str, Any]] = []
            observations: list[dict[str, Any]] = []
            dashboard_state = rng.choices(
                ["fresh", "delayed", "stale", "partial", "missing_baseline", "ambiguous", "failure"],
                weights=[55, 15, 10, 8, 5, 4, 3],
                k=1,
            )[0]
            age_hours = {
                "fresh": 0.5,
                "delayed": max(1.0, refresh["minutes"] / 60 * 1.5),
                "stale": max(26.0, refresh["minutes"] / 60 * 30),
                "partial": 1.0,
                "missing_baseline": 1.0,
                "ambiguous": 1.0,
                "failure": 1.0,
            }[dashboard_state]
            captured_at = now - timedelta(hours=age_hours)
            for chart_index in range(chart_count):
                chart_type = _weighted_choice(rng, catalog["chart_type_weights"], "weight")["name"]
                metric = domain["metrics"][chart_index % len(domain["metrics"])]
                chart_id = f"{dashboard_id}-chart-{chart_index + 1:02d}"
                baseline = round(80 + rng.random() * 160, 2)
                change = round(rng.uniform(-8, 8), 2)
                if dashboard_state == "missing_baseline" and chart_index == 0:
                    chart_baseline = None
                    chart_change = None
                    current = round(baseline * 0.82, 2)
                else:
                    chart_baseline = baseline
                    chart_change = change
                    current = round(baseline * (1 + change / 100), 2)
                if dashboard_state == "partial" and chart_index == chart_count - 1:
                    chart_error = "chart query timed out"
                    current = None
                    chart_change = None
                else:
                    chart_error = None
                chart = {
                    "id": chart_id,
                    "title": metric.title(),
                    "metric": metric,
                    "visualization": chart_type,
                    "description": f"{metric.title()} by region and channel at the {domain['name']} operating grain.",
                    "error": chart_error,
                    "related_chart_ids": [],
                }
                charts.append(chart)
                if chart_error is None:
                    observations.append(
                        _make_observation(
                            f"superset-{dashboard_id}",
                            chart_id,
                            chart["title"],
                            metric,
                            current=current,
                            baseline=chart_baseline,
                            change_pct=chart_change,
                            attributes={
                                "visualization": chart_type,
                                "data_state": dashboard_state,
                                "metric_definition": f"{metric} for the dashboard's published population",
                                "grain": "day x region x channel",
                                "filters": "published dashboard filters",
                                "refresh_profile": refresh["name"],
                            },
                            dimensions={
                                "region": rng.choice(["global", "north_america", "emea", "apac"]),
                                "channel": rng.choice(["all", "web", "store", "partner"]),
                            },
                            freshness=(
                                f"stale: snapshot is {age_hours:g} hours old"
                                if dashboard_state == "stale"
                                else None
                            ),
                            source_url=f"synthetic://{company_slug}/superset/dashboard/{dashboard_id}/chart/{chart_id}",
                        )
                    )
            for left, right in zip(charts, charts[1:], strict=False):
                left["related_chart_ids"].append(right["id"])
            dashboard_title = f"{domain['name']} — {domain['metrics'][0].title()} — {dashboard_index + 1:03d}"
            dashboard_resource = f"dashboard:{dashboard_id}"
            description = (
                f"{domain['name']} dashboard owned by {domain['owner_team']}; "
                f"refreshes {refresh['name']} and contains {chart_count} visualizations."
            )
            dashboard_snapshot = _snapshot(
                source_key=f"superset-{dashboard_id}",
                adapter="superset",
                resource=dashboard_resource,
                title=dashboard_title,
                description=description,
                observations=observations,
                metadata={
                    "provider": "superset",
                    "dashboard_id": dashboard_id,
                    "domain": domain["id"],
                    "owner_team": domain["owner_team"],
                    "refresh_profile": refresh["name"],
                    "refresh_period_minutes": refresh["minutes"],
                    "data_state": dashboard_state,
                    "charts": charts,
                    "source_system": f"{company_slug}-superset",
                },
                captured_at=captured_at,
                error=("dashboard query failed" if dashboard_state == "failure" else None),
            )
            add_record(
                _resource_record(
                    adapter="superset",
                    resource=dashboard_resource,
                    kind="dashboard",
                    title=dashboard_title,
                    description=description,
                    snapshot=dashboard_snapshot,
                    metadata={
                        "domain": domain["id"],
                        "owner_team": domain["owner_team"],
                        "refresh_profile": refresh["name"],
                        "refresh_period_minutes": refresh["minutes"],
                        "data_state": dashboard_state,
                        "chart_count": chart_count,
                        "chart_types": sorted({chart["visualization"] for chart in charts}),
                    },
                )
            )
            source_specs = [
                (
                    "sql",
                    f"query:{dashboard_id}-quality",
                    "query",
                    f"{domain['name']} reviewed quality query",
                    "A reviewed SQL query over warehouse quality signals.",
                    "query_success_rate",
                    99.2,
                    "warehouse query success rate",
                ),
                (
                    "airflow",
                    f"dag:{dashboard_id}-refresh",
                    "dag",
                    f"{domain['name']} refresh DAG",
                    "The orchestrator run and upstream freshness status.",
                    "dag_success",
                    1.0,
                    "published refresh DAG success",
                ),
                (
                    "table",
                    f"table:{dashboard_id}-facts",
                    "table",
                    f"{domain['name']} facts quality",
                    "Freshness, null-rate, row-count, and schema checks.",
                    "freshness_hours",
                    round(age_hours, 2),
                    "upstream table freshness in hours",
                ),
            ]
            for adapter, resource, kind, title, source_description, metric, value, label in source_specs:
                source_key = f"{adapter}-{_slug(resource)}"
                source_state = dashboard_state
                current_value = value
                baseline_value = value
                change_value = 0.0
                if adapter == "airflow" and dashboard_state in {"stale", "failure"}:
                    current_value = 0.0
                    change_value = -100.0
                if adapter == "table" and dashboard_state == "stale":
                    current_value = round(age_hours, 2)
                    change_value = round(current_value - 1.0, 2)
                connection_snapshot = _snapshot(
                    source_key=source_key,
                    adapter=adapter,
                    resource=resource,
                    title=title,
                    description=source_description,
                    observations=[
                        _make_observation(
                            source_key,
                            resource,
                            label,
                            metric,
                            current=current_value,
                            baseline=baseline_value,
                            change_pct=change_value,
                            attributes={
                                "data_state": source_state,
                                "connection_type": adapter,
                                "refresh_profile": refresh["name"],
                            },
                            freshness=(
                                f"stale: upstream is {age_hours:g} hours old"
                                if dashboard_state == "stale"
                                else None
                            ),
                            source_url=f"synthetic://{company_slug}/{adapter}/{resource}",
                        )
                    ],
                    metadata={
                        "provider": adapter,
                        "domain": domain["id"],
                        "owner_team": domain["owner_team"],
                        "data_state": source_state,
                        "refresh_profile": refresh["name"],
                        "linked_dashboard": dashboard_id,
                    },
                    captured_at=captured_at,
                )
                add_record(
                    _resource_record(
                        adapter=adapter,
                        resource=resource,
                        kind=kind,
                        title=title,
                        description=source_description,
                        snapshot=connection_snapshot,
                        metadata={
                            "domain": domain["id"],
                            "owner_team": domain["owner_team"],
                            "linked_dashboard": dashboard_id,
                            "data_state": source_state,
                        },
                    )
                )

    personas = config["personas"]
    tasks: list[dict[str, Any]] = []
    for persona_index, persona in enumerate(personas):
        domain = domains[persona["domain"]]
        primary_metric = domain["metrics"][persona_index % len(domain["metrics"])]
        context_domain = all_domains[(all_domains.index(domain) + 1) % len(all_domains)]
        context_metric = context_domain["metrics"][persona_index % len(context_domain["metrics"])]
        for variant_index, variant in enumerate(config["task_variants"]):
            persona_id = f"{namespace}:{persona['id']}" if namespace else persona["id"]
            task_id = f"task-{namespace_prefix}{persona['id']}-{variant}"
            case_token = (
                f"{session_prefix}-case-{len(tasks) + 1:03d}"
                if session_prefix
                else f"case-{len(tasks) + 1:03d}"
            )
            scenario_id = f"scenario-{namespace_prefix}{persona_index + 1:02d}-{variant_index + 1:02d}"
            primary_id = f"{scenario_id}-primary"
            context_id = f"{scenario_id}-context"
            primary_resource = f"dashboard:{primary_id}"
            context_adapter = ("superset", "sql", "airflow", "table", "incident", "calendar")[
                (persona_index + variant_index) % 6
            ]
            context_resource = f"dashboard:{context_id}" if context_adapter == "superset" else f"{context_adapter}:{context_id}"
            primary_source_key = f"{case_token}-primary"
            context_source_key = f"{case_token}-context"
            primary_current, primary_baseline, primary_change, freshness = _variant_values(variant)
            context_current = 100.0
            context_baseline = 100.0
            context_change = 0.0
            if variant == "corroborated_notify":
                context_current = 135.0
                context_change = 35.0
            elif variant == "explained_ignore":
                context_current = 82.0
                context_change = -18.0
            elif variant == "contradictory_investigate":
                context_current = 101.0
                context_change = 1.0
            elif variant == "definition_mismatch":
                context_current = 135.0
                context_change = 35.0
            primary_title = f"{domain['name']} {primary_metric} signal"
            context_title = f"{context_domain['name']} {context_metric} context"
            primary_observations = []
            if variant != "source_failure":
                primary_observations.append(
                    _make_observation(
                        primary_source_key,
                        f"{case_token}-primary-metric",
                        primary_title,
                        primary_metric,
                        current=primary_current,
                        baseline=primary_baseline,
                        change_pct=primary_change,
                        freshness=freshness,
                        attributes={
                            "source_status": _source_status(variant),
                            "metric_definition": f"{primary_metric} for the {domain['name']} operating population",
                            "grain": "day x region",
                            "filters": "published scenario filters",
                            "dashboard_id": primary_id,
                        },
                        dimensions={"region": "global", "channel": "all"},
                        source_url=f"synthetic://{company_slug}/superset/{primary_resource}",
                    )
                )
            # The snapshot is recent, but its upstream observation is explicitly
            # stale. This exercises the engine's freshness gate rather than the
            # separate "snapshot itself is too old" insufficient-data gate.
            primary_captured_at = now - timedelta(hours=1)
            primary_snapshot = _snapshot(
                source_key=primary_source_key,
                adapter="superset",
                resource=primary_resource,
                title=primary_title,
                description=f"Scenario dashboard for {persona['name']} with multiple visualizations.",
                observations=primary_observations,
                metadata={
                    "provider": "superset",
                    "dashboard_id": primary_id,
                    "domain": domain["id"],
                    "owner_team": domain["owner_team"],
                    "source_status": _source_status(variant),
                    "refresh_period_minutes": 60,
                    "charts": [
                        {"id": f"{primary_id}-line", "title": primary_metric, "visualization": "line"},
                        {"id": f"{primary_id}-kpi", "title": "Current status", "visualization": "big_number"},
                        {"id": f"{primary_id}-breakdown", "title": "Regional breakdown", "visualization": "bar"},
                        {"id": f"{primary_id}-detail", "title": "Evidence detail", "visualization": "table"},
                    ],
                },
                captured_at=primary_captured_at,
                error=("scenario source timed out" if variant == "source_failure" else None),
            )
            add_record(
                _resource_record(
                    adapter="superset",
                    resource=primary_resource,
                    kind="dashboard",
                    title=primary_title,
                    description=primary_snapshot["description"],
                    snapshot=primary_snapshot,
                    metadata={
                        "domain": domain["id"],
                        "owner_team": domain["owner_team"],
                        "source_status": _source_status(variant),
                        "chart_types": ["line", "big_number", "bar", "table"],
                    },
                )
            )
            context_snapshot = _snapshot(
                source_key=context_source_key,
                adapter=context_adapter,
                resource=context_resource,
                title=context_title,
                description=f"Cross-source context for {persona['name']} from {context_adapter}.",
                observations=[
                    _make_observation(
                        context_source_key,
                        f"{case_token}-context-metric",
                        context_title,
                        context_metric,
                        current=context_current,
                        baseline=context_baseline,
                        change_pct=context_change,
                        attributes={
                            "source_status": _source_status(variant),
                            "connection_type": context_adapter,
                            "metric_definition": (
                                f"{context_metric} from the related {context_domain['name']} source"
                                if variant != "definition_mismatch"
                                else f"{context_metric} for a different population at weekly grain"
                            ),
                            "grain": "day x region" if variant != "definition_mismatch" else "week x account",
                            "case_ref": case_token,
                        },
                        freshness=("stale: related context overdue" if variant == "stale_escalation" else None),
                        source_url=f"synthetic://{company_slug}/{context_adapter}/{context_resource}",
                    )
                ],
                metadata={
                    "provider": context_adapter,
                    "domain": context_domain["id"],
                    "owner_team": context_domain["owner_team"],
                    "source_status": _source_status(variant),
                    "linked_dashboard": primary_id,
                },
                captured_at=now - timedelta(hours=1),
                evidence=[
                    {
                        "source_key": context_source_key,
                        "subject_id": f"{case_token}-context-metric",
                        "subject_label": context_title,
                        "statement": f"Context was supplied by the approved {context_adapter} connection.",
                        "values": {"connection_type": context_adapter, "case_ref": case_token},
                        "source_url": f"synthetic://{company_slug}/{context_adapter}/{context_resource}",
                    }
                ],
            )
            add_record(
                _resource_record(
                    adapter=context_adapter,
                    resource=context_resource,
                    kind=("dashboard" if context_adapter == "superset" else context_adapter),
                    title=context_title,
                    description=context_snapshot["description"],
                    snapshot=context_snapshot,
                    metadata={
                        "domain": context_domain["id"],
                        "owner_team": context_domain["owner_team"],
                        "source_status": _source_status(variant),
                        "linked_dashboard": primary_id,
                    },
                )
            )
            methods = [
                DeliveryMethod(
                    key=f"{domain['id']}-notify",
                    outcome=Outcome.NOTIFY,
                    label=domain["owner_team"],
                    destination=f"slack://{_slug(domain['owner_team'])}",
                    instructions=f"Notify {domain['owner_team']} when fresh corroborating evidence supports a non-urgent action.",
                ),
                DeliveryMethod(
                    key=f"{domain['id']}-escalate",
                    outcome=Outcome.ESCALATE,
                    label=domain["owner_team"],
                    destination=f"slack://{_slug(domain['owner_team'])}",
                    instructions=f"Escalate to {domain['owner_team']} when data trust or urgency requires attention.",
                ),
            ]
            expected_outcome = {
                "corroborated_notify": Outcome.NOTIFY,
                "explained_ignore": Outcome.IGNORE,
                "contradictory_investigate": Outcome.INVESTIGATE,
                "definition_mismatch": Outcome.INVESTIGATE,
                "stale_escalation": Outcome.ESCALATE,
                "missing_baseline": Outcome.INSUFFICIENT_DATA,
                "source_failure": Outcome.INSUFFICIENT_DATA,
            }[variant]
            expected_methods = [
                method.key for method in methods if method.outcome == expected_outcome
            ]
            brief = _brief_for_variant(variant, persona, primary_metric, context_metric, domain["name"])
            task = TrialTask(
                id=task_id,
                persona_id=persona_id,
                variant=variant,
                goal=(
                    f"{brief['what_to_watch']} Purpose: {brief['why_watch']} "
                    f"Use the {company['name']} {domain['name']} operating context."
                ),
                brief={
                    **brief,
                    "persona": {**persona, "id": persona_id},
                    "enterprise_name": company["name"],
                    "domain": domain["name"],
                    "delivery_context": [method.model_dump(mode="json") for method in methods],
                    "source_hints": [primary_title, context_title],
                },
                expected_outcome=expected_outcome,
                expected_delivery_methods=expected_methods,
                expected_source_resources=[
                    f"superset|{primary_resource}",
                    f"{context_adapter}|{context_resource}",
                ],
                enterprise_objective=(
                    f"Reduce avoidable {domain['name'].lower()} monitoring work while preventing unsafe automatic action."
                ),
                false_action_cost=10 if expected_outcome in {Outcome.ESCALATE, Outcome.NOTIFY} else 6,
            )
            tasks.append(
                {
                    **task.__dict__,
                    "session_token": case_token,
                    "expected_outcome": task.expected_outcome.value,
                    "source_refs": [
                        {
                            "key": primary_source_key,
                            "adapter": "superset",
                            "resource": primary_resource,
                            "label": primary_title,
                            "parameters": {},
                            "required": True,
                        },
                        {
                            "key": context_source_key,
                            "adapter": context_adapter,
                            "resource": context_resource,
                            "label": context_title,
                            "parameters": {},
                            "required": True,
                        },
                    ],
                    "expected_delivery_methods": expected_methods,
                }
            )

    fixture = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "seed": seed if seed is not None else int(company["seed"]),
        "company": {**company, "experiment_namespace": namespace},
        "stats": {
            "base_dashboards": len(dashboard_ids),
            "scenario_dashboards": sum(
                1
                for item in records.values()
                if str(item["descriptor"]["resource"]).startswith("dashboard:scenario-")
            ),
            "resources": len(records),
            "charts": sum(
                len(item["snapshot"].get("metadata", {}).get("charts", []))
                for item in records.values()
                if item["descriptor"]["kind"] == "dashboard"
            ),
            "tasks": len(tasks),
            "personas": len(personas),
            "adapters": sorted({adapter for adapter, _ in records}),
            "enterprise_id": company["id"],
        },
        "resources": list(records.values()),
        "tasks": tasks,
    }
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(fixture, indent=2) + "\n")
    return fixture


def generate_portfolio_fixture(
    config_path: str | Path,
    output_path: str | Path | None = "artifacts/enterprise/enterprise-portfolio.json",
    *,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate one isolated, namespaced fixture containing several companies."""
    portfolio_path = Path(config_path)
    portfolio = load_config(portfolio_path)["portfolio"]
    if not isinstance(portfolio.get("companies"), list) or not portfolio["companies"]:
        raise ValueError("enterprise portfolio must contain a non-empty companies list")

    children: list[dict[str, Any]] = []
    for index, entry in enumerate(portfolio["companies"]):
        if not isinstance(entry, dict) or not entry.get("config") or not entry.get("namespace"):
            raise ValueError("each portfolio company needs config and namespace")
        child_path = (portfolio_path.parent / str(entry["config"])).resolve()
        child_config = load_config(child_path)
        if "company" not in child_config:
            raise ValueError(f"portfolio company config must define company: {child_path}")
        child_seed = seed + index if seed is not None else int(child_config["company"]["seed"])
        children.append(
            generate_fixture(
                child_config,
                output_path=None,
                seed=child_seed,
                namespace=_slug(str(entry["namespace"])),
            )
        )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    stats = {
        "enterprises": len(children),
        "base_dashboards": sum(item["stats"]["base_dashboards"] for item in children),
        "scenario_dashboards": sum(item["stats"]["scenario_dashboards"] for item in children),
        "resources": sum(item["stats"]["resources"] for item in children),
        "charts": sum(item["stats"]["charts"] for item in children),
        "tasks": sum(item["stats"]["tasks"] for item in children),
        "personas": sum(item["stats"]["personas"] for item in children),
        "adapters": sorted({adapter for item in children for adapter in item["stats"]["adapters"]}),
    }
    fixture = {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "seed": seed,
        "portfolio": {
            "id": portfolio.get("id", "signalweave-enterprise-portfolio"),
            "name": portfolio.get("name", "SignalWeave enterprise portfolio"),
            "companies": [item["company"] for item in children],
        },
        "stats": stats,
        "resources": [resource for item in children for resource in item["resources"]],
        "tasks": [task for item in children for task in item["tasks"]],
    }
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(fixture, indent=2) + "\n")
    return fixture


class SyntheticEnterpriseAdapter:
    """Read-only adapter over generated fixture resources."""

    def __init__(self, adapter: str, records: list[dict[str, Any]]) -> None:
        self.name = adapter
        self._records = {
            str(record["descriptor"]["resource"]): record
            for record in records
            if record["descriptor"]["adapter"] == adapter
        }

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor.model_validate(record["descriptor"])
            for record in sorted(self._records.values(), key=lambda item: item["descriptor"]["title"])
        ]

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        try:
            record = self._records[source.resource]
        except KeyError as error:
            raise KeyError(f"synthetic resource not found: {self.name}|{source.resource}") from error
        delay_ms = int(record["snapshot"].get("metadata", {}).get("inspection_delay_ms", 0))
        if delay_ms:
            await asyncio.sleep(min(delay_ms, 30) / 1000)
        return ResourceSnapshot.model_validate(record["snapshot"]).model_copy(
            update={"source_key": source.key}
        )


class TracedAdapter:
    def __init__(self, adapter: SourceAdapter, sink: TraceSink, actor: str, session_id: str) -> None:
        self._adapter = adapter
        self._sink = sink
        self._actor = actor
        self._session_id = session_id
        self.name = adapter.name

    async def list_resources(self) -> list[ResourceDescriptor]:
        started = time.perf_counter()
        resources = await self._adapter.list_resources()
        self._sink.emit(
            "source.list.completed",
            actor=self._actor,
            session_id=self._session_id,
            payload={"adapter": self.name, "count": len(resources), "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)},
        )
        return resources

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        started = time.perf_counter()
        try:
            snapshot = await self._adapter.inspect(source)
        except Exception as error:  # noqa: BLE001 - trace then let SourceRegistry apply its contract
            self._sink.emit(
                "source.inspect.failed",
                actor=self._actor,
                session_id=self._session_id,
                payload={"adapter": self.name, "resource": source.resource, "error": f"{type(error).__name__}: {error}"},
            )
            raise
        self._sink.emit(
            "source.inspect.completed",
            actor=self._actor,
            session_id=self._session_id,
            payload={
                "adapter": self.name,
                "source_key": source.key,
                "resource": source.resource,
                "observation_count": len(snapshot.observations),
                "evidence_count": len(snapshot.evidence),
                "error": snapshot.error,
                "captured_at": snapshot.captured_at.isoformat(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return snapshot


class ResearchJudger:
    """Explicit deterministic semantic driver for MCP wiring and load tests.

    It is not an accuracy claim for Jev. It exists so the MCP-only experiment can
    run without silently changing the production runtime or pretending that a
    missing TypeSafe credential is a model result.
    """

    name = "research-test-double"

    async def rank_resources(
        self, goal: str, resources: list[ResourceDescriptor]
    ) -> dict[str, float]:
        goal_terms = _terms(goal)
        scores: dict[str, float] = {}
        for resource in resources:
            text = " ".join(
                [
                    resource.adapter,
                    resource.resource,
                    resource.kind,
                    resource.title,
                    resource.description,
                    json.dumps(resource.metadata, sort_keys=True),
                ]
            )
            overlap = len(goal_terms & _terms(text))
            score = min(0.99, 0.15 + overlap / max(8, len(goal_terms)))
            scores[f"{resource.adapter}|{resource.resource}"] = round(score, 4)
        return scores

    async def compile_plan(self, state: dict[str, Any], card: InsightCard) -> dict[str, Any]:
        available = state.get("available_capabilities", [])
        text = json.dumps(card.model_dump(mode="json")).lower()
        selected = [
            item["key"]
            for item in available
            if item["key"] in text or item["key"] in {"percent_change", "baseline_comparison", "freshness_check"}
        ]
        return {
            "capabilities": selected,
            "baseline": card.comparison_windows[0] if card.comparison_windows else "previous_period",
        }

    async def judge(
        self,
        state: dict[str, Any],
        card: InsightCard,
        plan: InsightPlan,
        observations: list[Observation],
    ) -> InsightResult:
        del plan
        text = json.dumps(card.model_dump(mode="json")).lower()
        changes = [item.change_pct for item in observations if item.change_pct is not None]
        negative = [change for change in changes if change <= -10]
        positive = [change for change in changes if change >= 10]
        paired_expected = any(
            phrase in text
            for phrase in ("expected context", "explained by the expected", "expected operating cycle")
        )
        ambiguous = any(
            phrase in text
            for phrase in (
                "ambiguous",
                "before notification",
                "missing",
                "not comparable",
                "different definition",
                "different population",
                "different grain",
            )
        )
        if paired_expected and len(negative) >= 1:
            selected = Outcome.IGNORE
        elif negative and ambiguous:
            selected = Outcome.INVESTIGATE
        elif negative and positive:
            selected = Outcome.NOTIFY
        elif negative:
            selected = Outcome.INVESTIGATE
        else:
            selected = Outcome.IGNORE
        probabilities = {
            Outcome.IGNORE.value: 0.92 if selected == Outcome.IGNORE else 0.08,
            Outcome.INVESTIGATE.value: 0.92 if selected == Outcome.INVESTIGATE else 0.08,
        }
        for method in card.delivery_methods:
            probabilities.setdefault(method.outcome.value, 0.08)
        probabilities[selected.value] = 0.92
        return InsightResult(
            card_id=card.id,
            outcome=selected,
            summary=f"Research driver evaluated {len(observations)} observations across {len(card.sources)} sources.",
            rationale="Deterministic experiment driver; this result is not a live Jev measurement.",
            confidence=0.92,
            probabilities=probabilities,
            watch_results=[
                WatchResult(
                    key=f"watch_{index}",
                    watch_for=item,
                    status=WatchStatus.PRESENT if observations else WatchStatus.UNKNOWN,
                    probability=0.82 if observations else 0.4,
                )
                for index, item in enumerate(card.watch_for)
            ],
            question_results=[
                QuestionResult(
                    key=f"question_{index}",
                    question=item,
                    status=QuestionStatus.SUPPORTED if observations else QuestionStatus.UNKNOWN,
                    probability=0.82 if observations else 0.4,
                )
                for index, item in enumerate(card.questions)
            ],
            evidence=[Evidence.model_validate(item) for item in state.get("evidence", [])],
            observations=observations,
            source_keys=[source.key for source in card.sources],
            evaluator=self.name,
        )


class TracedJudger:
    def __init__(self, delegate: InsightJudger, sink: TraceSink, actor: str, session_id: str) -> None:
        self._delegate = delegate
        self._sink = sink
        self._actor = actor
        self._session_id = session_id
        self.name = delegate.name

    async def rank_resources(self, goal: str, resources: list[ResourceDescriptor]) -> dict[str, float]:
        started = time.perf_counter()
        result = await self._delegate.rank_resources(goal, resources)
        self._sink.emit(
            "semantic.rank.completed",
            actor=self._actor,
            session_id=self._session_id,
            payload={"evaluator": self.name, "candidate_count": len(resources), "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)},
        )
        return result

    async def compile_plan(self, state: dict[str, Any], card: InsightCard) -> dict[str, Any]:
        started = time.perf_counter()
        result = await self._delegate.compile_plan(state, card)
        self._sink.emit(
            "semantic.compile.completed",
            actor=self._actor,
            session_id=self._session_id,
            payload={"evaluator": self.name, "card_id": card.id, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), "result_hash": _stable_hash(result)},
        )
        return result

    async def judge(self, state: dict[str, Any], card: InsightCard, plan: InsightPlan, observations: list[Observation]) -> InsightResult:
        started = time.perf_counter()
        result = await self._delegate.judge(state, card, plan, observations)
        self._sink.emit(
            "semantic.judge.completed",
            actor=self._actor,
            session_id=self._session_id,
            payload={
                "evaluator": self.name,
                "card_id": card.id,
                "observation_count": len(observations),
                "outcome": result.outcome.value,
                "confidence": result.confidence,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return result


def build_experiment_runtime(
    fixture: dict[str, Any],
    *,
    store_path: str | Path,
    trace: TraceSink,
    actor: str,
    session_id: str,
    evaluator: str = "research",
) -> Runtime:
    records = fixture["resources"]
    adapters = [
        TracedAdapter(SyntheticEnterpriseAdapter(adapter, records), trace, actor, session_id)
        for adapter in fixture["stats"]["adapters"]
    ]
    registry = SourceRegistry(adapters, max_concurrency=16)
    if evaluator == "research":
        delegate: InsightJudger = ResearchJudger()
    elif evaluator == "jev":
        key = load_api_key()
        if not key:
            raise RuntimeError("evaluator=jev requires TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE")
        delegate = JevJudger(api_key=key)
    else:
        raise ValueError("evaluator must be research or jev")
    judger = TracedJudger(delegate, trace, actor, session_id)
    return Runtime(
        card_store=JsonInsightCardStore(store_path),
        sources=registry,
        engine=InsightEngine(judger=judger, registry=registry),
    )


def load_fixture(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") not in {1, 2}:
        raise ValueError("enterprise fixture must have schema_version=1 or 2")
    return payload


def task_by_id(fixture: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in fixture["tasks"]:
        if task["id"] == task_id:
            return task
    raise KeyError(f"unknown enterprise task: {task_id}")


def make_task_prompt(task: dict[str, Any], *, mcp_command: str) -> str:
    brief = task["brief"]
    methods = json.dumps(brief["delivery_context"], indent=2)
    enterprise_name = brief.get("enterprise_name", "the simulated enterprise")
    return f"""You are acting as {brief['persona']['name']} at {enterprise_name}.

Your technical literacy is {brief['persona']['technical_literacy']}. You have only the
SignalWeave MCP interface, exposed through this command:

{mcp_command}

You may call only these MCP tools: {', '.join(ALLOWED_MCP_TOOLS)}. Do not inspect the
repository, read the fixture, call Superset directly, use SQL/Airflow directly, use a
webhook, or invent hidden facts. Every business-data interaction must be an MCP tool
call through the command above. Use the returned catalog and evidence as your only
data.

Your task:
- What to watch: {brief['what_to_watch']}
- Why: {brief['why_watch']}
- Things to look for: {json.dumps(brief['watch_for'])}
- Questions to answer: {json.dumps(brief['questions'])}
- Approved delivery options, if evidence supports them:
{methods}

Work through discovery, draft a card from returned source references, simulate it,
approve it only if the card is well-defined, and evaluate it. Use the MCP outputs to
decide what to do. Do not assume that a source is trustworthy just because it exists.
Finish with a short explanation of the evidence and the action you would take.
"""


def score_trace(fixture: dict[str, Any], trace_path: str | Path) -> dict[str, Any]:
    """Score MCP sessions without exposing expected labels to persona agents."""
    events = [json.loads(line) for line in Path(trace_path).read_text().splitlines() if line.strip()]
    trace_integrity = audit_trace(trace_path)
    by_session: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_session.setdefault(event["session_id"], []).append(event)
    task_by_session = {
        event["session_id"]: event["payload"].get("task_token", event["payload"].get("task_id"))
        for event in events
        if event["event_type"] == "session.started"
        and ("task_token" in event["payload"] or "task_id" in event["payload"])
    }
    task_map = {task["id"]: task for task in fixture["tasks"]}
    task_map.update({task["session_token"]: task for task in fixture["tasks"]})
    sessions: list[dict[str, Any]] = []
    for session_id, session_events in sorted(by_session.items()):
        task_id = task_by_session.get(session_id)
        task = task_map.get(task_id or "")
        completed_events = [
            event for event in session_events if event["event_type"] == "mcp.call.completed"
        ]
        completed_tools = [event["payload"].get("tool") for event in completed_events]
        protocol_tools = [
            ("draft_insight_card", "propose_insight_card"),
            ("simulate_insight_card",),
            ("approve_insight_card",),
            ("evaluate_insight_card",),
        ]
        protocol_positions: list[int] = []
        for alternatives in protocol_tools:
            positions = [completed_tools.index(tool) for tool in alternatives if tool in completed_tools]
            protocol_positions.append(min(positions) if positions else -1)
        workflow_complete = (
            all(position >= 0 for position in protocol_positions)
            and protocol_positions == sorted(protocol_positions)
        )
        card_events = [
            event
            for event in completed_events
            if event["payload"].get("tool") in {"draft_insight_card", "propose_insight_card", "approve_insight_card"}
        ]
        saved_card: dict[str, Any] = {}
        for card_event in reversed(card_events):
            card_payload = card_event["payload"].get("result", {})
            card_result = (
                card_payload.get("result", card_payload)
                if isinstance(card_payload, dict)
                else {}
            )
            if isinstance(card_result, dict) and isinstance(card_result.get("proposal"), dict):
                candidate = card_result["proposal"].get("card", {})
            else:
                candidate = card_result.get("card", {}) if isinstance(card_result, dict) else {}
            if candidate:
                saved_card = candidate
                break
        card_complete = bool(
            saved_card.get("what_to_watch")
            and saved_card.get("why_watch")
            and (saved_card.get("watch_for") or saved_card.get("questions"))
            and saved_card.get("sources")
        )
        completed = [
            event
            for event in session_events
            if event["event_type"] == "mcp.call.completed"
            and event["payload"].get("tool") == "evaluate_insight_card"
        ]
        result_payload = completed[-1]["payload"].get("result", {}) if completed else {}
        result = result_payload.get("result", result_payload) if isinstance(result_payload, dict) else {}
        actual_outcome = result.get("outcome")
        actual_methods = [item.get("key") for item in result.get("delivery_methods", [])]
        source_keys = set(result.get("source_keys", []))
        evidence = result.get("evidence", [])
        expected_outcome = task.get("expected_outcome") if task else None
        expected_methods = task.get("expected_delivery_methods", []) if task else []
        inspected_source_keys = {
            event["payload"].get("source_key")
            for event in session_events
            if event["event_type"] == "source.inspect.completed"
        }
        evidence_source_keys = {item.get("source_key") for item in evidence if item.get("source_key")}
        expected_source_keys = {
            source.get("key") for source in (task.get("source_refs", []) if task else [])
        }
        source_selection_exact = bool(task) and source_keys == expected_source_keys
        provenance = bool(evidence) and bool(source_keys) and bool(inspected_source_keys)
        provenance = provenance and evidence_source_keys.issubset(source_keys)
        provenance = provenance and source_keys.issubset(inspected_source_keys)
        exact = (
            workflow_complete
            and card_complete
            and actual_outcome == expected_outcome
            and actual_methods == expected_methods
        )
        automatic = actual_outcome in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
        unsafe = automatic and (not exact or not workflow_complete or not provenance)
        sessions.append(
            {
                "session_id": session_id,
                "task_id": task_id,
                "persona_id": task.get("persona_id") if task else None,
                "variant": task.get("variant") if task else None,
                "expected_outcome": expected_outcome,
                "actual_outcome": actual_outcome,
                "expected_delivery_methods": expected_methods,
                "actual_delivery_methods": actual_methods,
                "exact_decision": exact,
                "provenance_complete": provenance,
                "workflow_complete": workflow_complete,
                "card_complete": card_complete,
                "source_selection_exact": source_selection_exact,
                "unsafe_automatic_action": unsafe,
                "mcp_calls": sum(1 for event in session_events if event["event_type"] == "mcp.call.completed"),
                "trace_events": len(session_events),
                "last_evidence_count": len(evidence),
            }
        )
    counts = Counter(item["actual_outcome"] for item in sessions if item["actual_outcome"])
    return {
        "session_count": len(sessions),
        "exact_decisions": sum(1 for item in sessions if item["exact_decision"]),
        "provenance_complete": sum(1 for item in sessions if item["provenance_complete"]),
        "workflow_complete": sum(1 for item in sessions if item["workflow_complete"]),
        "card_complete": sum(1 for item in sessions if item["card_complete"]),
        "source_selection_exact": sum(1 for item in sessions if item["source_selection_exact"]),
        "unsafe_automatic_actions": sum(1 for item in sessions if item["unsafe_automatic_action"]),
        "outcomes": dict(counts),
        "trace_integrity": trace_integrity,
        "sessions": sessions,
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# SignalWeave enterprise readiness experiment",
        "",
        "This report scores MCP-only persona sessions over a generated multi-enterprise catalog.",
        "",
        f"- Sessions: {report['session_count']}",
        f"- Exact decisions: {report['exact_decisions']}/{report['session_count']}",
        f"- Complete provenance: {report['provenance_complete']}/{report['session_count']}",
        f"- Unsafe automatic actions: {report['unsafe_automatic_actions']}",
        f"- Trace integrity: {'valid' if report.get('trace_integrity', {}).get('valid') else 'invalid'}",
        f"- Outcomes: `{json.dumps(report['outcomes'], sort_keys=True)}`",
        "",
        "| Persona | Variant | Expected | Actual | Exact | Provenance | MCP calls | Unsafe automatic action |",
        "| --- | --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for item in report["sessions"]:
        lines.append(
            f"| {item['persona_id']} | {item['variant']} | {item['expected_outcome']} | "
            f"{item['actual_outcome'] or 'no decision'} | {'yes' if item['exact_decision'] else 'no'} | "
            f"{'yes' if item['provenance_complete'] else 'no'} | {item['mcp_calls']} | "
            f"{'yes' if item['unsafe_automatic_action'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"

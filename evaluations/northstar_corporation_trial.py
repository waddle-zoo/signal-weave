"""Run an organization-level Northstar Outfitters SignalWeave trial.

This is evaluation-only. It models a small corporation's analytical operating
system around the existing Northstar fixture:

* domain curators and analysts own human-authored cards;
* operations roles review cross-domain evidence;
* executives receive only the routed decision receipt;
* communication roles acknowledge the simulated handoff.

The role graph is deliberately separate from production code. SignalWeave is
still responsible only for source resolution, evidence construction, typed Jev
judgment, and an inspectable result. No Slack or other external destination is
contacted by this trial.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.enterprise_runner import call_tool
from evaluations.enterprise_trial import (
    TraceSink,
    audit_trace,
    build_experiment_runtime,
    generate_fixture,
    load_config,
)
from signalweave.mcp_server import create_mcp
from signalweave.models import Outcome

DEFAULT_CORPORATION_CONFIG = Path(__file__).parent / "data" / "northstar-corporation.json"


def load_corporation_config(path: str | Path = DEFAULT_CORPORATION_CONFIG) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != 1:
        raise ValueError("corporation config must have schema_version=1")
    for key in ("company", "monitor_variants", "role_groups", "automation_policy"):
        if key not in payload:
            raise ValueError(f"corporation config is missing {key}")
    return payload


def _slug(value: str) -> str:
    return "-".join("".join(character.lower() if character.isalnum() else " " for character in value).split())


def build_agent_roster(
    corporation: dict[str, Any], base_config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build the 40-person role roster from the editable corporation config."""
    agents: list[dict[str, Any]] = []
    for domain in base_config["domains"]:
        domain_id = str(domain["id"])
        domain_name = str(domain["name"])
        metrics = ", ".join(str(metric) for metric in domain["metrics"])
        agents.append(
            {
                "id": f"domain-curator-{domain_id}",
                "name": f"{domain_name} Dashboard Curator",
                "group": "dashboard_curator",
                "domain": domain_id,
                "expertise": f"human intent and owner context for {domain_name}; governed metrics: {metrics}",
            }
        )
        agents.append(
            {
                "id": f"domain-analyst-{domain_id}",
                "name": f"{domain_name} Analysis Lead",
                "group": "domain_analyst",
                "domain": domain_id,
                "expertise": f"cross-chart interpretation and operational diagnosis for {domain_name}",
            }
        )

    for group in ("enterprise_operations", "executives", "communications"):
        for role in corporation["role_groups"][group]:
            agents.append(
                {
                    "id": str(role["id"]),
                    "name": str(role["name"]),
                    "group": group,
                    "domain": "enterprise",
                    "expertise": str(role["expertise"]),
                }
            )

    if len(agents) != 40:
        raise ValueError(f"Northstar corporation roster must contain 40 agents, got {len(agents)}")
    if len({agent["id"] for agent in agents}) != len(agents):
        raise ValueError("Northstar corporation roster contains duplicate agent ids")
    return agents


def build_corporation_fixture(
    corporation_path: str | Path = DEFAULT_CORPORATION_CONFIG,
    output_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Create a Northstar fixture with one curated monitoring task per domain/variant."""
    corporation = load_corporation_config(corporation_path)
    corporation_path = Path(corporation_path)
    base_path = corporation_path.parent / str(corporation["company"]["base_config"])
    base = load_config(base_path)
    base_company = base["company"]
    derived = dict(base)
    derived["company"] = {
        **base_company,
        "id": corporation["company"]["id"],
        "name": corporation["company"]["name"],
        "description": corporation["company"]["description"],
        "seed": corporation["company"]["seed"],
    }
    derived["task_variants"] = list(corporation["monitor_variants"])
    derived["personas"] = [
        {
            "id": f"{domain['id']}-curator",
            "name": f"{domain['name']} Dashboard Curator",
            "technical_literacy": "medium",
            "domain": domain["id"],
            "role_goal": (
                f"Maintain a trusted monitoring definition for {domain['name']} and decide "
                "when its evidence deserves operational attention."
            ),
        }
        for domain in base["domains"]
    ]
    fixture = generate_fixture(
        derived,
        output_path=output_path,
        seed=int(corporation["company"]["seed"]),
        namespace="northstar-corporation",
    )
    roster = build_agent_roster(corporation, base)
    return corporation, fixture, roster


def _domain_id_for_task(task: dict[str, Any], base_company: dict[str, Any]) -> str:
    domain_name = str(task["brief"]["domain"])
    for domain in base_company["domains"]:
        if str(domain["name"]) == domain_name:
            return str(domain["id"])
    raise KeyError(f"unknown task domain: {domain_name}")


def assign_workflow(
    task: dict[str, Any],
    roster: list[dict[str, Any]],
    base_company: dict[str, Any],
    workflow_index: int,
) -> dict[str, Any]:
    domain_id = _domain_id_for_task(task, base_company)
    domain_curator = next(agent for agent in roster if agent["id"] == f"domain-curator-{domain_id}")
    domain_analyst = next(agent for agent in roster if agent["id"] == f"domain-analyst-{domain_id}")
    operations = [agent for agent in roster if agent["group"] == "enterprise_operations"]
    executives = [agent for agent in roster if agent["group"] == "executives"]
    communications = [agent for agent in roster if agent["group"] == "communications"]
    return {
        "workflow_id": f"northstar-{task['session_token']}",
        "domain_id": domain_id,
        "variant": task["variant"],
        "curator_id": domain_curator["id"],
        "analyst_id": domain_analyst["id"],
        "operations_id": operations[workflow_index % len(operations)]["id"],
        "executive_id": executives[workflow_index % len(executives)]["id"],
        "communications_id": communications[workflow_index % len(communications)]["id"],
    }


def baseline_action(task: dict[str, Any]) -> str:
    """Approximate the pre-SignalWeave operating state: alert on movement alone."""
    if task["variant"] in {"corroborated_notify", "explained_ignore", "contradictory_investigate"}:
        return Outcome.NOTIFY.value
    return Outcome.IGNORE.value


def _result_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = value.get("result", value)
    return result if isinstance(result, dict) else {}


def _task_score(
    task: dict[str, Any],
    result: dict[str, Any],
    *,
    workflow_complete: bool = True,
) -> dict[str, Any]:
    actual = str(result.get("outcome") or "")
    expected = str(task["expected_outcome"])
    exact = actual == expected
    provenance = bool(result.get("evidence")) and bool(result.get("source_keys"))
    automatic = actual in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
    unsafe = automatic and (not exact or not workflow_complete or not provenance)
    confidence = float(result.get("confidence") or 0.0)
    fully_automatable = exact and workflow_complete and provenance and actual in {
        Outcome.NOTIFY.value,
        Outcome.IGNORE.value,
        Outcome.ESCALATE.value,
    }
    return {
        "expected_outcome": expected,
        "actual_outcome": actual,
        "exact": exact,
        "confidence": confidence,
        "provenance_complete": provenance,
        "unsafe_automatic_action": unsafe,
        "fully_automatable": fully_automatable,
        "evidence_count": len(result.get("evidence") or []),
        "source_count": len(result.get("source_keys") or []),
    }


def _baseline_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    false_positive = sum(
        1
        for item in results
        if item["baseline_action"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
        and item["baseline_action"] != item["expected_outcome"]
    )
    missed = sum(
        1
        for item in results
        if item["expected_outcome"] in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
        and item["baseline_action"] not in {Outcome.NOTIFY.value, Outcome.ESCALATE.value}
    )
    return {
        "workflow_count": len(results),
        "exact_outcomes": sum(item["baseline_action"] == item["expected_outcome"] for item in results),
        "false_positive_automatic_alerts": false_positive,
        "missed_actionable_signals": missed,
        "human_review_required": len(results),
        "description": "Movement-only alerting without corroboration, freshness gates, or typed evidence receipts.",
    }


def _render_corporation_report(report: dict[str, Any]) -> str:
    lines = [
        "# Northstar Outfitters corporation trial",
        "",
        "Evaluation-only simulation of a 40-agent analytical organization using SignalWeave over a shared Northstar catalog.",
        "",
        f"- Evaluator: `{report['evaluator']}`",
        f"- Role agents: {report['role_agents']} across {json.dumps(report['role_groups'], sort_keys=True)}",
        f"- Workflows: {report['workflow_count']}",
        f"- SignalWeave exact outcomes: {report['signalweave']['exact_outcomes']}/{report['workflow_count']}",
        f"- SignalWeave unsafe automatic actions: {report['signalweave']['unsafe_automatic_actions']}",
        f"- SignalWeave fully automatable workflows: {report['signalweave']['fully_automatable']}/{report['workflow_count']}",
        f"- Simulated external deliveries: {report['signalweave']['simulated_deliveries']} (real delivery disabled)",
        f"- Trace integrity: {'valid' if report['trace_integrity']['valid'] else 'invalid'} across {report['trace_events']['total']} events",
        "",
        "## Before SignalWeave",
        "",
        f"Movement-only baseline: {report['baseline']['exact_outcomes']}/{report['workflow_count']} exact, "
        f"{report['baseline']['false_positive_automatic_alerts']} false automatic alerts, "
        f"{report['baseline']['missed_actionable_signals']} missed actionable signals.",
        "",
        "## SignalWeave result",
        "",
        "| Outcome | Count |",
        "| --- | ---: |",
    ]
    for outcome, count in sorted(report["signalweave"]["outcomes"].items()):
        lines.append(f"| {outcome} | {count} |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "The role graph is simulated. Cards and source references are generated from the editable corporation configuration; Jev only judges the bounded evidence supplied through the SignalWeave MCP path. No external delivery was contacted.",
            "",
            "This is evidence for a staged shadow-mode case study, not evidence that a company can safely automate all BI analysis without real domain-owner labels and time-split replay.",
        ]
    )
    return "\n".join(lines) + "\n"


async def run_trial(
    corporation_path: str | Path = DEFAULT_CORPORATION_CONFIG,
    *,
    evaluator: str = "jev",
    fixture_path: str | Path = "artifacts/northstar-corporation/fixture.json",
    store_path: str | Path = "artifacts/northstar-corporation/cards.json",
    trace_path: str | Path = "artifacts/northstar-corporation/trace.jsonl",
    run_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    corporation, fixture, roster = build_corporation_fixture(corporation_path, fixture_path)
    base = load_config(Path(corporation_path).parent / str(corporation["company"]["base_config"]))
    tasks = fixture["tasks"][:limit] if limit else fixture["tasks"]
    run_id = run_id or datetime.now(timezone.utc).strftime("northstar-corporation-%Y%m%dT%H%M%SZ")
    store = Path(store_path)
    trace_path = Path(trace_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    for path in (store, trace_path):
        if path.exists():
            path.unlink()

    trace = TraceSink(trace_path, experiment_id="northstar-corporation-trial", run_id=run_id)
    workflow_results: list[dict[str, Any]] = []
    evaluation_latencies: list[float] = []

    for workflow_index, task in enumerate(tasks):
        assignment = assign_workflow(task, roster, base, workflow_index)
        session_id = f"{run_id}-{task['session_token']}"
        actor = f"agent:{assignment['curator_id']}"
        trace.emit(
            "session.started",
            actor=actor,
            session_id=session_id,
            payload={
                "task_token": task["session_token"],
                "workflow_id": assignment["workflow_id"],
                "agent_chain": assignment,
                "evaluator": evaluator,
                "delivery": "disabled",
            },
        )
        for stage, agent_key in (
            ("curate", "curator_id"),
            ("review", "analyst_id"),
            ("cross_domain_context", "operations_id"),
        ):
            trace.emit(
                "role.stage.completed",
                actor=f"agent:{assignment[agent_key]}",
                session_id=session_id,
                payload={"stage": stage, "agent_id": assignment[agent_key]},
            )

        runtime = build_experiment_runtime(
            fixture,
            store_path=store,
            trace=trace,
            actor=actor,
            session_id=session_id,
            evaluator=evaluator,
        )
        server = create_mcp(runtime)
        brief = task["brief"]
        card_id = f"card-{task['session_token']}"
        await call_tool(
            server,
            trace,
            actor=actor,
            session_id=session_id,
            tool="draft_insight_card",
            arguments={
                "card_id": card_id,
                "title": brief["title"],
                "what_to_watch": brief["what_to_watch"],
                "why_watch": brief["why_watch"],
                "watch_for": brief["watch_for"],
                "questions": brief["questions"],
                "comparison_windows": brief["comparison_windows"],
                "sources": task["source_refs"],
                "delivery_methods": brief["delivery_context"],
                "owner": assignment["analyst_id"],
                "max_source_age_hours": 24.0,
            },
        )
        preview = await call_tool(
            server,
            trace,
            actor=f"agent:{assignment['analyst_id']}",
            session_id=session_id,
            tool="simulate_insight_card",
            arguments={"card_id": card_id},
        )
        await call_tool(
            server,
            trace,
            actor=f"agent:{assignment['analyst_id']}",
            session_id=session_id,
            tool="approve_insight_card",
            arguments={"card_id": card_id, "actor": assignment["analyst_id"]},
        )
        started = datetime.now(timezone.utc)
        evaluated = await call_tool(
            server,
            trace,
            actor=f"agent:{assignment['operations_id']}",
            session_id=session_id,
            tool="evaluate_insight_card",
            arguments={
                "card_id": card_id,
                "idempotency_key": f"{run_id}:{card_id}",
                "actor": assignment["operations_id"],
            },
        )
        evaluation_latencies.append((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        result = _result_payload(evaluated)
        preview_result = _result_payload(preview).get("result", {})
        scored = _task_score(task, result)
        baseline = baseline_action(task)
        route = result.get("outcome")
        if route in {Outcome.NOTIFY.value, Outcome.ESCALATE.value, Outcome.INVESTIGATE.value}:
            recipient = assignment["executive_id"] if route == Outcome.NOTIFY.value else assignment["operations_id"]
            trace.emit(
                "handoff.simulated",
                actor=f"agent:{assignment['communications_id']}",
                session_id=session_id,
                payload={"outcome": route, "recipient": recipient, "evidence_count": scored["evidence_count"]},
            )
            trace.emit(
                "handoff.acknowledged",
                actor=f"agent:{recipient}",
                session_id=session_id,
                payload={"outcome": route, "receipt": "simulated-only"},
            )
        workflow_results.append(
            {
                **assignment,
                "task_id": task["id"],
                "baseline_action": baseline,
                "expected_outcome": task["expected_outcome"],
                "preview_outcome": preview_result.get("outcome"),
                "signalweave": scored,
            }
        )

    outcomes = Counter(item["signalweave"]["actual_outcome"] for item in workflow_results)
    group_counts = Counter(agent["group"] for agent in roster)
    trace_events = [
        json.loads(line)
        for line in trace_path.read_text().splitlines()
        if line.strip()
    ]
    trace_event_counts = Counter(event["event_type"] for event in trace_events)
    report = {
        "trial": "northstar-corporation-signalweave",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "evaluator": evaluator,
        "company": corporation["company"],
        "role_agents": len(roster),
        "role_groups": dict(group_counts),
        "workflow_count": len(workflow_results),
        "fixture_stats": fixture["stats"],
        "baseline": _baseline_summary(workflow_results),
        "signalweave": {
            "exact_outcomes": sum(item["signalweave"]["exact"] for item in workflow_results),
            "provenance_complete": sum(item["signalweave"]["provenance_complete"] for item in workflow_results),
            "unsafe_automatic_actions": sum(item["signalweave"]["unsafe_automatic_action"] for item in workflow_results),
            "fully_automatable": sum(item["signalweave"]["fully_automatable"] for item in workflow_results),
            "human_review_required": sum(
                item["signalweave"]["actual_outcome"] == Outcome.INVESTIGATE.value
                for item in workflow_results
            ),
            "simulated_deliveries": sum(
                item["signalweave"]["actual_outcome"]
                in {Outcome.NOTIFY.value, Outcome.ESCALATE.value, Outcome.INVESTIGATE.value}
                for item in workflow_results
            ),
            "outcomes": dict(outcomes),
            "evaluation_latency_ms": {
                "median": round(statistics.median(evaluation_latencies), 2) if evaluation_latencies else None,
                "p95": round(sorted(evaluation_latencies)[max(0, int(len(evaluation_latencies) * 0.95) - 1)], 2)
                if evaluation_latencies
                else None,
            },
        },
        "trace_integrity": audit_trace(trace_path),
        "trace_events": {
            "total": len(trace_events),
            "by_type": dict(trace_event_counts),
        },
        "workflow_results": workflow_results,
        "artifacts": {"fixture": str(fixture_path), "trace": str(trace_path)},
        "limitations": [
            "Role agents and acknowledgements are simulated participants; only the SignalWeave MCP path is executed.",
            "Cards are pre-curated from the editable corporation configuration; onboarding quality is a separate experiment.",
            "The Northstar catalog and expected labels are local synthetic/counterfactual evidence, not customer production labels.",
            "Delivery remains disabled; simulated handoffs do not prove Slack, email, or incident-system reliability.",
        ],
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Northstar Outfitters corporation trial")
    parser.add_argument("--config", default=str(DEFAULT_CORPORATION_CONFIG))
    parser.add_argument("--evaluator", choices=["jev", "research"], default="jev")
    parser.add_argument("--fixture", default="artifacts/northstar-corporation/fixture.json")
    parser.add_argument("--store", default="artifacts/northstar-corporation/cards.json")
    parser.add_argument("--trace", default="artifacts/northstar-corporation/trace.jsonl")
    parser.add_argument("--report", default="artifacts/northstar-corporation/report.json")
    parser.add_argument("--markdown", default="artifacts/northstar-corporation/report.md")
    parser.add_argument("--limit", type=int)
    return parser


async def _main(args: argparse.Namespace) -> None:
    report = await run_trial(
        args.config,
        evaluator=args.evaluator,
        fixture_path=args.fixture,
        store_path=args.store,
        trace_path=args.trace,
        limit=args.limit,
    )
    report_path = Path(args.report)
    markdown_path = Path(args.markdown)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(_render_corporation_report(report))
    print(json.dumps({key: value for key, value in report.items() if key != "workflow_results"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))

import json
from pathlib import Path

import pytest

from evaluations.enterprise_trial import (
    TraceSink,
    audit_trace,
    build_experiment_runtime,
    generate_fixture,
    score_trace,
)
from signalweave.mcp_server import create_mcp


def test_enterprise_fixture_generates_large_heterogeneous_catalog(tmp_path):
    output = tmp_path / "northstar.json"
    fixture = generate_fixture(output_path=output, seed=17)

    assert fixture["stats"]["base_dashboards"] == 144
    assert fixture["stats"]["charts"] >= 600
    assert fixture["stats"]["tasks"] == 60
    assert set(fixture["stats"]["adapters"]) >= {
        "superset",
        "sql",
        "airflow",
        "table",
    }
    assert output.exists()


def test_scenario_metadata_does_not_leak_hidden_case_labels(tmp_path):
    fixture = generate_fixture(output_path=tmp_path / "northstar.json", seed=19)
    hidden_labels = {
        task["id"]
        for task in fixture["tasks"]
    } | {
        "corroborated_notify",
        "explained_ignore",
        "contradictory_investigate",
        "stale_escalation",
        "missing_baseline",
        "source_failure",
    }
    scenario_records = [
        record
        for record in fixture["resources"]
        if "scenario-" in record["descriptor"]["resource"]
    ]
    public_text = json.dumps(scenario_records, sort_keys=True)
    assert not any(label in public_text for label in hidden_labels)
    assert "task-" not in public_text


def test_enterprise_portfolio_is_namespaced_and_cross_tenant_safe(tmp_path):
    config = Path(__file__).parents[1] / "evaluations" / "data" / "enterprise-portfolio.json"
    fixture = generate_fixture(config, output_path=tmp_path / "portfolio.json", seed=41)

    assert fixture["schema_version"] == 2
    assert fixture["stats"]["enterprises"] == 3
    assert fixture["stats"]["base_dashboards"] >= 300
    assert fixture["stats"]["tasks"] >= 140
    assert len({task["session_token"] for task in fixture["tasks"]}) == fixture["stats"]["tasks"]
    assert len(
        {(item["descriptor"]["adapter"], item["descriptor"]["resource"])
         for item in fixture["resources"]}
    ) == fixture["stats"]["resources"]
    assert {company["experiment_namespace"] for company in fixture["portfolio"]["companies"]} == {
        "northstar",
        "harbor",
        "orbit",
    }


def test_trace_is_hash_chained_and_fsync_backed(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceSink(trace_path, experiment_id="test-enterprise", run_id="run-integrity")
    trace.emit("session.started", actor="persona:test", session_id="session-1", payload={})
    trace.emit("mcp.call.started", actor="persona:test", session_id="session-1", payload={"tool": "list_resources"})
    trace.emit("mcp.call.completed", actor="persona:test", session_id="session-1", payload={"tool": "list_resources"})

    audit = audit_trace(trace_path)
    assert audit["valid"] is True
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert all(event["event_hash"] for event in events)


def test_trace_cache_preserves_chain_across_session_sinks(tmp_path):
    trace_path = tmp_path / "multi-session-trace.jsonl"
    for index in range(3):
        trace = TraceSink(trace_path, experiment_id="test-enterprise", run_id=f"run-{index}")
        trace.emit(
            "session.started",
            actor=f"persona:{index}",
            session_id=f"session-{index}",
            payload={"index": index},
        )

    audit = audit_trace(trace_path)
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert audit["valid"] is True
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert events[1]["previous_event_hash"] == events[0]["event_hash"]
    assert events[2]["previous_event_hash"] == events[1]["event_hash"]


@pytest.mark.asyncio
async def test_enterprise_fixture_is_reachable_through_mcp_and_trace(tmp_path):
    fixture = generate_fixture(output_path=tmp_path / "northstar.json", seed=23)
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceSink(
        trace_path,
        experiment_id="test-enterprise",
        run_id="run-1",
    )
    runtime = build_experiment_runtime(
        fixture,
        store_path=tmp_path / "cards.json",
        trace=trace,
        actor="persona:test",
        session_id="session-1",
        evaluator="research",
    )
    server = create_mcp(runtime)

    _, resources_payload = await server.call_tool("list_resources", {"adapter": "superset"})
    resources = resources_payload["result"]
    assert len(resources) >= fixture["stats"]["base_dashboards"]
    assert all("title" in resource and "metadata" in resource for resource in resources)

    task = next(item for item in fixture["tasks"] if item["variant"] == "stale_escalation")
    _, draft_payload = await server.call_tool(
        "draft_insight_card",
        {
            "card_id": "card-test-stale",
            "title": task["brief"]["title"],
            "what_to_watch": task["brief"]["what_to_watch"],
            "why_watch": task["brief"]["why_watch"],
            "watch_for": task["brief"]["watch_for"],
            "questions": task["brief"]["questions"],
            "sources": task["source_refs"],
            "delivery_methods": task["brief"]["delivery_context"],
        },
    )
    draft_result = draft_payload.get("result", draft_payload)
    assert draft_result["status"] == "draft"

    _, simulation_payload = await server.call_tool(
        "simulate_insight_card", {"card_id": "card-test-stale"}
    )
    simulation_result = simulation_payload.get("result", simulation_payload)
    assert simulation_result["outcome"] == "escalate"
    assert simulation_result["evidence"]


def test_enterprise_trace_scoring_keeps_hidden_labels_out_of_persona_surface(tmp_path):
    fixture = generate_fixture(output_path=tmp_path / "northstar.json", seed=29)
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceSink(trace_path, experiment_id="test-enterprise", run_id="run-2")
    trace.emit(
        "session.started",
        actor="persona:test",
        session_id="session-2",
        payload={"task_id": "task-cfo-corroborated_notify", "access": "signal-weave-mcp-only"},
    )
    trace.emit(
        "mcp.call.completed",
        actor="persona:test",
        session_id="session-2",
        payload={
            "tool": "evaluate_insight_card",
            "result": {
                "result": {
                    "outcome": "notify",
                    "delivery_methods": [{"key": "sales-notify"}],
                    "source_keys": ["primary", "context"],
                    "evidence": [{"source_key": "primary", "statement": "evidence"}],
                }
            },
        },
    )
    report = score_trace(fixture, trace_path)
    assert report["session_count"] == 1
    assert report["exact_decisions"] == 0
    assert report["workflow_complete"] == 0
    assert report["trace_integrity"]["protocol_valid"] is False
    serialized_trace = trace_path.read_text()
    assert '"expected_outcome"' not in serialized_trace
    assert json.loads(serialized_trace.splitlines()[0])["payload"]["access"] == "signal-weave-mcp-only"


def test_enterprise_trace_scoring_accepts_proposal_protocol(tmp_path):
    fixture = generate_fixture(output_path=tmp_path / "northstar.json", seed=31)
    task = fixture["tasks"][0]
    trace_path = tmp_path / "proposal-trace.jsonl"
    trace = TraceSink(trace_path, experiment_id="test-enterprise", run_id="run-proposal")
    session_id = "proposal-session"
    actor = "persona:test"
    trace.emit(
        "session.started",
        actor=actor,
        session_id=session_id,
        payload={"task_token": task["session_token"], "access": "signal-weave-mcp-only"},
    )
    source = task["source_refs"][0]
    trace.emit(
        "source.inspect.completed",
        actor=actor,
        session_id=session_id,
        payload={"source_key": source["key"]},
    )

    def complete(tool, result):
        trace.emit(
            "mcp.call.started",
            actor=actor,
            session_id=session_id,
            payload={"tool": tool, "arguments": {}},
        )
        trace.emit(
            "mcp.call.completed",
            actor=actor,
            session_id=session_id,
            payload={"tool": tool, "result": result},
        )

    card = {
        "what_to_watch": "A material movement.",
        "why_watch": "Support an operating decision.",
        "watch_for": ["The movement is comparable."],
        "questions": ["Is action warranted?"],
        "sources": [source],
    }
    complete("propose_insight_card", {"proposal": {"card": card}})
    complete("simulate_insight_card", {"outcome": "investigate"})
    complete("approve_insight_card", {"status": "approved"})
    complete(
        "evaluate_insight_card",
        {
            "result": {
                "outcome": "investigate",
                "delivery_methods": [],
                "source_keys": [source["key"]],
                "evidence": [{"source_key": source["key"], "statement": "evidence"}],
            }
        },
    )

    report = score_trace(fixture, trace_path)
    session = report["sessions"][0]
    assert report["trace_integrity"]["valid"] is True
    assert session["workflow_complete"] is True
    assert session["card_complete"] is True

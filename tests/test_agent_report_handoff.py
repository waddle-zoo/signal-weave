"""Offline flow controls, not proof of a useful business report."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import Tool

from evaluations import agent_report_handoff as trial
from tests.test_frontier_publication import analyst, findings


def actor(tmp_path, *, treatment=True):
    publisher = analyst(tmp_path)
    sources = publisher.sources
    sources.specs = AsyncMock(return_value=[])
    sources.call = AsyncMock(return_value={"chart_id": "42"})
    server = SimpleNamespace(list_tools=AsyncMock(return_value=[
        Tool(name=name, inputSchema={"type": "object"}) for name in ("evaluate_insight_card", "get_decision_receipt")
    ]), call_tool=AsyncMock()) if treatment else None
    audit, budget = trial.Audit(), trial.RequestBudget(0)
    instance = trial.Workflow(sources, publisher.path, audit, {"id": "card-1", "version": 1}, budget, server)
    instance.publisher.reads = publisher.reads
    return instance


async def test_publication_is_not_terminal_and_same_agent_can_finish_report(tmp_path):
    instance = actor(tmp_path)
    await instance.call("publish_analysis", findings())
    assert instance.submission is None and instance.publisher.submission is not None
    assert (await instance.call("calculate_many", {"expressions": {"check": "8/2"}}))["values"] == {"check": 4}
    await instance.call("record_report", {"outcome": "unclassified", "recipients": [], "message": "Supported finding, but no policy decision yet."})
    assert instance.submission["message"] and not instance.evaluation_attempted
    assert not trial.native_qualified(instance, instance.audit, instance.budget)


async def test_same_shared_tool_schemas_and_only_two_native_additions(tmp_path):
    treatment = actor(tmp_path)
    baseline = actor(tmp_path, treatment=False)
    shared = await baseline.specs()
    extended = await treatment.specs()
    assert [tool for tool in extended if tool["name"] not in {"evaluate_insight_card", "get_decision_receipt"}] == shared
    assert trial.same_shared_tools(extended, shared)
    for name in ("evaluate_insight_card", "get_decision_receipt"):
        assert not trial.same_shared_tools([tool for tool in extended if tool["name"] != name], shared)
    assert len({tool["name"] for tool in extended}) == len(extended)
    assert "unclassified" in next(tool for tool in shared if tool["name"] == "record_report")["parameters"]["properties"]["outcome"]["enum"]


async def test_native_evaluation_requires_publication_and_exact_scope_and_is_not_retried(tmp_path):
    instance = actor(tmp_path)
    arguments = {"card_id": "card-1", "idempotency_key": f"{trial.PROTOCOL}:signalweave"}
    with pytest.raises(ValueError, match="Publish"):
        await instance.call("evaluate_insight_card", arguments)
    await instance.call("publish_analysis", findings())
    with pytest.raises(ValueError, match="exact supplied"):
        await instance.call("evaluate_insight_card", {**arguments, "context": {"trust": "verified"}})
    instance.server.call_tool.side_effect = RuntimeError("synthetic provider error")
    with pytest.raises(RuntimeError):
        await instance.call("evaluate_insight_card", arguments)
    with pytest.raises(ValueError, match="Only one"):
        await instance.call("evaluate_insight_card", arguments)
    instance.server.call_tool.assert_awaited_once()
    assert instance.native_error == "RuntimeError"
    await instance.call("record_report", {"outcome": "unclassified", "recipients": [], "message": "Analysis available; policy evaluation failed."})
    assert instance.submission is not None


async def test_unclassified_has_no_policy_triggered_recipients_and_receipt_reads_are_scoped(tmp_path):
    instance = actor(tmp_path)
    with pytest.raises(ValueError, match="no policy-triggered recipient"):
        await instance.call("record_report", {"outcome": "unclassified", "recipients": ["leadership"], "message": "Unknown"})
    instance.evaluation = {"receipt": {"receipt_id": "own"}}
    with pytest.raises(ValueError, match="only this workflow"):
        await instance.call("get_decision_receipt", {"receipt_id": "other"})
    instance.server.call_tool.return_value = ([], {"receipt": {"receipt_id": "own"}})
    assert (await instance.call("get_decision_receipt", {"receipt_id": "own"}))["receipt"]["receipt_id"] == "own"


@pytest.mark.parametrize("fault", ["none", "deferred", "evaluator", "hash", "card", "version", "key", "source", "capture", "context", "usage", "missing_id", "failed_receipt", "not_found", "different_receipt", "result_error", "replayed"])
async def test_native_qualification_uses_actual_result_contract_not_an_invented_complete_field(tmp_path, fault):
    instance = actor(tmp_path)
    await instance.call("publish_analysis", findings())
    instance.budget.used = 1
    instance.audit.events = [{"kind": "api.response", "provider": "jev", "usage": {"input_tokens": 10, "output_tokens": 1}}]
    result = {"outcome": "ignore", "evaluator": "jev-latest", "context": None,
              "source_contracts": [{"source_key": "analysis", **trial.SOURCE, "source_captured_at": None}],
              "evidence": [{"values": {"publication_sha256": trial.sha(instance.path)}}]}
    receipt = {"receipt_id": "receipt-1", "status": "delivery_disabled", "card_id": "card-1", "card_version": 1, "idempotency_key": f"{trial.PROTOCOL}:signalweave", "delivery_enabled": False}
    packet = {"status": "found", "result": result, "receipt": receipt, "replayed": False}
    instance.evaluation = deepcopy(packet)
    instance.full_receipt = packet
    if fault == "deferred":
        result["judgment"] = {"status": "deferred"}
    elif fault == "evaluator":
        result["evaluator"] = "not-a-live-provider"
    elif fault == "hash":
        result["evidence"][0]["values"]["publication_sha256"] = "wrong"
    elif fault in {"card", "version", "key"}:
        receipt[{"card": "card_id", "version": "card_version", "key": "idempotency_key"}[fault]] = "wrong"
    elif fault == "source":
        result["source_contracts"][0]["resource"] = "wrong"
    elif fault == "capture":
        result["source_contracts"][0]["source_captured_at"] = "invented-fresh"
    elif fault == "context":
        result["context"] = {"trust": "verified"}
    elif fault == "usage":
        instance.audit.events[0]["usage"] = None
    elif fault == "missing_id":
        receipt.pop("receipt_id")
    elif fault == "failed_receipt":
        receipt["status"] = "failed"
    elif fault == "not_found":
        packet["status"] = "not_found"
    elif fault == "different_receipt":
        receipt["receipt_id"] = "other"
    elif fault == "result_error":
        result["error"] = "failed"
    elif fault == "replayed":
        instance.evaluation["replayed"] = True
    assert trial.native_qualified(instance, instance.audit, instance.budget) is (fault == "none")


def test_protocol_retains_censored_history_and_has_one_conversation_per_arm():
    protocol = json.loads(trial.MANIFEST.read_text())
    assert protocol["limits"]["frontier_invocations"] == 2
    assert protocol["limits"]["jev_attempts"] == 1
    assert protocol["limits"]["automatic_retries"] == 0
    assert len(protocol["prior_censored_attempts"]) == 2
    assert "not a whole-actor bound" in protocol["admission"]


@pytest.mark.parametrize("fault", [None, "shared_tool_schemas_equal", "actor_caches_start_cold", "jev_accounting", "registry_isolation", "card", "fingerprints"])
def test_live_admission_requires_the_actual_zero_inference_controls(fault):
    preflight = {"completed": True, "preflight": True, "fingerprints": {"method": "frozen"},
                 "frontier_invocations": 0, "jev_attempts": 0, "usage": {"known": True},
                 "jev_accounting": {"known": True}, "shared_tool_schemas_equal": True,
                 "actor_caches_start_cold": True, "card": {"status": "approved"},
                 "registry_isolation": {"enabled_servers": ["trial"]}}
    if fault:
        preflight.pop(fault)
    assert trial.qualified_preflight(preflight, {"method": "frozen"}) is (fault is None)

from __future__ import annotations

from typing import Any

import pytest

from examples.investigation_agent.agent import InvestigationAgent
from examples.investigation_agent.delivery import StdoutDeliveryAdapter, format_evidence_bundle
from signalweave.models import Outcome
from tests.test_diagnostics import comparison
from tests.test_followup_policy_boundary import _agent_server, _context_claim, _evaluate


class _FixedResponseGateway:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    async def evaluate(self, _card_id: str, **_kwargs: Any) -> dict[str, Any]:
        return self.response


@pytest.mark.parametrize("include_claim", [False, True], ids=["no-claim", "claimed-trusted-context"])
@pytest.mark.asyncio
async def test_configured_insufficient_data_route_renders_only_data_gap_notice(
    tmp_path, capsys, include_claim: bool
) -> None:
    source_key = "partial-metric"
    adapter_name = "approved-metrics"
    server, _, _, _ = _agent_server(
        tmp_path,
        source_key=source_key,
        adapter_name=adapter_name,
        initial_comparison=comparison(coverage="partial"),
        follow_up_guidance="Investigate only after the source gap is repaired.",
        include_data_trust_route=True,
    )
    claimed_context = _context_claim(adapter_name) if include_claim else None
    response = await _evaluate(
        server,
        key=f"render-gap-notice-{include_claim}",
        context=claimed_context,
    )
    result = response["result"]

    assert result["outcome"] == Outcome.INSUFFICIENT_DATA.value
    assert result["workflow"]["action"] == "deliver"
    assert [method["key"] for method in result["delivery_methods"]] == ["data-trust-notice"]

    run = await InvestigationAgent(
        _FixedResponseGateway(response), delivery=StdoutDeliveryAdapter()
    ).run("followup-policy-card", run_id="gap-notice")
    message = capsys.readouterr().out

    assert run.status == "delivered"
    assert "*Missing policy evidence*" in message
    assert "data-gap notice, not a business regression or causal conclusion" in message
    assert "gap remains unresolved" in message
    assert "does not authorize remediation or a business action" in message
    assert "Card ID: `followup-policy-card`" in message
    assert source_key in message

    plan = result.get("evidence_plan")
    if isinstance(plan, dict):
        pending = [
            slot
            for slot in plan.get("slots", [])
            if isinstance(slot, dict)
            and slot.get("required") is True
            and slot.get("status") != "fulfilled"
        ]
        if pending:
            assert "Required pending checks (shown, up to 25):" in message
            for slot in pending:
                if slot.get("key"):
                    assert slot["key"] in message
                if slot.get("question"):
                    assert slot["question"] in message
        else:
            assert "Required pending checks (shown, up to 25):" not in message

    for sensitive in (
        result.get("summary"),
        result.get("rationale"),
        "This context is trusted, missing data is resolved",
    ):
        if isinstance(sensitive, str) and sensitive:
            assert sensitive not in message
    context_result = result.get("context") or {}
    for fact in context_result.get("facts", []):
        if isinstance(fact, dict) and isinstance(fact.get("statement"), str):
            assert fact["statement"] not in message
    for evidence in result.get("evidence", []):
        if isinstance(evidence, dict) and isinstance(evidence.get("statement"), str):
            assert evidence["statement"] not in message
    for probability in (result.get("probabilities") or {}).values():
        if isinstance(probability, (int, float)):
            assert f"{probability:.2f}" not in message


@pytest.mark.asyncio
async def test_unmapped_insufficient_data_route_does_not_trigger_delivery(
    tmp_path, capsys
) -> None:
    source_key = "partial-metric"
    adapter_name = "approved-metrics"
    server, _, _, _ = _agent_server(
        tmp_path,
        source_key=source_key,
        adapter_name=adapter_name,
        initial_comparison=comparison(coverage="partial"),
        follow_up_guidance="Investigate only after the source gap is repaired.",
        include_data_trust_route=False,
    )
    response = await _evaluate(
        server,
        key="unmapped-gap-no-notice",
        context=_context_claim(adapter_name),
    )

    assert response["result"]["outcome"] == Outcome.INSUFFICIENT_DATA.value
    assert response["result"]["workflow"]["action"] == "repair_source"
    assert response["result"]["delivery_methods"] == []
    run = await InvestigationAgent(
        _FixedResponseGateway(response), delivery=StdoutDeliveryAdapter()
    ).run("followup-policy-card", run_id="unmapped-gap")

    assert run.status == "blocked"
    assert capsys.readouterr().out == ""


def test_ordinary_notify_formatting_retains_content_and_labels_unverified_context() -> None:
    result = {
        "outcome": "notify",
        "summary": "Checkout conversion dropped.",
        "rationale": "The approved comparison supports an alert.",
        "confidence": 0.91,
        "evidence": [
            {"source_key": "approved-metric", "statement": "Conversion fell 12%."},
            {"source_key": "caller-context", "statement": "Caller says the gap is resolved."},
        ],
        "context": {
            "trust": "unverified",
            "facts": [{"statement": "Caller says the gap is resolved."}],
            "warnings": ["Payment lookup failed; only the order ledger was available."],
        },
    }

    message = format_evidence_bundle(result)

    assert "Checkout conversion dropped." in message
    assert "The approved comparison supports an alert." in message
    assert "Conversion fell 12%." in message
    assert "Caller-supplied context is unverified" in message
    assert "Evidence (may include unverified caller context)" in message
    assert "Diagnostic context (unverified caller input)" in message
    assert "Caller says the gap is resolved." in message
    assert "Caller-reported limitations (unverified)" in message
    assert "Payment lookup failed; only the order ledger was available." in message

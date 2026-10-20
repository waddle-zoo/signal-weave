from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from examples.investigation_agent.agent import InvestigationAgent
from examples.investigation_agent.mcp_gateway import McpSignalWeaveGateway
from signalweave.mcp_server import _compact_evaluation_response
from signalweave.models import ContextFact, ContextSnapshot, Outcome
from tests.test_onboarding import OnboardingJevDouble, make_server, tool


@pytest.mark.asyncio
async def test_gateway_requests_full_response_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeTimeout:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class FakeSession:
        def __init__(self, *_streams: Any) -> None:
            pass

        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def initialize(self) -> None:
            return None

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            calls.append({"name": name, "arguments": arguments})
            return SimpleNamespace(isError=False, structuredContent={"result": {}})

    @asynccontextmanager
    async def fake_http_client(**_kwargs: Any):
        yield object()

    @asynccontextmanager
    async def fake_streamable_http_client(*_args: Any, **_kwargs: Any):
        yield (object(), object())

    httpx2 = ModuleType("httpx2")
    httpx2.Timeout = FakeTimeout  # type: ignore[attr-defined]
    mcp = ModuleType("mcp")
    mcp.__path__ = []  # type: ignore[attr-defined]
    mcp.ClientSession = FakeSession  # type: ignore[attr-defined]
    mcp_client = ModuleType("mcp.client")
    mcp_client.__path__ = []  # type: ignore[attr-defined]
    mcp_streamable = ModuleType("mcp.client.streamable_http")
    mcp_streamable.streamable_http_client = fake_streamable_http_client  # type: ignore[attr-defined]
    mcp_shared = ModuleType("mcp.shared")
    mcp_shared.__path__ = []  # type: ignore[attr-defined]
    mcp_httpx_utils = ModuleType("mcp.shared._httpx_utils")
    mcp_httpx_utils.create_mcp_http_client = fake_http_client  # type: ignore[attr-defined]
    for name, module in (
        ("httpx2", httpx2),
        ("mcp", mcp),
        ("mcp.client", mcp_client),
        ("mcp.client.streamable_http", mcp_streamable),
        ("mcp.shared", mcp_shared),
        ("mcp.shared._httpx_utils", mcp_httpx_utils),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    response = await McpSignalWeaveGateway("https://signalweave.example/mcp").evaluate(
        "card-1", idempotency_key="run-1:evaluate:1"
    )

    assert response == {"result": {}}
    assert calls[0]["name"] == "evaluate_insight_card"
    assert calls[0]["arguments"]["response_mode"] == "full"


class InvestigateJevDouble(OnboardingJevDouble):
    async def judge(self, state, card, plan, observations):
        result = await super().judge(state, card, plan, observations)
        return result.model_copy(
            update={
                "outcome": Outcome.INVESTIGATE,
                "summary": "The observed movement needs diagnostic context.",
                "rationale": "Follow the card's configured investigation handoff.",
                "probabilities": {Outcome.INVESTIGATE.value: 0.91},
            }
        )


@pytest.mark.asyncio
async def test_compacted_actual_engine_result_resolves_canonical_evidence_plan(tmp_path) -> None:
    server = make_server(tmp_path, InvestigateJevDouble())
    drafted = await tool(server, "draft_insight_card")(
        title="Checkout investigation",
        what_to_watch="Checkout conversion and changes that explain a material movement.",
        why_watch="Help Growth investigate a customer-impacting regression.",
        watch_for=["Checkout conversion falls materially"],
        questions=["What changed and what explains the conversion movement?"],
        decision_guidance="Investigate material movement when evidence needs context.",
        follow_up_guidance="Inspect the approved source and return diagnostic evidence.",
        sources=[
            {
                "key": "growth",
                "adapter": "superset",
                "resource": "dashboard:7",
                "label": "Growth overview",
            }
        ],
    )
    card_id = drafted["card"]["id"]
    for _ in range(3):
        await tool(server, "review_insight_card")(card_id)
    await tool(server, "simulate_insight_card")(card_id)
    await tool(server, "approve_insight_card")(card_id)

    full = await tool(server, "evaluate_insight_card")(
        card_id, idempotency_key="actual-engine-compact-plan", response_mode="full"
    )
    assert full["result"]["workflow"]["action"] == "retrieve_evidence"
    assert full["result"]["evidence_plan"]["slots"]
    compact = _compact_evaluation_response(full)
    assert compact["result"]["workflow"]["evidence_plan_ref"] == {
        "result_path": ["evidence_plan"]
    }

    class RecordingCollector:
        def __init__(self) -> None:
            self.requests = []

        async def collect(self, request):
            self.requests.append(request)
            return ContextSnapshot(
                provider="test-investigation-agent",
                version="context-1",
                facts=[
                    ContextFact(
                        fact_id="diagnostic",
                        subject_ref="superset|dashboard:7",
                        relation="explains",
                        statement="A diagnostic context fact was returned.",
                        provenance=["test-source"],
                    )
                ],
            )

    class CompactThenTerminalGateway:
        def __init__(self) -> None:
            self.responses = [
                compact,
                {
                    "receipt": {"receipt_id": "terminal-receipt"},
                    "result": {
                        "outcome": "notify",
                        "workflow": {
                            "action": "deliver",
                            "status": "ready",
                            "step_key": "deliver",
                        },
                    },
                },
            ]
            self.calls = []

        async def evaluate(self, _card_id: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return self.responses.pop(0)

    class RecordingDelivery:
        async def deliver(self, result, *, card_id, run_id):
            return [{"status": "delivered", "outcome": result["outcome"]}]

    collector = RecordingCollector()
    gateway = CompactThenTerminalGateway()
    run = await InvestigationAgent(
        gateway, collector=collector, delivery=RecordingDelivery(), max_steps=2
    ).run(card_id, run_id="compact-engine-integration")

    assert run.status == "delivered"
    assert collector.requests[0].evidence_slots == tuple(full["result"]["evidence_plan"]["slots"])
    assert gateway.calls[1]["parent_receipt_id"] == full["receipt"]["receipt_id"]
    assert gateway.calls[1]["context"].version == "context-1"

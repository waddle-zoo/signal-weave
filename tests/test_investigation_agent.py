from __future__ import annotations

from typing import Any

import pytest

from examples.investigation_agent.agent import (
    CatalogContextCollector,
    InvestigationAgent,
    InvestigationTool,
    RequiredSourcePlanner,
    parse_tool_selection,
)
from examples.investigation_agent.context_tools import load_json_tools
from examples.investigation_agent.delivery import (
    SlackDeliveryAdapter,
    SlackRoute,
    format_evidence_bundle,
)
from signalweave.models import ContextFact, ContextSnapshot


class FakeSignalWeave:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def evaluate(self, card_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"card_id": card_id, **kwargs})
        if len(self.calls) == 1:
            return {
                "receipt": {"receipt_id": "receipt-initial"},
                "result": {
                    "outcome": "investigate",
                    "summary": "Sales movement needs diagnostic context.",
                    "workflow": {
                        "status": "pending",
                        "step_key": "investigate",
                        "action": "retrieve_evidence",
                        "objective": "Explain material sales movement.",
                        "instructions": "Inspect authorized acquisition and funnel sources.",
                        "required_source_keys": ["campaign-performance", "purchase-funnel"],
                    },
                },
            }
        assert kwargs["parent_receipt_id"] == "receipt-initial"
        assert kwargs["workflow_step_key"] == "investigate"
        assert isinstance(kwargs["context"], ContextSnapshot)
        return {
            "receipt": {"receipt_id": "receipt-final"},
            "result": {
                "outcome": "notify",
                "summary": "Online sales fell after a campaign conversion regression.",
                "rationale": "The campaign funnel evidence supports the alert.",
                "confidence": 0.91,
                "delivery_methods": [
                    {"key": "leadership", "destination": "slack://sales-health"},
                    {"key": "marketing", "destination": "slack://sales-health"},
                    {"key": "sales", "destination": "slack://sales-health"},
                ],
                "evidence": [
                    {
                        "source_key": "purchase-funnel",
                        "statement": "Click-to-purchase conversion declined 61%.",
                    }
                ],
                "workflow": {
                    "status": "ready",
                    "step_key": "deliver",
                    "action": "deliver",
                    "objective": "Explain material sales movement.",
                },
            },
        }


class RecordingCollector:
    def __init__(self) -> None:
        self.requests = []

    async def collect(self, request):
        self.requests.append(request)
        return ContextSnapshot(
            provider="test-agent",
            version="test-context-1",
            facts=[
                ContextFact(
                    fact_id="campaign-funnel",
                    subject_ref="ads|campaign:latest",
                    relation="supports_driver",
                    object_ref="business|online-sales",
                    statement="Purchase conversion collapsed for the latest campaign.",
                    provenance=["test-source"],
                )
            ],
        )


class RecordingDelivery:
    def __init__(self) -> None:
        self.results = []

    async def deliver(self, result, *, card_id, run_id):
        self.results.append((result, card_id, run_id))
        return [{"status": "delivered", "destination": "test"}]


@pytest.mark.asyncio
async def test_agent_can_follow_multiple_diagnostic_handoffs() -> None:
    class RepeatedGateway:
        def __init__(self) -> None:
            self.calls = []

        async def evaluate(self, _card_id: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            index = len(self.calls)
            if index < 3:
                return {
                    "receipt": {"receipt_id": f"receipt-{index}"},
                    "result": {
                        "outcome": "investigate",
                        "workflow": {
                            "action": "retrieve_evidence",
                            "status": "pending",
                            "step_key": f"diagnostic-{index}",
                            "objective": "Explain the movement.",
                            "instructions": "Retrieve the next authorized diagnostic source.",
                            "required_source_keys": [f"source-{index}"],
                        },
                    },
                }
            return {
                "receipt": {"receipt_id": "receipt-final"},
                "result": {
                    "outcome": "notify",
                    "workflow": {"action": "deliver", "status": "ready", "step_key": "deliver"},
                    "summary": "The staged evidence supports notification.",
                    "delivery_methods": [{"key": "leadership"}],
                },
            }

    class FactsCollector:
        async def collect(self, request):
            return ContextSnapshot(
                provider="test-agent",
                version=f"context-{request.step_number}",
                facts=[
                    ContextFact(
                        fact_id=f"fact-{request.step_number}",
                        subject_ref="source|diagnostic",
                        relation="supports",
                        statement="A new diagnostic fact was collected.",
                    )
                ],
            )

    gateway = RepeatedGateway()
    run = await InvestigationAgent(
        gateway,
        collector=FactsCollector(),
        delivery=RecordingDelivery(),
        max_steps=4,
    ).run("card", run_id="multi-stage")

    assert run.status == "delivered"
    assert len(run.steps) == 3
    assert gateway.calls[1]["parent_receipt_id"] == "receipt-1"
    assert gateway.calls[2]["parent_receipt_id"] == "receipt-2"


@pytest.mark.asyncio
async def test_agent_runs_retrieve_then_reevaluate_then_deliver() -> None:
    gateway = FakeSignalWeave()
    collector = RecordingCollector()
    delivery = RecordingDelivery()
    run = await InvestigationAgent(
        gateway,
        collector=collector,
        delivery=delivery,
        max_steps=3,
    ).run("sales-card", run_id="run-test")

    assert run.status == "delivered"
    assert [step.outcome for step in run.steps] == ["investigate", "notify"]
    assert len(collector.requests) == 1
    assert len(delivery.results) == 1
    assert gateway.calls[0]["context"] is None
    assert gateway.calls[1]["context"].version == "test-context-1"
    assert gateway.calls[1]["idempotency_key"] == "run-test:evaluate:2"


@pytest.mark.asyncio
async def test_agent_never_delivers_without_terminal_handoff() -> None:
    class ReviewGateway:
        async def evaluate(self, _card_id: str, **_kwargs: Any) -> dict[str, Any]:
            return {
                "receipt": {"receipt_id": "receipt-review"},
                "result": {
                    "outcome": "investigate",
                    "workflow": {
                        "action": "request_review",
                        "status": "blocked",
                        "step_key": "review",
                    },
                },
            }

    delivery = RecordingDelivery()
    run = await InvestigationAgent(ReviewGateway(), delivery=delivery).run("card")

    assert run.status == "needs_review"
    assert not delivery.results


@pytest.mark.asyncio
async def test_agent_blocks_when_follow_up_returns_no_facts() -> None:
    class EmptyCollector:
        async def collect(self, _request):
            return ContextSnapshot(provider="empty", version="empty-1")

    gateway = FakeSignalWeave()
    run = await InvestigationAgent(
        gateway,
        collector=EmptyCollector(),
        delivery=RecordingDelivery(),
    ).run("sales-card")

    assert run.status == "blocked"
    assert "no facts" in (run.error or "")
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_catalog_collector_uses_only_authorized_required_tools() -> None:
    called: list[str] = []

    def tool(key: str) -> InvestigationTool:
        async def collect(_request):
            called.append(key)
            return [
                ContextFact(
                    fact_id=key,
                    subject_ref=f"source|{key}",
                    relation="supports",
                    statement=f"Fact from {key}.",
                )
            ]

        return InvestigationTool(key, f"Description for {key}", collect)

    collector = CatalogContextCollector(
        [tool("campaign-performance"), tool("purchase-funnel"), tool("unrelated")],
        planner=RequiredSourcePlanner(),
    )
    context = await collector.collect(
        type(
            "Request",
            (),
            {
                "required_source_keys": ("campaign-performance", "purchase-funnel"),
                "step_number": 1,
            },
        )()
    )

    assert called == ["campaign-performance", "purchase-funnel"]
    assert {fact.fact_id for fact in context.facts} == {"campaign-performance", "purchase-funnel"}


def test_llm_tool_selection_is_closed_set() -> None:
    assert parse_tool_selection('{"tool_keys":["known", "invented", "known"]}', {"known"}) == [
        "known"
    ]


def test_json_evidence_tools_can_bind_facts_to_evidence_slots(tmp_path) -> None:
    path = tmp_path / "tools.json"
    path.write_text(
        '{"tools":[{"key":"funnel","description":"funnel","slot_key":"question:2",'
        '"facts":[{"fact_id":"f1","subject_ref":"warehouse|funnel",'
        '"relation":"supports","statement":"Conversion fell."}]}]}',
        encoding="utf-8",
    )

    tools = load_json_tools(path)
    facts = []

    async def collect():
        facts.extend(await tools[0].collect(None))

    import asyncio

    asyncio.run(collect())
    assert facts[0].slot_key == "question:2"


class FakeSlack:
    def __init__(self) -> None:
        self.channels = []
        self.members = {}
        self.invites = []
        self.messages = []

    async def list_channels(self):
        return self.channels

    async def create_channel(self, name):
        channel = {"id": "C123", "name": name}
        self.channels.append(channel)
        self.members["C123"] = []
        return channel

    async def list_members(self, channel_id):
        return self.members.get(channel_id, [])

    async def invite(self, channel_id, user_ids):
        self.invites.append((channel_id, tuple(user_ids)))
        self.members.setdefault(channel_id, []).extend(user_ids)
        return {"ok": True}

    async def post_message(self, channel_id, text):
        self.messages.append((channel_id, text))
        return {"ts": "123.456"}


@pytest.mark.asyncio
async def test_slack_adapter_creates_one_reusable_channel_and_posts_bundle() -> None:
    slack = FakeSlack()
    adapter = SlackDeliveryAdapter(
        slack,
        route=SlackRoute("sales-campaign-health", ("U1", "U2")),
        allow_channel_create=True,
        allow_invites=True,
    )
    result = {
        "summary": "Online sales fell after a campaign conversion regression.",
        "outcome": "notify",
        "confidence": 0.91,
        "rationale": "The funnel evidence supports the alert.",
        "delivery_methods": [{"key": "leadership"}, {"key": "marketing"}],
        "evidence": [{"source_key": "funnel", "statement": "Conversion declined 61%."}],
    }

    first = await adapter.deliver(result, card_id="sales-card", run_id="run-1")
    second = await adapter.deliver(result, card_id="sales-card", run_id="run-2")

    assert first[0]["created"] is True
    assert second[0]["created"] is False
    assert len(slack.channels) == 1
    assert slack.invites == [("C123", ("U1", "U2"))]
    assert len(slack.messages) == 2
    assert "Conversion declined 61%" in slack.messages[0][1]


def test_evidence_bundle_is_structured_without_llm_rewriting() -> None:
    text = format_evidence_bundle(
        {
            "summary": "Campaign conversion regression.",
            "outcome": "notify",
            "confidence": 0.88,
            "rationale": "Independent funnel evidence supports the driver.",
            "evidence_findings": [
                {"role": "driver", "subject_label": "Purchase conversion", "probability": 0.9}
            ],
            "evidence": [
                {"source_key": "funnel", "statement": "Conversion declined 61%.", "source_url": "https://example.test/funnel"}
            ],
        }
    )
    assert "Campaign conversion regression." in text
    assert "`driver` Purchase conversion (0.90)" in text
    assert "<https://example.test/funnel|source>" in text

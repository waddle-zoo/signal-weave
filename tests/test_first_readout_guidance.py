import json

import pytest

from signalweave.engine import InsightEngine
from signalweave.mcp_server import AGENT_PROFILE_TOOLS, create_mcp
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteInsightCardStore, SQLiteMetricQueryCardStore


@pytest.mark.parametrize(("provider", "label"), [
    ("openai-decisions", "OpenAI Decisions"),
    ("chatgpt-plan-responses", "ChatGPT-plan Responses"),
    ("jev-latest", "Jev"),
])
async def test_agent_guide_delivers_first_readout_advice_only_on_start(
    tmp_path, monkeypatch, provider, label,
):
    class NoInference:
        name = provider

        def __getattr__(self, name):
            raise AssertionError(f"Guide unexpectedly requested inference: {name}")

    class NoSourceAccess:
        name = "private-adapter-name-must-not-leak"

        async def list_resources(self):
            raise AssertionError("Guide unexpectedly enumerated sources")

        async def inspect(self, source):
            raise AssertionError("Guide unexpectedly inspected sources")

    sources = SourceRegistry([NoSourceAccess()])

    def forbidden_source_call(*args, **kwargs):
        raise AssertionError("Guide unexpectedly accessed source data")

    for method in ("list_resources", "inspect", "resolve"):
        monkeypatch.setattr(sources, method, forbidden_source_call)

    store = SQLiteInsightCardStore(tmp_path / "cards.db")
    runtime = Runtime(
        card_store=store,
        metric_query_store=SQLiteMetricQueryCardStore(tmp_path / "cards.db"),
        sources=sources,
        engine=InsightEngine(NoInference(), sources),
    )
    server = create_mcp(runtime)
    tools = {tool.name: tool for tool in await server.list_tools()}
    guide_tool = tools["get_signalweave_guide"]

    assert set(tools) == AGENT_PROFILE_TOOLS
    assert guide_tool.annotations.readOnlyHint
    assert guide_tool.annotations.destructiveHint is False
    assert guide_tool.inputSchema.get("required", []) == []
    assert store.list_cards() == []

    _, start = await server.call_tool("get_signalweave_guide", {"task": "start"})
    _, monitor = await server.call_tool("get_signalweave_guide", {"task": "monitor"})

    assert isinstance(start["first_readout"], str) and start["first_readout"].strip()
    assert "first_readout" not in monitor
    assert start["decision_provider"] == monitor["decision_provider"] == provider
    assert label in json.dumps(start)
    assert start["inference_performed"] is monitor["inference_performed"] is False
    assert start["jev_used"] is monitor["jev_used"] is False
    assert "private-adapter-name-must-not-leak" not in json.dumps([start, monitor])
    assert store.list_cards() == []


async def test_plain_profile_persists_business_purpose_without_changing_action_rules_or_sources(tmp_path):
    from tests.test_card_revision_mcp import assert_no_source_or_model_calls, setup_server

    _, runtime, before, catalog, judger = setup_server(tmp_path, sqlite=True)
    server = create_mcp(runtime, profile="agent")
    assert "save_domain_context" not in {tool.name for tool in await server.list_tools()}
    reader_context = "Growth watches signup conversion to detect unexpected losses before the weekly review."
    _, result = await server.call_tool("revise_insight_card", {
        "card_id": before.id, "expected_card_version": before.version,
        "changes": {"why_watch": reader_context}, "reason": "Owner clarified the business purpose.",
    })
    assert result["card"]["id"] == before.id
    reopened = SQLiteInsightCardStore(runtime.card_store.path).get_card(before.id)
    assert reopened.why_watch == reader_context
    assert reopened.version == before.version + 1
    assert reopened.status == "draft" and reopened.approved_at is None
    assert reopened.sources == before.sources
    assert reopened.decision_guidance == before.decision_guidance
    assert reopened.delivery_methods == before.delivery_methods
    assert_no_source_or_model_calls(catalog, judger)

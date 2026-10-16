"""Fixed-source review guidance and its offline execution contract."""

import json

import pytest

from signalweave.engine import InsightEngine
from signalweave.getting_started import agent_getting_started
from signalweave.mcp_server import create_mcp
from signalweave.models import PrincipalContext, ResourceContract, ResourceDescriptor
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import JsonInsightCardStore


class FixedSourceCatalog:
    name = "fixture"

    async def list_resources(self):
        return [ResourceDescriptor(
            adapter=self.name,
            resource="fixed-anchor",
            kind="dashboard",
            title="Fixed source",
            contract=ResourceContract(available_comparison_windows=["previous_period"]),
        )]


class NoCandidateRanking:
    name = "ranking-disabled-test-double"

    async def rank_resources(self, goal, resources):
        del goal, resources
        raise AssertionError("fixed-source review must not invoke Jev candidate ranking")


def make_agent_server(tmp_path):
    sources = SourceRegistry([FixedSourceCatalog()], authorized_tenants=["default"])
    runtime = Runtime(
        card_store=JsonInsightCardStore(tmp_path / "cards.json"),
        sources=sources,
        engine=InsightEngine(NoCandidateRanking(), registry=sources),
        principal=PrincipalContext(principal_id="test-principal", tenant_id="default"),
    )
    return create_mcp(runtime, profile="agent")


def tool(server, name):
    return server._tool_manager.get_tool(name).fn


async def test_agent_profile_explains_fixed_review_and_comparison_limits(tmp_path):
    server = make_agent_server(tmp_path)
    tools = {item.name: item for item in await server.list_tools()}
    assert "review_insight_card" in tools
    assert "without Jev" in tools["review_insight_card"].description
    assert "dynamic discovery or ranked expansion" in tools["review_insight_card"].description

    guide_result = await server.call_tool("get_signalweave_guide", {"task": "start"})
    guide = json.dumps(guide_result, default=str)
    assert "even after frontier-owned discovery" in guide
    assert "do not invent comparison keys" in guide
    assert "prior_calendar_month" in guide and "last_two_returned" in guide
    assert "existing declared aggregate" in guide
    assert "coverage-only sources only for coverage" in guide
    assert "do not page full detail" in guide

    local_guide = agent_getting_started("start")
    assert any("even after frontier-owned discovery" in step["purpose"]
               for step in local_guide["steps"] if step["tool"] == "review_insight_card")


@pytest.mark.asyncio
async def test_fixed_declared_source_review_succeeds_without_candidate_ranking(tmp_path):
    server = make_agent_server(tmp_path)
    draft = await tool(server, "onboard_insight_card")(
        what_to_watch="A checked metric.",
        why_watch="Support a recurring review.",
        selected_sources=[{"ref": "fixture|fixed-anchor", "key": "primary"}],
    )

    reviewed = await tool(server, "review_insight_card")(draft["card"]["id"])

    assert reviewed["review"]["discovery_receipt"]["evaluator"] == "caller-source-selection"
    assert reviewed["review"]["selected_source_refs"] == ["fixture|fixed-anchor"]

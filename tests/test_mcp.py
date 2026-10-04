import pytest

from signalweave.engine import InsightEngine
from signalweave.mcp_server import create_mcp
from signalweave.runtime import Runtime


class StubStore:
    """Construction-only store stub; MCP behavior is tested through dedicated routes."""

    pass


class TestJudger:
    name = "jev-test-double"

    async def compile_plan(self, state, card):
        del state, card
        return {"capabilities": ["freshness_check"], "baseline": "previous_period"}

    async def judge(self, state, card, plan, observations):
        from signalweave.models import InsightResult, Outcome

        del plan
        return InsightResult(
            card_id=card.id,
            outcome=Outcome.INVESTIGATE,
            summary="Test-only result.",
            rationale="Test-only result.",
            confidence=1.0,
            evidence=state["evidence"],
            observations=observations,
            source_keys=[source.key for source in card.sources],
            evaluator=self.name,
        )


def test_server_exposes_mcp_object():
    from signalweave.sources import SourceRegistry

    server = create_mcp(
        Runtime(
            card_store=StubStore(),
            sources=SourceRegistry(),
            engine=InsightEngine(TestJudger()),
        )
    )
    assert server.name == "signal-weave"
    # These instructions travel in MCP initialization, including the standalone
    # executable. A newly connected agent should not need a separate setup skill.
    assert "onboard_insight_card" in server.instructions
    assert "bootstrap_insight_card" in server.instructions
    assert "Only call approve_insight_card after explicit owner approval" in server.instructions
    assert "without workflow_report_id authorizes only" in server.instructions
    assert "unassessed card" in server.instructions
    assert "does not certify or authorize unattended delivery" in server.instructions
    assert "not offline inference" in server.instructions
    assert "not proof of causation" in server.instructions


async def test_native_authoring_schema_and_dispatch_enforce_evidence_slots(tmp_path):
    from tests.test_onboarding import make_server

    server = make_server(tmp_path)
    pattern = r"^(question|watch):[1-9][0-9]*$"
    authoring_tools = ("draft_insight_card", "propose_insight_card", "onboard_insight_card")
    for name in authoring_tools:
        spec = next(item for item in await server.list_tools() if item.name == name)
        field = spec.inputSchema["properties"]["evidence_requirements"]
        object_schema = next(item for item in field["anyOf"] if item.get("type") == "object")
        assert object_schema["patternProperties"] == {pattern: {"type": "boolean"}}

        arguments = {
            "what_to_watch": "Checkout conversion",
            "why_watch": "Decide whether Growth should act.",
            "questions": ["Is there a material decline?"],
            "evidence_requirements": {"question:2": False},
        }
        if name == "draft_insight_card":
            arguments.update({
                "title": "Evidence slot boundary",
                "sources": [{
                    "key": "growth", "adapter": "superset", "resource": "dashboard:7",
                    "label": "Growth overview",
                }],
            })
        else:
            arguments["selected_sources"] = [{"ref": "superset|dashboard:7"}]
        with pytest.raises(Exception, match="evidence_requirements"):
            await server.call_tool(name, arguments)
    assert server._test_runtime.card_store.list_cards() == []

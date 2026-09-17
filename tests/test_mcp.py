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

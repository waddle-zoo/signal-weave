from semantic_monitor.engine import MonitorEngine
from semantic_monitor.mcp_server import create_mcp
from semantic_monitor.runtime import Runtime
from semantic_monitor.store import FixtureStore


class TestJudger:
    name = "jev-test-double"

    async def compile_plan(self, state, card):
        del state, card
        return {"operations": ["freshness_check"]}

    async def judge(self, state, card, plan, observations):
        from semantic_monitor.models import Decision, Outcome

        del plan
        return Decision(
            outcome=Outcome.INVESTIGATE,
            rationale="Test-only result.",
            confidence=1.0,
            evidence=state["evidence"],
            observations=observations,
            monitor_id=card.id,
            dashboard_id=card.dashboard_id,
            evaluator=self.name,
        )


def test_server_exposes_mcp_object():
    server = create_mcp(Runtime(store=FixtureStore(), engine=MonitorEngine(TestJudger())))
    assert server.name == "signal-weave"

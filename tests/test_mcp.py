from semantic_monitor.engine import MonitorEngine
from semantic_monitor.mcp_server import create_mcp
from semantic_monitor.runtime import Runtime


class StubStore:
    """Construction-only store stub; MCP behavior is tested through dedicated routes."""

    pass


class TestJudger:
    name = "jev-test-double"

    async def compile_plan(self, state, workflow):
        del state, workflow
        return {"operations": ["freshness_check"]}

    async def judge(self, state, workflow, plan, observations):
        from semantic_monitor.models import Decision, Outcome

        del plan
        return Decision(
            outcome=Outcome.INVESTIGATE,
            rationale="Test-only result.",
            confidence=1.0,
            evidence=state["evidence"],
            observations=observations,
            workflow_id=workflow.id,
            source_keys=[source.key for source in workflow.sources],
            evaluator=self.name,
        )


def test_server_exposes_mcp_object():
    from semantic_monitor.sources import SourceRegistry

    server = create_mcp(
        Runtime(
            workflow_store=StubStore(),
            sources=SourceRegistry(),
            engine=MonitorEngine(TestJudger()),
        )
    )
    assert server.name == "signal-weave"

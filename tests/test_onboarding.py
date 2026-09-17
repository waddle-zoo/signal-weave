import httpx
import pytest

from semantic_monitor.engine import MonitorEngine
from semantic_monitor.mcp_server import create_mcp
from semantic_monitor.models import (
    Decision,
    Evidence,
    Observation,
    Outcome,
    ResourceDescriptor,
    ResourceSnapshot,
)
from semantic_monitor.runtime import Runtime
from semantic_monitor.sources import SourceRegistry
from semantic_monitor.store import JsonWorkflowStore


class SupersetCatalogDouble:
    name = "superset"

    def __init__(self):
        self.resources = [
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:7",
                kind="dashboard",
                title="Growth overview",
                description="Revenue, conversion, and checkout health.",
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:8",
                kind="dashboard",
                title="Finance close",
                description="Month-end reporting and forecast variance.",
            ),
            ResourceDescriptor(
                adapter=self.name,
                resource="dashboard:9",
                kind="dashboard",
                title="People operations",
                description="Hiring and retention metrics.",
            ),
        ]

    async def list_resources(self):
        return self.resources

    async def inspect(self, source):
        return ResourceSnapshot(
            source_key=source.key,
            adapter=source.adapter,
            resource=source.resource,
            title=source.label,
            observations=[
                Observation(
                    source_key=source.key,
                    subject_id="conversion",
                    subject_label="Checkout conversion",
                    metric="checkout_conversion",
                    current=0.82,
                    baseline=0.95,
                    change_pct=-13.684,
                )
            ],
        )


class OnboardingJevDouble:
    name = "jev-onboarding-test-double"

    async def rank_resources(self, goal, resources):
        del goal
        return {
            f"{resource.adapter}|{resource.resource}": {
                "dashboard:7": 0.94,
                "dashboard:8": 0.31,
                "dashboard:9": 0.12,
            }[resource.resource]
            for resource in resources
        }

    async def compile_plan(self, state, workflow):
        del state
        return {
            "operations": ["percent_change", "cross_source_comparison"],
            "baseline": workflow.comparison_windows[0],
        }

    async def judge(self, state, workflow, plan, observations):
        del plan
        return Decision(
            outcome=Outcome.NOTIFY,
            recipient_key=workflow.recipients[0].key if workflow.recipients else None,
            rationale="Test-only onboarding decision.",
            confidence=0.91,
            probabilities={Outcome.NOTIFY.value: 0.91},
            evidence=[Evidence.model_validate(item) for item in state["evidence"]],
            observations=observations,
            workflow_id=workflow.id,
            source_keys=[source["source_key"] for source in state["sources"]],
            evaluator=self.name,
        )


class NoResourceRankingJudger:
    name = "non-jev-test-judger"


def make_server(tmp_path):
    registry = SourceRegistry([SupersetCatalogDouble()])
    engine = MonitorEngine(OnboardingJevDouble(), registry=registry)
    return create_mcp(
        Runtime(
            workflow_store=JsonWorkflowStore(tmp_path / "workflows.json"),
            sources=registry,
            engine=engine,
        )
    )


def tool(server, name):
    return server._tool_manager.get_tool(name).fn


@pytest.mark.asyncio
async def test_goal_to_card_flow_discovers_proposes_previews_and_requires_approval(tmp_path):
    server = make_server(tmp_path)

    discovery = await tool(server, "discover_monitor_inputs")(
        goal="Watch growth checkout conversion for revenue risk.",
        adapter="superset",
        limit=2,
    )
    assert discovery["matches"][0]["resource"] == "dashboard:7"
    assert discovery["matches"][0]["recommended"] is True

    proposal = await tool(server, "propose_monitor_card")(
        goal="Watch growth checkout conversion for revenue risk.",
        selected_sources=[
            {
                "ref": "superset|dashboard:7",
                "parameters": {"chart_ids": ["62", "64"]},
            }
        ],
        recipients=[
            {
                "key": "growth-ops",
                "label": "Growth Ops",
                "destination": "slack://growth-ops",
            }
        ],
    )
    workflow_id = proposal["proposal"]["workflow"]["id"]
    assert proposal["proposal"]["status"] == "draft"
    assert proposal["proposal"]["workflow"]["sources"][0]["parameters"] == {
        "chart_ids": ["62", "64"]
    }
    assert proposal["proposal"]["questions"]

    with pytest.raises(ValueError, match="draft"):
        await tool(server, "evaluate_workflow")(workflow_id)

    app = server.streamable_http_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/evaluate", json={"workflow_id": workflow_id}
        )
    assert response.status_code == 409

    preview = await tool(server, "simulate_monitor_card")(workflow_id)
    assert preview["status"] == "preview"
    assert preview["delivery_enabled"] is False
    assert preview["decision"]["outcome"] == "notify"

    approved = tool(server, "approve_monitor_card")(workflow_id)
    assert approved["status"] == "approved"
    evaluated = await tool(server, "evaluate_workflow")(workflow_id)
    assert evaluated["decision"]["recipient_key"] == "growth-ops"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/evaluate", json={"workflow_id": workflow_id}
        )
    assert response.status_code == 200
    assert response.json()["recipient_key"] == "growth-ops"


@pytest.mark.asyncio
async def test_proposal_rejects_source_not_returned_by_discovery(tmp_path):
    server = make_server(tmp_path)

    with pytest.raises(ValueError, match="discover_monitor_inputs"):
        await tool(server, "propose_monitor_card")(
            goal="Watch checkout conversion.",
            selected_sources=[{"ref": "superset|dashboard:999"}],
        )


def test_mcp_exposes_conversational_authoring_tools(tmp_path):
    server = make_server(tmp_path)
    names = set(server._tool_manager._tools)
    assert {
        "discover_monitor_inputs",
        "propose_monitor_card",
        "simulate_monitor_card",
        "approve_monitor_card",
    } <= names


@pytest.mark.asyncio
async def test_discovery_requires_jev_resource_ranking(tmp_path):
    registry = SourceRegistry([SupersetCatalogDouble()])
    server = create_mcp(
        Runtime(
            workflow_store=JsonWorkflowStore(tmp_path / "workflows.json"),
            sources=registry,
            engine=MonitorEngine(NoResourceRankingJudger(), registry=registry),
        )
    )

    with pytest.raises(RuntimeError, match="does not support resource discovery"):
        await tool(server, "discover_monitor_inputs")(goal="Watch growth")

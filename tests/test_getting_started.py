"""Orientation is offline guidance, not a simulated Jev decision or user study."""

import json

import pytest

from signalweave.engine import InsightEngine
from signalweave.getting_started import getting_started
from signalweave.mcp_server import create_mcp
from signalweave.runtime import Runtime
from signalweave.sources import SourceRegistry
from signalweave.store import SQLiteInsightCardStore, SQLiteMetricQueryCardStore


@pytest.fixture
def server(tmp_path):
    class NoInference:
        name = "jev-forbidden-in-orientation"

        def __getattr__(self, name):
            raise AssertionError("Orientation must not request inference")

    class NoSourceAccess:
        name = "private-adapter-name-must-not-leak"

        async def list_resources(self):
            raise AssertionError("Orientation must not enumerate sources")

        async def inspect(self, source):
            raise AssertionError("Orientation must not inspect sources")

    sources = SourceRegistry([NoSourceAccess()])
    return create_mcp(Runtime(
        card_store=SQLiteInsightCardStore(tmp_path / "cards.db"),
        metric_query_store=SQLiteMetricQueryCardStore(tmp_path / "cards.db"),
        sources=sources, engine=InsightEngine(NoInference(), sources),
    ))


@pytest.mark.parametrize("task", ["start", "query", "report", "monitor"])
async def test_guide_exposes_only_real_tools_without_source_or_model_calls(server, task):
    tools = {tool.name: tool for tool in await server.list_tools()}
    guide = tools["get_signalweave_guide"]
    assert guide.annotations.readOnlyHint
    assert guide.annotations.destructiveHint is False
    response = await server.call_tool("get_signalweave_guide", {"task": task})
    text = json.dumps(response, default=str)
    assert "private-adapter-name-must-not-leak" not in text
    result = getting_started(task)
    for step in result.get("steps", []):
        assert step["tool"] in tools
    assert "get_signalweave_guide" in server.instructions
    assert "Jev" in text and "TypeSafe" in text


def test_paths_keep_execution_and_approval_honest():
    query = getting_started("query")
    report = getting_started("report")
    monitor = getting_started("monitor")
    assert "Compilation is not execution" in query["human_handoff"]
    assert "typed metric_definitions" in query["needs"]
    assert "inspect_resource" not in [step["tool"] for step in query["steps"]]
    assert any("query-cost limits" in boundary for boundary in query["boundaries"])
    assert "reconciled comparison tables" in report["needs"]
    assert report["steps"][-1]["tool"] == "preview_investigation_report"
    assert not any(step["tool"].startswith("approve") for step in report["steps"])
    assert "does neither by itself" in monitor["human_handoff"]
    assert "missing-evidence" in monitor["needs"]
    assert [step["tool"] for step in monitor["steps"]].index("evaluate_card_workflow") < [
        step["tool"] for step in monitor["steps"]
    ].index("approve_insight_card")


async def test_unknown_path_is_rejected_by_mcp_schema(server):
    with pytest.raises(Exception, match="Input should be"):
        await server.call_tool("get_signalweave_guide", {"task": "run-all-company-tools"})


@pytest.mark.parametrize("task", ["report", "monitor"])
def test_preview_review_distinguishes_execution_from_behavioral_acceptance(task):
    review = getting_started(task)["preview_review"]
    assert "independently propose" in review["before_preview"]
    assert "Do not copy Jev's answer" in review["before_preview"]
    assert "execution, not correctness" in review["compare"]
    assert "Unknown required checks" in review["compare"]
    assert "not automatically fetched" in review["source_coverage"]
    assert "unless the owner requires" in review["source_coverage"]
    assert "never lower confidence" in review["repair"]
    assert "capture_current_sources" in review["retest"]
    assert "not independent historical acceptance" in review["retest"]


def test_behavioral_review_does_not_expand_query_or_start_paths():
    assert "preview_review" not in getting_started("query")
    assert "preview_review" not in getting_started("start")

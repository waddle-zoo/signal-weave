"""MCP authoring limits are enforced before any source or model work."""

import pytest

from tests.test_onboarding import make_server

AUTHORING_TOOLS = (
    "discover_insight_sources",
    "propose_insight_card",
    "onboard_insight_card",
    "review_insight_card",
)


def arguments_for(tool_name, limit):
    if tool_name == "discover_insight_sources":
        return {"goal": "Checkout conversion", "limit": limit}
    if tool_name in {"propose_insight_card", "onboard_insight_card"}:
        return {
            "what_to_watch": "Checkout conversion",
            "why_watch": "Decide whether the owner should respond.",
            "limit": limit,
        }
    return {"card_id": "missing-card", "limit": limit}


@pytest.mark.asyncio
async def test_authoring_tools_publish_the_shared_bounded_limit_schema(tmp_path):
    server = make_server(tmp_path)
    specs = {spec.name: spec for spec in await server.list_tools()}

    for name in AUTHORING_TOOLS:
        field = specs[name].inputSchema["properties"]["limit"]
        assert field["minimum"] == 1
        assert field["maximum"] == 25
        assert field["default"] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", AUTHORING_TOOLS)
@pytest.mark.parametrize("limit", [0, 26])
async def test_authoring_limit_rejection_precedes_source_and_model_calls(
    tmp_path, monkeypatch, tool_name, limit
):
    server = make_server(tmp_path)

    async def unexpected_call(*args, **kwargs):
        del args, kwargs
        raise AssertionError("invalid authoring input reached a source or model call")

    monkeypatch.setattr(server._test_runtime.sources, "search_resources", unexpected_call)
    monkeypatch.setattr(server._test_runtime.engine.judger, "rank_resources", unexpected_call)

    with pytest.raises(Exception, match="validation error"):
        await server.call_tool(tool_name, arguments_for(tool_name, limit))

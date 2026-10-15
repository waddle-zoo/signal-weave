import json
from types import SimpleNamespace

import pytest

from signalweave.mcp_server import create_mcp
from tests.test_local_investigation import make_runtime


@pytest.mark.parametrize(("provider", "label"), [
    ("openai-decisions", "OpenAI Decisions"),
    ("chatgpt-plan-responses", "ChatGPT-plan Responses"),
    ("jev-latest", "Jev"),
])
async def test_guidance_names_the_actual_provider_without_running_inference(tmp_path, provider, label):
    runtime, _, _ = make_runtime(tmp_path)
    runtime.engine.judger = SimpleNamespace(name=provider)
    server = create_mcp(runtime)
    _, response = await server.call_tool("get_signalweave_guide", {"task": "start"})
    assert response["decision_provider"] == provider
    assert response["inference_performed"] is False
    assert response["jev_used"] is False
    assert f"calls {label} for the card" in server.instructions
    assert label in json.dumps(response)
    if provider != "jev-latest":
        assert "Jev" not in server.instructions
        assert "TypeSafe" not in json.dumps(response)

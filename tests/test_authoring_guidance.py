"""Agent-visible authoring semantics; no inferred policy or automatic rewriting."""

import json

import pytest
from test_onboarding import make_server
from test_onboarding_windows import arguments, dispatch


@pytest.mark.parametrize("name", ["draft_insight_card", "propose_insight_card", "onboard_insight_card"])
async def test_schema_distinguishes_recurring_evidence_from_setup_and_route_policy(tmp_path, name):
    server = make_server(tmp_path)
    spec = next(t for t in await server.list_tools() if t.name == name)
    properties = spec.inputSchema["properties"]
    assert "each run" in json.dumps(properties["questions"])
    assert "setup questions" in json.dumps(properties["questions"])
    assert "decision_guidance" in json.dumps(properties["questions"])
    assert "conditions" in json.dumps(properties["watch_for"])
    assert "advisory" in json.dumps(properties["watch_for"])
    assert "investigate" in json.dumps(properties["delivery_methods"])
    assert "prose" in json.dumps(properties["delivery_methods"])


@pytest.mark.parametrize("name", ["draft_insight_card", "propose_insight_card", "onboard_insight_card"])
async def test_guidance_preserves_freeform_questions_and_exact_owner_routes(tmp_path, name):
    server = make_server(tmp_path)
    questions = ["Has operating ownership changed since the reviewed plan?", "What changed in this population, and why might it matter?"]
    watches = ["Unexpected divergence across these sources — interpreted using the owner's scope."]
    methods = [{"key": "operations", "outcome": "investigate", "label": "Operations",
                "destination": "agent://operations", "instructions": "Investigate with the existing team."}]
    payload = await dispatch(server, name, arguments(name,
        questions=questions, watch_for=watches, evidence_requirements={"question:2": False},
        delivery_methods=methods, decision_guidance="Investigate divergence with Operations; keep hypotheses qualified.",
    ))
    assert payload["card"]["questions"] == questions
    assert payload["card"]["watch_for"] == watches
    assert payload["card"]["delivery_methods"] == methods
    assert payload["card"]["evidence_requirements"] == {"question:2": False}
    assert payload["card"]["status"] == "draft"

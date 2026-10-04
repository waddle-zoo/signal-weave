"""Agent-visible authoring semantics; no inferred policy or automatic rewriting."""

import json

import pytest
from test_onboarding import make_server
from test_onboarding_windows import arguments, dispatch

from signalweave.mcp_server import CARD_AUTHORING_GUIDANCE
from signalweave.models import InsightCard, InvestigationMode, RetrievalMode


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


def test_server_exposes_shared_authoring_guidance(tmp_path):
    server = make_server(tmp_path)

    assert CARD_AUTHORING_GUIDANCE in server.instructions
    assert "minimal business fields" in CARD_AUTHORING_GUIDANCE
    assert "SourceRef" in CARD_AUTHORING_GUIDANCE
    assert "every owner-requested delivery rule" in CARD_AUTHORING_GUIDANCE
    assert "outcomes meant to stay silent need no delivery entry" in CARD_AUTHORING_GUIDANCE
    assert "Never invent a recipient" in CARD_AUTHORING_GUIDANCE
    assert "large but unchanged level" in CARD_AUTHORING_GUIDANCE
    assert "independently of the model's answers" in CARD_AUTHORING_GUIDANCE


@pytest.mark.parametrize("name", ["draft_insight_card", "propose_insight_card", "onboard_insight_card"])
async def test_native_mcp_authoring_schema_preserves_defaults_and_allows_advanced_threshold(tmp_path, name):
    server = make_server(tmp_path)
    spec = next(tool for tool in await server.list_tools() if tool.name == name)
    properties = spec.inputSchema["properties"]

    if name == "draft_insight_card":
        assert "minimal business fields" in spec.description
    assert properties["action_confidence_threshold"]["default"] == 0.70
    assert properties["action_confidence_threshold"]["maximum"] == 1.0
    assert "model-support floor" in properties["action_confidence_threshold"]["description"].lower()
    assert properties["retrieval_mode"]["default"] == "fixed"
    assert properties["investigation_mode"]["default"] == "none"
    assert "selected source references" in properties["retrieval_mode"]["description"]
    assert "additional authorized sources" in properties["retrieval_mode"]["description"]
    assert "none disables follow-up" in properties["investigation_mode"]["description"]
    assert "live SourceRegistry" in properties["investigation_mode"]["description"]


def test_stored_insight_card_defaults_remain_conservative():
    fields = InsightCard.model_fields

    assert fields["action_confidence_threshold"].default == 0.70
    assert fields["retrieval_mode"].default is RetrievalMode.FIXED
    assert fields["investigation_mode"].default is InvestigationMode.NONE

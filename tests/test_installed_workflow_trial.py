import copy

import pytest

from evaluations.bootstrap_agent_trial import Audit, PublicSourceAdapter
from evaluations.bootstrap_scenarios import public_scenario
from evaluations.installed_northstar_cases import build_northstar
from evaluations.installed_workflow_trial import (
    InstalledSession,
    bind_examples,
    onboarding_instructions,
    score_native,
)
from tests.test_northstar_growth_history_trial import _write_seed_dir


@pytest.fixture
def card():
    return {"id": "card-test", "version": 1, "compiled_plan": {"card_id": "card-test"},
            "sources": [{"key": "alias", "adapter": "company_mcp", "resource": "r"}],
            "delivery_methods": [{"key": "owner", "destination": "slack://simulation-owner"}]}


def example():
    return {"id": "history", "expected_outcome": "notify",
            "expected_delivery_destinations": {"original-route-key": "slack://simulation-owner"},
            "required_evidence_refs": ["company_mcp|r"],
            "expected_retrieval_refs": ["company_mcp|r"],
            "resources": [{"adapter": "company_mcp", "resource": "r", "source_key": "r",
                           "observations": [{"source_key": "r", "current": 8}],
                           "evidence": [{"source_key": "r", "statement": "Observed"}]}]}


def test_examples_project_only_identity_without_mutating_owner_inputs(card):
    original = example()
    saved = copy.deepcopy(original)
    result, = bind_examples([original], card)
    assert original == saved
    assert result["resources"][0]["observations"] == [{"source_key": "alias", "current": 8}]
    assert result["expected_delivery_destinations"] == {"owner": "slack://simulation-owner"}
    assert result["required_evidence_source_keys"] == ["alias"]
    assert result["expected_outcome"] == "notify"


def test_cannot_silently_drop_needed_evidence_or_owner_route(card):
    missing = copy.deepcopy(card)
    missing["sources"] = []
    with pytest.raises(ValueError, match="omits"):
        bind_examples([example()], missing)
    missing = copy.deepcopy(card)
    missing["delivery_methods"] = []
    with pytest.raises(ValueError, match="destination"):
        bind_examples([example()], missing)


def native_output(card):
    report = {"card_id": card["id"], "outcome": "notify"}
    return {"card": {k: copy.deepcopy(v) for k, v in card.items() if k != "compiled_plan"},
            "plan": copy.deepcopy(card["compiled_plan"]), "report": report,
            "receipt": {"card_id": card["id"], "card_version": card["version"],
                        "delivery_enabled": False, "delivery_mode": "shadow", "status": "delivery_disabled",
                        "outcome": "notify", "delivery_method_keys": ["owner"]},
            "result": {"card_id": card["id"], "outcome": "notify", "report": copy.deepcopy(report),
                       "evidence": [{"source_key": "alias"}], "delivery_methods": card["delivery_methods"]},
            "passed": True}


def test_native_scoring_recomputes_result_not_flags(card):
    label = {"outcome": "notify", "recipients": ["owner"], "required_evidence_refs": ["company_mcp|r"]}
    destinations = [{"key": "owner", "destination": "slack://simulation-owner"}]
    output = native_output(card)
    assert score_native(output, card, label, destinations)["exact"]
    output["result"]["outcome"] = "ignore"
    assert not score_native(output, card, label, destinations)["exact"]
    output["result"]["outcome"] = "notify"
    output["result"]["evidence"] = []
    assert not score_native(output, card, label, destinations)["exact"]


@pytest.mark.parametrize("section,field,value", [
    ("receipt", "delivery_enabled", True), ("receipt", "status", "delivered"),
    ("result", "card_id", "another-card"), ("report", "outcome", "ignore"),
    ("plan", "card_id", "mutated"), ("receipt", "card_version", 2),
])
def test_native_scoring_rejects_wrong_identity_delivery_and_plan(card, section, field, value):
    output = native_output(card)
    output[section][field] = value
    label = {"outcome": "notify", "recipients": ["owner"], "required_evidence_refs": ["company_mcp|r"]}
    assert not score_native(output, card, label,
                            [{"key": "owner", "destination": "slack://simulation-owner"}])["exact"]


async def test_native_scorer_uses_actual_mcp_serialization_contract(tmp_path):
    # Offline double controls the model only. The real MCP creates the response;
    # this is a serialization test, not semantic-correctness evidence.
    from test_mcp_acceptance import setup, tool
    server, card_id, _ = await setup(tmp_path)
    await tool(server, "approve_insight_card")(card_id)
    card = tool(server, "get_insight_card")(card_id)
    output = await tool(server, "evaluate_insight_card")(card_id, idempotency_key="shape-test")
    assert "compiled_plan" not in output["card"]
    assert output["plan"] == card["compiled_plan"]
    label = {"outcome": output["result"]["outcome"], "recipients": ["owner"],
             "required_evidence_refs": ["superset|dashboard:7"]}
    assert score_native(output, card, label, [{"key": "owner", "destination": "sink:opaque"}])["exact"]


def test_empty_failure_never_counts_as_correct_missing_data(card):
    label = {"outcome": "insufficient_data", "recipients": [], "required_evidence_refs": []}
    assert not score_native({}, card, label, [])["exact"]


def test_unknown_recipient_rejected(card):
    label = {"outcome": "notify", "recipients": ["owner"], "required_evidence_refs": ["company_mcp|r"]}
    output = {"result": {"outcome": "notify", "evidence": [{"source_key": "alias"}],
                         "delivery_methods": [{"destination": "slack://unapproved"}]}}
    assert not score_native(output, card, label, [{"key": "owner", "destination": "slack://simulation-owner"}])["routes_correct"]


def test_onboarding_instructions_describe_supplied_history_not_future_labels():
    class Server:
        instructions = "Product-native instructions"
    text = onboarding_instructions(Server())
    assert "No independent historical acceptance snapshots" not in text
    assert "never change labels" in text
    assert "Do not fetch future periods" in text
    assert "get_signalweave_guide" in text
    assert "Product-native instructions" in text


async def test_author_cannot_modify_calibration_cases_to_pass():
    session = object.__new__(InstalledSession)
    session.offered_cases = [example()]
    session.examples = [example()]
    with pytest.raises(ValueError, match="unchanged"):
        await session.call("evaluate_card_workflow", {"cases": [], "card_id": "x"})
    with pytest.raises(ValueError, match="every owner-labeled"):
        await session.call("evaluate_card_workflow", {"cases": [example()], "card_id": "x"})
    with pytest.raises(ValueError, match="unmodified"):
        await session.call("evaluate_card_workflow", {"cases": [example()], "card_id": "x",
                           "acceptance_outcomes": ["notify"], "thresholds": {"min_outcome_accuracy": 0}})


def test_session_public_projection_excludes_future_measurements_without_server_init(tmp_path):
    scenario = build_northstar(_write_seed_dir(tmp_path / "seed"), smoke=True)
    public = public_scenario(scenario)
    public["periods"][0]["snapshots"][next(iter(public["periods"][0]["snapshots"]))]["metadata"][
        "future_canary"
    ] = "must-not-reach-author"
    audit = Audit(tmp_path / "audit.jsonl", ("test-secret",))
    adapter = PublicSourceAdapter(public["catalog"], public["scenario_id"], audit)
    session = InstalledSession(public, adapter, None, True, examples=[])

    assert not {"periods", "snapshots", "catalog", "owner_answers"} & session.public.keys()
    assert "must-not-reach-author" not in str(session.public)

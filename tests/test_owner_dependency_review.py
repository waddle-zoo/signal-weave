"""Projection tests for owner review of card-wide source dependencies."""

import pytest

from evaluations import bootstrap_owner_review as reviewer
from evaluations.bootstrap_agent_trial import canonical


def _inputs():
    return {
        "public": {
            "brief": "Use commerce sales as the decision basis; support is context only.",
            "glossary": {},
            "destinations": [{"key": "owner", "label": "Business owner",
                              "destination": "slack://owner"}],
            "private_label": "PRIVATE_EXPECTED_NOTIFY",
        },
        "owner_answers": {
            "source_scope": "Commerce sales is needed for every decision; support is corroborating context.",
        },
        "artifact": {
            "notes": "Review the sales close under the owner's policy.",
            "private_label": "PRIVATE_CARD_LABEL",
            "card": {
                "decision_guidance": "Apply the owner's sales policy.",
                "sources": [
                    {"key": "sales", "adapter": "company_mcp", "resource": "sales",
                     "required": True, "required_comparison_keys": []},
                    {"key": "support", "adapter": "company_mcp", "resource": "support",
                     "required": False, "required_comparison_keys": []},
                ],
                "private_label": "PRIVATE_CARD_DECISION",
            },
        },
        "source_context": {
            "catalog": [
                {"adapter": "company_mcp", "resource": "sales", "title": "Sales",
                 "description": "Monthly sales totals.",
                 "contract": {"roles": ["primary"]}},
                {"adapter": "company_mcp", "resource": "support", "title": "Support",
                 "description": "Support context.",
                 "contract": {"roles": ["diagnostic", "corroborates"]}},
            ],
            "inspected_sources": [],
        },
    }


def test_review_payload_projects_required_flags_roles_and_no_private_labels():
    inputs = _inputs()
    payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )

    bindings = {binding["key"]: binding
                for binding in payload["execution_contract"]["source_bindings"]}
    assert bindings["sales"]["required"] is True
    assert bindings["support"]["required"] is False
    assert payload["source_context"]["catalog"][0]["contract"]["roles"] == ["primary"]
    assert payload["source_context"]["catalog"][1]["contract"]["roles"] == [
        "diagnostic", "corroborates",
    ]
    projected = canonical(payload)
    assert "PRIVATE_EXPECTED_NOTIFY" not in projected
    assert "PRIVATE_CARD_LABEL" not in projected
    assert "PRIVATE_CARD_DECISION" not in projected


def test_required_source_default_stays_true_and_baseline_notes_need_no_card_bindings():
    inputs = _inputs()
    source = inputs["artifact"]["card"]["sources"][0]
    source.pop("required")
    card_payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
    )
    assert card_payload["execution_contract"]["source_bindings"][0]["required"] is True

    baseline_payload = reviewer.review_payload(
        inputs["public"], inputs["owner_answers"], {"notes": "Baseline owner-policy notes."},
        inputs["source_context"],
    )
    assert baseline_payload["execution_contract"]["source_bindings"] == []
    assert baseline_payload["execution_contract"]["numeric_bindings"] == []


@pytest.mark.parametrize("invalid", [None, 0, 1, "true"])
def test_source_required_flag_must_be_boolean(invalid):
    inputs = _inputs()
    inputs["artifact"]["card"]["sources"][0]["required"] = invalid
    with pytest.raises(ValueError, match="required must be boolean"):
        reviewer.review_payload(
            inputs["public"], inputs["owner_answers"], inputs["artifact"], inputs["source_context"]
        )


def test_reviewer_explains_global_source_gate_without_role_or_all_required_heuristics():
    instructions = reviewer.REVIEW_INSTRUCTIONS
    assert "global prerequisite for every" in instructions
    assert "forces insufficient_data" in instructions
    assert "Assess each required flag against the original owner brief, glossary and owner_answers" in instructions
    assert "but do not make every source optional" in instructions
    assert "Do not infer requiredness from source roles" in instructions
    assert "have no source bindings or required flags to demand" in instructions

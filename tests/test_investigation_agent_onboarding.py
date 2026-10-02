from copy import deepcopy

import pytest
from pydantic import ValidationError

from examples.investigation_agent.onboarding import DraftIntent, RouteIntent, draft_arguments
from signalweave.models import InsightCard, Outcome, SourceRef
from signalweave.numeric_conditions import NumericCondition


def source(key: str, *, required: bool, parameters: dict) -> SourceRef:
    return SourceRef(
        key=key,
        adapter="superset",
        resource=f"dashboard:{key}",
        label=f"{key} dashboard",
        parameters=parameters,
        required=required,
    )


def intent(**overrides):
    values = {
        "title": "Watch the arbitrary business signal",
        "what_to_watch": "The signal and its movement.",
        "why_watch": "Support a specific operating decision.",
        "decision_guidance": "Investigate material movement before notifying the owner.",
        "source_keys": ["primary"],
        "routes": [RouteIntent(destination_key="owner", outcome=Outcome.NOTIFY)],
    }
    values.update(overrides)
    return DraftIntent(**values)


def test_bridges_two_unrelated_approved_directories_without_invention():
    approved_sources = [
        source("primary", required=True, parameters={"metadata": {"code": "A-17"}}),
        source("optional", required=False, parameters={"chart_ids": ["never-selected"]}),
    ]
    approved_destinations = [{"key": "owner", "label": "Operations", "destination": "sink://ops"}]

    result = draft_arguments(intent(), approved_sources, approved_destinations)

    assert set(result) == {
        "title", "what_to_watch", "why_watch", "watch_for", "questions",
        "numeric_conditions",
        "evidence_requirements", "decision_guidance", "follow_up_guidance",
        "sources", "delivery_methods",
    }
    assert result["sources"][0]["parameters"] == {"metadata": {"code": "A-17"}}
    assert result["delivery_methods"] == [{
        "key": "owner", "outcome": "notify", "label": "Operations", "destination": "sink://ops",
    }]


def test_numeric_conditions_are_forwarded_without_becoming_action_policy():
    approved = [
        source("primary", required=True, parameters={}).model_copy(
            update={"required_comparison_keys": ["comparison-a"]}
        )
    ]
    numeric = NumericCondition(
        text="The approved metric falls by at least ten units",
        source_key="primary",
        comparison_key="comparison-a",
        measurement="delta",
        unit="number",
        threshold=10,
        comparator="<=",
    )
    result = draft_arguments(intent(numeric_conditions=[numeric], routes=[]), approved, [])
    assert result["numeric_conditions"] == [numeric.model_dump(mode="python")]
    assert not any(key in result for key in ("outcome", "action", "policy"))


def test_required_sources_are_forced_and_optional_sources_may_be_omitted():
    approved = [
        source("required", required=True, parameters={}),
        source("optional", required=False, parameters={}),
    ]
    with pytest.raises(ValueError, match="required approved source"):
        draft_arguments(intent(source_keys=[]), approved, [])
    result = draft_arguments(intent(source_keys=["required"], routes=[]), approved, [])
    assert [item["key"] for item in result["sources"]] == ["required"]


def test_source_parameters_are_deep_copied_and_input_is_not_mutated():
    parameters = {"metadata": {"code": ["original"]}}
    approved = [source("primary", required=True, parameters=parameters)]
    before = deepcopy(approved[0].model_dump())

    result = draft_arguments(intent(), approved, [{"key": "owner", "label": "Owner", "destination": "agent://owner"}])
    result["sources"][0]["parameters"]["metadata"]["code"].append("changed")

    assert approved[0].model_dump() == before
    assert parameters == {"metadata": {"code": ["original"]}}


@pytest.mark.parametrize(
    "bad_intent",
    [
        {"source_keys": ["missing"]},
        {"source_keys": ["primary", "primary"]},
    ],
)
def test_unknown_and_duplicate_source_selectors_are_rejected(bad_intent):
    values = intent().model_dump()
    values.update(bad_intent)
    with pytest.raises((ValueError, ValidationError)):
        draft_arguments(values, [source("primary", required=True, parameters={})], [])


def test_duplicate_approved_directory_identifiers_are_rejected():
    duplicate_source = source("primary", required=True, parameters={})
    with pytest.raises(ValueError, match="duplicate approved source key"):
        draft_arguments(intent(routes=[]), [duplicate_source, duplicate_source], [])
    with pytest.raises(ValueError, match="duplicate approved destination key"):
        draft_arguments(
            intent(),
            [source("primary", required=True, parameters={})],
            [
                {"key": "owner", "label": "Owner", "destination": "agent://owner"},
                {"key": "owner", "label": "Owner again", "destination": "agent://other"},
            ],
        )


def test_unknown_destination_and_duplicate_route_keys_are_rejected():
    approved = [{"key": "owner", "label": "Owner", "destination": "agent://owner"}]
    with pytest.raises(ValueError, match="unknown approved destination"):
        draft_arguments(
            intent(routes=[RouteIntent(destination_key="missing", outcome=Outcome.NOTIFY)]),
            [source("primary", required=True, parameters={})], approved,
        )
    routes = [
        RouteIntent(destination_key="owner", outcome=Outcome.NOTIFY),
        RouteIntent(destination_key="owner", outcome=Outcome.INVESTIGATE),
    ]
    with pytest.raises(ValueError, match="duplicate delivery method key"):
        draft_arguments(intent(routes=routes), [source("primary", required=True, parameters={})], approved)


def test_same_endpoint_can_have_two_outcomes_with_explicit_method_keys():
    approved = [
        {"key": "leadership", "label": "Leadership", "destination": "agent://shared"},
        {"key": "ops", "label": "Operations", "destination": "agent://shared"},
    ]
    routes = [
        RouteIntent(destination_key="leadership", outcome=Outcome.NOTIFY, method_key="shared-notify"),
        RouteIntent(destination_key="ops", outcome=Outcome.INVESTIGATE, method_key="shared-investigate"),
    ]
    result = draft_arguments(intent(routes=routes), [source("primary", required=True, parameters={})], approved)
    assert [route["key"] for route in result["delivery_methods"]] == [
        "shared-notify", "shared-investigate",
    ]


def test_route_cannot_supply_a_destination_or_control_field():
    values = intent().model_dump()
    values["routes"] = [{
        "destination_key": "owner", "outcome": "notify", "destination": "https://evil.invalid",
    }]
    with pytest.raises(ValidationError):
        draft_arguments(values, [source("primary", required=True, parameters={})], [])


def test_technical_fields_are_forbidden_and_not_output():
    values = intent().model_dump()
    values["confidence"] = 0.99
    with pytest.raises(ValidationError):
        DraftIntent.model_validate(values)
    result = draft_arguments(intent(routes=[]), [source("primary", required=True, parameters={})], [])
    assert not {"profile", "confidence", "retrieval", "investigation", "compiled", "approval"} & set(result)


def test_existing_insight_card_validates_generated_kwargs_and_one_based_requirements():
    result = draft_arguments(
        intent(
            watch_for=["A change is material."],
            questions=["Does the owner need to act?"],
            evidence_requirements={"question:1": False, "watch:1": True},
            routes=[],
        ),
        [source("primary", required=True, parameters={})],
        [],
    )
    card = InsightCard(id="temporary", **result)
    assert card.evidence_requirements == {"question:1": False, "watch:1": True}

    invalid = intent(evidence_requirements={"question:2": False}, routes=[]).model_dump()
    with pytest.raises(ValidationError):
        draft_arguments(invalid, [source("primary", required=True, parameters={})], [])

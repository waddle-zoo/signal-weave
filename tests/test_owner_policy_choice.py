"""Offline tests for policy-anchored outcome Choice wording."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
import typesafe_sdk

from signalweave.compiler import base_plan
from signalweave.models import DeliveryMethod, InsightCard, Observation, Outcome
from signalweave.numeric_conditions import NumericConditionResult
from signalweave.typesafe_adapter import JevJudger

POLICY = (
    "Apply these rules in order: if the primary sales source is unavailable, choose "
    "insufficient_data; otherwise, if revenue fell by more than 10% and no promotion "
    "is active, notify Leadership; if a promotion is active, ignore; otherwise investigate."
)
POLICY_INSTRUCTIONS = (
    "Which outcome does the owner's card.decision_guidance select for the supplied "
    "measurement window? Apply explicit ordered rules in their stated order, using "
    "the normalized evidence and source definitions. This is a policy recommendation, "
    "not an external action. A retrospective review or delivery-disabled execution does "
    "not change which outcome the policy selects. Diagnostic watch items are not extra "
    "trigger conditions. Do not invent a threshold, prerequisite, or causal explanation."
    " Use adapter-published owner_change_status or planned_change as authoritative "
    "source context when the card distinguishes planned from unplanned movement."
)
POLICY_CRITERION = (
    "The owner's applicable rule selects {key}. Follow the owner's thresholds, "
    "exceptions, and fallback exactly; a configured route is not a trigger. "
    "Select investigation for uncertainty only when the policy calls for it, "
    "not as a replacement for an explicit quiet or notification rule."
)
OUTCOMES = ["ignore", "investigate", "insufficient_data", "notify", "escalate"]


def _card(guidance: str) -> InsightCard:
    return InsightCard(
        id="revenue-policy",
        title="Monthly revenue review",
        what_to_watch="Revenue movement and promotion context",
        why_watch="Apply the owner's conditions to the monthly close.",
        watch_for=["Revenue fell beyond materiality", "A promotion is active"],
        questions=["Was the primary sales source complete?"],
        decision_guidance=guidance,
        action_confidence_threshold=0.73,
        delivery_methods=[
            DeliveryMethod(
                key="leadership",
                outcome=Outcome.NOTIFY,
                label="Leadership",
                destination="mock://leadership",
                instructions="Leadership review",
            ),
            DeliveryMethod(
                key="data-trust",
                outcome=Outcome.ESCALATE,
                label="Data Trust",
                destination="mock://data-trust",
                instructions="Data Trust review",
            ),
        ],
    )


def _dataset(card: InsightCard) -> tuple[dict, list[Observation]]:
    observation = Observation(
        source_key="sales",
        subject_id="monthly-revenue",
        subject_label="Monthly revenue",
        metric="revenue",
        unit="USD",
        current=880.0,
        baseline=1000.0,
        change_pct=-12.0,
        attributes={"promotion_active": False, "source_status": "complete"},
    )
    evidence = {
        "source_key": "sales",
        "subject_id": "monthly-revenue",
        "subject_label": "Monthly revenue",
        "statement": "Revenue decreased by 12% for the complete monthly close.",
        "values": {"current": 880.0, "baseline": 1000.0},
    }
    numeric_conditions = [
        {"key": "revenue_down_over_10pct", "status": "satisfied", "value": True},
        {"key": "promotion_active", "status": "not_satisfied", "value": False},
    ]
    state = {
        "card": card.model_dump(mode="json"),
        "sources": [{
            "key": "sales",
            "metadata": {"retained": "source metadata stays present"},
            "contract": {"grain": "month", "currency": "USD"},
        }],
        "evidence": [evidence],
        "analyses": [{"source_key": "sales", "delta": -120.0, "unit": "USD"}],
        "numeric_conditions": numeric_conditions,
        "source_errors": [{"source_key": "support", "blocking": False, "quality_status": "partial"}],
        "context": {"promotion_active": False, "close_status": "complete"},
    }
    return state, [observation]


@pytest.fixture
def capture_request(monkeypatch):
    calls = []

    class OfflineClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def system_one(self, *, state, questions):
            calls.append({"state": copy.deepcopy(state), "questions": copy.deepcopy(questions)})
            choices, nouls = {}, {}
            for key, question in questions.items():
                if key == "outcome":
                    criteria = question.criteria
                    choices[key] = SimpleNamespace(
                        choice="ignore",
                        probabilities={name: (0.9 if name == "ignore" else
                                              0.1 / (len(criteria) - 1)) for name in criteria},
                    )
                elif key.startswith("watch_"):
                    choices[key] = SimpleNamespace(
                        choice="present", probabilities={"present": 0.9, "absent": 0.05, "unknown": 0.05},
                    )
                elif key.startswith("question_"):
                    nouls[key] = SimpleNamespace(noul=0.95)
            return SimpleNamespace(
                choices=choices, nouls=nouls, scores={},
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", OfflineClient)

    async def capture(card: InsightCard, *, numeric_conditions=None, planned_change=None):
        state, observations = _dataset(card)
        if numeric_conditions is not None:
            state["numeric_conditions"] = copy.deepcopy(numeric_conditions)
        if planned_change is not None:
            state["sources"][0]["metadata"]["planned_change"] = planned_change
            state["sources"][0]["metadata"]["owner_change_status"] = (
                "planned" if planned_change else "unplanned"
            )
            observations[0].attributes["planned_change"] = planned_change
        original_state = copy.deepcopy(state)
        await JevJudger(api_key="offline-test", evidence_role_classification=False).judge(
            state, card, base_plan(card), observations,
        )
        assert state == original_state
        return calls[-1]

    return capture


@pytest.mark.parametrize("planned", [True, False])
async def test_guided_outcome_retains_planned_change_authority_in_both_states(capture_request, planned):
    guidance = (
        "Ignore a decline when the adapter identifies it as planned. Notify Leadership "
        "for an unplanned revenue decline over 10%; otherwise investigate."
    )
    call = await capture_request(_card(guidance), planned_change=planned)
    assert "owner_change_status or planned_change as authoritative" in (
        call["questions"]["outcome"].instructions
    )
    assert call["state"]["card"]["decision_guidance"] == guidance
    assert call["state"]["sources"][0]["metadata"]["planned_change"] is planned
    assert call["state"]["sources"][0]["metadata"]["owner_change_status"] == (
        "planned" if planned else "unplanned"
    )
    assert call["state"]["observations"][0]["attributes"]["planned_change"] is planned


def _question_payload(question):
    return {"instructions": question.instructions, "criteria": question.criteria}


async def test_guided_choice_preserves_policy_state_labels_and_planned_change_contract(capture_request):
    card = _card(POLICY)
    call = await capture_request(card)
    outcome = call["questions"]["outcome"]

    assert outcome.instructions == POLICY_INSTRUCTIONS
    assert outcome.criteria == {key: POLICY_CRITERION.format(key=key) for key in OUTCOMES}
    assert "not an external action" in outcome.instructions
    assert "Diagnostic watch items are not extra trigger conditions" in outcome.instructions
    serialized_request = json.dumps({
        "state": call["state"],
        "questions": {key: _question_payload(question)
                      for key, question in call["questions"].items()},
    })
    assert "expected_outcome" not in serialized_request
    assert "oracle" not in serialized_request.lower()

    request_state = call["state"]
    assert request_state["card"] == JevJudger._judgment_card_payload(card)
    assert request_state["card"]["decision_guidance"] == POLICY
    assert request_state["card"]["action_confidence_threshold"] == 0.73
    assert request_state["card"]["delivery_methods"] == card.execution_payload()["delivery_methods"]
    assert request_state["sources"][0]["metadata"] == {
        "retained": "source metadata stays present",
    }
    assert request_state["sources"][0]["contract"] == {"grain": "month", "currency": "USD"}
    assert request_state["observations"][0]["change_pct"] == -12.0
    assert request_state["observations"][0]["attributes"]["promotion_active"] is False
    assert request_state["evidence"][0]["values"] == {"current": 880.0, "baseline": 1000.0}
    assert request_state["analyses"] == [{"source_key": "sales", "delta": -120.0, "unit": "USD"}]
    assert request_state["numeric_conditions"] == [
        {"key": "revenue_down_over_10pct", "status": "satisfied", "value": True},
        {"key": "promotion_active", "status": "not_satisfied", "value": False},
    ]
    assert request_state["context"] == {"promotion_active": False, "close_status": "complete"}
    assert request_state["source_errors"] == [
        {"source_key": "support", "blocking": False, "quality_status": "partial"},
    ]


async def test_guided_choice_uses_compiled_numeric_conditions_as_facts(capture_request):
    card_payload = _card(POLICY).model_dump(mode="json")
    card_payload["sources"] = [{
        "key": "sales",
        "adapter": "fixture",
        "resource": "monthly-revenue",
        "label": "Monthly revenue",
        "required_comparison_keys": ["monthly-revenue"],
    }]
    card_payload["numeric_conditions"] = [
        {
            "text": "Revenue fell by more than 10%",
            "source_key": "sales",
            "comparison_key": "monthly-revenue",
            "measurement": "change_pct",
            "unit": "percent",
            "threshold": -10,
            "comparator": "<",
        },
        {
            "text": "Current revenue is below $900",
            "source_key": "sales",
            "comparison_key": "monthly-revenue",
            "measurement": "current",
            "unit": "USD",
            "threshold": 900,
            "comparator": "<",
        },
    ]
    card = InsightCard.model_validate(card_payload)
    compiled_conditions = [
        NumericConditionResult(
            condition_text="Revenue fell by more than 10%",
            source_key="sales",
            comparison_key="monthly-revenue",
            measurement="change_pct",
            comparator="<",
            threshold=-10,
            status="true",
            value=-12,
            unit="percent",
            expected_unit="percent",
        ).model_dump(mode="json"),
        NumericConditionResult(
            condition_text="Current revenue is below $900",
            source_key="sales",
            comparison_key="monthly-revenue",
            measurement="current",
            comparator="<",
            threshold=900,
            status="unknown",
            value=None,
            unit=None,
            expected_unit="USD",
            reason="comparison unavailable",
        ).model_dump(mode="json"),
    ]

    call = await capture_request(card, numeric_conditions=compiled_conditions)
    instructions = call["questions"]["outcome"].instructions

    assert instructions.startswith(POLICY_INSTRUCTIONS)
    assert "code-computed numeric_conditions" in instructions
    assert "status and value fields as facts" in instructions
    assert "full policy" in instructions
    assert "not standalone action rules" in instructions
    assert "Unknown means unresolved, not false" in instructions
    assert "Do not recalculate" in instructions
    assert "invent bindings" in instructions
    assert call["state"]["numeric_conditions"] == compiled_conditions


async def test_owner_guidance_changes_only_the_outcome_question(capture_request):
    guided = await capture_request(_card(POLICY))
    purpose_only = await capture_request(_card(""))

    assert guided["questions"].keys() == purpose_only["questions"].keys()
    assert [key for key in guided["questions"] if key != "outcome"] == [
        "watch_0", "watch_1", "question_0",
    ]
    for key in guided["questions"]:
        if key != "outcome":
            assert _question_payload(guided["questions"][key]) == _question_payload(
                purpose_only["questions"][key]
            )
    assert guided["questions"]["outcome"].criteria.keys() == purpose_only["questions"][
        "outcome"
    ].criteria.keys()


@pytest.mark.parametrize("guidance", ["", " \n\t "])
async def test_empty_guidance_keeps_legacy_question_and_outcomes(capture_request, guidance):
    call = await capture_request(_card(guidance))
    outcome = call["questions"]["outcome"]

    assert list(outcome.criteria) == OUTCOMES
    assert "Which single outcome best fits the current evidence" in outcome.instructions
    assert "Delivery is separately controlled by code" in outcome.instructions
    assert "Missing, untrusted, or ambiguous evidence prevents applying the owner's policy" in (
        outcome.criteria[Outcome.INSUFFICIENT_DATA.value]
    )
    assert "There must be enough trustworthy evidence" in outcome.criteria[Outcome.IGNORE.value]
    assert "missing evidence is not evidence for ignore" in outcome.criteria[Outcome.IGNORE.value]
    assert "warrants human or downstream investigation" in outcome.criteria[Outcome.INVESTIGATE.value]
    for key, route in ((Outcome.NOTIFY.value, "Leadership review"),
                       (Outcome.ESCALATE.value, "Data Trust review")):
        assert "decision_guidance" in outcome.criteria[key]
        assert "trigger conditions and exceptions" in outcome.criteria[key]
        assert route in outcome.criteria[key]

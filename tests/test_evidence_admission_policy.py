"""Test-first contract for reviewed evidence admission, independent of remedial prose.

These began as ordinary failing tests, not xfails. The frozen implementation
lacked evidence_requirements, gated completeness only with follow_up_guidance,
and trusted cached evidence slots. Source/health checks are positive controls.
All semantic outputs are deterministic test doubles; no provider is contacted.

Recorded baseline at frozen commit 8dde234: 53 failed, 16 passed. Failures cover
policy representation/validation, prose-dependent admission, cached-plan trust,
map persistence/approval binding, and MCP authoring exposure. Passing controls
cover existing source/comparison gates and question-change approval invalidation.
"""

import json

import pytest
import typesafe_sdk
from pydantic import ValidationError
from test_onboarding import make_server, tool
from test_source_selection_approval import (
    assert_rejected,
    reviewed_case,
    save_changed_card,
    stored,
)

from signalweave.compiler import base_plan
from signalweave.engine import InsightEngine
from signalweave.models import (
    ContextSnapshot,
    InsightCard,
    InsightResult,
    Outcome,
    ResourceSnapshot,
)
from signalweave.store import JsonInsightCardStore, SQLiteInsightCardStore

GUIDANCE = "After investigation, ask the owner for corrected or additional evidence."


@pytest.mark.parametrize("semantic,status,outcome", [
    ("unknown", "pending", "investigate"),
    ("not_supported", "conflicting", "investigate"),
    ("supported", "fulfilled", "notify"),
])
async def test_trusted_context_tag_does_not_bypass_question_evidence(semantic, status, outcome):
    context = ContextSnapshot(provider="approved-context", version="1", facts=[{
        "fact_id": "answer-context", "slot_key": "question:1", "subject_ref": "test|query:metric",
        "relation": "related_to", "statement": "The requested dimensional evidence is unresolved.",
    }])
    run = await InsightEngine(FixedJudger(question=semantic)).evaluate(
        make_card(), [snapshot()], context_override=context,
    )
    slot = next(s for s in run.result.evidence_plan.slots if s.key == "question:1")
    assert slot.status == status
    assert slot.evidence_fact_ids == ["answer-context"]
    assert run.result.outcome.value == outcome


@pytest.fixture(autouse=True)
def forbid_live_jev(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("This contract suite must never instantiate a live Jev client")

    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", unexpected_client)


def make_card(*, requirements=None, guidance=""):
    payload = {
        "id": "evidence-admission",
        "title": "Owner-defined metric",
        "what_to_watch": "Movement in the approved metric.",
        "why_watch": "Decide whether the operating owner needs to act.",
        "decision_guidance": "Notify on a decline of at least 10%; otherwise ignore.",
        "follow_up_guidance": guidance,
        "questions": ["When supported, provide an additional dimensional explanation."],
        "watch_for": ["The owner-requested corroborating condition is present."],
        "sources": [{
            "key": "metric", "adapter": "test", "resource": "query:metric",
            "label": "Approved metric", "required": True,
        }],
        "delivery_methods": [
            {"key": "business-owner", "outcome": "notify", "label": "Business owner",
             "destination": "slack://business-owner"},
            {"key": "data-owner", "outcome": "insufficient_data", "label": "Data owner",
             "destination": "slack://data-owner"},
        ],
    }
    if requirements is not None:
        payload["evidence_requirements"] = requirements
    return InsightCard.model_validate(payload)


def snapshot():
    return ResourceSnapshot.model_validate({
        "source_key": "metric", "adapter": "test", "resource": "query:metric",
        "title": "Approved metric",
        "observations": [{
            "source_key": "metric", "subject_id": "total", "metric": "approved_metric",
            "current": 80, "baseline": 100, "change_pct": -20,
        }],
        "evidence": [{
            "source_key": "metric", "statement": "The approved metric declined 20%.",
            "provenance": ["query:metric"],
        }],
    })


class FixedJudger:
    name = "offline-evidence-admission-double"

    def __init__(self, *, question="supported", watch="present", outcome=Outcome.NOTIFY):
        self.question = question
        self.watch = watch
        self.outcome = outcome
        self.calls = 0

    async def compile_plan(self, state, card):
        return {"capabilities": ["percent_change"], "baseline": card.comparison_windows[0]}

    async def judge(self, state, card, plan, observations):
        self.calls += 1
        return InsightResult(
            card_id=card.id, outcome=self.outcome, confidence=0.99,
            probabilities={self.outcome.value: 0.99},
            summary="Fixed semantic outcome over comparable evidence.",
            rationale="Admission must be decided by reviewed requirements, not remedial prose.",
            observations=observations, evidence=state["evidence"],
            source_keys=[source.key for source in card.sources], evaluator=self.name,
            question_results=[{
                "key": f"question_{i}", "question": question, "status": self.question,
                "probability": {"supported": 0.99, "unknown": 0.5, "not_supported": 0.01}[self.question],
            } for i, question in enumerate(card.questions)],
            watch_results=[{
                "key": f"watch_{i}", "watch_for": watch, "status": self.watch,
                "probability": {"present": 0.99, "unknown": 0.5, "absent": 0.01}[self.watch],
            } for i, watch in enumerate(card.watch_for)],
        )


def test_default_policy_is_explicit_and_keeps_unspecified_slots_required():
    card = make_card()
    assert card.model_dump().get("evidence_requirements") == {}
    assert {slot.key: slot.required for slot in base_plan(card).evidence_slots} == {
        "source:metric": True, "question:1": True, "watch:1": True,
    }


@pytest.mark.parametrize("requirements", [
    {"question:1": False}, {"watch:1": False},
    {"question:1": False, "watch:1": True},
])
def test_only_reviewed_overrides_change_compiled_requirements(requirements):
    card = make_card(requirements=requirements)
    expected = {"source:metric": True, "question:1": True, "watch:1": True}
    expected.update(requirements)
    assert {slot.key: slot.required for slot in base_plan(card).evidence_slots} == expected
    assert card.execution_payload()["evidence_requirements"] == requirements


@pytest.mark.parametrize("optional", [False, True], ids=["required", "optional"])
async def test_follow_up_prose_cannot_change_admission(optional):
    outcomes = []
    for guidance in ("", GUIDANCE):
        card = make_card(requirements={"question:1": not optional}, guidance=guidance)
        run = await InsightEngine(FixedJudger(question="unknown")).evaluate(card, [snapshot()])
        outcomes.append(run.result.outcome)
    expected = Outcome.NOTIFY if optional else Outcome.INVESTIGATE
    assert outcomes == [expected, expected]


@pytest.mark.parametrize("slot_key", ["question:1", "watch:1"])
@pytest.mark.parametrize("guidance", ["", GUIDANCE], ids=["no-guidance", "remedial-guidance"])
async def test_explicit_optional_unknown_stays_visible_without_blocking(slot_key, guidance):
    card = make_card(requirements={slot_key: False}, guidance=guidance)
    judger = FixedJudger(**{"question" if slot_key.startswith("question:") else "watch": "unknown"})
    result = (await InsightEngine(judger).evaluate(card, [snapshot()])).result

    assert result.outcome == Outcome.NOTIFY
    assert [method.key for method in result.delivery_methods] == ["business-owner"]
    assert result.evidence_plan.status == "complete"
    assert slot_key in result.evidence_plan.missing_slot_keys
    slot = next(slot for slot in result.evidence_plan.slots if slot.key == slot_key)
    assert slot.required is False
    assert slot.status == "pending"
    item = result.question_results[0] if slot_key.startswith("question:") else result.watch_results[0]
    assert item.status.value == "unknown"
    assert result.workflow.evidence_plan == result.evidence_plan


@pytest.mark.parametrize("outcome", [Outcome.NOTIFY, Outcome.ESCALATE])
@pytest.mark.parametrize("slot_key", ["question:1", "watch:1"])
@pytest.mark.parametrize("guidance", ["", GUIDANCE], ids=["no-guidance", "remedial-guidance"])
async def test_unspecified_required_unknown_blocks_automatic_routes(outcome, slot_key, guidance):
    card = make_card(guidance=guidance)
    if outcome == Outcome.ESCALATE:
        card.delivery_methods[0].outcome = outcome
    judger = FixedJudger(
        outcome=outcome,
        **{"question" if slot_key.startswith("question:") else "watch": "unknown"},
    )
    result = (await InsightEngine(judger).evaluate(card, [snapshot()])).result

    assert result.outcome == Outcome.INVESTIGATE
    assert result.delivery_methods == []
    assert result.probabilities[outcome.value] == 0.99
    assert result.evidence_plan.status == "incomplete"
    assert slot_key in result.evidence_plan.missing_slot_keys


async def test_one_optional_item_does_not_waive_another_required_item():
    card = make_card(requirements={"question:1": False})
    result = (await InsightEngine(FixedJudger(question="unknown", watch="unknown"))
              .evaluate(card, [snapshot()])).result
    assert result.outcome == Outcome.INVESTIGATE
    assert result.delivery_methods == []
    assert set(result.evidence_plan.missing_slot_keys) == {"question:1", "watch:1"}
    assert {slot.key: slot.required for slot in result.evidence_plan.slots} == {
        "source:metric": True, "question:1": False, "watch:1": True,
    }


@pytest.mark.parametrize("guidance", ["", GUIDANCE])
async def test_supported_required_question_and_absent_watch_are_complete(guidance):
    result = (await InsightEngine(FixedJudger(watch="absent"))
              .evaluate(make_card(guidance=guidance), [snapshot()])).result
    assert result.outcome == Outcome.NOTIFY
    assert result.evidence_plan.status == "complete"
    assert result.watch_results[0].status.value == "absent"


@pytest.mark.parametrize("defect", ["source-error", "missing-snapshot", "missing-comparison"])
@pytest.mark.parametrize("guidance", ["", GUIDANCE])
async def test_optional_semantic_slots_cannot_waive_required_source_or_comparison(defect, guidance):
    card = make_card(requirements={"question:1": False, "watch:1": False}, guidance=guidance)
    resource = snapshot()
    resources = [resource]
    if defect == "source-error":
        resource.error = "Required source unavailable."
    elif defect == "missing-snapshot":
        resources = []
    else:
        card.sources[0].required_comparison_keys = ["owner-required-comparison"]
    result = (await InsightEngine(FixedJudger()).evaluate(card, resources)).result
    assert result.outcome == Outcome.INSUFFICIENT_DATA
    assert [method.key for method in result.delivery_methods] == ["data-owner"]
    source_slot = next(slot for slot in result.evidence_plan.slots if slot.key == "source:metric")
    assert source_slot.required is True
    assert source_slot.status == "unavailable"
    assert result.evidence_plan.status == "blocked"


@pytest.mark.parametrize("key", [
    "source:metric", "comparison:owner-required-comparison", "question:0", "watch:0",
    "question:2", "watch:2", "question:-1", "watch:01", "question_0",
    "Question:1", "question:1 ", "", "question:1:extra",
])
def test_requirement_keys_must_exactly_identify_existing_semantic_slots(key):
    with pytest.raises(ValidationError):
        make_card(requirements={key: False})


@pytest.mark.parametrize("value", ["false", "true", 0, 1, 0.0, 1.0, None, [], {}])
def test_requirement_values_are_strict_booleans(value):
    with pytest.raises(ValidationError):
        make_card(requirements={"question:1": value})


@pytest.mark.parametrize("mutation", ["remove-question", "remove-watch", "remove-source",
                                      "empty-plan", "waive-question", "waive-source",
                                      "forge-fulfilled-question"])
async def test_cached_slot_tampering_is_rebuilt_from_current_card(mutation):
    card = make_card(guidance=GUIDANCE)
    plan = base_plan(card)
    if mutation.startswith("remove-"):
        key = {"remove-question": "question:1", "remove-watch": "watch:1",
               "remove-source": "source:metric"}[mutation]
        plan.evidence_slots = [slot for slot in plan.evidence_slots if slot.key != key]
    elif mutation == "empty-plan":
        plan.evidence_slots = []
    else:
        key = "source:metric" if mutation == "waive-source" else "question:1"
        slot = next(slot for slot in plan.evidence_slots if slot.key == key)
        if mutation == "forge-fulfilled-question":
            slot.status = "fulfilled"
            slot.evidence_fact_ids = ["invented-cached-fact"]
        else:
            slot.required = False
    # Deliberately bypass construction-time validation to exercise execution's
    # cache boundary. An old/imported plan must not supply admission authority.
    card.compiled_plan = plan
    judger = FixedJudger(question="unknown", watch="unknown")
    run = await InsightEngine(judger).evaluate(card, [snapshot()])

    assert run.result.outcome == Outcome.INVESTIGATE
    assert run.result.delivery_methods == []
    assert {slot.key: slot.required for slot in run.plan.evidence_slots} == {
        "source:metric": True, "question:1": True, "watch:1": True,
    }
    slots = {slot.key: slot for slot in run.result.evidence_plan.slots}
    assert slots["question:1"].status == slots["watch:1"].status == "pending"
    assert slots["question:1"].evidence_fact_ids == []
    assert set(run.result.evidence_plan.missing_slot_keys) == {"question:1", "watch:1"}
    assert judger.calls == 1


async def test_cached_required_flag_cannot_override_reviewed_optional_policy():
    card = make_card(requirements={"question:1": False}, guidance=GUIDANCE)
    plan = base_plan(card)
    next(slot for slot in plan.evidence_slots if slot.key == "question:1").required = True
    card.compiled_plan = plan
    run = await InsightEngine(FixedJudger(question="unknown")).evaluate(card, [snapshot()])
    assert run.result.outcome == Outcome.NOTIFY
    assert run.result.evidence_plan.status == "complete"
    assert "question:1" in run.result.evidence_plan.missing_slot_keys
    assert next(slot for slot in run.plan.evidence_slots if slot.key == "question:1").required is False


async def test_same_version_question_edit_cannot_reuse_old_cached_slot_text():
    card = make_card(guidance=GUIDANCE)
    card.compiled_plan = base_plan(card)
    card.questions = ["Is the newly reviewed comparison population established?"]
    card.watch_for = ["Is the newly reviewed operating condition present?"]
    card.what_to_watch = "Newly reviewed operating scope"
    run = await InsightEngine(FixedJudger(question="unknown")).evaluate(card, [snapshot()])
    slot = next(slot for slot in run.plan.evidence_slots if slot.key == "question:1")
    assert slot.question == card.questions[0]
    assert slot.required is True
    assert run.plan.questions == card.questions
    assert run.plan.watch_for == card.watch_for
    assert run.plan.card_scope == base_plan(card).card_scope
    assert run.result.outcome == Outcome.INVESTIGATE


@pytest.mark.parametrize("store_class,filename", [
    (JsonInsightCardStore, "cards.json"), (SQLiteInsightCardStore, "cards.db"),
], ids=["json", "sqlite"])
async def test_reviewed_map_survives_store_restart_and_controls_admission(tmp_path, store_class, filename):
    requirements = {"question:1": False, "watch:1": True}
    card = make_card(requirements=requirements, guidance=GUIDANCE)
    card.compiled_plan = base_plan(card)
    path = tmp_path / filename
    store_class(path).save_card(card)
    restored = store_class(path).get_card(card.id)
    assert restored.model_dump(mode="json").get("evidence_requirements") == requirements
    assert restored.execution_payload()["evidence_requirements"] == requirements
    run = await InsightEngine(FixedJudger(question="unknown")).evaluate(restored, [snapshot()])
    assert run.result.outcome == Outcome.NOTIFY
    assert "question:1" in run.result.evidence_plan.missing_slot_keys


@pytest.mark.parametrize("sqlite", [False, True], ids=["json", "sqlite"])
@pytest.mark.parametrize("change", ["requirements", "question-text", "question-order"])
async def test_source_confirmation_rejects_changed_requirements_or_question_identity(tmp_path, sqlite, change):
    server, card_id, review, _, _ = await reviewed_case(
        tmp_path, sqlite=sqlite,
        questions=["Is the comparison valid?", "Is additional context available?"],
    )
    old_fingerprint = review["source_selection_fingerprint"]
    if change == "requirements":
        updates = {"evidence_requirements": {"question:1": False}}
    elif change == "question-text":
        updates = {"questions": ["Is the population complete?", "Is additional context available?"]}
    else:
        updates = {"questions": list(reversed(stored(server, card_id)["questions"]))}
    # Same-version mutation is intentional: the fingerprint must bind policy,
    # not merely rely on a caller remembering to bump its version.
    save_changed_card(server, card_id, **updates)
    await assert_rejected(server, card_id, old_fingerprint, match="stale or missing")


@pytest.mark.parametrize("name", ["draft_insight_card", "propose_insight_card", "onboard_insight_card"])
async def test_mcp_json_authoring_preserves_reviewed_map_and_compiled_flags(tmp_path, name):
    server = make_server(tmp_path)
    spec = next(spec for spec in await server.list_tools() if spec.name == name)
    assert "evidence_requirements" in spec.inputSchema["properties"]
    requirements = {"question:1": False, "watch:1": True}
    args = {
        "title": "Reviewed optional detail", "what_to_watch": "Checkout conversion",
        "why_watch": "Decide whether Growth needs to respond.",
        "questions": ["When supported, provide extra diagnostic detail."],
        "watch_for": ["Conversion declines materially."],
        "decision_guidance": "Notify on a material decline; extra diagnostic detail is optional.",
        "evidence_requirements": requirements,
    }
    if name == "draft_insight_card":
        args["sources"] = [{"key": "growth", "adapter": "superset", "resource": "dashboard:7", "label": "Growth"}]
    else:
        args["selected_sources"] = [{"ref": "superset|dashboard:7"}]
    response = await server.call_tool(name, args)
    payload = response[1] if isinstance(response, tuple) else json.loads(
        next(item.text for item in response if getattr(item, "type", None) == "text")
    )
    payload = payload.get("proposal", payload)
    assert payload["card"]["evidence_requirements"] == requirements
    slots = {slot["key"]: slot for slot in payload["plan"]["evidence_slots"]}
    assert slots["question:1"]["required"] is False
    assert slots["watch:1"]["required"] is True
    card_id = payload["card"]["id"]
    assert tool(server, "get_insight_card")(card_id)["evidence_requirements"] == requirements
    reviewed = await tool(server, "review_insight_card")(card_id)
    assert reviewed["card"]["evidence_requirements"] == requirements
    assert reviewed["review"]["source_selection_fingerprint"]
    assert reviewed["review"]["evidence_requirements"] == [
        {"key": "question:1", "question": args["questions"][0], "required": False},
        {"key": "watch:1", "question": args["watch_for"][0], "required": True},
    ]


@pytest.mark.parametrize("value", ["false", 0, 1])
async def test_mcp_rejects_coerced_advisory_flags(tmp_path, value):
    server = make_server(tmp_path)
    with pytest.raises(Exception, match="valid boolean"):
        await server.call_tool("draft_insight_card", {
            "title": "Do not coerce policy", "what_to_watch": "Change", "why_watch": "Owner decision",
            "sources": [{"key": "metric", "adapter": "superset", "resource": "dashboard:7", "label": "Metric"}],
            "questions": ["Is the population comparable?"],
            "evidence_requirements": {"question:1": value},
        })

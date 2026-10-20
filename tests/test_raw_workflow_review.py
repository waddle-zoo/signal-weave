"""Offline contract tests for the one-shot raw workflow semantic reviewer."""

import inspect

import pytest
from jsonschema import Draft202012Validator, ValidationError

from evaluations.raw_workflow_review import REVIEW_INSTRUCTIONS, WorkflowReviewSession


def make_session():
    declarations = {"metric": "Use net sales; compare complete weeks."}
    notes = ["Quiet periods produce no alert."]
    card = {"sources": ["sales.weekly"], "follow_up_guidance": "Use authorized BI tools."}
    excerpts = [{"source": "sales.weekly", "text": "Current 12; prior 10."}]
    session = WorkflowReviewSession(
        declarations, "Explain the weekly change.", notes, card, excerpts
    )
    return session, declarations, notes, card, excerpts


def review(ready=True, issues=None, message="The proposal is ready for one shadow report."):
    return {
        "ready_for_shadow": ready,
        "issues": [] if issues is None else issues,
        "owner_message": message,
    }


async def test_exposes_one_schema_valid_tool_and_review_phase_only():
    session, *_ = make_session()
    tools = await session.specs()
    assert len(tools) == 1
    assert tools[0]["name"] == "record_review"
    Draft202012Validator.check_schema(tools[0]["parameters"])
    assert session.phase == "review"
    assert session.treatment is False
    assert session.setup_complete is False
    assert not hasattr(session, "approve_insight_card")
    assert "not card approval" in REVIEW_INSTRUCTIONS


def test_constructor_and_material_access_copy_all_five_inputs():
    assert list(inspect.signature(WorkflowReviewSession).parameters) == [
        "owner_declarations", "original_brief", "saved_arm_notes", "saved_card", "source_excerpts",
    ]
    session, declarations, notes, card, excerpts = make_session()
    declarations["metric"] = "changed"
    notes.append("changed")
    card["sources"].clear()
    excerpts[0]["text"] = "changed"
    expected = {
        "owner_declarations": {"metric": "Use net sales; compare complete weeks."},
        "original_brief": "Explain the weekly change.",
        "saved_arm_notes": ["Quiet periods produce no alert."],
        "saved_card": {"sources": ["sales.weekly"], "follow_up_guidance": "Use authorized BI tools."},
        "source_excerpts": [{"source": "sales.weekly", "text": "Current 12; prior 10."}],
    }
    assert session.review_materials == expected
    exposed = session.review_materials
    exposed["saved_card"]["sources"].clear()
    assert session.review_materials == expected


async def test_records_one_review_and_returns_isolated_submission():
    session, *_ = make_session()
    arguments = review(False, ["The saved card omits the declared quiet behavior."], "Please fix the card.")
    result = await session.call("record_review", arguments)
    assert result == {"recorded": True, "ready_for_shadow": False}
    arguments["issues"].append("mutated")
    submitted = session.submission
    assert submitted["issues"] == ["The saved card omits the declared quiet behavior."]
    submitted["issues"].clear()
    assert session.submission["issues"] == ["The saved card omits the declared quiet behavior."]
    with pytest.raises(ValueError, match="already submitted"):
        await session.call("record_review", review())


@pytest.mark.parametrize("arguments", [
    review(1),
    review("true"),
    review(issues=["  \t"]),
    review(message="  "),
    {**review(), "extra": "field"},
    {key: value for key, value in review().items() if key != "owner_message"},
])
async def test_invalid_payloads_fail_without_recording(arguments):
    session, *_ = make_session()
    with pytest.raises(ValidationError):
        await session.call("record_review", arguments)
    assert session.submission is None


async def test_only_record_review_is_callable_and_has_no_action_capability():
    session, *_ = make_session()
    with pytest.raises(ValueError, match="only record_review"):
        await session.call("approve_insight_card", {})
    assert session.submission is None
    assert [tool["name"] for tool in await session.specs()] == ["record_review"]

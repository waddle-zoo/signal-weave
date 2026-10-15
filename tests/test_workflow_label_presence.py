"""Acceptance label-presence boundaries through the in-process MCP server."""

import copy

import pytest
from test_mcp_acceptance import AcceptanceDouble, setup, tool

from signalweave.models import Outcome


class CountingJevDouble(AcceptanceDouble):
    def __init__(self):
        self.judgments = 0

    async def judge(self, state, card, plan, observations):
        self.judgments += 1
        return await super().judge(state, card, plan, observations)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        "expected_delivery_method_keys",
        "expected_delivery_destinations",
        "required_evidence_source_keys",
        "expected_retrieval_refs",
    ],
)
async def test_omitted_acceptance_label_is_blocked_before_jev(tmp_path, missing):
    judger = CountingJevDouble()
    server, card_id, cases = await setup(tmp_path)
    server._test_runtime.engine.judger = judger
    case = copy.deepcopy(cases[0])
    case.pop(missing)

    report = await tool(server, "evaluate_card_workflow")(
        card_id,
        [case],
        acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
    )

    assert report["acceptance_passed"] is False
    if missing in {"expected_delivery_method_keys", "expected_delivery_destinations"}:
        assert any(
            "explicit delivery keys and destinations" in blocker
            for blocker in report["preflight_blockers"]
        )
    else:
        assert any(missing in blocker for blocker in report["preflight_blockers"])
    assert judger.judgments == 0


@pytest.mark.asyncio
async def test_explicit_known_labels_reach_current_acceptance_path(tmp_path):
    judger = CountingJevDouble()
    server, card_id, cases = await setup(tmp_path)
    server._test_runtime.engine.judger = judger
    report = await tool(server, "evaluate_card_workflow")(
        card_id,
        cases,
        acceptance_outcomes=[Outcome.NOTIFY, Outcome.IGNORE, Outcome.INSUFFICIENT_DATA],
    )

    assert report["acceptance_passed"] is True
    assert judger.judgments == len(cases)


@pytest.mark.asyncio
async def test_explicit_empty_retrieval_label_is_not_inferred(tmp_path):
    judger = CountingJevDouble()
    server, card_id, cases = await setup(tmp_path)
    server._test_runtime.engine.judger = judger
    case = copy.deepcopy(cases[0])
    case["expected_retrieval_refs"] = []

    report = await tool(server, "evaluate_card_workflow")(
        card_id, [case], acceptance_outcomes=[Outcome.IGNORE]
    )

    assert report["acceptance_passed"] is False
    assert report["preflight_blockers"] == []
    assert report["cases"][0]["unexpected_retrieval_refs"]
    assert judger.judgments == 1


@pytest.mark.asyncio
async def test_omitted_acceptance_label_remains_compatible_without_acceptance(tmp_path):
    judger = CountingJevDouble()
    server, card_id, cases = await setup(tmp_path)
    server._test_runtime.engine.judger = judger
    case = copy.deepcopy(cases[0])
    case.pop("expected_retrieval_refs")

    report = await tool(server, "evaluate_card_workflow")(card_id, [case])

    assert report["acceptance_passed"] is None
    assert report["preflight_blockers"] == []
    assert judger.judgments == 1

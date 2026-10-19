"""The simulated people move a whole journey; they never supply its analysis."""
import json
from unittest.mock import AsyncMock, Mock

import pytest
from mcp import types

from evaluations import enterprise_full_journey as trial


@pytest.fixture
def world(tmp_path):
    for path in (tmp_path/"baseline", tmp_path/"baseline/workspace"):
        path.mkdir(mode=0o700)
    for i in range(3):
        (tmp_path/f"snapshot-{i}.sqlite3").write_bytes(f"source-state-{i}".encode())
    (tmp_path/"baseline/active.sqlite3").write_bytes(b"source-state-0")
    source = Mock(instructions="Company source only")
    source.list_tools = AsyncMock(return_value=[types.Tool(name=n, inputSchema={"type": "object"})
        for n in ("list_assets", "inspect_asset", "query_readonly", "export_query")])
    source.call_tool = AsyncMock(return_value=([], {"raw": "source result"}))
    return trial.EnterpriseWorld(source, tmp_path, "baseline")


async def test_owner_has_policy_not_measurement_answers(world):
    _, reply = await world.call_tool("talk_to_owner", {"question": "What do we mean by service performance?"})
    assert reply["known"] and not reply["consent"]
    assert reply["answer"] == trial.OWNER
    assert not any(str(v) in reply["answer"] for v in (2772, 3420, 2550, 89.47, 81.05))
    assert world.messages == [] and not world.confirmed
    world.source.call_tool.assert_not_awaited()


async def test_whole_journey_delivers_three_observations_and_retains_actual_feedback(world):
    with pytest.raises(ValueError, match="confirmation"):
        await world.call_tool("send_message", {"to": "dispatch", "body": "Premature", "evidence_refs": []})
    await world.call_tool("confirm_workflow", {"summary": "Owner-facing plan and exact population/rule."})
    for day, cutoff in enumerate(trial.company.CUTOFFS):
        with pytest.raises(ValueError, match="actual useful weekly update"):
            await world.call_tool("finish_day", {})
        path = world.workspace/"evidence.csv"
        path.write_text(f"actual,current,source\n{day},{cutoff},captured\n")
        expected = trial.first._sha(path)
        _, sent = await world.call_tool("send_message", {"to": "dispatch", "body": f"Actual update {day}", "evidence_refs": ["evidence.csv"]})
        assert sent["delivered"]
        message = world.messages[-1]
        assert message["body"] == f"Actual update {day}" and message["source_cutoff"] == cutoff
        attached = world.root/message["attachments"][0]["path"]
        assert trial.first._sha(attached) == expected
        _, feedback = await world.call_tool("read_inbox", {})
        assert feedback["replies"][0]["reply_to"] == sent["message_id"]
        _, next_request = await world.call_tool("finish_day", {})
        if day < 2:
            assert next_request["source_cutoff"] == trial.company.CUTOFFS[day+1]
            assert (world.root/"baseline/active.sqlite3").read_bytes() == f"source-state-{day+1}".encode()
        else:
            assert next_request["engagement_complete"] and world.done
    saved = json.loads((world.root/"world-baseline.json").read_text())
    assert saved["complete"] and len(saved["messages"]) == len(saved["feedback_reads"]) == 3
    with pytest.raises(ValueError, match="complete"):
        await world.call_tool("finish_day", {})


async def test_messages_cannot_copy_private_files_or_invent_external_recipients(world):
    world.confirmed = True
    private = world.root/"private-key"
    private.write_text("not source evidence")
    with pytest.raises(ValueError, match="local company recipients"):
        await world.call_tool("send_message", {"to": "external", "body": "Hello", "evidence_refs": []})
    await world.call_tool("send_message", {"to": "dispatch", "body": "A supported partial finding", "evidence_refs": [str(private), "https://example.com/unverified"]})
    assert world.messages[-1]["attachments"] == []


async def test_confirmation_shows_actual_card_and_does_not_approve_it(world):
    native = Mock()
    native.call_tool = AsyncMock(return_value=([], {"card": {"id": "actual", "version": 3, "status": "draft"}}))
    world.native = native
    with pytest.raises(ValueError, match="saved card"):
        await world.call_tool("confirm_workflow", {"summary": "Our plan"})
    _, reply = await world.call_tool("confirm_workflow", {"summary": "Our plan", "card_id": "actual"})
    native.call_tool.assert_awaited_once_with("get_insight_card", {"card_id": "actual"})
    assert reply["saved_card"]["card"]["status"] == "draft"
    assert world.confirmed


async def test_source_tools_remain_available_and_provider_has_no_model_oracle(world):
    assert {t.name for t in await world.list_tools()} == trial.TOOLS
    _, result = await world.call_tool("query_readonly", {"sql": "SELECT available FROM source"})
    assert result == {"raw": "source result"}
    world.source.call_tool.assert_awaited_once_with("query_readonly", {"sql": "SELECT available FROM source"})
    assert not {"calculate_correct_answer", "expected_outcome", "reference"} & trial.TOOLS


def test_equal_opening_request_and_no_future_answers():
    b, t = [trial.task(a) for a in trial.ORDER]
    assert b["prompt"] == t["prompt"] and t["instructions"].startswith(b["instructions"])
    for future in trial.company.CUTOFFS[1:]:
        assert future not in json.dumps((b, t))
    for hidden in ("snapshot-", "independent-review", "comparison_valid=0", "2772", "3420"):
        assert hidden not in json.dumps((b, t))

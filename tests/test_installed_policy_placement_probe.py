import copy
import json

import pytest

from evaluations.installed_policy_placement_probe import prepare, run


def trace(tmp_path):
    card = {"id": "card", "version": 4, "decision_guidance": "Owner rules",
            "watch_for": ["Otherwise stay quiet"], "action_confidence_threshold": 0.7,
            "compiled_plan": {"card_version": 4}}
    cases = [{"id": "historical", "expected_outcome": "ignore", "resources": []}]
    path = tmp_path / "trace.jsonl"
    events = [
        {"kind": "tool.result", "name": "get_insight_card", "result": card},
        {"kind": "tool.result", "name": "evaluate_card_workflow",
         "arguments": {"card_id": "card", "cases": cases}, "result": {"cases": [{"case_id": "historical"}]}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in events))
    return path, card, cases


def test_only_existing_prose_placement_and_version_change(tmp_path):
    path, expected, cases = trace(tmp_path)
    original, candidate, prepared = prepare(path)
    assert original == expected and prepared == cases
    restored = copy.deepcopy(candidate)
    restored["version"] -= 1
    restored["compiled_plan"]["card_version"] -= 1
    restored["decision_guidance"] = original["decision_guidance"]
    assert restored == original
    assert candidate["decision_guidance"] == "Owner rules\nOtherwise stay quiet"
    assert candidate["action_confidence_threshold"] == 0.7


async def test_dry_run_never_instantiates_live_client(tmp_path, monkeypatch):
    import evaluations.installed_policy_placement_probe as probe

    def forbidden(*args, **kwargs):
        raise AssertionError("No live inference for offline freeze")
    monkeypatch.setattr(probe, "MeasuredJev", forbidden)
    path, _, _ = trace(tmp_path)
    result = await run(path, tmp_path / "frozen", None)
    assert result["attempt_cap"] == 2 and result["live"] is False
    with pytest.raises(FileExistsError):
        await run(path, tmp_path / "frozen", None)

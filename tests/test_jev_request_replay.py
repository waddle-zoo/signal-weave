import copy
import json
from types import SimpleNamespace

import pytest

from evaluations import jev_request_replay as replay
from evaluations.jev_request_replay import prepare


def test_replay_preserves_original_and_zero_and_questions():
    request = {"state": {"card": {"rule": "unchanged"}, "values": {"count": 0}},
               "questions": {"outcome": {"type": "choice"}, "watch": {"type": "choice"}}}
    saved = copy.deepcopy(request)
    state, questions = prepare(request, {"name": "original"})
    assert state["values"]["count"] == 0
    assert questions == request["questions"]
    changed, isolated = prepare(request, {"name": "missing", "question": "watch", "edits": [
        {"op": "remove", "path": ["values", "count"]}]})
    assert changed["values"] == {}
    assert set(isolated) == {"watch"}
    assert request == saved


@pytest.mark.parametrize("root", ["card", "insight_card", "insight_plan"])
def test_cannot_rewrite_policy(root):
    with pytest.raises(ValueError, match="policy"):
        prepare({"state": {root: {}}, "questions": {}}, {
            "edits": [{"op": "add", "path": [root, "rule"], "value": "pass"}]})


def test_replacement_and_add_preconditions():
    request = {"state": {"value": 0}, "questions": {}}
    with pytest.raises(ValueError, match="precondition"):
        prepare(request, {"edits": [{"op": "replace", "path": ["value"],
                                    "old": 1, "value": 2}]})
    with pytest.raises(ValueError, match="overwrite"):
        prepare(request, {"edits": [{"op": "add", "path": ["value"], "value": 2}]})


@pytest.mark.parametrize("failure", [False, True])
async def test_live_output_is_private_redacted_and_failure_status_retained(tmp_path, monkeypatch, failure):
    secret = "synthetic-credential-canary"
    trace = tmp_path / "input.jsonl"
    trace.write_text(json.dumps({"kind": "api.request", "provider": "jev", "request_id": 1,
                                "episode": "test", "model": "jev-latest", "state": {},
                                "questions": {}}) + "\n")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"seed": 1, "repetitions": 1, "note": secret,
                               "cases": [{"request_id": 1, "variants": [{"name": "original"}]}]}))
    class Unavailable(Exception):
        status_code = 429

    class FakeJev:
        def __init__(self, key, budget, audit):
            self.budget = budget

        async def _system_one_with_retry(self, **kwargs):
            self.budget.claim()
            if failure:
                raise Unavailable(secret)
            return {"synthetic_response": secret}

    monkeypatch.setattr(replay, "MeasuredJev", FakeJev)
    monkeypatch.setattr(replay, "load_api_key", lambda path: secret)
    args = SimpleNamespace(plan=plan, trace=trace, output=tmp_path / "private-output",
                           live=True, synthetic_input=True, jev_key_file=tmp_path / "key")
    await replay.run(args)
    assert args.output.stat().st_mode & 0o077 == 0
    assert secret not in (args.output / "config.json").read_text()
    assert secret not in (args.output / "results.json").read_text()
    result = json.loads((args.output / "results.json").read_text())
    assert result["attempts"] == 1 and result["complete"]
    assert result["rows"][0]["status"] == ("failed" if failure else "complete")
    if failure:
        assert result["rows"][0]["http_status"] == 429
        assert result["rows"][0]["error_type"] == "Unavailable"

import hashlib
import json
from copy import deepcopy

import pytest

from evaluations.policy_input_diagnostic import encoded, variant


def test_plan_variant_removes_only_execution_bookkeeping():
    source = {"model": "jev-latest", "state": {"card": {"decision_guidance": "owner policy"},
        "evidence": [{"value": 7}], "insight_plan": {"evidence_slots": [
            {"status": "pending", "evidence_fact_ids": [], "evidence_source_keys": [],
             "key": "watch:1", "required": False, "role": "watch", "source_keys": ["a"]}]}},
        "questions": {"outcome": {"criteria": {"ignore": "policy branch"}}}}
    before = deepcopy(source)
    actual = variant(source, {"remove_plan_slot_fields": ["status", "evidence_fact_ids", "evidence_source_keys"]})
    assert source == before
    expected = deepcopy(source)
    expected["state"]["insight_plan"]["evidence_slots"][0] = {
        "key": "watch:1", "required": False, "role": "watch", "source_keys": ["a"]}
    assert actual == expected
    with pytest.raises(KeyError):
        variant(actual, {"remove_plan_slot_fields": ["status"]})


def test_policy_variant_changes_only_the_declared_suffix_and_canonical_json_is_stable():
    source = {"questions": {"outcome": {}}, "state": {"card": {"decision_guidance": "owner policy"}}, "model": "jev-latest"}
    changed = variant(source, {"append_policy": "explicit fallback"})
    assert changed["state"]["card"]["decision_guidance"] == "owner policy explicit fallback"
    assert source["state"]["card"]["decision_guidance"] == "owner policy"
    assert variant(source, {}) == source
    assert encoded(source) == encoded(dict(reversed(list(source.items()))))


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [None, 2])
async def test_multiple_calls_write_unique_results_and_stop_without_retry(tmp_path, monkeypatch, fail_at):
    from evaluations import policy_input_diagnostic as probe

    sent = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, *, content, headers):
            sent.append(content)
            status = 503 if len(sent) == fail_at else 200
            return probe.httpx.Response(status, request=probe.httpx.Request("POST", url), json={
                "model": "fixed-model", "answers": {"outcome": {"choice": "ignore"}},
                "usage": {"input_tokens": 10, "output_tokens": 2}})

    monkeypatch.setattr(probe.httpx, "AsyncClient", Client)
    key = tmp_path/"key"
    key.write_text("not-a-live-credential")
    rows = []
    for i in range(3):
        payload = {"model": "model", "state": {"case": i}, "questions": {}}
        rows.append({"case": str(i), "variant": "control", "payload": payload,
                     "wire_sha256": hashlib.sha256(encoded(payload)).hexdigest(), "expected_outcomes": ["ignore"]})
    (tmp_path/"prepared.json").write_text(json.dumps({"scope": "test", "inputs": {}, "rows": rows,
        "max_requests": 3, "resolved_model": "fixed-model"}))
    result = await probe.run(tmp_path, key)
    count = fail_at or 3
    assert result == {"attempts": count, "planned": 3, "errors": int(bool(fail_at))}
    assert len(sent) == count
    assert sorted(p.name for p in tmp_path.glob("result-*.json")) == [f"result-{i:03d}.json" for i in range(1, count+1)]
    saved = json.loads((tmp_path/"results.json").read_text())["rows"]
    assert len(saved) == count
    if fail_at:
        assert saved[-1]["usage_known"] is False
    with pytest.raises(FileExistsError):
        await probe.run(tmp_path, key)
    assert len(sent) == count


def test_continuation_preserves_known_prefix_and_never_resubmits_or_rewrites_it(tmp_path):
    from evaluations import policy_input_diagnostic as probe
    from evaluations.harbor_workflow_preflight import _sha

    original = tmp_path/"original"
    original.mkdir()
    backup = original/"old-runner.py"
    backup.write_text("original method")
    rows, events = [], []
    for i in range(6):
        body = {"model": "fixed-model", "state": {"id": i}, "questions": {}}
        row = {"case": str(i), "variant": "control", "payload": body,
               "wire_sha256": hashlib.sha256(encoded(body)).hexdigest(), "expected_outcomes": ["ignore"]}
        rows.append(row)
        if i < 2:
            events.extend([
                {"kind": "api.request", "request_id": i+1, "payload": body, "wire_sha256": row["wire_sha256"]},
                {"kind": "api.result", "request_id": i+1, "case": str(i), "variant": "control",
                 "expected_outcomes": ["ignore"], "usage_known": True,
                 "response": {"model": "fixed-model", "usage": {"input_tokens": 10, "output_tokens": 2}}},
            ])
    (original/"prepared.json").write_text(json.dumps({"scope": "unit", "rows": rows, "max_requests": 6,
        "resolved_model": "fixed-model", "inputs": {probe.__file__: _sha(backup)}}))
    audit = original/"attempts.jsonl"
    audit.write_text("\n".join(json.dumps(e) for e in events)+"\n")
    before = {p.name: p.read_bytes() for p in original.iterdir()}
    output = tmp_path/"continued"
    assert probe.prepare_remaining(original, output, backup) == {
        "prior_attempts": 2, "remaining": 4, "total_cap": 6, "provider_calls": 0}
    amended = json.loads((output/"prepared.json").read_text())
    assert amended["rows"] == rows[2:]
    assert len(amended["inherited_results"]) == 2
    assert {p.name: p.read_bytes() for p in original.iterdir()} == before
    with pytest.raises(ValueError, match="New continuation"):
        probe.prepare_remaining(original, output, backup)
    audit.write_text("\n".join(json.dumps(e) for e in events[:-1])+"\n")
    with pytest.raises(ValueError, match="unknown or complete"):
        probe.prepare_remaining(original, tmp_path/"invalid", backup)

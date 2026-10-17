import copy
import json
from pathlib import Path

import pytest

from signalweave import local_run


def deferred_payload(reason: str, *, advertised_paths: bool) -> dict:
    result = {
        "card_id": "review-card",
        "outcome": None,
        "judgment": {
            "status": "deferred",
            "reason": reason,
            "provider_call_attempts": 0,
        },
        "judgment_state": {
            "observations": [{"metric": "orders", "current": 12}],
            "evidence": [{"subject_label": "orders", "statement": "12 orders observed"}],
        },
        "observation_facts": {"record_count": 1, "rows_complete": True},
        "source_by_key": {"sales": {"adapter": "superset", "resource": "chart:12"}},
        "source_contracts": [{"source_key": "sales", "contract": {"coverage": "complete"}}],
        "context_dependencies_at_run": [{"entry_id": "definition", "status": "needs_review"}],
    }
    payload = {
        "receipt": {
            "receipt_id": "receipt-deferred-1",
            "card_id": "review-card",
            "status": "decision_deferred",
            "outcome": None,
        },
        "replayed": False,
        "card": {"id": "review-card"},
        "result": result,
    }
    if advertised_paths:
        payload["evidence_access"] = {
            "available_sections": [
                {"path": ["judgment_state"], "count": 2},
                {"path": ["source_by_key"], "count": 1},
            ],
            "observation_coverage": {
                "result_path": ["judgment_state", "observations"],
                "total": 1,
                "included": 0,
                "next_offset": 0,
            },
            "observation_facts": {
                "location": "inline_projection",
                "inline_result_path": ["observation_facts"],
                "result_path": ["judgment_state", "observations"],
            },
            "instruction": "Read only the omitted evidence needed for this investigation.",
        }
    return payload


class FakeMcpServer:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if name == "get_decision_receipt":
            return ([], {
                "status": "found",
                "receipt": copy.deepcopy(self.payload["receipt"]),
                "result": copy.deepcopy(self.payload["result"]),
            })
        return ([], copy.deepcopy(self.payload))


@pytest.mark.parametrize(
    ("reason", "advertised_paths"),
    [
        ("local_judgment_payload_over_budget", True),
        ("context_review_required", False),
    ],
    ids=["payload-budget", "context-review"],
)
async def test_run_card_preserves_any_deferred_receipt_and_writes_honest_handoff(
    monkeypatch, tmp_path, reason, advertised_paths
):
    original = deferred_payload(reason, advertised_paths=advertised_paths)
    server = FakeMcpServer(original)
    monkeypatch.setattr(local_run, "create_mcp", lambda runtime, profile: server)

    response = await local_run.run_card(
        "review-card", "period:2026-10-14", tmp_path / "artifacts", runtime=object()
    )

    assert server.calls == [
        ("evaluate_insight_card", {"card_id": "review-card", "idempotency_key": "period:2026-10-14"}),
        ("get_decision_receipt", {"receipt_id": "receipt-deferred-1"}),
    ]
    assert response["receipt"] == original["receipt"]
    assert response["result"] == original["result"]
    assert response["result"]["outcome"] is None
    brief = response["handoff_brief"]
    assert "No policy outcome was produced" in brief
    assert "Receipt: receipt\\-deferred\\-1." in brief
    assert reason.replace("_", "\\_") in brief
    assert "get_decision_receipt" in brief
    assert "offset=0" in brief and "limit=25" in brief and "next_offset" in brief
    assert "caller owns" in brief
    assert "Outcome: **" not in brief

    if advertised_paths:
        assert r'result\_path=\["judgment\_state","observations"\]' in brief
        assert r'result\_path=\["observation\_facts"\]' not in brief
        assert "inline overview" in brief
        assert "Read only the omitted evidence needed" in brief
    else:
        assert r'result\_path=\["judgment\_state","observations"\]' in brief
        assert r'result\_path=\["source\_by\_key"\]' in brief

    artifacts = response["artifacts"]
    stored = json.loads(Path(artifacts["result"]).read_text())
    assert stored == {"receipt": original["receipt"], "result": original["result"]}
    artifact_brief = Path(artifacts["brief"]).read_text()
    assert "No policy outcome was produced" in artifact_brief
    assert "Archived receipt note" in artifact_brief
    assert Path(artifacts["result"]).stat().st_mode & 0o777 == 0o600
    assert Path(artifacts["brief"]).stat().st_mode & 0o777 == 0o600

    # Replays retain one canonical receipt artifact even though the response flag changes.
    replay_payload = copy.deepcopy(original)
    replay_payload["replayed"] = True
    replay_server = FakeMcpServer(replay_payload)
    monkeypatch.setattr(local_run, "create_mcp", lambda runtime, profile: replay_server)
    replay = await local_run.run_card(
        "review-card", "period:2026-10-14", tmp_path / "artifacts", runtime=object()
    )
    assert replay["replayed"] is True
    assert replay["artifacts"] == artifacts
    assert json.loads(Path(artifacts["result"]).read_text()) == stored
    assert Path(artifacts["brief"]).read_text() == artifact_brief


async def test_run_card_returns_deferred_brief_without_an_artifact_directory(monkeypatch):
    original = deferred_payload("context_review_required", advertised_paths=False)
    server = FakeMcpServer(original)
    monkeypatch.setattr(local_run, "create_mcp", lambda runtime, profile: server)

    response = await local_run.run_card("review-card", "period:1", runtime=object())

    assert response["result"] == original["result"]
    assert response["result"]["outcome"] is None
    assert "No policy outcome was produced" in response["handoff_brief"]
    assert "artifacts" not in response


def _artifact_contents(response):
    return {
        name: Path(path).read_bytes()
        for name, path in response["artifacts"].items()
    }


async def test_real_deferred_receipt_artifacts_remain_canonical_on_replay(tmp_path, monkeypatch):
    from tests.test_context_card_mcp import authorize_for_runtime_test, prepared

    server, runtime, assets, _, judger, _ = await prepared(tmp_path)
    authorize_for_runtime_test(runtime)
    assets.binding_namespace = "workspace-b"
    monkeypatch.setattr(local_run, "create_mcp", lambda supplied_runtime, profile: server)

    first = await local_run.run_card("repeat", "stale-period", tmp_path / "deferred", runtime=runtime)
    first_files = _artifact_contents(first)
    replay = await local_run.run_card("repeat", "stale-period", tmp_path / "deferred", runtime=runtime)

    assert replay["replayed"] is True
    assert replay["receipt"]["status"] == "replayed"
    assert replay["result"]["outcome"] is None
    assert replay["current_action_warning"].startswith("No policy outcome was produced")
    assert replay["current_context_dependencies"]["required_current"] is False
    assert _artifact_contents(replay) == first_files
    saved = json.loads(Path(replay["artifacts"]["result"]).read_text())
    assert saved["receipt"]["status"] == "decision_deferred"
    assert saved["result"]["judgment"]["reason"] == "context_review_required"
    assert "No policy outcome was produced" in Path(replay["artifacts"]["brief"]).read_text()
    assert "Archived receipt note" in Path(replay["artifacts"]["brief"]).read_text()
    assert not judger.states and assets.reads == 1


async def test_normal_historical_replay_keeps_archived_artifacts_and_warns_live(
    tmp_path, monkeypatch
):
    from tests.test_context_card_mcp import authorize_for_runtime_test, prepared

    server, runtime, assets, _, judger, _ = await prepared(tmp_path)
    authorize_for_runtime_test(runtime)
    monkeypatch.setattr(local_run, "create_mcp", lambda supplied_runtime, profile: server)

    first = await local_run.run_card("repeat", "normal-period", tmp_path / "normal", runtime=runtime)
    first_files = _artifact_contents(first)
    assert first["result"]["outcome"] == "notify"
    assert first["policy_action_available"] is True

    assets.binding_namespace = "workspace-b"
    replay = await local_run.run_card("repeat", "normal-period", tmp_path / "normal", runtime=runtime)

    assert replay["policy_result_is_historical"] is True
    assert replay["policy_action_available"] is False
    assert replay["result"]["delivery_methods"] == []
    assert "no current policy action is available" in replay["current_action_warning"]
    assert _artifact_contents(replay) == first_files
    archived = json.loads(Path(replay["artifacts"]["result"]).read_text())
    assert archived["outcome"] == "notify"
    assert archived["delivery_methods"]
    archived_brief = Path(replay["artifacts"]["brief"]).read_text()
    assert "Outcome: **notify**" in archived_brief
    assert "does not establish that an action is available under current context" in archived_brief
    assert replay["result"]["outcome"] == "notify"  # historical value, warned separately
    assert len(judger.states) == 1 and assets.reads == 1

"""Canary control fidelity; these mocked turns are not human-experience evidence."""

import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

from evaluations import confirmation_canary as canary
from tests.test_public_owner_report_trial import FakeNative, _response


class Native(FakeNative):
    async def call_tool(self, name, args):
        if name == "review_insight_card":
            return [], {"card": dict(self.card), "approval_handoff": {"owner_confirmation": {"card_id": self.card["id"]}}}
        _, result = await super().call_tool(name, args)
        if name == "evaluate_insight_card":
            result["receipt"]["delivery_enabled"] = False
        return [], result


def patched(tmp_path, monkeypatch, *, live, fault=None):
    binary, codex, key = [tmp_path / name for name in ("native", "codex", "key")]
    binary.write_bytes(b"offline native")
    codex.write_bytes(b"offline CLI")
    key.write_text("not-a-live-key")
    identity = {"binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
    monkeypatch.setattr(canary, "verify_binary", lambda _: identity)

    async def pinned(_):
        return {"path": str(codex), "sha256": hashlib.sha256(codex.read_bytes()).hexdigest()}

    monkeypatch.setattr(canary, "pinned_codex", pinned)
    state = {"turns": [], "natives": [], "budget": None}

    @asynccontextmanager
    async def native_context(_binary, _key, public, adapter, audit, root, *, request_budget):
        native = Native(adapter, public["scenario_id"])
        state["budget"] = request_budget
        state["natives"].append(native)
        assert root.is_dir() and not list(root.iterdir())
        skill = (canary.Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md").read_text()
        yield native, skill

    async def actor(session, **kwargs):
        if not live:
            raise AssertionError("preflight must not invoke a model")
        audit = kwargs["audit"]
        kind = next(k for k, v in canary.REPLIES.items() if v == kwargs["prompt_override"]["latest_owner_reply"])
        state["turns"].append(kind)
        audit.emit("api.request", provider="openai")
        card_id = session.native.card["id"]
        if kind == "approve":
            await session.call("approve_insight_card", {"card_id": card_id})
            state["budget"].claim()
            audit.emit("api.request", provider="jev")
            audit.emit("api.response", provider="jev", usage={"input_tokens": 10, "output_tokens": 1})
            await session.call("evaluate_insight_card", {"card_id": card_id, "idempotency_key": "unit"})
        elif kind == "revise_first":
            session.native.card["version"] += 1
            session.native.card["decision_guidance"] = "Notify at a 15% decline."
        elif fault == "unauthorized-approval" and kind == "ambiguous":
            await session.call("approve_insight_card", {"card_id": card_id})
        await session.call("record_response", {"message": "Offline response, not a business result."})
        if not (fault == "unknown-usage" and kind == "clarification_only"):
            audit.emit("api.response", provider="openai", usage=_response())
        return {"status": "complete"}

    monkeypatch.setattr(canary, "native_context", native_context)
    monkeypatch.setattr(canary, "codex_episode", actor)
    args = SimpleNamespace(binary=str(binary), codex_executable=str(codex), key_file=str(key),
                           output=str(tmp_path / "results"), run=live)
    return args, state


async def test_preflight_has_no_agents_provider_calls_or_approved_state(tmp_path, monkeypatch):
    args, state = patched(tmp_path, monkeypatch, live=False)
    result = await canary.run(args)
    assert result["completed"] and len(result["cases"]) == 4
    assert result["provider_attempts"] == result["agent_invocations_started"] == 0
    assert state["turns"] == []
    assert all(n.card["status"] == "draft" for n in state["natives"])


async def test_four_observed_states_not_self_reported_success(tmp_path, monkeypatch):
    args, state = patched(tmp_path, monkeypatch, live=True)
    result = await canary.run(args)
    assert result["completed"] and result["behavior_pass"] and result["provider_usage_known"]
    assert state["turns"] == list(canary.REPLIES)
    assert result["provider_attempts"] == 1 and result["agent_invocations_started"] == 4
    assert result["cases"][0]["after"]["status"] == "approved"
    assert all(e["after"]["status"] == "draft" for e in result["cases"][1:])


async def test_unauthorized_model_action_is_forwarded_and_fails_instead_of_hidden(tmp_path, monkeypatch):
    args, state = patched(tmp_path, monkeypatch, live=True, fault="unauthorized-approval")
    result = await canary.run(args)
    assert result["completed"] and not result["behavior_pass"]
    assert state["turns"] == list(canary.REPLIES)
    case = result["cases"][2]
    assert case["after"]["status"] == "approved" and not case["checks"]["no_approval_attempt"]


async def test_unknown_usage_stops_without_retry_or_remaining_calls(tmp_path, monkeypatch):
    args, state = patched(tmp_path, monkeypatch, live=True, fault="unknown-usage")
    result = await canary.run(args)
    assert not result.get("completed", False)
    assert state["turns"] == ["approve", "clarification_only"]
    assert result["provider_attempts"] == 1


async def test_invocation_cap_is_enforced_before_another_turn(tmp_path, monkeypatch):
    args, state = patched(tmp_path, monkeypatch, live=True)
    monkeypatch.setattr(canary, "LIMITS", {**canary.LIMITS, "agent_invocations": 1})
    result = await canary.run(args)
    assert not result.get("completed", False) and state["turns"] == ["approve"]


def test_claimed_success_without_actual_approval_or_receipt_does_not_pass():
    card = {"id": "card", "version": 1, "status": "draft"}
    checks = canary.behavior_checks("approve", card, card, [])
    assert not any(checks.values())

"""Offline orchestration checks, not provider or business-outcome proof."""

import copy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from evaluations import raw_superset_workflow as trial
from signalweave.models import InsightCard, SourceRef


class Sources:
    telemetry = {"logical_tool_calls": 0, "chart_query_http_requests": 0}

    def __init__(self, *args):
        pass

    async def specs(self):
        return [{"name": name, "description": name, "parameters": {"type": "object"}}
                for name in ("find_dashboards", "list_dashboard_charts", "profile_saved_chart", "read_chart_rows")]

    async def call(self, name, args):
        if name == "find_dashboards":
            return {"dashboards": [{"id": "3"}]}
        if name == "list_dashboard_charts":
            return {"charts": [{"id": "42"}]}
        return {"evidence": "actual test provider result", "query_scope": "saved chart"}


class Native:
    instructions = "Native instructions"

    def __init__(self):
        self.card, self.calls = None, []

    async def list_tools(self):
        return [SimpleNamespace(name=n, description=n, inputSchema={"type": "object"})
                for n in trial.AUTHOR_TOOLS | trial.REPORT_NATIVE]

    async def call_tool(self, name, args):
        self.calls.append(name)
        if name == "list_insight_cards":
            return [], {"cards": [copy.deepcopy(self.card)] if self.card else []}
        if name == "onboard_insight_card":
            self.card = InsightCard(id="actual-saved-card", title="Test", what_to_watch="Reported sales",
                                    why_watch="Understand sales", sources=[SourceRef(key="primary", adapter="superset",
                                    resource="chart:42", label="Declared saved source")]).model_dump(mode="json")
            return [], {"card": copy.deepcopy(self.card)}
        if name == "get_insight_card":
            return [], copy.deepcopy(self.card)
        if name == "review_insight_card":
            return [], {"card": copy.deepcopy(self.card), "review": {"readiness_status": "ready_for_approval"},
                        "approval_handoff": {"arguments_after_owner_confirmation": {"card_id": self.card["id"]}}}
        if name == "approve_insight_card":
            self.card["status"] = "approved"
            return [], {"status": "approved", "card": copy.deepcopy(self.card)}
        if name == "evaluate_insight_card":
            return [], {"result": {"outcome": "insufficient_data"}, "receipt": {"delivery_enabled": False}}
        return [], {}


def patch_runtime(monkeypatch, tmp_path, *, reject=None, unknown=False):
    # Contract tests use their own fake-only protocol, never reopen the real
    # closed paid cohort merely to exercise orchestration with test doubles.
    manifest = json.loads(trial.MANIFEST.read_text())
    owner = trial.MANIFEST.with_name(manifest["owner_reference_file"]).read_text()
    manifest["protocol"] = "unit-test-workflow"
    manifest.pop("execution_status", None)
    manifest.pop("closed_attempt", None)
    (tmp_path / manifest["owner_reference_file"]).write_text(owner)
    isolated_manifest = tmp_path / "unit-workflow.json"
    isolated_manifest.write_text(json.dumps(manifest))
    monkeypatch.setattr(trial, "MANIFEST", isolated_manifest)
    native = Native()
    codex = tmp_path / "codex"
    codex.write_text("test executable identity")
    key = tmp_path / "fake.key"
    key.write_text("synthetic-provider-key")
    args = SimpleNamespace(binary="/fake/binary", codex_executable=str(codex),
                           output=str(tmp_path / "preflight"), superset_url="http://127.0.0.1:18089",
                           run=False, preflight=None, key_file=str(key))
    monkeypatch.setattr(trial, "verify_binary", lambda *a: {"binary_sha256": "same-current-build"})
    monkeypatch.setattr(trial, "verify_capture_imports", lambda: None)

    async def identity(path):
        return {"path": str(codex), "sha256": trial.digest(codex)}
    monkeypatch.setattr(trial, "pinned_codex", identity)
    monkeypatch.setattr(trial, "RawSupersetTools", Sources)

    @asynccontextmanager
    async def connection(*a):
        yield native, "Actual packaged test skill"
    monkeypatch.setattr(trial, "native_connection", connection)
    state = {"invocations": [], "budgets": []}

    async def actor(session, **kwargs):
        audit = kwargs["audit"]
        state["invocations"].append(audit.episode)
        request_id = -len(state["invocations"])
        audit.emit("api.request", provider="openai", request_id=request_id)
        assert kwargs["accounting_drain"] is True
        assert kwargs["prompt_override"]["work_limit"]["total_tool_calls_including_final_record"] == kwargs["max_tool_calls"]
        if audit.episode.startswith("author"):
            await session.call("save_working_notes", {"notes": "The independently reusable business brief"})
            card_id = None
            if session.treatment:
                created = await session.call("onboard_insight_card", {})
                card_id = created["card"]["id"]
                await session.call("review_insight_card", {"card_id": card_id})
            await session.call("record_setup", {"message": "Supported source readout", "card_id": card_id, "unresolved": []})
            audit.emit("tool.result", name="profile_saved_chart", arguments={"id": "42"}, result={"source_fact": "captured"})
        elif audit.episode.startswith("review"):
            await session.call("record_review", {"ready_for_shadow": audit.episode != reject,
                                                 "issues": ["Material gap"] if audit.episode == reject else [],
                                                 "owner_message": "Expert assessed this exact saved proposal"})
        else:
            if session.treatment:
                await session.call("evaluate_insight_card", {"card_id": native.card["id"], "idempotency_key": session.run_key})
            await session.call("record_report", {"outcome": "insufficient_data", "recipients": ["Data Trust"],
                                                  "message": "Source-linked actual message"})
        if not unknown:
            audit.emit("api.response", provider="openai", request_id=request_id,
                       usage={"input_tokens": 100, "output_tokens": 10, "input_tokens_details": {"cached_tokens": 50}})
        return {"status": "complete"}
    monkeypatch.setattr(trial, "codex_episode", actor)
    return args, state, native


async def test_full_orchestration_uses_actual_authored_card_reviews_and_fresh_equal_policy(monkeypatch, tmp_path):
    args, state, native = patch_runtime(monkeypatch, tmp_path)
    preflight = await trial.run(args)
    assert preflight["invocations"] == 0 and state["invocations"] == []
    args.preflight = str(tmp_path / "preflight/report.json")
    args.output, args.run = str(tmp_path / "live"), True
    result = await trial.run(args)
    assert result["paired_reporting_complete"] and result["invocations"] == 6
    assert state["invocations"] == ["author:baseline", "author:signalweave", "review:baseline", "review:signalweave",
                                    "report:signalweave", "report:baseline"]
    assert native.calls.count("approve_insight_card") == 1
    assert native.calls.count("evaluate_insight_card") == 1
    report = json.loads((tmp_path / "live/report.json").read_text())
    assert report["card_policy_unchanged"]
    assert report["approval"]["card"]["id"] == "actual-saved-card"
    assert report["usage"]["input_tokens"] == 600


async def test_rejected_expert_review_never_approves_or_runs_reports(monkeypatch, tmp_path):
    args, state, native = patch_runtime(monkeypatch, tmp_path, reject="review:signalweave")
    await trial.run(args)
    args.preflight, args.output, args.run = str(tmp_path / "preflight/report.json"), str(tmp_path / "live"), True
    result = await trial.run(args)
    assert result["invocations"] == 4 and result["paired_reporting_complete"] is False
    assert "approve_insight_card" not in native.calls and "evaluate_insight_card" not in native.calls


async def test_unknown_usage_stops_before_next_actor_and_is_not_zero(monkeypatch, tmp_path):
    args, state, native = patch_runtime(monkeypatch, tmp_path, unknown=True)
    await trial.run(args)
    args.preflight, args.output, args.run = str(tmp_path / "preflight/report.json"), str(tmp_path / "live"), True
    with pytest.raises(Exception, match="usage unknown"):
        await trial.run(args)
    report = json.loads((tmp_path / "live/report.json").read_text())
    assert report["invocations"] == 1 and report["usage"] is None and not report["usage_known"]
    assert not report["completed"] and "approve_insight_card" not in native.calls


def test_source_excerpts_are_actual_and_fail_without_silent_truncation():
    events = [{"kind": "tool.result", "name": "read_chart_rows", "arguments": {"id": "42"}, "result": {"rows": [1]}},
              {"kind": "private.label", "name": "expected_outcome", "result": "MUST NOT LEAK"}]
    assert "MUST NOT LEAK" not in json.dumps(trial.source_excerpts(events, 1000))
    with pytest.raises(ValueError, match="budget exceeded"):
        trial.source_excerpts(events, 1)


async def test_report_tools_retain_company_access_and_cannot_edit_or_approve():
    session = trial.ReportEpisode(Sources(), {}, "Saved brief", Native(), approved_card_id="saved", run_key="current-run")
    names = {t["name"] for t in await session.specs()}
    assert {"find_dashboards", "profile_saved_chart", "read_chart_rows", "calculate", "read_working_notes",
            "evaluate_insight_card", "record_report"} <= names
    assert not {"onboard_insight_card", "approve_insight_card", "save_working_notes", "ask_owner"} & names
    with pytest.raises(ValueError, match="not available"):
        await session.call("approve_insight_card", {})
    with pytest.raises(ValueError, match="Evaluate the approved card once"):
        await session.call("record_report", {"outcome": "ignore", "recipients": [], "message": "No evaluation"})
    with pytest.raises(ValueError, match="exact approved card"):
        await session.call("evaluate_insight_card", {"card_id": "wrong", "idempotency_key": "current-run"})
    await session.call("evaluate_insight_card", {"card_id": "saved", "idempotency_key": "current-run"})
    with pytest.raises(ValueError, match="one new evaluation"):
        await session.call("evaluate_insight_card", {"card_id": "saved"})


def test_credential_cleanup_covers_partial_setup_without_config(tmp_path):
    root = tmp_path / "owned-research"
    (root / "native-home").mkdir(parents=True)
    copied = root / "native-home/typesafe.key"
    copied.write_text("synthetic-live-secret-copy")
    trial.scrub_copied_key(root)
    assert copied.read_text().strip() == "not-a-live-provider-key"
    assert copied.stat().st_mode & 0o777 == 0o600
    assert not (root / "native-home/config.toml").exists()


def test_credential_cleanup_refuses_links_and_preserves_original(tmp_path):
    original = tmp_path / "personal.key"
    original.write_text("do-not-change")
    root = tmp_path / "owned-research"
    (root / "native-home").mkdir(parents=True)
    (root / "native-home/typesafe.key").symlink_to(original)
    with pytest.raises(ValueError, match="symlink"):
        trial.scrub_copied_key(root)
    assert original.read_text() == "do-not-change"


def test_hardlinked_key_is_not_truncated(tmp_path):
    import os
    original = tmp_path / "original.key"
    original.write_text("do-not-truncate")
    root = tmp_path / "owned"
    (root / "native-home").mkdir(parents=True)
    os.link(original, root / "native-home/typesafe.key")
    with pytest.raises(ValueError, match="multiply-linked"):
        trial.scrub_copied_key(root)
    assert original.read_text() == "do-not-truncate"


async def test_remote_source_rejected_before_setup_or_auth(monkeypatch, tmp_path):
    args, state, native = patch_runtime(monkeypatch, tmp_path)
    args.superset_url = "https://unapproved.example"
    with pytest.raises(ValueError, match="loopback"):
        await trial.run(args)
    assert not (tmp_path / "preflight").exists() and state["invocations"] == []


def test_preflight_unknown_usage_cannot_enable_live_calls():
    previous = {"frozen": {"current": True}, "completed": True, "preflight_only": True,
                "invocations": 0, "upstream_jev_requests": 0, "source_probe_ok": True,
                "initial_card_count": 0, "shared_tools_equal": True,
                "credential_scrubbed": True, "binary_unchanged": True, "usage_known": False}
    with pytest.raises(ValueError, match="usage must be known"):
        trial.verify_preflight(previous, previous["frozen"])
    previous["usage_known"] = True
    trial.verify_preflight(previous, previous["frozen"])


async def test_changed_policy_at_approval_stops_before_either_report(monkeypatch, tmp_path):
    args, state, native = patch_runtime(monkeypatch, tmp_path)
    await trial.run(args)
    original = native.call_tool

    async def mutate(name, params):
        result = await original(name, params)
        if name == "approve_insight_card":
            native.card["decision_guidance"] = "Unreviewed changed policy"
        return result
    native.call_tool = mutate
    args.preflight, args.output, args.run = str(tmp_path / "preflight/report.json"), str(tmp_path / "live"), True
    with pytest.raises(ValueError, match="does not match"):
        await trial.run(args)
    assert len(state["invocations"]) == 4 and "evaluate_insight_card" not in native.calls


async def test_real_closed_workflow_rejected_before_setup(monkeypatch):
    from unittest.mock import Mock
    probe = Mock(side_effect=AssertionError("No probing of a closed study"))
    monkeypatch.setattr(trial, "verify_binary", probe)
    with pytest.raises(ValueError, match="cohort closed"):
        await trial.run(SimpleNamespace(run=True))
    probe.assert_not_called()

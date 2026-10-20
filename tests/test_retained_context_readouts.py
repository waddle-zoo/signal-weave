"""Offline orchestration checks; mocked reports are not business evidence."""

import hashlib
import json
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations import retained_owner_periods as trial
from signalweave.models import InsightCard, SourceRef


def patch_context(tmp_path, monkeypatch, *, live=False, wrong_context=False, unknown_usage=False):
    root = tmp_path / "prior"
    owned = root / "private-native-state"
    home = owned / "native-home"
    home.mkdir(parents=True)
    connection_files = {owned / "company-mcp.json": "original company manifest",
                        home / "config.toml": "original V7 home", home / "typesafe.key": "original V7 key"}
    for path, content in connection_files.items():
        path.write_text(content)
    # This fixture only exercises orchestration; it is not business proof.
    retailbase = trial.development_scenario()
    monkeypatch.setattr(trial, "development_scenario", lambda: retailbase)
    fixture, _ = trial.attach_owner_clarification(retailbase, trial.CLARIFICATION)
    public = trial.public_episode(fixture)
    asset = next(a for a in public["catalog"] if a["contract"].get("roles") == ["primary"])
    card = InsightCard(id="retained-v7-card", title="Mock retained card", what_to_watch="Service", why_watch="Test orchestration",
                       status="approved", version=3, sources=[SourceRef(key="service", adapter=asset["adapter"],
                                                                          resource=asset["resource"], label=asset["title"])])
    entry = {"id": json.loads(trial.CONTEXT_MANIFEST.read_text())["context_entry_ids"][0],
             "revision": 2, "review_status": "approved", "body": "Mock retained reviewed context"}
    authors = [{"arm": arm, "stage": "author", "notes": "Saved V7 notes", "setup": {"unresolved": ["Keep freshness open."]},
                "independent_review": {"approved": False},
                **({"card": card.model_dump(mode="json"), "native_calls": [{"name": "review_domain_context", "result": entry}]}
                   if arm == "signalweave" else {})} for arm in ("baseline", "signalweave")]
    prior = {"protocol": "courier-owner-clarified-v7", "completed": True, "usage_known": True,
             "agent_invocations_started": 4, "paired_reporting_complete": False, "qualified_arms": [],
             "onboarding_status": "needs_review", "episodes": authors, "usage": {}, "measurement_offset_seconds": 0,
             "scenario_sha256": hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()}
    report, trace = root / "report.json", root / "trace.jsonl"
    report.write_text(json.dumps(prior))
    trace.write_text("synthetic V7 trace\n")
    manifest = json.loads(trial.CONTEXT_MANIFEST.read_text())
    manifest.update(prior_report_sha256=trial.digest(report), prior_trace_sha256=trial.digest(trace))
    manifest_path = tmp_path / "context-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(trial, "CONTEXT_MANIFEST", manifest_path)
    binary, codex, key = (tmp_path / name for name in ("binary", "codex", "live-key"))
    for path in (binary, codex, key):
        path.write_text("offline " + path.name)
    monkeypatch.setattr(trial, "verify_binary", lambda _: {"source_sha256": "source", "binary_sha256": trial.digest(binary)})
    monkeypatch.setattr(trial, "source_fingerprint", lambda: "source")

    async def pinned(_):
        return {"path": str(codex), "sha256": trial.digest(codex)}

    monkeypatch.setattr(trial, "pinned_codex", pinned)
    state = {"calls": [], "context_reads": [], "cards": [], "credentials": [], "model_calls": [],
             "prompts": [], "budget": None, "skill_workspace": None, "connection_files": connection_files}

    async def credential(_binary, supplied_home, supplied_key):
        state["credentials"].append((supplied_home, supplied_key.read_text()))

    monkeypatch.setattr(trial, "credential", credential)

    @asynccontextmanager
    async def native(_binary, _key, _public, adapter, audit, supplied_owned, *, request_budget, skill_workspace=None):
        assert supplied_owned == owned
        state["budget"], state["skill_workspace"] = request_budget, skill_workspace
        for path in connection_files:
            path.write_text("changed by mocked native setup")

        class Native:
            async def call_tool(self, name, arguments):
                state["calls"].append(name)
                if name == "get_insight_card":
                    payload = card.model_dump(mode="json")
                    state["cards"].append(payload)
                    return [], payload
                if name == "retrieve_domain_context":
                    actual = dict(entry)
                    if wrong_context:
                        actual["body"] = "Different current context"
                    packet = {"entries": [actual] if arguments["entry_ids"] == [entry["id"]] else []}
                    state["context_reads"].append(packet["entries"])
                    return [], packet
                if name == "inspect_resource":
                    result = (await adapter.inspect(card.sources[0])).model_dump(mode="json")
                    result["contract"].update(asset["contract"])
                    return [], result
                if name == "evaluate_insight_card":
                    request_budget.claim()
                    audit.emit("api.request", provider="jev")
                    audit.emit("api.response", provider="jev", usage={"input_tokens": 8, "output_tokens": 2})
                    return [], {"receipt": {"card_id": card.id, "card_version": card.version,
                                             "idempotency_key": arguments["idempotency_key"],
                                             "delivery_enabled": False, "status": "decision_deferred"},
                                "result": {"card_id": card.id}}
                raise AssertionError(f"Unexpected native tool: {name}")

        skill = (Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md").read_text()
        yield Native(), skill

    monkeypatch.setattr(trial, "native_context", native)

    async def actor(session, **kwargs):
        prompt, audit = kwargs["prompt_override"], kwargs["audit"]
        state["model_calls"].append(session.treatment)
        state["prompts"].append(prompt)
        audit.emit("api.request", provider="openai")
        if session.treatment:
            await session.call("retrieve_domain_context", {"entry_ids": prompt["stored_brief"]["context_entry_ids"]})
            await session.call("evaluate_insight_card", {"card_id": session.approved_card_id, "idempotency_key": session.run_key})
        await session.call("record_report", {"outcome": "ignore", "recipients": [], "summary": "Mock report; not a quality score"})
        if not unknown_usage:
            audit.emit("api.response", provider="openai", usage={"input_tokens": 12, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 3}})
        return {"status": "complete"}

    monkeypatch.setattr(trial, "codex_episode", actor)
    args = SimpleNamespace(prior=str(root), binary=str(binary), codex_executable=str(codex),
                           output=str(tmp_path / "fresh-output"), run=live, key_file=str(key), context_readout=True,
                           preflight=None)
    return args, state, root, entry


async def test_preflight_verifies_context_and_restores_files_without_provider_or_agent_calls(tmp_path, monkeypatch):
    args, state, root, entry = patch_context(tmp_path, monkeypatch)
    result = await trial.run(args)
    assert result["completed"] and result["preflight_only"] and result["retained_context_verified"]
    assert result["context_unchanged"] and result["card_unchanged"] and result["connection_files_restored"]
    assert result["agent_invocations_started"] == result["provider_attempts"] == 0
    assert result["source_fidelity_verified_periods"] == [1, 2] and state["model_calls"] == []
    assert state["budget"].limit == 0 and state["context_reads"] == [[entry], [entry]]
    assert result["onboarding_qualified"] is False and result["prior_onboarding_status"] == "needs_review"
    assert state["skill_workspace"] == Path(args.output) and state["skill_workspace"] != root / "private-native-state"
    assert result["installed_skill_sha256"] == trial.digest(Path(__file__).resolve().parents[1] / "skills/signalweave/SKILL.md")
    assert all(path.read_text() == content for path, content in state["connection_files"].items())


async def test_live_readout_runs_four_reporters_and_retrieves_context_in_both_treatment_episodes(tmp_path, monkeypatch):
    args, state, root, entry = patch_context(tmp_path, monkeypatch, live=True)
    preflight = await trial.run(SimpleNamespace(**{**vars(args), "run": False}))
    assert preflight["completed"] and preflight["connection_files_restored"]
    args.preflight = str(Path(args.output) / "report.json")
    args.output = str(tmp_path / "live-output")
    result = await trial.run(args)
    assert result["completed"] and result["card_unchanged"] and result["context_unchanged"]
    assert result["onboarding_qualified"] is False and result["prior_onboarding_status"] == "needs_review"
    assert len(result["episodes"]) == result["agent_invocations_started"] == 4
    assert result["provider_attempts"] == 2 and state["budget"].limit == 2
    assert state["model_calls"] == [True, False, False, True]
    treated = [episode for episode in result["episodes"] if episode["arm"] == "signalweave"]
    assert all(len(episode["context_retrievals"]) == 1 and episode["context_retrievals"][0]["result"]["entries"] == [entry]
               for episode in treated)
    assert all(prompt["saved_setup"]["onboarding_qualified"] is False and "completed_policy_review" not in prompt
               for prompt in state["prompts"])
    assert result["preflight_report_sha256"] == trial.digest(args.preflight)
    assert not set(state["calls"]) & {"approve_insight_card", "review_domain_context", "save_domain_context", "save_working_notes", "onboard_insight_card"}
    assert [author["notes"] for author in json.loads((root / "report.json").read_text())["episodes"]] == ["Saved V7 notes"] * 2
    assert state["credentials"][-1][1] == "synthetic-retained-periods-no-inference"
    assert state["credentials"][-1][0] == root / "private-native-state/native-home"
    assert result["connection_files_restored"] and all(
        path.read_text() == content for path, content in state["connection_files"].items())


async def test_wrong_retained_context_stops_before_any_reporter_invocation(tmp_path, monkeypatch):
    args, state, _, entry = patch_context(tmp_path, monkeypatch, wrong_context=True)
    result = await trial.run(args)
    assert not result.get("completed") and "Retained current context changed" in result["failure"]["message"]
    changed = {**entry, "body": "Different current context"}
    assert state["model_calls"] == [] and state["context_reads"] == [[changed]]
    assert result["connection_files_restored"] and all(
        path.read_text() == content for path, content in state["connection_files"].items())
    assert state["credentials"][-1][1] == "synthetic-retained-periods-no-inference"


async def test_unknown_usage_is_global_stop_and_credentials_are_cleaned_up(tmp_path, monkeypatch):
    args, state, root, _ = patch_context(tmp_path, monkeypatch, live=True, unknown_usage=True)
    args.preflight = str(root / "report.json")

    def mocked_preflight_gate(path, report, manifest):
        assert path and report["onboarding_qualified"] is False and manifest["limits"]["agent_invocations"] == 4
        return "mock-preflight-artifact"

    monkeypatch.setattr(trial, "validate_context_preflight", mocked_preflight_gate)
    result = await trial.run(args)
    assert result["usage_known"] is False and result["provider_attempts"] == 1
    assert state["model_calls"] == [True]
    assert state["credentials"][-1] == (root / "private-native-state/native-home", "synthetic-retained-periods-no-inference")
    assert result["connection_files_restored"] and all(
        path.read_text() == content for path, content in state["connection_files"].items())


def test_context_preflight_guard_accepts_matching_artifact_and_rejects_stale_mutations(tmp_path):
    manifest = {"period_indices": [1, 2]}
    current = {"protocol": "readout-v1", "frozen": {"runner": "frozen"}, "build": {"sha256": "build"},
               "codex": {"sha256": "codex"}, "prior_report_sha256": "prior"}
    artifact = {**current, "completed": True, "preflight_only": True, "agent_invocations_started": 0,
                "provider_attempts": 0, "source_fidelity_verified_periods": [1, 2],
                "retained_context_verified": True, "card_unchanged": True, "context_unchanged": True,
                "connection_files_restored": True}
    path = tmp_path / "preflight-report.json"
    path.write_text(json.dumps(artifact))
    assert trial.validate_context_preflight(path, current, manifest) == trial.digest(path)
    with pytest.raises(ValueError, match="require --preflight"):
        trial.validate_context_preflight(None, current, manifest)
    mutations = [("completed", False), ("preflight_only", False), ("protocol", "stale"), ("frozen", {}),
                 ("build", {}), ("codex", {}), ("prior_report_sha256", "stale"),
                 ("agent_invocations_started", 1), ("provider_attempts", 1),
                 ("source_fidelity_verified_periods", [2, 1]), ("retained_context_verified", False),
                 ("card_unchanged", False), ("context_unchanged", False), ("connection_files_restored", False)]
    for field, value in mutations:
        path.write_text(json.dumps({**artifact, field: value}))
        with pytest.raises(ValueError):
            trial.validate_context_preflight(path, current, manifest)


def test_connection_restore_preserves_modes_and_removes_private_backup_copies(tmp_path, monkeypatch):
    args, state, root, _ = patch_context(tmp_path, monkeypatch)
    output = Path(args.output)
    output.mkdir()
    for original in state["connection_files"]:
        original.chmod(0o640)
    records = trial.backup_connections(root / "private-native-state", output)
    for original in state["connection_files"]:
        original.write_text("temporary research configuration")
        original.chmod(0o600)
    trial.restore_connections(records)
    assert all(original.read_text() == contents and stat.S_IMODE(original.stat().st_mode) == 0o640
               for original, contents in state["connection_files"].items())
    assert list((output / "original-connection-files").iterdir()) == []

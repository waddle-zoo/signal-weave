"""Offline authoring/admission contracts, not deployment or business-success proof."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from evaluations import northstar_source_authoring as trial


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def report(**updates):
    result = {"process_complete": True,
              "usage": {"known": True, "usage": {"input_tokens": 10, "uncached_input_tokens": 5}}}
    result.update(updates)
    return result


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Only temporary records; any unmocked source/author launch fails immediately."""
    repo, parent, root = (tmp_path/name for name in ("repo", "parent", "authoring"))
    for name in trial.METHOD_FILES:
        path = repo/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Offline method fixture: {name}\n")
    (repo/"docs").mkdir()
    (repo/"docs/mcp-source-bridge.md").write_text("Public snapshot-envelope reference, no analysis.\n")
    codex, source, binary = (tmp_path/name for name in ("codex", "source", "native"))
    for path in (codex, source, binary):
        path.write_text("Non-executable test identity\n")
    public = tmp_path/"public-sdk"
    public.mkdir()
    monkeypatch.setattr(trial, "ROOT", repo)
    monkeypatch.setattr(trial, "public_paths", lambda workspace: (public, Path(workspace)/"tool-responses"))
    identity, warehouse = {"fingerprint": "offline-native"}, {"sha256": "offline-data"}
    monkeypatch.setattr(trial, "verify_binary", Mock(return_value=identity))
    monkeypatch.setattr(trial.first, "warehouse_fingerprint", Mock(return_value=warehouse))
    monkeypatch.setattr(trial.first, "source_environment_identity", Mock(return_value={"sha256": "offline-source"}))
    monkeypatch.setattr(trial.first, "servers", Mock(side_effect=AssertionError("Unexpected source launch")))
    monkeypatch.setattr(trial, "codex_episode", AsyncMock(side_effect=AssertionError("Unexpected author launch")))
    prior = {"protocol": trial.previous.PROTOCOL, "warehouse": warehouse,
             "codex": {"path": str(codex), "sha256": trial._sha(codex)},
             "source_executable": str(source), "source_environment": {"sha256": "offline-source"},
             "url": "http://offline.invalid", "registry_sha256": "offline-registry", "workspaces": {}}
    for arm in trial.ORDER:
        workspace = tmp_path/"retained"/arm
        workspace.mkdir(parents=True, mode=0o700)
        (workspace/"tool-responses").mkdir(mode=0o700)
        write(workspace/"tool-responses/response-000001.json", {"structured": {"value": None}, "content": []})
        (workspace/"working-notes.md").write_text(f"Actual retained {arm} notes, including prior failures.\n")
        (workspace/"recurrence-request.md").write_text("Retained owner intent, not a researcher solution.\n")
        prior["workspaces"][arm] = str(workspace)
        write(parent/f"{arm}.json", report(workspace_files=trial.first.workspace_inventory(workspace)))
    write(parent/"study.json", prior)
    return SimpleNamespace(root=root, parent=parent, binary=binary, prior=prior, public=public,
                           prepare=lambda: trial.prepare(root, parent, binary))


def test_tasks_share_source_clock_and_access_without_researcher_analysis(corpus):
    b, bp = trial.task("baseline", corpus.prior)
    t, tp = trial.task("signalweave", corpus.prior)
    assert bp == tp
    assert b.split(" Implement automation/", 1)[0] == t.split(" Implement automation/", 1)[0]
    deployment = bp["deployment"]
    assert deployment["source_command"] == [corpus.prior["source_executable"], "--transport", "stdio"]
    assert set(deployment["source_environment"]) == {"SUPERSET_BASE_URL", "SUPERSET_USERNAME", "SUPERSET_PASSWORD"}
    assert "run-context.json" in deployment["historical_clock"]
    assert "never host CURRENT_DATE" in deployment["historical_clock"]
    assert "without any LLM at recurrence" in b and "Do not add SignalWeave dependencies" in b
    assert "must not select policy outcomes" in t and "after code consent" in t
    assert "automation/render.py" in t and "automation/run.py" in b
    supplied = json.dumps((b, bp, t, tp))
    for forbidden in ("SELECT ", "gold.", "mart_executive_daily", "expected_outcome",
                      "ordered_guidance", "7.92%", "272,662.26"):
        assert forbidden not in supplied


def test_public_paths_are_exact_dependencies_and_only_this_workspaces_captures(tmp_path, monkeypatch):
    requested = []

    def resolve(path, *, strict):
        assert strict is True
        requested.append(path)
        return path

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(trial, "ROOT", tmp_path/"repo")
    monkeypatch.setattr(trial.sys, "base_prefix", str(tmp_path/"python-runtime"))
    workspace = tmp_path/"analyst"
    expected = (tmp_path/"python-runtime", trial.ROOT/".venv/lib/python3.12/site-packages",
                trial.ROOT/".venv/bin", trial.ROOT/".venv/pyvenv.cfg",
                Path("/opt/homebrew/opt/gettext/lib"), Path("/opt/homebrew/opt/openssl@3/lib"),
                Path("/opt/homebrew/opt"), workspace/"tool-responses")
    assert trial.public_paths(workspace) == expected
    assert tuple(requested) == expected
    assert workspace not in requested and trial.ROOT not in requested and tmp_path not in requested


def test_prepare_preserves_each_actual_workspace_and_freezes_inputs_without_launches(corpus):
    originals = {arm: trial.first.workspace_inventory(Path(corpus.prior["workspaces"][arm]))
                 for arm in trial.ORDER}
    assert corpus.prepare() == {"prepared": True, "analyst_invocations": 0, "provider_requests": 0}
    study = trial.shared.read(corpus.root/"study.json")
    assert study["limits"] == trial.LIMITS and study["method"] == trial.method()
    assert study["limits"]["authors"] == 2 and study["limits"]["jev_requests"] == 0
    assert "not fresh onboarding, deployment, business success" in study["scope"]
    for arm in trial.ORDER:
        workspace = Path(study["workspaces"][arm])
        inventory = trial.first.workspace_inventory(workspace)
        assert all(inventory[name] == value for name, value in originals[arm].items())
        assert trial.first.workspace_inventory(Path(corpus.prior["workspaces"][arm])) == originals[arm]
        assert inventory == study["initial_inventory"][arm]
        assert study["public_read_paths"][arm] == [str(corpus.public), str(workspace/"tool-responses")]
        assert study["task_hashes"][arm] == trial._sha(corpus.root/f"{arm}-task.json")
        assert study["predecessors"][str(corpus.parent/f"{arm}.json")] == trial._sha(corpus.parent/f"{arm}.json")
        assert (workspace/"mcp-source-bridge.md").read_text() == (trial.ROOT/"docs/mcp-source-bridge.md").read_text()
    trial.verify(study, corpus.root)
    trial.first.servers.assert_not_called()
    trial.codex_episode.assert_not_awaited()
    with pytest.raises(ValueError, match="New study root"):
        corpus.prepare()


@pytest.mark.parametrize("defect", ["protocol", "warehouse", "source_runtime", "incomplete", "unknown_usage", "workspace"])
def test_prepare_rejects_invalid_actual_predecessors(corpus, defect):
    if defect == "protocol":
        write(corpus.parent/"study.json", {**corpus.prior, "protocol": "another-study"})
    elif defect == "warehouse":
        trial.first.warehouse_fingerprint.return_value = {"sha256": "changed"}
    elif defect == "source_runtime":
        trial.first.source_environment_identity.return_value = {"sha256": "changed"}
    elif defect == "workspace":
        (Path(corpus.prior["workspaces"]["baseline"])/"working-notes.md").write_text("Unrecorded change")
    else:
        path = corpus.parent/"signalweave.json"
        data = trial.shared.read(path)
        if defect == "incomplete":
            data["process_complete"] = False
        else:
            data["usage"]["known"] = False
        write(path, data)
    with pytest.raises(ValueError):
        corpus.prepare()
    trial.first.servers.assert_not_called()
    trial.codex_episode.assert_not_awaited()


@pytest.mark.parametrize("defect", ["protocol", "method", "limits", "native", "codex", "warehouse",
                                  "source_runtime", "predecessor", "task", "paths"])
def test_verify_rejects_frozen_input_drift(corpus, defect):
    corpus.prepare()
    study = trial.shared.read(corpus.root/"study.json")
    if defect in {"protocol", "method", "limits"}:
        study[defect] = None
    elif defect == "native":
        trial.verify_binary.return_value = {"fingerprint": "changed"}
    elif defect == "codex":
        Path(study["codex"]["path"]).write_text("changed")
    elif defect == "warehouse":
        trial.first.warehouse_fingerprint.return_value = {"sha256": "changed"}
    elif defect == "source_runtime":
        trial.first.source_environment_identity.return_value = {"sha256": "changed"}
    elif defect == "predecessor":
        (corpus.parent/"baseline.json").write_text("changed")
    elif defect == "task":
        (corpus.root/"baseline-task.json").write_text("changed")
    else:
        study["public_read_paths"]["baseline"].append(str(corpus.parent))
    with pytest.raises(ValueError):
        trial.verify(study, corpus.root)
    trial.first.servers.assert_not_called()
    trial.codex_episode.assert_not_awaited()


@pytest.fixture
def prepared(corpus, monkeypatch):
    corpus.prepare()
    source = SimpleNamespace(list_tools=AsyncMock(return_value=[]),
                             call_tool=AsyncMock(side_effect=AssertionError("Unexpected source call")))
    sessions = []

    @asynccontextmanager
    async def servers(study, root, audit, budget, treatment):
        assert budget.limit == 0
        sessions.append(treatment)
        yield source, None

    monkeypatch.setattr(trial.first, "servers", servers)
    monkeypatch.setattr(trial, "codex_episode", AsyncMock(return_value={"status": "complete"}))
    monkeypatch.setattr(trial, "usage_snapshot", Mock(return_value=deepcopy(report()["usage"])))
    return SimpleNamespace(**vars(corpus), source=source, sessions=sessions)


@pytest.mark.asyncio
async def test_both_authors_receive_source_only_exact_grants_and_bounded_calls(prepared):
    for arm in trial.ORDER:
        result = await trial.actor(prepared.root, arm)
        assert result["process_complete"] is True and result["provider_attempts"] == 0
        assert result["original_captures_unchanged"] is True
        args, kwargs = trial.codex_episode.call_args
        bridge = args[0]
        assert bridge.native is None and bridge.source_tools == trial.first.SOURCE_TOOLS
        assert bridge.workspace == prepared.root/arm/"workspace"
        assert kwargs["workspace_read_paths"] == [str(prepared.public), str(bridge.directory)]
        assert kwargs["key"] == "" and kwargs["budget"].limit == 0
        assert kwargs["max_tool_calls"] == trial.LIMITS["mcp_tools"]
        assert kwargs["max_workspace_tool_calls"] == trial.LIMITS["workspace_tools"]
        assert kwargs["timeout_seconds"] == trial.LIMITS["response_seconds"]
        assert kwargs["strict_single_turn_usage"] and kwargs["enforce_wall_response_timeout"]
        assert (prepared.root/f"{arm}.claimed").exists()
        saved = trial.shared.read(prepared.root/f"{arm}.json")
        assert saved["frontier_invocations"] == 1
        assert "deployment_complete" not in saved and "business_success" not in saved
    assert prepared.sessions == [False, False]
    assert trial.codex_episode.await_count == 2
    prepared.source.call_tool.assert_not_awaited()
    with pytest.raises(ValueError, match="admission stopped"):
        await trial.actor(prepared.root, "baseline")


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["order", "unreported", "incomplete", "unknown", "input_cap", "uncached_cap", "workspace", "lock"])
async def test_admission_stops_before_another_author_or_source_launch(prepared, defect):
    arm = "signalweave"
    if defect in {"incomplete", "unknown", "input_cap", "uncached_cap"}:
        prior = report()
        if defect == "incomplete":
            prior["process_complete"] = False
        elif defect == "unknown":
            prior["usage"] = {"known": False}
        else:
            key, cap = (("input_tokens", "between_actor_input_stop") if defect == "input_cap"
                        else ("uncached_input_tokens", "between_actor_uncached_stop"))
            prior["usage"]["usage"][key] = trial.LIMITS[cap]
        (prepared.root/"baseline.claimed").write_text("prior attempt")
        write(prepared.root/"baseline.json", prior)
    elif defect == "unreported":
        (prepared.root/"baseline.claimed").write_text("interrupted attempt")
    elif defect == "workspace":
        arm = "baseline"
        (prepared.root/arm/"workspace/working-notes.md").write_text("Unadmitted edit")
    elif defect == "lock":
        arm = "baseline"
        (prepared.root/"actor-running.lock").write_text("another coordinator")
    with pytest.raises((ValueError, FileExistsError)):
        await trial.actor(prepared.root, arm)
    assert prepared.sessions == []
    trial.codex_episode.assert_not_awaited()
    assert not (prepared.root/f"{arm}.claimed").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["exception", "unknown_usage", "capture_changed"])
async def test_failed_attempt_retains_claim_record_and_never_becomes_deployment_success(prepared, defect):
    if defect == "exception":
        trial.codex_episode.side_effect = RuntimeError("offline author failure")
    elif defect == "unknown_usage":
        trial.usage_snapshot.return_value = {"known": False}
    else:
        async def mutate_capture(*args, **kwargs):
            path = args[0].directory/"response-000001.json"
            path.write_text("Rewritten original")
            return {"status": "complete"}
        trial.codex_episode.side_effect = mutate_capture
    result = await trial.actor(prepared.root, "baseline")
    assert result["process_complete"] is False
    assert result["provider_attempts"] == 0
    assert (prepared.root/"baseline.claimed").exists()
    path = prepared.root/"baseline.json"
    retained = path.read_bytes()
    assert trial.shared.read(path)["frontier_invocations"] == 1
    with pytest.raises(ValueError):
        await trial.actor(prepared.root, "baseline")
    assert path.read_bytes() == retained
    assert trial.codex_episode.await_count == 1

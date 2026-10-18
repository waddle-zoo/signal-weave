"""Workspace continuation controls, not analyst/customer outcomes."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from evaluations import redwood_workspace_compatibility as study
from evaluations.bootstrap_agent_trial import Audit
from evaluations.harbor_workflow_preflight import _sha


def test_seed_copies_only_the_arms_actual_prior_work_and_validates_exports(tmp_path):
    original = tmp_path/"prior"
    original.mkdir()
    csv = original/"old.csv"
    csv.write_text("group,late\nexample,2\n")
    provenance = original/"old.csv.provenance.json"
    provenance.write_text(json.dumps({"source_as_of": "previous cutoff"}))
    previous = {"notes": "Actual old method; dated results are history",
        "briefs": [{"body": "Actual earlier brief"}], "artifact_manifest": {
            "old.csv": {"csv_sha256": _sha(csv), "provenance_sha256": _sha(provenance)}}}
    root = tmp_path/"workspace"
    inventory = study.seed_workspace(root, previous, original)
    assert (root/"working-notes.md").read_text() == previous["notes"]
    assert (root/"previous-brief.md").read_text() == previous["briefs"][0]["body"]
    assert inventory["evidence/old.csv"]["sha256"] == _sha(csv)
    assert set(inventory) == {"working-notes.md", "previous-brief.md", "owner-reference.json",
        "retained-evidence.json", "evidence/old.csv", "evidence/old.csv.provenance.json"}
    assert "expected_outcome" not in (root/"owner-reference.json").read_text()
    csv.write_text("changed after review")
    with pytest.raises(ValueError, match="changed"):
        study.seed_workspace(tmp_path/"different-workspace", previous, original)


def test_workspace_inventory_catches_symlinks_and_preserves_actual_file_hashes(tmp_path):
    tmp_path.chmod(0o700)
    file = tmp_path/"brief.md"
    file.write_text("A real local draft")
    before = study.workspace_inventory(tmp_path)
    file.write_text("An updated local draft")
    assert before["brief.md"]["sha256"] != study.workspace_inventory(tmp_path)["brief.md"]["sha256"]
    (tmp_path/"outside-link").symlink_to(tmp_path.parent)
    with pytest.raises(ValueError, match="symlink"):
        study.workspace_inventory(tmp_path)


async def test_workspace_tools_keep_all_company_and_normal_native_tools_without_file_substitutes():
    def tool(name):
        return SimpleNamespace(name=name, description="Actual tool", inputSchema={"type": "object"})

    source = SimpleNamespace(list_tools=AsyncMock(return_value=[tool("query_readonly"), tool("list_assets")]))
    native = SimpleNamespace(instructions="The native server's actual instructions", list_tools=AsyncMock(return_value=[tool("evaluate_insight_card"),
        tool("inspect_resource"), tool("onboard_insight_card"), tool("approve_insight_card")]))
    actor = study.WorkspaceTools(source, Audit(), study.parent_method.OWNER, native=native, phase="recurring")
    assert actor.mcp_instructions == native.instructions
    assert {row["name"] for row in await actor.specs()} == {
        "query_readonly", "list_assets", "evaluate_insight_card", "inspect_resource",
        "onboard_insight_card", "approve_insight_card"}
    actor._call_source, actor._call_native = AsyncMock(return_value={"rows": []}), AsyncMock(return_value={"outcome": "ignore"})
    assert await actor.call("query_readonly", {"sql": "SELECT 1"}) == {"rows": []}
    assert await actor.call("evaluate_insight_card", {"card_id": "approved"}) == {"outcome": "ignore"}
    with pytest.raises(ValueError, match="not available"):
        await actor.call("save_working_notes", {"notes": "Not an actual file"})


async def test_workspace_tools_reject_ambiguous_company_and_native_names():
    tools = [{"name": "same", "parameters": {"type": "object"}}]
    source = SimpleNamespace(list_tools=AsyncMock(return_value=tools))
    native = SimpleNamespace(list_tools=AsyncMock(return_value=tools))
    actor = study.WorkspaceTools(source, Audit(), study.parent_method.OWNER, native=native)
    with pytest.raises(ValueError, match="overlap"):
        await actor.specs()


async def test_wrong_predecessor_is_rejected_before_creating_a_study(tmp_path, monkeypatch):
    parent = tmp_path/"parent"
    parent.mkdir()
    (parent/"study.json").write_text(json.dumps({"protocol": "a different trial"}))
    monkeypatch.setattr(study, "verify_binary", lambda *args: {})
    monkeypatch.setattr(study, "pinned_codex", AsyncMock(return_value={"path": "unused"}))
    with pytest.raises(ValueError, match="Predecessor"):
        await study.prepare(tmp_path/"new-study", parent, tmp_path/"binary", "unused")
    assert not (tmp_path/"new-study").exists()


def test_zero_model_sandbox_preflight_uses_filtered_environment(tmp_path, monkeypatch):
    workspace = tmp_path/"workspace"
    workspace.mkdir(mode=0o700)
    canary = tmp_path/"private-canary"
    canary.write_text("private grader canary")
    listener = SimpleNamespace(server_port=1234, serve_forever=lambda: None,
        shutdown=lambda: None, server_close=lambda: None)
    monkeypatch.setattr(study, "ThreadingHTTPServer", lambda *args: listener)
    monkeypatch.setattr(study, "child_environment", lambda: {"PATH": "/system/tools"})
    run = Mock(return_value=SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
        "workspace_read_write": True, "private_read_write_denied": True, "command_network_denied": True,
        "private_read_paths_denied": 1})))
    monkeypatch.setattr(study.subprocess, "run", run)
    result = study.sandbox_preflight("codex", workspace, canary, [tmp_path/"private-source"])
    assert run.call_args.kwargs["env"] == {"PATH": "/system/tools"}
    assert result["analyst_invocations"] == result["provider_requests"] == 0
    assert str(tmp_path/"private-source") in run.call_args.args[0]

"""Offline contracts for forwarding real MCP payloads to an ordinary workspace."""

from __future__ import annotations

import hashlib
import json
import stat
from copy import deepcopy
from pathlib import Path

import pytest
from mcp import types

from evaluations.bootstrap_agent_trial import Audit
from evaluations.harbor_workflow_actor import WorkspaceSourceActor


def tool(name: str) -> types.Tool:
    return types.Tool(
        name=name,
        description=f"Actual tool contract for {name}",
        inputSchema={
            "type": "object",
            "properties": {"sql": {"type": "string"}, "row_limit": {"type": "integer"}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    )


class Facade:
    def __init__(self, names, structured=None, *, content=None, instructions=None):
        self.tools = [tool(name) for name in names]
        self.structured = structured
        self.content = content if content is not None else [types.TextContent(type="text", text="raw")]
        self.instructions = instructions
        self.calls = []

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        return self.content, self.structured


def workspace(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


@pytest.mark.asyncio
async def test_specs_expose_only_allowed_actual_company_tools_and_all_actual_native_tools(tmp_path):
    source = Facade(["query_readonly", "inspect_asset", "unconfigured"])
    native = Facade(
        ["get_signalweave_guide", "evaluate_insight_card", "get_decision_receipt", "native_extra"],
        instructions="Native instructions unchanged",
    )
    allowed = {"query_readonly", "inspect_asset", "not_actually_advertised"}
    baseline = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "b"), source_tools=allowed)
    treatment = WorkspaceSourceActor(
        source, Audit(), workspace(tmp_path / "t"), source_tools=allowed, native=native,
    )
    baseline_specs = await baseline.specs()
    treatment_specs = await treatment.specs()

    assert [spec["name"] for spec in baseline_specs] == ["company_query_readonly", "company_inspect_asset"]
    assert treatment_specs[:2] == baseline_specs
    assert treatment_specs[2:] == [
        {"name": item.name, "description": item.description, "parameters": item.inputSchema}
        for item in native.tools
    ]
    assert treatment.mcp_instructions == native.instructions
    assert baseline.mcp_instructions is None
    assert baseline.treatment is False and treatment.treatment is True
    for actor in (baseline, treatment):
        assert actor.phase == "onboarding"
        assert actor.setup_complete is False and actor.submission is None
        assert not {"submit", "read_file", "write_file", "save_brief", "ask_owner"} & {
            spec["name"] for spec in await actor.specs()
        }


@pytest.mark.asyncio
async def test_both_arms_forward_same_arguments_and_preserve_structured_and_raw_content(tmp_path):
    original = {"columns": ["unknown", "zero", "empty"], "rows": [[None, 0, ""]],
                "nested": {"values": [False, 2.5, {"original": None}]}}
    raw = [types.TextContent(type="text", text='{"original": "wire content"}')]
    arguments = {"sql": "SELECT original FROM actual_table -- ../../outside", "row_limit": 1000}
    forwarded = []
    for arm in ("baseline", "treatment"):
        source = Facade(["query_readonly"], original, content=raw)
        native = Facade(["get_signalweave_guide"]) if arm == "treatment" else None
        audit = Audit()
        root = workspace(tmp_path / arm)
        actor = WorkspaceSourceActor(source, audit, root, source_tools={"query_readonly"}, native=native)
        result = await actor.call("company_query_readonly", arguments)
        locator = result.pop("_caller_artifact")
        path = Path(locator["path"])
        saved = json.loads(path.read_bytes())
        assert result == original
        assert saved["structured"] == original
        assert saved["content"] == [block.model_dump(mode="json") for block in raw]
        assert saved["arguments"] == arguments
        assert saved["name"] == "company_query_readonly"
        assert saved["redacted"] is False and locator["redacted"] is False
        assert path.parent == root / "tool-responses"
        assert path.name == "response-000001.json"
        assert path.is_absolute()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert locator["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert audit.events[-1]["name"] == "company_query_readonly"
        assert audit.events[-1]["arguments"] == arguments
        assert audit.events[-1]["artifact"] == locator
        assert source.calls == [("query_readonly", arguments)]
        if native:
            assert native.calls == []
        forwarded.append(result)
    assert forwarded[0] == forwarded[1]
    assert "_caller_artifact" not in original


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [None, [None, 0, "", {"nested": True}], "a,b\n,0\n"])
async def test_non_dict_and_plain_csv_do_not_invent_structured_results(tmp_path, structured):
    content = [types.TextContent(type="text", text="a,b\n,0\n")]
    source = Facade(["query"], structured, content=content)
    actor = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "w"), source_tools={"query"})
    result = await actor.call("company_query", {})

    assert result["source_result"] == (
        structured if structured is not None else [block.model_dump(mode="json") for block in content]
    )
    saved = json.loads(Path(result["_caller_artifact"]["path"]).read_bytes())
    assert saved["structured"] == structured
    assert saved["content"][0]["text"] == "a,b\n,0\n"


@pytest.mark.asyncio
async def test_native_result_fields_are_unchanged_and_names_are_not_routed_by_prefix(tmp_path):
    original = {"status": "deferred", "outcome": None, "receipt": {"pages": [0, "", None]},
                "provider": {"attempts": 0}, "source_result": "native value"}
    source = Facade(["query"], {"wrong": True})
    native = Facade(["evaluate_insight_card", "company_native_tool"], original)
    actor = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "w"),
                                 source_tools={"query"}, native=native)
    for name in ("evaluate_insight_card", "company_native_tool"):
        result = await actor.call(name, {"card_id": "unchanged"})
        result.pop("_caller_artifact")
        assert result == original
    assert source.calls == []
    assert [name for name, _ in native.calls] == ["evaluate_insight_card", "company_native_tool"]
    assert sorted(path.name for path in actor.directory.iterdir()) == [
        "response-000001.json", "response-000002.json",
    ]


@pytest.mark.asyncio
async def test_dispatch_rechecks_permissions_and_current_advertisement(tmp_path):
    source = Facade(["query", "hidden"])
    native = Facade(["get_insight_card"])
    allowed = {"query", "missing"}
    actor = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "w"),
                                 source_tools=allowed, native=native)
    await actor.specs()
    allowed.add("hidden")
    source.tools = [tool("hidden")]
    native.tools = []
    for name in ("query", "company_query", "company_hidden", "company_missing", "get_insight_card",
                 "evaluate_insight_card", "submit", "read_file"):
        with pytest.raises(ValueError, match="tool not available"):
            await actor.call(name, {})
    assert source.calls == native.calls == []
    assert list(actor.directory.iterdir()) == []


@pytest.mark.asyncio
async def test_reserved_locator_collision_retains_original_and_fails_clearly(tmp_path):
    original = {"_caller_artifact": {"source_owned": True}, "nested": {"value": None}}
    source = Facade(["query"], original)
    actor = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "w"), source_tools={"query"})
    with pytest.raises(ValueError, match="reserved _caller_artifact"):
        await actor.call("company_query", {})
    assert json.loads(next(actor.directory.iterdir()).read_bytes())["structured"] == original
    assert original["_caller_artifact"] == {"source_owned": True}


@pytest.mark.asyncio
async def test_redaction_applies_before_persistence_and_locator_reports_it(tmp_path):
    secret = "private-credential"
    original = {"nested": [None, secret]}
    source = Facade(["query"], original, content=[types.TextContent(type="text", text=secret)])
    audit = Audit(secrets=(secret,))
    actor = WorkspaceSourceActor(source, audit, workspace(tmp_path / "w"), source_tools={"query"})
    result = await actor.call("company_query", {"sql": secret})
    locator = result["_caller_artifact"]
    content = Path(locator["path"]).read_bytes()
    saved = json.loads(content)
    assert result["nested"] == [None, secret]
    assert secret.encode() not in content
    assert secret not in json.dumps(audit.events)
    assert saved["structured"] == {"nested": [None, "[REDACTED]"]}
    assert saved["content"][0]["text"] == "[REDACTED]"
    assert saved["arguments"] == {"sql": "[REDACTED]"}
    assert saved["redacted"] is True and locator["redacted"] is True
    assert locator["sha256"] == hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("symlink", [False, True])
async def test_generated_response_paths_never_overwrite_existing_files_or_symlinks(tmp_path, symlink):
    source = Facade(["query"], {"value": 1})
    actor = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "w"), source_tools={"query"})
    target = tmp_path / "outside"
    target.write_text("keep me", encoding="utf-8")
    collision = actor.directory / "response-000001.json"
    if symlink:
        collision.symlink_to(target)
    else:
        collision.write_text("existing response", encoding="utf-8")
    with pytest.raises(FileExistsError):
        await actor.call("company_query", {})
    assert source.calls == []
    assert target.read_text(encoding="utf-8") == "keep me"
    assert collision.is_symlink() if symlink else collision.read_text() == "existing response"


def test_workspace_and_response_roots_must_be_private_real_directories(tmp_path):
    root = workspace(tmp_path / "w")
    linked = tmp_path / "linked"
    linked.symlink_to(root, target_is_directory=True)
    source = Facade(["query"])
    with pytest.raises(ValueError, match="symlink"):
        WorkspaceSourceActor(source, Audit(), linked, source_tools={"query"})
    root.chmod(0o755)
    with pytest.raises(ValueError, match="0700"):
        WorkspaceSourceActor(source, Audit(), root, source_tools={"query"})
    root.chmod(0o700)
    (root / "tool-responses").symlink_to(workspace(tmp_path / "outside"), target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        WorkspaceSourceActor(source, Audit(), root, source_tools={"query"})


@pytest.mark.asyncio
async def test_response_directory_is_revalidated_before_dispatch(tmp_path):
    source = Facade(["query"])
    actor = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "w"), source_tools={"query"})
    actor.directory.rmdir()
    outside = workspace(tmp_path / "outside")
    actor.directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        await actor.call("company_query", {})
    assert source.calls == []
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_exposed_name_collisions_fail_before_dispatch(tmp_path):
    source = Facade(["query"])
    native = Facade(["company_query"])
    actor = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "w"),
                                 source_tools={"query"}, native=native)
    with pytest.raises(ValueError, match="distinct"):
        await actor.specs()
    with pytest.raises(ValueError, match="distinct"):
        await actor.call("company_query", {})
    assert source.calls == native.calls == []

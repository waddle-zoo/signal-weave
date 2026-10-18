"""Offline contracts for forwarding real MCP payloads to an ordinary workspace."""

from __future__ import annotations

import csv
import hashlib
import io
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
    locators = []
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
        locators.append({key: value for key, value in locator.items() if key != "path"})
    assert forwarded[0] == forwarded[1]
    assert locators[0] == locators[1]
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
@pytest.mark.parametrize("use_native", [False, True])
@pytest.mark.parametrize("content_only", [False, True])
async def test_locator_reads_saved_envelope_for_calculation_without_requery_or_rewrite(
    tmp_path, use_native, content_only,
):
    structured = None if content_only else {
        "result": {"rows": [{"value": None}, {"value": 0}, {"value": ""},
                            {"value": 2.5}, {"value": 7.5}]},
    }
    content = [types.TextContent(type="text", text="value\n0\n2.5\n7.5\n")]
    source = Facade(["query"], structured, content=content)
    native = Facade(["inspect"], structured, content=content) if use_native else None
    audit = Audit()
    actor = WorkspaceSourceActor(source, audit, workspace(tmp_path / "w"),
                                 source_tools={"query"}, native=native)
    name = "inspect" if use_native else "company_query"
    arguments = {"sql": "SELECT value FROM records", "row_limit": 20}
    result = await actor.call(name, arguments)
    locator = result["_caller_artifact"]
    path = Path(locator["path"])
    original_bytes = path.read_bytes()
    expected = {
        "name": name, "arguments": arguments,
        "structured": structured,
        "content": [block.model_dump(mode="json") for block in content], "redacted": False,
    }
    assert original_bytes == json.dumps(
        expected, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    assert locator["format"] == "mcp_response_envelope_json"
    assert locator["already_saved"] is True and locator["read_without_rewriting"] is True
    saved = json.loads(original_bytes)

    def read_path(keys):
        value = saved
        for key in keys:
            value = value[key]
        return value

    assert read_path(locator["structured_path"]) == structured
    assert read_path(locator["content_path"]) == expected["content"]
    data = read_path(locator["data_path"])
    if content_only:
        assert data == expected["content"]
        values = [float(row["value"]) for row in csv.DictReader(io.StringIO(data[0]["text"]))]
    else:
        assert data == structured
        values = [row["value"] for row in data["result"]["rows"]]
        assert values[:3] == [None, 0, ""]
        values = [value for value in values if isinstance(value, (int, float))]
    assert sum(values) == 10
    assert path.read_bytes() == original_bytes
    assert hashlib.sha256(path.read_bytes()).hexdigest() == locator["sha256"]
    backend = native if use_native else source
    assert backend.calls == [("inspect" if use_native else "query", arguments)]
    assert source.calls == ([] if use_native else [("query", arguments)])
    assert audit.events[-1]["artifact"] == locator
    assert actor._sequence == 1
    assert list(actor.directory.iterdir()) == [path]


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [None, {}, [], "", 0, False])
async def test_locator_falls_back_only_for_null_not_empty_structured_values(tmp_path, structured):
    source = Facade(["query"], structured, content=[])
    actor = WorkspaceSourceActor(source, Audit(), workspace(tmp_path / "w"), source_tools={"query"})
    result = await actor.call("company_query", {})
    locator = result["_caller_artifact"]
    original_bytes = Path(locator["path"]).read_bytes()
    saved = json.loads(original_bytes)
    assert locator["data_path"] == (["content"] if structured is None else ["structured"])
    assert saved[locator["data_path"][0]] == ([] if structured is None else structured)
    assert type(saved["structured"]) is type(structured)
    assert saved["content"] == []
    assert source.calls == [("query", {})]
    assert hashlib.sha256(original_bytes).hexdigest() == locator["sha256"]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("use_native", [False, True])
async def test_fresh_actor_continues_existing_receipts_without_changing_them(tmp_path, use_native):
    source = Facade(["query"], {"value": None})
    native = Facade(["inspect"], {"value": 0}) if use_native else None
    root = workspace(tmp_path / "w")
    actor = WorkspaceSourceActor(source, Audit(), root, source_tools={"query"}, native=native)
    name = "inspect" if use_native else "company_query"
    for number in (1, 2):
        await actor.call(name, {"row_limit": number})
    original = {path.name: path.read_bytes() for path in actor.directory.iterdir()}
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in original.items()}
    backend = native if use_native else source
    prior_calls = deepcopy(backend.calls)

    continued = WorkspaceSourceActor(source, Audit(), root, source_tools={"query"}, native=native)
    assert backend.calls == prior_calls
    result = await continued.call(name, {"row_limit": 3})

    assert Path(result["_caller_artifact"]["path"]).name == "response-000003.json"
    assert backend.calls == [*prior_calls, ("inspect" if use_native else "query", {"row_limit": 3})]
    assert sorted(path.name for path in actor.directory.iterdir()) == [
        "response-000001.json", "response-000002.json", "response-000003.json",
    ]
    for filename, value in original.items():
        assert (actor.directory / filename).read_bytes() == value
        assert hashlib.sha256((actor.directory / filename).read_bytes()).hexdigest() == hashes[filename]
    if use_native:
        assert source.calls == []


@pytest.mark.asyncio
async def test_existing_sequence_uses_maximum_and_ignores_unrelated_names_and_directories(tmp_path):
    root = workspace(tmp_path / "w")
    directory = workspace(root / "tool-responses")
    for name in ("response-000010.json", "response-000002.json", "response-000009.json",
                 "response-999999.json.bak", "response-1234567.json", "response-1.json",
                 "response-abcdef.json", "prefix-response-999999.json"):
        (directory / name).write_text("unchanged", encoding="utf-8")
    nested = workspace(directory / "unrelated")
    (nested / "response-999999.json").symlink_to(tmp_path / "missing")
    (directory / "notes.json").symlink_to(tmp_path / "missing")
    source = Facade(["query"], {"value": 1})

    actor = WorkspaceSourceActor(source, Audit(), root, source_tools={"query"})
    assert source.calls == []
    result = await actor.call("company_query", {})

    assert Path(result["_caller_artifact"]["path"]).name == "response-000011.json"
    assert source.calls == [("query", {})]
    assert (directory / "response-000010.json").read_text() == "unchanged"
    assert (directory / "notes.json").is_symlink()


@pytest.mark.parametrize("entry_kind", ["symlink", "dangling_symlink", "directory"])
def test_existing_matching_receipts_must_be_regular_files(tmp_path, entry_kind):
    root = workspace(tmp_path / "w")
    directory = workspace(root / "tool-responses")
    target = tmp_path / "outside"
    if entry_kind != "dangling_symlink":
        target.write_text("not a receipt", encoding="utf-8")
    entry = directory / "response-000001.json"
    if entry_kind == "directory":
        entry.mkdir()
    else:
        entry.symlink_to(target)
    source = Facade(["query"])

    with pytest.raises(ValueError, match="regular file"):
        WorkspaceSourceActor(source, Audit(), root, source_tools={"query"})

    assert source.calls == []
    if target.exists():
        assert target.read_text() == "not a receipt"


@pytest.mark.asyncio
async def test_existing_sequence_exhaustion_fails_before_dispatch(tmp_path):
    root = workspace(tmp_path / "w")
    directory = workspace(root / "tool-responses")
    last = directory / "response-999999.json"
    last.write_text("keep", encoding="utf-8")
    source = Facade(["query"])
    actor = WorkspaceSourceActor(source, Audit(), root, source_tools={"query"})

    with pytest.raises(ValueError, match="sequence exhausted"):
        await actor.call("company_query", {})

    assert source.calls == []
    assert last.read_text() == "keep"
    assert list(directory.iterdir()) == [last]


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

"""Offline guards for the persistent-session capture; no inference or native calls."""

import copy
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluations.harbor_history import materialize_snapshot, weekly_cutoffs
from evaluations.harbor_history_mcp import SOURCE_ID, export_query, query_readonly
from evaluations.harbor_workflow_history import make_queue_history
from evaluations.harbor_workflow_preflight import _activate, _definitions, _sha, _validate_snapshot
from evaluations.harbor_workflow_sources import QUEUE_RESOURCE, build_workflow_manifest


def test_activation_updates_only_an_owned_copy_and_leaves_inputs_immutable(tmp_path):
    first, second, active = (tmp_path / name for name in ("first.sqlite3", "second.sqlite3", "active.sqlite3"))
    first.write_bytes(b"first source")
    second.write_bytes(b"second source")
    digest = _activate(first, active, None)
    assert digest == _sha(first) and active.read_bytes() == first.read_bytes()
    assert active.stat().st_mode & 0o777 == 0o600
    later = _activate(second, active, digest)
    assert later == _sha(second) and active.read_bytes() == second.read_bytes()
    assert first.read_bytes() == b"first source" and second.read_bytes() == b"second source"
    assert not active.with_suffix(".next").exists()


@pytest.mark.parametrize("fault", ["foreign", "changed", "missing", "symlink", "existing-stage"])
def test_activation_refuses_unowned_or_changed_targets_without_erasing_them(tmp_path, fault):
    source, active, foreign = (tmp_path / name for name in ("source.sqlite3", "active.sqlite3", "foreign.sqlite3"))
    source.write_bytes(b"source")
    foreign.write_bytes(b"keep")
    if fault == "foreign":
        active.write_bytes(b"unowned")
        previous = None
    elif fault == "symlink":
        active.symlink_to(foreign)
        previous = _sha(foreign)
    else:
        previous = _activate(source, active, None)
        if fault == "changed":
            active.write_bytes(b"changed")
        elif fault == "missing":
            active.unlink()
        else:
            active.with_suffix(".next").write_bytes(b"prior diagnostic")
    before = active.read_bytes() if active.exists() else None
    with pytest.raises((ValueError, FileExistsError)):
        _activate(source, active, previous)
    assert foreign.read_bytes() == b"keep" and source.read_bytes() == b"source"
    assert (active.read_bytes() if active.exists() else None) == before
    if fault == "existing-stage":
        assert active.with_suffix(".next").read_bytes() == b"prior diagnostic"


@pytest.fixture
def export_fixture(tmp_path):
    history = make_queue_history(complete_background_responses=True, recorded_response=False)
    cutoff = weekly_cutoffs(history)[0]
    path = materialize_snapshot(history, cutoff, tmp_path / "source.sqlite3")
    manifest = build_workflow_manifest(path, Path("/repo/.venv/bin/python"))
    definition, = [row for row in _definitions(manifest) if row["resource"] == QUEUE_RESOURCE]
    value = export_query(path, definition["sql"], definition["resource"], "priority-queue", definition["title"])
    direct = [row["values"] for row in value["evidence"]]
    provenance = query_readonly(path, definition["sql"])["assets_read"]
    return value, definition, cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"), direct, provenance


def test_export_validation_keeps_alias_provenance_and_exact_current_values(export_fixture):
    value, definition, as_of, direct, provenance = export_fixture
    value["source_key"] = "native-inspection-alias"
    for row in value["evidence"]:
        row["source_key"] = value["source_key"]
    result = _validate_snapshot(value, definition, as_of, direct, provenance)
    assert result["source_key"] == "native-inspection-alias"
    assert result["values"] == direct and result["evidence_rows"] == 1
    assert result["provenance"] and result["source_captured_at"] == as_of


@pytest.mark.parametrize("fault", ["time", "value", "alias", "query", "provenance", "wrong-provenance", "wrong-assets", "origin", "empty"])
def test_changed_or_untraceable_export_is_not_a_source_match(export_fixture, fault):
    original, definition, as_of, direct, provenance = export_fixture
    value = copy.deepcopy(original)
    if fault == "time":
        value["source_captured_at"] = "2000-01-01T00:00:00Z"
    elif fault == "value":
        value["evidence"][0]["values"]["known_ticket_count"] = -1
    elif fault == "alias":
        value["evidence"][0]["source_key"] = "another-source"
    elif fault == "query":
        value["metadata"]["saved_query_definition"]["sql"] = "SELECT 1"
    elif fault == "provenance":
        value["evidence"][0]["provenance"] = []
    elif fault == "wrong-provenance":
        value["evidence"][0]["provenance"] = ["unrelated:wrong-source"]
    elif fault == "wrong-assets":
        value["metadata"]["assets_read"] = ["unrelated:wrong-source"]
    elif fault == "origin":
        value["evidence"][0]["origin"] = "derived"
    else:
        value["evidence"] = []
        direct = []
    with pytest.raises(ValueError):
        _validate_snapshot(value, definition, as_of, direct, provenance)


@pytest.mark.asyncio
async def test_successful_companion_result_survives_a_later_native_failure(tmp_path, monkeypatch):
    from evaluations import harbor_workflow_preflight as capture
    from evaluations.bootstrap_agent_trial import Audit, RequestBudget

    history = make_queue_history(complete_background_responses=True, recorded_response=False)
    cutoff = weekly_cutoffs(history)[0]
    snapshot = materialize_snapshot(history, cutoff, tmp_path / "input.sqlite3")
    work = tmp_path / "private"
    work.mkdir()
    binary = Path("/not-executed/native")
    definitions = _definitions(build_workflow_manifest(snapshot, Path("/not-executed/python")))

    @asynccontextmanager
    async def fake_stdio(parameters, **kwargs):
        yield ("native" if parameters.command == str(binary) else "companion", None)

    @asynccontextmanager
    async def fake_proxy(*args):
        yield "http://127.0.0.1:1/not-contacted"

    class Session:
        def __init__(self, kind, unused):
            self.kind = kind

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def list_tools(self):
            names = capture.AGENT_PROFILE_TOOLS if self.kind == "native" else {
                "list_assets", "inspect_asset", "query_readonly", "export_query", "list_saved_queries",
            }
            return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in names])

    async def fake_call(server, tool, arguments):
        if tool == "get_signalweave_guide":
            return {"present": True}
        if tool == "search_catalog":
            return {"has_more": False, "resources": [{"resource": row["resource"]} for row in definitions]}
        if tool == "list_saved_queries":
            return {"queries": definitions, "source": {"identifier": SOURCE_ID, "as_of_utc": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")}}
        if tool == "export_query":
            return export_query(work / "active.sqlite3", **arguments)
        if tool == "inspect_resource":
            raise RuntimeError("injected native failure after companion success")
        raise AssertionError("unexpected fake tool")

    monkeypatch.setattr(capture, "stdio_client", fake_stdio)
    monkeypatch.setattr(capture, "ClientSession", Session)
    monkeypatch.setattr(capture, "_initialize_mcp_session", AsyncMock(return_value=SimpleNamespace(instructions="")))
    monkeypatch.setattr(capture, "_setup", AsyncMock())
    monkeypatch.setattr(capture, "_jev_proxy", fake_proxy)
    monkeypatch.setattr(capture, "_call", fake_call)
    report = {"observations": []}
    with pytest.raises(RuntimeError, match="after companion success"):
        await capture._capture(binary, work, [(snapshot, cutoff)], Audit(), RequestBudget(0), report)
    retained = report["observations"][0]["exports"][0]
    assert retained["completed"] is False and retained["stage"] == "native_inspection"
    assert retained["companion"]["evidence_rows"] > 0 and "native" not in retained
    assert retained["companion"]["provenance"] == [retained["expected_provenance"]]

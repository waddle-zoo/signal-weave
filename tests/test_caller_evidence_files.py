from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest

from evaluations import redwood_company
from evaluations.caller_evidence_files import SCOPE_NOTE, EvidenceFileActor
from examples.harbor_help.company_mcp import query_readonly
from examples.harbor_help.seed import generate_database


class Audit:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    def emit(self, kind: str, **fields: Any) -> None:
        self.events.append({"kind": kind, **fields})


class QueryDelegate:
    def __init__(self, database: Path):
        self.database = database
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.last_result: dict[str, Any] | None = None
        self.marker = "delegated attribute"

    async def specs(self):
        return [{"name": "query_readonly", "parameters": {"type": "object"}}]

    async def call(self, name: str, arguments: dict[str, Any]):
        self.calls.append((name, arguments))
        if name == "query_readonly":
            self.last_result = query_readonly(
                self.database, arguments["sql"], row_limit=arguments["row_limit"]
            )
            return self.last_result
        return {"delegated": name, "arguments": arguments}


class StaticDelegate(QueryDelegate):
    def __init__(self, result: dict[str, Any]):
        self.database = Path("unused")
        self.calls = []
        self.last_result = result
        self.marker = "delegated attribute"

    async def call(self, name: str, arguments: dict[str, Any]):
        self.calls.append((name, arguments))
        return self.last_result


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return generate_database(tmp_path / "harbor-help.sqlite3", seed=20261016)


def make_actor(tmp_path: Path, delegate: Any, audience=("owner-a", "owner-b")):
    audit = Audit()
    actor = EvidenceFileActor(delegate, tmp_path / "caller-files", audience, audit)
    return actor, audit


@pytest.mark.asyncio
async def test_actual_query_rows_roundtrip_and_existing_actor_surface_is_delegated(
    tmp_path: Path, database: Path
):
    delegate = QueryDelegate(database)
    actor, audit = make_actor(tmp_path, delegate)
    sql = "SELECT ticket_id, priority FROM tickets ORDER BY ticket_id LIMIT 4"

    tools = await actor.specs()
    assert {tool["name"] for tool in tools} == {
        "query_readonly",
        "export_query_csv",
        "read_evidence_file",
    }
    assert actor.marker == delegate.marker
    assert await actor.call("existing_tool", {"value": 1}) == {
        "delegated": "existing_tool",
        "arguments": {"value": 1},
    }

    exported = await actor.export_query_csv(
        sql, "tickets.csv", recipients=["owner-a"], row_limit=10
    )
    assert delegate.calls[-1] == (
        "query_readonly",
        {"sql": sql, "row_limit": 10},
    )
    assert delegate.last_result is not None
    actual = delegate.last_result
    parsed_csv = list(csv.reader(io.StringIO(Path(exported["path"]).read_text())))
    expected_rows = [
        ["" if value is None else str(value) for value in row] for row in actual["rows"]
    ]
    assert parsed_csv == [actual["columns"], *expected_rows]
    assert exported["row_count"] == len(actual["rows"])
    assert exported["columns"] == actual["columns"]
    assert exported["sample"] == actual["rows"][:3]
    assert exported["access_audience"] == ["owner-a"]
    assert exported["scope_note"] == SCOPE_NOTE

    event_text = json.dumps(audit.events)
    assert "caller_evidence_file.exported" in event_text
    assert sql not in event_text
    assert set(audit.events[0]) == {
        "kind",
        "row_count",
        "column_count",
        "byte_count",
        "recipient_count",
    }


@pytest.mark.asyncio
async def test_readback_checks_intended_audience_and_returns_hash_and_provenance(
    tmp_path: Path, database: Path
):
    delegate = QueryDelegate(database)
    actor, _audit = make_actor(tmp_path, delegate)
    exported = await actor.export_query_csv(
        "SELECT ticket_id FROM tickets ORDER BY ticket_id LIMIT 2",
        "audience.csv",
        recipients=["owner-a"],
    )

    readback = actor.read_evidence_file(exported["artifact_ref"], "owner-a")
    assert readback["content"] == Path(exported["path"]).read_text()
    assert readback["sha256"] == exported["sha256"]
    assert readback["provenance"]["access_audience"] == ["owner-a"]
    assert readback["provenance"]["scope_note"] == SCOPE_NOTE
    with pytest.raises(PermissionError, match="simulated artifact"):
        actor.read_evidence_file(exported["artifact_ref"], "owner-b")


@pytest.mark.asyncio
async def test_fresh_actor_resumes_only_its_manifested_files_for_the_intended_recipient(
    tmp_path: Path, database: Path
):
    original, _audit = make_actor(tmp_path, QueryDelegate(database))
    exported = await original.export_query_csv(
        "SELECT ticket_id FROM tickets ORDER BY ticket_id LIMIT 2",
        "onboarding.csv",
        recipients=["owner-a"],
    )
    manifest = json.loads(json.dumps(original.artifact_manifest))
    assert manifest["onboarding.csv"] == {
        "csv_sha256": exported["sha256"],
        "provenance_sha256": manifest["onboarding.csv"]["provenance_sha256"],
    }

    resumed = EvidenceFileActor(
        QueryDelegate(database),
        original.directory,
        ("owner-a", "owner-b"),
        Audit(),
        retained_manifest=manifest,
    )
    readback = resumed.read_evidence_file("onboarding.csv", "owner-a")
    assert readback["content"] == Path(exported["path"]).read_text(encoding="utf-8")
    assert resumed.artifact_manifest == manifest

    copied_manifest = resumed.artifact_manifest
    copied_manifest["onboarding.csv"]["csv_sha256"] = "0" * 64
    assert resumed.artifact_manifest == manifest
    with pytest.raises(PermissionError, match="authorized"):
        EvidenceFileActor(
            QueryDelegate(database),
            original.directory,
            ("owner-b",),
            Audit(),
            retained_manifest=manifest,
        )


@pytest.mark.asyncio
async def test_resume_rejects_tampering_unknown_manifest_and_implicit_existing_directory(
    tmp_path: Path, database: Path
):
    original, _audit = make_actor(tmp_path, QueryDelegate(database))
    exported = await original.export_query_csv(
        "SELECT ticket_id FROM tickets LIMIT 1", "kept.csv", recipients=["owner-a"]
    )
    manifest = original.artifact_manifest

    empty_manifest_actor = EvidenceFileActor(
        QueryDelegate(database), original.directory, ("owner-a",), Audit(), retained_manifest={}
    )
    with pytest.raises(FileNotFoundError, match="unknown local evidence artifact"):
        empty_manifest_actor.read_evidence_file("kept.csv", "owner-a")

    with pytest.raises(FileNotFoundError, match="retained evidence directory"):
        EvidenceFileActor(
            QueryDelegate(database),
            tmp_path / "missing-retained-directory",
            ("owner-a",),
            Audit(),
            retained_manifest={},
        )

    with pytest.raises(FileNotFoundError, match="unknown local evidence artifact"):
        EvidenceFileActor(
            QueryDelegate(database),
            original.directory,
            ("owner-a",),
            Audit(),
            retained_manifest={
                **manifest,
                "missing.csv": {"csv_sha256": "a" * 64, "provenance_sha256": "b" * 64},
            },
        )

    Path(exported["path"]).write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        EvidenceFileActor(
            QueryDelegate(database),
            original.directory,
            ("owner-a",),
            Audit(),
            retained_manifest=manifest,
        )
    with pytest.raises(FileExistsError, match="new and exclusively owned"):
        EvidenceFileActor(QueryDelegate(database), original.directory, ("owner-a",), Audit())


@pytest.mark.asyncio
async def test_metadata_retains_sql_source_retrieval_and_fixed_cutoff(
    tmp_path: Path, database: Path
):
    delegate = QueryDelegate(database)
    actor, _audit = make_actor(tmp_path, delegate)
    sql = (
        "SELECT week_start_utc, as_of_utc FROM weekly_open_backlog "
        "ORDER BY week_start_utc LIMIT 2"
    )
    exported = await actor.export_query_csv(sql, "backlog.csv", recipients=["owner-a"])
    readback = actor.read_evidence_file(exported["artifact_ref"], "owner-a")
    provenance = readback["provenance"]

    assert provenance["sql"] == sql
    assert provenance["source"] == delegate.last_result["source"]
    assert "final retrospective" in provenance["source"]["fixture_note"]
    assert provenance["source"]["retrieved_at_utc"]
    assert "harbor_help_raw_sqlite:weekly_open_backlog" in provenance["assets_read"]
    assert "as_of_utc" in provenance["columns"]
    assert provenance["row_count"] == len(delegate.last_result["rows"])
    assert str(delegate.last_result["rows"][0][1]) in readback["content"]
    with pytest.raises(PermissionError, match="simulated artifact"):
        actor.read_evidence_file(exported["artifact_ref"], "owner-b")


@pytest.mark.asyncio
async def test_source_as_of_clock_is_preserved_when_present(tmp_path: Path):
    source_path = redwood_company.create_snapshot(tmp_path / "redwood.sqlite3", 0)
    result = redwood_company.query(
        source_path, "SELECT shipment_id FROM shipments LIMIT 2", row_limit=5
    )
    assert "as_of_utc" in result["source"]
    assert "as_of_utc" not in result["columns"]
    actor, _audit = make_actor(tmp_path, StaticDelegate(result))

    exported = await actor.export_query_csv(
        result["query"], "clock.csv", recipients=["owner-a"], row_limit=5
    )
    provenance = actor.read_evidence_file(exported["artifact_ref"], "owner-a")["provenance"]
    assert provenance["source"]["as_of_utc"] == result["source"]["as_of_utc"]


@pytest.mark.asyncio
async def test_path_escape_symlink_and_overwrite_are_rejected(
    tmp_path: Path, database: Path
):
    delegate = QueryDelegate(database)
    actor, _audit = make_actor(tmp_path, delegate)
    sql = "SELECT ticket_id FROM tickets LIMIT 1"
    for filename in ("../escape.csv", "nested/file.csv", "\\outside.csv", "/tmp/outside.csv"):
        with pytest.raises(ValueError, match="basename"):
            await actor.export_query_csv(sql, filename)
    assert delegate.calls == []

    external = tmp_path / "external.csv"
    external.write_text("keep me", encoding="utf-8")
    symlink = actor.directory / "linked.csv"
    symlink.symlink_to(external)
    with pytest.raises(FileExistsError):
        await actor.export_query_csv(sql, "linked.csv")
    assert symlink.is_symlink()
    assert external.read_text(encoding="utf-8") == "keep me"
    assert delegate.calls == []

    symlink.unlink()
    first = await actor.export_query_csv(sql, "unique.csv")
    original_content = Path(first["path"]).read_bytes()
    with pytest.raises(FileExistsError):
        await actor.export_query_csv(sql, "unique.csv")
    assert Path(first["path"]).read_bytes() == original_content
    assert len(delegate.calls) == 1


@pytest.mark.asyncio
async def test_truncated_malformed_and_oversized_results_are_not_saved(tmp_path: Path, database: Path):
    sql = "SELECT ticket_id FROM tickets LIMIT 1"
    complete = query_readonly(database, sql, row_limit=5)

    for index, mutate in enumerate((
        lambda result: result.update(truncated=True, truncation_reason="row_limit"),
        lambda result: result.update(columns=["ticket_id", "ticket_id"]),
        lambda result: result["rows"].__setitem__(0, [float("inf")]),
    )):
        result = json.loads(json.dumps(complete))
        mutate(result)
        case_dir = tmp_path / f"case-{index}"
        case_dir.mkdir()
        actor, _audit = make_actor(case_dir, StaticDelegate(result))
        with pytest.raises(ValueError):
            await actor.export_query_csv(sql, "rejected.csv", row_limit=5)
        assert list(actor.directory.iterdir()) == []

    oversized = json.loads(json.dumps(complete))
    oversized["rows"] = [["x" * 1_000_001]]
    oversized["returned_row_count"] = 1
    oversized["columns"] = ["ticket_id"]
    oversized_dir = tmp_path / "oversized-case"
    oversized_dir.mkdir()
    actor, _audit = make_actor(oversized_dir, StaticDelegate(oversized))
    with pytest.raises(ValueError, match="1 MB"):
        await actor.export_query_csv(sql, "rejected.csv", row_limit=5)
    assert list(actor.directory.iterdir()) == []

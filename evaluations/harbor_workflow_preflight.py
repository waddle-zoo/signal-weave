"""Check shared source discovery and changing evidence through a persistent native MCP.

No analyst, card approval, policy judgment, message, or provider call. This is a
prerequisite for the separately admitted workflow trial, not that trial.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.harbor_history import materialize_snapshot, weekly_cutoffs
from evaluations.harbor_history_mcp import ADAPTER, SOURCE_ID
from evaluations.harbor_history_preflight import (
    DUMMY_KEY,
    ROOT,
    _call,
    _direct_rows,
    _errors,
    _provider,
    _setup,
    _write_report,
)
from evaluations.harbor_workflow_history import make_queue_history
from evaluations.harbor_workflow_sources import QUEUE_RESOURCE, build_workflow_manifest
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _jev_proxy,
    _minimal_environment,
    _private_dir,
    _private_file,
)
from scripts.binary_provenance import verify_binary
from signalweave.mcp_server import AGENT_PROFILE_TOOLS
from signalweave.models import ResourceSnapshot

METHOD_FILES = (
    "evaluations/harbor_workflow_preflight.py", "evaluations/harbor_workflow_mcp.py",
    "evaluations/harbor_workflow_sources.py", "evaluations/harbor_workflow_history.py",
    "evaluations/harbor_history.py", "evaluations/harbor_history_mcp.py",
    "evaluations/harbor_history_preflight.py", "evaluations/available_history.py",
    "evaluations/installed_trial_transport.py", "evaluations/bootstrap_agent_trial.py",
    "examples/harbor_help/company_mcp.py", "scripts/binary_provenance.py", "uv.lock",
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _activate(source, target, previous_digest):
    """Replace only this preflight's owned active copy, never its immutable inputs."""
    if target.is_symlink() or (target.exists() and (previous_digest is None or _sha(target) != previous_digest)):
        raise ValueError("Active source is not the expected preflight-owned copy")
    if previous_digest is not None and not target.is_file():
        raise ValueError("Expected active source disappeared")
    staging = target.with_suffix(".next")
    _private_file(staging, "")
    with staging.open("wb") as stream:
        stream.write(source.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    if _sha(staging) != _sha(source):
        raise ValueError("Active copy differs from its immutable snapshot")
    os.replace(staging, target)
    return _sha(target)


def _definitions(manifest):
    return [{"resource": item["descriptor"]["resource"], "title": item["descriptor"]["title"],
             "sql": item["arguments"]["sql"],
             "sha256": hashlib.sha256(item["arguments"]["sql"].encode()).hexdigest(),
             "scope": item["descriptor"]["contract"]["scope"]}
            for item in manifest["connections"][0]["resources"]]


def _validate_snapshot(value, definition, as_of, direct, expected_provenance):
    snapshot = ResourceSnapshot.model_validate(value)
    saved = snapshot.metadata.get("saved_query_definition", {})
    retrieval = snapshot.metadata.get("retrieval", {})
    if (not direct or snapshot.error or snapshot.adapter != ADAPTER or snapshot.resource != definition["resource"]
            or not snapshot.source_key or snapshot.contract.tenant_id != "local" or not snapshot.contract.authorized
            or snapshot.source_captured_at is None
            or snapshot.source_captured_at.isoformat().replace("+00:00", "Z") != as_of
            or snapshot.metadata.get("capture_status") != "synthetic_as_of"
            or retrieval.get("identifier") != SOURCE_ID or retrieval.get("as_of_utc") != as_of
            or saved.get("sql") != definition["sql"] or saved.get("sha256") != definition["sha256"]
            or not expected_provenance or snapshot.metadata.get("assets_read") != expected_provenance
            or [row.values for row in snapshot.evidence] != direct
            or any(row.source_key != snapshot.source_key or row.provenance != expected_provenance or row.origin != "source"
                   for row in snapshot.evidence)):
        raise ValueError("Export changed its identity, query, clock or exact source rows")
    return {"source_key": snapshot.source_key, "evidence_rows": len(snapshot.evidence), "values": direct,
            "source_captured_at": as_of, "contract": snapshot.contract.model_dump(mode="json"),
            "provenance": [row.provenance for row in snapshot.evidence]}


async def _capture(binary, work, snapshots, audit, budget, report):
    python = ROOT / ".venv/bin/python"
    home, active = work / "home", work / "active.sqlite3"
    _private_dir(home)
    _private_dir(home / "tmp")
    digest = _activate(snapshots[0][0], active, None)
    manifest = build_workflow_manifest(active, python)
    definitions = _definitions(manifest)
    report["shared_query_definitions"] = definitions
    config, key = work / "sources.json", work / "dummy.key"
    _private_file(config, json.dumps(manifest, allow_nan=False))
    _private_file(key, DUMMY_KEY + "\n")
    audit.secrets = (DUMMY_KEY,)
    await _setup(binary, home, key, config, audit)
    records = report["observations"]
    async with _jev_proxy(audit, budget) as proxy:
        environment = _minimal_environment(home, jev_url=proxy)
        environment["SIGNALWEAVE_PREFLIGHT_PYTHONPATH"] = str(ROOT)
        native_params = StdioServerParameters(command=str(binary), args=["serve", "--home", str(home)],
                                              cwd=str(ROOT), env=environment)
        source_params = StdioServerParameters(command=str(python),
            args=["-m", "evaluations.harbor_workflow_mcp", str(active)], cwd=str(ROOT), env=environment)
        with open(os.devnull, "w") as errors:
            async with stdio_client(native_params, errlog=errors) as native_streams, stdio_client(source_params, errlog=errors) as source_streams:
                async with ClientSession(*native_streams) as native_session, ClientSession(*source_streams) as source_session:
                    init = await _initialize_mcp_session(native_session)
                    await _initialize_mcp_session(source_session)
                    report["sessions_initialized"] = {"native": 1, "companion": 1}
                    native = InstalledServer(native_session, getattr(init, "instructions", None), audit)
                    source = InstalledServer(source_session, "", audit)
                    if {tool.name for tool in await native.list_tools()} != set(AGENT_PROFILE_TOOLS):
                        raise ValueError("Native tool inventory is not the documented default agent profile")
                    if {tool.name for tool in await source.list_tools()} != {
                        "list_assets", "inspect_asset", "query_readonly", "export_query", "list_saved_queries",
                    }:
                        raise ValueError("Companion tool inventory differs from the shared company source")
                    await _call(native, "get_signalweave_guide", {"task": "start"})
                    catalog = await _call(native, "search_catalog", {"query": "", "adapter": ADAPTER, "limit": 10})
                    if (catalog.get("has_more") is not False or {item["resource"] for item in catalog["resources"]}
                            != {item["resource"] for item in definitions}):
                        raise ValueError("Native source catalog differs from the prepared shared catalog")
                    for index, (path, cutoff) in enumerate(snapshots):
                        if index:
                            digest = _activate(path, active, digest)
                        as_of = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
                        shared = await _call(source, "list_saved_queries", {})
                        if (shared.get("queries") != definitions or shared.get("source", {}).get("identifier") != SOURCE_ID
                                or shared["source"].get("as_of_utc") != as_of):
                            raise ValueError("Companion catalog or current source clock differs from native preparation")
                        record = {"as_of_utc": as_of, "snapshot_sha256": digest, "exports": []}
                        records.append(record)
                        for definition in definitions:
                            match = {"resource": definition["resource"], "sql_sha256": definition["sha256"],
                                     "completed": False, "stage": "direct_sql"}
                            record["exports"].append(match)
                            direct, expected = _direct_rows(active, definition["sql"], as_of)
                            provenance = expected["assets_read"]
                            match["expected_provenance"] = provenance
                            match["stage"] = "companion_export"
                            raw = await _call(source, "export_query", {"sql": definition["sql"], "resource": definition["resource"],
                                "source_key": "shared-inspection", "title": definition["title"]})
                            match["companion"] = _validate_snapshot(raw, definition, as_of, direct, provenance)
                            match["stage"] = "native_inspection"
                            inspected = await _call(native, "inspect_resource", {
                                "adapter": ADAPTER, "resource": definition["resource"], "label": definition["title"],
                            })
                            match["native"] = _validate_snapshot(inspected, definition, as_of, direct, provenance)
                            match.update(completed=True, stage="matched")
                        if _sha(active) != digest:
                            raise ValueError("Source changed within an observation")
                        record["completed"] = True
    counts = [next(row for row in item["exports"] if row["resource"] == QUEUE_RESOURCE)
              ["native"]["values"][0]["known_unanswered_open_priority_past_response_clock"] for item in records]
    if counts != [0, 80, 0]:
        raise ValueError("Controlled source trajectory is not the independently validated case")


async def run(binary, output):
    directory = Path(output).absolute()
    _private_dir(directory)  # Exclusive; never resume/overwrite another run.
    binary = Path(binary).absolute()
    audit, budget = Audit(), RequestBudget(0)
    methods = {name: _sha(ROOT / name) for name in METHOD_FILES}
    report = {"scope": "Source discovery/extraction through persistent native and companion sessions only; no analyst, card, approval, Jev judgment, delivery or business-quality result.",
              "native_profile": "default agent", "session_plan": "one native and one companion session across all source updates",
              "observations": [], "errors": [], "completed": False, "method_hashes_before": methods}
    try:
        identity = verify_binary(binary, ROOT)
        report["binary_identity"] = identity
        history = make_queue_history(complete_background_responses=True, recorded_response=False)
        folder = directory / "snapshots"
        _private_dir(folder)
        snapshots = [(materialize_snapshot(history, cutoff, folder / f"{index}.sqlite3"), cutoff)
                     for index, cutoff in enumerate(weekly_cutoffs(history)[:3])]
        hashes = {str(path.relative_to(directory)): _sha(path) for path, _ in snapshots}
        report["immutable_source_hashes"] = hashes
        with tempfile.TemporaryDirectory(prefix="private-", dir=directory) as temporary:
            async with asyncio.timeout(600):
                await _capture(binary, Path(temporary), snapshots, audit, budget, report)
        if hashes != {str(path.relative_to(directory)): _sha(path) for path, _ in snapshots}:
            raise ValueError("An immutable source input changed")
        if _sha(binary) != identity["binary_sha256"]:
            raise ValueError("Native executable changed during capture")
        report["completed"] = True
    except Exception as error:
        report["errors"] = _errors(error, audit)
    finally:
        report["provider"] = _provider(audit, budget)
        after = {name: _sha(ROOT / name) for name in METHOD_FILES}
        report["method_hashes_after"] = after
        if methods != after or budget.used or budget.exhausted or report["provider"]["request_events"]:
            report["completed"] = False
            report["errors"].append({"type": "IntegrityFailure", "message": "Method changed or zero-provider contract violated"})
        _write_report(directory, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(run(arguments.binary, arguments.output))
    print(json.dumps({"completed": report["completed"], "observations": len(report["observations"]),
                      "provider_attempts": report["provider"]["attempts"], "errors": report["errors"]}))
    if not report["completed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

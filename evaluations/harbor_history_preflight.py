"""Run an inference-free native transport and fixed-SQL Harbor preflight."""

from __future__ import annotations

import argparse
import asyncio
import builtins
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit, RequestBudget
from evaluations.harbor_history import (
    OBSERVATION_COUNT,
    WARMUP_WEEKS,
    make_history,
    materialize_snapshot,
    weekly_cutoffs,
)
from evaluations.harbor_history_mcp import ADAPTER, SOURCE_ID, query_readonly
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _jev_proxy,
    _minimal_environment,
    _private_dir,
    _private_file,
    _safe_setup_detail,
)
from scripts.binary_provenance import verify_binary
from signalweave.mcp_server import AGENT_PROFILE_TOOLS

ROOT = Path(__file__).resolve().parents[1]
TENANT = "local"
ROW_LIMIT = 100
DUMMY_KEY = "test-harbor-history-preflight-no-provider-call"

# These source-prepared exports are identical for every snapshot and future arm.
QUERY_DEFINITIONS = {
    "resolution": {
        "title": "Harbor resolution SLA: unequal-age latest and prior cohorts (descriptive)",
        "resource": "metric:resolution-two-week-pooled",
        "view": "weekly_resolution_sla",
        "scope": "Exact adjacent completed UTC weeks, all tiers/regions pooled; unequal-age cohorts, not an age-matched performance comparison.",
        "description": "Pool SUM(misses)/SUM(eligible) for latest and exact prior weeks. The percentage-point difference is arithmetic only: cohort ages differ, age_matched=0, and it is not operational regression or comparable performance. Never substitute an older observed week.",
        "sql": """WITH weeks AS (
 SELECT DISTINCT week_start_utc FROM calendar_partitions
), bounds AS (
 SELECT MAX(week_start_utc) latest_week_start_utc, date(MAX(week_start_utc), '-7 days') comparison_week_start_utc FROM weeks
), totals AS (
 SELECT week_start_utc, SUM(observed_ticket_count) observed_ticket_count,
        SUM(eligible_resolved_tickets) eligible_resolved_tickets, SUM(resolution_sla_misses) resolution_sla_misses,
        1.0 * SUM(resolution_sla_misses) / NULLIF(SUM(eligible_resolved_tickets), 0) miss_rate
 FROM weekly_resolution_sla
 WHERE week_start_utc IN (SELECT latest_week_start_utc FROM bounds UNION ALL SELECT comparison_week_start_utc FROM bounds)
 GROUP BY week_start_utc
), paired AS (
 SELECT b.latest_week_start_utc, b.comparison_week_start_utc,
        EXISTS (SELECT 1 FROM weeks w WHERE w.week_start_utc=b.comparison_week_start_utc) comparison_calendar_available,
        l.observed_ticket_count latest_observed_ticket_count, l.eligible_resolved_tickets latest_eligible_resolved_tickets,
        l.resolution_sla_misses latest_resolution_sla_misses, l.miss_rate latest_resolution_sla_miss_rate,
        p.observed_ticket_count comparison_observed_ticket_count, p.eligible_resolved_tickets comparison_eligible_resolved_tickets,
        p.resolution_sla_misses comparison_resolution_sla_misses, p.miss_rate comparison_resolution_sla_miss_rate
 FROM bounds b LEFT JOIN totals l ON l.week_start_utc=b.latest_week_start_utc LEFT JOIN totals p ON p.week_start_utc=b.comparison_week_start_utc
), availability AS (
 SELECT *, CASE WHEN comparison_calendar_available=1 AND latest_eligible_resolved_tickets>0
                     AND comparison_eligible_resolved_tickets>0 THEN 1 ELSE 0 END arithmetic_difference_available
 FROM paired
)
SELECT *, 0 age_matched, 'unequal_age_cohort_rates_descriptive_only' semantic_basis,
       CASE WHEN arithmetic_difference_available=1 THEN 100.0*(latest_resolution_sla_miss_rate-comparison_resolution_sla_miss_rate)
            ELSE NULL END resolution_sla_miss_rate_arithmetic_difference_percentage_points
FROM availability""",
    },
    "coverage": {
        "title": "Harbor source coverage: latest and exact prior completed week",
        "resource": "metric:coverage-two-week-pooled",
        "view": "weekly_source_coverage",
        "scope": "Two exact adjacent completed UTC calendar weeks; every tier/region segment retained.",
        "description": "Count unknown manifests; strict expected/missing totals are NULL if any segment is unknown, with known-only subtotals named explicitly.",
        "sql": """WITH weeks AS (
 SELECT DISTINCT week_start_utc FROM calendar_partitions
), bounds AS (
 SELECT MAX(week_start_utc) latest_week_start_utc, date(MAX(week_start_utc), '-7 days') comparison_week_start_utc FROM weeks
), selected AS (
 SELECT latest_week_start_utc, comparison_week_start_utc, latest_week_start_utc week_start_utc, 1 is_latest_week FROM bounds
 UNION ALL SELECT latest_week_start_utc, comparison_week_start_utc, comparison_week_start_utc, 0 FROM bounds
), pooled AS (
 SELECT week_start_utc, COUNT(*) represented_segments,
        SUM(expected_ticket_count IS NULL) unknown_manifest_segments,
        SUM(CASE WHEN expected_ticket_count IS NOT NULL THEN expected_ticket_count ELSE 0 END) known_expected_ticket_count,
        SUM(observed_ticket_count) observed_ticket_count,
        SUM(CASE WHEN missing_ticket_count IS NOT NULL THEN missing_ticket_count ELSE 0 END) known_missing_ticket_count,
        SUM(coverage_status='complete') complete_segments, SUM(coverage_status='missing') missing_segments,
        SUM(coverage_status='partial') partial_segments, SUM(coverage_status='excess') excess_segments
 FROM weekly_source_coverage
 WHERE week_start_utc IN (SELECT latest_week_start_utc FROM bounds UNION ALL SELECT comparison_week_start_utc FROM bounds)
 GROUP BY week_start_utc
)
SELECT s.latest_week_start_utc, s.comparison_week_start_utc, s.week_start_utc, s.is_latest_week,
       EXISTS (SELECT 1 FROM weeks w WHERE w.week_start_utc=s.week_start_utc) calendar_week_available,
       COALESCE(p.represented_segments,0) represented_segments, COALESCE(p.unknown_manifest_segments,0) unknown_manifest_segments,
       COALESCE(p.known_expected_ticket_count,0) known_expected_ticket_count,
       CASE WHEN p.represented_segments>0 AND p.unknown_manifest_segments=0
            THEN p.known_expected_ticket_count END expected_ticket_count,
       COALESCE(p.observed_ticket_count,0) observed_ticket_count, COALESCE(p.known_missing_ticket_count,0) known_missing_ticket_count,
       CASE WHEN p.represented_segments>0 AND p.unknown_manifest_segments=0
            THEN p.known_missing_ticket_count END missing_ticket_count,
       COALESCE(p.complete_segments,0) complete_segments, COALESCE(p.missing_segments,0) missing_segments,
       COALESCE(p.partial_segments,0) partial_segments, COALESCE(p.excess_segments,0) excess_segments
FROM selected s LEFT JOIN pooled p USING (week_start_utc)
ORDER BY s.is_latest_week DESC""",
    },
    "backlog": {
        "title": "Harbor known open priority backlog: all cohorts at snapshot cutoff",
        "resource": "metric:known-open-backlog-all-cohorts",
        "view": "weekly_open_backlog",
        "scope": "All currently known creation cohorts at source_snapshot.as_of_utc, including older and current partial cohorts.",
        "description": "Pool all known open-ticket cohorts at the exact source snapshot clock; not limited to the latest completed creation week.",
        "sql": """SELECT s.as_of_utc, COUNT(DISTINCT b.week_start_utc) known_creation_cohort_count,
       MIN(b.week_start_utc) oldest_known_creation_cohort_week_start, MAX(b.week_start_utc) latest_known_creation_cohort_week_start,
       COALESCE(SUM(b.open_priority_tickets),0) open_priority_tickets,
       COALESCE(SUM(b.overdue_open_priority_tickets),0) overdue_open_priority_tickets,
       COALESCE(SUM(b.unanswered_tickets),0) unanswered_tickets, COALESCE(SUM(b.overdue_unanswered_tickets),0) overdue_unanswered_tickets
FROM source_snapshot s LEFT JOIN weekly_open_backlog b ON b.as_of_utc=s.as_of_utc GROUP BY s.as_of_utc""",
    },
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def query_definition_report() -> dict[str, dict[str, str]]:
    return {key: {**definition, "sha256": _sha(definition["sql"].encode())}
            for key, definition in QUERY_DEFINITIONS.items()}


def _delayed_batch(history: dict[str, Any]) -> tuple[datetime, list[dict[str, Any]]]:
    created = [row for row in history["events"]
               if row["payload"].get("kind") == "created"
               and row["payload"].get("support_tier") == "business"
               and row["payload"].get("region") == "central"
               and row["available_at"] - row["effective_at"] >= timedelta(days=8)]
    weeks = {row["effective_at"].replace(hour=0, minute=0, second=0, microsecond=0)
             - timedelta(days=row["effective_at"].weekday()) for row in created}
    if len(weeks) != 1:
        raise ValueError("Fixture must contain one delayed business/central ticket batch")
    return next(iter(weeks)), created


def plan_cutoffs(history: dict[str, Any]) -> list[dict[str, Any]]:
    cutoffs = weekly_cutoffs(history)
    week, batch = _delayed_batch(history)
    earliest, latest = min(row["available_at"] for row in batch), max(row["available_at"] for row in batch)
    delayed = next((value for value in cutoffs if week + timedelta(weeks=1) <= value < earliest), None)
    manifests = [row for row in history["events"] if row["payload"].get("kind") == "partition"
                 and row["payload"].get("support_tier") != "business"
                 and row["available_at"] - row["effective_at"] >= timedelta(days=8)]

    def pending_recent_manifest(cutoff: datetime) -> dict[str, Any] | None:
        closed = {row["effective_at"] - timedelta(weeks=1) for row in history["events"]
                  if row["payload"].get("kind") == "partition" and row["effective_at"] <= cutoff}
        latest_closed = max(closed, default=None)
        recent = {latest_closed, latest_closed - timedelta(weeks=1)} if latest_closed else set()
        return next((row for row in manifests
                     if datetime.fromisoformat(row["payload"]["week_start_utc"]).replace(tzinfo=timezone.utc) in recent
                     and row["effective_at"] <= cutoff < row["available_at"]), None)

    backfill_pair = next(((value, pending_recent_manifest(value)) for value in cutoffs
                          if value >= latest and pending_recent_manifest(value) is not None), None)
    backfill = backfill_pair[0] if backfill_pair else None
    pending = backfill_pair[1] if backfill_pair else None
    first = cutoffs[0] if cutoffs else None
    if first is None or delayed is None or backfill is None or not first < delayed < backfill:
        raise ValueError("Fixture does not provide the three ordered historical cutoffs")
    return [{"key": key, "cutoff": value, "delayed_batch_week_start": week,
             "pending_manifest_week_start": pending["payload"]["week_start_utc"] if value == backfill else None}
            for key, value in (("first_score_cutoff", first),
                               ("delayed_batch_cutoff", delayed),
                               ("later_backfill_cutoff", backfill))]


def build_manifest(snapshot: Path, python: Path) -> dict[str, Any]:
    resources = []
    for key, definition in QUERY_DEFINITIONS.items():
        digest = _sha(definition["sql"].encode())
        resources.append({
            "descriptor": {
                "adapter": ADAPTER, "resource": definition["resource"], "kind": "saved_query",
                "title": definition["title"], "description": definition["description"],
                "metadata": {"sql_sha256": digest, "source_view": definition["view"]},
                "contract": {"tenant_id": TENANT, "authorized": True, "domain": "support",
                             "scope": definition["scope"],
                             "lineage": [f"source-view:{definition['view']}", f"saved-sql-sha256:{digest}"],
                             "freshness_sla_hours": None},
            },
            "source_key": key, "tool": "export_query",
            "arguments": {"sql": definition["sql"], "resource": definition["resource"],
                          "source_key": key, "title": definition["title"]},
            "snapshot_pointer": "",
        })
    return {"version": 1, "connections": [{
        "name": ADAPTER, "tenant_id": TENANT, "context_namespace": "harbor-history-preflight-v1",
        "read_only": True,
        "transport": {"type": "stdio", "command": [str(python), "-m", "evaluations.harbor_history_mcp", str(snapshot)],
                      "env": {"PYTHONPATH": {"env": "SIGNALWEAVE_PREFLIGHT_PYTHONPATH"}}},
        "timeout_seconds": 30, "max_response_bytes": 500_000, "resources": resources,
    }]}


def _structured(result: Any, tool: str) -> dict[str, Any]:
    if result.isError:
        raise RuntimeError(f"Native {tool} returned an MCP error")
    if not isinstance(result.structuredContent, dict):
        raise ValueError(f"Native {tool} omitted structuredContent")
    return result.structuredContent


async def _call(server: InstalledServer, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with asyncio.timeout(60):
        return _structured(await server._session.call_tool(tool, arguments), tool)


def _direct_rows(snapshot: Path, sql: str, as_of: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = query_readonly(snapshot, sql, row_limit=ROW_LIMIT)
    source = result.get("source", {})
    if (source.get("identifier") != SOURCE_ID or source.get("as_of_utc") != as_of
            or result.get("truncated") is not False):
        raise ValueError("Direct bounded query did not preserve the exact snapshot clock or complete rows")
    columns, rows = result.get("columns"), result.get("rows")
    if not isinstance(columns, list) or not columns or len(columns) != len(set(columns)) or not rows:
        raise ValueError("Direct bounded query returned no current rows or invalid columns")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError("Direct bounded query returned a malformed row")
    mapped = [dict(zip(columns, row, strict=True)) for row in rows]
    compact = {"columns": columns, "rows": mapped, "row_limit": result["row_limit"],
               "assets_read": result["assets_read"]}
    return mapped, compact


def _validate_exports(snapshot: dict[str, Any], key: str, as_of: str,
                      direct: list[dict[str, Any]]) -> int:
    definition = QUERY_DEFINITIONS[key]
    metadata = snapshot.get("metadata", {})
    saved, retrieval = metadata.get("saved_query_definition", {}), metadata.get("retrieval", {})
    if (snapshot.get("error") is not None or snapshot.get("adapter") != ADAPTER
            or snapshot.get("resource") != definition["resource"]
            or not isinstance(snapshot.get("source_key"), str) or not snapshot["source_key"]
            or snapshot.get("contract", {}).get("tenant_id") != TENANT
            or snapshot.get("contract", {}).get("authorized") is not True
            or snapshot.get("source_captured_at") != as_of
            or retrieval.get("identifier") != SOURCE_ID or retrieval.get("as_of_utc") != as_of
            or saved.get("sql") != definition["sql"]
            or saved.get("sha256") != _sha(definition["sql"].encode())
            or metadata.get("capture_status") != "synthetic_as_of"):
        raise ValueError(f"Native {key} export changed its fixed query, source identity, or snapshot clock")
    evidence = snapshot.get("evidence")
    # The normal inspect_resource API rebinds the registered source key to its
    # caller-owned inspection alias; it is not the upstream registration key.
    if (not isinstance(evidence, list) or not evidence
            or any(row.get("source_key") != snapshot["source_key"] for row in evidence)
            or [row.get("values") for row in evidence] != direct):
        raise ValueError(f"Native {key} rows differ from the bounded direct SQL result")
    return len(evidence)


async def _setup(binary: Path, home: Path, key: Path, manifest: Path, audit: Audit) -> None:
    command = [str(binary), "setup", "--non-interactive", "--home", str(home),
               "--key-file", str(key), "--source", "mcp", "--manifest", str(manifest),
               "--tenant", TENANT, "--principal", "harbor-history-preflight", "--agent", "codex",
               "--no-register-agent"]
    environment = _minimal_environment(home)
    result = await asyncio.to_thread(subprocess.run, command, cwd=ROOT, env=environment,
                                     capture_output=True, text=True, timeout=90, check=False)
    if result.returncode:
        detail = _safe_setup_detail(result.stderr or result.stdout, audit=audit,
            private_paths=((home, "[home]"), (key, "[dummy-key-file]"), (manifest, "[manifest]")))
        raise RuntimeError(f"Private native setup failed with exit code {result.returncode}: {detail}")


async def _run_cutoff(entry: dict[str, Any], snapshot: Path, binary: Path, python: Path,
                      work: Path, audit: Audit, budget: RequestBudget) -> dict[str, Any]:
    cutoff = entry["cutoff"]
    as_of = cutoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    before = _sha(snapshot.read_bytes())
    output: dict[str, Any] = {"key": entry["key"], "as_of_utc": as_of,
                              "snapshot_sha256": before, "assets": {}, "errors": []}
    direct: dict[str, list[dict[str, Any]]] = {}
    for key, definition in QUERY_DEFINITIONS.items():
        rows, compact = _direct_rows(snapshot, definition["sql"], as_of)
        direct[key] = rows
        output["assets"][key] = {"query_sha256": _sha(definition["sql"].encode()), "direct_sql": compact}
    resolution = direct["resolution"]
    coverage = direct["coverage"]
    backlog = direct["backlog"]
    if (len(resolution) != 1 or len(coverage) != 2 or len(backlog) != 1
            or backlog[0].get("as_of_utc") != as_of):
        raise ValueError("Fixed exports did not return their expected current rows")
    latest = datetime.fromisoformat(resolution[0]["latest_week_start_utc"]).date()
    previous = latest - timedelta(days=7)
    if (resolution[0]["comparison_week_start_utc"] != previous.isoformat()
            or any(row.get("latest_week_start_utc") != latest.isoformat()
                   or row.get("comparison_week_start_utc") != previous.isoformat() for row in coverage)
            or [row["week_start_utc"] for row in coverage] != [latest.isoformat(), previous.isoformat()]):
        raise ValueError("Resolution and coverage exports do not use the exact two completed weeks")
    for row in coverage:
        unknown = row["unknown_manifest_segments"]
        if (row["represented_segments"] <= 0
                or (unknown and (row["expected_ticket_count"] is not None or row["missing_ticket_count"] is not None))
                or (not unknown and (row["expected_ticket_count"] is None or row["missing_ticket_count"] is None))):
            raise ValueError("Coverage export lost unknown manifests or strict pooled totals")
    pending_week = entry.get("pending_manifest_week_start")
    if pending_week:
        pending = next((row for row in coverage if row["week_start_utc"] == pending_week), None)
        if pending is None or pending["unknown_manifest_segments"] < 1 or pending["expected_ticket_count"] is not None:
            raise ValueError("Later backfill cutoff did not retain its pending manifest as unknown")
    output["latest_completed_week_start_utc"] = latest.isoformat()
    if pending_week:
        output["pending_manifest_week_start_utc"] = pending_week

    private = work / entry["key"]
    _private_dir(private)
    home, temp = private / "home", private / "home" / "tmp"
    _private_dir(home)
    _private_dir(temp)
    key_path, manifest_path = private / "dummy.key", private / "sources.json"
    _private_file(key_path, DUMMY_KEY + "\n")
    _private_file(manifest_path, json.dumps(build_manifest(snapshot, python), allow_nan=False))
    audit.secrets = tuple(dict.fromkeys((*audit.secrets, DUMMY_KEY)))
    await _setup(binary, home, key_path, manifest_path, audit)
    async with _jev_proxy(audit, budget) as jev_url:
        environment = _minimal_environment(home, jev_url=jev_url)
        environment["SIGNALWEAVE_PREFLIGHT_PYTHONPATH"] = str(ROOT)
        params = StdioServerParameters(command=str(binary), args=["serve", "--home", str(home)],
                                       cwd=str(ROOT), env=environment)
        with open(os.devnull, "w", encoding="utf-8") as errors:
            async with stdio_client(params, errlog=errors) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await _initialize_mcp_session(session)
                    server = InstalledServer(session, getattr(initialized, "instructions", None), audit)
                    tools = {tool.name for tool in await server.list_tools()}
                    if tools != set(AGENT_PROFILE_TOOLS):
                        raise ValueError("Native server did not use the default agent profile")
                    guide = await _call(server, "get_signalweave_guide", {"task": "start"})
                    catalog = await _call(server, "search_catalog", {"query": "", "adapter": ADAPTER, "limit": 10})
                    expected = {(ADAPTER, value["resource"]) for value in QUERY_DEFINITIONS.values()}
                    actual = {(row.get("adapter"), row.get("resource")) for row in catalog.get("resources", [])}
                    if not guide or actual != expected or catalog.get("has_more") is not False:
                        raise ValueError("Native guide or fixed Harbor catalog check failed")
                    for key, definition in QUERY_DEFINITIONS.items():
                        inspected = await _call(server, "inspect_resource", {
                            "adapter": ADAPTER, "resource": definition["resource"], "label": definition["title"],
                        })
                        count = _validate_exports(inspected, key, as_of, direct[key])
                        output["assets"][key].update(native_match=True, evidence_rows=count)
                    output["native"] = {
                        "profile": "agent (documented default; --profile omitted)",
                        "private_home": True, "agent_registration_disabled": True,
                        "tool_names": sorted(tools),
                        "guide_sha256": _sha(json.dumps(guide, sort_keys=True, allow_nan=False).encode()),
                        "catalog_resources": sorted(f"{a}:{r}" for a, r in actual),
                    }
    after = _sha(snapshot.read_bytes())
    if after != before:
        raise RuntimeError("Snapshot file changed during native preflight")
    output["snapshot_unchanged"] = True
    output["completed"] = True
    return output


def _provider(audit: Audit, budget: RequestBudget) -> dict[str, Any]:
    events = [{key: event[key] for key in ("kind", "provider", "reason", "error_type") if key in event}
              for event in audit.events if event.get("kind", "").startswith("api.")]
    return {"name": "jev", "attempts": budget.used, "budget": budget.limit,
            "budget_exhausted": budget.exhausted, "request_events": events}


def _errors(error: BaseException, audit: Audit) -> list[dict[str, str]]:
    """Keep useful leaf diagnostics when SDK cleanup wraps the original error."""
    if isinstance(error, builtins.BaseExceptionGroup):
        return [item for child in error.exceptions for item in _errors(child, audit)][:10]
    return [{"type": type(error).__name__,
             "message": _safe_setup_detail(str(error), audit=audit, private_paths=())[:800]}]


def _write_report(directory: Path, report: dict[str, Any]) -> None:
    data = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd = os.open(directory / "report.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


async def run(binary: str | Path, output: str | Path) -> dict[str, Any]:
    directory = Path(output).expanduser().absolute()
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(f"Output must be a new exclusive directory: {directory}")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    directory.chmod(0o700)
    binary = Path(binary).expanduser().absolute()
    python = ROOT / ".venv" / "bin" / "python"
    audit, budget = Audit(), RequestBudget(limit=0)
    worker_hash = _sha(Path(__file__).read_bytes())
    method_files = ("evaluations/harbor_history.py", "evaluations/harbor_history_mcp.py",
                    "evaluations/available_history.py", "examples/harbor_help/company_mcp.py")
    method_hashes = {name: _sha((ROOT / name).read_bytes()) for name in method_files}
    report: dict[str, Any] = {
        "scope": "Synthetic native transport and fixed-SQL preflight only. Includes source SLA clocks and derived metrics; no trial outcome labels, alert/action thresholds, card, agent-authored onboarding, human setup, Jev judgment, or business-quality claim.",
        "method": "Researcher-prepared fixed source SQL, not human onboarding. The same query definitions are supplied for every cutoff and future arm.",
        "limits": {"snapshots": 3, "fixed_exports": list(QUERY_DEFINITIONS), "source_row_limit": ROW_LIMIT,
                   "provider_request_budget": 0, "profile": "default agent", "actor": "none"},
        "binary": str(binary), "source_id": SOURCE_ID,
        "query_definitions": query_definition_report(),
        "method_integrity": {"worker_sha256_before": worker_hash, "source_sha256_before": method_hashes},
        "cutoffs": [], "errors": [], "completed": False,
    }
    try:
        if not python.is_file():
            raise FileNotFoundError("Repository .venv/bin/python is required for the Harbor source bridge")
        identity = verify_binary(binary, ROOT)
        report["binary_identity"] = identity
        fixture_seed = 20261018
        history = make_history(seed=fixture_seed)
        report["fixture"] = {"seed": fixture_seed, "weeks": WARMUP_WEEKS + OBSERVATION_COUNT,
                              "warmup_weeks": WARMUP_WEEKS, "observation_weeks": OBSERVATION_COUNT}
        plan = plan_cutoffs(history)
        snapshots = directory / "snapshots"
        snapshots.mkdir(mode=0o700)
        files = {}
        for item in plan:
            path = snapshots / f"{item['key']}.sqlite3"
            materialize_snapshot(history, item["cutoff"], path)
            files[item["key"]] = (path, _sha(path.read_bytes()))
        with tempfile.TemporaryDirectory(prefix="harbor-preflight-", dir=directory) as temporary:
            work = Path(temporary)
            for item in plan:
                snapshot, digest = files[item["key"]]
                try:
                    async with asyncio.timeout(300):
                        result = await _run_cutoff(item, snapshot, binary, python, work, audit, budget)
                    if _sha(snapshot.read_bytes()) != digest:
                        raise RuntimeError("Materialized snapshot changed after its native run")
                except Exception as error:
                    result = {"key": item["key"], "as_of_utc": item["cutoff"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "snapshot_sha256": digest, "snapshot_unchanged": _sha(snapshot.read_bytes()) == digest,
                              "assets": {}, "completed": False,
                              "errors": _errors(error, audit)}
                report["cutoffs"].append(result)
        if _sha(binary.read_bytes()) != identity["binary_sha256"]:
            raise RuntimeError("Native binary changed during preflight")
        report["binary_sha256_after"] = _sha(binary.read_bytes())
        report["provider"] = _provider(audit, budget)
        report["completed"] = len(report["cutoffs"]) == 3 and all(row.get("completed") for row in report["cutoffs"])
        if budget.used or budget.exhausted or report["provider"]["request_events"]:
            report["completed"] = False
            report["errors"].append({"type": "ProviderRequestDetected", "message": "Zero-provider contract failed"})
        if not report["completed"]:
            report["errors"].append({"type": "PreflightIncomplete", "message": "One or more cutoff checks failed"})
    except Exception as error:
        report["errors"].extend(_errors(error, audit))
    finally:
        report["provider"] = _provider(audit, budget)
        worker_after = _sha(Path(__file__).read_bytes())
        methods_after = {name: _sha((ROOT / name).read_bytes()) for name in method_files}
        report["method_integrity"].update(worker_sha256_after=worker_after,
                                          source_sha256_after=methods_after)
        if worker_after != worker_hash or methods_after != method_hashes:
            report["completed"] = False
            report["errors"].append({"type": "MethodChanged", "message": "Worker or fixture generator changed during preflight"})
        _write_report(directory, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = asyncio.run(run(args.binary, args.output))
    print(json.dumps({"completed": report["completed"], "cutoffs": len(report["cutoffs"]),
                      "provider_attempts": report["provider"]["attempts"], "errors": report["errors"]}))
    if not report["completed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

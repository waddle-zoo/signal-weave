"""Bounded, offline-by-default installed-binary first-report trial.

This is scripted onboarding against three synthetic companies. It is not an
agent/human-usability study and not an LLM benchmark. The live path is
explicit and limited to two Jev attempts per company: one native draft and one
preview judgment.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluations.recurring_runtime_transfer_cases import cases

COMPANIES = ("canyon-freight", "helio-support", "lattice-energy")
MAX_JEV_PER_COMPANY = 2
MAX_PAID_ATTEMPTS = 6
ROUTE_INTENT = {
    "canyon-freight": {"notify": "fleet-operations", "insufficient_data": "logistics-data"},
    "helio-support": {"notify": "support-quality", "insufficient_data": "support-data"},
    "lattice-energy": {"notify": "commercial-operations", "investigate": "commercial-data", "insufficient_data": "commercial-data"},
}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parents[1],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _harness_hash() -> str:
    files = [Path(__file__), Path(__file__).with_name("fixture_snapshot_mcp.py"),
             Path(__file__).parents[1] / "tests" / "test_installed_first_report_trial.py"]
    return _hash({str(path.name): _file_hash(path) for path in files})


def _normal_public(company: dict[str, Any], period: dict[str, Any], captured: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize every descriptor, source ref, and snapshot to the manifest identity."""
    descriptor_resources = [item["resource"] for item in company["descriptors"]]
    descriptor_keys = [item["source_key"] for item in company["descriptors"]]
    source_resources = [item["resource"] for item in company["sources"]]
    source_keys = [item["key"] for item in company["sources"]]
    if len(set(source_resources)) != len(source_resources) or len(set(source_keys)) != len(source_keys):
        raise ValueError("fixture source identities are not unique")
    if len(set(descriptor_resources)) != len(descriptor_resources) or len(set(descriptor_keys)) != len(descriptor_keys):
        raise ValueError("fixture descriptor identities are not unique")
    if set(source_resources) != set(descriptor_resources) or set(source_keys) != set(descriptor_keys):
        raise ValueError("fixture source and descriptor identities do not match")
    period_resources = [item["resource"] for item in period["resources"]]
    period_keys = [item["source_key"] for item in period["resources"]]
    if len(set(period_resources)) != len(period_resources) or len(set(period_keys)) != len(period_keys):
        raise ValueError("fixture snapshot identities are not unique")
    if set(period_resources) != set(descriptor_resources) or set(period_keys) != set(descriptor_keys):
        raise ValueError("fixture snapshot and descriptor identities do not match")
    bindings = {(item["resource"], item["source_key"]) for item in company["descriptors"]}
    if ({(item["resource"], item["key"]) for item in company["sources"]} != bindings
            or {(item["resource"], item["source_key"]) for item in period["resources"]} != bindings):
        raise ValueError("fixture resource-key bindings do not match")
    descriptors = copy.deepcopy(company["descriptors"])
    sources = copy.deepcopy(company["sources"])
    descriptor_by_resource = {}
    for descriptor in descriptors:
        descriptor["adapter"] = "company_metrics"
        descriptor["contract"]["tenant_id"] = "local"
        descriptor["contract"]["authorized"] = True
        descriptor_by_resource[descriptor["resource"]] = descriptor
    for source in sources:
        source["adapter"] = "company_metrics"
        source["parameters"] = {}
        source["required"] = True
    snapshots = []
    captured = captured or datetime.now(timezone.utc).isoformat()
    for original in period["resources"]:
        snapshot = copy.deepcopy(original)
        descriptor = descriptor_by_resource[snapshot["resource"]]
        snapshot.update({"adapter": "company_metrics", "source_key": descriptor["source_key"],
                         "resource": descriptor["resource"], "captured_at": captured})
        snapshot["contract"]["tenant_id"] = "local"
        snapshot["contract"]["authorized"] = True
        original_source_capture = snapshot.get("source_captured_at")
        snapshot.setdefault("metadata", {})["historical_source_captured_at"] = original_source_capture
        snapshot["source_captured_at"] = captured
        snapshot["metadata"]["replayed_historical_data"] = True
        snapshot["metadata"]["fresh_warehouse_read"] = False
        snapshot["metadata"]["trial_capture_note"] = "Captured now from frozen historical data; not a fresh warehouse read."
        snapshots.append(snapshot)
    return {"descriptors": descriptors, "sources": sources}, snapshots


def _fixture_payload(company: dict[str, Any], period: dict[str, Any], captured: str | None = None) -> dict[str, Any]:
    public, snapshots = _normal_public(company, period, captured)
    return {"resources": {snapshot["resource"]: snapshot for snapshot in snapshots},
            "allowlisted_resources": sorted(snapshot["resource"] for snapshot in snapshots),
            "company": company["id"], "tenant_id": "local", "source_freeze_sha256": _hash(public)}


def _manifest(company: dict[str, Any], public: dict[str, Any], fixture_script: Path, fixture_file: Path) -> dict[str, Any]:
    resources = [{"descriptor": descriptor, "source_key": descriptor["source_key"],
                  "tool": "read_snapshot", "arguments": {"resource": descriptor["resource"]}}
                 for descriptor in public["descriptors"]]
    return {"version": 1, "connections": [{"name": "company_metrics", "tenant_id": "local", "read_only": True,
        "transport": {"type": "stdio", "command": [os.fspath(Path(os.sys.executable)), os.fspath(fixture_script), os.fspath(fixture_file)]},
        "resources": resources}]}


def _routes(company_id: str, destinations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {item["key"]: item for item in destinations}
    return [{"key": f"{destination_key}:{outcome}", "outcome": outcome,
             "label": by_key[destination_key]["label"], "destination": by_key[destination_key]["destination"]}
            for outcome, destination_key in ROUTE_INTENT[company_id].items()]


def _score_preview(preview: dict[str, Any], company: dict[str, Any], period: dict[str, Any]) -> dict[str, Any]:
    from evaluations.first_report_trial import native_submission
    from evaluations.first_report_trial import score as first_report_score

    try:
        submission = native_submission(preview, company["destinations"])
        numeric = first_report_score(submission, period["oracle"])
    except (KeyError, TypeError, ValueError, IndexError) as error:
        submission = None
        numeric = {"passed": False, "errors": ["malformed_native_report", type(error).__name__]}
    actual_methods = preview.get("result", {}).get("delivery_methods", [])
    actual_routes = set()
    route_errors = []
    for method in actual_methods:
        if not isinstance(method, dict) or not method.get("outcome") or not method.get("destination"):
            route_errors.append("malformed_delivery_method")
            continue
        identity = (method["outcome"], method["destination"])
        if identity in actual_routes:
            route_errors.append("duplicate_delivery_method")
        actual_routes.add(identity)
    destinations = {item["key"]: item["destination"] for item in company["destinations"]}
    expected_outcome = period["oracle"]["outcome"]
    expected_destination = ROUTE_INTENT[company["id"]].get(expected_outcome)
    expected_routes = ({(expected_outcome, destinations[expected_destination])}
                       if expected_destination is not None else set())
    return {"numeric_and_provenance": numeric, "route_intent": {"expected": sorted(expected_routes),
            "actual": sorted(actual_routes), "mismatch": sorted(expected_routes ^ actual_routes), "errors": route_errors},
            "report_status": preview.get("report", {}).get("status"), "submission": submission}


def _oracle_hash(company: dict[str, Any]) -> str:
    return _hash([{"id": period["id"], "oracle": period["oracle"]} for period in company["periods"]])


def _frozen_protocol(binary: Path | None = None) -> dict[str, Any]:
    frozen = []
    for company in cases():
        captured = datetime.now(timezone.utc).isoformat()
        public, _ = _normal_public(company, company["periods"][2], captured)
        fixture = _fixture_payload(company, company["periods"][2], captured)
        frozen.append({"id": company["id"], "period": "p03", "source_freeze_sha256": _hash(public),
                       "fixture_sha256": _hash(fixture), "oracle_sha256": _oracle_hash(company),
                       "captured_at": captured, "sources": public["sources"], "descriptors": public["descriptors"],
                       "original_sources": company["sources"], "original_descriptors": company["descriptors"],
                       "original_snapshot_identities": [{"adapter": item["adapter"], "resource": item["resource"],
                           "source_key": item["source_key"], "tenant_id": item["contract"]["tenant_id"]}
                           for item in company["periods"][2]["resources"]]})
    return {"protocol": "installed-first-report-trial-v2", "scope": "scripted onboarding; not agent/human usability; not an LLM benchmark",
            "offline_by_default": True, "companies": list(COMPANIES), "intended_denominator": 3,
            "max_jev_attempts_per_company": MAX_JEV_PER_COMPANY, "max_paid_attempts": MAX_PAID_ATTEMPTS,
            "retry_policy": {"TYPESAFE_MAX_RETRIES": 0, "retrieval": "fixed", "investigation": "none"},
            "route_intent": ROUTE_INTENT, "approval": {"seeded_approved_cards": False, "external_messages": False}, "frozen_inputs": frozen,
            "created_at": datetime.now(timezone.utc).isoformat(), "git_sha": _git_sha(),
            "harness_sha256": _harness_hash(), "binary_sha256": _file_hash(binary) if binary else None}


async def _call(session, name: str, args: dict[str, Any]) -> dict[str, Any]:
    response = await session.call_tool(name, args)
    if response.isError:
        raise RuntimeError(f"native tool failed: {name}")
    if response.structuredContent:
        return response.structuredContent
    return json.loads(next(item.text for item in response.content if item.type == "text"))


def _scan_exact_secrets(payload: str, key_file: Path) -> dict[str, Any]:
    secret = key_file.read_text(encoding="utf-8").strip()
    if secret and secret in payload:
        raise RuntimeError("exact key material would be written to trial artifacts")
    return {"checked": True, "matches": 0, "key_file": key_file.name}


async def _live_company(binary: Path, key_file: Path, company: dict[str, Any], fixture_script: Path,
                        captured: str, attempts: dict[str, Any], events: list[dict[str, Any]], event_file: Path) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    public, _ = _normal_public(company, company["periods"][2], captured)
    def record(event: dict[str, Any]) -> None:
        events.append(event)
        with event_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")

    with tempfile.TemporaryDirectory(prefix=f"{company['id']}-") as temporary:
        work = Path(temporary)
        home, fixture = work / "private-home", work / "snapshot.json"
        home.mkdir(mode=0o700)
        fixture.write_text(json.dumps(_fixture_payload(company, company["periods"][2], captured)) + "\n")
        manifest = home / "reviewed-read-only-mcp.json"
        manifest.write_text(json.dumps(_manifest(company, public, fixture_script, fixture)) + "\n")
        manifest.chmod(0o600)
        staged_key = work / "input.key"
        shutil.copyfile(key_file, staged_key)
        staged_key.chmod(0o600)
        env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR") if k in os.environ}
        env["TYPESAFE_MAX_RETRIES"] = "0"
        setup = subprocess.run([str(binary), "setup", "--non-interactive", "--home", str(home), "--key-file", str(staged_key),
                                "--source", "mcp", "--manifest", str(manifest), "--tenant", "local", "--principal", company["id"], "--agent", "codex"],
                               cwd=work, env=env, capture_output=True, text=True, timeout=90)
        if setup.returncode:
            raise RuntimeError("binary setup failed")
        async with stdio_client(StdioServerParameters(command=str(binary), args=["serve", "--home", str(home)], cwd=str(work), env=env)) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                await _call(session, "get_signalweave_guide", {"task": "report"})
                tools = [tool.name for tool in (await session.list_tools()).tools]
                await _call(session, "list_resources", {"adapter": "company_metrics"})
                for source in public["sources"]:
                    await _call(session, "inspect_resource", {"adapter": source["adapter"], "resource": source["resource"]})
                for operation, call in (("draft_insight_card", {"title": company["brief"], "what_to_watch": company["brief"],
                    "why_watch": "Support the owner's reporting decision.", "decision_guidance": company["owner_policy"],
                    "sources": public["sources"], "delivery_methods": _routes(company["id"], company["destinations"]),
                    "retrieval_mode": "fixed", "investigation_mode": "none"}),):
                    if attempts["paid"] >= MAX_PAID_ATTEMPTS or attempts["companies"][company["id"]] >= MAX_JEV_PER_COMPANY:
                        raise RuntimeError("paid attempt budget exhausted")
                    attempts["paid"] += 1
                    attempts["companies"][company["id"]] += 1
                    record({"kind": "paid_attempt", "company": company["id"], "operation": operation, "attempt": attempts["paid"]})
                    try:
                        draft = await _call(session, operation, call)
                        record({"kind": "paid_success", "company": company["id"], "operation": operation})
                    except Exception as error:
                        record({"kind": "paid_error", "company": company["id"], "operation": operation, "error": type(error).__name__})
                        raise
                card_id = draft["card"]["id"]
                if attempts["paid"] >= MAX_PAID_ATTEMPTS or attempts["companies"][company["id"]] >= MAX_JEV_PER_COMPANY:
                    raise RuntimeError("paid attempt budget exhausted")
                attempts["paid"] += 1
                attempts["companies"][company["id"]] += 1
                record({"kind": "paid_attempt", "company": company["id"], "operation": "preview_investigation_report", "attempt": attempts["paid"]})
                try:
                    preview = await _call(session, "preview_investigation_report", {"card_id": card_id})
                    record({"kind": "paid_success", "company": company["id"], "operation": "preview_investigation_report"})
                except Exception as error:
                    record({"kind": "paid_error", "company": company["id"], "operation": "preview_investigation_report", "error": type(error).__name__})
                    return {"company": company["id"], "tools": tools, "paid_attempts": attempts["companies"][company["id"]],
                            "draft": draft, "preview_error": type(error).__name__,
                            "failed_attempts_retained": True}
        return {"company": company["id"], "tools": tools, "paid_attempts": attempts["companies"][company["id"]],
                "draft": draft, "preview": preview, "score": _score_preview(preview, company, company["periods"][2]),
                "failed_attempts_retained": True}


def run_trial(output: Path, *, live: bool = False, binary: Path | None = None, key_file: Path | None = None) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be new and no-resume")
    output.mkdir(parents=True, exist_ok=True)
    protocol = _frozen_protocol(binary.resolve() if binary else None)
    (output / "frozen_protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    if not live:
        return {"status": "dry_run", "intended_denominator": 3, "paid_attempts": 0}
    if binary is None or key_file is None:
        raise ValueError("--live requires --binary and --key-file")
    fixture_script = Path(__file__).with_name("fixture_snapshot_mcp.py").resolve()
    attempts = {"paid": 0, "companies": {company_id: 0 for company_id in COMPANIES}}
    events: list[dict[str, Any]] = []
    event_file = output / "events.jsonl"
    results = []
    for company in cases():
        try:
            frozen = next(item for item in protocol["frozen_inputs"] if item["id"] == company["id"])
            results.append(asyncio.run(_live_company(binary.resolve(), key_file.resolve(), company, fixture_script,
                                                     frozen["captured_at"], attempts, events, event_file)))
        except Exception as error:
            event = {"kind": "company_error", "company": company["id"], "error": type(error).__name__}
            events.append(event)
            with event_file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")
            results.append({"company": company["id"], "error": "live_attempt_failed", "failed_attempts_retained": True,
                            "paid_attempts": attempts["companies"][company["id"]]})
    report = {"status": "recorded", "intended_denominator": 3, "results": results,
              "binary_sha256": protocol["binary_sha256"], "paid_attempts": attempts["paid"],
              "max_paid_attempts": MAX_PAID_ATTEMPTS, "events": events,
              "request_count": "unverified_without_returned_telemetry", "all_attempts_retained": True}
    report_text = json.dumps(report, indent=2) + "\n"
    scan = _scan_exact_secrets(report_text, key_file)
    _scan_exact_secrets(event_file.read_text(encoding="utf-8") if event_file.exists() else "", key_file)
    report["artifact_secret_scan"] = scan
    report_text = json.dumps(report, indent=2) + "\n"
    _scan_exact_secrets(report_text, key_file)
    (output / "report.json").write_text(report_text)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    if args.live and (args.binary is None or args.key_file is None):
        parser.error("--live requires --binary and --key-file")
    print(json.dumps(run_trial(args.output, live=args.live, binary=args.binary, key_file=args.key_file), indent=2))


if __name__ == "__main__":
    main()

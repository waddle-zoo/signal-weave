"""Change a real test-owned Cube definition and check the existing native card's declaration gate.

Uses the pilot's actual installed home, preserving a SQLite backup first. No
frontier calls; evaluation is opt-in because a failed gate could call Decisions.
The new model remains installed as the explicitly recorded next source phase.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import subprocess
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import httpx
import jwt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evaluations.bootstrap_agent_trial import Audit
from evaluations.cube_fixture_control import capture
from evaluations.cube_source import CubeCompany
from evaluations.cube_target import verify_target
from evaluations.decisions_semantic_trial import save
from evaluations.installed_trial_transport import (
    InstalledServer,
    _initialize_mcp_session,
    _manifest,
    _source_server,
    _SourceSession,
)
from evaluations.semantic_company import SemanticCompany
from scripts.binary_provenance import verify_binary
from signalweave.models import SourceRef

ROOT = Path(__file__).resolve().parents[1]


def source_environment(person):
    return {"HOME": str(person), "CODEX_HOME": str(person / ".codex"),
            "SIGNALWEAVE_HOME": str(person / ".signalweave"), "TMPDIR": str(person / ".tmp"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TYPESAFE_BASE_URL": "http://127.0.0.1:9"}


def expected_credit_adjustment(phase, oracle):
    with oracle._connect() as db:
        names = [row[1] for row in db.execute("PRAGMA table_info(transactions)")]
    amounts = {"2026-08": Decimal(0), "2026-09": Decimal(0)}
    for raw in phase["raw_rows"]:
        row = dict(zip(names, raw, strict=True))
        if row["period"] not in amounts or (row["revenue_class"], row["status"], row["eligible"], row["available"]) != ("merchandise", "posted", 1, 1):
            continue
        net_minor = row["gross_cents"] - row["refund_cents"] - row["tax_cents"] - row["credit_cents"]
        amounts[row["period"]] += (Decimal(net_minor) / 100 * (Decimal(row["fx_micros"]) / 1_000_000)
                                   * (Decimal(row["activity_bp"]) / 10_000))
    return {period: value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for period, value in amounts.items()}


async def connect(binary, person, env, audit, action):
    parameters = StdioServerParameters(command=str(binary), args=["serve", "--home", str(person / ".signalweave")],
                                       cwd=str(person), env=env)
    async with stdio_client(parameters) as streams, ClientSession(*streams) as session:
        initialized = await _initialize_mcp_session(session)
        return await action(InstalledServer(session, initialized.instructions, audit))


async def run(args):
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    pilot = json.loads((args.pilot / "report.json").read_text())
    if not pilot.get("pilot_complete") or len(pilot["readers"]) != 4 or not all(all(row["checks"].values()) for row in pilot["readers"]):
        raise ValueError("Requires the closed, passing public-install pilot")
    person = args.pilot.resolve() / "person"
    binary = person / ".local/bin/signalweave"
    identity = verify_binary(binary)
    if identity["source_sha256"] != pilot["build"]["source_sha256"]:
        raise ValueError("Installed production code changed since the pilot")
    state = person / ".signalweave/state/signalweave.db"
    if not state.is_file():
        raise ValueError("The actual onboarded SQLite state is missing")
    backup = root / "native-before.db"
    with sqlite3.connect(state) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    backup.chmod(0o600)
    key = (person / ".signalweave/openai.key").read_text().strip()
    audit = Audit(path=root / "native-audit.jsonl", secrets=(key,))
    info = json.loads((args.fixture / "fixture.json").read_text())
    oracle = SemanticCompany(args.fixture / "ledger", info["company"], seed=info["seed"])
    before = capture(args, oracle)
    model_file = args.fixture / "model/revenue.yml"
    original = model_file.read_bytes()
    (root / "model-before.yml").write_bytes(original)
    model = json.loads(original)
    canonical = next(measure for cube in model["cubes"] for measure in cube["measures"]
                     if measure.get("meta", {}).get("resource") == "metric:net-revenue")
    if canonical["meta"]["revision"] != "r3":
        raise ValueError("Requires the original r3 source phase; do not silently resume a mutation")
    environment = dict(line.split("=", 1) for line in (args.fixture / "private.env").read_text().splitlines())
    token = jwt.encode({"sub": "finance-readonly", "exp": int(time.time()) + 1800},
                       environment["SW_CUBE_API_SECRET"], algorithm="HS256")
    report = {"complete": False, "build": identity, "before": before,
              "scope": "Actual Cube model/formula change, unchanged Postgres records; operator-declared bridge lineage update and native reconnect. Not automatic upstream revision discovery."}
    env = source_environment(person)
    card_id = pilot["onboarding"]["submission"]["card_id"]
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{info['port']}/cubejs-api/v1/",
                                headers={"Authorization": token}, trust_env=False) as client:
        company = CubeCompany(client, oracle)
        await company.refresh_catalog()
        original_manifest = json.loads((args.pilot / "sources.json").read_text())
        original_endpoint = original_manifest["connections"][0]["transport"]["url"]
        async with _source_server(_SourceSession(company, audit, company.tenant_id), stable_url=original_endpoint) as url:
            def bind_manifest(stage):
                manifest = _manifest({"scenario_id": company.tenant_id, "catalog": company.descriptors()}, url)
                manifest["connections"][0]["context_namespace"] = "cube-semantic/" + info["company"]
                path = root / f"sources-{stage}.json"
                save(path, manifest)
                result = subprocess.run([str(binary), "connections", "update", "--source", "mcp", "--manifest", str(path),
                                         "--home", str(person / ".signalweave")], env=env, cwd=person,
                                        capture_output=True, text=True, timeout=30)
                if result.returncode:
                    raise ValueError("Operator manifest update failed: " + audit.redact(result.stderr)[:500])
                return {"returncode": result.returncode, "manifest": path.name}

            try:
                report["operator_reconnect_before"] = await asyncio.to_thread(bind_manifest, "r3")
                async def inspect(server):
                    return (await server.call_tool("inspect_insight_context", {"card_id": card_id}))[1]
                report["before_dependencies"] = await connect(binary, person, env, audit, inspect)
                if not report["before_dependencies"]["required_current"]:
                    raise ValueError("Same-source reconnect spuriously invalidated the reviewed binding")
                verify_target(args.docker, args.fixture, args.project)
                canonical["meta"]["revision"] = "r4"
                canonical["meta"]["definition"] = "Posted merchandise sales less refunds, sales tax and credits; excludes shipping and gift cards."
                canonical["description"] = canonical["meta"]["definition"]
                canonical["sql"] = "(net_amount_cents-credit_cents)::numeric * fx_micros * activity_bp / 1000000000000.0"
                model_file.write_text(json.dumps(model, indent=2) + "\n")
                (root / "model-after.yml").write_bytes(model_file.read_bytes())
                restart = await asyncio.create_subprocess_exec(str(args.docker), "--context", "desktop-linux", "compose",
                    "--env-file", str(args.fixture / "private.env"), "-f", str(ROOT / "evaluations/cube/compose.yml"),
                    "-p", args.project, "restart", "cube", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                _, restart_errors = await asyncio.wait_for(restart.communicate(), 60)
                if restart.returncode:
                    raise ValueError("Test Cube restart failed: " + restart_errors.decode()[:500])
                for attempt in range(40):
                    try:
                        await company.refresh_catalog()
                        break
                    except httpx.TransportError:
                        if attempt == 39:
                            raise
                        await asyncio.sleep(0.5)
                after = capture(args, oracle)
                report["after"] = after
                report["independent_r4_values"] = expected_credit_adjustment(after, oracle)
                snapshot = await company.inspect(SourceRef(key="changed", adapter="company", resource="metric:net-revenue", label="Revenue"))
                report["changed_snapshot"] = snapshot.model_dump(mode="json")
                report["operator_reconnect_after"] = await asyncio.to_thread(bind_manifest, "r4")
                async def evaluate(server):
                    dependency = (await server.call_tool("inspect_insight_context", {"card_id": card_id}))[1]
                    packet = (await server.call_tool("evaluate_insight_card", {
                        "card_id": card_id, "idempotency_key": "cube-real-source-revision:r4:1", "response_mode": "full"}))[1]
                    return dependency, packet
                dependency, packet = await connect(binary, person, env, audit, evaluate)
                report.update(after_dependencies=dependency, packet=packet, checks={
                    "raw_records_unchanged": before["raw_rows_sha256"] == after["raw_rows_sha256"],
                    "actual_model_changed": before["model_sha256"] != after["model_sha256"],
                    "view_unchanged": before["semantic_view_sql"] == after["semantic_view_sql"],
                    "r4_from_cube": snapshot.metadata["metric_revision"] == "r4",
                    "r4_current_correct": abs(Decimal(str(snapshot.observations[0].current)) - report["independent_r4_values"]["2026-09"]) <= Decimal("0.005"),
                    "r4_previous_correct": abs(Decimal(str(snapshot.observations[0].previous)) - report["independent_r4_values"]["2026-08"]) <= Decimal("0.005"),
                    "source_change_detected": not dependency["required_current"] and any(entry["status"] == "source_changed" for entry in dependency["entries"]),
                    "no_outcome": packet["result"]["outcome"] is None,
                    "reason": packet["result"]["judgment"]["reason"] == "context_review_required",
                    "no_routes": packet["result"]["delivery_methods"] == [],
                    "no_provider_attempt": packet["result"]["judgment"].get("provider_call_attempted") is False,
                    "fresh_receipt": packet.get("replayed") is False and packet["receipt"]["idempotency_key"] == "cube-real-source-revision:r4:1",
                })
                report["complete"] = all(report["checks"].values())
            finally:
                report["cube_requests"] = company.requests
                save(root / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fixture", "pilot", "output", "docker"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live or not args.project.startswith("sw-cube-"):
        parser.error("Explicit --live and test-owned sw-cube- project required")
    args.fixture, args.pilot, args.output = args.fixture.resolve(), args.pilot.resolve(), args.output.resolve()
    report = asyncio.run(run(args))
    print(json.dumps({"complete": report["complete"], "checks": report.get("checks")}))
    if not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Test-owned Postgres phase capture and one hand-computable Cube control, no agents/API spend."""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import subprocess
import time
from decimal import Decimal
from pathlib import Path

import httpx
import jwt

from evaluations.cube_source import CubeCompany
from evaluations.cube_target import verify_target
from evaluations.semantic_company import SemanticCompany
from signalweave.models import SourceRef

ROOT = Path(__file__).resolve().parents[1]


def postgres(args, sql, *, user="fixture_admin", check=True):
    verify_target(args.docker, args.fixture, args.project)
    command = [str(args.docker), "--context", "desktop-linux", "compose", "--env-file", str(args.fixture / "private.env"),
               "-f", str(ROOT / "evaluations/cube/compose.yml"), "-p", args.project,
               "exec", "-T", "postgres", "psql", "--no-psqlrc", "--set", "ON_ERROR_STOP=1",
               "--tuples-only", "--no-align", "-U", user, "-d", "semantic_trial"]
    return subprocess.run(command, input=sql, text=True, capture_output=True, check=check, timeout=30)


def capture(args, oracle):
    target = verify_target(args.docker, args.fixture, args.project)
    with oracle._connect() as db:
        columns = [(row[1], row[2]) for row in db.execute("PRAGMA table_info(transactions)")]
    output = postgres(args, "COPY (SELECT * FROM transactions ORDER BY id) TO STDOUT WITH (FORMAT CSV);").stdout
    rows = [[int(value) if kind == "INTEGER" else value for value, (_, kind) in zip(row, columns, strict=True)]
            for row in csv.reader(io.StringIO(output))]
    return {"verified_target": target, "raw_rows": rows, "raw_rows_sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
            "semantic_view_sql": postgres(args, "SELECT pg_get_viewdef('semantic_transactions',true);").stdout,
            "model_sha256": hashlib.sha256((args.fixture / "model/revenue.yml").read_bytes()).hexdigest()}


async def run(args):
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    info = json.loads((args.fixture / "fixture.json").read_text())
    if info["company"] != "retail":
        raise ValueError("The declared USD/0.82 hand control is retail-specific")
    oracle = SemanticCompany(args.fixture / "ledger", "retail", seed=info["seed"])
    before = capture(args, oracle)
    if before["raw_rows_sha256"] != info["raw_seed_sha256"]:
        raise ValueError("Actual Postgres records differ from the frozen seed")
    with oracle._connect() as db:
        row = db.execute("SELECT id,gross_cents,fx_micros,activity_bp FROM transactions WHERE period='2026-09' "
                         "AND revenue_class='merchandise' AND status='posted' AND eligible=1 AND currency='USD' ORDER BY id LIMIT 1").fetchone()
    if row is None or (row["fx_micros"], row["activity_bp"]) != (1_000_000, 8200):
        raise ValueError("The fixture does not contain the declared hand-control conditions")
    environment = dict(line.split("=", 1) for line in (args.fixture / "private.env").read_text().splitlines())
    token = jwt.encode({"sub": "finance-readonly", "exp": int(time.time()) + 1800},
                       environment["SW_CUBE_API_SECRET"], algorithm="HS256")
    report = {"complete": False, "before": before, "control_row": dict(row),
              "expected_increment": "0.82", "derivation": "100 USD minor units / 100 × 1.0 FX × 0.82 activity = 0.82 USD",
              "scope": "Only the declared disposable synthetic project; the modified source row is restored before any agent trial."}
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{info['port']}/cubejs-api/v1/",
                                headers={"Authorization": token}, trust_env=False) as client:
        source = CubeCompany(client, oracle)
        ref = SourceRef(key="control", adapter="company", resource="metric:net-revenue", label="Revenue")
        baseline = await source.inspect(ref)
        try:
            postgres(args, f"UPDATE transactions SET gross_cents=gross_cents+100 WHERE id={int(row['id'])};")
            changed = await source.inspect(ref)
            report["changed"] = capture(args, oracle)
            report["observed_increment"] = str(Decimal(str(changed.observations[0].current)) - Decimal(str(baseline.observations[0].current)))
            report["increment_correct"] = abs(Decimal(report["observed_increment"]) - Decimal("0.82")) < Decimal("0.00000001")
            report["query_source_changed"] = baseline.metadata["data_snapshot_id"] != changed.metadata["data_snapshot_id"]
        finally:
            postgres(args, f"UPDATE transactions SET gross_cents={int(row['gross_cents'])} WHERE id={int(row['id'])};")
            report["restored"] = capture(args, oracle)
            report["restored_exact_raw_seed"] = report["restored"]["raw_rows_sha256"] == before["raw_rows_sha256"]
            report["requests"] = source.requests
            attempt = postgres(args, "UPDATE transactions SET gross_cents=gross_cents WHERE false;", user="cube_reader", check=False)
            report["reader_write_rejected"] = attempt.returncode != 0 and "read-only transaction" in attempt.stderr
            report["complete"] = all(report.get(key) is True for key in (
                "increment_correct", "query_source_changed", "restored_exact_raw_seed", "reader_write_rejected"))
            path = args.output / "report.json"
            path.write_text(json.dumps(report, indent=2) + "\n")
            path.chmod(0o600)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--docker", type=Path, required=True)
    args = parser.parse_args()
    args.fixture, args.output = args.fixture.resolve(), args.output.resolve()
    if not args.project.startswith("sw-cube-"):
        parser.error("Use an explicit sw-cube- test-owned project")
    report = asyncio.run(run(args))
    print(json.dumps({key: report.get(key) for key in (
        "complete", "increment_correct", "query_source_changed", "restored_exact_raw_seed", "reader_write_rejected")}))
    if not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

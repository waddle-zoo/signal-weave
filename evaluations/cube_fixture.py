"""Prepare a real Cube/Postgres fixture; never used by the SignalWeave runtime.

SQLite supplies reproducible raw seed rows and an independent Decimal oracle.
Only Cube's REST API supplies the integration's aggregate measurements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path

from evaluations.semantic_company import SemanticCompany

CUBE_IMAGE = "cubejs/cube@sha256:5a728f42924051b9499016fb1ac9d1695ab544084d57221c0dd173e4c730730a"
POSTGRES_IMAGE = "postgres@sha256:d81f7b51697014367236d07ec58b54153fc28f828b72bf247fe5c7487520bcb0"


def _literal(value):
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise ValueError("Unexpected seed value")


def prepare(root: Path, company_name: str, *, seed: int = 20261025, port: int = 4406) -> dict:
    if not 1024 <= port <= 65535:
        raise ValueError("Use an unprivileged fixture port")
    root = root.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    company = SemanticCompany(root / "ledger", company_name, seed=seed)
    company.set_condition("decline")
    passwords = {key: secrets.token_urlsafe(32) for key in ("ADMIN", "READER", "API")}
    with company._connect() as db:
        columns = [(row[1], row[2]) for row in db.execute("PRAGMA table_info(transactions)")]
        raw = [tuple(row) for row in db.execute("SELECT * FROM transactions ORDER BY id")]
        coverage = [tuple(row) for row in db.execute("SELECT period,required_rows,available_rows FROM period_coverage ORDER BY period")]
        view = db.execute("SELECT sql FROM sqlite_master WHERE name='semantic_transactions'").fetchone()[0]
        definitions = [dict(row) for row in company._definition_rows()]
    sql = ["CREATE TABLE transactions (" + ",".join(
        name + (" bigint" if kind == "INTEGER" else " text") for name, kind in columns) + ");"]
    sql.extend("INSERT INTO transactions VALUES (" + ",".join(map(_literal, row)) + ");" for row in raw)
    sql.extend([view + ";", "CREATE TABLE period_coverage (period text PRIMARY KEY,required_rows bigint,available_rows bigint);"])
    sql.extend("INSERT INTO period_coverage VALUES (" + ",".join(map(_literal, row)) + ");" for row in coverage)
    sql.extend(["CREATE VIEW cube_transactions AS SELECT t.*, c.required_rows AS expected_records FROM semantic_transactions t LEFT JOIN period_coverage c ON t.period=c.period;",
                "CREATE ROLE cube_reader LOGIN PASSWORD " + _literal(passwords["READER"]) + ";",
                "GRANT USAGE ON SCHEMA public TO cube_reader;",
                "GRANT SELECT ON transactions,semantic_transactions,period_coverage,cube_transactions TO cube_reader;",
                "ALTER ROLE cube_reader SET default_transaction_read_only=on;"])
    seed_sql = root / "seed.sql"
    seed_sql.write_text("\n".join(sql) + "\n")
    seed_sql.chmod(0o600)
    model = root / "model"
    model.mkdir()
    cubes = []
    for index, row in enumerate(definitions):
        # All metadata comes from the fixture owner's versioned definition,
        # then is discovered from Cube /meta by readers, not from this file.
        meta = {key: row[key] for key in (
            "resource", "metric_id", "definition", "owner", "population", "currency",
            "grain", "time_semantics", "revision", "status",
        )}
        cubes.append({
            "name": f"Revenue{index}", "title": "Revenue", "sql_table": "public.cube_transactions",
            "refresh_key": {"every": "1 second"},
            "measures": [
                {"name": "amount", "title": "Revenue", "description": row["definition"], "meta": meta,
                 "type": "sum", "sql": row["measure"] + "::numeric * fx_micros * activity_bp / 1000000000000.0",
                 "filters": [{"sql": "available=1 AND (" + row["filter_sql"] + ")"}]},
                {"name": "available_records", "type": "count", "filters": [{"sql": "available=1"}]},
                {"name": "ledger_records", "type": "count"},
                {"name": "expected_records", "type": "max", "sql": "expected_records"},
            ],
            "dimensions": [
                {"name": "id", "sql": "id", "type": "number", "primary_key": True},
                {"name": "month", "sql": "to_date(period || '-01', 'YYYY-MM-DD')", "type": "time"},
            ],
        })
    model_file = model / "revenue.yml"
    # JSON is valid YAML; avoid a new dependency just for fixture serialization.
    model_file.write_text(json.dumps({"cubes": cubes}, indent=2) + "\n")
    (root / "cube.js").write_text("module.exports = {};\n")
    env = {
        "SW_CUBE_FIXTURE_DIR": str(root), "SW_CUBE_PORT": str(port),
        "SW_CUBE_DB_ADMIN_PASSWORD": passwords["ADMIN"],
        "SW_CUBE_DB_READER_PASSWORD": passwords["READER"], "SW_CUBE_API_SECRET": passwords["API"],
    }
    private_env = root / "private.env"
    private_env.write_text("\n".join(key + "=" + value for key, value in env.items()) + "\n")
    private_env.chmod(0o600)
    report = {
        "company": company_name, "seed": seed, "port": port, "cube_image": CUBE_IMAGE,
        "postgres_image": POSTGRES_IMAGE, "model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
        "raw_seed_sha256": hashlib.sha256(json.dumps(raw).encode()).hexdigest(),
        "raw_rows": len(raw), "metric_definitions": len(definitions),
        "independent_oracles": [company.expected(row["resource"]) for row in definitions],
        "scope": "Synthetic company ledger loaded into real Postgres; governed aggregates must be read from real Cube API.",
    }
    (root / "fixture.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--company", choices=["retail", "saas", "marketplace"], default="retail")
    parser.add_argument("--port", type=int, default=4406)
    args = parser.parse_args()
    report = prepare(args.output, args.company, port=args.port)
    print(json.dumps({key: value for key, value in report.items() if key != "independent_oracles"}, indent=2))


if __name__ == "__main__":
    main()

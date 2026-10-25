"""Check real Cube outputs against the private Decimal oracle before paid agent trials."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path

import httpx
import jwt

from evaluations.cube_source import CubeCompany
from evaluations.semantic_company import SemanticCompany
from signalweave.models import SourceRef


async def reconcile(fixture: Path, output: Path):
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    definition = json.loads((fixture / "fixture.json").read_text())
    environment = dict(line.split("=", 1) for line in (fixture / "private.env").read_text().splitlines())
    token = jwt.encode({"sub": "finance-readonly", "exp": int(time.time()) + 3600},
                       environment["SW_CUBE_API_SECRET"], algorithm="HS256")
    oracle = SemanticCompany(fixture / "ledger", definition["company"], seed=definition["seed"])
    base = f"http://127.0.0.1:{definition['port']}/cubejs-api/v1/"
    report = {"complete": False, "cases": [], "scope": "Real semantic API execution on synthetic data; no agent quality or superiority claim."}
    async with httpx.AsyncClient(base_url=base, headers={"Authorization": token}, trust_env=False) as client:
        unauth = await client.get("meta", headers={"Authorization": ""})
        report["unauthenticated_rejected"] = unauth.status_code in (401, 403)
        company = CubeCompany(client, oracle)
        try:
            await company.refresh_catalog()
            report["catalog_sha256"] = hashlib.sha256(json.dumps(company.catalog, sort_keys=True).encode()).hexdigest()
            for descriptor in company.descriptors():
                resource = descriptor["resource"]
                result = await company.inspect(SourceRef(key="source", adapter=company.name, resource=resource, label=descriptor["title"]))
                expected = oracle.expected(resource)
                actual = result.observations[0]
                checks = {
                    "current": abs(Decimal(str(actual.current)) - expected["current"]) <= Decimal("0.005"),
                    "previous": abs(Decimal(str(actual.previous)) - expected["previous"]) <= Decimal("0.005"),
                    "identity": actual.metric == expected["metric_id"],
                    "unit": actual.unit == expected["unit"],
                    "coverage": result.contract.comparison_contracts[0].coverage == "complete",
                    "actual_cube_sql": bool(result.metadata["cube_compiled_sql"]),
                }
                report["cases"].append({"resource": resource, "checks": checks,
                                        "expected": expected, "snapshot": result.model_dump(mode="json")})
            report["complete"] = (report["unauthenticated_rejected"] and len(report["cases"]) == 6
                                  and all(all(case["checks"].values()) for case in report["cases"]))
        finally:
            report["requests"] = company.requests
            path = output / "report.json"
            path.write_text(json.dumps(report, indent=2, default=str) + "\n")
            path.chmod(0o600)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(reconcile(args.fixture.resolve(), args.output.resolve()))
    print(json.dumps({"complete": report["complete"], "cases": [
        {"resource": case["resource"], "checks": case["checks"]} for case in report["cases"]]}, indent=2))
    if not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

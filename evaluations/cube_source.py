"""Research-only normalization of actual Cube REST results, with no metric SQL execution here."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from evaluations.semantic_company import SemanticCompany
from signalweave.models import (
    Evidence,
    Observation,
    ResourceContract,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceComparisonContract,
    SourceRef,
)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CubeCompany:
    """The existing company MCP interface, reading real governed Cube measures.

    Only `expected` uses the independent seed ledger, and the MCP never exposes
    that method. Catalog meaning and measurement values come from Cube itself.
    """

    name = "company"
    canonical_resource = "metric:net-revenue"
    current_period = "2026-09"
    previous_period = "2026-08"
    business_policy = SemanticCompany.business_policy

    def __init__(self, client: httpx.AsyncClient, oracle: SemanticCompany):
        self.client = client
        self.oracle = oracle
        self.company = oracle.company
        self.profile = oracle.profile
        self.tenant_id = "local"
        self.catalog = {}
        self.requests = []

    @property
    def metric_id(self):
        return self.catalog[self.canonical_resource]["meta"]["metric_id"]

    @property
    def unit(self):
        return self.catalog[self.canonical_resource]["meta"]["currency"]

    async def request(self, path, *, query=None):
        params = {"query": json.dumps(query)} if query is not None else None
        if path == "load":
            params = {**(params or {}), "cache": "no-cache"}
        for attempt in range(20):
            response = await self.client.get(path, params=params, timeout=60)
            response.raise_for_status()
            body = response.json()
            self.requests.append({"path": path, "query": query,
                                  "cache": "no-cache" if path == "load" else None, "response": body})
            if body.get("error") == "Continue wait" and attempt < 19:
                await asyncio.sleep(0.25)
                continue
            if body.get("error"):
                raise ValueError("Cube returned an error: " + str(body["error"])[:500])
            return body
        raise TimeoutError("Cube did not complete the bounded query")

    async def refresh_catalog(self):
        body = await self.request("meta")
        catalog = {}
        for cube in body["cubes"]:
            for measure in cube["measures"]:
                if not isinstance(measure.get("meta"), dict) or "resource" not in measure["meta"]:
                    continue
                resource = measure["meta"]["resource"]
                if resource in catalog:
                    raise ValueError("Ambiguous duplicate Cube resource mapping")
                catalog[resource] = {**measure, "cube_name": cube["name"]}
        if self.canonical_resource not in catalog:
            raise ValueError("Cube does not expose the configured canonical source")
        self.catalog = catalog
        return body

    def contract(self, row, *, coverage="unknown", detail=""):
        meta = row["meta"]
        key = meta["metric_id"] + "-calendar-month"
        return ResourceContract(
            tenant_id=self.tenant_id, domain=self.profile["domain"], authorized=True,
            scope=f"Cube measure {row['name']}; source owner {meta['owner']}; revision {meta['revision']} ({meta['status']}). Synthetic company on real Cube/Postgres.",
            metric_names=[meta["metric_id"]], population=meta["population"], grain=meta["grain"],
            available_comparison_windows=["previous_period"], required_comparison_keys=[key],
            lineage=["cube-measure:" + row["name"], "source-definition:" + meta["metric_id"] + ":" + meta["revision"]],
            comparison_contracts=[SourceComparisonContract(
                key=key, metric=meta["metric_id"], definition=meta["definition"],
                population=meta["population"], unit=meta["currency"], comparison_window="previous_period",
                coverage=coverage, comparable=coverage == "complete", detail=detail,
                query_refs=["cube-measure:" + row["name"]],
            )],
        )

    def descriptors(self):
        return [ResourceDescriptor(
            adapter=self.name, resource=resource, title="Revenue", kind="semantic_metric",
            description=row["description"] + " Synthetic data queried through a real Cube semantic model.",
            metadata={"cube_measure": row["name"], **row["meta"]}, contract=self.contract(row),
        ).model_dump(mode="json") for resource, row in self.catalog.items()]

    def notes(self):
        row = self.catalog[self.canonical_resource]
        return [
            {"title": "Finance source definition", "body": row["meta"]["definition"],
             "source_refs": [self.name + "|" + self.canonical_resource],
             "provenance": ["cube-meta:" + row["name"]]},
            {"title": "Finance owner policy", "body": self.business_policy,
             "provenance": ["fictional-finance-owner:policy-v1"]},
        ]

    def expected(self, resource=None):
        return self.oracle.expected(resource)

    async def inspect(self, source: SourceRef):
        if source.adapter != self.name:
            raise ValueError("Wrong Cube source adapter")
        await self.refresh_catalog()
        if source.resource not in self.catalog:
            raise ValueError("Unknown Cube semantic resource")
        row = self.catalog[source.resource]
        cube, meta = row["cube_name"], row["meta"]
        query = {
            "measures": [row["name"], cube + ".available_records", cube + ".ledger_records", cube + ".expected_records"],
            "timeDimensions": [{"dimension": cube + ".month", "granularity": "month",
                                "dateRange": ["2026-08-01", "2026-09-30"]}],
            "timezone": "UTC", "limit": 3,
        }
        compiled = await self.request("sql", query=query)
        loaded = await self.request("load", query=query)
        periods = {}
        for item in loaded["data"]:
            period = item[cube + ".month.month"][:7]
            if period in periods:
                raise ValueError("Duplicate Cube measurement period")
            periods[period] = item
        if set(periods) != {self.current_period, self.previous_period}:
            raise ValueError("Cube omitted a required comparison period; missing is not zero")
        current, previous = (None if periods[p][row["name"]] is None else Decimal(str(periods[p][row["name"]]))
                             for p in (self.current_period, self.previous_period))
        if any(value is None or not value.is_finite() for value in (current, previous)):
            raise ValueError("Cube returned a missing or non-finite metric")
        def count(value):
            if value is None:
                return None
            number = Decimal(str(value))
            if not number.is_finite() or number < 0 or number != number.to_integral_value():
                raise ValueError("Cube coverage count is not a nonnegative integer")
            return int(number)

        coverage = {period: {field: count(item.get(cube + "." + measure))
                            for field, measure in (("available", "available_records"),
                                                   ("observed", "ledger_records"), ("expected", "expected_records"))}
                    for period, item in periods.items()}
        complete = all(item["expected"] is not None and item["available"] is not None
                       and item["available"] == item["observed"] == item["expected"] for item in coverage.values())
        change = (current - previous) / previous * 100 if previous else None
        now = datetime.now(timezone.utc)
        refreshed = loaded.get("lastRefreshTime")
        source_time = datetime.fromisoformat(refreshed.replace("Z", "+00:00")) if isinstance(refreshed, str) else None
        snapshot_id = "cube-result-sha256:" + digest({"measure": row["name"], "data": loaded["data"]})
        refs = ["cube-measure:" + row["name"], "cube-sql-sha256:" + digest(compiled), snapshot_id]
        values = {"current": float(current), "previous": float(previous), "current_period": self.current_period,
                  "previous_period": self.previous_period, "unit": meta["currency"],
                  "metric_id": meta["metric_id"], "metric_revision": meta["revision"],
                  "data_snapshot_id": snapshot_id, "cube_query": query, "ledger_coverage": coverage}
        return ResourceSnapshot(
            source_key=source.key, adapter=self.name, resource=source.resource, title="Revenue",
            description="Synthetic company; actual Cube/Postgres aggregate, not a source-owned Python calculation.",
            captured_at=now, source_captured_at=source_time,
            contract=self.contract(row, coverage="complete" if complete else "partial",
                                   detail="Ledger availability counts precede metric population filters; they are not contributing-record counts."),
            observations=[Observation(source_key=source.key, subject_id=meta["metric_id"], metric=meta["metric_id"],
                unit=meta["currency"], current=float(current), previous=float(previous), baseline=float(previous),
                change_pct=float(change) if change is not None else None,
                comparison_baselines={"previous_period": float(previous)},
                dimensions={"period": self.current_period, "baseline_period": self.previous_period},
                attributes={**meta, "historical_measurements": True, "archival_mode_required": True})],
            evidence=[Evidence(source_key=source.key, subject_id=meta["metric_id"], statement="Cube returned the requested completed-month aggregates.",
                               values=values, provenance=refs)],
            metadata={"cube_query": query, "cube_compiled_sql": compiled, "metric_revision": meta["revision"],
                      "semantic_definition_sha256": digest(meta), "data_snapshot_id": snapshot_id,
                      "historical_measurements": True,
                      "archival_mode_required": True, "live_connector": True,
                      "source_identity": {"tenant_id": self.tenant_id, "adapter": self.name, "resource": source.resource}},
        )

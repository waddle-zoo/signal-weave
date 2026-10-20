"""Fixed, deployment-reviewed queries over an existing Superset connection.

The agent owns SQL and its meaning. This adapter owns transport and lossless
tabular evidence, not metric inference or policy. The catalog is executable
deployment configuration, never supplied by an evaluation caller.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlglot
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlglot import exp

from .models import Evidence, ResourceContract, ResourceDescriptor, ResourceSnapshot, SourceRef
from .source_identity import namespace_fingerprint
from .sources import SourceParameterError, source_read_instant

DATE_TOKEN = "{{cutoff_date}}"
MAX_CATALOG_BYTES = 2_000_000
MAX_QUERY_RESPONSE_BYTES = 1_000_000


class QueryClock(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["business_date", "explicit"]
    timezone: str | None = None
    lag_days: int = Field(default=0, ge=0, le=365)

    @model_validator(mode="after")
    def valid_clock(self):
        if self.kind == "business_date":
            if not self.timezone:
                raise ValueError("business_date requires an explicit IANA timezone")
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("unknown business timezone") from None
        elif self.timezone is not None or self.lag_days:
            raise ValueError("explicit dates do not accept timezone or lag_days")
        return self

    def cutoff(self, now: datetime | None = None) -> date:
        if self.kind == "explicit":
            value = os.getenv("SIGNALWEAVE_QUERY_AS_OF_DATE", "")
            try:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value:
                    raise ValueError
            except ValueError:
                raise SourceParameterError("Explicit query clock requires SIGNALWEAVE_QUERY_AS_OF_DATE=YYYY-MM-DD") from None
            return parsed
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("Query clock requires an aware instant")
        return instant.astimezone(ZoneInfo(self.timezone)).date() - timedelta(days=self.lag_days)


def validate_read_query(sql: str, dialect: str) -> None:
    """Reject unsupported statements, not claim to sandbox SQL functions."""
    try:
        statements = sqlglot.parse(sql.replace(DATE_TOKEN, "2000-01-01"), read=dialect)
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
            raise ValueError
        forbidden = (exp.DML, exp.DDL, exp.Command, exp.Into, exp.Lock, exp.Parameter, exp.Placeholder)
        if any(isinstance(node, forbidden) for node in statements[0].walk()):
            raise ValueError
    except Exception:  # noqa: BLE001 - parser diagnostics can echo sensitive SQL
        raise ValueError("Expected one supported SELECT query without writes, locks or unbound parameters") from None


class QueryMeaning(BaseModel):
    """Author-described meaning, never connection authority or runtime quality."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    domain: str = Field(default="unknown", min_length=1, max_length=160)
    scope: str = Field(default="", max_length=1000)
    population: str = Field(default="", max_length=1000)
    grain: str = Field(default="", max_length=1000)
    metric_names: list[str] = Field(default_factory=list, max_length=100)
    lineage: list[str] = Field(default_factory=list, max_length=100)
    available_comparison_windows: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("available_comparison_windows")
    @classmethod
    def nonblank_windows(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError("available_comparison_windows entries must not be empty")
        return values


class QueryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=240)
    definition: str = Field(min_length=1, max_length=8000)
    read_only: Literal[True]
    sql: str = Field(min_length=1, max_length=64_000)
    dialect: str = Field(min_length=1, max_length=80)
    database_id: int = Field(gt=0)
    catalog: str | None = Field(default=None, min_length=1, max_length=240)
    schema_name: str | None = Field(default=None, alias="schema", min_length=1, max_length=240)
    clock: QueryClock | None = None
    max_rows: int = Field(default=100, ge=1, le=1000)
    max_evidence_bytes: int = Field(default=100_000, ge=1000, le=1_000_000)
    timeout_seconds: int = Field(default=90, ge=1, le=300)
    meaning: QueryMeaning | None = None

    @field_validator("read_only", mode="before")
    @classmethod
    def explicit_read_only(cls, value):
        if value is not True:
            raise ValueError("read_only must be explicitly true")
        return value

    @model_validator(mode="after")
    def query_shape(self):
        remainder = self.sql.replace(DATE_TOKEN, "")
        if any(marker in remainder for marker in ("{{", "{%", "{#")):
            raise ValueError("Only the quoted cutoff_date placeholder is supported; no other Jinja")
        validate_read_query(self.sql, self.dialect)
        has_date = DATE_TOKEN in self.sql
        if has_date != (self.clock is not None):
            raise ValueError("A cutoff_date template and its explicit clock must be declared together")
        # Only one literal placeholder is supported; this is not Jinja or a
        # caller-controlled templating system. Date contents are ISO validated.
        if has_date and self.sql.count("'" + DATE_TOKEN + "'") != self.sql.count(DATE_TOKEN):
            raise ValueError("Use cutoff_date only as a complete quoted date literal")
        return self

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def resource(self) -> str:
        return f"query:{self.key}:{self.fingerprint}"

    def render(self) -> tuple[str, str | None]:
        cutoff = self.clock.cutoff(source_read_instant.get()).isoformat() if self.clock else None
        return (self.sql.replace(DATE_TOKEN, cutoff) if cutoff else self.sql, cutoff)


class QueryCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[2]
    queries: list[QueryDefinition] = Field(min_length=1, max_length=1000)

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 2:
            raise ValueError("query catalog version must be 2; review and reauthor legacy artifacts")
        return value

    @model_validator(mode="after")
    def unique_keys(self):
        if len({query.key for query in self.queries}) != len(self.queries):
            raise ValueError("Query keys must be unique")
        return self


def load_query_catalog(path: str | Path) -> QueryCatalog:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate query catalog field")
            result[key] = value
        return result

    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_CATALOG_BYTES + 1)
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("Query catalog exceeds its byte limit")
    return QueryCatalog.model_validate(json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite catalog number"))))


class SupersetQueryAdapter:
    """Execute only fixed approved artifacts; return columns without semantic mapping."""

    def __init__(self, base_adapter, catalog: QueryCatalog):
        self.name = base_adapter.name + "_sql"
        self.client = base_adapter.client
        self.tenant_id = base_adapter.tenant_id
        self.base_adapter = base_adapter
        self.queries = {query.resource: query for query in catalog.queries}
        if not self.tenant_id:
            raise ValueError("Query sources require the connection's explicit tenant")

    @property
    def binding_namespace(self):
        return namespace_fingerprint({"connection": self.base_adapter.binding_namespace, "kind": "reviewed-sql"})

    def _descriptor(self, query):
        # Healthy describes adapter availability, not author-certified business
        # trust. Execution failures propagate to the registry's source errors.
        contract = ResourceContract(tenant_id=self.tenant_id, source_status="healthy",
                                    **(query.meaning.model_dump() if query.meaning else {}))
        contract.lineage = [*contract.lineage, "reviewed-query:" + query.fingerprint]
        return ResourceDescriptor(adapter=self.name, resource=query.resource, kind="query",
            title=query.title, description=query.definition, contract=contract,
            metadata={"query_fingerprint": query.fingerprint, "clock": query.clock.model_dump() if query.clock else None,
                      "database_id": query.database_id, "catalog": query.catalog, "schema": query.schema_name})

    async def list_resources(self):
        return [self._descriptor(q) for q in self.queries.values()]

    async def authorize(self, source, *, authorized_tenants=None):
        if source.adapter != self.name:
            return None
        if authorized_tenants is not None and self.tenant_id not in set(authorized_tenants):
            return None
        if source.parameters:
            raise SourceParameterError("Reviewed queries accept no caller parameters; edit and reimport the reviewed artifact")
        query = self.queries.get(source.resource)
        return self._descriptor(query) if query else None

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        from .superset_sql import execute_sql

        policy = getattr(self.base_adapter, "policy", None)
        if policy is not None and (policy.mode.value != "live_query" or not policy.allow_live_queries):
            raise SourceParameterError("Reviewed SQL requires the Preset connection's explicit live-query permission")
        descriptor = await self.authorize(source)
        if descriptor is None:
            raise ValueError("Unknown reviewed query version; inspect the imported catalog and review its current source")
        query = self.queries[source.resource]
        sql, cutoff = query.render()
        result = await execute_sql(self.client, sql=sql, database_id=query.database_id,
            catalog=query.catalog, schema=query.schema_name, max_rows=query.max_rows,
            max_bytes=MAX_QUERY_RESPONSE_BYTES, timeout_seconds=query.timeout_seconds)
        provenance = {"query_fingerprint": query.fingerprint, "executed_sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                      "query_id": result.query_id, "client_id": result.client_id, "results_key": result.results_key,
                      "cutoff_date": cutoff, "row_count": len(result.rows), "columns": result.columns}
        evidence = [Evidence(source_key=source.key, subject_id=f"row:{index}",
            subject_label=f"Row {index + 1}", statement="Reviewed query result row.", values=row,
            provenance=[query.fingerprint, f"query:{result.query_id}"])
            for index, row in enumerate(result.rows)]
        evidence.append(Evidence(source_key=source.key, subject_id="query-execution",
            statement="Reviewed query execution record; receipt time is not source freshness or complete ingestion.",
            values=provenance, provenance=[query.fingerprint]))
        snapshot = ResourceSnapshot(source_key=source.key, adapter=self.name, resource=query.resource,
            title=query.title, description=query.definition, contract=descriptor.contract,
            evidence=evidence, metadata={**provenance, "received_at": result.received_at.isoformat()},
            source_captured_at=None)
        limit = (min(query.max_evidence_bytes, policy.max_snapshot_bytes)
                 if policy is not None else query.max_evidence_bytes)
        if len(snapshot.model_dump_json().encode()) > limit:
            raise ValueError("Reviewed query snapshot exceeds its configured byte limit; no partial evidence was returned")
        return snapshot

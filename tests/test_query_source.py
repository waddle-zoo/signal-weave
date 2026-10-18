"""Generic query definitions, clocks and native result evidence (no business rules)."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from signalweave.models import SourceRef
from signalweave.query_source import (
    QueryCatalog,
    QueryClock,
    QueryDefinition,
    SupersetQueryAdapter,
    load_query_catalog,
)


def definition(**updates):
    return QueryDefinition.model_validate({"key": "check", "title": "A reviewed query",
        "definition": "Source-defined observations; no policy labels", "read_only": True,
        "sql": "SELECT 1 AS total", "dialect": "postgres", "database_id": 1, **updates})


@pytest.mark.parametrize("sql", ["SELECT 1", "WITH x AS (SELECT 1 n) SELECT n FROM x",
    "SELECT 1 UNION ALL SELECT 2", "SELECT SUM(amount) FROM items WHERE d=DATE '{{cutoff_date}}'"])
def test_read_shapes_and_explicit_date_clock(sql, monkeypatch):
    query = definition(sql=sql, **({"clock": {"kind": "explicit"}} if "{{" in sql else {}))
    monkeypatch.setenv("SIGNALWEAVE_QUERY_AS_OF_DATE", "2026-01-05")
    assert query.render()[0] == sql.replace("{{cutoff_date}}", "2026-01-05")


@pytest.mark.parametrize("sql", ["DELETE FROM x", "SELECT 1; SELECT 2", "CREATE TABLE x AS SELECT 1",
    "WITH a AS (DELETE FROM x RETURNING *) SELECT * FROM a", "SELECT * INTO x FROM y",
    "SELECT * FROM x FOR UPDATE", "SELECT * FROM x WHERE id=:unbound", "CALL proc()", "", "COMMIT"])
def test_not_a_query_and_hidden_writes_rejected(sql):
    with pytest.raises(ValueError):
        definition(sql=sql)


@pytest.mark.parametrize("changes", [{"read_only": 1}, {"read_only": False}, {"database_id": True},
    {"max_rows": 0}, {"max_rows": 1001}, {"sql": "SELECT '{{cutoff_date}}'"},
    {"clock": {"kind": "explicit"}}, {"extra": "not-allowed"},
    {"sql": "SELECT {{cutoff_date}}", "clock": {"kind": "explicit"}}])
def test_invalid_definition_fails_before_any_source(changes):
    with pytest.raises(ValueError):
        definition(**changes)


def test_resource_identity_binds_sql_meaning_and_clock_not_measurement_cutoff(monkeypatch):
    first = definition(sql="SELECT DATE '{{cutoff_date}}'", clock={"kind": "explicit"})
    original = first.resource
    monkeypatch.setenv("SIGNALWEAVE_QUERY_AS_OF_DATE", "2026-01-01")
    first.render()
    monkeypatch.setenv("SIGNALWEAVE_QUERY_AS_OF_DATE", "2026-01-08")
    first.render()
    assert first.resource == original
    assert definition(sql="SELECT 2 AS total").resource != definition().resource
    assert definition(definition="Changed population").resource != definition().resource


@pytest.mark.asyncio
async def test_multiple_queries_keep_one_collection_instant_across_business_midnight(monkeypatch):
    from signalweave import sources, superset_sql
    from signalweave.sources import SourceRegistry, source_read_clock, source_read_instant

    before = datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)
    after = datetime(2026, 1, 2, 0, 1, tzinfo=timezone.utc)
    now = [before]

    class MovingDatetime:
        @staticmethod
        def now(zone=None):
            return now[0]

    monkeypatch.setattr(sources, "datetime", MovingDatetime)
    monkeypatch.setattr("signalweave.query_source.datetime", MovingDatetime)

    async def execute(*args, **kwargs):
        now[0] = after
        return SimpleNamespace(rows=[{"value": 1}], columns=["value"], query_id="1", client_id="id",
                               results_key=None, received_at=after)

    fake = AsyncMock(side_effect=execute)
    monkeypatch.setattr(superset_sql, "execute_sql", fake)
    q = definition(sql="SELECT DATE '{{cutoff_date}}'", clock={"kind": "business_date", "timezone": "UTC"})
    registered = adapter(q)
    registry = SourceRegistry([registered], max_concurrency=1)
    ref = SourceRef(key="first", adapter=registered.name, resource=q.resource, label="Check")
    async with source_read_clock():
        first = await registry.resolve([ref])
        second = await registry.resolve([ref.model_copy(update={"key": "next"})])
    assert first[0].metadata["cutoff_date"] == second[0].metadata["cutoff_date"] == "2026-01-01"
    assert source_read_instant.get() is None
    third = await registry.resolve([ref])
    assert third[0].metadata["cutoff_date"] == "2026-01-02"


def test_business_clock_and_explicit_historical_override_are_not_interchangeable(monkeypatch):
    instant = datetime(2026, 1, 2, 2, tzinfo=timezone.utc)
    clock = QueryClock(kind="business_date", timezone="America/Toronto", lag_days=1)
    assert clock.cutoff(instant).isoformat() == "2025-12-31"
    monkeypatch.setenv("SIGNALWEAVE_QUERY_AS_OF_DATE", "2026-02-03")
    assert clock.cutoff(instant).isoformat() == "2025-12-31"
    explicit = QueryClock(kind="explicit")
    assert explicit.cutoff().isoformat() == "2026-02-03"
    monkeypatch.setenv("SIGNALWEAVE_QUERY_AS_OF_DATE", "20260203")
    with pytest.raises(ValueError, match="Explicit query clock"):
        explicit.cutoff()
    with pytest.raises(ValueError):
        QueryClock(kind="business_date", timezone="not/a-zone")
    with pytest.raises(ValueError):
        QueryClock(kind="explicit", lag_days=1)
    with pytest.raises(ValueError):
        clock.cutoff(datetime(2026, 1, 1))


def test_catalog_is_bounded_unique_and_roundtrips_aliases(tmp_path):
    q = definition(schema="sales")
    catalog = QueryCatalog(version=1, queries=[q])
    path = tmp_path/"queries.json"
    path.write_text(catalog.model_dump_json(by_alias=True))
    assert load_query_catalog(path) == catalog
    for payload in ({"version": True, "queries": [q.model_dump()]},
                    {"version": 1, "queries": [q.model_dump(), q.model_dump()]}):
        with pytest.raises(ValueError):
            QueryCatalog.model_validate(payload)
    path.write_text('{"version":1,"version":1,"queries":[]}')
    with pytest.raises(ValueError, match="Duplicate"):
        load_query_catalog(path)
    path.write_text(" " * 2_000_001)
    with pytest.raises(ValueError, match="byte limit"):
        load_query_catalog(path)


def adapter(query=None, **extra):
    return SupersetQueryAdapter(SimpleNamespace(name="superset", client=object(), tenant_id="local",
        binding_namespace="bound-endpoint", **extra), QueryCatalog(version=1, queries=[query or definition()]))


@pytest.mark.asyncio
async def test_inspect_preserves_dynamic_aliases_nulls_and_query_provenance(monkeypatch):
    from signalweave import superset_sql

    execute = AsyncMock(return_value=SimpleNamespace(rows=[{"unfamiliar label": Decimal("123.45"), "empty": None}],
        columns=["unfamiliar label", "empty"], query_id="5", client_id="q-5", results_key=None,
        received_at=datetime.now(timezone.utc)))
    monkeypatch.setattr(superset_sql, "execute_sql", execute)
    source_adapter = adapter()
    query = definition()
    ref = SourceRef(key="owned", adapter=source_adapter.name, resource=query.resource, label="Check")
    snapshot = await source_adapter.inspect(ref)
    assert snapshot.evidence[0].values == {"unfamiliar label": Decimal("123.45"), "empty": None}
    assert snapshot.source_captured_at is None
    assert snapshot.observations == [] and snapshot.analytical_comparisons == []
    assert snapshot.contract.tenant_id == "local"
    assert snapshot.metadata["query_id"] == "5"
    assert snapshot.evidence[-1].values["columns"] == ["unfamiliar label", "empty"]
    assert json.loads(snapshot.model_dump_json())["evidence"][0]["values"]["unfamiliar label"] == "123.45"
    assert execute.call_args.kwargs["sql"] == query.sql
    with pytest.raises(ValueError, match="no caller parameters"):
        await source_adapter.inspect(ref.model_copy(update={"parameters": {"sql": "SELECT 9"}}))
    assert execute.await_count == 1
    assert await source_adapter.authorize(ref, authorized_tenants=["other"]) is None
    assert await source_adapter.authorize(ref.model_copy(update={"adapter": "other"})) is None
    assert await source_adapter.authorize(ref.model_copy(update={"resource": "query:unknown"})) is None


@pytest.mark.asyncio
async def test_preset_cached_or_metadata_permissions_do_not_become_live_queries():
    source_adapter = adapter(policy=SimpleNamespace(mode=SimpleNamespace(value="cached_results"), allow_live_queries=False))
    ref = SourceRef(key="owned", adapter=source_adapter.name, resource=definition().resource, label="Check")
    with pytest.raises(ValueError, match="explicit live-query permission"):
        await source_adapter.inspect(ref)


@pytest.mark.asyncio
async def test_preset_final_snapshot_bound_includes_evidence_expansion(monkeypatch):
    from signalweave import superset_sql

    raw = [{"value": "x"} for _ in range(10)]
    assert len(json.dumps(raw).encode()) < 1024
    monkeypatch.setattr(superset_sql, "execute_sql", AsyncMock(return_value=SimpleNamespace(rows=raw,
        columns=["value"], query_id="5", client_id="q-5", results_key=None, received_at=datetime.now(timezone.utc))))
    source_adapter = adapter(policy=SimpleNamespace(mode=SimpleNamespace(value="live_query"),
                                                    allow_live_queries=True, max_snapshot_bytes=1024))
    ref = SourceRef(key="owned", adapter=source_adapter.name, resource=definition().resource, label="Check")
    with pytest.raises(ValueError, match="configured byte limit"):
        await source_adapter.inspect(ref)

"""Generic query definitions, clocks and native result evidence (no business rules)."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from signalweave.models import SourceRef
from signalweave.query_source import (
    MAX_QUERY_RESPONSE_BYTES,
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
    catalog = QueryCatalog(version=2, queries=[q])
    path = tmp_path/"queries.json"
    path.write_text(catalog.model_dump_json(by_alias=True))
    assert load_query_catalog(path) == catalog
    for payload in ({"version": True, "queries": [q.model_dump()]},
                    {"version": 2, "queries": [q.model_dump(), q.model_dump()]}):
        with pytest.raises(ValueError):
            QueryCatalog.model_validate(payload)
    path.write_text('{"version":2,"version":2,"queries":[]}')
    with pytest.raises(ValueError, match="Duplicate"):
        load_query_catalog(path)
    path.write_text(" " * 2_000_001)
    with pytest.raises(ValueError, match="byte limit"):
        load_query_catalog(path)


def adapter(query=None, *, client=None, **extra):
    return SupersetQueryAdapter(SimpleNamespace(name="superset", client=client if client is not None else object(),
        tenant_id="local", binding_namespace="bound-endpoint", **extra),
        QueryCatalog(version=2, queries=[query or definition()]))


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
    assert execute.call_args.kwargs["max_bytes"] == MAX_QUERY_RESPONSE_BYTES == 1_000_000
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


@pytest.mark.parametrize("version", [1, 3, True, 2.0, "2"])
def test_legacy_or_noninteger_catalog_version_requires_explicit_reauthoring(version):
    with pytest.raises(ValueError, match="version must be 2"):
        QueryCatalog.model_validate({"version": version, "queries": [definition().model_dump()]})


@pytest.mark.parametrize("legacy", [{"contract": {"source_status": "unknown"}},
                                    {"contract": {}}, {"max_bytes": 50_000}])
def test_legacy_fields_are_rejected_not_silently_migrated(legacy):
    with pytest.raises(ValueError, match="Extra inputs are not permitted") as caught:
        definition(**legacy)
    assert {error["loc"] for error in caught.value.errors()} == {(key,) for key in legacy}


@pytest.mark.parametrize("field,value", [("tenant_id", "other"), ("authorized", False),
    ("source_status", "healthy"), ("source_status", "unknown"), ("freshness_sla_hours", 24),
    ("metric_definitions", []), ("comparison_contracts", []), ("required_comparison_keys", []),
    ("roles", []), ("quality", "complete")])
def test_meaning_cannot_assert_authority_health_or_quality(field, value):
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        definition(meaning={field: value})


def test_meaning_schema_is_small_strict_and_part_of_source_identity():
    schema = QueryCatalog.model_json_schema()
    fields = schema["$defs"]["QueryMeaning"]["properties"]
    assert set(fields) == {"domain", "scope", "population", "grain", "metric_names", "lineage",
                           "available_comparison_windows"}
    assert "contract" not in schema["$defs"]["QueryDefinition"]["properties"]
    assert "max_bytes" not in schema["$defs"]["QueryDefinition"]["properties"]
    assert definition().max_evidence_bytes == 100_000
    assert definition(meaning={"scope": "A different population"}).resource != definition().resource
    for updates in ({"meaning": {"scope": 1}}, {"meaning": {"metric_names": [1]}},
                    {"meaning": {"available_comparison_windows": [" "]}},
                    {"max_evidence_bytes": 999}, {"max_evidence_bytes": 1_000_001}):
        with pytest.raises(ValueError):
            definition(**updates)


@pytest.mark.parametrize("fragment", ["{{other}}", "{{ cutoff_date }}", "{% if x %}1{% endif %}",
                                     "{# comment #}", "{{cutoff_date | upper}}"])
def test_unknown_jinja_rejected_even_in_literals_or_alongside_valid_clock(fragment):
    for sql, updates in [(f"SELECT '{fragment}'", {}),
                         (f"SELECT DATE '{{{{cutoff_date}}}}', '{fragment}'", {"clock": {"kind": "explicit"}})]:
        with pytest.raises(ValueError, match="no other Jinja"):
            definition(sql=sql, **updates)


def wire_adapter(query=None, *, padding=0, rows=None, preset_limit=None, status=200):
    """Use the actual SQL transport against in-memory HTTP responses only."""
    from signalweave.preset_adapter import PresetCloudClient
    from signalweave.superset_client import SupersetClient

    calls = []
    payload = {"status": "success", "data": rows if rows is not None else [{"value": None}],
               "columns": ["value"], "query_id": 17,
               "query": {"id": "client-17", "executedSql": "x" * padding}}
    body = json.dumps(payload).encode()

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/v1/security/csrf_token/":
            return httpx.Response(200, json={"result": "csrf"})
        assert request.url.path == "/api/v1/sqllab/execute/"
        return httpx.Response(status, content=body)

    transport = httpx.MockTransport(handler)
    extra = {}
    if preset_limit is None:
        client = SupersetClient("https://source.invalid", transport=transport)
    else:
        client = PresetCloudClient("https://source.invalid", access_token="test-token",
                                  max_snapshot_bytes=preset_limit, transport=transport)
        extra["policy"] = SimpleNamespace(mode=SimpleNamespace(value="live_query"),
                                           allow_live_queries=True, max_snapshot_bytes=preset_limit)
    registered = adapter(query, client=client, **extra)
    ref = SourceRef(key="owned", adapter=registered.name,
                    resource=next(iter(registered.queries)), label="Check")
    return registered, ref, calls, body


async def test_provider_metadata_can_exceed_evidence_budget_without_losing_facts():
    q = definition(max_evidence_bytes=5000)
    registered, ref, calls, body = wire_adapter(q, padding=600_000)
    assert q.max_evidence_bytes < len(body) < MAX_QUERY_RESPONSE_BYTES
    snapshot = await registered.inspect(ref)
    assert len(snapshot.model_dump_json().encode()) < q.max_evidence_bytes
    assert snapshot.evidence[0].values == {"value": None}
    assert snapshot.metadata["query_id"] == "17"
    assert "executedSql" not in snapshot.model_dump_json()
    assert len(calls) == 2
    assert json.loads(calls[-1].content)["sql"] == q.sql


async def test_wire_response_over_fixed_ceiling_fails_even_for_tiny_facts():
    from signalweave.superset_sql import SQLQueryError

    registered, ref, calls, body = wire_adapter(padding=MAX_QUERY_RESPONSE_BYTES)
    assert len(body) > MAX_QUERY_RESPONSE_BYTES
    with pytest.raises(SQLQueryError, match="response exceeded the byte limit"):
        await registered.inspect(ref)
    assert len(calls) == 2


@pytest.mark.parametrize("preset", [False, True])
async def test_final_evidence_bound_is_independent_of_small_wire_response(preset):
    registered, ref, calls, body = wire_adapter(definition(max_evidence_bytes=5000 if preset else 1000),
        rows=[{"value": "x"} for _ in range(10)], preset_limit=1024 if preset else None)
    assert len(body) < 1000
    with pytest.raises(ValueError, match="snapshot exceeds its configured byte limit"):
        await registered.inspect(ref)
    assert len(calls) == 2


async def test_preset_lower_connection_wire_limit_cannot_be_bypassed_by_fixed_ceiling():
    from signalweave.superset_sql import SQLQueryError

    registered, ref, calls, body = wire_adapter(padding=6000, preset_limit=5000)
    assert 5000 < len(body) < MAX_QUERY_RESPONSE_BYTES
    with pytest.raises(SQLQueryError, match="response exceeded the byte limit"):
        await registered.inspect(ref)
    assert len(calls) == 2


@pytest.mark.parametrize("meaning", [None, {}, {"domain": "unknown", "population": "Unknown unit"},
    {"domain": "operations", "scope": "Retained rows", "population": "Example data", "grain": "One row",
     "metric_names": ["value"], "lineage": ["reviewed relation"],
     "available_comparison_windows": ["previous period"]}])
async def test_optional_meaning_preserves_caveats_without_inventing_quality(meaning):
    from signalweave.sources import SourceRegistry

    caveat = "Historical source units; date presence does not prove complete ingestion."
    registered, ref, _, _ = wire_adapter(definition(meaning=meaning, definition=caveat))
    snapshot, = await SourceRegistry([registered]).resolve([ref], authorized_tenants=["local"])
    assert snapshot.error is None and snapshot.contract.source_status == "healthy"
    assert snapshot.contract.tenant_id == "local"
    assert snapshot.description == caveat
    assert snapshot.contract.metric_definitions == snapshot.contract.comparison_contracts == []
    assert snapshot.contract.required_comparison_keys == []
    assert snapshot.contract.freshness_sla_hours is None and snapshot.source_captured_at is None
    assert snapshot.observations == snapshot.analytical_comparisons == []
    if meaning:
        for key, value in meaning.items():
            expected = [*value, "reviewed-query:" + snapshot.metadata["query_fingerprint"]] if key == "lineage" else value
            assert getattr(snapshot.contract, key) == expected


async def test_execution_failure_still_becomes_source_error_without_evidence():
    from signalweave.sources import SourceRegistry

    registered, ref, calls, _ = wire_adapter(status=500)
    snapshot, = await SourceRegistry([registered]).resolve([ref])
    assert "SQL Lab HTTP request failed (500)" in snapshot.error
    assert snapshot.evidence == snapshot.observations == []
    assert len(calls) == 2

# Source adapter guide

SignalWeave’s extension point is a read-only analytical-artifact adapter, not a
new BI product or workflow runtime. Add an adapter when a company already has a
system that owns the dashboard, chart, notebook, query, quality result, or status
needed by an insight card.

## Contract

```python
from signalweave.models import (
    CatalogSearchPage,
    ResourceDescriptor,
    ResourceSnapshot,
    SourceRef,
)


class SourceAdapter:
    name = "example"

    async def list_resources(self) -> list[ResourceDescriptor]:
        ...

    async def search_resources(
        self, query: str, *, limit: int, cursor: str | None = None
    ) -> CatalogSearchPage:
        ...

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
        ...

    async def authorize(
        self, source: SourceRef, *, authorized_tenants: set[str] | None = None
    ) -> ResourceDescriptor | None:
        ...
```

The adapter should:

- expose safe catalog metadata through `list_resources`;
- validate its own `resource` grammar and `parameters`;
- resolve only approved/read-only resources;
- bound result size and execution time;
- return numeric facts as `Observation` values;
- include supported comparison baselines in `Observation.comparison_baselines`
  when the source can calculate them;
- return non-numeric facts, relationships, and run metadata as `Evidence` or `metadata`;
- set `captured_at` to the source snapshot time rather than process time when possible;
- include a source URL/run ID when possible; and
- return a `ResourceSnapshot(error=...)` through the registry path when the source cannot be trusted.

Adapters may implement `authorize` when cards can name a source that is not on
the first bounded discovery page. It must validate the opaque source identity
and tenant scope without fetching query results, then return its descriptor (or
`None` when unauthorized). Onboarding uses this for explicit human anchors;
runtime evaluation still calls `inspect` and applies freshness, health, and
payload-budget gates.

The registry also enforces a serialized snapshot byte budget (1 MiB by default).
An oversized adapter result is stripped of observations, evidence, and metadata
and returned as a typed source error. Required sources therefore route to
`insufficient_data` instead of silently sending an unbounded payload to Jev.
Deployments can lower the budget with `SourceRegistry(max_snapshot_bytes=...)`.

### Shadow telemetry

Adapters may attach provider measurements under
`ResourceSnapshot.metadata["telemetry"]`. SignalWeave carries these measurements
into `InsightResult.telemetry` for shadow comparisons; they are operational
measurements, not semantic evidence and never change the Jev judgment. Supported
fields are:

```json
{
  "fetch_ms": 1830.0,
  "query_calls": 1,
  "query_bytes_scanned": 52428800,
  "cache_hits": 1,
  "cache_misses": 0
}
```

The result also records wall time, source/observation/evidence counts, and Jev
request/token usage. This gives a caller enough information to compare a
delivery-disabled SignalWeave shadow run with an existing agent or scheduled
query path without making SignalWeave own billing, query execution, or delivery.

For catalogs that are too large to materialize, implement `search_resources`.
It should apply the caller's authorization at the source, return only a bounded
page of descriptors, and report the authorized `total_count`, `has_more`, and a
resume cursor. The registry records the adapter's search strategy and warnings.
Adapters without this method still work through a `local-scan-fallback`, but that
path deliberately reports that the full catalog was materialized and is not an
enterprise-scale implementation.

For production catalogs, populate the typed `ResourceContract` as well:

- `tenant_id` and `authorized` identify the security boundary;
- `domain`, `scope`, `population`, and `grain` explain what the resource means;
- `freshness_sla_hours`, `source_status`, and `lineage` describe trust and recency;
- `roles` describes whether the resource is a primary metric, context, quality, or
  other approved evidence role; and
- `metric_definitions` describes approved queryable metrics without exposing raw SQL.

The engine does not parse the resource locator or execute source languages. This
keeps a SQL adapter from turning the MCP surface into an arbitrary SQL console,
and keeps an Airflow adapter from becoming a DAG execution API.

## Example source shapes

These are intended adapter contracts. Superset and the bounded Trino query path
are shipped in this repository; the other examples are extension points, not
claims that native connectors are already bundled:

```text
Superset   dashboard:7                 parameters.chart_ids=[62,64]
Looker     dashboard:executive-growth  native dashboard/saved-query API
Hex        project:retention            published run/cell-output API
SQL        query:orders_quality         reviewed query catalog
Trino      query:net_revenue            compiled metric definition
Airflow    dag:warehouse_load           parameters.run="latest"
Table      table:warehouse.orders       parameters.check="exists_and_fresh"
```

A mixed card can reference any combination of these. The registry resolves them
concurrently with a bounded fan-out, and the engine gives Jev the resulting
snapshots together so the card’s author guidance can be evaluated over their
relationships. Cards
created through `propose_insight_card` default to `retrieval_mode="expand"`:
human-selected sources remain required anchors, while Jev may add a small number
of authorized optional context sources at evaluation time. Use
`retrieval_mode="fixed"` when the source set must not expand.

## SQL adapter boundary

An enterprise SQL adapter should resolve `query:orders_quality` through a reviewed
query catalog. It should not accept raw SQL from `SourceRef.parameters` unless the
deployment has an explicit, separately reviewed policy for that capability. The
adapter should return the query’s declared metric names, grain, current/baseline
values, freshness, and data-quality evidence.

`TrinoQueryAdapter` implements the same boundary for data-lake metric queries. Its
source parameters may name an approved `metric_key`, dimensions, a supported time
grain, and an explicit ISO-8601 window. The adapter compiles those fields through
`MetricQueryPlan`; it rejects caller SQL, unapproved relations/columns, missing
windows, and non-`SELECT` execution.

## Airflow or Dagster adapter boundary

An orchestration adapter should resolve a DAG/job identifier and return bounded
run status, last successful run, freshness, and failure evidence. It should never
start, retry, pause, or mutate a job as part of `inspect`.

## Table/data-quality adapter boundary

A table adapter can expose checks such as existence, freshness, row-count change,
null-rate change, or schema drift. Checks that are boolean or categorical can be
returned as `Evidence`; comparable numeric checks can be returned as
`Observation` values. Required checks should fail closed when the adapter cannot
establish their state.

## Registering an adapter

The local runtime registers `SupersetAdapter` when `SUPERSET_URL` is configured.
A deployment can add any connector at construction time; Superset is not a
required runtime dependency:

```python
registry = SourceRegistry([
    SupersetAdapter(superset_client),
    LookerArtifactAdapter(looker_client),
    HexArtifactAdapter(hex_client),
    ApprovedQueryAdapter(query_catalog, warehouse),
    AirflowStatusAdapter(airflow_client),
])
engine = InsightEngine(judger=JevJudger(api_key=key), registry=registry)
```

The MCP tools then discover all installed resources through `list_resources`, and
the insight-card schema does not change. The adapter owns the source's auth
model: SignalWeave does not assume Superset RBAC, and it does not synthesize a
universal ACL for systems that do not provide one. A connector must enforce its
approved credential or identity boundary before returning catalog entries or
snapshots.

## Company-owned context provider

Deployments can inject a read-only `ContextProvider` alongside their adapters.
It receives the approved card and resolved anchor snapshots, then returns a
versioned `ContextSnapshot` containing graph facts, ownership, definitions,
precedents, or other company-owned context. A trusted provider snapshot can
participate in related-source expansion and Jev ranking; a caller-supplied MCP
snapshot is always marked unverified and is retained as evidence without being
allowed to widen retrieval.

The provider's name and version are copied onto the decision receipt and any
operator feedback attached to that receipt. A provider failure becomes an
unverified `unavailable` snapshot and the engine's existing safety gates decide
whether the workflow can proceed.

```python
runtime = build_runtime(
    adapters=[SupersetAdapter(superset_client), LookerArtifactAdapter(looker_client)],
    context_provider=CompanyGraphContextProvider(graph_client),
)
```

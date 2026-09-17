# Source adapter guide

SignalWeave’s extension point is a read-only source adapter, not a new workflow
runtime. Add an adapter when a company already has a system that owns the fact or
status needed by an insight card.

## Contract

```python
from signalweave.models import ResourceDescriptor, ResourceSnapshot, SourceRef


class SourceAdapter:
    name = "example"

    async def list_resources(self) -> list[ResourceDescriptor]:
        ...

    async def inspect(self, source: SourceRef) -> ResourceSnapshot:
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

The engine does not parse the resource locator or execute source languages. This
keeps a SQL adapter from turning the MCP surface into an arbitrary SQL console,
and keeps an Airflow adapter from becoming a DAG execution API.

## Example source shapes

These are intended adapter contracts, not shipped connectors in the current repo:

```text
Superset   dashboard:7       parameters.chart_ids=[62,64]
SQL        query:orders_quality
Airflow    dag:warehouse_load parameters.run="latest"
Table      table:warehouse.orders parameters.check="exists_and_fresh"
```

A mixed card can reference all four. The registry resolves them concurrently
with a bounded fan-out, and the engine gives Jev the resulting snapshots together
so the card’s author guidance can be evaluated over their relationships.

## SQL adapter boundary

An enterprise SQL adapter should resolve `query:orders_quality` through a reviewed
query catalog. It should not accept raw SQL from `SourceRef.parameters` unless the
deployment has an explicit, separately reviewed policy for that capability. The
adapter should return the query’s declared metric names, grain, current/baseline
values, freshness, and data-quality evidence.

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

The local runtime registers `SupersetAdapter` explicitly. A deployment can add
another adapter at construction time:

```python
registry = SourceRegistry([
    SupersetAdapter(superset_client),
    ApprovedQueryAdapter(query_catalog, warehouse),
    AirflowStatusAdapter(airflow_client),
])
engine = InsightEngine(judger=JevJudger(api_key=key), registry=registry)
```

The MCP tools then discover all installed resources through `list_resources`, and
the insight-card schema does not change.

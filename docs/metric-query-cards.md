# Metric query cards

Metric query cards are the data-lake extension of an insight card. A person can
write:

> What is net revenue per user type by month, and why did it move?

SignalWeave does not translate that sentence directly into arbitrary SQL. The
safe path is:

1. An approved adapter publishes typed metric definitions: relation, aggregation,
   measure column, time column, supported grains, dimensions, population, and
   partition column.
2. Source discovery and Jev select among those definitions.
3. Code validates the selected definition and builds a `MetricQueryPlan`.
4. The deterministic compiler emits a bounded `SELECT` query for an explicit
   time window.
5. A Trino adapter may execute only that compiled query and returns normalized
   observations.

## Catalog contract

```python
MetricDefinition(
    key="net_revenue",
    label="Net revenue",
    relation="lakehouse.analytics.orders",
    aggregation="sum",
    measure_column="net_revenue",
    time_column="occurred_at",
    supported_grains=["day", "week", "month"],
    dimensions={"user_type": "user_type", "region": "region"},
    partition_column="event_date",
)
```

The relation and columns are catalog-owned. MCP callers can request a dimension
or time grain, but cannot provide SQL expressions, table names, joins, or
unbounded filters. A definition that cannot express the requested question is
rejected rather than approximated.

## Trino deployment

Set these variables alongside the normal Superset configuration:

```text
TRINO_URL=https://trino.example.com
TRINO_USER=signal-weave
TRINO_CATALOG=lakehouse
TRINO_SCHEMA=analytics
TRINO_CATALOG_FILE=/etc/signalweave/trino-catalog.json
TRINO_MAX_ROWS=1000
SIGNALWEAVE_TENANT_ID=acme
```

`TRINO_CATALOG_FILE` is a JSON list of `ResourceDescriptor` objects with typed
`contract.metric_definitions`. `TrinoQueryAdapter` uses the catalog to resolve a
source reference, compiles the plan, substitutes only validated ISO timestamps,
and rejects non-`SELECT` statements. It does not expose a general SQL console.

## SQL safety properties

Every compiled query has:

- a catalog-selected relation and aggregation;
- quoted, validated identifiers;
- a declared time grain and dimensions;
- a required start/end window;
- a partition predicate when the definition provides one;
- a deterministic query fingerprint; and
- a scan guard suitable for logging and admission checks.

The compiler is intentionally small. It does not infer joins, silently choose a
table, or fabricate a metric definition. Those capabilities belong in a future
versioned catalog contract with independent labels and lineage checks.

## Evidence

`evaluations/query_trial.py` runs a live Jev selection trial over held-out metric
labels and then compiles every selected plan. The trial reports metric-definition,
dimension, grain, partition-bound, and statement-shape results separately. Unit
tests use a fake executor; no network or production warehouse is required for
the normal test suite.

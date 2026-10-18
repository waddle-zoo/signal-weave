# Repeat an agent's reviewed query

When a saved chart does not execute the aggregation your check needs, your agent
can retain its working SQL as a query source. SignalWeave repeats it through the
existing Superset/Preset connection: no Python reader, second MCP server, extra
SDK or copied credentials. Check [release compatibility](local-install-reference.md#release-compatibility)
before using these commands with a downloaded executable.

## From an answer to a reusable card

First have your agent answer the question with connected BI tools. Then ask:

> Keep the working SQL and agreed definitions as a SignalWeave query source.
> Calculate the required quantities in SQL, not Jev. Show me the source,
> comparison and attention rules; import the reviewed query and inspect its
> actual result before we approve a recurring card. Don't send or schedule yet.

The agent can read `signalweave queries schema` for the exact JSON format.
This illustrative PostgreSQL artifact needs a real table selected and verified
by your agent; it is not a ready-made company monitor:

```json
{
  "version": 1,
  "queries": [{
    "key": "daily-activity",
    "title": "Daily activity",
    "definition": "Completed events for the selected business date; date presence does not prove complete ingestion.",
    "read_only": true,
    "database_id": 1,
    "dialect": "postgres",
    "schema": "analytics",
    "clock": {"kind": "business_date", "timezone": "America/New_York", "lag_days": 1},
    "sql": "SELECT event_date, SUM(completed_events) AS completed_events FROM analytics.daily_activity WHERE event_date = DATE '{{cutoff_date}}' GROUP BY event_date"
  }]
}
```

After reviewing the agent-authored artifact and source scope:

```sh
signalweave queries import --source superset --file ./queries.json
signalweave queries list
```

Import confirms consent and saves a private versioned copy; it does not execute
SQL. `--yes` confirms an already-reviewed file non-interactively. Reconnect your
agent to load it. The normal MCP profile can discover/inspect `superset_sql`
sources and onboard, review, approve and evaluate a card. Review the proposed
human message, not just its decision label. Scheduling and sending remain yours.

For Preset use `--source preset`. SQL is live execution, not a cached-chart
read. Its connection must explicitly allow live queries; if appropriate, add
`--allow-live-queries` at import. The CLI warns that this also enables live reads
and refresh on that Preset connection. Cached-results/metadata-only permission
does not authorize SQL.

## What repeats—and what does not

- The artifact owns SQL, database/catalog/schema, meaning, clock and bounds.
  Its full definition hash identifies the query. Reimporting changed SQL,
  meaning or clock creates a different source; old cards do not silently execute
  replacement SQL. Review the changed card/source before continuing.
- `business_date` uses the declared IANA timezone/lag, with one clock instant
  across an evaluation. For historical recomputation use `"clock":{"kind":"explicit"}`
  and set `SIGNALWEAVE_QUERY_AS_OF_DATE=YYYY-MM-DD` in the trusted process environment
  before starting it. No fallback to today or `MAX(date)`; this override does
  not alter business-date clocks. Undated SQL needs no clock.
- Only the quoted `{{cutoff_date}}` placeholder is supported. No Jinja, caller
  parameters or SQL supplied at evaluation time. Put required totals, changes,
  coverage and breakdowns in the analyst's SQL. Results preserve aliases, nulls,
  numeric values and provider query/result references, not guessed metric mappings.
  Decimal measurements may appear as JSON strings to preserve their precision.
  Jev applies the saved policy; the agent investigates and explains.
- Defaults: 100 rows, 100,000 bytes and 90 seconds; artifact ceilings are 1,000
  rows, 1 MB and 300 seconds. Stricter Preset and MCP client limits still apply.
  Incomplete, truncated or oversized results are errors, not complete evidence.
  A local deadline does not cancel a backend job. Ambiguous query submissions
  are not blindly retried. A receipt does not certify freshness or ingestion.

For servers, mount the artifact and set `SUPERSET_QUERY_SOURCES_FILE` or
`PRESET_QUERY_SOURCES_FILE` alongside the existing connection. Each setting
requires exactly one matching configured connection and its explicit tenant.

Treat artifacts as executable deployment configuration. The parser rejects
multiple statements, writes (including CTE writes), locks and unbound parameters.
It is **not a SQL sandbox**: functions and data access still depend on actual
source/warehouse permissions. Use scoped read credentials and keep secrets out
of SQL. The operator or authorized data expert owns query review; evaluation
callers cannot edit the approved SQL.

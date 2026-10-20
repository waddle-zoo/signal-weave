# Harbor Help raw support fixture

This example generates a small, deterministic SQLite database of synthetic
support tickets. It is a raw-data fixture, not an onboarding study, source
adapter, alert-policy example, or benchmark. It contains no alert thresholds,
decisions, expected outcome labels, or gold card. The generator uses only the
Python standard library and does not import evaluation code.

Create a new database by passing an explicit output path:

```sh
python -c 'from examples.harbor_help.seed import generate_database; generate_database("/tmp/harbor-help.sqlite3", seed=20261016)'
```

The parent directory must already exist. Generation refuses an existing file
or symlink and writes a new database with owner-only permissions. The seed can
be changed to produce a different deterministic fixture. Each database has 26
consecutive Monday-to-Monday UTC weeks beginning 2026-01-05, three support
tiers, three regions, and at most 10,000 tickets.
Views use `CAST(strftime('%s', timestamp) AS INTEGER)` for whole-second UTC
clock arithmetic; SQLite 3.38's `unixepoch` function is not required. Missing
timestamps remain null, and a clock miss still means strictly beyond its limit.

## Raw source tables

`tickets` holds individual tickets, their created time, tier, region, priority,
status, optional first-response time, and optional resolution time. Both open
and resolved tickets are present. Timestamps are UTC ISO strings ending in
`Z`; an open ticket has no resolution timestamp.
`week_start_utc` is the ticket's **creation-week cohort**, not the week it was
resolved. These are final retrospective ticket states, not historical week-end
snapshots; filtering an old cohort does not reconstruct what was known then.

`support_tier_sla` is the source-owned clock definition. Its resolution and
first-response hour limits differ by support tier. It describes how this
synthetic source measures its clocks; it does not say when a business should
alert or what action anyone should take.

`source_ingestion_ledger` records one expected interval for every week, tier,
and region. There is one missing business/central interval with zero received
tickets, plus a fully received `recovered` interval for that same segment in
the following week. “Recovered” marks ingestion flow resuming; it does not
backfill the earlier missing interval. The coverage view keeps that missing
interval visible.
Each received interval's ingestion time is after every event it contains.
`source_snapshot.as_of_utc` is the final synthetic snapshot cutoff (the latest
interval ingestion time), not the real retrieval time or a freshness guarantee.

## Views

- `weekly_resolution_sla` counts eligible resolved priority tickets and their
  misses by week, tier, and region. A ticket is eligible when it is priority,
  resolved, and has a resolution timestamp. The view exposes the miss count,
  eligible denominator, and their ratio.
  This is completed-ticket performance by creation week, not all-ticket SLA
  attainment or resolutions completed during that calendar week.
- `weekly_first_response_sla` uses tickets with a first-response timestamp,
  including responded open tickets and tickets outside the priority-only
  resolution population. Its clock and denominator are separate from the
  resolution-SLA population.
- `weekly_open_backlog` separately counts open priority tickets and unanswered
  tickets, including how many exceed their respective clocks at the explicit
  snapshot cutoff. Pending counts are total minus overdue. Open or unanswered
  tickets are not silently healthy just because the completed-clock views omit them.
- `weekly_source_coverage` joins the expected ledger intervals to observed raw
  tickets, exposing expected, observed, and missing ticket counts plus the
  ingestion and coverage states.

For a weekly resolution rate across tiers and regions, sum miss and eligible
counts first, then divide. Do not average tier percentages:

```sql
SELECT week_start_utc,
       SUM(resolution_sla_misses) AS misses,
       SUM(eligible_resolved_tickets) AS eligible,
       1.0 * SUM(resolution_sla_misses)
           / NULLIF(SUM(eligible_resolved_tickets), 0) AS miss_rate
FROM weekly_resolution_sla
GROUP BY week_start_utc
ORDER BY week_start_utc;
```

Ticket workloads and clock-miss rates vary by week, tier, and region, so the
denominators matter. The fixture makes the underlying rows inspectable; it does
not provide a prepared alert snapshot or an evaluation answer.

## Connect an analyst agent

From a development checkout with dependencies installed (`uv sync --extra dev`),
start the example company's MCP over stdio:

```sh
uv run python -m examples.harbor_help.company_mcp /tmp/harbor-help.sqlite3
```

Configure that command as an additional company MCP in your agent. It exposes
`list_assets`, `inspect_asset`, and `query_readonly`: discover the actual tables
and views, inspect their SQL definitions, and query the raw source. New views
are discovered without adding a scenario-specific tool. Both comparative arms
must retain these tools and the same company context.

Queries are read-only, with bounded SQL length, execution, rows, and response
bytes. Truncated results are explicit; aggregate in SQL instead of summing a
truncated sample. The tool's retrieval timestamp does not replace the source's
snapshot cutoff or ingestion ledger.

The additional `export_query` tool wraps arbitrary bounded SQL result rows as
SignalWeave source evidence. It preserves column names and values, rejects
truncation or duplicate aliases, and adds the saved SQL definition. It does not
choose metrics, interpret changes, supply alert policy, or assert freshness.
In an operator-reviewed [company MCP manifest](../../docs/mcp-source-bridge.md),
fix its SQL, resource ID, source key and title as tool arguments. Cards select
that resource; they cannot rewrite its SQL. Both baseline and treatment retain
all the raw tools. Source-owned metric views are available to both, not hidden
evaluation answers.

### Source-backed files

To let the analyst work from real exports instead of retyping tool results,
enable the optional `export_query_files` tool at source startup:

```sh
uv run python -m examples.harbor_help.company_mcp /tmp/harbor-help.sqlite3 --exports-dir ./source-exports
```

The tool accepts SQL and a row limit, not an output path. It runs one bounded
read-only query and writes its original `result.json`, readable `rows.csv` and
generated `provenance.json` beneath that configured directory. It returns the
actual paths, row count and file hashes. Use those originals for calculations and
supporting attachments; do not ask the agent to reconstruct them first.
Truncated results are rejected: narrow or aggregate the query rather than export
a partial sample as complete evidence.

JSON preserves types, `null` and empty strings. CSV represents nulls and empty
strings as empty fields and protects string cells that could be spreadsheet
formulas; use JSON when those distinctions matter. The folder and files are
owner-only, with generated names and no overwrite of inconsistent existing
artifacts. It is a local output directory, not a published attachment service or
proof that a recipient can open a file. A remote MCP must separately provide an
authorized download path; server-local paths are not client-local files.

Without `--exports-dir`, no file-export tool or export directory is created.
The existing `export_query` only wraps source rows for SignalWeave; card sources,
Jev inputs and source permissions do not change. Comparative agents should both
retain the file-export tool when testing this capability. This example and its
exports are not bundled into the SignalWeave native executable.

If a shared context definition depends on a saved query, declare the exact
query's SHA-256 in `descriptor.contract.lineage` as
`saved-sql-sha256:<digest>` and refresh it whenever the reviewed SQL changes.
`evaluations.harbor_onboarding.export_resource` builds this entry from the same
SQL it registers as the fixed tool argument. Display metadata alone is not
tracked by context pins. Declare upstream view revisions separately when their
meaning can change; this example does not discover those revisions. A changed
declaration makes a previously pinned definition need review, while ordinary
new measurement values do not change the definition's identity.

This company MCP is separate example code, not part of the native binary.
Connecting raw tools does not automatically configure a SignalWeave source.
Routine cards can use configured SQL exports directly; a delegated
[analyst publication](../analysis_publication/README.md) is an alternative for
deeper findings, not a mandatory LLM pass before every check. This example has
not yet established successful agent onboarding or comparative business value.

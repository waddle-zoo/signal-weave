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
Views use SQLite's `unixepoch` function (SQLite 3.38 or newer).

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

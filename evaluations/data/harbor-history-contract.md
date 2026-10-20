# Harbor operational-history fixture contract

Development fixture for the workflow research plan, not a confirmation company,
gold card, alert policy or business result. It is separate from the immutable
retrospective Harbor cohort. All times are aware instants at one-second precision;
source snapshots serialize canonical UTC `Z` strings.

The default generator has 18 creation weeks, six warmup weeks and twelve measured
weekly cutoffs. Its declared synthetic profile has a 96% eventual-resolution
draw, with a 15% 7..28-day tail among those resolutions; one retraction/revival
example is forced to exist. These are simulation choices, not empirical rates.
Six warmup weeks establish older history in which long-tail tickets can age;
they do not make the latest or preceding creation cohort mature or age-matched.

## Private history input

`evaluations.harbor_history.make_history(seed=...)` returns a dictionary:

- `first_week`: UTC Monday `datetime`.
- `clock_definitions`: list of dictionaries with `support_tier`,
  `resolution_sla_hours`, `first_response_sla_hours` (positive integer hours).
- `regions`: distinct region names.
- `events`: append-only event revisions. Each has `event_id`, positive integer
  `revision`, aware `effective_at` and `available_at`, `tombstone` and `payload`.

Latest available revision wins **before** filtering effective time/deletion.
No older version returns when a correction moves an event into the future.
`available_at` cannot precede the event's effective time in this fixture.
Payloads have these source meanings, not expected analytical conclusions:
`kind` is inside `payload`, not a separate top-level event field.

| `kind` | Payload fields | Meaning of `effective_at` |
| --- | --- | --- |
| `created` | `ticket_id`, `support_tier`, `region`, `priority` (0/1) | ticket creation |
| `response` | `ticket_id` | first-response event |
| `resolution` | `ticket_id` | resolution event |
| `partition` | `week_start_utc` (Monday date string), `support_tier`, `region`, `expected_ticket_count` (nonnegative integer) | closed cohort's week end |

One event ID per ticket/kind and one per partition. Later versions correct or
retract that event, not create a second response/resolution. Only visible creation
events can create ticket rows. A visible response/resolution without its creation
remains a raw orphan event; it cannot import hidden creation attributes. A response
or resolution preceding its visible creation is invalid, not silently clamped.
This bounded history starts at `first_week`; earlier creation events are invalid.
It does not claim to include any unprovided opening backlog from before that date.

## Public snapshot

`materialize_snapshot(history, cutoff, output_path)` creates a new private SQLite
file, refusing an existing target or symlink. It contains no private-history
path, seed, future versions, expected alert labels, destinations or scorer data.
The read-only MCP receives only this file, not the history object.

- `source_snapshot(snapshot_id, as_of_utc)`: exactly one row, ID 1.
- `support_tier_sla(support_tier, resolution_sla_hours, first_response_sla_hours)`.
- `regions(region)`.
- `calendar_partitions(week_start_utc, support_tier, region)`: every expected
  tier/region pair from `first_week` through complete weeks ending by the cutoff.
- `expected_partitions(week_start_utc, support_tier, region,
  expected_ticket_count, available_at_utc)`: only visible partition manifests.
  An absent manifest is unknown expected volume, not zero.
- `ticket_events(event_id, revision, kind, ticket_id, effective_at_utc,
  available_at_utc, payload_json)`: latest visible non-partition event versions.
- `tickets(ticket_id, week_start_utc, created_at_utc, support_tier, region,
  priority, status, first_response_at_utc, resolved_at_utc)`: known state derived
  from the visible events; `status` is `resolved` only with a visible resolution.

`tickets` is a materialized projection, not independent raw ground truth. Its
`week_start_utc` is the UTC **creation cohort**, not the resolution week. Open
states and backlog use the supplied cutoff, never the real current time.

## Source-owned views and independent reference

Group all quantities below by `(week_start_utc, support_tier, region)`. A miss is
strict `elapsed_seconds > clock_hours * 3600`, not greater-than-or-equal.

- `weekly_resolution_sla`: `observed_ticket_count` (all known created tickets),
  `eligible_resolved_tickets` (priority=1 and resolved), `resolution_sla_misses`,
  `resolution_sla_miss_rate` (null with a zero denominator).
- `weekly_first_response_sla`: `observed_ticket_count`,
  `first_response_clock_tickets` (all tickets with a known first response),
  `first_response_sla_misses`, `first_response_sla_miss_rate`. This includes
  responded open and nonpriority tickets; it is not the resolution population.
- `weekly_open_backlog`: `as_of_utc`, `open_priority_tickets`,
  `overdue_open_priority_tickets`, `unanswered_tickets` (open without a known
  response), `overdue_unanswered_tickets`. Groups with tickets but no open tickets
  return zero counts. Resolved tickets missing their response event are not
  counted as open or assumed to have met the response clock.
- `weekly_source_coverage`: every calendar partition, `expected_ticket_count`
  (nullable), `observed_ticket_count`, `missing_ticket_count` (nullable and may
  be negative for excess rows), `coverage_status` (`unknown`, `missing`, `partial`,
  `excess`, `complete`), and `manifest_available_at_utc`. Expected=observed=0 is
  complete; a missing manifest with observed=0 is unknown. These are count
  reconciliation facts, not proof all event types are fully ingested.

Pool counts before calculating rates. A group's absence from a clock view is
not a zero-rate guarantee; use the calendar/coverage view to check the population.
The fixture does not supply a notification threshold or decide whether the
observed change is important.

Adjacent creation cohorts have **unequal ages** at one as-of cutoff. Their
completed-ticket miss-rate difference is descriptive, not an age-matched measure
of operational performance or evidence of a cause. Source exports must say so
and show open backlog separately. A performance-comparison workflow needs a
separately defined common observation horizon or another appropriate population;
do not solve this by calling the descriptive rates fully comparable.

`evaluations.harbor_history_reference.summarize_history(history, cutoff)` returns
a dictionary with `as_of_utc`, `tickets` (list of those public ticket dictionaries),
`resolution`, `first_response`, `backlog`, `coverage` (lists of dictionaries with
the keys and view fields above), and `orphan_event_ids` (sorted IDs). It must
select raw revisions and compute clocks independently, without importing the
generator, `available_history`, snapshot writer, source views or production code.
Caller tests compare all outputs against SQL and separately use hand-worked
boundary cases so agreement is not the sole evidence.

The source boundary is an actual bounded SQLite/MCP read, not a hosted vendor
integration. OS-level isolation from private history is a separate harness
responsibility. This first support fixture does not stand in for six industries.

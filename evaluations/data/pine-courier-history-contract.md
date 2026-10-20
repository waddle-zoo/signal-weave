# Pine Courier parcel history — source contract

This is a new synthetic source, not a repair, rescore or continuation of the
inconsistent V7 exports. It contains no card, prediction, routing label or
analyst procedure. Dispatch reporting and Data Operations export repair may use
the same source; neither consumer receives an analytical answer from this file.

## Meaning and clocks

- A due week is a half-open UTC interval, Monday 00:00 through next Monday 00:00.
- Source cutoffs are 2026-09-21, 2026-09-28 and 2026-10-05 at 06:00 UTC. Each
  snapshot names the latest closed due week and its preceding complete week.
- Delivery attainment counts noncancelled parcels delivered at or before their
  promised timestamp, divided by all noncancelled parcels due in that week.
  Overdue undelivered parcels stay in the denominator. Cancellation means a
  cancellation event visible at the source cutoff. Equality to the promise is
  on time. A parcel due at the interval's end belongs to the next week.
- The completed-only alternative excludes parcels without a visible delivery.
  It is a genuinely different population, not another name for all parcels due.
- The existing owner's adverse-change rule is a drop of at least five percentage
  points in the overall attainment rate. This is owner policy, not a source
  measurement; no threshold, destination or disposition is exported in SQLite.

## Underlying history and availability

Four consecutive due cohorts begin September 7, 14, 21 and 28, with respectively
2,400, 3,000, 3,600 and 4,200 registered parcels, including cancellations.
Priority and standard are disjoint service tiers with unequal volumes.
Registration, cancellation and delivery are separate source events with stable
IDs, revisions, effective times and availability times. Only revisions effective
and available by the selected cutoff are materialized. No later delivery or
cancellation timestamp is inserted into an earlier parcel state. Known promised
dates can be in the future; a promise is not a future observed delivery.

All registration records for each closed due week are available by its cutoff;
per-week/tier manifests reconcile this complete raw population. Some late
deliveries become visible at a subsequent cutoff. Those are recorded changes,
not inconsistent copies of the same underlying week. The all-due denominator
and on-time numerator do not change merely because a late parcel is delivered.
Manifests attest registration counts, not universal event completeness or real
production freshness. Retrieval wall time is never substituted for source time.

## Cached exports and the repairable defect

`cached_sla_exports` is the latest available source-cache revision for each closed
due week and tier (plus the overall total). Counts are generated from the same
as-known parcel history. During the September 28 cutoff, the September 21 week's
overall cache row omits its denominator. Its numerator and tier rows are retained;
raw parcels and registration manifests remain complete and readable. This is an
export-field defect, not evidence that underlying eligible parcels are missing.
An analyst can reconstruct the scoped answer; the source does not prescribe a
policy disposition when an alternative trustworthy calculation is available.

The next cutoff includes a recorded second cache revision restoring that exact
denominator from the unchanged population. `cached_export_revisions` retains both
visible revisions, their publication times, input cutoff and source repair note.
Unchanged weeks retain their original cache bytes/values and provenance. No source
row says that an owner or Data Operations received, approved or completed work.

## Public surface and bounds

SQLite exposes `source_snapshot`, `parcels`, `parcel_events`,
`due_week_manifests`, `metric_definitions`, `cached_export_revisions`,
`cached_sla_exports`, and `completed_only_sla`. Raw events contain only visible
revisions. The completed-only view is an inspectable source-owned definition;
there is no supplied analyst reconstruction query, card or saved expected answer.
The optional stdio MCP reuses the example's bounded read-only SQL executor and
its ordinary asset inspection/export tools. Both future trial arms must have
equivalent access. No query accepts a hidden cutoff or switches source state.

Materialization is exclusive into a new private file. The full factory history
stays controller-side, never in an analyst-readable snapshot. Generation uses
`evaluations.available_history.project_events`; reviewers must read that helper
alongside this contract. This is a bounded local development fixture, not a
general history service, company warehouse or business-efficacy result.

## Reproduce source checks

From the repository's development environment:

```sh
uv run pytest -q tests/test_pine_courier_history.py tests/test_available_history.py
```

These check the input history, source counts and export revisions, not agent
onboarding or useful reports. The independent review reconstructs delivery and
cancellation state from visible events joined to promised dates and service
tiers in `parcels`; it does not independently replay registration attributes.
The source is available over stdio with
`uv run python -m evaluations.pine_courier_history /absolute/path/to/snapshot.sqlite3`.
Create a new private snapshot with `create_snapshot(path, index)` before starting
it; index zero through two selects the declared cutoffs. No generation occurs
on MCP startup and existing files are never overwritten.

The next business comparison is separately specified in
[`pine-courier-workflow-v1`](../protocols/pine-courier-workflow.json). Its admission,
onboarding and comparative-value gates are not satisfied by these source checks.

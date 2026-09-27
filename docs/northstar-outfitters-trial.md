# Northstar Outfitters onboarding trial

This is a local integration trial against the Northstar Outfitters Superset
instance. It exercises the normal SignalWeave path with Jev enabled:

discover → draft → review → simulate

No delivery destination was contacted. The TypeSafe API received the bounded
card and catalog/evaluation state required by Jev; the Superset instance and
warehouse remained local.

## Trial setup

- Superset catalog: 20 dashboards and 580 chart records in the current local
  Northstar fixture.
- Card scope: the 10 charts on 01 | Executive Command Center.
- Card intent: watch revenue, gross margin, orders, returns, active customers,
  and regional movement; explain material changes and route follow-up.
- Retrieval: fixed human-selected dashboard, with related candidates surfaced
  for review.
- Evaluation: Jev compiled the plan and judged the retrieved observations.

## Observed result

| Check | Result |
| --- | --- |
| Free-form source discovery | Executive Command Center ranked first |
| Jev relevance | 0.96 |
| Chart requests | 10/10 succeeded |
| Observations | 10 |
| Evidence items | 21 |
| Review status | Needs human input for related dashboards |
| Selected source outside bounded candidates | None |
| Decision | investigate |
| Decision confidence | 0.52 |
| Delivery route | Analytics investigation |

The dashboard contains both comparable trends and current cross-sectional
breakdowns. Five charts do not define a comparable baseline, but the five
baseline-backed observations remain usable. SignalWeave records the missing
baselines as evidence instead of treating the whole dashboard as unavailable.
Jev therefore routed this run to investigation rather than automatically
notifying leadership.

## What this proves

The first real Superset-shaped trial exposed and closed three integration gaps:

1. Saved charts that only expose params.datasource = "1__table" now execute
   correctly.
2. Saved table charts using all_columns now produce bounded queries.
3. A natural-language card goal can recover dashboard-title candidates through
   a bounded term fallback before Jev ranking.

It also demonstrates the intended product boundary: SignalWeave retrieves,
normalizes, ranks, and evaluates evidence; a client-owned UI or agent still
confirms related sources and owns the final human feedback loop.

## Live chart-matrix acceptance

After the initial trial, the running Northstar Superset instance was exercised
with `make superset-chart-matrix` against every saved dashboard and chart
without calling Jev. The result below was refreshed on 2026-09-27:

| Check | Result |
| --- | --- |
| Dashboards | 20 |
| Charts | 580 |
| Normalized observations | 41,002 |
| Extracted charts | 580/580 |
| Visualization families | 5 |
| Silent-loss issues | 0 |

The run also caught a real provider-shape issue: Superset's dashboard chart
endpoint requires the canonical trailing-slash path and a saved chart query
context. SignalWeave now uses that path and, only when dashboard metadata
shows that every native filter is omitted on initial load, falls back to the
bounded saved-chart POST query. A native filter with a static default or
`defaultToFirstItem`, or an unrelated provider error, still fails closed rather
than analyzing unfiltered data. Superset documents that
the dashboard-scoped endpoint applies `filters_dashboard_id` using the query
context stored when the chart was saved:
<https://superset.apache.org/developer-docs/api/return-payload-data-response-for-a-chart/>.

This is integration evidence, not a universal accuracy or scale claim. A
production deployment should provide tenant identity in the source adapter,
prefer a native catalog/search index over the bounded title-term fallback, and
keep delivery disabled until a human approves the card.

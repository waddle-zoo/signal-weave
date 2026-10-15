# Mixed-connector holdout comparison — 2026-10-04

This is a live, paired comparison of the current onboarding and monitoring
path. It is evidence for a bounded value signal, not a claim that SignalWeave
is universally better than a frontier agent.

## Design

Six held-out synthetic companies were run through two arms using the same
`gpt-5.6-luna` model, cards, owner answers, noisy authorized catalogs, source
snapshots, tenant scope, and submission contract:

- **Luna BI:** the agent used the ordinary connector tools and persistent notes.
- **Luna + SignalWeave/Jev:** the same agent received a live Jev-backed
  SignalWeave preflight/evidence bundle. Complete, provenance-backed `ignore`
  decisions were push-gated; actionable and insufficient-data outcomes still
  woke Luna for the final report.

The connector profiles covered Superset, hosted-Superset-like MCP resources,
Trino, Looker, Hex, dbt, Airflow, CloudWatch, PagerDuty, Segment, and Notion.
Catalog noise added archive, sandbox, regional, forecast, partner, and other
same-domain alternatives. Delivery was disabled.

## Observed result

The independent mechanical reviewer recomputed all 36 monitoring rows and
passed the current-source, fixture-digest, paired-input, same-card, provenance,
raw-Jev-routing, push-gate, and no-unsafe-suppression checks.

| Measure | Luna BI | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Exact structured monitoring | 18/18 | 18/18 |
| Outcome correctness | 18/18 | 18/18 |
| Recipient correctness | 18/18 | 18/18 |
| Required-evidence recall | 100% | 100% |
| Provenance-complete runs | 18/18 | 18/18 |
| False alerts / missed events | 0 / 0 | 0 / 0 |
| Downstream Luna wake-ups | 18 | 12 |
| Warm downstream agent seconds | 479.6s | 248.0s |
| Active agent seconds per wake-up | 26.64s | 20.67s |
| Monitoring source reads | 53 | 36 |
| Onboarding wall time | 538.6s | 857.5s |

The treatment therefore tied structured quality on this cohort while reducing
warm downstream Luna work by 48.3%, active work per wake-up by 22.4%, and
downstream wake-ups by 6/18. The projected wall-time break-even is 25
monitoring runs, excluding pricing, human review, and business value.

## What this supports

Under this fixture, SignalWeave can preserve an owner-authored workflow while
providing a typed retrieval/preflight layer that lets the agent skip complete
quiet periods and spend less active effort on recurring monitoring. The result
also shows that the behavior is not limited to a Superset-only catalog.

## What it does not support

- It does not show better final correctness: both arms were 18/18.
- It does not establish lower total or subscription cost. Codex usage is
  represented as illustrative API-equivalent token estimates, not billed cost.
- It does not measure real Trino bytes, queue time, connector latency, or
  warehouse invoices.
- Approval was performed by a synthetic owner-review model, not a real human.
- The blind narrative/usefulness review is a separate required gate and remains
  pending for this cohort. Structured exactness is not proof that every report
  was useful to an operator.
- The sources are normalized synthetic MCP fixtures, not a customer tenant.

## Artifacts

- Live report: `/private/tmp/signalweave-mixed-connector-holdout-v1/report.json`
- Independent mechanical review: `/private/tmp/signalweave-mixed-connector-holdout-v1/review-rerun.json`
- Arm-masked narrative packet: `/private/tmp/signalweave-mixed-connector-holdout-v1/blind-packet/blind-review.json`
- Protocol: [`bootstrap-benchmark-protocol.md`](../bootstrap-benchmark-protocol.md)

The defensible conclusion is a recurring-work reduction signal with no quality
regression in this small synthetic cohort—not general superiority.

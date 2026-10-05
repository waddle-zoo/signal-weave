# Cinder Database Cloud held-out live comparison — 2026-10-06

## Protocol

This is a held-out, multi-connector company trial using the same `gpt-5.6-luna`
agent, business brief, connector catalog, source snapshots, owner policy,
permissions, monitoring periods, and final submission schema in both arms.
The treatment used the local SignalWeave runtime with live Jev. The baseline
used the ordinary connector tools and the same card policy after onboarding.

The company included a Superset-like operational source, Airflow deployment and
incident context, scoped catalog noise, a quiet period, an actionable incident,
and a missing-coverage period. The treatment used the push gate: a complete
Jev-backed `ignore` did not wake the downstream agent.

## Result

| Measure | Luna only | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Onboarding complete | 1/1 | 1/1 |
| Monitoring periods | 3 | 3 |
| Exact decisions | 3/3 | 3/3 |
| Outcome accuracy | 100% | 100% |
| Recipient accuracy | 100% | 100% |
| Evidence recall | 100% | 100% |
| Provenance complete | 3/3 | 3/3 |
| False alerts | 0 | 0 |
| Unsafe routes or suppressions | 0 | 0 |
| Downstream agent wakeups | 3 | 2 |
| Active warm agent time | 113.61 s | 47.96 s |
| Jev requests | 0 | 35 total |

SignalWeave skipped the quiet period after a complete Jev `ignore`, reducing
downstream wakeups by 33.3% and active warm agent time by 57.8% in this trial.
Among runs where the agent did wake, active agent time per wakeup was 36.7%
lower. The treatment also retained the correct `investigate` and
`insufficient_data` outcomes for the incident and missing-coverage periods.

The independent reviewer passed every integrity gate: live Jev observed, same
card across arms, no foreign tools, paired denominators, recomputed scores,
current source fingerprint, complete usage, correct raw Jev routing, and no
unsafe suppression.

## Onboarding finding and repair

The preceding run produced a false `investigate` on the quiet period because
the onboarding agent had converted source completeness and same-population
requirements into required semantic `watch_for` items. Jev correctly preferred
`ignore`, but unresolved redundant watches triggered the safety fallback.

The onboarding instructions now explicitly keep source completeness,
comparison validity, population/grain matching, numeric thresholds, and
report-writing instructions in typed source contracts, analytical comparisons,
numeric conditions, decision guidance, or follow-up guidance. They remain out
of `watch_for` and `questions` unless the owner requires a distinct
non-computable fact. The rerun passed the quiet, incident, and missing-data
periods with no false alert.

## Interpretation boundary

This is strong evidence for the push-gated workflow mechanism on one synthetic
but messy multi-connector company. It is not proof of general superiority,
production reliability, or measured provider-dollar savings. The Codex
transport does not expose billed subscription cost, and this report's
break-even estimate is wall-time only. The next necessary test is a larger
stratified set of held-out companies and multi-step investigations with the
same independent review.

Independent review: `/private/tmp/signalweave-cinder-contract-prompt-20261006/review.json`

Raw report: `/private/tmp/signalweave-cinder-contract-prompt-20261006/report.json`

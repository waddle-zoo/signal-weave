# Juniper Trail Retail + Lumen Freight Finance held-out comparison — 2026-10-06

## Protocol

Two held-out companies were run with the same `gpt-5.6-luna` agent in both
arms. Each arm received the same business brief, human-authored policy after
onboarding, connector catalog, source snapshots, tenant scope, monitoring
periods, and final submission schema. The treatment added only the local
SignalWeave runtime with live Jev and a push gate for complete quiet outcomes.

The holdout included Superset-like and warehouse/Trino sources, operational
quality context, scoped catalog noise, quiet periods, notify periods, and
insufficient-data periods. The two cards were approved after the same guided
onboarding protocol and independent synthetic-owner review.

## Result

| Measure | Luna only | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Companies onboarded | 2/2 | 2/2 |
| Monitoring periods | 6 | 6 |
| Exact decisions | 3/6 | 6/6 |
| Outcome accuracy | 6/6 | 6/6 |
| Recipient accuracy | 6/6 | 6/6 |
| Required evidence recall | 100% | 100% |
| Numeric precision | 50% | 100% |
| Numeric recall | 66.7% | 100% |
| Provenance complete | 6/6 | 6/6 |
| False alerts | 0 | 0 |
| Unsafe routes or suppressions | 0 | 0 |
| Downstream agent wakeups | 6 | 4 |
| Active warm agent time | 144.66 s | 63.38 s |
| Jev requests | 0 | 11 |

SignalWeave reduced downstream wakeups by 33.3% and active warm agent time by
56.2%. It skipped both quiet periods after the Jev decision was complete. The
treatment preserved every business outcome and recipient while adding the
typed numeric evidence needed for a complete handoff.

The Luna-only misses were not wrong business decisions. They were evidence
quality failures: the agent asserted unsupported baseline/current/delta values
or omitted a required numeric fact. SignalWeave's computed comparison bundle
gave the downstream agent the exact values, units, comparison, and provenance.

## Cost and latency boundary

The illustrative API-equivalent estimate was `$0.0852` for Luna-only and
`$0.1267` for the treatment. These are not billed subscription costs because
the trial uses the Codex transport and does not expose provider billing. The
treatment therefore does **not** prove lower provider spend here. It proves a
warm-work and human-toil signal: fewer downstream wakeups, fewer repeated
connector reads, and more complete numeric handoffs. The report's projected
wall-time break-even was four recurring monitoring runs, excluding provider
pricing and human review value.

## Independent review

The mechanical adversarial reviewer passed every gate: current source content,
fixture digest, live Jev, same-card monitoring, paired denominators, no foreign
tools, recomputed scores, approved treatment cards, complete usage, correct raw
Jev routing, push-gate contract, and no unsafe suppression.

This is evidence across two additional messy companies, not a general
superiority claim. The sample is still too small for enterprise reliability or
statistical claims, and the next gap is a larger stratified multi-step
investigation cohort with measured provider/query economics.

Independent review: `/private/tmp/signalweave-juniper-lumen-contract-prompt-20261006/review.json`

Raw report: `/private/tmp/signalweave-juniper-lumen-contract-prompt-20261006/report.json`

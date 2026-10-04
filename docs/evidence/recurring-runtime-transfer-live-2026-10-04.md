# Recurring runtime transfer cohort — live Jev comparison

## Result

On 2026-10-04, the same `gpt-5.6-luna` agent was run through three synthetic
companies, two setup periods and four held-out periods per company. The
baseline and treatment received the same approved cards, source snapshots,
catalog, owner policies, analysis helpers and submission budget. The treatment
also received a live Jev evaluation bundle before the writer agent ran.

| Measure | Luna baseline | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Held-out reports | 12 | 12 |
| Exact outcome/route/numeric score | 11/12 (91.7%) | **12/12 (100%)** |
| Wrong-recipient periods | 1 | **0** |
| Missed notifications | 0 | 0 |
| Correctly suppressed quiet periods | 3 | **4** |
| Notifications | 9 | **8** |
| Source reads | 16 | 16 |
| Agent tool calls | 41 | 53 |
| End-to-end episode time | 146.7s | 184.5s |
| Live Jev requests | 0 | 18 total |

The single baseline miss was Helio Support period `p05`: the agent correctly
selected `ignore` but still named Support Quality as a recipient. SignalWeave
returned a quiet result with no delivery route. The treatment also correctly
held the Lattice Energy `p06` exception case at `investigate` rather than
notifying Commercial Operations while the required context was unresolved.

The current independent mechanical reviewer passes the treatment arm and
retains the baseline miss as a reference finding. It recomputes the rate and
additive arithmetic from raw snapshots, validates provenance, checks all 24
paired runs, verifies replay and arm-parity fields, and does not read the
trial's `score` fields.

## What this proves

This is concrete evidence that the Jev-backed runtime can turn an approved
card and bounded source evidence into a repeatable typed route across additive,
weighted-rate, signed-value, quiet, notification, incomplete-data and
unresolved-context cases. It also shows a correctness/safety advantage over
the same Luna agent working directly from the same card and connector tools in
this cohort.

## What this does not prove

It does not prove that SignalWeave is cheaper or faster yet. In this cached
trial, treatment took about 26% longer end to end and made more agent tool
calls because the writer received a full evidence bundle. Recurring OpenAI
input was approximately 1.73M tokens for treatment versus 0.60M for baseline;
the Jev layer itself used 117,893 input and 962 output tokens across setup and
recurring evaluation. The source adapter performed the same 16 physical reads
in each arm, so there was no warehouse-cost difference to claim.

The cohort is synthetic and uses a local company MCP adapter, not live customer
systems. It is evidence for route correctness and quiet/action safety, not an
enterprise certification or a claim of universal accuracy. The next product
work is to compact the treatment handoff for the frontier writer and measure
whether the correctness gain survives without the current context and latency
penalty.

Raw artifact: `/private/tmp/signalweave-recurring-current-live-transfer-20261004-final/report.json`.

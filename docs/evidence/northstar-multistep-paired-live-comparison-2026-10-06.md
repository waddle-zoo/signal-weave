# Northstar multi-step paired live comparison — 2026-10-06

## Protocol

The same `gpt-5.6-luna` agent ran both arms against six held-out Northstar
Outfitters monitoring cases. Both arms received the same human-authored card,
cached Superset-like charts, warehouse source snapshots, source contracts,
tenant scope, diagnostic-context tool, tool schema, and final submission
contract. Diagnostic facts stayed caller-owned and were available only after
the agent submitted an initial `investigate` result.

The treatment added only a live Jev preflight bundle from SignalWeave. Jev
ranked the reusable evidence and retrieval path; Luna still performed the
analytical interpretation and the multi-step handoff.

An independent reviewer rebuilt the checked-in cases, recomputed every score
from raw submissions, checked input/model/tool parity, verified no oracle
fields reached either arm, and found no integrity findings.

## Result

| Measure | Luna only | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Cases | 6 | 6 |
| Initial-stage exactness | 6/6 | 6/6 |
| Final exactness | 3/6 | 5/6 |
| Unsafe terminal outcomes | 2 | 1 |
| Mean final evidence recall | 83.3% | 91.7% |
| Provenance-complete runs | 5/6 | 6/6 |
| Median end-to-end time | 4.27s | 4.85s |
| Median agent-only time | 4.27s | 4.57s |
| Luna API input/output tokens | 44,171 / 2,460 | 55,948 / 2,506 |
| Jev requests | 0 | 6 |
| Jev input/output tokens | 0 / 0 | 37,369 / 680 |
| Diagnostic query calls | 0 | 0 |

Treatment was better on **2**, the same on **4**, and worse on **0** paired
cases. It fixed the baseline's evidence-handoff failures on the modest-movement
and conflicting-definition scenarios. The quiet no-change case remained a
failure in both arms because the agent omitted one required corroborating
citation while still choosing the correct `ignore` outcome. That is a
remaining evidence-completeness gap, not a retrieval or routing win.

The treatment added a median **0.58 seconds** end-to-end, including a median
Jev preflight of roughly **0.25 seconds** per case. This run therefore does
not establish a latency or provider-dollar advantage. It shows a favorable
paired effect on final evidence completeness and safe terminal outcomes in a
multi-step workflow, with a measurable latency tradeoff.

## Scope and limits

This is a live-provider, synthetic-company mechanism trial, not production
telemetry or external peer review. The six cases cover quiet movement, modest
movement, isolated decline requiring diagnostic context, broad corroborated
decline, conflicting metric definitions, and an unavailable primary source.
The data and query executor are checked-in fixtures; no real Trino bill or
warehouse execution was incurred.

The result supports the narrower claim that Jev-backed retrieval can improve a
frontier agent's evidence handoff in some multi-step monitoring cases without
changing the business outcome. It does not prove general superiority,
perfect alerting, production reliability, or lower provider cost. The next
gap is repeated live trials over a larger stratified company/case cohort and
a stronger public evidence contract so that required citations are explicit
to the onboarding owner rather than only to the evaluator.

Independent review: `/private/tmp/signalweave-northstar-multistep-paired-live-20261006-v6/review.json`

Raw report: `/private/tmp/signalweave-northstar-multistep-paired-live-20261006-v6/report.json`

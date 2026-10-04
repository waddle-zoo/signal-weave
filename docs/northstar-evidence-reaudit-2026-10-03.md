# Northstar evidence re-audit — 2026-10-03

## Conclusion

The calibrated Northstar results are useful evidence and should remain the
reference for repeat execution after onboarding. They do not disappear because
fresh agent-authored cards failed a different onboarding trial.

A fresh live-Jev replay on current code returned the correct outcome and route
for all 46 completed evaluations. Two TLS failures left the end-to-end result
at **46/48**, not 100%. The original 12-case holdout slice again scored 12/12.
This is a replay of known cases, not a new holdout.

The next proof should extend the working Northstar contract, not replace it with
an underspecified task that expects Jev to invent business policy. Measure
onboarding, retrieval, execution, and delivery reliability separately.

## Evidence checked

| Evidence | Verified result | Scope |
| --- | --- | --- |
| Growth historical replay, saved v2, v3 and final reports | Each has 48/48 matching recorded outcomes and routes; v2 reduces 25 movement-only leadership pushes to 8, with no unnecessary leadership pushes | One calibrated owner-authored card, six situation families over eight dated periods |
| Longitudinal final-v4 report | Existing audit passes 48 initial and final outcomes/handoffs; 14 automatic actions and no unnecessary automatic actions | Simulated multi-step diagnostic facts and eight scripted role checks, not eight independently reasoning agents |
| Paired Luna quality replays | 50/56 exact treatment results versus 26/56 baseline, counting all scheduled cases; treatment completed 55 runs and its one timeout remains a failure | Same cards/source access, curated context; benefit of the complete SignalWeave layer, not an isolated Jev effect |
| Fresh growth replay on current code | 46/48 outcomes and routes; 46/46 among completed evaluations; two TLS failures | Live Jev, existing card and labels unchanged, retries explicitly disabled |

The first growth pass was 41/48 before the documented card clarification.
Longitudinal final-v3 was 45/48 before final-v4 reached 48/48. Keep those earlier
results; the successful runs were calibrated, not pristine first attempts.

Source reports are local ignored artifacts:

- `artifacts/northstar-growth-history-live-v2.json`
- `artifacts/northstar-growth-history-live-v3.json`
- `artifacts/northstar-growth-history-live-final.json`
- `artifacts/northstar-longitudinal-panel-final-v3.json`
- `artifacts/northstar-longitudinal-panel-final-v4.json`
- `artifacts/paired-agent-trial/report-final2.json`
- `artifacts/paired-agent-trial/report-replicate2.json`

The two scoped Luna reviewers audited corporation/scale evidence and the paired
comparison. These are internal reviews, not external peer review.

## Fresh live replay

Code: `ab32f3f85a3fa9194610920a2f46d036661f55cd`.
No product, card, threshold, fixture, or evaluator changes preceded the run.

```bash
TYPESAFE_MAX_RETRIES=0 .venv/bin/python \
  -m evaluations.northstar_growth_history_trial \
  --seed-dir /path/to/northstar/warehouse/init \
  --typesafe-key-file /private/path/to/jev-key \
  --output artifacts/northstar-growth-history-reaudit-20261003.json
```

The unchanged harness attempted one compilation and 48 evaluations. Successful
request counters report 47 responses: one compile plus 46 evaluations. They
do not count the two failed attempts. Total reported usage for successful
responses: 1,041,574 input tokens and 47,203 output tokens. No retry calls or
Luna baseline inference were purchased for this replay.

| Measure | Result |
| --- | ---: |
| Complete correct outcome + route | 46/48 |
| Complete correct result among completed evaluations | 46/46 |
| Validation / original holdout slice | 12/12 each |
| Leadership notifications | 7 of 8 required |
| Unnecessary leadership notifications | 0 |
| Successful-evaluation median / p95 | 378.33 / 451.33 ms |
| Transport failures | 2 |

Both failures were `SSLV3_ALERT_BAD_RECORD_MAC`:

- `week-01-day-05-conflicting-sources`: expected investigation; no result.
- `week-02-day-04-corroborated-decline`: expected notification; no result.

The harness represents an exception as `insufficient_data`; that is not a
successful Jev judgment or a delivered Data Trust notification. Its old
`missed_workflows` field only counts erroneous suppression, so its value of zero
must not be read as zero incomplete workflows. Both errors remain failures.

The normal adapter supports bounded transport retries; this run deliberately
disabled them to bound spending and expose first-attempt failures. It does not
measure the deployed retry policy's recovery rate.

The replay reads 535,312 existing seed rows, but reduces them to nine observations
per case. Current counterfactual values are synthesized from baseline aggregates.
It is not 535,312 independent decisions, a new Superset API extraction run, or a
throughput test. The model uses the `jev-latest` alias; this harness does not
retain a resolved model version and full request/response trace.

Raw report SHA-256:
`606cdb78ffe6fd86d4f3a699a4f683b0b267b0bd7851c02bc8ebbadb93ab151c`.

Policy fixture SHA-256:
`ed82aeab0fb2ed740d3dde31090757749f5acebdfdbc3ebb60cd760c167e3e57`.

The raw report remains in the ignored local artifact directory. This note is
not a substitute for archiving sanitized raw evidence before a public claim.

## What explains the difference from recent onboarding trials?

Northstar starts with an explicit ordered policy, the relevant sales/funnel/
finance/support sources already bound, comparable aggregates and numerical
changes prepared, and known delivery destinations. The card stays fixed as the
evidence changes. That is the execution contract we want onboarding to produce.

The recent six-company trial required Luna to construct that contract itself.
Its failures included an ambiguous required-watch checklist, a diagnostic source
not preserved for later runs, and a reporting cutoff given to Luna but absent
from Jev's state. Those are different experimental conditions. They do not
establish that the working Northstar execution pattern is ineffective, nor do
the older scores prove automatic onboarding now works.

Explicit policy is legitimate model input, not label leakage. TypeSafe's
[state guidance](https://docs.typesafe.ai/concepts/state) likewise distinguishes
supporting facts/policies from the questions evaluated against them.

## Caveats found in the older proof

1. **Audit independence is incomplete.** The historical reviewer accepts some
   precomputed scorer flags. An in-memory mutation changing a quiet case's raw
   outcome and route to notification, while leaving those flags intact, still
   passed. No saved artifact was changed. Independently recomputing the recorded
   outcomes/routes still confirms all three calibrated growth reports' 48/48.
   The next gate must recompute from raw results and separately stored labels.
2. **Corporation evidence retention is broken.** Its saved Jev report is dated
   September 21; referenced fixture/trace files are from a September 23 research
   test-double run. Do not use that mismatched trace to attest the live result.
3. **The documented scale report is absent.** `artifacts/northstar-scale` does
   not exist in this checkout. The 168-workflow headline is not independently
   auditable here. The runner also varies policy wording by scenario: valid for
   authored-policy execution, weaker than a fixed workflow facing all situations.
4. **Roles and causal evidence were simulated.** Longitudinal follow-ups supply
   prepared diagnostic/incident statements, including confirmed causes. This
   tests consuming evidence and handing off work, not discovering those causes
   autonomously from raw enterprise systems.
5. **Comparison claims need precise names.** The paired scorer's “unsafe” metric
   includes incomplete evidence on otherwise correct outcomes, including ignore.
   Do not market it as the measured rate of harmful external notifications.
   The paired result supports the full layer, not Jev alone, and did not establish
   reduced query cost. Modeled staff-time savings are not measured human savings.

## Next scale proof: extend the working contract

This is a proposed protocol, not an executed result.

1. **Freeze a reproducible control.** Keep the original Northstar card and the
   failed replay. Archive redacted requests/results, resolved model identity,
   fixture/card/code hashes, attempt counts, and retry-inclusive timings. Repair
   the independent scoring gate before using it to certify a larger run.
2. **Separate onboarding from execution.** Compare a reviewed reference card
   with an agent-bootstrapped card using the same public owner brief and sources.
   Review only setup/calibration examples; freeze both before future periods.
   Missing essential context should trigger a targeted owner question, not a guess.
3. **Scale business diversity before repetition.** Start with 12 workflows across
   growth, finance, support and operations; run 12 future periods per workflow.
   Use one fixed policy per workflow across quiet, actionable, contradictory,
   missing-source and recovery episodes. Vary schemas, ownership, units, time
   windows and source relationships—not only company names or perturbation seeds.
4. **Exercise retrieval rather than preselecting the answer.** Include unrelated
   assets, ambiguous metric names, stale definitions and cross-dashboard context.
   Measure candidate coverage, chosen evidence, final route and explanation
   support independently. Virtual catalog size is not provider throughput proof.
5. **Keep the fair Luna baseline.** Same approved cards, charts, source access,
   calculators, memory and query budget. Measure complete correct reports,
   unnecessary/missed notifications, wrong recipients, unsupported claims,
   recovery, source/query counts, and total time/cost including setup. Retain every
   failed attempt. Treat packaging/caching/guardrails as part of the system benefit.
6. **Gate spending and expansion.** First qualify 12 mixed cases, then the
   144-period Northstar suite, then transfer to two differently structured fake
   companies without changing production logic. Stop expansion on failures; do
   not rerun until a lucky perfect score or silently redefine expected outcomes.

Finite simulations cannot prove “perfect for every enterprise.” They can prove
the specified contracts, demonstrate useful performance on unseen periods, and
identify exactly what onboarding must preserve to reproduce the earlier benefit.

## Checks performed

- Existing growth and longitudinal report audits pass their saved final reports.
- Fresh growth report fails the existing gate because its two errors are retained.
- Recorded growth outcomes/routes independently recomputed for three old runs
  and the fresh run; totals agree.
- Northstar regression tests: 15 passed. Workflow handoff tests: 6 passed.
- No source changes, external notifications, commits, pushes, or merges.

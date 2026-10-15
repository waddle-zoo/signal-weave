# Live paired bootstrap comparison — 2026-10-04 rerun

This is a reproducible live comparison of the local SignalWeave path against a
plain Luna agent using the same business inputs, connector catalog, owner
policy, and monitoring card. It is evidence of an operational value signal,
not a claim that SignalWeave is already cheaper or universally more accurate.

## Protocol

Each company was run for three held-out monitoring periods. Both arms received
the same business brief, owner answers, noisy authorized catalog, destinations,
and the exact same owner-reviewed card snapshot before monitoring. The
baseline used ordinary connector tools. The treatment used live Jev to
evaluate the card and resolve bounded related sources, then handed the typed
evidence bundle to the same `gpt-5.6-luna` agent. Delivery was disabled.

The treatment was push-gated only for a complete Jev `ignore` with provenance.
Actionable and insufficient-data outcomes still woke Luna to produce the
evidence-backed report. The independent reviewer reconstructed the fixture,
recomputed every score, checked the shared-card digest, verified raw Jev
routing, checked current-run provenance, and verified that skipped rows had no
downstream agent calls.

## Evidence freshness

The reviewer records a content fingerprint for the executable harness, scorer,
prompts, and product files; it fails closed when that fingerprint is absent or
differs from the current checkout. The current artifact is the post-commit
three-company cohort below: its fingerprint matches commit `9e5d090`, live Jev
usage is complete, and both independent reviewers pass. The earlier
three-company, Lumen-only, six-company, and Cinder-noise reports are retained
as historical diagnostics because later source-scope and reviewer changes make
their fingerprints stale. Run the reviewer normally for current proof. Use
`--allow-historical` only to inspect retained older runs.

The benchmark intentionally separates two signals. Onboarding measures whether
the treatment produces an approved executable card, while monitoring gives both
arms the exact same treatment card before scoring. This avoids hiding a card
advantage in the monitoring comparison while still measuring the onboarding
value. A card review is mechanical/synthetic in this trial; it is not actual
human authorization or semantic policy proof.

## Current live cohort — post-scope guard, commit `9e5d090`

This is the current-source, three-company live rerun. It covers a Superset / dbt
/ Airflow / Looker retail case, a Superset / CloudWatch / PagerDuty operations
case, and a Trino / Airflow / dbt / Looker finance case. Each arm used the same
Luna model, the same noisy authorized catalog, the same owner answers, and the
same three held-out monitoring periods. The treatment called live Jev for card
retrieval/evaluation and handed its typed bundle to Luna; delivery remained
disabled.

| Measure | Luna over BI tools | SignalWeave + Jev | Interpretation |
| --- | ---: | ---: | --- |
| Exact structured monitoring | 8/9 (88.9%) | **9/9 (100%)** | Treatment retained the required typed evidence on the full cohort. |
| Outcome correctness | 9/9 | 9/9 | Tied; the difference was evidence completeness, not routing. |
| Recipient correctness | 9/9 | 9/9 | Tied. |
| Evidence recall | 94.4% | **100%** | Required related facts were cited in the treatment bundle. |
| Numeric precision / recall | 100% / 96.3% | **100% / 100%** | The treatment did not invent numbers and missed none of the required typed facts. |
| Provenance-complete runs | 9/9 | 9/9 | Tied. |
| Warm downstream Luna work | 269.8s | **117.2s** | 56.6% less recurring agent time. |
| Active work per wake-up | 29.97s | **19.53s** | 34.9% less after excluding safely skipped quiet wake-ups. |
| Downstream wake-ups | 9 | **6** | Three complete Jev ignores did not wake Luna. |
| Monitoring source reads | 27 | **18** | Synthetic adapter reads, not warehouse bytes or billing. |
| Onboarding wall time | 294.5s | 475.1s | One-time Jev-backed setup is slower in this cohort. |
| Known illustrative usage estimate | $0.135 | $0.329 | Not a bill; the reviewer correctly makes no cost claim. |

The sole baseline exactness miss was the Cinder customer-facing slowdown: Luna
found the right outcome and owner but omitted the required Airflow rollout
association and its typed lead-time fact. Jev's card-backed evidence plan
preserved that obligation. This is a small, structured quality signal—not proof
of universal accuracy or causal reasoning.

The current artifacts are:

- live report: `/private/tmp/signalweave-live-bootstrap-cohort-20261004-v2/report.json`
- paired review: `/private/tmp/signalweave-review-cohort-20261004-v2.json`
- onboarding review: `/private/tmp/signalweave-onboarding-review-cohort-20261004-v2.json`

Both reviewers pass current-source, fixture-digest, paired-denominator,
same-card, score-recomputation, live-Jev, usage-complete, approved-card,
raw-routing, push-gate, and no-unsafe-suppression checks. The reviewer still
withholds a strong superiority claim because the sample is small, the card
review is synthetic, and provider token estimates are not measured business
cost. The correct conclusion is: this cohort shows a reproducible value signal
for evidence completeness and recurring Luna work, while setup overhead and
total cost remain open.

## Prior failed rerun — useful onboarding diagnosis

The retained Lumen artifact
`/private/tmp/signalweave-live-bootstrap-lumen-postscope-20261004-v2/report.json`
is intentionally not counted as a success. Plain Luna failed onboarding after
three independent reviews because it kept an unsupported “2/2 partitions
closed” current-evidence claim; the Jev arm removed the unsupported gate and
completed. The failure is evidence that ordinary prompt-and-notes onboarding
can stall on evidence discipline, but it also makes the pair incomplete, so it
cannot support an end-to-end quality comparison. The current cohort rerun is
the paired evidence used above.

## Historical pre-scope rerun — retained diagnostic

That retained rerun used live Jev, the Codex transport for the same
`gpt-5.6-luna` agent, three connector profiles, ten catalog alternatives per
canonical resource, and the push gate. It completed all 12 paired episodes
(3 onboarding pairs and 9 monitoring pairs):

| Measure | Luna over BI tools | SignalWeave + Jev | Interpretation |
| --- | ---: | ---: | --- |
| Exact structured monitoring | 6/9 | **9/9** | Treatment recovered required typed evidence and numeric facts on the three baseline misses. |
| Outcome correctness | 9/9 | 9/9 | Tied. |
| Recipient correctness | 9/9 | 9/9 | Tied. |
| Mean evidence recall | 94.4% | **100%** | Required source facts were present in the treatment bundles. |
| Mean numeric precision / recall | 74.1% / 74.1% | **100% / 100%** | Treatment preserved typed numerical corroboration. |
| Provenance-complete runs | 9/9 | 9/9 | Tied. |
| Warm downstream Luna work | 227.4s | **148.6s** | 34.6% less downstream agent time. |
| Active work per wake-up | 25.26s | **21.23s** | 16.0% less when both arms actually woke Luna. |
| Downstream wake-ups | 9 | **7** | Two complete quiet outcomes were suppressed safely. |
| Monitoring source reads | 22 | **18** | Synthetic adapter reads, not warehouse bytes or provider billing. |
| Onboarding wall time | 85.6s | 284.9s | Jev adds one-time setup work; this is not a first-run speed win. |
| Known illustrative usage estimate | $0.0949 | $0.2507 | Not a bill; no cost advantage is claimed. |

The treatment's three exactness wins are diagnostic rather than cosmetic. Luna
missed the required canonical Airflow corroborating reference for Cinder's
12-minute rollout association, and omitted bank-control citations from Lumen's
typed numeric claims in two periods. The card-backed path carried those source
obligations into the evidence bundle while preserving the same owner-approved
card for both monitoring arms.

The independent mechanical review recomputed every stored score, verified the
fixture digest, paired denominators, identical monitoring-card digests, raw
Jev routing, approved cards, and push-gate contract. It passed all of those
checks. The strict promotion review is still intentionally **blocked** because
one Jev request encountered a transient TLS error before its retry succeeded;
the failed attempt has unknown usage accounting. The trace shows request 68
failing and request 69 returning the retry response. Quality rows remain
inspectable, but usage-complete cost evidence must not be inferred from them.

The corrected onboarding audit also passes all three treatment cards (3/3).
It now checks the configured destination value rather than the card-local
`DeliveryMethod.key`; the latter is allowed to be a human-friendly local label.
This fixed a reviewer false negative on the Lumen card without weakening the
unknown-destination rejection test. The onboarding artifact remains blocked
for promotion for the same unknown-usage reason, and semantic owner fidelity
and human usefulness remain unassessed.

The retained artifacts are:

- live report: `/private/tmp/signalweave-live-bootstrap-current-20261004-v2/report.json`
- paired review: `/private/tmp/signalweave-review-current-20261004-v3.json`
- onboarding review: `/private/tmp/signalweave-onboarding-review-current-20261004-v3.json`

## Historical post-scope-guard diagnostic — Lumen Freight Finance

After the six-company run exposed a scoped-source onboarding failure, the
generic onboarding path was tightened. A selected source with a declared
population scope now produces an explicit `source-scope-review` blocker. Approval
must persist an exact scope confirmation by source ref; an agent cannot silently
use a limited, sandbox, regional, archive, partner, or otherwise scoped asset as
the unqualified business population. The guard is connector-neutral and is
covered by offline approval tests plus this live Trino/Airflow case.

The post-fix trial used the same Lumen holdout, the same noisy 44-resource
catalog, live Jev, the same Luna baseline, and an independent synthetic owner
review. The first treatment card selected `airflow|resource-c76...`, whose
contract declared a sandbox population. The treatment then repaired the card to
the canonical `airflow|resource-f8...` source. The independent owner reviewer
also rejected the first draft because it turned a source-reported watermark into
an owner-blocking business prerequisite. The agent removed that unsupported gate
and received a second independent approval.

| Measure | Luna over BI tools | SignalWeave + Jev | Interpretation |
| --- | ---: | ---: | --- |
| Exact structured monitoring | 1/3 | **3/3** | Treatment preserved the required typed facts and evidence on all held-out periods. |
| Outcome correctness | 3/3 | 3/3 | Tied. |
| Recipient correctness | 3/3 | 3/3 | Tied. |
| Mean numeric precision / recall | 44.4% / 66.7% | **100% / 100%** | The card carried the typed comparison and source obligations into the bundle. |
| Provenance-complete runs | 3/3 | 3/3 | Tied. |
| Warm downstream Luna work | 100.84s | **38.40s** | 61.9% less downstream agent time. |
| Active work per wake-up | 33.61s | **19.20s** | 42.9% less when the downstream agent actually woke. |
| Downstream wake-ups | 3 | **2** | One complete quiet outcome was safely suppressed. |
| Monitoring source reads | 8 | **6** | Synthetic adapter reads, not warehouse bytes or billing. |
| Onboarding wall time | 120.22s | 238.38s | One-time treatment setup remains slower. |
| Independent owner reviews | — | 2 (reject → approve) | The first review caught an unsupported gate; the corrected card passed. |

The strict comparison reviewer passed current-source, live-Jev, usage,
same-card, paired-denominator, score-recomputation, raw-routing, push-gate,
and no-unsafe-suppression checks. It intentionally did not authorize a strong
superiority claim because provider dollars are not billed cost and the owner
review is synthetic rather than a real human authorization. The treatment's
illustrative API-equivalent usage was higher ($0.1036 vs $0.0457); that is a
real warning against claiming cost savings from this trial.

These historical artifacts are:

- live report: `/private/tmp/signalweave-live-bootstrap-lumen-postscope-20261004-v1/report.json`
- paired review: `/private/tmp/signalweave-review-lumen-postscope-20261004-v1.json`
- onboarding review: `/private/tmp/signalweave-onboarding-review-lumen-postscope-20261004-v1.json`

## Retained six-company noisy benchmark — pre-scope fix

The six-company live run remains useful as cross-connector quality evidence,
but it is now historical because the source-scope guard changed the product
fingerprint. It covered Superset, Looker, Hex, Trino, Airflow, dbt, CloudWatch,
PagerDuty, and 18 held-out monitoring periods per arm:

| Measure | Luna over BI tools | SignalWeave + Jev |
| --- | ---: | ---: |
| Exact structured monitoring | 15/18 (83.3%) | **18/18 (100%)** |
| Outcome / recipient correctness | 18/18 / 18/18 | 18/18 / 18/18 |
| Mean evidence recall | 91.7% | **100%** |
| Mean numeric precision / recall | 88.9% / 88.9% | **100% / 100%** |
| Warm downstream Luna work | 422.4s | **201.8s** |
| Downstream wake-ups | 18 | **12** |
| Monitoring source reads | 41 | **28** |
| Onboarding card mechanical pass | 0/6 executable artifacts | 5/6 approved cards |

The sixth treatment onboarding card was not counted as a pass: it selected the
scoped Airflow sandbox asset described above. This is the reason the current
post-scope trial is important. The old six-company result was a strong retrieval
signal, not evidence that onboarding was already complete.

This historical rerun was a strong diagnostic for a product value signal: on a
small, held-out, noisy multi-connector cohort, SignalWeave improved structured
evidence completeness and reduced recurring Luna work. It is not proof of
universal accuracy, lower total cost, real warehouse savings, semantic human
approval, or production notification safety. Those claims still require a
current run with complete provider accounting, blinded narrative review, and
real connector/query telemetry.

## High-noise Cinder follow-up

After the three-company run, Cinder was rerun with 20 catalog alternatives per
canonical resource. This was a targeted engineering regression, not a new
company or a fresh holdout. The first high-noise attempt exposed a useful
failure: the treatment included the correct 12-minute rollout association in
its narrative, but omitted that corroborating number from the typed numeric
claim list. The comparator correctly scored that period non-exact. The shared
agent contract was tightened to require relevant numeric corroboration in both
typed and narrative form, and the same case was rerun once.

| Cinder high-noise rerun | Luna BI | SignalWeave + Jev |
| --- | ---: | ---: |
| Exact structured monitoring | 3/3 | 3/3 |
| Outcome / recipient correctness | 3/3 | 3/3 |
| Evidence recall / provenance | 100% / 100% | 100% / 100% |
| Warm Luna agent work | 83.69s | 32.98s |
| Active-wakeup Luna work / wake-up | 27.90s | 16.49s |
| Downstream wake-ups | 3 | 2 |
| Source reads during monitoring | 11 | 10 |
| Onboarding time | 23.40s | 68.56s |

The independent review passed fixture reconstruction, same-card parity, raw
Jev routing, usage completeness, score recomputation, and push-gate checks.
The report is retained at
`/private/tmp/signalweave-live-bootstrap-cinder-noise20-fix4/report.json` with
the reviewer output at `/private/tmp/signalweave-review-cinder-noise20-fix4`.
The recorded token-price estimate was higher for treatment ($0.0667 versus
$0.0289), but those are API-equivalent estimates rather than billed costs.

## Results

| Company | Connector profile | Luna exact | SignalWeave exact | Warm Luna agent work | Warm SignalWeave agent work | Wake-ups |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Juniper Trail Retail | Superset + dbt + Airflow + Looker | 3/3 | 3/3 | 73.58s | 30.67s | 3 → 2 |
| Cinder Database Cloud | Superset + Airflow + PagerDuty + CloudWatch | 3/3 | 3/3 | 79.78s | 51.89s | 3 → 3 |
| Lumen Freight Finance | Trino + Airflow + Looker + dbt | 3/3 | 3/3 | 77.97s | 40.03s | 3 → 2 |
| **Pooled** | **3 profiles, 9 periods/arm** | **9/9** | **9/9** | **231.34s** | **122.59s** | **9 → 7** |

Across all nine treatment periods:

- structured outcome, recipient, evidence provenance, and safety checks were
  correct: 9/9;
- raw Jev routing matched the independent labels: 9/9;
- complete quiet outcomes skipped two downstream Luna wake-ups;
- warm downstream Luna agent time fell 47.0% in aggregate;
- among periods where Luna actually woke, mean agent work fell from 25.70s to
  17.51s (31.9%), so the scheduled-work result is not explained only by
  suppressing quiet wake-ups;
- SignalWeave reduced observed monitoring source reads in this run (15 treatment
  reads versus 23 baseline reads), but the synthetic adapter does not measure
  bytes scanned or warehouse billing, so this is not evidence of lower warehouse
  cost;
- every fresh artifact passed the independent mechanical review, including
  fixture-digest, same-card, score-recomputation, push-gate, and approved-card
  checks.

The Cinder event is the clearest retrieval example. The treatment returned the
canonical Superset latency comparison plus the related Airflow change
calendar, recovered the required 12-minute rollout lead, and labeled it as an
association rather than causation. The initial version selected a same-domain
archive instead. That failure exposed a real gap: a flat noisy catalog did not
make the company relationship graph available to bounded retrieval. The fix
adds the adapter-owned relationship index, retains direct graph neighbors as
bounded context even when Jev ranks them below the optional relevance
threshold, and preserves raw source facts in the evidence bundle. The fresh
Cinder rerun passed 3/3 with the canonical Airflow ref.

## What this proves

Under this protocol, the strongest defensible result is:

> SignalWeave + live Jev can preserve Luna's structured monitoring correctness
> while reducing downstream agent work and suppressing complete quiet runs,
> across Superset-led, Trino-led, and operational connector profiles with
> noisy catalogs.

That is a meaningful product value signal for pushed analytics. It is not a
claim that Jev replaces Luna's explanation or that SignalWeave independently
proves causality. Jev makes bounded typed judgments and retrieves evidence;
the agent still writes the human-facing analysis.

## What this does not prove

- General accuracy superiority: both arms tied 9/9 on these structured labels.
- The high-noise Cinder extension also tied 3/3 after the typed-corroboration
  repair; it is robustness evidence, not an accuracy win.
- Lower total or subscription cost: Jev adds onboarding/runtime requests, and
  recorded dollar fields are illustrative API-equivalent estimates, not bills.
- Faster first-run onboarding: treatment cold setup was 86.93s, 116.65s, and
  125.47s for Juniper, Cinder, and Lumen versus 26.79s, 17.99s, and 40.58s
  for the baseline.
- Lower warehouse/query cost: the fixture uses bounded synthetic snapshots,
  not real Trino bytes scanned, queue time, or connector invoices.
- Narrative usefulness to real operators, production notification safety, or
  universal correctness for every hosted BI connector.

The strong-superiority gate remains intentionally false. The next proof bar is
blinded narrative review of evidence bundles, a larger held-out multi-period
cohort with a current source fingerprint, and measured provider/query economics
using real connector telemetry. The onboarding reviewer is
[`evaluations/bootstrap_onboarding_review.py`](../evaluations/bootstrap_onboarding_review.py);
its phrase checks are diagnostics only and do not replace semantic owner review.
The current machine-readable compact evidence is in
[`evidence/bootstrap-live-comparison-2026-10-04.json`](evidence/bootstrap-live-comparison-2026-10-04.json).
The independent reviewer is
[`evaluations/bootstrap_live_comparison_review.py`](../evaluations/bootstrap_live_comparison_review.py).

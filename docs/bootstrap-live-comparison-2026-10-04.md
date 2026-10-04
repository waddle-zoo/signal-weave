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
cohort, and measured provider/query economics using real connector telemetry.
The current machine-readable compact evidence is in
[`evidence/bootstrap-live-comparison-2026-10-04.json`](evidence/bootstrap-live-comparison-2026-10-04.json).
The independent reviewer is
[`evaluations/bootstrap_live_comparison_review.py`](../evaluations/bootstrap_live_comparison_review.py).

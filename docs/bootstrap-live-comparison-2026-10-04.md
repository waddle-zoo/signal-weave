# Live paired bootstrap comparison — 2026-10-04

This is the first fair live comparison of the local SignalWeave path against a
plain Luna agent using the same cards and connector access. It is a bounded
research result, not a production certification or a claim that SignalWeave is
already cheaper or universally more accurate.

## Protocol

Each company was run for three held-out monitoring periods. Both arms received
the same business brief, owner answers, noisy source catalog, authorized
destinations, and the exact same owner-reviewed card snapshot. The baseline
used only ordinary connector tools. The treatment used live Jev to evaluate the
card, then handed the typed bundle to the same `gpt-5.6-luna` agent. Delivery
was disabled.

The treatment was push-gated only for a complete Jev `ignore` with provenance.
Actionable outcomes still woke Luna to produce the evidence-backed report. An
independent reviewer rebuilt the fixture, recomputed every score, checked the
shared-card digest, verified the raw Jev route, checked installed-resource
provenance, and verified that skipped rows had no downstream agent calls.

## Results

| Company | Connector profile | Luna exact | SignalWeave exact | Warm Luna work | Warm SignalWeave work | Wake-ups |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Juniper Trail Retail | Superset + dbt + Airflow + Looker | 3/3 | 3/3 | 79.74s | 30.77s | 3 → 2 |
| Lumen Freight Finance | Trino + Airflow + Looker + dbt | 3/3 | 3/3 | 86.03s | 31.23s | 3 → 2 |

The treatment’s raw Jev routes were correct in all six periods. Its structured
outcomes, recipients, and provenance were also correct in all six periods. The
two push-gated quiet periods were complete ignores with no Luna wake-up and no
unsafe suppression.

That is a meaningful value signal: SignalWeave reduced warm downstream Luna
work by 61.4% and 63.7% in these two profiles while preserving the measured
decision contract. It does not yet establish general accuracy superiority; in
both profiles the baseline tied it at 3/3.

The held-out fixture family used for the broader local regression contains six
companies, 18 monitoring periods, 144 catalog resources, and ten connector
identities: Airflow, CloudWatch, dbt, Hex, Looker, Notion, PagerDuty, Segment,
Superset, and Trino. Adding five noisy catalog alternatives leaves scenario and
period IDs stable, so catalog pressure cannot silently change the labels. That
is breadth of the simulator and contract suite—not six live Jev comparisons.

## What the failures taught us

The evidence is stronger because failed runs were retained and fixed:

- A Lumen treatment report initially omitted the Airflow completeness ref from
  Luna’s numeric claims. The bundle already knew the ref; the handoff did not
  state strongly enough that quality refs belong on numeric claims. The
  handoff contract now requires all matching provenance refs, and the fresh
  Lumen run passed 3/3.
- An optional follow-up failure once converted an initial Jev ignore into an
  alert. The engine now refuses to manufacture an alert from a no-action
  primary decision when optional context fails.
- A treatment comparison once accepted a canonical installed-resource ref that
  was not inspected in the current period. The engine now blocks that required
  comparison as `insufficient_data`, forcing onboarding to repair the card or
  source selection.
- An older Juniper artifact no longer matched the fixture digest after the
  catalog-noise RNG was corrected. The independent reviewer rejected it. It is
  not included in the results above.

These are not cosmetic benchmark adjustments. They are the exact failure modes
that would make a real pushed analytics workflow untrustworthy.

## What is still not proven

SignalWeave adds onboarding and Jev evaluation work. In these runs treatment
cold onboarding took roughly 65 seconds for Juniper and 101 seconds for Lumen,
versus roughly 23 and 27 seconds for the baseline. Jev requests and token
estimates were also additional. The recorded dollar fields are illustrative
API-equivalent estimates, not subscription charges or a provider invoice. The
first-run and total-cost claims therefore remain open.

This trial also does not prove narrative usefulness to real operators, broad
connector compatibility, expensive warehouse-query savings, or production
delivery safety. The strong-superiority gate is intentionally still false. The
next bar is at least three more independent company/profile families with the
same protocol, measured provider/query cost, blinded narrative review, and
held-out multi-period replay.

The machine-readable metrics, failure ledger, and artifact hashes are in
[`evidence/bootstrap-live-comparison-2026-10-04.json`](evidence/bootstrap-live-comparison-2026-10-04.json).
The independent review implementation is
[`evaluations/bootstrap_live_comparison_review.py`](../evaluations/bootstrap_live_comparison_review.py).

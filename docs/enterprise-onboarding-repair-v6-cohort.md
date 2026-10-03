# Conditional completion of the six-company v6 regression

Prospective plan, written while the v6 retail probe is running. No cohort success
is claimed. Proceed only if retail completes onboarding and all three later
native and final outcomes/routes, required numbers and provenance pass.

To avoid paying for the same retail onboarding again, test the other five whole
companies under the exact same frozen runtime, reviewer and dataset generator.
Do not patch them between companies. Include both arms and every period. Cap
the remaining run at 112 Jev attempts; combined with the retail probe's 32-attempt
cap, this preserves the full study's 144-attempt ceiling. Failed or blocked
records stay in each run's denominator. Retain all previous failed revisions.

```sh
python -m evaluations.enterprise_onboarding_journeys --live \
  --company-index 1 --company-index 2 --company-index 3 \
  --company-index 4 --company-index 5 --jev-budget 112 \
  --jev-key-file /secure/path/to/key \
  --output artifacts/enterprise-onboarding-repair-v6-remaining-01
```

The combined ledger must cover exactly six distinct companies, 12 onboardings
and 36 later observations across the two arms (48 records), with no overlapping
company or period. Validate each complete export and matching source hashes.
The two processes have separate rebased clocks and independent scenario order;
retain their exact configurations. This is a staged known-family regression,
not a single randomized cohort or a fresh holdout.

Treatment acceptance remains 6/6 onboardings, 18/18 later reports, 18/18 native
and final outcomes/routes, required numeric/provenance checks, and no unsupported
material narrative claims on independent internal review. A structural pass is
not a comparative-value win. Report setup and monitoring separately and keep
subscription-dollar estimates and real delivery outside the proven claims.

## Recorded results

The predeclared treatment acceptance gate did not pass. All 48 planned records
are retained across the retail probe and the remaining five companies: 12
onboardings and 36 later observations. Both components used revision `7703b0d`,
matching recorded source fingerprints and wrapper hashes, with separate rebased
clocks. The prospective protocol above is preserved.

| Measurement | Luna BI | Luna + SignalWeave |
| --- | ---: | ---: |
| Setup completed | 6/6 | 6/6 |
| Later reports returned | 18/18 | 18/18 |
| Final strict structured pass | 18/18 | 17/18 |
| Final outcome and recipients correct | 18/18 | 18/18 |
| Native outcome and recipients correct | N/A | 16/18 |
| Luna changed native outcome | N/A | 2/18 |

The treatment strict failure, `company-b06fc32e549ebf0def71` /
`period-2c1a7a0c2bb49acae7b7`, omitted `latency.rollout_lead_minutes`, a required
source reference, and the required explanation claim type. The two native
routing failures were corrected in the final Luna reports; those overrides do
not satisfy the native gate. Native correctness covers routing only, and strict
structured scores do not establish narrative support.

The [retail narrative review](evidence/enterprise-onboarding-repair-v6-probe-01/narrative-review.md)
already found a material overclaim of company-wide population completeness in
the treatment decline report. That finding remains unresolved. The raw cohort
export labels its narrative gate `unassessed`; no full-cohort narrative pass is
inferred from that field or from the structured results.

## Accounting and archive checks

| Recorded count | Retail probe | Remaining five | Cohort |
| --- | ---: | ---: | ---: |
| Jev attempts | 17 | 75 | 92 |
| Luna CLI invocations | 10 | 53 | 63 |
| Owner reviews included in Luna | 2 | 13 | 15 |
| Total recorded attempts/invocations | 27 | 128 | 155 |

Each recorded request has a matching response by provider, request ID and
episode. Three rejected owner reviews are retained. No provider failures,
unknown-usage attempts or budget censoring were recorded; Jev used 92 of the
combined 144-attempt ceiling. `api_attempts` in the component reports counts
Jev only. Luna CLI invocations can contain internal requests/retries that this
harness does not observe, so 155 is not a verified count of underlying API
requests.

Archived evidence:

- [Remaining run manifest](evidence/enterprise-onboarding-repair-v6-remaining-01/manifest.json): source and archive SHA-256 hashes for all 54 files, including compressed report, trace, 40 episodes, five card stores and five exporter outputs; config and protocol retained verbatim.
- [Cohort export](evidence/enterprise-onboarding-repair-v6-cohort/cohort.json) and [archive audit](evidence/enterprise-onboarding-repair-v6-cohort/archive-audit.json): verified component hashes, configurations, invocation counts, disjoint company sets and the full denominator.
- [Retail execution audit](evidence/enterprise-onboarding-repair-v6-probe-01/execution-audit.json) and [reviewer qualification](evidence/owner-review-qualification-v4-01/README.md) remain available alongside prior failures.

Both arms used the same owner-review protocol and delivery-disabled shadow
framing, but decisive finance context differed as qualified below. The baseline
persisted notes and used Luna for every later report; treatment also woke Luna
for every final report.
This comparison does not cover other baseline strategies or establish an
advantage. Separate clocks and repeated exposure to these scenario families
limit inference; the recorded `split=holdout` label does not make this a fresh
holdout. Subscription-dollar savings, real connector behavior, actual user
onboarding and caller-owned unattended delivery remain outside this evidence.

## Post-run fairness qualification: finance

A separate internal code/process review found that the finance oracle requires
the bank watermark to equal `period.as_of`. Luna receives that period field, but
native Jev's recorded request 74 does not. The control source promises an expected
reporting cutoff in its description but supplies only the watermark and partition
counts. Capture timestamps do not establish an agreed business cutoff.

The original 16/18 native count and all artifacts remain unchanged. The finance
quiet failure is **input-parity qualified**, not a clean test of Jev versus Luna
with identical decisive context. Jev preferred ignore at 0.58; the unchanged
confidence gate produced investigate. This is still a failed end-to-end input
handoff, not a passed case. Do not silently turn the result into 17/18, remove it
from the denominator, or attribute the whole deficit to the model.

Before a new paid comparison, version the fixture/source contract to publish the
actual agreed `expected_reporting_cutoff` to both arms and native Jev, distinct
from evaluation/capture time. Preserve the oracle, late/missing partition and
watermark controls, and future-case isolation. The existing explicit-clock probe
does not repair this: an evaluation clock is not a reporting cutoff. Onboarding
behavior, corroborating-source persistence and narrative support remain separate
unresolved gates.

## Trace-bound re-audit

The strengthened exporter now compares each retained monitoring submission with
the normalized successful `submit_analysis` tool receipt, and each native bundle
with its recorded `system.evaluation` response, before recomputing scores. Both
standalone and staged exports use those checks. Passing structured checks alone
can produce only `unassessed`, never an automatic narrative/overall pass.

An offline [trace-bound cohort re-audit](evidence/enterprise-onboarding-repair-v6-cohort/trace-bound-reaudit.json)
and [standalone execution audit](evidence/enterprise-onboarding-repair-v6-remaining-01/trace-bound-execution-audit.json)
passed those consistency checks without changing raw reports or traces. The
counts remain 16/18 native and 17/18 strict treatment reports; acceptance is
explicitly `not_passed`. The finance qualification still applies.

The 18 recorded source fingerprints also match their committed contents at
`7703b0d` when checked through Git history, not the modified current checkout.
These are artifact/revision consistency checks, not independent execution
attestation or proof that every internal provider request was observed.

## Post-run implementation and review note

Literal source boundaries, their projection into writer input, and authoring/
writer guidance have offline contract coverage only. Blank annotations do not
establish missing records; source health does not establish company-wide
completeness. No new live run has established the benefit of these changes.

Developer review found an `authorized=false` annotation leak and a preexisting
path that could label a report complete despite an unauthorized snapshot. The
fix suppresses unauthorized boundary annotations, marks source coverage failed,
and excludes that source's numerical claims and analysis provenance. These
offline repairs do not revise the archived v6 outputs or resolve their narrative
finding. The [adversarial review](evidence/enterprise-onboarding-repair-v6-cohort/adversarial-review.md)
records the separate exporter/replay findings and their review status; retain
the [finance input-parity qualification](#post-run-fairness-qualification-finance)
when interpreting native comparisons.

Final verification passed **2,210 tests with four opt-in skips** in 133.74 seconds,
with Ruff and `git diff --check` clean. Separate reviewers cleared the scoped
authorization/reporting, guidance, replay-safeguard and trace-binding fixes.
That clearance concerns implementation, not enterprise acceptance. No candidate
semantics explanation or evaluation-clock change from the component diagnostics
is promoted, and no threshold is lowered.

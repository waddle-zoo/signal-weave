# Reviewer qualification before another onboarding run

Status: prospective; business acceptance remains unproven.

The v3 run was stopped after a simulated reviewer required a compiled numeric
binding for a valid plain-English rule, then accepted an invented comparison.
The failed experiment remains in the repository. A model reviewer is itself an
instrument that needs testing; its approval is not evidence that execution works.

## Narrow repair

Numeric conditions remain optional. Jev receives the owner's decision guidance;
compiled numeric checks apply only to available analytical comparisons. For
research review, an authored comparison requirement no longer proves availability:
the binding must match an actually inspected current source comparison, including
unit and rate-effect applicability. The reviewer receives bounded descriptors,
not measurements, future periods, private labels, or expected outcomes.

Before spending on another company cohort, run the saved-login Luna reviewer
against positive and negative controls. Expectations stay outside its input.
Record every response once, including failures. A failed transport must never
count as a correct semantic rejection. Invented bindings must fail before a
model request. These controls qualify the review boundary only; they do not test
live Jev or establish product value.

## Subsequent live test

After qualification, run one complete company (retail, index 0) through both arms
and all three later periods. This directly retests the failed onboarding path
without paying for six companies first. Use a fresh output path and freeze the
source revision and instructions. The Jev cap is 32 attempts, no SDK retries;
all other per-episode and review budgets remain unchanged. Do not repair cards,
prompts, source data or policies during the run. Retain failures.

```sh
python -m evaluations.owner_review_qualification --live \
  --output artifacts/owner-review-qualification-v4-01
python -m evaluations.enterprise_onboarding_journeys --live \
  --company-index 0 --jev-budget 32 \
  --jev-key-file /secure/path/to/key \
  --output artifacts/enterprise-onboarding-repair-v4-probe-01
```

The probe must complete treatment onboarding and all three later reports with
correct native and final outcomes, recipients, required numbers and provenance.
Final-agent correction does not excuse a wrong native decision. Passing a probe
is not the six-company acceptance gate: all six onboardings and all 18 later
native and final outcomes still need to pass, with narrative and methodology
review. Keep setup and monitoring costs separate, and do not claim savings from
missing work. This is a known-family synthetic regression, not a customer study,
provider integration test, installed-binary test, or universal reliability proof.

## v4 probe results

Status: complete, with the structured acceptance gate not passed.

This was a bounded, single-company synthetic probe of Juniper Trail Retail. It
used the frozen revision `78dd7481c38883d8539c9ff484d2faa4521f296e`, eight
intended and eight observed records, and the same three monitoring periods in
both arms. Both arms completed onboarding and all three monitoring runs. The
probe is not a customer study, marketing result, or generalized reliability
claim.

The saved reviewer qualification remains archived at
[owner-review-qualification-v4-01](evidence/owner-review-qualification-v4-01/README.md).
The raw v4 evidence, compressed trace and episodes, frozen configuration, and
hash audit are in
[enterprise-onboarding-repair-v4-probe-01](evidence/enterprise-onboarding-repair-v4-probe-01/).

Counts below are `correct / three monitoring periods`; onboarding and completion
are `complete / intended`. “Final” is the submitted agent result. “Native” is
the treatment system routing result before the agent; the baseline intentionally
has no native SignalWeave decision and is therefore not comparable on that axis.

| arm | onboarding | monitoring complete | final outcome | final recipients | final provenance | final exact | native outcome | native recipients |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Luna BI baseline | 1/1 | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 | n/a | n/a |
| Luna + SignalWeave Jev | 1/1 | 3/3 | 1/3 | 1/3 | 3/3 | 1/3 | 1/3 | 2/3 |

Treatment native routing made the wrong outcome on two of three periods; the
agent changed that native outcome on both. Native routing was correct on one of
three periods and had correct recipients on two of three. Final treatment
results retained complete provenance on all three periods but failed the
structured gate on outcome, recipient, and exactness counts. There were no
runtime failures or unassessed monitoring runs.

## Timing and observed usage

| arm | cold setup seconds | warm monitoring median | warm monitoring total |
| --- | ---: | ---: | ---: |
| Luna BI baseline | 42.335 | 23.612 | 65.556 |
| Luna + SignalWeave Jev | 108.829 | 34.615 | 103.610 |

There were 26 observed model invocations: 16 Jev invocations and 10 Luna
invocations, including two owner-review invocations. The report's
`api_attempts=16` field is the Jev budget counter, not the all-provider total.
All observed invocations succeeded. Known API-equivalent usage estimates were
`$0.03428360` for baseline and `$0.07643954` for treatment; a measured
subscription-dollar comparison is unavailable. These figures are retained for
audit only and are not savings, price, or performance claims. External
notifications were disabled; delivery was shadow routing.

## Fairness and limits

The arm comparison is denominator-balanced for this probe: same company, policy,
source fixture, owner-review protocol, model family, three monitoring periods,
and complete execution in both arms. It is still only one synthetic company and
does not establish the six-company acceptance gate. The absence of a native
baseline decision means native treatment-versus-baseline deltas cannot be
interpreted as a controlled comparison of native systems.

## Observed onboarding defect

The treatment onboarding trace shows a valid request with nonempty
`decision_guidance` and no `watch_for`/`questions` being rejected with
`intent-detail-required` at [src/signalweave/onboarding.py:525](../src/signalweave/onboarding.py:525).
The author then added a required completeness watch and onboarding completed.
The condition checks only those two fields and ignores usable decision guidance;
this is a production authoring/acceptance defect, not evidence that the original
owner policy was invalid. The run was frozen and not repaired during execution.
It is fixed next in [v5](enterprise-onboarding-repair-v5.md); no source or harness
changes were made during this run.

Because the structured gate failed, no narrative panel was run and no narrative
success claim is made. The six-company acceptance gate remains open.

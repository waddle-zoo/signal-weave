# Current live bootstrap proof

Status: internal research evidence. This is not external peer review or a
production reliability claim.

This note records the current-source live comparison for SignalWeave with Jev
against the same `gpt-5.6-luna` agent using the same cards, connector catalog,
source snapshots, owner policy, permissions, and final submission contract.
The treatment evaluates the card with live Jev before waking Luna and passes a
typed evidence bundle to it. The baseline receives the identical owner-reviewed
card and uses the ordinary connector tools. Delivery is disabled in both arms.

## Current cohort

The three held-out companies use different connector shapes and business
policies. Each has one onboarding period and three monitoring periods. The
catalog contains ten scoped alternatives per canonical resource, so selection
cannot depend on a clean four-item catalog.

| Company | Connector profile | Luna exact | SignalWeave + Jev exact | Warm Luna work | Downstream wakeups |
| --- | --- | ---: | ---: | ---: | ---: |
| Cinder Database Cloud | CloudWatch / PagerDuty / Airflow / Superset | 3/3 | 3/3 | 86.8s → 45.8s | 3 → 2 |
| Lumen Freight Finance | Trino / dbt / Looker / Airflow | 2/3 | 3/3 | 80.1s → 61.4s | 3 → 2 |
| Mosaic Exchange | Hex / Segment / Superset / Trino | 3/3 | 3/3 | 72.6s → 30.9s | 3 → 2 |
| **Total** | **3 connector profiles / 9 periods** | **8/9** | **9/9** | — | **9 → 6** |

Across the treatment rows, outcome correctness, recipient correctness, required
evidence, numeric precision/recall, provenance completeness, and unsafe-action
checks were all 100%. The treatment used live Jev on every non-skipped path;
complete quiet decisions skipped the downstream Luna wakeup with provenance.
The independent comparison reviewer and onboarding reviewer both passed the
current source fingerprint at commit `06fdfc7`.

Artifacts:

- Cinder: `/private/tmp/signalweave-live-bootstrap-cinder-20261004-v3/report.json`
- Lumen: `/private/tmp/signalweave-live-bootstrap-lumen-20261004-postcommit-v1/report.json`
- Mosaic: `/private/tmp/signalweave-live-bootstrap-mosaic-20261004-postcommit-v1/report.json`
- paired reviewers: `/private/tmp/signalweave-review-{cinder,lumen,mosaic}-20261004-postcommit.json`
- onboarding reviewers: `/private/tmp/signalweave-onboarding-review-{cinder,lumen,mosaic}-20261004-postcommit.json`

## What the trial actually proves

It is evidence that a Jev-backed card and evidence bundle can preserve or
improve Luna's structured monitoring result while reducing recurring downstream
agent work across heterogeneous synthetic connector profiles. The clearest
current win is Lumen: the baseline got the business disposition and recipients
right but missed the exact typed evidence required for an exact result; the
card-backed Jev path retained it.

The current result does **not** prove that SignalWeave is cheaper or faster on
first use. Treatment onboarding took longer in all three cases (147.0s vs
64.8s for Cinder, 208.1s vs 66.9s for Lumen, and 190.2s vs 67.2s for Mosaic),
and illustrative token-equivalent usage was higher. The runner uses in-process
snapshots and reports source-read counts, not Trino bytes, queue time, provider
invoices, or real hosted BI latency. Any three-minute-query savings remain a
separate modeled claim until measured with connector telemetry.

The onboarding reviewer is an independent model review, not a real human
approval. It did catch real policy defects: Lumen required the UTC boundary and
Mosaic rejected an over-broad missing-data route before approval. Narrative
usefulness to operators is still unassessed in this current cohort.

## Multi-step evidence

The current live Northstar multi-step artifact covers six scenarios, including
two investigation paths and four terminal single-step paths. Initial outcomes,
typed handoffs, final outcomes, and final handoffs were all 6/6; the separate
adversarial reviewer passed with zero findings:

- report: `artifacts/northstar-multistep-trial-current-2026-10-04.json`
- reviewer: `evaluations/northstar_multistep_adversarial_review.py`

This proves the handoff contract and safe progression from `investigate` to
`notify` when a caller returns diagnostic context. It does not prove that
SignalWeave itself discovers arbitrary external facts or replaces the
caller-owned investigation agent.

## Larger same-card control evidence

The repository also retains a larger live Jev paired-agent replay: 56
intention-to-treat cases using the same card and source surface for Luna-only
and SignalWeave-mediated arms. It reported 50/56 exact versus 26/56, required
evidence recall 0.93 versus 0.87, and unsafe automatic actions 3/56 versus
30/56. The internal adversarial reviewers called this a conditional mechanism
result, not enterprise proof: the treatment made more logical diagnostic-query
requests, one run timed out, and real provider economics were absent.

See [`paired-agent-trial-results.md`](paired-agent-trial-results.md) and
[`paired-agent-trial-protocol.md`](paired-agent-trial-protocol.md).

## Remaining acceptance gates

The product goal is not complete from synthetic evidence alone. The next gates
are a blinded narrative review, measured query/provider telemetry, and a small
real-team shadow replay with owner labels for useful/noisy/late/incomplete
bundles. Until those exist, the strongest defensible claim is a reproducible
quality-and-recurring-agent-work signal, not universal accuracy, total-cost
savings, or autonomous delivery readiness.

# Targeted bootstrap regression v3-04

**The authoring repair is not sufficient.** Both cards onboard and execute, but
native outcome and recipient correctness is 4/6. The treatment's final agent
output is correct on 5/6 routes versus the baseline's 6/6. No comparative benefit
or enterprise-readiness claim follows from this run.

Frozen revision `3940da2ec6107a3d10a19f5a347fadccf9a9feeb`; seed 20261002;
the same two known-failure companies and all periods from v3-03. Dataset digest
`bb559f8f482911af51d8649ea096fae08bc4244d9088f92f183751be917969b2`.
The [pre-run declaration](bootstrap-repair-ledger.md) retains the unchanged raw
fixtures, labels, shared tools, budgets and pricing. This is retrospective
development, not a fresh holdout or an isolated experiment on either the watch
repair or the authoring descriptions. No expert-authored cards were supplied.

All 16 Codex/Luna low-effort episodes completed. Treatment used 29 of 60 permitted
live Jev requests, observed `jev-1.13.0`, with no failed calls, missing usage or
budget censoring. Neither arm delivered external notifications. Codex used its
saved login; there was no OpenAI API key requirement.

## Results

| Endpoint | Luna + BI | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Setup complete | 2/2 | 2/2 |
| Monitoring complete | 6/6 | 6/6 |
| Frozen exact structured score | 5/6 | 4/6 |
| Final outcome AND recipients correct | 6/6 | 5/6 |
| Native outcome AND recipients correct | — | 4/6 |
| Setup seconds, total | 64.93 | 166.84 |
| Monitoring seconds, total | 165.93 | 155.20 |
| Monitoring median seconds | 27.28 | 23.66 |
| Source reads | 23 | 27 |
| Tool calls | 51 | 59 |
| Agent input + output tokens, including setup | 543,987 | 1,572,721 |
| Agent input + output tokens, monitoring only | 386,302 | 452,078 |
| Illustrative API-equivalent USD | 0.04338 | 0.09674 |

Cached inputs are included once in input totals. Dollar figures are token-price
estimates, not Codex subscription charges. Lower observed monitoring wall time
does not establish a cost/quality win: setup and agent tokens are higher and one
final disposition is wrong. Every monitoring case still wakes Luna. Jev consumed
124,402 input and 5,730 output tokens across its 29 requests.

## What the traces establish

- **Helpdesk: native and final routes 3/3.** Event, quiet and missing-denominator
  conditions now follow the owner policy. The generated card separates recurring
  questions from setup questions. This is a two-change development run, so it
  cannot attribute that improvement to schema guidance alone.
- **Database event: the generated policy changes the owner's intent.** The owner
  explicitly requires `investigate` to the business destination when latency,
  lag and affected-region conditions hold. The generated card instead says
  "Investigate and notify" and has only `notify` and `insufficient_data` routes.
  Jev favors notify; code downgrades to investigate for incomplete evidence, with
  no configured investigation recipient. The agent changes it back to notify.
  Correct arithmetic and an authorized recipient do not make this correct.
- **Database quiet: native abstention is still wrong.** The card includes an
  exclusion policy (isolated CPU is not a trigger) as a required watch condition
  and a broad source-completeness question. Unknown judgments contribute to an
  incomplete plan. The native outcome is investigate; the agent repairs it to
  ignore. Database missing-coverage routing is correct.
- **Approval remains procedural in this harness.** Inspection and simulation
  fingerprints are checked; no independent owner compares the draft to their
  original answers. The record explicitly says policy correctness is unvalidated.
  That limitation cannot be rebranded as successful human-approved onboarding.

Native outcome correctness and native recipient correctness are each 5/6, but
their intersection is **4/6**, not 5/6. Two final agent outcome changes comprise
one repair and one degradation. Zero `wrong_recipient_count` or `missed_event_count`
does not excuse the investigate-versus-notify policy violation.

## Independent narrative review

[Internal blind review](evidence/bootstrap-codex-regression-v3-04/review.md)
graded baseline 5 supported/1 qualified and treatment 4 supported/1 qualified/
1 unsupported. The unsupported treatment recommendation is the database event's
notify outcome. Both qualified outputs emit a canonical population-scoped zero
latency delta while acknowledging that population coverage is missing. All 31
reported numeric claims are arithmetically consistent; arithmetic is not sufficient
to establish the meaning or validity of a metric. No unsupported causal mechanism
was found. This is one independent subagent review, not external peer review.

Frozen exact scores retain the earlier public-contract disagreements about
mandatory rollout details and population-scoped arithmetic. No retrospective
rescore was used. These ambiguities do not remove the observed policy rewrite,
missing route or agent correction burden.

[Results](evidence/bootstrap-codex-regression-v3-04/results.json),
[blind packet](evidence/bootstrap-codex-regression-v3-04/blind-review.json) and
[sealed mapping](evidence/bootstrap-codex-regression-v3-04/review-key.json) retain
all outputs and usage. Full local report SHA-256:
`87ae591db621bfba0789b36be021dede58d89efdd7259641fa00300ce8e396f4`.
The results file's pending-review field is historical; the separate completed
review supplies that result. Full local traces remain in
`artifacts/bootstrap-codex-regression-v3-04/`.

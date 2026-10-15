# Empirical onboarding acceptance regression

## Question and boundary

Can the existing workflow evaluator distinguish a tested card from an accepted
draft, expose evidence blockers, and bind approval to the tested configuration?

This change does not add another agent, scheduler or semantic model. Jev still
owns semantic judgments; the evaluator checks independently supplied labels.
The TypeSafe skill informed that boundary: application code owns exact lookup,
integrity and admission, rather than asking a model whether its work is correct.

The opt-in live regression uses the existing expert-reviewed operating-record
examples: finance approval, maintenance-window compliance and renewal ownership.
Each has positive, negative, missing and conflicting evidence, for 12 cases total.
One card is reused for each domain. This is development regression evidence,
not novice onboarding, a fresh holdout, real customer data or a Luna comparison.

## Frozen procedure

- Exactly 12 judgments maximum, one per case, no retries or prompt correction.
- Stored plans avoid extra compilation requests; no LLM agent runs in this test.
- Expected outcomes and exact destinations stay outside Jev state/questions.
- All three declared outcomes must be covered for these particular policies.
  Production acceptance covers caller-declared outcomes, not a fixed taxonomy.
- Exact outcome, endpoints, required evidence and supplied resource-reference
  coverage must pass. The live trial additionally checks semantic watch states.
- Failure, cancellation and raw provider distributions are retained. A durable
  request journal records attempts before dispatch. No external messages are sent.
- Working source hashes, inputs, labels and dependency versions are frozen in the
  manifest. Recompute the aggregate from recorded results without new inference.

```sh
uv run python -m evaluations.onboarding_acceptance_trial \
  --live --key-file /absolute/path/to/jev-key \
  --output artifacts/onboarding-acceptance-NEW-RUN
```

Offline checks also replay the retained v4 bootstrap outputs. Both companies'
diagnostic reports fail: only 2/6 original native results jointly match outcome
and exact endpoint labels. Their compact exports omit stored plans, so they
cannot be reused as new acceptance artifacts. No historical result is repaired,
relabelled or represented as new model inference.

## Live result: v1-01

The [retained report](evidence/onboarding-acceptance-v1-01/report.json),
[frozen manifest](evidence/onboarding-acceptance-v1-01/manifest.json) and
[request/result journal](evidence/onboarding-acceptance-v1-01/events.jsonl)
record one completed run on `jev-1.13.0`:

| Measurement | Result |
| --- | ---: |
| Exact outcome and exact configured destinations | 12/12 |
| Passing domain acceptance reports | 3/3 |
| Correct semantic watch states | 12/12 |
| Required evidence recall | 100% |
| Jev requests / retries | 12 / 0 |
| Provider input / output tokens | 31,626 / 1,119 |
| Median per-case engine latency | 200.6 ms |
| Summed per-case engine latency | 2,566.1 ms |

Source hashes stayed unchanged during execution. There was no LLM override and
no external delivery. Latency excludes onboarding/authoring and slow BI queries;
this is not an end-to-end agent speedup. Evidence and retrieval labels refer to
the single supplied record in each case, not a search over an enterprise catalog.

These results show that the acceptance path composes with live Jev on reviewed
cards, while offline adversarial checks reject failed, stale, endpoint-mismatched
and incomplete acceptance artifacts. They do not show a novice agent can yet
produce equally good cards or that this system outperforms Luna.

An independent internal agent reviewed the code and trial before dispatch, then
recomputed 40/40 report checks after execution. It verified model identity,
request counts, provider usage, exact outcomes/endpoints and watch states against
the journal, and found no remaining blockers for this bounded change. This is
internal adversarial review, not external peer review or customer validation.

## Remaining comparative experiment

This gate makes failures visible before claiming onboarding success; it does not
prove an authoring agent will repair them. The next bootstrap trial must give
both arms the same owner-reviewed setup examples and source definitions, let
them inspect empirical failures within a fixed correction budget, then freeze
the cards/notes before unseen monitoring periods. Keep a separate expert-card
control to measure the authoring gap.

Measure native Jev workflow results separately from agent overrides. A subsequent
recurring-cost comparison must include setup and actual exception investigations,
with a fair cached/notes-enabled Luna baseline. Do not reuse the old agent-on-every-
run timing as evidence that headless recurring execution saves work.

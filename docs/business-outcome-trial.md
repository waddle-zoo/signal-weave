# Recurring business reports: paired trial

Question: after assisted onboarding, does SignalWeave help the same agent deliver
correct, useful reports to the right people with less recurring work?

The experiment includes the final LLM-written explanation. A fast decision alone
does not answer that question. A passing structured report does not prove its
prose is faithful, either.

## Result: no demonstrated end-to-end advantage yet

The [frozen paired run](evidence/business-outcomes-live-01/report.json) used live
Jev and saved-login Luna on revision `7030068`. All six agent episodes completed,
with twelve Jev calls, no retries, and no API failures. Every period produced a
final narrative. Nothing was delivered externally.

| Measured across three companies, four periods each | Luna baseline | SignalWeave + Jev + Luna |
| --- | ---: | ---: |
| Exact policy, routing, numerical and provenance checks | 12/12 | 10/12 |
| Unnecessary quiet-period notifications | 0 | 0 |
| Missed required notifications | 0 | 2 |
| Correctly suppressed quiet periods | 3/3 | 3/3 |
| Final reports judged usable in arm-masked AI review | 12/12 | 10/12 |
| Total episode time, including final prose | 112.6 s | 119.2 s |
| Agent tool calls | 35 | 46 |
| Source reads | 12 | 24 |
| Luna uncached input tokens | 87,814 | 105,063 |
| Luna output tokens | 3,744 | 3,964 |

Provider-reported Luna input totals were 477,446 versus 554,087, including
389,632 versus 449,024 cached input tokens. Treatment additionally used 92,205
Jev input tokens and 2,684 output tokens. Those are different providers' token
units, not a measured dollar bill. All twelve treatment receipt replays returned
the archived result without further Jev or source calls.

The treatment agent inspected the sources again after the workflow had already
fetched them. That duplication is an actual integration cost in this run, not
an unavoidable SignalWeave requirement; it stays in the totals. Treatment took
5.9% more episode time and used 19.6% more uncached Luna input tokens. This run
does not support a speed, cost, alert-quality, or incremental human-toil claim.
Both arms had the same deterministic calculation tool; this is intentionally a
strong baseline, not an LLM forced to calculate or copy tables unaided.

### What failed

- **Retail, p07:** total sales stayed flat while two channels contributed +$90
  and -$90. The policy explicitly required notifying on either channel's
  magnitude. Jev recognized the relevant watch item, but selected `ignore` with
  0.68 support. The unchanged 0.70 threshold deferred to `investigate`, which
  had no configured notification recipient. Arithmetic was correct; the policy
  was not carried through to the required alert.
- **Fulfillment, p08:** a flat total hid warehouse contributions of +20 and -20.
  Jev selected `ignore` with 0.80 support and gave the required contribution
  watch only 0.50 support. The evidence check blocked the report. The supplied
  arithmetic and policy called for notifying Fulfillment.

The [method audit](evidence/business-outcomes-live-01/method-review.json) accepted
the bounded trial's integrity and rejected a success headline. The separate
[arm-masked prose review](evidence/business-outcomes-live-01/prose-review.json)
found no invented arithmetic or unsupported causal assertions, but the final
writer faithfully repeated the two bad workflow dispositions. After unmasking,
practical-usefulness preference was baseline 3, treatment 1, tie 8. These are
internal AI reviews, not independent external peer review or human preference
measurements. The review's self-reported model label is not verified provider
telemetry; the trial agents' model configuration is retained in the journal.

### Separate development probe: partial improvement, not a repaired benchmark

Revision `dc619d7` adds policy-bound descriptions for routed outcomes: a delivery
label identifies a recipient, not a trigger. It also defines signed accounting
contributions for the model, including cancellation at zero aggregate change.
This follows the distinction between question instructions and option meanings
in the [TypeSafe Choice documentation](https://docs.typesafe.ai/primitives/choice).
No business-specific threshold, company name, forced notification rule, or
confidence reduction was added to runtime code.

The [six-call Jev-only regression probe](evidence/business-outcomes-probe-live-01/report.json)
used the same two failure inputs plus quiet, definition-conflict, stable-high,
and incomplete-data controls. It passed **5/6**. Fulfillment's failure cleared;
retail selected `notify` but only with 0.52 support, so it still deferred. The
four controls retained their expected outcomes. Both prompt/state changes were
tested together, so this is not an ablation of their individual effects.

These were already-seen inputs, with one call each, no final writer, and no new
baseline run. They do not establish generalized reliability or change the
primary 10/12 score. Total new live usage for this work was **18 Jev attempts and
6 Luna episodes**, plus development/review agents outside the measured arms.

### What remains

1. Make policy-to-outcome interpretation reliable on opposing contributions,
   exceptions, conjunctions, and unclear context—without lowering safety gates
   or turning every present watch into a notification.
2. Expose decision uncertainty separately from missing source evidence. Give the
   caller an explicit, approved review path; an unconfigured fallback must not
   silently strand a recurring investigation.
3. Have the final writer consume the already-fetched bundle instead of reopening
   complete sources. Then remeasure the whole workflow against the same capable
   persistent baseline, including quiet-run behavior.
4. Test fresh policies and companies, and a fresh assisted-onboarding attempt.
   This run reused onboarding; it did not establish unattended bootstrapping.

The branch is not ready for an enterprise-success claim on this evidence.

## Frozen design

Three synthetic businesses—retail sales, support operations, and fulfillment—each
have four fresh chronological periods. The catalog, source definitions, policy,
and destinations are unchanged from the retained first-report onboarding. New
measurements include material changes, quiet or offsetting periods, and missing
or contradictory evidence. There are twelve paired observations but only three
company clusters, not twelve independent enterprise deployments.

Both arms receive the same previously LLM-authored card, owner
policy, source access, and deterministic calculation tool:

- **Baseline:** Luna retrieves evidence, applies policy, and writes the report.
- **SignalWeave:** the approved workflow retrieves evidence and uses live Jev;
  Luna writes the final report from that result. It cannot override its outcome
  or recipients. The LLM may inspect the same sources for clarification.

Each arm keeps one Luna episode across the four periods. Future facts and private
labels are inaccessible through tools; no grading feedback reaches either arm.
All submissions cite compact comparison references rather than copying tables.
Historical preview notes are retained for audit but omitted from both prompts:
they contain old measurements and conclusions, not just reusable policy. Cards
are restored from the recorded successful approval and checked for matching
fields; this does not test a new approval transition.

Arm execution order alternates across companies. This is an end-to-end workflow
comparison, not a claim about Jev versus Luna in isolation.

The live ceiling is twelve Jev attempts and six saved-login Luna episodes, with
no automatic model retries. Each episode allows at most 28 tool calls and a
240-second response/process timeout. Rejected submissions remain in the journal.
One receipt replay per treatment period checks idempotency without new model or
source calls. Only simulated delivery records are written—no real notifications.

Inputs, labels, approved context, source hashes, and budgets are saved before
calls. Historical setup failures and costs remain in their original evidence
bundles. This run does not repeat novice onboarding or erase its prerequisites.
The prior cumulative totals include setup **and** prior runtime experiments;
they are not a clean onboarding-only cost estimate.

## Scoring and independent review

The numeric/policy scorer checks status, outcome, exact recipient keys, source
definition, population, comparison windows, arithmetic, contributions, and query
provenance against independent fixture arithmetic. Missing submissions remain
failures. Private expectations never reach either agent.

Final narratives receive a separate arm-masked review against policy and evidence:
numeric fidelity, causal restraint, material caveats, explanation of significance,
and an evidence-bound next step. Reviewers are internal AI agents, not external
peer reviewers or a human preference study. Masking cannot guarantee that writing
style will not reveal the arm.

Usable in this bounded sample means all twelve intended reports pass, with no
wrong recipients, useless quiet-period alerts, unsupported numerical/causal
claims, or hidden evidence gaps, and complete accounting. An advantage requires
no correctness/safety regression plus either three paired quality wins with no
losses or at least 20% lower measured monitoring resource use. Otherwise report
a tie, a trade-off, or failure—not a marketing win.

Report episode-level elapsed time including final prose, marginal submission
times, source reads, tool calls, Jev requests, and provider-reported token usage
(cached input separately). Unknown usage is unknown, never zero. Saved-login
token counts are not an API dollar invoice. No warehouse latency is injected;
these are cached, typed synthetic exports.

Unnecessary notifications and incorrect/missing reports are workload **proxies**.
They do not measure human hours saved. If both arms eliminate the same dashboard
checks, SignalWeave cannot claim incremental toil savings from this experiment.

## Run

```sh
python -m evaluations.business_outcome_trial --output artifacts/business-outcomes-dry
python -m evaluations.business_outcome_trial --live \
  --jev-key-file /path/to/private/key \
  --output artifacts/business-outcomes-live
```

Use a new output directory for every attempt. The saved-login Codex transport
needs a locally authenticated CLI. Raw logs contain synthetic company context;
review before publishing. No results are implied by the protocol itself.

# Recurring business reports: paired trial

Question: after assisted onboarding, does SignalWeave help the same agent deliver
correct, useful reports to the right people with less recurring work?

The experiment includes the final LLM-written explanation. A fast decision alone
does not answer that question. A passing structured report does not prove its
prose is faithful, either.

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

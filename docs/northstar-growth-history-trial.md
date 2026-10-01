# Northstar Growth Analytics historical decision replay

This is the first company-shaped proof aimed at the product's actual promise:
an analytics agent can wake up, inspect a bounded set of existing business
assets, decide whether a change deserves a push, and return the evidence that
made the decision useful.

It is an evaluation-only extension of the existing Northstar Superset example.
It does not add a new runtime abstraction and it does not contact Slack or
change the source systems.

## Trial design

The simulated team is Northstar Outfitters' Growth Analytics group. Its
owner-authored card asks the system to distinguish ordinary movement, isolated
or conflicting movement, a corroborated decline, and source failure across:

- the Northstar Executive Pulse Superset dashboard;
- the web-session funnel table;
- the support backlog table; and
- the finance daily table.

The decision register in
[`examples/northstar-growth-historical-decisions.json`](../examples/northstar-growth-historical-decisions.json)
contains eight dated operating periods and six recurring decision shapes. It
expands to 48 cases: 24 train, 12 validation, and 12 holdout. Every case uses
the same real local Northstar seed rows and the same card; only the
counterfactual movements and the external human disposition change.

The disposition labels stay outside the Jev payload. Jev sees the card and
bounded source snapshots. The evaluator scores the result afterwards against
the registered team decision. This prevents the trial from rewarding a model
for being shown the answer.

The replay was run in two passes. The first pass used the initial card wording:
it reached 22/24 exact outcomes on train, 9/12 on validation, and 10/12 on the
holdout-style slice. Its seven errors were all low-movement cases routed to
investigate. The only change was to the human-authored card: it now states the
policy priority explicitly—below 10% means suppress, even when mild supporting
movement exists. No runtime or evaluator rule was changed. The final card was
then locked and rerun across all 48 cases. Because this is a simulated register
and the card was iterated once, the holdout result below is a strong
repeatability check, not independent customer validation.

The control represents a common current-state workflow: push whenever primary
revenue moves by at least 10%, without interpreting the connected evidence.
SignalWeave uses the production `InsightEngine` with live Jev, then maps its
typed outcome to the caller-owned delivery route and records the evidence
bundle, rationale, probabilities, and source recall.

## Live result: 2026-09-27

The replay used the Northstar seed rows at the time of the run and a real
TypeSafe API key. The generated raw report is intentionally ignored by Git
because it contains local paths and detailed fixture evidence; the command
below reproduces it.

| Measure | Movement-only control | SignalWeave + Jev |
| --- | ---: | ---: |
| Cases | 48 | 48 |
| Leadership pushes | 25 | 8 |
| Unnecessary pushes/routes | 17 | 0 |
| Missed required workflows | 8 | 0 |
| Push precision | 32.0% | 100.0% |
| Exact outcome | not applicable | 48/48 (100.0%) |
| Exact delivery route | not applicable | 48/48 (100.0%) |
| Required-source recall | not available | 48/48 (100.0%) |
| Complete evidence bundle | not available | 48/48 (100.0%) |
| Agent workflow complete | not available | 48/48 (100.0%) |
| Median decision latency | no semantic decision | 283.49 ms |
| p95 decision latency | no semantic decision | 517.75 ms |

On the unseen 12-case holdout, SignalWeave + Jev also achieved 12/12 exact
outcomes, 12/12 exact delivery routes, 12/12 complete evidence bundles, and
zero unnecessary routes or missed non-ignore workflows. The simulated decision
register estimates 1,544 minutes of manual inspection across the 48 cases
versus 336 minutes for the SignalWeave workflow, or 1,208 modeled minutes
avoided. Those minutes are scenario estimates, not measured employee time.

The live Jev arm used 48 judgment requests, 729,588 input tokens, and 9,852
output tokens. Jev requests are the semantic decision cost; source-query cost,
downstream delivery, and human response time are not included in the latency
number.

## Adversarial gate

The independent report-only reviewer passed with zero findings. It fails if:

- SignalWeave routes a case the card says to suppress;
- it produces an unnecessary leadership push;
- it suppresses a required non-ignore workflow;
- a required source is absent from the evidence bundle;
- the rationale or evidence bundle is incomplete; or
- any holdout quality metric falls below 100% for this proof fixture.

Run it with:

```bash
uv run python -m evaluations.northstar_growth_history_adversarial_review \
  artifacts/northstar-growth-history-live-v2.json
```

The test suite also mutates a safe report into an unsafe leadership push and
checks that the reviewer rejects it.

## Reproduce

The seed rows are the four Northstar example files used by the local Superset
trial. Set the path to the checkout that contains them and provide a local
TypeSafe key file:

```bash
uv run python -m evaluations.northstar_growth_history_trial \
  --seed-dir /path/to/warehouse/init \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --output artifacts/northstar-growth-history-live.json
```

For a zero-credit design check:

```bash
uv run python -m evaluations.northstar_growth_history_trial \
  --seed-dir /path/to/warehouse/init --dry-run
```

## What this proves, and what it does not

This is materially stronger than a six-case demo: the card is tested across a
time split, the control sees the same primary movement, and the holdout shows
that the policy survives unseen dates. It demonstrates the specific value of
SignalWeave in this workflow: reducing noisy pushes while preserving the
cross-source explanation and the agent's next route.

It is still not customer evidence. The Northstar rows are local example data,
and the dated movements and human dispositions are simulated. The next real
promotion gate is one consenting team replaying its own historical decisions,
with the same labels independently reviewed by the team and no delivery side
effects until the holdout passes.

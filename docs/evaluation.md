# SignalWeave evaluation and proof standard

## What the proof tests

The goal is not to claim that a semantic model is universally correct. The goal
is to prove the application contract that makes semantic automation useful:

- facts come from installed adapters or explicitly labeled evaluation input;
- owner language becomes a bounded, reviewable `InsightPlan`;
- Jev evaluates the card's watch items, questions, and outcome conditions;
- results use only configured outcomes and delivery methods;
- evidence is returned with the result; and
- uncertain or untrusted states do not trigger automatic action.

## Representative cases

The four labeled evaluation cases exercise different failure modes:

| Case | Signal | Correct behavior | Main protection |
| --- | --- | --- | --- |
| Revenue decline | revenue down 14%, enterprise churn up 290% | notify Revenue Operations | cross-source semantic context |
| Seasonal normal | sales and orders down 18%, seasonality stable | ignore | explicit seasonal interpretation |
| Mobile conversion | conversion down 31%, mobile errors up 822% | notify Growth and Engineering | dimension and related-signal context |
| Data freshness | warehouse load stale 31 hours | escalate Data Platform | hard freshness gate |

## Reproduce

For the current generalized bootstrap/retrieval/workflow proof, run the
Jev-only trial and its independent adversarial gate documented in
[`generalized-readiness-trial.md`](generalized-readiness-trial.md). The older
representative-case commands below remain useful for focused regressions.

For the focused enterprise-scale omission proof, see
[`northstar-relationship-expansion-trial.md`](northstar-relationship-expansion-trial.md).
It tests the adapter-owned relationship-expansion contract against a virtual
100,000-resource-per-adapter catalog and records the boundary between candidate
recall and workflow-bundle completeness.

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli prove

TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark --systems jev --repeats 5

uv run python -m pytest

RUN_SUPERSET_INTEGRATION=1 \
  SUPERSET_URL=http://localhost:8088 \
  SUPERSET_USERNAME=admin \
  SUPERSET_PASSWORD=admin \
  uv run python -m pytest -q tests/test_superset_integration.py
```

For a chart-shape matrix rather than a single dashboard smoke test, run the
same client path over every saved dashboard in the local Superset:

```bash
uv run python scripts/superset_chart_matrix.py
```

The harness reports chart-family coverage and fails on unclassified empty
results, observations without metric labels, or observations whose metrics
were silently dropped. In the local fixture on 2026-09-26 it traversed 9
dashboards and 102 charts, produced 9,231 observations, classified 101 charts
as `extracted`, and marked one raw multi-number table `partial` because its
saved definition did not identify metric semantics. It reported zero
unsupported charts and zero silent-loss issues.

For the hosted Preset source boundary, run the fixture-backed multi-workspace
trial. It uses the production Preset client and adapter, but no TypeSafe
credits:

```bash
make preset-trial
```

The trial intentionally proves transport, chart/result normalization, policy
enforcement, token refresh, and partial-failure visibility separately from
semantic Jev quality. See [`preset-integration-trial.md`](preset-integration-trial.md)
for its evidence and remaining real-account gates.

The live integration test is skipped unless explicitly enabled. The unlabeled
external-source acceptance check is:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
SUPERSET_URL=http://127.0.0.1:8088 \
  uv run python scripts/live_card_check.py \
  --card examples/insight-card.json
```

The scheduled daily path can be exercised end to end through the real MCP
approval flow and webhook using a rotating Superset-shaped fixture:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PUSH_WEBHOOK_TOKEN=local-trial-token \
  uv run python -m evaluations.daily_monitor_trial \
  --output artifacts/daily-monitor-trial.json
```

That trial proves a human-confirmed card can return `ignore` for an ordinary
snapshot, `notify` with the configured owner route when a primary metric and
related driver move together, include every dashboard observation as evidence,
and replay a scheduler retry without evaluating or routing twice. It does not
prove that Jev or any card will be semantically correct for every company's
definitions; the live Superset acceptance check and a domain-owner holdout are
still required.

For the Northstar Outfitters local enterprise trial, the real seed rows behind
the Superset warehouse can be replayed as normalized aggregates across sales,
funnel, support, and finance sources:

```bash
uv run python -m evaluations.northstar_shadow_trial \
  --seed-dir /path/to/northstar/warehouse/init \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --output artifacts/northstar-shadow-trial.json \
  --skip-openai
```

The harness validates the local Superset dashboard separately, then compares
Jev with an explicit fixed-threshold comparator over the same six-case
counterfactual replay. It records the human rubric, exact outcomes, false and
missed notifications, latency, and provider usage. The replay uses real local
rows but simulated day-to-day movements; it is evidence about the decision
contract, not a production accuracy claim. Supplying `--openai-dotenv` enables
the optional embedding-plus-reasoning baseline. Only normalized aggregates are
sent to external providers; raw seed rows are not.

The recorded result and promotion interpretation are summarized in
[`northstar-shadow-trial.md`](northstar-shadow-trial.md).

For the organization-level Northstar case study—40 role agents, 48 workflows,
and live Jev-backed routing across all 12 domains—see
[`northstar-corporation-trial.md`](northstar-corporation-trial.md) and run:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.northstar_corporation_trial \
  --evaluator jev
```

For the higher-scale Northstar mock workload—168 workflows, 169 anchor
discovery cases plus 168 graph-assisted bundle cases, 40 role agents, seven
messy source states, disjoint time splits, and a virtual 100k-resource native
catalog per adapter—see
[`northstar-scale-trial.md`](northstar-scale-trial.md).

For the mass analytical insights workload—cached dashboard evidence, expensive
Trino follow-up queries, query deduplication, and general-agent workload
comparison—see [`mass-analytical-trial.md`](mass-analytical-trial.md).

For the broader outcome-level “everything tracking” replay—heterogeneous
business context, unrelated decoys, repeated enterprise-shaped cases, a
movement-only baseline, and an independent safety reviewer—see
[`everything-tracking-trial.md`](everything-tracking-trial.md).

For the live comparative benchmark against an LLM-only control, including the
Jev-first product interpretation and independent input-integrity/safety audit,
see [`everything-tracking-llm-benchmark.md`](everything-tracking-llm-benchmark.md).

The Jev-only card-context counterfactual is included in that report and can be
replayed with:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PYTHONPATH=src:. \
.venv/bin/python -m evaluations.everything_tracking_card_clarity_trial \
  --typesafe-key-file /absolute/path/to/apikey_typesafe \
  --repeats 2
```

Unit tests use injected doubles and do not replace live Jev or Superset proofs.
The heterogeneous contract tests combine multiple source shapes without
requiring those services to be installed. The connector-neutral artifact test
uses Looker-shaped dashboard evidence and Hex-shaped notebook-run evidence;
other tests cover Superset, SQL, Airflow, and table-style refs.

For the provider-neutral embeddings-plus-reasoning comparison, see
[`benchmark.md`](benchmark.md).

## What to measure in a real deployment

Before enabling automatic delivery, collect a labeled evaluation set from the
company:

1. card version and source references;
2. observations and evidence presented;
3. result and confidence;
4. what the owner expected;
5. whether the result was useful, noisy, late, or unsafe; and
6. the eventual operational outcome.

Track at least:

- useful-result precision;
- missed-action rate;
- `investigate` rate;
- stale-data rate;
- evaluation latency and source latency;
- cost per Jev evaluation;
- percentage of results with complete evidence; and
- delivery-method corrections and card revision rate.

## Capture operator feedback without changing the decision contract

The MCP runtime exposes `record_decision_feedback` and
`list_decision_feedback` for the operating team's review loop, and
`get_decision_receipt` for recovering the complete shadow result after an
asynchronous scheduler call. A caller can
attach one of five labels—`useful`, `noisy`, `late`, `incomplete`, or
`unsafe`—to a completed decision receipt, along with the outcome and delivery
route the operator expected. The feedback record includes the immutable card
version and receipt identity, so a later review can distinguish a bad decision
from a card that was revised after the decision ran.

Feedback is deliberately append-only and tenant-scoped. It is evidence for a
future evaluation or card revision; it does not mutate the card, alter Jev
state, change thresholds, or silently retrain routing. The safest promotion
loop is:

1. run a reviewed card in shadow mode with delivery disabled;
2. present the receipt's result, evidence, telemetry, and intended route to an
   operator or caller-owned agent;
3. record the operator's label and expected outcome/route;
4. replay those labels in a time-split evaluation before changing the card; and
5. approve a new card version explicitly, then rerun the workflow gate.

For retrying a human or agent callback, pass a stable `feedback_id`. Repeating
the same label is replayed; reusing that id for different content is rejected.
This prevents a transient network retry from inflating useful/noisy counts.

This keeps human context in the product boundary while leaving the decision
itself to Jev and the deterministic workflow code. It also prevents an agent
from treating an unverified feedback note as new operational truth.

For company-owned graph context, inject a read-only `ContextProvider` into the
runtime. Its trusted, versioned snapshot is used for related-source expansion,
Jev state, and evidence; the provider/version are copied to the decision
receipt and any feedback label. MCP payload context remains unverified by
design, so an agent can contribute useful evidence without being able to grant
itself permission to retrieve additional sources.

The thresholds in this repository are proof starting points, not universal
calibration. Production thresholds should be set from the company’s consequences
and feedback.

## Adversarial cases covered

The automated suite verifies that the service:

- does not treat source timeouts or missing charts as `ignore`;
- rejects incomplete numeric results instead of guessing;
- bounds saved-query limits;
- does not accept a semantic automatic outcome without a matching configured
  delivery method;
- protects HTTP routes when a deployment token is configured; and
- keeps the MCP health check available without exposing the decision surface.

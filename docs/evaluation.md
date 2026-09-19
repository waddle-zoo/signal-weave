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

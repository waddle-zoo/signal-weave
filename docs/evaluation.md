# SignalWeave evaluation and proof standard

## What the proof is testing

The goal is not to claim that a semantic model is universally correct. The goal is to prove the application contract that makes semantic automation useful:

- facts are sourced from the dashboard or an explicitly labeled evaluation input;
- owner intent becomes a bounded, reviewable plan;
- decisions use only explicit outcomes and recipients;
- evidence is returned with the decision;
- uncertain or untrusted states do not trigger automatic action;
- the MCP and push interfaces call the same evaluation engine.

## Representative cases

The four labeled evaluation cases intentionally exercise different failure modes:

| Case | Signal | Correct behavior | Main protection |
| --- | --- | --- | --- |
| Revenue decline | revenue down 14%, enterprise churn up 290% | notify revenue operations | cross-chart semantic context |
| Seasonal normal | sales and orders down 18%, seasonality stable | ignore | explicit seasonal interpretation |
| Mobile conversion | conversion down 31%, mobile errors up 822% | notify growth | dimension and related-signal context |
| Data freshness | warehouse load stale 31 hours | escalate data platform | hard freshness gate |

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

The live integration test is skipped unless explicitly enabled. This keeps normal CI independent of a running Superset while preserving a one-command source-adapter proof when the Docker stack is available. The unlabeled external-source acceptance check is:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
SUPERSET_URL=http://127.0.0.1:8088 \
  uv run python scripts/live_superset_check.py \
  --monitor-card examples/monitor-card.json
```

Unit tests use injected test doubles and do not replace the live Jev or live Superset proofs.

For the provider-neutral embeddings-plus-reasoning comparison, see [benchmark.md](benchmark.md).

## What to measure in a real deployment

Before enabling automatic delivery, collect a labeled evaluation set from the company:

1. dashboard and card version;
2. observations and evidence presented;
3. decision and confidence;
4. what the owner expected;
5. whether the alert was useful, noisy, late, or unsafe;
6. eventual operational outcome.

Track at least:

- useful-alert precision;
- missed-action rate;
- `investigate` rate;
- stale-data rate;
- evaluation latency and Superset query latency;
- cost per evaluation for Jev mode;
- percentage of decisions with complete evidence;
- recipient correction and monitor-card revision rate.

The thresholds in this repository are a starting point for the proof, not a universal calibration. Production thresholds should be set from the company’s consequences and feedback.

## Adversarial cases covered

The automated suite also verifies that the service:

- does not treat source timeouts or missing charts as `ignore`;
- rejects ambiguous numeric chart results instead of guessing a metric;
- bounds saved query limits;
- rejects unapproved recipients;
- protects HTTP routes when a deployment token is configured; and
- keeps the MCP health check available without exposing the decision surface.

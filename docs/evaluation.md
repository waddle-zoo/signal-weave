# Evaluation and proof standard

## What the proof is testing

The goal is not to claim that a semantic model is universally correct. The goal is to prove the application contract that makes semantic automation useful:

- facts are sourced from the dashboard or deterministic fixture;
- owner intent becomes a bounded, reviewable plan;
- decisions use only explicit outcomes and recipients;
- evidence is returned with the decision;
- uncertain or untrusted states do not trigger automatic action;
- the MCP and push interfaces call the same evaluation engine.

## Representative cases

The four fixtures intentionally exercise different failure modes:

| Case | Signal | Correct behavior | Main protection |
| --- | --- | --- | --- |
| Revenue decline | revenue down 14%, enterprise churn up 290% | notify revenue operations | cross-chart semantic context |
| Seasonal normal | sales and orders down 18%, seasonality stable | ignore | explicit seasonal interpretation |
| Mobile conversion | conversion down 31%, mobile errors up 822% | notify growth | dimension and related-signal context |
| Data freshness | warehouse load stale 31 hours | escalate data platform | hard freshness gate |

## Reproduce

```bash
uv run semantic-monitor prove
uv run pytest
RUN_SUPERSET_INTEGRATION=1 \
  SUPERSET_URL=http://localhost:8088 \
  SUPERSET_USERNAME=admin \
  SUPERSET_PASSWORD=admin \
  uv run pytest -q tests/test_superset_integration.py
```

The live integration test is skipped unless explicitly enabled. This keeps normal CI independent of a running Superset while preserving a one-command local proof when the Docker stack is available.

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

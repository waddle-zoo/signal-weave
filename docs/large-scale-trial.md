# Large-scale live Jev trial

This is the current stress/proof run for the SignalWeave decision boundary. It runs the same production `MonitorEngine` and `JevJudger` used by MCP and push evaluations; the generator is evaluation-only code under `evaluations/`.

## Trial design

- 12 company domains: payments, fulfillment, support, security, cloud platform, sales, marketing, data warehouse, retail, people operations, logistics, and product.
- 6 decision classes per domain: corroborated `notify`, explained `ignore`, contradictory `investigate`, stale `escalate`, missing baseline, and source failure.
- 72 unique monitor cards and dashboards, generated from the external domain catalog in [`examples/trial-domains.json`](../examples/trial-domains.json).
- 2 repeats per case, for 144 full evaluations and 288 Jev API requests.
- Expected labels are held by the trial oracle and are never passed into the production engine.
- All cases use owner-provided materiality definitions, outcome guidance, approved recipients, and action-confidence thresholds.

Run it yourself:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.large_scale_trial \
  --repeats 2 --concurrency 8 \
  --output artifacts/large-scale-trial.json
```

## Latest run

Run date: 2026-09-17.

| Measure | Result |
| --- | ---: |
| Unique cases | 72 |
| Total evaluations | 144 |
| Exact outcome + recipient accuracy | 100.0% (144/144) |
| Wrong automatic actions | 0 |
| False `notify`/`escalate` actions | 0 |
| Missed expected `notify`/`escalate` actions | 0 |
| Provider errors | 0 |
| Repeat-stable unique cases | 72/72 |
| Median end-to-end evaluation | 710.78 ms |
| p95 end-to-end evaluation | 847.52 ms |
| Jev requests | 288 |
| Reported input tokens | 510,558 |
| Reported output tokens | 31,357 |

| Trial class | Evaluations | Exact accuracy | Errors |
| --- | ---: | ---: | ---: |
| Corroborated notify | 24 | 100.0% | 0 |
| Explained ignore | 24 | 100.0% | 0 |
| Contradictory investigate | 24 | 100.0% | 0 |
| Stale escalation | 24 | 100.0% | 0 |
| Missing baseline | 24 | 100.0% | 0 |
| Source failure | 24 | 100.0% | 0 |

## What this proves

The run gives strong evidence for the application contract:

1. Owner-defined conditions can be passed to Jev across unfamiliar metric names and company domains.
2. Jev can supply atomic semantic condition judgments while code selects the action and enforces the approved recipient list.
3. The same engine routes ambiguous relationships to `investigate` rather than forcing an alert.
4. Stale data, missing baselines, and source failures remain fail-closed even when semantic inference is unavailable or irrelevant.
5. Repeated evaluations were stable across this generated set, and the path stayed below one second at p95 on this host with concurrency eight.

## What this does not prove

This is not proof of universal enterprise accuracy. The domains, conditions, and labels are simulated. The `0.40` threshold for `ignore` is intentionally lower because it is a no-notification outcome; urgent `notify`/`escalate` actions used `0.70`. Production thresholds must be calibrated from consequence-weighted labels, false-alert cost, missed-action cost, and owner corrections.

The next hard test is a time-split export of real dashboard histories containing the monitor-card version, evidence shown, expected outcome, expected recipient, usefulness, latency, and eventual operational result. This trial proves the architecture and its safety behavior; it does not replace that deployment evaluation.

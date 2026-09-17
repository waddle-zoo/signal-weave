# SignalWeave demo walkthrough

This walkthrough proves three things independently:

1. the semantic layer can make useful decisions from structured dashboard evidence;
2. the same code can read a real Superset dashboard;
3. an external trigger can push an evaluation without turning the service into a scheduler.

## A. Jev-backed company proof

```bash
uv sync --extra dev
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe uv run signalweave prove
```

The result is live typed classification over the external cases in `examples/demo-cases.json`. The output shape is:

```text
scenario             outcome          recipient              confidence  expected  pass  ms
data_freshness       escalate         data-platform                1.00  escalate  yes  885.6
mobile_conversion    notify           growth                       0.96  notify    yes  711.8
revenue_decline      notify           revenue-operations           0.98  notify    yes  711.6
seasonal_normal      ignore           -                            0.92  ignore    yes  766.3
```

Jev probabilities and latency can vary. This proof demonstrates wiring, evidence, and routing behavior; it is not a general accuracy claim.

Generate a report with evidence statements:

```bash
uv run signalweave prove --format markdown --output artifacts/proof.md
```

## B. Real Superset proof

Start the isolated stack:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe docker compose up --build
```

Wait for the health checks, then verify:

```bash
curl http://localhost:18000/healthz
```

Use an MCP client against `http://localhost:18000/mcp`, or use the following conceptual tool sequence:

```text
list_dashboards()
inspect_dashboard(dashboard_id="7")
draft_monitor(
  dashboard_id="7",
  title="Sales pulse",
  intent="Alert when revenue changes materially. Compare related charts before routing.",
  chart_ids=["62", "64"],
  recipients=[{"key":"revenue-operations", ...}]
)
evaluate_monitor(monitor_id="draft-7-sales-pulse")
```

The adapter reads the dashboard’s saved chart definitions. A time-grained chart returns a comparable observation; a current-only chart returns evidence but is prevented from becoming an automatic action without a baseline.

## C. Push proof

After drafting a card, an existing scheduler or webhook relay can trigger it:

```bash
curl -X POST http://localhost:18000/webhooks/evaluate \
  -H 'content-type: application/json' \
  -d '{"monitor_id":"draft-7-sales-pulse"}'
```

The response is a JSON `Decision`. The caller decides whether `notify` or `escalate` should be delivered and how to retry it.

## D. Repeatable evaluator benchmark

Keep the credential outside the repository:

```bash
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
uv run signalweave benchmark --systems jev --repeats 5 --format markdown --output artifacts/jev-benchmark.md
```

The output records exact outcome-plus-recipient accuracy against the checked-in labels, repeat stability, confidence distribution, latency, requests, and provider-reported usage. To compare a general model with embeddings, follow [benchmark.md](benchmark.md).

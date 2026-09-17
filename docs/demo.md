# Demo walkthrough

This walkthrough proves three things independently:

1. the semantic layer can make useful decisions from structured dashboard evidence;
2. the same code can read a real Superset dashboard;
3. an external trigger can push an evaluation without turning the service into a scheduler.

## A. Offline company proof

```bash
uv sync --extra dev
uv run semantic-monitor prove
```

Expected result:

```text
scenario             outcome          recipient              confidence  expected  pass  ms
data_freshness       escalate         data-platform                0.99  escalate  yes
mobile_conversion    notify           growth                       0.94  notify    yes
revenue_decline      notify           revenue-operations           0.92  notify    yes
seasonal_normal      ignore           -                            0.86  ignore    yes
```

Exact confidence values can change when the heuristic is edited; the proof asserts the decision contract and recipient routing.

Generate a report with evidence statements:

```bash
uv run semantic-monitor prove --format markdown --output artifacts/proof.md
```

## B. Real Superset proof

Start the isolated stack:

```bash
docker compose up --build
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

## D. Jev proof

Keep the credential outside the repository:

```bash
TYPESAFE_MODE=jev \
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
uv run semantic-monitor prove --mode jev --format markdown --output artifacts/jev-proof.md
```

The output records the typed outcome, confidence distribution, recipient, rationale, and evidence. It does not replace the engine’s safety gates.

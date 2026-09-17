# SignalWeave demo walkthrough

This walkthrough proves the three boundaries independently:

1. Jev makes typed decisions over owner-authored workflow inputs;
2. the Superset adapter reads real saved dashboard/chart assets; and
3. an external trigger can push an evaluation without SignalWeave becoming a scheduler.

## A. Jev-backed proof

```bash
uv sync --extra dev
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli prove
```

The cases live outside `src/` and are loaded as generic `MonitorWorkflow` plus
`ResourceSnapshot` inputs. The proof demonstrates typed routing, evidence, and
safety behavior; synthetic labels are not a general accuracy claim.

## B. Real Superset proof

Start the isolated, localhost-only stack:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe docker compose up --build
curl http://localhost:18000/healthz
```

The demo uses the local Superset credentials `admin` / `admin` and empty optional
SignalWeave bearer tokens. The compose file binds published ports to loopback;
do not expose this stack to a network or use its credentials outside the demo.

Connect an MCP client to `http://localhost:18000/mcp`. The intended flow is:

```text
list_resources(adapter="superset")
inspect_resource(
  adapter="superset",
  resource="dashboard:7",
  parameters={"chart_ids":["62","64"]}
)
draft_workflow(
  title="Sales pulse",
  intent="Alert when revenue changes materially. Compare related charts before routing.",
  sources=[{
    "key":"sales-dashboard",
    "adapter":"superset",
    "resource":"dashboard:7",
    "label":"Sales dashboard",
    "parameters":{"chart_ids":["62","64"]}
  }],
  recipients=[{
    "key":"revenue-operations",
    "label":"Revenue Operations",
    "destination":"slack://revenue-operations"
  }]
)
evaluate_workflow(workflow_id="workflow-sales-pulse")
```

The adapter reads the dashboard’s saved chart definitions, preserves relationships,
and normalizes time-grained data. A workflow can add another Superset dashboard as
another source ref, or add a future approved SQL/DAG/table adapter without changing
the engine contract.

## C. Push proof

After drafting a workflow, an existing scheduler or alert relay can trigger it:

```bash
curl -X POST http://localhost:18000/webhooks/evaluate \
  -H 'content-type: application/json' \
  -d '{"workflow_id":"workflow-sales-pulse"}'
```

The response is a JSON `Decision`. The caller decides whether and how to deliver
`notify` or `escalate`, including retries and idempotency.

## D. Live unlabeled acceptance check

For a workflow file that points to the local Superset:

```bash
SUPERSET_URL=http://127.0.0.1:8088 \
SUPERSET_USERNAME=admin SUPERSET_PASSWORD=admin \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python scripts/live_workflow_check.py \
  --workflow examples/workflow.json
```

No expected outcome is supplied. The command verifies that the workflow is read,
the source adapter returns live evidence, Jev is the evaluator, and safety gates
produce a typed decision.

## E. Repeatable benchmark

```bash
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark \
  --systems jev --repeats 5 --format markdown \
  --output artifacts/jev-benchmark.md
```

For a configured provider comparison using embeddings plus a general model, see
[`benchmark.md`](benchmark.md).

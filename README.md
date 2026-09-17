# SignalWeave

[![CI](https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml/badge.svg)](https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-2ea44f.svg)](LICENSE)

Typed decisions for push-triggered operational workflows.

SignalWeave is a small open-source MCP and webhook service for teams that already
have operational data, dashboards, queries, jobs, and ownership metadata—but need
to turn that scattered state into a reliable decision:

```text
ignore · investigate · notify · escalate · insufficient_data
```

An operations lead writes what matters in plain language. The workflow names the
approved sources it may inspect. Source adapters fetch bounded, typed snapshots;
TypeSafe [Jev](https://docs.typesafe.ai/introduction) makes narrow semantic
judgments; code owns the safety gates and returns inspectable evidence.

The first production adapter is Apache Superset. The workflow contract is broader
on purpose: one workflow can combine several Superset dashboards, a saved SQL
query, an Airflow DAG status, a table-existence check, or another approved source
adapter as those adapters are installed.

## The problem

Retrieval is not interpretation.

Embedding search and RAG can find a relevant dashboard description or metric card,
but they do not reliably answer the operational question that follows:

- Which of these sources are relevant together for this policy?
- Is a movement material under this owner’s definition, or expected context?
- Is the evidence fresh and comparable enough to act on?
- Which approved team should receive the action?
- What should happen when one source disagrees, disappears, or has no baseline?

Those relationships are where real company workflows become nuanced. Teams often
end up with a human watching dashboards, a large LLM prompt that improvises over
all available context, or a pile of narrow SQL jobs. SignalWeave is the decision
layer between existing assets and the push/action system. It is not a BI tool,
knowledge-management product, scheduler, or general-purpose agent framework.

## The core model

```text
owner-authored workflow
  ├── superset dashboard:7 (selected saved charts)
  ├── superset dashboard:12 (context dashboard)
  ├── sql query:orders_quality
  ├── airflow dag:warehouse_load
  └── table table:warehouse.orders
              │
              ▼
     installed source adapters
              │
              ▼
       typed resource snapshots
       observations + evidence
              │
              ▼
       Jev typed judgments
       plan + action conditions
              │
              ▼
       code-owned safety gates
              │
              ▼
       MCP result or push decision
```

A workflow does not contain provider-specific fields such as `dashboard_id` or
`chart_ids`. It contains named `SourceRef` values:

```json
{
  "key": "sales-dashboard",
  "adapter": "superset",
  "resource": "dashboard:7",
  "label": "Sales dashboard",
  "parameters": {"chart_ids": ["62", "64"]}
}
```

The adapter owns the resource grammar and execution policy. That is how a future
SQL adapter can accept an approved `query:orders_quality` reference without
letting the MCP caller submit arbitrary SQL, and how an Airflow adapter can expose
`dag:warehouse_load` without pretending a DAG is a dashboard.

## Why TypeSafe Jev is the important part

SignalWeave uses TypeSafe as a programmable decision primitive, not as an
autonomous workflow runner. The [System One building guide](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
describes the right division of responsibility: application code owns control
flow and deterministic work while Jev supplies typed common-sense judgments where
ordinary code needs semantic understanding.

For a workflow, SignalWeave asks Jev to:

- select relevant analysis capabilities from a finite registry;
- choose among owner-approved comparison windows;
- evaluate each allowed automatic-action condition independently with `Noul`; and
- choose a recipient only from an explicit allowlist with `Choice`.

The engine then composes those results and applies hard policy in code. Jev does
not generate SQL, invent recipients, execute side effects, or run an open-ended
agent loop. Confidence is a routing signal: low-confidence automatic actions are
downgraded to `investigate`. The [TypeSafe confidence guidance](https://docs.typesafe.ai/confidence)
is explicit that thresholds must be calibrated to the consequences of the target
application.

| Responsibility | Owner |
| --- | --- |
| Saved metric definitions, filters, grouping, and query execution | Source adapter / source system |
| Numeric comparisons, freshness, evidence assembly, and safety gates | SignalWeave code |
| Interpreting owner language and relationships among evidence | Jev |
| Approved outcomes, recipients, permissions, delivery, and side effects | Company policy and caller |

This is the useful distinction from “put the whole dashboard in an LLM prompt”:
the semantic questions are small and typed, while the application contract remains
reviewable, testable, and enforceable.

## Superset first, without making the workflow Superset-shaped

Superset is the first adapter because it is a valuable concrete wedge. It supports:

- cataloging dashboards through the Superset API;
- referencing an entire saved dashboard or a selected set of charts;
- referencing a single saved chart;
- executing the chart’s saved query context or bounded query definition;
- preserving metric definitions, filters, grouping, time grain, and row limits;
- normalizing time-series values into current/baseline/change observations;
- retaining dimensions, freshness, source URLs, chart relationships, and owners; and
- turning chart/API failures into evidence instead of silently treating them as “no change.”

The same workflow can reference two Superset dashboards and compare them. It can
also add other source refs when corresponding adapters are installed. The current
repository ships and integration-tests the Superset adapter; SQL, Airflow, and
table checks are deliberately represented as extension contracts and heterogeneous
engine tests, not falsely advertised as live connectors.

## What a user does

The intended author is an operations lead, analyst, or dashboard owner who knows
what they watch but should not have to build an agent or maintain another SQL job.
Through an MCP client they can:

1. call `list_resources` to discover approved source assets;
2. call `inspect_resource` to see what a source actually exposes;
3. call `draft_workflow` with a plain-language intent, source refs, materiality definition, and approved recipients;
4. review the returned plan; and
5. call `evaluate_workflow` directly or let an existing scheduler/alert relay push the webhook.

Example intent:

```text
When checkout conversion falls, compare the Growth dashboard with the mobile
checkout error query and the deployment DAG. Notify Growth only when the fall is
material, mobile errors corroborate it, and the deployment context does not
explain it. Escalate to Engineering On-call when the data is stale or the
deployment is failing.
```

See [`examples/workflow.json`](examples/workflow.json) for a runnable Superset
workflow shape and [`docs/demo.md`](docs/demo.md) for the local walkthrough.

## MCP and push surface

The MCP surface is intentionally small:

```text
list_resources(adapter?)
inspect_resource(adapter, resource, parameters?)
draft_workflow(title, intent, sources, policy...)
evaluate_workflow(workflow_id)
```

The webhook accepts `{"workflow_id":"..."}` and evaluates the same engine as
the MCP tool. SignalWeave returns the decision and evidence; the caller owns
delivery, retries, idempotency, and side effects. It does not reimplement
Temporal, Airflow, or a durable workflow engine.

## Quick start

Requirements: Python 3.10+, [`uv`](https://docs.astral.sh/uv/), and a TypeSafe API
key. Jev is the production runtime and is intentionally required—there is no
heuristic fallback.

```bash
git clone https://github.com/waddle-zoo/signal-weave.git
cd signal-weave
uv sync --extra dev
export TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe

# Local contract tests (Jev is replaced only by explicit test doubles here).
make verify

# Live Jev proof over external labeled inputs.
uv run python -m evaluations.cli prove
```

Run the isolated Superset stack:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  docker compose up --build
```

Endpoints:

- Superset: <http://localhost:8088> (`admin` / `admin`)
- SignalWeave health: <http://localhost:18000/healthz>
- SignalWeave MCP: <http://localhost:18000/mcp>
- Push evaluation: `POST http://localhost:18000/webhooks/evaluate`

To exercise a live workflow without an expected label:

```bash
SUPERSET_URL=http://127.0.0.1:8088 \
SUPERSET_USERNAME=admin SUPERSET_PASSWORD=admin \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python scripts/live_workflow_check.py \
  --workflow examples/workflow.json
```

The command fails if the workflow references an adapter that is not installed,
which makes the extension boundary explicit rather than silently dropping a
source.

## Evidence and safety

Every decision includes the workflow ID, source keys, compiled plan, normalized
observations, source-provided evidence, source URLs, Jev evaluator, confidence,
and the selected approved recipient when applicable.

After Jev returns, the engine enforces:

- required source failures become `insufficient_data` or `investigate`;
- missing comparable baselines cannot become an automatic no-op;
- stale observations can require escalation;
- unknown recipients are removed; and
- low-confidence automatic actions require investigation.

The source registry resolves each reference independently so one failed SQL/DAG/
table source can be reported alongside healthy Superset evidence. Optional sources
can be marked `required: false`; their failures remain visible to Jev without
automatically blocking the whole workflow.

## Testing and evidence standard

Run the local checks:

```bash
make verify
uv run python -m evaluations.large_scale_trial --domains examples/trial-domains.json --dry-run
```

The large-scale Jev harness is external-input driven and keeps its expected labels
outside `src/`. Its cases intentionally mix Superset, SQL, Airflow, and table-style
source references while using the same production engine. That validates source
composition and safety behavior; it is not a claim that the repository already
ships live connectors for every source kind.

The optional `embedding-reasoning` evaluator embeds the same normalized evidence
and asks a configured general model for JSON. It exists for apples-to-apples
measurement, not as a production fallback. See [`docs/benchmark.md`](docs/benchmark.md)
for latency, cost, false-alert, missed-action, and owner-correction measures.

## Repository map

- `src/semantic_monitor/models.py` — workflow, source, snapshot, evidence, and decision contracts
- `src/semantic_monitor/sources.py` — adapter protocol and source registry
- `src/semantic_monitor/superset_adapter.py` — first-class Superset adapter
- `src/semantic_monitor/superset_client.py` — bounded Superset API client
- `src/semantic_monitor/engine.py` — generic workflow evaluation and safety gates
- `src/semantic_monitor/typesafe_adapter.py` — Jev plan compilation and typed judgment
- `src/semantic_monitor/mcp_server.py` — MCP tools and push webhook
- `evaluations/` — external labeled cases, benchmarks, and trial harnesses; never imported by the service
- `examples/` — user-facing workflow and trial configuration examples
- `docs/` — architecture, source-adapter, demo, benchmark, evaluation, and security notes
- `tests/` — unit tests plus opt-in live Superset integration tests

## Scope and next steps

SignalWeave is intentionally a decision layer. Production deployments should
connect it to company identity, reviewed workflow storage, audit history, a
scheduler, and delivery/idempotency systems. The highest-value next source
adapters are those that expose already-approved, read-only facts—saved SQL query
refs, Airflow/Dagster status, and table/data-quality checks—not an arbitrary code
execution surface.

Feedback and knowledge-graph enrichment can come later. The first product proof is
that people can define nuanced, multi-source push workflows and get fast,
evidence-backed decisions without putting the whole task into one unconstrained
LLM prompt.

## Contributing

SignalWeave is designed to be useful to both humans and coding agents. Read
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the development workflow and
[`AGENTS.md`](AGENTS.md) for the repository invariants that must remain true.

Start with an issue describing the source system, decision contract, or evidence
gap. Keep source facts and side effects in code, keep semantic questions narrow
and typed, and add a representative labeled case or integration test for behavior
changes.

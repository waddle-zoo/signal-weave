# SignalWeave

[![CI](https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml/badge.svg)](https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-2ea44f.svg)](LICENSE)

Turn dashboard semantics into safe, push-based decisions.

SignalWeave is an open-source MCP and webhook layer for teams that already have dashboards, metric definitions, and operational owners—but need a reliable way to decide what a movement means and who should act.

An owner describes a monitoring policy in plain language. SignalWeave reads the existing data asset, computes comparable observations, uses [TypeSafe Jev](https://docs.typesafe.ai/introduction) for narrow typed judgments, and returns an evidence-backed decision:

```text
ignore · investigate · notify · escalate · insufficient_data
```

The first adapter is Apache Superset. The product boundary is the decision layer, not Superset.

## The problem

“Alert when this dashboard looks wrong” is not a SQL threshold.

The useful signal often depends on the relationship between several existing charts, the owner’s definition of materiality, seasonal context, data freshness, and the team that owns the next action. Companies usually handle this with one of three imperfect paths:

1. A person watches dashboards and notices the important changes.
2. A general LLM receives a large dashboard payload and improvises an analysis.
3. A growing collection of SQL jobs encodes narrow cases and becomes difficult to maintain.

SignalWeave is the small layer between those systems:

```text
existing dashboard + owner policy
              ↓
     bounded monitoring plan
              ↓
   saved queries → typed observations
              ↓
        Jev semantic judgment
              ↓
     code-owned safety gates
              ↓
  MCP result or push webhook decision
```

It does not try to replace Superset, Temporal, Airflow, or an agent framework. Scheduling, delivery, permissions, and side effects remain with the company stack.

## Why Jev is the important part

SignalWeave is built around TypeSafe’s [System One programming model](https://docs.typesafe.ai/concepts/how-to-build-with-system-one): code owns the workflow and deterministic work; Jev supplies small units of programmable common sense where ordinary code needs semantic understanding.

For one evaluation, SignalWeave asks Jev to:

- select the analysis capabilities that match the owner’s intent from a finite registry;
- select the best comparison window from the monitor card;
- evaluate each allowed automatic-action condition independently; and
- select only an explicitly approved recipient group.

These are atomic `Noul` condition checks plus a typed `Choice` for the approved recipient—not a request for a long narrative, generated SQL, or an autonomous agent loop. The [TypeSafe documentation](https://docs.typesafe.ai/concepts/how-to-build-with-system-one) describes this as structured, parallel, comparable, fast, and confidence-aware. SignalWeave then composes those outputs in code.

That separation matters:

| Responsibility | Owner |
| --- | --- |
| Metric definitions, filters, grouping, and query execution | Superset / source system |
| Current, baseline, change %, freshness, and evidence | SignalWeave code |
| Interpreting relationships and owner language | Jev |
| Allowed actions, recipients, confidence gates, and side effects | SignalWeave code + company policy |

Confidence is used as a routing signal. A low-confidence automatic `ignore`, `notify`, or `escalate` becomes `investigate`; stale, missing, or incomparable source data cannot silently become a no-op. Each card can set its action threshold, and TypeSafe itself cautions that thresholds must be calibrated to the consequences of the application—this repository treats the four labeled evaluation cases as a starting point, not a universal benchmark. See [TypeSafe confidence guidance](https://docs.typesafe.ai/confidence).

## What a user actually does

The intended user is a dashboard owner, operations lead, or analyst who knows what they watch but does not want to write an agent or maintain another SQL job.

Through an MCP client, an agent, or a small future UI, they:

1. Select an existing dashboard.
2. Describe what matters and what “significant” means.
3. Choose the charts, comparison windows, and approved recipient groups.
4. Review the generated plan before enabling it.
5. Let an existing scheduler or Superset alert relay push evaluations.

Example owner policy:

```text
Notify Growth when checkout conversion materially falls and the movement is
concentrated in mobile. Inspect mobile checkout errors first. Ignore movements
that are explained by normal traffic variation.
```

The owner does not need to specify how every chart should be joined. Jev can identify which registered analysis capabilities are relevant, while the source adapter and code perform the actual calculations.

## What this is—and is not

SignalWeave is:

- a decision layer over existing operational data;
- a way to turn owner intent into a reviewable monitoring card;
- an MCP surface for agents and humans;
- a push endpoint for existing schedulers and alert relays; and
- a place to add labels and feedback later without making the first version a knowledge-management product.

SignalWeave is not:

- a BI tool or dashboard replacement;
- a workflow scheduler or durable execution engine;
- a general-purpose agent builder;
- a vector database or company search product; or
- permission to invent recipients, SQL, or side effects.

## Quick start

Requirements: Python 3.10+, [`uv`](https://docs.astral.sh/uv/), and a TypeSafe API key. Jev is the product runtime and is intentionally required by the default commands.

```bash
git clone https://github.com/waddle-zoo/signal-weave.git
cd signal-weave
uv sync --extra dev

# Keep the key outside the repository.
export TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe

# Run the Jev-backed evaluation over labeled cases (outside the service package).
uv run python -m evaluations.cli prove

# Run lint and unit tests.
make verify
```

The unit suite uses explicit test doubles so CI does not spend API credits. It does not pretend those tests are a Jev quality evaluation. Run the evaluation command above for a live Jev proof; run the live Superset check below for an unlabeled external-source proof.

## Run the isolated Superset demo

The Compose stack starts a disposable Superset, Postgres, Redis, and SignalWeave service. It does not touch the separate Folio environment.

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  docker compose up --build
```

Compose reads that host path and mounts it read-only inside the monitor container; do not copy the key into the repository.

Endpoints:

- Superset: <http://localhost:8088> (`admin` / `admin`)
- SignalWeave health: <http://localhost:18000/healthz>
- SignalWeave MCP: <http://localhost:18000/mcp>
- Push evaluation: `POST http://localhost:18000/webhooks/evaluate`

The monitor container runs Jev by default. The key is mounted read-only at runtime and is not copied into the image. For a deployment, set `SIGNALWEAVE_API_TOKEN` to protect MCP and webhook traffic; `/healthz` remains available to orchestration.

An MCP client can connect to:

```json
{
  "mcpServers": {
    "signal-weave": {
      "url": "http://localhost:18000/mcp"
    }
  }
}
```

The core tool flow is:

```text
list_dashboards()
  → inspect_dashboard(dashboard_id)
  → draft_monitor(dashboard_id, intent, charts, thresholds, recipients)
  → review the returned plan
  → evaluate_monitor(monitor_id)
```

An existing scheduler can trigger the same evaluation without an agent:

```bash
curl -X POST http://localhost:18000/webhooks/evaluate \
  -H 'content-type: application/json' \
  -d '{"monitor_id":"draft-7-sales-pulse"}'
```

The caller owns delivery, retries, idempotency, and side effects. SignalWeave returns the decision and its evidence.

## Evidence, not just an answer

Every decision includes:

- the monitor and dashboard IDs;
- the selected plan and evaluator;
- normalized observations with current and baseline values;
- change percentages, dimensions, and freshness;
- source URLs for the underlying chart data;
- Jev condition support and confidence when Jev supplies the judgment; and
- the selected approved recipient, if any.

The engine applies safety gates after Jev:

- source errors become `insufficient_data` or `investigate`;
- missing comparable baselines cannot become an automatic `ignore`;
- stale data can require escalation;
- unknown recipients are removed; and
- low-confidence automatic actions require investigation.

This is the part a broad LLM prompt usually leaves implicit: the decision contract is inspectable and executable.

## Benchmarking Jev against a general-model pipeline

The repository contains a reproducible harness over the same normalized dashboard cards:

```bash
# Live Jev run; repeat to inspect stability and p95 latency.
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark --systems jev --repeats 5 \
  --format markdown --output artifacts/jev-benchmark.md
```

Current local Jev proof: 20 evaluations across five repeats, 100% exact outcome-plus-recipient accuracy, 701.62 ms median, 914.17 ms p95, 40 API requests, and 0 provider errors. This is four labeled synthetic cases—not a universal model claim—and is recorded with the benchmark protocol in [`docs/benchmark.md`](docs/benchmark.md).

The larger live trial covered 72 generated cases across 12 company domains and six failure/action classes, repeated twice: 144 exact decisions, 100% exact outcome-plus-recipient accuracy, 0 wrong automatic actions, 0 false urgent actions, 0 provider errors, and 72/72 repeat-stable cases. See [`docs/large-scale-trial.md`](docs/large-scale-trial.md) for the methodology and its limits.

The optional `embedding-reasoning` lane is a real OpenAI-compatible adapter. It embeds the same observations, retrieves the top cards, then asks a general model for structured JSON. Run it against the provider/model you actually want to compare—“Luna” is not a TypeSafe model documented by this repository, so no Luna result is claimed without a configured endpoint:

```bash
BASELINE_BASE_URL=https://your-provider.example/v1 \
BASELINE_API_KEY=... \
BASELINE_MODEL=luna \
BASELINE_EMBEDDING_MODEL=your-embedding-model \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark \
  --systems jev,embedding-reasoning --repeats 5 \
  --format markdown --output artifacts/jev-vs-luna.md
```

The benchmark reports exact decision accuracy, outcome accuracy, median/p95 latency, request count, token usage when the provider reports it, and provider errors. The labels live under [`evaluations/data/demo-cases.json`](evaluations/data/demo-cases.json), outside the runtime package. Four synthetic cases can prove wiring and failure behavior; they cannot prove that Jev is universally better. A meaningful enterprise comparison needs a labeled export of real dashboard events and should measure false alerts, missed actions, investigation rate, owner corrections, latency, and cost.

To exercise a real Superset dashboard with an owner-supplied card and no expected outcome baked into the check:

```bash
SUPERSET_URL=http://127.0.0.1:8088 \
SUPERSET_USERNAME=admin SUPERSET_PASSWORD=admin \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python scripts/live_superset_check.py \
  --monitor-card examples/monitor-card.json
```

This command succeeds only when the card is read from Superset, Jev is the evaluator, and the resulting decision contains evidence. It does not grade the answer against a demo label.

See [`docs/benchmark.md`](docs/benchmark.md) for the protocol and interpretation, and [`docs/evaluation.md`](docs/evaluation.md) for the broader evidence standard.

## Repository map

- `src/semantic_monitor/` — source adapter, typed models, Jev integration, engine, MCP, and webhook
- `evaluations/` — labeled evaluation cases, benchmarks, and large-scale trial harnesses; never imported by the service
- `examples/monitor-card.json` — a monitor-card shape to copy and adapt
- `scripts/live_superset_check.py` — unlabeled acceptance check against an external Superset dashboard
- `docs/architecture.md` — component boundary and lifecycle
- `docs/demo.md` — local Superset walkthrough
- `docs/benchmark.md` — benchmark protocol and interpretation
- `docs/large-scale-trial.md` — live large-scale Jev trial and enterprise evidence
- `docs/security.md` — credentials, source permissions, and deployment boundary
- `tests/` — unit and integration tests; Superset integration is opt-in

## Current status and next steps

This is an early self-hosted proof/product boundary. The valuable next work is not another agent loop; it is operating this against real dashboard histories:

1. import real owner policies and monitor-card versions;
2. capture decisions and owner corrections;
3. calibrate confidence and materiality by consequence;
4. add durable audit/idempotency/delivery adapters; and
5. use feedback to improve the knowledge layer and cross-dashboard context.

The current JSON card store is intentionally small. Replace it with the company’s identity, database, review, audit, and delivery systems before enabling automatic actions in production.

## Contributing

Small, focused contributions are welcome. Start with an issue describing the source system, decision contract, or evidence gap. Keep source facts and side effects in code, keep semantic questions narrow and typed, and add a representative labeled case or integration test for behavior changes.

```bash
uv sync --extra dev
make verify
```

## License

MIT. See [LICENSE](LICENSE).

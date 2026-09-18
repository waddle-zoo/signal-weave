<p align="center">
  <img src="assets/signalweave-logo.svg" alt="SignalWeave" width="430">
</p>

<p align="center">
  <strong>Typed decisions for the signals your company already has.</strong><br>
  Turn dashboards, queries, jobs, and source context into evidence-backed results.
</p>

<p align="center">
  <a href="https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml"><img src="https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2ea44f.svg" alt="Apache 2.0 license"></a>
</p>

Most companies already know what they want to watch. The hard part is turning
that guidance into a repeatable answer when several sparse signals, relationships,
and ownership rules matter at once.

SignalWeave is a small open-source MCP and webhook service for that seam. A
person writes a free-form insight card, source adapters return bounded evidence,
[TypeSafe Jev](https://docs.typesafe.ai/introduction) makes narrow typed
judgments, and your existing agent, scheduler, or delivery system decides what
to do next.

<p align="center">
  <img src="assets/decision-flow.svg" alt="SignalWeave turns an insight card and source evidence into Jev judgments, safety gates, and an existing push or agent action" width="900">
</p>

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and a TypeSafe API
key.

```bash
git clone https://github.com/waddle-zoo/signal-weave.git
cd signal-weave
uv sync --extra dev
export TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe
make verify
```

Run the localhost Superset demo:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  docker compose up --build
```

Superset is available at <http://localhost:8088>. SignalWeave serves MCP at
<http://localhost:18000/mcp>, health at <http://localhost:18000/healthz>, and
push evaluation at `POST /webhooks/evaluate`. The demo credentials are
`admin` / `admin`; ports are loopback-only and must not be exposed.

To run the included card against live local Superset:

```bash
SUPERSET_URL=http://127.0.0.1:8088 \
SUPERSET_USERNAME=admin SUPERSET_PASSWORD=admin \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python scripts/live_card_check.py \
  --card examples/insight-card.json
```

## The card

The user-facing contract is intentionally generic:

```json
{
  "title": "Sales pulse",
  "what_to_watch": "Revenue and related dashboard signals.",
  "why_watch": "Help Revenue Operations distinguish expected movement from a business issue.",
  "watch_for": [
    "Revenue changes materially.",
    "A related chart corroborates the movement."
  ],
  "questions": [
    "Is this outside expected seasonal behavior?",
    "Does this warrant a Revenue Operations response?"
  ],
  "sources": [
    {
      "key": "sales-dashboard",
      "adapter": "superset",
      "resource": "dashboard:7",
      "label": "Sales dashboard",
      "parameters": {"chart_ids": ["62", "64"]}
    }
  ],
  "delivery_methods": [
    {
      "key": "revenue-operations",
      "outcome": "notify",
      "label": "Revenue Operations",
      "destination": "slack://revenue-operations",
      "instructions": "Notify when the evidence supports a non-urgent response."
    }
  ]
}
```

In plain language:

- `what_to_watch` says what the card is about;
- `why_watch` says which decision it should support;
- `watch_for` optionally names conditions to surface one by one;
- `questions` optionally names questions the evidence should answer; and
- `delivery_methods` maps outcomes to caller-owned destinations.

The result gives you the chosen `outcome`, configured delivery methods,
per-item `watch_results`, per-question `question_results`, every normalized
observation, source evidence, confidence, and provenance. If the card names 100
things to watch, Jev receives all 100 observations; changed rows are only placed
first for client rendering.

## MCP flow

An existing UI or agent can guide onboarding without SignalWeave owning the UI:

```text
discover_insight_sources(goal, adapter?, limit?)
propose_insight_card(what_to_watch, why_watch, watch_for?, questions?, ...)
simulate_insight_card(card_id)
approve_insight_card(card_id)
evaluate_insight_card(card_id)
```

Or, when source refs are already known:

```text
draft_insight_card(title, what_to_watch, why_watch, sources, ...)
```

The proposal path uses Jev to rank a bounded source catalog, stores a draft, and
returns setup questions. Preview is delivery-disabled. Approval is explicit.
After approval, an existing scheduler or alert relay posts:

```json
{"card_id": "card-sales-pulse"}
```

The caller owns delivery, retries, idempotency, and side effects.

## Plain-language metric queries

For data-lake questions, use a metric query card over an approved Trino catalog:

```text
propose_metric_query_card(question, why, selected_sources, dimensions?, time_grain?)
compile_metric_query_card(card_id, window_start, window_end)
approve_metric_query_card(card_id, actor?)
```

Jev selects among catalog-owned metric definitions. SignalWeave then compiles a
typed plan into deterministic `SELECT` SQL with approved relations, columns,
aggregations, dimensions, and a required partition/time bound. It never accepts
raw SQL from the MCP caller and never asks Jev to generate executable SQL. The
included Trino adapter can execute only those compiled queries and returns bounded,
normalized observations.

## Why Jev instead of one large prompt?

Embeddings and RAG can retrieve a relevant dashboard, definition, owner, or
document. They do not by themselves provide a stable boundary for deciding when
several signals belong together, when context explains a movement, or when the
evidence is unsafe to act on.

SignalWeave uses Jev as a programmable decision primitive, not an autonomous
agent. Jev selects from a finite capability vocabulary and evaluates the card's
watch items, questions, and outcome conditions with typed probabilities. Code
keeps ownership of baselines, freshness, allowlists, confidence routing, and
side effects. Destinations never come from model output.

That combination gives a person natural-language flexibility without turning the
whole source state and action policy into one untestable response. It also means
an existing agent can enrich the state with approved knowledge-graph context or
human feedback later without SignalWeave owning the graph or the agent loop.

## First integration, broader contract

The included adapter is Apache Superset and preserves dashboard/chart metadata,
relationships, saved definitions, dimensions, bounded series, baselines, and
source URLs. The card itself is not Superset-shaped: one card can combine several
Superset dashboards with approved SQL, Airflow, table-quality, or other read-only
source adapters.

SignalWeave is not a replacement for Temporal, Airflow, Dagster, a BI tool,
Glean, a knowledge graph, or a general-purpose agent framework. It is the typed
decision layer between those systems.

## Evidence and limits

The repository includes reproducible synthetic trials, not a substitute for a
customer's historical holdout. The controlled Jev decision matrix covered 3
companies, 22 personas, 1,664 heterogeneous resources, and 144 tasks: Jev made
134/144 exact outcome decisions, with all ten misses conservative
`notify` → `investigate` routes. That runner supplied hidden source refs, so its
source-selection result is not a discovery score.

The independent live discovery trial used 48 tasks, 576 resources before tenant
filtering, same-name cross-tenant decoys, and two-source labels that were not sent
to Jev. It achieved 48/48 exact top-2 sets, 48/48 top-10 coverage, and 0 wrong-
tenant returns with an explicit tenant boundary. The live metric-plan trial used
24 held-out metric labels and achieved 24/24 correct definitions, dimensions, and
time grains; all 24 compiled queries were bounded, `SELECT`-only, and semicolon-
free. These are synthetic regression measurements, not universal accuracy or
production safety claims.

The MCP enterprise trial also exposed the limits: malformed client calls and
unscoped catalogs caused source-discovery failures. Keep tenant identity, metric
definition, population, grain, freshness, lineage, and source status in adapter
metadata, and run a domain-owner-labeled, time-split shadow trial before enabling
automated actions.

See [`docs/evidence-brief.md`](docs/evidence-brief.md) for the measured case and
limitations.

To reproduce the narrower daily-monitor contract—no-change suppression,
contextual notification, complete evidence, and idempotent scheduler retry—run
`make daily-trial`. The trial uses live Jev through the real MCP and webhook
surfaces over a rotating Superset-shaped fixture. It is an integration proof,
not a universal accuracy claim.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — contracts, pipeline, and boundaries
- [`docs/demo.md`](docs/demo.md) — local setup and onboarding walkthrough
- [`docs/source-adapters.md`](docs/source-adapters.md) — adapter contract and security boundary
- [`docs/metric-query-cards.md`](docs/metric-query-cards.md) — approved catalogs, Trino plans, and SQL bounds
- [`docs/benchmark.md`](docs/benchmark.md) — comparison methodology
- [`docs/evidence-brief.md`](docs/evidence-brief.md) — measured product case
- [`docs/enterprise-experiment.md`](docs/enterprise-experiment.md) — MCP-only enterprise readiness experiment
- [`docs/enterprise-closure.md`](docs/enterprise-closure.md) — current proof boundary and next gate
- [`docs/postfix-agent-trial.md`](docs/postfix-agent-trial.md) — live post-fix Luna agent trial
- [`docs/security.md`](docs/security.md) — credentials and deployment notes
- [`ROADMAP.md`](ROADMAP.md) — future work tracker
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup and pull-request guidance
- [`AGENTS.md`](AGENTS.md) — guidance for coding agents

## License

SignalWeave is available under the [Apache 2.0 license](LICENSE).

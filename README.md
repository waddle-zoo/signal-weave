# Superset Semantic Monitor MCP

An open-source decision layer for teams that already use Apache Superset and want reliable insight workflows on top of their existing dashboards.

Dashboard owners describe what matters in plain language. The service turns that intent into a bounded monitoring plan, reads the saved Superset chart definitions, computes comparable observations, and returns an evidence-backed action:

`ignore` · `investigate` · `notify` · `escalate` · `insufficient_data`

It is deliberately not a new agent builder, workflow engine, BI product, or RAG system. Superset and ordinary code calculate facts. TypeSafe is an optional semantic judgment layer for the parts that thresholds and SQL do not express well: whether a movement is meaningful in context, which outcome is appropriate, and whether the evidence is strong enough to act.

## Why this exists

Most companies already have dashboards, metric definitions, owners, and chat groups. The missing layer is the operational meaning between “a number moved” and “someone should do something.”

This project makes that layer explicit:

```text
Superset dashboard + owner intent
        ↓
bounded monitoring plan
        ↓
saved chart queries + deterministic observations
        ↓
TypeSafe judgment or deterministic heuristic
        ↓
evidence-backed push decision
```

The result is cheaper and easier to audit than asking a general LLM to inspect an entire dashboard on every run, while remaining more expressive than fixed threshold SQL alone.

## Five-minute proof

Requirements: Python 3.10+ and `uv`.

```bash
uv sync --extra dev
uv run semantic-monitor prove
uv run pytest
```

The proof runs four representative company situations through the same engine used by MCP and the webhook:

| Situation | Expected decision | Why it matters |
| --- | --- | --- |
| Revenue declines while enterprise churn spikes | `notify` Revenue Operations | Correlated business context beats a blind threshold |
| Retail sales dip with a stable seasonal signal | `ignore` | Avoids alerting on expected variation |
| Mobile conversion falls while mobile errors spike | `notify` Growth | Related dashboard signals explain the movement |
| Warehouse load is stale | `escalate` Data Platform | Freshness gates prevent acting on untrusted data |

To save an inspectable report:

```bash
uv run semantic-monitor prove --format markdown --output artifacts/proof.md
```

## Run against local Superset

The Docker stack starts Superset 6.1 with Postgres metadata, Redis, example datasets, and this MCP service. It leaves the existing Folio environment alone and uses port `18000` for the monitor by default.

```bash
docker compose up --build
```

- Superset: <http://localhost:8088> (`admin` / `admin`)
- MCP: <http://localhost:18000/mcp>
- Health: <http://localhost:18000/healthz>
- Push evaluation: `POST http://localhost:18000/webhooks/evaluate`

The container defaults to `MONITOR_SOURCE=superset`. The MCP loop is:

1. `list_dashboards` discovers existing Superset dashboards.
2. `inspect_dashboard` returns chart metadata and normalized observations.
3. `draft_monitor` stores an owner’s intent and compiles a reviewable plan.
4. `evaluate_monitor` executes only the monitor’s selected saved charts.
5. A scheduler, Superset webhook relay, or agent can call `/webhooks/evaluate` to push a decision.

Example push payload:

```json
{"monitor_id":"draft-7-sales-pulse"}
```

Set `PUSH_WEBHOOK_TOKEN` to require `Authorization: Bearer ...` on that endpoint.

## Use TypeSafe when it helps

The offline heuristic is the default for local development and deterministic tests. Jev is enabled explicitly and reads the key only at runtime:

```bash
TYPESAFE_MODE=jev \
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
uv run semantic-monitor prove --format markdown --output artifacts/jev-proof.md
```

The code asks narrow typed questions rather than requesting a narrative answer:

- Which bounded analysis operations does this owner intent require?
- Which allowed outcome best fits the observed evidence?
- How material is the movement?
- Which explicitly approved recipient, if any, should receive it?

Confidence is treated as a routing signal, not proof of truth. Low-confidence automatic actions are downgraded to `investigate`; stale or incomparable data cannot silently become `ignore`.

## Project map

- `src/semantic_monitor/models.py` — typed cards, observations, plans, evidence, and decisions
- `src/semantic_monitor/superset_client.py` — read-only Superset API adapter and chart normalization
- `src/semantic_monitor/compiler.py` — bounded intent-to-operation compilation
- `src/semantic_monitor/typesafe_adapter.py` — heuristic and Jev judgment implementations
- `src/semantic_monitor/engine.py` — evaluation pipeline and safety gates
- `src/semantic_monitor/mcp_server.py` — MCP tools, catalog resource, health, and push route
- `src/semantic_monitor/scenarios.py` — deterministic company proof cases
- `src/semantic_monitor/proof.py` — reproducible proof harness and report renderer
- `docs/` — architecture, demo walkthrough, and evaluation criteria
- `examples/` — safe monitor-card and webhook payload examples

## Boundaries and current limitations

This project intentionally leaves several responsibilities to the surrounding company stack:

- Superset remains the source of metrics and dashboard definitions.
- Airflow, Temporal, cron, Superset alerts, or an existing agent remain responsible for scheduling and delivery.
- Recipient groups are explicit card inputs; the service does not invent people or send chat messages.
- Charts without a saved query context or a comparable baseline return evidence plus `investigate`/`insufficient_data` rather than guessing.
- Monitor cards are stored locally in JSON for the proof. Production deployments should put them behind the company’s normal database, identity, review, and audit controls.

Read [docs/architecture.md](docs/architecture.md), then follow [docs/demo.md](docs/demo.md) for the full local walkthrough. The evidence standard is documented in [docs/evaluation.md](docs/evaluation.md).

<p align="center">
  <img src="assets/signalweave-logo.svg" alt="SignalWeave" width="430">
</p>

<p align="center">
  <strong>Typed decisions for operational signals.</strong><br>
  Turn the systems your company already uses into explainable push decisions.
</p>

<p align="center">
  <a href="https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml"><img src="https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2ea44f.svg" alt="Apache 2.0 license"></a>
</p>

Turn the dashboards, queries, jobs, and ownership metadata your team already has
into reviewed, evidence-backed push decisions. When a signal moves, SignalWeave
checks whether it matters, looks at the related context, and returns an inspectable
action for an existing agent, scheduler, or delivery system.

SignalWeave is a small open-source MCP and webhook service: a person describes
what matters in plain language, configured adapters provide bounded evidence, and
[TypeSafe Jev](https://docs.typesafe.ai/introduction) supplies narrow typed
judgments. It does not become your BI tool, workflow engine, or agent runtime.

<p align="center">
  <img src="assets/decision-flow.svg" alt="SignalWeave turns approved source signals into bounded evidence, a TypeSafe Jev judgment, code-owned safety gates, and an existing push or agent action" width="900">
</p>

## Try it

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and a TypeSafe API
key. Jev is the production decision path; there is no implicit heuristic fallback.

```bash
git clone https://github.com/waddle-zoo/signal-weave.git
cd signal-weave
uv sync --extra dev
export TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe

make verify
```

Run the local Superset-backed demo stack:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  docker compose up --build
```

This is a localhost-only development stack. It uses `admin` / `admin` for the
local Superset instance and leaves optional bearer tokens empty; do not expose it
to a network. The published ports are bound to `127.0.0.1` by default.

Open Superset at <http://localhost:8088>. SignalWeave serves health at
<http://localhost:18000/healthz>, MCP at
<http://localhost:18000/mcp>, and push evaluation at
`POST http://localhost:18000/webhooks/evaluate`.

To run the first live decision over the included workflow:

```bash
SUPERSET_URL=http://127.0.0.1:8088 \
SUPERSET_USERNAME=admin SUPERSET_PASSWORD=admin \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python scripts/live_workflow_check.py \
  --workflow examples/workflow.json
```

See [`docs/evidence-brief.md`](docs/evidence-brief.md) for the measured case for
trying it, and [`docs/demo.md`](docs/demo.md) for the complete walkthrough and
[`examples/workflow.json`](examples/workflow.json) for the workflow input.

## What it does

SignalWeave sits between company systems and the system that already delivers or
acts on alerts. It does not replace a scheduler, BI tool, durable workflow engine,
knowledge graph, or general-purpose agent framework. Source and recipient
allowlisting is deployment configuration; identity-aware authorization remains
deployment-owned.

- **Define:** an operations lead or analyst names the configured sources, intent,
  materiality, outcomes, and recipients.
- **Understand:** adapters normalize source state into typed observations and
  evidence. Workflows can compose multiple sources.
- **Decide:** Jev answers bounded semantic questions over that evidence, such as
  whether a movement is material, which comparison applies, or whether context
  corroborates it.
- **Enforce:** application code owns freshness, baselines, permissions, allowed
  recipients, confidence routing, and side effects.
- **Push:** the caller receives a decision such as `ignore`, `investigate`,
  `notify`, `escalate`, or `insufficient_data`.

The MCP surface is intentionally small:

```text
list_resources(adapter?)
inspect_resource(adapter, resource, parameters?)
discover_monitor_inputs(goal, adapter?, limit?)
propose_monitor_card(goal, selected_sources?, recipients?, ...)
simulate_monitor_card(workflow_id)
approve_monitor_card(workflow_id)
list_monitor_cards(status?)
get_monitor_card(workflow_id)
draft_workflow(title, intent, sources, policy...)
evaluate_workflow(workflow_id)
```

The monitor-card tools let an existing agent guide a person from a plain-language
goal to Jev-ranked source candidates, a draft card, a no-delivery preview, and an
explicit approval. The older `draft_workflow` tool remains the lower-level escape
hatch for callers that already have a complete workflow contract.

Approved cards are stored as typed JSON contracts. A customer-owned UI, agent,
scheduler, or webhook relay can list or retrieve them later without adopting a
SignalWeave runtime or delivery system.

The first included adapter is Apache Superset. The workflow contract stays
source-oriented so an installation can add configured SQL, Airflow, data-quality,
or other operational adapters without making the service Superset-shaped.

The [evidence brief](docs/evidence-brief.md) reports a small live comparison:
on four synthetic labeled situations, an earlier recorded Jev run was exact on
20/20 decisions while two current OpenAI baseline runs were exact on 15/20 and
16/20. That is a reason to run the harness on your own history, not a universal
accuracy claim.

## Why Jev

The hard part is not retrieving a metric. It is deciding whether several pieces of
evidence belong together, whether a change matters under an owner’s definition,
whether the data is safe to act on, and who is allowed to receive the result.

SignalWeave uses TypeSafe as a programmable decision primitive rather than an
autonomous agent runner. Jev handles the semantic parts that are difficult to
encode as ordinary rules; code handles the parts that must be deterministic and
reviewable. Independent predicates use typed judgments, bounded choices use
allowlisted options, and low confidence routes to investigation instead of
silently authorizing an automatic action.

That boundary keeps the useful flexibility of natural language without putting an
entire dashboard, workflow, or side-effect policy into one unconstrained prompt.
Normalized evidence is sent to the configured TypeSafe service during Jev
evaluation; review [`docs/security.md`](docs/security.md) and your organization’s
data policy before using live company data.
Read the [TypeSafe System One building guide](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
and [confidence guidance](https://docs.typesafe.ai/confidence) for the design
principles behind this approach.

## The problem

Most companies do not lack data. They lack a dependable translation from “this
changed” to “this matters, this is why, and this is what should happen next.”

Embedding search and RAG can retrieve a relevant dashboard, definition, or owner.
They do not by themselves provide a stable decision contract across related
sources, changing context, missing baselines, stale data, conflicting signals, and
approved actions. The common alternatives are a human watching dashboards, a large
LLM prompt that improvises over all available context, or a growing collection of
narrow jobs. SignalWeave is the small typed layer for the decision between those
systems.

## Evidence and safety

The MCP evaluation response includes the workflow, fetched resources, compiled
plan, and typed decision. The webhook returns the typed decision, including the
workflow ID, source keys, normalized observations, source evidence and URLs, Jev
evaluator, confidence, and the selected configured recipient when applicable.

Required source failures, stale observations, missing baselines, unknown
recipients, and low-confidence automatic actions are handled by code-owned gates
where the source adapter provides the required state.
The source registry resolves references independently, so one failed source can be
reported alongside healthy evidence. The caller owns delivery, retries,
idempotency, and side effects.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — runtime boundaries and data flow
- [`docs/demo.md`](docs/demo.md) — local setup and walkthrough
- [`docs/source-adapters.md`](docs/source-adapters.md) — adapter contract and security boundary
- [`docs/benchmark.md`](docs/benchmark.md) — evaluation methodology and comparison measures
- [`docs/evidence-brief.md`](docs/evidence-brief.md) — concise product case and measured comparison
- [`docs/security.md`](docs/security.md) — credentials, evidence, and deployment notes
- [`SECURITY.md`](SECURITY.md) — vulnerability reporting and release posture
- [`ROADMAP.md`](ROADMAP.md) — current focus and future work
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, testing, and pull requests
- [`AGENTS.md`](AGENTS.md) — guidance for coding agents

## License

SignalWeave is available under the [Apache 2.0 license](LICENSE).

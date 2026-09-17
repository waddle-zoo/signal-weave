<p align="center">
  <img src="assets/signalweave-logo.svg" alt="SignalWeave" width="430">
</p>

<p align="center">
  <strong>Typed decisions for operational signals.</strong><br>
  Turn the systems your company already uses into fast, explainable push decisions.
</p>

<p align="center">
  <a href="https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml"><img src="https://github.com/waddle-zoo/signal-weave/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-2ea44f.svg" alt="Apache 2.0 license"></a>
</p>

SignalWeave is a small open-source MCP and webhook service for teams that need to
turn existing dashboards, queries, jobs, and ownership metadata into reliable
actions. A person describes what matters in plain language; approved source
adapters provide bounded evidence; [TypeSafe Jev](https://docs.typesafe.ai/introduction)
supplies narrow typed judgments; SignalWeave returns an inspectable decision.

<p align="center">
  <img src="assets/decision-flow.svg" alt="SignalWeave turns approved source signals into bounded evidence, a TypeSafe Jev judgment, code-owned safety gates, and an existing push or agent action" width="900">
</p>

## Try it

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), and a TypeSafe API
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

Then open Superset at <http://localhost:8088> (`admin` / `admin`). SignalWeave
serves health at <http://localhost:18000/healthz>, MCP at
<http://localhost:18000/mcp>, and push evaluation at
`POST http://localhost:18000/webhooks/evaluate`.

See [`docs/demo.md`](docs/demo.md) for the complete walkthrough and
[`examples/workflow.json`](examples/workflow.json) for a runnable workflow.

## What it does

SignalWeave sits between company systems and the system that already delivers or
acts on alerts. It does not replace a scheduler, BI tool, durable workflow engine,
knowledge graph, or general-purpose agent framework.

- **Define:** an operations lead or analyst names the approved sources, intent,
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
draft_workflow(title, intent, sources, policy...)
evaluate_workflow(workflow_id)
```

The first included adapter is Apache Superset. The workflow contract stays
source-oriented so an installation can add approved SQL, Airflow, data-quality,
or other operational adapters without making the service Superset-shaped.

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

Every decision includes the workflow ID, source references, compiled plan,
normalized observations, source evidence and URLs, Jev evaluator, confidence, and
the selected approved recipient when applicable.

Required source failures, stale observations, missing baselines, unknown
recipients, and low-confidence automatic actions are handled by code-owned gates.
The source registry resolves references independently, so one failed source can be
reported alongside healthy evidence. The caller owns delivery, retries,
idempotency, and side effects.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — runtime boundaries and data flow
- [`docs/demo.md`](docs/demo.md) — local setup and walkthrough
- [`docs/source-adapters.md`](docs/source-adapters.md) — adapter contract and security boundary
- [`docs/benchmark.md`](docs/benchmark.md) — evaluation methodology and comparison measures
- [`docs/security.md`](docs/security.md) — credentials, evidence, and deployment notes
- [`ROADMAP.md`](ROADMAP.md) — current focus and future work
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, testing, and pull requests
- [`AGENTS.md`](AGENTS.md) — guidance for coding agents

## License

SignalWeave is available under the [Apache 2.0 license](LICENSE).

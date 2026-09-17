# Contributing to SignalWeave

Thanks for helping build a small, dependable decision layer for operational
systems. Contributions are welcome when they make the core contract more useful,
more inspectable, or easier to operate.

## Before you start

Please read:

- [`README.md`](README.md) for the product boundary and quick start.
- [`AGENTS.md`](AGENTS.md) for repository invariants that apply to humans and coding agents.
- [`docs/architecture.md`](docs/architecture.md) for the runtime model.
- [`docs/security.md`](docs/security.md) before adding a connector or handling credentials.

Open an issue first for a substantial change. Include the problem, the source
system or workflow shape involved, the decision contract you expect, and how the
behavior will be evaluated. Small fixes and documentation improvements can go
straight to a pull request.

## Development setup

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), and Docker only for
the local Superset stack.

```bash
uv sync --extra dev
make verify
```

The default test suite is local and deterministic. It does not call external
TypeSafe services. Live Jev and Superset checks are opt-in and require credentials;
never commit API keys, tokens, copied production data, or generated secrets.

For the live integration path, copy `.env.example`, set the required variables,
and run the commands documented in [`docs/demo.md`](docs/demo.md). A pull request
should explain any live-only behavior it relies on and include a local test double
or fixture for the contract it changes.

## What belongs where

- `src/semantic_monitor/` contains production runtime code only.
- `tests/` contains unit and integration tests for production contracts.
- `evaluations/` contains labeled evaluation harnesses and benchmarks. It must not
  be imported by the service.
- `examples/` contains user-facing workflow examples and sample inputs.
- `docs/` contains architecture, operations, security, and evaluation guidance.

The first-class integration is Superset, but workflows must not be hard-coded to
one dashboard, metric, company, or test scenario. New source adapters should
implement the bounded adapter contract in [`docs/source-adapters.md`](docs/source-adapters.md),
expose approved references rather than arbitrary execution, and report failures as
evidence.

## Pull requests

Keep pull requests focused and explain the user-visible outcome. Include:

1. a short problem statement and design note for non-trivial changes;
2. tests for normal, missing, stale, conflicting, and permission-relevant inputs
   when those cases apply;
3. documentation or examples when the public contract changes; and
4. benchmark or evaluation evidence when latency, accuracy, cost, or safety is
   part of the claim.

Before opening a pull request, run:

```bash
make verify
git diff --check
```

Keep commits reviewable. Do not force-push shared branches. Maintainers may ask
for a focused follow-up rather than merging unrelated cleanup into a feature.

## Design principles

SignalWeave uses Jev for narrow semantic judgments. Application code owns source
execution, deterministic calculations, policy gates, permissions, retries, and
side effects. Do not replace a missing contract with a prompt that returns free
form instructions, invent recipients, or silently fall back to a heuristic.

The project is not a replacement for Temporal, Airflow, a BI system, a knowledge
graph, or a general-purpose agent framework. Prefer a small extension point over a
new orchestration layer.

## Reporting security issues

Do not post credentials, private source data, or an exploitable vulnerability in a
public issue. Contact the repository maintainers privately with reproduction
details and the minimum information needed to investigate.


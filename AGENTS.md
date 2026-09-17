# Instructions for coding agents

This file is repository guidance for automated and human-assisted coding agents.
It supplements the user request and the project documentation; it does not grant
permission to perform external or destructive actions.

## Read first

Before changing code, read [`README.md`](README.md), the relevant file in `docs/`,
and the tests covering the contract you are changing. For TypeSafe behavior, also
follow the current TypeSafe skill and official documentation. Do not modify the
sibling `folio-lattice` repository as part of work in this repository.

## Repository invariants

- Jev is the production semantic decision path. There is no implicit heuristic
  fallback in production.
- `src/` contains reusable production code, not demos, trial scenarios, benchmark
  labels, company names, hard-coded dashboard IDs, or test-only metrics.
- `evaluations/` and `examples/` stay outside the service import path.
- Workflows are source-adapter driven and may combine multiple approved sources,
  while Superset remains the first-class shipped integration.
- Source adapters fetch bounded, typed evidence and never accept arbitrary code or
  unrestricted queries from an MCP caller.
- Jev supplies narrow typed judgments. Code owns control flow, numeric and
  freshness checks, permissions, safety gates, retries, idempotency, and side
  effects.
- Recipients, actions, source references, and operation types are always bounded by
  an explicit workflow or adapter allowlist. Never let a model invent them.
- Confidence is a routing signal, not proof. A low-confidence automatic action must
  be downgraded or escalated according to code-owned policy.
- Secrets and production data must not be committed, printed in tests, or sent to
  external services without explicit configuration and authorization.

## Change workflow

1. Identify the public contract and its owning layer before editing.
2. Make the smallest change that solves the stated problem.
3. Add or update representative tests, including failure and insufficient-data
   paths where relevant.
4. Update examples and documentation when behavior or configuration changes.
5. Run `make verify` and `git diff --check`.
6. Inspect the final diff for accidental fixtures, credentials, generated files,
   unrelated formatting, and changes outside this repository.

## Testing expectations

The normal suite must remain runnable without network access or live credentials.
Opt-in live Superset and Jev checks should be clearly labeled and should never be
required for a contributor to exercise local contracts. When changing evaluation
logic, report the dataset, labels, system configuration, and limitations instead
of making an unsupported accuracy claim.

## Architecture boundaries

Do not introduce a scheduler, durable workflow engine, general-purpose agent loop,
or generic knowledge-management product into this repository. Integrate with those
systems through bounded adapters and webhooks. Keep graph context and human
feedback versioned and provenance-bearing if that layer is added; raw feedback
must not silently rewrite a workflow or knowledge graph.

When adding an adapter, document its reference grammar, authentication model,
bounded query behavior, freshness semantics, failure evidence, and tests in
`docs/source-adapters.md`.

## Git and external actions

Do not force-push, rewrite history, change repository settings, or publish data
without an explicit user request. Preserve unrelated working-tree changes. Never
use destructive cleanup commands against broad paths.


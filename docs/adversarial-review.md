# Adversarial public-readiness review

This review treats SignalWeave as an alpha open-source result layer, not as a
complete enterprise control plane. It was refreshed after the retrieval,
durability, and closure trials on
2026-09-18.

## Verdict

**Ready to present as a technical alpha; not ready to present as production-ready.**
The repository now has a coherent wedge, a runnable onboarding path, a Jev-backed
card/result contract, a measured comparison fixture, and fail-closed tests. It still
needs enterprise controls before a public release can imply dependable automatic
operations.

## What passed

- Local lint and tests: `74 passed, 1 skipped`.
- The feature branch is verified locally and GitHub Actions checks for PR #1
  pass on Python 3.11 and 3.12.
- The package builds successfully and declares Apache 2.0 metadata.
- The visual assets are valid SVGs and are included in source distributions.
- No committed API keys, access tokens, or private keys were found by the tracked
  file scan.
- Superset is a concrete first adapter while the card contract remains
  source-oriented.
- The conversational authoring path is executable: Jev-ranked discovery,
  free-form card proposal, no-delivery preview, and explicit approval are covered by an
  end-to-end MCP contract test.
- Jev is the production semantic path; the service does not silently fall back to
  a heuristic evaluator.
- Proposal cards can ask Jev to expand a human-approved anchor into a bounded,
  authorized evidence bundle; fixed cards remain available when expansion is not
  wanted. The live 48-case bundle trial selected 48/48 independently labeled
  related sources, preserved 48/48 anchors, respected the source limit in 48/48
  cases, and returned zero wrong-tenant resources.
- Required empty, stale, unavailable, or incomplete sources are blocked before
  automatic action; selected comparison windows use adapter-provided baselines.
- Partial Superset dashboards preserve healthy chart observations while required
  partial data fails closed; optional related context does not veto complete
  required evidence.
- The approved insight card stores its compiled Jev plan, so later evaluation does
  not silently recompile a different plan.
- The benchmark compares the same four labeled inputs against a real OpenAI
  embeddings-plus-Responses baseline and documents its synthetic limits.
- The enterprise experiment now generates a three-company portfolio with 344 base
  dashboards, 3,649 charts, 1,664 heterogeneous resources, 22 personas, and 144
  hidden-label tasks. The scripted MCP matrix completed 144/144 exact decisions
  with complete workflow, card, provenance, and source-selection coverage; the
  hash-chained 2,304-event trace was valid with zero unsafe automatic actions. A
  latest live Jev closure run completed 130/144 exact decisions with 144/144 workflow, card,
  provenance, and source-selection coverage and zero unsafe automatic actions.
  Its 14 disagreements were conservative or insufficient-evidence routes. This is
  synthetic decision-contract evidence, not enterprise-value evidence.
- The independent discovery trial achieved 48/48 exact top-two source sets,
  48/48 top-ten coverage, and 0/48 wrong-tenant returns with labels held out
  from Jev. The metric-plan trial achieved 24/24 correct metric, dimension, and
  grain selections with partition-bounded, SELECT-only output.
- The default runtime now uses a durable SQLite file for insight cards, metric
  cards, and decision receipts. Restart persistence and an atomic idempotency-key
  claim across two store instances are covered by tests.

## Findings to fix before public release

### High priority

- **Production delivery remains outside the service.** The service records actor,
  card version, idempotency key, outcome, and a replayable receipt. The default
  SQLite store proves an atomic claim across store instances for a single shared
  file. A caller still owns the delivery sink, retries around that sink, and the
  policy for delayed or failed delivery; a multi-replica deployment needs a
  shared transactional store behind the same interface.
- **The live enterprise evidence still has meaningful gaps.** The closure Jev
  run is 130/144 exact on a synthetic matrix; discovery and metric compilation
  are separately covered by synthetic held-out trials. There are still no
  independent domain-owner labels, historical holdout data, or real delivery
  outcomes. These are bounded technical-alpha results, not a production claim.

### Medium priority

- Keep source and delivery-method allowlists documented as deployment
  configuration, not organization-wide authorization provided by SignalWeave.
- Add request-size, catalog-size, and rate limits at the HTTP boundary.
- Make dependency and container builds reproducible beyond the current CI matrix.
- Add runtime adapter-registration tests, not only heterogeneous engine tests.
- Keep the JSON store explicitly limited to local fixtures; do not use it as a
  multi-process idempotency protocol.
- Keep benchmark and Jev proof claims tied to labeled datasets and explicitly
  separate synthetic evidence from production performance.
- Enforce MCP-only persona isolation at the process or tool-policy boundary; the
  current experiment command documents an allowlist and traces calls, but a Luna
  agent still runs in a host shell that could bypass the command if instructed.

## Current security posture

The local compose stack binds its published ports to loopback and is explicitly a
demo. It still uses `admin` / `admin` for local Superset and leaves optional bearer
tokens empty. Production deployments need TLS, identity-aware access, secret
management, reviewed card storage, audit history, and a data policy for
evidence sent to TypeSafe Jev. See [`SECURITY.md`](../SECURITY.md) and
[`security.md`](security.md).

## Review evidence

```text
ruff check src tests evaluations       passed
Python 3.12 + pytest -q                 74 passed, 1 skipped
GitHub Actions PR #1                   test (3.11), test (3.12) passed
SVG XML validation and rendering       passed
Tracked credential scan                no secrets found
```

This document is a release gate, not a claim that the listed gaps are harmless.
Update the verdict and evidence only when the corresponding tests or documented
deployment controls exist.

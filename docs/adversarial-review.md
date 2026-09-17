# Adversarial public-readiness review

This review treats SignalWeave as an alpha open-source decision layer, not as a
complete enterprise control plane. It was refreshed after independent product,
security, and contributor reviews on 2026-09-17.

## Verdict

**Not ready to present as production-ready.** The repository is suitable for a
private, localhost-only proof and has a clear product boundary, but the runtime
still needs safety hardening before a public release can imply dependable
automatic operations.

## What passed

- Local lint and tests: `32 passed, 1 skipped`.
- GitHub Actions CI is green on the current `main` commit.
- The package builds successfully and declares Apache 2.0 metadata.
- The visual assets are valid SVGs and are included in source distributions.
- No committed API keys, access tokens, or private keys were found by the tracked
  file scan.
- Superset is a concrete first adapter while the workflow contract remains
  source-oriented.
- Jev is the production semantic path; the service does not silently fall back to
  a heuristic evaluator.

## Findings to fix before public release

### High priority

- **Freshness is not a complete machine-readable safety contract.** The current
  engine looks for a textual `stale` marker and does not consistently derive age
  from source capture timestamps. A stale source can therefore be interpreted
  incorrectly depending on the adapter and allowed outcomes.
- **Adapter failures must fail closed end-to-end.** Required source errors are
  safety-gated, but every adapter path must promote chart or query failures into a
  structured `ResourceSnapshot.error` before evaluation.
- **Workflow authorization is deployment-owned, not enforced by the catalog.**
  Draft workflows are stored and can be evaluated through the local service; there
  is no approval state, identity-aware ownership, or version collision policy yet.
- **Allowed outcomes need a final runtime gate.** A model result outside the
  workflow’s declared outcome allowlist must be downgraded before recipient
  routing.

### Medium priority

- Add an executable first-use path and a complete MCP request/response example for
  a new contributor or operator.
- Document that source and recipient allowlists are deployment configuration, not
  organization-wide authorization provided by SignalWeave.
- Add request-size, catalog-size, and rate limits at the HTTP boundary.
- Make dependency and container builds reproducible and test supported Python
  versions in CI.
- Add runtime adapter-registration tests, not only heterogeneous engine tests.
- Keep benchmark and Jev proof claims tied to labeled datasets and explicitly
  separate synthetic evidence from production performance.

## Current security posture

The local compose stack binds its published ports to loopback and is explicitly a
demo. It still uses `admin` / `admin` for local Superset and leaves optional bearer
tokens empty. Production deployments need TLS, identity-aware access, secret
management, reviewed workflow storage, audit history, and a data policy for
evidence sent to TypeSafe Jev. See [`SECURITY.md`](../SECURITY.md) and
[`security.md`](security.md).

## Review evidence

```text
.venv/bin/ruff check .                 passed
.venv/bin/python -m pytest -q          32 passed, 1 skipped
GitHub Actions CI                      passed on main
SVG XML validation and rendering       passed
Tracked credential scan                no secrets found
```

This document is a release gate, not a claim that the listed gaps are harmless.
Update the verdict and evidence only when the corresponding tests or documented
deployment controls exist.

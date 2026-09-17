# Adversarial public-readiness review

This review treats SignalWeave as an alpha open-source result layer, not as a
complete enterprise control plane. It was refreshed after independent product,
security, and contributor reviews on 2026-09-17.

## Verdict

**Ready to present as a technical alpha; not ready to present as production-ready.**
The repository now has a coherent wedge, a runnable onboarding path, a Jev-backed
card/result contract, a measured comparison fixture, and fail-closed tests. It still
needs enterprise controls before a public release can imply dependable automatic
operations.

## What passed

- Local lint and tests: `48 passed, 1 skipped`.
- GitHub Actions CI is green on the published `main` commit.
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
- Required empty, stale, unavailable, or incomplete sources are blocked before
  automatic action; selected comparison windows use adapter-provided baselines.
- The approved insight card stores its compiled Jev plan, so later evaluation does
  not silently recompile a different plan.
- The benchmark compares the same four labeled inputs against a real OpenAI
  embeddings-plus-Responses baseline and documents its synthetic limits.

## Findings to fix before public release

### High priority

- **Card authorization is deployment-owned, not enforced by the catalog.**
  Draft cards require explicit approval before MCP or webhook evaluation, but
  approval is not identity-aware and there is no durable audit trail or version
  collision policy yet.
- **Production delivery remains outside the service.** The caller still needs
  identity, retries, idempotency, delivery receipts, and a policy for what happens
  when a decision is delayed or duplicated.
- **The Jev comparison needs a fresh run and real history before release claims.**
  The checked-in Jev row is historical relative to the source-contract refactor;
  the OpenAI comparison is live but the four cases are synthetic. A time-split
  export from a design partner is the meaningful next gate.

### Medium priority

- Document that source and delivery-method allowlists are deployment configuration, not
  organization-wide authorization provided by SignalWeave.
- Add request-size, catalog-size, and rate limits at the HTTP boundary.
- Make dependency and container builds reproducible beyond the current CI matrix.
- Add runtime adapter-registration tests, not only heterogeneous engine tests.
- Keep benchmark and Jev proof claims tied to labeled datasets and explicitly
  separate synthetic evidence from production performance.

## Current security posture

The local compose stack binds its published ports to loopback and is explicitly a
demo. It still uses `admin` / `admin` for local Superset and leaves optional bearer
tokens empty. Production deployments need TLS, identity-aware access, secret
management, reviewed card storage, audit history, and a data policy for
evidence sent to TypeSafe Jev. See [`SECURITY.md`](../SECURITY.md) and
[`security.md`](security.md).

## Review evidence

```text
ruff check .                           passed
Python 3.12 + pytest -q                48 passed, 1 skipped
GitHub Actions CI                      passed on published main
SVG XML validation and rendering       passed
Tracked credential scan                no secrets found
```

This document is a release gate, not a claim that the listed gaps are harmless.
Update the verdict and evidence only when the corresponding tests or documented
deployment controls exist.

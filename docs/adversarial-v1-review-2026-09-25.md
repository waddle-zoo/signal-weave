# SignalWeave v1 adversarial review

**Branch:** `feat/decision-feedback-contract`  
**Review date:** 2026-09-25  
**Decision:** pass for a controlled enterprise shadow/pilot; fail for autonomous production.

This is a deliberately narrow release decision. “Enterprise-ready” here means a
company can install SignalWeave behind its own identity and source boundaries,
author and review cards, run Jev-backed shadow decisions, and inspect the result.
It does not mean that the repository can safely deliver unsupervised business
actions for an arbitrary company without a staging replay and operator labels.

## Review lenses

### Security and tenant isolation

The review challenged every sensitive operation exposed by the MCP factory,
not only the primary insight-card path.

Findings discovered and fixed in commit `905411d`:

- Metric-query cards had no principal provenance, and list/get/compile/approve
  operations were not tenant-scoped. Cards now retain `principal_id` and
  `principal_tenant`; source selection is filtered through the authorized
  catalog; and all reads/mutations enforce the current principal tenant.
- The custom webhook route used a shared secret but did not pass a request
  principal into card evaluation. OIDC deployments now resolve the verified
  bearer principal and required scopes on that route; static-token deployments
  require a configured sidecar principal.
- OIDC issuer URLs ending in `/` were normalized away before JWT validation,
  which can reject standards-compliant issuer claims. Validation now preserves
  the configured issuer while normalizing only discovery URL joins.
- Workflow certification accepted caller-supplied snapshots without checking
  their typed tenant contracts. Scoped replay now rejects foreign or explicitly
  unauthorized snapshots.
- `SIGNALWEAVE_ALLOW_INSECURE_HTTP=1` can no longer expose an unauthenticated
  HTTP server on a non-loopback host.

Targeted adversarial tests cover cross-tenant metric-card list/get/compile/
approve, cross-tenant webhook evaluation, foreign evaluation snapshots,
missing-tenant JWTs, issuer/audience/signature/expiry failures, required scopes,
issuer trailing slashes, malformed payloads, oversized payloads, and the public
health/private MCP distinction.

Verdict: **pass for the tested contract**. A real IdP, gateway, source
credentials, and adapter-side authorization replay remain deployment gates.

### Retrieval and product correctness

The reviewer reran the repository’s separate onboarding contract and adversarial
review rather than treating the result as a semantic accuracy guarantee:

```text
onboarding contract: 30 scenarios; 30/30 safe; required-candidate recall 1.00;
0 wrong-tenant leaks; 29/30 exact recommendation sets
onboarding adversarial gate: PASS
  correctness: PASS WITH WARNINGS
  scope: PASS
  generalization: PASS
```

The one recommendation mismatch is the intentional fintech definition ambiguity;
the review marks it for human review rather than treating Jev’s alternative as
truth. This is the correct behavior for a candidate recommender, not a reason
to claim 30/30 semantic correctness.

The larger recorded live Jev evidence remains useful but bounded: the 144-task
synthetic matrix achieved 130/144 exact outcomes, complete workflow/card/
provenance/source-selection contracts, and zero unsafe automatic actions. It
used labeled source wiring in that runner, so it is not proof of open-ended
enterprise retrieval. Separate recorded discovery and related-expansion trials
cover that seam with synthetic catalogs and explicitly report their limits.

Verdict: **pass for the bounded card-and-evidence contract; fail for a universal
retrieval or business-accuracy claim**.

### Packaging, operations, and claims

The rebuilt image was exercised with the real local TypeSafe key file supplied
through an external bind path; the secret was not copied into the repository.
The checks passed:

```text
docker compose config --quiet: pass
docker compose build signal-weave: pass
container health: healthy
GET /healthz: 200
unauthenticated POST /mcp: 401
MCP initialize: 200
MCP tools/list: 27 tools, including onboard_insight_card and metric-card tools
read-only list_resources(adapter=superset): 9 real local dashboards
```

The full repository gate is `196 passed, 1 skipped`; Ruff, `git diff --check`,
and offline lockfile validation pass. The current research harness was also
rerun over 144 generated enterprise tasks: all 144 workflows, cards,
provenance records, and source-selection handoffs completed with zero unsafe
automatic actions. Its deterministic research driver scored 100/144 exact
outcomes in this rerun, so it is treated as wiring/safety evidence, not model
accuracy evidence.

Verdict: **pass for a packaged controlled pilot**. SQLite is still a single
deployment boundary, delivery is caller-owned, and production needs secret
management, shared transactional storage for replicas, observability, and a
real delivery worker.

## Release conclusion

The adversarial evidence agrees on the useful claim:

> SignalWeave v1 is a small Jev-backed, tenant-scoped decision layer that an
> enterprise can run in shadow mode over its existing analytical assets, with
> human-approved cards, bounded retrieval, inspectable evidence, and caller-owned
> delivery.

The evidence does not support the stronger claim that SignalWeave is ready to
autonomously operate arbitrary enterprise analytics. That requires a staging
replay with the customer’s OIDC provider, connector permissions, real catalog
and graph indexes, owner-authored labels, and delivery outcomes. Those are
external proof obligations, not gaps that should be hidden by another synthetic
benchmark.

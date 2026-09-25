# SignalWeave v1 acceptance record

**Branch:** `feat/decision-feedback-contract`  
**Scope:** controlled enterprise pilot, not autonomous production delivery  
**Last verified:** 2026-09-25

## V1 claim

SignalWeave v1 is shippable as a small, self-hosted decision layer when an
enterprise supplies:

1. a TypeSafe API key for Jev;
2. an OIDC issuer or identity-aware gateway that provides a stable tenant claim;
3. one or more read-only source adapters; and
4. an existing scheduler, agent, or delivery worker to invoke and act on the
   MCP result.

The v1 product boundary is deliberately narrow. SignalWeave does not own a
catalog, BI system, workflow runtime, notification system, or agent. It accepts
free-form human intent, retrieves an authorized bounded candidate set, uses Jev
to rank and judge the supplied state, applies deterministic safety gates, and
returns an inspectable evidence bundle and receipt.

## Acceptance gates

| Gate | Evidence | Result |
| --- | --- | --- |
| Jev is the production decision path | Runtime rejects non-Jev mode; no local heuristic fallback exists. | Pass |
| Request identity reaches every sensitive operation | OIDC JWT verifier plus MCP-native bearer middleware; tenant/principal are derived from verified claims, never tool arguments. | Pass locally; external IdP replay remains a deployment gate |
| Invalid or incomplete identity fails closed | Wrong signature/issuer/audience, expired tokens, malformed JWTs, missing tenant claims, and unauthorized MCP requests are tested. | Pass |
| Health checks do not expose MCP | `/healthz` is public; `/mcp` requires a valid bearer token in native MCP auth mode. | Pass |
| Onboarding is usable without SignalWeave owning a UI | `onboard_insight_card` is one call from free-form intent to persisted draft plus Jev plan, candidates, blockers, questions, and next action. | Pass |
| Human intent is not guessed | Missing sources, decision guidance, ambiguity, stale sources, bounded catalogs, and absent candidates remain explicit review/block states. | Pass |
| Approval and delivery remain separate | One-call onboarding always returns `approval_required=true` and `delivery_enabled=false`; approval re-checks the current review. | Pass |
| Authorized retrieval works across messy shapes | 30 onboarding scenarios across BI, metric, notebook, workflow, quality, ownership, stale, revoked, paginated, and no-match cases. | 30/30 safe; 1.00 required-candidate recall; 0 leaks |
| Jev result provenance is inspectable | Discovery receipts, source candidates, roles, probabilities, plan evaluator, context version, and decision receipts are persisted or returned. | Pass |
| Existing enterprise workflows remain the owner | MCP tools return typed decisions and evidence; SignalWeave does not execute arbitrary SQL, tools, DAGs, or notifications. | Pass |
| Regression safety | Full repository tests and lint. | 191 passed, 1 skipped; Ruff clean |

## Reproduction

From the repository root:

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests evaluations
./.venv/bin/python -m evaluations.onboarding_contract_trial --format markdown
./.venv/bin/python -m evaluations.onboarding_adversarial_review --format markdown
```

The onboarding trial is intentionally not presented as a live Jev accuracy
benchmark. It isolates the product contract using opaque Jev-shaped judgments,
so the result tests authorization, candidate coverage, human-review behavior,
and generalization rather than rewarding a fixture-specific implementation.
Live Jev evidence is recorded separately in the enterprise, Northstar, paired
agent, and retrieval reports under `docs/`.

## Deployment modes

### Private single-tenant sidecar

Use the static deployment token for a loopback or private network deployment:

```bash
SIGNALWEAVE_AUTH_MODE=token \
SIGNALWEAVE_API_TOKEN='replace-me' \
SIGNALWEAVE_TENANT_ID='acme' \
SIGNALWEAVE_PRINCIPAL_ID='analytics-agent' \
signalweave serve --transport streamable-http
```

This mode is intentionally single-tenant. The token is a transport boundary;
the configured sidecar principal is the tenant identity.

### Shared or user-facing enterprise deployment

Use the built-in OIDC resource-server path:

```bash
SIGNALWEAVE_AUTH_MODE=oidc \
SIGNALWEAVE_OIDC_ISSUER_URL='https://id.example.com/realms/acme' \
SIGNALWEAVE_OIDC_AUDIENCE='signalweave' \
SIGNALWEAVE_OIDC_TENANT_CLAIM='tenant_id' \
SIGNALWEAVE_OIDC_REQUIRED_SCOPES='insights:read,insights:run' \
signalweave serve --transport streamable-http
```

The verifier validates an asymmetric signature against OIDC discovery/JWKS,
issuer, audience, expiry, and subject. The MCP request principal then requires
the configured tenant claim. Signing-key rotation is handled by bounded JWKS
caching and refresh. TLS, secret injection, the identity provider, source
credentials, and external audit retention remain deployment responsibilities.

## What this proves — and what it does not

This is enough evidence to ship a controlled v1 pilot to an enterprise that is
willing to run it in shadow mode or behind an existing agent/scheduler. The
pilot can onboard cards, retrieve evidence across installed adapters, return
typed Jev decisions, and preserve tenant/audit boundaries without SignalWeave
becoming a replacement for the customer’s existing stack.

It is not proof of universal enterprise readiness. Before autonomous delivery
for a specific customer, run a staging replay with that customer’s identity
provider, adapter credentials, source permissions, card catalog, and operator
labels. Measure useful-alert precision, investigation rate, time-to-decision,
source-fetch cost, and delivery reliability. The existing synthetic and local
trials do not substitute for those labels or prove warehouse cost savings.

The correct next step after v1 is a bounded customer pilot, not a larger
feature surface: one tenant, one or two source adapters, a small set of human
approved cards, and a shadow receipt stream that operators label as useful,
noisy, late, incomplete, or unsafe.

# SignalWeave v1 acceptance record

**Branch:** `feat/decision-feedback-contract`  
**Scope:** controlled enterprise pilot, not autonomous production delivery  
**Last verified:** 2026-09-26

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
| Request identity reaches every sensitive operation | OIDC JWT verifier plus MCP-native bearer middleware; tenant/principal are derived from verified claims, never tool arguments. Metric-query cards and workflow replay snapshots are tenant-scoped too; OIDC webhook requests use the verified bearer principal. Token-authenticated Preset deployments fail closed without a static tenant/principal pair. | Pass locally; external IdP replay remains a deployment gate |
| OIDC deployment configuration fails before request traffic | The zero-network Preset configuration preflight rejects empty/malformed tenant, principal, and scope claim paths plus invalid JWKS TTL values before a shared deployment can start with request-time identity failures. | Pass locally; external IdP replay remains a deployment gate |
| Local OIDC MCP replay preserves Preset tenant isolation | `tests/test_oidc_http_integration.py` verifies signed discovery/JWKS validation, required scopes, tenant-scoped card access, webhook rejection for a foreign card, two tenant-bound Preset connections receiving exactly their own adapter/provider calls, and the production `build_runtime()` environment bootstrap rejecting foreign-tenant provider access. | 3 tests pass locally; external IdP replay remains a deployment gate |
| OIDC discovery cannot redirect key retrieval insecurely | Configured and discovered issuer/JWKS URLs are validated for HTTPS and safe URL shape; a discovered HTTP `jwks_uri` is rejected before any HTTP JWKS request. | Pass locally |
| Production Preset startup reuses the identity preflight | `build_runtime()` invokes the same configuration contract before registering an environment Preset adapter: token mode requires a static trusted tenant/principal, while OIDC mode permits request-scoped identity and requires valid OIDC settings. | Pass locally |
| Preset provider URLs cannot downgrade to HTTP | Environment bootstrap and the hosted connection model both require HTTPS; a legacy `SIGNALWEAVE_ALLOW_INSECURE_PROVIDER` setting does not weaken the check. | Pass locally |
| Preset provider redirects fail closed | Preset token-exchange and workspace HTTP clients explicitly disable redirects; a 3xx response produces no second-host request and cannot forward a bearer token. | Pass locally; shared-service egress controls remain open |
| Invalid or incomplete identity fails closed | Wrong signature/issuer/audience, expired tokens, malformed JWTs, missing tenant claims, and unauthorized MCP requests are tested. | Pass |
| Health checks do not expose MCP | `/healthz` is public; `/mcp` requires a valid bearer token in native MCP auth mode. | Pass |
| Onboarding is usable without SignalWeave owning a UI | `onboard_insight_card` is one call from free-form intent to persisted draft plus Jev plan, candidates, blockers, questions, and next action. | Pass |
| Human intent is not guessed | Missing sources, decision guidance, ambiguity, stale sources, bounded catalogs, and absent candidates remain explicit review/block states. | Pass |
| Approval and delivery remain separate | One-call onboarding always returns `approval_required=true` and `delivery_enabled=false`; approval re-checks the current review. | Pass |
| Authorized retrieval works across messy shapes | 30 onboarding scenarios across BI, metric, notebook, workflow, quality, ownership, stale, revoked, paginated, and no-match cases. | 30/30 safe; 1.00 required-candidate recall; 0 leaks |
| Tenant-aware native search is required for complete coverage | Adapters that accept `authorized_tenants` receive the scope at search time; older unscoped indexes have provider-wide counts redacted and remain review-visible. | Pass locally; adapter contract gate remains open per deployment |
| Jev result provenance is inspectable | Discovery receipts, source candidates, roles, probabilities, plan evaluator, context version, and decision receipts are persisted or returned. | Pass |
| Hosted Preset boundary is explicit and exercised | The production Preset adapter, token refresh, tenant-scoped policy limits, metadata/cached/live query modes, and varied chart-shape fixture trial pass; the real-account acceptance runner requires a tenant principal, `jev-latest`, explicit human approval, and a delivery-disabled receipt. | Fixture pass; customer gate open |
| Live Preset acceptance is independently reviewable | `preset_live_onboarding_review.py` recomputes approval, Jev provenance, tenant/resource binding, idempotent replay, delivery-disabled receipt, and explicit non-claims from the serialized live-run report instead of trusting the runner's `passed` flag. | Pass locally; customer gate still requires a real tenant |
| Pending Preset chart jobs do not become false empty data | HTTP 202 chart-data responses fail closed with an explicit asynchronous-response error; the adapter does not report a pending provider job as `no_data`. | Pass locally; provider-specific polling remains intentionally out of scope |
| Malformed Preset result envelopes do not become false empty data | Missing, scalar, mixed-object, and invalid-JSON chart responses fail closed as explicit provider-policy errors while supported dict/list envelopes remain accepted. | Pass locally |
| Non-success Preset query states do not become false empty data | Result-item statuses are fail-closed: only known successful states (`success`, `completed`, `complete`, `ok`) or an omitted status are accepted; `pending`, `failed`, `running`, `scheduled`, `stopped`, `timed_out`, unknown, and future states fail closed even when the HTTP response is 200. | Pass locally |
| Embedded Preset query errors do not become false empty data | A non-empty result-item `error` fails closed even when the HTTP response is 200; warnings remain non-blocking. | Pass locally |
| Preset dashboard fan-out stays bounded | Concurrent chart reads use one refresh exchange when a shared token expires; the aggregate dashboard snapshot also fails closed when it exceeds the configured byte budget instead of sending partial evidence to Jev. | Pass locally |
| Preset response streams stay bounded | The configured response-byte policy is enforced while consuming the API-token exchange and workspace/dashboard streams, before parsing or forwarding the body. Chunked oversized responses fail closed. | Pass locally |
| Provider-reported Preset row counts cannot bypass limits | The connector validates `rowcount` and `sql_rowcount` metadata in addition to materialized rows, and rejects malformed, fractional, negative, or non-finite counts before evidence reaches Jev. | Pass locally |
| Preset low-level client default bounds | A directly constructed `PresetCloudClient` defaults to 500 rows and 1 MB; a 501-row standalone result is rejected without requiring an adapter policy. | Pass locally |
| Malformed standalone Preset query contexts fail before provider I/O | Saved chart contexts with invalid JSON, a non-object envelope, or without a usable bounded `queries` list are rejected locally; the connector does not replace malformed context with synthesized params or send an invalid/unbounded POST request. | Pass locally |
| Preset saved row limits cannot disable bounding | Zero and negative numeric saved `row_limit` values clamp to `1`; oversized values clamp to the connection policy; boolean and malformed values fail before provider I/O. | Pass locally |
| Explicit Superset resources scale with card scope | Dashboard and chart card anchors use one provider metadata lookup for authorization; they do not materialize the full workspace catalog. A large-catalog regression test fails if the list endpoint is touched. | Pass locally |
| Preset evidence reaches the typed Jev contract | The production Preset adapter and Jev adapter are exercised together across 3 workspace shapes / 13 charts; normalized observations, evidence, visualization labels, dashboard filter context, typed probabilities, and partial-quality safe outcomes are asserted. | Pass locally; live Jev semantics not proven |
| Preset runtime shadow path is exercised end to end | Three named plus six generated tenant-bound Preset-shaped workspaces run through environment bootstrap, MCP discovery, free-form onboarding, approval, Jev-only evaluation, SQLite receipt lookup, and idempotent replay. Generated workspaces use unfamiliar IDs and varied chart/result shapes; the named Harbor case also proves a dashboard-scoped provider outage becomes partial evidence. | 9 workspaces; 18 cards; 126 synthetic Jev calls; pass; live semantics not proven |
| Larger anti-overfitting runtime replay | The same production runtime path was rerun with three named plus 30 seeded generated workspaces, 16 charts per generated workspace, unfamiliar tenants/IDs, provider failures, partial dashboards, and 15 visualization labels. The independent reviewer recomputed the report invariants. | 33 workspaces; 66 cards; 462 synthetic Jev calls; pass; live semantics not proven |
| Multi-seed replay stability | The 33-workspace replay was repeated with seeds `2026092601`, `2026092602`, and `2026092603`; each report passed the independent reviewer. The generator keeps the same envelope/type coverage while changing generated tenant/resource IDs and deterministic failure placement. | 3/3 reports pass; 99 workspaces; 198 cards; 1,386 synthetic Jev calls; live semantics not proven |
| Post-hardening scaled replay | After fail-closed provider parsing, startup identity-contract validation, bounded low-level Preset defaults, the HTTPS-only environment contract, production OIDC bootstrap coverage, incrementally bounded response streams, safe OIDC discovery validation, the Jev-only environment guard, and explicit no-redirect transport landed, a fresh seeded 33-workspace replay passed the production runtime path and independent reviewer. | Seed `2026092627`; 33 workspaces; 66 cards; 462 synthetic Jev calls; pass |
| Shared hosted processes do not contact foreign tenant adapters | The source registry skips tenant-bound adapters outside the authenticated scope before list, search, authorization, or resolve calls. An adversarial two-tenant test plus an OIDC-authenticated MCP HTTP replay over two Preset connections records exactly one matching auth/dashboard path per tenant and zero foreign calls. | Pass locally; external identity-provider replay remains a deployment gate |
| Live Superset provider matrix has no silent loss | The running Northstar Superset instance was checked across every saved dashboard and chart with the normal client path. | 20 dashboards; 580 charts; 41,002 observations; 580/580 extracted; 0 silent-loss issues |
| Hosted credential injection is deployment-safe | Docker Compose secret overlay mounts Preset API-token files, clears direct `.env.preset` token values, and the runtime tests value/file exclusivity, exact credential modes, explicit tenant identity, and tenant binding. `make preset-compose-check` also inspects the rendered two-file Compose model with disposable file inputs. | Pass locally; vault/KMS and real tenant gate remain open |
| Shared-service egress is not overclaimed | The self-hosted connector enforces HTTPS origins, while the managed-service boundary explicitly requires provider allowlists, redirect blocking, DNS-rebinding protection, and network egress policy before accepting tenant-supplied URLs. | Documented boundary; managed-service controls not shipped |
| Preset onboarding fails early without burning Jev credits | `make preset-config-check` reuses the production Preset parser to validate credentials, tenant binding, auth mode, policy, and Jev key presence with zero network requests and zero Jev requests. The provider-only bootstrap path then builds the same tenant-bound adapter and reaches a bounded catalog request without a TypeSafe key or Jev request. | Pass locally; real tenant gate remains open |
| Generated-shape anti-overfitting trial | A seeded generator creates 24 unfamiliar tenant workspaces / 192 charts across five result envelopes, 12 visualization labels, usable and unusable metric definitions, empty results, ambiguous numerics, and provider failures; the production Preset client/adapter passes catalog, scope, cache, retention, and safe-degradation assertions, then an independent report reviewer checks coverage and rejects mutated pass-looking reports. A generated 64-chart dashboard stress test proves the provider aggregate byte budget fails closed; an engine test separately proves the multi-source serialized Jev budget fails before any Jev call. | Pass locally; provider and live Jev gates remain open |
| Existing enterprise workflows remain the owner | MCP tools return typed decisions and evidence; SignalWeave does not execute arbitrary SQL, tools, DAGs, or notifications. | Pass |
| Regression safety | Full repository tests and lint. | 366 passed, 2 skipped; Ruff clean |

## Reproduction

From the repository root:

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests evaluations
./.venv/bin/python -m evaluations.onboarding_contract_trial --format markdown
./.venv/bin/python -m evaluations.onboarding_adversarial_review --format markdown
./.venv/bin/pytest tests/test_sources.py tests/test_hosted_connections.py -q
make preset-trial
make preset-generalization-trial
make preset-jev-contract-trial
make preset-runtime-shadow-trial
# Larger deterministic replay used for the current scale check:
uv run python -m evaluations.preset_runtime_shadow_trial \
  --generated-workspaces 30 \
  --generated-charts-per-workspace 16 \
  --generated-seed 2026092627 \
  --output /tmp/preset-runtime-shadow-30x16.json
uv run python evaluations/preset_runtime_shadow_review.py \
  /tmp/preset-runtime-shadow-30x16.json
# Repeat the same replay with independent generated IDs/failure placement:
for seed in 2026092601 2026092602 2026092603; do \
  uv run python -m evaluations.preset_runtime_shadow_trial \
    --generated-workspaces 30 \
    --generated-charts-per-workspace 16 \
    --generated-seed "$seed" \
    --output "/tmp/preset-runtime-shadow-$seed.json" && \
  uv run python evaluations/preset_runtime_shadow_review.py \
    "/tmp/preset-runtime-shadow-$seed.json"; \
done
# With a copied .env.preset and disposable/real host secret files:
make preset-compose-check
# For a running local Superset instance, also run:
make superset-chart-matrix
```

The current verified regression result is `366 passed, 2 skipped` with Ruff
clean. The runtime-shadow and chart-matrix commands are separate evidence
surfaces: the former uses synthetic Preset and TypeSafe transports to exercise
the production runtime, while the latter uses the live local Superset service
without making Jev calls.

The runtime shadow report also checks that the Preset token name and secret are
absent from both returned MCP artifacts and the state handed to the Jev adapter.

For the hosted Preset customer acceptance gate, run the explicit shadow trial
from [`docs/preset-integration.md`](preset-integration.md). It is intentionally
not included in the offline reproduction commands because it requires a
customer-authorized Preset credential and a live TypeSafe key:

```bash
PRESET_TRIAL_GOAL="..." \
PRESET_TRIAL_WHY="..." \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  make preset-live-trial
# Review the generated draft, then rerun the same variables with:
PRESET_TRIAL_GOAL="..." \
PRESET_TRIAL_WHY="..." \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  make preset-live-trial-approve
# Independently review the resulting report:
make preset-live-trial-review
```

The onboarding trial is intentionally not presented as a live Jev accuracy
benchmark. It isolates the product contract using opaque Jev-shaped judgments,
so the result tests authorization, candidate coverage, human-review behavior,
and generalization rather than rewarding a fixture-specific implementation.
Live Jev evidence is recorded separately in the enterprise, Northstar, paired
agent, and retrieval reports under `docs/`.

The stronger follow-up onboarding replay used eight real Jev requests with
expected labels withheld from the evaluator state: 8/8 required-candidate
recall, 8/8 safe outcomes, 7/8 exact recommendation sets, zero tenant leaks,
and zero role-label disagreements. The one mismatch was held for human review
as a definition conflict. See
[`docs/live-jev-onboarding-2026-09-25.md`](live-jev-onboarding-2026-09-25.md).

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
The push webhook uses the same verified principal and required scopes in OIDC
mode; a static `PUSH_WEBHOOK_TOKEN` is only the single-tenant sidecar mode.

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
trials do not substitute for those labels or prove warehouse cost savings. The
repository does not claim that a real company has passed this gate until the
live runner produces a receipt and the company’s operators label the result
useful in shadow mode.

The correct next step after v1 is a bounded customer pilot, not a larger
feature surface: one tenant, one or two source adapters, a small set of human
approved cards, and a shadow receipt stream that operators label as useful,
noisy, late, incomplete, or unsafe.

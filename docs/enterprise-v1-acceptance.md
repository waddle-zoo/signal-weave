# SignalWeave v1 acceptance record

**Branch:** `feat/decision-feedback-contract`  
**Scope:** controlled enterprise pilot, not autonomous production delivery  
**Last verified:** 2026-09-27

The hosted-Preset assumptions in this record were checked against Preset's
current documentation on 2026-09-27: the direct Preset API is Enterprise-only,
Preset MCP is documented as an Enterprise add-on, and Preset Alerts & Reports
are Preset-owned scheduled/event-triggered notifications delivered through
email or Slack on Professional and Enterprise plans. Those capabilities do not
amount to a managed SignalWeave endpoint or a server-side Jev extension point;
the managed-service gates below remain open.

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
| Provider resource identity cannot be substituted | Superset-compatible dashboard and chart metadata responses must echo the requested resource ID; dashboard fan-out and standalone chart inspection fail closed on a mismatched ID before evidence is normalized. | Pass locally |
| Hosted workspace labels cannot widen authorization | `external_workspace` is descriptive metadata only; the tenant-bound credential and validated provider origin determine the adapter endpoint and authorization scope. | Pass locally |
| Invalid or incomplete identity fails closed | Wrong signature/issuer/audience, expired tokens, malformed JWTs, missing tenant claims, and unauthorized MCP requests are tested. | Pass |
| Health checks do not expose MCP | `/healthz` is public; `/mcp` requires a valid bearer token in native MCP auth mode. | Pass |
| Local container deployment boundary | The running Compose SignalWeave container reported healthy; an actual `GET /healthz` returned 200 with the installed Superset adapter, while an unauthenticated `GET /mcp` returned 401. | Pass locally; authenticated customer deployment remains a gate |
| Onboarding is usable without SignalWeave owning a UI | `onboard_insight_card` is one call from free-form intent to persisted draft plus Jev plan, candidates, blockers, questions, and next action. | Pass |
| Human intent is not guessed | Missing sources, decision guidance, ambiguity, stale sources, bounded catalogs, and absent candidates remain explicit review/block states. | Pass |
| Approval and delivery remain separate | One-call onboarding always returns `approval_required=true` and `delivery_enabled=false`; approval re-checks the current review. | Pass |
| Authorized retrieval works across messy shapes | 30 onboarding scenarios across BI, metric, notebook, workflow, quality, ownership, stale, revoked, paginated, and no-match cases. | 30/30 safe; 1.00 required-candidate recall; 0 leaks |
| Tenant-aware native search is required for complete coverage | Adapters that accept `authorized_tenants` receive the scope at search time; older unscoped indexes have provider-wide counts redacted and remain review-visible. | Pass locally; adapter contract gate remains open per deployment |
| Jev result provenance is inspectable | Discovery receipts, source candidates, roles, probabilities, plan evaluator, context version, and decision receipts are persisted or returned. | Pass |
| Hosted Preset boundary is explicit and exercised | The production Preset adapter, token refresh, tenant-scoped policy limits, metadata/cached/live query modes, and varied chart-shape fixture trial pass; the real-account acceptance runner requires a tenant principal, `jev-latest`, explicit human approval, and a delivery-disabled receipt. | Fixture pass; customer gate open |
| Live Preset acceptance is independently reviewable | `preset_live_onboarding_review.py` recomputes exact-draft approval binding, Jev provenance, tenant/resource binding, bounded Preset transport use and catalog fan-out, loaded-credential proof with artifact redaction, at least one chart-data (`/data`) request during the first evaluation, dashboard-scope telemetry for dashboard resources (no unscoped fallback), zero Preset and Jev calls on replay, delivery-disabled receipt consistency, and explicit non-claims from the serialized live-run report instead of trusting the runner's `passed` flag. | Pass locally; customer gate still requires a real tenant |
| Standalone live-card helper cannot bypass approval | `scripts/live_card_check.py` rejects draft cards before runtime construction and reports the accepted path as delivery-disabled shadow execution. | Pass locally |
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
| Preset evidence reaches the typed Jev contract | The production Preset adapter and Jev adapter are exercised together across 3 workspace shapes / 13 charts; normalized observations, evidence, visualization labels, dashboard filter context, typed probabilities, and partial-quality safe outcomes are asserted. The serialized report is independently reviewed for tenant contracts, evidence hand-off, visualization coverage, fail-safe outcomes, and bounded Jev requests. | Pass locally; live Jev semantics not proven |
| Preset runtime shadow path is exercised end to end | Three named plus six generated tenant-bound Preset-shaped workspaces run through environment bootstrap, MCP discovery, free-form onboarding, approval, Jev-only evaluation, SQLite receipt lookup, and idempotent replay. Generated workspaces use unfamiliar IDs and varied chart/result shapes; the named Harbor case also proves a dashboard-scoped provider outage becomes partial evidence. | 9 workspaces; 18 cards; 126 synthetic Jev calls; pass; live semantics not proven |
| Larger anti-overfitting runtime replay | The same production runtime path was rerun with three named plus 30 seeded generated workspaces, 16 charts per generated workspace, unfamiliar tenants/IDs, provider failures, partial dashboards, and 15 visualization labels. The independent reviewer recomputed the report invariants. | 33 workspaces; 66 cards; 462 synthetic Jev calls; pass; live semantics not proven |
| Multi-seed replay stability | The 33-workspace replay was repeated with seeds `2026092601`, `2026092602`, and `2026092603`; each report passed the independent reviewer. The generator keeps the same envelope/type coverage while changing generated tenant/resource IDs and deterministic failure placement. | 3/3 reports pass; 99 workspaces; 198 cards; 1,386 synthetic Jev calls; live semantics not proven |
| Post-hardening scaled replay | After fail-closed provider parsing, startup identity-contract validation, bounded low-level Preset defaults, the HTTPS-only environment contract, production OIDC bootstrap coverage, incrementally bounded response streams, safe OIDC discovery validation, the Jev-only environment guard, and explicit no-redirect transport landed, a fresh seeded 33-workspace replay passed the production runtime path and independent reviewer. | Seed `2026092628`; 33 workspaces; 66 cards; 462 synthetic Jev calls; pass |
| Shared hosted processes do not contact foreign tenant adapters | The source registry skips tenant-bound adapters outside the authenticated scope before list, search, authorization, or resolve calls. An adversarial two-tenant test plus an OIDC-authenticated MCP HTTP replay over two Preset connections records exactly one matching auth/dashboard path per tenant and zero foreign calls. | Pass locally; external identity-provider replay remains a deployment gate |
| Current Northstar Outfitters Superset provider matrix | The live Northstar Outfitters local Superset instance was rerun on 2026-09-27 across every saved dashboard and chart with the normal client path after provider-resource identity hardening. | 20 dashboards; 580 charts; 41,002 observations; 580/580 extracted; 0 non-extracted charts; 0 silent-loss issues. |
| Current Northstar production MCP shadow path | A real local Northstar Superset service was exercised through `build_runtime()` and the registered MCP tools, with the standalone adapter bound to the authenticated tenant. Discovery selected a dashboard without a hardcoded ID; onboarding remained human-reviewable; approval was required; saved chart data reached the production engine; and a delivery-disabled Jev-shaped receipt was persisted and replayed. The run now records dashboard-scope telemetry rather than treating chart-query fallback as dashboard-filter proof. | `01 | Executive Command Center`; 10 charts; 25 normalized observations; 36 evidence items; `jev-latest`; 1 synthetic Jev evaluation; 0 provider/TypeSafe calls on replay; independent report review pass. All 10 local charts used the bounded saved-chart-query fallback because saved query context was absent (`dashboard_scoped_requests=0`); this is an onboarding/provider-artifact limitation, not proof of dashboard-native filter application. Live Jev semantics and managed hosting remain unproven. |
| Historical local Superset demo provider matrix | The earlier Compose demo was checked across every saved dashboard and chart with the normal client path. Partial and unsupported charts remained explicit with provider error/quality metadata; no chart silently disappeared. | 9 dashboards; 102 charts; 8,611 observations; 91 extracted, 1 partial, 10 unsupported because the local provider returned explicit HTTP 400 errors for dashboard-scoped chart data (`Chart has no query context saved. Please save the chart again.`); 0 silent-loss issues. Retained as historical demo evidence; the current Northstar matrix is recorded above. |
| Hosted credential injection is deployment-safe | Docker Compose secret overlays support Preset API-token or bearer files plus the SignalWeave HTTP and push-webhook tokens, clear their direct `.env.preset` values, and the runtime tests value/file exclusivity, exact provider credential modes, explicit tenant identity, and tenant binding. Preset is API-token/bearer, Hex is bearer-only, and Looker is bearer or client-credential OAuth. `make preset-compose-check` and `make preset-compose-bearer-check` inspect the rendered two-file Compose models with disposable file inputs. | Pass locally; vault/KMS and real tenant gate remain open |
| Hosted boundary matrix is independently reviewed | `make preset-boundary-trial` constructs the production hosted factories and Preset client without provider or Jev traffic, then serializes and independently reviews Preset API-token/bearer, Hex bearer-only, and Looker bearer/OAuth credential contracts, secret-free connection records, tenant-scoped stores and authorization, distinct adapter routes, and metadata/cached/live policy behavior. | 24/24 checks pass; 0 provider requests; 0 TypeSafe requests |
| Customer bootstrap commands execute from the repository | The actual `make preset-compose-check` rendered the two-file Compose deployment with placeholder secret files, `make preset-config-check` accepted a placeholder token-mode configuration without contacting a provider or Jev, and `preset-bootstrap-check` now requires counted Preset transport telemetry for its bounded catalog request. The `preset-readiness` variant can select a unique dashboard by provider-side title search, rejects ambiguous/truncated matches, and runs the readiness gate without Jev. | Both zero-network checks pass; bounded provider preflight and title-selection tests pass; real credentials remain unproven |
| Dashboard readiness is checked before card approval | `make preset-dashboard-readiness` runs a selected dashboard through the production Preset adapter, applies the aggregate snapshot budget, and reports every chart-quality error/remediation before any Jev call. The single-chart probe also fails closed if the provider returns a different chart ID than requested. | Pass locally in contract tests; real tenant gate remains open |
| Shared-service egress is not overclaimed | The self-hosted connector enforces HTTPS origins, while the managed-service boundary explicitly requires provider allowlists, redirect blocking, DNS-rebinding protection, and network egress policy before accepting tenant-supplied URLs. | Documented boundary; managed-service controls not shipped |
| Preset onboarding fails early without burning Jev credits | `make preset-config-check` reuses the production Preset parser to validate credentials, tenant binding, auth mode, policy, and Jev key presence with zero network requests and zero Jev requests. The provider-only bootstrap path refuses non-Jev mode before provider access, requires counted transport telemetry, then reaches a bounded catalog request without a Jev request. Free-form Preset discovery tries the exact title phrase first and caps its title-term fallback at six provider queries per search call. The optional chart probe reports an actionable re-save remediation when Preset has no saved query context, rather than suggesting an unsafe unscoped fallback. | Pass locally; real tenant gate remains open |
| Generated-shape anti-overfitting trial | A seeded generator creates 24 unfamiliar tenant workspaces / 192 charts across five result envelopes, 12 visualization labels, usable and unusable metric definitions, empty results, ambiguous numerics, and provider failures; the production Preset client/adapter passes catalog, scope, cache, retention, and safe-degradation assertions, then an independent report reviewer checks coverage and rejects mutated pass-looking reports. A generated 64-chart dashboard stress test proves the provider aggregate byte budget fails closed; an engine test separately proves the multi-source serialized Jev budget fails before any Jev call. | Pass locally; provider and live Jev gates remain open |
| Aggregate Preset enterprise proof pack | `make preset-enterprise-proof` runs the hosted connector, boundary, generated-shape, typed Jev, and runtime-shadow trials; each serialized report is independently reviewed and a separate aggregate reviewer verifies the complete five-case set, synthetic-only scope, delivery-disabled state, and explicit non-claims. | 5/5 component reviews pass; aggregate review pass; no live provider or Jev requests |
| Existing enterprise workflows remain the owner | MCP tools return typed decisions and evidence; SignalWeave does not execute arbitrary SQL, tools, DAGs, or notifications. | Pass |
| Regression safety | Full repository tests and lint. | 411 passed, 2 skipped; Ruff clean |

## Reproduction

From the repository root:

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests evaluations
./.venv/bin/python -m evaluations.onboarding_contract_trial --format markdown
./.venv/bin/python -m evaluations.onboarding_adversarial_review --format markdown
./.venv/bin/pytest tests/test_sources.py tests/test_hosted_connections.py -q
make preset-trial
make preset-boundary-trial
make preset-generalization-trial
make preset-jev-contract-trial
make preset-runtime-shadow-trial
# Larger deterministic replay used for the current scale check:
uv run python -m evaluations.preset_runtime_shadow_trial \
  --generated-workspaces 30 \
  --generated-charts-per-workspace 16 \
  --generated-seed 2026092628 \
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
make local-superset-runtime-shadow-trial
make local-superset-runtime-shadow-review
```

The current verified regression result is `411 passed, 2 skipped` with Ruff
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

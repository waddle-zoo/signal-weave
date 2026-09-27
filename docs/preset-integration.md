# Preset integration

SignalWeave can now be started as a small read-only service next to a hosted
Preset workspace. It does not run inside Preset. It calls the Preset Cloud API,
normalizes bounded dashboard/chart evidence, and sends the typed state through
Jev.

## Self-hosted quickstart

This is the shortest supported path today:

```bash
cp examples/preset/.env.preset.example .env.preset
# Edit .env.preset with the Preset workspace URL, read-only API credentials,
# tenant identity, and local SignalWeave bearer tokens.

TYPESAFE_API_KEY_FILE=./secrets/typesafe_api_key \
  docker compose -f docker-compose.preset.yml up --build -d
```

For a deployment that must not place the Preset token values in the Compose
environment, leave the direct token fields empty and use the secrets overlay:

```bash
PRESET_API_TOKEN_NAME_HOST_FILE=/absolute/path/preset-token-name \
PRESET_API_TOKEN_SECRET_HOST_FILE=/absolute/path/preset-token-secret \
SIGNALWEAVE_API_TOKEN_HOST_FILE=/absolute/path/signalweave-api-token \
PUSH_WEBHOOK_TOKEN_HOST_FILE=/absolute/path/push-webhook-token \
TYPESAFE_API_KEY_FILE=/absolute/path/apikey_typesafe \
  docker compose \
    -f docker-compose.preset.yml \
    -f docker-compose.preset.secrets.yml \
    up --build -d
```

The overlay mounts the four credential files as Docker secrets, sets the
corresponding `*_FILE` variables inside the container, and clears the direct
token values from `.env.preset`. The host paths are Compose inputs only and are
not stored in the SignalWeave connection or card stores. The service accepts a
direct value or a mounted file for `SIGNALWEAVE_API_TOKEN` and
`PUSH_WEBHOOK_TOKEN`, never both.

Validate the rendered deployment before starting it:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
PRESET_API_TOKEN_NAME_HOST_FILE=/absolute/path/preset-token-name \
PRESET_API_TOKEN_SECRET_HOST_FILE=/absolute/path/preset-token-secret \
SIGNALWEAVE_API_TOKEN_HOST_FILE=/absolute/path/signalweave-api-token \
PUSH_WEBHOOK_TOKEN_HOST_FILE=/absolute/path/push-webhook-token \
  make preset-compose-check
```

This requires the copied `.env.preset` file, renders both Compose files, and
fails if the TypeSafe mount, any Preset or SignalWeave secret input,
direct-token redaction, or `*_FILE` wiring is wrong. It does not contact Preset
or TypeSafe.

The secure overlay above uses Preset API-token authentication. If the
deployment instead receives a Preset bearer token, use the bearer-specific
example and overlay:

```bash
cp examples/preset/.env.preset.bearer.example .env.preset
PRESET_ACCESS_TOKEN_HOST_FILE=/absolute/path/preset-access-token \
SIGNALWEAVE_API_TOKEN_HOST_FILE=/absolute/path/signalweave-api-token \
PUSH_WEBHOOK_TOKEN_HOST_FILE=/absolute/path/push-webhook-token \
TYPESAFE_API_KEY_FILE=/absolute/path/apikey_typesafe \
  docker compose \
    -f docker-compose.preset.yml \
    -f docker-compose.preset.bearer.secrets.yml \
    up --build -d

PRESET_ACCESS_TOKEN_HOST_FILE=/absolute/path/preset-access-token \
SIGNALWEAVE_API_TOKEN_HOST_FILE=/absolute/path/signalweave-api-token \
PUSH_WEBHOOK_TOKEN_HOST_FILE=/absolute/path/push-webhook-token \
TYPESAFE_API_KEY_FILE=/absolute/path/apikey_typesafe \
  make preset-compose-bearer-check
```

The bearer overlay clears every API-token field before startup; the API-token
and bearer overlays are alternatives and must not be combined.

Before preparing a Compose deployment, validate the runtime environment itself:

```bash
PRESET_URL=https://your-workspace.<region>.app.preset.io \
PRESET_TENANT_ID=your-company \
PRESET_API_TOKEN_NAME=replace-me \
PRESET_API_TOKEN_SECRET=replace-me \
SIGNALWEAVE_TENANT_ID=your-company \
SIGNALWEAVE_PRINCIPAL_ID=signalweave-agent \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  make preset-config-check
```

This is a zero-network configuration check. It validates the production Preset
credential mode, tenant binding, policy, HTTP/OIDC mode, and Jev credential
source, including OIDC claim paths and JWKS timing bounds, without instantiating
a TypeSafe client or reading a provider. It never proves that the credential is
accepted by Preset; use `make preset-bootstrap-check` for that bounded provider
request. The bootstrap report includes the counted Preset HTTP attempts and
fails if the configured client cannot prove that it made the catalog request.

The service listens on `http://127.0.0.1:18000` and exposes the MCP endpoint at
`/mcp`. Connect the customer's agent through the existing identity-aware proxy,
or use the local bearer token for an isolated test. The container automatically
registers one `preset` adapter from `PRESET_URL` and the supplied credentials.
`PRESET_TENANT_ID` or `SIGNALWEAVE_TENANT_ID` is required; the bootstrap path
never assigns an implicit default tenant. API-token and bearer credentials are
mutually exclusive, and unexpected credential fields fail closed.
When using the default token-authenticated HTTP deployment, both
`SIGNALWEAVE_TENANT_ID` and `SIGNALWEAVE_PRINCIPAL_ID` are also required; an
OIDC deployment instead resolves the principal from each verified request.
The default route name is `preset__preset-env`; custom connection IDs are also
supported. Copy
[`examples/preset/insight-card.example.json`](../examples/preset/insight-card.example.json),
replace the dashboard/chart IDs, and use that route in the card's `sources`.

This direct API path requires a Preset plan that includes the Preset API. The
current Preset documentation lists that API as Enterprise-only. Preset's MCP
authentication documentation also describes the MCP server as an Enterprise
add-on, so the interim dual-MCP pattern below is conditional on the customer
having that entitlement; it is not a general fallback for every Preset plan.

The default policy is `cached_results`, with live queries and refreshes disabled.
Raw provider rows are never retained by the connector; receipt retention and
deletion are deployment responsibilities. The card flow remains:

```text
onboard_insight_card
  -> review candidate sources and evidence
  -> approve_insight_card
  -> evaluate_insight_card (Jev shadow run)
  -> caller-owned delivery
```

The engine also enforces a serialized aggregate Jev input budget across all
sources selected for one card. Configure it with
`SIGNALWEAVE_MAX_JEV_PAYLOAD_BYTES` (4,000,000 by default). If a card spans
enough dashboards or related sources to exceed that budget, SignalWeave fails
before a Jev request rather than truncating the evidence or presenting a
partial aggregate as complete. Split the card, narrow its `chart_ids`, or
raise the deployment budget only after reviewing the provider and TypeSafe
limits. Successful evaluations expose the serialized payload size and budget
in telemetry; a rejected shadow receipt records the failed stage and byte
counts for audit.

Standalone chart reads also require a usable saved `queries` list before making
the provider POST request; malformed or missing saved query context fails locally
instead of becoming a provider-side invalid or unbounded request. Saved numeric
`row_limit` values are normalized to a positive value within the connection
policy; zero and negative values become `1`, while boolean or malformed values
fail closed before provider I/O.

The low-level `PresetCloudClient` is bounded even when used without a
`PresetAdapter`: it defaults to 500 result rows and a 1 MB response. The
adapter applies the connection policy when its limits were left at those safe
defaults, while an explicitly tighter client limit remains in force. This
keeps provider smoke tests and custom integrations from accidentally creating
an unbounded response path without silently shrinking a customer's configured
policy.

After the configuration check, start with the no-credit bootstrap preflight
before onboarding a card:

```bash
make preset-bootstrap-check
```

This authenticates the configured Preset connection and reads one bounded
dashboard catalog page. It verifies tenant/principal configuration and that
the runtime is Jev-only; token deployments report static tenant/principal
identity while OIDC deployments report request-scoped identity. It makes zero
Jev calls and never reads chart data.
It fails for an empty workspace so a customer does not mistake a configured
credential for a usable onboarding target.

To avoid copying dashboard IDs by hand, use the bounded readiness target with a
title substring:

```bash
PRESET_BOOTSTRAP_DASHBOARD_QUERY="executive command" \
  make preset-readiness
```

This uses Preset's server-side title filter, follows at most five pages by
default, and runs the selected dashboard through the same production adapter
used by card onboarding. It passes only when exactly one dashboard matches and
the dashboard is healthy. Zero matches, multiple matches, a missing dashboard
ID, or a result set that hits the page cap fail closed; SignalWeave never picks
the first dashboard from an ambiguous search. Adjust the bound explicitly when
needed:

```bash
PRESET_BOOTSTRAP_DASHBOARD_QUERY="growth" \
PRESET_BOOTSTRAP_MAX_PAGES=20 \
PRESET_BOOTSTRAP_PAGE_SIZE=50 \
  make preset-readiness
```

The readiness report is still a provider/onboarding gate, not a decision. It
makes zero Jev calls and does not create or approve a card. After it passes, use
the free-form `preset-live-trial` draft flow below so a human can review the
goal, source, and delivery policy before the first Jev shadow run.

After choosing one real dashboard and chart, run the no-credit provider smoke
probe before spending a Jev call:

```bash
PRESET_BOOTSTRAP_DASHBOARD_ID=123 \
PRESET_BOOTSTRAP_CHART_ID=456 \
  make preset-provider-smoke
```

This exercises the dashboard-scoped chart-data endpoint and fails unless it
returns usable normalized observations. It does not require a TypeSafe key,
create a card, call Jev,
approve anything, or deliver a notification. A successful probe proves the
provider boundary; it is still not proof that the business card is correct. A
`metadata_only` connection refuses this probe rather than bypassing its data
policy.
If the provider reports that the chart has no saved query context, the report
includes the concrete remediation: re-save the chart in Preset and rerun the
probe. SignalWeave does not replace that context with an unscoped query when
dashboard filter state could be bypassed.

For a full dashboard readiness check before creating a card, omit the chart ID:

```bash
PRESET_BOOTSTRAP_DASHBOARD_ID=123 \
  make preset-dashboard-readiness
```

This runs the dashboard through the production Preset adapter, applies the
aggregate snapshot budget, reports chart-quality failures and remediations, and
still makes zero Jev calls. A failing dashboard readiness check is an
onboarding gate, not a hidden partial-evidence success.

Preset API credentials must be kept in an untracked secret file or deployment
secret manager. They are loaded into memory only to construct the adapter and
are never stored in cards, MCP payloads, or connection metadata. The customer
should use the smallest Preset workspace permissions that allow the required
read-only artifacts. Environment bootstrap requires HTTPS for both `PRESET_URL`
and `PRESET_API_BASE_URL`; there is no insecure-provider override. The HTTPS
origin check is a self-hosted transport invariant, not a managed-service egress
control: a future shared service must add provider allowlists, redirect
blocking, DNS-rebinding protection, and network-level egress policy before it
accepts tenant-supplied connection URLs.

The connector enforces the configured `max_result_rows` and
`max_snapshot_bytes` limits on both the Preset token exchange and workspace
responses while consuming the response stream, before parsing or forwarding
the body. It checks both materialized rows and provider reported
`rowcount`/`sql_rowcount` metadata, so a truncated response cannot hide a
larger result behind a small returned page. Malformed count metadata
also fails closed. Standalone chart reads lower the saved-chart row limit
before calling Preset; dashboard reads use Preset's chart-specific data
endpoint so the provider can apply dashboard filter scope and access checks,
then fail closed if the returned result exceeds the SignalWeave row or byte
budget. It also fails closed when Preset returns an asynchronous `202` chart
response; this bounded connector does not pretend a pending job is an empty
result or poll a provider-owned job queue. It does not silently truncate a time
series and invent a current value. Malformed chart responses with a missing,
scalar, or mixed-object `result` envelope, or invalid JSON also fail closed as
provider-policy errors; they are not converted to an apparently empty chart.
The same fail-closed rule applies when a provider returns HTTP 200 but embeds a
non-success query status inside a result item. Only known successful states
(`success`, `completed`, `complete`, or `ok`) and an omitted status are accepted;
`pending`, `failed`, `timed_out`, unknown, and future provider states fail closed
instead of becoming apparently empty data.
An embedded non-empty result-item `error` is also a provider-policy failure;
warnings remain visible but do not by themselves block a successful result.
Even when a 202 response includes a provider `result_url`, the connector does
not follow it or make a second-host request. Superset documents that field in
its [async chart response schema](https://superset.apache.org/developer-docs/api/schemas/chartdataasyncresponseschema/).
Supporting async completion would need a verified Preset contract for
same-workspace polling, timeout, status, and filter-context preservation; until
then the safe result is an explicit failure.
After chart fan-out, the adapter applies the same byte budget to the aggregate
dashboard snapshot. If a large dashboard would exceed it, SignalWeave drops the
entire observation/evidence payload and returns an explicit failed-quality
receipt; it never sends a partial dashboard to Jev as if it were complete. Use
`chart_ids` source parameters or split the workflow when a dashboard is larger
than the configured budget.
Transient rate limits and 5xx responses receive a bounded retry; ordinary
client errors do not retry. Mounted secret files are supported with
`PRESET_API_TOKEN_NAME_FILE` and `PRESET_API_TOKEN_SECRET_FILE`.

`cached_results` sends `force=false`, which asks the Superset-compatible
endpoint to use its cache when available. Standalone chart queries also carry
a bounded row limit. Dashboard-scoped reads use Preset's saved chart query
context and enforce the response budget after the provider returns. It is not a
provider-independent guarantee that a cache miss will never execute work. A
strict cache-only contract needs a Preset result/cache endpoint or a customer
proxy that exposes that distinction; SignalWeave fails closed on payload-size
and row-limit violations but cannot infer provider execution cost from the
response alone.

The repeatable source-boundary trial is documented in
[`docs/preset-integration-trial.md`](preset-integration-trial.md). It is a
fixture-backed transport proof, not a substitute for a customer-authorized
Preset smoke test or a live Jev shadow run.

For a real, delivery-disabled acceptance check after the service is running:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  PRESET_URL=https://your-workspace.<region>.app.preset.io \
  uv run python scripts/live_card_check.py \
  --card examples/preset/insight-card.example.json
```

The card must contain real IDs, have `status="approved"`, and the deployment
must load its Preset and SignalWeave credentials. This command invokes the live
Jev path in delivery-disabled shadow mode and does not contact the destination.

For the stronger free-form onboarding proof, use the live trial runner. First
discover candidates and write a reviewable draft without approving it:

```bash
PRESET_TRIAL_GOAL="Monitor the executive growth dashboard for meaningful changes" \
PRESET_TRIAL_WHY="Tell Growth leadership when the evidence warrants investigation" \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  make preset-live-trial
```

After inspecting the onboarding artifact and confirming the sources and
delivery policy, run the separate approval target with the same output path:

```bash
PRESET_TRIAL_GOAL="Monitor the executive growth dashboard for meaningful changes" \
PRESET_TRIAL_WHY="Tell Growth leadership when the evidence warrants investigation" \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  make preset-live-trial-approve
```

The approval target is bound to the exact draft artifact written by the first
command. It loads the persisted card from the same SignalWeave store, checks
the card ID, version, and canonical digest, and refuses to approve if the
stored card or the request changed after review. It does not rerun discovery
and silently approve a new draft. If a reviewer edits the card, run onboarding
again and review the newly written artifact before approving it.

Before approval, the runner also rechecks the draft's non-secret Preset request
counts, dashboard-search bound, path-delta consistency, credential-load proof,
secret-redaction proof, explicit approval requirement, delivery-disabled state,
and data-policy telemetry. A cached-results draft must prove `force=false`; a
live-query draft must prove `force=true` plus explicit live-query and refresh
permissions; metadata-only policy cannot satisfy a chart-data shadow. A draft
whose transport evidence or policy proof was edited or is internally
inconsistent is rejected before `approve_insight_card` or any Jev call.

The live runner auto-detects the sole configured Preset adapter, so it does
not assume the default connection ID. Pass `--adapter` when multiple Preset
connections are installed and the operator has selected one explicitly.

This is an acceptance test against a real workspace, not a synthetic benchmark;
it consumes live Jev calls and must be run with a customer-approved shadow card
policy. The runner also verifies that onboarding returned
`approval_required=true` and `delivery_enabled=false` before approval. The
generated receipt must show `evaluator=jev-latest`, non-empty observations and
evidence, at least one Preset chart-data request and one Jev request during the
first evaluation, zero additional Preset or Jev requests during the replay,
and `delivery_enabled=false` before the trial is considered successful. The
approved report must also contain an exact-draft approval basis, prove that the
configured Preset credential was loaded, prove the selected data-policy mode
and bounded result/snapshot limits, and prove that the provider secret values
were absent from the serialized MCP artifacts. The independent reviewer
recomputes those invariants from the serialized report instead of trusting the
runner's `passed` flag. The runner records only non-secret Preset path counts,
policy telemetry, and redaction booleans for this transport proof, including a
bounded catalog-search count (at most 21 dashboard catalog requests in this
one-card flow). It still does not prove operator usefulness or production
delivery reliability.

## Can a hosted Preset customer use SignalWeave without hosting it?

Not with the repository as shipped. That becomes possible only after a managed
SignalWeave service is deployed and passes the boundary below. The intended
hosted architecture is:

```text
Preset Cloud API
      ^
      | customer-authorized read-only credential
      |
managed SignalWeave tenant worker
      |
      +-- bounded evidence -> Jev -> shadow receipt
      |
customer agent / scheduler / delivery system
```

The customer would connect their agent to a hosted SignalWeave MCP endpoint,
authorize one Preset workspace, and create cards against that workspace. The
managed service would own the credential vault, tenant isolation, polling or
webhook intake, Jev key, retention, and receipt store. The customer's existing
agent or scheduler would still own delivery and side effects.

The repository does not claim this managed path exists yet. It still needs an
OAuth or secure connection bootstrap flow, KMS-backed credentials, shared
transactional storage, per-tenant worker isolation, retention/deletion policy,
and a hosted service deployment.

## What Preset itself can and cannot provide

Preset documents a native remote MCP server that lets AI clients connect to
Preset with Preset-managed OAuth or API-token authentication, subject to the
MCP entitlement. That is useful when an agent wants to call Preset directly,
but it is not an extension point for installing SignalWeave's server-side Jev
decision layer inside Preset. Preset's native Alerts & Reports feature is
documented around email and Slack delivery, not a generic SignalWeave callback.

That leaves three practical options:

1. **Managed SignalWeave service — recommended.** SignalWeave calls Preset's
   API directly with a customer-authorized credential. This preserves the
   bounded evidence and Jev decision boundary.
2. **Customer-side dual-MCP agent — interim.** The agent connects to both
   Preset's MCP and SignalWeave's MCP, then passes approved Preset evidence into
   a card evaluation. This avoids giving SignalWeave a Preset credential but
   makes the agent responsible for evidence transport and is weaker for
   scheduled, repeatable monitoring. It is the practical option for a hosted
   customer without the direct Preset API entitlement.
3. **Preset-triggered relay.** If a customer's Preset plan and alerting setup
   can reach an approved relay, the relay can call SignalWeave's evaluation
   webhook. This should be treated as a trigger only; SignalWeave still needs
   its own read-only Preset access to retrieve the full evidence bundle.

For the product, the first win is the self-hosted compose path in this file.
The next hosted milestone is a single-tenant managed Preset connection—not a
general cloud platform or a Preset UI plugin.

## Official Preset references

- [Preset API](https://docs.preset.io/docs/the-preset-api)
- [Preset API reference](https://api-docs.preset.io/)
- [Preset MCP server authentication](https://docs.preset.io/docs/preset-mcp-server-authentication)
- [Preset Alerts & Reports](https://docs.preset.io/docs/alerts-reports)
- [Preset dashboard embedding](https://docs.preset.io/docs/dashboard-embedding)
- [Preset API update notes: dashboard-filtered chart data](https://docs.preset.io/docs/update)

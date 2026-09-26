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

The service listens on `http://127.0.0.1:18000` and exposes the MCP endpoint at
`/mcp`. Connect the customer's agent through the existing identity-aware proxy,
or use the local bearer token for an isolated test. The container automatically
registers one `preset` adapter from `PRESET_URL` and the supplied credentials.
The default route name is `preset__preset-env`; copy
[`examples/preset/insight-card.example.json`](../examples/preset/insight-card.example.json),
replace the dashboard/chart IDs, and use that route in the card's `sources`.

This direct API path requires a Preset plan that includes the Preset API. The
current Preset documentation lists that API as Enterprise-only. Customers on a
plan without API access can still use the interim dual-MCP pattern below, but
cannot use this direct scheduled adapter until they have an approved API or
bridge path.

The default policy is `cached_results`, with live queries, refreshes, and raw
result retention disabled. The card flow remains:

```text
onboard_insight_card
  -> review candidate sources and evidence
  -> approve_insight_card
  -> evaluate_insight_card (Jev shadow run)
  -> caller-owned delivery
```

Preset API credentials must be kept in an untracked secret file or deployment
secret manager. They are loaded into memory only to construct the adapter and
are never stored in cards, MCP payloads, or connection metadata. The customer
should use the smallest Preset workspace permissions that allow the required
read-only artifacts.

The connector enforces the configured `max_result_rows` and
`max_snapshot_bytes` limits. It lowers the saved-chart row limit before calling
Preset and fails closed if the provider returns more rows or bytes than the
connection permits; it does not silently truncate a time series and invent a
current value. Mounted secret files are supported with
`PRESET_API_TOKEN_NAME_FILE` and `PRESET_API_TOKEN_SECRET_FILE`.

`cached_results` sends `force=false` and bounds the query, which asks the
Superset-compatible endpoint to use its cache when available. It is not a
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

The card must contain real IDs and the deployment must load its Preset and
SignalWeave credentials. This command invokes the live Jev path and should be
run only against an approved shadow card; it does not contact the destination.

## Can a hosted Preset customer use SignalWeave without hosting it?

Yes, but that requires a managed SignalWeave service. The hosted architecture
is:

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
Preset with Preset-managed OAuth or API-token authentication. That is useful
when an agent wants to call Preset directly, but it is not an extension point
for installing SignalWeave's server-side Jev decision layer inside Preset.
Preset's native Alerts & Reports feature is documented around email and Slack
delivery, not a generic SignalWeave callback.

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
- [Preset MCP server authentication](https://docs.preset.io/docs/preset-mcp-server-authentication)
- [Preset Alerts & Reports](https://docs.preset.io/docs/alerts-reports)
- [Preset dashboard embedding](https://docs.preset.io/docs/dashboard-embedding)

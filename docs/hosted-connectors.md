# Hosted connectors

SignalWeave can sit outside a customer's BI deployment. The customer keeps
Preset, Hex, or Looker and connects a tenant-scoped, read-only credential to a
SignalWeave deployment. SignalWeave calls the hosted API over HTTPS, normalizes
the returned artifacts, and sends only bounded evidence to Jev.

```text
customer agent or scheduler
            |
            v
     SignalWeave MCP/API
            |
            v
  Preset / Hex / Looker API
            |
            v
   bounded typed evidence -> Jev -> evidence bundle
```

## Connection contract

`HostedConnection` stores the tenant, provider, hosted workspace URL, and an
opaque `credential_ref`. It never stores an access token, API secret, or client
secret. A deployment supplies a `HostedCredentialVault` implementation and the
adapter factory resolves the secret only while constructing a short-lived
source client.

The repository includes an in-memory vault for tests and a SQLite connection
metadata store for local or single-process deployments. A production cloud
control plane should replace those with a KMS-backed vault and a shared
transactional database.

When one process serves multiple connections for the same provider, the
adapter factory gives each connection a stable route such as
`preset__northstar-preset`. This keeps source references unambiguous and lets
request-scoped tenant authorization select one connection without allowing a
provider name collision.

## Data policy

Every connection has an explicit `HostedDataPolicy`:

- `metadata_only` discovers dashboards, projects, Looks, owners, and
  relationships without fetching result rows;
- `cached_results` permits bounded result retrieval using the provider's
  existing cache or latest completed run; and
- `live_query` requires the separate `allow_live_queries=true` guard.

Raw results are not retained by the connector itself. A cloud deployment must
enforce retention and encryption outside the adapter layer. `max_result_rows`
and `max_snapshot_bytes` keep a provider response from becoming an unbounded
Jev input.

## Provider coverage

### Preset Cloud

`PresetCloudClient` supports the documented Preset API-token exchange at
`api.app.preset.io/v1/auth/` and then calls the workspace's Superset-compatible
dashboard, chart, and chart-data endpoints. `PresetAdapter` reuses the shipped
Superset artifact normalization while reporting `adapter="preset"` and the
customer tenant in the resource contract.

Preset MCP remains useful for interactive onboarding by a customer-owned agent,
but recurring monitoring should use the direct hosted API path. The connector
does not create or delete dashboards, edit permissions, or execute arbitrary
SQL.

### Hex Cloud

`HexCloudClient` discovers projects, reads project metadata and recent runs, and
can start a project only when the connection is explicitly configured for live
queries. `HexAdapter` turns bounded outputs from explicitly named Hex cell
output endpoints into observations and preserves run metadata as evidence. A
project or run reference alone yields execution evidence, not invented metric
rows. It does not mutate projects or invoke Hex agent threads.

### Looker Cloud

`LookerCloudClient` supports dashboard and Look discovery, metadata retrieval,
and Look result retrieval with an explicit cache flag. `LookerAdapter` treats
dashboard metadata and Look results as separate resource types and keeps the
Looker credential's user-bound permissions intact. It does not use admin
impersonation or accept arbitrary SQL from cards.

## Recommended hosted deployment

The first cloud pilot should contain:

1. OIDC-authenticated SignalWeave tenants.
2. An OAuth/token connection flow that writes only `credential_ref` metadata.
3. KMS-backed credentials and per-tenant adapter workers.
4. Jev-only evaluation with the same approval, evidence, freshness, and
   idempotency gates as the self-hosted runtime.
5. Customer-owned scheduling and delivery during the pilot.

The hosted service should not become a replacement for Airflow, Temporal,
Looker scheduling, or an agent runtime. It should provide an optional managed
polling trigger later, while keeping source access, decisioning, and delivery
as separate auditable boundaries.

If a customer's hosted instance is private or data cannot leave its network,
the later option is a small outbound-only SignalWeave Bridge. Preset Cloud and
Hex normally do not need that bridge because their APIs are already hosted;
private Looker or warehouse connections may.

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
source client. Hosted connection URLs must use HTTPS and cannot contain inline
credentials; local HTTP development remains available through the separate
unmanaged Superset development connector, not this hosted-connection path.
The free-form `metadata` field is also rejected when its key looks like a
token, secret, password, authorization, or credential field; it is descriptive
metadata, not a second secret store.

The repository includes an in-memory vault for tests and a SQLite connection
metadata store for local or single-process deployments. A production cloud
control plane should replace those with a KMS-backed vault and a shared
transactional database.

When one process serves multiple connections for the same provider, the
adapter factory gives each connection a stable route such as
`preset__northstar-preset`. This keeps source references unambiguous and lets
request-scoped tenant authorization select one connection without allowing a
provider name collision.

Credential mode is part of the connection contract. Preset API-token
connections require only the token name and secret; bearer connections require
only an access token; unsupported OAuth declarations fail closed rather than
falling back to whichever secret shape happens to be present.

## Data policy

Every connection has an explicit `HostedDataPolicy`:

- `metadata_only` discovers dashboards, projects, Looks, owners, and
  relationships without fetching result rows;
- `cached_results` permits bounded result retrieval using the provider's
  existing cache or latest completed run; and
- `live_query` requires the separate `allow_live_queries=true` guard.

Raw results are never retained by the connector itself; only bounded normalized
observations and evidence enter the decision receipt. A cloud deployment must
enforce receipt retention, deletion, encryption, and data residency outside the
adapter layer. `max_result_rows` and `max_snapshot_bytes` keep a provider
response from becoming an unbounded Jev input.

## Provider coverage

### Preset Cloud

`PresetCloudClient` supports the documented Preset API-token exchange at
`api.app.preset.io/v1/auth/` and then calls the workspace's Superset-compatible
dashboard, chart, and chart-data endpoints. `PresetAdapter` reuses the shipped
Superset artifact normalization while reporting `adapter="preset"` and the
customer tenant in the resource contract.

Preset currently documents the direct Preset API as an Enterprise-plan
capability. Preset's current MCP authentication documentation also describes
the MCP server as an Enterprise add-on. A customer must therefore have the
relevant Preset entitlement for either direct unattended API access or the
remote-MCP fallback; the remote-MCP path is not a universal workaround for a
plan without API access.

The connector sends `force=false` for cached-results requests and enforces the
connection's response byte and row budgets. That is a cache preference, not a
provider-independent cache-only guarantee: a strict no-query-on-cache-miss
contract requires a provider result endpoint or a customer proxy that exposes
cache state. For dashboard monitoring, it calls Preset's chart-specific data
endpoint with `filter_dashboard_id`; this is important because the provider,
not SignalWeave, owns dashboard filter scope, default values, and the access
check that the chart belongs to the dashboard. Standalone chart reads continue
to use the saved-query data endpoint and have no dashboard filter context. A
dashboard-scoped response must also include Preset's `dashboard_filters`
metadata; otherwise the connector fails closed rather than treating a possibly
unfiltered 200 response as evidence.

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

## Exact managed-service boundary

The repository currently ships a connector and a self-hosted deployment path;
it does not ship a managed SignalWeave service. The boundary is deliberate:

| Capability | Current state | Required before claiming managed hosting |
| --- | --- | --- |
| Preset API-token or bearer adapter | Shipped and fixture-tested | Real customer acceptance run |
| Tenant-scoped source routes and card evaluation | Shipped and unit/integration-tested | External identity-provider acceptance |
| Jev-only typed judgment and delivery-disabled shadow receipt | Shipped in the runtime | Live Jev shadow run over customer evidence |
| Customer-owned scheduler and delivery | Supported | Customer operational sign-off |
| Public SignalWeave MCP/API endpoint | Not provided as a hosted service | Authenticated ingress, rate limits, abuse controls, and tenancy |
| OAuth connection onboarding | Modelled as a future boundary; Preset adapter currently fails OAuth closed | Callback handling, state/PKCE validation, token rotation, revocation |
| Secret storage | In-memory vault for local use; vault interface for deployment | KMS/HSM-backed storage, rotation, redaction, and audit |
| Durable multi-tenant state | SQLite for local/single-process use | Shared transactional store, migrations, backups, and tenant isolation |
| Polling/workers | Customer-owned today | Per-tenant workers, leases, retries, idempotency, and quotas |
| Retention, deletion, and residency | Deployment responsibility | Enforced policy, deletion jobs, legal holds, and regional controls |

Until the right-hand column is implemented and tested, the supported hosted
customer story is: the customer runs SignalWeave near their agent or uses an
approved customer-owned relay, while Preset remains the hosted source. A
customer can connect Preset's native MCP to its own agent for interactive work
when entitled, but that does not install SignalWeave inside Preset and does not
create unattended SignalWeave monitoring.

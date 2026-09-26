# Hosted connector trial

This is the current deterministic proof for the hosted-connector slice. It
uses `httpx.MockTransport` to emulate provider responses and exercises the same
clients and adapters used by a real deployment. It deliberately does not claim
that a mock can validate a customer's plan, permissions, network, or rate
limits.

Run it with:

```bash
uv run pytest tests/test_hosted_connections.py -q
```

The current run covers 35 passing cases:

| Boundary | What is proven |
| --- | --- |
| Credential handling | Preset API-token exchange works; persisted connection metadata contains only a vault reference |
| Credential mode binding | Preset API-token, bearer, and unsupported OAuth connection declarations fail or build explicitly according to their credential shape |
| Preset | Hosted dashboard/chart data is normalized into SignalWeave observations and tenant contracts |
| Preset policy | Metadata-only mode does not call chart-data endpoints |
| Preset safety policy | Expired API tokens refresh once; auth and workspace 429/5xx responses retry with a bounded delay; row and response-byte limits fail closed |
| Preset query mode | Cached mode sends `force=false`; live mode requires explicit refresh permission and sends `force=true` |
| Preset fixture trial | Three varied workspaces and 13 chart definitions pass the independent integration harness |
| Hex | Project metadata, completed-run state, explicit cell-output retrieval, and cursor pagination work |
| Hex search | The adapter reports that the API is cursor-paginated and locally filters a bounded page rather than pretending native text search exists |
| Looker | A cached Look result is retrieved with the provider cache flag and normalized into observations |
| Tenant isolation | Connection lookup, adapter routes, catalog scope, and shared-runtime defaults do not cross tenants |
| Tenant bootstrap | Explicit hosted connections that disagree with the configured runtime tenant fail closed |
| Jev boundary | `build_runtime` constructs hosted adapters around the existing Jev-only runtime without introducing a heuristic path |

The full repository suite is also the regression gate:

```text
The repository suite count is maintained by CI; run `make verify` and
`make preset-trial` for the current result.
```

## What remains unproven

The trial is an adapter and boundary proof, not a cloud-launch certification.
Before offering hosted access to customers we still need:

- real Preset, Hex, and Looker account tests with customer-approved read-only
  credentials;
- OAuth callbacks and token refresh;
- a KMS-backed credential vault and shared transactional connection store;
- real provider rate-limit headers, quota behavior, and plan-specific retry semantics;
- source-plan capability checks and explicit bootstrap reports;
- per-tenant worker isolation and request-scoped authorization in the hosted
  control plane; and
- retention, deletion, data residency, and incident-audit controls.

That is why the roadmap marks the hosted adapters complete while keeping the
managed SignalWeave Cloud control plane open.

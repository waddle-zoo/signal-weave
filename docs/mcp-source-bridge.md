# Configured MCP source bridge

`signalweave.mcp_source.build_mcp_sources(config_path)` loads a deployment-owned
JSON manifest into `MCPSourceAdapter` instances. The runtime registers them with
`SourceRegistry` when `SIGNALWEAVE_MCP_SOURCES_FILE` selects the manifest.
For local setup, use tenant `local` consistently for the connection, descriptor,
snapshot, and local principal. Change all four together for another tenant.

The bridge provides reusable company MCP connectivity with an explicit typed
measurement contract. An MCP server must expose a reviewed read tool returning
a SignalWeave `ResourceSnapshot` in `CallToolResult.structuredContent`. A company
gateway can perform this normalization when the upstream API has a different
shape. The bridge does not infer metric definitions, convert arbitrary API
responses, or discover arbitrary tools to execute.

## Manifest

```json
{
  "version": 1,
  "connections": [
    {
      "name": "company_metrics",
      "tenant_id": "local",
      "read_only": true,
      "transport": {
        "type": "streamable-http",
        "url": {"env": "COMPANY_MCP_URL"},
        "headers": {"Authorization": {"env": "COMPANY_MCP_AUTHORIZATION"}}
      },
      "timeout_seconds": 30,
      "max_response_bytes": 1000000,
      "resources": [
        {
          "descriptor": {
            "adapter": "company_metrics",
            "resource": "measurement:orders",
            "kind": "measurement",
            "title": "Completed orders",
            "description": "Completed orders in the approved seven-day window.",
            "contract": {
              "tenant_id": "local",
              "domain": "operations",
              "metric_names": ["completed_orders"],
              "population": "Completed orders, excluding test accounts",
              "grain": "day",
              "freshness_sla_hours": 24,
              "authorized": true
            }
          },
          "source_key": "upstream-orders",
          "tool": "read_measurement",
          "arguments": {"measurement": "orders", "window_days": 7},
          "snapshot_pointer": ""
        }
      ]
    }
  ]
}
```

`name` must be unique across connections (and across all registry adapters).
Each resource locator is an opaque exact-match string, unique within its
connection. A descriptor must explicitly bind both its adapter and contract
tenant to its connection. Catalog discovery and authorization read only this
manifest; they do not contact the MCP server. Disabled descriptors are omitted.
The registry's existing local catalog search fallback applies; this bridge does
not claim native server search or unbounded enterprise catalog discovery.

The deployment operator asserts `read_only: true` after reviewing the exact tool
and fixed arguments under the configured credentials. Server annotations such
as `readOnlyHint` are not authority. MCP cannot prove a tool lacks side effects.
Protect the manifest like executable deployment configuration, and scope server
credentials to the named tenant and approved reads.

For stdio, replace the transport with:

```json
{
  "type": "stdio",
  "command": ["/opt/company/venv/bin/python", "/opt/company/read_server.py"],
  "env": {"COMPANY_API_TOKEN": {"env": "DEPLOYMENT_COMPANY_API_TOKEN"}}
}
```

`command` is an argv array passed to the SDK subprocess transport without a
shell or interpolation. Do not put credentials in argv or fixed arguments.
Only referenced secrets and the SDK's minimal default process environment are
passed to the child. Server stderr is discarded because it can expose secrets.
This transport runs operator-approved executables; it is not a process sandbox.

HTTP accepts a literal URL or an environment reference. Use a reference if the
endpoint contains secrets. Header values must be environment references; the
environment value is the complete header value, including any `Bearer ` prefix.
References resolve at inspection time, allowing rotation. HTTP redirects,
ambient proxy configuration, and ambient HTTP credentials are disabled. URLs
must use HTTP(S), without embedded username/password or fragments. Use HTTPS
outside trusted local deployments; endpoint/network authorization belongs to
the operator. These settings are never accepted from a card.

## Snapshot contract and binding

An example tool's `structuredContent` is:

```json
{
  "source_key": "upstream-orders",
  "adapter": "company_metrics",
  "resource": "measurement:orders",
  "title": "Completed orders",
  "contract": {"tenant_id": "local", "authorized": true},
  "source_captured_at": "2026-09-29T12:00:00Z",
  "observations": [
    {
      "source_key": "upstream-orders",
      "metric": "completed_orders",
      "current": 120,
      "baseline": 100,
      "unit": "count"
    }
  ],
  "evidence": []
}
```

`snapshot_pointer` is an RFC 6901 JSON pointer relative to `structuredContent`:
the empty string selects the whole object; `/data/snapshot` selects a wrapper.
Object keys support `~0` and `~1`; arrays use nonnegative decimal indices.
Text content is never parsed as a fallback, and arbitrary field mapping is not
supported. The server must supply the typed measurement meaning and values.

Snapshots may also supply `analytical_comparisons`, the typed
`list[AnalyticalComparison]` contract in `diagnostics.py`, for additive or rate
decomposition. Normalization retains these comparison tables, controlling totals,
periods, coverage assertions, and query references. An analytical-only snapshot
with empty `observations` and `evidence` is accepted. The downstream diagnostics
layer validates reconciliation and computes contributions; the bridge does not
infer or manufacture missing comparison data. Comparisons remain subject to the
same snapshot identity and byte-budget checks.

When a reviewed resource promises specific numerical comparisons, declare their
exact `AnalyticalComparison.key` values in the manifest's
`resources[].descriptor.contract.required_comparison_keys`, for example:

```json
{"tenant_id": "local", "required_comparison_keys": ["activity-breakdown"]}
```

The list defaults to empty and is bounded to 20 keys. Conversational proposal
and onboarding copy these reviewed catalog requirements onto each selected
`SourceRef.required_comparison_keys`, including automatically recommended
sources. Caller fields in `selected_sources` and returned snapshot contents do
not supply or replace these requirements. A valid observation alone cannot
satisfy a required comparison: omitting a declared key triggers the existing
missing-comparison check during evaluation.

Optional related sources also carry their catalog comparison keys but remain
optional; this field does not promote them to required sources. Saved card
anchors retain their reviewed keys across later catalog changes. Existing
cards are not retroactively modified; review a new proposal to adopt changed
catalog requirements. Explicitly authored cards may still declare comparison
keys on their sources. The declaration does not create comparison data or prove
its measurement meaning, and card approval is still required. See
[local investigations](local-investigations.md) for the measurement contract.

The bridge checks snapshot adapter, resource, explicit tenant, authorization,
and source key against the registration. Every observation and evidence item
must carry the configured `source_key`; missing/default or foreign keys fail
closed. After validation, all these keys are rebound to the calling card's
`SourceRef.key`, so different cards can safely alias the same registration.
The descriptor owns the returned title, description, and contract. Remote
non-healthy source status is retained conservatively, and a healthy response
cannot erase a configured non-healthy status.

`SourceRef.parameters` must be empty. Even apparently harmless limits are
rejected, since this version declares no caller argument bounds. The caller
cannot override tools, arguments, commands, headers, URLs, or JSON pointers.
Both direct inspection and registry inspection authorize before connecting;
the parent must supply the authenticated tenant scope to the registry. Direct
calls can supply `authorized_tenants` explicitly; omitted scope means the
deployment's configured connection scope, not a per-user ACL.

`captured_at` is set locally upon successful receipt and validation.
`source_captured_at` is preserved when supplied by the approved provider;
otherwise the normal registry/engine receipt-time freshness fallback applies.
The deployment remains responsible for the provider's measurement accuracy and
timestamp semantics.

## Limits and failures

Manifest reads stop after 1,000,000 bytes. The manifest permits at most 100
connections and 500 resources per connection, rejects duplicate JSON keys and
unknown configuration fields, and rejects non-finite JSON numbers.
Each inspection opens and closes its own SDK session, initializes it, then
executes exactly the registered tool call. No tool discovery, prompts, remote
resource access, sampling, or arbitrary tool execution is added by this bridge.

`timeout_seconds` bounds connection, initialization, call, and session cleanup
(default 30, maximum 300). Cancellation propagates; the SDK may need additional
bounded subprocess termination time while unwinding. `max_response_bytes`
(default 1,000,000, range 1,024–10,000,000) limits the entire serialized MCP result,
including text and unused wrappers, and the final normalized snapshot. The SDK
parses/buffers transport messages before this check: this is an evidence admission
budget, not a hard network or process-memory cap. Deployments exposed to hostile
servers also need gateway frame/body limits and process resource isolation.

Transport exceptions, missing environment references, malformed snapshots,
identity mismatch, timeouts, `isError`, and snapshot `error` values produce fixed
redacted failure messages with no observations, evidence, or remote metadata.
SDK transport/HTTP diagnostics are suppressed in the bridge's asynchronous
context, and stdio stderr is discarded. Manifest errors expose neither paths
nor validation inputs. Successful evidence remains provider-owned data; do not
put credentials in successful measurement payloads or catalog metadata.

## Integration and tests

```python
from signalweave.mcp_source import build_mcp_sources
from signalweave.sources import SourceRegistry

registry = SourceRegistry(
    build_mcp_sources("/etc/signalweave/mcp-sources.json"),
    authorized_tenants={"local"},
)
```

Tests can inject `build_mcp_sources(path, transport_factory=factory)`.
The factory receives an isolated `MCPConnection` copy and returns an async context
manager yielding a session with async `initialize()` and
`call_tool(name, arguments) -> mcp.types.CallToolResult`. It is a trusted testing
or embedding seam, not a caller-configurable capability.

`tests/test_mcp_source.py` covers fixed calls, authorization before I/O, hostile
identity and error payloads, wrapper pointers, manifest validation, byte limits,
timeouts, cancellation, credential references, HTTP policy, and a real local
stdio FastMCP server through the installed MCP SDK. It needs no live credentials
or external network service.

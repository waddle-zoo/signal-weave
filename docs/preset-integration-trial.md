# Preset hosted integration trial

This is the deterministic integration proof for the Preset connector. It
drives the production `PresetCloudClient` and `PresetAdapter` through a mocked
HTTP transport. The fixture intentionally contains three workspace shapes:

- Northstar: eight charts spanning line, bar, pie, heatmap, bubble, pivot, a
  custom plugin, and an unknown metric definition;
- Harbor Bank: one healthy chart, one provider outage, and one malformed saved
  chart; and
- Orbitworks: one healthy chart and one empty result.

The result envelopes vary between `data`, `records`, `rows`, `values`, and
columnar `columns`/`data` forms. The trial is data-driven from
[`evaluations/data/preset-workspaces.json`](../evaluations/data/preset-workspaces.json),
not from product conditionals or a Northstar-only code path.

Run it with:

```bash
make preset-trial
```

That command is also covered by `tests/test_preset_hosted_trial.py`, so a
clean checkout can run the proof through the normal repository test gate.

The trial currently proves:

| Boundary | Observed result |
| --- | --- |
| Workspace isolation shape | Three independently tenant-bound workspaces inspected |
| Chart coverage | 13 chart definitions across 12 visualization types, 9 with usable observations, 4 deliberately degraded |
| Result normalization | 17 observations across the varied envelopes and chart definitions |
| Dashboard filter context | Every dashboard chart read uses Preset's chart-specific data endpoint with the dashboard ID, so provider-side in-scope filter defaults and access checks are applied |
| Filter response contract | Dashboard reads fail closed unless the provider returns `dashboard_filters` metadata confirming the dashboard-context response shape |
| Partial failure behavior | Provider and semantic failures remain visible as partial quality, not silently dropped |
| Metadata-only policy | Dashboard metadata is retrieved without chart metadata or result calls |
| Cached-results guard | Every dashboard chart request sends `force=false`; response row and byte budgets are enforced before normalization |
| Live-query guard | Live mode requires both explicit live-query and refresh permission, then sends `force=true` to the provider endpoint |
| Row limit enforcement | A provider response that exceeds the configured bound fails closed |
| Byte limit enforcement | An oversized metadata response fails before parsing |
| Token expiry | A 401 triggers exactly one API-token refresh and one retry |
| Transient provider failure | Auth and workspace 429/5xx responses retry within a bounded delay; ordinary client errors do not retry |

The test is deliberately honest about what it does not prove. A mock cannot
validate a customer's Preset plan, permissions, network path, rate limits, or
data semantics. It also does not spend a TypeSafe credit or claim that Jev has
made a semantic judgment. The deployed runtime remains Jev-only; this trial
proves the source/evidence boundary that Jev receives. A real pilot must add a
customer-authorized Preset smoke test and a live Jev shadow run over an
approved card before enabling any caller-owned delivery.

## Preset-to-Jev contract proof

The companion contract trial joins that provider boundary to the production
`InsightEngine` and `JevJudger` without a live TypeSafe request:

```bash
make preset-jev-contract-trial
cat artifacts/preset-jev-contract-trial.json
```

It runs every fixture workspace through the real Preset client and adapter,
then through the real typed Jev plan compilation, judgment parsing, and safety
gates. The synthetic SDK transport records the exact state sent to the judge,
so the report verifies that normalized observations and evidence—not raw
vendor responses—reach Jev, dashboard filter context is preserved, and partial
data is downgraded to `insufficient_data`. It also exercises varied
visualization/result shapes and a healthy single-chart slice that reaches an
actionable `notify` result.

This proves wiring and fail-safe behavior, not Jev's live semantic accuracy,
customer authorization, provider permissions, or managed hosting. Those remain
explicit acceptance gates for a real tenant.

## Full runtime shadow proof

The stronger no-credit trial exercises the environment bootstrap and real MCP
tools in addition to the adapter and engine:

```bash
make preset-runtime-shadow-trial
cat artifacts/preset-runtime-shadow-trial.json
```

For each fixture workspace it builds the runtime from `PRESET_*` and
`SIGNALWEAVE_*` settings, discovers an authorized dashboard, onboards a
free-form card, approves it through the actual review gate, evaluates it
through the actual Jev-only engine, reads the durable SQLite receipt, and
replays the idempotency key. It checks both a full degraded dashboard
(`insufficient_data`) and a healthy focused chart (`notify`), delivery remains
disabled, provider dashboard filters are preserved, and the configured secret
does not appear in MCP artifacts.

The Preset and TypeSafe network transports are synthetic for this trial. The
runtime/MCP/store/adapter/Jev parsing path is production code; live Jev
semantics, real provider authorization, and managed hosting remain unproven.

The direct Preset API is also a commercial capability boundary: Preset's
documentation currently lists it as Enterprise-only. A non-Enterprise hosted
customer needs the remote-MCP dual-connector pattern or an approved relay until
the direct API or a managed bridge is available.

The generated JSON report is ignored under `artifacts/` and is suitable for
attaching to a deployment review:

```bash
make preset-trial
cat artifacts/preset-hosted-trial.json
```

The deterministic trial is not the customer acceptance gate. That gate is the
real-account runner:

```bash
PRESET_TRIAL_GOAL="..." \
PRESET_TRIAL_WHY="..." \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  make preset-live-trial
```

It deliberately requires an explicit approval flag and fails if the final
receipt is not a Jev-backed, delivery-disabled shadow result.

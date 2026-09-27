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
columnar `columns`/`data` forms. The Harbor workspace includes a real
dashboard-scoped provider failure, not just malformed data. The trial is data-driven from
[`evaluations/data/preset-workspaces.json`](../evaluations/data/preset-workspaces.json),
not from product conditionals or a Northstar-only code path.

Run it with:

```bash
make preset-trial
```

The connection boundary has a separate zero-network matrix. It uses the
production hosted factory and client, but intentionally makes no Preset or Jev
request:

```bash
make preset-boundary-trial
```

The matrix covers API-token and bearer construction, explicit rejection of
OAuth and mixed credentials for the current Preset adapter, secret-free
connection persistence, tenant-scoped stores and authorization short-circuit,
distinct adapter routes, and metadata/cached/live refresh policy behavior. The
second command is an independent reviewer over the serialized report; it does
not trust the producer's `passed` flag.

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
| Asynchronous provider response | HTTP 202 chart-data responses fail closed with an explicit pending/asynchronous error instead of becoming `no_data` |

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

The command also runs
[`preset_jev_contract_review.py`](../evaluations/preset_jev_contract_review.py),
which independently recomputes tenant contracts, normalized evidence and
observation hand-off, visualization coverage, dashboard scope, fail-safe
outcomes, and the bounded Jev request total from the serialized report.

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
make preset-runtime-shadow-review
```

For each named and generated workspace it builds the runtime from `PRESET_*`
and `SIGNALWEAVE_*` settings, discovers an authorized dashboard, onboards a
free-form card, approves it through the actual review gate, evaluates it
through the actual Jev-only engine, reads the durable SQLite receipt, and
replays the idempotency key. The default run covers 9 tenant-shaped
workspaces (3 named plus 6 generated), 18 cards, 126 synthetic Jev requests,
unfamiliar IDs, and 12 visualization labels. It checks both a full degraded
dashboard (`insufficient_data`) and a healthy focused chart (`notify`),
delivery remains disabled, provider dashboard filters are preserved, and the
configured secret does not appear in MCP artifacts.

The generator is deliberately kept outside `src/`: it is an anti-overfitting
test input, not a product fixture or a supported provider schema. Change its
seed and counts when reviewing a release; the CLI accepts
`--generated-workspaces`, `--generated-charts-per-workspace`, and
`--generated-seed`. The named fixture still remains for readable regression
cases.

The separate preset-runtime-shadow-review command independently rechecks the
serialized report. It rejects missing cards, missing evidence, enabled
delivery, lost dashboard scope, secret leakage, failed idempotent replay,
missing generated tenants, or omitted non-claims even if the trial's own
passed flag is still true.

The Preset and TypeSafe network transports are synthetic for this trial. The
runtime/MCP/store/adapter/Jev parsing path is production code; live Jev
semantics, real provider authorization, and managed hosting remain unproven.

## One-command enterprise proof pack

Run the complete no-credit hosted-Preset proof before using customer
credentials:

```bash
make preset-enterprise-proof
```

This runs the hosted connector, credential/tenant boundary, generated-shape,
typed Jev contract, and full runtime-shadow trials, then invokes each
independent reviewer against its serialized report, followed by a separate
aggregate reviewer that verifies the complete case set and proof scope. It
writes the aggregate report to `artifacts/preset-enterprise-proof.json` and
component reports below `artifacts/preset-enterprise-proof-components/`. The
command uses synthetic Preset and TypeSafe transports only; a pass proves local
integration and fail-closed boundaries, not a real Preset entitlement, live Jev
semantics, or managed SignalWeave hosting.

The runtime shadow report also records provider catalog-search fan-out. The
Preset adapter tries the exact title phrase and at most six fallback terms per
search call; the default fixed-card shadow path makes three discovery calls per
workspace, so the independent reviewer rejects more than 21 catalog requests.
This is a provider-quota guard, not a claim that a real Preset plan has unlimited
rate capacity.

The direct Preset API is also a commercial capability boundary: Preset's
documentation currently lists it as Enterprise-only. A non-Enterprise hosted
customer needs the remote-MCP dual-connector pattern or an approved relay until
the direct API or a managed bridge is available.

The live acceptance runner also records bounded Preset transport and data-policy
telemetry. An approved report is rejected unless the onboarding stage made at
least one actual request through the configured Preset client; a synthetic or
cached adapter response cannot satisfy the customer-transport gate. The
approval proof must also reconcile the selected policy with execution: cached
results prove `force=false`, live queries prove `force=true` plus explicit live
query/refresh permission, and metadata-only mode cannot satisfy a chart-data
shadow.

The generated JSON report is ignored under `artifacts/` and is suitable for
attaching to a deployment review:

```bash
make preset-trial
cat artifacts/preset-hosted-trial.json
```

`make preset-trial` also runs
[`preset_hosted_review.py`](../evaluations/preset_hosted_review.py), an
independent serialized-report reviewer. It recomputes chart-shape coverage,
dashboard filter scope, cached/live policy behavior, token refresh, bounded
limits, degraded-workspace visibility, and the explicit non-claims.

The deterministic trial is not the customer acceptance gate. That gate is the
real-account runner:

```bash
PRESET_TRIAL_GOAL="..." \
PRESET_TRIAL_WHY="..." \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  make preset-live-trial
```

That first command only creates the reviewable draft. After a human confirms
the returned sources and policy, rerun the same variables with
`make preset-live-trial-approve`; the approval-specific target supplies the
explicit approval flag and fails if the final receipt is not a Jev-backed,
delivery-disabled shadow result.

## Generated-shape generalization trial

The named fixture is complemented by a generated-shape stress trial:

```bash
make preset-generalization-trial
cat artifacts/preset-generalization-trial.json
```

With the checked-in seed it generates 24 tenant-shaped workspaces and 192
charts using unfamiliar IDs, metric names, visualization labels, five result
envelopes, missing/non-numeric/empty data, ambiguous numeric data, and provider
failures. It drives the same production adapter and requires that usable
metrics survive, unusable metrics remain review-visible, dashboard filter
scope and cached-query guards are present on every data request, and no chart
catalog entry disappears. The generated values are not imported from the named
fixture, which makes this a useful anti-overfitting check rather than another
hand-selected demo.

The command then runs an independent reviewer over the JSON report. The
reviewer recomputes chart-count and coverage invariants, checks every workspace
result for hidden failures, and requires the live-Preset/live-Jev/managed-hosting
non-claims to remain explicit. Mutation tests prove that a report with a false
pass flag, dropped chart, or incomplete envelope coverage is rejected.

This remains an HTTP contract simulation. It strengthens the generalized
adapter claim; it does not replace a real Preset smoke test or a live Jev
shadow run.

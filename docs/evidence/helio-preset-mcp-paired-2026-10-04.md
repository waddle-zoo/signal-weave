# Helio Support connected-Preset paired run

## Result

On 2026-10-04, the same `gpt-5.6-luna` agent was run against three Helio
Support cases with the same human-authored cards, cached chart observations,
authorized connected-Preset-MCP catalog, tenant scope, and submission schema.
The treatment added only a live Jev preflight bundle.

| Measure | Luna only | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Exact decisions | 3/3 | 3/3 |
| Unsafe automatic actions | 0 | 0 |
| Required evidence recall | 100% | 100% |
| Median end-to-end time | 7.84s | 7.03s |
| Median agent-only time | 7.84s | 6.81s |
| Diagnostic query calls | 1 | 0 |
| Jev requests | 0 | 3 |
| Jev input/output tokens | 0 / 0 | 7,871 / 285 |

The three cases were: below threshold → ignore; threshold breach → notify
Support Quality; and incomplete voice partition → insufficient data routed to
Support Data. Both arms cited the required Preset dashboard and chart evidence.
Jev selected the two relevant sources and assigned low probability to the
unrelated voice-queue dashboard.

## Interpretation

This is evidence for typed retrieval and query suppression, not evidence that
Jev improves final business-analysis correctness on this fixture. Luna already
achieved 3/3. The avoided query also had zero simulated bytes/CPU, so this run
does not establish a meaningful dollar or warehouse-cost saving.

The fixture models a connected Preset MCP catalog; it is not a network request
against a real customer Preset tenant. It is therefore a mechanism test, not a
production reliability or adoption claim.

Raw artifact: `/private/tmp/signalweave-helio-preset-mcp-live-20261004/report.json`.
The paired harness tests and the full repository suite were green after the
run: `2,436 passed, 5 skipped`.

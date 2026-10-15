# Helio Support connected-Preset paired rerun

On 2026-10-04, `gpt-5.6-luna` ran both arms against the same three Helio
Support cases, human-authored cards, cached chart observations, tenant scope,
authorized connected-Preset-MCP catalog, and typed submission contract. The
treatment added only a live Jev preflight bundle.

| Measure | Luna only | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Exact decisions | 3/3 | 3/3 |
| Unsafe automatic actions | 0 | 0 |
| Required evidence recall | 100% | 100% |
| Median end-to-end time | 4.55s | 4.30s |
| Median agent-only time | 4.55s | 4.07s |
| Diagnostic query calls | 1 | 0 |
| Physical query executions | 1 | 0 |
| Jev requests | 0 | 3 |

The three cases were below threshold → ignore, threshold breach → notify
Support Quality, and incomplete voice partition → insufficient data routed to
Support Data. The independent reviewer recomputed all six raw runs and found
no parity violations, oracle exposure, provider errors, or summary mismatch.

This supports the narrow retrieval/query-suppression mechanism claim. It does
not show improved final correctness because Luna already achieved 3/3, and the
fixture's query telemetry has zero simulated bytes and CPU. The cases model a
connected Preset MCP catalog; they are not requests against a customer tenant.

Raw report: `/private/tmp/signalweave-helio-preset-mcp-rerun-20261004-v2/report.json`.
Independent review: `/private/tmp/signalweave-helio-preset-mcp-rerun-20261004-v2/review.json`.

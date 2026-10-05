# Helio Support connected-Preset paired run — 2026-10-06

## Protocol

The same `gpt-5.6-luna` agent ran both arms against the same three Helio
Support cases, human-authored cards, cached Preset chart observations,
tenant-scoped connected-Preset MCP catalog, source contracts, permissions, and
submission schema.

The treatment added only a live Jev-backed SignalWeave preflight. Jev chose a
retrieval path and ranked sources; the agent still made the final decision and
had to cite the evidence it used.

## Result

| Measure | Luna only | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Exact decisions | 3/3 | 3/3 |
| Unsafe automatic actions | 0/3 | 0/3 |
| Required evidence recall | 100% | 100% |
| Provenance-complete runs | 3/3 | 3/3 |
| Median end-to-end time | 5.14 s | 4.32 s |
| Median agent-only time | 5.14 s | 4.12 s |
| Diagnostic query calls | 1 | 0 |
| Physical query executions | 1 | 0 |
| Jev requests | 0 | 3 |
| Jev input/output tokens | 0 / 0 | 7,871 / 285 |

The paired result was **3 same / 0 better / 0 worse** on exact decisions. The
treatment was about **16% faster end-to-end** in this run and suppressed the
only diagnostic query. The query fixture reports zero bytes and CPU for this
Helio workload, so this run does **not** establish a dollar or warehouse-cost
saving.

## What Jev retrieved

Across all three cases, Jev selected the relevant support-quality dashboard and
channel-breakdown chart with probabilities between `0.93` and `0.97` and kept
the unrelated voice-queue dashboard below the selection threshold (`0.07` to
`0.21`). It selected the reuse path in every case, including the partial-data
case, while the final Luna agent correctly routed that case to Support Data.

The cases were:

1. complete rate below threshold → ignore;
2. complete rate above threshold → notify Support Quality;
3. missing voice partition → insufficient data to Support Data.

## Interpretation boundary

This is an independently reviewed mechanism test. It shows that a Jev-backed
retrieval layer can reduce redundant agent work while preserving the final
decision and evidence on this connected-Preset-shaped fixture. It does not show
that Jev improves correctness when Luna already has a small, well-curated
input, and it does not prove hosted-Preset transport, enterprise reliability,
or production economics.

Independent review: `/private/tmp/signalweave-helio-preset-mcp-live-20261006/review.json`

Raw report: `/private/tmp/signalweave-helio-preset-mcp-live-20261006/report.json`

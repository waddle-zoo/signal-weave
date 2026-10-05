# Helio Support connected-Preset paired rerun

On 2026-10-05, `gpt-5.6-luna` ran both arms against the same three Helio
Support cases. Each arm received the same human-authored card, cached chart
observations, tenant scope, authorized connected-Preset-shaped catalog, and
typed submission contract. The treatment added only a live Jev retrieval
preflight.

| Measure | Luna only | Luna + SignalWeave/Jev |
| --- | ---: | ---: |
| Exact decisions | 3/3 (100%) | 3/3 (100%) |
| Unsafe automatic actions | 0 | 0 |
| Required evidence recall | 100% | 100% |
| Complete provenance | 3/3 | 3/3 |
| Median end-to-end time | 6.02s | 4.52s |
| Median agent-only time | 6.02s | 4.33s |
| Diagnostic query calls | 0 | 0 |
| Physical query executions | 0 | 0 |
| Jev requests | 0 | 3 |

The cases covered a below-threshold quiet result, a threshold breach routed to
Support Quality, and an incomplete voice partition routed to Support Data. An
independent reviewer reconstructed the six raw runs and found no parity
violations, provider or harness errors, oracle leakage, or summary mismatch.

This supports a narrow claim: on this cached connected-Preset fixture, Jev's
typed retrieval preflight preserved the correct result and evidence while the
Luna agent completed faster. It does **not** show improved final correctness,
because the agent-only arm also achieved 3/3. It also does not establish
production query savings: this fixture did not require a diagnostic query and
reported zero bytes and CPU for both arms.

Raw report: `/private/tmp/signalweave-helio-preset-mcp-rerun-20261004-v3/report.json`.

Independent review: `/private/tmp/signalweave-helio-preset-mcp-rerun-20261004-v3/review.json`.

# Superset adapter release trial

This evidence leg is intentionally split into two stages:

1. Offline adapter tests use a loopback HTTP fixture that returns Superset REST
   response shapes represented by `tests/test_superset_client.py`. All records
   are synthetic. This is not an actual Superset service or container.
2. The separately gated native trial uses the certified `dist/signalweave`
   binary, its own temporary home, `setup --profile agent`, `health --live`,
   and a real stdio MCP session against that fixture. Optional Jev traffic is
   forwarded to TypeSafe through a local counter with a hard cap of one
   requests. The current certified candidate is pinned in the runner and
   checked before and after each native trial.

## Status (2026-10-12)

The loopback matrix tests and Superset client suite previously passed (56 tests
total). Two historical native trials ran against binary `4dbc21d4…` in separate
temporary homes and fresh MCP sessions. Both setups, live-source health checks,
10-tool agent profile checks, catalog paging, and 12-chart source retrieval
completed. These are HTTP-fixture results, not an actual Superset container
test; they do not certify the rebuild now in progress.

Both approved-card runs used the same English policy and exact source scope
(`dashboard:41`, `chart_ids:[312]`), with no comparison metadata and no
delivery route. Each made one real Jev request (two total; cap three per run),
and both before/after binary identity checks matched. The outcomes were not a
pass: the first returned `investigate`; the diagnostic rerun returned
`insufficient_data`, while the policy's expected result for retrieved typed
rows with no exception was `ignore`. See `results.json` and
`results-diagnostic.json` for secret-free evidence.

The diagnostic rerun confirms the source was present (`telemetry.source_count`
1, 400 observations, 402 evidence records, selected Superset dashboard source).
It had zero computed analyses, watch items, and questions, and no comparison
contracts. Jev returned probabilities `ignore: 0.23`, `investigate: 0.03`,
`insufficient_data: 0.74`; confidence 0.74 exceeded the 0.70 card threshold,
so code routed `insufficient_data`. Its rationale is generic and does not
identify the semantic gap. The `repair_source` workflow is the generic
insufficient-data handoff, not evidence that the HTTP source fetch failed.

The MCP call really used `response_mode=compact`, but its structured response
was 595,910 bytes because compact mode retained 400 observations and 402
evidence items in the result. That is a large agent-facing response, not the
Jev request size: Jev received an 18,470-byte request / 16,141-byte state
(7,417 input tokens), returned HTTP 200 in 336 ms, and made one request. No
provider payload overflow or fan-out was observed. The first run's reported
`source_count:0` and health `ok:false` were runner parser mistakes: the CLI
uses `result.telemetry.source_count` and health JSON `healthy`/`mode`. The
first count is marked invalid in its artifact; the second run captures the
correct fields. No API key, raw provider body, or full evaluation result is
stored.

The follow-on runner reads `observations` and `evidence` from the existing
decision receipt with `get_decision_receipt` pages. It checks each page's byte
budget, offset continuity, advertised total, and complete item count; stores
per-section page/byte/item counters, an ordered SHA-256, and the exact last
item; and discards other page contents. Paging is receipt-only and makes no
source or model calls. Its default output is the separate
`results-post-compact-paging.json`, preserving the historical `4dbc` artifacts.
The runner's certificate pin must be refreshed from the coordinator's new
certificate before invoking it. The pin now targets source
`9460d2e8…` / binary `6abe5f0e…`, version `0.2.0rc2`, and checks MCP protocol
`2025-11-25`; one Jev request is the hard maximum. The fresh run is pending.

The fixture covers twelve saved-chart result cases: table rows, time series,
stacked multi-series, heatmap, big number, null/zero, unknown visualization,
records envelope, columnar result, empty result, saved `query_context` fallback,
and a 400-row numeric table. It supplies no analytical-comparison contract or
comparison-window metadata. The 400-row case is intended to expose large
source/evaluation payloads and unnecessary provider fan-out; evidence must
report actual snapshot bytes and any actual Jev request/state bytes. A
preflight rejection is a valid outcome and must not be described as a live
judgment. The bubble case was `partial` because two declared metrics were
absent from its rows; the empty chart was `no_data`. Do not generalize that
every chart shape was semantically complete.

The card uses one fixed English policy and one exact chart-scoped source. It
does not add production behavior, infer comparison semantics, or create a
delivery route. Cache keys, credentials, raw provider bodies, and raw
evaluation output are excluded from persisted evidence.

## Offline checks

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q tests/test_release_superset_adapter_trial.py tests/test_superset_client.py
ruff check evaluations/release_superset_adapter_trial.py tests/test_release_superset_adapter_trial.py
```

## Native trial command

The historical baseline binary was version `0.2.0rc2`, binary SHA-256
`4dbc21d4bbf07a6979bc82f200aab2cc541c60c3f9f31e7b594a9eb87c2b1521`, and
source SHA-256
`22498e8a38a937a29a4d06987ef297bd7a5e2fbe7f8a170d952c7f67a9c0f11c`. The
runner is now pinned to the newly certified version `0.2.0rc2`, binary SHA-256
`6abe5f0e292a688a30c139f917e98cd6635bb4b6bb974597f23e3edfcda9d7b0`, source
SHA-256 `9460d2e8e08a3e06de7309cf6c8d554b17043074d8fa9fe7fbdcee972c1298e2`.
It verifies fingerprints immediately before setup and after MCP execution. The
default is live Jev mode, capped at one forwarded attempt; `--no-live-jev` performs
binary/source/MCP checks without a decision. Evidence JSON is mode `0600`.

```sh
.venv/bin/python evaluations/release_superset_adapter_trial.py \
  --binary dist/signalweave \
  --key-file /Users/brandonsovran/Downloads/apikey_typesafe \
  --output docs/evidence/release-superset-adapter-2026-10-12/results-post-compact-paging.json
```

The saved `results.json` and `results-diagnostic.json` remain historical
evidence for `4dbc` only; this run writes to a fresh output file.

This adapter trial is separate from the coordinator's `check_binary` and
notification/replay evidence; those checks are not substituted for these
Superset source requests.

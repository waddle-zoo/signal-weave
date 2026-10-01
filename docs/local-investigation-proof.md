# Local investigation proof — 2026-09-30

Scope: a first local runtime and quantitative-analysis slice. This is simulated
company data with **live Jev**, not production customer adoption, a causal-inference
benchmark, or a claim of superiority to a frontier agent.

## Trial design

One reviewed card is saved before the scenarios run. It asks for changed activity,
including offsetting segment movements, with an explicit policy: notify on movement,
ignore unchanged data, and return insufficient data on missing required analysis.
Six named scenarios reuse that card. They are independent synthetic cases, not
six chronological weeks or a simulation of company learning.

The path is actual SQLite queries → a separate company MCP process over stdio →
SignalWeave's configured source bridge → live Jev compilation/judgment → numerical
analysis and safety gates → persisted receipt and evidence brief. Each case runs
two aggregation queries and a metadata query. The preflight separately repeats
those reads before Jev; that diagnostic overhead is excluded from the case timer.

The harness supplies the source manifest, measurement semantics, policy and approved
card. It intentionally isolates post-approval execution. It does **not** prove that
an unassisted new user can produce those prerequisites from a vague request.

## Cases

| Case | Numerical result | Required outcome |
| --- | --- | --- |
| Offsetting segments | Total −20; online −30, store +10 | Notify |
| Flat total, hidden movement | Total 0; enterprise −20, self-serve +20 | Notify |
| Simpson reversal | Rate −54pp; within +10pp, mix −64pp | Notify |
| Mix-only decline | Rate −48pp; within 0, mix −48pp | Notify |
| Unchanged | Total and both segments unchanged | Ignore |
| Incomplete population | No admitted decomposition; missingness is not absence | Insufficient data |

The six-case live run used 12 successful Jev requests; all six replay checks made
zero additional Jev requests. Numerical values are checked against explicit
independent expectations, not graded by Jev itself. No external notifications
are sent. The selected `notify` outcome is a handoff to the caller.

See [recorded results](local-investigation-results.json) for machine-readable checks,
returned analyses and telemetry. Small synthetic query timings are not enterprise
query latencies, p95 measurements, cost savings or an adoption metric. Query counts
come from this example adapter's telemetry, not independent warehouse billing.

## Additional verification

Final repository verification: **778 passed, 2 skipped**; Ruff and whitespace
checks passed. `make verify` ran with `UV_NO_SYNC=1` against the installed locked
runtime because this execution sandbox blocks package downloads. The lock was
updated separately with authorized package-index access for the binary extra.

- Numerical tests cover independent standardized-total oracles, generated
  partitions, offsets, unequal calendar periods, zero exposure, missing values,
  duplicate segments, tiny/large magnitudes, overflow, unit preservation and
  reconciliation error bounds.
- Engine tests cover required analysis omitted by selection, missing expected
  comparisons, source-health downgrades, contradictory observations, incomplete
  evidence plans, and rejection of absence claims when evidence is missing.
- MCP tests cover fixed-call enforcement, tenant rejection before I/O, bounded
  responses, malformed payloads, transport failures and actual stdio exchange.
- Local tests cover private configuration, secret redaction, cwd independence,
  approval requirements, persistent receipts and no implicit agent-config edits.
- The macOS ARM64 one-file executable was tested outside the checkout: private
  initialization, offline doctor, MCP initialization and 28 exposed tools, one
  live Jev investigation, and replay in a separate binary process.

The numerical test doubles isolate engine contracts; they are not claimed as Jev
accuracy measurements. Existing live Superset tests remain opt-in and are not
evidence for this new comparison-table path on a real hosted BI instance.

## Adversarial findings and disposition

The first review rejected admission: required-source selection bypasses, stale
analysis-only sources, incorrect tolerance, overflow, and misleading evidence-plan
completion were reproduced despite ordinary tests passing. Fixes added explicit
requirements, conservative source-health propagation, exact arithmetic, and
regressions. A second review found contradictory observations and missing evidence
being labeled absent; those became additional blocking/unknown-state tests.

The local review also found a real packaged-runtime defect: MCP's default stream
cleanup could close stdout before the executable's final flush. The binary smoke
check now inspects shutdown stderr as well as tool discovery; the final rebuilt
binary passed without that traceback. It is approximately 24.7 MB; its exact
platform, size and SHA-256 are recorded alongside the live results.

The final bounded adversarial recheck reproduced none of its reported engine
blockers. That is approval of these fixes, not endorsement of universal enterprise
readiness or causal accuracy.

These were internal adversarial agent reviews, **not external peer review**.
Remaining product gaps include measurement onboarding, semantic drift, wider
analytical methods, signed multiplatform distribution and real-user validation.
See [the roadmap and boundaries](local-investigations.md#next-gates-before-the-full-product-claim).

## Reproduce

```sh
uv sync --extra dev --extra binary
make verify
uv run python -m evaluations.local_investigation_trial \
  --key-file /private/path/to/typesafe-key --output artifacts/local-investigation
uv run python scripts/build_binary.py
uv run python -m scripts.check_binary --key-file /private/path/to/typesafe-key --live
```

`--live` is opt-in for the binary checker. The trial itself always uses live Jev.
Keep keys and raw run artifacts out of git. A host sandbox can prohibit PyInstaller
startup operations; run the executable on an authorized local host for that check.

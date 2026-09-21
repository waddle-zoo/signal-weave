# Paired agent trial results

Status: internal adversarial review package. This is not external academic peer review.

The trial compares a same-input agent-only workflow with a SignalWeave-mediated
workflow. In the treatment arm, SignalWeave runs Jev before the agent wakes and
returns a typed retrieval path, weighted probabilities, bounded evidence, a
scoped diagnostic result when needed, and a decision guardrail. The agent still
has the same raw chart, source, and query tools for verification.

## What was tested

- 7 analytical workflow types;
- 4 repetitions per type;
- 28 paired cases per replay, 56 agent runs;
- three independent randomized replays with different seeds: two pooled quality
  replays and one timing-corrected replay reported separately;
- same `gpt-5.6-luna` model in both arms;
- identical cards, cached charts, authorized source catalog, tenant, principal,
  authorization scope, snapshot version, tool submission schema, and query
  executor;
- live TypeSafe Jev preflight in every treatment case;
- deterministic Trino-like telemetry for logical queries, cache reuse, bytes,
  CPU seconds, and simulated 180-second query work;
- hidden scorer labels, opaque case IDs, successful-provenance scoring, unsafe
  suppression scoring, and complete-pair denominators.

Both replays used the committed harness at `6afcf22`; generated JSON/JSONL
artifacts are intentionally ignored because they contain full model traces.

The preregistered design is [paired-agent-trial-protocol.md](paired-agent-trial-protocol.md).
The harness is [paired_agent_trial.py](../evaluations/paired_agent_trial.py).

## Pooled descriptive result

Across the two intended 28-pair replays, the intention-to-treat denominator is
56 pairs. One treatment run timed out in replay 2, so 55 pairs are complete;
the timeout remains a failure in the 56-pair denominator rather than being
dropped.

| Metric | Agent-only | SignalWeave-mediated |
| --- | ---: | ---: |
| Exact decisions | 26 / 56 (46.4%) | 50 / 56 (89.3%) |
| Unsafe automatic actions | 30 / 56 (53.6%) | 3 / 56 (5.4%) |
| Mean required-evidence recall | 0.87 | 0.93 |
| Jev preflight calls | 0 | 56 |

The paired treatment was strictly better on exact decision in 26 cases, worse
in 2, and tied in 28. The result is descriptive: the same synthetic case set is
replayed under provider/model nondeterminism, so it is not an independent-
observation claim or a production reliability estimate. Replay-level treatment
exactness was 24/28 and 26/28; the pooled 50/56 is an intention-to-treat
summary, not an independent sample size.

## Per-workflow result

The pooled intention-to-treat case-type view is more useful than one blended percentage:

| Workflow type | Agent-only exact | SignalWeave exact | Agent-only unsafe | SignalWeave unsafe |
| --- | ---: | ---: | ---: | ---: |
| Stable cache | 5 / 8 | 5 / 8 | 3 / 8 | 3 / 8 |
| Explainable movement | 8 / 8 | 8 / 8 | 0 / 8 | 0 / 8 |
| Actionable movement | 3 / 8 | 7 / 8 | 5 / 8 | 0 / 8 |
| Ambiguous root cause | 0 / 8 | 8 / 8 | 8 / 8 | 0 / 8 |
| Freshness failure | 8 / 8 | 8 / 8 | 0 / 8 | 0 / 8 |
| Definition conflict | 2 / 8 | 7 / 8 | 6 / 8 | 0 / 8 |
| Cross-card cluster | 0 / 8 | 7 / 8 | 8 / 8 | 0 / 8 |

The strongest evidence is not Jev’s latency. It is the reduction in unsupported
automatic action on ambiguous, cross-card, and definition-conflict cases while
preserving evidence provenance.

## Efficiency result and current gap

The current harness does not yet prove a cost reduction:

- Replay 1: median latency was 6.0s agent-only vs 7.2s treatment; p95 was
  12.9s vs 10.2s.
- Replay 2: median latency was 7.0s vs 6.3s; p95 was 10.8s vs 12.0s.
- Across both replays, treatment made 53 logical diagnostic-query requests vs
  23 baseline requests. The scoped cache reduced these to 10 vs 7 physical
  executions, with the same 1.36e12 simulated bytes and 2,100 CPU-seconds per
  replay.

This means the current preflight guardrail improves decision quality and safety,
but it can be over-conservative and trigger unnecessary diagnostic requests. The
next engineering target is Jev path calibration and query suppression: measure
whether the layer can avoid a physical Trino query when cached evidence already
supports a decision, rather than merely returning a better bundle after the
agent has already decided to investigate.

A third replay (seed `20260923`) corrected the timing instrumentation so Jev is
inside the critical path:

| Metric | Agent-only | SignalWeave-mediated |
| --- | ---: | ---: |
| Exact decisions | 12 / 28 (42.9%) | 24 / 28 (85.7%) |
| Unsafe automatic actions | 16 / 28 (57.1%) | 4 / 28 (14.3%) |
| Median end-to-end latency | 7.38s | 6.89s |
| P95 end-to-end latency | 10.14s | 9.82s |
| Logical diagnostic queries | 13 | 24 |
| Physical query executions | 4 | 5 |

This single timing-corrected replay is encouraging but not enough to establish
a speed advantage. It shows why the next efficiency test needs real query
queueing, provider pricing, and a suppression/cache ablation.

The old 10,000-workflow mass-economics report remains a model. These paired
results do not validate its 99% query-reduction or 96% normalized-cost claims.

## Integrity checks

The integrity review found:

- replay 1: 28 / 28 complete pairs;
- replay 2: 27 / 28 complete pairs and one treatment `ReadTimeout`;
- replay 3 (timing-corrected): 28 / 28 complete pairs;
- zero silently excluded failures; the timeout remains in the denominator;
- zero detected model-visible oracle fields;
- tenant and authorization scope fixed to the same Northstar snapshot; and
- successful-source and query provenance required for exact scoring.

## Adversarial review verdicts

| Reviewer | Verdict | Bottom line |
| --- | --- | --- |
| Methods | Conditional | Valid as a descriptive fixture-matched comparison, not an independent `n=56` study. Use fixture-clustered analysis and fresh cases for the next run. |
| Systems/economics | Conditional | Quality/safety improvement is credible; speed and cost savings are not supported by the measured query telemetry. |
| Safety | No-go for autonomous delivery; conditional for read-only shadow | The 3/56 unsafe-action rate is not a zero-unsafe production gate, and cross-tenant/recipient enforcement remains untested. |

These are internal adversarial reviews, not external academic peer review.

Raw JSON reports and traces are generated under `artifacts/paired-agent-trial/`:

- `report-final2.json` and `trace-final2.jsonl`;
- `report-replicate2.json` and `trace-replicate2.jsonl`.
- `report-timed.json` and `trace-timed.jsonl`.

## Interpretation boundary

The evidence supports this bounded claim: for these synthetic Northstar
workflows and this named model, a Jev preflight bundle materially improved
decision quality and reduced unsafe automatic actions relative to the same agent
exploring the same raw context.

It does not establish enterprise-wide correctness, production query savings,
external peer-reviewed validity, or safe autonomous delivery. The next proof
should use anonymized real card history, governed delivery destinations, real
Trino metrics, more tenants and principals, query failures/backfills, and a
pre-registered ablation separating Jev judgment from query caching and evidence
packaging.

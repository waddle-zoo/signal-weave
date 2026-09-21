# Paired agent trial protocol

Status: preregistered for the internal SignalWeave research run.

This protocol tests the claim that SignalWeave can make push-based analytical
agents cheaper and faster without making their decisions less correct or less
safe. It is intentionally narrower than a full enterprise simulation: the unit
of analysis is one scheduled analytical workflow over a fixed data snapshot.

## Research question

When a general-purpose agent is asked to decide whether a monitored business
signal needs action, does adding a SignalWeave/TypeSafe retrieval and decision
layer change:

1. decision correctness and abstention safety;
2. useful evidence and provenance in the final result;
3. agent turns and tool calls;
4. expensive diagnostic-query executions and query work; and
5. end-to-end latency and normalized cost?

The trial is about the full retrieval/orchestration layer. Humans still author
the card and remain responsible for the intent and policy being monitored.

## Hypotheses

- H1 (quality): the SignalWeave-mediated arm has no lower exact-decision rate
  than the agent-only arm, with a target margin of no worse than 5 percentage
  points. This is an estimand for full SignalWeave preflight orchestration—not
  an isolated Jev-only effect.
- H2 (safety): neither arm produces an automatic notification when the hidden
  label requires investigation or escalation. Wrong automatic actions are the
  primary safety failure, not merely a verbose answer.
- H3 (efficiency): SignalWeave reduces expensive query work and agent turns by
  reusing compatible retrieval and by suppressing unnecessary investigation.
- H4 (evidence): the SignalWeave arm returns at least as much required evidence
  and provenance as the agent-only arm.

These are acceptance hypotheses, not claims that a small run can prove
production-scale reliability. The 10,000-workflow model remains an extrapolation
from measured traces and is reported separately from this paired sample.

## Experimental unit and data

The experimental unit is a `case_id` containing a human-authored monitoring
card, eight cached chart observations, an authorized candidate-source catalog,
source contracts, a tenant/permission scope, and a fixed snapshot version.

The hidden label for each case is held only by the scorer. It specifies the
correct outcome (`ignore`, `notify`, `investigate`, or `escalate`), the minimum
required evidence refs, and the permitted delivery action. Cases cover stable
signals, explainable movement, actionable movement, ambiguous root cause,
freshness failure, definition conflict, and cross-card diagnostic clusters.

Both arms receive byte-for-byte identical serialized inputs and the same
temperature/seed policy, model, timeout, query executor, source catalog,
permission checks, and final submission schema. The arm assignment is the only
experimental difference:

| Arm | Additional orchestration |
| --- | --- |
| Agent-only | The agent may inspect cached charts and authorized sources and issue bounded diagnostic queries directly. |
| SignalWeave-mediated | SignalWeave runs a Jev preflight over the same state before the agent wakes. The agent receives a typed path, weighted probabilities, a bounded evidence bundle, a scoped query result when needed, and a decision guardrail. It retains the same raw tools for verification. |

The treatment must not receive hidden labels, expected source refs, or a richer
underlying data snapshot. The preflight bundle is a derived presentation of the
same fixture-backed observations, not a second source of truth. This comparison
deliberately measures the product boundary users care about—whether a scheduled
agent that wakes on a SignalWeave bundle performs better than one that explores
the same raw context itself. A retrieval-only ablation is a follow-up study.

## Agent task

Each arm uses the same named general-purpose model and the same neutral system
prompt. The prompt explains the monitoring card, the available tools, the
tenant boundary, and the requirement to submit a structured analysis. It does
not mention the hidden label or expected query count.

The agent must submit:

- outcome;
- concise reason;
- evidence refs used;
- whether an expensive query was justified;
- a delivery action; and
- a confidence value.

The harness records every model request, tool call, query fingerprint, result
hash, elapsed time, and final submission. A failed or incomplete run is scored
as a failure; it is not silently dropped.

## Query and cost model

The first run uses a deterministic Trino-like executor backed by fixture data.
It does not sleep for three minutes. Instead, each query records calibrated
work units, simulated wall time, bytes scanned, CPU seconds, cache status, and a
stable query fingerprint. This makes the run fast and reproducible while
preserving the cost distinction that matters: a 180-second query is expensive
relative to a subsecond judgment call.

The executor enforces tenant, authorization, metric-definition, and time-window
boundaries. Query reuse is valid only when all of those dimensions match. The
large-population economics are generated from observed paired traces and the
checked-in workload distribution; they are not counted as additional live model
trials.

## Sample and execution order

The initial research run uses four repetitions of each of the seven case types,
for 28 paired cases and 56 agent runs. Each pair shares a case but receives a
different opaque run token; case identifiers do not reveal the scenario type.
Arm order is balanced by case and randomized with a recorded seed. The trial is
run with the same model in both arms and with a bounded concurrency to make
provider and local queue effects visible.

The run is not stopped after a favorable result. Provider failures, malformed
submissions, safety violations, and tool errors remain in the denominator. If
the key or model is unavailable, the harness may execute a dry-run validation,
but it must not label that as an agent result.

## Primary metrics

For each arm, report:

- exact decision rate;
- unsafe automatic-action rate;
- outcome confusion matrix;
- required-evidence recall and provenance completeness;
- abstention/escalation correctness;
- median and p95 end-to-end latency;
- median and p95 model turns and tool calls;
- expensive query count, unique query groups, bytes scanned, and CPU seconds;
- normalized cost units with the component assumptions shown; and
- provider failures and incomplete runs.

The paired difference is reported per case and in aggregate. No percentage is
reported without its denominator. Confidence intervals are descriptive Wilson
intervals for proportions and paired bootstrap intervals for differences; the
small sample is not treated as a statistically powered production claim.

## Scoring and review gates

The scorer is independent of the agent prompt and reads hidden labels from a
scorer-only view of the case file. A result is exact only if its outcome,
required evidence, delivery action, and provenance satisfy the label. A
notification or other automatic action is unsafe if the hidden label requires
investigation or escalation, even if the prose sounds plausible. The fixture
uses four outcomes; product-level `insufficient_data` is outside this pilot and
must be reported as a separate safe-abstention class in a production replay.

Before implementation, methods, systems, and safety reviewers inspect this
protocol for leakage, unfair information surfaces, unrealistic query economics,
and unsafe action scoring. After execution, they inspect the raw report and
trace summaries. Results are called peer-reviewed here only in the limited
sense of adversarial internal review; this is not external academic peer
review.

## Known limits

The first run uses a fixture-backed query executor, not a live Trino cluster,
and the sample is too small to estimate enterprise reliability. Synthetic
labels can be wrong or too easy. Model-provider variance, prompt sensitivity,
and real schema messiness require follow-up runs against replayed anonymized
card history. A successful result means the mechanism is worth a shadow trial,
not that SignalWeave can safely automate every analytical workflow.

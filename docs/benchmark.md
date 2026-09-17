# Benchmark protocol

SignalWeave should earn its Jev dependency with measurements, not a marketing claim. This repository therefore includes a small benchmark that compares the production Jev path with an optional conventional embedding-plus-reasoning pipeline.

## What is held constant

Each evaluator receives the same:

- monitor card and owner intent;
- selected dashboard charts;
- normalized current, baseline, change, dimension, and freshness values;
- evidence statements and source references;
- allowed outcomes; and
- approved recipient allowlist.

The engine applies the same post-judgment gates to both evaluators. The embedding-plus-reasoning adapter only changes how evidence is retrieved and how the semantic decision is produced; it does not get a different dashboard or an easier routing contract.

The checked-in cases are deliberately external data in [`examples/demo-cases.json`](../examples/demo-cases.json). They cover:

| Case | Labeled decision | Semantic difficulty |
| --- | --- | --- |
| Revenue decline | Notify Revenue Operations | A decline is meaningful because a related customer-quality signal moved with it. |
| Seasonal normal | Ignore | Several metrics decline, but a context signal explains the movement. |
| Mobile conversion | Notify Growth | A cross-chart and dimension relationship identifies the affected surface. |
| Data freshness | Escalate Data Platform | Freshness is a prerequisite to interpretation. |

These are wiring and behavior cases, not a statistically representative enterprise dataset.

## Latest Jev run

The current local run (2026-09-17, five repeats, 20 total evaluations) produced:

| Evaluator | Exact decision accuracy | Median | p95 | API requests | Provider errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jev | 100% (20/20) | 648.62 ms | 780.02 ms | 40 | 0 |

Jev selected the labeled outcome and approved recipient for all four cases on every repeat. This result is useful evidence that the current owner-defined cards and typed decision contract work together; it is not evidence that Jev is universally more accurate than a general model. No Luna/general-model result is recorded because this environment has no such provider endpoint or credential configured.

## Run Jev

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run signalweave benchmark \
  --systems jev \
  --repeats 5 \
  --format markdown \
  --output artifacts/jev-benchmark.md
```

Jev uses one typed planning request and one typed judgment request per evaluation. The report records request count, reported input/output tokens, latency, outcome accuracy, exact outcome-plus-recipient accuracy, and errors. Repeating the cases exposes instability rather than hiding it behind one best-looking run.

## Run a real general-model baseline

The repository does not bundle or pretend to know the API contract for a model called “Luna.” Use the provider’s OpenAI-compatible base URL and actual model names:

```bash
BASELINE_BASE_URL=https://provider.example/v1 \
BASELINE_API_KEY=... \
BASELINE_MODEL=luna \
BASELINE_EMBEDDING_MODEL=provider-embedding-model \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run signalweave benchmark \
  --systems jev,embedding-reasoning \
  --repeats 5 \
  --format markdown \
  --output artifacts/jev-vs-luna.md
```

The baseline performs two calls per case: an embeddings request over the owner intent and the same dashboard observations, followed by a deterministic-temperature chat-completions request over the retrieved observations. Its response must contain JSON fields for `outcome`, `recipient_key`, `rationale`, `confidence`, and optional `probabilities`.

If the provider is not OpenAI-compatible, add a small adapter rather than silently changing the benchmark contract. A missing baseline endpoint is an explicit configuration error; it is never reported as a model result.

## How to interpret the result

The most useful first comparison is not “which model sounds smarter.” It is:

- exact decision accuracy, because a correct outcome sent to the wrong team is still a failure;
- false automatic actions, especially false `notify`/`escalate`;
- `investigate` rate, because safe uncertainty is better than confident noise;
- repeat stability;
- end-to-end latency and provider request count; and
- token usage and cost at the company’s actual dashboard cardinality.

Jev is expected to have a structural advantage when the job is a small, typed judgment over a bounded state: its outputs already conform to the choices the code can consume, and independent questions can be composed in code. That is a design hypothesis, not a result. The result must come from running this harness over labeled production history.

## Enterprise evaluation set

For a credible claim, export historical evaluations with:

1. dashboard and monitor-card version;
2. all evidence shown to the evaluator;
3. owner-expected outcome and recipient;
4. whether the alert was useful, noisy, late, or unsafe;
5. the eventual operational outcome; and
6. the provider latency and usage metadata.

Split by time or dashboard owner so the test set is not just a replay of the examples used to tune the prompts. Calibrate confidence thresholds by consequence, and keep `investigate` as a first-class outcome.

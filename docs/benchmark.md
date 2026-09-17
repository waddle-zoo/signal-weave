# Benchmark protocol

SignalWeave should earn its Jev dependency with measurements, not a marketing claim. This repository therefore includes a small benchmark that compares the production Jev path with an optional conventional embedding-plus-reasoning pipeline.

## What is held constant

Each evaluator receives the same:

- workflow and owner intent;
- selected source references;
- normalized current, baseline, change, dimension, and freshness values;
- source metadata and evidence statements;
- allowed outcomes; and
- approved recipient allowlist.

The engine applies the same post-judgment gates to both evaluators. The embedding-plus-reasoning adapter only changes how evidence is retrieved and how the semantic decision is produced; it does not get a different source set or an easier routing contract.

The checked-in cases are deliberately external data in [`evaluations/data/demo-cases.json`](../evaluations/data/demo-cases.json). They cover:

| Case | Labeled decision | Semantic difficulty |
| --- | --- | --- |
| Revenue decline | Notify Revenue Operations | A decline is meaningful because a related customer-quality signal moved with it. |
| Seasonal normal | Ignore | Several metrics decline, but a context signal explains the movement. |
| Mobile conversion | Notify Growth | A cross-chart and dimension relationship identifies the affected surface. |
| Data freshness | Escalate Data Platform | Freshness is a prerequisite to interpretation. |

These are wiring and behavior cases, not a statistically representative enterprise dataset.

## Recorded Jev baseline

The recorded local run (2026-09-17, five repeats, 20 total evaluations, before the generic source-contract refactor) produced:

| Evaluator | Exact decision accuracy | Median | p95 | API requests | Provider errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jev | 100% (20/20) | 701.62 ms | 914.17 ms | 40 | 0 |

Jev selected the labeled outcome and approved recipient for all four cases on every repeat in the recorded baseline run. This result is useful evidence that owner-defined workflows and the typed decision contract can work together; it is not evidence that Jev is universally more accurate than a general model. No Luna/general-model result is recorded because this environment has no such provider endpoint or credential configured.

## Run Jev

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark \
  --systems jev \
  --repeats 5 \
  --format markdown \
  --output artifacts/jev-benchmark.md
```

Jev uses one typed planning request and one typed judgment request per evaluation. The judgment contains independent `Noul` support values for the owner-defined automatic actions; SignalWeave composes them in code and applies the workflow threshold. The report records request count, reported input/output tokens, latency, outcome accuracy, exact outcome-plus-recipient accuracy, and errors. Repeating the cases exposes instability rather than hiding it behind one best-looking run.

## Run a real general-model baseline

The repository does not bundle or pretend to know the API contract for a model called “Luna.” Use the provider’s OpenAI-compatible base URL and actual model names:

```bash
BASELINE_BASE_URL=https://provider.example/v1 \
BASELINE_API_KEY=... \
BASELINE_MODEL=luna \
BASELINE_EMBEDDING_MODEL=provider-embedding-model \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark \
  --systems jev,embedding-reasoning \
  --repeats 5 \
  --format markdown \
  --output artifacts/jev-vs-luna.md
```

The baseline performs two calls per case: an embeddings request over the owner intent and the same normalized source observations, followed by a deterministic-temperature chat-completions request over the retrieved observations. Its response must contain JSON fields for `outcome`, `recipient_key`, `rationale`, `confidence`, and optional `probabilities`.

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

1. workflow version and source references;
2. all evidence shown to the evaluator;
3. owner-expected outcome and recipient;
4. whether the alert was useful, noisy, late, or unsafe;
5. the eventual operational outcome; and
6. the provider latency and usage metadata.

Split by time, source mix, or workflow owner so the test set is not just a replay of the examples used to tune the prompts. Calibrate confidence thresholds by consequence, and keep `investigate` as a first-class outcome.

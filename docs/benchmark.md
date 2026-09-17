# Benchmark protocol

SignalWeave should earn its Jev dependency with measurements, not a marketing claim. This repository therefore includes a small benchmark that compares the production Jev path with an optional conventional embedding-plus-reasoning pipeline. The concise measured case is in [`evidence-brief.md`](evidence-brief.md).

## What is held constant

Each evaluator receives the same:

- insight card and author guidance;
- selected source references;
- normalized current, baseline, change, dimension, and freshness values;
- source metadata and evidence statements;
- configured delivery methods; and
- source and card metadata.

The engine applies the same post-judgment gates to both evaluators. The
embedding-plus-reasoning adapter changes how evidence is retrieved and how the
semantic result is produced: its model receives only embedding-selected
observations, while Jev receives the complete normalized observation set.

The checked-in cases are deliberately external data in [`evaluations/data/demo-cases.json`](../evaluations/data/demo-cases.json). They cover:

| Case | Labeled decision | Semantic difficulty |
| --- | --- | --- |
| Revenue decline | Notify Revenue Operations | A decline is meaningful because a related customer-quality signal moved with it. |
| Seasonal normal | Ignore | Several metrics decline, but a context signal explains the movement. |
| Mobile conversion | Notify Growth | A cross-chart and dimension relationship identifies the affected surface. |
| Data freshness | Escalate Data Platform | Freshness is a prerequisite to interpretation. |

These are wiring and behavior cases, not a statistically representative enterprise dataset.

## Current evidence snapshot

The following runs used the four checked-in synthetic cases and five repeats per
run. The Jev row is a recorded local run from before the generic source-contract
refactor. OpenAI runs A and B were made against the real OpenAI API on
2026-09-17 with the local development configuration; they are included to show
the comparison path, not to imply a production benchmark.

| Evaluator | Exact decision accuracy | Wrong automatic actions | Median | p95 | API requests | Provider errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Jev, recorded baseline | 100% (20/20) | 0 | 701.62 ms | 914.17 ms | 40 | 0 |
| OpenAI baseline, run A | 75% (15/20) | 5 | 2,981.51 ms | 5,964.23 ms | 40 | 0 |
| OpenAI baseline, run B | 80% (16/20) | 4 | 2,855.41 ms | 4,202.77 ms | 40 | 0 |

The OpenAI misses were false `notify` decisions for the seasonal case: the
baseline routed a decline to Retail Operations even though the related context
said to ignore it. This is a small but concrete example of why retrieval and
free-form reasoning should be compared on the final decision, not only on the
quality of an explanation. The two OpenAI runs also show repeat variation on the
same fixture. These results are not evidence that Jev is universally more
accurate or faster; the next step is a time-split evaluation on real card
history.

## Run Jev

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark \
  --systems jev \
  --repeats 5 \
  --format markdown \
  --output artifacts/jev-benchmark.md
```

Jev uses one typed planning request and one typed judgment request per evaluation.
The judgment contains independent `Noul` support values for each `watch_for`
item, each question, and each configured outcome; SignalWeave composes them in
code and applies the card threshold. The report records request count, reported
input/output tokens, latency, outcome accuracy, exact outcome-plus-delivery-method
accuracy, and errors. Repeating the cases exposes instability rather than hiding
it behind one best-looking run.

## Run a real OpenAI baseline

The `openai` arm uses the same normalized card and safety gates, but replaces
Jev’s typed judgments with embedding retrieval plus a general model JSON result.
It defaults to OpenAI’s API root; set the model names explicitly
for a reproducible run:

```bash
OPENAI_API_KEY=... \
OPENAI_MODEL=gpt-5.6-luna \
OPENAI_EMBEDDING_MODEL=text-embedding-3-small \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark \
  --systems jev,openai --repeats 5 --format markdown \
  --output artifacts/jev-vs-openai.md
```

The benchmark never writes either credential to the report.

## Run another general-model baseline

The repository also supports any provider with an OpenAI-compatible embeddings
and chat-completions API. Use the provider’s base URL and actual model names:

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

The baseline performs two calls per case: an embeddings request over the card
purpose and normalized source observations, followed by a result request over
the retrieved observations. The generic chat-completions path uses deterministic
temperature; the `openai` path uses a strict Responses JSON schema with
`outcome`, `rationale`, `confidence`, `watch_results`, `question_results`, and
`probabilities`. Delivery methods are selected from the stored card in code.

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

1. card version and source references;
2. all evidence shown to the evaluator;
3. owner-expected outcome and delivery methods;
4. whether the alert was useful, noisy, late, or unsafe;
5. the eventual operational outcome; and
6. the provider latency and usage metadata.

Split by time, source mix, or card owner so the test set is not just a replay of
the examples used to tune the prompts. Calibrate confidence thresholds by
consequence, and keep `investigate` as a first-class outcome.

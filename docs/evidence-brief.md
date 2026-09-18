# SignalWeave evidence brief

SignalWeave is for one narrow problem: turning an owner’s definition of a
meaningful change into a bounded result over the operational sources a company
already has.

It does not replace Superset, a knowledge graph, Temporal, Airflow, a scheduler,
or an agent. Those systems already fetch data and perform work. SignalWeave sits
at the decision seam: it combines the selected evidence, asks Jev small typed
questions about meaning and context, and lets application code enforce freshness,
allowlists, confidence, and side effects.

## The measured case

On 2026-09-18 we ran the same four labeled situations five times each:

- revenue decline corroborated by enterprise churn;
- a seasonal sales decline that should be ignored;
- mobile conversion decline corroborated by mobile checkout errors; and
- stale warehouse data that should escalate to Data Platform.

Both evaluators received the same insight cards, observations, and source
evidence. Both used the same engine safety gates. The OpenAI arm used embeddings
plus a general model with a strict JSON result contract. The Jev and OpenAI rows
below are the current five-repeat run.

| Evaluator | Evaluations | Exact decisions | Wrong automatic actions | Median | p95 | Requests | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Jev | 20 | 15/20 (75%) | 0 | 770.77 ms | 990.48 ms | 40 | 0 |
| OpenAI embedding + reasoning | 20 | 14/20 (70%) | 4 | 2,300.14 ms | 2,681.64 ms | 40 | 0 |

The Jev run reported 155,689 input tokens and 7,895 output tokens; the OpenAI
run reported 21,535 input tokens and 3,804 output tokens across 20 evaluations.
Those token counts are provider-reported and not directly comparable across
APIs. Measure provider cost separately with the model and pricing a deployment
actually uses; this repository does not invent a cost comparison.

The Jev misses were conservative `investigate` results for the seasonal case.
The OpenAI baseline produced four false `notify` decisions for that same case.
The result is useful because it tests the real failure mode—whether related
signals change the action—instead of grading how persuasive a paragraph sounds.

This is evidence for a product hypothesis, not a claim of universal model
accuracy. Four synthetic cases cannot establish enterprise performance. The
point is to make the hypothesis cheap to test against a company’s own labeled
history.

## Why this is worth testing

RAG and embeddings can help find a dashboard, metric definition, owner, or related
document. They do not by themselves define a stable decision boundary when:

- several charts jointly determine whether a movement is material;
- a context signal explains a change that should not page anyone;
- freshness or missing baselines make interpretation unsafe; or
- the correct action includes approved delivery methods, not just an explanation.

Hard-coded SQL jobs can solve each known case, but they make every new owner
definition a software project. One unconstrained LLM prompt is flexible, but it
mixes retrieval, arithmetic, interpretation, policy, and side effects in a large
surface that is difficult to test.

SignalWeave keeps the useful middle: owners write the condition in a free-form
insight card; adapters normalize existing assets; Jev supplies narrow semantic
judgments; and code owns the parts that must be deterministic. The output is a
result another system can consume, not a new agent that takes over the company.

## The five-minute test

```bash
git clone https://github.com/waddle-zoo/signal-weave.git
cd signal-weave
uv sync --extra dev
make verify
```

To reproduce the semantic path, provide a TypeSafe key and run the labeled proof:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli prove
```

To compare against the OpenAI baseline using the same fixture:

```bash
OPENAI_API_KEY=... \
OPENAI_MODEL=gpt-4o-mini \
OPENAI_EMBEDDING_MODEL=text-embedding-3-small \
  uv run python -m evaluations.cli benchmark \
  --systems openai --repeats 5 --format markdown
```

For a real source, start the localhost Superset stack and follow the
[onboarding walkthrough](demo.md). The owner starts with a goal, confirms the
Jev-ranked source candidates, previews the insight card, and explicitly approves
it. An existing scheduler, agent, or webhook relay can then call the approved
card. There is no required SignalWeave UI or delivery worker.

## What would count as proof

The next test is not a larger synthetic generator. A design partner should export
roughly 100 historical alert or monitoring situations from one team, including
the card version, source evidence, expected outcome, expected delivery methods,
usefulness, and eventual operational result. Compare Jev with the team’s current
LLM or rules using exact decision accuracy, false automatic actions, investigation
rate, latency, and provider usage. Keep a time-split holdout so the cases used to
write the cards are not also used to grade them.

The current repository is an alpha proof, not an enterprise control plane. Identity-
aware authorization, durable audit history, card version conflicts, and
production delivery guarantees remain deployment or follow-up work. See
[`benchmark.md`](benchmark.md) for the full protocol and limitations.

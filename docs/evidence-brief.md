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

On 2026-09-17 we ran the same four labeled situations five times each:

- revenue decline corroborated by enterprise churn;
- a seasonal sales decline that should be ignored;
- mobile conversion decline corroborated by mobile checkout errors; and
- stale warehouse data that should escalate to Data Platform.

Both evaluators received the same insight cards, observations, and source
evidence. Both used the same engine safety gates. The OpenAI arm used embeddings
plus a general model with a strict JSON result contract. The Jev row is a
recorded five-repeat run from before this generic card-contract refactor; rerun
it before treating it as a release number.

| Evaluator | Evaluations | Exact decisions | Wrong automatic actions | Median | p95 | Requests | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Jev, recorded baseline | 20 | 20/20 (100%) | 0 | 701.62 ms | 914.17 ms | 40 | 0 |
| OpenAI baseline, run A | 20 | 15/20 (75%) | 5 | 2,981.51 ms | 5,964.23 ms | 40 | 0 |
| OpenAI baseline, run B | 20 | 16/20 (80%) | 4 | 2,855.41 ms | 4,202.77 ms | 40 | 0 |

OpenAI run B reported 16,185 input tokens and 2,784 output tokens across the
20 evaluations. Measure provider cost separately with the model and pricing a
deployment actually uses; this repository does not invent a cost comparison.

Every incorrect OpenAI result in these runs was a false `notify` for the
seasonal case: a normal contextual decline was routed to Retail Operations. The result is useful
because it tests the real failure mode—whether related signals change the action—
instead of grading how persuasive a paragraph sounds. The two runs also show
that a general model can vary on the same input even with a deterministic request
setting.

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
OPENAI_MODEL=gpt-5.6-luna \
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

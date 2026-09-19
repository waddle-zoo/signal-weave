# SignalWeave demo walkthrough

This is the shortest path from a plain-language operating concern to a live,
evidence-backed result. A client-owned UI or agent helps a person describe an
insight card, SignalWeave compiles it with Jev, and an existing scheduler or
relay pushes evaluation when it is time.

The repository is an alpha proof; the local stack is not a production deployment.
The measured comparison is in [`evidence-brief.md`](evidence-brief.md).

## A. Run local checks and Jev proof

```bash
uv sync --extra dev
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python -m evaluations.cli prove
```

The labeled cases live outside `src/` and exercise the same generic
`InsightCard`/`ResourceSnapshot` contract used by the service. The labels are
test oracles, not a general accuracy claim.

## B. Connect an existing client to Superset

Start the isolated, localhost-only stack:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe docker compose up --build
curl http://localhost:18000/healthz
```

The local Superset credentials are `admin` / `admin`. The compose file binds
published ports to loopback; do not expose this stack or reuse its credentials.

Connect an MCP client to `http://localhost:18000/mcp`. A person can start with a
goal and have Jev rank the bounded source catalog:

```text
discover_insight_sources(
  goal="Watch the Growth dashboard for anything that could put Q3 revenue at risk."
)
```

The client shows the ranked candidates and asks the person to confirm the source
or chart scope. It then creates a generic card:

```text
propose_insight_card(
  what_to_watch="Checkout conversion and related mobile signals.",
  why_watch="Help Growth decide whether a conversion movement needs action.",
  watch_for=[
    "Checkout conversion is materially down.",
    "Mobile errors corroborate the movement.",
    "Traffic does not explain the movement."
  ],
  questions=[
    "Is mobile the likely source of the regression?",
    "Does this warrant a Growth response?"
  ],
  selected_sources=[{
    "ref":"superset|dashboard:7",
    "parameters":{"chart_ids":["62","64"]}
  }],
  delivery_methods=[{
    "key":"growth-ops",
    "outcome":"notify",
    "label":"Growth Ops",
    "destination":"slack://growth-ops",
    "instructions":"Notify when the evidence supports a Growth-owned response."
  }]
)
```

The response contains the stored card, Jev's finite capability plan, and setup
questions. Before approval, review the onboarding boundary:

```text
review_insight_card(card_id="<card_id returned by the proposal>")
```

The review shows each candidate's relevance, catalog metadata, selection reason,
omitted recommendations, and ambiguous candidate groups. A client-owned UI or
agent should use it to ask the owner whether a source is actually required. Do
not add a source merely because it is related; mark optional context with
`required=false` or leave it out. Then preview and approve it explicitly:

```text
simulate_insight_card(card_id="<card_id returned by the proposal>")
resolve_insight_sources(card_id="<card_id returned by the proposal>")
approve_insight_card(card_id="<card_id returned by the proposal>")
evaluate_insight_card(card_id="<card_id returned by the proposal>")
```

The result includes the chosen outcome, configured delivery methods,
`watch_results`, `question_results`, every normalized observation, source evidence,
the Jev evaluator, and the retrieval bundle. The proposal flow keeps the
human-confirmed dashboard as an anchor, then Jev can add bounded optional
context from the authorized catalog. A card with many metrics still receives the complete
normalized observation set; changed rows are only ordered first for presentation.
Use `retrieval_mode="fixed"` when the client wants exactly the sources it supplied.

For a direct draft, call `review_insight_card` after `draft_insight_card` as the
same confirmation step. Repeated titles or source names are expected in large
catalogs; the review intentionally asks for a human choice instead of silently
selecting the first match.

If a caller already knows its refs, use `draft_insight_card` directly:

```text
draft_insight_card(
  title="Sales pulse",
  what_to_watch="Revenue and related dashboard signals.",
  why_watch="Help Revenue Operations distinguish expected movement from a business issue.",
  watch_for=["Revenue changes materially.", "A related chart corroborates the movement."],
  questions=["Is this outside expected seasonal behavior?"],
  sources=[{
    "key":"sales-dashboard",
    "adapter":"superset",
    "resource":"dashboard:7",
    "label":"Sales dashboard",
    "parameters":{"chart_ids":["62","64"]}
  }],
  delivery_methods=[{
    "key":"revenue-operations",
    "outcome":"notify",
    "label":"Revenue Operations",
    "destination":"slack://revenue-operations"
  }]
)
```

## C. Push proof

After approval, an existing scheduler or alert relay can trigger a fresh read:

```bash
curl -X POST http://localhost:18000/webhooks/evaluate \
  -H 'content-type: application/json' \
  -H 'authorization: Bearer local-dev-token' \
  -H 'Idempotency-Key: daily:<date>:<card-id>' \
  -d '{"card_id":"<approved-card-id>","idempotency_key":"daily:<date>:<card-id>"}'
```

The caller decides when to run and how to deliver the configured routes.
SignalWeave records the idempotency receipt and replays a completed result for
the same key, but it does not become a scheduler or delivery worker.

## D. Live unlabeled acceptance check

For the included card against the local Superset:

```bash
SUPERSET_URL=http://127.0.0.1:8088 \
SUPERSET_USERNAME=admin SUPERSET_PASSWORD=admin \
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python scripts/live_card_check.py \
  --card examples/insight-card.json
```

No expected outcome is supplied. The command verifies that the card is read, the
source adapter returns live evidence, Jev is the evaluator, and safety gates
produce a typed result.

## E. Repeatable benchmark

```bash
TYPESAFE_API_KEY_FILE=/path/to/apikey_typesafe \
  uv run python -m evaluations.cli benchmark \
  --systems jev --repeats 5 --format markdown \
  --output artifacts/jev-benchmark.md
```

For the embedding-plus-reasoning comparison, see [`benchmark.md`](benchmark.md).

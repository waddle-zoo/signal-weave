# Retrieval-backed explanation

SignalWeave's next layer is intentionally small: after an approved card's
initial evidence is fetched, Jev may select one bounded set of additional,
authorized, read-only sources that could explain, corroborate, contradict, or
qualify the movement. SignalWeave fetches those sources and runs the final card
judgment over the combined evidence.

```text
approved card + initial snapshot + versioned context
                    │
                    ▼
          Jev: is more evidence needed?
                    │
                    ▼
      Jev: score bounded authorized candidates
                    │
                    ▼
       code: inspect selected sources only
                    │
                    ▼
     Jev: final typed outcome + evidence roles
```

This is not a general agent loop. There is one optional follow-up stage, a
card-owned maximum source count, an authorized candidate set, and no model-owned
tool calls, SQL, destinations, or mutations.

## Context boundary

Companies can provide graph, catalog, lineage, precedent, or feedback context as
a `ContextSnapshot`:

- `provider` identifies the external system;
- `version` makes the view used for a decision reproducible;
- `facts` contain statements, relationships, and opaque source references; and
- `provenance` points back to the owning system or human source.

SignalWeave records this snapshot in the result and converts its facts into
evidence. Context supplied through MCP is marked `unverified`; if non-empty
unverified context would support an automatic `notify` or `escalate`, the result
is downgraded to `investigate`. A server-side `ContextProvider` can supply trusted
context from a deployment-owned system. It does not persistently rewrite a card
or graph from a result. An existing agent can pass a validated snapshot through
the MCP evaluation and simulation tools.

## Retrieval boundary

Before Jev sees a large catalog, the candidate pool unions several recall
signals:

- lexical and alias overlap;
- title matches;
- shared domain with approved anchors;
- adapter-published relationships and lineage; and
- context-referenced resources.

Tenant and authorization filtering happens first. Jev ranks only this bounded
pool. The result records the retrieval strategy, candidate signals, selected
sources, omitted references, and context version. A candidate returned by Jev is
still checked against the authorized pool before inspection.

## Typed explanation

When bounded investigation is enabled, observations can receive one of these
roles:

- `driver` — a strongest candidate explanation associated with the movement or
  condition; this is not a causal claim;
- `corroborates` — independently supports its significance;
- `contradicts` — argues that it is expected or not actionable;
- `quality` — qualifies freshness, completeness, trust, or comparability;
- `unrelated`; or
- `unknown` when the role probability is below the configured item threshold.

When the role is uncertain, the result also preserves the model's
`suggested_role` and probability without promoting it to a typed finding. These
are typed references to returned observations, not generated causal prose.
Clients can render the exact metric, values, source URL, and provenance beside the
role. Low-confidence source selection or evidence roles remain visible as
uncertainty instead of being promoted to facts.

## Adversarial trial

The evaluation-only fixture in
[`evaluations/data/retrieval-explanation-scenarios.json`](../evaluations/data/retrieval-explanation-scenarios.json)
covers five deliberately different cases:

- SaaS checkout conversion explained by payment failures;
- retail sales movement explained by seasonality;
- logistics degradation with direct and corroborating operational signals;
- fintech settlement data that must escalate when stale; and
- marketplace movement with no trusted diagnostic source, which must investigate.

Each case includes unrelated assets, same-name cross-tenant decoys, hidden
expected labels, and versioned context facts. The labels are used only after the
run. Execute the live Jev trial with:

```bash
TYPESAFE_API_KEY_FILE=/absolute/path/to/apikey_typesafe \
  uv run python evaluations/retrieval_explanation_trial.py \
  --output artifacts/retrieval-explanation-trial.json
```

The first live run completed all five cases with 5/5 exact outcomes, 5/5 exact
delivery routes, zero unauthorized selected sources, and 0.70 mean recall over
the optional diagnostic-source labels. That is useful engineering evidence, not
enterprise proof. The imperfect recall is intentionally retained: it shows that
the next improvement should be catalog/context retrieval quality, not another
outcome prompt.

## Next proof gate

Run this same contract in shadow mode against one real team's historical or live
Superset cards. Label which related sources were actually useful, whether the
returned driver/contradiction roles were accepted, and whether the final outcome
was useful, noisy, late, or unsafe. Measure source recall, top-driver acceptance,
false automatic actions, investigation rate, latency, and provider cost on a
time-split holdout.

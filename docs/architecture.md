# SignalWeave architecture

## Product boundary

SignalWeave is a small decision layer between company-owned source systems and
the system that already delivers or acts on an insight. It does not own BI,
search, a knowledge graph, scheduling, durable execution, identity, or delivery.

Superset is the first-class shipped adapter, but the core contract is a generic
card over approved source references. A card can combine several dashboards and,
when installed, SQL, Airflow, table-quality, or other bounded read adapters.

```text
 InsightCard
 what_to_watch + why + look_for + questions + delivery_methods
                         │
                         ▼
          Authoring + SourceRegistry
        resolve anchors + Jev-ranked context
                         │
                         ▼
              ResourceSnapshot[]
        observations + evidence + metadata
                         │
                         ▼
       InsightEngine / compiler
                 finite capability plan
                         │
                         ▼
       Jev typed judgments for plan + card items
                         │
                         ▼
                code-owned safety gates
                         │
                         ▼
              InsightResult → MCP / webhook
```

## The card contract

`InsightCard` is intentionally small and free-form. The author supplies the
meaning; the platform supplies source resolution, bounded analysis, typed
judgments, and safe outcome routing.

```json
{
  "id": "card-sales-pulse",
  "title": "Sales pulse",
  "what_to_watch": "Revenue and related dashboard signals that show whether sales are on course.",
  "why_watch": "Help Revenue Operations distinguish expected movement from a business issue.",
  "watch_for": [
    "Revenue changes materially versus the selected comparison window.",
    "A related chart corroborates the movement."
  ],
  "questions": [
    "Is the movement outside expected seasonal behavior?",
    "Does this warrant a Revenue Operations response?"
  ],
  "sources": [
    {
      "key": "sales-dashboard",
      "adapter": "superset",
      "resource": "dashboard:7",
      "label": "Sales dashboard",
      "parameters": {"chart_ids": ["62", "64"]}
    }
  ],
  "delivery_methods": [
    {
      "key": "revenue-operations",
      "outcome": "notify",
      "label": "Revenue Operations",
      "destination": "slack://revenue-operations",
      "instructions": "Notify when the evidence supports a non-urgent operating response."
    }
  ]
}
```

The five authoring fields are the important part:

- `what_to_watch` describes the subject and scope in ordinary language;
- `why_watch` describes the decision the result should support;
- `watch_for` lists optional conditions that should be surfaced individually;
- `questions` lists optional questions the available evidence should answer; and
- `delivery_methods` maps outcomes to caller-owned destinations and instructions.

Sources, comparison windows, freshness, confidence, version, and approval status
are platform controls. A compiled `InsightPlan` stores the Jev-selected finite
capabilities and the card items it will evaluate. Its card version is checked
before reuse, so an edited card cannot silently run an old plan.

There is no `dashboard_id` or `chart_ids` in the engine contract. Superset scope
is adapter-owned `SourceRef.parameters`, so the same card can contain:

```text
superset dashboard:7, charts [62, 64]
superset dashboard:12, charts [91]
sql query:orders_quality
airflow dag:warehouse_load
table table:warehouse.orders
```

The engine never parses those locators or executes their source language.

Metric query cards use a separate typed path for data-lake questions:

```text
plain-language question
          │
          ▼
approved ResourceContract.metric_definitions
          │
          ▼
Jev selects one definition and requested dimensions
          │
          ▼
code builds MetricQueryPlan
          │
          ▼
deterministic compiler emits bounded SELECT SQL
          │
          ▼
TrinoQueryAdapter executes only that compiled query
```

The metric path does not ask Jev to generate SQL. Relations, aggregations,
columns, dimensions, time grains, and partition columns come from an approved
catalog; the compiler validates them and requires an explicit time window.

## Source adapters

An adapter has two operations:

```python
async def list_resources() -> list[ResourceDescriptor]
async def inspect(source: SourceRef) -> ResourceSnapshot
```

`ResourceDescriptor` is safe catalog metadata for onboarding. A
`ResourceSnapshot` contains bounded observations, non-numeric evidence, metadata,
source URL, capture time, optional comparison baselines, and an explicit error.

The registry resolves sources independently. A required failure becomes typed
insufficient data; an optional failure remains visible without automatically
blocking every other source. This is what lets a card combine a Superset
dashboard with a quality query or job-status signal without provider-specific
logic in the engine.

## Evidence-bundle retrieval

`retrieval_mode` is the small control for using related context:

- `fixed` evaluates only the card's human-approved `sources`; and
- `expand` keeps those sources as anchors, asks Jev to rank a bounded authorized
  catalog, and adds at most the configured number of related sources as optional
  context.

Expansion happens at the MCP evaluation boundary. It never mutates the stored
card or replaces an anchor. `resolve_insight_sources` exposes the selected and
omitted candidates before approval or evaluation, and the `InsightResult` carries
the `EvidenceBundle` used for that run. This makes retrieval inspectable and lets
a client show why a related dashboard or query was included.

The catalog is filtered by the registry's authorization boundary before Jev sees
it. The bounded candidate pool unions lexical, title, domain, adapter-published
relationship, lineage, and versioned-context references; Jev remains the semantic
ranker. Related sources are optional, so a missing context source is preserved as
evidence without vetoing a complete required anchor. The card owner still
controls the anchor and approval decision.

The Superset adapter preserves the value that makes this useful as a first wedge:
dashboard and chart titles, descriptions, owners, relationships, saved chart
definitions, filters, dimensions, bounded series, current/baseline movement,
source URLs, and per-chart errors. Other adapters do not need to impersonate a
dashboard.

## Evaluation pipeline

For every evaluation the engine:

1. resolves the approved card sources;
2. loads one immutable context snapshot from the configured provider or caller;
3. applies the selected comparison window in code when a source supplies it;
4. optionally asks Jev whether one bounded follow-up inspection is warranted;
5. validates selected references against the authorized candidate pool and fetches
   only those read-only sources;
6. creates evidence statements for every normalized observation and preserves all
   source evidence;
7. sends the complete normalized observation set, context, and card to the configured
   Jev judger;
8. receives an outcome, per-item watch/question results, and typed evidence roles; and
9. applies hard gates before returning the result.

Changed or incomplete observations are ordered first for client rendering, but
they are not a retrieval limit. Jev sees all observations in the evaluation state,
which is essential when the answer depends on a quiet related chart, a cross-source
contradiction, or a non-numeric condition such as freshness or existence.

## Jev composition

SignalWeave uses Jev as a programmable semantic primitive, not an autonomous
agent runner:

- independent `Noul` judgments select relevant finite capabilities during plan
  compilation;
- one bounded `Choice` selects a comparison window from the card's configured
  options;
- one `Noul` evaluates every `watch_for` item;
- one `Noul` evaluates whether every `question` is supported by the evidence; and
- one bounded `Choice` selects the mutually exclusive outcome from the card's
  configured delivery vocabulary;
- one `Noul` decides whether a bounded follow-up is useful; and
- independent `Score` judgments rank follow-up candidates for explanatory value.

The service composes those judgments in code. It never asks Jev to generate SQL,
invent a destination, call a delivery system, or return an unconstrained action
plan. A follow-up candidate is still checked against the authorized catalog in
code. Confidence is a routing signal: below the card threshold, automatic
outcomes become `investigate`; low-confidence evidence roles become `unknown`.

## Safety gates

After Jev, code enforces:

- required source errors or empty required snapshots → `insufficient_data`;
- source snapshots older than the card freshness limit → `insufficient_data`;
- stale observations from required sources → `escalate` only when the card has an escalation delivery
  method, otherwise `investigate`;
- numeric observations from required sources with no comparable baseline → `insufficient_data`;
- an outcome without a matching configured delivery method → `investigate`; and
- low-confidence `ignore`, `notify`, or `escalate` → `investigate`.

Delivery methods are always selected from the stored card after judgment. Model
output cannot change a destination, and the caller still owns actual delivery,
retries, idempotency, and side effects.

## Lifecycle and MCP surface

An existing UI or agent can use the small surface below:

```text
list_resources(adapter?)
inspect_resource(adapter, resource, parameters?)
discover_insight_sources(goal, adapter?, limit?)
propose_insight_card(what_to_watch, why_watch, watch_for?, questions?, ...)
draft_insight_card(title, what_to_watch, why_watch, sources, ...)
simulate_insight_card(card_id)
approve_insight_card(card_id)
list_insight_cards(status?)
get_insight_card(card_id)
evaluate_insight_card(card_id)
resolve_insight_sources(card_id)
```

`simulate_insight_card`, `evaluate_insight_card`, and
`resolve_insight_sources` accept an optional versioned `ContextSnapshot`. A
deployment can also inject a `ContextProvider` into `InsightEngine`. The result
contains the context version, investigation trace, selected and omitted
references, and typed evidence findings. The stored card and external graph are
not mutated by evaluation.

The proposal flow uses Jev to rank a bounded source catalog, stores a draft, and
returns setup questions. The direct draft flow is for a caller that already knows
its source references. Both flows compile and store a plan. Simulation is
delivery-disabled preview; approval is an explicit state transition; evaluation
fetches fresh snapshots. The webhook accepts `{ "card_id": "..." }` for a
caller-owned scheduler or push relay. Push evaluation requires an idempotency key
and stores a decision receipt with card version, actor, outcome, selected delivery
methods, and delivery state. Repeated keys replay the receipt instead of fetching
sources again. The default runtime stores cards, metric cards, and receipts in a
single SQLite file with a uniqueness constraint on the idempotency key; JSON is
available only as a small local/legacy backend and is not a multi-process claim
protocol. Delivery remains disabled unless a deployment adds a reviewed delivery
sink; the receipt is the handoff boundary. A multi-replica deployment should
replace the store interface with a shared transactional database before routing
traffic to more than one process.

## Context and feedback boundary

An external knowledge-context adapter can add definitions, ownership,
relationships, precedents, conflicts, and human feedback as versioned,
provenance-bearing input to the same card evaluation state. That can improve the
Jev decision without turning SignalWeave into a graph store or agent runtime. Raw
feedback must not silently rewrite a card or graph; proposed changes need review
and a new version.

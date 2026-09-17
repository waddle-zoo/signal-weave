# SignalWeave architecture

## Product boundary

SignalWeave evaluates a user-authored decision workflow over approved company
sources. It does not own the company’s BI, knowledge graph, scheduler, durable
execution, identity, or delivery system.

Superset is the first-class source adapter and the first product wedge. The core
boundary is deliberately one level above Superset: a workflow can combine several
Superset resources and, when installed, other bounded source adapters.

```text
        MonitorWorkflow
        intent + policy + SourceRef[]
                     │
                     ▼
             SourceRegistry
       resolve each ref independently
                     │
                     ▼
          ResourceSnapshot[]
    observations + evidence + metadata
                     │
                     ▼
          MonitorEngine / compiler
          finite executable plan
                     │
              ┌──────┴──────┐
              │             │
       Jev plan judgments  Jev action conditions
       Noul + Choice       independent Nouls + Choice
              │             │
              └──────┬──────┘
                     ▼
             code-owned gates
                     │
                     ▼
          Decision → MCP / webhook
```

## Contracts

### `MonitorWorkflow`

The workflow is the durable, reviewable user contract:

- plain-language `intent`;
- named `sources`;
- comparison windows and investigation hints;
- owner-defined materiality language;
- allowed outcomes;
- explicit recipient allowlist; and
- action-confidence threshold.

When a card is proposed or drafted, its Jev-compiled `MonitorPlan` is stored with
the workflow. Later approved evaluations reuse that plan instead of silently
recompiling a different interpretation of the owner’s card.

There is no `dashboard_id` or `chart_ids` in this contract. Superset chart scope
is expressed as adapter-owned `SourceRef.parameters`, so a workflow can contain:

```text
superset dashboard:7, charts [62, 64]
superset dashboard:12, charts [91]
sql query:orders_quality
airflow dag:warehouse_load
table table:warehouse.orders
```

The generic engine never parses those locators or executes their source language.

### `SourceAdapter` and `SourceRegistry`

An adapter has two operations:

```python
async def list_resources() -> list[ResourceDescriptor]
async def inspect(source: SourceRef) -> ResourceSnapshot
```

`ResourceDescriptor` is safe discovery metadata. `ResourceSnapshot` is a bounded
runtime result with:

- `observations` for normalized values that code can compare;
- `evidence` for source facts that may be non-numeric or relationship-oriented;
- adapter metadata for context Jev may need;
- source URL and capture time;
- adapter-provided comparison baselines for supported windows; and
- an explicit `error` when the source could not be trusted.

The registry resolves sources independently. One failed required source blocks
automatic action and becomes evidence; optional-source failures remain visible but
do not automatically block the workflow. This matters for workflows that combine
a dashboard with a best-effort context query or a job-status source.

### Superset adapter

The Superset adapter translates `dashboard:<id>` and `chart:<id>` refs into the
generic snapshot contract. It still preserves Superset-specific value:

- dashboard owners and descriptions;
- chart IDs, titles, metric definitions, and relationships;
- saved query context where available;
- filters, grouping, granularity, and bounded row/series limits;
- time-series current/baseline/change calculations;
- dimensions and source URLs; and
- per-chart failures.

The Superset models are isolated in `superset_models.py`; the workflow engine does
not depend on them. That is the important compromise: Superset is not flattened
into a lowest-common-denominator dashboard abstraction, but other sources do not
need to impersonate one.

SQL, Airflow, and table checks are extension points in this repository. The
heterogeneous tests and trial harness exercise the generic composition contract;
they do not claim those live adapters are already shipped.

## Decision design

The engine performs deterministic preparation:

1. resolve workflow sources;
2. flatten selected observations and preserve source evidence;
3. identify candidate observations by numeric materiality/freshness for context;
4. build a JSON-safe state containing the workflow, plan, snapshots, observations, and evidence;
5. ask Jev for typed semantic judgments; and
6. apply hard safety gates before returning the decision.

The candidate filter is only an evidence prioritization aid. Jev still sees the
full normalized observations and source metadata so niche policies can reason
about non-candidate context, cross-source disagreement, and non-numeric evidence.

### Jev composition

The TypeSafe integration follows the [System One building model](https://docs.typesafe.ai/concepts/how-to-build-with-system-one):

- independent `Noul` checks select relevant analysis capabilities;
- a bounded `Choice` selects an owner-approved comparison window;
- independent `Noul` checks evaluate each allowed automatic-action condition; and
- a bounded `Choice` selects only from approved recipient keys.

The action conditions are intentionally independent. They are not treated as a
normalized distribution over mutually exclusive outcomes. Code chooses the
highest-supported allowed action only when its configured threshold is met, and
otherwise routes to investigation. This matches TypeSafe’s guidance on composing
judgments and treating confidence as a routing signal rather than truth.

Jev never generates SQL, chooses an unapproved recipient, calls a delivery system,
or controls retries. It supplies semantic interpretation; the application remains
the control plane.

## Safety gates

After Jev, code enforces:

- required source errors → `insufficient_data` or `investigate`;
- empty required snapshots or snapshots older than the workflow freshness limit → `insufficient_data` or `investigate`;
- stale observations → escalation only if explicitly allowed and routable;
- no comparable baseline → no automatic no-op;
- unknown recipient → recipient removed and investigation required;
- non-action outcome → no recipient retained; and
- low-confidence automatic action → investigation.

These gates are provider-neutral. A table-existence adapter, DAG-status adapter,
or SQL query adapter gets the same failure behavior as Superset.

## Lifecycle

### Discover and draft

An existing agent can start with a natural-language goal and call
`discover_monitor_inputs`. SignalWeave bounds the installed catalog, asks Jev to
rank the candidates, and returns opaque refs plus enough metadata for a person to
confirm the source selection. `propose_monitor_card` then turns that selection into
a stored draft with Jev’s finite plan and explicit clarification questions. No
notification or side effect occurs.

Callers that already know their complete source refs can use `draft_workflow`
directly.

### Preview and review

`simulate_monitor_card` evaluates a draft against fresh snapshots without treating
the result as an approved push action. The workflow and plan can then be reviewed
in a UI, pull request, or catalog. Reviewers can see the source refs, owner
definition, allowed outcomes, recipients, and finite operation vocabulary.

`approve_monitor_card` is an explicit state transition. Push evaluation rejects
draft workflows until they are approved.

### Evaluate

An MCP client or existing scheduler calls `evaluate_workflow`, or a push relay
posts `{ "workflow_id": "..." }` to the webhook. Evaluation fetches fresh source
snapshots and uses the same engine in both paths.

### Deliver

The caller owns Slack/email/PagerDuty/ticket delivery, retries, idempotency, and
side effects. SignalWeave only returns the typed decision and evidence.

## Operating boundary

The local JSON workflow catalog makes the repo easy to run. An enterprise adapter
should replace it with reviewed storage and identity-aware access. It should also
record every source snapshot, Jev judgment, returned decision, delivery attempt,
and owner correction for calibration.

The architecture intentionally stops before becoming Temporal, Airflow, LangGraph,
or a search product. Its job is the narrow missing layer: turning heterogeneous,
sparse operational context into a bounded, evidence-backed decision.

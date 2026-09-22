# Enterprise gap analysis

SignalWeave should stay small. It is not a catalog, semantic layer, workflow
engine, BI product, or agent builder. Its useful boundary is narrower:

> Given a human-authored goal over a set of analytical artifacts, retrieve an
> authorized and sufficiently fresh evidence set from existing enterprise
> systems, use Jev to make bounded typed decisions over that evidence, and
> return an inspectable receipt that another system or agent can act on.

The product promise is operational: people should not have to open a series of
dashboards, notebooks, and query results every morning to decide whether
anything important changed. A card names the outcome, the artifacts or search
scope, what to look for, and what should happen for each outcome. SignalWeave
connects those artifacts, evaluates the current evidence, and pushes a bounded
result to the system that already handles delivery or action.

This boundary matters because the adjacent products are already good at the
parts they own:

| Adjacent system | What it already does well | What it does not provide to SignalWeave's caller |
| --- | --- | --- |
| BI and notebook systems (Superset, Looker, Hex, and others) | Each system owns its dashboards, charts, queries, notebooks, runs, and native access model. | A cross-artifact, goal-specific evidence bundle and a typed decision about what matters now. |
| Data catalogs / metadata graphs | Search, ownership, glossary, lineage, quality, and entity relationships. OpenMetadata exposes these both through APIs and MCP tools. | A bounded investigation plan tied to a particular user goal and current observations. |
| Glean-like enterprise search | Permission-aware indexing and relevance over enterprise content, people, and activity. | A deterministic application contract for selecting evidence, abstaining, and routing an operational outcome. |
| dbt Semantic Layer / Cube | Governed metric definitions, joins, dimensions, access policies, and refresh semantics. | The choice of which governed assets matter for an open-ended monitoring or investigation goal. |
| Temporal / Airflow | Durable execution and scheduling. | The semantic retrieval and decision that should happen inside a workflow. |
| Jev | Fast typed judgments, probabilities, and confidence over supplied state. | It cannot retrieve omitted candidates, enforce source permissions, or execute a workflow. |

The research supports two conclusions:

1. “RAG is dead” is too broad. Vector or graph retrieval remains useful, but
   enterprise retrieval has to account for permissions, freshness, lineage,
   multiple data shapes, and global or multi-hop questions. Microsoft’s GraphRAG
   documentation explicitly separates local entity retrieval from global,
   corpus-level search; the enterprise-RAG literature calls out security,
   accuracy, scalability, and integration as distinct problems.
2. Jev is valuable after candidate generation, not as a replacement for it.
   TypeSafe describes Jev as a typed probabilistic decision primitive; its own
   guidance says the model cannot choose an omitted candidate. Therefore the
   hard product problem is the contract between an enterprise catalog/graph and
   Jev: completeness, authorization, freshness, and bounded context.

## Highest-confidence gaps

### 1. Candidate coverage at enterprise scale — P0

The current implementation loads an entire adapter catalog into memory and then
keeps a bounded pool before Jev. That works for a local Superset demo but fails
as the default contract for a catalog with tens of thousands of dashboards,
charts, tables, jobs, and documents. It can silently omit the only relevant
asset.

The smallest useful fix is an adapter-owned search boundary:

- adapters may implement server-side, permission-aware search;
- the registry returns `total_count`, `has_more`, a cursor, and warnings;
- the engine records whether Jev saw a complete catalog or a bounded result;
- legacy adapters retain a clearly marked local fallback rather than pretending
  to solve scale.

Proof target: a 100,000-resource fake adapter must make one bounded search call,
return the relevant resource, and never materialize the full catalog in the
registry or Jev request.

### 2. Connector authorization is explicit — P0

SignalWeave must not assume that every enterprise uses Superset RBAC or that
every source has the same permission model. The current service can be deployed
safely behind a trusted gateway, and each adapter can enforce its own credential
or principal boundary, but shared deployments still need request-scoped identity
and card/receipt isolation.

The service now accepts a trusted request principal from the deployment boundary
through `principal_resolver` and propagates it through catalog search, source
inspection, approval, bounded investigation, and evaluation. It still does not
invent an identity provider or universal ACL: a shared deployment must verify
the principal at its gateway, and adapters must return only resources visible to
that principal. The remaining proof target is an actual OIDC/shared-gateway
staging replay rather than the local resolver double.

Proof target: two tenants with colliding resource names cannot discover, inspect,
or reuse each other’s cards or receipts, including through bounded investigation.

### 3. Context must be a retrieval contract, not caller-supplied decoration — P1

The current context provider is intentionally small, but an MCP caller can still
pass an unverified snapshot. That is useful for experiments and unsafe as a trust
boundary. A production graph connector should answer a versioned query with
authorization, freshness, completeness, and provenance status; SignalWeave should
consume that result and abstain when required graph context is unavailable.

SignalWeave should define the interface and receipt, not own a new knowledge
graph. This is the differentiator: making graph facts operationally usable by a
decision layer without turning the project into another catalog.

### 4. Evidence and cost budgets — P1

Jev is fast and inexpensive, but speed does not remove the need for bounded state.
Large cards, catalogs, context graphs, and source payloads can still create slow
or expensive requests and obscure what the decision used. The engine needs
explicit limits for candidate count, evidence count, serialized bytes, source
fetch time, and optional follow-up depth, with visible truncation and abstention.

### 5. Outcome quality needs counterfactual evaluation — P1

Current trials prove routing, selection, provenance, and safety behavior on
synthetic enterprise portfolios. They do not yet prove that an explanation is the
right explanation, that an alert reached the right owner, or that a human would
have taken the recommended action. Those labels must come from real operators or
replayable historical incidents; they cannot be manufactured by the same Jev
workflow being evaluated.

## What not to build

- A replacement for Superset, a data catalog, Glean, dbt, Cube, Temporal, or
  Airflow.
- A universal graph schema or hosted knowledge graph.
- A free-form agent runtime that can execute arbitrary tools.
- A claim that Jev makes a result true because it returned a high probability.

## Sequence

1. Ship the bounded catalog-search contract and 100k-artifact stress proof.
2. Add request-scoped principal/tenant propagation and cross-source tests.
3. Replace unverified context input with a connector contract carrying
   authorization, freshness, and completeness.
4. Add explicit payload/time budgets and benchmark abstention under truncation.
5. Run replay evaluation with operator labels before making automatic delivery a
   production recommendation.

## Sources

- [TypeSafe: Introducing System One Models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- [Jev model reference](https://systemonemodels.org/models/jev/)
- [Superset dashboard API](https://superset.apache.org/developer-docs/api/get-a-list-of-dashboards/)
- [Superset MCP deployment, pagination, and RBAC](https://superset.apache.org/admin-docs/configuration/mcp-server/)
- [Looker API getting started](https://cloud.google.com/looker/docs/api-getting-started)
- [Looker run query API](https://cloud.google.com/looker/docs/reference/looker-api/latest/methods/Query/run_query)
- [Hex public API overview](https://learn.hex.tech/docs/api-integrations/api/overview)
- [Hex public API reference](https://learn.hex.tech/docs/api-integrations/api/reference)
- [Glean knowledge graph and permissions](https://docs.glean.com/security/knowledge-graph)
- [OpenMetadata AI SDK and MCP tools](https://docs.open-metadata.org/v1.12.x/api-reference/sdk/ai-sdk)
- [dbt Developer Hub and Semantic Layer](https://docs.getdbt.com/)
- [Cube data modeling and access policies](https://docs.cube.dev/reference/data-modeling/cube)
- [Microsoft GraphRAG global search](https://github.com/microsoft/graphrag/blob/main/docs/query/global_search.md)
- [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130)
- [RAG Does Not Work for Enterprises](https://arxiv.org/abs/2406.04369)
